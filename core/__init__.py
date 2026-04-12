"""
Core modules for Kick Discord Bot

Modules:
- kick_api: Hybrid API client (official + unofficial fallback)
- kick_official_api: Official Kick API client with OAuth 2.1
- kick_webhooks: Webhook event handlers for Kick events
- oauth_server: Flask OAuth server for user linking and bot authorization
"""

from .kick_api import (
    HAS_OFFICIAL_API,
    KickAPI,
    KickHybridAPI,
    check_stream_live,
    create_clip,
    fetch_chatroom_id,
    get_channel_info,
    get_clips,
)
from .kick_official_api import OAUTH_SCOPES, WEBHOOK_EVENTS, KickOfficialAPI, OAuthTokens, verify_webhook_signature
from .kick_webhooks import WebhookEventHandler, create_discord_notifier, register_webhook_routes

__all__ = [
    # Hybrid API
    "KickAPI",
    "KickHybridAPI",
    "fetch_chatroom_id",
    "check_stream_live",
    "get_channel_info",
    "create_clip",
    "get_clips",
    "HAS_OFFICIAL_API",
    # Official API
    "KickOfficialAPI",
    "OAuthTokens",
    "OAUTH_SCOPES",
    "WEBHOOK_EVENTS",
    "verify_webhook_signature",
    # Webhooks
    "WebhookEventHandler",
    "register_webhook_routes",
    "create_discord_notifier",
]
