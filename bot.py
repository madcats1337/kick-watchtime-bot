import os
import json
import random
import string
import asyncio
import requests
import websockets
import aiohttp
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

import discord
from discord.ext import commands, tasks

from kick_client import KickChatClient
import asyncio

kick_client = KickChatClient("madcats")

async def start_kick_listener():
    await kick_client.connect()

bot.loop.create_task(start_kick_listener())

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

# Role thresholds in minutes (change or make configurable via env as needed)
WATCHTIME_ROLES = [
    {"name": "🎯 Fan", "minutes": 60},
    {"name": "🔥 Superfan", "minutes": 300},
    {"name": "💎 Elite Viewer", "minutes": 1000},
]

# Kick API / websocket
KICK_API_CHANNEL = "https://kick.com/api/v2/channels"
KICK_CHAT_WS = "wss://chat.service.kick.com/socket.io/?EIO=4&transport=websocket"

# -------------------------
# Database (SQLAlchemy engine)
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
        kick_name TEXT
    );
    """))
    conn.execute(text("""
    CREATE TABLE IF NOT EXISTS pending_links (
        discord_id BIGINT,
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

# In-memory active viewer last-seen map (username -> datetime aware UTC)
active_viewers = {}

# -------------------------
# Kick listener
# -------------------------
async def fetch_chatroom_id(channel_name: str):
    """Fetch chatroom id via Kick channel API."""
    try:
        r = requests.get(f"{KICK_API_CHANNEL}/{channel_name}", timeout=8)
        if r.status_code != 200:
            print(f"[Kick] Channel API returned {r.status_code} for {channel_name}")
            return None
        data = r.json()
        # chatroom id location may vary; these fields are common in Kick responses
        # try several keys used historically
        chatroom = data.get("chatroom") or data.get("livestream", {}).get("chatroom")
        if chatroom and isinstance(chatroom, dict):
            return chatroom.get("id")
        return data.get("chatroom", {}).get("id")
    except Exception as e:
        print(f"[Kick] fetch_chatroom_id error: {e}")
        return None

async def kick_chat_loop(channel_name: str):
    """Run loop that connects to Kick WS, joins room, and updates active_viewers."""
    while True:
        try:
            chatroom_id = await asyncio.get_event_loop().run_in_executor(None, fetch_chatroom_id, channel_name)
            if not chatroom_id:
                print(f"[Kick] Could not obtain chatroom id for {channel_name}. Retrying in 30s.")
                await asyncio.sleep(30)
                continue

            print(f"[Kick] Connecting to chatroom {chatroom_id} for channel {channel_name} ...")
            async with websockets.connect(KICK_CHAT_WS, max_size=None) as ws:
                # Socket.IO connect handshake
                # send '40' to establish Engine.IO connection (Socket.IO protocol)
                await ws.send("40")
                await asyncio.sleep(0.5)
                # join the chatroom
                join_payload = f'42["joinRoom",{{"chatroom_id":{chatroom_id}}}]'
                await ws.send(join_payload)
                print(f"[Kick] Joined chatroom {chatroom_id}")

                # listen loop
                while True:
                    msg = await ws.recv()
                    if not msg:
                        continue

                    # heartbeat ping from socket.io (starts with '2'), respond with '3'
                    if isinstance(msg, str) and msg.startswith("2"):
                        try:
                            await ws.send("3")
                        except Exception:
                            pass
                        continue

                    # The protocol often wraps events with leading digits; find first '['
                    try:
                        idx = msg.find('[')
                        if idx == -1:
                            continue
                        payload = json.loads(msg[idx:])
                        # payload is usually like ["message", { ... }]
                        if isinstance(payload, list) and len(payload) >= 2:
                            event = payload[0]
                            content = payload[1]
                            if event == "message":
                                sender = content.get("sender", {}).get("username")
                                if sender:
                                    active_viewers[sender.lower()] = datetime.now(timezone.utc)
                                    # optional: print message content for debugging
                                    text = content.get("content") or content.get("text") or ""
                                    print(f"[Kick] {sender}: {text}")
                    except Exception:
                        # ignore parse errors
                        pass

        except websockets.InvalidURI as e:
            print(f"[Kick] Invalid WS URI: {e}. Aborting.")
            await asyncio.sleep(30)
        except Exception as e:
            print(f"[Kick] Connection error: {e}. Reconnecting in 10s.")
            await asyncio.sleep(10)
            continue

# -------------------------
# Watchtime updater
# -------------------------
@tasks.loop(seconds=WATCH_INTERVAL_SECONDS)
async def update_watchtime_task():
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=5)
    with engine.begin() as conn:
        for user, last_seen in list(active_viewers.items()):
            # keep only users seen in the last 5 minutes as active
            if last_seen and last_seen >= cutoff:
                # upsert: works on sqlite (ON CONFLICT) and Postgres
                conn.execute(text("""
                    INSERT INTO watchtime (username, minutes, last_active)
                    VALUES (:u, 1, :t)
                    ON CONFLICT(username) DO UPDATE SET
                        minutes = watchtime.minutes + 1,
                        last_active = :t
                """), {"u": user, "t": last_seen.isoformat()})

