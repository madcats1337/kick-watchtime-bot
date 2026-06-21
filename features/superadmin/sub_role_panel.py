"""Subscription-tier role panel (Components V2).

A persistent panel with one "Claim subscription role" button. When a user clicks
it, the bot looks up their highest active paid tier across the servers they
administer (server_admins, populated at dashboard login), then full-syncs their
tier role on the official guild: removes any other configured tier role they
hold and adds the one matching their tier.

Tier→role ids are stored in bot_settings (sub_role_tier1_id … sub_role_tier4_id)
under the official guild.

Rendered with Components V2: the panel is a LayoutView containing a Container of
text plus an ActionRow with the claim button (no embed).
"""

import logging

import discord

from utils.subscription_tier import get_user_highest_tier

from ._panel_base import ACCENT, OFFICIAL_GUILD_ID, GlobalPanel, get_setting, text_block

logger = logging.getLogger(__name__)

# Tier 1..4 → bot_settings role-id key. The full set is what we "manage" when
# syncing (so an old tier role gets removed when a user changes tier).
_ALL_TIER_KEYS = {
    "free": "sub_role_tier1_id",
    "tier2": "sub_role_tier2_id",
    "tier3": "sub_role_tier3_id",
    "tier4": "sub_role_tier4_id",
}

_TIER_LABEL = {"free": "Tier 1", "tier2": "Tier 2", "tier3": "Tier 3", "tier4": "Tier 4"}

_PANEL_TEXT = (
    "# 🎟️ Subscription Roles\n"
    "Click the button below to claim the Discord role for your active "
    "subscription tier.\n\n"
    "Your role matches the **highest active paid tier** among the servers you "
    "manage on the dashboard. If you upgrade or downgrade, click again to re-sync.\n"
    "-# Make sure you've logged into the dashboard at least once."
)


class SubRolePanelView(discord.ui.LayoutView):
    """Persistent Components V2 panel: explainer Container + claim button.

    timeout=None + a stable button custom_id make it survive restarts once
    registered via bot.add_view."""

    def __init__(self, bot, engine):
        super().__init__(timeout=None)
        self.bot = bot
        self.engine = engine

        container = discord.ui.Container(accent_colour=ACCENT)
        container.add_item(text_block(_PANEL_TEXT))
        container.add_item(discord.ui.ActionRow(self._ClaimButton()))
        self.add_item(container)

    class _ClaimButton(discord.ui.Button):
        def __init__(self):
            super().__init__(
                label="Claim subscription role",
                style=discord.ButtonStyle.success,
                emoji="🎟️",
                custom_id="claim_subscription_role",
            )

        async def callback(self, interaction: discord.Interaction):
            view: "SubRolePanelView" = self.view  # type: ignore[assignment]
            try:
                await view._handle_claim(interaction)
            except Exception as e:
                logger.error(f"[sub_roles] claim error: {e}")
                if not interaction.response.is_done():
                    await interaction.response.send_message("❌ Something went wrong.", ephemeral=True)

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

        # Any managed tier roles the user holds that aren't the target → remove.
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

    def build_view(self, data=None) -> discord.ui.LayoutView:
        return SubRolePanelView(self.bot, self.engine)


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
