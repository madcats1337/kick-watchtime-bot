"""Server-rules panel (Components V2). Reads rules_title + rules_list (JSON
array) from bot_settings under the official guild."""

import json
import logging

import discord

from ._panel_base import ACCENT, TEXT_CAP, GlobalPanel, get_setting, text_block

logger = logging.getLogger(__name__)


class RulesPanel(GlobalPanel):
    PANEL_TYPE = "rules"

    def build_view(self, data=None) -> discord.ui.LayoutView:
        title = get_setting(self.engine, "rules_title") or "📜 Server Rules"
        raw = get_setting(self.engine, "rules_list") or "[]"
        try:
            rules = json.loads(raw)
            if not isinstance(rules, list):
                rules = []
        except Exception:
            rules = []

        lines = [f"**{i}.** {str(rule).strip()}" for i, rule in enumerate(rules, 1) if str(rule).strip()]
        body = "\n\n".join(lines) if lines else "No rules have been set yet."
        if len(body) > TEXT_CAP:
            body = body[: TEXT_CAP - 1] + "…"

        container = discord.ui.Container(accent_colour=ACCENT)
        container.add_item(text_block(f"# {title}"))
        container.add_item(discord.ui.Separator())
        container.add_item(text_block(body))

        view = discord.ui.LayoutView(timeout=None)
        view.add_item(container)
        return view


async def setup_rules_panel_system(bot, engine):
    from ._panel_base import OFFICIAL_GUILD_ID

    return {OFFICIAL_GUILD_ID: RulesPanel(bot, engine)}
