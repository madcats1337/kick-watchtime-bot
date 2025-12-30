#!/usr/bin/env python3
"""
Sync Webhook Subscriptions

This script queries Kick's API for existing webhook subscriptions
and syncs them to the database. Use this when:
- Webhooks exist but subscription IDs are missing from database
- You see "Unknown subscription ID" errors in logs

Usage:
    python sync_webhook_subscriptions.py --discord-server-id 123456789
    python sync_webhook_subscriptions.py --all
"""

import os
import sys
import argparse
import asyncio
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
    sys.exit(1)

# Database connection
DATABASE_URL = os.getenv('DATABASE_URL', '')
if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

WEBHOOK_URL = "https://bot.lelebot.xyz/webhooks/kick"


def get_database_engine():
    if not DATABASE_URL:
        print("❌ Error: DATABASE_URL not set")
        sys.exit(1)
    return create_engine(DATABASE_URL, pool_pre_ping=True)


async def get_oauth_tokens(engine, discord_server_id: str):
    """Get OAuth tokens from database"""
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT key, value 
            FROM bot_settings
            WHERE discord_server_id = :server_id
            AND key IN ('kick_channel', 'kick_broadcaster_user_id', 'kick_access_token', 'kick_refresh_token')
        """), {"server_id": discord_server_id}).fetchall()
        
        if result:
            data = {}
            for row in result:
                key, value = row[0], row[1]
                if key == 'kick_channel':
                    data['username'] = value
                elif key == 'kick_broadcaster_user_id':
                    data['broadcaster_user_id'] = value
                elif key == 'kick_access_token':
                    data['access_token'] = value
                elif key == 'kick_refresh_token':
                    data['refresh_token'] = value
            return data
        return None


async def sync_webhooks_for_server(discord_server_id: str):
    """Query Kick API and sync webhook subscriptions to database"""
    print(f"\n{'='*60}")
    print(f"Syncing webhooks for Discord server: {discord_server_id}")
    print(f"{'='*60}\n")
    
    engine = get_database_engine()
    oauth_data = await get_oauth_tokens(engine, discord_server_id)
    
    if not oauth_data:
        print(f"❌ No OAuth data found for server {discord_server_id}")
        return False
    
    broadcaster_user_id = oauth_data.get('broadcaster_user_id')
    username = oauth_data.get('username', 'Unknown')
    access_token = oauth_data.get('access_token')
    
    print(f"✅ Found broadcaster: {username} (ID: {broadcaster_user_id})")
    
    client_id = os.getenv("KICK_CLIENT_ID")
    client_secret = os.getenv("KICK_CLIENT_SECRET")
    
    api = KickOfficialAPI(
        client_id=client_id,
        client_secret=client_secret,
        access_token=access_token
    )
    
    try:
        # Get existing webhooks from Kick
        print("\n📋 Fetching webhooks from Kick API...")
        subscriptions = await api.get_webhook_subscriptions()
        
        print(f"Found {len(subscriptions)} total webhook(s)")
        
        # Filter to this broadcaster's webhooks
        synced_count = 0
        for sub in subscriptions:
            sub_dict = sub.__dict__ if hasattr(sub, '__dict__') else sub
            sub_broadcaster = str(sub_dict.get('broadcaster_user_id', ''))
            
            if sub_broadcaster == str(broadcaster_user_id):
                sub_id = sub_dict.get('id')
                event = sub_dict.get('event')
                callback = sub_dict.get('callback_url')
                
                print(f"\n📥 Found subscription:")
                print(f"   ID: {sub_id}")
                print(f"   Event: {event}")
                print(f"   Callback: {callback}")
                
                if callback == WEBHOOK_URL:
                    # Check if this subscription is in the database
                    with engine.connect() as conn:
                        existing = conn.execute(text("""
                            SELECT subscription_id, webhook_secret 
                            FROM kick_webhook_subscriptions
                            WHERE subscription_id = :sub_id
                        """), {"sub_id": sub_id}).fetchone()
                        
                        if existing:
                            print(f"   ✅ Already in database")
                        else:
                            # Check if there's an entry with fallback ID
                            fallback_id = f"{broadcaster_user_id}_{event}"
                            fallback_entry = conn.execute(text("""
                                SELECT subscription_id, webhook_secret 
                                FROM kick_webhook_subscriptions
                                WHERE subscription_id = :fallback_id
                            """), {"fallback_id": fallback_id}).fetchone()
                            
                            if fallback_entry:
                                webhook_secret = fallback_entry[1]
                                print(f"   🔄 Found fallback entry, updating to real ID...")
                                
                                # Update the subscription_id
                                with engine.begin() as txn_conn:
                                    txn_conn.execute(text("""
                                        UPDATE kick_webhook_subscriptions
                                        SET subscription_id = :new_id
                                        WHERE subscription_id = :old_id
                                    """), {"new_id": sub_id, "old_id": fallback_id})
                                
                                print(f"   ✅ Updated: {fallback_id} -> {sub_id}")
                                synced_count += 1
                            else:
                                print(f"   ⚠️  Not in database and no fallback entry found")
                                print(f"   💡 Run setup_webhooks.py to properly register webhooks")
                else:
                    print(f"   ⏭️  Different callback URL, skipping")
        
        print(f"\n{'='*60}")
        print(f"Sync complete: {synced_count} subscription(s) updated")
        print(f"{'='*60}\n")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        await api.close()


async def sync_all_servers():
    """Sync webhooks for all configured servers"""
    engine = get_database_engine()
    
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT DISTINCT discord_server_id 
            FROM bot_settings 
            WHERE key = 'kick_access_token'
            AND value IS NOT NULL
            AND value != ''
        """)).fetchall()
        
        server_ids = [row[0] for row in result]
    
    if not server_ids:
        print("❌ No servers found with Kick OAuth configured")
        return
    
    print(f"✅ Found {len(server_ids)} server(s)")
    
    for server_id in server_ids:
        await sync_webhooks_for_server(server_id)


def main():
    parser = argparse.ArgumentParser(description="Sync Kick webhook subscriptions to database")
    parser.add_argument('--discord-server-id', type=str, help='Discord server ID')
    parser.add_argument('--all', action='store_true', help='Sync all servers')
    
    args = parser.parse_args()
    
    if not args.discord_server_id and not args.all:
        parser.print_help()
        sys.exit(1)
    
    if args.all:
        asyncio.run(sync_all_servers())
    else:
        asyncio.run(sync_webhooks_for_server(args.discord_server_id))


if __name__ == "__main__":
    main()
