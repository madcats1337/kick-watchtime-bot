"""
Core modules for Kick Discord Bot

Modules:
- kick_api: Hybrid API client (official + unofficial fallback)
- kick_official_api: Official Kick API client with OAuth 2.1
- kick_webhooks: Webhook event handlers for Kick events
- oauth_server: Flask OAuth server for user linking and bot authorization
"""

from .kick_api import (
    KickAPI,
    KickHybridAPI,
    fetch_chatroom_id,
    check_stream_live,
    get_channel_info,
    create_clip,
    get_clips,
    HAS_OFFICIAL_API,
)

from .kick_official_api import (
    KickOfficialAPI,
    OAuthTokens,
    OAUTH_SCOPES,
    WEBHOOK_EVENTS,
    verify_webhook_signature,
)

from .kick_webhooks import (
    WebhookEventHandler,
    register_webhook_routes,
    create_discord_notifier,
)

__all__ = [
    # Hybrid API
    'KickAPI',
    'KickHybridAPI',
    'fetch_chatroom_id',
    'check_stream_live',
    'get_channel_info',
    'create_clip',
    'get_clips',
    'HAS_OFFICIAL_API',
    # Official API
    'KickOfficialAPI',
    'OAuthTokens',
    'OAUTH_SCOPES',
    'WEBHOOK_EVENTS',
    'verify_webhook_signature',
    # Webhooks
    'WebhookEventHandler',
    'register_webhook_routes',
    'create_discord_notifier',
]
