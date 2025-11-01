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
import hmac
import hashlib
import base64
from typing import Optional
from kick_api import USER_AGENTS
from datetime import datetime, timedelta, timezone
from functools import partial

from dotenv import load_dotenv
from sqlalchemy import create_engine, text # type: ignore
from kick_api import fetch_chatroom_id, check_stream_live, KickAPI, USER_AGENTS  # Consolidated Kick API module

import discord
from discord.ext import commands, tasks

# Raffle system imports
from raffle_system.database import setup_raffle_database, get_current_period, create_new_period, migrate_add_created_at_to_shuffle_wagers
from raffle_system.watchtime_converter import setup_watchtime_converter
from raffle_system.gifted_sub_tracker import setup_gifted_sub_handler
from raffle_system.shuffle_tracker import setup_shuffle_tracker
from raffle_system.auto_leaderboard import setup_auto_leaderboard
from raffle_system.commands import setup as setup_raffle_commands
from raffle_system.scheduler import setup_raffle_scheduler

# Slot call tracker import
from slot_calls import setup_slot_call_tracker
from slot_request_panel import setup_slot_panel

# Timed messages import
from timed_messages import setup_timed_messages

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

# Slot call tracker configuration
SLOT_CALLS_CHANNEL_ID = int(os.getenv("SLOT_CALLS_CHANNEL_ID")) if os.getenv("SLOT_CALLS_CHANNEL_ID") else None

# OAuth configuration
OAUTH_BASE_URL = os.getenv("OAUTH_BASE_URL", "")  # e.g., https://your-app.up.railway.app
KICK_CLIENT_ID = os.getenv("KICK_CLIENT_ID", "")
KICK_CLIENT_SECRET = os.getenv("KICK_CLIENT_SECRET", "")  # Used for both OAuth and Kick bot
OAUTH_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "")

# Kick bot configuration (for sending chat messages)
# Requires User Access Token from OAuth flow with chat:write scope
KICK_BOT_USER_TOKEN = os.getenv("KICK_BOT_USER_TOKEN", "")  # User access token for Kick bot

# CRITICAL: If FLASK_SECRET_KEY is not set, OAuth will not work!
if not OAUTH_SECRET_KEY:
    print("=" * 80, flush=True)
    print("⚠️  CRITICAL: FLASK_SECRET_KEY environment variable is NOT SET!", flush=True)
    print("⚠️  OAuth linking will NOT WORK without this key!", flush=True)
    print("⚠️  Please set FLASK_SECRET_KEY in Railway environment variables.", flush=True)
    print("=" * 80, flush=True)
else:
    print(f"[Bot] FLASK_SECRET_KEY loaded: {len(OAUTH_SECRET_KEY)} chars, hash={hash(OAUTH_SECRET_KEY) % 10000}", flush=True)

# -------------------------
# 🔒 Security: OAuth URL Signing
# -------------------------
def generate_signed_oauth_url(discord_id: int) -> str:
    """
    Generate a cryptographically signed OAuth URL to prevent initiation spoofing.
    Only URLs generated by this bot will have valid signatures.
    """
    timestamp = int(datetime.now(timezone.utc).timestamp())
    message = f"{discord_id}:{timestamp}"
    signature = hmac.new(
        OAUTH_SECRET_KEY.encode(),
        message.encode(),
        hashlib.sha256
    ).digest()
    sig_encoded = base64.urlsafe_b64encode(signature).decode().rstrip('=')
    
    return f"{OAUTH_BASE_URL}/auth/kick?discord_id={discord_id}&timestamp={timestamp}&signature={sig_encoded}"

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
    {"name": "Tier 1", "minutes": 120},
    {"name": "Tier 2", "minutes": 600},
    {"name": "Tier 3", "minutes": 2000},
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

# -------------------------
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
        
        # Create timer_panels table for reaction-based timer management
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS timer_panels (
            id SERIAL PRIMARY KEY,
            guild_id BIGINT NOT NULL,
            channel_id BIGINT NOT NULL,
            message_id BIGINT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(guild_id, channel_id, message_id)
        );
        """))
        
        # Create bot_settings table for persistent configuration
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS bot_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """))
        
        # Create link_logs_config table for Discord logging configuration
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS link_logs_config (
            guild_id BIGINT PRIMARY KEY,
            channel_id BIGINT NOT NULL,
            enabled BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """))
        
        # Create watchtime_roles table for configurable role thresholds
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS watchtime_roles (
            id SERIAL PRIMARY KEY,
            role_name TEXT NOT NULL,
            minutes_required INTEGER NOT NULL,
            display_order INTEGER NOT NULL,
            enabled BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """))
        
        # Insert default roles if table is empty
        role_count = conn.execute(text("SELECT COUNT(*) FROM watchtime_roles")).fetchone()[0]
        if role_count == 0:
            print("📝 Initializing default watchtime roles...")
            for idx, role in enumerate(WATCHTIME_ROLES, 1):
                conn.execute(text("""
                    INSERT INTO watchtime_roles (role_name, minutes_required, display_order, enabled)
                    VALUES (:name, :minutes, :order, TRUE)
                """), {"name": role["name"], "minutes": role["minutes"], "order": idx})
            print("✅ Default watchtime roles created")
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

# Kick chat WebSocket connection (for sending messages)
kick_ws = None
kick_chatroom_id_global = None

# Stream status tracking
stream_tracking_enabled = True  # Admin can toggle this
# When true, admins can force watchtime updates to run even if the live-detection
# checks (unique chatters, recent activity) would normally block updates.
tracking_force_override = False
# When true, enables detailed debug logging for watchtime tracking
watchtime_debug_enabled = True  # Admin can toggle this

# Load tracking_force_override from database
try:
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT value FROM bot_settings WHERE key = 'tracking_force_override'
        """)).fetchone()
        if result:
            tracking_force_override = result[0].lower() == 'true'
            print(f"🔧 Loaded tracking_force_override from database: {tracking_force_override}")
except Exception as e:
    print(f"ℹ️ Could not load tracking_force_override from database (using default): {e}")

last_chat_activity = None  # Track last time we saw any chat activity

# 🔒 SECURITY: Track unique chatters in recent window for stream-live detection
recent_chatters = {}  # {username: timestamp} - rolling window of recent chat activity

# Raffle system global tracker
gifted_sub_tracker = None  # Will be initialized in on_ready()
shuffle_tracker = None  # Will be initialized in on_ready()
slot_call_tracker = None  # Will be initialized in on_ready()
MIN_UNIQUE_CHATTERS = 2  # Require at least 2 different people chatting to consider stream "live"
CHAT_ACTIVITY_WINDOW_MINUTES = 5  # Look back 5 minutes for unique chatters

# -------------------------
# Helper functions
# -------------------------
def get_active_chatters_count():
    """Get the number of active chatters in the recent window"""
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)  # Use timezone-aware datetime
    chat_cutoff = now - timedelta(minutes=CHAT_ACTIVITY_WINDOW_MINUTES)
    
    active_chatters = {
        username: timestamp 
        for username, timestamp in recent_chatters.items() 
        if timestamp >= chat_cutoff
    }
    
    return len(active_chatters)

# -------------------------
# Role configuration helper
# -------------------------
def load_watchtime_roles():
    """Load watchtime role configuration from database."""
    try:
        with engine.connect() as conn:
            roles = conn.execute(text("""
                SELECT role_name, minutes_required 
                FROM watchtime_roles 
                WHERE enabled = TRUE 
                ORDER BY display_order ASC
            """)).fetchall()
            
            if roles:
                role_list = [{"name": r[0], "minutes": r[1]} for r in roles]
                print(f"🎯 Loaded {len(role_list)} watchtime roles from database")
                return role_list
            else:
                print("⚠️ No roles found in database, using hardcoded defaults")
                return WATCHTIME_ROLES
    except Exception as e:
        print(f"⚠️ Could not load roles from database: {e}")
        return WATCHTIME_ROLES

# -------------------------
# Link logging helper
# -------------------------
async def log_link_attempt(discord_user, kick_username: str, success: bool, error_message: str = None):
    """Log account linking attempts to configured Discord channel."""
    if not DISCORD_GUILD_ID:
        return
    
    try:
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT channel_id, enabled FROM link_logs_config 
                WHERE guild_id = :guild_id
            """), {"guild_id": DISCORD_GUILD_ID}).fetchone()
            
            if not result or not result[1]:  # Not configured or disabled
                return
            
            channel_id = result[0]
        
        # Get the channel
        channel = bot.get_channel(channel_id)
        if not channel:
            return
        
        # Create embed
        embed = discord.Embed(
            title="🔗 Account Link Attempt" if success else "❌ Account Link Failed",
            color=0x53FC18 if success else 0xFF0000,
            timestamp=datetime.now(timezone.utc)
        )
        
        embed.add_field(name="Discord User", value=f"{discord_user.mention} ({discord_user})", inline=False)
        embed.add_field(name="Kick Username", value=kick_username, inline=True)
        embed.add_field(name="Status", value="✅ Success" if success else "❌ Failed", inline=True)
        
        if not success and error_message:
            embed.add_field(name="Error", value=error_message, inline=False)
        
        embed.set_footer(text=f"Discord ID: {discord_user.id}")
        
        await channel.send(embed=embed)
        
    except Exception as e:
        print(f"⚠️ Failed to log link attempt: {e}")

