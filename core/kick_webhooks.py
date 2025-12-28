"""
Kick Webhook Handler Module
Handles incoming webhook events from Kick's official API

This module provides Flask routes and handlers for processing Kick webhook events:
- chat.message.sent - Chat messages
- channel.followed - New followers
- channel.subscription.new - New subscriptions
- channel.subscription.renewal - Subscription renewals
- channel.subscription.gifts - Gifted subscriptions
- livestream.status.updated - Stream live/offline events
- moderation.banned - User banned from chat
- kicks.gifted - Tips (Kicks) received

Usage:
    from core.kick_webhooks import register_webhook_routes, WebhookEventHandler

    # Register routes with Flask app
    register_webhook_routes(app, event_handler)
"""

import os
import hashlib
import hmac
import secrets
import json
from datetime import datetime, timezone
from typing import Callable, Dict, Any, Optional
from dataclasses import dataclass
from functools import wraps

from flask import Blueprint, request, jsonify, abort

# Import webhook payload classes
try:
    from .kick_official_api import (
        WebhookChatMessage,
        WebhookGiftedSubs,
        WebhookKicksGifted,
        WebhookLivestreamStatus,
        verify_webhook_signature,
    )
except ImportError:
    # Fallback definitions if import fails
    pass

# -------------------------
# Webhook Configuration
# -------------------------

WEBHOOK_SECRET = os.getenv("KICK_WEBHOOK_SECRET", "")

# Create Flask Blueprint for webhook routes
kick_webhooks_bp = Blueprint('kick_webhooks', __name__)

# -------------------------
# Signature Verification
# -------------------------

def verify_kick_signature(raw_body: bytes, signature_header: str, webhook_secret: str) -> bool:
    """
    Verify the Kick webhook signature using HMAC-SHA256.
    
    Args:
        raw_body: Raw request body as bytes
        signature_header: Signature from Kick-Signature header
        webhook_secret: The webhook secret for this broadcaster
    
    Returns:
        True if signature is valid, False otherwise
    """
    if not signature_header or not webhook_secret:
        return False
    
    try:
        # Compute expected signature
        expected_hash = hmac.new(
            key=webhook_secret.encode('utf-8'),
            msg=raw_body,
            digestmod=hashlib.sha256
        ).hexdigest()
        
        expected_signature = f"sha256={expected_hash}"
        
        # Constant-time comparison
        return hmac.compare_digest(expected_signature, signature_header.strip())
    except Exception as e:
        print(f"[Webhook] ❌ Signature verification error: {e}")
        return False

def require_webhook_signature(f):
    """Decorator to require valid webhook signature"""
    @wraps(f)
    def decorated(*args, **kwargs):
        # Note: Signature verification happens in the route handler
        # after we look up the secret from the database
        return f(*args, **kwargs)
    return decorated

# -------------------------
# Event Handler Class
# -------------------------

class WebhookEventHandler:
    """
    Handler for Kick webhook events.

    Register callbacks for specific event types, then pass events to handle().

    Usage:
        handler = WebhookEventHandler()

        @handler.on("chat.message.sent")
        async def handle_chat(event_data):
            print(f"Chat: {event_data['sender']['username']}: {event_data['content']}")

        @handler.on("channel.subscription.gifts")
        async def handle_gifted_subs(event_data):
            gifter = event_data['gifter']['username']
            count = len(event_data['giftees'])
            print(f"{gifter} gifted {count} subs!")
    """

    def __init__(self):
        self._handlers: Dict[str, Callable] = {}
        self._default_handler: Optional[Callable] = None

    def on(self, event_type: str):
        """
        Decorator to register a handler for an event type.

        Args:
            event_type: The webhook event type (e.g., "chat.message.sent")
        """
        def decorator(func):
            self._handlers[event_type] = func
            return func
        return decorator

    def set_default_handler(self, func):
        """Set a default handler for unregistered event types"""
        self._default_handler = func
        return func

    async def handle(self, event_type: str, event_data: Dict[str, Any]) -> bool:
        """
        Handle a webhook event.

        Args:
            event_type: The event type from webhook headers
            event_data: The parsed JSON payload

        Returns:
            True if handler was found and executed
        """
        handler = self._handlers.get(event_type, self._default_handler)

        if handler is None:
            print(f"[Webhook] ⚠️ No handler for event type: {event_type}")
            return False

        try:
            # Check if handler is async
            import asyncio
            if asyncio.iscoroutinefunction(handler):
                await handler(event_data)
            else:
                handler(event_data)
            return True
        except Exception as e:
            print(f"[Webhook] ❌ Error in handler for {event_type}: {e}")
            import traceback
            traceback.print_exc()
            return False

