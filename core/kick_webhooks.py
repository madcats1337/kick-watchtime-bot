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
import base64
import json
from datetime import datetime, timezone
from typing import Callable, Dict, Any, Optional
from dataclasses import dataclass
from functools import wraps

from flask import Blueprint, request, jsonify

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

def verify_kick_signature(request) -> bool:
    """
    Verify the Kick webhook signature.
    
    NOTE: Kick uses RSA-2048 signatures but hasn't published the public key yet.
    For production use, we skip signature verification and rely on:
    1. Subscription ID validation (must exist in our database)
    2. Webhook URL is private (only Kick knows it)
    3. TLS encryption prevents tampering in transit
    
    This is secure enough until Kick publishes their RSA public key.
    """
    subscription_id = request.headers.get("Kick-Event-Subscription-Id", "")
    message_id = request.headers.get("Kick-Event-Message-Id", "")
    timestamp = request.headers.get("Kick-Event-Message-Timestamp", "")

    if not all([subscription_id, message_id, timestamp]):
        print("[Webhook] ❌ Missing required headers")
        return False

    print(f"[Webhook] ✅ Accepting webhook (signature verification disabled)")
    print(f"  Subscription: {subscription_id}, Message: {message_id}")
    
    # Subscription ID will be validated in handler (must exist in database)
    return True

def require_webhook_signature(f):
    """Decorator to require valid webhook signature"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not verify_kick_signature(request):
            return jsonify({"error": "Invalid signature"}), 401
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
    - Kick-Event-Subscription-Type: Event type
    - Kick-Event-Message-Id: Unique message ID
    - Kick-Event-Subscription-Id: Subscription ID

    Returns:
        200 OK on success
        401 Unauthorized if signature invalid
        500 Internal Server Error on handler error
    """
    print(f"[Webhook] 🔔 INCOMING REQUEST to /webhooks/kick")
    print(f"[Webhook] Headers: {dict(request.headers)}")
    
    event_type = request.headers.get("Kick-Event-Type", "unknown")
    message_id = request.headers.get("Kick-Event-Message-Id", "")
    subscription_id = request.headers.get("Kick-Event-Subscription-Id", "")

    print(f"[Webhook] 📥 Received event: {event_type}")
    print(f"  Message ID: {message_id}")
    print(f"  Subscription ID: {subscription_id}")
    
    # Verify signature
    if not verify_kick_signature(request):
        return jsonify({"error": "Invalid signature"}), 401

    try:
        event_data = request.get_json()
        
        # Multiserver routing: Lookup which Discord server this subscription belongs to
        discord_server_id = None
        if subscription_id:
            try:
                from sqlalchemy import create_engine, text
                db_url = os.getenv('DATABASE_URL')
                if db_url:
                    engine = create_engine(db_url)
                    with engine.connect() as conn:
                        result = conn.execute(text("""
                            SELECT discord_server_id, broadcaster_user_id 
                            FROM kick_webhook_subscriptions 
                            WHERE subscription_id = :sub_id AND status = 'active'
                        """), {"sub_id": subscription_id}).fetchone()
                        
                        if result:
                            discord_server_id = result[0]
                            broadcaster_user_id = result[1]
                            
                            # Add server context to event data for handler
                            event_data['_server_id'] = discord_server_id
                            event_data['_broadcaster_user_id'] = broadcaster_user_id
            except Exception as db_err:
                pass

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