# -------------------------
# Kick chat message sending
# -------------------------
async def get_kick_bot_token() -> Optional[str]:
    """
    Get an OAuth access token for the Kick bot using Client Credentials flow.
    
    Returns:
        str: Access token if successful, None otherwise
    """
    global KICK_BOT_TOKEN
    
    if not KICK_CLIENT_ID or not KICK_CLIENT_SECRET:
        print("[Kick Bot] ⚠️ Client credentials not configured")
        return None
    
    try:
        # Official Kick OAuth token endpoint
        token_url = "https://id.kick.com/oauth/token"
        
        # Must be form-encoded, not JSON
        payload = {
            "grant_type": "client_credentials",
            "client_id": KICK_CLIENT_ID,
            "client_secret": KICK_CLIENT_SECRET
        }
        
        headers = {
            "Content-Type": "application/x-www-form-urlencoded"
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(token_url, data=payload, headers=headers, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    KICK_BOT_TOKEN = data.get("access_token")
                    expires_in = data.get("expires_in", 3600)
                    print(f"[Kick Bot] ✅ Got access token (expires in {expires_in}s)")
                    return KICK_BOT_TOKEN
                else:
                    error_text = await response.text()
                    print(f"[Kick Bot] ❌ Failed to get token (HTTP {response.status}): {error_text}")
                    return None
    
    except Exception as e:
        print(f"[Kick Bot] ❌ Error getting token: {e}")
        return None


# -------------------------
# Kick Chat Messaging
# -------------------------

async def refresh_kick_oauth_token() -> bool:
    """
    Refresh the Kick OAuth token using the refresh_token.
    
    Returns:
        True if token was refreshed successfully, False otherwise
    """
    if not engine:
        print("[Kick] ❌ No database connection for token refresh")
        return False
    
    try:
        # Get refresh token from database
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT refresh_token FROM bot_tokens 
                WHERE bot_username = 'maikelele'
                ORDER BY created_at DESC LIMIT 1
            """)).fetchone()
            
            if not result or not result[0]:
                print("[Kick] ❌ No refresh token available in database")
                return False
            
            refresh_token = result[0]
        
        print(f"[Kick] 🔄 Attempting to refresh OAuth token...")
        
        # Call Kick's token endpoint to refresh
        token_url = "https://id.kick.com/oauth/token"
        token_data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": KICK_CLIENT_ID,
            "client_secret": KICK_CLIENT_SECRET
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(token_url, data=token_data, timeout=10) as response:
                if response.status == 200:
                    token_response = await response.json()
                    new_access_token = token_response.get("access_token")
                    new_refresh_token = token_response.get("refresh_token", refresh_token)
                    expires_in = token_response.get("expires_in", 3600)  # Default to 1 hour
                    
                    if not new_access_token:
                        print("[Kick] ❌ No access_token in refresh response")
                        return False
                    
                    print(f"[Kick] ✅ New token expires in {expires_in} seconds ({expires_in/3600:.1f} hours)")
                    
                    # Calculate expiration time in Python (safer than SQL date math)
                    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
                    
                    # Update tokens in database with expiration time
                    with engine.begin() as conn:
                        conn.execute(text("""
                            UPDATE bot_tokens 
                            SET access_token = :access_token, 
                                refresh_token = :refresh_token,
                                expires_at = :expires_at,
                                created_at = CURRENT_TIMESTAMP
                            WHERE bot_username = 'maikelele'
                        """), {
                            "access_token": new_access_token,
                            "refresh_token": new_refresh_token,
                            "expires_at": expires_at
                        })
                    
                    print(f"[Kick] ✅ OAuth token refreshed successfully!")
                    return True
                else:
                    error_text = await response.text()
                    print(f"[Kick] ❌ Token refresh failed (HTTP {response.status}): {error_text}")
                    return False
    
    except Exception as e:
        print(f"[Kick] ❌ Error refreshing token: {e}")
        import traceback
        traceback.print_exc()
        return False


async def send_kick_message(message: str, retry_count: int = 0) -> bool:
    """
    Send a message to Kick chat using official Chat API with OAuth access token.
    Automatically refreshes token on 401 errors.
    
    Uses the official endpoint: POST https://api.kick.com/public/v1/chat
    Documentation: https://docs.kick.com/apis/chat
    
    Args:
        message: The message to send
        retry_count: Internal counter to prevent infinite retry loops
        
    Returns:
        True if successful, False otherwise
    """
    # Try to load access token from database first
    access_token = None
    if engine:
        try:
            with engine.connect() as conn:
                result = conn.execute(text("""
                    SELECT access_token FROM bot_tokens 
                    WHERE bot_username = 'maikelele'
                    ORDER BY created_at DESC LIMIT 1
                """)).fetchone()
                if result and result[0]:
                    access_token = result[0]
                    print(f"[Kick] ✅ Loaded OAuth token from database: {access_token[:20]}...")
        except Exception as e:
            print(f"[Kick] ⚠️ Could not load token from database: {e}")
    
    # Fall back to environment variable
    if not access_token:
        access_token = KICK_BOT_USER_TOKEN
        if access_token:
            print(f"[Kick] ℹ️  Using OAuth token from environment variable")
    
    if not access_token:
        print("[Kick] ❌ No OAuth access token available")
        print("[Kick] 💡 Owner of maikelele account must authorize at:")
        print(f"[Kick]    https://kick-dicord-bot-test-production.up.railway.app/bot/authorize?token=YOUR_BOT_AUTH_TOKEN")
        return False
    
    # Send message using official Chat API
    try:
        url = "https://api.kick.com/public/v1/chat"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        payload = {
            "content": message,
            "type": "bot"  # When type=bot, message goes to channel attached to token
        }
        
        print(f"[Kick] 📤 Sending message via official Chat API...")
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload, timeout=10) as response:
                response_text = await response.text()
                
                if response.status == 200:
                    try:
                        response_data = json.loads(response_text)
                        message_id = response_data.get("data", {}).get("message_id")
                        print(f"[Kick] ✅ Message sent successfully! ID: {message_id}")
                        return True
                    except json.JSONDecodeError:
                        print(f"[Kick] ✅ Message sent (response: {response_text[:100]})")
                        return True
                
                elif response.status == 401:
                    print(f"[Kick] ❌ 401 Unauthorized: {response_text}")
                    
                    # Try to refresh token automatically (only once)
                    if retry_count == 0:
                        print(f"[Kick] 🔄 Attempting automatic token refresh...")
                        if await refresh_kick_oauth_token():
                            print(f"[Kick] ✅ Token refreshed, retrying message send...")
                            return await send_kick_message(message, retry_count=1)
                        else:
                            print(f"[Kick] ❌ Token refresh failed")
                    
                    print(f"[Kick] 💡 OAuth token expired and refresh failed. Owner of maikelele account must re-authorize at:")
                    print(f"[Kick]    https://kick-dicord-bot-test-production.up.railway.app/bot/authorize?token=YOUR_BOT_AUTH_TOKEN")
                    return False
                
                else:
                    print(f"[Kick] ❌ Failed to send message (HTTP {response.status}): {response_text}")
                    return False
    
    except Exception as e:
        print(f"[Kick] ❌ Error sending message: {e}")
        import traceback
        traceback.print_exc()
        return False


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
    global last_chat_activity, recent_chatters, kick_chatroom_id_global
    
    while True:
        try:
            # Check if chatroom ID is hardcoded in environment (bypass for Cloudflare issues)
            if KICK_CHATROOM_ID:
                chatroom_id = KICK_CHATROOM_ID
                kick_chatroom_id_global = chatroom_id
                print(f"[Kick] Using hardcoded chatroom ID: {chatroom_id}")
            else:
                chatroom_id = await fetch_chatroom_id(channel_name)
                kick_chatroom_id_global = chatroom_id
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
                
                # Initialize last_chat_activity to assume stream is live when we connect
                last_chat_activity = datetime.now(timezone.utc)
                print(f"[Kick] Initialized chat activity tracking")

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
                                now = datetime.now(timezone.utc)
                                last_chat_activity = now  # Update stream activity
                                
                                event_data = json.loads(data.get("data", "{}"))
                                sender = event_data.get("sender", {})
                                username = sender.get("username")
                                
                                if username:
                                    username_lower = username.lower()
                                    # Only log if this is a new viewer (first time in active_viewers)
                                    is_new_viewer = username_lower not in active_viewers
                                    active_viewers[username_lower] = now
                                    # 🔒 SECURITY: Track unique chatters for stream-live detection
                                    recent_chatters[username_lower] = now
                                    content_text = event_data.get("content", "")
                                    print(f"[Kick] {username}: {content_text}")
                                    if watchtime_debug_enabled and is_new_viewer:
                                        print(f"[Watchtime Debug] New viewer: {username_lower} (total: {len(active_viewers)})")
                                    
                                    # Handle slot call commands (!call or !sr)
                                    content_stripped = content_text.strip()
                                    if slot_call_tracker and (content_stripped.startswith("!call") or content_stripped.startswith("!sr")):
                                        # Extract the slot call (everything after "!call " or "!sr ")
                                        # 🔒 SECURITY: Limit length to prevent abuse (200 chars max)
                                        if content_stripped.startswith("!call"):
                                            slot_call = content_stripped[5:].strip()[:200]  # Remove "!call"
                                        else:  # !sr
                                            slot_call = content_stripped[3:].strip()[:200]  # Remove "!sr"
                                        
                                        if slot_call:  # Only process if there's actually a call
                                            await slot_call_tracker.handle_slot_call(username, slot_call)
                            
                            # Handle gifted subscription events
                            # Kick may use different event types for gifts, so we check multiple possibilities
                            if event_type in [
                                "App\\Events\\GiftedSubscriptionsEvent",
                                "App\\Events\\SubscriptionEvent",
                                "App\\Events\\ChatMessageEvent"  # Sometimes gifts come as special chat messages
                            ]:
                                event_data = json.loads(data.get("data", "{}"))
                                
                                # Check if this is a gifted sub (might be in message type or metadata)
                                message_type = event_data.get("type")
                                is_gift = (
                                    "gift" in str(message_type).lower() or
                                    "subscription" in str(message_type).lower() or
                                    event_data.get("gifted_usernames") is not None or
                                    event_data.get("gift_count") is not None
                                )
                                
                                if is_gift and gifted_sub_tracker:
                                    # Handle the gifted sub event
                                    result = await gifted_sub_tracker.handle_gifted_sub_event(event_data)
                                    
                                    if result['status'] == 'success':
                                        print(f"[Raffle] 🎁 {result['gifter']} gifted {result['gift_count']} sub(s) → +{result['tickets_awarded']} tickets")
                                    elif result['status'] == 'not_linked':
                                        print(f"[Raffle] 🎁 {result['kick_name']} gifted sub(s) but account not linked")
                                    elif result['status'] == 'duplicate':
                                        # Already processed, silent skip
                                        pass
                                    else:
                                        print(f"[Raffle] ⚠️ Failed to process gifted sub: {result}")
                                    
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
        if watchtime_debug_enabled:
            print(f"[Watchtime Debug] Task running - tracking enabled: {stream_tracking_enabled}")
        
        # Check if tracking is enabled by admin
        if not stream_tracking_enabled:
            return
        
        now = datetime.now(timezone.utc)
        
        # 🔒 SECURITY: Multi-factor stream-live detection
        # Require multiple unique chatters to prevent single-user farming
        if not tracking_force_override:
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
                print("[Security] Tip: Use '!tracking force on' to override if stream has low chat activity")
                return
            
            print(f"[Security] ✅ Stream appears live: {unique_chatter_count} unique chatters in last {CHAT_ACTIVITY_WINDOW_MINUTES} min")
        else:
            print("[Security] Force override enabled - skipping multi-factor live detection")
        
        cutoff = now - timedelta(minutes=5)
        
        # Get active viewers who were seen recently
        active_users = {
            user: last_seen 
            for user, last_seen in list(active_viewers.items())
            if last_seen and last_seen >= cutoff
        }
        
        if watchtime_debug_enabled:
            print(f"[Watchtime Debug] Total tracked viewers: {len(active_viewers)}, Active in last 5min: {len(active_users)}")
        
        if not active_users:
            if watchtime_debug_enabled:
                print("[Watchtime Debug] No active users found to update (users must chat to be tracked)")
            return  # No active users to update
            
        if watchtime_debug_enabled:
            print(f"[Watchtime Debug] Updating watchtime for {len(active_users)} active user(s): {list(active_users.keys())}")
            
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
                        existing_minutes, last_active = daily_check
                        # PostgreSQL returns datetime objects directly
                        if last_active is None:
                            last_active = today_start
                        else:
                            # Ensure timezone-aware comparison
                            if last_active.tzinfo is None:
                                last_active = last_active.replace(tzinfo=timezone.utc)
                        
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
                    if watchtime_debug_enabled:
                        print(f"[Watchtime Debug] ✅ Updated {user}: +{minutes_to_add} minutes")
                except Exception as e:
                    print(f"⚠️ Error updating watchtime for {user}: {e}")
                    continue  # Skip this user but continue with others
                    
    except Exception as e:
        print(f"⚠️ Error in watchtime update task: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if watchtime_debug_enabled:
            print(f"[Watchtime Debug] Task iteration complete, will run again in {WATCH_INTERVAL_SECONDS}s")

@update_watchtime_task.before_loop
async def before_watchtime_task():
    """Wait for bot to be ready before starting watchtime updates."""
    await bot.wait_until_ready()
    if watchtime_debug_enabled:
        print("[Watchtime Debug] Watchtime task waiting for bot ready - complete")

@update_watchtime_task.error
async def update_watchtime_task_error(error):
    """Handle errors in the watchtime task loop."""
    print(f"❌ Watchtime task encountered an error: {error}")
    import traceback
    traceback.print_exc()

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
            
        # Load current role configuration from database
        current_roles = load_watchtime_roles()
        
        # Cache role objects and validate they exist
        role_cache = {}
        for role_info in current_roles:
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
        for role_info in current_roles:
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
                    # Check if this is a failed attempt (kick_username starts with "FAILED:")
                    is_failed = kick_username.startswith("FAILED:")
                    actual_kick_username = None
                    error_message = None
                    
                    if is_failed:
                        # Parse failed attempt: "FAILED:<username>:<error>"
                        parts = kick_username.split(":", 2)
                        actual_kick_username = parts[1] if len(parts) > 1 else "unknown"
                        error_type = parts[2] if len(parts) > 2 else "unknown_error"
                        
                        if error_type == "already_linked":
                            error_message = "This Kick account is already linked to another Discord user"
                        else:
                            error_message = f"Error: {error_type}"
                    else:
                        actual_kick_username = kick_username
                    
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
                        if is_failed:
                            # Send failure message via DM
                            try:
                                await user.send(f"❌ **Link Failed**\n\n{error_message}\n\nKick account: **{actual_kick_username}**")
                            except discord.Forbidden:
                                pass  # User has DMs disabled
                            
                            # Log the failed attempt
                            await log_link_attempt(user, actual_kick_username, success=False, error_message=error_message)
                        else:
                            # Send success message via DM
                            try:
                                await user.send(f"✅ **Verification Successful!**\n\nYour Discord account has been linked to Kick account **{actual_kick_username}**.")
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
                                                await target_channel.send(f"{member.mention} ✅ **Verification Successful!** Your account has been linked to Kick **{actual_kick_username}**.")
                            
                            # Log the successful link attempt
                            await log_link_attempt(user, actual_kick_username, success=True)
                    
                    # Mark as processed
                    conn.execute(text("""
                        UPDATE oauth_notifications 
                        SET processed = TRUE 
                        WHERE id = :id
                    """), {"id": notification_id})
                    
                    print(f"✅ Sent OAuth notification to Discord {discord_id}", flush=True)
                    
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
@tasks.loop(minutes=30)  # Check every 30 minutes for faster response
async def proactive_token_refresh_task():
    """Proactively refresh OAuth token before it expires."""
    if not engine:
        return
    
    try:
        # Check if token will expire soon
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT expires_at, bot_username FROM bot_tokens 
                WHERE bot_username = 'maikelele'
                ORDER BY created_at DESC LIMIT 1
            """)).fetchone()
            
            if not result:
                return
            
            expires_at, bot_username = result
            
            if not expires_at:
                print("[Kick] ⚠️  No expiration time stored - token will refresh on-demand")
                return
            
            # Make expires_at timezone-aware if it isn't already
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            
            now = datetime.now(timezone.utc)
            time_until_expiry = expires_at - now
            minutes_until_expiry = time_until_expiry.total_seconds() / 60
            
            # Refresh if token expires in less than 30 minutes (very aggressive)
            # This ensures we always have a valid token
            if minutes_until_expiry < 30:
                print(f"[Kick] ⚠️  Token expires in {minutes_until_expiry:.1f} minutes - refreshing proactively...")
                if await refresh_kick_oauth_token():
                    print(f"[Kick] ✅ Proactive token refresh successful!")
                else:
                    print(f"[Kick] ❌ Proactive token refresh failed - will retry on next cycle")
            elif minutes_until_expiry < 120:
                # Warn if getting close
                print(f"[Kick] ⚠️  Token expires in {minutes_until_expiry:.1f} minutes")
            else:
                # Only log occasionally to avoid spam
                hours = minutes_until_expiry / 60
                print(f"[Kick] ✓ Token valid for {hours:.1f} more hours")
    
    except Exception as e:
        print(f"[Kick] ❌ Error in proactive token refresh: {e}")
        import traceback
        traceback.print_exc()

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

