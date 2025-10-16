import os
import json
import random
import string
import asyncio
import aiohttp
import websockets
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

import discord
from discord.ext import commands, tasks

# -------------------------
# Load config
# -------------------------
load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DISCORD_GUILD_ID = int(os.getenv("DISCORD_GUILD_ID")) if os.getenv("DISCORD_GUILD_ID") else None
KICK_CHANNEL = os.getenv("KICK_CHANNEL")

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///watchtime.db")
WATCH_INTERVAL_SECONDS = int(os.getenv("WATCH_INTERVAL_SECONDS", "60"))
ROLE_UPDATE_INTERVAL_SECONDS = int(os.getenv("ROLE_UPDATE_INTERVAL_SECONDS", "600"))
CODE_EXPIRY_MINUTES = int(os.getenv("CODE_EXPIRY_MINUTES", "10"))

# Role thresholds in minutes
WATCHTIME_ROLES = [
    {"name": "🎯 Fan", "minutes": 60},
    {"name": "🔥 Superfan", "minutes": 300},
    {"name": "💎 Elite Viewer", "minutes": 1000},
]

# Kick API / websocket
KICK_API_CHANNEL = "https://kick.com/api/v2/channels"
KICK_CHAT_WS = "wss://ws-us3.pusher.com/app/dd11c46dae0376080879?protocol=7&client=js&version=8.4.0&flash=false"

# -------------------------
# Database setup
# -------------------------
engine = create_engine(DATABASE_URL, future=True)

with engine.begin() as conn:
    conn.execute(text("""
    CREATE TABLE IF NOT EXISTS watchtime (
        username TEXT PRIMARY KEY,
        minutes INTEGER DEFAULT 0,
        last_active TIMESTAMP
    );
    """))
    conn.execute(text("""
    CREATE TABLE IF NOT EXISTS links (
        discord_id BIGINT PRIMARY KEY,
        kick_name TEXT UNIQUE
    );
    """))
    conn.execute(text("""
    CREATE TABLE IF NOT EXISTS pending_links (
        discord_id BIGINT PRIMARY KEY,
        kick_name TEXT,
        code TEXT,
        timestamp TEXT
    );
    """))

# -------------------------
# Discord bot setup
# -------------------------
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# In-memory active viewer tracking
active_viewers = {}

# -------------------------
# Kick listener functions
# -------------------------
async def fetch_chatroom_id(channel_name: str):
    """Fetch chatroom id via Kick channel API."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{KICK_API_CHANNEL}/{channel_name}", timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    print(f"[Kick] Channel API returned {resp.status} for {channel_name}")
                    return None
                data = await resp.json()
                
                # Extract chatroom id from response
                if "chatroom" in data and isinstance(data["chatroom"], dict):
                    return data["chatroom"].get("id")
                return None
    except Exception as e:
        print(f"[Kick] fetch_chatroom_id error: {e}")
        return None

async def kick_chat_loop(channel_name: str):
    """Connect to Kick's Pusher WebSocket and listen for chat messages."""
    while True:
        try:
            chatroom_id = await fetch_chatroom_id(channel_name)
            if not chatroom_id:
                print(f"[Kick] Could not obtain chatroom id for {channel_name}. Retrying in 30s.")
                await asyncio.sleep(30)
                continue

            print(f"[Kick] Connecting to chatroom {chatroom_id} for channel {channel_name}...")
            
            # Connect to Pusher WebSocket
            async with websockets.connect(KICK_CHAT_WS, max_size=None) as ws:
                print("[Kick] WebSocket connected, subscribing to channel...")
                
                # Subscribe to the chatroom channel
                subscribe_msg = json.dumps({
                    "event": "pusher:subscribe",
                    "data": {
                        "auth": "",
                        "channel": f"chatrooms.{chatroom_id}.v2"
                    }
                })
                await ws.send(subscribe_msg)
                print(f"[Kick] Subscribed to chatrooms.{chatroom_id}.v2")

                # Listen for messages
                while True:
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=30)
                        
                        if not msg:
                            continue

                        # Parse Pusher message
                        try:
                            data = json.loads(msg)
                            event_type = data.get("event")
                            
                            # Respond to ping
                            if event_type == "pusher:ping":
                                await ws.send(json.dumps({"event": "pusher:pong"}))
                                continue
                            
                            # Handle chat message
                            if event_type == "App\\Events\\ChatMessageEvent":
                                event_data = json.loads(data.get("data", "{}"))
                                sender = event_data.get("sender", {})
                                username = sender.get("username")
                                
                                if username:
                                    active_viewers[username.lower()] = datetime.now(timezone.utc)
                                    content_text = event_data.get("content", "")
                                    print(f"[Kick] {username}: {content_text}")
                                    
                        except json.JSONDecodeError:
                            pass
                        except Exception as e:
                            print(f"[Kick] Error parsing message: {e}")
                            
                    except asyncio.TimeoutError:
                        # Send ping to keep connection alive
                        try:
                            await ws.send(json.dumps({"event": "pusher:ping"}))
                        except:
                            break

        except websockets.exceptions.WebSocketException as e:
            print(f"[Kick] WebSocket error: {e}. Reconnecting in 10s.")
            await asyncio.sleep(10)
        except Exception as e:
            print(f"[Kick] Connection error: {e}. Reconnecting in 10s.")
            await asyncio.sleep(10)

