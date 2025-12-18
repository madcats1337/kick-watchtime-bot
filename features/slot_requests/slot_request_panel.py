"""
Slot Request Panel - Interactive Discord panel for managing slot requests
Shows statistics and allows picking random slots via buttons
"""

import logging
import discord
from discord.ext import commands, tasks
from discord.ui import View, Button, Modal, TextInput
from sqlalchemy import text
from datetime import datetime

logger = logging.getLogger(__name__)

# Emojis
EMOJI_RANDOM = "🎲"  # Pick random slot
EMOJI_REFRESH = "♻️"  # Refresh panel

class SetMaxRequestsModal(Modal, title="Set Max Requests Per User"):
    """Modal for setting maximum requests per user"""

    max_requests = TextInput(
        label="Maximum Requests (0 = unlimited)",
        placeholder="Enter a number from 0 to 10",
        required=True,
        min_length=1,
        max_length=2,
        default="0"
    )

    def __init__(self, panel):
        super().__init__()
        self.panel = panel
        # Set current value as default
        current = panel.tracker.max_requests_per_user
        self.max_requests.default = str(current)

    async def on_submit(self, interaction: discord.Interaction):
        """Handle modal submission"""
        try:
            # Validate input
            value = int(self.max_requests.value)

            if value < 0 or value > 10:
                await interaction.response.send_message(
                    "❌ Please enter a number between 0 and 10.",
                    ephemeral=True
                )
                return

            # Set the limit
            success = self.panel.tracker.set_max_requests(value)

            if success:
                limit_text = f"{value} request(s)" if value > 0 else "unlimited"
                await interaction.response.send_message(
                    f"✅ Max requests per user set to: **{limit_text}**",
                    ephemeral=True
                )

                # Update the panel
                await self.panel.update_panel(force=True)
            else:
                await interaction.response.send_message(
                    "❌ Failed to update the limit. Check logs for details.",
                    ephemeral=True
                )

        except ValueError:
            await interaction.response.send_message(
                "❌ Please enter a valid number.",
                ephemeral=True
            )

