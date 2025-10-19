import os
import json
import time
import random
import string
import asyncio
import aiohttp
import ssl
import requests
import websockets
from typing import Optional
from playwright.async_api import async_playwright
from kick_api import USER_AGENTS
from datetime import datetime, timedelta, timezone
from functools import partial

from dotenv import load_dotenv
from sqlalchemy import create_engine, text # type: ignore
from kick_api import fetch_chatroom_id, check_stream_live, KickAPI, USER_AGENTS  # Consolidated Kick API module

import discord
from discord.ext import commands, tasks

# -------------------------
# Command checks and utils
# -------------------------
def in_guild():
    """Check if command is used in the configured guild."""
    async def predicate(ctx):
        if not DISCORD_GUILD_ID:
            return True
        return ctx.guild and ctx.guild.id == DISCORD_GUILD_ID
    return commands.check(predicate)

def has_manage_roles():
    """Check if user has manage roles permission."""
    async def predicate(ctx):
        if not ctx.guild:
            return False
        return ctx.author.guild_permissions.manage_roles
    return commands.check(predicate)

# -------------------------
# Load config
# -------------------------
load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
if not DISCORD_TOKEN:
    raise ValueError("DISCORD_TOKEN not found in environment variables")

KICK_CHANNEL = os.getenv("KICK_CHANNEL")
if not KICK_CHANNEL:
    raise ValueError("KICK_CHANNEL not found in environment variables")

# Optional: Hardcoded chatroom ID to bypass Cloudflare issues
KICK_CHATROOM_ID = os.getenv("KICK_CHATROOM_ID")  # Set this on Railway to skip fetching

DISCORD_GUILD_ID = int(os.getenv("DISCORD_GUILD_ID")) if os.getenv("DISCORD_GUILD_ID") else None
if not DISCORD_GUILD_ID:
    print("⚠️ Warning: DISCORD_GUILD_ID not set. Some features may be limited.")

# Database configuration with cloud PostgreSQL support
DATABASE_URL = os.getenv("DATABASE_URL", "")

if not DATABASE_URL:
    print("⚠️ WARNING: DATABASE_URL not set! Using in-memory SQLite database.")
    print("⚠️ This is fine for testing but data will be lost on restart.")
    print("⚠️ For production, set DATABASE_URL environment variable.")
    DATABASE_URL = "sqlite:///watchtime.db"

# Convert postgres:// to postgresql:// for SQLAlchemy compatibility (Heroku uses postgres://)
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    print("📊 Converted database URL to use postgresql:// scheme")
    
print(f"📊 Using database: {DATABASE_URL.split('@')[1] if '@' in DATABASE_URL else 'SQLite (local)'}")

WATCH_INTERVAL_SECONDS = int(os.getenv("WATCH_INTERVAL_SECONDS", "60"))
ROLE_UPDATE_INTERVAL_SECONDS = int(os.getenv("ROLE_UPDATE_INTERVAL_SECONDS", "600"))
CODE_EXPIRY_MINUTES = int(os.getenv("CODE_EXPIRY_MINUTES", "10"))

# URLs and Pusher config
KICK_API_BASE = "https://kick.com"
KICK_API_CHANNEL = f"{KICK_API_BASE}/api/v2/channels"
KICK_API_USER = f"{KICK_API_BASE}/api/v2/users"  # Updated to v2 API

# Browser configuration for API requests
CHROME_VERSION = "118.0.0.0"
BROWSER_CONFIG = {
    "headers": {
        "User-Agent": f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{CHROME_VERSION} Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Sec-Ch-Ua": f'"Google Chrome";v="{CHROME_VERSION}", "Chromium";v="{CHROME_VERSION}", "Not=A?Brand";v="24"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
        "Connection": "keep-alive"
    }
}

PUSHER_CONFIG = {
    "key": "32cbd69e4b950bf97679",  # Updated Pusher key
    "cluster": "us2",
    "version": "8.4.0",             # Updated version
    "protocol": 7,
}
KICK_CHAT_WS = f"wss://ws-{PUSHER_CONFIG['cluster']}.pusher.com/app/{PUSHER_CONFIG['key']}"  # Standard Pusher WebSocket endpoint

