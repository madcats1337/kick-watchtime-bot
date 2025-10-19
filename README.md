# 🎮 Kick.com Watchtime Discord Bot

A Discord bot that tracks viewer watchtime on Kick.com and rewards loyal fans with Discord roles. Features secure account linking with Playwright-based bio verification to prevent unauthorized account linking.

## ✨ Features

- **🔒 Secure Account Linking**: Users verify Kick account ownership by adding a code to their bio
- **⏱️ Watchtime Tracking**: Automatically tracks viewer activity in your Kick chat
- **🏆 Role Rewards**: Assigns Discord roles based on watchtime milestones
- **📊 Leaderboards**: Shows top viewers with interactive embeds
- **🔄 Real-time Sync**: Updates watchtime every minute
- **🌐 Playwright Integration**: Uses Firefox/Chromium to bypass Cloudflare protection
- **🐳 Dockerized**: Easy deployment to Railway, Heroku, Render, or any container platform
- **☁️ Cloud-Ready**: PostgreSQL support for production deployments

## 🔐 Authentication System

The bot uses a **bio verification system** with Playwright automation to ensure users can only link their own Kick accounts:

1. User runs `/link <kick_username>` in Discord
2. Bot generates a unique 6-digit code
3. User adds the code to their Kick profile bio (on the About page)
4. User runs `/verify` to complete linking
5. Bot uses Playwright (Firefox preferred) to check the Kick bio for the code
6. If verified, the accounts are permanently linked

**Security features:**
- Codes expire after 10 minutes (configurable)
- One Kick account can only be linked to one Discord user
- Must have access to the Kick account to add code to bio
- Prevents unauthorized account linking
- Cloudflare bypass with Firefox/Chromium stealth mode

## 🚀 Quick Start (Local Testing)

