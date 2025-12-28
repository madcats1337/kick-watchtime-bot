# 🎮 Kick.com Discord Bot with Raffle System & Admin Dashboard

A comprehensive Discord bot ecosystem that tracks viewer watchtime on Kick.com, rewards loyal fans with Discord roles, and runs monthly raffles with tickets earned from watchtime, gifted subs, and Shuffle wagers. Features **OAuth 2.0 linking**, **button-based link panels**, and a **web-based admin dashboard** for seamless management.

## ✨ Features

### Core Features
- **🔗 OAuth Account Linking**: Instant linking with Kick OAuth (no manual bio editing!)
- **📌 Button Link Panels**: Users click a button to get their personal OAuth link (ephemeral messages!)
- **⏱️ Watchtime Tracking**: Automatically tracks viewer activity in your Kick chat
- **🏆 Role Rewards**: Assigns Discord roles based on watchtime milestones
- **⚙️ Database-Configurable Roles**: Manage role thresholds without code changes
- **📊 Leaderboards**: Shows top viewers with interactive embeds
- **🔒 HMAC-SHA256 Security**: Cryptographically signed OAuth URLs with 10-minute expiry
- **🔄 Real-time Sync**: Updates watchtime every minute
- **🌐 Web Admin Dashboard**: Manage bot settings, view analytics, and control features via web interface (Private)

### 🎟️ Raffle System
- **🎁 Gifted Sub Tracking**: Earn 15 tickets per gifted sub (real-time)
- **⏰ Watchtime Conversion**: Earn 10 tickets per hour watched
- **💰 Shuffle Wager Tracking**: Earn 20 tickets per $1000 wagered
- **🎲 Fair Drawing**: Cryptographically random winner selection
- **📅 Monthly Resets**: Automatic period transitions on the 1st
- **🏅 Ticket Leaderboard**: Track your progress and compete
- **🔗 Shuffle Integration**: Link your Shuffle.com account with verification
- **📈 Detailed Statistics**: View raffle stats and ticket breakdown
- **🌐 Dashboard Management**: Configure raffle settings via web interface

### 🎰 Slot Request System
- **📢 Real-time Tracking**: Monitors Kick chat for `!call` and `!sr` commands
- **📝 Discord Notifications**: Auto-posts slot requests to Discord channel
- **🎯 User Attribution**: Shows which Kick user requested each slot
- **🔧 Admin Panel**: Web-based slot request management and configuration
- **🚫 Blacklist System**: Block users from making slot requests
- **⚡ Instant Posting**: No delay between request and Discord notification
- **🎮 Slot Library**: Searchable database of 4,790+ slots synced from N9Assets
- **📊 Request Analytics**: Track slot request patterns and popular slots

### 🎮 Guess the Balance Game
- **💰 Interactive Betting Game**: Players guess the final balance after slot spins
- **📊 Discord Panel UI**: Buttons and modals for easy game management
- **🏆 Automatic Winner Detection**: Closest guess wins automatically
- **💵 Configurable Prize Pools**: Admins set prize amounts per session
- **📈 Real-time Updates**: Live session status and guess tracking
- **🌐 Dashboard Control**: Manage GTB sessions from web interface

### 🌐 Admin Dashboard (Private Repository)
- **📊 Analytics Dashboard**: View watchtime stats, raffle analytics, and user activity
- **🎫 Slot Request Controls**: Configure request limits, blacklist users, search slots
- **🎲 Raffle Management**: Monitor ticket distribution, view leaderboards, manage periods
- **⚙️ Bot Configuration**: Update settings, manage roles, control features
- **👥 User Management**: View linked accounts, watchtime history, ticket balances
- **📈 Real-time Monitoring**: Live bot status, active viewers, recent activities
- **🔐 Secure Access**: Protected with authentication and role-based permissions