@bot.command(name="link")
@progressive_cooldown(base_seconds=10, increment_seconds=10, max_seconds=60)
@in_guild()
async def cmd_link(ctx):
    """Link your Kick account using OAuth (instant, no bio editing required)."""
    
    if not OAUTH_BASE_URL or not KICK_CLIENT_ID:
        await ctx.send("❌ OAuth linking is not configured on this bot.")
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
    
    # Generate cryptographically signed OAuth URL
    oauth_url = generate_signed_oauth_url(discord_id)
    
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
    
    # Load current role configuration
    current_roles = load_watchtime_roles()
    
    # Check which roles they've earned
    earned_roles = []
    for role_info in current_roles:
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
        for role_info in current_roles:
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
async def toggle_tracking(ctx, action: str = None, subaction: str = None):
    """
    Admin command to control watchtime tracking.
    Usage: !tracking on|off|status
           !tracking force on|off|status
           !tracking debug on|off|status
    """
    global stream_tracking_enabled, tracking_force_override, watchtime_debug_enabled
    
    # Support a force subcommand: !tracking force on|off|status
    if action is None or action.lower() == "status":
        status = "🟢 ENABLED" if stream_tracking_enabled else "🔴 DISABLED"
        force_status = "🟢 FORCE ON" if tracking_force_override else "🔴 FORCE OFF"
        debug_status = "🟢 DEBUG ON" if watchtime_debug_enabled else "🔴 DEBUG OFF"
        await ctx.send(f"**Watchtime Tracking Status:** {status}\n**Force override:** {force_status}\n**Debug logging:** {debug_status}")
        return

    if action.lower() == "on":
        stream_tracking_enabled = True
        await ctx.send("✅ **Watchtime tracking ENABLED**\nUsers will now earn watchtime from chat activity.")
    elif action.lower() == "off":
        stream_tracking_enabled = False
        await ctx.send("⏸️ **Watchtime tracking DISABLED**\nUsers will NOT earn watchtime until re-enabled.")
    elif action.lower() == "force":
        if subaction is None or subaction.lower() == "status":
            force_status = "🟢 FORCE ON" if tracking_force_override else "🔴 FORCE OFF"
            await ctx.send(f"**Force override:** {force_status}")
            return
        
        if subaction.lower() == "on":
            tracking_force_override = True
            # Save to database
            with engine.begin() as conn:
                conn.execute(text("""
                    INSERT INTO bot_settings (key, value, updated_at)
                    VALUES ('tracking_force_override', 'true', CURRENT_TIMESTAMP)
                    ON CONFLICT (key) DO UPDATE SET 
                        value = 'true',
                        updated_at = CURRENT_TIMESTAMP
                """))
            await ctx.send("🔒 **Watchtime FORCE override ENABLED**\nWatchtime updates will run regardless of live-detection checks.")
        elif subaction.lower() == "off":
            tracking_force_override = False
            # Save to database
            with engine.begin() as conn:
                conn.execute(text("""
                    INSERT INTO bot_settings (key, value, updated_at)
                    VALUES ('tracking_force_override', 'false', CURRENT_TIMESTAMP)
                    ON CONFLICT (key) DO UPDATE SET 
                        value = 'false',
                        updated_at = CURRENT_TIMESTAMP
                """))
            await ctx.send("🔓 **Watchtime FORCE override DISABLED**\nLive-detection checks will be enforced again.")
        else:
            await ctx.send("❌ Invalid force option. Use: `!tracking force on` or `!tracking force off` or `!tracking force status`")
    elif action.lower() == "debug":
        if subaction is None or subaction.lower() == "status":
            debug_status = "🟢 DEBUG ON" if watchtime_debug_enabled else "🔴 DEBUG OFF"
            await ctx.send(f"**Debug logging:** {debug_status}")
            return
        
        if subaction.lower() == "on":
            watchtime_debug_enabled = True
            await ctx.send("🐛 **Watchtime DEBUG logging ENABLED**\nDetailed debug messages will appear in logs.")
        elif subaction.lower() == "off":
            watchtime_debug_enabled = False
            await ctx.send("🔇 **Watchtime DEBUG logging DISABLED**\nDebug messages will be suppressed.")
        else:
            await ctx.send("❌ Invalid debug option. Use: `!tracking debug on` or `!tracking debug off` or `!tracking debug status`")
    else:
        await ctx.send("❌ Invalid option. Use: `!tracking on`, `!tracking off`, `!tracking status`, or `!tracking force/debug ...`")

