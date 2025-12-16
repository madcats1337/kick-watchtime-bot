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
import redis
from typing import Optional
from core.kick_api import USER_AGENTS
from datetime import datetime, timedelta, timezone
from functools import partial
from redis_subscriber import start_redis_subscriber

from dotenv import load_dotenv
from sqlalchemy import create_engine, text # type: ignore
from core.kick_api import fetch_chatroom_id, check_stream_live, get_clips, KickAPI, USER_AGENTS  # Consolidated Kick API module
# Clip service moved to Dashboard - bot now calls Dashboard API

import discord
from discord.ext import commands, tasks

# Raffle system imports
from raffle_system.database import setup_raffle_database, get_current_period, create_new_period, migrate_add_created_at_to_shuffle_wagers, migrate_add_platform_to_wager_tables
from raffle_system.migrations.add_provably_fair_to_draws import migrate_add_provably_fair_to_draws
from raffle_system.watchtime_converter import setup_watchtime_converter
from raffle_system.gifted_sub_tracker import setup_gifted_sub_handler
from raffle_system.shuffle_tracker import setup_shuffle_tracker
from raffle_system.auto_leaderboard import setup_auto_leaderboard
from raffle_system.commands import setup as setup_raffle_commands
from raffle_system.scheduler import setup_raffle_scheduler

# Bot settings manager - loads settings from database with env var fallbacks
from utils.bot_settings import BotSettingsManager

# Slot call tracker import
from features.slot_requests.slot_calls import setup_slot_call_tracker
from features.slot_requests.slot_request_panel import setup_slot_panel

# Timed messages import
from features.messaging.timed_messages import setup_timed_messages

# Guess the Balance import
from features.games.guess_the_balance import GuessTheBalanceManager, parse_amount
from features.games.gtb_panel import setup_gtb_panel

# Link panel import
from features.linking.link_panel import setup_link_panel_system

# Custom commands import
from features.custom_commands import CustomCommandsManager

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

# KICK_CHANNEL can come from env var or database (via BotSettingsManager after engine init)
# We'll set a temporary value here and load from settings later
KICK_CHANNEL = os.getenv("KICK_CHANNEL")  # May be None, will be loaded from DB later

# Optional: Hardcoded chatroom ID to bypass Cloudflare issues
# Can also be configured via dashboard
KICK_CHATROOM_ID = os.getenv("KICK_CHATROOM_ID")  # Set this on Railway to skip fetching

# Multiserver support: Settings are loaded per-guild dynamically
# No need for DISCORD_GUILD_ID - each guild has its own configuration in the database
print("✅ Multiserver mode: Settings loaded per-guild dynamically")

# Database configuration with cloud PostgreSQL support
DATABASE_URL = os.getenv("DATABASE_URL", "")

# Redis configuration for publishing events
REDIS_URL = os.getenv("REDIS_URL", "")
redis_client = None
if REDIS_URL:
    try:
        _ru = REDIS_URL if '://' in REDIS_URL else f'redis://{REDIS_URL}'
        redis_client = redis.from_url(_ru, decode_responses=True)
        redis_client.ping()
        print("✅ Redis client connected for event publishing")
    except Exception as e:
        print(f"⚠️  Redis unavailable: {e}")
        redis_client = None
else:
    print("⚠️  REDIS_URL not set, events will not be published")

