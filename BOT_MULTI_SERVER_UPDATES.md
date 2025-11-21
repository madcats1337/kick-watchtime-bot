# BOT MULTI-SERVER QUERY UPDATES

## Summary
The bot currently works for a single server. To support multiple Discord servers running the same bot instance, you need to add `WHERE discord_server_id = ctx.guild.id` to queries.

## Files to Update

### 1. bot.py (Main bot file)
**Lines with queries needing discord_server_id filter:**

```python
# Line 392 - watchtime_roles count
# CURRENT:
role_count = conn.execute(text("SELECT COUNT(*) FROM watchtime_roles")).fetchone()[0]
# NEEDS:
role_count = conn.execute(text("SELECT COUNT(*) FROM watchtime_roles WHERE discord_server_id = :sid"), {"sid": ctx.guild.id}).fetchone()[0]

# Line 1719, 3921, 3955 - oauth_notifications cleanup
# CURRENT:
conn.execute(text("DELETE FROM oauth_notifications WHERE discord_id = :d AND processed = FALSE"), {"d": discord_id})
# NEEDS:
conn.execute(text("DELETE FROM oauth_notifications WHERE discord_id = :d AND discord_server_id = :sid AND processed = FALSE"), {"d": discord_id, "sid": ctx.guild.id})

# Line 1758 - Delete user links
# CURRENT:
conn.execute(text("DELETE FROM links WHERE discord_id = :d"), {"d": discord_id})
# NEEDS:
conn.execute(text("DELETE FROM links WHERE discord_id = :d AND discord_server_id = :sid"), {"d": discord_id, "sid": ctx.guild.id})

# Line 1761 - Delete oauth notifications
# Already covered above

# Line 1764 - Delete pending links
# CURRENT:
conn.execute(text("DELETE FROM pending_links WHERE discord_id = :d"), {"d": discord_id})
# NEEDS:
conn.execute(text("DELETE FROM pending_links WHERE discord_id = :d AND discord_server_id = :sid"), {"d": discord_id, "sid": ctx.guild.id})

# Line 2250 - Max display order for watchtime roles
# CURRENT:
max_order = conn.execute(text("SELECT COALESCE(MAX(display_order), 0) FROM watchtime_roles")).fetchone()[0]
# NEEDS:
max_order = conn.execute(text("SELECT COALESCE(MAX(display_order), 0) FROM watchtime_roles WHERE discord_server_id = :sid"), {"sid": ctx.guild.id}).fetchone()[0]

# Line 3129 - Watchtime count
# CURRENT:
result = conn.execute(text("SELECT COUNT(*) FROM watchtime"))
# NEEDS:
result = conn.execute(text("SELECT COUNT(*) FROM watchtime WHERE discord_server_id = :sid"), {"sid": ctx.guild.id})

# Line 3134 - Links count
# CURRENT:
result = conn.execute(text("SELECT COUNT(*) FROM links"))
# NEEDS:
result = conn.execute(text("SELECT COUNT(*) FROM links WHERE discord_server_id = :sid"), {"sid": ctx.guild.id})

# Line 3139 - Active watchtime roles count
# CURRENT:
result = conn.execute(text("SELECT COUNT(*) FROM watchtime_roles WHERE enabled = true"))
# NEEDS:
result = conn.execute(text("SELECT COUNT(*) FROM watchtime_roles WHERE enabled = true AND discord_server_id = :sid"), {"sid": ctx.guild.id})
```

### 2. features/custom_commands/manager.py

```python
# Line 59 - Load custom commands
# CURRENT:
cursor.execute("""
    SELECT id, command, response, cooldown, enabled, use_count
    FROM custom_commands
    ORDER BY command
""")
# NEEDS:
cursor.execute("""
    SELECT id, command, response, cooldown, enabled, use_count
    FROM custom_commands
    WHERE discord_server_id = %s
    ORDER BY command
""", (guild_id,))
# NOTE: You'll need to pass guild_id to this function

# Line 160 - Update command use count
# CURRENT:
cursor.execute("""
    UPDATE custom_commands
    SET use_count = use_count + 1
    WHERE id = %s
""", (command_id,))
# NEEDS:
cursor.execute("""
    UPDATE custom_commands
    SET use_count = use_count + 1
    WHERE id = %s AND discord_server_id = %s
""", (command_id, guild_id))
# NOTE: You'll need to pass guild_id to this function
```

## Tables That Need Filtering

Based on the migration, these tables have discord_server_id and need filtering in bot queries:

✅ **Already have column:**
- links
- pending_links  
- watchtime
- watchtime_roles
- custom_commands
- timed_messages
- slot_requests
- slot_call_blacklist
- shuffle_slots
- gtb_sessions
- gtb_guesses
- gtb_winners
- raffle_periods
- raffle_tickets
- raffle_ticket_log
- raffle_shuffle_wagers
- raffle_shuffle_links
- raffle_gifted_subs
- raffle_draws
- bonus_hunt_sessions
- bonus_hunt_bonuses
- feature_settings
- bot_settings
- activity_logs
- link_panels
- timer_panels

❌ **System tables (no filtering needed):**
- oauth_states
- oauth_notifications  
- bot_tokens

## Implementation Strategy

### Option 1: Quick Fix (Current)
Keep DEFAULT value (914986636629143562) in database. Bot works for your current server. When adding server #2, update queries then.

### Option 2: Full Multi-Server Support
1. Update all queries to include discord_server_id filter
2. Pass ctx.guild.id or interaction.guild.id to all database functions
3. Update INSERT queries to explicitly set discord_server_id
4. Test with multiple Discord servers

## INSERT Queries

The migration added DEFAULT values, so INSERT queries work without changes:
```python
# This works (uses DEFAULT):
INSERT INTO links (discord_id, kick_name) VALUES (%s, %s)

# But for clarity and multi-server support, use:
INSERT INTO links (discord_id, kick_name, discord_server_id) VALUES (%s, %s, %s)
```

## Testing Plan

1. Deploy bot to a TEST Discord server with different ID
2. Add test data (links, commands, etc.)
3. Verify each server only sees/modifies its own data
4. Check that queries don't leak data between servers

## Estimated Effort

- **bot.py**: ~15-20 queries to update
- **features/**: ~5-10 queries to update  
- **Testing**: 2-3 hours
- **Total**: 4-6 hours

## Current Status

✅ Database schema ready (all tables have discord_server_id)
✅ Bot works for single server (DEFAULT value)
⏳ Queries need updating for multi-server isolation
⏳ Need to pass guild.id to database functions
