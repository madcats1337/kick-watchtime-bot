# Shuffle Wager Tracking Fix

## Problem
Shuffle wager raffle tickets are not being awarded to users because the `setup_shuffle_tracker()` function is never being called during bot initialization.

## Solution
The shuffle tracker polling task exists (`raffle_system/shuffle_tracker.py`) but needs to be activated during bot startup.

## How to Fix

Add this code to `bot.py` during bot initialization (in the `on_ready` event or similar):

```python
from raffle_system import setup_shuffle_tracker

# In your on_ready event or bot setup:
@bot.event
async def on_ready():
    print(f'Bot logged in as {bot.user}')
    
    # ... existing setup code ...
    
    # CRITICAL: Start shuffle wager polling (runs every 15 minutes)
    # Do this for each guild/server the bot is in
    for guild in bot.guilds:
        try:
            shuffle_tracker = await setup_shuffle_tracker(bot, engine, server_id=guild.id)
            print(f"✅ Shuffle tracker started for guild: {guild.name}")
        except Exception as e:
            print(f"⚠️ Failed to start shuffle tracker for {guild.name}: {e}")
```

## What This Does

1. **Polls affiliate API every 15 minutes** - Fetches latest wager data from configured affiliate URL
2. **Filters by campaign code** - Only tracks wagers using your code (e.g., 'lele')
3. **Calculates delta** - Compares current wager vs last known wager
4. **Awards tickets** - Gives raffle tickets based on `WAGER_TICKETS_PER_1000_USD` setting (default: 20 tickets per $1000 wagered)
5. **Logs activity** - Records all ticket awards in raffle_ticket_log table

## Configuration

Make sure these environment variables are set in Railway:

```bash
WAGER_AFFILIATE_URL=https://affiliate.shuffle.com/stats/YOUR-UUID-HERE
WAGER_CAMPAIGN_CODE=lele
WAGER_TICKETS_PER_1000_USD=20
```

Or they can be stored in the `bot_settings` database table per server.

## Verification

After fixing, you should see in the logs every 15 minutes:

```
[Shuffle Tracker] 🔄 Checking wagers...
[Shuffle Tracker] ✅ Updated X wager(s)
💰 username (shuffle_user): $123.45 wagered → 2 tickets
```

## Current Status

- ✅ Shuffle tracker code exists and is functional
- ✅ Database schema is correct (raffle_shuffle_wagers, raffle_shuffle_links)
- ✅ Polling task is defined (runs every 15 minutes)
- ❌ **Task is never started** - needs `setup_shuffle_tracker()` call
- ❌ Users not receiving tickets because polling never runs

## Files Modified

- `raffle_system/__init__.py` - Exported `setup_shuffle_tracker` for easy import
