"""
Slot Request Panel - Interactive Discord panel for managing slot requests
Shows statistics and allows picking random slots via reactions
"""

import logging
import discord
from discord.ext import commands, tasks
from sqlalchemy import text
from datetime import datetime

logger = logging.getLogger(__name__)

# Emojis
EMOJI_RANDOM = "🎲"  # Pick random slot
EMOJI_REFRESH = "♻️"  # Refresh panel


class SlotRequestPanel:
    """Manages the slot request panel message"""
    
    def __init__(self, bot, engine, slot_call_tracker, kick_send_callback=None):
        self.bot = bot
        self.engine = engine
        self.tracker = slot_call_tracker
        self.kick_send_callback = kick_send_callback
        self.panel_message_id = None
        self.panel_channel_id = None
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
        
        try:
            with self.engine.connect() as conn:
                # Get counts
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
        
        # Instructions
        embed.add_field(
            name="How to use",
            value=f"{EMOJI_RANDOM} Pick random slot\n{EMOJI_REFRESH} Refresh stats",
            inline=False
        )
        
        embed.set_footer(text=f"Last updated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}")
        
        return embed
    
    async def create_panel(self, channel: discord.TextChannel):
        """Create a new panel in the specified channel"""
        try:
            embed = self._create_panel_embed()
            message = await channel.send(embed=embed)
            
            # Add reactions
            await message.add_reaction(EMOJI_RANDOM)
            await message.add_reaction(EMOJI_REFRESH)
            
            # Save panel info
            self.panel_message_id = message.id
            self.panel_channel_id = channel.id
            self._save_panel_info()
            
            logger.info(f"Created slot request panel in {channel.name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create panel: {e}")
            return False
    
    async def update_panel(self):
        """Update the existing panel"""
        if not self.panel_message_id or not self.panel_channel_id:
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
            await message.edit(embed=embed)
            
            return True
            
        except discord.NotFound:
            logger.warning("Panel message not found, needs to be recreated")
            self.panel_message_id = None
            self.panel_channel_id = None
            return False
        except Exception as e:
            logger.error(f"Failed to update panel: {e}")
            return False
    
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
        """Pick a random slot request"""
        if not self.engine:
            return
        
        try:
            with self.engine.connect() as conn:
                # Get a random unpicked slot request
                result = conn.execute(text("""
                    SELECT id, kick_username, slot_call, requested_at
                    FROM slot_requests
                    WHERE picked = FALSE
                    ORDER BY RANDOM()
                    LIMIT 1
                """)).fetchone()
                
                if not result:
                    # No slots available - just update panel
                    await self.update_panel()
                    return
                
                request_id, username, slot_call, requested_at = result
                
                # Mark as picked
                with self.engine.begin() as update_conn:
                    update_conn.execute(text("""
                        UPDATE slot_requests
                        SET picked = TRUE, picked_at = CURRENT_TIMESTAMP
                        WHERE id = :id
                    """), {"id": request_id})
                
                logger.info(f"Panel picked random slot: {slot_call} by {username}")
                
                # Send message to Kick chat
                if self.kick_send_callback:
                    try:
                        kick_message = f"🎰 Random slot picked: {slot_call} (requested by @{username})"
                        await self.kick_send_callback(kick_message)
                    except Exception as kick_error:
                        logger.error(f"Failed to send pick notification to Kick: {kick_error}")
                
                # Update panel
                await self.update_panel()
                
        except Exception as e:
            logger.error(f"Failed to pick random slot from panel: {e}")


class SlotRequestPanelCommands(commands.Cog):
    """Commands for managing the slot request panel"""
    
    def __init__(self, bot, panel: SlotRequestPanel):
        self.bot = bot
        self.panel = panel
        self.auto_update_task.start()
    
    def cog_unload(self):
        """Clean up when cog is unloaded"""
        self.auto_update_task.cancel()
    
    @tasks.loop(minutes=1)
    async def auto_update_task(self):
        """Auto-update panel every minute"""
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
