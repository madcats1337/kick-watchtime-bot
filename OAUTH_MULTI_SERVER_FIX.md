# OAuth Multi-Server Link Fix

## Problem
The Kick link function was not setting the correct `discord_server_id` in the links table, causing all new links to be created with `discord_server_id=0`. This broke multi-server isolation where users linking their accounts on different Discord servers were not properly separated.

## Root Cause
The OAuth flow involved multiple services:
1. **Discord Bot** (knows guild_id) → generates OAuth URL
2. **User clicks link** → redirects to Flask OAuth server
3. **Flask OAuth Server** (doesn't know guild_id) → completes OAuth and inserts link
4. **Result**: `discord_server_id` defaulted to 0 or NULL

The guild context was lost when the user was redirected from Discord to the Flask OAuth server.

## Solution
Pass `guild_id` through the entire OAuth flow using URL parameters and cryptographic signatures.

### Changes Made

#### 1. Bot OAuth URL Generation (`bot.py`)
- **Function**: `generate_signed_oauth_url(discord_id, guild_id=None)`
- **Changes**:
  - Added `guild_id` parameter (defaults to 0 for backwards compatibility)
  - Included `guild_id` in HMAC signature: `f"{discord_id}:{guild_id}:{timestamp}"`
  - Added `guild_id` to URL parameters: `&guild_id={guild_id}`
  - Updated all call sites to pass `guild_id` from `ctx.guild.id` or `interaction.guild.id`

#### 2. Link Panel (`features/linking/link_panel.py`)
- **Function**: `handle_link_account(interaction)`
- **Changes**:
  - Extract `guild_id` from `interaction.guild.id`
  - Pass `guild_id` to `oauth_url_generator(discord_id, guild_id)`

#### 3. OAuth Server Signature Functions (`core/oauth_server.py`)
- **Functions**: `sign_discord_id()`, `verify_discord_id_signature()`
- **Changes**:
  - Added `guild_id` parameter to both functions
  - Include `guild_id` in signature message: `f"{discord_id}:{guild_id}:{timestamp}"`
  - Verify guild_id matches between URL and signature

#### 4. OAuth Initiation Endpoint (`core/oauth_server.py`)
- **Route**: `/auth/kick`
- **Changes**:
  - Extract `guild_id` from query parameters (default to '0')
  - Verify signature with `guild_id`
  - Store `guild_id` in `oauth_states` table alongside `discord_id`

#### 5. OAuth States Table (`core/oauth_server.py`)
- **Table**: `oauth_states`
- **Changes**:
  - Added column: `guild_id BIGINT DEFAULT 0`
  - Migration: `ALTER TABLE oauth_states ADD COLUMN IF NOT EXISTS guild_id BIGINT DEFAULT 0`

#### 6. OAuth Callback Endpoint (`core/oauth_server.py`)
- **Route**: `/auth/kick/callback`
- **Changes**:
  - Extract `guild_id` from `oauth_states` table when retrieving state
  - Pass `guild_id` to `handle_user_linking_callback()`

#### 7. Link Insertion (`core/oauth_server.py`)
- **Function**: `handle_user_linking_callback(code, code_verifier, state, discord_id, created_at, guild_id=0)`
- **Changes**:
  - Added `guild_id` parameter
  - Check if Kick account is already linked on **this server**: `WHERE kick_name = :k AND discord_server_id = :gid`
  - Insert with composite PK: `INSERT INTO links (discord_id, kick_name, discord_server_id) VALUES (:d, :k, :gid)`
  - Update ON CONFLICT to use composite PK: `ON CONFLICT(discord_id, discord_server_id) DO UPDATE...`

### Security Considerations
- The `guild_id` is part of the HMAC signature, preventing tampering
- Signature expires after 1 hour
- State tokens expire after 30 minutes
- No plaintext sensitive data in URLs

### Backwards Compatibility
- All new parameters default to 0 if not provided
- Existing links in the database can be fixed using `!fixlinks backfill`
- Old OAuth URLs without `guild_id` will still work (signature verification defaults to guild_id=0)

## Testing
1. **Generate new OAuth URL** from Discord bot link panel
2. **Complete OAuth flow** in browser
3. **Verify link inserted** with correct `discord_server_id`:
   ```sql
   SELECT discord_id, kick_name, discord_server_id, linked_at 
   FROM links 
   WHERE discord_id = YOUR_DISCORD_ID;
   ```
4. **Run diagnostics**: `!fixlinks check` should show no more links with `discord_server_id=0`

## Admin Commands
The following admin commands are available to manage links:
- `!fixlinks check` - Show diagnostics and link distribution
- `!fixlinks backfill` - Auto-fix existing links with `discord_server_id=0`
- `!fixlinks duplicates` - List Kick names on multiple servers
- `!fixlinks resolve <kick_name> <server_id>` - Resolve duplicate conflicts

## Migration Path
1. **Deploy updated code** (commit de5b82f)
2. **Run backfill** to fix existing links: `!fixlinks backfill`
3. **Verify** no more 0 values: `!fixlinks check`
4. **Test** new linking flows on each server

## Files Modified
- `bot.py` - OAuth URL generation and command updates
- `core/oauth_server.py` - OAuth server endpoints and callbacks
- `features/linking/link_panel.py` - Link panel button handler
- `test_links_multi_server.py` - Diagnostic script (previous commit)

## Commit Hash
`de5b82f` - fix: pass guild_id through OAuth flow to fix multi-server link isolation
