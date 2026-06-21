"""Subscription-tier role panel.

A persistent panel with one "Claim subscription role" button. When a user clicks
it, the bot looks up their highest active paid tier across the servers they
administer (server_admins, populated at dashboard login), then full-syncs their
tier role on the official guild: removes any other configured tier role they
hold and adds the one matching their tier.

Tier→role ids are stored in bot_settings (sub_role_tier1_id … sub_role_tier4_id)
under the official guild.
"""

import logging

import discord
from discord.ui import Button, View

from utils.subscription_tier import get_user_highest_tier

from ._panel_base import OFFICIAL_GUILD_ID, GlobalPanel, get_setting

logger = logging.getLogger(__name__)

# Maps the four panel tiers to their bot_settings role-id key + a label.
# "free" / tier1 = no paid role (the claim button is only meaningful for paid).
_TIER_KEYS = {
    "tier2": ("sub_role_tier2_id", "Tier 2"),
    "tier3": ("sub_role_tier3_id", "Tier 3"),
    "tier4": ("sub_role_tier4_id", "Tier 4"),
}
# Tier 1 maps to sub_role_tier1_id; included so a free/owner still gets a role if
# one is configured, and so we know the full set of "managed" role ids to sync.
_ALL_TIER_KEYS = {
    "free": "sub_role_tier1_id",
    "tier2": "sub_role_tier2_id",
    "tier3": "sub_role_tier3_id",
    "tier4": "sub_role_tier4_id",
}

_TIER_LABEL = {"free": "Tier 1", "tier2": "Tier 2", "tier3": "Tier 3", "tier4": "Tier 4"}


class SubRolePanelView(View):
    """Persistent view carrying the claim button (custom_id stable across
    restarts)."""

    def __init__(self, bot, engine):
        super().__init__(timeout=None)
        self.bot = bot
        self.engine = engine

    def _configured_role_ids(self, guild):
        """{tier: discord.Role} for every tier that has a valid configured role."""
        out = {}
        for tier, key in _ALL_TIER_KEYS.items():
            rid = get_setting(self.engine, key)
            if not rid or not str(rid).isdigit():
                continue
            role = guild.get_role(int(rid))
            if role:
                out[tier] = role
        return out

    @discord.ui.button(
        label="Claim subscription role",
        style=discord.ButtonStyle.success,
        emoji="🎟️",
        custom_id="claim_subscription_role",
    )
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await self._handle_claim(interaction)
        except Exception as e:
            logger.error(f"[sub_roles] claim error: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Something went wrong.", ephemeral=True)

    async def _handle_claim(self, interaction: discord.Interaction):
        guild = self.bot.get_guild(OFFICIAL_GUILD_ID)
        if not guild:
            await interaction.response.send_message("❌ The official server isn't available right now.", ephemeral=True)
            return

        member = guild.get_member(interaction.user.id)
        if not member:
            await interaction.response.send_message(
                "❌ You need to be a member of the official server to claim a role.", ephemeral=True
            )
            return

        tier = get_user_highest_tier(self.engine, interaction.user.id)
        configured = self._configured_role_ids(guild)
        target_role = configured.get(tier)

        # No paid subscription (or tier1 with no configured role) → strip any
        # managed tier roles they might still hold and tell them.
        managed_roles = set(configured.values())
        to_remove = [r for r in member.roles if r in managed_roles and r != target_role]

        if tier == "free" or target_role is None:
            if to_remove:
                try:
                    await member.remove_roles(*to_remove, reason="Subscription tier sync: no active paid tier")
                except discord.Forbidden:
                    pass
            await interaction.response.send_message(
                "ℹ️ You don't have an active paid subscription on any server you administer, "
                "so there's no tier role to grant. Subscribe on the dashboard, then click again.",
                ephemeral=True,
            )
            return

        # Already correct?
        if target_role in member.roles and not to_remove:
            await interaction.response.send_message(
                f"✅ You already have the **{target_role.name}** role.", ephemeral=True
            )
            return

        try:
            if to_remove:
                await member.remove_roles(*to_remove, reason=f"Subscription tier sync: now {tier}")
            if target_role not in member.roles:
                await member.add_roles(target_role, reason=f"Subscription tier sync: {tier}")
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ I don't have permission to manage that role. Ask an admin to move my role "
                "above the subscription roles.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"🎟️ You've been given the **{target_role.name}** role ({_TIER_LABEL.get(tier, tier)}).",
            ephemeral=True,
        )


class SubRolePanel(GlobalPanel):
    PANEL_TYPE = "sub_roles"

    def __init__(self, bot, engine, guild_id=OFFICIAL_GUILD_ID):
        super().__init__(bot, engine, guild_id)
        self._view = SubRolePanelView(bot, engine)

    def build_embed(self, data=None) -> discord.Embed:
        embed = discord.Embed(
            title="🎟️ Subscription Roles",
            description=(
                "Click the button below to claim the Discord role for your active "
                "subscription tier.\n\n"
                "Your role matches the **highest active paid tier** among the servers "
                "you manage on the dashboard. If you upgrade or downgrade, click again "
                "to re-sync."
            ),
            color=0xFACC15,
        )
        embed.set_footer(text="Make sure you've logged into the dashboard at least once.")
        return embed

    def build_view(self):
        return self._view


async def setup_sub_role_panel_system(bot, engine):
    """Build the sub-role panel registry, register the global persistent view,
    and re-attach it to an existing panel message on restart."""
    panel = SubRolePanel(bot, engine)
    panels = {OFFICIAL_GUILD_ID: panel}

    # Register ONE global persistent view so the button keeps working across
    # restarts (matches every posted sub-role message via its custom_id).
    try:
        bot.add_view(SubRolePanelView(bot, engine))
    except Exception as e:
        logger.warning(f"[sub_roles] add_view failed (non-fatal): {e}")

    # Re-attach to the existing message on restart.
    if panel.panel_message_id and panel.panel_channel_id:
        try:
            channel = bot.get_channel(int(panel.panel_channel_id))
            if channel:
                message = await channel.fetch_message(int(panel.panel_message_id))
                await message.edit(view=SubRolePanelView(bot, engine))
        except Exception as e:
            logger.info(f"[sub_roles] re-attach skipped: {e}")

    return panels
