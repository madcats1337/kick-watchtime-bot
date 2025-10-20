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

# OAuth configuration
OAUTH_BASE_URL = os.getenv("OAUTH_BASE_URL", "")  # e.g., https://your-app.up.railway.app
KICK_CLIENT_ID = os.getenv("KICK_CLIENT_ID", "")

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
    {"name": "Tier 1", "minutes": 60},
    {"name": "Tier 2", "minutes": 300},
    {"name": "Tier 3", "minutes": 1000},
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
    # 🔒 SECURITY: Use semaphore to limit concurrent browser instances
    async with playwright_semaphore:
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
    pool_size=10,           # 🔒 SECURITY: Increased from 3 to 10 to prevent connection exhaustion
    max_overflow=10,        # 🔒 SECURITY: Increased from 5 to 10 for better availability
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
        
        # Create oauth_notifications table
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS oauth_notifications (
            id SERIAL PRIMARY KEY,
            discord_id BIGINT NOT NULL,
            kick_username TEXT NOT NULL,
            channel_id BIGINT,
            message_id BIGINT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            processed BOOLEAN DEFAULT FALSE
        );
        """))
        
        # Migrate existing oauth_notifications table to add new columns if they don't exist
        try:
            conn.execute(text("""
                ALTER TABLE oauth_notifications 
                ADD COLUMN IF NOT EXISTS channel_id BIGINT
            """))
            conn.execute(text("""
                ALTER TABLE oauth_notifications 
                ADD COLUMN IF NOT EXISTS message_id BIGINT
            """))
        except Exception as e:
            print(f"ℹ️ Migration note: {e}")
        
        # Create link_panels table for reaction-based OAuth linking
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS link_panels (
            id SERIAL PRIMARY KEY,
            guild_id BIGINT NOT NULL,
            channel_id BIGINT NOT NULL,
            message_id BIGINT NOT NULL,
            emoji TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(guild_id, channel_id, message_id)
        );
        """))
    print("✅ Database tables initialized successfully")
except Exception as e:
    print(f"⚠️ Database initialization error: {e}")
    raise

# -------------------------
# Discord bot setup
# -------------------------
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.reactions = True  # Enable reaction events

bot = commands.Bot(command_prefix="!", intents=intents)

# In-memory active viewer tracking
active_viewers = {}

# Stream status tracking
stream_tracking_enabled = True  # Admin can toggle this
last_chat_activity = None  # Track last time we saw any chat activity

# 🔒 SECURITY: Track unique chatters in recent window for stream-live detection
recent_chatters = {}  # {username: timestamp} - rolling window of recent chat activity
MIN_UNIQUE_CHATTERS = 3  # Require at least 3 different people chatting to consider stream "live"
CHAT_ACTIVITY_WINDOW_MINUTES = 10  # Look back 10 minutes for unique chatters

