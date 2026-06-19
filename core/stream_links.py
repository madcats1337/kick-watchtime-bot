"""
Platform-aware helpers for the `links` table (viewer identity).

After the add_platform_to_links migration, `links` holds one row per
(discord_id, discord_server_id, platform). A Discord user may link a Kick AND a
Twitch account in the same server; both credit the SAME discord_id downstream
(unified identity — watchtime/points/raffle tickets stay keyed off discord_id).

Use these helpers wherever a link is created/removed or a chat username must be
resolved to a discord_id, so the platform dimension is handled consistently.
"""

import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)


def upsert_link(engine, discord_id: int, username: str, guild_id: int, platform: str = "kick"):
    """Create/update a viewer's link for a platform (idempotent upsert)."""
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO links (discord_id, kick_name, discord_server_id, platform, linked_at)
                VALUES (:d, :u, :gid, :platform, CURRENT_TIMESTAMP)
                ON CONFLICT (discord_id, discord_server_id, platform) DO UPDATE
                SET kick_name = excluded.kick_name, linked_at = CURRENT_TIMESTAMP
                """
            ),
            {"d": discord_id, "u": username.lower(), "gid": guild_id, "platform": platform},
        )


def remove_link(engine, discord_id: int, guild_id: int, platform: str = None):
    """Remove a viewer's link. If platform is None, removes ALL platforms for the
    user in this server (full unlink); otherwise just the one platform."""
    with engine.begin() as conn:
        if platform is None:
            conn.execute(
                text("DELETE FROM links WHERE discord_id = :d AND discord_server_id = :gid"),
                {"d": discord_id, "gid": guild_id},
            )
        else:
            conn.execute(
                text("DELETE FROM links WHERE discord_id = :d AND discord_server_id = :gid AND platform = :p"),
                {"d": discord_id, "gid": guild_id, "p": platform},
            )


def resolve_discord_id(engine, username: str, guild_id: int, platform: str):
    """Resolve a chat username on a given platform to the linked discord_id, or None."""
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT discord_id FROM links
                WHERE LOWER(kick_name) = :u AND discord_server_id = :gid AND platform = :p
                """
            ),
            {"u": username.lower(), "gid": guild_id, "p": platform},
        ).fetchone()
    return row[0] if row else None


def resolve_canonical_identity(engine, username: str, guild_id: int, platform: str):
    """
    Resolve (username, platform) -> (discord_id, canonical_username) under the
    unified-identity model.

    A viewer may have both a Kick and a Twitch link. Downstream tables
    (watchtime/user_points/raffle_tickets) are keyed by username STRING, so to
    keep a single shared balance we pick a CANONICAL username per Discord user:
    the earliest-linked row for that server (prefer Kick, then by linked_at).
    Both platforms' chat then credit that one canonical username.

    Returns (discord_id, canonical_username) or (None, None) if not linked.
    """
    discord_id = resolve_discord_id(engine, username, guild_id, platform)
    if discord_id is None:
        return None, None
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT kick_name FROM links
                WHERE discord_id = :d AND discord_server_id = :gid
                ORDER BY (platform <> 'kick'), linked_at ASC
                LIMIT 1
                """
            ),
            {"d": discord_id, "gid": guild_id},
        ).fetchone()
    canonical = row[0] if row else username.lower()
    return discord_id, canonical
