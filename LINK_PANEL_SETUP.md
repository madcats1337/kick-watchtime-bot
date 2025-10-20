# Link Panel Setup Guide

## Overview
The Link Panel is a reaction-based system that allows users to link their Discord and Kick accounts via OAuth without cluttering your bot channel with commands. Users simply react to a pinned message to start the linking process.

## Features
✅ **Clean UX**: No command spam in your bot channel  
✅ **Automatic**: Users get a DM with their personal OAuth link  
✅ **Fallback**: `!link` command still works if reactions fail  
✅ **Auto-cleanup**: Reactions are automatically removed after sending the link  
✅ **Privacy**: OAuth links are sent via DM (falls back to channel if DMs disabled)  

## Setup Instructions

### 1. Create a Link Panel (Admin Only)

Use the `!setup_link_panel` command in the channel where you want the panel:

```
!setup_link_panel
```

Or specify a custom emoji:

```
!setup_link_panel 🎮
```

### 2. What Happens Next

The bot will:
1. ✅ Post an embed with instructions
2. ✅ Add the reaction emoji
3. ✅ Pin the message (if bot has permission)
4. ✅ Store the panel info in the database

### 3. User Experience

When a user reacts:
1. Bot checks if they're already linked
2. Bot sends them a DM with a personal OAuth link
3. User clicks the link and authorizes with Kick
4. Accounts are automatically linked
5. User gets a success notification
6. Original reaction is removed

## Command Reference

### Admin Commands

#### `!setup_link_panel [emoji]`
Creates a new link panel in the current channel.
- **Permission Required**: Administrator
- **Default Emoji**: 🔗
- **Example**: `!setup_link_panel 🎮`
- **Note**: Only one panel per channel (creating a new one replaces the old)

### User Commands (Fallbacks)

#### `!link`
Traditional command-based OAuth linking (still available as fallback)
- Works the same as clicking the reaction
- Useful if reactions aren't working

#### `!linkbio <username>`
Alternative bio-based verification method
- Doesn't require OAuth
- User adds a code to their Kick bio

#### `!unlink`
Unlink your Discord from your Kick account

## Troubleshooting

### Bot can't pin messages
**Error**: "I don't have permission to pin messages"  
**Solution**: Grant the bot "Manage Messages" permission in that channel

### User didn't receive DM
**Cause**: User has DMs from server members disabled  
**Solution**: Bot automatically sends the link in the channel instead (deletes after 60 seconds)

### Reaction not working
**Fallback**: User can type `!link` instead

### Multiple panels in same channel
**Behavior**: Creating a new panel automatically removes the old one from the database (only the newest panel works)

## Database Schema

The link panel system uses the `link_panels` table:

```sql
CREATE TABLE link_panels (
    id SERIAL PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    message_id BIGINT NOT NULL,
    emoji TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(guild_id, channel_id, message_id)
);
```

## Best Practices

1. **Pin the message**: Makes it easy for users to find
2. **Use a dedicated channel**: Keep it separate from general chat
3. **Clear instructions**: The default embed provides good instructions
4. **Monitor**: Check if users report issues with DMs
5. **Test**: React yourself to test the flow before announcing

## Security Features

- ✅ OAuth links are unique per user
- ✅ Links expire after 10 minutes
- ✅ Bot checks if user is already linked before sending link
- ✅ Reactions are removed after processing to prevent spam
- ✅ Messages auto-delete if sent in channel (60 second timeout)

## Technical Details

### Event Flow
```
User reacts → on_raw_reaction_add triggered
  ↓
Check if message is a link panel
  ↓
Check if user already linked
  ↓
Generate unique OAuth URL
  ↓
Send DM (or channel message if DMs disabled)
  ↓
Store message info in oauth_notifications table
  ↓
Remove reaction
  ↓
User completes OAuth flow on website
  ↓
Background task detects completion
  ↓
Delete original message
  ↓
Send success notification
```

### Advantages Over Command-Based Linking

| Feature | `!link` Command | Reaction Panel |
|---------|----------------|----------------|
| Channel clutter | ❌ High | ✅ None |
| Discoverability | ❌ Low | ✅ High (pinned) |
| User experience | ⚠️ Manual typing | ✅ One click |
| Visibility | ❌ Scrolls away | ✅ Pinned |
| Rate limiting | ⚠️ Per user | ✅ Shared cooldown |

## Example Embed

The default link panel looks like this:

```
🎮 Link Your Kick Account
React with 🔗 below to link your Discord account with your Kick account!

📝 How it works
1. Click the 🔗 reaction below
2. You'll receive a DM with your personal OAuth link
3. Click the link and authorize with Kick
4. Done! Your accounts are now linked

💡 Benefits
• Earn watchtime automatically
• Unlock exclusive roles
• Show your support for the stream

You can also use !link command as a fallback
```

## FAQ

**Q: Can I have multiple link panels?**  
A: Yes, but only one per channel. You can create panels in different channels.

**Q: What happens to old panels when I create a new one?**  
A: The old panel message stays, but only the new one will be active in the database.

**Q: Can users abuse this by spamming reactions?**  
A: No, reactions are automatically removed and users can only link once per account.

**Q: Does this replace the !link command?**  
A: No, the `!link` command is kept as a fallback option.

**Q: Can I customize the embed?**  
A: Currently no, but you can modify the code in `bot.py` around line 1572.
