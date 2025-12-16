#!/usr/bin/env python3
"""
Register Kick webhook subscription for chat.message.sent events.

This script registers your bot to receive chat messages via webhooks instead of the deprecated Pusher system.
Run this once per broadcaster channel you want to monitor.

Usage:
    python register_kick_webhook.py --broadcaster-id 152837 --webhook-url https://bot.lelebot.xyz/webhooks/kick
"""

import os
import sys
import argparse
import asyncio
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add parent directory to path to import core modules
sys.path.insert(0, os.path.dirname(__file__))

try:
    from core.kick_official_api import KickOfficialAPI
except ImportError:
    print("❌ Error: Could not import KickOfficialAPI")
    print("Make sure you're in the Kick-dicord-bot directory and core/kick_official_api.py exists")
    sys.exit(1)


async def register_webhook(broadcaster_user_id: str, webhook_url: str, access_token: str = None):
    """
    Register a webhook subscription for chat messages.
    
    Args:
        broadcaster_user_id: The Kick broadcaster user ID (e.g., "152837")
        webhook_url: The webhook endpoint URL (e.g., "https://bot.lelebot.xyz/webhooks/kick")
        access_token: Optional OAuth access token (will use client credentials if not provided)
    """
    client_id = os.getenv("KICK_CLIENT_ID")
    client_secret = os.getenv("KICK_CLIENT_SECRET")
    
    if not client_id or not client_secret:
        print("❌ Error: KICK_CLIENT_ID and KICK_CLIENT_SECRET must be set in environment variables")
        sys.exit(1)
    
    print(f"🔧 Registering webhook subscription...")
    print(f"   Broadcaster User ID: {broadcaster_user_id}")
    print(f"   Webhook URL: {webhook_url}")
    print(f"   Event: chat.message.sent")
    print()
    
    api = KickOfficialAPI(
        client_id=client_id,
        client_secret=client_secret,
        access_token=access_token
    )
    
    try:
        # Get access token if not provided
        if not access_token:
            print("🔑 Getting access token using client credentials...")
            token_data = await api.get_client_credentials_token()
            api.access_token = token_data.get("access_token")
            print(f"✅ Got access token (expires in {token_data.get('expires_in')}s)")
            print()
        
        # List existing subscriptions first
        print("📋 Checking existing subscriptions...")
        existing = await api.get_webhook_subscriptions()
        
        if existing:
            print(f"Found {len(existing)} existing subscription(s):")
            for sub in existing:
                sub_dict = sub.__dict__ if hasattr(sub, '__dict__') else sub
                print(f"  • ID: {sub_dict.get('id')}")
                print(f"    Event: {sub_dict.get('event')}")
                print(f"    Broadcaster: {sub_dict.get('broadcaster_user_id')}")
                print(f"    Callback: {sub_dict.get('callback_url')}")
                print(f"    Status: {sub_dict.get('status')}")
                print()
        else:
            print("No existing subscriptions found")
            print()
        
        # Check if subscription already exists
        for sub in existing:
            sub_dict = sub.__dict__ if hasattr(sub, '__dict__') else sub
            if (sub_dict.get('event') == 'chat.message.sent' and 
                sub_dict.get('broadcaster_user_id') == broadcaster_user_id and
                sub_dict.get('callback_url') == webhook_url):
                print(f"✅ Webhook subscription already exists (ID: {sub_dict.get('id')})")
                print("No action needed!")
                return
        
        # Subscribe to chat.message.sent events
        print("📨 Creating new webhook subscription...")
        subscription = await api.subscribe_webhook(
            event="chat.message.sent",
            callback_url=webhook_url,
            broadcaster_user_id=broadcaster_user_id
        )
        
        sub_dict = subscription.__dict__ if hasattr(subscription, '__dict__') else subscription
        
        print()
        print("✅ Webhook subscription created successfully!")
        print(f"   Subscription ID: {sub_dict.get('id')}")
        print(f"   Event: {sub_dict.get('event')}")
        print(f"   Broadcaster User ID: {sub_dict.get('broadcaster_user_id')}")
        print(f"   Callback URL: {sub_dict.get('callback_url')}")
        print(f"   Status: {sub_dict.get('status')}")
        print()
        print("🎉 All set! Your bot will now receive chat messages via webhooks.")
        print("   The old Pusher system can now be disabled.")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        await api.close()


async def list_subscriptions(access_token: str = None):
    """List all existing webhook subscriptions."""
    client_id = os.getenv("KICK_CLIENT_ID")
    client_secret = os.getenv("KICK_CLIENT_SECRET")
    
    if not client_id or not client_secret:
        print("❌ Error: KICK_CLIENT_ID and KICK_CLIENT_SECRET must be set in environment variables")
        sys.exit(1)
    
    api = KickOfficialAPI(
        client_id=client_id,
        client_secret=client_secret,
        access_token=access_token
    )
    
    try:
        # Get access token if not provided
        if not access_token:
            print("🔑 Getting access token...")
            token_data = await api.get_client_credentials_token()
            api.access_token = token_data.get("access_token")
            print()
        
        subscriptions = await api.get_webhook_subscriptions()
        
        if not subscriptions:
            print("📋 No webhook subscriptions found")
            return
        
        print(f"📋 Found {len(subscriptions)} webhook subscription(s):\n")
        
        for i, sub in enumerate(subscriptions, 1):
            sub_dict = sub.__dict__ if hasattr(sub, '__dict__') else sub
            print(f"{i}. Subscription ID: {sub_dict.get('id')}")
            print(f"   Event: {sub_dict.get('event')}")
            print(f"   Broadcaster User ID: {sub_dict.get('broadcaster_user_id')}")
            print(f"   Callback URL: {sub_dict.get('callback_url')}")
            print(f"   Status: {sub_dict.get('status')}")
            print(f"   Created: {sub_dict.get('created_at')}")
            print()
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        await api.close()


def main():
    parser = argparse.ArgumentParser(
        description="Register Kick webhook subscriptions for chat messages",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Register webhook for broadcaster ID 152837
  python register_kick_webhook.py --broadcaster-id 152837 --webhook-url https://bot.lelebot.xyz/webhooks/kick
  
  # List existing subscriptions
  python register_kick_webhook.py --list
  
  # Use custom access token
  python register_kick_webhook.py --broadcaster-id 152837 --webhook-url https://bot.lelebot.xyz/webhooks/kick --token YOUR_TOKEN
        """
    )
    
    parser.add_argument(
        '--broadcaster-id',
        type=str,
        help='Kick broadcaster user ID (e.g., 152837 for maikelele)'
    )
    
    parser.add_argument(
        '--webhook-url',
        type=str,
        help='Webhook callback URL (e.g., https://bot.lelebot.xyz/webhooks/kick)'
    )
    
    parser.add_argument(
        '--token',
        type=str,
        help='OAuth access token (optional, will use client credentials if not provided)'
    )
    
    parser.add_argument(
        '--list',
        action='store_true',
        help='List existing webhook subscriptions'
    )
    
    args = parser.parse_args()
    
    if args.list:
        asyncio.run(list_subscriptions(access_token=args.token))
    elif args.broadcaster_id and args.webhook_url:
        asyncio.run(register_webhook(
            broadcaster_user_id=args.broadcaster_id,
            webhook_url=args.webhook_url,
            access_token=args.token
        ))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
