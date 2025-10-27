# 🎟️ RAFFLE SYSTEM IMPLEMENTATION PLAN
## Complete architecture for monthly raffle ticket system

---

## 🎯 CORE FEATURES

### 1. Chat Activity Tracking → Tickets
- **Already exists**: Watchtime tracking in `watchtime` table
- **Conversion rate**: 60 minutes = 10 tickets (1 hour)
- **Update frequency**: Every hour, convert accumulated watchtime to tickets

### 2. Gifted Subs → Tickets
- **Event source**: Kick websocket gifted sub events
- **Conversion rate**: 1 gifted sub = 15 tickets
- **Tracking**: Store each gift in database with timestamp

### 3. Shuffle.com Affiliate Wagers → Tickets
- **Data source**: https://affiliate.shuffle.com/stats/1755f751-33a9-4532-804e-b14b5c90236b
- **Conversion rate**: $1000 wagered = 20 tickets
- **Update frequency**: Poll every 15 minutes
- **Tracking**: Track per-user cumulative wager for the month

### 4. Monthly Reset
- **Schedule**: 1st of every month at 00:00 UTC
- **Actions**: Archive old data, reset ticket counts, start fresh raffle period

---

## 📊 DATABASE SCHEMA

### New Tables

```sql
-- Monthly raffle periods
CREATE TABLE raffle_periods (
    id SERIAL PRIMARY KEY,
    start_date TIMESTAMP NOT NULL,
    end_date TIMESTAMP NOT NULL,
    status VARCHAR(20) DEFAULT 'active',  -- active, ended, archived
    winner_discord_id BIGINT,
    winner_kick_name TEXT,
    winning_ticket_number INTEGER,
    total_tickets INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- User ticket balances (resets monthly)
CREATE TABLE raffle_tickets (
    id SERIAL PRIMARY KEY,
    period_id INTEGER REFERENCES raffle_periods(id),
    discord_id BIGINT NOT NULL,
    kick_name TEXT NOT NULL,
    
    -- Ticket sources
    watchtime_tickets INTEGER DEFAULT 0,
    gifted_sub_tickets INTEGER DEFAULT 0,
    shuffle_wager_tickets INTEGER DEFAULT 0,
    bonus_tickets INTEGER DEFAULT 0,  -- Manual admin awards
    
    -- Totals
    total_tickets INTEGER DEFAULT 0,
    
    -- Metadata
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(period_id, discord_id)
);

-- Watchtime conversion tracking (prevent double-counting)
CREATE TABLE raffle_watchtime_converted (
    id SERIAL PRIMARY KEY,
    period_id INTEGER REFERENCES raffle_periods(id),
    kick_name TEXT NOT NULL,
    minutes_converted INTEGER NOT NULL,
    tickets_awarded INTEGER NOT NULL,
    converted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Gifted sub event log
CREATE TABLE raffle_gifted_subs (
    id SERIAL PRIMARY KEY,
    period_id INTEGER REFERENCES raffle_periods(id),
    gifter_kick_name TEXT NOT NULL,
    gifter_discord_id BIGINT,  -- NULL if not linked
    recipient_kick_name TEXT NOT NULL,
    sub_count INTEGER DEFAULT 1,  -- For multi-gifts
    tickets_awarded INTEGER NOT NULL,
    gifted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    kick_event_id TEXT UNIQUE  -- Prevent duplicate processing
);

-- Shuffle.com wager tracking
CREATE TABLE raffle_shuffle_wagers (
    id SERIAL PRIMARY KEY,
    period_id INTEGER REFERENCES raffle_periods(id),
    shuffle_username TEXT NOT NULL,
    kick_name TEXT,  -- If we can map shuffle→kick
    discord_id BIGINT,  -- NULL if not linked
    
    -- Wager tracking
    total_wager_usd DECIMAL(15, 2) DEFAULT 0,
    last_known_wager DECIMAL(15, 2) DEFAULT 0,
    tickets_awarded INTEGER DEFAULT 0,
    
    -- Metadata
    last_checked TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Shuffle username → Kick/Discord mapping
CREATE TABLE raffle_shuffle_links (
    id SERIAL PRIMARY KEY,
    shuffle_username TEXT NOT NULL UNIQUE,
    kick_name TEXT NOT NULL,
    discord_id BIGINT NOT NULL,
    linked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    verified BOOLEAN DEFAULT FALSE  -- Admin verification
);

-- Ticket transaction log (audit trail)
CREATE TABLE raffle_ticket_log (
    id SERIAL PRIMARY KEY,
    period_id INTEGER REFERENCES raffle_periods(id),
    discord_id BIGINT NOT NULL,
    kick_name TEXT NOT NULL,
    ticket_change INTEGER NOT NULL,  -- +10, +15, etc.
    source VARCHAR(50) NOT NULL,  -- 'watchtime', 'gifted_sub', 'shuffle_wager', 'bonus', 'reset'
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Raffle draw history
CREATE TABLE raffle_draws (
    id SERIAL PRIMARY KEY,
    period_id INTEGER REFERENCES raffle_periods(id) UNIQUE,
    total_tickets INTEGER NOT NULL,
    total_participants INTEGER NOT NULL,
    winner_discord_id BIGINT NOT NULL,
    winner_kick_name TEXT NOT NULL,
    winner_shuffle_name TEXT,
    winning_ticket INTEGER NOT NULL,
    prize_description TEXT,
    drawn_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    drawn_by_discord_id BIGINT  -- Admin who triggered draw
);

-- Indices for performance
CREATE INDEX idx_raffle_tickets_period ON raffle_tickets(period_id);
CREATE INDEX idx_raffle_tickets_discord ON raffle_tickets(discord_id);
CREATE INDEX idx_raffle_ticket_log_period ON raffle_ticket_log(period_id);
CREATE INDEX idx_raffle_gifted_subs_period ON raffle_gifted_subs(period_id);
CREATE INDEX idx_raffle_shuffle_period ON raffle_shuffle_wagers(period_id);
```

