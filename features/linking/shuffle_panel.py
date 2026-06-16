"""
Shuffle Verify Panel - Interactive Discord panel for Shuffle affiliate auto-verification.

A user clicks the "Verify Shuffle Account" button, enters their Shuffle username in a
modal, and the bot checks that username against the live affiliate-stats JSON (fetched
from the guild's configured `shuffle_affiliate_url`). If the username appears in that
JSON for the configured campaign code, the user is auto-verified (raffle_shuffle_links,
verified=TRUE) and granted the configured `shuffle_verified_role_id` role.

This mirrors features/linking/link_panel.py (embed + persistent button view + admin
create command + re-attach on restart) and is the automated equivalent of the admin
`!verifyshuffle` command in raffle_system/commands.py.
"""

import asyncio
import logging

import aiohttp
import discord
from discord.ext import commands
from discord.ui import Modal, TextInput, View
from sqlalchemy import text

logger = logging.getLogger(__name__)

EMBED_COLOR = 0x6C5CE7  # Shuffle purple


async def _fetch_affiliate_data(affiliate_url: str):
    """Fetch the affiliate-stats JSON array from the configured URL.

    Mirrors ShuffleWagerTracker._fetch_shuffle_data (shuffle_tracker.py:422):
    GET the URL, expect a JSON array, return None on any failure.
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(affiliate_url, timeout=30) as response:
                if response.status != 200:
                    logger.error(f"Affiliate API returned status {response.status}")
                    return None

                data = await response.json()
                if not isinstance(data, list):
                    logger.error(f"Unexpected affiliate API response format: {type(data)}")
                    return None

                return data
    except asyncio.TimeoutError:
        logger.error("Timeout fetching affiliate data")
        return None
    except Exception as e:
        logger.error(f"Error fetching affiliate data: {e}")
        return None


async def verify_and_grant(interaction: discord.Interaction, engine, settings_getter, entered_username: str):
    """Verify the entered Shuffle username against affiliate stats and grant the role.

    Replies to the interaction with an ephemeral message in every branch.
    """
    discord_id = interaction.user.id
    guild = interaction.guild
    guild_id = guild.id if guild else None
    entered = (entered_username or "").strip()

    if not entered:
        await interaction.response.send_message("❌ Please enter your Shuffle username.", ephemeral=True)
        return

    # 1. Already-verified check — scoped to the SHUFFLE platform so a user's
    #    howl link doesn't make the shuffle flow report "already verified".
    try:
        with engine.connect() as conn:
            existing = conn.execute(
                text(
                    "SELECT shuffle_username FROM raffle_shuffle_links "
                    "WHERE discord_id = :d AND platform = 'shuffle'"
                ),
                {"d": discord_id},
            ).fetchone()
        if existing:
            await interaction.response.send_message(f"✅ You're already verified as **{existing[0]}**!", ephemeral=True)
            return
    except Exception as e:
        logger.error(f"Error checking existing Shuffle link: {e}")
        await interaction.response.send_message("❌ Database error. Please try again.", ephemeral=True)
        return

    # Resolve per-guild settings
    settings = settings_getter(guild_id) if guild_id is not None else None
    affiliate_url = settings.shuffle_affiliate_url if settings else ""
    campaign_code = settings.shuffle_campaign_code if settings else ""

    if not affiliate_url:
        await interaction.response.send_message(
            "❌ Shuffle verification isn't configured for this server yet. Please contact an admin.",
            ephemeral=True,
        )
        return

    # Defer: the affiliate fetch can take a few seconds
    await interaction.response.defer(ephemeral=True, thinking=True)

    # 2. Fetch affiliate JSON
    data = await _fetch_affiliate_data(affiliate_url)
    if data is None:
        await interaction.followup.send(
            "❌ Couldn't reach the Shuffle affiliate stats right now. Please try again later.",
            ephemeral=True,
        )
        return

    # 3. Match: case-insensitive username, filtered by campaign code(s)
    campaign_codes = [code.strip().lower() for code in (campaign_code or "").split(",") if code.strip()]
    entered_lower = entered.lower()
    matched = None
    for row in data:
        if str(row.get("username", "")).lower() != entered_lower:
            continue
        # If campaign codes are configured, require a match; otherwise accept any
        if campaign_codes and str(row.get("campaignCode", "")).lower() not in campaign_codes:
            continue
        matched = row
        break

    if not matched:
        await interaction.followup.send(
            f"❌ **{entered}** wasn't found in our affiliate stats. Make sure you used code "
            f"**{campaign_code}** when signing up on Shuffle, then try again.",
            ephemeral=True,
        )
        return

    matched_username = str(matched.get("username"))

    # 4a. Look up an existing Kick name for this Discord user (optional)
    kick_name = None
    try:
        with engine.connect() as conn:
            link_row = conn.execute(
                text(
                    "SELECT kick_name FROM links WHERE discord_id = :d "
                    "AND (:sid IS NULL OR discord_server_id = :sid)"
                ),
                {"d": discord_id, "sid": guild_id},
            ).fetchone()
        if link_row:
            kick_name = link_row[0]
    except Exception as e:
        logger.error(f"Error looking up Kick name for {discord_id}: {e}")

    # 4b. Persist the verified link (verified by the user themselves)
    result = _insert_verified_link(engine, matched_username, kick_name, discord_id)
    status = result.get("status")

    if status == "already_linked":
        await interaction.followup.send(
            f"❌ **{matched_username}** is already verified by another Discord account.", ephemeral=True
        )
        return
    if status == "discord_already_linked":
        await interaction.followup.send(
            f"✅ You're already verified as **{result.get('existing_shuffle_username')}**!", ephemeral=True
        )
        return
    if status != "success":
        await interaction.followup.send("❌ Failed to save your verification. Please try again.", ephemeral=True)
        return

    # 4c. Grant the configured role (mirrors bot.py:3959-3999)
    role_note = await _grant_role(interaction, engine, guild, discord_id, guild_id, matched_username)

    await interaction.followup.send(
        f"🎉 Verified! Your Shuffle account **{matched_username}** is now linked.{role_note}",
        ephemeral=True,
    )


def _insert_verified_link(engine, shuffle_username, kick_name, discord_id):
    """Insert a verified raffle_shuffle_links row (self-verified).

    Uses the same status contract as ShuffleWagerTracker.link_shuffle_account so the
    caller can give friendly messages for the UNIQUE(shuffle_username)/UNIQUE(discord_id)
    cases without relying on a DB exception.
    """
    try:
        with engine.begin() as conn:
            existing = conn.execute(
                text(
                    "SELECT discord_id FROM raffle_shuffle_links "
                    "WHERE shuffle_username = :u AND platform = 'shuffle'"
                ),
                {"u": shuffle_username},
            ).fetchone()
            if existing:
                return {"status": "already_linked", "existing_discord_id": existing[0]}

            discord_existing = conn.execute(
                text(
                    "SELECT shuffle_username FROM raffle_shuffle_links "
                    "WHERE discord_id = :d AND platform = 'shuffle'"
                ),
                {"d": discord_id},
            ).fetchone()
            if discord_existing:
                return {"status": "discord_already_linked", "existing_shuffle_username": discord_existing[0]}

            conn.execute(
                text(
                    """
                    INSERT INTO raffle_shuffle_links
                        (shuffle_username, kick_name, discord_id, platform, verified, verified_by_discord_id, verified_at)
                    VALUES
                        (:shuffle_username, :kick_name, :discord_id, 'shuffle', TRUE, :verified_by, CURRENT_TIMESTAMP)
                    """
                ),
                {
                    "shuffle_username": shuffle_username,
                    "kick_name": kick_name,
                    "discord_id": discord_id,
                    "verified_by": discord_id,  # self-verified
                },
            )
        logger.info(
            f"🔗 Auto-verified Shuffle link: {shuffle_username} → "
            f"{kick_name or '(no Kick link)'} (Discord: {discord_id})"
        )
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Failed to insert verified Shuffle link: {e}")
        return {"status": "error", "error": str(e)}


async def _grant_role(interaction, engine, guild, discord_id, guild_id, matched_username):
    """Grant the configured shuffle_verified_role_id role. Returns a note for the user."""
    if not guild or not guild_id:
        return ""

    try:
        with engine.connect() as conn:
            role_id = conn.execute(
                text(
                    "SELECT value FROM bot_settings "
                    "WHERE key = 'shuffle_verified_role_id' AND discord_server_id = :guild_id"
                ),
                {"guild_id": guild_id},
            ).scalar()
    except Exception as e:
        logger.error(f"Failed to query shuffle_verified_role_id: {e}")
        role_id = None

    if not role_id or not str(role_id).strip():
        return ""  # No role configured — verification still succeeded

    try:
        role = guild.get_role(int(role_id))
    except (ValueError, TypeError):
        logger.error(f"Invalid shuffle_verified_role_id {role_id!r} for guild {guild_id}")
        return ""

    if not role:
        logger.warning(f"Shuffle verified role {role_id} not found in guild {guild.name}")
        return ""

    member = guild.get_member(int(discord_id))
    if not member:
        logger.warning(f"Member {discord_id} not found in guild {guild.name}")
        return ""

    if role in member.roles:
        return f" You already have the **{role.name}** role."

    try:
        await member.add_roles(role, reason=f"Verified Shuffle account: {matched_username}")
        logger.info(f"✅ Granted role '{role.name}' to {member.display_name} for Shuffle verification")
        return f" You've been given the **{role.name}** role."
    except Exception as e:
        logger.error(f"Error granting Shuffle verified role: {e}")
        return ""


class ShuffleVerifyModal(Modal, title="Verify Your Shuffle Account"):
    """Modal that collects the user's Shuffle username."""

    shuffle_username = TextInput(
        label="Shuffle Username",
        placeholder="Your exact Shuffle.com username",
        required=True,
        min_length=1,
        max_length=64,
    )

    def __init__(self, engine, settings_getter):
        super().__init__()
        self.engine = engine
        self.settings_getter = settings_getter

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await verify_and_grant(interaction, self.engine, self.settings_getter, self.shuffle_username.value)
        except Exception as e:
            logger.error(f"Error handling Shuffle verify modal: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ An error occurred.", ephemeral=True)
            else:
                await interaction.followup.send("❌ An error occurred.", ephemeral=True)


