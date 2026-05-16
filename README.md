# Kick Community Bot
## Premium Discord-Kick Integration Platform

A production-grade Discord bot designed specifically for Kick streamers, providing automated watchtime tracking, provably fair raffle systems, multi-platform gambling integration, and comprehensive community management tools.

**Status:** Active & Maintained | **License:** MIT | **Python:** 3.12+ | **Discord.py:** 2.7.0+

---

## Core Features

### Account Linking & Verification
- **OAuth 2.0 Authentication** - Secure one-click Kick account linking with HMAC-SHA256 cryptographic signatures
- **Button-Based Link Panels** - Ephemeral messaging for privacy-first user experience
- **Automatic Role Assignment** - Discord roles based on linked account status
- **Complete Audit Trail** - Link attempt logging and monitoring for security
- **10-Minute Expiring Tokens** - Time-limited authentication for enhanced security

### Automated Watchtime Tracking
- **Real-Time Monitoring** - Tracks all viewers across streams continuously
- **Persistent Storage** - PostgreSQL-backed watchtime database with complete history
- **Hourly Ticket Conversion** - Automatic 10 tickets/hour conversion to raffle system
- **Manual Management** - Administrative commands for watchtime adjustments
- **Role-Based Rewards** - Automatic Discord role assignment at configurable thresholds

### Advanced Raffle System
**Multi-Source Ticket Earning:**
- Watchtime: 10 tickets per hour streamed
- Gifted Subscriptions: 15 tickets per sub (real-time detection)
- Multi-Platform Wagers: Configurable tickets per $1,000 wagered
- Supported Platforms: Shuffle, Stake, Stake.us, and extensible to any platform
- Admin Bonuses: Manual ticket awards for special events

**Provably Fair Drawing:**
- Cryptographically random winner selection with complete transparency
- Weighted probability-based drawing with audit trails
- Historical records with win percentages and participant statistics
- Real-time leaderboard updates and analytics

**Period Management:**
- Flexible monthly/custom period scheduling
- Automated start/end dates with manual override capability
- Period-specific ticket isolation and statistics
- Comprehensive analytics per period with participant tracking

### Gifted Subscription Tracking
- Automatic detection of Kick gifted subscriptions
- Real-time ticket award system upon gifted sub event
- Community contribution leaderboards
- Complete gifted sub history and analytics dashboard

### Multi-Platform Gambling Integration
- **Configurable Platform Support** - Shuffle, Stake, Stake.us with extensible architecture
- **Multiple Campaign Codes** - Track multiple affiliate codes simultaneously (comma-separated)
- **Real-Time Monitoring** - Automatic wager detection via platform APIs
- **Verification System** - User account linking for gambling platforms
- **Customizable Rates** - Configure ticket rewards per platform and per streamer

### Slot Request Management
- **Interactive Panel** - Real-time slot request interface with Discord buttons
- **Kick Chat Integration** - `!call` and `!sr` commands for easy submissions
- **Channel Routing** - Automatic request posting to configured Discord channel
- **Blacklist System** - Manage restricted slots and users
- **Admin Workflow** - Approval/denial system with complete history

### Guess The Balance Game
- **Interactive Gameplay** - `!gtb <amount>` command in Kick chat
- **Discord Admin Panel** - Real-time game controls and monitoring
- **Closest Guess Algorithm** - Fair winner selection mechanism
- **Prize Distribution** - Automatic prize tracking and history
- **Analytics** - Complete game statistics and player performance data

### Custom Commands System
- **User-Defined Commands** - Create custom chat commands without code changes
- **Dynamic Responses** - Configurable responses with variable substitution
- **Permission Levels** - Role-based command restrictions
- **Audit Logging** - Track all command usage and modifications

### Giveaway System
- **Raffle Integration** - Entries based on raffle ticket balance
- **Fair Selection** - Random winner selection with provable fairness
- **Multi-Prize Support** - Run multiple giveaways simultaneously
- **Comprehensive Tracking** - Complete history and statistics

