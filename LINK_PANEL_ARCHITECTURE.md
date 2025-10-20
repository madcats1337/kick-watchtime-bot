# Link Panel System Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         Discord Server                          │
│                                                                 │
│  ┌──────────────────────────────────────┐                      │
│  │     #link Channel (Dedicated)        │                      │
│  │                                      │                      │
│  │  📌 [Pinned Message]                │                      │
│  │  ┌────────────────────────────────┐  │                      │
│  │  │  🎮 Link Your Kick Account    │  │                      │
│  │  │                                │  │                      │
│  │  │  React with 🔗 below...       │  │                      │
│  │  │                                │  │                      │
│  │  │  📝 How it works:             │  │                      │
│  │  │  1. Click 🔗                   │  │                      │
│  │  │  2. Get DM with OAuth link    │  │                      │
│  │  │  3. Authorize with Kick       │  │                      │
│  │  │  4. Done!                     │  │                      │
│  │  └────────────────────────────────┘  │                      │
│  │  Reactions: 🔗 (by bot)             │                      │
│  └──────────────────────────────────────┘                      │
│                    ↓                                           │
│           [User reacts with 🔗]                                │
│                    ↓                                           │
└────────────────────┼────────────────────────────────────────────┘
                     │
                     ↓
┌────────────────────────────────────────────────────────────────┐
│                        Bot Backend                             │
│                                                                │
│  on_raw_reaction_add(payload)                                 │
│    ↓                                                           │
│    ├─ Check: Is this a link panel message?                    │
│    │   └─ Query: link_panels table                            │
│    │                                                           │
│    ├─ Check: Does emoji match?                                │
│    │   └─ Compare: reaction vs stored emoji                   │
│    │                                                           │
│    ├─ Check: Is user already linked?                          │
│    │   └─ Query: links table                                  │
│    │                                                           │
│    ├─ Generate OAuth URL                                      │
│    │   └─ URL: {OAUTH_BASE_URL}/auth/kick?discord_id=123      │
│    │                                                           │
│    ├─ Send DM to user                                         │
│    │   ├─ Success: Store in oauth_notifications               │
│    │   └─ Fail: Send in channel (60s auto-delete)             │
│    │                                                           │
│    └─ Remove reaction                                         │
│                                                                │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ↓
┌────────────────────────────────────────────────────────────────┐
│                      User's DM                                 │
│                                                                │
│  From: YourBot                                                 │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │  🔗 Link with Kick OAuth                                │  │
│  │                                                          │  │
│  │  Click the button below to securely link your          │  │
│  │  Kick account.                                          │  │
│  │                                                          │  │
│  │  📝 Instructions                                        │  │
│  │  1. Click the link below                               │  │
│  │  2. Log in to Kick (if needed)                         │  │
│  │  3. Authorize the connection                           │  │
│  │  4. You're done!                                       │  │
│  │                                                          │  │
│  │  [🎮 Link with Kick] ← Button                          │  │
│  │                                                          │  │
│  │  Link expires in 10 minutes                            │  │
│  └─────────────────────────────────────────────────────────┘  │
│                                                                │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     │ [User clicks button]
                     ↓
┌────────────────────────────────────────────────────────────────┐
│                    OAuth Web Server                            │
│              (kick-dicord-bot-test.up.railway.app)             │
│                                                                │
│  /auth/kick?discord_id=123456789                              │
│    ↓                                                           │
│    ├─ Generate PKCE challenge                                 │
│    ├─ Store state in oauth_states table                       │
│    └─ Redirect to: kick.com/oauth/authorize                   │
│                                                                │
│  User logs in to Kick → Authorizes                            │
│                                                                │
│  /auth/kick/callback?code=ABC&state=XYZ                       │
│    ↓                                                           │
│    ├─ Verify state                                            │
│    ├─ Exchange code for access_token                          │
│    ├─ Call: api.kick.com/public/v1/users (with Bearer token) │
│    ├─ Get username from response                              │
│    ├─ Store: INSERT INTO links (discord_id, kick_name)        │
│    ├─ Update: oauth_notifications (set kick_username)         │
│    └─ Show success page                                       │
│                                                                │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ↓
┌────────────────────────────────────────────────────────────────┐
│                  Bot Background Task                           │
│             check_oauth_notifications_task()                   │
│                  (runs every 5 seconds)                        │
│                                                                │
│  Query oauth_notifications WHERE processed = FALSE            │
│    ↓                                                           │
│    └─ Found new completion?                                   │
│        ↓                                                       │
│        ├─ Fetch original DM message                           │
│        ├─ Delete the message                                  │
│        ├─ Send success notification:                          │
│        │   "✅ Successfully linked to {kick_username}!"       │
│        └─ Mark as processed                                   │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

## Data Flow

### 1. Setup Phase (Admin)
```
Admin: !setup_link_panel 🔗
  ↓
Bot: Creates embed → Adds reaction → Pins message
  ↓
Database: INSERT INTO link_panels (guild_id, channel_id, message_id, emoji)
```

