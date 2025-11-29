# Bot-Testing Environment Variable Setup

## 🎯 Overview

For multi-server testing, we need to configure Railway bot-testing environment with the correct values. Some variables should be **removed** or **changed** from production values.

## ⚠️ Critical Changes Needed

### Variables to REMOVE from bot-testing

These variables lock the bot to a single server and must be removed for multi-server testing:

```
DISCORD_GUILD_ID  ❌ REMOVE THIS
```

**Why?** The bot code checks `if DISCORD_GUILD_ID:` and restricts certain features to that single guild. For multi-server testing, we want the bot to work with all guilds it's invited to.

### Variables to KEEP (Same as Production)

These can stay the same since they're shared resources:

```
✅ DATABASE_URL (already points to bot-testing postgres)
✅ REDIS_URL (already points to bot-testing redis)
✅ KICK_BOT_USER_TOKEN (shared - bot watches same Kick channel)
✅ KICK_CLIENT_ID (OAuth app ID)
✅ KICK_CLIENT_SECRET (OAuth secret)
✅ KICK_WEBHOOK_SECRET (Webhook validation)
✅ BOT_AUTH_TOKEN (Dashboard auth)
✅ FLASK_SECRET_KEY (Session encryption)
```

### Variables to CREATE (New for Testing)

#### 1. DISCORD_TOKEN
**Current value**: Uses production bot token
**Should be**: **DIFFERENT TEST BOT TOKEN**

You need to create a separate test bot:
1. Go to Discord Developer Portal
2. Create a new application: "LeleBot Testing"
3. Go to Bot section
4. Generate new token
5. Use this token in bot-testing

**Why?** You can't run the same bot token in two places (production + testing). Discord will disconnect one.

#### 2. KICK_CHANNEL (Optional)
**Current**: Not set (loaded from database)
**Recommendation**: Keep not set, configure per-server in database

#### 3. SLOT_CALLS_CHANNEL_ID (Optional)
**Current**: `1432817725620617357` (production channel)
**Recommendation**: Set to a channel ID in one of your test servers, or remove it

#### 4. OAUTH_BASE_URL
**Current**: `lelebot.xyz` (production domain)
**Should be**: Use Railway's public domain or keep as is

## 📝 Step-by-Step Railway Configuration

### Step 1: Create a Test Discord Bot

