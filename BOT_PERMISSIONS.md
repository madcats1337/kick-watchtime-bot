# Required Bot Permissions

## Critical Permissions for Link Panel

For the reaction-based link panel to work properly, the bot needs these permissions:

### Required:
- ✅ **Read Messages/View Channels** - See the link panel message
- ✅ **Send Messages** - Send DM or channel messages
- ✅ **Embed Links** - Send embeds with OAuth links
- ✅ **Add Reactions** - Add the initial reaction to the panel
- ✅ **Read Message History** - Fetch the panel message
- ✅ **Manage Messages** - **CRITICAL:** Remove users' reactions

### For Pinning:
- ✅ **Manage Messages** - Pin the link panel message (optional, can pin manually)

## Permission Issues

### Symptom: Reactions Not Being Removed
**Cause**: Bot is missing "Manage Messages" permission

**Fix**:
1. Go to Server Settings → Roles
2. Find your bot's role
3. Enable "Manage Messages" permission
4. OR: Right-click the channel → Edit Channel → Permissions → Bot Role → Enable "Manage Messages"

### Symptom: Cannot Pin Message
**Cause**: Bot is missing "Manage Messages" permission

**Fix**: Same as above - enable "Manage Messages"

## How to Check Permissions

Run this in your bot channel:
```
User reacts to panel → Check bot logs for errors
```

You should see:
```
✅ Removed reaction from Username on link panel
```

If you see:
```
⚠️ Missing permissions to remove reaction for Username
```

Then the bot needs "Manage Messages" permission!

## Recommended Bot Role Setup

Create a role for your bot with these permissions:

**General Permissions:**
- [x] View Channels
- [x] Manage Roles (for watchtime roles)
- [x] Manage Messages (for reactions and pinning)

**Text Permissions:**
- [x] Send Messages
- [x] Embed Links
- [x] Attach Files
- [x] Read Message History
- [x] Add Reactions

**Important:** The bot's role must be **higher** than the watchtime roles in the role hierarchy!
