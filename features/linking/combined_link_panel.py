"""
Combined Link Panel — one Discord panel with per-platform link buttons.

Replaces the separate Kick-only (link_panel.py) and Twitch-only (twitch_panel.py)
panels with a single panel that shows a "Link Kick" and/or "Link Twitch" button
based on the server's `stream_platforms` setting:
  - kick-only server   → only the Kick button
  - twitch-only server → only the Twitch button
  - both               → both buttons

Each button hands the viewer a signed OAuth URL via the same generators the old
panels used (generate_signed_oauth_url / generate_signed_twitch_oauth_url), so the
existing /auth/kick and /auth/twitch/link viewer flows are unchanged. Links are
written per-platform (links.platform) so a viewer can link both.

panel_type = 'link' (one row per guild in link_panels).
"""

import logging
import os

import discord
from discord.ext import commands
from discord.ui import Button, View
from sqlalchemy import text

logger = logging.getLogger(__name__)

PANEL_TYPE = "link"

# Unicode fallbacks used when a brand-logo application emoji isn't available
# (PNG missing or upload failed) so the panel buttons always render something.
FALLBACK_EMOJI = {"kick": "🟢", "twitch": "🟣"}

# Application-emoji names + the PNG files supplied under assets/emojis/.
_EMOJI_FILES = {"kick": "kick.png", "twitch": "twitch.png"}
_EMOJI_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "assets", "emojis")


async def ensure_link_emojis(bot) -> dict:
    """Idempotently register the Kick/Twitch brand logos as the bot's application
    emojis and return ``{"kick": <Emoji|None>, "twitch": <Emoji|None>}``.

    On first run the PNGs under ``assets/emojis/`` are uploaded; on later runs the
    already-uploaded emojis are reused (matched by name). A missing PNG or any API
    error yields ``None`` for that platform, which makes the buttons fall back to
    the unicode circle — the panel still works either way.
    """
    result = {"kick": None, "twitch": None}
    try:
        existing = {e.name: e for e in await bot.fetch_application_emojis()}
    except Exception as e:
        logger.warning(f"[CombinedLink] Could not fetch application emojis (using unicode fallback): {e}")
        return result

    for name, filename in _EMOJI_FILES.items():
        if name in existing:
            result[name] = existing[name]
            logger.info(f"[CombinedLink] Reusing existing '{name}' application emoji.")
            continue
        path = os.path.join(_EMOJI_DIR, filename)
        if not os.path.isfile(path):
            logger.warning(f"[CombinedLink] {filename} not found at {path} — '{name}' button falls back to unicode.")
            continue
        try:
            with open(path, "rb") as f:
                image_bytes = f.read()
            result[name] = await bot.create_application_emoji(name=name, image=image_bytes)
            logger.info(f"[CombinedLink] Uploaded '{name}' application emoji.")
        except Exception as e:
            logger.error(f"[CombinedLink] Failed to upload '{name}' application emoji: {e}")

    return result


def _active_platforms(engine, guild_id) -> list:
    """Return the platforms this server runs, from bot_settings.stream_platforms
    (default 'kick'). Always a non-empty list."""
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT value FROM bot_settings WHERE key = 'stream_platforms' AND discord_server_id = :g"),
                {"g": guild_id},
            ).fetchone()
        raw = (row[0] if row and row[0] else "kick") or "kick"
        platforms = [p.strip().lower() for p in str(raw).split(",") if p.strip()]
        return platforms or ["kick"]
    except Exception as e:
        logger.warning(f"[CombinedLink] Could not read stream_platforms for {guild_id}: {e}")
        return ["kick"]