# -------------------------
# Watchtime updater task
# -------------------------
@tasks.loop(seconds=WATCH_INTERVAL_SECONDS)
async def update_watchtime_task():
    """Update watchtime for active viewers."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=5)
    
    with engine.begin() as conn:
        for user, last_seen in list(active_viewers.items()):
            if last_seen and last_seen >= cutoff:
                # Add 1 minute of watchtime per interval
                minutes_to_add = WATCH_INTERVAL_SECONDS / 60
                conn.execute(text("""
                    INSERT INTO watchtime (username, minutes, last_active)
                    VALUES (:u, :m, :t)
                    ON CONFLICT(username) DO UPDATE SET
                        minutes = watchtime.minutes + :m,
                        last_active = :t
                """), {"u": user, "m": minutes_to_add, "t": last_seen.isoformat()})

# -------------------------
# Role updater task
# -------------------------
@tasks.loop(seconds=ROLE_UPDATE_INTERVAL_SECONDS)
async def update_roles_task():
    """Assign Discord roles based on watchtime thresholds."""
    if DISCORD_GUILD_ID is None:
        return

    guild = bot.get_guild(DISCORD_GUILD_ID)
    if not guild:
        return

    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT l.discord_id, w.minutes, l.kick_name
            FROM links l
            JOIN watchtime w ON l.kick_name = w.username
        """)).fetchall()

    for discord_id, minutes, kick_name in rows:
        member = guild.get_member(int(discord_id))
        if not member:
            continue

        # Assign all eligible roles
        for role_info in WATCHTIME_ROLES:
            role = discord.utils.get(guild.roles, name=role_info["name"])
            if role and minutes >= role_info["minutes"] and role not in member.roles:
                try:
                    await member.add_roles(role, reason=f"Reached {role_info['minutes']} min watchtime")
                    print(f"[Discord] Assigned {role.name} to {member.display_name} ({kick_name})")
                except discord.Forbidden:
                    print(f"[Discord] Missing permission to assign {role.name}")
                except Exception as e:
                    print(f"[Discord] Error assigning role: {e}")

# -------------------------
# Cleanup expired verification codes
# -------------------------
@tasks.loop(minutes=5)
async def cleanup_pending_links_task():
    """Remove expired verification codes and notify users."""
    expiry_cutoff = datetime.now(timezone.utc) - timedelta(minutes=CODE_EXPIRY_MINUTES)
    
    with engine.begin() as conn:
        rows = conn.execute(text(
            "SELECT discord_id FROM pending_links WHERE timestamp < :t"
        ), {"t": expiry_cutoff.isoformat()}).fetchall()
        
        expired_ids = [r[0] for r in rows]
        
        conn.execute(text(
            "DELETE FROM pending_links WHERE timestamp < :t"
        ), {"t": expiry_cutoff.isoformat()})

    # Notify users their codes expired
    for discord_id in expired_ids:
        try:
            user = await bot.fetch_user(int(discord_id))
            if user:
                try:
                    await user.send(
                        "⏰ Your Kick verification code expired. "
                        "Use `!link <kick_username>` to generate a new one."
                    )
                except discord.Forbidden:
                    pass
        except Exception:
            pass

