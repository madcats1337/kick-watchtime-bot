# Kick OAuth Implementation Guide

## ✅ What Was Fixed

### 1. **Removed Duplicate Functions**
- Cleaned up `bot.py` which had two conflicting `send_kick_message()` functions
- Now has one clean implementation using official Kick API

### 2. **Implemented Official Chat API**
- **Endpoint**: `POST https://api.kick.com/public/v1/chat`
- **Documentation**: https://docs.kick.com/apis/chat
- **Authentication**: OAuth Bearer token (what you already have!)
- **Payload Format**:
  ```json
  {
    "content": "Your message here",
    "type": "bot"
  }
  ```
- **Key**: When `type="bot"`, the message goes to the channel attached to the OAuth token

### 3. **Fixed Database Schema**
- Updated `create_bot_tokens_table.py` to use OAuth schema:
  - `bot_username` (primary key)
  - `access_token` (OAuth access token)
  - `refresh_token` (OAuth refresh token)
  - `created_at` (timestamp)

## 🔧 What You Need To Do

### Step 1: Update Database Schema
Run this script to recreate the table with correct columns:
```powershell
python create_bot_tokens_table.py
```

**⚠️ WARNING**: This will DROP the existing `bot_tokens` table and create a new one!

### Step 2: Get Fresh OAuth Token
The **owner of the maikelele Kick account** needs to authorize the bot:

1. Go to: `https://kick-dicord-bot-test-production.up.railway.app/bot/authorize?token=YOUR_BOT_AUTH_TOKEN`
2. Log in with the maikelele account
3. Grant permissions (needs `chat:write` scope)
4. The OAuth flow will save `access_token` and `refresh_token` to the database

### Step 3: Deploy Updated Code
```powershell
git add .
git commit -m "Implement official Kick Chat API with OAuth"
git push
```

Railway will auto-deploy the updated code.

### Step 4: Test
Once deployed and authorized, test by running a timer command in Discord:
- `!timer list` - Should show available timers
- `!timer add <timer_id>` - Should enable timer and start sending messages to Kick

## 🎯 How It Works Now

1. **Bot starts** → Loads OAuth `access_token` from database (or `KICK_BOT_USER_TOKEN` env var)
2. **Timer triggers** → Calls `send_kick_message(message)`
3. **Function executes**:
   - Gets OAuth token from database or environment
   - Sends POST to `https://api.kick.com/public/v1/chat`
   - Uses `Authorization: Bearer {token}` header
   - Sends payload: `{"content": "message", "type": "bot"}`
4. **Success** → Returns True, message appears in maikelele's chat
5. **401 Error** → Token expired, user needs to re-authorize

## 📋 Key Changes in bot.py

### Before (OLD - BROKEN):
- Two duplicate `send_kick_message()` functions
- Tried multiple endpoints (v1, v2, session-based)
- Complex token refresh logic
- Mixed OAuth and session-based authentication

### After (NEW - CLEAN):
- One `send_kick_message()` function
- Uses official endpoint: `https://api.kick.com/public/v1/chat`
- Simple OAuth Bearer token authentication
- Clear error messages with re-authorization instructions

## 🚨 Important Notes

1. **No Automatic Token Refresh**:
   - OAuth tokens from Kick expire
   - When expired, user must re-authorize at the authorization URL
   - Bot will print clear instructions in logs

2. **Type = "bot" is Critical**:
   - Must include `"type": "bot"` in payload
   - This tells Kick to send the message to the channel attached to the token
   - Without this, the API might not know where to send the message

3. **Scopes Matter**:
   - OAuth token must have `chat:write` scope
   - Make sure this is included in your OAuth authorization URL

4. **Environment Variables**:
   - `KICK_BOT_USER_TOKEN` - Optional fallback if database is empty
   - `KICK_CLIENT_ID` - OAuth client ID
   - `KICK_CLIENT_SECRET` - OAuth client secret
   - All set in Railway environment

## 🧹 Optional Cleanup

You can delete these files (they were for session-based auth, no longer needed):
- `update_session_tokens.py`
- `test_kick_session.py`
- `KICK_SESSION_AUTH_GUIDE.md`

## 📚 References

- **Official Kick Docs**: https://docs.kick.com
- **Chat API**: https://docs.kick.com/apis/chat
- **OAuth Flow**: https://docs.kick.com/getting-started/generating-tokens-oauth2-flow
- **Scopes**: https://docs.kick.com/getting-started/scopes

## ✨ Why This Approach Works

- ✅ Uses official, documented API
- ✅ Simple OAuth Bearer token (what you already have)
- ✅ No need for manual browser token extraction
- ✅ Works with bot accounts
- ✅ Clear error handling
- ✅ No session cookies or XSRF tokens needed

The previous approach tried to use session-based authentication (like the kick-js library), which requires manual browser login to extract tokens. Since you don't own the maikelele account, that approach wouldn't work. This OAuth approach is the correct way for bot applications! 🎉
