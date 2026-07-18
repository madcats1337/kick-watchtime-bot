"""
Standalone (Discord-less) workspace discovery.

The dashboard's email accounts can create workspaces that are normal
`servers` rows keyed by a synthetic NEGATIVE discord_server_id — no Discord
guild exists for them, so they never appear in bot.guilds. The bot still
serves their KICK/TWITCH chat features (slot requests, Guess the Balance):
bot.py's startup + the Redis settings-reload hook use this module to find
which standalone workspaces have a Kick channel configured and spin up the
same per-server chat runtime (settings manager, slot tracker, GTB manager,
kickpython websocket) that real guilds get.

Everything Discord-side (panels, announcements, role features) stays off for
these ids: the chat pipeline is registry/dict-keyed and its Discord posts are
already best-effort/None-guarded, and utils.subscription_tier subtracts the
Discord-dependent features for negative ids.
"""

import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)


def standalone_chat_servers(engine):
    """Standalone workspaces with a configured Kick channel.

    Returns a list of (discord_server_id, server_name, kick_channel) tuples;
    empty on any error (startup must never fail on this).
    """
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT s.discord_server_id, s.server_name, bs.value
                    FROM servers s
                    JOIN bot_settings bs
                      ON bs.discord_server_id = s.discord_server_id
                     AND bs.key = 'kick_channel'
                    WHERE s.discord_server_id < 0
                      AND COALESCE(bs.value, '') <> ''
                    """
                )
            ).fetchall()
        return [(int(r[0]), r[1] or str(r[0]), r[2]) for r in rows]
    except Exception as e:
        logger.info(f"[Standalone] discovery query failed: {e}")
        return []