### Deployment
- **🐳 Dockerized**: Easy deployment to Railway, Heroku, Render, or any container platform
- **☁️ Cloud-Ready**: PostgreSQL support for production deployments
- **🔒 Session-Based Auth**: Reliable Kick chat interaction with session tokens
- **📄 Legal Compliance**: Built-in Terms of Service and Privacy Policy

## 🌐 Admin Dashboard

The bot includes a comprehensive web-based admin dashboard for managing all bot features through an intuitive interface.

**Note:** The dashboard repository is private and available upon request for authorized users only.

### Dashboard Features

**📊 Analytics & Monitoring:**
- Real-time bot status and health metrics
- Watchtime analytics and viewer statistics
- Raffle participation and ticket distribution graphs
- Slot request trends and popular slots analysis

**🎫 Slot Request Management:**
- Configure request limits and cooldown periods
- Search and browse 4,790+ slots synced from N9Assets
- Manage blacklisted users and view request history
- Control slot request panel settings

**🎲 Raffle Administration:**
- View ticket leaderboards and user balances
- Monitor raffle period status and dates
- Award or remove bonus tickets
- View detailed raffle statistics and history

**⚙️ Bot Configuration:**
- Manage watchtime role thresholds
- Configure OAuth settings and link panels
- Update bot behavior and feature toggles
- View and manage linked Discord/Kick accounts

**🔐 Security & Access:**
- Secure authentication system
- Role-based permissions
- Activity logging and audit trails
- Protected with HMAC-SHA256 signatures

**📱 Modern Interface:**
- Responsive design (mobile-friendly)
- Dark mode optimized
- Real-time updates via WebSocket
- Built with Flask, Tailwind CSS, and Alpine.js

### Accessing the Dashboard

The dashboard is deployed separately and accessible at your configured admin URL. Contact the bot administrator for access credentials.

**Dashboard Repository:** Private - contact for access

## 📁 Project Structure

```
kick-watchtime-bot/
├── bot.py                      # Main Discord bot entry point
├── start.py                    # Combined bot + OAuth server launcher
├── combined_server.py          # Alternative unified server
├── requirements.txt            # Python dependencies
├── core/                       # Core functionality
│   ├── kick_api.py            # Kick.com API integration
│   └── oauth_server.py        # Flask OAuth authorization server
├── features/                   # Bot features (modular)
│   ├── slot_requests/         # Slot call tracker
│   │   ├── slot_calls.py     # Kick chat !call command tracker
│   │   └── slot_request_panel.py  # Discord panel UI
│   ├── games/                 # Interactive games
│   │   ├── guess_the_balance.py   # GTB game logic
│   │   └── gtb_panel.py          # GTB Discord UI
│   ├── linking/               # Account linking
│   │   └── link_panel.py     # Button-based link panel
│   └── messaging/             # Automated messaging
│       └── timed_messages.py # Scheduled Kick chat messages
├── raffle_system/             # Monthly raffle system
│   ├── commands.py            # Raffle Discord commands
│   ├── database.py            # Raffle database operations
│   ├── scheduler.py           # Auto-draw scheduler
│   ├── tickets.py             # Ticket management
│   ├── gifted_sub_tracker.py # Gifted sub event tracker
│   ├── shuffle_tracker.py    # Shuffle wager tracker
│   └── watchtime_converter.py # Convert watchtime to tickets
├── config/                    # Deployment configuration
│   ├── Dockerfile            # Docker container config
│   ├── docker-compose.yml    # Multi-container setup
│   ├── railway.json          # Railway deployment config
│   └── Procfile              # Heroku deployment config
├── scripts/                   # Utility scripts
│   ├── setup_database.py     # Initialize database schema
│   ├── generate_oauth_url.py # Generate OAuth authorization URL
│   ├── health_check.py       # Database health diagnostics
│   └── create_bot_tokens_table.py  # Bot token table setup
├── docs/                      # Documentation
└── tests/                     # Unit tests
```

## 🔐 Account Linking

Users link their Kick and Discord accounts to earn watchtime and raffle tickets.

### For Users

