"""
Link Panel - Interactive Discord panel for Kick OAuth linking
Uses buttons and ephemeral messages instead of reactions and DMs
"""

import logging
import discord
from discord.ext import commands
from discord.ui import View, Button
from sqlalchemy import text

logger = logging.getLogger(__name__)


class LinkPanelView(View):
    """Button view for link panel"""
    
    def __init__(self, bot, engine, oauth_url_generator):
        super().__init__(timeout=None)  # Persistent view
        self.bot = bot
        self.engine = engine
        self.oauth_url_generator = oauth_url_generator
        
        # Add link button
        self.add_item(Button(
            style=discord.ButtonStyle.success,
            label="Link Account",
            emoji="🔗",
            custom_id="link_account"
        ))
    
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """This runs before any button callback"""
        return True  # Allow everyone to use the link button
    
    async def callback(self, interaction: discord.Interaction, button: Button):
        """Handle button clicks"""
        try:
            if button.custom_id == "link_account":
                await self.handle_link_account(interaction)
        except Exception as e:
            logger.error(f"Error handling link button interaction: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ An error occurred.", ephemeral=True)
    
    async def handle_link_account(self, interaction: discord.Interaction):
        """Handle link account button click"""
        discord_id = interaction.user.id
        
        # Check if already linked
        try:
            with self.engine.connect() as conn:
                existing = conn.execute(text(
                    "SELECT kick_name FROM links WHERE discord_id = :d"
                ), {"d": discord_id}).fetchone()
                
                if existing:
                    await interaction.response.send_message(
                        f"✅ You are already linked to **{existing[0]}**!",
                        ephemeral=True
                    )
                    return
        except Exception as e:
            logger.error(f"Error checking existing link: {e}")
            await interaction.response.send_message(
                "❌ Database error. Please try again.",
                ephemeral=True
            )
            return
        
        # Generate OAuth URL
        try:
            oauth_url = self.oauth_url_generator(discord_id)
        except Exception as e:
            logger.error(f"Error generating OAuth URL: {e}")
            await interaction.response.send_message(
                "❌ Failed to generate OAuth link. Please contact an admin.",
                ephemeral=True
            )
            return
        
        # Create embed with instructions
        embed = discord.Embed(
            title="🔗 Link Your Kick Account",
            description="Click the button below to securely link your Kick account with Discord.",
            color=0x53FC18
        )
        embed.add_field(
            name="📝 Instructions",
            value=(
                "1. Click the **'Link with Kick'** button below\n"
                "2. Log in to Kick (if needed)\n"
                "3. Authorize the connection\n"
                "4. You're done! 🎉"
            ),
            inline=False
        )
        embed.add_field(
            name="🔒 Security",
            value="This link is unique to you and expires in 10 minutes.",
            inline=False
        )
        embed.set_footer(text="Keep this link private • Expires in 10 minutes")
        
        # Create view with OAuth link button
        view = View(timeout=600)  # 10 minute timeout
        oauth_button = Button(
            label="Link with Kick",
            style=discord.ButtonStyle.link,
            url=oauth_url,
            emoji="🎮"
        )
        view.add_item(oauth_button)
        
        # Send ephemeral message (only visible to user)
        await interaction.response.send_message(
            embed=embed,
            view=view,
            ephemeral=True
        )
        
        logger.info(f"Sent OAuth link to {interaction.user.name} (ID: {discord_id}) via ephemeral message")