# Role thresholds in minutes
WATCHTIME_ROLES = [
    {"name": "🎯 Fan", "minutes": 60},
    {"name": "🔥 Superfan", "minutes": 300},
    {"name": "💎 Elite Viewer", "minutes": 1000},
]

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "Host": "kick.com",
    "Pragma": "no-cache",
    "Referer": "https://kick.com/",
    "Origin": "https://kick.com",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
}

# -------------------------
# Utility functions
# -------------------------
_kick_api = None

async def get_kick_api():
    """Get or create a KickAPI instance."""
    global _kick_api
    if _kick_api is None:
        from kick_api import KickAPI
        _kick_api = KickAPI()
        await _kick_api.setup()
    return _kick_api

async def get_kick_bio(username: str) -> Optional[dict]:
    """Get a Kick user's bio using Playwright."""
    print(f"[Verify] Fetching bio for {username} using Playwright...")
    browser = None
    context = None
    page = None
    
    try:
        async with async_playwright() as p:
            try:
                # Try Firefox first (often bypasses Cloudflare better than Chromium)
                try:
                    browser = await p.firefox.launch(
                        headless=True,
                        firefox_user_prefs={
                            "dom.webdriver.enabled": False,
                            "useAutomationExtension": False,
                            "general.platform.override": "Win32",
                            "general.useragent.override": random.choice(USER_AGENTS)
                        }
                    )
                    print("[Verify] Using Firefox browser")
                except Exception as ff_error:
                    print(f"[Verify] Firefox not available ({ff_error}), falling back to Chromium")
                    # Fallback to Chromium with enhanced stealth
                    browser = await p.chromium.launch(
                        headless=True,
                        args=[
                            '--disable-blink-features=AutomationControlled',
                            '--disable-web-security',
                            '--disable-features=IsolateOrigins,site-per-process',
                            '--no-sandbox',
                            '--window-size=1920,1080',
                            '--disable-setuid-sandbox',
                            '--disable-dev-shm-usage',
                            '--disable-accelerated-2d-canvas',
                            '--no-first-run',
                            '--no-zygote',
                            '--disable-gpu',
                            '--hide-scrollbars',
                            '--mute-audio'
                        ]
                    )
                    print("[Verify] Using Chromium browser")
                
                # Enhanced browser context with more realistic settings
                context = await browser.new_context(
                    user_agent=random.choice(USER_AGENTS),
                    viewport={'width': 1920, 'height': 1080},
                    bypass_csp=True,
                    ignore_https_errors=True,
                    extra_http_headers={
                        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                        'Accept-Language': 'en-US,en;q=0.9',
                        'Accept-Encoding': 'gzip, deflate, br',
                        'Connection': 'keep-alive',
                        'Upgrade-Insecure-Requests': '1',
                        'Sec-Fetch-Dest': 'document',
                        'Sec-Fetch-Mode': 'navigate',
                        'Sec-Fetch-Site': 'none',
                        'Sec-Fetch-User': '?1',
                        'Cache-Control': 'no-cache',
                        'Pragma': 'no-cache'
                    },
                    java_script_enabled=True,
                    locale='en-US',
                    timezone_id='America/New_York',
                    color_scheme='light',
                    permissions=['geolocation']
                )
                
                # Configure page to evade detection
                page = await context.new_page()
                await page.set_viewport_size({"width": 1920, "height": 1080})
                
                # Add evasion scripts
                await page.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', { get: () => false });
                    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
                    Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
                """)
                
                print(f"[Verify] Navigating to profile about page...")
                
                # First try with shorter timeout
                try:
                    # Add random delay before navigation
                    await asyncio.sleep(random.uniform(1, 3))
                    
                    response = await page.goto(
                        f"https://kick.com/{username}/about",
                        wait_until="domcontentloaded",
                        timeout=15000
                    )
                except Exception as e:
                    print(f"[Verify] Initial load timeout, retrying with different strategy: {str(e)}")
                    
                    # Clear cookies and cache before retry
                    await context.clear_cookies()
                    await page.evaluate("() => { localStorage.clear(); sessionStorage.clear(); }")
                    
                    # Add random delay before retry
                    await asyncio.sleep(random.uniform(2, 4))
                    
                    # Try again with networkidle strategy
                    response = await page.goto(
                        f"https://kick.com/{username}/about",
                        wait_until="networkidle",
                        timeout=20000
                    )
                    
                    # Handle Cloudflare if needed
                    if response.status == 403:
                        print("[Verify] Detected Cloudflare protection, waiting for challenge...")
                        try:
                            # Wait for Cloudflare to resolve
                            await page.wait_for_load_state("networkidle", timeout=30000)
                            # Get new response after challenge
                            response = await page.goto(
                                f"https://kick.com/{username}/about",
                                wait_until="networkidle",
                                timeout=15000
                            )
                        except Exception as cf_e:
                            print(f"[Verify] Failed to bypass protection: {str(cf_e)}")
                            return None
                
                if not response:
                    print("[Verify] No response from page navigation")
                    return None
                
                if response.status == 404:
                    print("[Verify] Profile page not found")
                    return None
                
                if response.status != 200:
                    print(f"[Verify] Unexpected status code: {response.status}")
                    return None
                
                # Wait for specific elements
                try:
                    await page.wait_for_selector(
                        'script[type="application/json"], meta[property="og:title"], .profile-header',
                        timeout=5000
                    )
                except Exception as e:
                    print(f"[Verify] Warning - page elements not fully loaded: {str(e)}")
                
                # Extract user data with multiple fallback methods
                user_data = await page.evaluate("""() => {
                    // Method 1: Find data in JSON script tags
                    const scripts = document.querySelectorAll('script[type="application/json"]');
                    for (const script of scripts) {
                        try {
                            const data = JSON.parse(script.textContent);
                            if (data && data.user) return data.user;
                        } catch (e) {}
                    }
                    
                    // Method 2: Search inline scripts
                    const allScripts = document.querySelectorAll('script');
                    for (const script of allScripts) {
                        const text = script.textContent || '';
                        if (text.includes('"user":')) {
                            try {
                                const match = text.match(/user":\s*({[^}]+})/);
                                if (match) return JSON.parse(match[1]);
                            } catch (e) {}
                        }
                    }
                    
                    // Method 3: Check meta description
                    const bioMeta = document.querySelector('meta[name="description"]');
                    if (bioMeta) {
                        return { bio: bioMeta.content };
                    }
                    
                    // Method 4: Try various profile selectors
                    const bioSelectors = [
                        '.profile-card-description',
                        '.profile-bio',
                        '.channel-profile-bio',
                        '[data-bio]',
                        '.bio',
                        '.user-bio'
                    ];
                    
                    for (const selector of bioSelectors) {
                        const element = document.querySelector(selector);
                        if (element) {
                            return { bio: element.textContent.trim() };
                        }
                    }
                    
                    return null;
                }""")
                
                if user_data:
                    print("[Verify] Successfully found user data")
                return user_data
                
            except Exception as e:
                print(f"[Verify] Error during profile access: {str(e)}")
                # Attempt to capture error state
                try:
                    if page:
                        await page.screenshot(path=f"debug_{username}_error.png")
                        print(f"[Verify] Saved error screenshot to debug_{username}_error.png")
                except:
                    pass
                return None
                
            finally:
                if page:
                    await page.close()
                if context:
                    await context.close()
                if browser:
                    await browser.close()
                    
    except Exception as e:
        print(f"[Verify] Playwright initialization error: {str(e)}")
        return None

# -------------------------
# Database setup and utilities
# -------------------------

class DBConnection:
    """Context manager for safe database connections."""
    def __init__(self):
        self.conn = None

    async def __aenter__(self):
        retries = 3
        while retries > 0:
            try:
                self.conn = engine.connect()
                return self.conn
            except Exception as e:
                retries -= 1
                if retries == 0:
                    raise
                await asyncio.sleep(1)

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.conn:
            self.conn.close()

# -------------------------
# Database setup
# -------------------------
engine = create_engine(
    DATABASE_URL,
    future=True,
    pool_pre_ping=True,     # Detect disconnections
    pool_recycle=1800,      # Recycle connections after 30 minutes (Railway timeout)
    pool_size=3,            # Smaller pool for Railway's connection limits
    max_overflow=5,         # Allow up to 5 connections beyond pool_size
    pool_timeout=30,        # Wait up to 30 seconds for a connection
    echo=False,             # Don't log all SQL
    echo_pool=False,        # Disable pool logging to reduce noise
    pool_use_lifo=True,     # Last In First Out for better performance
    connect_args={
        "connect_timeout": 10,           # Connection timeout
        "keepalives": 1,                 # Enable TCP keepalives
        "keepalives_idle": 30,           # Start keepalives after 30s idle
        "keepalives_interval": 10,       # Send keepalive every 10s
        "keepalives_count": 5            # Drop connection after 5 failed keepalives
    } if DATABASE_URL.startswith('postgresql') else {}
)

try:
    with engine.begin() as conn:
        # Create watchtime table
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS watchtime (
            username TEXT PRIMARY KEY,
            minutes INTEGER DEFAULT 0,
            last_active TIMESTAMP
        );
        """))
        
        # Create links table
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS links (
            discord_id BIGINT PRIMARY KEY,
            kick_name TEXT UNIQUE
        );
        """))
        
        # Create pending_links table
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS pending_links (
            discord_id BIGINT PRIMARY KEY,
            kick_name TEXT,
            code TEXT,
            timestamp TEXT
        );
        """))
    print("✅ Database tables initialized successfully")
