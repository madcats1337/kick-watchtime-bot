# Kick Discord Bot - Deployment Guide

## 🚀 Cloud Deployment Options

This bot can be deployed to various cloud platforms. Below are guides for the most popular options.

### Prerequisites
- Discord Bot Token ([Discord Developer Portal](https://discord.com/developers/applications))
- Kick Channel Name
- PostgreSQL Database (for production)

---

## 📦 Option 1: Railway.app (Recommended)

Railway offers free tier with PostgreSQL database included.

### Steps:

1. **Create Railway Account**
   - Go to [railway.app](https://railway.app)
   - Sign up with GitHub

2. **Create New Project**
   - Click "New Project"
   - Select "Deploy from GitHub repo"
   - Connect your repository

3. **Add PostgreSQL Database**
   - Click "New" → "Database" → "PostgreSQL"
   - Railway will automatically create `DATABASE_URL` variable

4. **Configure Environment Variables**
   - Go to your bot service → "Variables"
   - Add the following:
     ```
     DISCORD_TOKEN=your_discord_bot_token
     DISCORD_GUILD_ID=your_server_id
     KICK_CHANNEL=your_kick_channel_name
     ```

5. **Initialize Database**
   - After first deployment, run:
     ```bash
     railway run python setup_database.py
     ```

6. **Deploy**
   - Railway auto-deploys on git push
   - Monitor logs in Railway dashboard

---

## 🔷 Option 2: Heroku

### Steps:

1. **Install Heroku CLI**
   ```bash
   curl https://cli-assets.heroku.com/install.sh | sh
   ```

2. **Login and Create App**
   ```bash
   heroku login
   heroku create your-bot-name
   ```

3. **Add PostgreSQL**
   ```bash
   heroku addons:create heroku-postgresql:mini
   ```

4. **Set Environment Variables**
   ```bash
   heroku config:set DISCORD_TOKEN=your_token
   heroku config:set DISCORD_GUILD_ID=your_server_id
   heroku config:set KICK_CHANNEL=your_channel
   ```

5. **Deploy**
   ```bash
   git push heroku main
   ```

6. **Initialize Database**
   ```bash
   heroku run python setup_database.py
   ```

7. **Scale Worker**
   ```bash
   heroku ps:scale worker=1
   ```

Create `Procfile`:
```
worker: python bot.py
```

---

## 🐳 Option 3: Docker (Any Platform)

Works with: DigitalOcean, AWS, Google Cloud, Azure, etc.

### Steps:

1. **Build Image**
   ```bash
   docker build -t kick-watchtime-bot .
   ```

2. **Run with Environment Variables**
   ```bash
   docker run -d \
     -e DISCORD_TOKEN=your_token \
     -e DISCORD_GUILD_ID=your_server_id \
     -e KICK_CHANNEL=your_channel \
     -e DATABASE_URL=postgresql://... \
     kick-watchtime-bot
   ```

3. **Initialize Database**
   ```bash
   docker exec -it <container_id> python setup_database.py
   ```

---

## 💚 Option 4: Render.com

1. **Create Account** at [render.com](https://render.com)

2. **New Web Service**
   - Connect GitHub repository
   - Environment: Docker
   - Plan: Free (or Starter for 24/7)

3. **Add PostgreSQL Database**
   - Dashboard → "New" → "PostgreSQL"
   - Copy internal connection string

4. **Environment Variables**
   ```
   DISCORD_TOKEN=your_token
   DISCORD_GUILD_ID=your_server_id
   KICK_CHANNEL=your_channel
   DATABASE_URL=<internal_postgres_url>
   ```

5. **Deploy & Initialize**
   - Render auto-deploys
   - Use Shell access to run: `python setup_database.py`

---

## 🗄️ Database Configuration

### PostgreSQL (Production)

The bot automatically converts `postgres://` to `postgresql://` for SQLAlchemy compatibility.

**Connection String Format:**
```
postgresql://username:password@host:port/database
```

**Railway Example:**
```
postgresql://postgres:pass@containers-us-west-123.railway.app:5432/railway
```

**Supabase Example:**
```
postgresql://postgres:pass@db.projectref.supabase.co:5432/postgres
```

### SQLite (Development Only)
```
DATABASE_URL=sqlite:///watchtime.db
```

⚠️ **Warning:** SQLite is not recommended for production as it doesn't persist in containerized environments.

---

## 🔧 Environment Variables Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DISCORD_TOKEN` | ✅ Yes | - | Bot token from Discord Developer Portal |
| `DISCORD_GUILD_ID` | ✅ Yes | - | Your Discord server ID |
| `KICK_CHANNEL` | ✅ Yes | - | Kick channel name to monitor |
| `DATABASE_URL` | ⚠️ Recommended | `sqlite:///watchtime.db` | PostgreSQL connection string |
| `WATCH_INTERVAL_SECONDS` | No | `60` | How often to check for viewers |
| `ROLE_UPDATE_INTERVAL_SECONDS` | No | `600` | How often to update roles |
| `CODE_EXPIRY_MINUTES` | No | `10` | Verification code expiry time |

---

## 🎯 Post-Deployment Checklist

- [ ] Database tables created (run `setup_database.py`)
- [ ] Bot is online in Discord server
- [ ] Bot has necessary permissions:
  - Manage Roles
  - Send Messages
  - Read Message History
  - View Channels
- [ ] Watchtime roles created in Discord:
  - 🎯 Fan (1 hour)
  - 🔥 Superfan (5 hours)
  - 💎 Elite Viewer (16+ hours)
- [ ] Test commands:
  - `/link` - Start verification
  - `/verify` - Complete verification
  - `/watchtime` - Check watchtime
  - `/leaderboard` - View rankings

---

## 📊 Monitoring & Logs

### Railway
- View logs in project dashboard
- Auto-restarts on crash

### Heroku
```bash
heroku logs --tail
```

### Docker
```bash
docker logs -f <container_id>
```

---

## 🔒 Security Notes

1. **Never commit `.env` file** - It's already in `.gitignore`
2. **Use environment variables** for all secrets
3. **Rotate tokens** if accidentally exposed
4. **Database credentials** should be unique and strong
5. **Enable 2FA** on all platform accounts

---

## 🆘 Troubleshooting

### Bot not responding
- Check logs for errors
- Verify `DISCORD_TOKEN` is correct
- Ensure bot has proper permissions

### Database connection errors
- Verify `DATABASE_URL` format
- Check database is accessible
- Run `setup_database.py` if tables missing

### Cloudflare blocking Playwright
- Playwright uses Firefox first (better bypass)
- Falls back to Chromium if Firefox unavailable
- May need to retry verification multiple times

### Watchtime not tracking
- Verify `KICK_CHANNEL` name is correct
- Check if Kick API is accessible
- Review WebSocket connection logs

---

## 📚 Additional Resources

- [Discord.py Documentation](https://discordpy.readthedocs.io/)
- [Railway Documentation](https://docs.railway.app/)
- [PostgreSQL Documentation](https://www.postgresql.org/docs/)
- [Playwright Documentation](https://playwright.dev/python/)

---

## 🤝 Support

For issues and questions:
1. Check existing GitHub issues
2. Review logs for error messages
3. Verify environment variables
4. Test with `/ping` command

---

Made with ❤️ for the Kick community