def publish_redis_event(channel: str, action: str, data: dict = None):
    """Publish an event to Redis for dashboard real-time updates"""
    if not redis_client:
        return False
    try:
        payload = {
            'action': action,
            'data': data or {},
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
        redis_client.publish(channel, json.dumps(payload))
        return True
    except Exception as e:
        print(f"Failed to publish Redis event: {e}")
        return False

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
# Can also be configured via dashboard
SLOT_CALLS_CHANNEL_ID = int(os.getenv("SLOT_CALLS_CHANNEL_ID")) if os.getenv("SLOT_CALLS_CHANNEL_ID") else None

# OAuth configuration
OAUTH_BASE_URL = os.getenv("OAUTH_BASE_URL", "")  # e.g., https://your-app.up.railway.app
# Ensure OAUTH_BASE_URL has https:// scheme
if OAUTH_BASE_URL and not OAUTH_BASE_URL.startswith(('http://', 'https://')):
    OAUTH_BASE_URL = f"https://{OAUTH_BASE_URL}"
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
def generate_signed_oauth_url(discord_id: int, guild_id: int = None) -> str:
    """
    Generate a cryptographically signed OAuth URL to prevent initiation spoofing.
    Only URLs generated by this bot will have valid signatures.

    Args:
        discord_id: Discord user ID
        guild_id: Discord server/guild ID (optional, defaults to 0 if not provided)
    """
    timestamp = int(datetime.now(timezone.utc).timestamp())
    # Include guild_id in signature to prevent tampering
    guild_id = guild_id or 0
    message = f"{discord_id}:{guild_id}:{timestamp}"
    signature = hmac.new(
        OAUTH_SECRET_KEY.encode(),
        message.encode(),
        hashlib.sha256
    ).digest()
    sig_encoded = base64.urlsafe_b64encode(signature).decode().rstrip('=')

    return f"{OAUTH_BASE_URL}/auth/kick?discord_id={discord_id}&guild_id={guild_id}&timestamp={timestamp}&signature={sig_encoded}"

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
        from core.kick_api import KickAPI
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

        # Create links table (multi-server aware)
        # New columns:
        # - discord_server_id: isolates links per guild
        # - linked_at: timestamp for link creation
        # Backwards compatibility: migrate existing schema if needed
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS links (
            discord_id BIGINT,
            kick_name TEXT,
            discord_server_id BIGINT,
            linked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (discord_id, discord_server_id),
            UNIQUE (kick_name, discord_server_id)
        );
        """))

        # --- Migration for older schema (without discord_server_id / linked_at) ---
        try:
            conn.execute(text("ALTER TABLE links ADD COLUMN IF NOT EXISTS discord_server_id BIGINT"))
        except Exception as e:
            print(f"ℹ️ links table migration (discord_server_id) note: {e}")
        try:
            conn.execute(text("ALTER TABLE links ADD COLUMN IF NOT EXISTS linked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"))
        except Exception as e:
            print(f"ℹ️ links table migration (linked_at) note: {e}")
        # Note: No automatic backfill for multiserver - each link must have discord_server_id set

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
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            discord_server_id BIGINT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (key, discord_server_id)
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

        # Create Guess the Balance tables
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS gtb_sessions (
            id SERIAL PRIMARY KEY,
            opened_by TEXT NOT NULL,
            opened_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            closed_at TIMESTAMP,
            result_amount NUMERIC(12, 2),
            status TEXT DEFAULT 'open' CHECK (status IN ('open', 'closed', 'completed')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """))

        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS gtb_guesses (
            id SERIAL PRIMARY KEY,
            session_id INTEGER NOT NULL REFERENCES gtb_sessions(id) ON DELETE CASCADE,
            kick_username TEXT NOT NULL,
            guess_amount NUMERIC(12, 2) NOT NULL,
            guessed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            discord_server_id BIGINT,
            UNIQUE(session_id, kick_username)
        );
        """))

        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS gtb_winners (
            id SERIAL PRIMARY KEY,
            session_id INTEGER NOT NULL REFERENCES gtb_sessions(id) ON DELETE CASCADE,
            kick_username TEXT NOT NULL,
            rank INTEGER NOT NULL CHECK (rank IN (1, 2, 3)),
            guess_amount NUMERIC(12, 2) NOT NULL,
            result_amount NUMERIC(12, 2) NOT NULL,
            difference NUMERIC(12, 2) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """))

        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS clips (
            id SERIAL PRIMARY KEY,
            kick_username TEXT NOT NULL,
            clip_duration INTEGER NOT NULL,
            clip_url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """))

        # -------------------------
        # Point Reward System Tables
        # -------------------------

        # Points balance for each user
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS user_points (
            id SERIAL PRIMARY KEY,
            kick_username TEXT NOT NULL,
            discord_id BIGINT,
            points INTEGER DEFAULT 0,
            total_earned INTEGER DEFAULT 0,
            total_spent INTEGER DEFAULT 0,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(kick_username)
        );
        """))

        # Track watchtime already converted to points (similar to raffle system)
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS points_watchtime_converted (
            id SERIAL PRIMARY KEY,
            kick_username TEXT NOT NULL,
            minutes_converted INTEGER NOT NULL,
            points_awarded INTEGER NOT NULL,
            converted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """))

        # Point shop items
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS point_shop_items (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            price INTEGER NOT NULL,
            stock INTEGER DEFAULT -1,
            image_url TEXT,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """))

        # Point shop sales/purchases
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS point_sales (
            id SERIAL PRIMARY KEY,
            item_id INTEGER REFERENCES point_shop_items(id),
            kick_username TEXT NOT NULL,
            discord_id BIGINT,
            item_name TEXT NOT NULL,
            price_paid INTEGER NOT NULL,
            quantity INTEGER DEFAULT 1,
            status TEXT DEFAULT 'pending',
            notes TEXT,
            purchased_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """))

        # Add notes column if it doesn't exist (migration for existing databases)
        try:
            conn.execute(text("""
            ALTER TABLE point_sales ADD COLUMN IF NOT EXISTS notes TEXT;
            """))
        except Exception:
            pass  # Column might already exist or DB doesn't support IF NOT EXISTS

        # Point system settings
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS point_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """))

        # =========================================================================
        # MULTISERVER MIGRATION - Add discord_server_id to tables
        # =========================================================================
        print("🔄 Running multiserver migration...")

        # Step 1: Add discord_server_id columns if they don't exist
        migration_tables = [
            'user_points', 'points_watchtime_converted', 'point_sales',
            'watchtime', 'gtb_sessions', 'clips', 'watchtime_roles',
            'pending_links', 'oauth_notifications'
        ]
        
        for table in migration_tables:
            try:
                conn.execute(text(f"""
                    ALTER TABLE {table} ADD COLUMN IF NOT EXISTS discord_server_id BIGINT
                """))
            except Exception as e:
                # Column might already exist - this is fine
                pass

        # Step 2: Backfill existing data with first server ID (if exists)
        # Only attempt if servers table exists and has data
        try:
            # Check if servers table exists
            servers_exist = conn.execute(text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'servers'
                )
            """)).fetchone()[0]
            
            if servers_exist:
                first_server = conn.execute(text("""
                    SELECT discord_server_id FROM servers LIMIT 1
                """)).fetchone()
                
                if first_server:
                    server_id = first_server[0]
                    print(f"🔄 Backfilling tables with server ID: {server_id}")
                    
                    for table in migration_tables:
                        try:
                            result = conn.execute(text(f"""
                                UPDATE {table} SET discord_server_id = :sid WHERE discord_server_id IS NULL
                            """), {"sid": server_id})
                            if result.rowcount > 0:
                                print(f"   ✅ {table}: Updated {result.rowcount} rows")
                        except Exception:
                            pass  # Table might be empty or not exist yet
                else:
                    print("ℹ️ No servers found in servers table - skipping backfill")
            else:
                print("ℹ️ Servers table not found - skipping backfill")
        except Exception as e:
            print(f"ℹ️ Backfill skipped: {e}")

        # Step 3: Update primary keys for tables that need composite keys
        # Only attempt if tables have data or NULL discord_server_id values filled
        # user_points: (kick_username, discord_server_id)
        try:
            # First check if table has any rows with NULL discord_server_id
            null_check = conn.execute(text("""
                SELECT COUNT(*) FROM user_points WHERE discord_server_id IS NULL
            """)).fetchone()[0]
            
            if null_check == 0:
                # Safe to update primary key
                conn.execute(text("""
                    ALTER TABLE user_points DROP CONSTRAINT IF EXISTS user_points_kick_username_key
                """))
                conn.execute(text("""
                    ALTER TABLE user_points DROP CONSTRAINT IF EXISTS user_points_pkey
                """))
                conn.execute(text("""
                    ALTER TABLE user_points ADD CONSTRAINT user_points_pkey_multiserver 
                    PRIMARY KEY (kick_username, discord_server_id)
                """))
                print("   ✅ user_points: Updated primary key")
            else:
                print(f"   ℹ️ user_points: Skipping PK update ({null_check} rows with NULL discord_server_id)")
        except Exception as e:
            # PK might already be updated or table might be empty
            pass

        # watchtime: (username, discord_server_id)
        try:
            # Check for NULL values first
            null_check = conn.execute(text("""
                SELECT COUNT(*) FROM watchtime WHERE discord_server_id IS NULL
            """)).fetchone()[0]
            
            if null_check == 0:
                conn.execute(text("""
                    ALTER TABLE watchtime DROP CONSTRAINT IF EXISTS watchtime_pkey
                """))
                conn.execute(text("""
                    ALTER TABLE watchtime ADD CONSTRAINT watchtime_pkey_multiserver 
                    PRIMARY KEY (username, discord_server_id)
                """))
                print("   ✅ watchtime: Updated primary key")
            else:
                print(f"   ℹ️ watchtime: Skipping PK update ({null_check} rows with NULL discord_server_id)")
        except Exception as e:
            # PK might already be updated or table might be empty
            pass

        # Step 4: Create indexes for performance
        indexes = {
            'idx_user_points_server': 'user_points(discord_server_id)',
            'idx_points_watchtime_server': 'points_watchtime_converted(discord_server_id)',
            'idx_point_sales_server': 'point_sales(discord_server_id)',
            'idx_watchtime_server': 'watchtime(discord_server_id)',
            'idx_gtb_sessions_server': 'gtb_sessions(discord_server_id)',
            'idx_clips_server': 'clips(discord_server_id)',
            'idx_watchtime_roles_server': 'watchtime_roles(discord_server_id)',
            'idx_pending_links_server': 'pending_links(discord_server_id)',
            'idx_oauth_notifications_server': 'oauth_notifications(discord_server_id)'
        }
        
        for idx_name, idx_def in indexes.items():
            try:
                conn.execute(text(f"""
                    CREATE INDEX IF NOT EXISTS {idx_name} ON {idx_def}
                """))
            except Exception:
                # Index might already exist
                pass

        print("✅ Multiserver migration complete")
        # =========================================================================

    print("✅ Database tables initialized successfully")
except Exception as e:
    print(f"⚠️ Database initialization error: {e}")
    raise

# -------------------------
# Bot Settings Manager
# -------------------------
# Multi-server support: Per-guild settings managers
# MULTISERVER: Initialize settings manager without guild-specific configuration
# Guild settings are loaded dynamically via get_guild_settings(guild_id)
bot_settings = BotSettingsManager(engine)
print("✅ Multiserver bot initialized")
print("   Each Discord server configures via Dashboard → Profile Settings")

# Dictionary to store per-guild settings managers
guild_settings_managers = {}

def get_guild_settings(guild_id: int) -> BotSettingsManager:
    """
    Get settings manager for a specific guild.
    REQUIRED for all guild-specific operations.
    
    Args:
        guild_id: Discord guild/server ID
        
    Returns:
        BotSettingsManager instance for the guild
    """
    # Get or create guild-specific settings
    if guild_id not in guild_settings_managers:
        guild_settings_managers[guild_id] = BotSettingsManager(engine, guild_id=guild_id)
        print(f"✅ Loaded settings for guild {guild_id}")
    
    return guild_settings_managers[guild_id]

# Multiserver: No global KICK_CHANNEL or SLOT_CALLS_CHANNEL_ID
# All features must use get_guild_settings(guild.id) to access per-guild configuration
print("✅ Multiserver bot ready - configure each guild in Dashboard → Profile Settings")

# -------------------------
# Discord bot setup
# -------------------------
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.reactions = True  # Enable reaction events

bot = commands.Bot(command_prefix="!", intents=intents)

# Store settings manager on bot for access throughout
bot.settings_manager = bot_settings

# Multiserver tracking - per-guild dictionaries
# active_viewers_by_guild[guild_id][username] = last_seen_time
active_viewers_by_guild = {}
# recent_chatters_by_guild[guild_id][username] = last_chat_time
recent_chatters_by_guild = {}
# last_chat_activity_by_guild[guild_id] = last_activity_time
last_chat_activity_by_guild = {}
# kick_chatroom_ids[guild_id] = chatroom_id
kick_chatroom_ids = {}

# Legacy global variables (for backward compatibility during transition)
active_viewers = {}
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

# Clip buffer tracking
clip_buffer_active = False  # Track if clip buffer is running on Dashboard
last_stream_live_state = None  # Track last known stream live state (for detecting transitions)

# Raffle system global trackers - now per-guild dictionaries
gifted_sub_trackers = {}  # guild_id -> GiftedSubTracker
shuffle_trackers = {}  # guild_id -> ShuffleTracker
slot_call_trackers = {}  # guild_id -> SlotCallTracker
gtb_managers = {}  # guild_id -> GTBManager

# Legacy global variables (for backward compatibility)
gifted_sub_tracker = None
shuffle_tracker = None
slot_call_tracker = None
gtb_manager = None
MIN_UNIQUE_CHATTERS = 2  # Require at least 2 different people chatting to consider stream "live"
CHAT_ACTIVITY_WINDOW_MINUTES = 5  # Look back 5 minutes for unique chatters

# -------------------------
# Helper functions
# -------------------------
def get_active_chatters_count(guild_id: Optional[int] = None):
    """Get the number of active chatters in the recent window for a specific guild"""
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    chat_cutoff = now - timedelta(minutes=CHAT_ACTIVITY_WINDOW_MINUTES)

    if guild_id is None:
        # Legacy: use global recent_chatters
        active_chatters = {
            username: timestamp
            for username, timestamp in recent_chatters.items()
            if timestamp >= chat_cutoff
        }
    else:
        # Multiserver: use per-guild tracking
        guild_chatters = recent_chatters_by_guild.get(guild_id, {})
        active_chatters = {
            username: timestamp
            for username, timestamp in guild_chatters.items()
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
    # Multiserver: guild_id should be passed as parameter, but for now skip if not available
    # TODO: Update callers to pass guild_id
    return  # Temporarily disabled for multiserver migration

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

async def kick_chat_loop(channel_name: str, guild_id: int):
    """Connect to Kick's Pusher WebSocket and listen for chat messages for a specific guild."""
    global kick_chatroom_id_global
    
    # Initialize per-guild tracking dictionaries if they don't exist
    if guild_id not in active_viewers_by_guild:
        active_viewers_by_guild[guild_id] = {}
    if guild_id not in recent_chatters_by_guild:
        recent_chatters_by_guild[guild_id] = {}
    if guild_id not in last_chat_activity_by_guild:
        last_chat_activity_by_guild[guild_id] = None

    # Track current channel and chatroom to detect changes
    current_channel = channel_name
    current_chatroom_id = None
    
    # Get guild settings
    guild_settings = get_guild_settings(guild_id)

    while True:
        try:
            # Refresh settings to detect changes
            guild_settings.refresh()
            
            # Check if channel has been updated in settings (allow hot-reload on reconnect)
            new_channel = guild_settings.kick_channel
            if new_channel and new_channel != current_channel:
                print(f"[Kick][Guild {guild_id}] 🔄 Channel changed from '{current_channel}' to '{new_channel}'")
                current_channel = new_channel

            # Use current_channel instead of the original channel_name
            channel_to_use = current_channel

            # Fetch channel data (chatroom ID and channel ID for subscriptions)
            chatroom_id = None
            channel_id = None

            # Check if chatroom ID is hardcoded in environment (bypass for Cloudflare issues)
            # Or configured in guild settings (per-guild configuration)
            chatroom_id_from_settings = guild_settings.kick_chatroom_id

            if KICK_CHATROOM_ID or chatroom_id_from_settings:
                chatroom_id = KICK_CHATROOM_ID or chatroom_id_from_settings
                kick_chatroom_ids[guild_id] = chatroom_id  # Store per-guild
                kick_chatroom_id_global = chatroom_id  # Legacy global
                print(f"[Kick][Guild {guild_id} - {channel_to_use}] Using configured chatroom ID: {chatroom_id}")

                # Still try to fetch channel_id for subscription events
                try:
                    async with aiohttp.ClientSession() as session:
                        headers = {
                            'User-Agent': random.choice(USER_AGENTS),
                            'Accept': 'application/json',
                            'Referer': 'https://kick.com/',
                        }
                        async with session.get(
                            f'https://kick.com/api/v2/channels/{channel_to_use}',
                            headers=headers,
                            timeout=aiohttp.ClientTimeout(total=10)
                        ) as response:
                            if response.status == 200:
                                data = await response.json()
                                channel_id = str(data.get('id'))
                                print(f"[Kick] ✅ Fetched channel ID: {channel_id}")
                            else:
                                print(f"[Kick] ⚠️ Could not fetch channel ID (HTTP {response.status})")
                except Exception as e:
                    print(f"[Kick] ⚠️ Error fetching channel ID: {e}")
            else:
                # Fetch full channel data to get both chatroom_id and channel_id
                try:
                    async with aiohttp.ClientSession() as session:
                        headers = {
                            'User-Agent': random.choice(USER_AGENTS),
                            'Accept': 'application/json',
                            'Referer': 'https://kick.com/',
                        }
                        async with session.get(
                            f'https://kick.com/api/v2/channels/{channel_to_use}',
                            headers=headers,
                            timeout=aiohttp.ClientTimeout(total=10)
                        ) as response:
                            if response.status == 200:
                                data = await response.json()
                                chatroom_id = str(data.get('chatroom', {}).get('id'))
                                channel_id = str(data.get('id'))  # Channel ID for subscription events
                                kick_chatroom_id_global = chatroom_id
                                print(f"[Kick] ✅ Found chatroom ID: {chatroom_id}, channel ID: {channel_id}")
                            else:
                                print(f"[Kick] Failed to fetch channel data: HTTP {response.status}")
                except Exception as e:
                    print(f"[Kick] Error fetching channel data: {e}")

                if not chatroom_id:
                    print(f"[Kick] Could not obtain chatroom id for {channel_to_use}. Retrying in 30s.")
                    await asyncio.sleep(30)
                    continue
            
            # Check if chatroom_id has changed (hot-reload support)
            if current_chatroom_id and chatroom_id != current_chatroom_id:
                print(f"[Kick][Guild {guild_id}] 🔄 Chatroom ID changed from {current_chatroom_id} to {chatroom_id} for THIS GUILD ONLY - reconnecting...")
            
            # Store current chatroom_id for change detection
            current_chatroom_id = chatroom_id

            print(f"[Kick][Guild {guild_id}] Connecting to chatroom {chatroom_id} for channel {channel_to_use}...")

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

                    # Subscribe to the chatroom channel (for chat messages)
                    subscribe_msg = json.dumps({
                    "event": "pusher:subscribe",
                    "data": {
                        "auth": "",
                        "channel": f"chatrooms.{chatroom_id}.v2"
                    }
                })
                await ws.send(subscribe_msg)
                print(f"[Kick] ✅ Subscribed to chatrooms.{chatroom_id}.v2")

                # Subscribe to channel events (for subscriptions, raids, follows, etc.)
                if channel_id:
                    channel_events_msg = json.dumps({
                        "event": "pusher:subscribe",
                        "data": {
                            "auth": "",
                            "channel": f"channel.{channel_id}"
                        }
                    })
                    await ws.send(channel_events_msg)
                    print(f"[Kick] ✅ Subscribed to channel.{channel_id} (for subscription events)")
                else:
                    print(f"[Kick] ⚠️ Channel ID not available - subscription events may not be received")

                                # Initialize last_chat_activity to assume stream is live when we connect
                last_chat_activity_by_guild[guild_id] = datetime.now(timezone.utc)
                print(f"[Kick][Guild {guild_id}] Initialized chat activity tracking")

                # Listen for messages
                last_settings_check = datetime.now(timezone.utc)
                settings_check_interval = 30  # Check for settings changes every 30 seconds
                
                while True:
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=30)
                        
                        # Periodically check if chatroom_id has changed in settings
                        now = datetime.now(timezone.utc)
                        if (now - last_settings_check).total_seconds() >= settings_check_interval:
                            guild_settings.refresh()
                            new_chatroom_id = guild_settings.kick_chatroom_id or KICK_CHATROOM_ID
                            if new_chatroom_id and new_chatroom_id != current_chatroom_id:
                                print(f"[Kick][Guild {guild_id}] 🔄 Detected chatroom ID change for THIS GUILD: {current_chatroom_id} → {new_chatroom_id}")
                                print(f"[Kick][Guild {guild_id}] Breaking connection to reconnect with new chatroom (other guilds unaffected)...")
                                break  # Break inner loop to reconnect with new chatroom_id
                            last_settings_check = now

                        if not msg:
                            continue

                        # Parse Pusher message
                        try:
                            data = json.loads(msg)
                            event_type = data.get("event")

                            # DEBUG: Log ALL event types (except ping/pong and chat) to catch subscription events
                            if event_type and event_type not in ["pusher:ping", "pusher:pong", "App\\Events\\ChatMessageEvent"]:
                                print(f"[KICK EVENT] Type: {event_type}")
                                print(f"[KICK EVENT] Data keys: {list(json.loads(data.get('data', '{}')).keys()) if data.get('data') else 'No data'}")

                            # Respond to ping
                            if event_type == "pusher:ping":
                                await ws.send(json.dumps({"event": "pusher:pong"}))
                                continue

                            # Handle chat message
                            if event_type == "App\\Events\\ChatMessageEvent":
                                now = datetime.now(timezone.utc)
                                last_chat_activity_by_guild[guild_id] = now  # Update stream activity for this guild

                                event_data = json.loads(data.get("data", "{}"))
                                sender = event_data.get("sender", {})
                                username = sender.get("username")

                                if username:
                                    username_lower = username.lower()
                                    # Track per-guild active viewers
                                    guild_active_viewers = active_viewers_by_guild.get(guild_id, {})
                                    is_new_viewer = username_lower not in guild_active_viewers
                                    guild_active_viewers[username_lower] = now
                                    active_viewers_by_guild[guild_id] = guild_active_viewers
                                    
                                    # Track per-guild recent chatters for stream-live detection
                                    guild_recent_chatters = recent_chatters_by_guild.get(guild_id, {})
                                    guild_recent_chatters[username_lower] = now
                                    recent_chatters_by_guild[guild_id] = guild_recent_chatters
                                    
                                    # Also update legacy global tracking (for backward compatibility)
                                    active_viewers[username_lower] = now
                                    recent_chatters[username_lower] = now
                                    
                                    content_text = event_data.get("content", "")
                                    print(f"[Kick][Guild {guild_id}] {username}: {content_text}")
                                    if watchtime_debug_enabled and is_new_viewer:
                                        print(f"[Watchtime Debug][Guild {guild_id}] New viewer: {username_lower} (total: {len(guild_active_viewers)})")

                                    # Check for custom commands first (they get priority)
                                    if hasattr(bot, 'custom_commands_manager') and bot.custom_commands_manager:
                                        try:
                                            handled = await bot.custom_commands_manager.handle_message(content_text, username)
                                            if handled:
                                                continue  # Command was handled, skip other processing
                                        except Exception as e:
                                            print(f"⚠️ Error handling custom command: {e}")

                                    # Handle slot call commands (!call or !sr)
                                    content_stripped = content_text.strip()
                                    # Use bot.slot_call_tracker instead of global variable
                                    if hasattr(bot, 'slot_call_tracker') and bot.slot_call_tracker and (content_stripped.startswith("!call") or content_stripped.startswith("!sr")):
                                        # 🔒 SECURITY: Check if user is blacklisted (per-guild)
                                        is_blacklisted = False
                                        try:
                                            guild_id = bot.slot_call_tracker.discord_server_id if hasattr(bot.slot_call_tracker, 'discord_server_id') else None
                                            if guild_id:
                                                with engine.begin() as check_conn:
                                                    blacklist_check = check_conn.execute(text("""
                                                        SELECT 1 FROM slot_call_blacklist 
                                                        WHERE kick_username = :username AND discord_server_id = :guild_id
                                                    """), {"username": username_lower, "guild_id": guild_id}).fetchone()
                                                    is_blacklisted = blacklist_check is not None
                                        except Exception as e:
                                            print(f"Error checking slot call blacklist: {e}")

                                        if is_blacklisted:
                                            print(f"[Slot Call] Blocked blacklisted user: {username}")
                                            # No response sent to blacklisted users
                                        else:
                                            # Extract the slot call (everything after "!call " or "!sr ")
                                            # 🔒 SECURITY: Limit length to prevent abuse (200 chars max)
                                            if content_stripped.startswith("!call"):
                                                slot_call = content_stripped[5:].strip()[:200]  # Remove "!call"
                                            else:  # !sr
                                                slot_call = content_stripped[3:].strip()[:200]  # Remove "!sr"

                                            if slot_call:  # Only process if there's actually a call
                                                await bot.slot_call_tracker.handle_slot_call(username, slot_call)
                                            else:
                                                # Send usage message when no content is provided (only to non-blacklisted users)
                                                try:
                                                    await send_kick_message(f"@{username} Please specify a slot!")
                                                    print(f"[Slot Call] Sent usage instructions to {username}")
                                                except Exception as e:
                                                    print(f"Failed to send usage message to {username}: {e}")

                                    # Handle !raffle command
                                    if content_stripped.lower() == "!raffle":
                                        raffle_message = (
                                            "Do you want to win a $100 super buy on Sweet Bonanza 1000? "
                                            "All you gotta do is join my discord, verify with lelebot and follow the instructions -> "
                                            "https://discord.gg/k7CXJtfrPY"
                                        )
                                        # Send message to Kick chat using the API
                                        await send_kick_message(raffle_message)

                                    # Handle !gtb (Guess the Balance) command
                                    if content_stripped.lower().startswith("!gtb"):
                                        gtb_parts = content_stripped.split(maxsplit=1)
                                        if len(gtb_parts) == 2:
                                            amount_str = gtb_parts[1]
                                            amount = parse_amount(amount_str)

                                            if amount is not None:
                                                success, message = gtb_manager.add_guess(username, amount)
                                                if success:
                                                    # Send confirmation to Kick chat
                                                    response = f"@{username} {message} Good luck! 🎰"
                                                    await send_kick_message(response)
                                                    print(f"[GTB] {username} guessed ${amount:,.2f}")
                                                else:
                                                    # Send error message to Kick chat
                                                    await send_kick_message(f"@{username} {message}")
                                                    print(f"[GTB] Failed guess from {username}: {message}")
                                            else:
                                                await send_kick_message(f"@{username} Invalid amount. Use: !gtb <amount> (e.g., !gtb 1234.56)")
                                        else:
                                            await send_kick_message(f"@{username} Usage: !gtb <amount> (e.g., !gtb 1234.56)")

                                    # Handle !clip command - Create a clip of the livestream
                                    if content_stripped.lower().startswith("!clip"):
                                        # Get clip duration from bot_settings (default 30 seconds)
                                        clip_duration = 30
                                        try:
                                            with engine.connect() as conn:
                                                result = conn.execute(text("""
                                                    SELECT value FROM bot_settings WHERE key = 'clip_duration'
                                                """)).fetchone()
                                                if result:
                                                    clip_duration = int(result[0])
                                        except Exception as e:
                                            print(f"[Clip] Using default duration, couldn't load from DB: {e}")

                                        # Everything after !clip is the title
                                        clip_title = content_stripped[5:].strip()  # Remove "!clip" and trim
                                        
                                        if not clip_title:
                                            # No title provided - generate default
                                            timestamp = datetime.now().strftime("%b %d, %Y %H:%M")
                                            clip_title = f"Clip by {username} - {timestamp}"

                                        # Use background task for clip creation (non-blocking)
                                        print(f"[Clip] {username} requested a clip ({clip_duration}s) - Title: {clip_title}")

                                        async def create_clip_background(user: str, duration: int, title: str):
                                            """Background task to create clip via Dashboard API"""
                                            try:
                                                # Refresh settings from database to get latest values
                                                bot_settings.refresh()

                                                # Get Dashboard URL from bot_settings (database)
                                                dashboard_url = bot_settings.dashboard_url
                                                api_key = bot_settings.bot_api_key

                                                print(f"[Clip] DEBUG - dashboard_url from DB: '{dashboard_url}'")
                                                print(f"[Clip] DEBUG - bot_api_key exists: {bool(api_key)}")

                                                if not dashboard_url:
                                                    print(f"[Clip] ❌ Dashboard URL not configured in bot_settings table")
                                                    await send_kick_message(f"@{user} Clip service not configured - contact admin!")
                                                    return

                                                # Create clip via Dashboard API
                                                async with aiohttp.ClientSession() as http_session:
                                                    headers = {
                                                        'Content-Type': 'application/json',
                                                        'X-API-Key': api_key
                                                    }
                                                    payload = {
                                                        'channel': KICK_CHANNEL,
                                                        'duration': duration,
                                                        'username': user,
                                                        'title': title
                                                    }

                                                    async with http_session.post(
                                                        f"{dashboard_url}/api/clips/create",
                                                        json=payload,
                                                        headers=headers,
                                                        timeout=aiohttp.ClientTimeout(total=60)
                                                    ) as response:
                                                        clip_result = await response.json()

                                                        print(f"[Clip] Dashboard API response: {clip_result}")

                                                        if response.status == 200 and clip_result.get('success'):
                                                            # Success - extract clip URL
                                                            clip_url = clip_result.get('clip_url', '')
                                                            clip_filename = clip_result.get('filename', '')
                                                            file_size_mb = clip_result.get('file_size_mb', clip_result.get('file_size', 0) / 1024 / 1024)
                                                            actual_duration = clip_result.get('duration', duration)

                                                            await send_kick_message(f"@{user} Your clip is ready! ({actual_duration}s, {file_size_mb:.1f}MB) {clip_url}")
                                                            print(f"[Clip] ✅ Clip created for {user}: {clip_filename}")

                                                            # Save clip data to database
                                                            try:
                                                                with engine.connect() as conn:
                                                                    conn.execute(text("""
                                                                        INSERT INTO clips (kick_username, clip_duration, clip_url, filename, file_size)
                                                                        VALUES (:username, :duration, :url, :filename, :file_size)
                                                                    """), {
                                                                        "username": user,
                                                                        "duration": actual_duration,
                                                                        "url": clip_url,
                                                                        "filename": clip_filename,
                                                                        "file_size": clip_result.get('file_size', 0)
                                                                    })
                                                                    conn.commit()
                                                                print(f"[Clip] 💾 Saved clip data for {user}")
                                                            except Exception as db_err:
                                                                print(f"[Clip] ⚠️ Failed to save clip to DB: {db_err}")

                                                            # Post clip embed to Discord channel if configured
                                                            try:
                                                                clip_channel_id = None
                                                                with engine.connect() as conn:
                                                                    result = conn.execute(text("""
                                                                        SELECT value FROM bot_settings WHERE key = 'clip_channel_id'
                                                                    """)).fetchone()
                                                                    if result and result[0]:
                                                                        clip_channel_id = int(result[0])

                                                                if clip_channel_id:
                                                                    discord_channel = bot.get_channel(clip_channel_id)
                                                                    if discord_channel:
                                                                        clip_embed = discord.Embed(
                                                                            title=f"🎬 {title}",
                                                                            description=f"New clip created by **{user}** in Kick chat!",
                                                                            color=0x53FC18,
                                                                            url=clip_url if clip_url.startswith('http') else None,
                                                                            timestamp=datetime.now(timezone.utc)
                                                                        )
                                                                        clip_embed.add_field(name="Duration", value=f"{actual_duration} seconds", inline=True)
                                                                        clip_embed.add_field(name="Created by", value=user, inline=True)
                                                                        clip_embed.add_field(name="Size", value=f"{file_size_mb:.1f} MB", inline=True)
                                                                        if clip_url:
                                                                            clip_embed.add_field(name="🔗 Watch Clip", value=f"[Click here]({clip_url})" if clip_url.startswith('http') else clip_url, inline=False)
                                                                        clip_embed.set_footer(text=f"Kick Channel: {KICK_CHANNEL}")
                                                                        await discord_channel.send(embed=clip_embed)
                                                                        print(f"[Clip] 📢 Posted clip to Discord channel {clip_channel_id}")
                                                            except Exception as discord_err:
                                                                print(f"[Clip] ⚠️ Failed to post clip to Discord: {discord_err}")
                                                        else:
                                                            # Handle error from Dashboard API
                                                            error_type = clip_result.get('error', 'unknown')
                                                            error_msg = clip_result.get('message', 'Unknown error')

                                                            if error_type == 'not_live' or error_type == 'not_recording':
                                                                await send_kick_message(f"@{user} Stream must be live to create clips!")
                                                            elif error_type == 'no_segments' or error_type == 'no_buffer':
                                                                await send_kick_message(f"@{user} Buffer still loading - try again in 30 seconds!")
                                                            else:
                                                                await send_kick_message(f"@{user} Couldn't create clip - {error_msg}")

                                                            print(f"[Clip] ❌ Clip creation failed for {user}: {error_type}")

                                            except Exception as e:
                                                print(f"[Clip] ❌ Background clip error: {e}")
                                                await send_kick_message(f"@{user} Clip failed - try again later!")

                                        # Start background task (non-blocking)
                                        asyncio.create_task(create_clip_background(username, clip_duration, clip_title))

                            # Handle subscription events (both regular and gifted)
                            # Kick may use different event types for subs
                            subscription_event_types = [
                                "App\\Events\\GiftedSubscriptionsEvent",
                                "App\\Events\\LuckyUsersWhoGotGiftSubscriptionsEvent",
                                "App\\Events\\SubscriptionEvent",
                                "App\\Events\\ChatMessageEvent"  # Sometimes subs come as special chat messages
                            ]

                            # DEBUG: Check if event type should match
                            if event_type and "Subscription" in event_type:
                                print(f"[SUB CHECK] Event type: {event_type}")
                                print(f"[SUB CHECK] Event type repr: {repr(event_type)}")
                                print(f"[SUB CHECK] In list: {event_type in subscription_event_types}")
                                print(f"[SUB CHECK] Expected: {subscription_event_types[1]}")
                                print(f"[SUB CHECK] Expected repr: {repr(subscription_event_types[1])}")
                                print(f"[SUB CHECK] Match: {event_type == subscription_event_types[1]}")

                            if event_type in subscription_event_types:
                                print(f"[SUB HANDLER] Entering subscription handler for event type: {event_type}")
                                print(f"[SUB HANDLER] gifted_sub_tracker initialized: {gifted_sub_tracker is not None}")

                                event_data = json.loads(data.get("data", "{}"))

                                # DEBUG: Log subscription events
                                if event_type == "App\\Events\\LuckyUsersWhoGotGiftSubscriptionsEvent":
                                    print(f"[SUB DEBUG] LuckyUsersWhoGotGiftSubscriptionsEvent detected!")
                                    print(f"[SUB DEBUG] Gifter: {event_data.get('gifter_username')}")
                                    print(f"[SUB DEBUG] Recipients: {event_data.get('usernames')}")
                                    print(f"[SUB DEBUG] Full event data: {json.dumps(event_data, indent=2)}")

                                # DEBUG: Check what ChatMessageEvent contains
                                if event_type == "App\\Events\\ChatMessageEvent":
                                    msg_type = event_data.get("type")
                                    if msg_type and msg_type != "message":
                                        print(f"[SUB DEBUG] ChatMessageEvent type: {msg_type}")
                                        print(f"[SUB DEBUG] Event data: {json.dumps(event_data, indent=2)[:500]}")

                                # Check if this is any type of subscription
                                message_type = event_data.get("type")
                                is_subscription = (
                                    event_type == "App\\Events\\LuckyUsersWhoGotGiftSubscriptionsEvent" or
                                    event_type == "App\\Events\\GiftedSubscriptionsEvent" or
                                    event_type == "App\\Events\\SubscriptionEvent" or
                                    "gift" in str(message_type).lower() or
                                    "subscription" in str(message_type).lower() or
                                    "sub" in str(message_type).lower() or
                                    event_data.get("gifted_usernames") is not None or
                                    event_data.get("usernames") is not None or  # LuckyUsersWhoGotGiftSubscriptionsEvent
                                    event_data.get("gifter_username") is not None or  # LuckyUsersWhoGotGiftSubscriptionsEvent
                                    event_data.get("gift_count") is not None or
                                    event_data.get("months") is not None  # Regular subs often have months field
                                )

                                if is_subscription:
                                    print(f"[SUB DEBUG] Detected subscription! Type: {message_type}")
                                    print(f"[SUB DEBUG] Event data: {json.dumps(event_data, indent=2)[:800]}")
                                else:
                                    print(f"[SUB DEBUG] NOT detected as subscription. message_type: {message_type}")

                                if is_subscription and gifted_sub_tracker:
                                    print(f"[SUB HANDLER] Processing subscription with gifted_sub_tracker")
                                    # Handle any subscription event (gifted or regular)
                                    result = await gifted_sub_tracker.handle_gifted_sub_event(event_data)
                                    print(f"[SUB HANDLER] Result: {result}")

                                    if result['status'] == 'success':
                                        sub_type = "gifted" if result.get('gift_count', 1) > 1 else "subscribed"
                                        print(f"[Raffle] 🎁 {result['gifter']} {sub_type} → +{result['tickets_awarded']} tickets")
                                    elif result['status'] == 'not_linked':
                                        print(f"[Raffle] 🎁 {result['kick_name']} subscribed but account not linked")
                                    elif result['status'] == 'duplicate':
                                        # Already processed, silent skip
                                        pass
                                    else:
                                        print(f"[Raffle] ⚠️ Failed to process gifted sub: {result}")
                                elif is_subscription and not gifted_sub_tracker:
                                    print(f"[SUB HANDLER] ⚠️ Subscription detected but gifted_sub_tracker is None!")

                        except json.JSONDecodeError:
                            pass
                        except Exception as e:
                            print(f"[Kick] Error parsing message: {e}")

                    except asyncio.TimeoutError:
                        # Check for settings changes on timeout
                        guild_settings.refresh()
                        new_chatroom_id = guild_settings.kick_chatroom_id or KICK_CHATROOM_ID
                        if new_chatroom_id and new_chatroom_id != current_chatroom_id:
                            print(f"[Kick][Guild {guild_id}] 🔄 Detected chatroom ID change during timeout for THIS GUILD: {current_chatroom_id} → {new_chatroom_id}")
                            print(f"[Kick][Guild {guild_id}] Breaking connection to reconnect with new chatroom (other guilds unaffected)...")
                            break  # Break inner loop to reconnect
                        
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
# Point Reward System
# -------------------------
async def award_points_for_watchtime(active_usernames: list, guild_id: Optional[int] = None):
    """
    Award points to users based on their new watchtime.
    Similar to raffle ticket system but tracks points separately.
    Only awards points for NEW watchtime since last conversion.
    
    Args:
        active_usernames: List of usernames to award points to
        guild_id: Discord guild/server ID for multi-server support
    """
    try:
        # Multiserver: Require guild_id parameter
        if not guild_id:
            print("[Points] ⚠️ No guild_id provided for award_points")
            return
        server_id = guild_id
            
        # Get point settings from database
        points_per_5min = 1  # Default: 1 point per 5 minutes
        sub_points_per_5min = 2  # Default: 2 points per 5 minutes for subs

        with engine.connect() as conn:
            # Load settings (multiserver: filter by server_id)
            result = conn.execute(text("""
                SELECT key, value FROM point_settings
                WHERE key IN ('points_per_5min', 'sub_points_per_5min')
                AND (discord_server_id = :sid OR discord_server_id IS NULL)
                ORDER BY discord_server_id NULLS FIRST
            """), {"sid": server_id}).fetchall()

            for key, value in result:
                if key == 'points_per_5min':
                    points_per_5min = int(value)
                elif key == 'sub_points_per_5min':
                    sub_points_per_5min = int(value)

        if points_per_5min == 0 and sub_points_per_5min == 0:
            return  # Points system disabled

        with engine.begin() as conn:
            for username in active_usernames:
                try:
                    # Get current total watchtime for user (multiserver: filter by server_id)
                    result = conn.execute(text("""
                        SELECT minutes FROM watchtime 
                        WHERE username = :u AND discord_server_id = :sid
                    """), {"u": username, "sid": server_id}).fetchone()

                    if not result:
                        continue

                    total_minutes = result[0]

                    # Get how many minutes have already been converted to points (multiserver)
                    converted_result = conn.execute(text("""
                        SELECT COALESCE(SUM(minutes_converted), 0)
                        FROM points_watchtime_converted
                        WHERE kick_username = :u AND discord_server_id = :sid
                    """), {"u": username, "sid": server_id}).fetchone()

                    minutes_already_converted = converted_result[0] if converted_result else 0

                    # Calculate new minutes since last conversion
                    new_minutes = total_minutes - minutes_already_converted

                    # Only award if we have at least 5 new minutes
                    if new_minutes >= 5:
                        # Calculate points (5 minutes = 1 interval)
                        intervals = int(new_minutes // 5)
                        minutes_to_convert = intervals * 5

                        # TODO: Check if user is subscriber for bonus points
                        # For now, use regular points rate
                        points_to_award = intervals * points_per_5min

                        if points_to_award > 0:
                            # Get discord_id from links table if available (multiserver: filter by server)
                            link_result = conn.execute(text("""
                                SELECT discord_id FROM links 
                                WHERE LOWER(kick_name) = LOWER(:u) AND discord_server_id = :sid
                            """), {"u": username, "sid": server_id}).fetchone()
                            discord_id = link_result[0] if link_result else None

                            # Update or insert user points (multiserver: composite PK with discord_server_id)
                            conn.execute(text("""
                                INSERT INTO user_points (kick_username, discord_id, points, total_earned, discord_server_id, last_updated)
                                VALUES (:u, :d, :p, :p, :sid, CURRENT_TIMESTAMP)
                                ON CONFLICT(kick_username, discord_server_id) DO UPDATE SET
                                    points = user_points.points + :p,
                                    total_earned = user_points.total_earned + :p,
                                    discord_id = COALESCE(:d, user_points.discord_id),
                                    last_updated = CURRENT_TIMESTAMP
                            """), {"u": username, "d": discord_id, "p": points_to_award, "sid": server_id})

                            # Log the conversion (multiserver: add discord_server_id)
                            conn.execute(text("""
                                INSERT INTO points_watchtime_converted
                                (kick_username, minutes_converted, points_awarded, discord_server_id)
                                VALUES (:u, :m, :p, :sid)
                            """), {"u": username, "m": minutes_to_convert, "p": points_to_award, "sid": server_id})

                            if watchtime_debug_enabled:
                                print(f"[Points] ✅ {username}: +{points_to_award} points ({minutes_to_convert} min converted)")

                except Exception as e:
                    print(f"[Points] ⚠️ Error awarding points to {username}: {e}")
                    continue

    except Exception as e:
        print(f"[Points] ⚠️ Error in points award task: {e}")

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

        # Multiserver: Process each guild independently
        for guild in bot.guilds:
            server_id = guild.id
            # Get active viewers for this guild
            guild_active_viewers = active_viewers_by_guild.get(server_id, {})
            
            # Filter to active users (seen in last 5 minutes)
            active_users = {
                user: last_seen
                for user, last_seen in list(guild_active_viewers.items())
                if (datetime.now(timezone.utc) - last_seen).total_seconds() < (WATCH_INTERVAL_SECONDS + 60)
            }
            
            if not active_users:
                continue

            # Update all active users for this guild
            with engine.begin() as conn:
                for user, last_seen in active_users.items():
                    try:
                        conn.execute(text("""
                            INSERT INTO watchtime (username, minutes, last_active, discord_server_id)
                            VALUES (:u, :m, :t, :sid)
                            ON CONFLICT(username, discord_server_id) DO UPDATE SET
                                minutes = watchtime.minutes + :m,
                                last_active = :t
                        """), {
                            "u": user,
                            "m": minutes_to_add,
                            "t": last_seen.isoformat(),
                            "sid": server_id
                        })
                        if watchtime_debug_enabled:
                            print(f"[Watchtime Debug][Guild {guild.name}] ✅ Updated {user}: +{minutes_to_add} minutes")
                    except Exception as e:
                        print(f"⚠️ Error updating watchtime for {user}: {e}")
                        continue  # Skip this user but continue with others

            # Award points for new watchtime (runs after watchtime update)
            await award_points_for_watchtime(list(active_users.keys()), guild_id=server_id)

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
        # Multiserver: Update roles for all guilds
        for guild in bot.guilds:
            try:
                # Validate bot permissions
                if not guild.me.guild_permissions.manage_roles:
                    print(f"⚠️ [Guild {guild.name}] Bot lacks manage_roles permission!")
                    continue

                # Load current role configuration from database
                current_roles = load_watchtime_roles()

                # Cache role objects and validate they exist
                role_cache = {}
                for role_info in current_roles:
                    role = discord.utils.get(guild.roles, name=role_info["name"])
                    if not role:
                        print(f"⚠️ [Guild {guild.name}] Role {role_info['name']} not found in server!")
                        continue
                    role_cache[role_info["name"]] = role

                # Get linked users with watchtime for this guild
                with engine.connect() as conn:
                    rows = conn.execute(text("""
                        SELECT l.discord_id, w.minutes, l.kick_name
                        FROM links l
                        JOIN watchtime w ON l.kick_name = w.username AND l.discord_server_id = w.discord_server_id
                        WHERE l.discord_server_id = :sid
                    """), {"sid": guild.id}).fetchall()

                # Update roles for each user
                for discord_id, minutes, kick_name in rows:
                    member = guild.get_member(int(discord_id))
                    if not member:
                        continue

                    # Assign all eligible roles
                    for role_info in current_roles:
                        role = role_cache.get(role_info["name"])
                        if role and minutes >= role_info["minutes"] and role not in member.roles:
                            try:
                                await member.add_roles(role, reason=f"Reached {role_info['minutes']} min watchtime")
                                print(f"[Guild {guild.name}] Assigned {role.name} to {member.display_name} ({kick_name})")

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
                                    print(f"[Guild {guild.name}] Sent role notification DM to {member.display_name}")
                                except discord.Forbidden:
                                    pass  # User has DMs disabled
                                except Exception as dm_error:
                                    print(f"[Guild {guild.name}] Error sending DM: {dm_error}")

                            except discord.Forbidden:
                                print(f"[Guild {guild.name}] Missing permission to assign {role.name}")
                            except Exception as e:
                                print(f"[Guild {guild.name}] Error assigning role: {e}")

            except Exception as guild_error:
                print(f"⚠️ [Guild {guild.name}] Role update error: {guild_error}")
                
    except Exception as e:
        print(f"⚠️ Error in role update task: {e}")
        import traceback
        traceback.print_exc()

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
                                # Multiserver: Try all guilds where the user is a member
                                for guild in bot.guilds:
                                    if not guild:
                                        continue
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

@tasks.loop(seconds=30)
async def clip_buffer_management_task():
    """
    Monitor stream status and manage clip buffer on Dashboard.

    - When stream goes LIVE: Start clip buffer on Dashboard
    - When stream goes OFFLINE: Stop clip buffer on Dashboard

    This ensures the clip buffer is always recording when the stream is live,
    so clips can capture the past 30+ seconds of footage.
    """
    global clip_buffer_active, last_stream_live_state

    try:
        # Get settings from database
        if not hasattr(bot, 'settings_manager') or not bot.settings_manager:
            print(f"[Clip Buffer] ⚠️ settings_manager not initialized")
            return

        # Refresh settings to get latest values
        bot.settings_manager.refresh()

        dashboard_url = bot.settings_manager.dashboard_url
        bot_api_key = bot.settings_manager.bot_api_key
        kick_channel = bot.settings_manager.kick_channel

        if not dashboard_url or not bot_api_key or not kick_channel:
            print(f"[Clip Buffer] ⚠️ Missing configuration: dashboard_url={bool(dashboard_url)}, bot_api_key={bool(bot_api_key)}, kick_channel={kick_channel}")
            return

        # Check if stream is currently live
        try:
            is_live = await check_stream_live(kick_channel)
            print(f"[Clip Buffer] Stream live check for '{kick_channel}': {is_live} | Last state: {last_stream_live_state} | Buffer active: {clip_buffer_active}")
        except Exception as e:
            # Cloudflare block or other error - skip this iteration
            if "403" not in str(e) and "Cloudflare" not in str(e):
                print(f"[Clip Buffer] ⚠️ Error checking stream status: {e}")
            return

        # Detect state transitions
        should_start_buffer = False
        if last_stream_live_state is None:
            # First run - initialize state
            last_stream_live_state = is_live
            if is_live:
                print(f"[Clip Buffer] 🎬 Stream is already live on startup, starting buffer...")
                should_start_buffer = True
            else:
                print(f"[Clip Buffer] 📴 Stream is offline on startup")

        # If stream is live but buffer is not active, check if we need to start it
        if is_live and not clip_buffer_active and not should_start_buffer:
            # Verify buffer status with dashboard
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        f'{dashboard_url}/api/clips/buffer/status?channel={kick_channel}',
                        timeout=aiohttp.ClientTimeout(total=10)
                    ) as response:
                        if response.status == 404:
                            # No buffer exists, need to start it
                            print(f"[Clip Buffer] 🔄 Stream is live but no buffer running, starting...")
                            should_start_buffer = True
                        elif response.status == 200:
                            status = await response.json()
                            if status.get('is_recording'):
                                clip_buffer_active = True
                                print(f"[Clip Buffer] ℹ️ Buffer already running")
                            else:
                                print(f"[Clip Buffer] ⚠️ Buffer exists but not recording, restarting...")
                                should_start_buffer = True
            except Exception as e:
                print(f"[Clip Buffer] ⚠️ Error checking buffer status: {e}")
        
        # Periodic verification: Even if we think buffer is active, verify with dashboard
        elif is_live and clip_buffer_active:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        f'{dashboard_url}/api/clips/buffer/status?channel={kick_channel}',
                        timeout=aiohttp.ClientTimeout(total=10)
                    ) as response:
                        if response.status == 404:
                            # Buffer disappeared (dashboard restarted?)
                            print(f"[Clip Buffer] ⚠️ Buffer disappeared! Restarting...")
                            clip_buffer_active = False
                            should_start_buffer = True
                        elif response.status == 200:
                            status = await response.json()
                            if not status.get('is_recording'):
                                print(f"[Clip Buffer] ⚠️ Buffer stopped recording! Restarting...")
                                clip_buffer_active = False
                                should_start_buffer = True
            except Exception as e:
                print(f"[Clip Buffer] ⚠️ Error verifying buffer status: {e}")

        # Handle transition: OFFLINE -> LIVE (or first run while live)
        if (is_live and not last_stream_live_state) or should_start_buffer:
            if not should_start_buffer:
                print(f"[Clip Buffer] 🟢 Stream went LIVE! Starting clip buffer...")
            
            # Use the robust playback URL fetcher with caching and validation
            playback_url: Optional[str] = None
            try:
                from core.kick_api import get_playback_url
                # Force refresh if this is a new live transition (not a retry)
                force_refresh = not should_start_buffer
                playback_url = await get_playback_url(kick_channel, force_refresh=force_refresh)
                
                if playback_url:
                    print(f"[Clip Buffer] 📺 Obtained playback URL: {playback_url[:80]}...")
                else:
                    print(f"[Clip Buffer] ⚠️ No playback URL available")
                    print(f"[Clip Buffer] 💡 Set KICK_PLAYBACK_URL env var for manual override")
            except Exception as e:
                print(f"[Clip Buffer] ⚠️ Error fetching playback URL: {e}")
                # Don't set to None here - keep whatever value we had

            try:
                print(f"[Clip Buffer] Sending start request to {dashboard_url}/api/clips/buffer/start")
                async with aiohttp.ClientSession() as session:
                    headers = {
                        'X-API-Key': bot_api_key,
                        'Content-Type': 'application/json'
                    }
                    payload = {'channel': kick_channel}
                    if playback_url:
                        payload['playback_url'] = playback_url
                        print(f"[Clip Buffer] 📤 Including playback_url in request")
                    else:
                        print(f"[Clip Buffer] ⚠️ No playback_url to include - dashboard will attempt fetch")
                    
                    async with session.post(
                        f'{dashboard_url}/api/clips/buffer/start',
                        headers=headers,
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=30)
                    ) as response:
                        response_text = await response.text()
                        print(f"[Clip Buffer] Start response: HTTP {response.status} - {response_text}")
                        if response.status == 200:
                            result = await response.json()
                            clip_buffer_active = True
                            print(f"[Clip Buffer] ✅ Buffer started: {result.get('message', 'OK')}")
                        else:
                            print(f"[Clip Buffer] ❌ Failed to start buffer: HTTP {response.status} - {response_text}")
            except Exception as e:
                print(f"[Clip Buffer] ❌ Error starting buffer: {e}")
                import traceback
                traceback.print_exc()

        # Handle transition: LIVE -> OFFLINE
        elif not is_live and last_stream_live_state:
            print(f"[Clip Buffer] 🔴 Stream went OFFLINE! Stopping clip buffer...")
            try:
                async with aiohttp.ClientSession() as session:
                    headers = {
                        'X-API-Key': bot_api_key,
                        'Content-Type': 'application/json'
                    }
                    async with session.post(
                        f'{dashboard_url}/api/clips/buffer/stop',
                        headers=headers,
                        json={'channel': kick_channel},
                        timeout=aiohttp.ClientTimeout(total=30)
                    ) as response:
                        if response.status == 200:
                            result = await response.json()
                            clip_buffer_active = False
                            print(f"[Clip Buffer] ✅ Buffer stopped: {result.get('message', 'OK')}")
                        else:
                            error = await response.text()
                            print(f"[Clip Buffer] ⚠️ Failed to stop buffer: HTTP {response.status} - {error}")
            except Exception as e:
                print(f"[Clip Buffer] ⚠️ Error stopping buffer: {e}")

        # Update last known state
        last_stream_live_state = is_live

    except Exception as e:
        print(f"[Clip Buffer] ❌ Error in buffer management task: {e}")
        import traceback
        traceback.print_exc()

