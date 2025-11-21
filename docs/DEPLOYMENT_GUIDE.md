# 🚀 Production Deployment Guide

Complete guide for deploying the Kick Discord Bot with Raffle System to production.

## 📋 Pre-Deployment Checklist

### 1. Security Verification
Run the automated security checker:
```bash
python tests/verify_system.py
```

Expected output:
```
✅ Security: No exposed secrets
✅ Gifted Sub Tracking: 100% operational
✅ Shuffle Tracking: Configured correctly
🚀 System is production-ready!
```

### 2. Environment Variables

Set these in your hosting platform (Railway, Heroku, Render, etc.):

#### Required Variables
```env
# Discord Bot
DISCORD_TOKEN=your_bot_token
DISCORD_GUILD_ID=your_server_id

# Kick.com Integration
KICK_CHANNEL=your_kick_username

# Database (PostgreSQL)
DATABASE_URL=postgresql://user:password@host:5432/database

# OAuth (Account Linking)
OAUTH_BASE_URL=https://your-app.up.railway.app
KICK_CLIENT_ID=your_kick_client_id
KICK_CLIENT_SECRET=your_kick_client_secret
FLASK_SECRET_KEY=your_flask_secret  # Generate: python -c "import secrets; print(secrets.token_hex(32))"
```

#### Optional Variables
```env
# Raffle System
RAFFLE_AUTO_DRAW=true                    # Auto-draw winner on 1st of month
RAFFLE_ANNOUNCEMENT_CHANNEL_ID=123456    # Discord channel for announcements

# Intervals (default values shown)
WATCH_INTERVAL_SECONDS=60                # Watchtime tracking frequency
ROLE_UPDATE_INTERVAL_SECONDS=600         # Role assignment check frequency
```

### 3. Database Setup

The bot automatically creates tables on first run. To manually initialize:

```bash
python setup_database.py
```

**Database Tables Created:**
- Watchtime tracking: `users`, `links`, `watchtime_roles`
- Raffle system: `raffle_periods`, `raffle_tickets`, `raffle_ticket_log`, `raffle_draws`, `raffle_watchtime_converted`, `raffle_gifted_subs`, `raffle_shuffle_wagers`, `raffle_shuffle_links`

---

## 🐳 Deployment Options

### Option 1: Railway (Recommended)

1. **Fork this repository** to your GitHub account