# -------------------------
# Commands
# -------------------------
@bot.command(name="link")
async def cmd_link(ctx, kick_username: str):
    """Generate a verification code to link Kick account to Discord."""
    discord_id = ctx.author.id
    kick_username = kick_username.lower()
    
    # Check if this Kick account is already linked to another Discord user
    with engine.connect() as conn:
        existing = conn.execute(text(
            "SELECT discord_id FROM links WHERE kick_name = :k"
        ), {"k": kick_username}).fetchone()
        
        if existing and existing[0] != discord_id:
            await ctx.send(
                f"❌ The Kick account **{kick_username}** is already linked to another Discord user. "
                "If this is your account, ask them to `!unlink` first."
            )
            return
    
    # Generate 6-digit verification code
    code = ''.join(random.choices(string.digits, k=6))
    now_iso = datetime.now(timezone.utc).isoformat()

    with engine.begin() as conn:
        # Remove any existing pending verification for this Discord user
        conn.execute(text("DELETE FROM pending_links WHERE discord_id = :d"), {"d": discord_id})
        
        # Insert new pending verification
        conn.execute(text("""
            INSERT INTO pending_links (discord_id, kick_name, code, timestamp)
            VALUES (:d, :k, :c, :t)
        """), {"d": discord_id, "k": kick_username, "c": code, "t": now_iso})

    await ctx.send(
        f"🔗 **Link your Kick account**\n\n"
        f"1. Go to https://kick.com/dashboard/settings/profile\n"
        f"2. Add this code to your bio: **{code}**\n"
        f"3. Run `!verify {kick_username}` here\n\n"
        f"⏰ Code expires in {CODE_EXPIRY_MINUTES} minutes."
    )