### Database Views (for easy querying)

```sql
-- Leaderboard view
CREATE VIEW raffle_leaderboard AS
SELECT 
    rt.period_id,
    rt.discord_id,
    rt.kick_name,
    rt.total_tickets,
    rt.watchtime_tickets,
    rt.gifted_sub_tickets,
    rt.shuffle_wager_tickets,
    rt.bonus_tickets,
    RANK() OVER (PARTITION BY rt.period_id ORDER BY rt.total_tickets DESC) as rank
FROM raffle_tickets rt
WHERE rt.total_tickets > 0
ORDER BY rt.period_id DESC, rt.total_tickets DESC;

-- Current period stats
CREATE VIEW raffle_current_stats AS
SELECT 
    rp.id as period_id,
    rp.start_date,
    rp.end_date,
    rp.status,
    COUNT(DISTINCT rt.discord_id) as total_participants,
    COALESCE(SUM(rt.total_tickets), 0) as total_tickets,
    COALESCE(SUM(rt.watchtime_tickets), 0) as watchtime_tickets,
    COALESCE(SUM(rt.gifted_sub_tickets), 0) as gifted_sub_tickets,
    COALESCE(SUM(rt.shuffle_wager_tickets), 0) as shuffle_wager_tickets,
    COALESCE(SUM(rt.bonus_tickets), 0) as bonus_tickets
FROM raffle_periods rp
LEFT JOIN raffle_tickets rt ON rt.period_id = rp.id
WHERE rp.status = 'active'
GROUP BY rp.id;
```

---

## 🏗️ SYSTEM ARCHITECTURE

### New Python Modules

```
raffle_system/
├── __init__.py
├── config.py              # Raffle configuration (rates, schedules)
├── database.py            # Schema setup and migrations
├── tickets.py             # Core ticket management logic
├── watchtime_converter.py # Convert watchtime → tickets
├── gifted_sub_tracker.py  # Listen for Kick gifted subs
├── shuffle_tracker.py     # Poll Shuffle.com affiliate API
├── raffle_commands.py     # Discord commands (!tickets, !raffle, etc.)
├── scheduler.py           # Monthly reset and periodic tasks
└── draw.py                # Raffle drawing logic
```

### Integration Points

