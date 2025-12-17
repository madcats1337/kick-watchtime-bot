# Kick Chat Integration Guide

## Overview
The bot now properly reads and writes to Kick chat using the correct chatroom_id and broadcaster_user_id.

## Setup Requirements

### 1. Dashboard Configuration
Go to **Dashboard → Profile Settings**:

1. **Enter Kick Channel Username**
   - Save the channel name (e.g., "yourkickchannel")

2. **Link Kick Account (OAuth)**
   - Click "Link Kick Account" button
   - Complete OAuth flow (must be the streamer)
   - This provides the OAuth token needed for API access

3. **Sync Channel Info**
   - Click "Sync from Kick" button
   - This fetches and stores:
     - `kick_broadcaster_user_id` (from Official API)
     - `kick_chatroom_id` (from kickpython)

### 2. Environment Variables
```bash
# Required for both methods
KICK_CLIENT_ID=your_client_id
KICK_CLIENT_SECRET=your_client_secret
OAUTH_BASE_URL=https://your-bot.railway.app

# Optional: Bot account token (for kickpython WebSocket method)
KICK_BOT_USER_TOKEN=your_bot_oauth_token

# Feature flag (default: false)
KICK_USE_KICKPYTHON_WS=false  # Set to true to use WebSocket listener
```

## How Chat Works

### Reading Chat Messages (Incoming)

**Primary Method: Webhooks** (Recommended)
- Kick sends `chat.message.sent` events to your webhook endpoint
- Registered via OAuth in dashboard
- Handles all chat messages in real-time
- Already implemented in `core/kick_webhooks.py`

**Alternative: kickpython WebSocket** (Optional)
- Set `KICK_USE_KICKPYTHON_WS=true` to enable
- Connects to Kick chat via WebSocket
- Uses `kick_chatroom_id` from bot_settings
- Receives messages via `add_message_handler()`
- Updates `recent_chatters_by_guild` for watchtime tracking

### Writing Chat Messages (Outgoing)

The bot automatically chooses the best method:

**Method 1: Official Kick API** (Default)
- Uses `broadcaster_user_id` from bot_settings
- Requires OAuth token from linked account
- Sends via `POST /public/v1/chat`
- Works without WebSocket connection
- ✅ **Recommended for production**

**Method 2: kickpython WebSocket** (Optional)
- Only if `KICK_USE_KICKPYTHON_WS=true` and connected
- Uses `kick_chatroom_id` from bot_settings
- Sends via `api.post_chat(channel_id=chatroom_id)`
- Requires persistent WebSocket connection

### Automatic Fallback
```python
async def send_kick_message(message: str, guild_id: int) -> bool:
    # Try kickpython WS if enabled and connected
    if KICK_USE_KICKPYTHON_WS and guild_id in kick_ws_manager.connections:
        return await kick_ws_manager.send_message(...)
    
    # Fall back to Official API
    return await send_via_official_api(...)
```

## What Gets Stored in Database

After clicking "Sync from Kick", these are stored in `bot_settings`:

```sql
-- From Official Kick API
key = 'kick_broadcaster_user_id'
value = '123456'  -- Used for Official API chat sends

-- From kickpython (via core.kick_api.fetch_chatroom_id)
key = 'kick_chatroom_id'  
value = '789012'  -- Used for WebSocket sends (if enabled)

-- The configured channel
key = 'kick_channel'
value = 'yourkickchannel'
```

## Usage Examples

### Send a Chat Message
```python
# From any bot command or feature
await send_kick_message("Hello from bot!", guild_id=ctx.guild.id)
```

The function automatically:
1. Checks if kickpython WS is available (if enabled)
2. Falls back to Official API with broadcaster_user_id
3. Fetches OAuth token from database
4. Sends the message
5. Returns True/False for success

### Receive Chat Messages

**Via Webhooks** (Already working):
```python
# In core/kick_webhooks.py - already implemented
@webhook_handler.on("chat.message.sent")
async def handle_chat(event_data):
    username = event_data['sender']['username']
    content = event_data['content']
    guild_id = event_data['_server_id']  # Multiserver routing
    
    # Your chat processing logic here
    # Updates watchtime, processes commands, etc.
```

**Via kickpython WS** (Optional, if KICK_USE_KICKPYTHON_WS=true):
```python
# In bot.py KickWebSocketManager._handle_incoming_message()
async def _handle_incoming_message(self, guild_id, guild_name, msg):
    username = msg.get('sender_username')
    content = msg.get('content')
    
    # Updates recent_chatters_by_guild
    # Publishes to Redis
    # Processes commands if needed
```

## Troubleshooting

### Messages Not Sending
1. **Check broadcaster_user_id is set**
   - Dashboard → Profile Settings → "Sync from Kick"
   - Should show Broadcaster ID value

2. **Verify OAuth token exists**
   - Someone must link their Kick account in dashboard
   - Must be the streamer (not just any mod)

3. **Check logs for errors**
   ```
   [GuildName] ⚠️ broadcaster_user_id not configured
   [GuildName] ⚠️ No OAuth token available
   ```

### Messages Not Received
1. **Webhooks method** (Default)
   - Verify webhook subscription exists
   - Check `/webhooks/kick` endpoint is accessible
   - View webhook logs in dashboard

2. **kickpython WS method** (Optional)
   - Only if `KICK_USE_KICKPYTHON_WS=true`
   - Check chatroom_id is set
   - Verify `KICK_BOT_USER_TOKEN` is valid
   - Look for connection logs on startup

### Sync Button Fails
- **"No OAuth token found"**: Link Kick account first
- **"Could not find channel"**: Verify channel name is correct
- **chatroom_id not resolved**: Check kickpython is installed and KICK_BOT_USER_TOKEN is set (helps reliability)

## Migration Notes

### From Old Pusher System
- Pusher is deprecated by Kick
- Webhooks replace Pusher for chat events
- chatroom_id is now fetched via kickpython (more reliable than HTTP API)
- No code changes needed - bot auto-detects and uses correct method

### Multiserver Support
- Each Discord server has its own:
  - `kick_channel` (channel username)
  - `kick_broadcaster_user_id` (for API)
  - `kick_chatroom_id` (for WebSocket if enabled)
- All settings isolated by `discord_server_id`
- Webhook events routed to correct server via subscription lookup

## Best Practices

1. **Use Official API method (default)**
   - More reliable for production
   - No persistent connection required
   - Easier to debug

2. **Enable kickpython WS only if needed**
   - Useful for high-frequency chat monitoring
   - Adds complexity (connection management)
   - Webhooks + Official API cover 99% of use cases

3. **Always click Sync after changing channel**
   - Updates both broadcaster_user_id and chatroom_id
   - Ensures IDs are fresh and accurate

4. **Monitor logs**
   - Watch for connection issues
   - Check for authentication errors
   - Verify messages are sent/received

## Status Check

Run this to verify everything is configured:

```python
# In bot console or command
!check_kick_config

# Should show:
# ✅ kick_channel: yourkickchannel
# ✅ kick_broadcaster_user_id: 123456
# ✅ kick_chatroom_id: 789012
# ✅ OAuth token: exists
# ✅ Webhooks: registered
# ✅ Chat: ready to send/receive
```

---

**Summary**: The bot now properly reads chat via webhooks, writes chat via Official API, and uses kickpython only for reliable chatroom_id resolution. Everything "just works" after clicking Sync in the dashboard!
