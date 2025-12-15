# Multiserver Implementation Plan - Kick Discord Bot

## Overview
Transform the bot from single-server to multi-server support, allowing it to operate across multiple Discord servers simultaneously with isolated data and settings per server.

## Current Architecture
- **Single Guild Mode**: Uses `DISCORD_GUILD_ID` environment variable
- **Global Settings**: BotSettingsManager loads settings without server context
- **Shared Database**: All servers would share the same data (not isolated)

## Target Architecture
- **Multi-Guild Mode**: Bot joins and operates in multiple Discord servers
- **Server-Scoped Settings**: BotSettingsManager loads per-server settings
- **Data Isolation**: Each server has separate data via `discord_server_id` column

## Changes Required

### 1. Core Bot Changes

#### bot.py
- [x] Remove global `DISCORD_GUILD_ID` dependency
- [ ] Store guild context in command execution
- [ ] Pass `guild_id` / `discord_server_id` to all database queries
- [ ] Update permission checks to be guild-aware
- [ ] Update role management to work per-guild

#### utils/bot_settings.py (BotSettingsManager)
- [ ] Add `guild_id` parameter to initialization
- [ ] Update `refresh()` to filter by `discord_server_id`
- [ ] Update all `get()` methods to use guild context
- [ ] Cache settings per-guild (not globally)

### 2. Database Query Updates

All database queries need `discord_server_id` filtering. The dashboard already has this column in these tables:
- `bot_settings` - Already has `discord_server_id`
- `custom_commands` - Already has `discord_server_id`
- `timed_messages` - Already has `discord_server_id`
- `point_settings` - Already has `discord_server_id`
- `raffle_periods` - Already has `discord_server_id`
- `raffle_tickets` - Via join with raffle_periods
- `raffle_draws` - Via join with raffle_periods
- `shuffle_slots` - Already has `discord_server_id`

New queries to add:
- `servers` table queries (already exists in dashboard)
- `kick_oauth_tokens` - Needs guild context
- `user_points` - Needs `discord_server_id` column
- `point_sales` - Needs `discord_server_id` column
- `slot_requests` - Needs `discord_server_id` column

### 3. Feature Updates

#### raffle_system/
- [ ] Update all queries to include `discord_server_id`
- [ ] Pass guild_id through entire raffle flow
- [ ] Update scheduler to work per-guild
- [ ] Update leaderboards to be per-guild

#### features/custom_commands/
- [ ] Already uses `discord_server_id` in queries
- [ ] Verify guild context is passed correctly

#### features/slot_requests/
- [ ] Add `discord_server_id` to slot_requests table
- [ ] Update all queries to filter by guild
- [ ] Update slot call tracker for per-guild tracking

#### features/games/guess_the_balance/
- [ ] Add guild context to GTB games
- [ ] Store guild_id with game state

#### features/linking/
- [ ] Update OAuth to store guild context
- [ ] Update link panel per-guild

#### features/messaging/timed_messages/
- [ ] Already uses `discord_server_id`
- [ ] Verify guild context

### 4. Migration Strategy

#### Phase 1: Add Missing Columns
```sql
-- Add discord_server_id to tables that don't have it
ALTER TABLE user_points ADD COLUMN IF NOT EXISTS discord_server_id BIGINT;
ALTER TABLE point_sales ADD COLUMN IF NOT EXISTS discord_server_id BIGINT;
ALTER TABLE slot_requests ADD COLUMN IF NOT EXISTS discord_server_id BIGINT;
ALTER TABLE kick_oauth_tokens ADD COLUMN IF NOT EXISTS discord_server_id BIGINT;

-- Backfill with default server (if exists)
UPDATE user_points SET discord_server_id = (SELECT discord_server_id FROM servers LIMIT 1) WHERE discord_server_id IS NULL;
UPDATE point_sales SET discord_server_id = (SELECT discord_server_id FROM servers LIMIT 1) WHERE discord_server_id IS NULL;
UPDATE slot_requests SET discord_server_id = (SELECT discord_server_id FROM servers LIMIT 1) WHERE discord_server_id IS NULL;
UPDATE kick_oauth_tokens SET discord_server_id = (SELECT discord_server_id FROM servers LIMIT 1) WHERE discord_server_id IS NULL;

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_user_points_server ON user_points(discord_server_id);
CREATE INDEX IF NOT EXISTS idx_point_sales_server ON point_sales(discord_server_id);
CREATE INDEX IF NOT EXISTS idx_slot_requests_server ON slot_requests(discord_server_id);
CREATE INDEX IF NOT EXISTS idx_kick_oauth_tokens_server ON kick_oauth_tokens(discord_server_id);
```

#### Phase 2: Update Bot Code
1. Update BotSettingsManager to be guild-aware
2. Update core bot.py to track guild context
3. Update each feature module one by one
4. Test with multiple guilds

#### Phase 3: Deployment
1. Deploy with migrations
2. Test single-server mode (backwards compatible)
3. Add bot to second server for testing
4. Verify data isolation

## Implementation Order

1. **Core Infrastructure** (Priority: CRITICAL)
   - [ ] Add migration code to bot.py startup
   - [ ] Update BotSettingsManager for multi-guild
   - [ ] Create guild context helper

2. **Bot Settings** (Priority: HIGH)
   - [ ] Update all bot_settings queries
   - [ ] Test settings isolation per-guild

3. **Raffle System** (Priority: HIGH)
   - [ ] Update raffle database queries
   - [ ] Update raffle commands
   - [ ] Update raffle scheduler

4. **Custom Commands** (Priority: MEDIUM)
   - [ ] Verify existing multi-guild support
   - [ ] Test command isolation

5. **Point System** (Priority: MEDIUM)
   - [ ] Add discord_server_id to user_points
   - [ ] Update point tracking
   - [ ] Update point shop

6. **Slot Requests** (Priority: MEDIUM)
   - [ ] Add discord_server_id to slot_requests
   - [ ] Update slot tracker
   - [ ] Update slot panel

7. **OAuth/Linking** (Priority: LOW)
   - [ ] Add guild context to OAuth
   - [ ] Update link panel

8. **Testing** (Priority: CRITICAL)
   - [ ] Test with multiple guilds
   - [ ] Verify data isolation
   - [ ] Test role updates per-guild
   - [ ] Test Redis pub/sub per-guild

## Success Criteria

✅ Bot can join multiple Discord servers  
✅ Each server has isolated settings  
✅ Each server has isolated raffle data  
✅ Each server has isolated custom commands  
✅ Each server has isolated point system  
✅ Each server has isolated slot requests  
✅ No data leakage between servers  
✅ Backwards compatible with single-server setup  

## Rollback Plan

If issues arise:
1. Bot still works in single-server mode
2. Can deploy previous version quickly
3. Database migrations are additive (columns added, not removed)
4. Can continue using first server without issues

## Timeline

- **Phase 1** (Core): 2-3 hours
- **Phase 2** (Features): 4-6 hours
- **Phase 3** (Testing): 2-3 hours
- **Total**: 8-12 hours estimated

## Notes

- Dashboard is already multiserver-ready
- Most tables already have `discord_server_id` column
- Main work is updating bot code to use guild context
- BotSettingsManager is the key component to update first
