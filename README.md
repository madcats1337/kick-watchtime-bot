<p align="center">
  <img src="assets/branding/wagerlabs_logo.png" alt="Wagerlabs" width="160">
</p>

<h1 align="center">Wagerlabs Bot</h1>

<p align="center">
  The real-time bot and event service behind <a href="https://wagerlabs.app/">Wagerlabs</a>, a stream-automation platform for Kick and Twitch creators.
</p>

## Overview

Wagerlabs Bot connects streaming communities across Kick, Twitch, and optional Discord servers. It handles chat activity, viewer identity, rewards, interactive games, live notifications, and platform events while staying synchronized with the Wagerlabs dashboard.

This repository contains the bot-side service. It is one part of the hosted Wagerlabs platform and works with the dashboard/API, a shared PostgreSQL database, and Redis messaging. It is not a standalone drop-in Discord bot.

## What it does

- **Kick and Twitch integration:** Connects creator channels, processes chat and platform events, sends chat messages, and supports stream-live workflows.
- **Optional Discord integration:** Provides community panels, role rewards, account linking, announcements, and interactive management features.
- **Cross-platform identity:** Resolves linked Kick and Twitch handles to one viewer identity so watchtime, points, purchases, and limits remain consistent.
- **Activity-based watchtime:** Awards watchtime from recent chat participation, with anti-farming controls and configurable reward thresholds.
- **Points and shop:** Maintains a shared viewer balance across linked platforms and supports Discord-based point-shop purchases.
- **Provably fair systems:** Powers raffles, giveaways, and slot-request selections using recorded commit-reveal data that can be independently verified.
- **Multi-source raffle tickets:** Supports activity rewards, watchtime conversion, gifted subscriptions, verified Shuffle and Howl wagers, and manual awards.
- **Stream interaction:** Includes slot requests, Guess the Balance, custom commands, timed messages, viewer games, and configurable chat automation.
- **Live notifications:** Coordinates Kick and Twitch go-live events with Discord announcements and dashboard-managed settings.
- **Real-time synchronization:** Receives dashboard actions through authenticated Redis pub/sub and publishes updates used by the dashboard and OBS workflows.

## Platform architecture

```text
Kick / Twitch / Discord
          |
          v
   Wagerlabs Bot <---- Redis ----> Wagerlabs Dashboard / API
          \                           /
           +---- shared PostgreSQL --+
                                      |
                                      v
                         Browser extension / OBS widgets
```

Tenant data is scoped per workspace. The bot and dashboard share the same database schema, while signed Redis messages coordinate settings, notifications, drawings, purchases, and other real-time actions between services.

## Development setup

### Requirements

- Python 3.11 or newer
- PostgreSQL
- Redis
- Credentials for the platform integrations you intend to run
- FFmpeg when developing clip or media-buffer features

### Install

```bash
git clone https://github.com/madcats1337/Wagerlabs-bot.git
cd Wagerlabs-bot

python -m venv .venv
```

Activate the virtual environment:

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

```bash
# macOS or Linux
source .venv/bin/activate
```

Then install the dependencies:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Copy [`.env.example`](.env.example) to `.env`, and configure the services you need. Important settings include:

| Setting | Purpose |
| --- | --- |
| `DATABASE_URL` | Shared PostgreSQL connection |
| `REDIS_URL` | Dashboard-to-bot messaging and real-time events |
| `REDIS_MSG_SECRET` | HMAC authentication shared with the dashboard |
| `DISCORD_TOKEN` | Discord bot authentication when Discord is enabled |
| `BOT_PUBLIC_URL` | Public OAuth and webhook host for this service |
| Kick/Twitch credentials | OAuth, chat, webhook, and EventSub access |

Never commit credentials or a populated `.env` file.

### Run

```bash
python combined_server.py
```

The production entry point starts the Discord/chat worker and the Flask OAuth and webhook service. Railway deployment uses the same entry point through the repository's Docker configuration.

### Test

```bash
python -m pytest
```

Some integration tests require PostgreSQL, Redis, or platform-specific environment variables. Use isolated test services and credentials; do not point development tests at production data.

## Security and fairness

- OAuth credentials, webhook secrets, and API tokens are read from environment variables.
- Production Redis messages can be HMAC-signed to prevent unauthorized cross-service actions.
- Workspace data is tenant-scoped throughout the shared database.
- Raffle and slot-request outcomes retain the data required for public verification.
- Platform webhooks are signature-verified before trusted events are processed.

Please report security issues privately to [support@wagerlabs.app](mailto:support@wagerlabs.app) rather than opening a public issue.

## Links

- [Wagerlabs](https://wagerlabs.app/)
- [Terms of Service](TERMS_OF_SERVICE.md)
- [Privacy Policy](PRIVACY_POLICY.md)
- [Issue tracker](https://github.com/madcats1337/Wagerlabs-bot/issues)

## Repository scope

The Wagerlabs admin dashboard, browser extension, and public support content are maintained as separate components. Changes to shared database tables or Redis event contracts must remain compatible with both the bot and dashboard services.