@clip_buffer_management_task.before_loop
async def before_clip_buffer_task():
    """Wait for bot to be ready before starting clip buffer management."""
    await bot.wait_until_ready()
    # Initial delay to allow settings to load
    await asyncio.sleep(10)
    print("[Clip Buffer] 🎬 Starting clip buffer management task...")
    print(f"[Clip Buffer] Settings manager initialized: {hasattr(bot, 'settings_manager') and bot.settings_manager is not None}")
    if hasattr(bot, 'settings_manager') and bot.settings_manager:
        bot.settings_manager.refresh()
        print(f"[Clip Buffer] dashboard_url: {bool(bot.settings_manager.dashboard_url)}")
        print(f"[Clip Buffer] bot_api_key: {bool(bot.settings_manager.bot_api_key)}")
        print(f"[Clip Buffer] kick_channel: {bot.settings_manager.kick_channel}")

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
# Note: Commands now work in all guilds (multiserver support)
# Each guild has its own settings loaded dynamically

@bot.command(name="link")
@progressive_cooldown(base_seconds=10, increment_seconds=10, max_seconds=60)
async def cmd_link(ctx):
    """Link your Kick account using OAuth (instant, no bio editing required)."""

    if not OAUTH_BASE_URL or not KICK_CLIENT_ID:
        await ctx.send("❌ OAuth linking is not configured on this bot.")
        return

    discord_id = ctx.author.id
    guild_id = ctx.guild.id if ctx.guild else None

    # Check if already linked
    with engine.connect() as conn:
        existing = conn.execute(text(
            "SELECT kick_name FROM links WHERE discord_id = :d AND discord_server_id = :g"
        ), {"d": discord_id, "g": guild_id}).fetchone()

        if existing:
            await ctx.send(
                f"✅ You are already linked to **{existing[0]}**.\n"
                f"Contact an admin if you need to unlink your account."
            )
            return

    # Generate cryptographically signed OAuth URL
    oauth_url = generate_signed_oauth_url(discord_id, guild_id)

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
        # Delete any existing pending OAuth for this user in this guild
        conn.execute(text("DELETE FROM oauth_notifications WHERE discord_id = :d AND discord_server_id = :g AND processed = FALSE"), {"d": discord_id, "g": guild_id})

        # Store message info (will be updated with kick_username when OAuth completes)
        conn.execute(text("""
            INSERT INTO oauth_notifications (discord_id, kick_username, channel_id, message_id, processed, discord_server_id)
            VALUES (:d, '', :c, :m, FALSE, :g)
        """), {"d": discord_id, "c": ctx.channel.id, "m": message.id, "g": guild_id})