except Exception as e:
    print(f"⚠️ Database initialization error: {e}")
    raise
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

# Stream status tracking
stream_tracking_enabled = True  # Admin can toggle this
last_chat_activity = None  # Track last time we saw any chat activity

# -------------------------
# Kick listener functions
# -------------------------
# Browser-like headers for requests
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Connection": "keep-alive",
    "Host": "kick.com",
    "Origin": "https://kick.com"
}

async def kick_chat_loop(channel_name: str):
    """Connect to Kick's Pusher WebSocket and listen for chat messages."""
    while True:
        try:
            # Check if chatroom ID is hardcoded in environment (bypass for Cloudflare issues)
            if KICK_CHATROOM_ID:
                chatroom_id = KICK_CHATROOM_ID
                print(f"[Kick] Using hardcoded chatroom ID: {chatroom_id}")
            else:
                chatroom_id = await fetch_chatroom_id(channel_name)
                if not chatroom_id:
                    print(f"[Kick] Could not obtain chatroom id for {channel_name}. Retrying in 30s.")
                    await asyncio.sleep(30)
                    continue

            print(f"[Kick] Connecting to chatroom {chatroom_id} for channel {channel_name}...")
            
            # Build WebSocket URL matching successful connection pattern
            ws_url = (
                f"{KICK_CHAT_WS}"
                f"?protocol={PUSHER_CONFIG['protocol']}"
                f"&client=js"
                f"&version={PUSHER_CONFIG['version']}"
                f"&flash=false"
                f"&cluster={PUSHER_CONFIG['cluster']}"
            )
            print(f"[Kick] Connecting to WebSocket: {ws_url}")
            
            # Prepare SSL context
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            
            # Connect to Pusher WebSocket with headers
            async with websockets.connect(
                ws_url,
                max_size=None,
                ssl=ssl_context,
                additional_headers={
                    "User-Agent": BROWSER_HEADERS["User-Agent"],
                    "Origin": "https://kick.com",
                    "Sec-WebSocket-Extensions": "permessage-deflate; client_max_window_bits",
                }
            ) as ws:
                print("[Kick] WebSocket connected, waiting for server response...")
                
                # Wait for connection established
                response = await ws.recv()
                print(f"[Kick] Initial response: {response}")
                response_data = json.loads(response)
                
                # Handle connection errors
                if response_data.get("event") == "pusher:error":
                    error_data = response_data.get("data", {})
                    error_code = error_data.get("code")
                    error_message = error_data.get("message")
                    raise Exception(f"WebSocket error code {error_code}: {error_message}")
                
                # Handle successful connection
                if response_data.get("event") == "pusher:connection_established":
                    socket_details = json.loads(response_data["data"])
                    socket_id = socket_details["socket_id"]
                    print(f"[Kick] Got socket_id: {socket_id}")
                    
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
                                global last_chat_activity
                                last_chat_activity = datetime.now(timezone.utc)  # Update stream activity
                                
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
    """Update watchtime for active viewers (only when tracking is enabled)."""
    global stream_tracking_enabled
    
    try:
        # Check if tracking is enabled by admin
        if not stream_tracking_enabled:
            return
        
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(minutes=5)
        
        # Get active viewers who were seen recently
        active_users = {
            user: last_seen 
            for user, last_seen in list(active_viewers.items())
            if last_seen and last_seen >= cutoff
        }
        
        if not active_users:
            return  # No active users to update
            
        # Calculate minutes to add
        minutes_to_add = WATCH_INTERVAL_SECONDS / 60
        
        # Update all active users in a single transaction
        with engine.begin() as conn:
            for user, last_seen in active_users.items():
                try:
                    conn.execute(text("""
                        INSERT INTO watchtime (username, minutes, last_active)
                        VALUES (:u, :m, :t)
                        ON CONFLICT(username) DO UPDATE SET
                            minutes = watchtime.minutes + :m,
                            last_active = :t
                    """), {
                        "u": user,
                        "m": minutes_to_add,
                        "t": last_seen.isoformat()
                    })
                except Exception as e:
                    print(f"⚠️ Error updating watchtime for {user}: {e}")
                    continue  # Skip this user but continue with others
                    
    except Exception as e:
        print(f"⚠️ Error in watchtime update task: {e}")
        await asyncio.sleep(5)  # Wait before retrying

