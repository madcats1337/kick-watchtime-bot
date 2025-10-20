# 🎮 Kick.com Watchtime Discord Bot

A Discord bot that tracks viewer watchtime on Kick.com and rewards loyal fans with Discord roles. Features **OAuth 2.0 linking** and **reaction-based link panels** for seamless account verification.

## ✨ Features

- **� OAuth Account Linking**: Instant linking with Kick OAuth (no manual bio editing!)
- **📌 Reaction Link Panels**: Users react to a pinned message to start linking (no command spam!)
- **⏱️ Watchtime Tracking**: Automatically tracks viewer activity in your Kick chat
- **🏆 Role Rewards**: Assigns Discord roles based on watchtime milestones
- **📊 Leaderboards**: Shows top viewers with interactive embeds
- **🔄 Real-time Sync**: Updates watchtime every minute
- **🐳 Dockerized**: Easy deployment to Railway, Heroku, Render, or any container platform
- **☁️ Cloud-Ready**: PostgreSQL support for production deployments

## 🔐 Authentication Methods

### 🌟 Method 1: OAuth Link Panel (Recommended)
The easiest way for users to link accounts - **no typing required!**

**Admin Setup:**
```
!setup_link_panel 🔗
```

This creates a pinned message with a reaction. Users simply:
1. React with 🔗 on the pinned message
2. Get a DM with their personal OAuth link
3. Click link → Authorize with Kick → Done!

**Benefits:**
- ✅ No channel spam (no commands)
- ✅ Always visible (pinned message)
- ✅ One-click experience
- ✅ Professional appearance

👉 **See [LINK_PANEL_QUICKSTART.md](LINK_PANEL_QUICKSTART.md) for setup guide**

### Method 2: OAuth Command (Fallback)
Users can type `!link` to get their personal OAuth link via DM.

**How it works:**
1. User runs `!link` in Discord
2. Bot sends DM with OAuth authorization link
3. User clicks link and authorizes with Kick
4. Bot automatically retrieves Kick username
5. Accounts are instantly linked

**Benefits:**
- ✅ Instant linking (no bio editing)
- ✅ Automatic username retrieval
- ✅ Secure OAuth 2.0 with PKCE
- ✅ Works as fallback if reactions fail

👉 **See [OAUTH_SETUP.md](OAUTH_SETUP.md) for OAuth configuration**

### Method 3: Bio Verification (Legacy)
Manual verification by adding a code to Kick bio.

**How it works:**
1. User runs `!linkbio <kick_username>` in Discord
2. Bot generates a unique 6-digit code
3. User adds the code to their Kick profile bio
4. User runs `!verify` to complete linking
5. Bot uses Playwright to check the Kick bio for the code

**Security features:**
- Codes expire after 10 minutes (configurable)
- One Kick account can only be linked to one Discord user
- Must have access to the Kick account to add code to bio
- Cloudflare bypass with Playwright stealth mode

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

# OAuth Configuration (for instant linking)
OAUTH_BASE_URL=https://your-app.up.railway.app  # Your deployed OAuth server URL
KICK_CLIENT_ID=your_kick_oauth_client_id        # Get from Kick developer portal

# Optional: Customize intervals
WATCH_INTERVAL_SECONDS=60
ROLE_UPDATE_INTERVAL_SECONDS=600
CODE_EXPIRY_MINUTES=10
```

**Note:** OAuth linking requires deploying the OAuth server (see [OAUTH_SETUP.md](OAUTH_SETUP.md)).  
For local testing without OAuth, users can still use the bio verification method (`!linkbio`).

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

### Account Linking
| Command | Description | Example |
|---------|-------------|---------|
| `!setup_link_panel [emoji]` | **[Admin]** Create reaction-based link panel | `!setup_link_panel 🔗` |
| `!link` | Get personal OAuth link (instant linking) | `!link` |
| `!linkbio <kick_username>` | Generate bio verification code (legacy method) | `!linkbio madcats` |
| `!verify` | Verify bio code and complete linking | `!verify` |
| `!unlink` | Unlink your Kick account from Discord | `!unlink` |

### Watchtime & Stats
| Command | Description | Example |
|---------|-------------|---------|
| `!watchtime` | Check your current watchtime | `!watchtime` |
| `!leaderboard [top]` | Show top viewers (default: 10, max: 25) | `!leaderboard 15` |

### Admin Commands
| Command | Description | Example |
|---------|-------------|---------|
| `!tracking on/off/status` | Enable/disable watchtime tracking | `!tracking on` |

## 📋 Linking Workflow Examples

### 🌟 Recommended: Reaction Panel Method
```
Admin: !setup_link_panel 🔗

