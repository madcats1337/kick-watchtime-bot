"""Patch-notes / changelog panel (Components V2).

Content is NOT stored in the DB — the dashboard forwards the latest `release`
object from the /patch-notes page in the post_panel event data. Shape:
  {version, date, tag, tone, groups: [{category, title, entries: [{html}]}]}

The posted panel is a COMPACT changelog: a heading line plus a few bullets per
group, so it stays short in Discord even though the dashboard page is detailed.
"""

import logging
import re

import discord

from ._panel_base import ACCENT, GlobalPanel, text_block

logger = logging.getLogger(__name__)

# Keep the Discord post compact: at most this many bullets per group, and an
# overall entry length cap so a single long line can't blow the post up.
_MAX_ENTRIES_PER_GROUP = 5
_ENTRY_CAP = 200


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


def _shorten(text: str) -> str:
    """Trim a single changelog entry to a compact one-liner. Keeps the leading
    bolded label (up to the em dash) intact when it fits."""
    text = " ".join(text.split())  # collapse whitespace/newlines
    if len(text) <= _ENTRY_CAP:
        return text
    cut = text[:_ENTRY_CAP].rsplit(" ", 1)[0]
    return cut + "…"


class PatchNotesPanel(GlobalPanel):
    PANEL_TYPE = "patchnotes"
    # Prefix shown above the version line. The extension panel overrides this so
    # the post is clearly labelled as a browser-extension release.
    HEADING_PREFIX = ""

    def build_view(self, data=None) -> discord.ui.LayoutView:
        release = (data or {}).get("release") or {}
        version = release.get("version") or "Patch Notes"
        date = release.get("date") or ""
        tag = release.get("tag") or ""

        header = f"# {self.HEADING_PREFIX}{version}"
        if tag:
            header += f" — {tag}"
        if date:
            header += f"\n-# {date}"

        container = discord.ui.Container(accent_colour=ACCENT)
        container.add_item(text_block(header))

        # Prefer the purpose-written `summary` (concise, Discord-ready markdown).
        # Fall back to condensing the full `groups` only when no summary is given.
        summary = release.get("summary") or []
        any_section = False

        if summary:
            for section in summary:
                title = section.get("title") or "Changes"
                items = [str(i).strip() for i in (section.get("items") or []) if str(i).strip()]
                if not items:
                    continue
                any_section = True
                container.add_item(discord.ui.Separator())
                bullets = "\n".join(f"- {i}" for i in items)
                container.add_item(text_block(f"**{title}**\n{bullets}"))
        else:
            for group in release.get("groups", []) or []:
                name = group.get("title") or "Changes"
                bullets = []
                for entry in (group.get("entries", []) or [])[:_MAX_ENTRIES_PER_GROUP]:
                    txt = _html_to_text(entry.get("html", ""))
                    if txt:
                        bullets.append(f"- {_shorten(txt)}")
                if not bullets:
                    continue
                any_section = True
                container.add_item(discord.ui.Separator())
                container.add_item(text_block(f"**{name}**\n" + "\n".join(bullets)))

        if not any_section:
            container.add_item(text_block("No changelog entries."))

        view = discord.ui.LayoutView(timeout=None)
        view.add_item(container)
        return view


class ExtensionPatchNotesPanel(PatchNotesPanel):
    """Browser-extension changelog panel. Identical rendering to the dashboard
    patch-notes panel, but a distinct PANEL_TYPE (so it's tracked as its own
    message in link_panels and moves independently) and a labelled heading."""

    PANEL_TYPE = "patchnotes_extension"
    HEADING_PREFIX = "🧩 Extension — "


async def setup_patchnotes_panel_system(bot, engine):
    """Build the per-(official)-guild patch-notes panel registry. Returns
    {guild_id: PatchNotesPanel}."""
    from ._panel_base import OFFICIAL_GUILD_ID

    return {OFFICIAL_GUILD_ID: PatchNotesPanel(bot, engine)}


async def setup_extension_patchnotes_panel_system(bot, engine):
    """Build the per-(official)-guild EXTENSION patch-notes panel registry.
    Returns {guild_id: ExtensionPatchNotesPanel}."""
    from ._panel_base import OFFICIAL_GUILD_ID

    return {OFFICIAL_GUILD_ID: ExtensionPatchNotesPanel(bot, engine)}