### Prerequisites
- Python 3.11+
- Discord Bot Token ([Create one here](https://discord.com/developers/applications))
- Kick.com channel to monitor
- Playwright browsers installed

### Installation

1. **Clone the repository**
```bash
git clone <your-repo-url>
cd kick-discord-bot
```

2. **Install dependencies**
```bash
pip install -r requirements.txt
playwright install firefox chromium
playwright install-deps
```

3. **Configure environment variables**

Copy `.env.example` to `.env` and fill in your values:

```env
# Discord Configuration
DISCORD_TOKEN=your_bot_token_here
DISCORD_GUILD_ID=your_server_id_here

# Kick Channel to Monitor
KICK_CHANNEL=your_kick_username

# Database (use SQLite for local testing)
DATABASE_URL=sqlite:///watchtime.db

# Optional: Customize intervals
WATCH_INTERVAL_SECONDS=60
ROLE_UPDATE_INTERVAL_SECONDS=600
CODE_EXPIRY_MINUTES=10
```

4. **Create the watchtime roles in your Discord server**

The bot looks for these roles (create them manually or the bot will skip role assignment):
- 🎯 Fan (60 minutes)
- 🔥 Superfan (300 minutes / 5 hours)
- 💎 Elite Viewer (1000 minutes / ~16.7 hours)

**Important:** The bot's role must be positioned **above** these roles in your server's role hierarchy!

5. **Run the bot**
```bash
python bot.py
```

You should see:
```
✅ Logged in as YourBot#1234 (ID: ...)
📺 Monitoring Kick channel: your_channel
✅ Watchtime updater started
✅ Role updater started
✅ Cleanup task started
✅ Kick chat listener started
```

## 🎮 Commands

| Command | Description | Example |
|---------|-------------|---------|
| `!link <kick_username>` | Generate verification code to link accounts | `!link madcats` |
| `!verify <kick_username>` | Verify account ownership and complete linking | `!verify madcats` |
| `!unlink` | Unlink your Kick account from Discord | `!unlink` |
| `!watchtime` | Check your current watchtime | `!watchtime` |
| `!leaderboard [top]` | Show top viewers (default: 10, max: 25) | `!leaderboard 15` |

## 📋 Linking Workflow Example

```
User: !link madcats

Bot: 🔗 Link your Kick account

1. Go to https://kick.com/dashboard/settings/profile
2. Add this code to your bio: 847261
3. Run !verify madcats here

⏰ Code expires in 10 minutes.

---

[User adds code to Kick bio]

User: !verify madcats

Bot: ✅ Verified! Your Discord account is now linked to Kick user madcats
You can now remove the code from your bio.
```

## 🐳 Deployment (Production)

For detailed deployment guides, see **[DEPLOYMENT.md](DEPLOYMENT.md)** which includes:
- Railway.app (Recommended - Free tier with database)
- Heroku (Easy deployment)
- Render.com (Free tier available)
- Docker deployment (Any platform)

### Quick Deploy to Railway

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/new)

1. Click the button above or go to [railway.app](https://railway.app)
2. Connect your GitHub repository
3. Add PostgreSQL database
4. Set environment variables:
   ```
   DISCORD_TOKEN=your_bot_token
   DISCORD_GUILD_ID=your_server_id
   KICK_CHANNEL=your_channel_name
   ```
5. Deploy! Railway handles everything automatically
6. Initialize database: `railway run python setup_database.py`

### Docker Compose (Local Testing with PostgreSQL)

```bash
# Start bot and PostgreSQL
docker-compose up -d

# Initialize database
docker-compose exec bot python setup_database.py

# View logs
docker-compose logs -f bot
```

### Database Initialization

After first deployment, initialize the database:

```bash
# For Railway
railway run python setup_database.py

# For Heroku
heroku run python setup_database.py

# For Docker
docker exec -it <container_id> python setup_database.py
```

Verify database health:
```bash
python health_check.py
```

## ⚙️ Configuration

### Role Thresholds

Edit `WATCHTIME_ROLES` in `bot.py`:

```python
WATCHTIME_ROLES = [
    {"name": "🎯 Fan", "minutes": 60},           # 1 hour
    {"name": "🔥 Superfan", "minutes": 300},     # 5 hours
    {"name": "💎 Elite Viewer", "minutes": 1000}, # ~16.7 hours
    {"name": "👑 Legend", "minutes": 5000},      # ~83 hours
]
```

### Intervals

Adjust in `.env`:

- `WATCH_INTERVAL_SECONDS`: How often to update watchtime (default: 60)
- `ROLE_UPDATE_INTERVAL_SECONDS`: How often to check and assign roles (default: 600)
- `CODE_EXPIRY_MINUTES`: How long verification codes are valid (default: 10)

## 🔍 Troubleshooting

### "Could not obtain chatroom id"
- Verify `KICK_CHANNEL` matches your exact Kick username
- Check if the Kick API is accessible from your network

### Roles not being assigned
- Ensure role names match exactly (including emojis)
- Check bot's role is above the reward roles in Discord hierarchy
- Verify `DISCORD_GUILD_ID` is correct

### Verification code not found
- Make sure the code is visible in the public bio (not just saved in editor)
- Wait a moment after saving bio before running `!verify`
- Check for typos in the username

### Database errors
- For SQLite: ensure write permissions in the directory
- For PostgreSQL: verify `DATABASE_URL` is correct and database exists

## 📊 Database Schema

```sql
-- User watchtime tracking
watchtime (
    username TEXT PRIMARY KEY,
    minutes INTEGER DEFAULT 0,
    last_active TIMESTAMP
)

-- Linked Discord<->Kick accounts
links (
    discord_id BIGINT PRIMARY KEY,
    kick_name TEXT UNIQUE
)

-- Pending verifications
pending_links (
    discord_id BIGINT PRIMARY KEY,
    kick_name TEXT,
    code TEXT,
    timestamp TEXT
)
```

## 🛡️ Security Notes

- **Never commit `.env`** - it's already in `.gitignore`
- **Rotate tokens** if accidentally exposed
- **Use PostgreSQL** in production (SQLite is for testing only)
- **Bio verification** prevents unauthorized linking
- **Code expiry** limits time window for attacks

## 📝 License

MIT License - feel free to modify and use for your community!

## 🤝 Contributing

Contributions are welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## 💬 Support

Need help? Check these resources:
- [Discord.py Documentation](https://discordpy.readthedocs.io/)
- [Kick API Documentation](https://kick.com/api)
- Open an issue on GitHub

---

Made with ❤️ for the Kick.com community