# 🔒 SECURITY: Semaphore to limit concurrent Playwright operations (prevent resource exhaustion)
playwright_semaphore = asyncio.Semaphore(2)  # Max 2 concurrent browser instances

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
                                global last_chat_activity, recent_chatters
                                now = datetime.now(timezone.utc)
                                last_chat_activity = now  # Update stream activity
                                
                                event_data = json.loads(data.get("data", "{}"))
                                sender = event_data.get("sender", {})
                                username = sender.get("username")
                                
                                if username:
                                    username_lower = username.lower()
                                    active_viewers[username_lower] = now
                                    # 🔒 SECURITY: Track unique chatters for stream-live detection
                                    recent_chatters[username_lower] = now
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
    """Update watchtime for active viewers (only when tracking is enabled and stream has real activity)."""
    global stream_tracking_enabled, last_chat_activity, recent_chatters
    
    try:
        # Check if tracking is enabled by admin
        if not stream_tracking_enabled:
            return
        
        now = datetime.now(timezone.utc)
        
        # 🔒 SECURITY: Multi-factor stream-live detection
        # Require multiple unique chatters to prevent single-user farming
        
        if last_chat_activity is None:
            print("[Security] No chat activity detected yet - skipping watchtime update")
            return
        
        # Check 1: Recent chat activity (within last 10 minutes)
        time_since_last_chat = (now - last_chat_activity).total_seconds() / 60
        if time_since_last_chat > CHAT_ACTIVITY_WINDOW_MINUTES:
            print(f"[Security] No chat activity for {time_since_last_chat:.1f} minutes - stream likely offline")
            return
        
        # Check 2: Count unique chatters in the recent window
        chat_cutoff = now - timedelta(minutes=CHAT_ACTIVITY_WINDOW_MINUTES)
        active_chatters = {
            username: timestamp 
            for username, timestamp in recent_chatters.items() 
            if timestamp >= chat_cutoff
        }
        
        unique_chatter_count = len(active_chatters)
        
        if unique_chatter_count < MIN_UNIQUE_CHATTERS:
            print(f"[Security] Only {unique_chatter_count} unique chatter(s) in last {CHAT_ACTIVITY_WINDOW_MINUTES} min (need {MIN_UNIQUE_CHATTERS})")
            print("[Security] Stream might be offline or being farmed - skipping watchtime update")
            print("[Security] Tip: Use '!tracking on' to override if stream has low chat activity")
            return
        
        print(f"[Security] ✅ Stream appears live: {unique_chatter_count} unique chatters in last {CHAT_ACTIVITY_WINDOW_MINUTES} min")
        
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
        
        # 🔒 SECURITY: Daily watchtime cap (max 18 hours per day to prevent abuse)
        MAX_DAILY_HOURS = 18
        MAX_DAILY_MINUTES = MAX_DAILY_HOURS * 60
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Update all active users in a single transaction
        with engine.begin() as conn:
            for user, last_seen in active_users.items():
                try:
                    # Check today's watchtime for this user
                    daily_check = conn.execute(text("""
                        SELECT minutes, last_active FROM watchtime WHERE username = :u
                    """), {"u": user}).fetchone()
                    
                    if daily_check:
                        existing_minutes, last_active_str = daily_check
                        last_active = datetime.fromisoformat(last_active_str) if last_active_str else today_start
                        
                        # If last active was today and they've hit the cap, skip
                        if last_active >= today_start and existing_minutes >= MAX_DAILY_MINUTES:
                            print(f"[Security] User {user} has reached daily watchtime cap ({MAX_DAILY_HOURS}h)")
                            continue
                    
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
# Cleanup expired verification codes and old chat data
# -------------------------
@tasks.loop(seconds=5)  # Check every 5 seconds for fast response
async def check_oauth_notifications_task():
    """Check for OAuth link success notifications and send Discord messages."""
    try:
        with engine.begin() as conn:
            # Get unprocessed notifications
            notifications = conn.execute(text("""
                SELECT id, discord_id, kick_username, channel_id, message_id
                FROM oauth_notifications 
                WHERE processed = FALSE AND kick_username != ''
                ORDER BY created_at ASC
                LIMIT 10
            """)).fetchall()
            
            for notification_id, discord_id, kick_username, channel_id, message_id in notifications:
                try:
                    # Delete the original "Link with Kick OAuth" message if we have the IDs
                    if channel_id and message_id:
                        try:
                            channel = bot.get_channel(int(channel_id))
                            if channel:
                                try:
                                    original_message = await channel.fetch_message(int(message_id))
                                    await original_message.delete()
                                    print(f"🗑️ Deleted original OAuth message", flush=True)
                                except (discord.NotFound, discord.Forbidden):
                                    pass
                        except Exception as e:
                            print(f"⚠️ Could not delete original message: {e}", flush=True)
                    
                    # Get the user
                    user = await bot.fetch_user(int(discord_id))
                    if user:
                        # Send success message via DM
                        try:
                            await user.send(f"✅ **Verification Successful!**\n\nYour Discord account has been linked to Kick account **{kick_username}**.")
                        except discord.Forbidden:
                            # If DM fails, try to find a guild channel
                            if DISCORD_GUILD_ID:
                                guild = bot.get_guild(DISCORD_GUILD_ID)
                                if guild:
                                    member = guild.get_member(int(discord_id))
                                    if member:
                                        # Try to send in the same channel as original message, or system channel
                                        target_channel = bot.get_channel(int(channel_id)) if channel_id else None
                                        if not target_channel or not target_channel.permissions_for(guild.me).send_messages:
                                            target_channel = guild.system_channel or next((ch for ch in guild.text_channels if ch.permissions_for(guild.me).send_messages), None)
                                        
                                        if target_channel:
                                            await target_channel.send(f"{member.mention} ✅ **Verification Successful!** Your account has been linked to Kick **{kick_username}**.")
                    
                    # Mark as processed
                    conn.execute(text("""
                        UPDATE oauth_notifications 
                        SET processed = TRUE 
                        WHERE id = :id
                    """), {"id": notification_id})
                    
                    print(f"✅ Sent OAuth success notification to Discord {discord_id}", flush=True)
                    
                except Exception as e:
                    print(f"⚠️ Error sending OAuth notification to {discord_id}: {e}", flush=True)
                    # Mark as processed anyway to avoid retry loops
                    conn.execute(text("""
                        UPDATE oauth_notifications 
                        SET processed = TRUE 
                        WHERE id = :id
                    """), {"id": notification_id})
                    
    except Exception as e:
        print(f"⚠️ Error in OAuth notifications task: {e}", flush=True)