class CombinedLinkPanelView(View):
    """Persistent view with a Kick and a Twitch link button. Both buttons are
    always attached (so the single persistent view registered at startup matches
    every posted message); each button checks at click time whether its platform
    is active for the server and whether the user is already linked."""

    def __init__(self, bot, engine, kick_url_generator, twitch_url_generator, kick_emoji=None, twitch_emoji=None):
        super().__init__(timeout=None)  # Persistent
        self.bot = bot
        self.engine = engine
        self.kick_url_generator = kick_url_generator
        self.twitch_url_generator = twitch_url_generator
        # Brand-logo application emojis (or None → unicode fallback). The
        # decorator emoji is static, so override it on the instance here.
        self.kick_emoji = kick_emoji or FALLBACK_EMOJI["kick"]
        self.twitch_emoji = twitch_emoji or FALLBACK_EMOJI["twitch"]
        self.kick_button.emoji = self.kick_emoji
        self.twitch_button.emoji = self.twitch_emoji

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return True

    async def _handle(self, interaction, platform, url_generator, label_emoji):
        discord_id = interaction.user.id
        guild_id = interaction.guild.id if interaction.guild else None

        # Gate by the server's active platforms.
        if platform not in _active_platforms(self.engine, guild_id):
            await interaction.response.send_message(
                f"❌ {platform.capitalize()} linking isn't enabled on this server.", ephemeral=True
            )
            return

        # Already linked on this platform for this server?
        try:
            with self.engine.connect() as conn:
                existing = conn.execute(
                    text(
                        """
                        SELECT kick_name FROM links
                        WHERE discord_id = :d AND (:sid IS NULL OR discord_server_id = :sid)
                        AND platform = :p
                        """
                    ),
                    {"d": discord_id, "sid": guild_id, "p": platform},
                ).fetchone()
            if existing:
                await interaction.response.send_message(
                    f"✅ Your {platform.capitalize()} is already linked to **{existing[0]}**!", ephemeral=True
                )
                return
        except Exception as e:
            logger.error(f"[CombinedLink] DB error checking {platform} link: {e}")
            await interaction.response.send_message("❌ Database error. Please try again.", ephemeral=True)
            return

        try:
            oauth_url = url_generator(discord_id, guild_id)
        except Exception as e:
            logger.error(f"[CombinedLink] Error generating {platform} OAuth URL: {e}")
            await interaction.response.send_message(
                "❌ Failed to generate OAuth link. Please contact an admin.", ephemeral=True
            )
            return

        view = View(timeout=600)
        view.add_item(
            Button(
                label=f"Authorize with {platform.capitalize()}",
                style=discord.ButtonStyle.link,
                url=oauth_url,
                emoji=label_emoji,
            )
        )
        await interaction.response.send_message(
            f"{label_emoji} Click the button below to link your {platform.capitalize()} account "
            f"(expires in 10 minutes):",
            view=view,
            ephemeral=True,
        )
        logger.info(f"[CombinedLink] Sent {platform} OAuth link to {interaction.user.name} ({discord_id})")

    @discord.ui.button(style=discord.ButtonStyle.success, label="Link Kick", emoji="🟢", custom_id="link_kick_account")
    async def kick_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await self._handle(interaction, "kick", self.kick_url_generator, self.kick_emoji)
        except Exception as e:
            logger.error(f"[CombinedLink] Kick button error: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ An error occurred.", ephemeral=True)

    @discord.ui.button(
        style=discord.ButtonStyle.secondary, label="Link Twitch", emoji="🟣", custom_id="link_twitch_account"
    )
    async def twitch_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await self._handle(interaction, "twitch", self.twitch_url_generator, self.twitch_emoji)
        except Exception as e:
            logger.error(f"[CombinedLink] Twitch button error: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ An error occurred.", ephemeral=True)


def _build_view_for_guild(
    bot, engine, kick_url_generator, twitch_url_generator, guild_id, kick_emoji=None, twitch_emoji=None
):
    """Build a view showing only the buttons for the guild's active platforms.
    Used when POSTING the panel (so a kick-only server shows just the Kick button).
    The persistent view registered globally keeps both custom_ids alive."""
    platforms = _active_platforms(engine, guild_id)
    view = CombinedLinkPanelView(
        bot, engine, kick_url_generator, twitch_url_generator, kick_emoji=kick_emoji, twitch_emoji=twitch_emoji
    )
    # Drop buttons for platforms this server doesn't run.
    for item in list(view.children):
        cid = getattr(item, "custom_id", "")
        if cid == "link_kick_account" and "kick" not in platforms:
            view.remove_item(item)
        if cid == "link_twitch_account" and "twitch" not in platforms:
            view.remove_item(item)
    return view, platforms


