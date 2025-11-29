# Multi-Server Testing Guide

## 🎯 Testing Objectives

Verify that the bot maintains complete data isolation between Discord servers:
- Each server has independent raffle periods
- Each server has independent ticket ledgers
- Each server has independent settings
- Background tasks process each server separately

## 📋 Test Server Information

**Test Servers (IDs)**:
1. **Server 1**: `1444335288599187459`
2. **Server 2**: `1444335540945031221`
3. **Server 3**: `1444335793622614149`

**Production Server (for reference)**: `914986636629143562`

## 🚀 Step 1: Configure Railway Deployment

### A. Set Bot-Testing to Use Feature Branch

1. Go to Railway dashboard: https://railway.app/
2. Select project: **Discord bot**
3. Select environment: **Bot-testing**
4. Click on **LeleBot** service
5. Go to **Settings** tab
6. Under **Source**, click **Configure**
7. Change branch from `main` to `feature/multi-server-migration`
8. Save changes
9. Railway will automatically trigger a new deployment

### B. Verify Deployment

Wait for deployment to complete (check the **Deployments** tab). You should see:
- ✅ Build successful
- ✅ Deploy successful
- Bot should come online in Discord

## 🤖 Step 2: Invite Bot to Test Servers

### Generate OAuth2 URL

1. Go to Discord Developer Portal: https://discord.com/developers/applications
2. Select your bot application
3. Go to **OAuth2** → **URL Generator**
4. Select scopes:
   - ✅ `bot`
   - ✅ `applications.commands`
5. Select bot permissions:
   - ✅ Administrator (or specific permissions your bot needs)
6. Copy the generated URL
7. Open the URL in 3 different browser tabs/windows
8. For each tab, select one of your test servers and authorize

### Verify Bot Joined

Check that the bot appears in the member list of all 3 test servers.

## 🧪 Step 3: Test Data Isolation

### Test 1: Independent Raffle Periods

**In Server 1**:
```
!raffleinfo
```
Expected: Shows current raffle period for Server 1

**In Server 2**:
```
!raffleinfo
```
Expected: Shows current raffle period for Server 2 (should be independent)

**In Server 3**:
```
!raffleinfo
```
Expected: Shows current raffle period for Server 3 (should be independent)

### Test 2: Independent Ticket Ledgers

**Setup**: Link a Kick user in all 3 servers (use OAuth flow or admin command if available)

**In Server 1**:
```
!rafflegive @User 100
```
Expected: User receives 100 tickets in Server 1

**In Server 2**:
```
!tickets @User
```
Expected: User has 0 tickets in Server 2 (not affected by Server 1)

**In Server 3**:
```
!tickets @User
```
Expected: User has 0 tickets in Server 3 (not affected by Server 1)

**In Server 1**:
```
!tickets @User
```
Expected: User still has 100 tickets in Server 1

### Test 3: Independent Settings

**In Server 1**:
```
!settings raffle_enabled
```
Check current value, then toggle it if possible.

**In Server 2**:
```
!settings raffle_enabled
```
Expected: Server 2's setting should be independent (not affected by Server 1 change)

### Test 4: Leaderboard Isolation

**In Server 1**:
```
!raffleboard
```
Expected: Shows only Server 1 participants

**In Server 2**:
```
!raffleboard
```
Expected: Shows only Server 2 participants (empty if no tickets given yet)

### Test 5: Background Task Isolation

**Setup**: In Database
1. Connect to bot-testing database
2. Check `raffle_periods` table - should see separate periods for each discord_server_id
3. Check `raffle_tickets` table - tickets should be separated by discord_server_id

**Query Examples**:
```sql
-- Check periods per server
SELECT discord_server_id, start_date, end_date, status 
FROM raffle_periods 
ORDER BY discord_server_id, created_at;

-- Check tickets per server
SELECT discord_server_id, COUNT(*), SUM(amount) 
FROM raffle_tickets 
GROUP BY discord_server_id;

-- Check watchtime per server
SELECT discord_server_id, COUNT(*) 
FROM raffle_watchtime_converted 
GROUP BY discord_server_id;
```

## 🔍 Step 4: Verify Database Isolation

### Connect to Bot-Testing Database

```powershell
cd "c:\Users\linus\Desktop\Admin-Dashboard"
railway link
# Select: Discord bot > Bot-testing > postgres
railway connect postgres
```

### Run Verification Queries