@tasks.loop(minutes=5)
async def cleanup_pending_links_task():
    """Remove expired verification codes and old chat activity data."""
    global recent_chatters
    
    now = datetime.now(timezone.utc)
    
    # 🔒 SECURITY: Clean up old chatter data to prevent memory leak
    chat_cutoff = now - timedelta(minutes=CHAT_ACTIVITY_WINDOW_MINUTES * 2)  # Keep 2x window for safety
    recent_chatters = {
        username: timestamp 
        for username, timestamp in recent_chatters.items() 
        if timestamp >= chat_cutoff
    }
    
    expiry_cutoff = now - timedelta(minutes=CODE_EXPIRY_MINUTES)
    
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
# Progressive cooldown tracking: {user_id: {command: attempt_count}}
progressive_cooldown_attempts = {}

class CommandCooldowns:
    # Cooldown settings (base values, will increase progressively)
    LINK_COOLDOWN = commands.CooldownMapping.from_cooldown(1, 10, commands.BucketType.user)  # Start at 10s, +10s per attempt
    VERIFY_COOLDOWN = commands.CooldownMapping.from_cooldown(3, 300, commands.BucketType.user)  # 🔒 SECURITY: Max 3 attempts per 5 minutes
    LEADERBOARD_COOLDOWN = commands.CooldownMapping.from_cooldown(1, 30, commands.BucketType.channel)
    WATCHTIME_COOLDOWN = commands.CooldownMapping.from_cooldown(1, 15, commands.BucketType.user)
    UNLINK_COOLDOWN = commands.CooldownMapping.from_cooldown(1, 300, commands.BucketType.user)