**How to Link:**
1. Click the **"Link Account"** button on the link panel
2. Click **"Link with Kick"** in the message (only you can see it)
3. Authorize with Kick → Done!

**Alternative - Command:**
- Type `!link` in Discord to get your personal link button

**Unlink:**
- Type `!unlink` to remove your account link

### For Admins

**Setup Link Panel:**
```
!setup_link_panel
```
Creates a permanent panel with a button users can click to link accounts.

**Monitor Link Attempts:**
```
!linklogs on     # Enable link attempt logging
!linklogs off    # Disable logging
!linklogs status # Check logging status
```

**Security:** All OAuth links are cryptographically signed (HMAC-SHA256) with 10-minute expiration. Links appear as ephemeral messages (only visible to the clicking user).

👉 **Full setup guide:** [docs/OAUTH_SETUP.md](docs/OAUTH_SETUP.md)

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

# Optional: Raffle System
RAFFLE_AUTO_DRAW=true                          # Auto-draw winner on 1st of month
RAFFLE_ANNOUNCEMENT_CHANNEL_ID=123456789       # Channel for raffle announcements

# Optional: Slot Call Tracker
SLOT_CALLS_CHANNEL_ID=123456789                # Discord channel for slot call notifications
BOT_AUTH_TOKEN=your_secret_token                # Required for /bot/authorize endpoint (generate with: python -c "import secrets; print(secrets.token_urlsafe(32))")
```

**Note:** OAuth linking requires deploying the OAuth server (see [docs/OAUTH_SETUP.md](docs/OAUTH_SETUP.md)).

**Kick Chat Responses:** To enable automatic responses in Kick chat when users use `!call` or `!sr`:

The bot uses **session-based authentication** (more reliable than OAuth). Follow these steps:

1. **Generate and set BOT_AUTH_TOKEN:**
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```
   - Set this as `BOT_AUTH_TOKEN` in your environment variables
   - Keep this secret - it protects the bot authorization endpoint

2. **Get Session Tokens (Bearer + XSRF + Cookies):**
   
   See **[KICK_SESSION_AUTH_GUIDE.md](KICK_SESSION_AUTH_GUIDE.md)** for detailed instructions.
   
   Quick steps:
   - Log into kick.com as your bot account in browser
   - Open DevTools (F12) → Network tab
   - Send a chat message
   - Find the `/messages/send/` request
   - Copy the `Authorization`, `X-CSRF-Token`, and `Cookie` headers
   - Run: `python scripts/update_session_tokens.py`
   - Paste the tokens when prompted

3. **Test the Connection:**
   ```bash
   python scripts/test_kick_session.py
   ```
   - Verifies tokens are valid
   - Sends a test message to Kick chat
   - Confirms everything is working

4. **Important Requirements:**
   - Bot account must **follow the channel** (required for follower-only chat)
   - If chat is subscriber-only, bot must be subscribed
   - Session tokens expire after ~30 days of inactivity (refresh as needed)
   - Tokens stored securely in database

**Raffle System:** See [docs/implementation/RAFFLE_SYSTEM_IMPLEMENTATION_PLAN.md](docs/implementation/RAFFLE_SYSTEM_IMPLEMENTATION_PLAN.md) for complete documentation on ticket earning and raffle mechanics.

