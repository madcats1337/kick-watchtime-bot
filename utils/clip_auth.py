"""Resolve the bot -> dashboard clip API key.

This is a single system secret the operator controls, NOT a per-server value. It is
read from the environment first (CLIPS_API_KEY, then BOT_API_KEY) and only falls back
to a legacy per-server bot_settings.bot_api_key value for backwards compatibility during
migration.

Set CLIPS_API_KEY on the bot service to the SAME value as the dashboard's CLIPS_API_KEY
env var; the /api/clips/* endpoints authenticate the X-API-Key header against it. Once
the env var is in place you can delete any old bot_api_key rows from bot_settings.
"""

import os


def get_clip_api_key(db_fallback: str = "") -> str:
    """Return the clip API key: env-controlled, with the legacy DB value as fallback."""
    return os.getenv("CLIPS_API_KEY") or os.getenv("BOT_API_KEY") or (db_fallback or "")