**bot.py changes:**
```python
# Import raffle system
from raffle_system import setup_raffle_system, raffle_commands

# In on_ready()
await setup_raffle_system(bot, engine)

# Add raffle commands
bot.add_cog(raffle_commands.RaffleCog(bot, engine))
```

**Existing systems to leverage:**
- ✅ Watchtime tracking (already running every 60s)
- ✅ Kick websocket listener (add gifted sub handler)
- ✅ Discord bot framework (add raffle commands)
- ✅ PostgreSQL database (add raffle tables)
- ✅ Account linking (`links` table for Discord↔Kick)

---

## 🔄 TICKET EARNING WORKFLOWS

### Workflow 1: Watchtime → Tickets

```
[Existing watchtime updater runs every 60s]
   ↓
[New: Every 60 minutes, raffle_watchtime_converter runs]
   ↓
1. Query watchtime table for all users
2. Check raffle_watchtime_converted to see what's been counted
3. Calculate new minutes since last conversion
4. Convert: minutes / 60 * 10 = tickets
5. Update raffle_tickets (watchtime_tickets += tickets)
6. Log in raffle_watchtime_converted
7. Log in raffle_ticket_log
```

**Example:**
```
User "viewer123" has 185 minutes watchtime
Last conversion was at 120 minutes
New minutes: 185 - 120 = 65 minutes
Tickets: 65 / 60 * 10 = 10.83 → 10 tickets (floor)
Award 10 tickets, mark 180 minutes as converted (60*3)
```

### Workflow 2: Gifted Subs → Tickets

```
[Kick websocket receives "ChatMessageEvent"]
   ↓
[Check if event type is "gift_subscription"]
   ↓
1. Extract gifter username and gift count
2. Check kick_event_id to prevent duplicates
3. Look up gifter Discord ID from links table
4. Calculate tickets: gift_count * 15
5. Insert into raffle_gifted_subs
6. Update raffle_tickets (gifted_sub_tickets += tickets)
7. Log in raffle_ticket_log
8. Send Discord notification: "🎁 @user earned 15 tickets for gifting a sub!"
```

**Kick websocket event example:**
```json
{
  "event": "ChatMessageEvent",
  "data": {
    "id": "abc123...",
    "type": "gift_subscription",
    "sender": {
      "username": "generous_viewer"
    },
    "metadata": {
      "gift_count": 5
    }
  }
}
```

### Workflow 3: Shuffle.com Wagers → Tickets

```
[Scheduler runs shuffle_tracker every 15 minutes]
   ↓
1. Fetch https://affiliate.shuffle.com/stats/1755f751-33a9-4532-804e-b14b5c90236b
2. Parse JSON array of {username, campaignCode, wagerAmount}
3. Filter for campaignCode === "lele"
4. For each user:
   a. Check raffle_shuffle_links to map shuffle→kick/discord
   b. Compare new wagerAmount vs last_known_wager
   c. Calculate new wager delta: wagerAmount - last_known_wager
   d. Calculate tickets: (delta / 1000) * 20
   e. Update raffle_shuffle_wagers (total_wager_usd, tickets_awarded)
   f. Update raffle_tickets (shuffle_wager_tickets += new_tickets)
   g. Log in raffle_ticket_log
5. Send Discord notification for significant tickets (>20)
```

**Example:**
```
User "obel" (Shuffle) → linked to "obel_kick" (Kick) → Discord ID 123456
Last known wager: $1667.69
New wager: $2100.00
Delta: $432.31
Tickets: (432.31 / 1000) * 20 = 8.64 → 8 tickets
Award 8 tickets, update last_known_wager to $2100.00
```

---

## 🗓️ MONTHLY RESET WORKFLOW

```
[Scheduler detects 1st of month at 00:00 UTC]
   ↓
1. Get current active raffle_period
2. Set status = 'ended'
3. Optionally: Trigger raffle draw (or manual admin draw)
4. Create new raffle_period:
   - start_date = 1st of month 00:00 UTC
   - end_date = Last day of month 23:59 UTC
   - status = 'active'
5. Clear raffle_tickets for new period (CASCADE will handle)
6. Archive old data (optional: move to raffle_archive table)
7. Send Discord announcement:
   "🎟️ NEW RAFFLE PERIOD STARTED!
   Last month's winner: @user (1,234 tickets)
   Start earning tickets for this month!"
```

