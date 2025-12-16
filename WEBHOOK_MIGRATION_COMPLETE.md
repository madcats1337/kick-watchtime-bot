# Webhook Migration Complete ✅

## Summary
Successfully migrated from **Pusher WebSocket** (deprecated) to **Kick Official Events API with Webhooks**.

---

## What's Working Now

### ✅ Chat Message Tracking (via Webhooks)
- **Event**: `chat.message.sent` 
- **Flow**: Kick → Webhook → Flask → Redis → Bot
- **Features Enabled**:
  - Watchtime tracking (`active_viewers_by_guild` updated per message)
  - Points system (awards points based on watchtime)
  - Custom commands (`!call`, `!gtb`, `!raffle`, etc.)
  - Slot call tracking
  - Timed messages (checks active chatters)
  - Clip creation (`!clip`)

### ✅ Multiserver Support
- Each Discord server gets webhooks for their configured Kick channel
- Webhook subscription registered automatically during OAuth flow
- Events routed to correct server via `subscription_id` → `discord_server_id` mapping

### ✅ Security Model
- Subscription ID validation (must exist in database)
- Private webhook URL (only known to Kick)
- TLS encryption
- RSA-2048 signature verification **disabled** (Kick hasn't published public key yet)

---

## Architecture

```
[Kick Chat Message]
         ↓
[Kick Events API] - POST to webhook
         ↓
[Flask oauth_server.py] - Receives webhook, validates subscription_id
         ↓
[Redis pub/sub] - Channel: bot_events
         ↓
[Bot redis_subscriber.py] - Subscribes to bot_events
         ↓
[active_viewers_by_guild] - Updates tracking dictionaries
         ↓
[update_watchtime_task] - Runs every 60s, awards points
```

---

## Configuration

### Environment Variables
```bash
USE_KICK_WEBHOOKS=true           # Enable webhooks (default)
KICK_CLIENT_ID=<your_client_id>  # OAuth app credentials
KICK_CLIENT_SECRET=<secret>
REDIS_URL=<redis_connection>     # Required for webhook→bot communication
```

### Database Tables
- `kick_webhook_subscriptions` - Maps subscription_id to discord_server_id
- `kick_oauth_tokens` - Stores OAuth tokens per streamer
- `watchtime` - Tracks user watch minutes per server
- `points_watchtime_converted` - Tracks points awarded

---

## What's NOT Migrated Yet

### ⚠️ Subscription Events (No Webhook Support from Kick)
Kick's Events API currently only supports `chat.message.sent`. The following events are **not available as webhooks yet**:

- `channel.subscription` (regular subs)
- `channel.subscription.gift` (gifted subs)
- `channel.follow` (new followers)
- `stream.online` / `stream.offline` (stream status changes)

**Current Status**: These events are still handled by **Pusher WebSocket** (now disabled by default).

**Impact**:
- ❌ Gifted sub raffle tracking not working
- ❌ Subscription notifications not working
- ❌ Stream status detection not working

**Workarounds**:
1. **Enable Pusher temporarily** (set `USE_KICK_WEBHOOKS=false`) - NOT RECOMMENDED as Kick deprecated Pusher
2. **Wait for Kick to add webhook support** - Check Kick API updates at https://api.kick.com/swagger/v1/doc.json
3. **Poll Kick API** - Could implement periodic polling for stream status (not ideal)

---

## Migration Steps Completed

### 1. ✅ Created Webhook Handler System
- File: `core/kick_webhooks.py`
- Validates signatures (currently bypassed)
- Routes events to correct Discord server
- Publishes to Redis for bot consumption

### 2. ✅ OAuth Flow with Auto-Registration
- File: `core/kick_official_api.py`
- Automatically registers webhook when streamer connects
- Stores subscription in database
- Handles token refresh

### 3. ✅ Redis Event Bridge
- Flask publishes to `bot_events` channel
- Bot subscribes and processes events
- Maintains separation between Flask and bot processes

### 4. ✅ Bot Integration
- File: `redis_subscriber.py` → `handle_webhook_event()`
- Updates `active_viewers_by_guild[server_id][username]`
- Updates `last_chat_activity_by_guild[server_id]`
- Processes commands, GTB, slot calls, etc.

### 5. ✅ Database Schema
```sql
CREATE TABLE kick_webhook_subscriptions (
    subscription_id VARCHAR(255) UNIQUE NOT NULL,
    discord_server_id BIGINT NOT NULL,
    broadcaster_user_id VARCHAR(255) NOT NULL,
    event_type VARCHAR(100) NOT NULL,
    webhook_url TEXT NOT NULL,
    status VARCHAR(50) DEFAULT 'active',
    created_at TIMESTAMP DEFAULT NOW()
);
```

### 6. ✅ Disabled Pusher by Default
- Set `USE_KICK_WEBHOOKS=true` (default)
- Pusher connection skipped on startup
- Can re-enable for testing with environment variable

---

## Testing

### Verify Webhook System
1. Send chat message in Kick stream
2. Check logs for:
   ```
   [Webhook] 📥 Received event: chat.message.sent
   [Webhook] 🎯 Routing to server: 914986636629143562
   [Webhook] ✅ Forwarded chat message to bot via Redis
   [Redis] 💬 [channel] username: message
   [Redis] ✅ Updated active viewers for guild 914986636629143562
   ```
3. Wait 60 seconds for watchtime task
4. Check database: `SELECT username, minutes FROM watchtime WHERE discord_server_id = <server_id>`

### Verify Multiserver
- Each Discord server should only receive events for their configured streamer
- Check `subscription_id` in webhook headers matches database entry

---

## Future Enhancements

### When Kick Adds More Webhook Events:

1. **Subscription Webhooks** (`channel.subscription.gift`)
   - Add handler in `oauth_server.py`:
     ```python
     @webhook_handler.on("channel.subscription.gift")
     async def handle_gifted_subs(event_data):
         # Publish to Redis for raffle system
     ```
   - Update raffle system to process from webhooks instead of Pusher

2. **Stream Status Webhooks** (`stream.online`, `stream.offline`)
   - Replace Pusher-based live detection
   - More reliable than chat-activity-based detection

3. **Follow Webhooks** (`channel.follow`)
   - Track new followers
   - Announce in Discord

### Performance Optimizations:
- [ ] Add Redis connection pooling
- [ ] Batch database writes for watchtime
- [ ] Cache subscription lookups (currently queries DB per webhook)
- [ ] Add webhook delivery retries (currently relies on Kick's retry logic)

---

## Rollback Plan

If webhooks fail, temporarily re-enable Pusher:

```bash
# In Railway/production environment
USE_KICK_WEBHOOKS=false

# Or comment out the check in bot.py line 4648
```

**Note**: Pusher is deprecated by Kick and may stop working at any time.

---

## Success Metrics

- ✅ Webhooks receiving events: **YES** (logs confirm)
- ✅ Active viewers tracking: **YES** (Redis updates confirmed)
- ✅ Watchtime awards: **YES** (with force override enabled)
- ✅ Points system: **YES** (depends on watchtime)
- ✅ Commands working: **YES** (`!call`, `!gtb`, etc.)
- ❌ Subscription tracking: **NO** (waiting for Kick webhook support)
- ❌ Stream status: **NO** (using chat activity heuristic)

---

## Support

If webhooks stop working:
1. Check Railway logs for webhook errors
2. Verify `kick_webhook_subscriptions` table has entries
3. Confirm `REDIS_URL` is set and Redis is running
4. Test webhook manually: `POST https://bot.lelebot.xyz/webhooks/kick`
5. Check Kick API status: https://api.kick.com/swagger/v1/doc.json

---

**Migration Date**: December 16, 2025  
**Status**: ✅ Complete for chat events  
**Next Steps**: Wait for Kick to add subscription/status webhooks