Bot: Creates pinned message:
┌────────────────────────────────┐
│  🎮 Link Your Kick Account     │
│  React with 🔗 below...        │
│                                │
│  📝 How it works:              │
│  1. Click 🔗                   │
│  2. Get DM with OAuth link     │
│  3. Authorize with Kick        │
│  4. Done!                      │
└────────────────────────────────┘

[User reacts with 🔗]

Bot (via DM): 
🔗 Link with Kick OAuth
[Button: 🎮 Link with Kick]

[User clicks button → authorizes → done!]

Bot: ✅ Successfully linked to your Kick account!
```

### Method 2: OAuth Command
```
User: !link

Bot (via DM):
🔗 Link with Kick OAuth
[Button: 🎮 Link with Kick]

[User clicks button → authorizes → done!]

Bot: ✅ Successfully linked to your Kick account!
```

### Method 3: Bio Verification (Legacy)

### Method 3: Bio Verification (Legacy)
```
User: !linkbio madcats

Bot: 🔗 Link your Kick account

1. Go to https://kick.com/dashboard/settings/profile
2. Add this code to your bio: 847261
3. Run !verify here

⏰ Code expires in 10 minutes.

---

[User adds code to Kick bio]

User: !verify

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

-- Pending bio verifications
pending_links (
    discord_id BIGINT PRIMARY KEY,
    kick_name TEXT,
    code TEXT,
    timestamp TEXT
)

-- OAuth state tracking (PKCE flow)
oauth_states (
    state TEXT PRIMARY KEY,
    discord_id BIGINT NOT NULL,
    code_verifier TEXT NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)

-- OAuth success notifications
oauth_notifications (
    id SERIAL PRIMARY KEY,
    discord_id BIGINT NOT NULL,
    kick_username TEXT NOT NULL,
    channel_id BIGINT,
    message_id BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processed BOOLEAN DEFAULT FALSE
)

-- Reaction-based link panels
link_panels (
    id SERIAL PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    message_id BIGINT NOT NULL,
    emoji TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(guild_id, channel_id, message_id)
)
```

## � Documentation

This bot includes comprehensive documentation:

- **[LINK_PANEL_QUICKSTART.md](LINK_PANEL_QUICKSTART.md)** - Quick start guide for reaction-based link panels
- **[LINK_PANEL_SETUP.md](LINK_PANEL_SETUP.md)** - Complete setup guide for link panels
- **[LINK_PANEL_ARCHITECTURE.md](LINK_PANEL_ARCHITECTURE.md)** - Technical architecture and flow diagrams
- **[LINK_PANEL_IMPLEMENTATION.md](LINK_PANEL_IMPLEMENTATION.md)** - Implementation details and code changes
- **[OAUTH_SETUP.md](OAUTH_SETUP.md)** - OAuth server setup and configuration guide

## �🛡️ Security Notes

- **Never commit `.env`** - it's already in `.gitignore`
- **Rotate tokens** if accidentally exposed
- **Use PostgreSQL** in production (SQLite is for testing only)
- **OAuth PKCE** protects against authorization code interception
- **Bio verification** prevents unauthorized linking (legacy method)
- **Code expiry** limits time window for attacks
- **Unique links** - each user gets a unique OAuth URL

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