@toggle_tracking.error
async def tracking_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ You need administrator permissions to use this command.")

@bot.command(name="linklogs")
@commands.has_permissions(administrator=True)
@in_guild()
async def link_logs_toggle(ctx, action: str = None):
    """
    Admin command to configure link attempt logging to Discord channel.
    Usage: !linklogs on|off|status
    
    When enabled, all account linking attempts (successful and failed) will be logged
    to the channel where this command is run.
    """
    guild_id = ctx.guild.id
    channel_id = ctx.channel.id
    
    if action is None or action.lower() == "status":
        # Check current status
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT channel_id, enabled FROM link_logs_config 
                WHERE guild_id = :guild_id
            """), {"guild_id": guild_id}).fetchone()
            
            if not result:
                await ctx.send("📊 **Link Logging Status:** 🔴 NOT CONFIGURED\nUse `!linklogs on` to enable logging in this channel.")
                return
            
            log_channel = bot.get_channel(result[0])
            status = "🟢 ENABLED" if result[1] else "🔴 DISABLED"
            channel_mention = log_channel.mention if log_channel else f"<#{result[0]}>"
            await ctx.send(f"📊 **Link Logging Status:** {status}\n**Log Channel:** {channel_mention}")
            return
    
    if action.lower() == "on":
        # Enable logging in current channel
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO link_logs_config (guild_id, channel_id, enabled, updated_at)
                VALUES (:guild_id, :channel_id, TRUE, CURRENT_TIMESTAMP)
                ON CONFLICT (guild_id) DO UPDATE SET
                    channel_id = :channel_id,
                    enabled = TRUE,
                    updated_at = CURRENT_TIMESTAMP
            """), {"guild_id": guild_id, "channel_id": channel_id})
        
        await ctx.send(
            f"✅ **Link logging ENABLED** in {ctx.channel.mention}\n\n"
            f"All account linking attempts will be logged here with:\n"
            f"• Discord user attempting to link\n"
            f"• Success/failure status\n"
            f"• Kick username\n"
            f"• Timestamp\n\n"
            f"Use `!linklogs off` to disable logging."
        )
    
    elif action.lower() == "off":
        # Disable logging
        with engine.begin() as conn:
            conn.execute(text("""
                UPDATE link_logs_config 
                SET enabled = FALSE, updated_at = CURRENT_TIMESTAMP
                WHERE guild_id = :guild_id
            """), {"guild_id": guild_id})
        
        await ctx.send("⏸️ **Link logging DISABLED**\nAccount linking attempts will no longer be logged.")
    
    else:
        await ctx.send("❌ Invalid option. Use: `!linklogs on`, `!linklogs off`, or `!linklogs status`")

@link_logs_toggle.error
async def link_logs_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ You need administrator permissions to use this command.")

