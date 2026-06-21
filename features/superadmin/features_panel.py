"""Feature-list panel (Components V2).

Renders a professional, multi-section feature catalog. Content priority:
  1. features_body from the console, if set. The body may be split into sections
     with `## Section Heading` lines; each section becomes its own headed block
     with a divider. Plain text (no `##`) renders as a single section.
  2. Otherwise the built-in full catalog (DEFAULT_SECTIONS).

The optional features_title overrides the panel heading.
"""

import logging

import discord

from ._panel_base import ACCENT, TEXT_CAP, GlobalPanel, get_setting, text_block

logger = logging.getLogger(__name__)

_DEFAULT_TITLE = "LeleBot — Feature Overview"
_INTRO = (
    "The complete stream toolkit for **Kick** and **Twitch** casino streamers — "
    "a web dashboard, a chat & Discord bot, and a browser extension, working together."
)

# Built-in full catalog: (heading, [bullet lines]). Used when no console body is
# set. Professional tone, no emojis.
DEFAULT_SECTIONS = [
    (
        "Bonus Hunt",
        [
            "**Hunt tracking** — live sessions with starting balance, profit/loss, total bet, payouts, and break-even multipliers.",
            "**Slot management** — add bonuses with search, drag-to-reorder, randomize, and bulk edit.",
            "**Open Bonuses** — step through each bonus to record payouts on stream, with full hunt history.",
        ],
    ),
    (
        "Slot Requests & Guess the Balance",
        [
            "**Slot Requests** — viewers request slots from chat into a live queue, with random pick, add-to-hunt, an OBS overlay, and a ban list.",
            "**Guess the Balance** — a chat prediction game with live guesses and an automatic winner.",
        ],
    ),
    (
        "Raffles & Giveaways",
        [
            "**Raffles** — earn tickets from watchtime, gifted subs, and wagers; provably-fair, ticket-weighted draws with animated OBS overlays and an auto-updating leaderboard.",
            "**Giveaways** — keyword, active-chatter, or ticket-weighted draws with Discord announcements.",
        ],
    ),
    (
        "Wagers & Leaderboards",
        [
            "**Wager tracking** — automatic Shuffle.com and Howl.gg tracking with stats and a live activity feed.",
            "**Affiliate Leaderboard Generator** — run wager competitions with prize periods, a public results page, frozen winners, and JSON / text / PDF export.",
        ],
    ),
    (
        "Points & Economy",
        [
            "**Point rewards** — earn points from watchtime, subscriptions, and sub-gifting, with a leaderboard.",
            "**Point shop** — sell items with images and discounts, manage orders, and post the shop to Discord.",
            "**Provably-fair games** — point-based Blackjack, Roll, and Double, fully verifiable.",
        ],
    ),
    (
        "Stream Widgets & Overlays",
        [
            "**OBS overlays** — template-based widgets for bonus hunts, Guess the Balance, and raffle draws.",
            "**Customization** — brand colors, typography, and layout, with multiple saved projects per template.",
            "**Advanced editor** — build fully custom widgets with your own layout and styling.",
        ],
    ),
    (
        "Bot & Chat Automation",
        [
            "**Custom commands** — with dynamic variables for user, channel, tickets, points, and watchtime.",
            "**Timed messages** — scheduled announcements posted to your active platform(s).",
            "**Clips** — create clips from chat or the dashboard, with history.",
        ],
    ),
    (
        "Discord Integration",
        [
            "**Account linking** — viewers connect their Kick/Twitch accounts; verification panels for Shuffle and Howl.",
            "**Roles & alerts** — automatic watchtime roles and customizable go-live notifications.",
            "**Subscription roles** — claim the Discord role matching your active subscription tier.",
        ],
    ),
    (
        "Platforms & Plans",
        [
            "**Kick and Twitch** — run either platform, or both at once on Tier 3, with one shared identity per viewer.",
            "**Browser extension** — add bonuses straight from the casino and view live hunt stats.",
            "**Subscriptions** — manage your plan in-dashboard via Stripe, with instant feature unlocks.",
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
            # Built-in full catalog.
            for heading, bullets in DEFAULT_SECTIONS:
                container.add_item(discord.ui.Separator())
                lines = "\n".join(f"- {b}" for b in bullets)
                container.add_item(text_block(f"### {heading}\n{lines}"))

        view = discord.ui.LayoutView(timeout=None)
        view.add_item(container)
        return view


async def setup_features_panel_system(bot, engine):
    from ._panel_base import OFFICIAL_GUILD_ID

    return {OFFICIAL_GUILD_ID: FeaturesPanel(bot, engine)}