# -------------------------
# Role updater
# -------------------------
@tasks.loop(seconds=ROLE_UPDATE_INTERVAL_SECONDS)
async def update_roles_task():
    if DISCORD_GUILD_ID is None:
        print("[Discord] DISCORD_GUILD_ID not set; skipping role updates.")
        return

    guild = bot.get_guild(DISCORD_GUILD_ID)
    if not guild:
        print("[Discord] Guild not found; ensure the bot is in the server and DISCORD_GUILD_ID is correct.")
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

        for role_info in WATCHTIME_ROLES:
            role = discord.utils.get(guild.roles, name=role_info["name"])
            if role and minutes >= role_info["minutes"] and role not in member.roles:
                try:
                    await member.add_roles(role, reason="Reached watchtime threshold")
                    print(f"[Discord] Assigned role {role.name} to {member.display_name} ({kick_name} - {minutes}m)")
                except discord.Forbidden:
                    print(f"[Discord] Missing permission to assign {role.name}. Ensure bot role is above target roles.")
                except Exception as e:
                    print(f"[Discord] Error assigning role: {e}")

# -------------------------
# Pending links cleanup (and DM expired users)
# -------------------------
@tasks.loop(minutes=5)
async def cleanup_pending_links_task():
    expiry_cutoff = datetime.now(timezone.utc) - timedelta(minutes=CODE_EXPIRY_MINUTES)
    expired = []
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT discord_id FROM pending_links WHERE timestamp < :t"), {"t": expiry_cutoff.isoformat()}).fetchall()
        expired = [r[0] for r in rows]
        conn.execute(text("DELETE FROM pending_links WHERE timestamp < :t"), {"t": expiry_cutoff.isoformat()})

    for discord_id in expired:
        try:
            user = await bot.fetch_user(int(discord_id))
            if user:
                try:
                    await user.send("⏰ Your Kick verification code expired. Use `!link <kick_username>` to start again.")
                except discord.Forbidden:
                    pass
        except Exception:
            pass

# -------------------------
# Commands: link, verify, unlink, leaderboard
# -------------------------
@bot.command(name="link")
async def cmd_link(ctx, kick_username: str):
    discord_id = ctx.author.id
    code = ''.join(random.choices(string.digits, k=6))
    now_iso = datetime.now(timezone.utc).isoformat()

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM pending_links WHERE discord_id = :d"), {"d": discord_id})
        conn.execute(text("""
            INSERT INTO pending_links (discord_id, kick_name, code, timestamp)
            VALUES (:d, :k, :c, :t)
        """), {"d": discord_id, "k": kick_username.lower(), "c": code, "t": now_iso})

    await ctx.send(
        f"🔗 To verify ownership of **{kick_username}**, please add this code to your Kick bio:\n\n"
        f"**{code}**\n\n"
        f"Then run `!verify {kick_username}` once it's added. The code expires in {CODE_EXPIRY_MINUTES} minutes."
    )

@bot.command(name="verify")
async def cmd_verify(ctx, kick_username: str):
    discord_id = ctx.author.id
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT code, timestamp FROM pending_links
            WHERE discord_id = :d AND kick_name = :k
        """), {"d": discord_id, "k": kick_username.lower()}).fetchone()

    if not row:
        await ctx.send("❌ No pending verification found. Use `!link <kick_username>` first.")
        return

    code, ts = row
    ts_dt = datetime.fromisoformat(ts)
    if datetime.now(timezone.utc) - ts_dt > timedelta(minutes=CODE_EXPIRY_MINUTES):
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM pending_links WHERE discord_id = :d"), {"d": discord_id})
        await ctx.send("⏰ Your verification code expired. Run `!link <kick_username>` again.")
        return

    # check Kick bio via Kick's channel API
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.get(f"{KICK_API_CHANNEL}/{kick_username}") as resp:
                if resp.status != 200:
                    await ctx.send("❌ Couldn't find Kick user. Check spelling.")
                    return
                data = await resp.json()
    except Exception as e:
        await ctx.send("❌ Error contacting Kick API. Try again later.")
        return

    bio = data.get("bio") or ""
    if bio and code in bio:
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO links (discord_id, kick_name)
                VALUES (:d, :k)
                ON CONFLICT(discord_id) DO UPDATE SET kick_name = excluded.kick_name
            """), {"d": discord_id, "k": kick_username.lower()})
            conn.execute(text("DELETE FROM pending_links WHERE discord_id = :d"), {"d": discord_id})

        await ctx.send(f"✅ Verified and linked Discord -> Kick ` {kick_username} `")
    else:
        await ctx.send("❌ Could not find the verification code in your Kick bio. Make sure it's visible and try again.")

@bot.command(name="unlink")
async def cmd_unlink(ctx):
    discord_id = ctx.author.id
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM links WHERE discord_id = :d"), {"d": discord_id})
    await ctx.send("🔓 Unlinked your Kick account from this Discord account.")

@bot.command(name="leaderboard")
async def cmd_leaderboard(ctx, top: int = 10):
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT username, minutes FROM watchtime ORDER BY minutes DESC LIMIT :n"), {"n": top}).fetchall()
    if not rows:
        await ctx.send("No watchtime data yet.")
        return

    embed = discord.Embed(title="🏆 Kick Watchtime Leaderboard", color=0x00FF00)
    for i, (username, minutes) in enumerate(rows, start=1):
        embed.add_field(name=f"#{i} {username}", value=f"{minutes} minutes ({minutes/60:.2f} hrs)", inline=False)
    await ctx.send(embed=embed)

# -------------------------
# Startup and tasks
# -------------------------
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (id: {bot.user.id})")
    # start background tasks if not already running
    if not update_watchtime_task.is_running():
        update_watchtime_task.start()
    if not update_roles_task.is_running():
        update_roles_task.start()
    if not cleanup_pending_links_task.is_running():
        cleanup_pending_links_task.start()

    # start Kick listener in background
    bot.loop.create_task(kick_chat_loop(KICK_CHANNEL))

# -------------------------
# Run
# -------------------------
if not DISCORD_TOKEN:
    raise SystemExit("DISCORD_TOKEN environment variable is required")

bot.run(DISCORD_TOKEN)