# -------------------------
# Role updater task
# -------------------------
@tasks.loop(seconds=ROLE_UPDATE_INTERVAL_SECONDS)
async def update_roles_task():
    """Update Discord roles based on watchtime."""
    try:
        if not DISCORD_GUILD_ID:
            print("⚠️ Role updates disabled: DISCORD_GUILD_ID not set")
            return

        guild = bot.get_guild(DISCORD_GUILD_ID)
        if not guild:
            print(f"⚠️ Could not find guild with ID {DISCORD_GUILD_ID}")
            return
            
        # Validate bot permissions
        if not guild.me.guild_permissions.manage_roles:
            print("⚠️ Bot lacks manage_roles permission!")
            return
            
        # Cache role objects and validate they exist
        role_cache = {}
        for role_info in WATCHTIME_ROLES:
            role = discord.utils.get(guild.roles, name=role_info["name"])
            if not role:
                print(f"⚠️ Role {role_info['name']} not found in server!")
                continue
            role_cache[role_info["name"]] = role
            
    except Exception as e:
        print(f"⚠️ Error in role update task: {e}")
        await asyncio.sleep(5)  # Wait before retrying

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
                    
                    # Send DM notification to user
                    try:
                        hours = minutes / 60
                        embed = discord.Embed(
                            title="🎉 New Role Unlocked!",
                            description=f"Congratulations! You've earned the **{role.name}** role!",
                            color=0x53FC18
                        )
                        embed.add_field(
                            name="Your Watchtime",
                            value=f"{minutes:.0f} minutes ({hours:.1f} hours)",
                            inline=False
                        )
                        embed.add_field(
                            name="Keep Watching",
                            value="Continue watching to unlock more exclusive roles!",
                            inline=False
                        )
                        embed.set_footer(text=f"Kick: {kick_name}")
                        
                        await member.send(embed=embed)
                        print(f"[Discord] Sent role notification DM to {member.display_name}")
                    except discord.Forbidden:
                        # User has DMs disabled
                        print(f"[Discord] Could not DM {member.display_name} (DMs disabled)")
                    except Exception as dm_error:
                        print(f"[Discord] Error sending DM: {dm_error}")
                        
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
# Command cooldowns and checks
# -------------------------
class CommandCooldowns:
    # Cooldown settings
    LINK_COOLDOWN = commands.CooldownMapping.from_cooldown(1, 60, commands.BucketType.user)
    VERIFY_COOLDOWN = commands.CooldownMapping.from_cooldown(1, 30, commands.BucketType.user)
    LEADERBOARD_COOLDOWN = commands.CooldownMapping.from_cooldown(1, 30, commands.BucketType.channel)
    WATCHTIME_COOLDOWN = commands.CooldownMapping.from_cooldown(1, 15, commands.BucketType.user)
    UNLINK_COOLDOWN = commands.CooldownMapping.from_cooldown(1, 300, commands.BucketType.user)

