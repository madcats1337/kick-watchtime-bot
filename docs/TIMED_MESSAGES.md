# Timed Messages System

## Overview

The timed messages system allows admins to schedule recurring messages that are automatically sent to Kick chat at specified intervals.

## Features

- 📅 Schedule messages with custom intervals (minutes)
- ✅/❌ Enable/disable individual messages
- 🔄 Update intervals without recreating messages
- 📋 List and manage all timed messages
- 🎛️ Interactive reaction-based control panel
- 💾 Persistent storage in database
- ⏰ Background task checks every minute

## Commands

### Admin Commands

#### Add Timed Message
```
!addtimer <minutes> <message>
```
Schedule a new recurring message.

**Examples:**
```
!addtimer 30 Join our Discord: discord.gg/example
!addtimer 60 🎰 Use !call to request slots!
!addtimer 15 Thanks for watching! Follow the channel for more!
```

#### Remove Timed Message
```
!removetimer <message_id>
```
Permanently delete a timed message.

**Example:**
```
!removetimer 1
```

#### Enable/Disable Message
```
!toggletimer <message_id> <on|off>
```
Toggle a message on or off without deleting it.

**Examples:**
```
!toggletimer 1 off
!toggletimer 2 on
```

#### Update Interval
```
!updatetimer <message_id> <minutes>
```
Change how often a message is sent.

**Examples:**
```
!updatetimer 1 45
!updatetimer 2 120
```

#### List All Messages
```
!listtimers
```
Show all configured timed messages with their status and timing.

#### Control Panel
```
!timerpanel
```
Open an interactive message management panel with reaction buttons.

## Usage Examples

### Setting Up Promotional Messages

```bash
# Add Discord link every 30 minutes
!addtimer 30 Join our community: discord.gg/example

# Add social media reminder every hour
!addtimer 60 Follow us on Twitter @example for giveaways!

# Add slot request info every 15 minutes
!addtimer 15 🎰 Type !call <slot name> to request a game!
```

### Managing Messages

```bash
# List all timers to see their IDs
!listtimers

# Disable a message temporarily
!toggletimer 1 off

# Change interval to 45 minutes
!updatetimer 1 45

# Re-enable the message
!toggletimer 1 on

# Remove a message completely
!removetimer 3
```

## Database Schema

```sql
CREATE TABLE timed_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message TEXT NOT NULL,
    interval_minutes INTEGER NOT NULL,
    enabled BOOLEAN DEFAULT TRUE,
    last_sent TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by BIGINT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## How It Works

### Background Task
- Runs every 1 minute
- Checks all enabled messages
- Calculates if each message is due based on `interval_minutes` and `last_sent`
- Sends messages via Kick chat API
- Updates `last_sent` timestamp

### Message Timing
- **First Send:** Sent immediately on first check after creation
- **Subsequent Sends:** Sent when `current_time - last_sent >= interval_minutes`
- **Disabled Messages:** Skipped entirely, timer doesn't advance

### Example Timeline
```
Message: "Join our Discord"
Interval: 30 minutes
Created: 10:00

10:01 → First check → Sent (last_sent = 10:01)
10:15 → Check → Not due (only 14 minutes)
10:31 → Check → Sent (30+ minutes passed)
11:01 → Check → Sent
11:31 → Check → Sent
... continues every 30 minutes
```

## Integration

### In bot.py

```python
from timed_messages import setup_timed_messages

# In on_ready()
timed_messages_manager = await setup_timed_messages(
    bot,
    engine,
    kick_send_callback=send_kick_message if KICK_BOT_USER_TOKEN else None
)
```

### Requirements

- **KICK_BOT_USER_TOKEN**: Must be set for messages to send to Kick chat
- **Database**: SQLite or PostgreSQL with timed_messages table
- **Kick OAuth**: Bot must have chat:write scope

## Reaction Panel (Future Enhancement)

The `!timerpanel` command creates an interactive panel where admins can react to:
- ➕ Add new timer
- 📋 List all timers
- 🔄 Refresh panel

To implement full reaction handling, add:

```python
@commands.Cog.listener()
async def on_reaction_add(self, reaction, user):
    if user.bot:
        return
    
    # Check if reaction is on a timer panel
    # Handle different reaction types
    # Update panel accordingly
```

## Best Practices

### Interval Guidelines
- **Promotional messages:** 30-60 minutes
- **Command reminders:** 15-30 minutes
- **Social links:** 45-90 minutes
- **Important announcements:** 120+ minutes

### Message Content
- Keep messages under 200 characters for readability
- Use emojis to catch attention: 🎰 💰 🎁 ⭐
- Include clear calls to action
- Avoid spammy language
- Test messages in a test channel first

### Management
- Review and update messages weekly
- Disable messages during special events
- Remove outdated promotional content
- Monitor chat reaction to adjust intervals

## Troubleshooting

**Messages not sending:**
- Check KICK_BOT_USER_TOKEN is set
- Verify bot has chat:write scope
- Check bot follows the channel
- Run `!listtimers` to confirm messages are enabled

**Messages sending too frequently:**
- Use `!updatetimer <id> <minutes>` to increase interval
- Temporarily disable with `!toggletimer <id> off`

**Database errors:**
- Ensure database connection is working
- Check table was created: `SELECT * FROM timed_messages`
- Verify write permissions

## Examples

### Stream Setup
```bash
# Social media links
!addtimer 45 Follow on Twitter: @streamername
!addtimer 60 Subscribe on YouTube: youtube.com/@streamername

# Chat engagement
!addtimer 20 🎁 Type !raffle to join the giveaway!
!addtimer 30 🎰 Request slots with !call <game name>

# Community
!addtimer 90 Join Discord for exclusive perks: discord.gg/link
```

### Event Management
```bash
# Before event - Add countdown
!addtimer 10 🔴 GIVEAWAY STARTING IN 30 MINUTES! 🔴

# During event - Pause regular messages
!toggletimer 1 off
!toggletimer 2 off

# After event - Resume
!toggletimer 1 on
!toggletimer 2 on
```

## Future Enhancements

Potential improvements:
- [ ] Variable message rotation (random selection from pool)
- [ ] Time-based scheduling (only send during stream hours)
- [ ] Viewer count triggers (only send if viewers > X)
- [ ] Message templates with variables (e.g., {streamer_name})
- [ ] Copy messages between timers
- [ ] Import/export timer configurations
- [ ] Statistics tracking (times sent, last 10 sends)
- [ ] Web dashboard for easier management
