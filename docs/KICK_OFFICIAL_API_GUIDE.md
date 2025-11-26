# Kick Official API Integration Guide

This document explains how to use the official Kick API integration in the bot.

## Overview

As of November 2025, Kick has released their official API with proper OAuth 2.1 authentication, webhooks, and REST endpoints. This replaces the need for unofficial WebSocket connections and browser automation.

**Official Documentation:** https://docs.kick.com  
**API Server:** https://api.kick.com  
**OAuth Server:** https://id.kick.com  
**OpenAPI Spec:** https://api.kick.com/swagger/v1/doc.yaml

## Available Features

### OAuth Scopes

| Scope | Description |
|-------|-------------|
| `user:read` | Read user profile information |
| `channel:read` | Read channel information |
| `channel:write` | Modify channel settings (title, category) |
| `chat:write` | Send chat messages as a bot |
| `streamkey:read` | Read stream key |
| `events:subscribe` | Subscribe to webhooks |
| `moderation:ban` | Ban/unban users from chat |
| `kicks:read` | Read Tips (Kicks) leaderboard |

### Webhook Events

| Event | Description |
|-------|-------------|
| `chat.message.sent` | New chat message |
| `channel.followed` | New follower |
| `channel.subscription.new` | New subscription |
| `channel.subscription.renewal` | Subscription renewal |
| `channel.subscription.gifts` | Gifted subscriptions |
| `livestream.status.updated` | Stream went live/offline |
| `moderation.banned` | User banned from chat |
| `kicks.gifted` | Tips (Kicks) received |

## Module Structure

```
core/
├── kick_official_api.py   # Official API client with OAuth
├── kick_api.py            # Hybrid API (official + unofficial fallback)
├── kick_webhooks.py       # Webhook route handlers
└── oauth_server.py        # Flask OAuth server with webhook endpoints
```

## Usage Examples

### 1. Basic API Client

```python
from core.kick_official_api import KickOfficialAPI

# Initialize with OAuth token
api = KickOfficialAPI(
    client_id="your_client_id",
    client_secret="your_client_secret",
    access_token="user_access_token",
    refresh_token="user_refresh_token",
)

# Send a chat message
await api.send_chat_message("Hello from the bot!", broadcaster_user_id=12345)

# Get channel info
channels = await api.get_channels(broadcaster_user_ids=[12345])

# Subscribe to webhooks
await api.subscribe_webhook(
    event="channel.subscription.gifts",
    callback_url="https://your-server.com/webhooks/kick"
)

# Don't forget to close
await api.close()
```

### 2. Hybrid API (Recommended)

The hybrid API automatically uses official endpoints when authenticated, with fallback to unofficial API for public data:

```python
from core.kick_api import KickHybridAPI

api = KickHybridAPI(access_token="your_token")
await api.setup()

# Official API - requires auth
await api.send_message("Hello!", broadcaster_user_id=12345)
await api.ban_user(broadcaster_user_id=12345, user_id=67890, duration_minutes=10)

# Unofficial API - works without auth
channel_info = await api.get_channel_info("channelname")
is_live = await api.check_stream_live("channelname")

await api.close()
```

### 3. Webhook Handling

```python
from core.kick_webhooks import WebhookEventHandler, register_webhook_routes

# Create event handler
handler = WebhookEventHandler()

@handler.on("channel.subscription.gifts")
async def on_gifted_subs(data):
    gifter = data['gifter']['username']
    count = len(data['giftees'])
    print(f"{gifter} gifted {count} subs!")

@handler.on("kicks.gifted")
async def on_kicks(data):
    sender = data['sender']['username']
    amount = data['amount']
    print(f"{sender} sent ${amount} in Kicks!")

# Register with Flask app
register_webhook_routes(app, handler)
```

### 4. Discord Integration

```python
from core.kick_webhooks import create_discord_notifier

# Create handler that sends notifications to Discord
handler = create_discord_notifier(
    discord_bot=bot,
    channel_id=123456789  # Discord channel for notifications
)

register_webhook_routes(app, handler)
```

## Environment Variables

Add these to your Railway/environment:

