# 🎮 Kick.com Watchtime Discord Bot

A Discord bot that tracks viewer watchtime on Kick.com and rewards loyal fans with Discord roles. Features **OAuth 2.0 linking** and **reaction-based link panels** for seamless account verification.

## ✨ Features

- **🔗 OAuth Account Linking**: Instant linking with Kick OAuth (no manual bio editing!)
- **📌 Reaction Link Panels**: Users react to a pinned message to start linking (no command spam!)
- **⏱️ Watchtime Tracking**: Automatically tracks viewer activity in your Kick chat
- **🏆 Role Rewards**: Assigns Discord roles based on watchtime milestones
- **⚙️ Database-Configurable Roles**: Manage role thresholds without code changes
- **📊 Leaderboards**: Shows top viewers with interactive embeds
- **� Link Attempt Logging**: Monitor account linking activity (admin feature)
- **🔒 HMAC-SHA256 Security**: Cryptographically signed OAuth URLs with 1-hour expiry
- **�🔄 Real-time Sync**: Updates watchtime every minute
- **🐳 Dockerized**: Easy deployment to Railway, Heroku, Render, or any container platform
- **☁️ Cloud-Ready**: PostgreSQL support for production deployments
- **📄 Legal Compliance**: Built-in Terms of Service and Privacy Policy

## 🔐 Account Linking

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
- ✅ HMAC-SHA256 signed URLs (1-hour expiry)

👉 **See [docs/LINK_PANEL_QUICKSTART.md](docs/LINK_PANEL_QUICKSTART.md) for setup guide**

### Method 2: OAuth Command (Fallback)
Users can type `!link` to get their personal OAuth link via DM.

**How it works:**
1. User runs `!link` in Discord
2. Bot sends DM with cryptographically signed OAuth authorization link
3. User clicks link and authorizes with Kick
4. Bot automatically retrieves Kick username
5. Accounts are instantly linked

**Benefits:**
- ✅ Instant linking (no bio editing)
- ✅ Automatic username retrieval
- ✅ Secure OAuth 2.0 with PKCE
- ✅ HMAC-SHA256 signature validation
- ✅ Works as fallback if reactions fail

👉 **See [docs/OAUTH_SETUP.md](docs/OAUTH_SETUP.md) for OAuth configuration**

### 🔒 Security Features
- **HMAC-SHA256 Signatures**: All OAuth URLs are cryptographically signed to prevent tampering
- **Time-Limited Links**: OAuth URLs expire after 1 hour
- **PKCE Flow**: Protects against authorization code interception
- **Unique State Tokens**: Each linking attempt uses a unique cryptographic state
- **Link Attempt Logging**: Track all successful and failed linking attempts (admin feature)

## 🚀 Quick Start (Local Testing)