4. **Initialize the database**
```bash
python scripts/setup_database.py
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

### 👤 User Commands

**Account Linking:**
- `!link` - Get OAuth link to connect your Kick account
- `!unlink` - Disconnect your Kick account

**Watchtime & Stats:**
- `!watchtime` - Check your watchtime
- `!leaderboard [top]` - View top viewers (default: 10, max: 25)

**Raffle System:**
- `!tickets` - Check your raffle ticket balance
- `!raffleboard [limit]` - View raffle leaderboard
- `!raffleinfo` - View current raffle period info
- `!linkshuffle <username>` - Link your Shuffle.com account (code: lele)

**Kick Chat (tracked automatically):**
- `!call <slot_name>` - Request slot call (posts to Discord)
- `!sr <slot_name>` - Same as !call

### 🛡️ Admin Commands

**Account Linking:**
- `!setup_link_panel` - Create button-based link panel
- `!linklogs on/off/status` - Toggle link attempt logging

**Watchtime Roles:**
- `!roles list` - Show all configured roles
- `!roles add <role> <minutes>` - Add watchtime role
- `!roles update <role> <minutes>` - Update role threshold
- `!roles remove <role>` - Remove role
- `!roles enable/disable <role>` - Toggle role
- `!roles members <role>` - List members with role

**Raffle Management:**
- `!rafflegive @user <amount> [reason]` - Award bonus tickets
- `!raffleremove @user <amount> [reason]` - Remove tickets
- `!raffledraw` - Draw winner manually
- `!rafflestats [@user]` - View raffle statistics
- `!rafflestart [start] [end]` - Start new period
- `!raffleend` - End current period
- `!rafflerestart` - End current & start new period
- `!rafflesetdate <start> <end>` - Set custom dates
- `!verifyshuffle @user <username>` - Verify Shuffle account

**Slot Request Panel:**
- `!slotpanel` - Create/update slot request panel (button-based UI)
- `!callblacklist add <user> [reason]` - Block user from !call
- `!callblacklist remove <user>` - Unblock user
- `!callblacklist list` - Show blocked users

**Guess the Balance:**
- `!gtbpanel` - Create/update GTB game panel (button-based UI)
- `!gtbstats` - View GTB game statistics

**System:**
- `!health` - Check bot status and diagnostics
- `!tracking on/off/status` - Toggle watchtime tracking
- `!dashboard` - Get link to admin dashboard (if enabled)

## 📋 Usage Examples

### 🎰 Slot Request Tracker
```
Admin: !slotpanel
Bot: Creates interactive panel with buttons to manage slot requests

[Kick viewer types in chat: !call Book of Dead]

Bot (auto-posts to Discord):
🎰 **Slot Request**
kickuser123 requested: **Book of Dead**
📅 2025-11-25 14:35:21

[Another viewer: !sr Gates of Olympus]

Bot (auto-posts to Discord):
🎰 **Slot Request**
slotfan456 requested: **Gates of Olympus**
📅 2025-11-25 14:37:08

Admin: Uses web dashboard to view all requests and manage settings
```

### 🎮 Guess the Balance Game
```
Admin: !gtbpanel
Bot: Creates GTB panel with buttons (Start Session, End Session, etc.)

[Admin starts session via button]
Bot: 🎮 GTB Session Started! Guess with !gtb <amount> in Kick chat

[Kick chat:]
Viewer: !gtb 1500
Bot: ✅ Your guess of $1,500.00 has been recorded!

Viewer2: !gtb 2000
Bot: ✅ Your guess of $2,000.00 has been recorded!

[Admin ends session and enters final balance: $1,650]
Bot: 🏆 Winner: Viewer ($1,500.00 was closest to $1,650.00)
     💰 Prize: $50.00
```

### 🌐 Dashboard Usage
```
Admin: Opens dashboard at configured URL
Dashboard: Shows analytics, recent activity, and management options

Navigation:
- 📊 Dashboard: Overview and statistics
- 🎫 Slot Requests: Manage requests and search slots
- 🎲 Raffle: View tickets and manage periods
- ⚙️ Settings: Configure bot behavior

Actions:
- Search for "Zeus vs Typhon" in slot library
- Blacklist user from making requests
- Award bonus raffle tickets
- Update watchtime role thresholds
```

## 📋 Linking Workflow Examples

**Admin sets up link panel:**
```
Admin: !setup_link_panel
Bot: Creates panel with "Link Account" button
```

**User links account:**
```
[User clicks "Link Account" button or types !link]

Bot (ephemeral message - only user sees it): 
🔗 Link Your Kick Account
[Button: 🎮 Link with Kick]

[User clicks → Authorizes on Kick → Redirected]
Bot: ✅ Successfully linked!
```

**Admin monitoring:**
```
Admin: !linklogs on
Bot: Link attempt logging enabled

