"""Server-rules panel. Reads rules_title + rules_list (JSON array) from
bot_settings under the official guild."""

import json
import logging

import discord

from ._panel_base import GlobalPanel, get_setting

logger = logging.getLogger(__name__)

_DESC_CAP = 4096


class RulesPanel(GlobalPanel):
    PANEL_TYPE = "rules"

    def build_embed(self, data=None) -> discord.Embed:
        title = get_setting(self.engine, "rules_title") or "📜 Server Rules"
        raw = get_setting(self.engine, "rules_list") or "[]"
        try:
            rules = json.loads(raw)
            if not isinstance(rules, list):
                rules = []
        except Exception:
            rules = []

        lines = [f"**{i}.** {str(rule).strip()}" for i, rule in enumerate(rules, 1) if str(rule).strip()]
        description = "\n\n".join(lines) if lines else "No rules have been set yet."
        if len(description) > _DESC_CAP:
            description = description[: _DESC_CAP - 1] + "…"
        return discord.Embed(title=title, description=description, color=0xFACC15)


async def setup_rules_panel_system(bot, engine):
    from ._panel_base import OFFICIAL_GUILD_ID

    return {OFFICIAL_GUILD_ID: RulesPanel(bot, engine)}
