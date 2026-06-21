"""Feature-list panel (Components V2).

Renders a polished, multi-section feature showcase. Content priority:
  1. features_body from the console, if set. The body may be split into sections
     with `## Section Heading` lines; each section becomes its own headed block
     with a divider. Plain text (no `##`) renders as a single section.
  2. Otherwise a professionally-written built-in default (DEFAULT_SECTIONS).

The optional features_title overrides the panel heading.
"""

import logging

import discord

from ._panel_base import ACCENT, TEXT_CAP, GlobalPanel, get_setting, text_block

logger = logging.getLogger(__name__)

_DEFAULT_TITLE = "✨ LeleBot — Features"
_INTRO = "The all-in-one toolkit for **Kick & Twitch** casino streamers — dashboard, bot, and browser extension."

# Built-in default: (emoji+heading, [bullet lines]). Used when no console body is
# set. Kept tight and skimmable.
DEFAULT_SECTIONS = [
    (
        "🎰 Streaming Tools",
        [
            "**Bonus Hunt** — live hunt tracking with profit/loss, payouts & multipliers",
            "**Slot Requests** — viewers queue slots from chat, with an OBS overlay",
            "**Guess the Balance** — chat prediction game with a live winner",
        ],
    ),
    (
        "🎟️ Community & Rewards",
        [
            "**Raffles** — earn tickets from watchtime, subs & wagers; animated draws",
            "**Giveaways** — keyword, active-chatter, or ticket-weighted",
            "**Points & Shop** — earn points and redeem rewards in chat",
        ],
    ),
    (
        "💰 Wagers & Leaderboards",
        [
            "**Wager tracking** — Shuffle.com & Howl.gg, with live stats",
            "**Affiliate leaderboards** — prize periods + a public results page",
        ],
    ),
    (
        "📺 Overlays & Bot",
        [
            "**Stream widgets** — OBS overlays for hunts, GTB & raffle draws",
            "**Custom commands & timed messages** for Kick and Twitch",
            "**Go-live alerts, account linking & roles** in Discord",
        ],
    ),
]


def _parse_sections(body: str):
    """Split a console body into [(heading|None, text)] sections on `## ` lines.

    A leading chunk before the first `##` (or a body with no `##` at all) becomes
    a headingless section, so plain-text bodies still render cleanly.
    """
    sections = []
    heading = None
    buf = []

    def flush():
        text = "\n".join(buf).strip()
        if text:
            sections.append((heading, text))

    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            flush()
            heading = stripped[3:].strip()
            buf = []
        else:
            buf.append(line)
    flush()
    return sections


class FeaturesPanel(GlobalPanel):
    PANEL_TYPE = "features"

    def build_view(self, data=None) -> discord.ui.LayoutView:
        title = (get_setting(self.engine, "features_title") or _DEFAULT_TITLE).strip()
        body = (get_setting(self.engine, "features_body") or "").strip()

        container = discord.ui.Container(accent_colour=ACCENT)
        container.add_item(text_block(f"# {title}\n{_INTRO}"))

        if body:
            sections = _parse_sections(body)
            if not sections:  # body was only whitespace after parsing
                sections = [(None, body)]
            for heading, text in sections:
                container.add_item(discord.ui.Separator())
                block = f"### {heading}\n{text}" if heading else text
                container.add_item(text_block(block[:TEXT_CAP]))
        else:
            # Polished built-in default.
            for heading, bullets in DEFAULT_SECTIONS:
                container.add_item(discord.ui.Separator())
                lines = "\n".join(f"• {b}" for b in bullets)
                container.add_item(text_block(f"### {heading}\n{lines}"))

        view = discord.ui.LayoutView(timeout=None)
        view.add_item(container)
        return view


async def setup_features_panel_system(bot, engine):
    from ._panel_base import OFFICIAL_GUILD_ID

    return {OFFICIAL_GUILD_ID: FeaturesPanel(bot, engine)}