def dynamic_cooldown(cooldown_mapping):
    async def predicate(ctx):
        bucket = cooldown_mapping.get_bucket(ctx.message)
        retry_after = bucket.update_rate_limit()
        if retry_after:
            raise commands.CommandOnCooldown(bucket, retry_after, cooldown_mapping._type)
        return True
    return commands.check(predicate)

# -------------------------
# Commands
# -------------------------
def in_guild():
    """Check if command is used in the configured guild."""
    async def predicate(ctx):
        if not DISCORD_GUILD_ID:
            return True
        return ctx.guild and ctx.guild.id == DISCORD_GUILD_ID
    return commands.check(predicate)

@bot.command(name="link")
@commands.cooldown(1, 60, commands.BucketType.user)  # One use per minute per user
@in_guild()
async def cmd_link(ctx, kick_username: str):
    """Generate a verification code to link Kick account to Discord."""
    try:
        discord_id = ctx.author.id
        kick_username = kick_username.lower()
        
        with engine.connect() as conn:
            # Check if this Discord user is already linked to any Kick account
            existing_link = conn.execute(text(
                "SELECT kick_name FROM links WHERE discord_id = :d"
            ), {"d": discord_id}).fetchone()
            
            if existing_link:
                await ctx.send(
                    f"✅ You are already linked to **{existing_link[0]}**.\n"
                    f"Use `!unlink` first if you want to link a different account."
                )
                return
            
            # Check if this Kick account is already linked to another Discord user
            existing_kick = conn.execute(text(
                "SELECT discord_id FROM links WHERE kick_name = :k"
            ), {"k": kick_username}).fetchone()
            
            if existing_kick and existing_kick[0] != discord_id:
                await ctx.send(
                    f"❌ The Kick account **{kick_username}** is already linked to another Discord user."
                )
                return
    except Exception as e:
        print(f"⚠️ Error in link command: {e}")
        await ctx.send("❌ An error occurred while checking account linkage. Please try again.")
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
@dynamic_cooldown(CommandCooldowns.VERIFY_COOLDOWN)
@in_guild()
async def cmd_verify(ctx, kick_username: str):
    """Verify Kick account ownership by checking bio for code."""
    discord_id = ctx.author.id
    kick_username = kick_username.lower()
    
    print(f"[Verify] Starting verification for {kick_username}")
    
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
    
    # Get user profile using Playwright
    try:
        user_data = await get_kick_bio(kick_username)
        if not user_data:
            await ctx.send("❌ Couldn't find that Kick user. Check the spelling and try again.")
            return
            
        # Get bio from user data
        bio = user_data.get("bio", "")
        if not bio:
            await ctx.send("❌ Couldn't read user's bio. Make sure you've added the verification code.")
            return
    except Exception as e:
        print(f"[Verify] Error fetching bio: {e}")
        await ctx.send("❌ Error accessing Kick profile. Try again later.")
        return
    
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
        # Enhanced browser-like headers
        verify_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Referer": "https://kick.com/",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-User": "?1",
            "Sec-Fetch-Dest": "document",
            "sec-ch-ua": '"Chromium";v="118", "Google Chrome";v="118", "Not=A?Brand";v="99"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"'
        }

        # Use Playwright to fetch bio from the about page
        print(f"[Verify] Fetching profile data for {kick_username}")
        user_data = await get_kick_bio(kick_username)
        
        if user_data is None:
            await ctx.send(
                "❌ Couldn't access Kick profile. The user might not exist or Kick is temporarily unavailable. Try again later."
            )
            return
        
        # Extract bio from user data
        bio = user_data.get('bio', '') if isinstance(user_data, dict) else ''
        
        if not bio:
            await ctx.send(
                "❌ No bio found on this Kick profile. Please add your verification code to your Kick bio and try again."
            )
            return
                
    except asyncio.TimeoutError:
        await ctx.send("❌ Request timed out. Please try again.")
        return
    except Exception as e:
        print(f"[Verify] Error during verification: {type(e).__name__}: {e}")
        await ctx.send("❌ Error contacting Kick. Try again later.")
        return

    # Check if code is in bio
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
@dynamic_cooldown(CommandCooldowns.WATCHTIME_COOLDOWN)
@in_guild()
async def cmd_watchtime(ctx, user: str = None):
    """Check watchtime for yourself or another user."""
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
# Admin Commands
# -------------------------
@bot.command(name="tracking")
@commands.has_permissions(administrator=True)
@in_guild()
async def toggle_tracking(ctx, action: str = None):
    """
    Admin command to control watchtime tracking.
    Usage: !tracking on|off|status
    """
    global stream_tracking_enabled
    
    if action is None or action.lower() == "status":
        status = "🟢 ENABLED" if stream_tracking_enabled else "🔴 DISABLED"
        await ctx.send(f"**Watchtime Tracking Status:** {status}")
        return
    
    if action.lower() == "on":
        stream_tracking_enabled = True
        await ctx.send("✅ **Watchtime tracking ENABLED**\nUsers will now earn watchtime from chat activity.")
    elif action.lower() == "off":
        stream_tracking_enabled = False
        await ctx.send("⏸️ **Watchtime tracking DISABLED**\nUsers will NOT earn watchtime until re-enabled.")
    else:
        await ctx.send("❌ Invalid option. Use: `!tracking on`, `!tracking off`, or `!tracking status`")

