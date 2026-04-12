# Multiserver Implementation Status

## Completed ✅

### 1. BotSettingsManager Refactored
**File**: `utils/bot_settings.py`

**Changes**:
- Added `guild_id` parameter to `__init__()`
- Updated `refresh()` method to filter by guild_id:
  - Single-server mode: Loads only global settings (NULL discord_server_id)
  - Multi-server mode: Loads global settings + guild-specific overrides
- Updated `set()` method to save settings with guild_id
- Added `guild_id` property

**Usage**:
```python
# Single-server (backwards compatible)
settings = BotSettingsManager(engine)

# Multi-server
settings = BotSettingsManager(engine, guild_id=123456789)
settings.refresh(guild_id=987654321)  # Can also override on refresh
```

### 2. Database Migration Added
**File**: `bot.py` (startup code)

**Changes**:
- Added automatic migration on bot startup
- Adds `discord_server_id` columns to 9 tables:
  - `user_points` (composite PK)
  - `points_watchtime_converted`
  - `point_sales`
  - `watchtime` (composite PK)
  - `gtb_sessions`
  - `clips`
  - `watchtime_roles`
  - `pending_links`
  - `oauth_notifications`
- Backfills existing data with first server ID
- Updates primary keys to composite keys where needed
- Creates indexes for performance

**Migration SQL**: `MULTISERVER_MIGRATION_SQL.md`

### 3. Documentation Created
- **MULTISERVER_IMPLEMENTATION_PLAN.md**: Implementation strategy
- **MULTISERVER_MIGRATION_SQL.md**: Database migration details

## In Progress 🔄

### Bot Core Updates
**Current Task**: Remove global DISCORD_GUILD_ID, add per-guild context

**Key Issues**:
1. `DISCORD_GUILD_ID` is used globally (30+ locations)
2. Settings manager is global (single instance)
3. Trackers are global (raffle, shuffle, slot calls, GTB)
4. No guild context passed to commands

**Strategy**:
- Keep `DISCORD_GUILD_ID` as optional env var for backwards compatibility
- Create per-guild settings managers dictionary
- Update commands to get guild from context
- Pass guild_id to all database queries
- Update trackers to be guild-aware

## Pending ⏸️

### 3. Raffle System
**Location**: `raffle_system/`

**Changes Needed**:
- Update all queries to filter by `discord_server_id`
- Pass `guild_id` through entire raffle flow
- Update `gifted_sub_tracker` to be guild-aware
- Test period management per-guild

### 4. Point System
**Location**: `bot.py` (inline code)

**Changes Needed**:
- Add `discord_server_id` to `user_points` queries
- Add `discord_server_id` to `point_sales` queries
- Update `award_points_for_watchtime()` to accept guild_id
- Filter point shop by server

### 5. Slot Requests
**Location**: `features/slot_requests/`

**Changes Needed**:
- Add `discord_server_id` to `slot_requests` queries
- Update `slot_call_tracker` to be guild-aware
- Filter slot panel by server

### 6. Linking System
**Location**: `bot.py`, `core/oauth_server.py`

**Changes Needed**:
- Ensure `links` queries filter by `discord_server_id`
- Update OAuth flow to include guild context
- Test link panels per-guild

### 7. Watchtime System
**Location**: `bot.py` (update_watchtime_task)

**Changes Needed**:
- Add `discord_server_id` to watchtime queries
- Track active viewers per-guild
- Update role assignment per-guild

### 8. Custom Commands
**Location**: `features/custom_commands/`

**Status**: ✅ Already has `discord_server_id` in queries
**Action**: Verify guild context is passed correctly

### 9. Timed Messages
**Location**: `features/messaging/timed_messages/`

**Status**: ✅ Already has `discord_server_id` in queries
**Action**: Verify guild context is passed correctly

## Architecture Overview

### Single-Server Mode (Backwards Compatible)
```
Bot Startup
├── Load settings (global only)
├── Use DISCORD_GUILD_ID from env
├── Commands restricted to single guild
└── All data stored with that server's ID
```

### Multi-Server Mode (New)
```
Bot Startup
├── Load settings per-guild on-demand
├── Commands work in any joined guild
├── Guild context from command/interaction
└── Data isolated by discord_server_id
```

### Guild Context Flow
```
Command/Interaction
└── Get guild from ctx/interaction
    └── Get/Create guild settings manager
        └── Pass guild_id to database queries
            └── Data filtered by discord_server_id
```

## Database Schema

### Tables with discord_server_id
All these tables now have the `discord_server_id` column:

**Composite Primary Keys**:
- `bot_settings` (key, discord_server_id)
- `point_settings` (key, discord_server_id)
- `raffle_widget_settings` (setting_key, discord_server_id)
- `user_points` (kick_username, discord_server_id)
- `watchtime` (username, discord_server_id)
- `links` (discord_id, discord_server_id)

**Regular Column**:
- All other tables with discord_server_id as indexed column

### Foreign Key Relationships
```
servers (discord_server_id) [PK]
├── bot_settings (discord_server_id)
├── custom_commands (discord_server_id)
├── raffle_periods (discord_server_id)
│   ├── raffle_tickets (via period_id)
│   └── raffle_draws (via period_id)
├── shuffle_slots (discord_server_id)
├── point_shop_items (discord_server_id)
├── slot_requests (discord_server_id)
├── user_points (discord_server_id)
├── watchtime (discord_server_id)
└── ... (all other tables)
```

## Testing Plan

### Phase 1: Single Server (Backwards Compatibility)
1. ✅ Database migration runs successfully
2. ✅ Bot starts without errors
3. ⏸️ Existing commands work
4. ⏸️ Settings load correctly
5. ⏸️ Raffle system works
6. ⏸️ Point system works

### Phase 2: Two Servers
1. ⏸️ Join bot to second Discord server
2. ⏸️ Configure settings for second server
3. ⏸️ Run commands in both servers
4. ⏸️ Verify data doesn't leak between servers
5. ⏸️ Test raffle in both servers
6. ⏸️ Test linking in both servers

### Phase 3: Stress Test
1. ⏸️ Join bot to 5+ servers
2. ⏸️ Simultaneous commands in multiple servers
3. ⏸️ Verify performance
4. ⏸️ Check database query efficiency

## Next Steps

1. **Remove DISCORD_GUILD_ID dependency**
   - Create per-guild settings manager dictionary
   - Update `in_guild()` check to be guild-aware
   - Pass guild context through commands

2. **Update database queries**
   - Add guild_id parameter to all query functions
   - Filter by discord_server_id in WHERE clauses
   - Test with multiple guilds

3. **Update feature modules**
   - Raffle system (high priority)
   - Point system (medium priority)
   - Slot requests (medium priority)
   - OAuth linking (low priority)

4. **Testing and deployment**
   - Test single-server mode
   - Test multi-server mode
   - Deploy to production
   - Monitor for issues

## Notes

- **Backwards Compatibility**: The bot will continue to work in single-server mode if `DISCORD_GUILD_ID` is set
- **Data Safety**: All existing data is preserved during migration
- **Performance**: Indexes added for all discord_server_id columns
- **Rollback**: Migration can be reverted if needed (see MULTISERVER_MIGRATION_SQL.md)