2. **Create new Railway project**
   - Visit [railway.app](https://railway.app)
   - Click "New Project" → "Deploy from GitHub repo"
   - Select your forked repository

3. **Add PostgreSQL database**
   - In Railway project, click "New" → "Database" → "PostgreSQL"
   - Railway automatically sets `DATABASE_URL`

4. **Configure environment variables**
   - Go to your service → "Variables"
   - Add all required variables from checklist above
   - Railway will auto-deploy on save

5. **Verify deployment**
   - Check logs for "Bot connected as YourBotName"
   - Run `!health` in Discord to verify

### Option 2: Heroku

1. **Install Heroku CLI**
```bash
heroku login
```

2. **Create Heroku app**
```bash
heroku create your-app-name
```

3. **Add PostgreSQL addon**
```bash
heroku addons:create heroku-postgresql:mini
```

4. **Set environment variables**
```bash
heroku config:set DISCORD_TOKEN=your_token
heroku config:set DISCORD_GUILD_ID=your_guild_id
heroku config:set KICK_CHANNEL=your_channel
# ... set all other variables
```

5. **Deploy**
```bash
git push heroku main
```

6. **Scale worker**
```bash
heroku ps:scale worker=1
```

### Option 3: Docker (Self-Hosted)

1. **Build image**
```bash
docker build -t kick-discord-bot .
```

2. **Run container**
```bash
docker run -d \
  -e DISCORD_TOKEN=your_token \
  -e DISCORD_GUILD_ID=your_guild_id \
  -e KICK_CHANNEL=your_channel \
  -e DATABASE_URL=your_database_url \
  # ... add all other env vars
  --name kick-bot \
  kick-discord-bot
```

3. **Using Docker Compose**
```bash
docker-compose up -d
```

---

## ⚙️ Post-Deployment Setup

### 1. Configure Watchtime Roles

In Discord, run these commands (requires Admin):

```
!roles add @Viewer 60        # 1 hour
!roles add @Fan 720          # 12 hours
!roles add @Supporter 4320   # 3 days
!roles add @VIP 21600        # 15 days
```

**Important:** Bot's role must be **above** these roles in Server Settings → Roles!

### 2. Setup OAuth Link Panel

Create reaction-based linking panel:

```
!setup_link_panel 🔗
```

This creates a pinned message users can react to for account linking.

### 3. Enable Link Logging (Optional)

Track all account linking attempts:

```
!linklogs on
```

View logs: Check `link_attempts` table in database or `data/link_attempts.json`

### 4. Test Account Linking

1. React to link panel with 🔗
2. Bot sends DM with OAuth link
3. Click link → Authorize with Kick
4. Verify with `!watchtime`

### 5. Verify Raffle System

Run health check:
```
!health
```

Check raffle status:
```
!raffleinfo
```

---

## 🎟️ Raffle System Configuration

### Ticket Earning Rates

Configured in `raffle_system/config.py`:
- **Watchtime**: 10 tickets per hour
- **Gifted Subs**: 15 tickets per sub
- **Shuffle Wagers**: 20 tickets per $1000 wagered

### Shuffle Integration Setup

1. **User links Shuffle account:**
   ```
   !linkshuffle ShuffleUsername
   ```

2. **Admin verifies in Shuffle dashboard:**
   - Check affiliate stats: https://affiliate.shuffle.com/stats/1755f751-33a9-4532-804e-b14b5c90236b
   - Confirm user has "lele" campaign code
   - Verify wager activity

3. **Admin approves link:**
   ```
   !raffleverify @user
   ```

4. **Tickets awarded automatically** for wagers going forward

### Monthly Draw Process

**Automatic (Recommended):**
- Set `RAFFLE_AUTO_DRAW=true`
- Bot automatically draws winner on 1st of month
- Announces in configured channel

**Manual:**
```
!raffledraw
```

Winner selected using cryptographic randomness (fair drawing).

---

## 📊 Monitoring & Maintenance

### Health Checks

```bash
# Discord command
!health

# Expected output
✅ Bot Status: Online
✅ Kick Connection: Connected
✅ Database: Connected
✅ OAuth Server: Running
✅ Raffle System: Active
```

### Logs to Monitor

- Bot connection: "Bot connected as..."
- Kick websocket: "Connected to Kick chat"
- Gifted subs: "Awarded X tickets to @user (gifted subs)"
- Shuffle wagers: "Updated shuffle wagers for X users"
- Period transitions: "New raffle period started"

### Common Issues

**Bot not tracking watchtime:**
- Verify `KICK_CHANNEL` matches exact Kick username
- Check Kick chat connection in logs
- Ensure users have linked accounts

**Gifted subs not awarding tickets:**
- Check bot logs for "Awarded X tickets" messages
- Verify user has linked Kick → Discord
- Run `!rafflestats` to check database

**Shuffle wagers not tracking:**
- Verify Shuffle URL in `raffle_system/config.py`
- Confirm user's Shuffle link is verified: `!rafflestats`
- Check user has "lele" campaign code

**Roles not assigning:**
- Bot role must be **above** watchtime roles
- Check role configuration: `!roles list`
- Verify bot has "Manage Roles" permission

---

## 🔒 Security Best Practices

### Before Deployment

✅ Run security verification:
```bash
python tests/verify_system.py
```

✅ Verify `.env` is in `.gitignore`

✅ Never commit secrets to git

✅ Use strong `FLASK_SECRET_KEY` (32+ characters)

✅ Rotate secrets periodically

### In Production

✅ Use PostgreSQL (not SQLite)

✅ Enable database backups

✅ Monitor logs for unusual activity

✅ Keep dependencies updated:
```bash
pip install --upgrade -r requirements.txt
```

✅ Review link logs regularly:
```
!linklogs status
```

---

## 📖 Additional Documentation

- **OAuth Setup**: [docs/OAUTH_SETUP.md](docs/OAUTH_SETUP.md)
- **Link Panel Guide**: [docs/LINK_PANEL_QUICKSTART.md](docs/LINK_PANEL_QUICKSTART.md)
- **Raffle Implementation**: [docs/implementation/RAFFLE_SYSTEM_IMPLEMENTATION_PLAN.md](docs/implementation/RAFFLE_SYSTEM_IMPLEMENTATION_PLAN.md)
- **Security Report**: [docs/SECURITY_VERIFICATION_REPORT.md](docs/SECURITY_VERIFICATION_REPORT.md)

---

## 🆘 Support

**Issues?** Check logs first:
```bash
# Railway: View in dashboard
# Heroku: heroku logs --tail
# Docker: docker logs kick-bot
```

**Still stuck?** Open an issue on GitHub with:
- Error messages from logs
- Steps to reproduce
- Environment (Railway/Heroku/Docker)

---

## ✅ Deployment Complete!

Your bot should now be:
- ✅ Tracking watchtime in Kick chat
- ✅ Assigning Discord roles
- ✅ Awarding raffle tickets
- ✅ Ready for monthly draws

**Test everything:**
1. Link an account: React to link panel
2. Check watchtime: `!watchtime`
3. Check tickets: `!tickets`
4. View leaderboard: `!leaderboard`
5. Check raffle info: `!raffleinfo`

**🎉 Congratulations on deploying your Kick Discord Bot!**
