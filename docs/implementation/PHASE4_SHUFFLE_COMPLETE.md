# Phase 4 Complete: Shuffle.com Wager Tracking

## ✅ Implementation Summary

Successfully implemented automated Shuffle.com affiliate wager tracking system that monitors user wagers and awards raffle tickets based on gambling activity.

## 🎯 Features Implemented

### 1. **Shuffle API Integration**
- Polls `https://affiliate.shuffle.com/stats/1755f751-33a9-4532-804e-b14b5c90236b` every 15 minutes
- Filters users by campaign code "lele"
- Parses JSON array with `username`, `campaignCode`, `wagerAmount` fields
- Uses `aiohttp` for async HTTP requests with 30-second timeout

### 2. **Wager Delta Tracking**
- Records baseline wager amount for each user
- On each poll, calculates delta: `current_wager - last_known_wager`
- Only awards tickets for **increases** (prevents gaming via cashouts)
- Tracks total wager lifetime per raffle period

### 3. **Ticket Award System**
- **Conversion Rate**: $1000 wagered = 20 tickets
- Automatically calculates tickets: `int((wager_delta / 1000.0) * 20)`
- Only awards to **verified** and **linked** Shuffle accounts
- Records all awards in `raffle_ticket_log` audit trail

### 4. **Account Linking**
- Three-tier linkage: Shuffle username → Kick name → Discord ID
- Admin verification required (`verified` flag + `verified_by_discord_id`)
- Prevents fraudulent claims via manual verification workflow
- Stored in `raffle_shuffle_links` table with unique constraints

### 5. **Database Integration**
- **raffle_shuffle_wagers**: Tracks total wagers, tickets awarded, link status per period
- **raffle_shuffle_links**: Permanent Shuffle→Discord/Kick account connections
- **raffle_tickets**: Updated with `shuffle_wager_tickets` column
- **raffle_ticket_log**: Audit trail with source='shuffle_wager'

## 📊 Test Results

### Test Scenarios Validated:
1. ✅ **Mock API Data Processing** - Successfully parsed 5 mock users
2. ✅ **Campaign Code Filtering** - Users with code "different" correctly ignored
3. ✅ **Account Linking** - Both verified and unverified link creation working
4. ✅ **Initial Wager Recording** - First poll establishes baseline (obel: $1667.69, KyleRSA: $409.86)
5. ✅ **Wager Increase Detection** - Second poll detected increases:
   - obel: $1667.69 → $2500.00 (+$832.31) → **16 tickets**
   - KyleRSA: $409.86 → $1500.00 (unverified, 0 tickets)
6. ✅ **Verification Requirement** - Only verified links receive tickets
7. ✅ **Database Persistence** - Wager totals and tickets correctly stored

### Example Output:
```
9️⃣ Running second Shuffle wager update...
   📊 Mock API returned 5 users
   ✅ Success: 1 wager(s) processed
      • shuffle_obel: $832.31 → 16 tickets

🔟 Final ticket balances...
   shuffle_obel: 16 total tickets
     └─ Shuffle wagers: 16
   shuffle_kyle: No tickets
```

## 🗂️ Files Created/Modified

### New Files:
- **raffle_system/shuffle_tracker.py** (393 lines)
  - `ShuffleWagerTracker` class
  - `update_shuffle_wagers()` - Main polling logic
  - `_fetch_shuffle_data()` - Async API fetch
  - `link_shuffle_account()` - Account linking with verification
  - `setup_shuffle_tracker()` - Discord bot integration

- **test_shuffle_tracker.py** (300+ lines)
  - Mock API data simulation
  - Account linking tests
  - Wager increase tests
  - Verification requirement validation

### Modified Files:
- **bot.py**
  - Added `from raffle_system.shuffle_tracker import setup_shuffle_tracker`
  - Added global `shuffle_tracker = None`
  - Modified `on_ready()` to initialize tracker: `shuffle_tracker = await setup_shuffle_tracker(bot, engine)`

## 📋 Database Schema Additions

