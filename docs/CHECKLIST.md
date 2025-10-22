# 🚀 Pre-Launch Checklist

## 1. Environment Setup ✅

### Required Environment Variables
- [ ] `DISCORD_TOKEN` - Get from [Discord Developer Portal](https://discord.com/developers/applications)
- [ ] `DISCORD_GUILD_ID` - Your Discord server ID (Enable Developer Mode → Right-click server → Copy ID)
- [ ] `KICK_CHANNEL` - Your Kick channel name (without @ or kick.com/)
- [ ] `DATABASE_URL` - PostgreSQL connection string for production

### Optional Environment Variables
- [ ] `WATCH_INTERVAL_SECONDS` (default: 60)
- [ ] `ROLE_UPDATE_INTERVAL_SECONDS` (default: 600)
- [ ] `CODE_EXPIRY_MINUTES` (default: 10)

---

## 2. Discord Bot Configuration ✅

### Create Bot Application
1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Click "New Application"
3. Name your application
4. Go to "Bot" tab → Click "Add Bot"
5. Copy the bot token (save to `DISCORD_TOKEN`)

### Bot Permissions
Enable these intents in Bot settings:
- [ ] Presence Intent
- [ ] Server Members Intent
- [ ] Message Content Intent

### Invite Bot to Server
Use this permission calculator:
- Scopes: `bot`, `applications.commands`
- Bot Permissions:
  - [ ] Manage Roles
  - [ ] Send Messages
  - [ ] Read Message History
  - [ ] View Channels
  - [ ] Use Slash Commands

**Invite URL Format:**
```
https://discord.com/api/oauth2/authorize?client_id=YOUR_CLIENT_ID&permissions=268435456&scope=bot%20applications.commands
```

---

## 3. Discord Server Setup ✅

### Create Watchtime Roles
Create these roles in your Discord server (Settings → Roles):

1. **🎯 Fan** (1 hour)
2. **🔥 Superfan** (5 hours)  
3. **💎 Elite Viewer** (16+ hours)

**Important:** Bot's role must be ABOVE these roles in the hierarchy!

### Verify Role Hierarchy
```
[Bot Role] ← Must be here or higher
🎯 Fan
🔥 Superfan
💎 Elite Viewer
@everyone
```

---

## 4. Database Setup ✅

### Local Development (SQLite)
```bash
python setup_database.py
```

### Production (PostgreSQL)
1. Create PostgreSQL database on your cloud platform
2. Set `DATABASE_URL` environment variable
3. Run database initialization:
   ```bash
   python setup_database.py
   ```
4. Verify with health check:
   ```bash
   python health_check.py
   ```

---

## 5. Dependencies Installation ✅

### Python Requirements
```bash
pip install -r requirements.txt
```

### Playwright Browsers (Required)
```bash
playwright install firefox chromium
playwright install-deps
```

---

## 6. Testing Before Launch ✅

### Test Local Run
```bash
python bot.py
```

### Test Bot Commands
1. **Ping Test**
   ```
   /ping
   ```
   Expected: "Pong! Bot is online."

2. **Link Account**
   ```
   /link kick_username
   ```
   Expected: Verification code displayed

3. **Verify Account**
   ```
   /verify
   ```
   Expected: Account linked successfully

4. **Check Watchtime**
   ```
   /watchtime
   ```
   Expected: Your watchtime displayed

5. **View Leaderboard**
   ```
   /leaderboard
   ```
   Expected: Top 10 viewers list

6. **Admin: Stats**
   ```
   /stats
   ```
   Expected: Bot statistics (requires Manage Roles permission)

7. **Admin: Force Update**
   ```
   /force_update_roles
   ```
   Expected: Roles updated (requires Manage Roles permission)

---

## 7. Cloud Deployment ✅

### Choose Your Platform
- [ ] Railway.app (Recommended - Free tier with database)
- [ ] Heroku (Requires credit card even for free tier)
- [ ] Render.com (Free tier available)
- [ ] DigitalOcean/AWS/GCP (Docker deployment)

### Deployment Steps
See [DEPLOYMENT.md](DEPLOYMENT.md) for detailed platform-specific instructions.

### Post-Deployment Checks
- [ ] Bot shows as online in Discord
- [ ] Database tables created (run `python setup_database.py` on cloud)
- [ ] Health check passes (run `python health_check.py`)
- [ ] Test all commands work
- [ ] Check logs for errors

---

## 8. Security Checklist ✅

- [ ] `.env` file is in `.gitignore`
- [ ] Never commit credentials to Git
- [ ] Database password is strong
- [ ] Bot token is kept secret
- [ ] Enable 2FA on Discord account
- [ ] Enable 2FA on cloud platform account

---

## 9. Monitoring Setup ✅

### Log Monitoring
Check logs regularly for:
- Connection errors
- API rate limits
- Database issues
- Cloudflare blocks

### Platform-Specific
- **Railway**: View logs in project dashboard
- **Heroku**: `heroku logs --tail`
- **Docker**: `docker logs -f <container_id>`

---

## 10. Common Issues & Solutions ✅

### Bot Not Responding
- Check bot is online in Discord
- Verify `DISCORD_TOKEN` is correct
- Ensure intents are enabled
- Check bot has proper permissions

### Database Errors
- Verify `DATABASE_URL` format
- Run `python setup_database.py`
- Check database is accessible
- Run `python health_check.py`

### Watchtime Not Tracking
- Verify `KICK_CHANNEL` name is correct
- Check Kick channel is live
- Review WebSocket connection logs
- Verify Kick API is accessible

### Verification Failing (403)
- Cloudflare is blocking requests
- Playwright uses Firefox first (better bypass)
- May need multiple retry attempts
- Check `/about` page exists on Kick profile

### Roles Not Updating
- Check bot role is above watchtime roles
- Verify bot has "Manage Roles" permission
- Check role names match exactly (including emojis)
- Review `ROLE_UPDATE_INTERVAL_SECONDS` setting

---

## 11. Performance Optimization ✅

### Database
- [ ] Connection pooling enabled (default in bot.py)
- [ ] Indexes created (automatic in setup_database.py)
- [ ] Regular vacuum/maintenance (PostgreSQL auto-handles)

### Bot
- [ ] Background tasks running efficiently
- [ ] Memory usage monitored
- [ ] API calls rate-limited
- [ ] Error handling implemented

---

## 12. Backup & Recovery ✅

### Database Backups
Set up automatic backups on your cloud platform:
- **Railway**: Automatic backups included
- **Heroku**: Enable Postgres backups addon
- **Render**: Backups in paid plans

### Manual Backup
```bash
# PostgreSQL
pg_dump DATABASE_URL > backup.sql

# SQLite
cp watchtime.db watchtime.db.backup
```

---

## 13. Documentation ✅

Files included:
- [ ] README.md - Project overview
- [ ] DEPLOYMENT.md - Deployment guide
- [ ] CHECKLIST.md - This file
- [ ] .env.example - Environment template
- [ ] requirements.txt - Python dependencies
- [ ] Dockerfile - Container configuration
- [ ] setup_database.py - Database initialization
- [ ] health_check.py - Database health check

---

## 14. Final Launch Steps ✅

1. [ ] Run full test suite locally
2. [ ] Deploy to cloud platform
3. [ ] Initialize database on cloud
4. [ ] Verify bot comes online
5. [ ] Test all commands in production
6. [ ] Announce bot to community
7. [ ] Monitor logs for first 24 hours
8. [ ] Set up alerting for downtime

---

## 🎉 Ready to Launch!

Once all items are checked:
1. Deploy to production
2. Monitor for first hour
3. Test with real users
4. Enjoy your automated Kick Discord bot!

---

## 📞 Support Resources

- **Discord.py Docs**: https://discordpy.readthedocs.io/
- **SQLAlchemy Docs**: https://docs.sqlalchemy.org/
- **Playwright Docs**: https://playwright.dev/python/
- **Railway Docs**: https://docs.railway.app/

---

**Last Updated**: October 19, 2025
