#!/usr/bin/env python3
"""
Setup Kick Webhooks with Proper Signature Verification

This script:
1. Uses existing OAuth tokens from database
2. Refreshes access token if needed
3. Deletes old webhooks
4. Registers new webhooks with secure secrets
5. Stores webhook secrets in database

Usage:
    # For a specific Discord server
    python setup_webhooks.py --discord-server-id 123456789

    # For all configured servers
    python setup_webhooks.py --all
"""

import os
import sys
import argparse
import asyncio
import secrets
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# Load environment variables
load_dotenv()

# Add parent directory to path
sys.path.insert(0, os.path.dirname(__file__))

try:
    from core.kick_official_api import KickOfficialAPI
except ImportError:
    print("❌ Error: Could not import KickOfficialAPI")
    print("Make sure you're in the Kick-dicord-bot directory")
    sys.exit(1)

# Database connection
DATABASE_URL = os.getenv('DATABASE_URL', '')
if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

# Webhook URL
WEBHOOK_URL = "https://bot.lelebot.xyz/webhooks/kick"

# Events to subscribe to
WEBHOOK_EVENTS = [
    "livestream.status.updated",
    "channel.subscription.new",
    "channel.subscription.gifts",
    "channel.subscription.renewal",
    # "chat.message.sent",  # Optional - kickpython already handles this
]


def get_database_engine():
    """Create database engine"""
    if not DATABASE_URL:
        print("❌ Error: DATABASE_URL not set")
        sys.exit(1)
    return create_engine(DATABASE_URL, pool_pre_ping=True)


