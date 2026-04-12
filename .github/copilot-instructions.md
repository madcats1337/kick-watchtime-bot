# LeleBot Discord Bot - Copilot Instructions

## Architecture Overview

This is a **Discord.py bot** that tracks Kick.com viewer watchtime, manages raffles, and integrates with a companion Flask admin dashboard.

**Two-repo ecosystem:**
1. **Kick-discord-bot** (this repo) - Discord bot with Kick chat integration
2. **Admin-Dashboard** (companion) - Flask web admin interface

Both share **PostgreSQL** and sync via **Redis pub/sub**.

## Data Flow

```
Kick.com Webhooks/WS → Bot → PostgreSQL → Dashboard reads
Dashboard changes → Redis pub/sub → Bot subscribes → Live update
```

## Key Patterns

### Multi-Server Support
All database operations MUST filter by `discord_server_id`:
```python
with engine.connect() as conn:
    result = conn.execute(text("""
        SELECT * FROM raffle_tickets
        WHERE discord_server_id = :server_id
    """), {"server_id": guild.id})
```

### Bot Settings Per Guild
Use `BotSettingsManager` for server-specific configs:
```python
from utils.bot_settings import BotSettingsManager
settings = BotSettingsManager(engine, guild_id)
kick_channel = settings.get('kick_channel')
```

### Redis Subscriber Pattern
Bot listens for dashboard events in [redis_subscriber.py](redis_subscriber.py):
```python
# Dashboard publishes → Bot receives and reacts
# Channel format: 'dashboard:{feature}'
# Example: 'dashboard:slot_requests' with action 'toggle'
```

Start subscriber in `on_ready()`:
```python
asyncio.create_task(start_redis_subscriber(bot))
```

## File Structure

| Directory | Purpose |
|-----------|---------|
| `core/` | Kick API, webhooks, OAuth server |
| `features/` | Bot features: slot_requests, games, giveaway, messaging |
| `raffle_system/` | Monthly raffle logic, ticket tracking, Shuffle integration |
| `utils/` | Bot settings, error helpers |

## Feature Modules

Each feature follows this pattern in `features/`:
```python
# features/slot_requests/slot_calls.py
def setup_slot_call_tracker(bot, engine):
    """Called from bot.py during startup"""
    # Register listeners, commands, etc.
```

Called from [bot.py](bot.py):
```python
setup_slot_call_tracker(bot, engine)
```

## Running Locally

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
# Set DISCORD_TOKEN, DATABASE_URL, REDIS_URL, KICK_* vars in .env
python bot.py
```

## Deployment

- **Platform**: Railway with `Procfile: worker: python bot.py`
- **Note**: Runs as `worker` (not `web`) - no HTTP server needed

## Common Tasks

### Adding a new bot feature
1. Create module in `features/{category}/`
2. Add `setup_*` function accepting `(bot, engine)`
3. Import and call in [bot.py](bot.py)

### Handling dashboard events
Add handler in [redis_subscriber.py](redis_subscriber.py):
```python
async def handle_my_feature(action: str, data: dict):
    if action == 'toggle':
        # React to dashboard toggle
        pass
```

### Database migrations
Raffle schema in [raffle_system/database.py](raffle_system/database.py).
Dashboard runs migrations; bot expects schema to exist.

## Kick Integration

- **Webhooks**: [core/kick_webhooks.py](core/kick_webhooks.py) - handles chat, subs, gifted subs
- **API**: [core/kick_api.py](core/kick_api.py) - fetch chatroom ID, stream status
- **OAuth**: [core/oauth_server.py](core/oauth_server.py) - link Discord ↔ Kick accounts