**Important**: Don't delete old data! Keep for:
- Winner verification
- Stats/analytics
- Dispute resolution

---

## 🎲 RAFFLE DRAW LOGIC

### Fair Random Draw Algorithm

```python
import random
import secrets

def draw_winner(period_id: int, engine):
    """
    Provably fair raffle draw using cryptographic randomness.
    Each ticket is a numbered entry; higher tickets = higher chance.
    """
    # Get all participants and ticket counts
    result = engine.execute(text("""
        SELECT discord_id, kick_name, total_tickets
        FROM raffle_tickets
        WHERE period_id = :period_id AND total_tickets > 0
        ORDER BY id
    """), {"period_id": period_id})
    
    participants = list(result)
    if not participants:
        return None  # No entries
    
    # Build ticket number ranges
    # User A: 10 tickets → tickets 1-10
    # User B: 25 tickets → tickets 11-35
    # User C: 5 tickets → tickets 36-40
    ticket_ranges = []
    current_ticket = 1
    
    for discord_id, kick_name, ticket_count in participants:
        ticket_ranges.append({
            'discord_id': discord_id,
            'kick_name': kick_name,
            'ticket_count': ticket_count,
            'start_ticket': current_ticket,
            'end_ticket': current_ticket + ticket_count - 1
        })
        current_ticket += ticket_count
    
    total_tickets = current_ticket - 1
    
    # Draw winning ticket using cryptographic randomness
    winning_ticket = secrets.randbelow(total_tickets) + 1
    
    # Find winner
    for entry in ticket_ranges:
        if entry['start_ticket'] <= winning_ticket <= entry['end_ticket']:
            return {
                'winner_discord_id': entry['discord_id'],
                'winner_kick_name': entry['kick_name'],
                'winning_ticket': winning_ticket,
                'total_tickets': total_tickets,
                'total_participants': len(participants)
            }
    
    return None  # Should never happen
```

### Draw Announcement

```
🎉 RAFFLE WINNER ANNOUNCEMENT 🎉

Congratulations to @winner!

📊 Draw Statistics:
• Total Tickets: 15,432
• Total Participants: 287
• Winning Ticket: #8,721

🎟️ Winner's Tickets:
• Watchtime: 120 tickets
• Gifted Subs: 45 tickets
• Shuffle Wagers: 83 tickets
• Total: 248 tickets

📈 Winner's Odds: 248/15,432 (1.6%)

Prize: $500 Cash / 500,000 Kick Points

Next raffle starts now! Start earning tickets! 🎰
```

---

## 💬 DISCORD COMMANDS

### User Commands

```
!tickets
- Show your current ticket balance with breakdown

!tickets @user
- Check another user's tickets (public)

!leaderboard [top]
- Show top 10 ticket holders (default)
- Optional: !leaderboard 25

!raffle info
- Show current raffle period details
- Total tickets, participants, end date

!raffle history
- Show past 5 raffle winners

!link shuffle <username>
- Link your Shuffle.com username to earn wager tickets
- Requires admin verification to prevent abuse
```

### Admin Commands

```
!raffle draw
- Manually trigger raffle draw for current period
- Announces winner
- Ends current period

!raffle reset
- Force start new raffle period
- Archives current period

!raffle stats
- Detailed statistics dashboard
- Tickets by source, top earners, projections

!raffle give <@user> <tickets> [reason]
- Award bonus tickets manually
- Example: !raffle give @user 50 Won community event

!raffle remove <@user> <tickets> [reason]
- Remove tickets (for violations)
- Example: !raffle remove @user 100 TOS violation

!raffle verify shuffle <shuffle_user> <kick_user>
- Admin verify Shuffle→Kick link
- Prevents fraudulent linking
```

---

## ⚙️ CONFIGURATION

### raffle_system/config.py