async def get_oauth_tokens(engine, discord_server_id: str):
    """Get OAuth tokens and broadcaster info from database"""
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT 
                kick_username,
                kick_broadcaster_user_id,
                kick_access_token,
                kick_refresh_token
            FROM bot_settings
            WHERE discord_server_id = :server_id
            AND key IN ('kick_username', 'kick_broadcaster_user_id', 'kick_access_token', 'kick_refresh_token')
        """), {"server_id": discord_server_id}).fetchall()
        
        if not result:
            return None
        
        # Parse results
        data = {}
        for row in result:
            key = row[0]
            if key == 'kick_username':
                data['username'] = row[1]
            elif key == 'kick_broadcaster_user_id':
                data['broadcaster_user_id'] = row[1]
            elif key == 'kick_access_token':
                data['access_token'] = row[1]
            elif key == 'kick_refresh_token':
                data['refresh_token'] = row[1]
        
        # Try alternative query if needed
        if not data:
            result = conn.execute(text("""
                SELECT value FROM bot_settings
                WHERE discord_server_id = :server_id
                AND key = 'kick_broadcaster_user_id'
            """), {"server_id": discord_server_id}).fetchone()
            
            if result:
                data['broadcaster_user_id'] = result[0]
        
        return data if data else None


async def setup_webhooks_for_server(discord_server_id: str):
    """Setup webhooks for a specific Discord server"""
    print(f"\n{'='*60}")
    print(f"Setting up webhooks for Discord server: {discord_server_id}")
    print(f"{'='*60}\n")
    
    engine = get_database_engine()
    
    # Get OAuth tokens from database
    print("🔍 Looking up OAuth tokens...")
    oauth_data = await get_oauth_tokens(engine, discord_server_id)
    
    if not oauth_data:
        print(f"❌ No OAuth data found for Discord server {discord_server_id}")
        print("   Run OAuth flow first to connect Kick account")
        return False
    
    broadcaster_user_id = oauth_data.get('broadcaster_user_id')
    username = oauth_data.get('username', 'Unknown')
    access_token = oauth_data.get('access_token')
    refresh_token = oauth_data.get('refresh_token')
    
    if not broadcaster_user_id:
        print(f"❌ No broadcaster_user_id found for server {discord_server_id}")
        return False
    
    print(f"✅ Found broadcaster: {username} (ID: {broadcaster_user_id})")
    
    # Initialize API client
    client_id = os.getenv("KICK_CLIENT_ID")
    client_secret = os.getenv("KICK_CLIENT_SECRET")
    
    if not client_id or not client_secret:
        print("❌ KICK_CLIENT_ID and KICK_CLIENT_SECRET must be set")
        return False
    
    api = KickOfficialAPI(
        client_id=client_id,
        client_secret=client_secret,
        access_token=access_token
    )
    
    try:
        # Refresh access token if we have refresh token
        if refresh_token:
            print("🔄 Refreshing access token...")
            try:
                token_data = await api.refresh_access_token(refresh_token)
                api.access_token = token_data.get("access_token")
                new_refresh_token = token_data.get("refresh_token")
                
                # Update tokens in database
                with engine.begin() as conn:
                    conn.execute(text("""
                        UPDATE bot_settings
                        SET value = :access_token
                        WHERE discord_server_id = :server_id AND key = 'kick_access_token'
                    """), {"access_token": api.access_token, "server_id": discord_server_id})
                    
                    if new_refresh_token:
                        conn.execute(text("""
                            UPDATE bot_settings
                            SET value = :refresh_token
                            WHERE discord_server_id = :server_id AND key = 'kick_refresh_token'
                        """), {"refresh_token": new_refresh_token, "server_id": discord_server_id})
                
                print("✅ Access token refreshed")
            except Exception as e:
                print(f"⚠️  Could not refresh token: {e}")
                if not access_token:
                    print("❌ No valid access token available")
                    return False
        
        # List existing webhooks
        print("\n📋 Checking existing webhooks...")
        existing_subs = await api.get_webhook_subscriptions()
        
        # Delete existing webhooks for this broadcaster
        deleted_count = 0
        for sub in existing_subs:
            sub_dict = sub.__dict__ if hasattr(sub, '__dict__') else sub
            if sub_dict.get('broadcaster_user_id') == broadcaster_user_id:
                sub_id = sub_dict.get('id')
                event = sub_dict.get('event')
                print(f"🗑️  Deleting old webhook: {event} (ID: {sub_id})")
                try:
                    await api.delete_webhook_subscription(sub_id)
                    deleted_count += 1
                except Exception as e:
                    print(f"   ⚠️  Failed to delete: {e}")
        
        if deleted_count > 0:
            print(f"✅ Deleted {deleted_count} old webhook(s)")
        else:
            print("ℹ️  No existing webhooks found")
        
        # Register new webhooks with secrets
        print(f"\n📨 Registering new webhooks for events: {', '.join(WEBHOOK_EVENTS)}")
        
        for event_type in WEBHOOK_EVENTS:
            # Generate unique secret for this webhook
            webhook_secret = secrets.token_hex(32)  # 256-bit secret
            
            print(f"\n🔧 Registering: {event_type}")
            print(f"   URL: {WEBHOOK_URL}")
            print(f"   Secret: {webhook_secret[:8]}...{webhook_secret[-8:]}")
            
            try:
                subscription = await api.subscribe_webhook(
                    event=event_type,
                    callback_url=WEBHOOK_URL,
                    broadcaster_user_id=broadcaster_user_id,
                    secret=webhook_secret  # Pass the secret to Kick
                )
                
                sub_dict = subscription.__dict__ if hasattr(subscription, '__dict__') else subscription
                subscription_id = sub_dict.get('id')
                
                print(f"   ✅ Subscription created: {subscription_id}")
                
                # Store in database
                with engine.begin() as conn:
                    conn.execute(text("""
                        INSERT INTO kick_webhook_subscriptions 
                        (subscription_id, discord_server_id, broadcaster_user_id, event_type, webhook_url, webhook_secret, status)
                        VALUES (:sub_id, :server_id, :broadcaster_id, :event, :url, :secret, 'active')
                        ON CONFLICT (subscription_id) 
                        DO UPDATE SET 
                            webhook_secret = EXCLUDED.webhook_secret,
                            status = 'active',
                            updated_at = NOW()
                    """), {
                        "sub_id": subscription_id,
                        "server_id": discord_server_id,
                        "broadcaster_id": broadcaster_user_id,
                        "event": event_type,
                        "url": WEBHOOK_URL,
                        "secret": webhook_secret
                    })
                
                print(f"   ✅ Stored in database")
                
            except Exception as e:
                print(f"   ❌ Failed to register: {e}")
        
        print(f"\n{'='*60}")
        print(f"✅ Webhook setup complete for {username}!")
        print(f"{'='*60}\n")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Error setting up webhooks: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        await api.close()


async def setup_all_servers():
    """Setup webhooks for all servers with OAuth tokens"""
    engine = get_database_engine()
    
    print("🔍 Looking for all servers with Kick OAuth tokens...")
    
    with engine.connect() as conn:
        # Get all Discord servers with broadcaster_user_id
        result = conn.execute(text("""
            SELECT DISTINCT discord_server_id
            FROM bot_settings
            WHERE key = 'kick_broadcaster_user_id'
            AND value IS NOT NULL
            AND value != ''
        """)).fetchall()
        
        server_ids = [row[0] for row in result]
    
    if not server_ids:
        print("❌ No servers found with Kick OAuth configured")
        return
    
    print(f"✅ Found {len(server_ids)} server(s)")
    
    success_count = 0
    for server_id in server_ids:
        success = await setup_webhooks_for_server(server_id)
        if success:
            success_count += 1
    
    print(f"\n{'='*60}")
    print(f"Setup complete: {success_count}/{len(server_ids)} servers successful")
    print(f"{'='*60}")


def main():
    parser = argparse.ArgumentParser(
        description="Setup Kick webhooks with proper signature verification",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Setup webhooks for specific Discord server
  python setup_webhooks.py --discord-server-id 1234567890
  
  # Setup webhooks for all configured servers
  python setup_webhooks.py --all
        """
    )
    
    parser.add_argument(
        '--discord-server-id',
        type=str,
        help='Discord server ID to setup webhooks for'
    )
    
    parser.add_argument(
        '--all',
        action='store_true',
        help='Setup webhooks for all servers with OAuth configured'
    )
    
    args = parser.parse_args()
    
    if args.all:
        asyncio.run(setup_all_servers())
    elif args.discord_server_id:
        asyncio.run(setup_webhooks_for_server(args.discord_server_id))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