@toggle_tracking.error
async def tracking_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ You need Administrator permission to use this command.")

# -------------------------
# Bot events
# -------------------------
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")
    print(f"📺 Monitoring Kick channel: {KICK_CHANNEL}")
    
    try:
        # Ensure we're connected to the right guild
        if DISCORD_GUILD_ID:
            guild = bot.get_guild(DISCORD_GUILD_ID)
            if not guild:
                print(f"⚠️ Could not find guild with ID {DISCORD_GUILD_ID}")
                return
            
            # Validate bot permissions
            me = guild.me
            if not me.guild_permissions.manage_roles:
                print("⚠️ Bot lacks manage_roles permission!")
                return
            
            # Validate roles exist
            existing_roles = {role.name for role in guild.roles}
            for role_config in WATCHTIME_ROLES:
                if role_config["name"] not in existing_roles:
                    print(f"⚠️ Role {role_config['name']} does not exist in the server!")
        
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
            
    except Exception as e:
        print(f"⚠️ Error during startup: {e}")

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
    elif isinstance(error, commands.CommandOnCooldown):
        # Format cooldown message
        seconds = int(error.retry_after)
        if seconds < 60:
            await ctx.send(f"⏳ Please wait {seconds} seconds before using this command again.")
        else:
            minutes = seconds // 60
            await ctx.send(f"⏳ Please wait {minutes} minutes before using this command again.")
    elif isinstance(error, commands.CheckFailure):
        if "in_guild" in str(error):
            await ctx.send("❌ This command can only be used in the configured server.")
        else:
            await ctx.send("❌ You don't have permission to use this command.")
    elif isinstance(error, discord.HTTPException):
        if error.code == 429:  # Rate limit error
            retry_after = error.retry_after
            if retry_after > 1:  # If retry_after is significant
                await ctx.send(f"⚠️ Rate limited. Please try again in {int(retry_after)} seconds.")
            else:
                await ctx.send("⚠️ Too many requests. Please try again in a moment.")
        else:
            print(f"[HTTP Error] {error}")
            await ctx.send("❌ A network error occurred. Please try again.")
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
