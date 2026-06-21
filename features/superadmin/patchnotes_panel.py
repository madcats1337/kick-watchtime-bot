"""Patch-notes / changelog panel.

Content is NOT stored in the DB — the dashboard forwards the latest `release`
object from the /patch-notes page in the post_panel event data. Shape:
  {version, date, tag, tone, groups: [{category, title, entries: [{html}]}]}
"""

import logging
import re

import discord

from ._panel_base import GlobalPanel

logger = logging.getLogger(__name__)

# Discord field values cap at 1024 chars.
_FIELD_CAP = 1024


def _html_to_text(html: str) -> str:
    """Reduce the inline changelog HTML to plain text (markdown-ish).

    Entries use only <strong>/<em>/<code> and a few HTML entities; keep bold as
    Discord **bold**, render code spans with backticks, drop everything else."""
    if not html:
        return ""
    s = html
    s = re.sub(r"</?strong>", "**", s)
    s = re.sub(r"</?b>", "**", s)
    s = re.sub(r"</?em>", "*", s)
    s = re.sub(r"</?i>", "*", s)
    s = re.sub(r"</?code>", "`", s)
    s = re.sub(r"<[^>]+>", "", s)  # strip any remaining tags
    # Common entities present in the source data.
    for ent, ch in (
        ("&rsquo;", "’"),
        ("&lsquo;", "‘"),
        ("&ldquo;", "“"),
        ("&rdquo;", "”"),
        ("&amp;", "&"),
        ("&lt;", "<"),
        ("&gt;", ">"),
        ("&nbsp;", " "),
    ):
        s = s.replace(ent, ch)
    return s.strip()


class PatchNotesPanel(GlobalPanel):
    PANEL_TYPE = "patchnotes"

    def build_embed(self, data=None) -> discord.Embed:
        release = (data or {}).get("release") or {}
        version = release.get("version") or "Patch Notes"
        date = release.get("date") or ""
        tag = release.get("tag") or ""

        title = f"📋 {version}"
        if tag:
            title += f" — {tag}"
        embed = discord.Embed(title=title, color=0xFACC15)
        if date:
            embed.set_footer(text=date)

        for group in release.get("groups", []) or []:
            name = group.get("title") or "Changes"
            lines = []
            for entry in group.get("entries", []) or []:
                txt = _html_to_text(entry.get("html", ""))
                if txt:
                    lines.append(f"• {txt}")
            value = "\n".join(lines).strip()
            if not value:
                continue
            if len(value) > _FIELD_CAP:
                value = value[: _FIELD_CAP - 1] + "…"
            embed.add_field(name=name, value=value, inline=False)

        if not embed.fields:
            embed.description = "No changelog entries."
        return embed


async def setup_patchnotes_panel_system(bot, engine):
    """Build the per-(official)-guild patch-notes panel registry and re-attach
    on restart. Returns {guild_id: PatchNotesPanel}."""
    from ._panel_base import OFFICIAL_GUILD_ID

    panels = {OFFICIAL_GUILD_ID: PatchNotesPanel(bot, engine)}
    return panels