# -------------------------
# Flask Routes
# -------------------------

# Global event handler (set via register_webhook_routes)
_event_handler: Optional[WebhookEventHandler] = None

@kick_webhooks_bp.route('/webhooks/kick', methods=['POST'])
def handle_kick_webhook():
    """
    Main webhook endpoint for Kick events.

    Expected Headers:
    - Kick-Event-Type: Event type
    - Kick-Event-Message-Id: Unique message ID
    - Kick-Event-Subscription-Id: Subscription ID
    - Kick-Signature: HMAC-SHA256 signature

    Returns:
        200 OK on success
        401 Unauthorized if signature invalid
        500 Internal Server Error on handler error
    """
    # 1️⃣ GET RAW BODY FIRST (before any parsing)
    raw_body: bytes = request.get_data(cache=True)
    
    # 2️⃣ GET HEADERS
    event_type = request.headers.get("Kick-Event-Type", "unknown")
    message_id = request.headers.get("Kick-Event-Message-Id", "")
    subscription_id = request.headers.get("Kick-Event-Subscription-Id", "")
    signature_header = (
        request.headers.get("Kick-Signature")
        or request.headers.get("X-Kick-Signature")
    )
    
    if not signature_header:
        print("[Webhook] ❌ Missing signature header")
        return jsonify({"error": "Missing signature"}), 401
    
    if not subscription_id:
        print("[Webhook] ❌ Missing subscription ID")
        return jsonify({"error": "Missing subscription ID"}), 400

    try:
        # 3️⃣ PARSE JSON AFTER RAW BODY
        try:
            event_data = json.loads(raw_body.decode('utf-8'))
        except json.JSONDecodeError:
            return jsonify({"error": "Invalid JSON"}), 400
        
        # 4️⃣ EXTRACT BROADCASTER ID
        broadcaster_id = (
            event_data.get("broadcaster", {}).get("id")
            or event_data.get("channel", {}).get("id")
            or event_data.get("data", {}).get("broadcaster_id")
        )
        
        if not broadcaster_id:
            print("[Webhook] ❌ Missing broadcaster ID in payload")
            return jsonify({"error": "Missing broadcaster ID"}), 400
        
        # 5️⃣ MULTISERVER ROUTING: Look up Discord server & webhook secret for this subscription
        discord_server_id = None
        webhook_secret = None
        
        try:
            from sqlalchemy import create_engine, text
            db_url = os.getenv('DATABASE_URL')
            if db_url:
                engine = create_engine(db_url, pool_pre_ping=True)
                with engine.connect() as conn:
                    result = conn.execute(text("""
                        SELECT discord_server_id, broadcaster_user_id, webhook_secret
                        FROM kick_webhook_subscriptions 
                        WHERE subscription_id = :sub_id AND status = 'active'
                    """), {"sub_id": subscription_id}).fetchone()
                    
                    if result:
                        discord_server_id = result[0]
                        broadcaster_user_id = result[1]
                        webhook_secret = result[2]
                        
                        # Add server context to event data for handler
                        event_data['_server_id'] = discord_server_id
                        event_data['_broadcaster_user_id'] = broadcaster_user_id
                        
                        print(f"[Webhook] 📥 Event for server {discord_server_id}, broadcaster {broadcaster_user_id}")
                    else:
                        print(f"[Webhook] ❌ Unknown subscription ID: {subscription_id}")
                        return jsonify({"error": "Unknown subscription"}), 401
        except Exception as db_err:
            print(f"[Webhook] ❌ Database error: {db_err}")
            return jsonify({"error": "Database error"}), 500
        
        if not webhook_secret:
            print(f"[Webhook] ❌ No webhook secret found for subscription {subscription_id}")
            return jsonify({"error": "No webhook secret"}), 401
        
        # 6️⃣ VERIFY SIGNATURE
        if not verify_kick_signature(raw_body, signature_header, webhook_secret):
            print(f"[Webhook] ❌ Invalid signature for subscription {subscription_id}")
            return jsonify({"error": "Invalid signature"}), 401
        
        print(f"[Webhook] ✅ Signature verified for subscription {subscription_id}")

        # 7️⃣ HANDLE EVENT
        if _event_handler:
            import asyncio
            # Run async handler in event loop
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(_event_handler.handle(event_type, event_data))
            finally:
                loop.close()
        else:
            _log_event(event_type, event_data)

        return jsonify({"status": "ok", "message_id": message_id}), 200

    except Exception as e:
        print(f"[Webhook] ❌ Error processing webhook: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@kick_webhooks_bp.route('/webhooks/kick/challenge', methods=['GET', 'POST'])
def handle_webhook_challenge():
    """
    Handle Kick webhook verification challenge.

    Kick may send a challenge request when registering webhooks.
    We need to echo back the challenge value.
    """
    if request.method == 'GET':
        challenge = request.args.get('challenge', '')
    else:
        data = request.get_json() or {}
        challenge = data.get('challenge', '')

    if challenge:
        return challenge, 200, {'Content-Type': 'text/plain'}

    return jsonify({"status": "ready"}), 200

@kick_webhooks_bp.route('/webhooks/kick/test', methods=['GET'])
def test_webhook_endpoint():
    """Test endpoint to verify webhook server is reachable"""
    return jsonify({
        "status": "ok", 
        "message": "Webhook server is running",
        "endpoint": "/webhooks/kick",
        "secret_configured": bool(WEBHOOK_SECRET)
    }), 200

def _log_event(event_type: str, event_data: Dict[str, Any]):
    """Log webhook event for debugging (used when no handler registered)"""
    print(f"[Webhook] Event Data:")
    print(json.dumps(event_data, indent=2, default=str))

# -------------------------
# Registration Function
# -------------------------

def register_webhook_routes(app, event_handler: WebhookEventHandler = None):
    """
    Register webhook routes with a Flask app.

    Args:
        app: Flask application
        event_handler: Optional WebhookEventHandler for processing events
    """
    global _event_handler
    _event_handler = event_handler

    app.register_blueprint(kick_webhooks_bp)
    print("[Webhook] ✅ Registered Kick webhook routes at /webhooks/kick")

# -------------------------
# Pre-built Event Handlers
# -------------------------

def create_discord_notifier(discord_bot, channel_id: int):
    """
    Create a WebhookEventHandler that sends notifications to Discord.

    Args:
        discord_bot: Discord bot instance
        channel_id: Discord channel ID for notifications

    Returns:
        Configured WebhookEventHandler
    """
    handler = WebhookEventHandler()

    @handler.on("channel.subscription.new")
    async def on_new_sub(data):
        """Handle new subscription"""
        subscriber = data.get("subscriber", {}).get("username", "Unknown")
        duration = data.get("duration", 1)
        broadcaster = data.get("broadcaster", {}).get("username", "")

        channel = discord_bot.get_channel(channel_id)
        if channel:
            await channel.send(
                f"🎉 **New Subscriber!**\n"
                f"**{subscriber}** just subscribed to **{broadcaster}** ({duration} month(s))!"
            )

    @handler.on("channel.subscription.gifts")
    async def on_gifted_subs(data):
        """Handle gifted subscriptions"""
        gifter = data.get("gifter", {}).get("username", "Anonymous")
        giftees = data.get("giftees", [])
        count = len(giftees)
        broadcaster = data.get("broadcaster", {}).get("username", "")
        discord_server_id = data.get("_server_id")

        # Track in raffle system
        if discord_server_id:
            try:
                from raffle_system.gifted_sub_tracker import track_gifted_sub
                from sqlalchemy import create_engine, text
                
                db_url = os.getenv('DATABASE_URL')
                if db_url:
                    engine = create_engine(db_url, pool_pre_ping=True)
                    with engine.connect() as conn:
                        # Get active raffle period
                        period_result = conn.execute(text("""
                            SELECT id FROM raffle_periods
                            WHERE status = 'active' AND discord_server_id = :guild_id
                            LIMIT 1
                        """), {"guild_id": discord_server_id}).fetchone()
                        
                        if period_result:
                            period_id = period_result[0]
                            
                            # Track each giftee
                            for giftee in giftees:
                                giftee_username = giftee.get("username")
                                if giftee_username:
                                    # Track gifted sub for raffle
                                    await track_gifted_sub(
                                        kick_username=giftee_username,
                                        guild_id=discord_server_id,
                                        period_id=period_id
                                    )
                            
                            print(f"[Webhook] ✅ Tracked {count} gifted subs for raffle")
            except Exception as e:
                print(f"[Webhook] ⚠️ Failed to track gifted subs in raffle: {e}")

        channel = discord_bot.get_channel(channel_id)
        if channel:
            giftee_names = ", ".join(g.get("username", "?") for g in giftees[:5])
            if count > 5:
                giftee_names += f" and {count - 5} more"

            await channel.send(
                f"🎁 **Gifted Subs!**\n"
                f"**{gifter}** gifted **{count}** sub(s) to **{broadcaster}**!\n"
                f"Recipients: {giftee_names}"
            )

    @handler.on("channel.subscription.renewal")
    async def on_sub_renewal(data):
        """Handle subscription renewal"""
        subscriber = data.get("subscriber", {}).get("username", "Unknown")
        duration = data.get("duration", 1)
        broadcaster = data.get("broadcaster", {}).get("username", "")
        discord_server_id = data.get("_server_id")
        
        print(f"[Webhook] 🔄 Sub renewal: {subscriber} renewed for {duration} month(s)")
        
        # Renewals could grant bonus tickets or other rewards in the future
        # For now, just log it
        
        channel = discord_bot.get_channel(channel_id)
        if channel:
            await channel.send(
                f"🔄 **Subscription Renewed!**\n"
                f"**{subscriber}** renewed their subscription to **{broadcaster}** ({duration} month(s))!"
            )

    @handler.on("kicks.gifted")
    async def on_kicks(data):
        """Handle Kicks (tips)"""
        sender = data.get("sender", {}).get("username", "Anonymous")
        amount = data.get("amount", 0)
        kick_count = data.get("kick_count", 0)
        broadcaster = data.get("broadcaster", {}).get("username", "")

        channel = discord_bot.get_channel(channel_id)
        if channel:
            await channel.send(
                f"💚 **Kicks Received!**\n"
                f"**{sender}** sent **{kick_count}** Kicks (${amount:.2f}) to **{broadcaster}**!"
            )

    @handler.on("livestream.status.updated")
    async def on_stream_status(data):
        """Handle stream going live/offline"""
        is_live = data.get("is_live", False)
        broadcaster = data.get("broadcaster", {}).get("username", "")
        title = data.get("livestream", {}).get("session_title", "")

        channel = discord_bot.get_channel(channel_id)
        if channel:
            if is_live:
                await channel.send(
                    f"🔴 **Stream Live!**\n"
                    f"**{broadcaster}** is now streaming!\n"
                    f"Title: {title}\n"
                    f"https://kick.com/{broadcaster}"
                )
            else:
                await channel.send(
                    f"⚫ **Stream Ended**\n"
                    f"**{broadcaster}** has ended their stream."
                )

    @handler.on("channel.followed")
    async def on_follow(data):
        """Handle new follower"""
        follower = data.get("follower", {}).get("username", "Unknown")
        broadcaster = data.get("broadcaster", {}).get("username", "")

        channel = discord_bot.get_channel(channel_id)
        if channel:
            await channel.send(
                f"👋 **New Follower!**\n"
                f"**{follower}** just followed **{broadcaster}**!"
            )

    return handler

# Export all public interfaces
__all__ = [
    'kick_webhooks_bp',
    'WebhookEventHandler',
    'register_webhook_routes',
    'create_discord_notifier',
    'verify_kick_signature',
    'require_webhook_signature',
]