```env
# Required for OAuth
KICK_CLIENT_ID=your_client_id
KICK_CLIENT_SECRET=your_client_secret
OAUTH_BASE_URL=https://your-app.up.railway.app

# Required for webhooks
KICK_WEBHOOK_SECRET=your_webhook_secret

# Optional - for bot chat messages
KICK_BOT_USER_TOKEN=access_token_from_oauth
```

## API Endpoints

The OAuth server exposes these endpoints:

### Status & Health
- `GET /health` - Health check
- `GET /api/status` - Detailed API status with available features

### OAuth
- `GET /auth/kick?discord_id=...` - Start OAuth flow for user linking
- `GET /auth/kick/callback` - OAuth callback handler
- `GET /bot/authorize?token=...` - Authorize bot for chat:write scope

### Webhooks
- `POST /webhooks/kick` - Receive Kick webhook events
- `GET /webhooks/kick/challenge` - Handle webhook verification
- `GET /api/webhooks` - List webhook subscriptions (requires auth)
- `POST /api/webhooks` - Create webhook subscription (requires auth)
- `DELETE /api/webhooks/<id>` - Delete webhook subscription (requires auth)

## Setting Up Webhooks

1. **Authorize the bot** with `events:subscribe` scope:
   ```
   https://your-app.up.railway.app/bot/authorize?token=YOUR_BOT_AUTH_TOKEN
   ```

2. **Create webhook subscription** via API:
   ```bash
   curl -X POST https://your-app.up.railway.app/api/webhooks \
     -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
       "event": "channel.subscription.gifts",
       "callback_url": "https://your-app.up.railway.app/webhooks/kick"
     }'
   ```

3. **List subscriptions**:
   ```bash
   curl https://your-app.up.railway.app/api/webhooks \
     -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
   ```

## Webhook Signature Verification

Kick signs webhooks with HMAC SHA256. The signature is in the `Kick-Event-Signature` header.

Verify like this:
```python
from core.kick_official_api import verify_webhook_signature

is_valid = verify_webhook_signature(
    signature=request.headers.get("Kick-Event-Signature"),
    message_id=request.headers.get("Kick-Event-Message-Id"),
    timestamp=request.headers.get("Kick-Event-Message-Timestamp"),
    body=request.get_data(),
    secret=os.getenv("KICK_WEBHOOK_SECRET")
)
```

## Migration from Unofficial API

The bot still uses WebSocket connections for real-time chat listening (as webhooks may have latency). However, the following features now use the official API:

| Feature | Before | After |
|---------|--------|-------|
| Send chat messages | ❌ Not possible | ✅ `chat:write` scope |
| Get channel info | Unofficial API | Hybrid (official when auth'd) |
| Stream status | Unofficial API | Webhooks + unofficial fallback |
| Gifted subs tracking | Manual parsing | ✅ `channel.subscription.gifts` webhook |
| Tips (Kicks) tracking | Not available | ✅ `kicks.gifted` webhook |
| Ban/unban users | Not available | ✅ `moderation:ban` scope |

## Rate Limits

The official Kick API has rate limits. Check the response headers:
- `X-RateLimit-Limit` - Max requests per window
- `X-RateLimit-Remaining` - Requests remaining
- `X-RateLimit-Reset` - Unix timestamp when limit resets

## Troubleshooting

### "No OAuth token available"
- Ensure the bot account has been authorized at `/bot/authorize`
- Check that `KICK_BOT_USER_TOKEN` is set or token is in database

### "Official Kick API not available"
- The `kick_official_api` module failed to import
- Check for missing dependencies in `requirements.txt`

### Webhooks not received
- Verify your callback URL is HTTPS and publicly accessible
- Check `KICK_WEBHOOK_SECRET` matches what Kick has on file
- Ensure firewall/Railway allows incoming POST requests

### Token expired
- Refresh tokens are now reusable (as of Nov 25, 2025)
- The API client automatically refreshes on 401 errors
- If refresh fails, re-authorize at `/bot/authorize`

## Changelog

### November 2025
- Initial official API integration
- Added OAuth 2.1 with PKCE support
- Added webhook subscription management
- Added moderation endpoints (ban/unban)
- Added Kicks (tips) leaderboard API
- Added hybrid API client for backward compatibility