@bot.command(name="roles")
@commands.has_permissions(administrator=True)
@in_guild()
async def manage_roles(ctx, action: str = None, role_name: str = None, minutes: int = None):
    """
    Admin command to manage watchtime role thresholds.
    Usage:
      !roles list - Show current role configuration
      !roles add <role_name> <minutes> - Add a new role threshold
      !roles update <role_name> <minutes> - Update existing role threshold
      !roles remove <role_name> - Remove a role threshold
      !roles enable <role_name> - Enable a role
      !roles disable <role_name> - Disable a role
    
    Example: !roles add "Tier 4" 5000
    """
    
    if action is None or action.lower() == "list":
        # Show current configuration
        with engine.connect() as conn:
            roles = conn.execute(text("""
                SELECT role_name, minutes_required, enabled, display_order
                FROM watchtime_roles
                ORDER BY display_order ASC
            """)).fetchall()
        
        if not roles:
            await ctx.send("📋 No roles configured.")
            return
        
        embed = discord.Embed(
            title="🎯 Watchtime Role Configuration",
            description="Current role thresholds for automatic role assignment",
            color=0x53FC18
        )
        
        for role_name, minutes, enabled, order in roles:
            hours = minutes / 60
            status = "✅ Enabled" if enabled else "❌ Disabled"
            embed.add_field(
                name=f"{order}. {role_name}",
                value=f"**{minutes:,} minutes** ({hours:.1f} hours)\n{status}",
                inline=False
            )
        
        embed.set_footer(text="Use !roles add/update/remove to modify • Changes take effect immediately")
        await ctx.send(embed=embed)
        return
    
    if action.lower() == "add":
        if not role_name or minutes is None:
            await ctx.send("❌ Usage: `!roles add <role_name> <minutes>`\nExample: `!roles add \"Tier 4\" 5000`")
            return
        
        try:
            with engine.begin() as conn:
                # Get highest display order
                max_order = conn.execute(text("SELECT COALESCE(MAX(display_order), 0) FROM watchtime_roles")).fetchone()[0]
                
                # Insert new role
                conn.execute(text("""
                    INSERT INTO watchtime_roles (role_name, minutes_required, display_order, enabled)
                    VALUES (:name, :minutes, :order, TRUE)
                """), {"name": role_name, "minutes": minutes, "order": max_order + 1})
            
            await ctx.send(f"✅ Added role **{role_name}** at **{minutes:,} minutes** ({minutes/60:.1f} hours)")
        except Exception as e:
            await ctx.send(f"❌ Error adding role: {e}")
    
    elif action.lower() == "update":
        if not role_name or minutes is None:
            await ctx.send("❌ Usage: `!roles update <role_name> <minutes>`\nExample: `!roles update \"Tier 1\" 180`")
            return
        
        try:
            with engine.begin() as conn:
                result = conn.execute(text("""
                    UPDATE watchtime_roles
                    SET minutes_required = :minutes, updated_at = CURRENT_TIMESTAMP
                    WHERE role_name = :name
                    RETURNING id
                """), {"name": role_name, "minutes": minutes}).fetchone()
                
                if not result:
                    await ctx.send(f"❌ Role **{role_name}** not found.")
                    return
            
            await ctx.send(f"✅ Updated **{role_name}** to **{minutes:,} minutes** ({minutes/60:.1f} hours)")
        except Exception as e:
            await ctx.send(f"❌ Error updating role: {e}")
    
    elif action.lower() == "remove":
        if not role_name:
            await ctx.send("❌ Usage: `!roles remove <role_name>`\nExample: `!roles remove \"Tier 4\"`")
            return
        
        try:
            with engine.begin() as conn:
                result = conn.execute(text("""
                    DELETE FROM watchtime_roles
                    WHERE role_name = :name
                    RETURNING id
                """), {"name": role_name}).fetchone()
                
                if not result:
                    await ctx.send(f"❌ Role **{role_name}** not found.")
                    return
            
            await ctx.send(f"✅ Removed role **{role_name}** from configuration")
        except Exception as e:
            await ctx.send(f"❌ Error removing role: {e}")
    
    elif action.lower() in ["enable", "disable"]:
        if not role_name:
            await ctx.send(f"❌ Usage: `!roles {action} <role_name>`")
            return
        
        enabled = action.lower() == "enable"
        try:
            with engine.begin() as conn:
                result = conn.execute(text("""
                    UPDATE watchtime_roles
                    SET enabled = :enabled, updated_at = CURRENT_TIMESTAMP
                    WHERE role_name = :name
                    RETURNING id
                """), {"name": role_name, "enabled": enabled}).fetchone()
                
                if not result:
                    await ctx.send(f"❌ Role **{role_name}** not found.")
                    return
            
            status = "enabled" if enabled else "disabled"
            await ctx.send(f"✅ Role **{role_name}** {status}")
        except Exception as e:
            await ctx.send(f"❌ Error updating role: {e}")
    
    elif action.lower() == "members":
        if not role_name:
            await ctx.send("❌ Usage: `!roles members <role_name>`\nExample: `!roles members \"Tier 1\"`")
            return
        
        # Find the Discord role
        role = discord.utils.get(ctx.guild.roles, name=role_name)
        if not role:
            await ctx.send(f"❌ Discord role **{role_name}** not found in this server.")
            return
        
        # Get members with this role
        members = role.members
        
        if not members:
            await ctx.send(f"📋 No members have the **{role_name}** role yet.")
            return
        
        # Get watchtime for linked members only
        member_list = []
        linked_count = 0
        with engine.connect() as conn:
            for member in members[:50]:  # Check up to 50, but only show linked ones
                # Try to get their watchtime
                link = conn.execute(text(
                    "SELECT kick_name FROM links WHERE discord_id = :d"
                ), {"d": member.id}).fetchone()
                
                if link:  # Only add linked members
                    linked_count += 1
                    kick_name = link[0]
                    watchtime = conn.execute(text(
                        "SELECT minutes FROM watchtime WHERE username = :u"
                    ), {"u": kick_name}).fetchone()
                    
                    if watchtime:
                        minutes = watchtime[0]
                        hours = minutes / 60
                        member_list.append(f"• {member.mention} - **{kick_name}** ({minutes:,} min / {hours:.1f}h)")
                    else:
                        member_list.append(f"• {member.mention} - **{kick_name}** (0 min)")
                    
                    # Stop if we have 25 linked members
                    if linked_count >= 25:
                        break
        
        if not member_list:
            await ctx.send(f"📋 No linked members have the **{role_name}** role yet.")
            return
        
        # Create embed
        embed = discord.Embed(
            title=f"👥 Linked Members with {role_name}",
            description=f"Showing **{len(member_list)}** linked member{'s' if len(member_list) != 1 else ''} (Total with role: {len(members)})",
            color=role.color if role.color != discord.Color.default() else 0x53FC18
        )
        
        # Split into chunks if too many
        chunk_size = 20
        for i in range(0, len(member_list), chunk_size):
            chunk = member_list[i:i+chunk_size]
            embed.add_field(
                name=f"Members {i+1}-{min(i+chunk_size, len(member_list))}" if len(member_list) > chunk_size else "Members",
                value="\n".join(chunk),
                inline=False
            )
        
        if linked_count >= 25 and len(members) > linked_count:
            embed.set_footer(text=f"Showing first 25 linked members • {len(members) - linked_count} unlinked not shown")
        
        await ctx.send(embed=embed)
    
    else:
        await ctx.send(
            "❌ Invalid action. Available actions:\n"
            "• `!roles list` - Show current roles\n"
            "• `!roles add <name> <minutes>` - Add new role\n"
            "• `!roles update <name> <minutes>` - Update role threshold\n"
            "• `!roles remove <name>` - Remove role\n"
            "• `!roles enable/disable <name>` - Enable/disable role\n"
            "• `!roles members <name>` - List members with a role"
        )

@manage_roles.error
async def manage_roles_error(ctx, error):
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

@bot.command(name="post_link_info")
@commands.has_permissions(manage_guild=True)
@in_guild()
async def post_link_info(ctx):
    """
    Admin command to post an informational embed explaining why users should link their accounts.
    Usage: !post_link_info
    
    This creates a detailed explanation of the benefits of linking Kick accounts.
    """
    
    # Create the detailed embed
    embed = discord.Embed(
        title="🔗 Link Your Kick Account to Discord!",
        description="Connect your Kick account to unlock exclusive benefits in Maikelele's community!",
        color=0x53FC18
    )
    
    embed.add_field(
        name="📝 Why Link Your Account?",
        value="** **",  # Spacer
        inline=False
    )
    
    embed.add_field(
        name="🎁 Enter Giveaways",
        value="• Only linked accounts can participate\n• Ensures fair distribution to real viewers\n• No alt accounts allowed",
        inline=False
    )
    
    embed.add_field(
        name="🏆 Automatic Role Rewards",
        value="• Earn roles based on Kick chat activity\n• Get recognized for your watch time",
        inline=False
    )
    
    embed.add_field(
        name="🛡️ Verified Member Status",
        value="• Prove you're a real supporter\n• Stand out in the community\n• Help keep the server authentic",
        inline=False
    )
    
    embed.add_field(
        name="⚡ How to Link (Easy!)",
        value="React with 🔗 on the pinned message above!\n\n1. Click the 🔗 reaction\n2. Check your DMs for a secure link\n3. Authorize with your Kick account\n4. Done! Your accounts are now linked\n\n*Note: Contact an admin if you need to unlink*",
        inline=False
    )
    
    embed.set_footer(text="🔒 Your data is secure • Takes less than 30 seconds")
    
    # Send the embed
    await ctx.send(embed=embed)
    
    # Delete the command message to keep the channel clean
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass  # If we can't delete, no big deal
    except discord.HTTPException:
        pass

