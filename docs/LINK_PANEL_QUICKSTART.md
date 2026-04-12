# Quick Start: Link Panel

## Setup (Admin)

1. Go to the channel where you want users to link their accounts
2. Run the command:
   ```
   !setup_link_panel
   ```
   Or with a custom emoji:
   ```
   !setup_link_panel 🎮
   ```

3. The bot will:
   - Create a nice embed with instructions
   - Add the reaction emoji
   - Pin the message

4. Done! Users can now react to link their accounts.

## What Users See

When they react to the pinned message:
1. ✅ Get a DM with their personal OAuth link
2. ✅ Click the link → log in to Kick → authorize
3. ✅ Accounts linked automatically
4. ✅ Success notification sent

## Benefits

### Before (using `!link` command):
```
User1: !link
User2: !link
User3: !link
User4: !link
... spam continues ...
```
❌ Channel gets messy
❌ Commands scroll away
❌ Users might miss instructions

### After (using reaction panel):
```
[Pinned Message]
🎮 Link Your Kick Account
React with 🔗 below...

[No visible reactions in channel]
```
✅ Clean channel
✅ Always visible (pinned)
✅ One-click process

## Fallback Option

The `!link` command still works if:
- Reactions fail
- User can't see pinned messages
- User prefers typing commands

## Testing

Test these scenarios:
1. ✅ React with correct emoji → should get DM
2. ✅ React when already linked → should get "already linked" message
3. ✅ DMs disabled → should get message in channel (auto-deletes)
4. ✅ After OAuth success → original message should be deleted

## Bot Permissions Needed

Make sure your bot has:
- ✅ Manage Messages (to pin)
- ✅ Add Reactions
- ✅ Read Message History
- ✅ Send Messages
- ✅ Embed Links

## Commands Overview

### Admin
- `!setup_link_panel [emoji]` - Create the link panel

### Users
- React to pinned message - Start OAuth linking (NEW!)
- `!link` - Fallback command-based linking
- `!linkbio <username>` - Alternative bio verification
- `!unlink` - Unlink account

## Need Help?

See the full guides:
- **LINK_PANEL_SETUP.md** - Complete setup guide
- **LINK_PANEL_IMPLEMENTATION.md** - Technical details