class CombinedLinkPanel:
    """Manages the combined link panel message for a specific guild."""

    def __init__(
        self, bot, engine, kick_url_generator, twitch_url_generator, guild_id=None, kick_emoji=None, twitch_emoji=None
    ):
        self.bot = bot
        self.engine = engine
        self.kick_url_generator = kick_url_generator
        self.twitch_url_generator = twitch_url_generator
        self.kick_emoji = kick_emoji
        self.twitch_emoji = twitch_emoji
        self.guild_id = guild_id
        self.panel_message_id = None
        self.panel_channel_id = None
        self.panel_guild_id = None
        self._load_panel_info()

    def _load_panel_info(self):
        if not self.engine or self.guild_id is None:
            return
        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text(
                        """
                        SELECT guild_id, channel_id, message_id
                        FROM link_panels
                        WHERE guild_id = :guild_id AND panel_type = :ptype
                        ORDER BY created_at DESC
                        LIMIT 1
                        """
                    ),
                    {"guild_id": self.guild_id, "ptype": PANEL_TYPE},
                ).fetchone()
                if result:
                    self.panel_guild_id, self.panel_channel_id, self.panel_message_id = result
        except Exception as e:
            logger.error(f"[CombinedLink] Failed to load panel info for {self.guild_id}: {e}")

    def _save_panel_info(self, guild_id, channel_id, message_id):
        if not self.engine:
            return
        try:
            with self.engine.begin() as conn:
                conn.execute(
                    text("DELETE FROM link_panels WHERE guild_id = :guild_id AND panel_type = :ptype"),
                    {"guild_id": guild_id, "ptype": PANEL_TYPE},
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO link_panels (guild_id, channel_id, message_id, emoji, panel_type, created_at)
                        VALUES (:guild_id, :channel_id, :message_id, '🔗', :ptype, CURRENT_TIMESTAMP)
                        """
                    ),
                    {"guild_id": guild_id, "channel_id": channel_id, "message_id": message_id, "ptype": PANEL_TYPE},
                )
        except Exception as e:
            logger.error(f"[CombinedLink] Failed to save panel info: {e}")

    async def create_panel(self, channel: discord.TextChannel):
        try:
            view, platforms = _build_view_for_guild(
                self.bot,
                self.engine,
                self.kick_url_generator,
                self.twitch_url_generator,
                channel.guild.id,
                kick_emoji=self.kick_emoji,
                twitch_emoji=self.twitch_emoji,
            )
            names = " & ".join(p.capitalize() for p in platforms)
            embed = discord.Embed(
                title="🔗 Link Your Account",
                description=(
                    f"Link your {names} account with Discord to participate in raffles and track your watchtime!\n\n"
                    "**Benefits:**\n"
                    "• Earn raffle tickets from watchtime\n"
                    "• Get bonus tickets from subscriptions\n"
                    "• Participate in raffles and giveaways\n"
                    "• Earn roles based on chat activity\n"
                    "• Track your stats and progress"
                ),
                color=0x9146FF if platforms == ["twitch"] else 0x53FC18,
            )
            if len(platforms) > 1:
                embed.add_field(
                    name="How to Link",
                    value="Use the buttons below — you can link **both** platforms.",
                    inline=False,
                )
            else:
                embed.add_field(
                    name="How to Link",
                    value=f"Click the **'Link {platforms[0].capitalize()}'** button below to get started!",
                    inline=False,
                )
            embed.add_field(
                name="🔒 Privacy & Security",
                value=(
                    "• OAuth links are unique and expire after 10 minutes\n"
                    "• Links are sent privately, only you can see them\n"
                    "• Your password is never shared with this bot"
                ),
                inline=False,
            )
            embed.set_footer(text="Click a button to get your personal OAuth link")

            message = await channel.send(embed=embed, view=view)
            self.panel_guild_id = channel.guild.id
            self.panel_channel_id = channel.id
            self.panel_message_id = message.id
            self._save_panel_info(channel.guild.id, channel.id, message.id)
            logger.info(f"[CombinedLink] Created panel in {channel.guild.name} / #{channel.name} ({names})")
            return True
        except Exception as e:
            logger.error(f"[CombinedLink] Failed to create panel: {e}")
            return False


async def setup_combined_link_panel_system(bot, engine, kick_url_generator, twitch_url_generator):
    """Set up the combined link panel: per-guild instances, a global persistent
    view (both custom_ids), the !createlinkpanel command, and restart re-attach."""
    # Register (or reuse) the Kick/Twitch brand-logo application emojis once, then
    # thread them into every view so the panel buttons show the logos.
    emojis = await ensure_link_emojis(bot)
    kick_emoji = emojis.get("kick")
    twitch_emoji = emojis.get("twitch")

    panels = {}
    for guild in bot.guilds:
        panels[guild.id] = CombinedLinkPanel(
            bot,
            engine,
            kick_url_generator,
            twitch_url_generator,
            guild_id=guild.id,
            kick_emoji=kick_emoji,
            twitch_emoji=twitch_emoji,
        )

    # Register ONE global persistent view carrying both custom_ids so buttons keep
    # working across restarts regardless of which platforms a guild shows.
    try:
        bot.add_view(
            CombinedLinkPanelView(
                bot, engine, kick_url_generator, twitch_url_generator, kick_emoji=kick_emoji, twitch_emoji=twitch_emoji
            )
        )
    except Exception as e:
        logger.warning(f"[CombinedLink] add_view failed (non-fatal): {e}")

    @bot.command(name="createlinkpanel")
    @commands.has_permissions(administrator=True)
    async def create_link_panel_cmd(ctx):
        """[ADMIN] Create the combined link panel in this channel."""
        panel = panels.get(ctx.guild.id)
        if not panel:
            await ctx.send("❌ Link panel not initialized for this server")
            return
        if await panel.create_panel(ctx.channel):
            await ctx.send("✅ Link panel created! Users can now link their accounts.")
        else:
            await ctx.send("❌ Failed to create link panel. Check logs for details.")

    # Re-attach the (platform-filtered) view to existing panel messages on restart.
    for guild_id, panel in panels.items():
        if panel.panel_message_id and panel.panel_channel_id:
            try:
                channel = bot.get_channel(panel.panel_channel_id)
                if channel:
                    message = await channel.fetch_message(panel.panel_message_id)
                    view, _ = _build_view_for_guild(
                        bot,
                        engine,
                        kick_url_generator,
                        twitch_url_generator,
                        guild_id,
                        kick_emoji=kick_emoji,
                        twitch_emoji=twitch_emoji,
                    )
                    await message.edit(view=view)
            except Exception as e:
                logger.error(f"[CombinedLink] Failed to re-attach view for guild {guild_id}: {e}")

    return panels