class ShufflePanelView(View):
    """Button view for the Shuffle verify panel (persistent)."""

    def __init__(self, bot, engine, settings_getter):
        super().__init__(timeout=None)
        self.bot = bot
        self.engine = engine
        self.settings_getter = settings_getter

    @discord.ui.button(
        style=discord.ButtonStyle.success,
        label="Verify Shuffle Account",
        emoji="🎰",
        custom_id="shuffle_verify",
    )
    async def verify_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.response.send_modal(ShuffleVerifyModal(self.engine, self.settings_getter))
        except Exception as e:
            logger.error(f"Error opening Shuffle verify modal: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ An error occurred.", ephemeral=True)


class ShufflePanel:
    """Manages the Shuffle verify panel message for a specific guild.

    Reuses the link_panels table, scoped by panel_type = 'shuffle_verify'.
    """

    PANEL_TYPE = "shuffle_verify"

    def __init__(self, bot, engine, settings_getter, guild_id=None):
        self.bot = bot
        self.engine = engine
        self.settings_getter = settings_getter
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
                    {"guild_id": self.guild_id, "ptype": self.PANEL_TYPE},
                ).fetchone()
                if result:
                    self.panel_guild_id = result[0]
                    self.panel_channel_id = result[1]
                    self.panel_message_id = result[2]
                    logger.debug(f"Loaded Shuffle panel info for guild {self.guild_id}")
        except Exception as e:
            logger.error(f"Failed to load Shuffle panel info for guild {self.guild_id}: {e}")

    def _save_panel_info(self, guild_id: int, channel_id: int, message_id: int):
        if not self.engine:
            return
        try:
            with self.engine.begin() as conn:
                # Only delete this guild's *shuffle* panels — leave the Kick link panel untouched
                conn.execute(
                    text("DELETE FROM link_panels WHERE guild_id = :guild_id AND panel_type = :ptype"),
                    {"guild_id": guild_id, "ptype": self.PANEL_TYPE},
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO link_panels (guild_id, channel_id, message_id, emoji, panel_type, created_at)
                        VALUES (:guild_id, :channel_id, :message_id, '🎰', :ptype, CURRENT_TIMESTAMP)
                        """
                    ),
                    {
                        "guild_id": guild_id,
                        "channel_id": channel_id,
                        "message_id": message_id,
                        "ptype": self.PANEL_TYPE,
                    },
                )
        except Exception as e:
            logger.error(f"Failed to save Shuffle panel info: {e}")

    async def create_panel(self, channel: discord.TextChannel):
        try:
            embed = discord.Embed(
                title="🎰 Verify Your Shuffle Account",
                description=(
                    "Verify that you're one of our Shuffle affiliates to unlock your reward role!\n\n"
                    "**How to Verify:**\n"
                    "Click the **'Verify Shuffle Account'** button below and enter your "
                    "Shuffle.com username. We'll check it against our affiliate stats and "
                    "grant your role instantly."
                ),
                color=EMBED_COLOR,
            )
            embed.add_field(
                name="📋 Before you start",
                value=(
                    "• Make sure you signed up on Shuffle using our affiliate code\n"
                    "• Enter your **exact** Shuffle username\n"
                    "• One Shuffle account per Discord user"
                ),
                inline=False,
            )
            embed.set_footer(text="Click 'Verify Shuffle Account' to get started")

            view = ShufflePanelView(self.bot, self.engine, self.settings_getter)
            message = await channel.send(embed=embed, view=view)

            self.panel_guild_id = channel.guild.id
            self.panel_channel_id = channel.id
            self.panel_message_id = message.id
            self._save_panel_info(channel.guild.id, channel.id, message.id)

            logger.info(f"Created Shuffle panel in {channel.guild.name} / #{channel.name}")
            return True
        except Exception as e:
            logger.error(f"Failed to create Shuffle panel: {e}")
            return False


async def setup_shuffle_panel_system(bot, engine, settings_getter):
    """Set up the Shuffle verify panel system with per-guild instances."""
    panels = {}

    for guild in bot.guilds:
        panel = ShufflePanel(bot, engine, settings_getter, guild_id=guild.id)
        panels[guild.id] = panel
        logger.debug(f"✅ [Guild {guild.name}] Shuffle verify panel initialized")

    @bot.command(name="createshufflepanel")
    @commands.has_permissions(administrator=True)
    async def create_shuffle_panel_cmd(ctx):
        """[ADMIN] Create the Shuffle verify panel in this channel"""
        panel = panels.get(ctx.guild.id)
        if not panel:
            await ctx.send("❌ Shuffle panel not initialized for this server")
            return

        success = await panel.create_panel(ctx.channel)
        if success:
            await ctx.send("✅ Shuffle verify panel created! Affiliates can now verify their accounts.")
        else:
            await ctx.send("❌ Failed to create Shuffle panel. Check logs for details.")

    # Re-attach views to existing panels on bot restart
    for guild_id, panel in panels.items():
        if panel.panel_message_id and panel.panel_channel_id:
            try:
                channel = bot.get_channel(panel.panel_channel_id)
                if channel:
                    message = await channel.fetch_message(panel.panel_message_id)
                    view = ShufflePanelView(bot, engine, settings_getter)
                    await message.edit(view=view)
                    logger.debug(f"Re-attached Shuffle panel view to existing message in guild {guild_id}")
            except Exception as e:
                logger.error(f"Failed to re-attach Shuffle panel view for guild {guild_id}: {e}")

    return panels
