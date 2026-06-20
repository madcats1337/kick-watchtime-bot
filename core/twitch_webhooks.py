"""
Twitch EventSub Webhook Handler Module
Handles incoming EventSub notifications from Twitch.

Mirrors core/kick_webhooks.py. Key differences from Kick:
- Twitch first sends a `webhook_callback_verification` request that we MUST answer
  by echoing the `challenge` value as plain-text 200, or the subscription never
  activates. (https://dev.twitch.tv/docs/eventsub/handling-webhook-events/)
- Signatures are HMAC-SHA256 over (message_id + timestamp + raw_body) keyed by the
  per-subscription secret (Twitch-Eventsub-Message-Signature: "sha256=..."), not
  RSA like Kick.
- A `revocation` message type tells us a subscription was dropped by Twitch.

Reuse strategy: we normalize Twitch stream events into the SAME payload shape the
Kick `livestream.status.updated` handler consumes, then dispatch to the shared
notifier so go-live behavior is identical across platforms.

Usage:
    from core.twitch_webhooks import register_twitch_webhook_routes, TwitchWebhookEventHandler
    register_twitch_webhook_routes(app, event_handler)
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Optional

from flask import Blueprint, jsonify, request

from .twitch_api import (
    HDR_MESSAGE_ID,
    HDR_MESSAGE_SIGNATURE,
    HDR_MESSAGE_TIMESTAMP,
    HDR_MESSAGE_TYPE,
    HDR_SUBSCRIPTION_TYPE,
    MSG_TYPE_NOTIFICATION,
    MSG_TYPE_REVOCATION,
    MSG_TYPE_VERIFICATION,
    verify_eventsub_signature,
)

logger = logging.getLogger(__name__)

# Reject notifications whose timestamp is older than this (replay protection).
MAX_MESSAGE_AGE = timedelta(minutes=10)

twitch_webhooks_bp = Blueprint("twitch_webhooks", __name__)

_tables_initialized = False


def ensure_webhook_tables(engine):
    """Ensure the dedup table exists. Shares `processed_webhook_messages` with the
    Kick handler — message_id is unique across both since Twitch and Kick IDs never
    collide and the column is platform-agnostic."""
    global _tables_initialized
    if _tables_initialized:
        return
    try:
        from sqlalchemy import text

        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                CREATE TABLE IF NOT EXISTS processed_webhook_messages (
                    id SERIAL PRIMARY KEY,
                    message_id VARCHAR(255) NOT NULL,
                    broadcaster_user_id VARCHAR(50) NOT NULL,
                    event_type VARCHAR(100),
                    processed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    CONSTRAINT unique_message_id UNIQUE (message_id)
                )
                """
                )
            )
        _tables_initialized = True
        logger.info("[Twitch Webhook] ✅ Webhook tables ready")
    except Exception as e:
        logger.info(f"[Twitch Webhook] ⚠️ Could not initialize tables: {e}")


# -------------------------
# Event Handler Class
# -------------------------


class TwitchWebhookEventHandler:
    """Register callbacks per EventSub subscription type, then dispatch via handle()."""

    def __init__(self):
        self._handlers: Dict[str, Callable] = {}
        self._default_handler: Optional[Callable] = None

    def on(self, sub_type: str):
        def decorator(func):
            self._handlers[sub_type] = func
            return func

        return decorator

    def set_default_handler(self, func):
        self._default_handler = func
        return func

    async def handle(self, sub_type: str, event_data: Dict[str, Any]) -> bool:
        handler = self._handlers.get(sub_type, self._default_handler)
        if handler is None:
            logger.info(f"[Twitch Webhook] ⚠️ No handler for type: {sub_type}")
            return False
        try:
            if asyncio.iscoroutinefunction(handler):
                await handler(event_data)
            else:
                handler(event_data)
            return True
        except Exception as e:
            logger.info(f"[Twitch Webhook] ❌ Error in handler for {sub_type}: {e}")
            import traceback

            traceback.print_exc()
            return False


_event_handler: Optional[TwitchWebhookEventHandler] = None


# -------------------------
# Helpers
# -------------------------


