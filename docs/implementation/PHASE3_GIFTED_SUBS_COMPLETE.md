# ✅ Phase 3 Complete: Gifted Sub Tracking

## What We Built

### Files Created
- ✅ `raffle_system/gifted_sub_tracker.py` - Real-time gifted sub event handler
- ✅ `test_gifted_sub_tracker.py` - Test suite for the tracker

### Files Modified
- ✅ `bot.py` - Added gifted sub event detection in `kick_chat_loop()`

## How It Works

### Real-Time Event Processing

The `GiftedSubTracker` listens to Kick websocket events and:

1. **Detects gifted sub events** - Monitors multiple event types that could indicate gifts
2. **Extracts event details** - Parses sender username and gift count
3. **Prevents duplicates** - Checks `kick_event_id` to avoid double-processing
4. **Looks up Discord account** - Joins with `links` table for Discord ↔ Kick mapping
5. **Awards tickets immediately** - 1 sub = 15 tickets (configurable)
6. **Logs everything** - Records in `raffle_gifted_subs` and `raffle_ticket_log`

### Example Flow

```
🎁 Event received from Kick websocket:
{
  "event": "App\\Events\\GiftedSubscriptionsEvent",
  "data": {
    "id": "event_12345",
    "sender": {"username": "generous_viewer"},
    "gift_count": 5
  }
}

Processing:
1. Check if event_12345 already processed → No
2. Look up generous_viewer in links table → Discord ID: 123456
3. Calculate tickets: 5 × 15 = 75 tickets
4. Award 75 tickets to Discord ID 123456
5. Log in raffle_gifted_subs (with event_id)
6. Log in raffle_ticket_log (audit trail)
7. Print: "🎁 generous_viewer gifted 5 sub(s) → +75 tickets"

Result:
✅ User gets 75 tickets instantly
✅ Event logged to prevent re-processing
✅ Full audit trail maintained
```

### Kick Event Types Monitored

The tracker watches for multiple event types to catch different formats:

```python
event_types = [
    "App\\Events\\GiftedSubscriptionsEvent",  # Primary gifted sub event
    "App\\Events\\SubscriptionEvent",         # General subscription events
    "App\\Events\\ChatMessageEvent"            # Sometimes gifts appear as special messages
]
```

Within these events, it checks for:
- `gift_count` field
- `gifted_usernames` array
- Message type containing "gift" or "subscription"

### Key Features

✅ **Immediate awarding** - Tickets granted in real-time (not hourly like watchtime)
✅ **Duplicate prevention** - Uses `kick_event_id` to prevent double-processing
✅ **Multi-gift support** - Handles single gifts and mass gifts (e.g., 5 subs)
✅ **Linked users only** - Requires Discord ↔ Kick account linking
✅ **Unlinked tracking** - Logs unlinked gifts (0 tickets) for later manual award
✅ **Full audit trail** - Every gift logged in `raffle_ticket_log`

## Integration with Bot

The gifted sub tracker is now integrated into your Kick websocket listener:

```python
# In kick_chat_loop() websocket message handler
if event_type in ["GiftedSubscriptionsEvent", "SubscriptionEvent", "ChatMessageEvent"]:
    if is_gift and gifted_sub_tracker:
        result = await gifted_sub_tracker.handle_gifted_sub_event(event_data)

        if result['status'] == 'success':
            print(f"[Raffle] 🎁 {result['gifter']} gifted {result['gift_count']} sub(s) → +{result['tickets_awarded']} tickets")
```

## Configuration

From `raffle_system/config.py`:

```python
GIFTED_SUB_TICKETS = 15  # 1 gifted sub = 15 tickets
```

You can adjust this value to change the reward rate for gifted subs.

## Testing

Run the test suite:
```bash
python test_gifted_sub_tracker.py
```

Test results:
- ✅ Single gift: 1 sub → 15 tickets
- ✅ Multi-gift: 5 subs → 75 tickets
- ✅ Duplicate prevention: Same event ID ignored
- ✅ Unlinked user: Event logged but 0 tickets
- ✅ Multiple gifts same user: Tickets accumulate
- ✅ Audit trail: All events in raffle_ticket_log

## Database Tables Used

### Read From:
- `links` - Discord ↔ Kick account mappings
- `raffle_periods` - Current active period
- `raffle_gifted_subs` - Check for duplicate event IDs

### Write To:
- `raffle_tickets` - User ticket balances (gifted_sub_tickets column)
- `raffle_gifted_subs` - Log all gifted sub events
- `raffle_ticket_log` - Audit trail of all ticket changes

## Unlinked User Handling

When someone who hasn't linked their account gifts subs:
- ✅ Event is logged in `raffle_gifted_subs` with `gifter_discord_id = NULL`
- ✅ `tickets_awarded = 0` (no tickets given)
- ✅ Admin can manually award tickets later if user links their account
- ✅ Prevents abuse (can't claim tickets retroactively without verification)

## Next Steps

The gifted sub tracking is complete and ready for production!

**Phase 4 next:** Shuffle.com Wager Tracking
- Poll Shuffle affiliate API every 15 minutes
- Track wager amount increases per user
- Award tickets: $1000 wagered = 20 tickets
- Link Shuffle usernames to Kick/Discord accounts