@bot.command(name="unlink")
@commands.has_permissions(manage_guild=True)

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
    guild_id = ctx.guild.id if ctx.guild else None

    # Check if user has a linked account
    with engine.connect() as conn:
        existing = conn.execute(text(
            "SELECT kick_name FROM links WHERE discord_id = :d AND discord_server_id = :guild_id"
        ), {"d": discord_id, "guild_id": guild_id}).fetchone()

    if not existing:
        await ctx.send(f"❌ {member.mention} doesn't have a linked Kick account.")
        return

    kick_name = existing[0]

    # Unlink without confirmation (admin action)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM links WHERE discord_id = :d AND discord_server_id = :guild_id"), {"d": discord_id, "guild_id": guild_id})

        # Also clean up any pending OAuth notifications
        conn.execute(text("DELETE FROM oauth_notifications WHERE discord_id = :d AND discord_server_id = :guild_id"), {"d": discord_id, "guild_id": guild_id})

        # Clean up pending verifications
        conn.execute(text("DELETE FROM pending_links WHERE discord_id = :d AND discord_server_id = :guild_id"), {"d": discord_id, "guild_id": guild_id})

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

    guild_id = ctx.guild.id if ctx.guild else None
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT username, minutes FROM watchtime WHERE discord_server_id = :guild_id ORDER BY minutes DESC LIMIT :n"
        ), {"n": top, "guild_id": guild_id}).fetchall()

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

async def cmd_watchtime(ctx, kick_username: str = None):
    """
    Check watchtime for yourself or another user.
    Usage: !watchtime (check your own) or !watchtime <kick_username> (admins only)
    """
    discord_id = ctx.author.id
    is_admin = ctx.guild and ctx.author.guild_permissions.administrator

    guild_id = ctx.guild.id if ctx.guild else None
    with engine.connect() as conn:
        # If kick_username provided, check if admin
        if kick_username:
            if not is_admin:
                await ctx.send("❌ Only administrators can check other users' watchtime.")
                return

            # Admin lookup by Kick username
            kick_name = kick_username.lower()
            watchtime = conn.execute(text(
                "SELECT minutes FROM watchtime WHERE username = :u AND discord_server_id = :guild_id"
            ), {"u": kick_name, "guild_id": guild_id}).fetchone()

            if not watchtime or watchtime[0] == 0:
                await ctx.send(
                    f"⏱️ No watchtime recorded for **{kick_name}**."
                )
                return
        else:
            # Regular user checking their own watchtime
            link = conn.execute(text(
                "SELECT kick_name FROM links WHERE discord_id = :d AND discord_server_id = :guild_id"
            ), {"d": discord_id, "guild_id": guild_id}).fetchone()

            if not link:
                await ctx.send(
                    "❌ You haven't linked your Kick account yet."
                )
                return

            kick_name = link[0]

            # Get watchtime
            watchtime = conn.execute(text(
                "SELECT minutes FROM watchtime WHERE username = :u AND discord_server_id = :guild_id"
            ), {"u": kick_name, "guild_id": guild_id}).fetchone()

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
  # 🔒 SECURITY: Ensure command only works in the configured guild
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
                    INSERT INTO bot_settings (key, value, discord_server_id, updated_at)
                    VALUES ('tracking_force_override', 'true', :guild_id, CURRENT_TIMESTAMP)
                    ON CONFLICT (key, discord_server_id) DO UPDATE SET
                        value = 'true',
                        updated_at = CURRENT_TIMESTAMP
                """), {"guild_id": ctx.guild.id})
            await ctx.send("🔒 **Watchtime FORCE override ENABLED**\nWatchtime updates will run regardless of live-detection checks.")
        elif subaction.lower() == "off":
            tracking_force_override = False
            # Save to database
            with engine.begin() as conn:
                conn.execute(text("""
                    INSERT INTO bot_settings (key, value, discord_server_id, updated_at)
                    VALUES ('tracking_force_override', 'false', :guild_id, CURRENT_TIMESTAMP)
                    ON CONFLICT (key, discord_server_id) DO UPDATE SET
                        value = 'false',
                        updated_at = CURRENT_TIMESTAMP
                """), {"guild_id": ctx.guild.id})
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

@bot.command(name="callblacklist", aliases=["srblacklist", "blockslotcall"])
@commands.has_permissions(administrator=True)

async def slot_call_blacklist(ctx, action: str = None, kick_username: str = None, *, reason: str = None):
    """
    Admin command to blacklist Kick users from using !call/!sr commands.
    Usage:
      !callblacklist add <kick_username> [reason]
      !callblacklist remove <kick_username>
      !callblacklist list
      !callblacklist check <kick_username>
    """
    if action is None or action.lower() not in ["add", "remove", "list", "check"]:
        await ctx.send(
            "**Slot Call Blacklist Management**\n\n"
            "**Usage:**\n"
            "• `!callblacklist add <kick_username> [reason]` - Block a user from using !call/!sr\n"
            "• `!callblacklist remove <kick_username>` - Unblock a user\n"
            "• `!callblacklist list` - Show all blacklisted users\n"
            "• `!callblacklist check <kick_username>` - Check if a user is blacklisted"
        )
        return

    if action.lower() == "add":
        if not kick_username:
            await ctx.send("❌ Please provide a Kick username: `!callblacklist add <kick_username> [reason]`")
            return

        kick_username_lower = kick_username.lower()

        with engine.begin() as conn:
            # Check if already blacklisted
            existing = conn.execute(text("""
                SELECT 1 FROM slot_call_blacklist WHERE kick_username = :username AND discord_server_id = :guild_id
            """), {"username": kick_username_lower, "guild_id": ctx.guild.id}).fetchone()

            if existing:
                await ctx.send(f"⚠️ User `{kick_username}` is already blacklisted.")
                return

            # Add to blacklist
            conn.execute(text("""
                INSERT INTO slot_call_blacklist (kick_username, reason, blacklisted_by, discord_server_id)
                VALUES (:username, :reason, :admin_id, :guild_id)
            """), {
                "username": kick_username_lower,
                "reason": reason or "No reason provided",
                "admin_id": ctx.author.id,
                "guild_id": ctx.guild.id
            })

        await ctx.send(
            f"✅ **User blacklisted from !call/!sr**\n"
            f"**Kick Username:** `{kick_username}`\n"
            f"**Reason:** {reason or 'No reason provided'}\n"
            f"**By:** {ctx.author.mention}"
        )

    elif action.lower() == "remove":
        if not kick_username:
            await ctx.send("❌ Please provide a Kick username: `!callblacklist remove <kick_username>`")
            return

        kick_username_lower = kick_username.lower()

        with engine.begin() as conn:
            result = conn.execute(text("""
                DELETE FROM slot_call_blacklist WHERE kick_username = :username AND discord_server_id = :guild_id
            """), {"username": kick_username_lower, "guild_id": ctx.guild.id})

            if result.rowcount == 0:
                await ctx.send(f"⚠️ User `{kick_username}` is not blacklisted.")
                return

        await ctx.send(f"✅ User `{kick_username}` removed from !call/!sr blacklist.")

    elif action.lower() == "list":
        with engine.connect() as conn:
            results = conn.execute(text("""
                SELECT kick_username, reason, created_at
                FROM slot_call_blacklist
                WHERE discord_server_id = :guild_id
                ORDER BY created_at DESC
            """), {"guild_id": ctx.guild.id}).fetchall()

            if not results:
                await ctx.send("📋 No users are currently blacklisted from !call/!sr commands.")
                return

            embed = discord.Embed(
                title="🚫 Slot Call Blacklist",
                description=f"**{len(results)}** blacklisted user(s)",
                color=discord.Color.red()
            )

            for username, reason, created_at in results[:25]:  # Limit to 25 for embed
                embed.add_field(
                    name=f"👤 {username}",
                    value=f"**Reason:** {reason}\n**Added:** {created_at.strftime('%Y-%m-%d')}",
                    inline=False
                )

            if len(results) > 25:
                embed.set_footer(text=f"Showing first 25 of {len(results)} blacklisted users")

            await ctx.send(embed=embed)

    elif action.lower() == "check":
        if not kick_username:
            await ctx.send("❌ Please provide a Kick username: `!callblacklist check <kick_username>`")
            return

        kick_username_lower = kick_username.lower()

        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT reason, blacklisted_by, created_at
                FROM slot_call_blacklist
                WHERE kick_username = :username AND discord_server_id = :guild_id
            """), {"username": kick_username_lower, "guild_id": ctx.guild.id}).fetchone()

            if not result:
                await ctx.send(f"✅ User `{kick_username}` is **NOT** blacklisted.")
                return

            reason, admin_id, created_at = result
            admin = await bot.fetch_user(admin_id) if admin_id else None

            await ctx.send(
                f"🚫 User `{kick_username}` is **BLACKLISTED**\n"
                f"**Reason:** {reason}\n"
                f"**Added by:** {admin.mention if admin else 'Unknown'}\n"
                f"**Date:** {created_at.strftime('%Y-%m-%d %H:%M UTC')}"
            )

@slot_call_blacklist.error
async def slot_call_blacklist_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ You need administrator permissions to use this command.")

@bot.command(name="roles")
@commands.has_permissions(administrator=True)

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
        guild_id = ctx.guild.id if ctx.guild else None
        with engine.connect() as conn:
            roles = conn.execute(text("""
                SELECT role_name, minutes_required, enabled, display_order
                FROM watchtime_roles
                WHERE discord_server_id = :guild_id
                ORDER BY display_order ASC
            """), {"guild_id": guild_id}).fetchall()

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
            guild_id = ctx.guild.id if ctx.guild else None
            with engine.begin() as conn:
                # Get highest display order for this guild
                max_order = conn.execute(text("SELECT COALESCE(MAX(display_order), 0) FROM watchtime_roles WHERE discord_server_id = :guild_id"), {"guild_id": guild_id}).fetchone()[0]

                # Insert new role
                conn.execute(text("""
                    INSERT INTO watchtime_roles (role_name, minutes_required, display_order, enabled, discord_server_id)
                    VALUES (:name, :minutes, :order, TRUE, :guild_id)
                """), {"name": role_name, "minutes": minutes, "order": max_order + 1, "guild_id": guild_id})

            await ctx.send(f"✅ Added role **{role_name}** at **{minutes:,} minutes** ({minutes/60:.1f} hours)")
        except Exception as e:
            await ctx.send(f"❌ Error adding role: {e}")

    elif action.lower() == "update":
        if not role_name or minutes is None:
            await ctx.send("❌ Usage: `!roles update <role_name> <minutes>`\nExample: `!roles update \"Tier 1\" 180`")
            return

        try:
            guild_id = ctx.guild.id if ctx.guild else None
            with engine.begin() as conn:
                result = conn.execute(text("""
                    UPDATE watchtime_roles
                    SET minutes_required = :minutes, updated_at = CURRENT_TIMESTAMP
                    WHERE role_name = :name AND discord_server_id = :guild_id
                    RETURNING id
                """), {"name": role_name, "minutes": minutes, "guild_id": guild_id}).fetchone()

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
            guild_id = ctx.guild.id if ctx.guild else None
            with engine.begin() as conn:
                result = conn.execute(text("""
                    DELETE FROM watchtime_roles
                    WHERE role_name = :name AND discord_server_id = :guild_id
                    RETURNING id
                """), {"name": role_name, "guild_id": guild_id}).fetchone()

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
            guild_id = ctx.guild.id if ctx.guild else None
            with engine.begin() as conn:
                result = conn.execute(text("""
                    UPDATE watchtime_roles
                    SET enabled = :enabled, updated_at = CURRENT_TIMESTAMP
                    WHERE role_name = :name AND discord_server_id = :guild_id
                    RETURNING id
                """), {"name": role_name, "enabled": enabled, "guild_id": guild_id}).fetchone()

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

@bot.command(name="testsub")
@commands.has_permissions(administrator=True)