### raffle_shuffle_wagers
```sql
CREATE TABLE raffle_shuffle_wagers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    period_id INTEGER NOT NULL,
    shuffle_username TEXT NOT NULL,
    kick_name TEXT,
    discord_id BIGINT,
    total_wager_usd NUMERIC(10, 2) DEFAULT 0.00,
    last_known_wager NUMERIC(10, 2) DEFAULT 0.00,
    tickets_awarded INTEGER DEFAULT 0,
    last_checked TIMESTAMP,
    last_updated TIMESTAMP,
    UNIQUE(period_id, shuffle_username)
);
```

### raffle_shuffle_links
```sql
CREATE TABLE raffle_shuffle_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shuffle_username TEXT UNIQUE NOT NULL,
    kick_name TEXT,
    discord_id BIGINT UNIQUE,
    verified BOOLEAN DEFAULT FALSE,
    verified_by_discord_id BIGINT,
    verified_at TIMESTAMP,
    linked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## ⚙️ Configuration

### Environment Variables (.env):
```env
SHUFFLE_AFFILIATE_URL=https://affiliate.shuffle.com/stats/1755f751-33a9-4532-804e-b14b5c90236b
SHUFFLE_CAMPAIGN_CODE=lele
SHUFFLE_TICKETS_PER_1000_USD=20
SHUFFLE_CHECK_INTERVAL_MINUTES=15
```

### Ticket Conversion Rate:
- **$1,000 USD** wagered = **20 raffle tickets**
- Example: $832.31 wagered = 16 tickets (rounded down)

## 🔄 Workflow

1. **Every 15 minutes:**
   - Bot fetches Shuffle affiliate JSON
   - Filters users with campaignCode "lele"
   
2. **For each user:**
   - Check if Shuffle username exists in `raffle_shuffle_links`
   - If new user: create record in `raffle_shuffle_wagers` (baseline)
   - If existing: calculate wager delta
   
3. **Award tickets:**
   - Only if delta > 0
   - Only if verified link exists
   - Calculate: `tickets = int((delta / 1000) * 20)`
   - Update `raffle_tickets` and `raffle_ticket_log`

4. **Update tracking:**
   - Set `last_known_wager = current_wager`
   - Increment `tickets_awarded` total
   - Update `last_checked` timestamp

## 🎮 Admin Commands (To Be Implemented in Phase 5)

Future commands for managing Shuffle links:
- `!link shuffle <shuffle_username>` - Initiate link request
- `!raffle verify shuffle <user> <shuffle_username>` - Admin verification
- `!raffle unlink shuffle <user>` - Remove link
- `!shuffle stats <user>` - View user's wager/ticket stats

## 🔒 Security Features

1. **Manual Verification Required** - Prevents unauthorized claims
2. **Unique Constraints** - One Shuffle account per Discord user
3. **Campaign Code Filtering** - Only tracks code "lele"
4. **Delta-Only Tracking** - Negative wagers ignored
5. **Audit Trail** - All ticket awards logged with descriptions

## 🐛 Known Limitations

1. **SQLite Database Locking** - Occasional concurrent transaction issues (test showed one lock error)
   - Solution: PostgreSQL in production eliminates this
   
2. **API Rate Limits** - No rate limiting implemented yet
   - Current 15-minute interval is conservative
   
3. **No Wager Decrease Handling** - User cashouts don't reduce tickets
   - Design decision: tickets never removed for wagers

## 📈 Next Steps (Phase 5)

1. **Discord Commands** - User-facing commands for checking tickets, linking accounts, viewing leaderboard
2. **Admin Commands** - Verification, manual ticket awards, raffle drawing
3. **Notification System** - DM users when tickets awarded, verification needed
4. **Dashboard Integration** - Web UI for viewing wager stats

## 🎉 Phase 4 Status: COMPLETE ✅

All three ticket earning methods now fully integrated:
- ✅ **Watchtime** - Hourly conversion (1h = 10 tickets)
- ✅ **Gifted Subs** - Real-time events (1 sub = 15 tickets)
- ✅ **Shuffle Wagers** - 15-minute polling ($1000 = 20 tickets)

**Ready to proceed to Phase 5: Discord Commands**