class SlotPanelView(View):
    """Button view for slot request panel"""

    def __init__(self, panel):
        super().__init__(timeout=None)  # Persistent view
        self.panel = panel

        # Add buttons
        self.add_item(Button(
            style=discord.ButtonStyle.primary,
            label="Pick Random",
            emoji="🎲",
            custom_id="slot_pick_random"
        ))
        self.add_item(Button(
            style=discord.ButtonStyle.secondary,
            label="Refresh",
            emoji="♻️",
            custom_id="slot_refresh"
        ))
        self.add_item(Button(
            style=discord.ButtonStyle.success,
            label="Enable Requests",
            emoji="✅",
            custom_id="slot_enable"
        ))
        self.add_item(Button(
            style=discord.ButtonStyle.danger,
            label="Disable Requests",
            emoji="❌",
            custom_id="slot_disable"
        ))
        self.add_item(Button(
            style=discord.ButtonStyle.secondary,
            label="Set Limit",
            emoji="🔢",
            custom_id="slot_set_limit"
        ))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Check if user has permission to use buttons"""
        # Check if user is admin
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Only administrators can use this panel.", ephemeral=True)
            return False
        return True

    async def callback(self, interaction: discord.Interaction, button: Button):
        """Handle button clicks"""
        try:
            if button.custom_id == "slot_pick_random":
                await self.panel.pick_random_slot_interaction(interaction)
            elif button.custom_id == "slot_refresh":
                await self.panel.refresh_interaction(interaction)
            elif button.custom_id == "slot_enable":
                await self.panel.enable_requests_interaction(interaction)
            elif button.custom_id == "slot_disable":
                await self.panel.disable_requests_interaction(interaction)
            elif button.custom_id == "slot_set_limit":
                await self.panel.set_limit_interaction(interaction)
        except Exception as e:
            logger.error(f"Error handling button interaction: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ An error occurred.", ephemeral=True)

class SlotRequestPanel:
    """Manages the slot request panel message"""

    def __init__(self, bot, engine, slot_call_tracker, kick_send_callback=None):
        self.bot = bot
        self.engine = engine
        self.tracker = slot_call_tracker
        self.kick_send_callback = kick_send_callback
        self.panel_message_id = None
        self.panel_channel_id = None
        self.last_update_time = None  # Track last update time for rate limiting
        self.update_cooldown = 30  # Minimum 30 seconds between updates
        self._load_panel_info()

    def _load_panel_info(self):
        """Load panel message ID and channel from database"""
        if not self.engine:
            return

        try:
            with self.engine.connect() as conn:
                result = conn.execute(text("""
                    SELECT value FROM bot_settings
                    WHERE key = 'slot_panel_message_id'
                """)).fetchone()

                if result:
                    self.panel_message_id = int(result[0])

                result = conn.execute(text("""
                    SELECT value FROM bot_settings
                    WHERE key = 'slot_panel_channel_id'
                """)).fetchone()

                if result:
                    self.panel_channel_id = int(result[0])

        except Exception as e:
            logger.error(f"Failed to load panel info: {e}")

    def _save_panel_info(self):
        """Save panel message ID and channel to database"""
        if not self.engine:
            return

        try:
            with self.engine.begin() as conn:
                # Save message ID
                if self.panel_message_id:
                    conn.execute(text("""
                        INSERT INTO bot_settings (key, value, updated_at)
                        VALUES ('slot_panel_message_id', :value, CURRENT_TIMESTAMP)
                        ON CONFLICT (key)
                        DO UPDATE SET value = :value, updated_at = CURRENT_TIMESTAMP
                    """), {"value": str(self.panel_message_id)})

                # Save channel ID
                if self.panel_channel_id:
                    conn.execute(text("""
                        INSERT INTO bot_settings (key, value, updated_at)
                        VALUES ('slot_panel_channel_id', :value, CURRENT_TIMESTAMP)
                        ON CONFLICT (key)
                        DO UPDATE SET value = :value, updated_at = CURRENT_TIMESTAMP
                    """), {"value": str(self.panel_channel_id)})

        except Exception as e:
            logger.error(f"Failed to save panel info: {e}")

    def _get_slot_stats(self):
        """Get slot request statistics from database"""
        if not self.engine:
            return None

        # Get server_id from tracker
        server_id = self.tracker.server_id if self.tracker else None
        if not server_id:
            logger.warning("No server_id available for stats, showing all servers")

        try:
            with self.engine.connect() as conn:
                # Get counts - filter by server_id if available
                if server_id:
                    total = conn.execute(text("SELECT COUNT(*) FROM slot_requests WHERE discord_server_id = :server_id"), {"server_id": server_id}).fetchone()[0]
                    unpicked = conn.execute(text("SELECT COUNT(*) FROM slot_requests WHERE picked = FALSE AND discord_server_id = :server_id"), {"server_id": server_id}).fetchone()[0]
                    picked = conn.execute(text("SELECT COUNT(*) FROM slot_requests WHERE picked = TRUE AND discord_server_id = :server_id"), {"server_id": server_id}).fetchone()[0]

                    # Get last picked slot for this server
                    last_picked = conn.execute(text("""
                        SELECT kick_username, slot_call, picked_at
                        FROM slot_requests
                        WHERE picked = TRUE AND discord_server_id = :server_id
                        ORDER BY picked_at DESC
                        LIMIT 1
                    """), {"server_id": server_id}).fetchone()
                else:
                    # Fallback: show all servers
                    total = conn.execute(text("SELECT COUNT(*) FROM slot_requests")).fetchone()[0]
                    unpicked = conn.execute(text("SELECT COUNT(*) FROM slot_requests WHERE picked = FALSE")).fetchone()[0]
                    picked = conn.execute(text("SELECT COUNT(*) FROM slot_requests WHERE picked = TRUE")).fetchone()[0]

                    # Get last picked slot
                    last_picked = conn.execute(text("""
                        SELECT kick_username, slot_call, picked_at
                        FROM slot_requests
                        WHERE picked = TRUE
                        ORDER BY picked_at DESC
                        LIMIT 1
                    """)).fetchone()

                return {
                    "total": total,
                    "unpicked": unpicked,
                    "picked": picked,
                    "last_picked": last_picked
                }
        except Exception as e:
            logger.error(f"Failed to get slot stats: {e}")
            return None

    def _create_panel_embed(self):
        """Create the panel embed with current stats"""
        stats = self._get_slot_stats()

        if not stats:
            embed = discord.Embed(
                title="🎰 Slot Request Panel",
                description="❌ Could not load statistics",
                color=discord.Color.red()
            )
            return embed

        # Build description
        desc_lines = []
        desc_lines.append(f"**Total Requests:** {stats['total']}")
        desc_lines.append(f"**Available:** {stats['unpicked']}")
        desc_lines.append(f"**Already Picked:** {stats['picked']}")

        if stats['last_picked']:
            username, slot_call, picked_at = stats['last_picked']
            time_str = picked_at.strftime("%H:%M:%S") if picked_at else "Unknown"
            desc_lines.append(f"\n**Last Picked:**")
            desc_lines.append(f"• {slot_call}")
            desc_lines.append(f"• by {username} at {time_str}")
        else:
            desc_lines.append(f"\n**Last Picked:** None yet")

        embed = discord.Embed(
            title="🎰 Slot Request Panel",
            description="\n".join(desc_lines),
            color=discord.Color.gold()
        )

        # Status indicator
        status = "✅ Open" if self.tracker.is_enabled() else "❌ Closed"
        embed.add_field(name="Status", value=status, inline=True)

        # Max requests per user
        max_req = self.tracker.max_requests_per_user
        limit_text = f"{max_req} request(s)" if max_req > 0 else "Unlimited"
        embed.add_field(name="Max Per User", value=limit_text, inline=True)

        # Instructions
        embed.add_field(
            name="How to use",
            value="Use the buttons below to manage slot requests",
            inline=False
        )

        embed.set_footer(text=f"Last updated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}")

        return embed

    async def create_panel(self, channel: discord.TextChannel):
        """Create a new panel in the specified channel"""
        try:
            embed = self._create_panel_embed()
            view = SlotPanelView(self)

            # Setup button callbacks
            for item in view.children:
                if isinstance(item, Button):
                    item.callback = lambda interaction, b=item: view.callback(interaction, b)

            message = await channel.send(embed=embed, view=view)

            # Save panel info
            self.panel_message_id = message.id
            self.panel_channel_id = channel.id
            self._save_panel_info()

            logger.info(f"Created slot request panel in {channel.name}")
            return True

        except Exception as e:
            logger.error(f"Failed to create panel: {e}")
            return False

    async def update_panel(self, force=False):
        """
        Update the existing panel

        Args:
            force: If True, bypass rate limiting (for user actions like button clicks)
        """
        if not self.panel_message_id or not self.panel_channel_id:
            return False

        # Rate limiting - prevent Discord API spam
        if not force and self.last_update_time:
            time_since_last = (datetime.utcnow() - self.last_update_time).total_seconds()
            if time_since_last < self.update_cooldown:
                logger.debug(f"Skipping panel update (cooldown: {self.update_cooldown - time_since_last:.1f}s remaining)")
                return False

        try:
            channel = self.bot.get_channel(self.panel_channel_id)
            if not channel:
                logger.error(f"Panel channel {self.panel_channel_id} not found")
                return False

            message = await channel.fetch_message(self.panel_message_id)
            if not message:
                logger.error(f"Panel message {self.panel_message_id} not found")
                return False

            embed = self._create_panel_embed()
            view = SlotPanelView(self)

            # Setup button callbacks
            for item in view.children:
                if isinstance(item, Button):
                    item.callback = lambda interaction, b=item: view.callback(interaction, b)

            await message.edit(embed=embed, view=view)
            self.last_update_time = datetime.utcnow()  # Update timestamp

            return True

        except discord.NotFound:
            logger.warning("Panel message not found, needs to be recreated")
            self.panel_message_id = None
            self.panel_channel_id = None
            return False
        except Exception as e:
            logger.error(f"Failed to update panel: {e}")
            return False

    async def pick_random_slot_interaction(self, interaction: discord.Interaction):
        """Handle pick random button click"""
        await interaction.response.defer(ephemeral=True)

        result = await self._pick_random_slot(interaction.channel)
        if result:
            await interaction.followup.send("✅ Random slot picked!", ephemeral=True)
        else:
            await interaction.followup.send("❌ No slot requests available.", ephemeral=True)

    async def refresh_interaction(self, interaction: discord.Interaction):
        """Handle refresh button click"""
        await interaction.response.defer(ephemeral=True)

        success = await self.update_panel(force=True)  # Force update for user action
        if success:
            await interaction.followup.send("✅ Panel refreshed!", ephemeral=True)
        else:
            await interaction.followup.send("❌ Failed to refresh panel.", ephemeral=True)

    async def enable_requests_interaction(self, interaction: discord.Interaction):
        """Handle enable requests button click"""
        await interaction.response.defer(ephemeral=True)

        if self.tracker.is_enabled():
            await interaction.followup.send("ℹ️ Slot requests are already enabled.", ephemeral=True)
        else:
            await self.tracker.set_enabled(True)
            await interaction.followup.send("✅ Slot requests **enabled**!", ephemeral=True)

    async def disable_requests_interaction(self, interaction: discord.Interaction):
        """Handle disable requests button click"""
        await interaction.response.defer(ephemeral=True)

        if not self.tracker.is_enabled():
            await interaction.followup.send("ℹ️ Slot requests are already disabled.", ephemeral=True)
        else:
            await self.tracker.set_enabled(False)
            await interaction.followup.send("✅ Slot requests **disabled**!", ephemeral=True)

    async def set_limit_interaction(self, interaction: discord.Interaction):
        """Handle set limit button click - show modal"""
        modal = SetMaxRequestsModal(self)
        await interaction.response.send_modal(modal)

    async def handle_reaction(self, payload):
        """Handle reaction on the panel"""
        # Ignore if not the panel message
        if payload.message_id != self.panel_message_id:
            return

        # Ignore bot's own reactions
        if payload.user_id == self.bot.user.id:
            return

        # Get the user
        user = self.bot.get_user(payload.user_id)
        if not user:
            return

        # Get the channel and message
        channel = self.bot.get_channel(payload.channel_id)
        if not channel:
            return

        try:
            message = await channel.fetch_message(payload.message_id)

            # Remove user's reaction
            await message.remove_reaction(payload.emoji, user)

            # Check if user has admin permissions
            member = channel.guild.get_member(user.id)
            if not member or not member.guild_permissions.administrator:
                # Silently ignore non-admins
                return

            # Handle the reaction
            if str(payload.emoji) == EMOJI_RANDOM:
                await self._pick_random_slot(channel)
            elif str(payload.emoji) == EMOJI_REFRESH:
                await self.update_panel()

        except Exception as e:
            logger.error(f"Error handling panel reaction: {e}")

    async def _pick_random_slot(self, channel):
        """Pick a random slot request - returns True if successful, False if no slots available"""
        if not self.engine:
            return False

        # Get guild_id from channel
        guild_id = channel.guild.id if hasattr(channel, 'guild') else None
        if not guild_id:
            logger.error("Cannot pick slot: no guild_id available")
            return False

        try:
            with self.engine.connect() as conn:
                # Get a random unpicked slot request for this server
                result = conn.execute(text("""
                    SELECT id, kick_username, slot_call, requested_at
                    FROM slot_requests
                    WHERE picked = FALSE AND discord_server_id = :server_id
                    ORDER BY RANDOM()
                    LIMIT 1
                """), {"server_id": guild_id}).fetchone()

                if not result:
                    # No slots available - just update panel
                    await self.update_panel()
                    return False

                request_id, username, slot_call, requested_at = result

                # Mark as picked
                with self.engine.begin() as update_conn:
                    update_conn.execute(text("""
                        UPDATE slot_requests
                        SET picked = TRUE, picked_at = CURRENT_TIMESTAMP
                        WHERE id = :id
                    """), {"id": request_id})

                logger.info(f"[Server {guild_id}] Panel picked random slot: {slot_call} by {username}")

                # Send message to Kick chat
                if self.kick_send_callback:
                    try:
                        kick_message = f"🎰 Random slot picked: {slot_call} (requested by @{username})"
                        await self.kick_send_callback(kick_message, guild_id=guild_id)
                    except Exception as kick_error:
                        logger.error(f"Failed to send pick notification to Kick: {kick_error}")

                # Update panel
                await self.update_panel()
                return True

        except Exception as e:
            logger.error(f"Failed to pick random slot from panel: {e}")
            return False

class SlotRequestPanelCommands(commands.Cog):
    """Commands for managing the slot request panel"""

    def __init__(self, bot, panel: SlotRequestPanel):
        self.bot = bot
        self.panel = panel
        self.auto_update_task.start()

    def cog_unload(self):
        """Clean up when cog is unloaded"""
        self.auto_update_task.cancel()

    @tasks.loop(minutes=3)
    async def auto_update_task(self):
        """Auto-update panel every 3 minutes"""
        await self.panel.update_panel()

    @auto_update_task.before_loop
    async def before_auto_update(self):
        """Wait for bot to be ready"""
        await self.bot.wait_until_ready()

    @commands.command(name='slotpanel')
    @commands.has_permissions(administrator=True)
    async def create_slot_panel(self, ctx):
        """
        [ADMIN] Create a slot request panel in this channel
        Usage: !slotpanel
        """
        success = await self.panel.create_panel(ctx.channel)
        if success:
            await ctx.send("✅ Slot request panel created! React with 🎲 to pick a random slot.")
        else:
            await ctx.send("❌ Failed to create panel. Check logs for details.")

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        """Handle reactions on the panel"""
        await self.panel.handle_reaction(payload)

async def setup_slot_panel(bot, engine, slot_call_tracker, kick_send_callback=None):
    """Setup the slot request panel system"""
    panel = SlotRequestPanel(bot, engine, slot_call_tracker, kick_send_callback)

    # Set panel reference in tracker so it can trigger updates
    slot_call_tracker.panel = panel

    await bot.add_cog(SlotRequestPanelCommands(bot, panel))
    logger.info("Slot request panel system initialized")
    return panel
