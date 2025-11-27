"""
Auto-Updating Raffle Leaderboard
Posts and updates a raffle ticket leaderboard in a specified channel
"""

import logging
import discord
from discord.ext import tasks
from sqlalchemy import text
from datetime import datetime
import os

from .config import AUTO_LEADERBOARD_UPDATE_INTERVAL

logger = logging.getLogger(__name__)


class AutoLeaderboard:
    """Manages auto-updating raffle leaderboard"""
    
    def __init__(self, bot, engine, channel_id):
        self.bot = bot
        self.engine = engine
        self.channel_id = channel_id
        self.message_id = None
        self.channel = None
    
    async def initialize(self):
        """Initialize the leaderboard system"""
        try:
            self.channel = self.bot.get_channel(self.channel_id)
            
            if not self.channel:
                print(f"[Auto-Leaderboard] ❌ Could not find channel with ID {self.channel_id}")
                return False
            
            print(f"[Auto-Leaderboard] Found channel: #{self.channel.name}")
            
            # Try to find existing leaderboard message
            async for message in self.channel.history(limit=50):
                if message.author == self.bot.user and message.embeds:
                    embed = message.embeds[0]
                    if embed.title and "🎟️ Raffle Ticket Leaderboard" in embed.title:
                        self.message_id = message.id
                        print(f"[Auto-Leaderboard] Found existing message: {self.message_id}")
                        break
            
            if not self.message_id:
                # Post initial leaderboard
                print("[Auto-Leaderboard] No existing message found, posting new leaderboard...")
                await self.post_new_leaderboard()
            
            return True
            
        except Exception as e:
            print(f"[Auto-Leaderboard] ❌ Failed to initialize: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def post_new_leaderboard(self):
        """Post a new leaderboard message"""
        try:
            embed = await self.create_leaderboard_embed()
            message = await self.channel.send(embed=embed)
            self.message_id = message.id
            print(f"[Auto-Leaderboard] Posted new message: {self.message_id}")
            
        except Exception as e:
            print(f"[Auto-Leaderboard] ❌ Failed to post: {e}")
            import traceback
            traceback.print_exc()
    
    async def update_leaderboard(self):
        """Update the existing leaderboard message"""
        try:
            if not self.message_id:
                print("[Auto-Leaderboard] No message ID, posting new leaderboard...")
                await self.post_new_leaderboard()
                return
            
            # Fetch the message
            try:
                message = await self.channel.fetch_message(self.message_id)
            except discord.NotFound:
                print("[Auto-Leaderboard] Message not found, posting new one...")
                await self.post_new_leaderboard()
                return
            
            # Create updated embed
            embed = await self.create_leaderboard_embed()
            
            # Edit the message
            await message.edit(embed=embed)
            print(f"[Auto-Leaderboard] ✅ Updated message: {self.message_id}")
            
        except Exception as e:
            print(f"[Auto-Leaderboard] ❌ Failed to update: {e}")
            import traceback
            traceback.print_exc()
    
    async def create_leaderboard_embed(self):
        """Create the leaderboard embed"""
        try:
            with self.engine.begin() as conn:
                # Get active period
                period_result = conn.execute(text("""
                    SELECT id, start_date, end_date 
                    FROM raffle_periods 
                    WHERE status = 'active'
                """))
                
                period_row = period_result.fetchone()
                
                if not period_row:
                    return discord.Embed(
                        title="🎟️ Raffle Ticket Leaderboard",
                        description="No active raffle period",
                        color=discord.Color.red()
                    )
                
                period_id = period_row[0]
                start_date = period_row[1]
                end_date = period_row[2]
                
                # Check if period hasn't started yet
                now = datetime.now()
                if now < start_date:
                    days_until_start = (start_date - now).days
                    hours_until_start = ((start_date - now).seconds // 3600)
                    
                    time_msg = f"{days_until_start} days" if days_until_start > 0 else f"{hours_until_start} hours"
                    
                    return discord.Embed(
                        title="🎟️ Raffle Ticket Leaderboard",
                        description=(
                            f"**Raffle Period Not Started Yet**\n\n"
                            f"📅 **Starts:** {start_date.strftime('%b %d, %Y at %I:%M %p')}\n"
                            f"📅 **Ends:** {end_date.strftime('%b %d, %Y at %I:%M %p')}\n\n"
                            f"⏳ **Time until start:** {time_msg}\n\n"
                            f"Get ready to earn tickets by watching streams, gifting subs, and wagering on Shuffle!"
                        ),
                        color=discord.Color.blue()
                    )
                
                # Get top 5 participants
                result = conn.execute(text("""
                    SELECT 
                        kick_name,
                        total_tickets,
                        watchtime_tickets,
                        gifted_sub_tickets,
                        shuffle_wager_tickets,
                        bonus_tickets
                    FROM raffle_tickets
                    WHERE period_id = :period_id
                    ORDER BY total_tickets DESC
                    LIMIT 5
                """), {'period_id': period_id})
                
                rows = result.fetchall()
                
                # Get total stats
                stats_result = conn.execute(text("""
                    SELECT 
                        COUNT(DISTINCT discord_id),
                        COALESCE(SUM(total_tickets), 0)
                    FROM raffle_tickets
                    WHERE period_id = :period_id
                """), {'period_id': period_id})
                
                stats_row = stats_result.fetchone()
                total_participants = stats_row[0] or 0
                total_tickets = stats_row[1] or 0
            
            # Create embed
            embed = discord.Embed(
                title="🎟️ Raffle Ticket Leaderboard",
                description=f"**Period:** {start_date.strftime('%b %d')} - {end_date.strftime('%b %d, %Y')}\n"
                           f"**Participants:** {total_participants:,} | **Total Tickets:** {total_tickets:,}",
                color=discord.Color.gold(),
                timestamp=datetime.utcnow()
            )
            
            if not rows:
                embed.add_field(
                    name="No Participants Yet",
                    value="Be the first to earn tickets!",
                    inline=False
                )
            else:
                # Medals for top 3
                medals = ["🥇", "🥈", "🥉"]
                
                leaderboard_text = ""
                for idx, row in enumerate(rows, 1):
                    kick_name = row[0] or "Unknown"
                    total = row[1]
                    watchtime = row[2]
                    gifted = row[3]
                    shuffle = row[4]
                    bonus = row[5]
                    
                    # Medal or rank number
                    rank = medals[idx-1] if idx <= 3 else f"`{idx}.`"
                    
                    # Calculate win probability
                    win_prob = (total / total_tickets * 100) if total_tickets > 0 else 0
                    
                    leaderboard_text += f"{rank} **{kick_name}** - {total:,} tickets ({win_prob:.2f}%)\n"
                    leaderboard_text += f"    ⏱️ {watchtime} 🎁 {gifted} 🎲 {shuffle} ⭐ {bonus}\n"
                
                embed.add_field(
                    name="🏆 Top 5",
                    value=leaderboard_text,
                    inline=False
                )
            
            # Add how to earn tickets section
            embed.add_field(
                name="📋 How to Earn Tickets",
                value=(
                    "⏱️ **Watch Streams** - 10 tickets per hour\n"
                    "🎁 **Gift Subs** - 15 tickets per sub\n"
                    "🎲 **Shuffle Wagers** - 20 tickets per $1000 wagered\n"
                    "⭐ **Bonus** - Admin awarded for events\n\n"
                    "Use `!tickets` to check your balance!"
                ),
                inline=False
            )
            
            # Dynamic footer based on update interval
            if AUTO_LEADERBOARD_UPDATE_INTERVAL >= 3600:
                update_text = f"Updates every {AUTO_LEADERBOARD_UPDATE_INTERVAL/3600:.1f} hours"
            elif AUTO_LEADERBOARD_UPDATE_INTERVAL >= 60:
                update_text = f"Updates every {AUTO_LEADERBOARD_UPDATE_INTERVAL/60:.0f} minutes"
            else:
                update_text = f"Updates every {AUTO_LEADERBOARD_UPDATE_INTERVAL} seconds"
            
            embed.set_footer(text=update_text)
            
            return embed
            
        except Exception as e:
            print(f"[Auto-Leaderboard] ❌ Failed to create embed: {e}")
            import traceback
            traceback.print_exc()
            return discord.Embed(
                title="🎟️ Raffle Ticket Leaderboard",
                description="Error loading leaderboard data",
                color=discord.Color.red()
            )


async def setup_auto_leaderboard(bot, engine, channel_id=None):
    """
    Setup the auto-updating leaderboard as a Discord bot task
    
    Args:
        bot: Discord bot instance
        engine: SQLAlchemy engine
        channel_id: Discord channel ID for leaderboard (optional, falls back to env var)
    """
    # Get channel ID from parameter, bot_settings, or environment variable
    if channel_id is None:
        # Try to get from bot_settings if available
        if hasattr(bot, 'settings_manager') and bot.settings_manager:
            channel_id = bot.settings_manager.raffle_leaderboard_channel_id
        
        # Fall back to environment variable
        if channel_id is None:
            channel_id_str = os.getenv('RAFFLE_LEADERBOARD_CHANNEL_ID')
            if channel_id_str:
                try:
                    channel_id = int(channel_id_str)
                except ValueError:
                    print(f"[Auto-Leaderboard] ❌ Invalid RAFFLE_LEADERBOARD_CHANNEL_ID: {channel_id_str}")
                    return None
    
    if not channel_id:
        print("[Auto-Leaderboard] ⚠️ Channel ID not set - auto-leaderboard disabled")
        return None
    
    print(f"[Auto-Leaderboard] Setting up for channel ID: {channel_id}")
    
    leaderboard = AutoLeaderboard(bot, engine, channel_id)
    
    @tasks.loop(seconds=AUTO_LEADERBOARD_UPDATE_INTERVAL)
    async def update_leaderboard_task():
        """Periodic task to update the leaderboard"""
        print("🔄 [Auto-Leaderboard] Updating...")
        await leaderboard.update_leaderboard()
    
    @update_leaderboard_task.before_loop
    async def before_leaderboard_task():
        """Wait for bot to be ready and initialize"""
        await bot.wait_until_ready()
        
        print(f"[Auto-Leaderboard] Initializing for channel {channel_id}...")
        
        # Initialize the leaderboard
        success = await leaderboard.initialize()
        
        if success:
            if AUTO_LEADERBOARD_UPDATE_INTERVAL >= 3600:
                print(f"✅ [Auto-Leaderboard] Started (updates every {AUTO_LEADERBOARD_UPDATE_INTERVAL/3600:.1f} hours)")
            elif AUTO_LEADERBOARD_UPDATE_INTERVAL >= 60:
                print(f"✅ [Auto-Leaderboard] Started (updates every {AUTO_LEADERBOARD_UPDATE_INTERVAL/60:.0f} minutes)")
            else:
                print(f"✅ [Auto-Leaderboard] Started (updates every {AUTO_LEADERBOARD_UPDATE_INTERVAL} seconds)")
        else:
            print("❌ [Auto-Leaderboard] Failed to initialize - task cancelled")
            update_leaderboard_task.cancel()
    
    # Start the task
    update_leaderboard_task.start()
    
    return leaderboard