async def test_subscription(ctx, kick_username: str = None, sub_count: int = 1):
    """
    [ADMIN/DEBUG] Simulate a subscription event to test raffle ticket awarding
    Usage: !testsub <kick_username> [sub_count]
    Example: !testsub testuser123 5  (simulates 5 gifted subs)
    """
    guild_id = ctx.guild.id if ctx.guild else None
    if not guild_id:
        await ctx.send("❌ This command must be used in a server.")
        return
    
    gifted_sub_tracker = gifted_sub_trackers.get(guild_id)

    if not gifted_sub_tracker:
        await ctx.send("❌ **Gifted sub tracker not initialized for this server!**\n\n"
                       "**Possible reasons:**\n"
                       "• Bot is still starting up (wait a few seconds)\n"
                       "• Database connection failed\n"
                       "• Raffle system initialization error\n\n"
                       "Check the bot console for error messages.")
        return

    if not kick_username:
        await ctx.send("❌ Usage: `!testsub <kick_username> [sub_count]`\nExample: `!testsub testuser123 5`")
        return

    # Create a fake subscription event that matches Kick's structure
    fake_event = {
        "id": f"test_{int(datetime.now().timestamp())}",
        "sender": {
            "username": kick_username,
            "id": 99999
        },
        "gift_count": sub_count if sub_count > 1 else None,
        "months": 1 if sub_count == 1 else None
    }

    await ctx.send(f"🧪 **Testing subscription event...**\n"
                   f"User: `{kick_username}`\n"
                   f"Type: {'Gifted ' + str(sub_count) + ' subs' if sub_count > 1 else 'Regular subscription'}")

    # Process the fake event
    result = await gifted_sub_tracker.handle_gifted_sub_event(fake_event)

    # Show results
    embed = discord.Embed(
        title="🧪 Test Subscription Result",
        color=discord.Color.green() if result['status'] == 'success' else discord.Color.red(),
        timestamp=datetime.utcnow()
    )

    embed.add_field(name="Status", value=result['status'], inline=True)
    embed.add_field(name="Kick Username", value=kick_username, inline=True)
    embed.add_field(name="Sub Count", value=str(sub_count), inline=True)

    if result['status'] == 'success':
        embed.add_field(name="✅ Tickets Awarded", value=str(result['tickets_awarded']), inline=True)
        embed.add_field(name="Discord ID", value=str(result['discord_id']), inline=True)
        embed.description = f"Successfully awarded **{result['tickets_awarded']} tickets** to {result['gifter']}"
    elif result['status'] == 'not_linked':
        embed.description = f"❌ User `{kick_username}` is not linked to a Discord account.\nThey need to use `!link` to connect their accounts."
        embed.add_field(name="Note", value="Sub was logged but no tickets awarded", inline=False)
    elif result['status'] == 'duplicate':
        embed.description = f"⚠️ This event was already processed (duplicate)"
    elif result['status'] == 'no_active_period':
        embed.description = f"❌ No active raffle period found.\nUse raffle commands to create a new period."
    else:
        embed.description = f"❌ Error: {result.get('error', 'Unknown error')}"

    embed.set_footer(text=f"Test performed by {ctx.author.name}")
    await ctx.send(embed=embed)

@test_subscription.error
async def test_subscription_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ You need administrator permissions to use this command.")

@bot.command(name="convertwatchtime")
@commands.has_permissions(administrator=True)

async def convert_watchtime_manual(ctx):
    """
    [ADMIN/DEBUG] Manually trigger watchtime to tickets conversion
    Usage: !convertwatchtime
    """
    if not engine:
        await ctx.send("❌ Database not initialized!")
        return

    await ctx.send("🔄 Converting watchtime to raffle tickets...")

    try:
        from raffle_system.watchtime_converter import WatchtimeConverter
        converter = WatchtimeConverter(engine)
        result = await converter.convert_watchtime_to_tickets()

        embed = discord.Embed(
            title="🎟️ Watchtime Conversion Result",
            color=discord.Color.blue() if result['status'] == 'success' else discord.Color.red(),
            timestamp=datetime.utcnow()
        )

        embed.add_field(name="Status", value=result['status'], inline=True)
        embed.add_field(name="Users Converted", value=str(result.get('conversions', 0)), inline=True)

        if result['status'] == 'success' and result.get('details'):
            details_text = "\n".join([
                f"• **{d['kick_name']}**: {d['hours_converted']}h → {d['tickets_awarded']} tickets"
                for d in result['details'][:10]
            ])
            embed.add_field(name="Conversions", value=details_text or "None", inline=False)
        elif result['status'] == 'no_active_period':
            embed.description = "❌ No active raffle period found"
        elif result['status'] == 'no_users':
            embed.description = "ℹ️ No linked users with convertible watchtime (need 60+ minutes)"
        elif result['status'] == 'error':
            embed.description = f"❌ Error: {result.get('error', 'Unknown')}"

        await ctx.send(embed=embed)

    except Exception as e:
        await ctx.send(f"❌ Error: {str(e)}")

@convert_watchtime_manual.error
async def convert_watchtime_manual_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ You need administrator permissions to use this command.")

@bot.command(name="fixwatchtime")
@commands.has_permissions(administrator=True)

async def fix_watchtime_for_current_period(ctx):
    """
    [ADMIN] Fix watchtime tracking for current period by snapshotting existing totals
    This prevents re-awarding tickets for old watchtime
    Usage: !fixwatchtime
    """
    if not engine:
        await ctx.send("❌ Database not initialized!")
        return

    await ctx.send("🔄 Fixing watchtime tracking for current period...")

    try:
        from raffle_system.database import get_current_period

        # Get current period
        period = get_current_period(engine)
        if not period:
            await ctx.send("❌ No active raffle period found!")
            return

        period_id = period['id']

        with engine.begin() as conn:
            # First, get list of users who don't have a snapshot yet
            users_to_snapshot = conn.execute(text("""
                SELECT w.username, w.minutes
                FROM watchtime w
                WHERE w.minutes > 0
                AND NOT EXISTS (
                    SELECT 1 FROM raffle_watchtime_converted c
                    WHERE c.period_id = :period_id
                    AND LOWER(c.kick_name) = LOWER(w.username)
                )
            """), {'period_id': period_id}).fetchall()

            # Insert snapshots for users without one
            affected = 0
            for username, minutes in users_to_snapshot:
                conn.execute(text("""
                    INSERT INTO raffle_watchtime_converted (period_id, kick_name, minutes_converted, tickets_awarded)
                    VALUES (:period_id, :username, :minutes, 0)
                """), {'period_id': period_id, 'username': username, 'minutes': minutes})
                affected += 1

        embed = discord.Embed(
            title="✅ Watchtime Tracking Fixed",
            description=f"Snapshotted current watchtime for period #{period_id}",
            color=discord.Color.green(),
            timestamp=datetime.utcnow()
        )

        embed.add_field(name="Users Updated", value=str(affected), inline=True)
        embed.add_field(name="Effect", value="Only NEW watchtime will be converted from now on", inline=False)

        await ctx.send(embed=embed)

    except Exception as e:
        await ctx.send(f"❌ Error: {str(e)}")

@fix_watchtime_for_current_period.error
async def fix_watchtime_for_current_period_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ You need administrator permissions to use this command.")

@bot.command(name="checkwatchtime")

async def check_watchtime_conversion(ctx, kick_username: str = None):
    """
    Check watchtime conversion status for a user
    Usage: !checkwatchtime [kick_username]
    """
    if not engine:
        await ctx.send("❌ Database not initialized!")
        return

    # If no username provided, try to get from links table
    if not kick_username:
        try:
            with engine.connect() as conn:
                result = conn.execute(text("""
                    SELECT kick_name FROM links
                    WHERE discord_id = :discord_id AND discord_server_id = :guild_id
                """), {'discord_id': ctx.author.id, 'guild_id': ctx.guild.id})
                row = result.fetchone()
                if row:
                    kick_username = row[0]
                else:
                    await ctx.send("❌ You need to link your account first using `!link <kick_username>`")
                    return
        except Exception as e:
            await ctx.send(f"❌ Error looking up your linked account: {e}")
            return

    try:
        from raffle_system.watchtime_converter import WatchtimeConverter
        converter = WatchtimeConverter(engine)
        info = converter.get_unconverted_watchtime(kick_username)

        if not info:
            await ctx.send(f"❌ No watchtime data found for **{kick_username}**")
            return

        embed = discord.Embed(
            title=f"⏱️ Watchtime Status: {kick_username}",
            color=discord.Color.blue(),
            timestamp=datetime.utcnow()
        )

        total_hours = info['total_minutes'] / 60
        converted_hours = info['converted_minutes'] / 60
        unconverted_hours = info['unconverted_minutes'] / 60

        embed.add_field(name="Total Watchtime", value=f"{total_hours:.1f}h ({info['total_minutes']} min)", inline=False)
        embed.add_field(name="Already Converted", value=f"{converted_hours:.1f}h ({info['converted_minutes']} min)", inline=True)
        embed.add_field(name="Not Yet Converted", value=f"{unconverted_hours:.1f}h ({info['unconverted_minutes']} min)", inline=True)
        embed.add_field(name="Convertible Now", value=f"{info['convertible_hours']}h → {info['potential_tickets']} tickets", inline=False)

        if info['unconverted_minutes'] < 60:
            embed.set_footer(text=f"Need {60 - info['unconverted_minutes']} more minutes to convert next hour")
        else:
            embed.set_footer(text="Watchtime converts automatically every 10 minutes")

        await ctx.send(embed=embed)

    except Exception as e:
        await ctx.send(f"❌ Error: {str(e)}")

@bot.command(name="commandlist", aliases=["commands"])

async def command_list(ctx):
    """
    Show available bot commands for regular users
    Usage: !commandlist or !commands
    """
    embed = discord.Embed(
        title="📋 User Commands",
        description="Commands available to everyone",
        color=discord.Color.blue(),
        timestamp=datetime.utcnow()
    )

    # Account Linking
    embed.add_field(
        name="🔗 Account Linking",
        value=(
            "`!link <kick_username>` - Link your Kick account\n"
            "`!unlink` - Unlink your Kick account"
        ),
        inline=False
    )

    # Watchtime & Stats
    embed.add_field(
        name="⏱️ Watchtime & Stats",
        value=(
            "`!watchtime [user]` - Check your or someone's watchtime\n"
            "`!leaderboard` - View watchtime leaderboard\n"
            "`!checkwatchtime [kick_username]` - Check watchtime conversion status"
        ),
        inline=False
    )

    # Raffle System
    embed.add_field(
        name="🎰 Monthly Raffle",
        value=(
            "`!tickets` - View your raffle tickets\n"
            "`!raffleboard` - View ticket leaderboard\n"
            "`!raffleinfo` - View raffle period information\n"
            "`!linkshuffle <username>` - Link gambling account for wager tracking"
        ),
        inline=False
    )

    embed.set_footer(text="Admins: Use !admincommands to see administrator commands")

    await ctx.send(embed=embed)

@bot.command(name="admincommands", aliases=["adminhelp"])
@commands.has_permissions(administrator=True)

async def admin_command_list(ctx):
    """
    Show all available administrator commands
    Usage: !admincommands or !adminhelp
    """
    embed = discord.Embed(
        title="🔧 Administrator Commands",
        description="Commands available to server administrators",
        color=discord.Color.red(),
        timestamp=datetime.utcnow()
    )

    # Tracking Control
    embed.add_field(
        name="� Tracking Control",
        value=(
            "`!tracking [on|off|status]` - Control watchtime tracking\n"
            "`!tracking force [on|off]` - Force tracking override\n"
            "`!tracking debug [on|off]` - Toggle debug mode\n"
            "`!linklogs` - View recent account links"
        ),
        inline=False
    )

    # Role Management
    embed.add_field(
        name="👥 Role Management",
        value=(
            "`!roles list` - Show role configuration\n"
            "`!roles add <name> <minutes>` - Add role threshold\n"
            "`!roles update <name> <minutes>` - Update threshold\n"
            "`!roles remove <name>` - Remove role\n"
            "`!roles enable/disable <name>` - Toggle role\n"
            "`!roles members <name>` - List members with role"
        ),
        inline=False
    )

    # Raffle Management
    embed.add_field(
        name="🎲 Raffle Management",
        value=(
            "`!rafflestart [start_day] [end_day]` - Start new raffle period\n"
            "`!raffleend` - End current raffle period\n"
            "`!raffledraw [prize]` - Draw raffle winner\n"
            "`!rafflestats [@user]` - View raffle statistics\n"
            "`!rafflegive <@user> <amount> [reason]` - Award tickets\n"
            "`!raffleremove <@user> <amount> [reason]` - Remove tickets\n"
            "`!verifyshuffle <@user> <username>` - Verify gambling account\n"
            "`!convertwatchtime` - Manually convert watchtime\n"
            "`!fixwatchtime` - Fix watchtime tracking"
        ),
        inline=False
    )

    # Slot Requests
    embed.add_field(
        name="🎰 Slot Requests",
        value=(
            "`!slotpanel` - Create/update slot request panel\n"
            "`!callblacklist add <username> [reason]` - Block user from requests\n"
            "`!callblacklist remove <username>` - Unblock user\n"
            "`!callblacklist list` - View blacklisted users"
        ),
        inline=False
    )

    # Testing & Debug
    embed.add_field(
        name="🧪 Testing & Debug",
        value=(
            "`!testsub <kick_username> [count]` - Test subscription event\n"
            "`!systemstatus` - Check system initialization\n"
            "`!health` - Bot health check"
        ),
        inline=False
    )

    # Setup Commands
    embed.add_field(
        name="⚙️ Setup",
        value=(
            "`!createlinkpanel` - Create button-based linking panel\n"
            "`!post_link_info` - Post linking instructions"
        ),
        inline=False
    )

    embed.set_footer(text="Regular users: Use !commandlist to see user commands")

    await ctx.send(embed=embed)

@bot.command(name="systemstatus")
@commands.has_permissions(administrator=True)

async def raffle_system_info(ctx):
    """
    [ADMIN/DEBUG] Check raffle system initialization status
    Usage: !systemstatus
    """
    guild_id = ctx.guild.id if ctx.guild else None
    if not guild_id:
        await ctx.send("❌ This command must be used in a server.")
        return
    
    # Get guild-specific trackers
    gifted_sub_tracker = gifted_sub_trackers.get(guild_id)
    shuffle_tracker = shuffle_trackers.get(guild_id)
    slot_call_tracker = slot_call_trackers.get(guild_id)

    embed = discord.Embed(
        title="🎰 Raffle System Status",
        color=discord.Color.blue(),
        timestamp=datetime.utcnow()
    )

    # Check each component
    sub_status = "✅ Initialized" if gifted_sub_tracker else "❌ Not initialized"
    shuffle_status = "✅ Initialized" if shuffle_tracker else "❌ Not initialized"
    slot_status = "✅ Initialized" if slot_call_tracker else "❌ Not initialized"

    embed.add_field(name="Gifted Sub Tracker", value=sub_status, inline=False)
    embed.add_field(name="Shuffle Tracker", value=shuffle_status, inline=False)
    embed.add_field(name="Slot Call Tracker", value=slot_status, inline=False)

    # Check database
    db_status = "✅ Connected" if engine else "❌ Not connected"
    embed.add_field(name="Database", value=db_status, inline=False)

    # Check active raffle period
    if engine:
        try:
            period = get_current_period(engine)
            if period:
                period_info = f"✅ Active Period #{period['id']}\n"
                period_info += f"Started: {period['start_date'].strftime('%Y-%m-%d')}\n"
                period_info += f"Status: {period['status']}"
            else:
                period_info = "❌ No active period"
            embed.add_field(name="Current Raffle Period", value=period_info, inline=False)
        except Exception as e:
            embed.add_field(name="Current Raffle Period", value=f"❌ Error: {str(e)[:100]}", inline=False)

    embed.set_footer(text=f"Bot uptime: {datetime.now() - bot.uptime_start if hasattr(bot, 'uptime_start') else 'Unknown'}")

    await ctx.send(embed=embed)

@raffle_system_info.error
async def raffle_system_info_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ You need administrator permissions to use this command.")