@bot.command(name="verify")
async def cmd_verify(ctx, kick_username: str):
    """Verify Kick account ownership by checking bio for code."""
    discord_id = ctx.author.id
    kick_username = kick_username.lower()
    
    # Check for pending verification
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT code, timestamp FROM pending_links
            WHERE discord_id = :d AND kick_name = :k
        """), {"d": discord_id, "k": kick_username}).fetchone()

    if not row:
        await ctx.send(
            "❌ No pending verification found. Use `!link <kick_username>` first."
        )
        return

    code, ts = row
    ts_dt = datetime.fromisoformat(ts)
    
    # Check if code expired
    if datetime.now(timezone.utc) - ts_dt > timedelta(minutes=CODE_EXPIRY_MINUTES):
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM pending_links WHERE discord_id = :d"), {"d": discord_id})
        await ctx.send(
            "⏰ Your verification code expired. Run `!link <kick_username>` again."
        )
        return

    # Fetch Kick user profile to check bio
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.get(
                f"{KICK_API_CHANNEL}/{kick_username}",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    await ctx.send(
                        "❌ Couldn't find that Kick user. Check the spelling and try again."
                    )
                    return
                data = await resp.json()
    except Exception as e:
        print(f"[Verify] API error: {e}")
        await ctx.send("❌ Error contacting Kick API. Try again later.")
        return

    # Check if code is in bio
    bio = data.get("bio") or ""
    if code in bio:
        with engine.begin() as conn:
            # Link accounts
            conn.execute(text("""
                INSERT INTO links (discord_id, kick_name)
                VALUES (:d, :k)
                ON CONFLICT(discord_id) DO UPDATE SET kick_name = excluded.kick_name
            """), {"d": discord_id, "k": kick_username})
            
            # Remove pending verification
            conn.execute(text("DELETE FROM pending_links WHERE discord_id = :d"), {"d": discord_id})

        await ctx.send(
            f"✅ **Verified!** Your Discord account is now linked to Kick user **{kick_username}**\n"
            f"You can now remove the code from your bio."
        )
    else:
        await ctx.send(
            f"❌ Could not find code `{code}` in your Kick bio.\n"
            "Make sure you added it exactly as shown and try again."
        )

@bot.command(name="unlink")
async def cmd_unlink(ctx):
    """Unlink Kick account from Discord."""
    discord_id = ctx.author.id
    
    with engine.begin() as conn:
        result = conn.execute(text(
            "DELETE FROM links WHERE discord_id = :d RETURNING kick_name"
        ) if "postgres" in DATABASE_URL else text(
            "DELETE FROM links WHERE discord_id = :d"
        ), {"d": discord_id})
        
        # For SQLite, check if row was deleted
        if "sqlite" in DATABASE_URL:
            was_linked = result.rowcount > 0
        else:
            was_linked = result.fetchone() is not None
    
    if was_linked:
        await ctx.send("🔓 Your Kick account has been unlinked from Discord.")
    else:
        await ctx.send("❌ You don't have a linked Kick account.")

@bot.command(name="leaderboard")
async def cmd_leaderboard(ctx, top: int = 10):
    """Show top viewers by watchtime."""
    if top > 25:
        top = 25
    
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT username, minutes FROM watchtime ORDER BY minutes DESC LIMIT :n"
        ), {"n": top}).fetchall()
    
    if not rows:
        await ctx.send("📊 No watchtime data yet. Start watching to appear on the leaderboard!")
        return

    embed = discord.Embed(
        title="🏆 Kick Watchtime Leaderboard",
        description=f"Top {len(rows)} viewers",
        color=0x53FC18
    )
    
    medals = ["🥇", "🥈", "🥉"]
    for i, (username, minutes) in enumerate(rows, start=1):
        medal = medals[i-1] if i <= 3 else f"#{i}"
        hours = minutes / 60
        embed.add_field(
            name=f"{medal} {username}",
            value=f"⏱️ {minutes:.0f} min ({hours:.1f} hrs)",
            inline=False
        )
    
    await ctx.send(embed=embed)

@bot.command(name="watchtime")
async def cmd_watchtime(ctx):
    """Check your current watchtime."""
    discord_id = ctx.author.id
    
    with engine.connect() as conn:
        # Get linked Kick username
        link = conn.execute(text(
            "SELECT kick_name FROM links WHERE discord_id = :d"
        ), {"d": discord_id}).fetchone()
        
        if not link:
            await ctx.send(
                "❌ You haven't linked your Kick account yet. Use `!link <kick_username>` to get started."
            )
            return
        
        kick_name = link[0]
        
        # Get watchtime
        watchtime = conn.execute(text(
            "SELECT minutes FROM watchtime WHERE username = :u"
        ), {"u": kick_name}).fetchone()
    
    if not watchtime or watchtime[0] == 0:
        await ctx.send(
            f"⏱️ No watchtime recorded yet for **{kick_name}**. Start watching to earn time!"
        )
        return
    
    minutes = watchtime[0]
    hours = minutes / 60
    
    # Check which roles they've earned
    earned_roles = []
    for role_info in WATCHTIME_ROLES:
        if minutes >= role_info["minutes"]:
            earned_roles.append(role_info["name"])
    
    embed = discord.Embed(
        title=f"⏱️ Watchtime for {kick_name}",
        color=0x53FC18
    )
    embed.add_field(name="Total Time", value=f"{minutes:.0f} minutes ({hours:.1f} hours)", inline=False)
    
    if earned_roles:
        embed.add_field(name="Earned Roles", value="\n".join(earned_roles), inline=False)
    
    await ctx.send(embed=embed)

# -------------------------
# Bot events
# -------------------------
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")
    print(f"📺 Monitoring Kick channel: {KICK_CHANNEL}")
    
    # Start background tasks
    if not update_watchtime_task.is_running():
        update_watchtime_task.start()
        print("✅ Watchtime updater started")
    
    if not update_roles_task.is_running():
        update_roles_task.start()
        print("✅ Role updater started")
    
    if not cleanup_pending_links_task.is_running():
        cleanup_pending_links_task.start()
        print("✅ Cleanup task started")

    # Start Kick chat listener
    bot.loop.create_task(kick_chat_loop(KICK_CHANNEL))
    print("✅ Kick chat listener started")

@bot.event
async def on_command_error(ctx, error):
    """Handle command errors gracefully."""
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Missing argument: `{error.param.name}`")
    elif isinstance(error, commands.CommandNotFound):
        pass  # Ignore unknown commands
    else:
        print(f"[Error] {error}")
        await ctx.send("❌ An error occurred. Please try again.")

# -------------------------
# Run bot
# -------------------------
if not DISCORD_TOKEN:
    raise SystemExit("❌ DISCORD_TOKEN environment variable is required")

if not KICK_CHANNEL:
    raise SystemExit("❌ KICK_CHANNEL environment variable is required")

bot.run(DISCORD_TOKEN)