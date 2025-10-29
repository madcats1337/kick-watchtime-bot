"""
Slot Call Tracker - Monitor Kick chat for !call commands and post to Discord
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, Dict
import discord
from discord.ext import commands
from sqlalchemy import text

logger = logging.getLogger(__name__)


class SlotCallTracker:
    """Track slot calls from Kick chat and post to Discord"""
    
    def __init__(self, bot, discord_channel_id: Optional[int] = None, kick_send_callback=None, engine=None):
        self.bot = bot
        self.discord_channel_id = discord_channel_id
        self.engine = engine
        self.last_call_time: Dict[str, datetime] = {}  # Track per-user cooldown
        self.cooldown_seconds = 30  # 30 second cooldown per user
        self.max_username_length = 50  # Maximum username length
        self.max_slot_call_length = 200  # Maximum slot call text length
        self.kick_send_callback = kick_send_callback  # Callback to send messages to Kick chat
        
        # Initialize database and load enabled state
        self._init_database()
        self.enabled = self._load_enabled_state()
        
    def _init_database(self):
        """Create feature_settings table if it doesn't exist"""
        if not self.engine:
            logger.warning("No database engine provided - slot call state won't persist")
            return
            
        try:
            with self.engine.begin() as conn:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS feature_settings (
                        feature_name TEXT PRIMARY KEY,
                        enabled BOOLEAN NOT NULL DEFAULT TRUE,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """))
            logger.info("feature_settings table initialized")
        except Exception as e:
            logger.error(f"Failed to initialize feature_settings table: {e}")
    
    def _load_enabled_state(self) -> bool:
        """Load enabled state from database, default to True if not found"""
        if not self.engine:
            return True  # Default to enabled if no database
            
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text("""
                    SELECT enabled FROM feature_settings 
                    WHERE feature_name = 'slot_calls'
                """)).fetchone()
                
                if result:
                    enabled = result[0]
                    logger.info(f"Loaded slot call state from database: {'enabled' if enabled else 'disabled'}")
                    return enabled
                else:
                    # First time - set default to enabled
                    with self.engine.begin() as conn:
                        conn.execute(text("""
                            INSERT INTO feature_settings (feature_name, enabled)
                            VALUES ('slot_calls', TRUE)
                        """))
                    logger.info("Initialized slot call state in database: enabled")
                    return True
        except Exception as e:
            logger.error(f"Failed to load slot call state from database: {e}")
            return True  # Default to enabled on error
        
    def is_enabled(self) -> bool:
        """Check if slot call tracking is enabled"""
        return self.enabled
    
    def set_enabled(self, enabled: bool):
        """Enable or disable slot call tracking and persist to database"""
        self.enabled = enabled
        logger.info(f"Slot call tracking {'enabled' if enabled else 'disabled'}")
        
        # Persist to database
        if self.engine:
            try:
                with self.engine.begin() as conn:
                    conn.execute(text("""
                        INSERT INTO feature_settings (feature_name, enabled, updated_at)
                        VALUES ('slot_calls', :enabled, CURRENT_TIMESTAMP)
                        ON CONFLICT (feature_name) 
                        DO UPDATE SET enabled = :enabled, updated_at = CURRENT_TIMESTAMP
                    """), {"enabled": enabled})
                logger.info(f"Persisted slot call state to database")
            except Exception as e:
                logger.error(f"Failed to persist slot call state to database: {e}")
    
    async def handle_slot_call(self, kick_username: str, slot_call: str):
        """
        Handle a slot call from Kick chat
        
        Args:
            kick_username: Username from Kick chat
            slot_call: The slot call text (everything after !call)
        """
        if not self.enabled:
            # Send "slot requests not open" message to Kick chat
            if self.kick_send_callback:
                try:
                    await self.kick_send_callback(f"@{kick_username} Slot requests are not open at the moment.")
                    logger.info(f"Sent 'slot requests not open' message to {kick_username}")
                except Exception as e:
                    logger.error(f"Failed to send disabled message to Kick: {e}")
            return
        
        if not self.discord_channel_id:
            logger.warning("Slot call received but no Discord channel configured")
            return
        
        # 🔒 SECURITY: Rate limiting - prevent spam
        now = datetime.utcnow()
        username_lower = kick_username.lower()
        
        if username_lower in self.last_call_time:
            time_since_last = (now - self.last_call_time[username_lower]).total_seconds()
            if time_since_last < self.cooldown_seconds:
                logger.debug(f"Rate limit: {kick_username} must wait {self.cooldown_seconds - time_since_last:.1f}s")
                return  # Silently ignore - don't spam the user
        
        # Update last call time
        self.last_call_time[username_lower] = now
        
        # 🔒 SECURITY: Input validation - prevent excessively long inputs
        kick_username_safe = kick_username[:self.max_username_length]
        slot_call_safe = slot_call[:self.max_slot_call_length]
        
        # Get the Discord channel
        channel = self.bot.get_channel(self.discord_channel_id)
        if not channel:
            logger.error(f"Could not find Discord channel {self.discord_channel_id}")
            return
        
        # Create embed for the slot call
        embed = discord.Embed(
            title="🎰 Slot Call",
            description=f"**{kick_username_safe}** requested **{slot_call_safe}**",
            color=discord.Color.gold(),
            timestamp=datetime.utcnow()
        )
        embed.set_footer(text=f"From Kick chat • {kick_username_safe}")
        
        try:
            await channel.send(embed=embed)
            logger.info(f"Posted slot call from {kick_username_safe}: {slot_call_safe}")
            
            # Send confirmation message to Kick chat if callback is available
            if self.kick_send_callback:
                kick_response = f"@{kick_username_safe} Your slot request for {slot_call_safe} has been received! ✅"
                try:
                    await self.kick_send_callback(kick_response)
                    logger.info(f"Sent Kick chat response to {kick_username_safe}")
                except Exception as kick_error:
                    logger.error(f"Failed to send Kick chat response: {kick_error}")
                    
        except Exception as e:
            logger.error(f"Failed to post slot call to Discord: {e}")


class SlotCallCommands(commands.Cog):
    """Discord commands for managing slot call tracking"""
    
    def __init__(self, bot, tracker: SlotCallTracker):
        self.bot = bot
        self.tracker = tracker
    
    @commands.command(name='slotcalls')
    @commands.has_permissions(administrator=True)
    async def toggle_slot_calls(self, ctx, action: str = None):
        """
        [ADMIN] Toggle slot call tracking on/off or check status
        Usage: !slotcalls [on|off|status]
        """
        if action is None or action.lower() == "status":
            status = "✅ **enabled**" if self.tracker.is_enabled() else "❌ **disabled**"
            channel_id = self.tracker.discord_channel_id
            channel_mention = f"<#{channel_id}>" if channel_id else "Not configured"
            
            embed = discord.Embed(
                title="🎰 Slot Call Tracker Status",
                color=discord.Color.green() if self.tracker.is_enabled() else discord.Color.red()
            )
            embed.add_field(name="Status", value=status, inline=True)
            embed.add_field(name="Channel", value=channel_mention, inline=True)
            embed.add_field(
                name="🔒 Security",
                value=f"• Rate limit: {self.tracker.cooldown_seconds}s cooldown per user\n"
                      f"• Max username: {self.tracker.max_username_length} chars\n"
                      f"• Max slot call: {self.tracker.max_slot_call_length} chars",
                inline=False
            )
            embed.add_field(
                name="How it works",
                value="When users type `!call <slot>` or `!sr <slot>` in Kick chat, it posts to the configured Discord channel.",
                inline=False
            )
            
            await ctx.send(embed=embed)
            return
        
        if action.lower() == "on":
            self.tracker.set_enabled(True)
            await ctx.send("✅ Slot call tracking **enabled**! Users can now use `!call <slot>` or `!sr <slot>` in Kick chat.")
        elif action.lower() == "off":
            self.tracker.set_enabled(False)
            await ctx.send("❌ Slot call tracking **disabled**. `!call` and `!sr` commands will be ignored.")
        else:
            await ctx.send("❌ Invalid action. Use `!slotcalls on`, `!slotcalls off`, or `!slotcalls status`")
    
    @toggle_slot_calls.error
    async def toggle_slot_calls_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("❌ You need administrator permission to use this command.")


async def setup_slot_call_tracker(bot, discord_channel_id: Optional[int] = None, kick_send_callback=None, engine=None):
    """
    Setup slot call tracker
    
    Args:
        bot: Discord bot instance
        discord_channel_id: Discord channel ID to post slot calls to
        kick_send_callback: Optional callback function to send messages to Kick chat
        engine: SQLAlchemy engine for persisting state
    
    Returns:
        SlotCallTracker instance
    """
    tracker = SlotCallTracker(bot, discord_channel_id, kick_send_callback, engine)
    
    # Add commands
    await bot.add_cog(SlotCallCommands(bot, tracker))
    
    logger.info(f"✅ Slot call tracker initialized (channel: {discord_channel_id or 'Not set'})")
    
    return tracker

