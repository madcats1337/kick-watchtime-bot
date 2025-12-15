# Multiserver Migration SQL for Kick Discord Bot

## Overview
This migration adds `discord_server_id` columns to tables that don't have them yet, enabling the bot to support multiple Discord servers simultaneously with isolated data.

## Tables That Already Have discord_server_id
These tables are already multiserver-ready from the Admin Dashboard:
- ✅ bot_settings (key, discord_server_id) - PRIMARY KEY
- ✅ custom_commands (id, discord_server_id) 
- ✅ timed_messages (id, discord_server_id)
- ✅ point_settings (key, discord_server_id) - PRIMARY KEY  
- ✅ raffle_periods (id, discord_server_id)
- ✅ raffle_tickets (linked via raffle_periods)
- ✅ raffle_draws (linked via raffle_periods)
- ✅ shuffle_slots (id, discord_server_id)
- ✅ point_shop_items (id, discord_server_id)
- ✅ links (discord_id, discord_server_id) - PRIMARY KEY
- ✅ slot_requests (id, discord_server_id)
- ✅ servers (discord_server_id) - PRIMARY KEY

## Tables That Need Migration

###  1. user_points
**Current PK**: kick_username (UNIQUE)
**Strategy**: Add discord_server_id, make composite PK (kick_username, discord_server_id)

```sql
-- Add column
ALTER TABLE user_points ADD COLUMN IF NOT EXISTS discord_server_id BIGINT;

-- Backfill with first server ID (if exists)
UPDATE user_points SET discord_server_id = (
    SELECT discord_server_id FROM servers LIMIT 1
) WHERE discord_server_id IS NULL;

-- Drop old unique constraint
ALTER TABLE user_points DROP CONSTRAINT IF EXISTS user_points_kick_username_key;

-- Add composite primary key
ALTER TABLE user_points ADD CONSTRAINT user_points_pkey_multiserver 
    PRIMARY KEY (kick_username, discord_server_id);

-- Add index for queries
CREATE INDEX IF NOT EXISTS idx_user_points_server ON user_points(discord_server_id);
```

### 2. points_watchtime_converted  
**Current**: No PK constraint
**Strategy**: Add discord_server_id as foreign key reference

```sql
-- Add column
ALTER TABLE points_watchtime_converted ADD COLUMN IF NOT EXISTS discord_server_id BIGINT;

-- Backfill
UPDATE points_watchtime_converted SET discord_server_id = (
    SELECT discord_server_id FROM servers LIMIT 1
) WHERE discord_server_id IS NULL;

-- Add index
CREATE INDEX IF NOT EXISTS idx_points_watchtime_server ON points_watchtime_converted(discord_server_id);
```

### 3. point_sales
**Current**: id (SERIAL PRIMARY KEY)
**Strategy**: Add discord_server_id, keep id as PK

```sql
-- Add column
ALTER TABLE point_sales ADD COLUMN IF NOT EXISTS discord_server_id BIGINT;

-- Backfill
UPDATE point_sales SET discord_server_id = (
    SELECT discord_server_id FROM servers LIMIT 1
) WHERE discord_server_id IS NULL;

-- Add index
CREATE INDEX IF NOT EXISTS idx_point_sales_server ON point_sales(discord_server_id);
```

### 4. watchtime
**Current**: username (PRIMARY KEY)
**Strategy**: Add discord_server_id, make composite PK

```sql
-- Add column
ALTER TABLE watchtime ADD COLUMN IF NOT EXISTS discord_server_id BIGINT;

-- Backfill
UPDATE watchtime SET discord_server_id = (
    SELECT discord_server_id FROM servers LIMIT 1
) WHERE discord_server_id IS NULL;

-- Recreate primary key as composite
ALTER TABLE watchtime DROP CONSTRAINT IF EXISTS watchtime_pkey;
ALTER TABLE watchtime ADD CONSTRAINT watchtime_pkey_multiserver 
    PRIMARY KEY (username, discord_server_id);

-- Add index
CREATE INDEX IF NOT EXISTS idx_watchtime_server ON watchtime(discord_server_id);
```

### 5. gtb_sessions, gtb_guesses, gtb_winners
**Current**: Serial IDs
**Strategy**: Add discord_server_id to sessions (cascades to guesses/winners)

```sql
-- Add to gtb_sessions
ALTER TABLE gtb_sessions ADD COLUMN IF NOT EXISTS discord_server_id BIGINT;

-- Backfill
UPDATE gtb_sessions SET discord_server_id = (
    SELECT discord_server_id FROM servers LIMIT 1
) WHERE discord_server_id IS NULL;

-- Add index
CREATE INDEX IF NOT EXISTS idx_gtb_sessions_server ON gtb_sessions(discord_server_id);
```

### 6. clips
**Current**: id (SERIAL PRIMARY KEY)
**Strategy**: Add discord_server_id

