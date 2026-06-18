"""Shared helpers for raffle ticket reward settings."""

import re

from sqlalchemy import text


def _normalize_ticket_value(raw_value, default_value):
    """Extract a numeric ticket value from DB strings like '20 tickets ...'."""
    if raw_value is None:
        return default_value

    raw = str(raw_value).strip()
    if not raw:
        return default_value

    match = re.search(r"\d+(?:\.\d+)?", raw)
    if not match:
        return default_value

    number_text = match.group(0)
    try:
        number = float(number_text)
        if number.is_integer():
            return str(int(number))
        return str(number).rstrip("0").rstrip(".")
    except Exception:
        return number_text


def _get_setting_value(conn, key, server_id):
    result = conn.execute(
        text(
            """
            SELECT value FROM bot_settings
            WHERE key = :key
              AND (discord_server_id = :server_id OR discord_server_id IS NULL)
            ORDER BY CASE WHEN discord_server_id = :server_id THEN 0 ELSE 1 END
            LIMIT 1
            """
        ),
        {"key": key, "server_id": server_id},
    ).fetchone()
    return result[0] if result else None


# Display names for the supported wager platforms (wager_platform_name is
# stored lowercase, e.g. "shuffle" / "howl"). Falls back to a title-cased
# version of whatever value is stored so an unknown platform still renders.
_PLATFORM_DISPLAY_NAMES = {
    "shuffle": "Shuffle",
    "howl": "Howl",
}


def platform_display_name(settings, default="Shuffle"):
    """Return the user-facing wager-platform name (e.g. "Shuffle" / "Howl").

    Reads `wager_platform_name` from a BotSettingsManager. Used so raffle
    messages show the platform the server is actually configured for instead
    of a hardcoded "Shuffle".
    """
    if settings is None:
        return default
    try:
        raw = (settings.get("wager_platform_name") or "").strip().lower()
    except Exception:
        return default
    if not raw:
        return default
    return _PLATFORM_DISPLAY_NAMES.get(raw, raw.title())


def get_ticket_reward_settings(engine, server_id=None, logger=None):
    """Return (watchtime_tickets, gifted_sub_tickets, wager_tickets) as display-safe strings."""
    watchtime_tickets = "10"
    gifted_sub_tickets = "15"
    wager_tickets = "20"

    try:
        with engine.begin() as conn:
            watchtime_raw = _get_setting_value(conn, "watchtime_tickets_per_hour", server_id)
            gifted_raw = _get_setting_value(conn, "gifted_sub_tickets", server_id)
            wager_raw = _get_setting_value(conn, "shuffle_tickets_per_1000", server_id)

            watchtime_tickets = _normalize_ticket_value(watchtime_raw, watchtime_tickets)
            gifted_sub_tickets = _normalize_ticket_value(gifted_raw, gifted_sub_tickets)
            wager_tickets = _normalize_ticket_value(wager_raw, wager_tickets)
    except Exception as e:
        if logger:
            logger.warning(f"Failed to fetch ticket reward settings from DB for server {server_id}: {e}")

    return watchtime_tickets, gifted_sub_tickets, wager_tickets
