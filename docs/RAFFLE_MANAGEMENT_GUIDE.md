# 🎟️ Raffle Period Management Guide

Quick reference for managing raffle periods.

---

## 📅 Period Management Commands

### Start a New Period

**Default (Current Month)**
```
!rafflestart
```
Creates period from 1st to last day of current month.

**Custom Dates (Same Month)**
```
!rafflestart 1 30
```
Creates period from day 1 to day 30 of current month.

**Specific Dates**
```
!rafflesetdate 2025-11-01 2025-11-30
```
Updates current period to Nov 1-30, 2025.

---

### End Current Period

```
!raffleend
```
- Ends the active raffle period
- Sets status to 'ended'
- Use `!raffledraw` to select winner
- Then `!rafflestart` to begin new period

---

### Reset for Next Month

```
!rafflerestart
```
- Ends current period
- Creates new period for next month (1st to last day)
- Automatically calculates dates
- Reminds you to draw winner from old period

**Example Flow:**
1. October 31st: `!rafflerestart`
2. Old period ends, new period created for Nov 1-30
3. `!raffledraw` to pick winner from October
4. Winners announced, November raffle begins!

---

### Update Period Dates

```
!rafflesetdate 2025-12-01 2025-12-31
```
Changes current active period dates to December 1-31, 2025.

**Format**: `YYYY-MM-DD YYYY-MM-DD` (start end)

---

## 🎯 Common Workflows

### Monthly Reset (Recommended)
```
# End of month
!raffledraw                    # Pick winner
!rafflerestart                 # Start new period
# Announce winner in channel
```

### Custom Period
```
# Start custom period
!rafflestart 15 28             # Day 15-28 of current month

# Or specific dates
!rafflesetdate 2025-11-15 2025-11-28

# End when ready
!raffleend
!raffledraw
```

### Emergency Stop
```
!raffleend                     # Stop ticket accumulation
!rafflestats                   # Review stats
!raffledraw                    # Pick winner if ready
```

---

## 📊 Check Status

**View Current Period**
```
!raffleinfo
```
Shows:
- Period dates
- Total tickets
- Total participants
- Days remaining

**Detailed Stats**
```
!rafflestats                   # Overall stats
!rafflestats @user             # User-specific breakdown
```

---

## ⚠️ Important Notes

### Before Ending a Period
✅ Check stats: `!rafflestats`
✅ Announce to users
✅ Verify all tickets tracked

### After Drawing Winner
✅ Screenshot winner announcement
✅ Contact winner
✅ Start new period
✅ Announce new period dates

### Date Rules
- Start date must be before end date
- Can't have 2 active periods
- End old period before starting new one (unless using `!rafflerestart`)

---

## 🔧 Troubleshooting

**"No active raffle period"**
→ Use `!rafflestart` to create one

**"Already an active period"**
→ Use `!raffleend` first, or `!rafflerestart` to auto-handle

**"Invalid date format"**
→ Use `YYYY-MM-DD` format (e.g., 2025-11-01)

**Need to fix dates?**
→ `!rafflesetdate` updates current period without resetting tickets

---

## 📅 Example Timeline

**Typical Monthly Cycle:**

```
Nov 1, 00:00 UTC  → Period starts (!rafflestart or auto)
Nov 1-30          → Users earn tickets
Nov 30, 23:59 UTC → Period ends (!raffleend or auto)
Dec 1, 00:00 UTC  → Draw winner (!raffledraw)
Dec 1, 00:01 UTC  → New period starts (!rafflestart)
```

**With Auto-Draw Enabled:**
```env
RAFFLE_AUTO_DRAW=true
```
Bot automatically draws winner on 1st of month!

---

## 💡 Pro Tips

1. **Announce Early**: Tell users about raffle dates at start of month
2. **Consistent Schedule**: Same dates each month (1st-last day)
3. **Screenshot Winners**: Keep records of all draws
4. **Use Auto-Draw**: Set `RAFFLE_AUTO_DRAW=true` for hands-free
5. **Check Stats Daily**: Monitor participation with `!rafflestats`

---

## 🎮 Full Command List

| Command | What It Does |
|---------|--------------|
| `!rafflestart` | Start new period (current month) |
| `!rafflestart 1 30` | Start period for days 1-30 |
| `!raffleend` | End current period |
| `!rafflerestart` | End & start new (next month) |
| `!rafflesetdate 2025-11-01 2025-11-30` | Update dates |
| `!raffledraw` | Pick a winner |
| `!raffleinfo` | View current period info |
| `!rafflestats` | View detailed stats |
| `!raffleboard` | View leaderboard |
| `!tickets` | Check your tickets |
