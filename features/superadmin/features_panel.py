"""Feature-list panel. Reads features_title + features_body from bot_settings
under the official guild."""

import logging

import discord

from ._panel_base import GlobalPanel, get_setting

logger = logging.getLogger(__name__)

_DESC_CAP = 4096


class FeaturesPanel(GlobalPanel):
    PANEL_TYPE = "features"

    def build_embed(self, data=None) -> discord.Embed:
        title = get_setting(self.engine, "features_title") or "✨ Features"
        body = (get_setting(self.engine, "features_body") or "").strip()
        if not body:
            body = "The feature list hasn't been written yet."
        if len(body) > _DESC_CAP:
            body = body[: _DESC_CAP - 1] + "…"
        return discord.Embed(title=title, description=body, color=0xFACC15)


async def setup_features_panel_system(bot, engine):
    from ._panel_base import OFFICIAL_GUILD_ID

    return {OFFICIAL_GUILD_ID: FeaturesPanel(bot, engine)}
