"""Shared base for the global super-admin panels.

Each panel tracks its posted Discord message in the existing `link_panels` table
(free-text `panel_type`), keyed by the official guild id, so the redis
`_post_panel` move/re-attach logic works unchanged. Subclasses override
`PANEL_TYPE` and implement `build_embed(data)` (+ optionally `build_view()`).
"""

import logging
import os

import discord
from sqlalchemy import text

logger = logging.getLogger(__name__)

OFFICIAL_GUILD_ID = int(os.getenv("OFFICIAL_GUILD_ID", "914986636629143562"))


def get_setting(engine, key, default=None):
    """Read a single bot_settings value for the official guild."""
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT value FROM bot_settings WHERE key = :k AND discord_server_id = :g"),
                {"k": key, "g": OFFICIAL_GUILD_ID},
            ).fetchone()
        if row and row[0] is not None:
            return row[0]
    except Exception as e:
        logger.warning(f"[SuperAdminPanel] get_setting({key}) failed: {e}")
    return default


class GlobalPanel:
    """Base class for a single-message global panel in the official guild."""

    PANEL_TYPE = "global"

    def __init__(self, bot, engine, guild_id=OFFICIAL_GUILD_ID):
        self.bot = bot
        self.engine = engine
        self.guild_id = guild_id
        self.panel_channel_id = None
        self.panel_message_id = None
        self._load_panel_info()

    # -- persistence (link_panels) -----------------------------------------
    def _load_panel_info(self):
        if not self.engine:
            return
        try:
            with self.engine.connect() as conn:
                row = conn.execute(
                    text(
                        """
                        SELECT channel_id, message_id FROM link_panels
                        WHERE guild_id = :g AND panel_type = :p
                        ORDER BY created_at DESC LIMIT 1
                        """
                    ),
                    {"g": self.guild_id, "p": self.PANEL_TYPE},
                ).fetchone()
            if row:
                self.panel_channel_id, self.panel_message_id = row
        except Exception as e:
            logger.error(f"[{self.PANEL_TYPE}] load panel info failed: {e}")

    def _save_panel_info(self, channel_id, message_id):
        if not self.engine:
            return
        try:
            with self.engine.begin() as conn:
                conn.execute(
                    text("DELETE FROM link_panels WHERE guild_id = :g AND panel_type = :p"),
                    {"g": self.guild_id, "p": self.PANEL_TYPE},
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO link_panels
                            (guild_id, channel_id, message_id, emoji, panel_type, discord_server_id, created_at)
                        VALUES (:g, :c, :m, '📌', :p, :g, CURRENT_TIMESTAMP)
                        """
                    ),
                    {"g": self.guild_id, "c": channel_id, "m": message_id, "p": self.PANEL_TYPE},
                )
        except Exception as e:
            logger.error(f"[{self.PANEL_TYPE}] save panel info failed: {e}")

    # -- subclass hooks -----------------------------------------------------
    def build_embed(self, data=None) -> discord.Embed:
        raise NotImplementedError

    def build_view(self):
        """Override to attach a persistent view. Default: static embed."""
        return None

    # -- posting ------------------------------------------------------------
    async def create_panel(self, channel, data=None):
        try:
            embed = self.build_embed(data)
            view = self.build_view()
            if view is not None:
                message = await channel.send(embed=embed, view=view)
            else:
                message = await channel.send(embed=embed)
            self.panel_channel_id = channel.id
            self.panel_message_id = message.id
            self._save_panel_info(channel.id, message.id)
            logger.info(f"[{self.PANEL_TYPE}] Posted panel in #{getattr(channel, 'name', channel.id)}")
            return True
        except Exception as e:
            logger.error(f"[{self.PANEL_TYPE}] Failed to post panel: {e}")
            return False