```python
# Ticket conversion rates
WATCHTIME_TICKETS_PER_HOUR = 10      # 1 hour = 10 tickets
GIFTED_SUB_TICKETS = 15              # 1 sub = 15 tickets
SHUFFLE_TICKETS_PER_1000_USD = 20    # $1000 = 20 tickets

# Update intervals
WATCHTIME_CONVERSION_INTERVAL = 3600  # 1 hour (seconds)
SHUFFLE_CHECK_INTERVAL = 900          # 15 minutes (seconds)

# Shuffle.com configuration
SHUFFLE_AFFILIATE_URL = "https://affiliate.shuffle.com/stats/1755f751-33a9-4532-804e-b14b5c90236b"
SHUFFLE_CAMPAIGN_CODE = "lele"

# Monthly reset
RESET_DAY_OF_MONTH = 1  # 1st
RESET_HOUR_UTC = 0      # 00:00 UTC

# Raffle settings
MINIMUM_TICKETS_TO_ENTER = 1
AUTO_DRAW_ON_RESET = False  # Manual draw by default

# Notifications
RAFFLE_ANNOUNCEMENT_CHANNEL_ID = None  # Set in .env
TICKET_NOTIFICATION_THRESHOLD = 20     # Only notify for 20+ tickets at once
```

### Environment Variables (.env)

```env
# Existing variables
DISCORD_TOKEN=...
DATABASE_URL=...

# New raffle variables
RAFFLE_ANNOUNCEMENT_CHANNEL_ID=1234567890123456789
SHUFFLE_AFFILIATE_URL=https://affiliate.shuffle.com/stats/1755f751-33a9-4532-804e-b14b5c90236b
```

---

## 📅 IMPLEMENTATION TIMELINE

### Phase 1: Database & Core Logic (Week 1)
- [x] Design schema
- [ ] Create migration script (`raffle_system/database.py`)
- [ ] Build ticket management core (`raffle_system/tickets.py`)
- [ ] Implement draw algorithm (`raffle_system/draw.py`)
- [ ] Write unit tests

### Phase 2: Watchtime Integration (Week 1-2)
- [ ] Build watchtime converter (`raffle_system/watchtime_converter.py`)
- [ ] Add hourly task to bot
- [ ] Test conversion logic
- [ ] Add Discord notifications

### Phase 3: Gifted Sub Tracking (Week 2)
- [ ] Identify Kick websocket event format for gifts
- [ ] Implement event handler (`raffle_system/gifted_sub_tracker.py`)
- [ ] Test with live gifted subs
- [ ] Add Discord notifications

### Phase 4: Shuffle.com Integration (Week 2-3)
- [ ] Build Shuffle API poller (`raffle_system/shuffle_tracker.py`)
- [ ] Implement linking system for Shuffle→Kick→Discord
- [ ] Add verification workflow (admin approval)
- [ ] Test with live Shuffle data
- [ ] Add Discord notifications

### Phase 5: Discord Commands (Week 3)
- [ ] Implement user commands (`raffle_system/raffle_commands.py`)
  - !tickets, !leaderboard, !raffle info
- [ ] Implement admin commands
  - !raffle draw, !raffle give, !raffle verify
- [ ] Add embeds with rich formatting
- [ ] Test all commands

### Phase 6: Scheduler & Automation (Week 4)
- [ ] Build scheduler (`raffle_system/scheduler.py`)
- [ ] Implement monthly reset
- [ ] Add automatic draw option
- [ ] Test date transitions
- [ ] Add admin notifications

### Phase 7: Testing & Polish (Week 4)
- [ ] End-to-end integration testing
- [ ] Load testing (simulate 1000+ users)
- [ ] Security audit (prevent cheating)
- [ ] Documentation
- [ ] Deploy to production

---

## 🔒 SECURITY CONSIDERATIONS

### Prevent Cheating

1. **Duplicate Detection**
   - Gifted subs: Store `kick_event_id` to prevent replay
   - Shuffle wagers: Only count increases (never decreases)
   - Watchtime: Track converted minutes to prevent double-counting

2. **Shuffle Link Verification**
   - Require admin approval for Shuffle→Kick links
   - Prevent one Shuffle account linking to multiple Discord accounts
   - Rate limit link requests