def _timestamp_too_old(timestamp: str) -> bool:
    """True if the EventSub message timestamp is older than MAX_MESSAGE_AGE."""
    if not timestamp:
        return False
    try:
        # Twitch sends RFC3339 with nanoseconds, e.g. 2023-01-01T00:00:00.123456789Z
        ts = timestamp.replace("Z", "+00:00")
        # Python can't parse 9-digit fractional seconds; trim to 6.
        if "." in ts:
            head, frac = ts.split(".", 1)
            tzpart = ""
            for marker in ("+", "-"):
                if marker in frac:
                    frac, tzpart = frac.split(marker, 1)
                    tzpart = marker + tzpart
                    break
            frac = frac[:6]
            ts = f"{head}.{frac}{tzpart}"
        parsed = datetime.fromisoformat(ts)
        return datetime.now(timezone.utc) - parsed > MAX_MESSAGE_AGE
    except Exception:
        # If we can't parse it, don't reject on age alone.
        return False


def _resolve_subscription(subscription_id: str, broadcaster_user_id: str = None):
    """Look up (discord_server_id, broadcaster_user_id, webhook_secret) for a sub.

    Does NOT filter on status: the verification challenge arrives while the sub is
    still 'webhook_callback_verification_pending', and we need its secret to answer
    it. Excludes only deleted/revoked rows.

    Falls back to matching by broadcaster_user_id when the subscription_id isn't in
    our DB yet (a row-commit race right after creation). All of a broadcaster's
    subs share one secret, so the secret + server resolve correctly either way.

    Returns (None, None, None) if unknown.
    """
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        return None, None, None
    from sqlalchemy import create_engine, text

    engine = create_engine(db_url, pool_pre_ping=True)
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT discord_server_id, broadcaster_user_id, webhook_secret
                FROM twitch_webhook_subscriptions
                WHERE subscription_id = :sub_id
                  AND status NOT IN ('deleted', 'revoked')
                """
            ),
            {"sub_id": subscription_id},
        ).fetchone()
        if not row and broadcaster_user_id:
            row = conn.execute(
                text(
                    """
                    SELECT discord_server_id, broadcaster_user_id, webhook_secret
                    FROM twitch_webhook_subscriptions
                    WHERE broadcaster_user_id = :bid
                      AND status NOT IN ('deleted', 'revoked')
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """
                ),
                {"bid": str(broadcaster_user_id)},
            ).fetchone()
    if not row:
        return None, None, None
    return row[0], row[1], row[2]


def _already_processed(message_id: str, broadcaster_user_id: str, event_type: str) -> bool:
    """Idempotency check + record. True if this message_id was already handled."""
    if not message_id:
        return False
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        return False
    try:
        from sqlalchemy import create_engine, text

        engine = create_engine(db_url, pool_pre_ping=True)
        with engine.begin() as conn:
            existing = conn.execute(
                text(
                    """
                    SELECT id FROM processed_webhook_messages
                    WHERE message_id = :msg_id LIMIT 1
                    """
                ),
                {"msg_id": message_id},
            ).fetchone()
            if existing:
                return True
            conn.execute(
                text(
                    """
                    INSERT INTO processed_webhook_messages
                        (message_id, broadcaster_user_id, event_type, processed_at)
                    VALUES (:msg_id, :broadcaster_id, :event_type, NOW())
                    ON CONFLICT (message_id) DO NOTHING
                    """
                ),
                {
                    "msg_id": message_id,
                    "broadcaster_id": str(broadcaster_user_id or ""),
                    "event_type": event_type,
                },
            )
        return False
    except Exception as e:
        # Fail open — better to process twice than drop a real event.
        logger.info(f"[Twitch Webhook] ⚠️ Dedup check failed: {e}")
        return False


def _run_async(coro):
    """Run a coroutine to completion from this sync Flask handler."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# -------------------------
# Flask Route
# -------------------------