```sql
-- Add column
ALTER TABLE clips ADD COLUMN IF NOT EXISTS discord_server_id BIGINT;

-- Backfill
UPDATE clips SET discord_server_id = (
    SELECT discord_server_id FROM servers LIMIT 1
) WHERE discord_server_id IS NULL;

-- Add index
CREATE INDEX IF NOT EXISTS idx_clips_server ON clips(discord_server_id);
```

### 7. link_panels, timer_panels
**Current**: guild_id is already present (renamed to discord_server_id for consistency)
**Strategy**: These already use guild_id - ensure consistency

```sql
-- link_panels and timer_panels already have guild_id column
-- They are already multiserver-aware
-- No changes needed
```

### 8. watchtime_roles
**Current**: Global configuration (id PRIMARY KEY)
**Strategy**: Add discord_server_id for per-server role configs

```sql
-- Add column
ALTER TABLE watchtime_roles ADD COLUMN IF NOT EXISTS discord_server_id BIGINT;

-- Backfill global roles (NULL = default for all servers)
-- Existing rows stay NULL for backwards compatibility

-- Add index
CREATE INDEX IF NOT EXISTS idx_watchtime_roles_server ON watchtime_roles(discord_server_id);
```

### 9. link_logs_config
**Current**: guild_id (PRIMARY KEY)
**Strategy**: Already uses guild_id - rename for consistency (optional)

```sql
-- Already uses guild_id as primary key
-- No changes needed, guild_id = discord_server_id semantically
```

### 10. oauth_notifications, pending_links, bot_tokens
**Current**: Used for OAuth flow
**Strategy**: Add discord_server_id to track which server initiated the link

```sql
-- pending_links
ALTER TABLE pending_links ADD COLUMN IF NOT EXISTS discord_server_id BIGINT;

-- oauth_notifications
ALTER TABLE oauth_notifications ADD COLUMN IF NOT EXISTS discord_server_id BIGINT;

-- Backfill if needed
UPDATE pending_links SET discord_server_id = (SELECT discord_server_id FROM servers LIMIT 1) WHERE discord_server_id IS NULL;
UPDATE oauth_notifications SET discord_server_id = (SELECT discord_server_id FROM servers LIMIT 1) WHERE discord_server_id IS NULL;

-- Add indexes
CREATE INDEX IF NOT EXISTS idx_pending_links_server ON pending_links(discord_server_id);
CREATE INDEX IF NOT EXISTS idx_oauth_notifications_server ON oauth_notifications(discord_server_id);
```

## Complete Migration Script

```sql
-- ===================================================================
-- MULTISERVER MIGRATION FOR KICK DISCORD BOT
-- ===================================================================
-- This migration adds discord_server_id columns to enable multi-guild support
-- Run this on your PostgreSQL database after backing up
-- ===================================================================

BEGIN;

-- Step 1: Add discord_server_id columns
ALTER TABLE user_points ADD COLUMN IF NOT EXISTS discord_server_id BIGINT;
ALTER TABLE points_watchtime_converted ADD COLUMN IF NOT EXISTS discord_server_id BIGINT;
ALTER TABLE point_sales ADD COLUMN IF NOT EXISTS discord_server_id BIGINT;
ALTER TABLE watchtime ADD COLUMN IF NOT EXISTS discord_server_id BIGINT;
ALTER TABLE gtb_sessions ADD COLUMN IF NOT EXISTS discord_server_id BIGINT;
ALTER TABLE clips ADD COLUMN IF NOT EXISTS discord_server_id BIGINT;
ALTER TABLE watchtime_roles ADD COLUMN IF NOT EXISTS discord_server_id BIGINT;
ALTER TABLE pending_links ADD COLUMN IF NOT EXISTS discord_server_id BIGINT;
ALTER TABLE oauth_notifications ADD COLUMN IF NOT EXISTS discord_server_id BIGINT;

-- Step 2: Backfill existing data with first server ID (if exists)
DO $$
DECLARE
    first_server_id BIGINT;
BEGIN
    -- Get first server ID
    SELECT discord_server_id INTO first_server_id FROM servers LIMIT 1;
    
    IF first_server_id IS NOT NULL THEN
        -- Backfill all tables
        UPDATE user_points SET discord_server_id = first_server_id WHERE discord_server_id IS NULL;
        UPDATE points_watchtime_converted SET discord_server_id = first_server_id WHERE discord_server_id IS NULL;
        UPDATE point_sales SET discord_server_id = first_server_id WHERE discord_server_id IS NULL;
        UPDATE watchtime SET discord_server_id = first_server_id WHERE discord_server_id IS NULL;
        UPDATE gtb_sessions SET discord_server_id = first_server_id WHERE discord_server_id IS NULL;
        UPDATE clips SET discord_server_id = first_server_id WHERE discord_server_id IS NULL;
        UPDATE pending_links SET discord_server_id = first_server_id WHERE discord_server_id IS NULL;
        UPDATE oauth_notifications SET discord_server_id = first_server_id WHERE discord_server_id IS NULL;
        
        RAISE NOTICE 'Backfilled all tables with server ID: %', first_server_id;
    ELSE
        RAISE WARNING 'No server found in servers table - skipping backfill';
    END IF;
END $$;

-- Step 3: Update primary keys for tables that need composite keys
-- user_points: (kick_username, discord_server_id)
ALTER TABLE user_points DROP CONSTRAINT IF EXISTS user_points_kick_username_key;
ALTER TABLE user_points DROP CONSTRAINT IF EXISTS user_points_pkey;
ALTER TABLE user_points ADD CONSTRAINT user_points_pkey_multiserver 
    PRIMARY KEY (kick_username, discord_server_id);

-- watchtime: (username, discord_server_id)
ALTER TABLE watchtime DROP CONSTRAINT IF EXISTS watchtime_pkey;
ALTER TABLE watchtime ADD CONSTRAINT watchtime_pkey_multiserver 
    PRIMARY KEY (username, discord_server_id);

-- Step 4: Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_user_points_server ON user_points(discord_server_id);
CREATE INDEX IF NOT EXISTS idx_points_watchtime_server ON points_watchtime_converted(discord_server_id);
CREATE INDEX IF NOT EXISTS idx_point_sales_server ON point_sales(discord_server_id);
CREATE INDEX IF NOT EXISTS idx_watchtime_server ON watchtime(discord_server_id);
CREATE INDEX IF NOT EXISTS idx_gtb_sessions_server ON gtb_sessions(discord_server_id);
CREATE INDEX IF NOT EXISTS idx_clips_server ON clips(discord_server_id);
CREATE INDEX IF NOT EXISTS idx_watchtime_roles_server ON watchtime_roles(discord_server_id);
CREATE INDEX IF NOT EXISTS idx_pending_links_server ON pending_links(discord_server_id);
CREATE INDEX IF NOT EXISTS idx_oauth_notifications_server ON oauth_notifications(discord_server_id);

COMMIT;

-- ===================================================================
-- Migration complete!
-- ===================================================================
-- Next steps:
-- 1. Update bot code to pass guild_id to all database queries
-- 2. Test with multiple Discord servers
-- 3. Verify data isolation between servers
-- ===================================================================
```