@bot.command(name="setup_link_panel")
@commands.has_permissions(manage_guild=True)

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
        guild_id = ctx.guild.id if ctx.guild else None
        guild_settings = get_guild_settings(guild_id) if guild_id else None
        
        if guild_settings:
            kick_channel = guild_settings.kick_channel
            kick_chatroom_id = guild_settings.kick_chatroom_id
            
            if kick_chatroom_id:
                checks.append(f"✅ **Kick Chatroom ID**: Configured ({kick_chatroom_id})")
            elif kick_channel:
                chatroom_id = await fetch_chatroom_id(kick_channel)
                if chatroom_id:
                    checks.append(f"✅ **Kick API**: Accessible (ID: {chatroom_id})")
                else:
                    checks.append(f"⚠️ **Kick API**: Could not fetch chatroom ID")
                    has_warnings = True
            else:
                checks.append(f"⚠️ **Kick Channel**: Not configured for this server")
                has_warnings = True
        else:
            checks.append(f"⚠️ **Settings**: Not loaded for this server")
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
        guild_id = ctx.guild.id if ctx.guild else None
        with engine.connect() as conn:
            tables_check = []

            # Check watchtime table for this guild
            result = conn.execute(text("SELECT COUNT(*) FROM watchtime WHERE discord_server_id = :guild_id"), {"guild_id": guild_id})
            watchtime_count = result.fetchone()[0]
            tables_check.append(f"{watchtime_count} viewers")

            # Check links table for this guild
            result = conn.execute(text("SELECT COUNT(*) FROM links WHERE discord_server_id = :guild_id"), {"guild_id": guild_id})
            links_count = result.fetchone()[0]
            tables_check.append(f"{links_count} linked accounts")

            # Check watchtime_roles table for this guild
            result = conn.execute(text("SELECT COUNT(*) FROM watchtime_roles WHERE enabled = true AND discord_server_id = :guild_id"), {"guild_id": guild_id})
            roles_count = result.fetchone()[0]
            tables_check.append(f"{roles_count} active roles")

            checks.append(f"✅ **Database Stats** (This Server): {' | '.join(tables_check)}")
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
        # Sync for all guilds
        for guild in bot.guilds:
            # Get the "Shuffle Code User" role
            shuffle_role = discord.utils.get(guild.roles, name="Shuffle Code User")
            if not shuffle_role:
                continue  # Skip guilds without this role

            # Get all verified Shuffle links for this guild
            with engine.begin() as conn:
                result = conn.execute(text("""
                    SELECT DISTINCT discord_id
                    FROM raffle_shuffle_links
                    WHERE verified = TRUE
                        AND (discord_server_id IS NULL OR discord_server_id = :guild_id)
                """), {"guild_id": guild.id})
                verified_discord_ids = {row[0] for row in result.fetchall()}

            if not verified_discord_ids:
                continue  # No verified links for this guild

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
                print(f"✅ Shuffle role sync for {guild.name}: +{added}, -{removed}")

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

    # Start Redis subscriber with Kick message callback
    kick_callback = send_kick_message if KICK_BOT_USER_TOKEN else None
    asyncio.create_task(start_redis_subscriber(bot, kick_callback))

    if kick_callback:
        print("✅ Redis subscriber will send messages to Kick chat")
    else:
        print("ℹ️  Redis subscriber started (messages logged only - set KICK_BOT_USER_TOKEN to enable Kick chat)")

    # Auto-migrate database: create bot_tokens table and add expires_at column if missing
    if engine:
        try:
            with engine.begin() as conn:
                # Create bot_tokens table if it doesn't exist
                print("🔄 Checking bot_tokens table...")
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS bot_tokens (
                        bot_username TEXT PRIMARY KEY,
                        access_token TEXT NOT NULL,
                        refresh_token TEXT NOT NULL,
                        expires_at TIMESTAMP,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """))
                print("✅ bot_tokens table ready")

                # Check if expires_at column exists (for old tables)
                result = conn.execute(text("""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name = 'bot_tokens' AND column_name = 'expires_at'
                """)).fetchone()

                if not result:
                    print("🔄 Adding expires_at column to bot_tokens table...")
                    conn.execute(text("ALTER TABLE bot_tokens ADD COLUMN expires_at TIMESTAMP"))
                    print("✅ Database migrated: expires_at column added")

                # Create slot_call_blacklist table if missing
                print("🔄 Checking slot_call_blacklist table...")
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS slot_call_blacklist (
                        kick_username TEXT,
                        discord_server_id BIGINT,
                        reason TEXT,
                        blacklisted_by BIGINT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (kick_username, discord_server_id)
                    )
                """))
                print("✅ slot_call_blacklist table ready")
        except Exception as e:
            print(f"⚠️ Database migration check failed: {e}")

    try:
        # Multiserver: Validate bot permissions for ALL guilds
        for guild in bot.guilds:
            me = guild.me
            if not me.guild_permissions.manage_roles:
                print(f"⚠️ [Guild {guild.name}] Bot lacks manage_roles permission!")
            
            # Validate roles exist
            current_roles = load_watchtime_roles()
            existing_roles = {role.name for role in guild.roles}
            for role_config in current_roles:
                if role_config["name"] not in existing_roles:
                    print(f"⚠️ [Guild {guild.name}] Role {role_config['name']} does not exist in the server!")

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

        # Start clip buffer management task
        if not clip_buffer_management_task.is_running():
            clip_buffer_management_task.start()
            print("✅ Clip buffer management task started (monitors stream status)")

        # Initialize raffle system
        try:
            global gifted_sub_tracker, shuffle_tracker, slot_call_tracker

            # Setup raffle database (creates tables if needed)
            setup_raffle_database(engine)

            # Run migrations
            migrate_add_created_at_to_shuffle_wagers(engine)
            migrate_add_platform_to_wager_tables(engine)
            migrate_add_provably_fair_to_draws(engine)

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

            # Initialize per-guild trackers and managers (without adding cogs yet)
            for guild in bot.guilds:
                print(f"[Init] Loading settings for guild {guild.name} ({guild.id})...")
                guild_settings = get_guild_settings(guild.id)
                
                # Debug: Print loaded settings
                print(f"[Init] Guild {guild.name} loaded {len(guild_settings._cache)} settings:")
                print(f"  - kick_channel: '{guild_settings.kick_channel}'")
                print(f"  - slot_calls_channel_id: {guild_settings.slot_calls_channel_id}")
                print(f"  - raffle_announcement_channel_id: {guild_settings.raffle_announcement_channel_id}")
                
                # Setup gifted sub tracker for this guild
                gifted_sub_trackers[guild.id] = setup_gifted_sub_handler(engine)
                print(f"✅ [Guild {guild.name}] Gifted sub tracker initialized")

                # Setup Shuffle wager tracker for this guild
                shuffle_trackers[guild.id] = await setup_shuffle_tracker(bot, engine)
                print(f"✅ [Guild {guild.name}] Shuffle tracker initialized")

                # Setup auto-updating leaderboard for this guild
                leaderboard_channel_id = guild_settings.raffle_leaderboard_channel_id
                auto_leaderboard = await setup_auto_leaderboard(bot, engine, leaderboard_channel_id)
                if not hasattr(bot, 'auto_leaderboards'):
                    bot.auto_leaderboards = {}
                bot.auto_leaderboards[guild.id] = auto_leaderboard
                print(f"📊 [Guild {guild.name}] Leaderboard channel: {leaderboard_channel_id or 'Not configured'}")

                # Setup raffle scheduler for this guild
                raffle_auto_draw = guild_settings.raffle_auto_draw
                raffle_channel_id = guild_settings.raffle_announcement_channel_id
                await setup_raffle_scheduler(
                    bot=bot,
                    engine=engine,
                    auto_draw=raffle_auto_draw,
                    announcement_channel_id=raffle_channel_id
                )
                print(f"✅ [Guild {guild.name}] Raffle system initialized (auto-draw: {raffle_auto_draw})")

                # Create slot call tracker for this guild (but don't register cog yet)
                from features.slot_requests.slot_calls import SlotCallTracker
                slot_calls_channel_id = guild_settings.slot_calls_channel_id
                slot_call_trackers[guild.id] = SlotCallTracker(
                    bot=bot,
                    discord_channel_id=slot_calls_channel_id,
                    kick_send_callback=send_kick_message if KICK_BOT_USER_TOKEN else None,
                    engine=engine,
                    server_id=guild.id
                )
                if not hasattr(bot, 'slot_call_trackers_by_guild'):
                    bot.slot_call_trackers_by_guild = {}
                bot.slot_call_trackers_by_guild[guild.id] = slot_call_trackers[guild.id]
                print(f"✅ [Guild {guild.name}] Slot call tracker initialized (channel: {slot_calls_channel_id or 'Not configured'})")

                # Setup Guess the Balance manager for this guild
                gtb_managers[guild.id] = GuessTheBalanceManager(engine, guild.id)
                if not hasattr(bot, 'gtb_managers_by_guild'):
                    bot.gtb_managers_by_guild = {}
                bot.gtb_managers_by_guild[guild.id] = gtb_managers[guild.id]
                print(f"✅ [Guild {guild.name}] GTB system initialized")

            # Sync Shuffle code user role (run once, not per-guild)
            await sync_shuffle_role_on_startup(bot, engine)

            # Add cogs globally (only once, not per-guild)
            # These cogs will use the per-guild trackers from bot.slot_call_trackers_by_guild
            if slot_call_trackers:
                from features.slot_requests.slot_calls import SlotCallCommands
                first_tracker = list(slot_call_trackers.values())[0]  # Use first guild's tracker for cog
                await bot.add_cog(SlotCallCommands(bot, first_tracker))
                print(f"✅ Slot call commands cog registered")

            # Create slot panels per-guild (but only add cogs once)
            first_guild = True
            for guild in bot.guilds:
                # Create panel instances
                from features.slot_requests.slot_request_panel import SlotRequestPanel
                slot_panel = SlotRequestPanel(
                    bot, 
                    engine, 
                    slot_call_trackers[guild.id],
                    kick_send_callback=send_kick_message if KICK_BOT_USER_TOKEN else None
                )
                slot_call_trackers[guild.id].panel = slot_panel
                
                if not hasattr(bot, 'slot_panels_by_guild'):
                    bot.slot_panels_by_guild = {}
                bot.slot_panels_by_guild[guild.id] = slot_panel
                print(f"✅ [Guild {guild.name}] Slot request panel initialized")

                # Setup GTB panel for this guild (just the instance, no commands)
                from features.games.gtb_panel import GTBPanel
                gtb_panel = GTBPanel(
                    bot,
                    engine,
                    gtb_managers[guild.id],
                    kick_send_callback=send_kick_message if KICK_BOT_USER_TOKEN else None
                )
                if not hasattr(bot, 'gtb_panels_by_guild'):
                    bot.gtb_panels_by_guild = {}
                bot.gtb_panels_by_guild[guild.id] = gtb_panel
                print(f"✅ [Guild {guild.name}] GTB panel initialized")
                
                # Add cogs only once on first iteration
                if first_guild:
                    from features.slot_requests.slot_request_panel import SlotRequestPanelCommands
                    await bot.add_cog(SlotRequestPanelCommands(bot, slot_panel))
                    print(f"✅ Slot request panel commands cog registered")
                    
                    # Add GTB panel command (only once)
                    @bot.command(name='creategtbpanel')
                    @commands.has_permissions(administrator=True)
                    async def create_gtb_panel_cmd(ctx):
                        """[ADMIN] Create the GTB panel in this channel"""
                        guild_panel = bot.gtb_panels_by_guild.get(ctx.guild.id)
                        if not guild_panel:
                            await ctx.send("❌ GTB panel not initialized for this server")
                            return
                        success = await guild_panel.create_panel(ctx.channel)
                        if success:
                            await ctx.send("✅ GTB panel created!")
                        else:
                            await ctx.send("❌ Failed to create GTB panel.")
                    
                    print(f"✅ GTB panel commands registered")
                    first_guild = False

            print("📝 About to setup raffle commands...")
            # Setup raffle commands (global cog)
            await setup_raffle_commands(bot, engine)
            print("✅ Raffle commands setup complete")
            
            # Set legacy global references (use first guild for backward compatibility)
            if bot.guilds:
                first_guild_id = bot.guilds[0].id
                gifted_sub_tracker = gifted_sub_trackers.get(first_guild_id)
                shuffle_tracker = shuffle_trackers.get(first_guild_id)
                slot_call_tracker = slot_call_trackers.get(first_guild_id)
                gtb_manager = gtb_managers.get(first_guild_id)
                bot.slot_call_tracker = slot_call_tracker
                bot.gtb_manager = gtb_manager

            print("✅ All guilds initialized with multiserver features")

            print("📝 About to setup link panel...")
            # Setup link panel (button-based OAuth linking)
            link_panel = await setup_link_panel_system(
                bot,
                engine,
                generate_signed_oauth_url
            )
            print(f"✅ Link panel system initialized (button + ephemeral messages)")

            # Setup timed messages system
            timed_messages_manager = await setup_timed_messages(
                bot,
                engine,
                kick_send_callback=send_kick_message if KICK_BOT_USER_TOKEN else None
            )
            # Store as bot attribute for Redis subscriber
            bot.timed_messages_manager = timed_messages_manager

            if KICK_BOT_USER_TOKEN:
                print(f"✅ Timed messages system initialized ({len(timed_messages_manager.messages)} messages)")
            else:
                print("ℹ️  Timed messages disabled (set KICK_BOT_USER_TOKEN to enable)")

            # Setup custom commands manager
            if KICK_BOT_USER_TOKEN:
                custom_commands_manager = CustomCommandsManager(
                    bot,
                    send_message_callback=send_kick_message
                )
                await custom_commands_manager.start()
                # Store as bot attribute for Redis subscriber
                bot.custom_commands_manager = custom_commands_manager
                print(f"✅ Custom commands system initialized")
            else:
                print("ℹ️  Custom commands disabled (set KICK_BOT_USER_TOKEN to enable)")

            # Clip service is now on Dashboard - no local buffer needed
            # Bot calls Dashboard API at /api/clips/create when !clip is used
            # Dashboard URL is configured per-guild in settings
            print(f"✅ Clip service configured via Dashboard API")
            print(f"   Configure Dashboard URL in Profile Settings for each guild")

        except Exception as e:
            print(f"⚠️ Failed to initialize raffle system: {e}")
            import traceback
            traceback.print_exc()

    except Exception as e:
        print(f"⚠️ Error during startup: {e}")

    # Start Kick chat listeners for all guilds with configured Kick channels
    for guild in bot.guilds:
        try:
            guild_settings = get_guild_settings(guild.id)
            kick_channel = guild_settings.kick_channel
            
            if kick_channel and kick_channel.strip():
                bot.loop.create_task(kick_chat_loop(kick_channel, guild.id))
                print(f"✅ Kick chat listener started for guild {guild.name} ({guild.id}) → {kick_channel}")
            else:
                print(f"⚠️ No Kick channel configured for guild {guild.name} ({guild.id})")
                print(f"   Configure it in Dashboard → Profile Settings")
        except Exception as e:
            print(f"⚠️ Failed to start Kick listener for guild {guild.id}: {e}")

async def handle_timer_panel_reaction(payload):
    """Handle reactions on timer panel messages."""
    from features.messaging.timed_messages import TimedMessagesManager

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
    guild_id = payload.guild_id

    # Check if already linked
    with engine.connect() as conn:
        existing = conn.execute(text(
            "SELECT kick_name FROM links WHERE discord_id = :d AND discord_server_id = :g"
        ), {"d": discord_id, "g": guild_id}).fetchone()

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
    oauth_url = generate_signed_oauth_url(discord_id, guild_id)

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
            # Delete any existing pending OAuth for this user in this guild
            conn.execute(text("DELETE FROM oauth_notifications WHERE discord_id = :d AND discord_server_id = :g AND processed = FALSE"), {"d": discord_id, "g": guild_id})

            # Store DM message info (will be updated with kick_username when OAuth completes)
            conn.execute(text("""
                INSERT INTO oauth_notifications (discord_id, kick_username, channel_id, message_id, processed, discord_server_id)
                VALUES (:d, '', :c, :m, FALSE, :g)
            """), {"d": discord_id, "c": dm_message.channel.id, "m": dm_message.id, "g": guild_id})

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
                # Delete any existing pending OAuth for this user in this guild
                conn.execute(text("DELETE FROM oauth_notifications WHERE discord_id = :d AND discord_server_id = :g AND processed = FALSE"), {"d": discord_id, "g": guild_id})

                # Store channel message info
                conn.execute(text("""
                    INSERT INTO oauth_notifications (discord_id, kick_username, channel_id, message_id, processed, discord_server_id)
                    VALUES (:d, '', :c, :m, FALSE, :g)
                """), {"d": discord_id, "c": channel_message.channel.id, "m": channel_message.id, "g": guild_id})

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
# Admin Commands: Links Table Management
# -------------------------

@bot.group(name='fixlinks', invoke_without_command=True)
@commands.has_permissions(administrator=True)
async def fixlinks(ctx):
    """[ADMIN] Fix and manage links table. Use subcommands for specific actions."""
    await ctx.send(
        "**Links Table Management**\n"
        "Use `!fixlinks <subcommand>` with one of:\n"
        "• `check` - Run diagnostics on links table\n"
        "• `backfill` - Fix missing discord_server_id values\n"
        "• `duplicates` - Show duplicate kick names across servers\n"
        "• `resolve <kick_name> <keep_server_id>` - Resolve duplicate by keeping one server"
    )

@fixlinks.command(name='check')
@commands.has_permissions(administrator=True)
async def fixlinks_check(ctx):
    """[ADMIN] Run diagnostics on links table."""
    try:
        with engine.connect() as conn:
            # Check for missing discord_server_id
            result = conn.execute(text("""
                SELECT COUNT(*) as cnt
                FROM links
                WHERE discord_server_id IS NULL OR discord_server_id = 0
            """)).fetchone()
            missing_count = result[0] if result else 0

            # Get distribution by server
            dist_result = conn.execute(text("""
                SELECT COALESCE(discord_server_id, 0) as server_id, COUNT(*) as cnt
                FROM links
                GROUP BY COALESCE(discord_server_id, 0)
                ORDER BY cnt DESC
                LIMIT 10
            """)).fetchall()

            # Check for duplicates
            dup_result = conn.execute(text("""
                SELECT kick_name, COUNT(DISTINCT discord_server_id) as server_count
                FROM links
                WHERE discord_server_id IS NOT NULL AND discord_server_id != 0
                GROUP BY kick_name
                HAVING COUNT(DISTINCT discord_server_id) > 1
                ORDER BY server_count DESC
                LIMIT 10
            """)).fetchall()

            embed = discord.Embed(
                title="🔍 Links Table Diagnostics",
                color=0x3498db
            )

            if missing_count > 0:
                embed.add_field(
                    name="⚠️ Missing Server IDs",
                    value=f"{missing_count} rows need backfill\nRun `!fixlinks backfill` to fix",
                    inline=False
                )
            else:
                embed.add_field(
                    name="✅ Server IDs",
                    value="All rows have valid discord_server_id",
                    inline=False
                )

            # Server distribution
            dist_text = "\n".join([
                f"{'MISSING/0' if r[0] in (0, None) else str(r[0])}: {r[1]} links"
                for r in dist_result[:5]
            ])
            embed.add_field(
                name="📊 Distribution",
                value=dist_text or "No data",
                inline=False
            )

            # Duplicates
            if dup_result:
                dup_text = "\n".join([
                    f"• `{r[0]}` on {r[1]} servers"
                    for r in dup_result[:5]
                ])
                embed.add_field(
                    name="⚠️ Duplicates Across Servers",
                    value=f"{len(dup_result)} kick names on multiple servers:\n{dup_text}",
                    inline=False
                )
            else:
                embed.add_field(
                    name="✅ No Duplicates",
                    value="Each kick name belongs to one server only",
                    inline=False
                )

            await ctx.send(embed=embed)

    except Exception as e:
        await ctx.send(f"❌ Error running diagnostics: {e}")
        print(f"[fixlinks check] Error: {e}")

@fixlinks.command(name='backfill')
@commands.has_permissions(administrator=True)
async def fixlinks_backfill(ctx):
    """[ADMIN] Fix rows with missing discord_server_id."""
    if not DISCORD_GUILD_ID:
        await ctx.send("❌ DISCORD_GUILD_ID not configured. Cannot determine target server.")
        return

    try:
        with engine.begin() as conn:
            # Count rows needing fix
            result = conn.execute(text("""
                SELECT COUNT(*) as cnt
                FROM links
                WHERE discord_server_id IS NULL OR discord_server_id = 0
            """)).fetchone()
            missing_count = result[0] if result else 0

            if missing_count == 0:
                await ctx.send("✅ No rows need backfilling. All rows have valid discord_server_id.")
                return

            # Update missing values
            conn.execute(text("""
                UPDATE links
                SET discord_server_id = :sid
                WHERE discord_server_id IS NULL OR discord_server_id = 0
            """), {"sid": DISCORD_GUILD_ID})

            await ctx.send(
                f"✅ **Backfill Complete**\n"
                f"Updated {missing_count} rows with server ID `{DISCORD_GUILD_ID}`"
            )
            print(f"[fixlinks backfill] Updated {missing_count} rows")

    except Exception as e:
        await ctx.send(f"❌ Error during backfill: {e}")
        print(f"[fixlinks backfill] Error: {e}")