def progressive_cooldown(base_seconds: int, increment_seconds: int, max_seconds: int):
    """
    Progressive cooldown that increases with each use.
    
    Args:
        base_seconds: Starting cooldown (e.g., 10)
        increment_seconds: How much to add per attempt (e.g., 10)
        max_seconds: Maximum cooldown cap (e.g., 60)
    
    Example: 10s -> 20s -> 30s -> 40s -> 50s -> 60s (capped)
    """
    async def predicate(ctx):
        # 🔒 ADMIN BYPASS: Admins skip cooldowns for testing
        if ctx.guild and ctx.author.guild_permissions.administrator:
            return True
        
        user_id = ctx.author.id
        command_name = ctx.command.name
        
        # Initialize tracking
        if user_id not in progressive_cooldown_attempts:
            progressive_cooldown_attempts[user_id] = {}
        
        if command_name not in progressive_cooldown_attempts[user_id]:
            progressive_cooldown_attempts[user_id][command_name] = {
                'count': 0,
                'last_use': None
            }
        
        tracking = progressive_cooldown_attempts[user_id][command_name]
        now = datetime.now(timezone.utc)
        
        # Reset count if enough time has passed (2x max cooldown = full reset)
        if tracking['last_use']:
            time_since_last = (now - tracking['last_use']).total_seconds()
            if time_since_last > (max_seconds * 2):
                tracking['count'] = 0
        
        # Calculate progressive cooldown
        current_cooldown = min(base_seconds + (tracking['count'] * increment_seconds), max_seconds)
        
        # Check if user is still on cooldown
        if tracking['last_use']:
            time_since_last = (now - tracking['last_use']).total_seconds()
            if time_since_last < current_cooldown:
                retry_after = current_cooldown - time_since_last
                raise commands.CommandOnCooldown(None, retry_after, commands.BucketType.user)
        
        # Update tracking
        tracking['count'] += 1
        tracking['last_use'] = now
        
        return True
    return commands.check(predicate)

def dynamic_cooldown(cooldown_mapping):
    async def predicate(ctx):
        # 🔒 SECURITY: Admins bypass cooldowns for testing
        if ctx.guild and ctx.author.guild_permissions.administrator:
            return True
        
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

@bot.command(name="linkbio")
@progressive_cooldown(base_seconds=10, increment_seconds=10, max_seconds=60)  # 10s -> 20s -> 30s -> ... -> 60s (capped)
@in_guild()
async def cmd_linkbio(ctx, kick_username: str):
    """Generate a verification code to link Kick account to Discord (bio method)."""
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
                    f"Contact an admin if you need to unlink your account."
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
        return
    
    # 🔒 SECURITY: Generate unique verification code with collision detection
    max_attempts = 10
    code = None
    
    with engine.begin() as conn:
        for attempt in range(max_attempts):
            # Generate 6-digit verification code
            candidate_code = ''.join(random.choices(string.digits, k=6))
            
            # Check if code already exists in pending_links
            existing_code = conn.execute(text(
                "SELECT discord_id FROM pending_links WHERE code = :c"
            ), {"c": candidate_code}).fetchone()
            
            if not existing_code:
                code = candidate_code
                break
        
        if not code:
            await ctx.send("❌ Unable to generate verification code. Please try again.")
            return
        
        # Remove any existing pending verification for this Discord user
        conn.execute(text("DELETE FROM pending_links WHERE discord_id = :d"), {"d": discord_id})
        
        # Insert new pending verification
        now_iso = datetime.now(timezone.utc).isoformat()
        conn.execute(text("""
            INSERT INTO pending_links (discord_id, kick_name, code, timestamp)
            VALUES (:d, :k, :c, :t)
        """), {"d": discord_id, "k": kick_username, "c": code, "t": now_iso})
    
    await ctx.send(
        f"🔗 **Link your Kick account**\n\n"
        f"1. Go to https://kick.com/dashboard/settings/profile\n"
        f"2. Add this code to your bio: **{code}**\n"
        f"3. Run `!verify {kick_username}` here\n\n"
        f"⏰ Code expires in {CODE_EXPIRY_MINUTES} minutes.\n\n"
        f"💡 **Tip:** Use `!link` for instant OAuth linking without editing your bio!"
    )