1. Go to https://discord.com/developers/applications
2. Click "New Application"
3. Name it: **LeleBot Testing** (or similar)
4. Click "Create"
5. Go to **Bot** section in left sidebar
6. Click "Reset Token" (or "Add Bot" if new)
7. Copy the token (you'll only see it once!)
8. Under **Privileged Gateway Intents**, enable:
   - ✅ PRESENCE INTENT
   - ✅ SERVER MEMBERS INTENT
   - ✅ MESSAGE CONTENT INTENT
9. Click "Save Changes"

### Step 2: Get OAuth2 URL for Test Bot

1. Still in Discord Developer Portal
2. Go to **OAuth2** → **URL Generator**
3. Select scopes:
   - ✅ `bot`
   - ✅ `applications.commands`
4. Select permissions (at minimum):
   - ✅ Read Messages/View Channels
   - ✅ Send Messages
   - ✅ Manage Messages
   - ✅ Embed Links
   - ✅ Read Message History
   - ✅ Add Reactions
   - ✅ Manage Roles (if using role features)
   - Or just: ✅ **Administrator** (for testing simplicity)
5. Copy the generated URL (save it for later)

### Step 3: Update Railway Bot-Testing Variables

Go to Railway dashboard → Discord bot → Bot-testing → LeleBot → Variables

**Remove these variables:**
```bash
DISCORD_GUILD_ID  # Delete this completely
```

**Update these variables:**
```bash
DISCORD_TOKEN=YOUR_NEW_TEST_BOT_TOKEN_HERE
```

**Optional: Update these if you want separate test channels:**
```bash
SLOT_CALLS_CHANNEL_ID=YOUR_TEST_CHANNEL_ID_HERE  # or delete
```

**Keep everything else the same**

### Step 4: Configure Railway to Deploy Feature Branch

1. In Railway dashboard, go to LeleBot service
2. Click **Settings** tab
3. Scroll to **Source** section
4. Click "Configure" or "Change"
5. Set branch to: `feature/multi-server-migration`
6. Click "Save"
7. Deployment will start automatically

### Step 5: Invite Test Bot to Your 3 Test Servers

Using the OAuth2 URL from Step 2:

1. Open the URL in your browser
2. Select: **Server 1** (ID: 1444335288599187459)
3. Click "Authorize"
4. Repeat with **Server 2** (ID: 1444335540945031221)
5. Repeat with **Server 3** (ID: 1444335793622614149)

### Step 6: Verify Bot is Online

Check in Discord:
- ✅ Test bot appears as online (green circle) in all 3 servers
- ✅ Check Railway logs: `railway logs` - should see "Bot is ready!"

## 🔧 Code Changes Needed (Optional)

There's one issue in bot.py line 4082 where gifted_sub_tracker is initialized:

```python
gifted_sub_tracker = setup_gifted_sub_handler(engine, DISCORD_GUILD_ID)
```

This should actually create a tracker **per event** when a gifted sub happens, not at startup. Since `DISCORD_GUILD_ID` will be `None` in testing, this will cause issues.

**Fix needed in bot.py:**

Option 1: Remove this line entirely (create tracker on-demand per event)
Option 2: Don't initialize it if DISCORD_GUILD_ID is None
Option 3: Skip it for now and test raffle commands first

## 📊 Environment Comparison

### Production (main branch)
```
DISCORD_GUILD_ID=914986636629143562  # Single production server
DISCORD_TOKEN=<production bot token>
DATABASE_URL=<production postgres>
REDIS_URL=<production redis>
```

### Bot-Testing (feature branch)
```
DISCORD_GUILD_ID=<NOT SET - multi-server mode>  ← KEY DIFFERENCE
DISCORD_TOKEN=<test bot token - different from production>
DATABASE_URL=<bot-testing postgres - separate from production>
REDIS_URL=<bot-testing redis - separate from production>
```

## ✅ Verification Checklist

After configuration:

- [ ] Created new test bot in Discord Developer Portal
- [ ] Copied new test bot token
- [ ] Removed `DISCORD_GUILD_ID` from Railway bot-testing
- [ ] Updated `DISCORD_TOKEN` in Railway bot-testing to use test bot token
- [ ] Set Railway source branch to `feature/multi-server-migration`
- [ ] Deployment succeeded (check Railway logs)
- [ ] Invited test bot to all 3 test servers using OAuth2 URL
- [ ] Test bot shows as online in all 3 servers
- [ ] No errors in Railway logs

## 🐛 Known Issues to Fix

### Issue 1: gifted_sub_tracker initialization (bot.py line 4082)

**Problem**: Code tries to create gifted_sub_tracker with `DISCORD_GUILD_ID` at startup
**Impact**: Will fail or be None if DISCORD_GUILD_ID not set
**Solution**: We need to fix this before testing

### Issue 2: in_guild() decorator

**Problem**: Commands with `@in_guild()` decorator check `DISCORD_GUILD_ID`
**Impact**: In multi-server mode, this check will always pass (returns True if DISCORD_GUILD_ID is None)
**Solution**: This is actually fine for testing - commands will work in all servers

### Issue 3: Role update tasks

**Problem**: Some tasks check `if DISCORD_GUILD_ID:` before running
**Impact**: These features will be disabled in multi-server mode
**Solution**: Acceptable for Phase 2 testing - these need to be refactored later

## 🚀 Next Steps

1. Create test bot and get token
2. Update Railway variables as documented above
3. Deploy feature branch
4. Fix gifted_sub_tracker initialization issue
5. Invite bot to test servers
6. Begin testing per TESTING_GUIDE.md