@post_link_info.error
async def post_link_info_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ You need 'Manage Server' permission to use this command.")

@bot.command(name="health")
@commands.has_permissions(manage_guild=True)
@in_guild()
async def health_check(ctx):
    """
    Admin command to check if all bot systems are functioning correctly.
    Usage: !health
    
    Checks:
    - Discord connection
    - Database connection
    - Kick API accessibility
    - OAuth configuration
    - Background tasks status
    - WebSocket connection
    """
    
    embed = discord.Embed(
        title="🏥 System Health Check",
        description="Checking all bot systems...",
        color=0x3498db
    )
    
    status_msg = await ctx.send(embed=embed)
    
    checks = []
    overall_status = "✅ All Systems Operational"
    has_warnings = False
    has_errors = False
    
    # 1. Discord Connection
    try:
        latency_ms = round(bot.latency * 1000, 2)
        if latency_ms < 200:
            checks.append(f"✅ **Discord Connection**: {latency_ms}ms")
        elif latency_ms < 500:
            checks.append(f"⚠️ **Discord Connection**: {latency_ms}ms (Slow)")
            has_warnings = True
        else:
            checks.append(f"❌ **Discord Connection**: {latency_ms}ms (Very Slow)")
            has_errors = True
    except Exception as e:
        checks.append(f"❌ **Discord Connection**: Error - {str(e)}")
        has_errors = True
    
    # 2. Database Connection
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            result.fetchone()
        db_type = "PostgreSQL" if "postgresql" in DATABASE_URL else "SQLite"
        checks.append(f"✅ **Database Connection**: {db_type} OK")
    except Exception as e:
        checks.append(f"❌ **Database Connection**: {str(e)[:50]}")
        has_errors = True
    
    # 3. Kick API Check
    try:
        if KICK_CHATROOM_ID:
            checks.append(f"✅ **Kick Chatroom ID**: Configured ({KICK_CHATROOM_ID})")
        else:
            chatroom_id = await asyncio.to_thread(fetch_chatroom_id, KICK_CHANNEL)
            if chatroom_id:
                checks.append(f"✅ **Kick API**: Accessible (ID: {chatroom_id})")
            else:
                checks.append(f"⚠️ **Kick API**: Could not fetch chatroom ID")
                has_warnings = True
    except Exception as e:
        checks.append(f"❌ **Kick API**: {str(e)[:50]}")
        has_errors = True
    
    # 4. OAuth Configuration
    oauth_checks = []
    if OAUTH_BASE_URL:
        oauth_checks.append("✅ Base URL configured")
    else:
        oauth_checks.append("❌ Base URL missing")
        has_errors = True
    
    if KICK_CLIENT_ID:
        oauth_checks.append("✅ Client ID configured")
    else:
        oauth_checks.append("❌ Client ID missing")
        has_errors = True
    
    if OAUTH_SECRET_KEY:
        oauth_checks.append("✅ Secret key configured")
    else:
        oauth_checks.append("❌ Secret key missing")
        has_errors = True
    
    oauth_status = " | ".join(oauth_checks)
    checks.append(f"**OAuth Config**: {oauth_status}")
    
    # 5. Background Tasks
    task_statuses = []
    
    if update_watchtime_task.is_running():
        task_statuses.append("✅ Watchtime tracker")
    else:
        task_statuses.append("❌ Watchtime tracker")
        has_errors = True
    
    if update_roles_task.is_running():
        task_statuses.append("✅ Role updater")
    else:
        task_statuses.append("❌ Role updater")
        has_errors = True
    
    if check_oauth_notifications_task.is_running():
        task_statuses.append("✅ OAuth checker")
    else:
        task_statuses.append("❌ OAuth checker")
        has_errors = True
    
    if cleanup_pending_links_task.is_running():
        task_statuses.append("✅ Cleanup task")
    else:
        task_statuses.append("❌ Cleanup task")
        has_errors = True
    
    checks.append(f"**Background Tasks**: {' | '.join(task_statuses)}")
    
    # 6. Database Tables Check
    try:
        with engine.connect() as conn:
            tables_check = []
            
            # Check watchtime table
            result = conn.execute(text("SELECT COUNT(*) FROM watchtime"))
            watchtime_count = result.fetchone()[0]
            tables_check.append(f"{watchtime_count} viewers")
            
            # Check links table
            result = conn.execute(text("SELECT COUNT(*) FROM links"))
            links_count = result.fetchone()[0]
            tables_check.append(f"{links_count} linked accounts")
            
            # Check watchtime_roles table
            result = conn.execute(text("SELECT COUNT(*) FROM watchtime_roles WHERE enabled = true"))
            roles_count = result.fetchone()[0]
            tables_check.append(f"{roles_count} active roles")
            
            checks.append(f"✅ **Database Stats**: {' | '.join(tables_check)}")
    except Exception as e:
        checks.append(f"⚠️ **Database Stats**: {str(e)[:50]}")
        has_warnings = True
    
    # 7. WebSocket Status
    if hasattr(bot, 'ws') and bot.ws:
        checks.append(f"✅ **WebSocket**: Connected")
    else:
        checks.append(f"⚠️ **WebSocket**: Not connected")
        has_warnings = True
    
    # 8. Uptime
    if hasattr(bot, 'uptime_start'):
        uptime = datetime.now() - bot.uptime_start
        hours, remainder = divmod(int(uptime.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        checks.append(f"⏱️ **Uptime**: {hours}h {minutes}m {seconds}s")
    
    # Determine overall status
    if has_errors:
        overall_status = "❌ System Issues Detected"
        color = 0xe74c3c  # Red
    elif has_warnings:
        overall_status = "⚠️ System Operational with Warnings"
        color = 0xf39c12  # Orange
    else:
        overall_status = "✅ All Systems Operational"
        color = 0x2ecc71  # Green
    
    # Update embed
    embed = discord.Embed(
        title="🏥 System Health Check",
        description=overall_status,
        color=color,
        timestamp=datetime.now()
    )
    
    for check in checks:
        embed.add_field(name="\u200b", value=check, inline=False)
    
    embed.set_footer(text=f"Requested by {ctx.author.display_name}")
    
    await status_msg.edit(embed=embed)

@health_check.error
async def health_check_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ You need 'Manage Server' permission to use this command.")

# -------------------------
# Helper Functions
# -------------------------
async def sync_shuffle_role_on_startup(bot, engine):
    """Sync Shuffle Code User role with verified links on bot startup"""
    try:
        # Get the guild
        if not DISCORD_GUILD_ID:
            return
        
        guild = bot.get_guild(DISCORD_GUILD_ID)
        if not guild:
            return
        
        # Get the "Shuffle Code User" role
        shuffle_role = discord.utils.get(guild.roles, name="Shuffle Code User")
        if not shuffle_role:
            print("⚠️ 'Shuffle Code User' role not found - skipping sync")
            return
        
        # Get all verified Shuffle links
        with engine.begin() as conn:
            result = conn.execute(text("""
                SELECT DISTINCT discord_id
                FROM raffle_shuffle_links
                WHERE verified = TRUE
            """))
            verified_discord_ids = {row[0] for row in result.fetchall()}
        
        added = 0
        removed = 0
        
        # Remove role from users without verified links
        members_with_role = shuffle_role.members
        for member in members_with_role:
            if member.id not in verified_discord_ids:
                try:
                    await member.remove_roles(shuffle_role, reason="Startup sync: No verified Shuffle link")
                    removed += 1
                except Exception as e:
                    print(f"⚠️ Could not remove Shuffle role from {member}: {e}")
        
        # Add role to verified users who don't have it
        for discord_id in verified_discord_ids:
            member = guild.get_member(discord_id)
            if member and shuffle_role not in member.roles:
                try:
                    await member.add_roles(shuffle_role, reason="Startup sync: Has verified Shuffle link")
                    added += 1
                except Exception as e:
                    print(f"⚠️ Could not add Shuffle role to {member}: {e}")
        
        if added > 0 or removed > 0:
            print(f"✅ Shuffle role sync: +{added}, -{removed}")
        
    except Exception as e:
        print(f"⚠️ Error syncing Shuffle roles on startup: {e}")

# -------------------------
# Bot events
# -------------------------
@bot.event
async def on_ready():
    # Track bot uptime for health checks
    if not hasattr(bot, 'uptime_start'):
        bot.uptime_start = datetime.now()
    
    print(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")
    print(f"📺 Monitoring Kick channel: {KICK_CHANNEL}")
    
    # Attach helper function to bot so other cogs can access it
    bot.get_active_chatters_count = get_active_chatters_count
    
    # Auto-migrate database: add expires_at column if missing
    if engine:
        try:
            with engine.begin() as conn:
                # Check if expires_at column exists
                result = conn.execute(text("""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name = 'bot_tokens' AND column_name = 'expires_at'
                """)).fetchone()
                
                if not result:
                    print("🔄 Adding expires_at column to bot_tokens table...")
                    conn.execute(text("ALTER TABLE bot_tokens ADD COLUMN expires_at TIMESTAMP"))
                    print("✅ Database migrated: expires_at column added")
        except Exception as e:
            print(f"⚠️ Database migration check failed: {e}")
    
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
            current_roles = load_watchtime_roles()
            existing_roles = {role.name for role in guild.roles}
            for role_config in current_roles:
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
        
        if not proactive_token_refresh_task.is_running() and engine:
            proactive_token_refresh_task.start()
            print("✅ Proactive token refresh task started (runs every 30 minutes)")
        
        if not check_oauth_notifications_task.is_running():
            check_oauth_notifications_task.start()
            print("✅ OAuth notifications task started")
        
        # Initialize raffle system
        try:
            global gifted_sub_tracker, shuffle_tracker, slot_call_tracker
            
            # Setup raffle database (creates tables if needed)
            setup_raffle_database(engine)
            
            # Run migrations
            migrate_add_created_at_to_shuffle_wagers(engine)
            
            # Ensure there's an active raffle period
            current_period = get_current_period(engine)
            if not current_period:
                # Create initial raffle period for this month
                start = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                if start.month == 12:
                    end = start.replace(year=start.year + 1, month=1, day=1) - timedelta(seconds=1)
                else:
                    end = start.replace(month=start.month + 1, day=1) - timedelta(seconds=1)
                
                period_id = create_new_period(engine, start, end)
                print(f"✅ Created initial raffle period #{period_id}")
            else:
                print(f"✅ Active raffle period found (#{current_period['id']})")
            
            # Setup watchtime converter (runs every hour)
            await setup_watchtime_converter(bot, engine)
            
            # Setup gifted sub tracker
            gifted_sub_tracker = setup_gifted_sub_handler(engine)
            
            # Setup Shuffle wager tracker (runs every 15 minutes)
            shuffle_tracker = await setup_shuffle_tracker(bot, engine)
            
            # Setup auto-updating leaderboard (runs every 5 minutes)
            auto_leaderboard = await setup_auto_leaderboard(bot, engine)
            bot.auto_leaderboard = auto_leaderboard  # Store for manual updates
            
            # Setup raffle commands
            await setup_raffle_commands(bot, engine)
            
            # Setup raffle scheduler (monthly reset + auto-draw)
            raffle_auto_draw = os.getenv("RAFFLE_AUTO_DRAW", "false").lower() == "true"
            raffle_channel_id = os.getenv("RAFFLE_ANNOUNCEMENT_CHANNEL_ID")
            raffle_channel_id = int(raffle_channel_id) if raffle_channel_id else None
            
            await setup_raffle_scheduler(
                bot=bot,
                engine=engine,
                auto_draw=raffle_auto_draw,
                announcement_channel_id=raffle_channel_id
            )
            
            print("✅ Raffle system initialized")
            print(f"   • Auto-draw: {raffle_auto_draw}")
            print(f"   • Announcement channel: {raffle_channel_id or 'Not configured'}")
            
            # Sync Shuffle code user role on startup
            await sync_shuffle_role_on_startup(bot, engine)
            
            # Setup slot call tracker with Kick chat callback
            slot_call_tracker = await setup_slot_call_tracker(
                bot, 
                SLOT_CALLS_CHANNEL_ID,
                kick_send_callback=send_kick_message if KICK_BOT_USER_TOKEN else None,
                engine=engine
            )
            if SLOT_CALLS_CHANNEL_ID:
                print(f"✅ Slot call tracker initialized (channel: {SLOT_CALLS_CHANNEL_ID})")
                if KICK_BOT_USER_TOKEN:
                    print(f"✅ Kick chat responses enabled")
                    print(f"   • Using User Access Token with 'chat:write' scope")
                    print(f"   • Make sure bot account follows the channel")
                else:
                    print("ℹ️  Kick chat responses disabled (set KICK_BOT_USER_TOKEN to enable)")
            else:
                print("⚠️ Slot call tracker initialized but no channel configured (set SLOT_CALLS_CHANNEL_ID)")
            
            # Setup slot request panel
            slot_panel = await setup_slot_panel(
                bot,
                engine,
                slot_call_tracker,
                kick_send_callback=send_kick_message if KICK_BOT_USER_TOKEN else None
            )
            print(f"✅ Slot request panel system initialized")
            
            # Setup timed messages system
            timed_messages_manager = await setup_timed_messages(
                bot,
                engine,
                kick_send_callback=send_kick_message if KICK_BOT_USER_TOKEN else None
            )
            if KICK_BOT_USER_TOKEN:
                print(f"✅ Timed messages system initialized ({len(timed_messages_manager.messages)} messages)")
            else:
                print("ℹ️  Timed messages disabled (set KICK_BOT_USER_TOKEN to enable)")
            
        except Exception as e:
            print(f"⚠️ Failed to initialize raffle system: {e}")
            import traceback
            traceback.print_exc()
            
    except Exception as e:
        print(f"⚠️ Error during startup: {e}")

    # Start Kick chat listener
    bot.loop.create_task(kick_chat_loop(KICK_CHANNEL))
    print("✅ Kick chat listener started")

async def handle_timer_panel_reaction(payload):
    """Handle reactions on timer panel messages."""
    from timed_messages import TimedMessagesManager
    
    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return
    
    member = guild.get_member(payload.user_id)
    if not member:
        return
    
    # Check admin permissions
    if not member.guild_permissions.administrator:
        channel = bot.get_channel(payload.channel_id)
        if channel:
            await channel.send(
                f"❌ {member.mention} Only administrators can use the timer panel!",
                delete_after=5
            )
        # Remove reaction
        try:
            message = await channel.fetch_message(payload.message_id)
            await message.remove_reaction(payload.emoji, member)
        except:
            pass
        return
    
    reaction_emoji = str(payload.emoji)
    channel = bot.get_channel(payload.channel_id)
    if not channel:
        return
    
    # Refresh the panel
    message = await channel.fetch_message(payload.message_id)
    
    # Get timer manager
    manager = TimedMessagesManager(engine)
    messages = manager.list_messages()
    
    # Handle different reactions
    if reaction_emoji == "":  # Refresh panel
        embed = discord.Embed(
            title="⏰ Timed Messages Control Panel",
            description="React to this message to manage timers:\n\n"
                       " - Refresh panel\n"
                       "📋 - Show list of timers\n"
                       "❌ - Disable timer (will ask for ID)\n"
                       "✅ - Enable timer (will ask for ID)",
            color=discord.Color.blue(),
            timestamp=datetime.utcnow()
        )
        
        if not messages:
            embed.add_field(
                name="📭 No Timers",
                value="Use `!addtimer <minutes> <message>` to create one!",
                inline=False
            )
        else:
            enabled_count = sum(1 for m in messages if m.enabled)
            disabled_count = len(messages) - enabled_count
            
            summary = f"**Total:** {len(messages)} timer(s)\n"
            summary += f"✅ **Enabled:** {enabled_count}\n"
            summary += f"❌ **Disabled:** {disabled_count}"
            
            embed.add_field(name="📊 Summary", value=summary, inline=False)
            
            for i, msg in enumerate(messages[:10], 1):
                status_emoji = "✅" if msg.enabled else "❌"
                last_sent = msg.last_sent.strftime('%H:%M') if msg.last_sent else "Never"
                
                if msg.enabled and msg.last_sent:
                    next_send = msg.last_sent + timedelta(minutes=msg.interval_minutes)
                    time_until = next_send - datetime.utcnow()
                    if time_until.total_seconds() > 0:
                        minutes_left = int(time_until.total_seconds() / 60)
                        next_info = f"in {minutes_left}m"
                    else:
                        next_info = "due now"
                else:
                    next_info = "waiting"
                
                field_value = (
                    f"{status_emoji} **ID:** {msg.message_id} | **Every:** {msg.interval_minutes}m | **Next:** {next_info}\n"
                    f"💬 {msg.message[:60]}{'...' if len(msg.message) > 60 else ''}"
                )
                
                embed.add_field(name=f"Timer #{i}", value=field_value, inline=False)
            
            if len(messages) > 10:
                embed.add_field(
                    name="ℹ️ More Timers",
                    value=f"Showing 10 of {len(messages)}. Use `!listtimers` to see all.",
                    inline=False
                )
        
        embed.add_field(
            name="📝 Commands",
            value=(
                "`!addtimer <min> <msg>` • `!removetimer <id>`\n"
                "`!toggletimer <id> on/off` • `!updatetimer <id> <min>`"
            ),
            inline=False
        )
        embed.set_footer(text=f"Checks every 1 minute • React to manage")
        
        await message.edit(embed=embed)
        
    elif reaction_emoji == "📋":  # Show list of timers
        embed = discord.Embed(
            title="📋 All Timers",
            color=discord.Color.blue(),
            timestamp=datetime.utcnow()
        )
        
        if not messages:
            embed.description = "No timers configured"
        else:
            for msg in messages[:20]:  # Show up to 20
                status_emoji = "✅" if msg.enabled else "❌"
                last_sent = msg.last_sent.strftime('%H:%M') if msg.last_sent else "Never"
                
                if msg.enabled and msg.last_sent:
                    next_send = msg.last_sent + timedelta(minutes=msg.interval_minutes)
                    time_until = next_send - datetime.utcnow()
                    if time_until.total_seconds() > 0:
                        minutes_left = int(time_until.total_seconds() / 60)
                        next_info = f"in {minutes_left}m"
                    else:
                        next_info = "due now"
                else:
                    next_info = "waiting"
                
                embed.add_field(
                    name=f"{status_emoji} Timer ID: {msg.message_id}",
                    value=f"**Every:** {msg.interval_minutes}m | **Next:** {next_info}\n{msg.message[:80]}{'...' if len(msg.message) > 80 else ''}",
                    inline=False
                )
            
            if len(messages) > 20:
                embed.set_footer(text=f"Showing 20 of {len(messages)} • Use !listtimers to see all • React 🔄 to go back")
            else:
                embed.set_footer(text=f"{len(messages)} total • React  to go back")
        
        await message.edit(embed=embed)
        
    elif reaction_emoji == "❌":  # Disable timer (ask for ID)
        embed = discord.Embed(
            title="❌ Disable Timer",
            description=f"{member.mention}, please reply with the **Timer ID** you want to disable.\n\nYou have 30 seconds to respond.",
            color=discord.Color.red()
        )
        
        if messages:
            enabled = [m for m in messages if m.enabled]
            if enabled:
                timer_list = "\n".join([f"• **ID {m.message_id}**: {m.message[:50]}{'...' if len(m.message) > 50 else ''}" for m in enabled[:10]])
                embed.add_field(name="Enabled Timers:", value=timer_list, inline=False)
            else:
                embed.description = "No enabled timers to disable!"
        
        embed.set_footer(text="Type 'cancel' to cancel")
        await message.edit(embed=embed)
        
        # Wait for user response
        def check(m):
            return m.author.id == member.id and m.channel.id == channel.id
        
        try:
            response = await bot.wait_for('message', timeout=30.0, check=check)
            
            if response.content.lower() == 'cancel':
                await response.delete()
                await channel.send(f"❌ {member.mention} Cancelled.", delete_after=3)
                # Refresh panel
                payload.emoji = "🔄"
                await handle_timer_panel_reaction(payload)
                return
            
            try:
                timer_id = int(response.content)
                await response.delete()
                
                # Find and disable the timer
                timer = next((m for m in messages if m.message_id == timer_id), None)
                if timer:
                    if not timer.enabled:
                        await channel.send(f"ℹ️ {member.mention} Timer {timer_id} is already disabled.", delete_after=5)
                    else:
                        manager.toggle_message(timer_id, False)
                        await channel.send(f"✅ {member.mention} Timer {timer_id} has been **disabled**!", delete_after=5)
                else:
                    await channel.send(f"❌ {member.mention} Timer ID {timer_id} not found.", delete_after=5)
                
            except ValueError:
                await response.delete()
                await channel.send(f"❌ {member.mention} Invalid ID. Please use a number.", delete_after=5)
            
            # Refresh panel
            payload.emoji = "♻️"
            await handle_timer_panel_reaction(payload)
            return
            
        except asyncio.TimeoutError:
            await channel.send(f"⏰ {member.mention} Timed out. Please try again.", delete_after=5)
            # Refresh panel
            payload.emoji = "♻️"
            await handle_timer_panel_reaction(payload)
            return
        
    elif reaction_emoji == "✅":  # Enable timer (ask for ID)
        embed = discord.Embed(
            title="✅ Enable Timer",
            description=f"{member.mention}, please reply with the **Timer ID** you want to enable.\n\nYou have 30 seconds to respond.",
            color=discord.Color.green()
        )
        
        if messages:
            disabled = [m for m in messages if not m.enabled]
            if disabled:
                timer_list = "\n".join([f"• **ID {m.message_id}**: {m.message[:50]}{'...' if len(m.message) > 50 else ''}" for m in disabled[:10]])
                embed.add_field(name="Disabled Timers:", value=timer_list, inline=False)
            else:
                embed.description = "No disabled timers to enable!"
        
        embed.set_footer(text="Type 'cancel' to cancel")
        await message.edit(embed=embed)
        
        # Wait for user response
        def check(m):
            return m.author.id == member.id and m.channel.id == channel.id
        
        try:
            response = await bot.wait_for('message', timeout=30.0, check=check)
            
            if response.content.lower() == 'cancel':
                await response.delete()
                await channel.send(f"❌ {member.mention} Cancelled.", delete_after=3)
                # Refresh panel
                payload.emoji = "🔄"
                await handle_timer_panel_reaction(payload)
                return
            
            try:
                timer_id = int(response.content)
                await response.delete()
                
                # Find and enable the timer
                timer = next((m for m in messages if m.message_id == timer_id), None)
                if timer:
                    if timer.enabled:
                        await channel.send(f"ℹ️ {member.mention} Timer {timer_id} is already enabled.", delete_after=5)
                    else:
                        manager.toggle_message(timer_id, True)
                        await channel.send(f"✅ {member.mention} Timer {timer_id} has been **enabled**!", delete_after=5)
                else:
                    await channel.send(f"❌ {member.mention} Timer ID {timer_id} not found.", delete_after=5)
                
            except ValueError:
                await response.delete()
                await channel.send(f"❌ {member.mention} Invalid ID. Please use a number.", delete_after=5)
            
            # Refresh panel
            payload.emoji = "♻️"
            await handle_timer_panel_reaction(payload)
            return
            
        except asyncio.TimeoutError:
            await channel.send(f"⏰ {member.mention} Timed out. Please try again.", delete_after=5)
            # Refresh panel
            payload.emoji = "🔄"
            await handle_timer_panel_reaction(payload)
            return
    
    # Remove the reaction
    try:
        await message.remove_reaction(payload.emoji, member)
    except:
        pass

@bot.event
async def on_raw_reaction_add(payload):
    """Handle reactions to link panel and timer panel messages."""
    
    # Ignore bot's own reactions
    if payload.user_id == bot.user.id:
        return
    
    # Check if this reaction is on a timer panel message
    with engine.connect() as conn:
        timer_panel = conn.execute(text("""
            SELECT id FROM timer_panels 
            WHERE guild_id = :g AND channel_id = :c AND message_id = :m
        """), {"g": payload.guild_id, "c": payload.channel_id, "m": payload.message_id}).fetchone()
        
        if timer_panel:
            # Handle timer panel reactions
            await handle_timer_panel_reaction(payload)
            return
    
    # Check if this reaction is on a link panel message
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT emoji FROM link_panels 
            WHERE guild_id = :g AND channel_id = :c AND message_id = :m
        """), {"g": payload.guild_id, "c": payload.channel_id, "m": payload.message_id}).fetchone()
        
        if not result:
            return  # Not a link panel or timer panel message
        
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
    
    # Generate cryptographically signed OAuth URL
    oauth_url = generate_signed_oauth_url(discord_id)
    
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
