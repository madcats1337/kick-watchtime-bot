# Kick Session-Based Authentication Guide

## Overview

The bot now uses **session-based authentication** (like the kick-js library) instead of OAuth tokens. This is more reliable and matches how Kick's API actually works.

## What Changed?

### Old System (OAuth)
- Used `access_token` and `refresh_token`
- Tokens expired frequently
- Required OAuth authorization flow
- Endpoint: `https://api.kick.com/public/v1/chat`

### New System (Session-Based)
- Uses `bearer_token`, `xsrf_token`, and `cookies`
- Session-based authentication
- More stable, lasts longer
- Endpoint: `https://kick.com/api/v2/messages/send/{chatroom_id}`

## How to Get Session Tokens

### Step 1: Log into Kick
1. Open your browser (Chrome, Firefox, etc.)
2. Go to https://kick.com
3. Log in as your bot account (maikelele)
4. Navigate to your channel or any channel

### Step 2: Open Developer Tools
1. Press **F12** (or right-click → Inspect)
2. Click on the **Network** tab
3. Make sure "Preserve log" is checked

### Step 3: Send a Test Message
1. Type a message in the chat
2. Press Enter to send it
3. In the Network tab, you'll see a new request appear

### Step 4: Find the Message Request
1. Look for a request to `/messages/send/` or with URL like:
   ```
   https://kick.com/api/v2/messages/send/12345
   ```
2. Click on this request
3. Go to the **Headers** tab

### Step 5: Copy the Required Headers

#### Authorization Header (Bearer Token)
- Find: `Authorization: Bearer eyJ...`
- Copy: Everything **after** "Bearer " (the long token)
- Example: `eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJ...` (very long string)

#### X-CSRF-Token Header (XSRF Token)
- Find: `X-CSRF-Token: abc123...`
- Copy: The full token value
- Example: `abc123def456ghi789...` (long string)

#### Cookie Header (Full Cookies)
- Find: `Cookie: XSRF-TOKEN=...`
- Copy: The **entire** cookie string
- Example: `XSRF-TOKEN=abc123; kick_session=xyz789; ...` (very long string with multiple cookies)

**⚠️ Important:** Copy the ENTIRE cookie header, not just one cookie!

## Updating the Database

### Option 1: Use the Helper Script (Recommended)

Run the update script:
```bash
python update_session_tokens.py
```

When prompted, paste each token value:
1. Bearer Token (without "Bearer " prefix)
2. XSRF Token
3. Full Cookie string

The script will:
- Validate the tokens
- Update the database
- Show confirmation

### Option 2: Manual Database Update

If you prefer to update manually:

```sql
-- Update existing bot_tokens table
INSERT INTO bot_tokens (bot_username, bearer_token, xsrf_token, cookies, created_at, last_used)
VALUES (
    'maikelele',
    'YOUR_BEARER_TOKEN_HERE',
    'YOUR_XSRF_TOKEN_HERE',
    'YOUR_FULL_COOKIE_STRING_HERE',
    CURRENT_TIMESTAMP,
    CURRENT_TIMESTAMP
)
ON CONFLICT (bot_username) 
DO UPDATE SET 
    bearer_token = EXCLUDED.bearer_token,
    xsrf_token = EXCLUDED.xsrf_token,
    cookies = EXCLUDED.cookies,
    last_used = CURRENT_TIMESTAMP;
```

## How the Bot Uses These Tokens

When sending a Kick message, the bot now:

1. **Loads session tokens** from the database (if not already loaded)
2. **Fetches chatroom ID** for the configured channel
3. **Sends message** to: `https://kick.com/api/v2/messages/send/{chatroom_id}`
4. **Uses these headers:**
   ```
   Authorization: Bearer {bearer_token}
   X-CSRF-Token: {xsrf_token}
   Cookie: {cookies}
   Content-Type: application/json
   Cluster: v2
   ```

## When Do Tokens Expire?

Session tokens expire when:
- You log out of Kick
- Kick invalidates the session (security reasons)
- The session times out from inactivity (exact timeout unknown)

**Pro tip:** The bot now runs a proactive session check every 6 hours to validate tokens are still working.

## Troubleshooting

### Error: "Session tokens not available"
**Solution:** Run `update_session_tokens.py` to add tokens to the database

### Error: "HTTP 401 Unauthorized"
**Cause:** Session expired or tokens are invalid
**Solution:** Get fresh tokens from browser and update database

### Error: "Could not find chatroom ID"
**Cause:** Channel name might be wrong or channel doesn't exist
**Solution:** Verify `KICK_CHANNEL` in your .env file

### Messages not sending?
1. Check bot is logged in: `python update_session_tokens.py`
2. Verify channel name is correct
3. Check Railway logs for errors
4. Make sure bot account follows the channel (if follower-only mode)

## Environment Variables

The bot still uses these variables:
- `KICK_CHANNEL` - The channel username to send messages to (e.g., "maikelele")

You **no longer need:**
- ~~`KICK_BOT_USER_TOKEN`~~ (replaced by database session tokens)
- ~~`KICK_CLIENT_ID`~~ (OAuth not used)
- ~~`KICK_CLIENT_SECRET`~~ (OAuth not used)

## Benefits of Session-Based Auth

✅ **More Reliable** - Matches Kick's actual API implementation  
✅ **Longer Sessions** - Tokens last longer than OAuth tokens  
✅ **Simpler** - No OAuth flow complications  
✅ **Proven** - Same method used by kick-js library  
✅ **Better Error Messages** - Clearer instructions when tokens expire  

## References

This implementation is based on:
- [kick-js library](https://github.com/retconned/kick-js) - TypeScript Kick API wrapper
- Kick's actual API endpoints used by their web interface
- Browser DevTools analysis of Kick.com requests
