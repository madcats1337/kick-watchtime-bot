"""Shared base for the global super-admin panels.

These panels render with Discord **Components V2** (discord.py 2.6+): instead of
a classic embed, each panel sends a `discord.ui.LayoutView` containing a colored
`Container` of `TextDisplay` blocks (and, for the subscription-role panel, an
`ActionRow` with the claim button). A Components V2 message carries no embed and
no top-level content — it's the LayoutView only.

Each panel tracks its posted Discord message in the existing `link_panels` table
(free-text `panel_type`), keyed by the official guild id, so the redis
`_post_panel` move/re-attach logic works unchanged. Subclasses override
`PANEL_TYPE` and implement `build_view(data)`.
"""

import logging
import os

import discord
from sqlalchemy import text

logger = logging.getLogger(__name__)

OFFICIAL_GUILD_ID = int(os.getenv("OFFICIAL_GUILD_ID", "914986636629143562"))

# Brand accent used across the panels (matches the dashboard yellow).
ACCENT = 0xFACC15

# Component limits we defend against. A single TextDisplay can hold up to 4000
# chars; we keep a little headroom.
TEXT_CAP = 3900


def text_block(content):
    """A Components V2 markdown text block (replaces an embed's description)."""
    return discord.ui.TextDisplay(content if content else "​")


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

    # -- subclass hook ------------------------------------------------------
    def build_view(self, data=None) -> discord.ui.LayoutView:
        """Return the Components V2 LayoutView for this panel. Subclasses build a
        Container of TextDisplay blocks (+ an ActionRow for interactive panels)."""
        raise NotImplementedError

    def panel_files(self):
        """Optional discord.File attachments to send with the panel (e.g. a logo
        referenced by a MediaGallery via attachment://). Default: none."""
        return []

    # -- posting ------------------------------------------------------------
    async def create_panel(self, channel, data=None):
        try:
            view = self.build_view(data)
            files = self.panel_files()
            # Components V2: send the LayoutView only (no embed, no content). Any
            # panel_files() are attached so a MediaGallery can reference them.
            message = await channel.send(view=view, files=files) if files else await channel.send(view=view)
            self.panel_channel_id = channel.id
            self.panel_message_id = message.id
            self._save_panel_info(channel.id, message.id)
            logger.info(f"[{self.PANEL_TYPE}] Posted panel in #{getattr(channel, 'name', channel.id)}")
            return True
        except Exception as e:
            logger.error(f"[{self.PANEL_TYPE}] Failed to post panel: {e}")
            return False