@bot.command(name="link")
@progressive_cooldown(base_seconds=10, increment_seconds=10, max_seconds=60)
@in_guild()
async def cmd_link(ctx):
    """Link your Kick account using OAuth (instant, no bio editing required)."""
    
    if not OAUTH_BASE_URL or not KICK_CLIENT_ID:
        await ctx.send(
            "❌ OAuth linking is not configured on this bot.\n"
            "Use `!linkbio <kick_username>` for bio verification instead."
        )
        return
    
    discord_id = ctx.author.id
    
    # Check if already linked
    with engine.connect() as conn:
        existing = conn.execute(text(
            "SELECT kick_name FROM links WHERE discord_id = :d"
        ), {"d": discord_id}).fetchone()
        
        if existing:
            await ctx.send(
                f"✅ You are already linked to **{existing[0]}**.\n"
                f"Contact an admin if you need to unlink your account."
            )
            return
    
    # Generate OAuth URL
    oauth_url = f"{OAUTH_BASE_URL}/auth/kick?discord_id={discord_id}"
    
    embed = discord.Embed(
        title="🔗 Link with Kick OAuth",
        description="Click the button below to securely link your Kick account.",
        color=0x53FC18
    )
    embed.add_field(
        name="📝 Instructions",
        value="1. Click the link below\n2. Log in to Kick (if needed)\n3. Authorize the connection\n4. You're done!",
        inline=False
    )
    embed.set_footer(text="Link expires in 10 minutes")
    
    # Create a view with a button
    view = discord.ui.View()
    button = discord.ui.Button(
        label="Link with Kick",
        style=discord.ButtonStyle.link,
        url=oauth_url,
        emoji="🎮"
    )
    view.add_item(button)
    
    message = await ctx.send(embed=embed, view=view)
    
    # Store message info for later deletion
    with engine.begin() as conn:
        # Delete any existing pending OAuth for this user
        conn.execute(text("DELETE FROM oauth_notifications WHERE discord_id = :d AND processed = FALSE"), {"d": discord_id})
        
        # Store message info (will be updated with kick_username when OAuth completes)
        conn.execute(text("""
            INSERT INTO oauth_notifications (discord_id, kick_username, channel_id, message_id, processed)
            VALUES (:d, '', :c, :m, FALSE)
        """), {"d": discord_id, "c": ctx.channel.id, "m": message.id})

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
@commands.has_permissions(manage_guild=True)
@in_guild()
async def cmd_unlink(ctx, member: discord.Member = None):
    """Admin command to unlink a user's Kick account from Discord.
    
    Usage: 
    !unlink @user - Unlink another user's account (admin only)
    """
    
    # Admin must specify a user
    if member is None:
        await ctx.send("❌ Usage: `!unlink @user`\n\nAdmins must specify which user to unlink.")
        return
    
    discord_id = member.id
    
    # Check if user has a linked account
    with engine.connect() as conn:
        existing = conn.execute(text(
            "SELECT kick_name FROM links WHERE discord_id = :d"
        ), {"d": discord_id}).fetchone()
    
    if not existing:
        await ctx.send(f"❌ {member.mention} doesn't have a linked Kick account.")
        return
    
    kick_name = existing[0]
    
    # Unlink without confirmation (admin action)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM links WHERE discord_id = :d"), {"d": discord_id})
        
        # Also clean up any pending OAuth notifications
        conn.execute(text("DELETE FROM oauth_notifications WHERE discord_id = :d"), {"d": discord_id})
        
        # Clean up pending verifications
        conn.execute(text("DELETE FROM pending_links WHERE discord_id = :d"), {"d": discord_id})
    
    await ctx.send(
        f"🔓 Admin action: {member.mention}'s Kick account **{kick_name}** has been unlinked.\n"
        f"Their watchtime has been preserved."
    )