### Prerequisites
- Python 3.11+
- Discord Bot Token ([Create one here](https://discord.com/developers/applications))
- Kick.com OAuth Application ([Register here](https://kick.com/developer/applications))
- PostgreSQL database (Railway, Supabase, or local)

### Installation

1. **Clone the repository**
```bash
git clone https://github.com/madcats1337/kick-watchtime-bot.git
cd kick-watchtime-bot
```

2. **Install dependencies**
```bash
pip install -r requirements.txt
```

3. **Configure environment variables**

Copy `.env.example` to `.env` and fill in your values:

```env
# Discord Configuration
DISCORD_TOKEN=your_bot_token_here
DISCORD_GUILD_ID=your_server_id_here

# Kick Channel to Monitor
KICK_CHANNEL=your_kick_username

# Database (PostgreSQL required)
DATABASE_URL=postgresql://user:password@host:5432/database

# OAuth Configuration (required for account linking)
OAUTH_BASE_URL=https://your-app.up.railway.app  # Your deployed OAuth server URL
KICK_CLIENT_ID=your_kick_oauth_client_id        # Get from Kick developer portal
KICK_CLIENT_SECRET=your_kick_oauth_client_secret # Get from Kick developer portal
FLASK_SECRET_KEY=random_secret_key_here          # Generate with: python -c "import secrets; print(secrets.token_hex(32))"

# Optional: Customize intervals
WATCH_INTERVAL_SECONDS=60
ROLE_UPDATE_INTERVAL_SECONDS=600
```

**Note:** OAuth linking requires deploying the OAuth server (see [docs/OAUTH_SETUP.md](docs/OAUTH_SETUP.md)).

4. **Initialize the database**
```bash
python setup_database.py
```

5. **Configure watchtime roles**

Use the `!roles` command to manage role thresholds (see Admin Commands below). The bot's role must be positioned **above** the watchtime roles in your server's role hierarchy!

6. **Run the bot**
```bash
python combined_server.py
```

This starts both the Discord bot and OAuth Flask server. You should see:
```
✅ Logged in as YourBot#1234 (ID: ...)
📺 Monitoring Kick channel: your_channel
✅ Watchtime updater started
✅ Role updater started
✅ OAuth notification checker started
✅ Kick chat listener started
 * Running on http://0.0.0.0:8080
```

## 🎮 Commands

### Account Linking
| Command | Description | Example |
|---------|-------------|---------|
| `!setup_link_panel [emoji]` | **[Admin]** Create reaction-based link panel | `!setup_link_panel 🔗` |
| `!link` | Get personal OAuth link (instant linking) | `!link` |
| `!unlink` | Unlink your Kick account from Discord | `!unlink` |

### Watchtime & Stats
| Command | Description | Example |
|---------|-------------|---------|
| `!watchtime` | Check your current watchtime | `!watchtime` |
| `!leaderboard [top]` | Show top viewers (default: 10, max: 25) | `!leaderboard 15` |

### Admin Commands
| Command | Description | Example |
|---------|-------------|---------|
| `!health` | **[Admin]** Check system status and diagnostics | `!health` |
| `!tracking on/off/status` | Enable/disable watchtime tracking | `!tracking on` |
| `!linklogs on/off/status` | Enable/disable link attempt logging | `!linklogs on` |
| `!roles list` | Show all configured watchtime roles | `!roles list` |
| `!roles add <role> <minutes>` | Add a new watchtime role | `!roles add @Veteran 720` |
| `!roles update <role> <minutes>` | Update role threshold | `!roles update @Fan 90` |
| `!roles remove <role>` | Remove a watchtime role | `!roles remove @Fan` |
| `!roles enable <role>` | Enable a disabled role | `!roles enable @Fan` |
| `!roles disable <role>` | Disable a role without deleting | `!roles disable @Fan` |
| `!roles members <role>` | List members with specific role | `!roles members @Fan` |

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

### Admin Monitoring
```
Admin: !linklogs on

Bot: � Link attempt logging enabled!
     All successful and failed link attempts will be logged here.

[User attempts to link]

Bot (in logs channel):
🔗 Account Linked
User: @username
Kick: madcats
Time: 2025-10-22 14:35:21

[Failed attempt]

Bot (in logs channel):
❌ Link Failed
User: @username
Kick: invalid_user
Error: User not found
Time: 2025-10-22 14:36:12
```

## 🐳 Deployment (Production)

For detailed deployment guides, see **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)** which includes:
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

Roles are managed entirely through the `!roles` command - **no code changes needed!**

```
# Add a new role
!roles add @Fan 60

# Update threshold
!roles update @Superfan 300

# Temporarily disable without deleting
!roles disable @Elite Viewer

# Re-enable
!roles enable @Elite Viewer

# List all roles
!roles list
```

Roles are stored in the `watchtime_roles` table and checked dynamically. Changes take effect immediately.

### Intervals

Adjust in `.env`:

- `WATCH_INTERVAL_SECONDS`: How often to update watchtime (default: 60)
- `ROLE_UPDATE_INTERVAL_SECONDS`: How often to check and assign roles (default: 600)

## 🔍 Troubleshooting

### "Could not obtain chatroom id"
- Verify `KICK_CHANNEL` matches your exact Kick username
- Check if the Kick API is accessible from your network

### Roles not being assigned
- Use `!roles list` to verify roles are configured
- Check bot's role is above the reward roles in Discord hierarchy
- Verify `DISCORD_GUILD_ID` is correct
- Ensure role is enabled: `!roles enable @RoleName`

### OAuth linking fails (403 Forbidden)
- Verify `FLASK_SECRET_KEY` is set in environment variables
- Check that `KICK_CLIENT_ID` and `KICK_CLIENT_SECRET` are correct
- Ensure `OAUTH_BASE_URL` matches your deployed server URL
- Check Railway logs for detailed error messages

### Database errors
- PostgreSQL is required (SQLite no longer supported)
- Verify `DATABASE_URL` is correct and database exists
- Run `python setup_database.py` to initialize tables

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

-- OAuth state tracking (PKCE flow)
oauth_states (
    state TEXT PRIMARY KEY,
    discord_id BIGINT NOT NULL,
    code_verifier TEXT NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)

-- OAuth success/failure notifications
oauth_notifications (
    id SERIAL PRIMARY KEY,
    discord_id BIGINT NOT NULL,
    kick_username TEXT NOT NULL,  -- Stores "FAILED:<username>:<error>" for failures
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

-- Database-configurable watchtime roles
watchtime_roles (
    id SERIAL PRIMARY KEY,
    role_name TEXT NOT NULL UNIQUE,
    minutes_required INTEGER NOT NULL,
    display_order INTEGER DEFAULT 0,
    enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)

-- Link attempt logging configuration
link_logs_config (
    guild_id BIGINT PRIMARY KEY,
    channel_id BIGINT NOT NULL,
    enabled BOOLEAN DEFAULT TRUE
)
```

## 📚 Documentation

This bot includes comprehensive documentation in the `docs/` folder:

### Setup Guides
- **[docs/LINK_PANEL_QUICKSTART.md](docs/LINK_PANEL_QUICKSTART.md)** - Quick start guide for reaction-based link panels
- **[docs/LINK_PANEL_SETUP.md](docs/LINK_PANEL_SETUP.md)** - Complete setup guide for link panels
- **[docs/OAUTH_SETUP.md](docs/OAUTH_SETUP.md)** - OAuth server setup and configuration guide
- **[docs/DEPLOYMENT_RAILWAY.md](docs/DEPLOYMENT_RAILWAY.md)** - Railway deployment guide

### Technical Documentation
- **[docs/LINK_PANEL_ARCHITECTURE.md](docs/LINK_PANEL_ARCHITECTURE.md)** - Technical architecture and flow diagrams
- **[docs/LINK_PANEL_IMPLEMENTATION.md](docs/LINK_PANEL_IMPLEMENTATION.md)** - Implementation details and code changes
- **[docs/SECURITY_IMPLEMENTATION.md](docs/SECURITY_IMPLEMENTATION.md)** - HMAC signature security details

### Legal & Compliance
- **[TERMS_OF_SERVICE.md](TERMS_OF_SERVICE.md)** - Terms of service for bot users
- **[PRIVACY_POLICY.md](PRIVACY_POLICY.md)** - Privacy policy (GDPR/CCPA compliant)

### Maintenance
- **[SECURITY_SCAN.md](SECURITY_SCAN.md)** - Security audit report

## 🛡️ Security

### Security Features
- **HMAC-SHA256 Signed URLs**: All OAuth links cryptographically signed to prevent tampering
- **Time-Limited Links**: OAuth URLs expire after 1 hour (configurable)
- **PKCE Flow**: Protects against authorization code interception attacks
- **Constant-Time Comparison**: HMAC signatures validated using timing-attack-resistant comparison
- **Unique State Tokens**: Each linking attempt uses a unique cryptographic state parameter
- **Environment Variables**: All secrets stored in `.env` (never committed to git)

### Best Practices
- **Never commit `.env`** - it's already in `.gitignore`
- **Rotate tokens** if accidentally exposed
- **Use PostgreSQL** in production with encrypted connections
- **Set strong FLASK_SECRET_KEY**: Generate with `python -c "import secrets; print(secrets.token_hex(32))"`
- **Monitor link attempts**: Enable `!linklogs` to track suspicious activity
- **Review legal docs**: Ensure Terms of Service and Privacy Policy match your usage

See **[SECURITY_SCAN.md](SECURITY_SCAN.md)** for the latest security audit.

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