```sql
-- 1. Check that all tables have discord_server_id column
SELECT column_name, data_type 
FROM information_schema.columns 
WHERE table_name LIKE 'raffle_%' AND column_name = 'discord_server_id';

-- 2. Verify indices exist
SELECT indexname 
FROM pg_indexes 
WHERE tablename LIKE 'raffle_%' AND indexname LIKE '%discord_server_id%';

-- 3. Check data distribution
SELECT 
    'raffle_periods' as table_name, discord_server_id, COUNT(*) 
FROM raffle_periods GROUP BY discord_server_id
UNION ALL
SELECT 
    'raffle_tickets', discord_server_id, COUNT(*) 
FROM raffle_tickets GROUP BY discord_server_id
UNION ALL
SELECT 
    'raffle_entries', discord_server_id, COUNT(*) 
FROM raffle_entries GROUP BY discord_server_id;

-- 4. Verify production data is intact (should all be server 914986636629143562)
SELECT discord_server_id, COUNT(*) 
FROM raffle_tickets 
WHERE discord_server_id = 914986636629143562;
```

## 📊 Step 5: Monitor Logs

### Watch Railway Logs

```powershell
railway logs
```

Look for:
- ✅ `[Server 1444335288599187459]` prefixes in logs
- ✅ `[Server 1444335540945031221]` prefixes in logs
- ✅ `[Server 1444335793622614149]` prefixes in logs
- ✅ Background tasks mentioning "Processing guild XXXXXX"
- ❌ No errors about missing discord_server_id

### Key Log Messages to Look For

**Scheduler**:
```
[Server 1444335288599187459] Checking raffle period transition...
[Server 1444335540945031221] Checking raffle period transition...
```

**Watchtime Converter**:
```
[Server 1444335288599187459] Converting watchtime to tickets...
[Server 1444335540945031221] Converting watchtime to tickets...
```

**Shuffle Tracker**:
```
[Server 1444335288599187459] Processing shuffle wagers...
[Server 1444335540945031221] Processing shuffle wagers...
```

## ✅ Success Criteria

All tests pass if:
- ✅ Each server shows independent raffle periods
- ✅ Tickets given in one server don't appear in other servers
- ✅ Settings can be changed independently per server
- ✅ Leaderboards show only their server's participants
- ✅ Database queries show data properly separated by discord_server_id
- ✅ Logs show per-server processing with correct guild IDs
- ✅ No errors in Railway logs
- ✅ Production data (server 914986636629143562) remains intact

## 🐛 Troubleshooting

### Bot Not Responding to Commands

1. Check Railway logs for errors
2. Verify bot has correct permissions in test servers
3. Check that bot is online (green status in Discord)
4. Try `!ping` or similar basic command

### Commands Show Wrong Server Data

1. Check logs for which guild_id is being passed
2. Verify database queries are filtering by discord_server_id
3. Query database directly to see what data exists per server

### Background Tasks Not Running

1. Check Railway logs for scheduler/watchtime/shuffle messages
2. Verify bot.guilds contains all 3 test servers
3. Check for any exceptions in setup functions

### Database Connection Issues

1. Verify DATABASE_URL environment variable is set correctly
2. Check Railway postgres service is running
3. Test connection manually using railway connect postgres

## 📝 Test Results Template

After testing, document results:

```markdown
# Test Results - [Date]

## Server 1 (1444335288599187459)
- Raffle Info: [PASS/FAIL] - [notes]
- Tickets: [PASS/FAIL] - [notes]
- Leaderboard: [PASS/FAIL] - [notes]

## Server 2 (1444335540945031221)
- Raffle Info: [PASS/FAIL] - [notes]
- Tickets: [PASS/FAIL] - [notes]
- Leaderboard: [PASS/FAIL] - [notes]

## Server 3 (1444335793622614149)
- Raffle Info: [PASS/FAIL] - [notes]
- Tickets: [PASS/FAIL] - [notes]
- Leaderboard: [PASS/FAIL] - [notes]

## Database Isolation
- Query Results: [PASS/FAIL] - [notes]
- Data Integrity: [PASS/FAIL] - [notes]

## Background Tasks
- Scheduler: [PASS/FAIL] - [notes]
- Watchtime: [PASS/FAIL] - [notes]
- Shuffle: [PASS/FAIL] - [notes]

## Overall Result: [PASS/FAIL]
```

## 🎉 Next Steps After Successful Testing

Once all tests pass:
1. Begin Phase 3 (Dashboard updates)
2. Prepare production deployment plan
3. Create rollback procedures
4. Schedule production migration window
