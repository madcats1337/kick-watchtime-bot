# Link Panel Feature - Implementation Summary

## What Was Added

### 1. Database Table: `link_panels`
Stores information about reaction-based link panels:
- `guild_id`: Discord server ID
- `channel_id`: Channel where panel is posted
- `message_id`: The pinned message ID
- `emoji`: The reaction emoji to use
- `created_at`: Timestamp

### 2. New Command: `!setup_link_panel`
**Usage**: `!setup_link_panel [emoji]`
- **Permission**: Administrator only
- **Default emoji**: 🔗
- **Function**: Creates a pinned message with instructions and adds a reaction
- **Behavior**: Replaces any existing panel in the same channel

### 3. Event Handler: `on_raw_reaction_add`
Detects when users react to link panel messages:
- Validates the reaction is on a registered link panel
- Checks if user is already linked
- Generates unique OAuth URL per user
- Sends DM with OAuth link (falls back to channel if DMs disabled)
- Automatically removes the reaction after processing
- Stores message info for later cleanup via background task

### 4. Intent Addition
Added `intents.reactions = True` to enable reaction event handling

## Code Changes

### Modified Files
1. **bot.py**
   - Added `link_panels` table creation (line ~490)
   - Added `intents.reactions = True` (line ~508)
   - Added `!setup_link_panel` command (line ~1552)
   - Added `on_raw_reaction_add` event handler (line ~1685)

### New Files
1. **LINK_PANEL_SETUP.md** - Complete setup guide and documentation

## How It Works

### Admin Setup Flow
```
Admin: !setup_link_panel 🔗
  ↓
Bot creates embed with instructions
  ↓
Bot adds 🔗 reaction
  ↓
Bot pins message (if permission available)
  ↓
Bot stores panel info in database
```

### User Linking Flow
```
User reacts with 🔗
  ↓
Bot checks: Is this a registered panel? ✓
  ↓
Bot checks: Is user already linked? ✗
  ↓
Bot generates OAuth URL with discord_id
  ↓
Bot sends DM with OAuth link button
  ↓
Bot stores DM message ID in oauth_notifications
  ↓
Bot removes user's reaction
  ↓
User clicks link → OAuth flow → Accounts linked
  ↓
Background task detects completion
  ↓
Bot deletes original DM
  ↓
Bot sends success notification
```

## Key Features

### 1. No Channel Spam
- Users don't type commands
- Reactions are auto-removed
- DMs are used for OAuth links

### 2. Privacy & Security
- OAuth links sent via DM (not public)
- Links expire in 10 minutes
- Each user gets unique link
- Already-linked users are notified

### 3. Fallback Support
- `!link` command still works
- Channel fallback if DMs disabled
- Clear error messages

### 4. Auto-Cleanup
- Reactions removed after processing
- Channel messages auto-delete (60s)
- Original OAuth message deleted on success

## Database Migrations

The bot automatically creates the new table on startup:
```sql
CREATE TABLE IF NOT EXISTS link_panels (
    id SERIAL PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    message_id BIGINT NOT NULL,
    emoji TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(guild_id, channel_id, message_id)
);
```

No manual migration required - existing databases will work fine.

## Testing Checklist

Before deploying:
- [ ] Bot has "Manage Messages" permission (for pinning)
- [ ] Bot has "Add Reactions" permission
- [ ] Bot has "Read Message History" permission
- [ ] OAuth is configured (OAUTH_BASE_URL, KICK_CLIENT_ID set)
- [ ] Test with DMs enabled
- [ ] Test with DMs disabled (channel fallback)
- [ ] Test when already linked (should show error)
- [ ] Verify reaction removal works
- [ ] Verify message cleanup after OAuth success

## Deployment Notes

### Environment Variables Required
- `OAUTH_BASE_URL`: Your Railway app URL
- `KICK_CLIENT_ID`: Kick OAuth client ID
- `DATABASE_URL`: PostgreSQL connection string

### No Breaking Changes
- All existing commands still work
- No changes to existing database tables
- Backwards compatible

### Bot Permissions Required
- ✅ Manage Messages (for pinning)
- ✅ Add Reactions
- ✅ Read Message History
- ✅ Send Messages
- ✅ Embed Links

## Usage Instructions

### For Server Admins
1. Run `!setup_link_panel` in your desired channel
2. Bot will create and pin the message
3. Tell users to react with the emoji to link

### For Users
1. React to the pinned message with 🔗
2. Check DMs for your personal OAuth link
3. Click the link and authorize with Kick
4. Done!

## Comparison: Command vs Reaction

| Aspect | `!link` Command | Reaction Panel |
|--------|-----------------|----------------|
| **Discoverability** | Low (users must know command) | High (always visible, pinned) |
| **Channel spam** | High (everyone types !link) | None (reactions invisible) |
| **User friction** | Medium (type command) | Low (one click) |
| **Visual clutter** | High (many command messages) | None (one pinned message) |
| **Availability** | Always | Set up by admin |
| **Fallback** | Primary | If reactions fail |

## Future Enhancements (Optional)

- [ ] Custom embed text per server
- [ ] Multiple emojis for different link types
- [ ] Analytics: track how many users use reaction vs command
- [ ] Cooldown per user to prevent spam
- [ ] Admin command to remove link panel
- [ ] Admin command to list all active link panels

## Troubleshooting

### "I don't have permission to pin messages"
**Fix**: Grant bot "Manage Messages" permission

### Reaction not detected
**Debug**: Check if bot has "Add Reactions" and "Read Message History" permissions

### DM not sent
**Expected**: Bot falls back to channel message (auto-deletes in 60s)

### Multiple panels not working
**Expected**: Only one panel per channel works at a time (newest one)