3. **Audit Trail**
   - `raffle_ticket_log` records every ticket change
   - Can investigate suspicious activity
   - Admin actions logged with discord_id

4. **Fair Draw**
   - Use `secrets.randbelow()` (cryptographic RNG)
   - Log draw parameters (seed, timestamp)
   - Publicly announce winning ticket number

### Rate Limits

```python
# Prevent spam/abuse
LINK_SHUFFLE_COOLDOWN = 86400  # 24 hours between link attempts
MAX_SHUFFLE_LINKS_PER_USER = 1  # One Shuffle account per Discord user
```

---

## 📊 SAMPLE DATA FLOW

### Example Month (November 2025)

**Week 1:**
- User "viewer123" watches 10 hours → 100 tickets (watchtime)
- Gifts 2 subs → 30 tickets (gifted subs)
- Wagers $500 on Shuffle → 10 tickets (shuffle)
- **Total: 140 tickets**

**Week 2:**
- Watches 8 more hours → 80 tickets
- No gifts
- Wagers another $1200 → 24 tickets
- **Total: 244 tickets**

**Week 3:**
- Watches 12 hours → 120 tickets
- Gifts 1 sub → 15 tickets
- No Shuffle activity
- **Total: 379 tickets**

**Week 4:**
- Watches 5 hours → 50 tickets
- No gifts
- Wagers $300 → 6 tickets
- Admin bonus for event win → 50 tickets
- **Total: 485 tickets**

**End of Month:**
- Total participants: 287
- Total tickets in pool: 15,432
- viewer123's odds: 485/15,432 = 3.14%
- Draw winner: Ticket #8,721 → Another user wins
- viewer123 starts fresh in December with 0 tickets

---

## 🚀 DEPLOYMENT CHECKLIST

### Railway.app Setup

1. **Database Migration**
   ```bash
   railway run python -m raffle_system.database
   ```

2. **Environment Variables**
   - Add `RAFFLE_ANNOUNCEMENT_CHANNEL_ID`
   - Add `SHUFFLE_AFFILIATE_URL`

3. **Cron Jobs** (if using Railway cron)
   - Watchtime conversion: Every hour
   - Shuffle check: Every 15 minutes
   - Monthly reset: 1st of month at 00:00 UTC

4. **Test Data**
   - Create test raffle period
   - Award test tickets
   - Test draw algorithm
   - Verify reset logic

---

## 📈 FUTURE ENHANCEMENTS

### V2 Features (Optional)

1. **Multiple Raffles**
   - Weekly mini-raffles
   - Grand prize monthly raffle
   - Separate ticket pools

2. **Ticket Shop**
   - Spend tickets on perks instead of only raffle entries
   - Custom Discord roles
   - Priority queue for requests

3. **Predictions**
   - Show users their win probability
   - "You need 50 more tickets to reach top 10!"

4. **Social Features**
   - Gift tickets to other users
   - Team competitions

5. **Analytics Dashboard**
   - Web dashboard showing live leaderboard
   - Ticket earning charts
   - Historical raffle data

---

## 🎯 SUCCESS METRICS

Track these metrics to measure engagement:

- **Participation Rate**: % of linked users earning tickets
- **Ticket Sources**: Ratio of watchtime:subs:shuffle tickets
- **Monthly Growth**: Increase in total tickets month-over-month
- **Shuffle Adoption**: % of users linking Shuffle accounts
- **Gift Activity**: Average gifts per user per month

---

## 📞 NEXT STEPS

Ready to start building? I recommend this order:

1. ✅ **Review this plan** - Any changes needed?
2. 🔨 **Create database schema** - Run migration
3. 🎟️ **Build ticket core** - tickets.py + tests
4. ⏱️ **Watchtime integration** - Quick win (leverage existing)
5. 🎁 **Gifted subs** - Medium complexity
6. 🎰 **Shuffle tracking** - Most complex (API + linking)
7. 💬 **Discord commands** - User-facing features
8. 🗓️ **Scheduler** - Automation
9. 🧪 **Testing** - End-to-end validation
10. 🚀 **Deploy** - Production launch

Would you like me to start implementing any specific phase?