## Rollback Script

```sql
BEGIN;

-- Remove indexes
DROP INDEX IF EXISTS idx_user_points_server;
DROP INDEX IF EXISTS idx_points_watchtime_server;
DROP INDEX IF EXISTS idx_point_sales_server;
DROP INDEX IF EXISTS idx_watchtime_server;
DROP INDEX IF EXISTS idx_gtb_sessions_server;
DROP INDEX IF EXISTS idx_clips_server;
DROP INDEX IF EXISTS idx_watchtime_roles_server;
DROP INDEX IF EXISTS idx_pending_links_server;
DROP INDEX IF EXISTS idx_oauth_notifications_server;

-- Restore old primary keys
ALTER TABLE user_points DROP CONSTRAINT IF EXISTS user_points_pkey_multiserver;
ALTER TABLE user_points ADD CONSTRAINT user_points_kick_username_key UNIQUE (kick_username);

ALTER TABLE watchtime DROP CONSTRAINT IF EXISTS watchtime_pkey_multiserver;
ALTER TABLE watchtime ADD CONSTRAINT watchtime_pkey PRIMARY KEY (username);

-- Remove columns
ALTER TABLE user_points DROP COLUMN IF EXISTS discord_server_id;
ALTER TABLE points_watchtime_converted DROP COLUMN IF EXISTS discord_server_id;
ALTER TABLE point_sales DROP COLUMN IF EXISTS discord_server_id;
ALTER TABLE watchtime DROP COLUMN IF EXISTS discord_server_id;
ALTER TABLE gtb_sessions DROP COLUMN IF EXISTS discord_server_id;
ALTER TABLE clips DROP COLUMN IF EXISTS discord_server_id;
ALTER TABLE watchtime_roles DROP COLUMN IF EXISTS discord_server_id;
ALTER TABLE pending_links DROP COLUMN IF EXISTS discord_server_id;
ALTER TABLE oauth_notifications DROP COLUMN IF EXISTS discord_server_id;

COMMIT;
```

## Testing Checklist

After running the migration:

1. ✅ Verify all indexes were created
2. ✅ Check primary key constraints are correct
3. ✅ Confirm data was backfilled
4. ✅ Test bot startup (should not error)
5. ✅ Join bot to second Discord server
6. ✅ Verify settings isolation between servers
7. ✅ Test commands in both servers
8. ✅ Verify raffle data doesn't leak between servers
9. ✅ Test point system per-server
10. ✅ Verify watchtime tracking per-server

## Notes

- **Backwards Compatibility**: Existing single-server bots will continue to work after migration
- **Data Safety**: All existing data is preserved and backfilled with the first server ID
- **Performance**: Indexes added for all discord_server_id columns
- **Rollback Available**: Can revert changes if needed (see Rollback Script)
