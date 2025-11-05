# Multi-Platform Wager Tracking Setup

## Overview

The bot now supports **any gambling platform** with an affiliate stats API (Shuffle, Stake, Stake.us, etc.) via environment variables. Each streamer configures their own platform.

## Environment Variables

Set these in your Railway/Heroku environment:

### Required Variables

```bash
# Platform Configuration
WAGER_PLATFORM_NAME=shuffle          # Platform name (shuffle, stake, stakeus, etc.)
WAGER_AFFILIATE_URL=https://affiliate.shuffle.com/stats/YOUR-UUID-HERE
WAGER_CAMPAIGN_CODE=yourcode         # Your affiliate/referral code
WAGER_TICKETS_PER_1000_USD=20        # Tickets awarded per $1000 wagered
```

### Optional Variables

```bash
WAGER_CHECK_INTERVAL=900             # How often to check for updates (seconds, default: 900 = 15 min)
```

## Platform-Specific Examples

### Shuffle.com

```bash
WAGER_PLATFORM_NAME=shuffle
WAGER_AFFILIATE_URL=https://affiliate.shuffle.com/stats/1755f751-33a9-4532-804e-b14b5c90236b
WAGER_CAMPAIGN_CODE=lele
WAGER_TICKETS_PER_1000_USD=20
```

### Stake.com

```bash
WAGER_PLATFORM_NAME=stake
WAGER_AFFILIATE_URL=https://affiliate.stake.com/stats/YOUR-AFFILIATE-ID
WAGER_CAMPAIGN_CODE=trainwrecks
WAGER_TICKETS_PER_1000_USD=20
```

### Stake.us

```bash
WAGER_PLATFORM_NAME=stakeus
WAGER_AFFILIATE_URL=https://affiliate.stake.us/stats/YOUR-AFFILIATE-ID
WAGER_CAMPAIGN_CODE=yourcode
WAGER_TICKETS_PER_1000_USD=15
```

## How It Works

1. **Bot polls your affiliate URL** every 15 minutes (or your configured interval)
2. **Filters users** using your campaign code
3. **Calculates new wagers** since last check
4. **Awards tickets** to linked users based on `WAGER_TICKETS_PER_1000_USD`

## Finding Your Affiliate URL

### Shuffle.com
1. Go to https://shuffle.com/affiliates
2. View your stats page
3. Copy the full URL (format: `https://affiliate.shuffle.com/stats/UUID`)

### Stake.com
1. Go to your Stake affiliate dashboard
2. Find your stats API endpoint
3. Copy the full URL

## User Linking Process

### For Users:
```
!linkshuffle <platform_username>
```

Example:
```
!linkshuffle CryptoKing420
```

### For Admins:
```
!verifyshuffle @user <platform_username>
```

Example:
```
!verifyshuffle @John CryptoKing420
```

## Backwards Compatibility

Old environment variables still work:
- `SHUFFLE_AFFILIATE_URL` → Automatically used if `WAGER_AFFILIATE_URL` not set
- `SHUFFLE_CAMPAIGN_CODE` → Maps to `WAGER_CAMPAIGN_CODE`
- `SHUFFLE_TICKETS_PER_1000_USD` → Maps to `WAGER_TICKETS_PER_1000_USD`

## Troubleshooting

### No wagers being tracked

1. **Check affiliate URL is correct**
   ```bash
   # Test in browser - should return JSON array
   curl YOUR_AFFILIATE_URL
   ```

2. **Verify campaign code matches**
   - Users must use YOUR exact code when signing up
   - Case-insensitive matching

3. **Check bot logs**
   ```
   Found X users with campaign code 'yourcode' on platform_name
   ```

### Users not earning tickets

1. **Verify user linked their account**
   ```
   !tickets
   ```

2. **Check admin verified the link**
   ```
   !verifyshuffle @user platform_username
   ```

3. **Confirm wagers are above threshold**
   - Need at least $1 in new wagers to earn 1 ticket (at 20 tickets/$1000 rate)

## Migration from Old System

If you were using the hardcoded Shuffle URL:

1. **Add new environment variables** to Railway
2. **Restart the bot** - migration runs automatically
3. **No data loss** - all existing wagers preserved
4. **Platform column added** to database tables

## Security Notes

- ✅ **No API keys required** - Public affiliate stats pages
- ✅ **Read-only access** - Bot only reads data, never modifies
- ✅ **No user credentials** - Users link via username only
- ✅ **Admin verification** - Links require admin approval

## Support

If you encounter issues:
1. Check bot logs for error messages
2. Verify environment variables are set correctly
3. Test affiliate URL in browser
4. Use `!health` command to check bot status