@fixlinks.command(name='duplicates')
@commands.has_permissions(administrator=True)
async def fixlinks_duplicates(ctx):
    """[ADMIN] Show kick names that exist on multiple servers."""
    try:
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT
                    l.kick_name,
                    l.discord_server_id,
                    l.discord_id,
                    l.linked_at
                FROM links l
                WHERE l.kick_name IN (
                    SELECT kick_name
                    FROM links
                    WHERE discord_server_id IS NOT NULL AND discord_server_id != 0
                    GROUP BY kick_name
                    HAVING COUNT(DISTINCT discord_server_id) > 1
                )
                ORDER BY l.kick_name, l.linked_at DESC
            """)).fetchall()

            if not result:
                await ctx.send("✅ No duplicate kick names found across servers.")
                return

            # Group by kick_name
            duplicates = {}
            for row in result:
                kick_name = row[0]
                if kick_name not in duplicates:
                    duplicates[kick_name] = []
                duplicates[kick_name].append({
                    'server_id': row[1],
                    'discord_id': row[2],
                    'linked_at': row[3]
                })

            embed = discord.Embed(
                title="⚠️ Duplicate Kick Names Across Servers",
                description=f"Found {len(duplicates)} kick names on multiple servers",
                color=0xe74c3c
            )

            for kick_name, entries in list(duplicates.items())[:10]:  # Show max 10
                servers_text = "\n".join([
                    f"Server `{e['server_id']}`: <@{e['discord_id']}> (linked {e['linked_at'].strftime('%Y-%m-%d') if e['linked_at'] else 'unknown'})"
                    for e in entries
                ])
                embed.add_field(
                    name=f"🔗 {kick_name}",
                    value=servers_text,
                    inline=False
                )

            if len(duplicates) > 10:
                embed.set_footer(text=f"Showing 10 of {len(duplicates)} duplicates")

            embed.add_field(
                name="How to Resolve",
                value="Use `!fixlinks resolve <kick_name> <keep_server_id>` to keep one link and remove others",
                inline=False
            )

            await ctx.send(embed=embed)

    except Exception as e:
        await ctx.send(f"❌ Error fetching duplicates: {e}")
        print(f"[fixlinks duplicates] Error: {e}")

@fixlinks.command(name='resolve')
@commands.has_permissions(administrator=True)
async def fixlinks_resolve(ctx, kick_name: str, keep_server_id: int):
    """[ADMIN] Resolve duplicate by keeping one server's link and removing others."""
    try:
        with engine.begin() as conn:
            # Check if duplicate exists
            result = conn.execute(text("""
                SELECT discord_server_id, discord_id
                FROM links
                WHERE kick_name = :name
                ORDER BY discord_server_id
            """), {"name": kick_name}).fetchall()

            if not result:
                await ctx.send(f"❌ No links found for kick name `{kick_name}`")
                return

            if len(result) == 1:
                await ctx.send(f"✅ `{kick_name}` only exists on one server. No action needed.")
                return

            # Check if keep_server_id is valid
            server_ids = [r[0] for r in result]
            if keep_server_id not in server_ids:
                await ctx.send(
                    f"❌ Server `{keep_server_id}` doesn't have a link for `{kick_name}`\n"
                    f"Available servers: {', '.join(map(str, server_ids))}"
                )
                return

            # Delete other servers' links
            deleted = conn.execute(text("""
                DELETE FROM links
                WHERE kick_name = :name AND discord_server_id != :keep_server
                RETURNING discord_server_id, discord_id
            """), {"name": kick_name, "keep_server": keep_server_id}).fetchall()

            deleted_info = ", ".join([f"Server {r[0]} (<@{r[1]}>)" for r in deleted])

            await ctx.send(
                f"✅ **Duplicate Resolved**\n"
                f"Kept: `{kick_name}` on server `{keep_server_id}`\n"
                f"Removed from: {deleted_info}"
            )
            print(f"[fixlinks resolve] Kept {kick_name} on server {keep_server_id}, removed {len(deleted)} duplicates")

    except Exception as e:
        await ctx.send(f"❌ Error resolving duplicate: {e}")
        print(f"[fixlinks resolve] Error: {e}")

# -------------------------
# Point Shop Interactive Components
# -------------------------

class PointShopConfirmView(discord.ui.View):
    """View with button to confirm purchase"""

    def __init__(self, item_id: int, item_name: str, price: int, kick_username: str, discord_id: int, guild_id: int, requirement_value: str = None, note: str = None):
        super().__init__(timeout=300)  # 5 minute timeout
        self.item_id = item_id
        self.item_name = item_name
        self.price = price
        self.kick_username = kick_username
        self.discord_id = discord_id
        self.guild_id = guild_id
        self.requirement_value = requirement_value
        self.note = note

    @discord.ui.button(label="Complete Purchase", style=discord.ButtonStyle.success, emoji="✅")
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Process the purchase when button is clicked"""
        try:
            with engine.begin() as conn:
                # Get item details (fresh from DB)
                item = conn.execute(text("""
                    SELECT id, name, price, stock, is_active
                    FROM point_shop_items
                    WHERE id = :id
                """), {"id": self.item_id}).fetchone()

                if not item:
                    await interaction.response.edit_message(content="❌ This item no longer exists.", view=None)
                    return

                item_id, item_name, price, stock, is_active = item

                if not is_active:
                    await interaction.response.edit_message(content="❌ This item is no longer available.", view=None)
                    return

                if stock == 0:
                    await interaction.response.edit_message(content="❌ This item is sold out!", view=None)
                    return

                # Check user's points balance
                user_points = conn.execute(text("""
                    SELECT points FROM user_points
                    WHERE kick_username = :k AND discord_server_id = :g
                """), {"k": self.kick_username, "g": self.guild_id}).fetchone()

                if not user_points or user_points[0] < price:
                    current_balance = user_points[0] if user_points else 0
                    await interaction.response.edit_message(
                        content=f"❌ Insufficient points! You have **{current_balance:,}** points but need **{price:,}** points.",
                        view=None
                    )
                    return

                # Deduct points
                conn.execute(text("""
                    UPDATE user_points
                    SET points = points - :p,
                        total_spent = total_spent + :p,
                        last_updated = CURRENT_TIMESTAMP
                    WHERE kick_username = :k AND discord_server_id = :g
                """), {"p": price, "k": self.kick_username, "g": self.guild_id})

                # Reduce stock if not unlimited
                if stock > 0:
                    conn.execute(text("""
                        UPDATE point_shop_items
                        SET stock = stock - 1,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = :id
                    """), {"id": item_id})

                # Record the sale with note and requirement input
                conn.execute(text("""
                    INSERT INTO point_sales (item_id, kick_username, discord_id, item_name, price_paid, quantity, status, notes, requirement_input)
                    VALUES (:item_id, :kick, :discord, :name, :price, 1, 'pending', :notes, :req_input)
                """), {
                    "item_id": item_id,
                    "kick": self.kick_username,
                    "discord": self.discord_id,
                    "name": item_name,
                    "price": price,
                    "notes": self.note,
                    "req_input": self.requirement_value
                })

                # Get updated balance
                new_balance = conn.execute(text("""
                    SELECT points FROM user_points WHERE kick_username = :k AND discord_server_id = :g
                """), {"k": self.kick_username, "g": self.guild_id}).fetchone()[0]

            # Publish event to notify dashboard of new purchase
            publish_redis_event('point_shop', 'new_purchase', {
                'item_id': item_id,
                'item_name': item_name,
                'buyer': self.kick_username,
                'price': price,
                'discord_id': self.discord_id
            })

            # Success response
            note_text = f"\n📝 Note: _{self.note}_" if self.note else ""
            req_text = f"\n📋 {self.requirement_value}" if self.requirement_value else ""
            await interaction.response.edit_message(
                content=f"✅ **Purchase Successful!**\n"
                f"🛒 You bought **{item_name}** for **{price:,}** points!\n"
                f"💰 Your new balance: **{new_balance:,}** points{req_text}{note_text}\n\n"
                f"_An admin will fulfill your purchase soon._",
                view=None
            )

            print(f"[Point Shop] {self.kick_username} (Discord ID: {self.discord_id}) purchased {item_name} for {price} points")

        except Exception as e:
            print(f"[Point Shop] Purchase error: {e}")
            import traceback
            traceback.print_exc()
            await interaction.response.edit_message(
                content=f"❌ An error occurred during purchase. Please try again later.",
                view=None
            )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Cancel the purchase"""
        await interaction.response.edit_message(content="❌ Purchase cancelled.", view=None)

class PointShopPurchaseModal(discord.ui.Modal):
    """Modal for confirming a point shop purchase"""

    def __init__(self, item_id: int, item_name: str, price: int, description: str, stock: int, requirement_title: str = None, requirement_footer: str = None):
        super().__init__(title=f"Purchase: {item_name[:40]}")
        self.item_id = item_id
        self.item_name = item_name
        self.price = price
        self.description = description
        self.stock = stock
        self.requirement_title = requirement_title
        self.requirement_footer = requirement_footer

        # Stock display text
        stock_text = "Unlimited" if stock < 0 else f"{stock} remaining"

        # Add requirement input field if needed
        self.requirement_input = None
        if requirement_title:
            label = requirement_title[:45]  # Discord label limit
            placeholder = requirement_footer[:100] if requirement_footer else "Enter required information"
            self.requirement_input = discord.ui.TextInput(
                label=label,
                placeholder=placeholder,
                required=True,
                max_length=200,
                style=discord.TextStyle.short
            )
            self.add_item(self.requirement_input)

        # Optional note/message field
        self.note_input = discord.ui.TextInput(
            label="Note for admin (optional)",
            placeholder="e.g., preferred delivery method, etc.",
            required=False,
            max_length=200,
            style=discord.TextStyle.paragraph
        )
        self.add_item(self.note_input)

    async def on_submit(self, interaction: discord.Interaction):
        """Show confirmation view after modal is submitted"""

        discord_id = interaction.user.id
        note = self.note_input.value.strip() if self.note_input.value else None
        requirement_value = self.requirement_input.value.strip() if self.requirement_input else None

        # Get user's balance
        with engine.connect() as conn:
            # Get linked account
            link = conn.execute(text("""
                SELECT kick_name FROM links
                WHERE discord_id = :d AND discord_server_id = :s
            """), {"d": discord_id, "s": interaction.guild.id}).fetchone()

            if not link:
                await interaction.response.send_message(
                    "❌ You need to link your Kick account first!",
                    ephemeral=True
                )
                return

            kick_username = link[0]

            # Get balance
            points_data = conn.execute(text("""
                SELECT points FROM user_points WHERE kick_username = :k
            """), {"k": kick_username}).fetchone()

            current_balance = points_data[0] if points_data else 0

        # Check if they can afford it
        if current_balance < self.price:
            await interaction.response.send_message(
                f"❌ **Insufficient Points!**\n\n"
                f"**{self.item_name}** costs **{self.price:,}** points\n"
                f"Your balance: **{current_balance:,}** points\n"
                f"You need **{self.price - current_balance:,}** more points!",
                ephemeral=True
            )
            return

        # Build confirmation message
        confirm_text = f"**Confirm Purchase**\n\n"
        confirm_text += f"🛒 Item: **{self.item_name}**\n"
        confirm_text += f"💰 Price: **{self.price:,}** points\n"
        confirm_text += f"📊 Your balance: **{current_balance:,}** points\n"
        confirm_text += f"📊 Balance after: **{current_balance - self.price:,}** points\n"
        if requirement_value:
            req_label = self.requirement_title or "Requirement"
            confirm_text += f"\n📝 {req_label}: {requirement_value}\n"
        if note:
            confirm_text += f"\n💬 Note: _{note}_\n"

        # Create confirmation view with button
        view = PointShopConfirmView(
            item_id=self.item_id,
            item_name=self.item_name,
            price=self.price,
            kick_username=kick_username,
            discord_id=discord_id,
            guild_id=interaction.guild_id,
            requirement_value=requirement_value,
            note=note
        )

        await interaction.response.send_message(confirm_text, view=view, ephemeral=True)

class PointShopItemSelect(discord.ui.Select):
    """Dropdown to select a shop item"""

    def __init__(self, items: list):
        self.items_data = {}  # Store item data for quick lookup
        options = []

        for item in items[:25]:  # Discord limit
            item_id, name, description, price, stock, image_url, is_active, requirement_title, requirement_footer = item
            if is_active:
                # Stock display
                if stock < 0:
                    stock_text = "∞"
                elif stock == 0:
                    stock_text = "SOLD OUT"
                else:
                    stock_text = str(stock)

                self.items_data[str(item_id)] = {
                    "id": item_id,
                    "name": name,
                    "description": description or "No description",
                    "price": price,
                    "stock": stock,
                    "requirement_title": requirement_title,
                    "requirement_footer": requirement_footer
                }

                # Format: "Item Name: Xpts" with "──── In-stock: X ────" as description
                options.append(discord.SelectOption(
                    label=f"{name}: {price:,}pts"[:100],
                    description=f"━━━━ In-stock: {stock_text} ━━━━"[:100],
                    value=str(item_id),
                    emoji="🎁"
                ))

        if not options:
            options.append(discord.SelectOption(
                label="No items available",
                value="none",
                emoji="❌"
            ))

        super().__init__(
            placeholder="🛍️ Select an item to purchase...",
            options=options,
            custom_id="shop_item_select"
        )

    async def callback(self, interaction: discord.Interaction):
        """Show purchase modal when item is selected"""
        selected_id = self.values[0]

        if selected_id == "none":
            await interaction.response.send_message(
                "❌ No items are available for purchase right now.",
                ephemeral=True
            )
            return

        item = self.items_data.get(selected_id)
        if not item:
            await interaction.response.send_message(
                "❌ Item not found. Please try again.",
                ephemeral=True
            )
            return

        if item["stock"] == 0:
            await interaction.response.send_message(
                f"❌ **{item['name']}** is sold out!",
                ephemeral=True
            )
            return

        # First, show the user their balance and item details
        discord_id = interaction.user.id

        with engine.connect() as conn:
            # Get linked account
            link = conn.execute(text("""
                SELECT kick_name FROM links
                WHERE discord_id = :d AND discord_server_id = :s
            """), {"d": discord_id, "s": interaction.guild.id}).fetchone()

            if not link:
                await interaction.response.send_message(
                    "❌ You need to link your Kick account first! Use the link panel or `!link` command.",
                    ephemeral=True
                )
                return

            kick_username = link[0]

            # Get balance
            points_data = conn.execute(text("""
                SELECT points FROM user_points WHERE kick_username = :k
            """), {"k": kick_username}).fetchone()

            current_balance = points_data[0] if points_data else 0

        # Check if they can afford it
        if current_balance < item["price"]:
            await interaction.response.send_message(
                f"❌ **Insufficient Points!**\n\n"
                f"**{item['name']}** costs **{item['price']:,}** points\n"
                f"Your balance: **{current_balance:,}** points\n"
                f"You need **{item['price'] - current_balance:,}** more points!",
                ephemeral=True
            )
            return

        # Show the purchase modal
        modal = PointShopPurchaseModal(
            item_id=item["id"],
            item_name=item["name"],
            price=item["price"],
            description=item["description"],
            stock=item["stock"],
            requirement_title=item.get("requirement_title"),
            requirement_footer=item.get("requirement_footer")
        )
        await interaction.response.send_modal(modal)

class PointShopView(discord.ui.View):
    """Persistent view for the point shop with item selector (legacy)"""

    def __init__(self, items: list):
        super().__init__(timeout=None)

        if items:
            self.add_item(PointShopItemSelect(items))

        # Add a check balance button
        self.add_item(PointShopBalanceButton())

class PointShopBalanceButton(discord.ui.Button):
    """Button to check point balance"""

    def __init__(self):
        super().__init__(
            style=discord.ButtonStyle.secondary,
            label="Check Balance",
            custom_id="shop_check_balance",
            emoji="💰"
        )

    async def callback(self, interaction: discord.Interaction):
        """Show user's point balance"""
        discord_id = interaction.user.id

        with engine.connect() as conn:
            link = conn.execute(text("""
                SELECT kick_name FROM links
                WHERE discord_id = :d AND discord_server_id = :s
            """), {"d": discord_id, "s": interaction.guild.id}).fetchone()

            if not link:
                await interaction.response.send_message(
                    "❌ You need to link your Kick account first! Use the link panel or `!link` command.",
                    ephemeral=True
                )
                return

            kick_username = link[0]

            points_data = conn.execute(text("""
                SELECT points, total_earned, total_spent
                FROM user_points
                WHERE kick_username = :k
            """), {"k": kick_username}).fetchone()

            if not points_data:
                points, total_earned, total_spent = 0, 0, 0
            else:
                points, total_earned, total_spent = points_data

        embed = discord.Embed(
            title="💰 Your Point Balance",
            color=0xFFD700
        )
        embed.add_field(name="Current Balance", value=f"**{points:,}** points", inline=True)
        embed.add_field(name="Total Earned", value=f"{total_earned:,} points", inline=True)
        embed.add_field(name="Total Spent", value=f"{total_spent:,} points", inline=True)
        embed.set_footer(text=f"Kick Account: {kick_username}")

        await interaction.response.send_message(embed=embed, ephemeral=True)