### 2. User Reaction Phase
```
User: Clicks 🔗 on pinned message
  ↓
Bot: on_raw_reaction_add triggered
  ↓
Database: SELECT * FROM link_panels WHERE message_id = ?
  ↓
Database: SELECT * FROM links WHERE discord_id = ? (check if already linked)
  ↓
Bot: Generates OAuth URL
  ↓
Bot: Sends DM with button
  ↓
Database: INSERT INTO oauth_notifications (discord_id, message_id, ...)
  ↓
Bot: Removes user's reaction
```

### 3. OAuth Phase (External)
```
User: Clicks "Link with Kick" button in DM
  ↓
Browser: Redirects to OAuth server
  ↓
OAuth Server: Generates PKCE, stores state
  ↓
Kick: User authorizes app
  ↓
OAuth Server: Receives callback with code
  ↓
OAuth Server: Exchanges code for access_token
  ↓
Kick API: Returns user data (username)
  ↓
Database: INSERT INTO links (discord_id, kick_name)
  ↓
Database: UPDATE oauth_notifications SET kick_username = ? WHERE discord_id = ?
  ↓
Browser: Shows success page
```

### 4. Cleanup Phase (Background Task)
```
Background Task: Runs every 5 seconds
  ↓
Database: SELECT * FROM oauth_notifications WHERE processed = FALSE
  ↓
Found unprocessed notification?
  ↓
Bot: Fetches message by ID
  ↓
Bot: Deletes original DM
  ↓
Bot: Sends success message to user
  ↓
Database: UPDATE oauth_notifications SET processed = TRUE
```

## Database Schema

```sql
-- Stores pinned link panel messages
CREATE TABLE link_panels (
    id SERIAL PRIMARY KEY,
    guild_id BIGINT NOT NULL,        -- Discord server ID
    channel_id BIGINT NOT NULL,      -- Channel where panel is posted
    message_id BIGINT NOT NULL,      -- The pinned message ID
    emoji TEXT NOT NULL,             -- Reaction emoji (e.g., "🔗")
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(guild_id, channel_id, message_id)
);

-- Stores pending OAuth notifications
CREATE TABLE oauth_notifications (
    id SERIAL PRIMARY KEY,
    discord_id BIGINT NOT NULL,      -- User's Discord ID
    kick_username TEXT NOT NULL,     -- Kick username (empty until OAuth completes)
    channel_id BIGINT,               -- DM or channel ID where message was sent
    message_id BIGINT,               -- Message ID to delete after OAuth success
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processed BOOLEAN DEFAULT FALSE  -- Whether cleanup task has processed this
);

-- Stores linked accounts
CREATE TABLE links (
    discord_id BIGINT PRIMARY KEY,   -- User's Discord ID
    kick_name TEXT UNIQUE            -- User's Kick username
);

-- Stores OAuth state for PKCE flow
CREATE TABLE oauth_states (
    state TEXT PRIMARY KEY,          -- Random state token
    discord_id BIGINT NOT NULL,      -- User's Discord ID
    code_verifier TEXT NOT NULL,     -- PKCE code verifier
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## Event Flow Timeline

```
T=0s    Admin runs !setup_link_panel
        ↓ (<1s)
        Bot creates and pins message
        
T=10s   User reacts with 🔗
        ↓ (<1s)
        Bot detects reaction
        ↓
        Bot sends DM with OAuth link
        ↓
        Bot removes reaction
        
T=15s   User clicks OAuth button in DM
        ↓ (varies - user must log in)
        User authorizes on Kick
        ↓ (1-2s)
        OAuth server links accounts
        ↓
        Success page shown
        
T=20s   Background task runs (every 5s)
        ↓ (<1s)
        Task detects new link
        ↓
        Bot deletes original DM
        ↓
        Bot sends success notification
```

## Comparison: Command vs Reaction

### Command Method (`!link`)
```
Channel Timeline:
-------------------
10:00 AM | User1: !link
10:00 AM | Bot: [OAuth embed for User1]
10:01 AM | User2: !link
10:01 AM | Bot: [OAuth embed for User2]
10:02 AM | User3: !link
10:02 AM | Bot: [OAuth embed for User3]
...
[20+ messages visible, scrolling continues]
```
❌ Cluttered  
❌ Spam  
❌ Hard to find  

### Reaction Method
```
Channel Timeline:
-------------------
10:00 AM | Bot: [Pinned OAuth instructions]
           📌 Pinned to top
           [No other messages - reactions are invisible]
           
[Users react → get DMs → no channel spam]
```
✅ Clean  
✅ Professional  
✅ Always visible  

## Security Features

1. **Unique OAuth URLs**: Each user gets a unique `discord_id` parameter
2. **PKCE Flow**: Protects against authorization code interception
3. **State Validation**: Prevents CSRF attacks
4. **Token Expiry**: OAuth links expire in 10 minutes
5. **One Link Per User**: Database enforces unique discord_id
6. **Reaction Cleanup**: Prevents spam by removing reactions
7. **DM Privacy**: OAuth links sent privately (not in public channel)

## Error Handling

```
┌─────────────────────┐
│ User reacts         │
└──────┬──────────────┘
       │
       ├─ User already linked?
       │  └─→ Send "already linked" DM, remove reaction
       │
       ├─ DMs disabled?
       │  └─→ Send in channel (auto-delete 60s), remove reaction
       │
       ├─ OAuth not configured?
       │  └─→ Send error message
       │
       └─ Success
          └─→ Send OAuth link DM, remove reaction
```