### Security & Compliance
- **OAuth 2.0** - Industry-standard authentication protocol
- **HMAC-SHA256** - Cryptographic signature verification
- **SQL Injection Protection** - Parameterized queries throughout
- **Environment-Based Configuration** - Zero hardcoded credentials
- **Input Validation** - All user inputs sanitized and validated
- **Role-Based Access Control** - Granular permission management

## Admin Dashboard (Separate Repository)

The bot includes integration with a comprehensive web-based admin dashboard for managing all bot features through an intuitive interface.

**Note:** The dashboard is maintained in a separate private repository: `admin-dashboard`

**Dashboard Features:**
- 📊 Real-time analytics and monitoring
- 🎫 Slot request management
- 🎲 Raffle administration
- ⚙️ Bot configuration and settings
- 👥 User management and statistics
- 🔐 Secure authentication and RBAC

**Access:** The dashboard repository is private and available upon request for authorized users only. Contact the project administrator for access.

---

## 📁 Project Structure
### Quick Start

#### Prerequisites
- Python 3.12+ ([Download](https://www.python.org/downloads/))
- Discord Bot Token ([Create at Discord Developer Portal](https://discord.com/developers/applications))
- Kick.com OAuth Application ([Register at Kick Developer](https://kick.com/developer/applications))
- PostgreSQL Database (Railway free tier or local installation)

#### Installation (Local Development)

1. **Clone Repository**
```bash
git clone https://github.com/madcats1337/kick-discord-bot.git
cd kick-discord-bot
```

2. **Create Virtual Environment**
```bash
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# or
.venv\Scripts\activate  # Windows
```

3. **Install Dependencies**
```bash
pip install -r requirements.txt
```

4. **Configure Environment Variables**
```bash
cp .env.example .env
# Edit .env with your credentials
```

5. **Initialize Database**
```bash
python scripts/setup_database.py
```

6. **Start Bot**
```bash
python combined_server.py
```

#### Environment Configuration

Create a `.env` file with the following variables:

```env
# Discord Bot
DISCORD_TOKEN=your_bot_token_here
DISCORD_GUILD_ID=your_guild_id_here

# Kick Channel
KICK_CHANNEL=your_kick_username

# Database (PostgreSQL Required)
DATABASE_URL=postgresql://user:password@localhost:5432/kick_bot

# OAuth Configuration
OAUTH_BASE_URL=https://your-deployment-url.com
KICK_CLIENT_ID=your_kick_client_id
KICK_CLIENT_SECRET=your_kick_client_secret
FLASK_SECRET_KEY=your_secret_key_here

# Optional: Raffle Configuration
RAFFLE_ANNOUNCEMENT_CHANNEL_ID=channel_id_here
RAFFLE_AUTO_DRAW=true

# Optional: Slot Requests
SLOT_CALLS_CHANNEL_ID=channel_id_here
BOT_AUTH_TOKEN=your_bot_auth_token

# Optional: Performance Tuning
WATCH_INTERVAL_SECONDS=60
ROLE_UPDATE_INTERVAL_SECONDS=600
```

### Production Deployment

#### Railway (Recommended - One-Click Deploy)
[Deploy to Railway →](https://railway.app/new)

1. Connect GitHub repository
2. Add PostgreSQL database plugin
3. Set environment variables
4. Deploy automatically with Railway

#### Docker & Docker Compose

```bash
# Start bot with PostgreSQL
docker-compose up -d

# Initialize database
docker-compose exec bot python scripts/setup_database.py
```

#### Manual Server Deployment

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for comprehensive deployment guides for Heroku, Render, and other platforms.

---

## Command Reference

### User Commands

| Command | Usage | Description |
|---------|-------|-------------|
| `!link` | - | Get OAuth link to connect Kick account |
| `!unlink` | - | Disconnect Kick account |
| `!watchtime` | - | View personal watchtime statistics |
| `!tickets` | - | Check raffle ticket balance |
| `!leaderboard` | [limit] | View top watchtime contributors |
| `!raffleboard` | [limit] | View raffle standings |
| `!raffleinfo` | - | View current raffle period details |
| `!commandlist` | - | View all user commands |

### Administrator Commands

#### Account Management
| Command | Usage | Description |
|---------|-------|-------------|
| `!setup_link_panel` | - | Deploy button-based link panel |
| `!linklogs` | on/off/status | Enable/disable link attempt logging |

#### Raffle Administration
| Command | Usage | Description |
|---------|-------|-------------|
| `!rafflegive` | @user amount [reason] | Award bonus tickets |
| `!raffleremove` | @user amount [reason] | Remove tickets |
| `!raffledraw` | - | Draw winner manually |
| `!rafflestats` | [@user] | View raffle statistics |
| `!rafflestart` | [start] [end] | Start new raffle period |
| `!raffleend` | - | End current period |
| `!convertwatchtime` | @user - | Convert watchtime to tickets |

#### Watchtime & Roles
| Command | Usage | Description |
|---------|-------|-------------|
| `!roles list` | - | Show configured roles |
| `!roles add` | @role minutes | Add watchtime role |
| `!roles update` | @role minutes | Update role threshold |
| `!roles remove` | @role | Remove role |

#### Slot Requests
| Command | Usage | Description |
|---------|-------|-------------|
| `!slotpanel` | - | Deploy slot request panel |
| `!callblacklist add` | user [reason] | Block user from requests |
| `!callblacklist remove` | user | Unblock user |

#### System Commands
| Command | Usage | Description |
|---------|-------|-------------|
| `!health` | - | Check bot status and diagnostics |
| `!admincommands` | - | View all admin commands |

### Kick Chat Commands

| Command | Usage | Description |
|---------|-------|-------------|
| `!call` | slot_name | Request slot call |
| `!sr` | slot_name | Slot request (alias) |
| `!gtb` | amount | Guess the balance game |

---

## Project Architecture

```
kick-discord-bot/
├── bot.py                     # Main Discord bot entry point
├── combined_server.py         # Bot + Flask OAuth server
├── requirements.txt           # Python dependencies
├── core/
│   ├── kick_api.py           # Kick.com API integration
│   └── oauth_server.py       # Flask OAuth server
├── features/
│   ├── custom_commands/      # User-defined commands
│   ├── games/                # GTB & gambling games
│   ├── giveaway/             # Giveaway system
│   ├── linking/              # Account linking
│   ├── messaging/            # Timed messages
│   └── slot_requests/        # Slot management
├── raffle_system/
│   ├── commands.py           # Raffle Discord commands
│   ├── database.py           # Raffle database ops
│   ├── scheduler.py          # Auto-draw scheduler
│   ├── gifted_sub_tracker.py # Gifted sub tracking
│   └── shuffle_tracker.py    # Gambling tracking
├── utils/                    # Shared utilities
├── scripts/                  # Setup & maintenance scripts
├── docs/                     # Comprehensive documentation
└── config/                   # Deployment configs
```

---

## Configuration & Setup Guides

### OAuth & Account Linking
See [docs/OAUTH_SETUP.md](docs/OAUTH_SETUP.md) for comprehensive OAuth configuration.

### Raffle System
See [docs/RAFFLE_MANAGEMENT_GUIDE.md](docs/RAFFLE_MANAGEMENT_GUIDE.md) for raffle administration.

### Kick Session Authentication
See [docs/KICK_SESSION_AUTH_GUIDE.md](docs/KICK_SESSION_AUTH_GUIDE.md) for Kick chat integration.

### Gambling Platform Integration
See [docs/WAGER_TRACKING_SETUP.md](docs/WAGER_TRACKING_SETUP.md) for multi-platform setup.

---

## Troubleshooting

### OAuth Linking Issues
- **403 Forbidden**: Verify `FLASK_SECRET_KEY` is set and `KICK_CLIENT_ID`/`KICK_CLIENT_SECRET` are correct
- **Invalid Redirect URI**: Ensure `OAUTH_BASE_URL` matches your deployment URL
- **Link Attempts Not Logging**: Check that `link_logs_config` table exists with `!linklogs on`

### Watchtime & Roles
- **Roles Not Assigned**: Verify bot's role is positioned above reward roles in Discord hierarchy
- **Watchtime Not Updating**: Check `KICK_CHANNEL` matches exact Kick username; verify API access
- **Missing Users**: Run `!fixwatchtime` to repair tracking inconsistencies

### Database Issues
- **Connection Failed**: Verify `DATABASE_URL` is correct and database service is running
- **Schema Issues**: Run `python scripts/setup_database.py` to initialize/repair tables
- **Performance Slow**: Check database indexes; optimize queries in raffle queries if needed

### System Diagnostics
Run `!health` command to display:
- Bot connection status
- Database connectivity
- Discord API latency
- System uptime
- Recent error log

---

## Database Schema

### Core Tables
- **users** - Discord/Kick user mappings with linked accounts
- **watchtime** - Viewer watchtime tracking with timestamps
- **links** - OAuth linked account storage
- **oauth_states** - PKCE flow state tokens
- **oauth_notifications** - Link attempt audit trail

### Raffle Tables
- **raffle_periods** - Raffle period management
- **raffle_tickets** - User ticket balances per period
- **raffle_draws** - Historical draw records with winners
- **raffle_leaderboards** - Real-time ranking data
- **gifted_subs** - Gifted subscription tracking
- **shuffle_wagers** - Multi-platform gambling wagers
- **watchtime_conversions** - Hourly to ticket conversions

### System Tables
- **link_panels** - Deployed button panels
- **watchtime_roles** - Configurable role thresholds
- **custom_commands** - User-defined commands
- **giveaways** - Active giveaway records
- **slot_blacklist** - Restricted users/slots

---

## Technology Stack

| Component | Version | Purpose |
|-----------|---------|---------|
| Python | 3.12+ | Runtime environment |
| Discord.py | 2.7.0+ | Discord API wrapper |
| Flask | 3.1.3+ | OAuth server & web endpoints |
| SQLAlchemy | 2.0.36+ | Database ORM |
| PostgreSQL | 14+ | Production database |
| Redis | 7.0+ | Message queue (optional) |
| Gunicorn | 23.0.0+ | Production WSGI server |

---

## Security Considerations

### In Production
✅ Use PostgreSQL with encrypted connections
✅ Store all credentials in environment variables
✅ Enable HTTPS for OAuth server
✅ Use strong `FLASK_SECRET_KEY` (32+ characters)
✅ Rotate tokens immediately if exposed
✅ Monitor link attempt logs regularly
✅ Keep dependencies updated

### Best Practices
- Never commit `.env` to version control
- Use environment variable secrets management (Railway, GitHub Secrets, etc.)
- Review `!linklogs` output for suspicious activity
- Test in staging before production deployment
- Monitor error logs and set up alerts
- Implement rate limiting on critical endpoints

---

## Documentation

Comprehensive documentation is available in the `docs/` directory:

### Setup & Configuration
- [OAUTH_SETUP.md](docs/OAUTH_SETUP.md) - OAuth 2.0 configuration
- [KICK_SESSION_AUTH_GUIDE.md](docs/KICK_SESSION_AUTH_GUIDE.md) - Kick chat authentication
- [DEPLOYMENT.md](docs/DEPLOYMENT.md) - Deployment guides (Railway, Heroku, Docker)
- [DEPLOYMENT_GUIDE.md](docs/DEPLOYMENT_GUIDE.md) - Complete setup walkthrough

### Administration
- [RAFFLE_MANAGEMENT_GUIDE.md](docs/RAFFLE_MANAGEMENT_GUIDE.md) - Raffle system administration
- [WAGER_TRACKING_SETUP.md](docs/WAGER_TRACKING_SETUP.md) - Gambling platform configuration
- [BOT_PERMISSIONS.md](docs/BOT_PERMISSIONS.md) - Required Discord permissions

### Technical Details
- [LINK_PANEL_ARCHITECTURE.md](docs/LINK_PANEL_ARCHITECTURE.md) - System architecture
- [LINK_PANEL_IMPLEMENTATION.md](docs/LINK_PANEL_IMPLEMENTATION.md) - Implementation details
- [SECURITY_IMPLEMENTATION.md](docs/SECURITY_IMPLEMENTATION.md) - Security architecture
- [BOT_SUMMARY.md](docs/BOT_SUMMARY.md) - Feature overview

### Legal & Compliance
- [TERMS_OF_SERVICE.md](TERMS_OF_SERVICE.md) - Terms of service
- [PRIVACY_POLICY.md](PRIVACY_POLICY.md) - Privacy policy
- [SECURITY.md](docs/SECURITY.md) - Security audit report

---

## FAQ

**Q: Can I use this with other streaming platforms?**
A: This bot is optimized for Kick.com but can be adapted. The architecture is modular and extensible.

**Q: What database do I need?**
A: PostgreSQL is required for production. SQLite is no longer supported due to concurrency requirements.

**Q: How often are watchtime updates?**
A: Configurable via `WATCH_INTERVAL_SECONDS` (default: 60 seconds). Role updates via `ROLE_UPDATE_INTERVAL_SECONDS` (default: 600 seconds).

**Q: Is the raffle drawing fair?**
A: Yes. Drawings use provably fair algorithms with complete transparency and audit trails. All draws are cryptographically random and logged.

**Q: Can I customize ticket rates?**
A: Yes. Configure rates per platform and per period via environment variables and raffle commands.

**Q: What happens if the bot goes down?**
A: The bot resumes tracking from where it left off. Watchtime data is persistent in PostgreSQL.

**Q: Can multiple admins manage the bot?**
A: Yes. Use Discord role-based permissions to grant admin access to multiple users.

---

## Contributing

Contributions welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/your-feature`)
3. Make your changes
4. Commit with clear messages (`git commit -m 'Add feature'`)
5. Push to branch (`git push origin feature/your-feature`)
6. Open a Pull Request

### Development Setup
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# Configure .env with test credentials
python bot.py
```

---

## Support & Resources

### Documentation
- [Discord.py Documentation](https://discordpy.readthedocs.io/)
- [Kick Developer Docs](https://kick.com/api)
- [PostgreSQL Docs](https://www.postgresql.org/docs/)

### Community
- Open GitHub Issues for bug reports
- Open GitHub Discussions for feature requests
- Check existing documentation before asking

### Deployment Support
- [Railway Documentation](https://docs.railway.app/)
- [Discord.py Installation](https://discordpy.readthedocs.io/en/latest/intro.html#installing)
- PostgreSQL: [Installation](https://www.postgresql.org/download/) | [Docs](https://www.postgresql.org/docs/)

---

## License

**MIT License** - Feel free to modify and use for your community.

See [LICENSE](LICENSE) file for full terms.

---

## Acknowledgments

Built with:
- [Discord.py](https://github.com/Rapptz/discord.py) - Discord API library
- [Flask](https://flask.palletsprojects.com/) - Web framework
- [SQLAlchemy](https://www.sqlalchemy.org/) - Database ORM
- [PostgreSQL](https://www.postgresql.org/) - Database

---

## Changelog & Version History

Check [GitHub Releases](https://github.com/madcats1337/kick-discord-bot/releases) for the latest version and changelog.

---

**Built with ❤️ for the Kick.com community**

*For issues, feature requests, or contributions, visit the [GitHub repository](https://github.com/madcats1337/kick-discord-bot)*