@cmd_unlink.error
async def unlink_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ This command is admin-only. Regular users cannot unlink accounts to prevent abuse.")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("❌ Invalid user. Usage: `!unlink @user`")

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
async def cmd_watchtime(ctx, kick_username: str = None):
    """
    Check watchtime for yourself or another user.
    Usage: !watchtime (check your own) or !watchtime <kick_username> (admins only)
    """
    discord_id = ctx.author.id
    is_admin = ctx.guild and ctx.author.guild_permissions.administrator
    
    with engine.connect() as conn:
        # If kick_username provided, check if admin
        if kick_username:
            if not is_admin:
                await ctx.send("❌ Only administrators can check other users' watchtime.")
                return
            
            # Admin lookup by Kick username
            kick_name = kick_username.lower()
            watchtime = conn.execute(text(
                "SELECT minutes FROM watchtime WHERE username = :u"
            ), {"u": kick_name}).fetchone()
            
            if not watchtime or watchtime[0] == 0:
                await ctx.send(
                    f"⏱️ No watchtime recorded for **{kick_name}**."
                )
                return
        else:
            # Regular user checking their own watchtime
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
    else:
        # Show next role milestone
        for role_info in WATCHTIME_ROLES:
            if minutes < role_info["minutes"]:
                remaining = role_info["minutes"] - minutes
                embed.add_field(
                    name="Next Role", 
                    value=f"**{role_info['name']}** in {remaining:.0f} more minutes",
                    inline=False
                )
                break
    
    await ctx.send(embed=embed)

# -------------------------
# Admin Commands
# -------------------------
@bot.command(name="tracking")
@commands.has_permissions(administrator=True)
@in_guild()  # 🔒 SECURITY: Ensure command only works in the configured guild
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
        await ctx.send("❌ You need administrator permissions to use this command.")

@bot.command(name="setup_link_panel")
@commands.has_permissions(manage_guild=True)
@in_guild()
async def setup_link_panel(ctx, emoji: str = "🔗"):
    """
    Admin command to create a pinned message for reaction-based OAuth linking.
    Usage: !setup_link_panel [emoji]
    Default emoji: 🔗
    
    Users can react to the pinned message to link their Kick account via OAuth.
    """
    
    if not OAUTH_BASE_URL or not KICK_CLIENT_ID:
        await ctx.send(
            "❌ OAuth linking is not configured on this bot.\n"
            "Please set OAUTH_BASE_URL and KICK_CLIENT_ID environment variables."
        )
        return
    
    # Create the embed for the pinned message
    embed = discord.Embed(
        title="🎮 Link Your Kick Account",
        description=f"React with {emoji} below to link your Discord account with your Kick account!",
        color=0x53FC18
    )
    embed.set_footer(text="Contact an admin if you need to unlink your account")
    
    # Send the message
    message = await ctx.send(embed=embed)
    
    # Add the reaction
    await message.add_reaction(emoji)
    
    # Pin the message
    try:
        await message.pin()
    except discord.Forbidden:
        await ctx.send("⚠️ I don't have permission to pin messages. Please pin the message manually.")
    except discord.HTTPException as e:
        await ctx.send(f"⚠️ Failed to pin message: {e}")
    
    # Store in database
    with engine.begin() as conn:
        # Remove any existing link panel for this channel (only one per channel)
        conn.execute(text("""
            DELETE FROM link_panels 
            WHERE guild_id = :g AND channel_id = :c
        """), {"g": ctx.guild.id, "c": ctx.channel.id})
        
        # Insert new link panel
        conn.execute(text("""
            INSERT INTO link_panels (guild_id, channel_id, message_id, emoji)
            VALUES (:g, :c, :m, :e)
        """), {"g": ctx.guild.id, "c": ctx.channel.id, "m": message.id, "e": emoji})
    
    await ctx.send(f"✅ Link panel created! Users can now react with {emoji} to start the OAuth linking process.")

@setup_link_panel.error
async def setup_link_panel_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ You need 'Manage Server' permission to use this command.")

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
        
        if not check_oauth_notifications_task.is_running():
            check_oauth_notifications_task.start()
            print("✅ OAuth notifications task started")
            
    except Exception as e:
        print(f"⚠️ Error during startup: {e}")

    # Start Kick chat listener
    bot.loop.create_task(kick_chat_loop(KICK_CHANNEL))
    print("✅ Kick chat listener started")