class LinkPanel:
    """Manages the link panel message"""
    
    def __init__(self, bot, engine, oauth_url_generator):
        self.bot = bot
        self.engine = engine
        self.oauth_url_generator = oauth_url_generator
        self.panel_message_id = None
        self.panel_channel_id = None
        self.panel_guild_id = None
        self._load_panel_info()
    
    def _load_panel_info(self):
        """Load panel message info from database"""
        if not self.engine:
            return
        
        try:
            with self.engine.connect() as conn:
                # Get the most recent link panel
                result = conn.execute(text("""
                    SELECT guild_id, channel_id, message_id
                    FROM link_panels
                    ORDER BY created_at DESC
                    LIMIT 1
                """)).fetchone()
                
                if result:
                    self.panel_guild_id = result[0]
                    self.panel_channel_id = result[1]
                    self.panel_message_id = result[2]
                    
        except Exception as e:
            logger.error(f"Failed to load link panel info: {e}")
    
    def _save_panel_info(self, guild_id: int, channel_id: int, message_id: int):
        """Save panel message info to database"""
        if not self.engine:
            return
        
        try:
            with self.engine.begin() as conn:
                # Delete old panels for this guild
                conn.execute(text("""
                    DELETE FROM link_panels WHERE guild_id = :guild_id
                """), {"guild_id": guild_id})
                
                # Insert new panel info
                conn.execute(text("""
                    INSERT INTO link_panels (guild_id, channel_id, message_id, emoji, created_at)
                    VALUES (:guild_id, :channel_id, :message_id, '🔗', CURRENT_TIMESTAMP)
                """), {
                    "guild_id": guild_id,
                    "channel_id": channel_id,
                    "message_id": message_id
                })
                
        except Exception as e:
            logger.error(f"Failed to save link panel info: {e}")
    
    async def create_panel(self, channel: discord.TextChannel):
        """Create a new link panel in the specified channel"""
        try:
            # Create the embed
            embed = discord.Embed(
                title="🔗 Link Your Kick Account",
                description=(
                    "Link your Kick account with Discord to participate in raffles and track your watchtime!\n\n"
                    "**Benefits:**\n"
                    "• Earn raffle tickets from watchtime\n"
                    "• Get bonus tickets from subscriptions\n"
                    "• Participate in raffles and giveaways\n"
                    "• Earn roles based on Kick chat activity\n"
                    "• Track your stats and progress"
                ),
                color=0x53FC18
            )
            embed.add_field(
                name="How to Link",
                value="Click the **'Link Account'** button below to get started!",
                inline=False
            )
            embed.add_field(
                name="🔒 Privacy & Security",
                value=(
                    "• OAuth links are unique and expire after 10 minutes\n"
                    "• Links are sent in private messages only you can see\n"
                    "• Your Kick password is never shared with this bot"
                ),
                inline=False
            )
            embed.set_footer(text="Click 'Link Account' to get your personal OAuth link")
            
            # Create the view
            view = LinkPanelView(self.bot, self.engine, self.oauth_url_generator)
            
            # Setup button callback
            for item in view.children:
                if isinstance(item, Button):
                    item.callback = lambda interaction, b=item: view.callback(interaction, b)
            
            # Send the message
            message = await channel.send(embed=embed, view=view)
            
            # Save panel info
            self.panel_guild_id = channel.guild.id
            self.panel_channel_id = channel.id
            self.panel_message_id = message.id
            self._save_panel_info(channel.guild.id, channel.id, message.id)
            
            logger.info(f"Created link panel in {channel.guild.name} / #{channel.name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create link panel: {e}")
            return False


async def setup_link_panel_system(bot, engine, oauth_url_generator):
    """Setup the link panel system"""
    panel = LinkPanel(bot, engine, oauth_url_generator)
    
    # Add command to create the panel
    @bot.command(name='createlinkpanel')
    @commands.has_permissions(administrator=True)
    async def create_link_panel_cmd(ctx):
        """[ADMIN] Create the link panel in this channel"""
        success = await panel.create_panel(ctx.channel)
        if success:
            await ctx.send("✅ Link panel created! Users can now click the button to link their accounts.")
        else:
            await ctx.send("❌ Failed to create link panel. Check logs for details.")
    
    # Re-attach view to existing panel on bot restart
    if panel.panel_message_id and panel.panel_channel_id:
        try:
            channel = bot.get_channel(panel.panel_channel_id)
            if channel:
                message = await channel.fetch_message(panel.panel_message_id)
                view = LinkPanelView(bot, engine, oauth_url_generator)
                
                # Setup button callback
                for item in view.children:
                    if isinstance(item, Button):
                        item.callback = lambda interaction, b=item: view.callback(interaction, b)
                
                # Re-attach the view
                await message.edit(view=view)
                logger.info(f"Re-attached link panel view to existing message")
        except Exception as e:
            logger.error(f"Failed to re-attach link panel view: {e}")
    
    return panel
