"""Global Discord slash commands exposed by the Wagerlabs application."""

import logging

import discord
from discord import app_commands
from discord.ext import commands

from utils.log_context import server_context
from utils.server_urls import get_server_public_page_url

logger = logging.getLogger(__name__)

WAGERLABS_YELLOW = 0xFACC15
WAGERLABS_LANDING_URL = "https://wagerlabs.app/"


def _link_view(*buttons: tuple[str, str]) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    for label, url in buttons:
        view.add_item(discord.ui.Button(label=label, url=url))
    return view


def register_wagerlabs_slash_commands(bot: commands.Bot, engine) -> None:
    """Register the global, read-only slash commands once on the local tree."""

    if bot.tree.get_command("wagerlabs") is None:

        @bot.tree.command(
            name="wagerlabs",
            description="Learn what Wagerlabs does and open the official website.",
        )
        @app_commands.guild_only()
        async def wagerlabs(interaction: discord.Interaction) -> None:
            guild_id = interaction.guild_id
            guild_name = interaction.guild.name if interaction.guild else None
            with server_context(guild_id, guild_name):
                fair_url = get_server_public_page_url(engine, guild_id, "/provably-fair")
                embed = discord.Embed(
                    title="Wagerlabs",
                    description=(
                        "Stream automation for Kick and Twitch creators, with "
                        "optional Discord integration, viewer rewards, raffles, "
                        "slot requests, games, and OBS widgets."
                    ),
                    color=WAGERLABS_YELLOW,
                )
                embed.add_field(
                    name="Official website",
                    value="Open the Wagerlabs landing page to explore the platform.",
                    inline=False,
                )
                embed.set_footer(text="wagerlabs.app")
                view = _link_view(
                    ("Open Wagerlabs", WAGERLABS_LANDING_URL),
                    ("Verify draws", fair_url),
                )
                await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
                logger.debug("Handled /wagerlabs")

    if bot.tree.get_command("fair") is None:

        @bot.tree.command(
            name="fair",
            description=("Open this server's public verifier for provably fair draws."),
        )
        @app_commands.guild_only()
        async def fair(interaction: discord.Interaction) -> None:
            guild_id = interaction.guild_id
            guild_name = interaction.guild.name if interaction.guild else None
            with server_context(guild_id, guild_name):
                fair_url = get_server_public_page_url(engine, guild_id, "/provably-fair")
                embed = discord.Embed(
                    title="Provably Fair Draws",
                    description=(
                        "Wagerlabs records the commitment, seeds, nonce, and "
                        "result needed to independently verify supported draws."
                    ),
                    color=WAGERLABS_YELLOW,
                )
                view = _link_view(("Open verifier", fair_url))
                await interaction.response.send_message(embed=embed, view=view)
                logger.debug("Handled /fair")


async def sync_global_slash_commands(bot: commands.Bot) -> bool:
    """Publish the local command tree globally, once per process.

    A failed HTTP sync leaves the guard unset so a later Discord gateway
    reconnect can retry without restarting the service.
    """

    if getattr(bot, "_wagerlabs_slash_commands_synced", False):
        return True

    try:
        synced = await bot.tree.sync()
    except Exception as exc:
        logger.warning(
            "Could not sync global Discord slash commands: %s",
            exc,
            exc_info=True,
        )
        return False

    bot._wagerlabs_slash_commands_synced = True
    command_names = ", ".join(f"/{command.name}" for command in synced) or "none"
    logger.info("Global Discord slash commands synced: %s", command_names)
    return True