@bot.event
async def on_raw_reaction_add(payload):
    """Handle reactions to link panel messages."""
    
    # Ignore bot's own reactions
    if payload.user_id == bot.user.id:
        return
    
    # Check if this reaction is on a link panel message
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT emoji FROM link_panels 
            WHERE guild_id = :g AND channel_id = :c AND message_id = :m
        """), {"g": payload.guild_id, "c": payload.channel_id, "m": payload.message_id}).fetchone()
        
        if not result:
            return  # Not a link panel message
        
        panel_emoji = result[0]
        
        # Check if the reaction emoji matches
        reaction_emoji = str(payload.emoji)
        if reaction_emoji != panel_emoji:
            return  # Wrong emoji
    
    # Get the user
    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return
    
    member = guild.get_member(payload.user_id)
    if not member:
        return
    
    discord_id = member.id
    
    # Check if already linked
    with engine.connect() as conn:
        existing = conn.execute(text(
            "SELECT kick_name FROM links WHERE discord_id = :d"
        ), {"d": discord_id}).fetchone()
        
        if existing:
            # Send message in channel instead of DM
            channel = bot.get_channel(payload.channel_id)
            if channel:
                await channel.send(
                    f"✅ {member.mention} You are already linked to **{existing[0]}**!",
                    delete_after=8  # Auto-delete after 8 seconds
                )
            
            # Remove the reaction
            try:
                if channel:
                    message = await channel.fetch_message(payload.message_id)
                    await message.remove_reaction(payload.emoji, member)
                    print(f"✅ Removed reaction from {member.name} (already linked)")
            except discord.Forbidden:
                print(f"⚠️ Missing permissions to remove reaction for {member.name}")
            except discord.NotFound:
                print(f"⚠️ Message or reaction not found for {member.name}")
            except Exception as e:
                print(f"⚠️ Failed to remove reaction for {member.name}: {e}")
            
            return
    
    # Generate OAuth URL
    oauth_url = f"{OAUTH_BASE_URL}/auth/kick?discord_id={discord_id}"
    
    embed = discord.Embed(
        title="🔗 Link with Kick OAuth",
        description="Click the button below to securely link your Kick account.",
        color=0x53FC18
    )
    embed.add_field(
        name="📝 Instructions",
        value="1. Click the link below\n2. Log in to Kick (if needed)\n3. Authorize the connection\n4. You're done!",
        inline=False
    )
    embed.set_footer(text="Link expires in 10 minutes")
    
    # Create a view with a button
    view = discord.ui.View()
    button = discord.ui.Button(
        label="Link with Kick",
        style=discord.ButtonStyle.link,
        url=oauth_url,
        emoji="🎮"
    )
    view.add_item(button)
    
    # Try to DM the user
    try:
        dm_message = await member.send(embed=embed, view=view)
        
        # Send confirmation message in channel (only visible to user, auto-deletes)
        channel = bot.get_channel(payload.channel_id)
        if channel:
            confirmation = await channel.send(
                f"✅ {member.mention} Check your DMs for the OAuth link!",
                delete_after=5  # Auto-delete after 5 seconds
            )
        
        # Remove the reaction immediately after sending DM
        try:
            if channel:
                message = await channel.fetch_message(payload.message_id)
                await message.remove_reaction(payload.emoji, member)
                print(f"✅ Removed reaction from {member.name} on link panel")
            else:
                print(f"⚠️ Could not find channel {payload.channel_id}")
        except discord.Forbidden:
            print(f"⚠️ Missing permissions to remove reaction for {member.name}")
        except discord.NotFound:
            print(f"⚠️ Message or reaction not found for {member.name}")
        except Exception as e:
            print(f"⚠️ Failed to remove reaction for {member.name}: {e}")
        
        # Store the DM message info for later deletion
        with engine.begin() as conn:
            # Delete any existing pending OAuth for this user
            conn.execute(text("DELETE FROM oauth_notifications WHERE discord_id = :d AND processed = FALSE"), {"d": discord_id})
            
            # Store DM message info (will be updated with kick_username when OAuth completes)
            conn.execute(text("""
                INSERT INTO oauth_notifications (discord_id, kick_username, channel_id, message_id, processed)
                VALUES (:d, '', :c, :m, FALSE)
            """), {"d": discord_id, "c": dm_message.channel.id, "m": dm_message.id})
            
    except discord.Forbidden:
        # User has DMs disabled, send in channel instead
        try:
            channel = bot.get_channel(payload.channel_id)
            channel_message = await channel.send(
                f"{member.mention} Check your DMs for the OAuth link! (If you don't see it, make sure DMs are enabled)",
                embed=embed,
                view=view,
                delete_after=60  # Auto-delete after 1 minute
            )
            
            # Remove the reaction immediately after sending message
            try:
                message = await channel.fetch_message(payload.message_id)
                await message.remove_reaction(payload.emoji, member)
                print(f"✅ Removed reaction from {member.name} (DMs disabled)")
            except discord.Forbidden:
                print(f"⚠️ Missing permissions to remove reaction for {member.name}")
            except discord.NotFound:
                print(f"⚠️ Message or reaction not found for {member.name}")
            except Exception as e:
                print(f"⚠️ Failed to remove reaction for {member.name}: {e}")
            
            # Store the channel message info
            with engine.begin() as conn:
                # Delete any existing pending OAuth for this user
                conn.execute(text("DELETE FROM oauth_notifications WHERE discord_id = :d AND processed = FALSE"), {"d": discord_id})
                
                # Store channel message info
                conn.execute(text("""
                    INSERT INTO oauth_notifications (discord_id, kick_username, channel_id, message_id, processed)
                    VALUES (:d, '', :c, :m, FALSE)
                """), {"d": discord_id, "c": channel_message.channel.id, "m": channel_message.id})
                
        except Exception as e:
            print(f"Failed to send OAuth link to {member}: {e}")

@bot.event
async def on_command_error(ctx, error):
    """Handle command errors gracefully."""
    try:
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"❌ Missing argument: `{error.param.name}`")
        elif isinstance(error, commands.CommandNotFound):
            pass  # Ignore unknown commands
        elif isinstance(error, commands.CommandOnCooldown):
            # 🔒 ADMIN BYPASS: Skip cooldown for administrators
            if ctx.guild and ctx.author.guild_permissions.administrator:
                await ctx.reinvoke()
                return
            
            # Format cooldown message
            seconds = int(error.retry_after)
            if seconds < 60:
                await ctx.send(f"⏳ Please wait **{seconds}** seconds before using this command again.")
            else:
                minutes = seconds // 60
                remaining_seconds = seconds % 60
                if remaining_seconds > 0:
                    await ctx.send(f"⏳ Please wait **{minutes}m {remaining_seconds}s** before using this command again.")
                else:
                    await ctx.send(f"⏳ Please wait **{minutes} minutes** before using this command again.")
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
    except discord.Forbidden:
        # Bot doesn't have permission to send messages in this channel
        print(f"[Permission Error] Cannot send error message in channel {ctx.channel.id}: {error}")
    except Exception as e:
        # Catch any other errors to prevent crash
        print(f"[Critical Error in error handler] {e}")


# -------------------------
# Run bot
# -------------------------
if not DISCORD_TOKEN:
    raise SystemExit("❌ DISCORD_TOKEN environment variable is required")

if not KICK_CHANNEL:
    raise SystemExit("❌ KICK_CHANNEL environment variable is required")

bot.run(DISCORD_TOKEN)