@twitch_webhooks_bp.route("/webhooks/twitch", methods=["POST"])
def handle_twitch_webhook():
    """
    EventSub webhook endpoint.
    https://dev.twitch.tv/docs/eventsub/handling-webhook-events/

    Returns 200/204 on success, 2xx for already-processed/unknown (so Twitch stops
    retrying), 401 on bad signature, 4xx/5xx otherwise.
    """
    raw_body: bytes = request.get_data(cache=True)

    message_id = request.headers.get(HDR_MESSAGE_ID, "")
    message_timestamp = request.headers.get(HDR_MESSAGE_TIMESTAMP, "")
    signature = request.headers.get(HDR_MESSAGE_SIGNATURE, "")
    message_type = request.headers.get(HDR_MESSAGE_TYPE, "")
    sub_type = request.headers.get(HDR_SUBSCRIPTION_TYPE, "")

    # Parse just enough to get the subscription id (present on all message types).
    try:
        body = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except json.JSONDecodeError:
        return jsonify({"error": "Invalid JSON"}), 400

    subscription = body.get("subscription", {}) or {}
    subscription_id = subscription.get("id", "")
    # The broadcaster id is in the subscription condition; used as a fallback to
    # find the shared secret if the sub row hasn't committed yet (creation race).
    cond = subscription.get("condition", {}) or {}
    cond_broadcaster_id = cond.get("broadcaster_user_id")

    if not subscription_id:
        logger.info("[Twitch Webhook] ❌ Missing subscription id in payload")
        return jsonify({"error": "Missing subscription id"}), 400

    # 1️⃣ Resolve subscription context + secret from our DB.
    try:
        discord_server_id, broadcaster_user_id, webhook_secret = _resolve_subscription(
            subscription_id, cond_broadcaster_id
        )
    except Exception as db_err:
        logger.info(f"[Twitch Webhook] ❌ Database error: {db_err}")
        return jsonify({"error": "Database error"}), 500

    if not webhook_secret:
        # Unknown sub (legacy/stale) — 200 so Twitch stops retrying.
        logger.info(f"[Twitch Webhook] ⚠️ Unknown subscription {subscription_id}, ignoring")
        return jsonify({"status": "ok", "message": "unknown subscription"}), 200

    # 2️⃣ Verify HMAC signature against the stored secret.
    if not verify_eventsub_signature(webhook_secret, message_id, message_timestamp, raw_body, signature):
        logger.info(f"[Twitch Webhook] ❌ Invalid signature for {subscription_id}")
        return jsonify({"error": "Invalid signature"}), 403

    # 3️⃣ Replay protection.
    if _timestamp_too_old(message_timestamp):
        logger.info(f"[Twitch Webhook] ⚠️ Stale message {message_id} (>10m), ignoring")
        return jsonify({"status": "ok", "message": "stale"}), 200

    # 4️⃣ Verification challenge — echo it back as plain text.
    if message_type == MSG_TYPE_VERIFICATION:
        challenge = body.get("challenge", "")
        logger.info(f"[Twitch Webhook] ✅ Challenge for {subscription_id} ({sub_type})")
        return challenge, 200, {"Content-Type": "text/plain"}

    # 5️⃣ Revocation — mark the subscription dead.
    if message_type == MSG_TYPE_REVOCATION:
        status = subscription.get("status", "revoked")
        logger.info(f"[Twitch Webhook] ⚠️ Subscription {subscription_id} revoked: {status}")
        try:
            from sqlalchemy import create_engine, text

            engine = create_engine(os.getenv("DATABASE_URL"), pool_pre_ping=True)
            with engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        UPDATE twitch_webhook_subscriptions
                        SET status = 'revoked', updated_at = NOW()
                        WHERE subscription_id = :sub_id
                        """
                    ),
                    {"sub_id": subscription_id},
                )
        except Exception as e:
            logger.info(f"[Twitch Webhook] ⚠️ Failed to mark revoked: {e}")
        return jsonify({"status": "ok"}), 200

    if message_type != MSG_TYPE_NOTIFICATION:
        logger.info(f"[Twitch Webhook] ⚠️ Unexpected message type: {message_type}")
        return jsonify({"status": "ok"}), 200

    # 6️⃣ Idempotency.
    if _already_processed(message_id, broadcaster_user_id, sub_type):
        logger.info(f"[Twitch Webhook] ℹ️ Duplicate {message_id}, already processed")
        return jsonify({"status": "ok", "message": "already processed"}), 200

    # 7️⃣ Dispatch the event.
    event = body.get("event", {}) or {}
    event["_server_id"] = discord_server_id
    event["_broadcaster_user_id"] = broadcaster_user_id
    event["_subscription_type"] = sub_type
    event["_platform"] = "twitch"

    logger.info(f"[Twitch Webhook] 📥 {sub_type} for server {discord_server_id}")

    try:
        if _event_handler:
            _run_async(_event_handler.handle(sub_type, event))
        else:
            logger.info(f"[Twitch Webhook] Event: {json.dumps(event, default=str)}")
        return jsonify({"status": "ok", "message_id": message_id}), 200
    except Exception as e:
        logger.info(f"[Twitch Webhook] ❌ Error processing webhook: {e}")
        import traceback

        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@twitch_webhooks_bp.route("/webhooks/twitch/test", methods=["GET"])
def test_twitch_webhook_endpoint():
    return (
        jsonify(
            {
                "status": "ok",
                "message": "Twitch webhook server is running",
                "endpoint": "/webhooks/twitch",
            }
        ),
        200,
    )


def register_twitch_webhook_routes(app, event_handler: TwitchWebhookEventHandler = None):
    """Register Twitch webhook routes with a Flask app."""
    global _event_handler
    _event_handler = event_handler
    app.register_blueprint(twitch_webhooks_bp)
    logger.info("[Twitch Webhook] ✅ Registered Twitch webhook routes at /webhooks/twitch")


# -------------------------
# Pre-built event handler — normalizes Twitch events to the shared notifier
# -------------------------


def create_twitch_event_handler():
    """
    Build a TwitchWebhookEventHandler whose stream events reuse the SAME go-live
    notification path as Kick by normalizing payloads into the Kick
    `livestream.status.updated` shape and delegating to the shared sender.
    """
    handler = TwitchWebhookEventHandler()

    def _broadcaster_name(event: Dict[str, Any]) -> str:
        return event.get("broadcaster_user_name") or event.get("broadcaster_user_login") or ""

    async def _notify_stream_status(event: Dict[str, Any], is_live: bool, title: str = "", category: str = ""):
        """Reuse the shared stream-notification sender (see send_stream_notification
        in the notifier module) with platform='twitch'."""
        from core.stream_notifications import send_stream_notification

        await send_stream_notification(
            discord_server_id=event.get("_server_id"),
            streamer=_broadcaster_name(event),
            is_live=is_live,
            title=title,
            category=category,
            platform="twitch",
        )

    @handler.on("stream.online")
    async def on_stream_online(event):
        logger.info(f"[Twitch Webhook] 📺 stream.online: {_broadcaster_name(event)}")
        # channel.update carries title/category; stream.online does not, so fetch
        # current channel info inside the notifier if needed.
        await _notify_stream_status(event, is_live=True)

    @handler.on("stream.offline")
    async def on_stream_offline(event):
        logger.info(f"[Twitch Webhook] ⚫ stream.offline: {_broadcaster_name(event)}")
        await _notify_stream_status(event, is_live=False)

    @handler.on("channel.update")
    async def on_channel_update(event):
        # Title/category changed mid-stream; not a go-live, but useful for keeping
        # the latest title/category cached. No Discord post here.
        logger.info(
            f"[Twitch Webhook] ✏️ channel.update: {_broadcaster_name(event)} "
            f"title={event.get('title')!r} category={event.get('category_name')!r}"
        )

    @handler.on("channel.chat.message")
    async def on_chat_message(event):
        # Normalize to the shared chat handler so watchtime/points/!commands/
        # bonus-hunt/slot/GTB all work for Twitch (Phase 3 wires the handler).
        from core.stream_provider import dispatch_twitch_chat_message

        await dispatch_twitch_chat_message(event)

    return handler


__all__ = [
    "twitch_webhooks_bp",
    "TwitchWebhookEventHandler",
    "register_twitch_webhook_routes",
    "create_twitch_event_handler",
]