[Successful link]
Bot: 🔗 Account Linked | @discorduser → kickuser123

[Failed link]
Bot: ❌ Link Failed | @discorduser | Error: Invalid user
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
6. Initialize database: `railway run python scripts/setup_database.py`

### Docker Compose (Local Testing with PostgreSQL)

```bash
# Start bot and PostgreSQL
docker-compose up -d

# Initialize database
docker-compose exec bot python scripts/setup_database.py

# View logs
docker-compose logs -f bot
```

### Database Initialization

After first deployment, initialize the database:

```bash
# For Railway
railway run python scripts/setup_database.py

# For Heroku
heroku run python scripts/setup_database.py

# For Docker
docker exec -it <container_id> python scripts/setup_database.py
```

Verify database health:
```bash
python scripts/health_check.py
```

## ⚙️ Configuration

### Role Thresholds

Roles are managed entirely through the `!roles` command or via the web dashboard - **no code changes needed!**

**Via Discord Commands:**
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

**Via Web Dashboard:**
- Navigate to Settings → Watchtime Roles
- Add, edit, or remove roles with a visual interface
- Changes take effect immediately

Roles are stored in the `watchtime_roles` table and checked dynamically.

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
- Check deployment logs for detailed error messages

### Kick chat responses not working
- Verify session tokens are set correctly (see Kick Session Auth Guide)
- Check that bot account follows the channel
- Ensure tokens haven't expired (~30 days of inactivity)
- Run `python scripts/test_kick_session.py` to verify connection
- Check that `BOT_AUTH_TOKEN` is set

### Dashboard not accessible
- Verify dashboard is deployed and URL is correct
- Check that authentication credentials are configured
- Ensure database connection is working
- Review dashboard deployment logs

### Database errors
- PostgreSQL is required (SQLite no longer supported)
- Verify `DATABASE_URL` is correct and database exists
- Run `python scripts/setup_database.py` to initialize tables

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

### Dashboard (Private Repository)
- **Web-based Admin Interface** - Complete management dashboard with analytics, configuration, and monitoring
- Contact for access to private dashboard repository

### Bonus Hunt (Kick chat → Discord buttons)
- **[integrations/bonus_hunt_kick_chat/](integrations/bonus_hunt_kick_chat/)** - Packaged integration for Kick slot requests with Discord button workflow (ready for reuse)

### Setup Guides
- **[docs/LINK_PANEL_QUICKSTART.md](docs/LINK_PANEL_QUICKSTART.md)** - Quick start guide for link panels
- **[docs/LINK_PANEL_SETUP.md](docs/LINK_PANEL_SETUP.md)** - Complete setup guide for link panels
- **[docs/OAUTH_SETUP.md](docs/OAUTH_SETUP.md)** - OAuth server setup and configuration guide
- **[KICK_SESSION_AUTH_GUIDE.md](KICK_SESSION_AUTH_GUIDE.md)** - Session-based Kick chat authentication
- **[docs/DEPLOYMENT_RAILWAY.md](docs/DEPLOYMENT_RAILWAY.md)** - Railway deployment guide

### Technical Documentation
- **[docs/LINK_PANEL_ARCHITECTURE.md](docs/LINK_PANEL_ARCHITECTURE.md)** - Technical architecture and flow diagrams
- **[docs/LINK_PANEL_IMPLEMENTATION.md](docs/LINK_PANEL_IMPLEMENTATION.md)** - Implementation details and code changes
- **[docs/SECURITY_IMPLEMENTATION.md](docs/SECURITY_IMPLEMENTATION.md)** - HMAC signature security details
- **[docs/implementation/RAFFLE_SYSTEM_IMPLEMENTATION_PLAN.md](docs/implementation/RAFFLE_SYSTEM_IMPLEMENTATION_PLAN.md)** - Complete raffle system documentation

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
#   T r i g g e r   r e d e p l o y  
 