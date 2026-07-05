"""Per-server dashboard base-URL derivation.

The dashboard serves every server on its own subdomain
(https://<subdomain>.<base-domain>) — both the viewer-facing pages and the
/api/* endpoints the bot calls (clip create, buffer start/stop). Deriving the
base from `servers.subdomain` replaces the hand-maintained `dashboard_url`
bot_setting, which went stale on the lelebot.xyz → wagerlabs.app domain move.
"""

import logging
import os

from sqlalchemy import text

logger = logging.getLogger(__name__)

# Env override first; defaults to the production domain (lelebot.xyz was
# retired in the Wagerlabs rebrand).
PUBLIC_BASE_DOMAIN = (os.getenv("PUBLIC_BASE_DOMAIN") or os.getenv("BASE_DOMAIN") or "wagerlabs.app").strip().lower()


def get_server_base_url(engine, guild_id):
    """https://<subdomain>.<PUBLIC_BASE_DOMAIN> for this server, or None when
    the server has no registered subdomain (or the lookup fails)."""
    if not guild_id or engine is None:
        return None
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT subdomain FROM servers WHERE discord_server_id = :gid LIMIT 1"),
                {"gid": int(guild_id)},
            ).fetchone()
        subdomain = (row[0] or "").strip().lower() if row else ""
        if not subdomain:
            return None
        return f"https://{subdomain}.{PUBLIC_BASE_DOMAIN}"
    except Exception as e:
        logger.warning(f"[ServerURL] Could not resolve base URL for guild {guild_id}: {e}")
        return None