async def create_shop_mosaic_image(items, max_width=2400):
    """Create a grid mosaic image from shop item images, preserving original aspect ratios

    Layout per item:
    ┌─────────────┐
    │ Item Name   │  <- Title above image (no number)
    ├─────────────┤
    │   IMAGE     │  <- Much larger, high quality image
    │             │
    ├─────────────┤
    │ 500 pts     │  <- Bigger price
    │ In-stock: 10│  <- Full stock text
    └─────────────┘

    Args:
        items: List of shop items
        max_width: Maximum width of the entire mosaic (default 2400px for very large images)
    """
    from PIL import Image, ImageDraw, ImageFont
    import aiohttp
    import io
    import math

    # Filter items with images
    items_with_images = [(i, item) for i, item in enumerate(items) if item[5]]  # item[5] is image_url

    if not items_with_images:
        return None

    # Settings - VERY LARGE sizes for maximum visibility
    COLS = min(len(items_with_images), 3)  # Max 3 columns
    PADDING = 30
    TITLE_HEIGHT = 70  # Title above image
    FOOTER_HEIGHT = 140  # Price + stock below image (increased for larger fonts)
    TITLE_FONT_SIZE = 42  # Much bigger title
    PRICE_FONT_SIZE = 46  # Increased price font size
    STOCK_FONT_SIZE = 34  # Increased stock font size
    BG_COLOR = (30, 30, 35)
    TITLE_BG_COLOR = (45, 45, 55)
    FOOTER_BG_COLOR = (50, 50, 60)
    TEXT_COLOR = (255, 255, 255)
    PRICE_COLOR = (255, 215, 0)  # Gold for price
    STOCK_COLOR = (100, 200, 100)  # Green for stock
    SOLDOUT_COLOR = (255, 100, 100)  # Red for sold out

    # Calculate cell width based on max_width and columns (very large cells)
    cell_width = (max_width - (COLS + 1) * PADDING) // COLS

    # Try to load fonts - prefer bold/semi-bold for titles
    try:
        title_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", TITLE_FONT_SIZE)
        price_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", PRICE_FONT_SIZE)
        stock_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", STOCK_FONT_SIZE)
    except:
        try:
            title_font = ImageFont.truetype("arialbd.ttf", TITLE_FONT_SIZE)  # Arial Bold
            price_font = ImageFont.truetype("arialbd.ttf", PRICE_FONT_SIZE)
            stock_font = ImageFont.truetype("arial.ttf", STOCK_FONT_SIZE)
        except:
            try:
                title_font = ImageFont.truetype("arial.ttf", TITLE_FONT_SIZE)
                price_font = ImageFont.truetype("arial.ttf", PRICE_FONT_SIZE)
                stock_font = ImageFont.truetype("arial.ttf", STOCK_FONT_SIZE)
            except:
                title_font = ImageFont.load_default()
                price_font = title_font
                stock_font = title_font

    # First pass: download all images and calculate row heights
    downloaded_images = []
    async with aiohttp.ClientSession() as session:
        for item_idx, item in items_with_images:
            item_id, name, description, price, stock, image_url, is_active, requirement_title, requirement_footer = item

            try:
                async with session.get(image_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        img_data = await resp.read()
                        img = Image.open(io.BytesIO(img_data))

                        # Convert to RGB if necessary
                        if img.mode in ('RGBA', 'P'):
                            bg = Image.new('RGB', img.size, BG_COLOR)
                            if img.mode == 'P':
                                img = img.convert('RGBA')
                            bg.paste(img, mask=img.split()[3] if len(img.split()) > 3 else None)
                            img = bg
                        elif img.mode != 'RGB':
                            img = img.convert('RGB')

                        # Scale image to fit cell width while preserving aspect ratio
                        orig_w, orig_h = img.size
                        scale = cell_width / orig_w
                        new_h = int(orig_h * scale)
                        img = img.resize((cell_width, new_h), Image.Resampling.LANCZOS)

                        downloaded_images.append((item_idx, item, img))
                    else:
                        downloaded_images.append((item_idx, item, None))
            except Exception as e:
                print(f"[Point Shop Mosaic] Failed to load image for {name}: {e}")
                downloaded_images.append((item_idx, item, None))

    if not downloaded_images:
        return None

    # Group into rows and calculate height per row
    rows_data = [downloaded_images[i:i + COLS] for i in range(0, len(downloaded_images), COLS)]
    row_heights = []

    for row in rows_data:
        # Find max image height in this row
        max_img_height = 0
        for item_idx, item, img in row:
            if img:
                max_img_height = max(max_img_height, img.size[1])
            else:
                max_img_height = max(max_img_height, 500)  # Very large placeholder height
        row_heights.append(max_img_height)

    # Calculate total canvas size (title + image + footer per row)
    total_height = PADDING
    for rh in row_heights:
        total_height += TITLE_HEIGHT + rh + FOOTER_HEIGHT + PADDING

    canvas_width = COLS * cell_width + (COLS + 1) * PADDING
    canvas = Image.new('RGB', (canvas_width, total_height), BG_COLOR)
    draw = ImageDraw.Draw(canvas)

    # Second pass: place images on canvas
    current_y = PADDING
    for row_idx, row in enumerate(rows_data):
        row_height = row_heights[row_idx]

        for col_idx, (item_idx, item, img) in enumerate(row):
            item_id, name, description, price, stock, image_url, is_active, requirement_title, requirement_footer = item

            x = PADDING + col_idx * (cell_width + PADDING)

            # Draw TITLE background (above image)
            draw.rectangle([x, current_y, x + cell_width, current_y + TITLE_HEIGHT], fill=TITLE_BG_COLOR)

            # Draw item title (no item number, just the name)
            max_chars = cell_width // 14
            name_text = f"{name[:max_chars]}{'...' if len(name) > max_chars else ''}"
            # Center the title text
            bbox = draw.textbbox((0, 0), name_text, font=title_font)
            text_width = bbox[2] - bbox[0]
            text_x = x + (cell_width - text_width) // 2
            draw.text((text_x, current_y + 10), name_text, fill=TEXT_COLOR, font=title_font)

            # IMAGE area starts after title
            img_y = current_y + TITLE_HEIGHT

            if img:
                # Center image vertically in its cell if shorter than row height
                img_h = img.size[1]
                y_offset = (row_height - img_h) // 2
                canvas.paste(img, (x, img_y + y_offset))

                # Draw sold out overlay if applicable
                if stock == 0:
                    overlay = Image.new('RGBA', img.size, (0, 0, 0, 150))
                    composited = Image.alpha_composite(img.convert('RGBA'), overlay).convert('RGB')
                    canvas.paste(composited, (x, img_y + y_offset))

                    # Draw "SOLD OUT" text centered on image
                    sold_text = "SOLD OUT"
                    bbox = draw.textbbox((0, 0), sold_text, font=price_font)
                    tw = bbox[2] - bbox[0]
                    th = bbox[3] - bbox[1]
                    draw.text(
                        (x + (cell_width - tw) // 2, img_y + y_offset + (img_h - th) // 2),
                        sold_text,
                        fill=SOLDOUT_COLOR,
                        font=price_font
                    )
            else:
                # Draw placeholder
                draw.rectangle([x, img_y, x + cell_width, img_y + row_height], fill=(60, 60, 70))
                draw.text((x + 10, img_y + row_height // 2), "No Image", fill=TEXT_COLOR, font=title_font)

            # Draw FOOTER background (below image)
            footer_y = img_y + row_height
            draw.rectangle([x, footer_y, x + cell_width, footer_y + FOOTER_HEIGHT], fill=FOOTER_BG_COLOR)

            # Line 1: Price (big, gold)
            price_text = f"{price:,} pts"
            draw.text((x + 10, footer_y + 15), price_text, fill=PRICE_COLOR, font=price_font)

            # Line 2: Stock text
            if stock < 0:
                stock_text = "In-stock: ∞"
                stock_color = STOCK_COLOR
            elif stock == 0:
                stock_text = "In-stock: SOLD OUT"
                stock_color = SOLDOUT_COLOR
            else:
                stock_text = f"In-stock: {stock}"
                stock_color = STOCK_COLOR

            draw.text((x + 10, footer_y + 75), stock_text, fill=stock_color, font=stock_font)

        current_y += TITLE_HEIGHT + row_height + FOOTER_HEIGHT + PADDING

    # Save to bytes with high quality
    output = io.BytesIO()
    canvas.save(output, format='PNG', optimize=False)  # No optimization for better quality
    output.seek(0)

    return output

async def post_point_shop_to_discord(bot, guild_id: int = None, channel_id: int = None, update_existing: bool = True, use_components_v2: bool = True):
    """Post or update the point shop using Components V2 with grid mosaic layout"""

    try:
        # If channel_id not provided, get from settings
        if not channel_id:
            with engine.connect() as conn:
                result = conn.execute(text("""
                    SELECT value FROM point_settings WHERE key = 'shop_channel_id'
                """)).fetchone()

                if not result:
                    print("[Point Shop] No shop channel configured")
                    return False

                channel_id = int(result[0])

        channel = bot.get_channel(channel_id)
        if not channel:
            print(f"[Point Shop] Channel {channel_id} not found")
            return False

        # Get active shop items
        with engine.connect() as conn:
            items = conn.execute(text("""
                SELECT id, name, description, price, stock, image_url, is_active, requirement_title, requirement_footer
                FROM point_shop_items
                WHERE is_active = TRUE
                ORDER BY price ASC
            """)).fetchall()

            # Get existing message ID
            existing_msg_result = conn.execute(text("""
                SELECT value FROM point_settings WHERE key = 'shop_message_id'
            """)).fetchone()
            existing_message_id = int(existing_msg_result[0]) if existing_msg_result else None

            # Get existing interactive message ID
            existing_interactive_result = conn.execute(text("""
                SELECT value FROM point_settings WHERE key = 'shop_interactive_id'
            """)).fetchone()
            existing_interactive_id = int(existing_interactive_result[0]) if existing_interactive_result else None

            # Get existing footer message ID
            existing_footer_result = conn.execute(text("""
                SELECT value FROM point_settings WHERE key = 'shop_footer_id'
            """)).fetchone()
            existing_footer_id = int(existing_footer_result[0]) if existing_footer_result else None

        # Delete existing messages if updating
        if update_existing:
            for msg_id in [existing_message_id, existing_interactive_id, existing_footer_id]:
                if msg_id:
                    try:
                        existing_message = await channel.fetch_message(msg_id)
                        await existing_message.delete()
                        print(f"[Point Shop] Deleted old shop message {msg_id}")
                    except discord.NotFound:
                        pass
                    except Exception as e:
                        print(f"[Point Shop] Error deleting message {msg_id}: {e}")

        # Check if Components V2 is supported (discord.py 2.6+)
        has_components_v2 = hasattr(discord.ui, 'LayoutView') and hasattr(discord.ui, 'MediaGallery')

        print(f"[Point Shop] Components V2 available: {has_components_v2}, use_components_v2: {use_components_v2}, items count: {len(items)}")

        if use_components_v2 and has_components_v2 and items:
            # ==================== Components V2 Mode with Mosaic ====================
            v2_success = False
            try:
                # Generate the mosaic image (name, price, stock already included in image)
                mosaic_image = await create_shop_mosaic_image(items)
                mosaic_file = None
                if mosaic_image:
                    mosaic_file = discord.File(mosaic_image, filename="shop_items.png")

                # Build Components V2 layout
                class ShopLayout(discord.ui.LayoutView):
                    def __init__(self, has_mosaic):
                        super().__init__(timeout=None)
                        self._build_layout(has_mosaic)

                    def _build_layout(self, has_mosaic):
                        # Header container
                        self.add_item(discord.ui.Container(
                            discord.ui.TextDisplay("# 🛍️ Point Shop"),
                            discord.ui.TextDisplay("Spend your hard-earned points on awesome rewards!"),
                            accent_colour=0xFFD700
                        ))

                        # Show mosaic image in MediaGallery
                        if has_mosaic:
                            self.add_item(discord.ui.MediaGallery(
                                discord.MediaGalleryItem("attachment://shop_items.png")
                            ))

                layout = ShopLayout(mosaic_file is not None)

                # Send the Components V2 display with mosaic
                if mosaic_file:
                    message = await channel.send(view=layout, file=mosaic_file)
                else:
                    message = await channel.send(view=layout)

                # Send a follow-up message with interactive components (select + button)
                interactive_view = PointShopView(items)
                interactive_msg = await channel.send("**Purchase an item:**", view=interactive_view)

                # Send footer message at the bottom
                footer_msg = await channel.send("💡 *Earn points by watching streams!*")

                # Mark as successful after messages are sent
                v2_success = True

                # Store all three message IDs - critical operation
                with engine.begin() as conn:
                    conn.execute(text("""
                        INSERT INTO point_settings (key, value, updated_at)
                        VALUES ('shop_message_id', :m, CURRENT_TIMESTAMP)
                        ON CONFLICT (key) DO UPDATE SET value = :m, updated_at = CURRENT_TIMESTAMP
                    """), {"m": str(message.id)})
                    conn.execute(text("""
                        INSERT INTO point_settings (key, value, updated_at)
                        VALUES ('shop_interactive_id', :m, CURRENT_TIMESTAMP)
                        ON CONFLICT (key) DO UPDATE SET value = :m, updated_at = CURRENT_TIMESTAMP
                    """), {"m": str(interactive_msg.id)})
                    conn.execute(text("""
                        INSERT INTO point_settings (key, value, updated_at)
                        VALUES ('shop_footer_id', :m, CURRENT_TIMESTAMP)
                        ON CONFLICT (key) DO UPDATE SET value = :m, updated_at = CURRENT_TIMESTAMP
                    """), {"m": str(footer_msg.id)})

                print(f"[Point Shop] Posted Components V2 mosaic shop to channel {channel_id}")
                return True

            except Exception as v2_error:
                if not v2_success:
                    print(f"[Point Shop] Components V2 failed, falling back to legacy: {v2_error}")
                    import traceback
                    traceback.print_exc()
                    # Fall through to legacy mode
                else:
                    # Messages were sent successfully, just log the error and return
                    print(f"[Point Shop] Components V2 posted but error occurred: {v2_error}")
                    return True

        # ==================== Legacy Mode (Embed + Mosaic) ====================
        if not items:
            embed = discord.Embed(
                title="🛍️ Point Shop",
                description="No items available at the moment. Check back later!",
                color=0xFFD700
            )
            embed.set_footer(text="💡 Tip: Earn points by watching streams!")
            message = await channel.send(embed=embed)

            with engine.begin() as conn:
                conn.execute(text("""
                    INSERT INTO point_settings (key, value, updated_at)
                    VALUES ('shop_message_id', :m, CURRENT_TIMESTAMP)
                    ON CONFLICT (key) DO UPDATE SET value = :m, updated_at = CURRENT_TIMESTAMP
                """), {"m": str(message.id)})
            return True

        # Create mosaic image for legacy mode
        mosaic_file = None
        mosaic_image = await create_shop_mosaic_image(items)
        if mosaic_image:
            mosaic_file = discord.File(mosaic_image, filename="shop_items.png")

        embed = discord.Embed(
            title="🛍️ Point Shop",
            description="Spend your hard-earned points on awesome rewards!\nSelect an item from the dropdown below to purchase.",
            color=0xFFD700
        )

        if mosaic_file:
            embed.set_image(url="attachment://shop_items.png")

        for idx, item in enumerate(items):
            item_id, name, description, price, stock, image_url, is_active, requirement_title, requirement_footer = item
            stock_text = "∞" if stock < 0 else f"{stock}" if stock > 0 else "SOLD OUT"

            field_value = f"$: **{price:,}** pts | In stock: {stock_text}"
            if description:
                desc_short = description[:50] + "..." if len(description) > 50 else description
                field_value += f"\n_{desc_short}_"

            embed.add_field(name=f"#{idx + 1} {name}", value=field_value, inline=True)

        embed.set_footer(text="💡 Earn points by watching streams! | Check balance: !points")

        view = PointShopView(items)

        if mosaic_file:
            message = await channel.send(embed=embed, file=mosaic_file, view=view)
        else:
            message = await channel.send(embed=embed, view=view)

        # Store the message ID for future updates (legacy mode has interactive in same message)
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO point_settings (key, value, updated_at)
                VALUES ('shop_message_id', :m, CURRENT_TIMESTAMP)
                ON CONFLICT (key) DO UPDATE SET value = :m, updated_at = CURRENT_TIMESTAMP
            """), {"m": str(message.id)})
            # Clear interactive ID since legacy mode includes it in same message
            conn.execute(text("""
                DELETE FROM point_settings WHERE key = 'shop_interactive_id'
            """))

        print(f"[Point Shop] Posted shop to channel {channel_id}")
        return True

    except Exception as e:
        print(f"[Point Shop] Error posting shop: {e}")
        import traceback
        traceback.print_exc()
        return False

async def update_point_shop_message(bot):
    """Update the existing point shop message with current data"""
    return await post_point_shop_to_discord(bot, update_existing=True)

@bot.command(name="points", aliases=["balance", "pts"])
async def cmd_points(ctx):
    """Check your point balance"""
    discord_id = ctx.author.id

    # Get linked Kick account
    with engine.connect() as conn:
        link = conn.execute(text("""
            SELECT kick_name FROM links
            WHERE discord_id = :d AND discord_server_id = :s
        """), {"d": discord_id, "s": ctx.guild.id}).fetchone()

        if not link:
            await ctx.send("❌ You need to link your Kick account first! Use the link panel or `!link` command.")
            return

        kick_username = link[0]

        # Get points balance
        points_data = conn.execute(text("""
            SELECT points, total_earned, total_spent
            FROM user_points
            WHERE kick_username = :k AND discord_server_id = :s
        """), {"k": kick_username, "s": ctx.guild.id}).fetchone()

        if not points_data:
            points, total_earned, total_spent = 0, 0, 0
        else:
            points, total_earned, total_spent = points_data

    embed = discord.Embed(
        title="💰 Your Point Balance",
        color=0xFFD700
    )
    embed.add_field(name="Current Balance", value=f"**{points:,}** points", inline=True)
    embed.add_field(name="Total Earned", value=f"{total_earned:,} points", inline=True)
    embed.add_field(name="Total Spent", value=f"{total_spent:,} points", inline=True)
    embed.set_footer(text=f"Kick Account: {kick_username}")

    await ctx.send(embed=embed)

@bot.command(name="pointslb", aliases=["pointsleaderboard", "ptslb"])
async def cmd_points_leaderboard(ctx, limit: int = 10):
    """Show the points leaderboard"""
    if limit < 1:
        limit = 10
    if limit > 25:
        limit = 25

    guild_id = ctx.guild.id if ctx.guild else None
    with engine.connect() as conn:
        leaders = conn.execute(text("""
            SELECT kick_username, points, total_earned
            FROM user_points
            WHERE points > 0 AND discord_server_id = :guild_id
            ORDER BY points DESC
            LIMIT :limit
        """), {"limit": limit, "guild_id": guild_id}).fetchall()

    if not leaders:
        await ctx.send("📊 No one has earned any points yet!")
        return

    embed = discord.Embed(
        title="🏆 Points Leaderboard",
        color=0xFFD700
    )

    leaderboard_text = ""
    for i, (username, points, total_earned) in enumerate(leaders, 1):
        rank_emoji = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        leaderboard_text += f"{rank_emoji} **{username}** - {points:,} pts\n"

    embed.description = leaderboard_text
    embed.set_footer(text=f"Top {len(leaders)} point holders")

    await ctx.send(embed=embed)

@bot.command(name="postshop")
@commands.has_permissions(administrator=True)
async def cmd_post_shop(ctx, channel: discord.TextChannel = None):
    """[ADMIN] Post the point shop to a channel"""
    target_channel = channel or ctx.channel

    # Save channel setting
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO point_settings (key, value, updated_at)
            VALUES ('shop_channel_id', :c, CURRENT_TIMESTAMP)
            ON CONFLICT (key) DO UPDATE SET value = :c, updated_at = CURRENT_TIMESTAMP
        """), {"c": str(target_channel.id)})

    success = await post_point_shop_to_discord(bot, ctx.guild.id, target_channel.id)

    if success:
        if channel:
            await ctx.send(f"✅ Point shop posted to {target_channel.mention}!")
    else:
        await ctx.send("❌ Failed to post point shop. Check that there are active items.")

# -------------------------
# Run bot
# -------------------------
if __name__ == "__main__":
    if not DISCORD_TOKEN:
        raise SystemExit("❌ DISCORD_TOKEN environment variable is required")

    print("✅ Multiserver bot starting")
    print("   Configure each Discord server in Dashboard → Profile Settings")
    print("   Set Kick channel name, slot calls channel, raffle settings per-server")

    bot.run(DISCORD_TOKEN)
