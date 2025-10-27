"""
Raffle Period Scheduler
Handles automatic monthly period resets and optional auto-draw
"""

import logging
from datetime import datetime, timedelta
from discord.ext import tasks
from sqlalchemy import text
from .database import create_new_period, get_current_period
from .draw import RaffleDraw

logger = logging.getLogger(__name__)


class RaffleScheduler:
    """Manages automatic raffle period transitions"""
    
    def __init__(self, engine, bot=None, auto_draw=False, announcement_channel_id=None):
        """
        Initialize raffle scheduler
        
        Args:
            engine: SQLAlchemy database engine
            bot: Discord bot instance (for announcements)
            auto_draw: Whether to automatically draw winner at period end
            announcement_channel_id: Discord channel ID for winner announcements
        """
        self.engine = engine
        self.bot = bot
        self.auto_draw = auto_draw
        self.announcement_channel_id = announcement_channel_id
        self.raffle_draw = RaffleDraw(engine)
        
        logger.info(f"📅 Raffle scheduler initialized (auto_draw: {auto_draw})")
    
    def check_period_transition(self):
        """
        Check if we need to transition to a new raffle period
        Should be called daily (typically at midnight)
        
        Returns:
            dict: Transition info or None if no transition needed
        """
        try:
            current_period = get_current_period(self.engine)
            
            if not current_period:
                logger.warning("No active raffle period found!")
                return None
            
            now = datetime.now()
            end_date = current_period['end_date']
            
            # Ensure end_date is a datetime object
            if isinstance(end_date, str):
                end_date = datetime.fromisoformat(end_date)
            
            # Check if current period has ended
            if now > end_date:
                logger.info(f"🔔 Raffle period #{current_period['id']} has ended!")
                return self._transition_to_new_period(current_period)
            else:
                # Period still active
                days_remaining = (end_date - now).days
                logger.debug(f"Current period #{current_period['id']} active ({days_remaining} days remaining)")
                return None
                
        except Exception as e:
            logger.error(f"Failed to check period transition: {e}")
            return None
    
    def _transition_to_new_period(self, old_period):
        """
        Transition from old period to new period
        
        Args:
            old_period: Current period that's ending
            
        Returns:
            dict: Transition details
        """
        try:
            transition_info = {
                'old_period_id': old_period['id'],
                'old_period_start': old_period['start_date'],
                'old_period_end': old_period['end_date'],
                'winner_drawn': False,
                'winner_info': None,
                'new_period_id': None,
                'transition_time': datetime.now()
            }
            
            # Step 1: Draw winner if auto-draw enabled and not already drawn
            if self.auto_draw and not old_period.get('winner_discord_id'):
                logger.info(f"🎲 Auto-drawing winner for period #{old_period['id']}...")
                
                winner = self.raffle_draw.draw_winner(
                    period_id=old_period['id'],
                    prize_description="Monthly Raffle Prize",
                    drawn_by_discord_id=None  # Automatic draw
                )
                
                if winner:
                    transition_info['winner_drawn'] = True
                    transition_info['winner_info'] = winner
                    logger.info(f"🎉 Winner drawn: {winner['winner_kick_name']}")
                else:
                    logger.warning("No participants to draw from")
            
            # Step 2: Close the old period
            with self.engine.begin() as conn:
                conn.execute(text("""
                    UPDATE raffle_periods
                    SET status = 'ended'
                    WHERE id = :period_id
                """), {'period_id': old_period['id']})
            
            logger.info(f"✅ Period #{old_period['id']} closed")
            
            # Step 3: Create new period for next month
            now = datetime.now()
            
            # Start on 1st of next month
            if now.month == 12:
                start = datetime(now.year + 1, 1, 1, 0, 0, 0, 0)
            else:
                start = datetime(now.year, now.month + 1, 1, 0, 0, 0, 0)
            
            # End on last day of that month
            if start.month == 12:
                end = datetime(start.year + 1, 1, 1, 0, 0, 0, 0) - timedelta(seconds=1)
            else:
                end = datetime(start.year, start.month + 1, 1, 0, 0, 0, 0) - timedelta(seconds=1)
            
            new_period_id = create_new_period(self.engine, start, end)
            transition_info['new_period_id'] = new_period_id
            
            logger.info(f"✅ New period #{new_period_id} created ({start.strftime('%b %d')} - {end.strftime('%b %d, %Y')})")
            
            return transition_info
            
        except Exception as e:
            logger.error(f"Failed to transition periods: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    async def announce_winner(self, winner_info):
        """
        Announce raffle winner to Discord channel
        
        Args:
            winner_info: Winner details from draw_winner()
        """
        if not self.bot or not self.announcement_channel_id:
            logger.warning("Cannot announce winner: bot or channel not configured")
            return
        
        try:
            channel = self.bot.get_channel(self.announcement_channel_id)
            if not channel:
                logger.error(f"Announcement channel {self.announcement_channel_id} not found")
                return
            
            # Try to mention winner if possible
            try:
                discord_user = await self.bot.fetch_user(winner_info['winner_discord_id'])
                mention = discord_user.mention
            except:
                mention = winner_info['winner_kick_name']
            
            message = f"""
🎉 **MONTHLY RAFFLE WINNER!** 🎉

Congratulations {mention}!

**Winner**: {winner_info['winner_kick_name']}
**Tickets**: {winner_info['winner_tickets']:,} out of {winner_info['total_tickets']:,}
**Win Probability**: {winner_info['win_probability']:.2f}%

Please contact an admin to claim your prize! 🎊
            """
            
            await channel.send(message.strip())
            logger.info(f"📢 Winner announcement sent to channel {self.announcement_channel_id}")
            
        except Exception as e:
            logger.error(f"Failed to announce winner: {e}")
    
    async def announce_new_period(self, new_period_id, start_date, end_date):
        """
        Announce new raffle period to Discord channel
        
        Args:
            new_period_id: New period ID
            start_date: Period start date
            end_date: Period end date
        """
        if not self.bot or not self.announcement_channel_id:
            return
        
        try:
            channel = self.bot.get_channel(self.announcement_channel_id)
            if not channel:
                return
            
            message = f"""
🎰 **NEW RAFFLE PERIOD STARTED!** 🎰

**Period**: #{new_period_id}
**Duration**: {start_date.strftime('%B %d')} - {end_date.strftime('%B %d, %Y')}

**How to Earn Tickets**:
• Watch streams: 10 tickets per hour
• Gift subs: 15 tickets per sub
• Wager on Shuffle.com (code 'lele'): 20 tickets per $1000

Use `!tickets` to check your balance!
Good luck! 🍀
            """
            
            await channel.send(message.strip())
            logger.info(f"📢 New period announcement sent to channel {self.announcement_channel_id}")
            
        except Exception as e:
            logger.error(f"Failed to announce new period: {e}")


async def setup_raffle_scheduler(bot, engine, auto_draw=False, announcement_channel_id=None):
    """
    Setup automatic raffle period management as a Discord bot task
    
    Args:
        bot: Discord bot instance
        engine: SQLAlchemy database engine
        auto_draw: Whether to auto-draw winners at period end
        announcement_channel_id: Channel ID for announcements
        
    Returns:
        RaffleScheduler instance
    """
    scheduler = RaffleScheduler(
        engine=engine,
        bot=bot,
        auto_draw=auto_draw,
        announcement_channel_id=announcement_channel_id
    )
    
    @tasks.loop(hours=24)  # Check daily at midnight
    async def check_raffle_period():
        """Daily task to check if raffle period needs to transition"""
        try:
            logger.debug("🔍 Checking raffle period status...")
            
            transition = scheduler.check_period_transition()
            
            if transition:
                logger.info(f"📊 Period transition completed:")
                logger.info(f"   Old period: #{transition['old_period_id']}")
                logger.info(f"   New period: #{transition['new_period_id']}")
                
                # Announce winner if drawn
                if transition['winner_drawn'] and transition['winner_info']:
                    await scheduler.announce_winner(transition['winner_info'])
                
                # Announce new period
                if transition['new_period_id']:
                    # Get new period details
                    new_period = get_current_period(engine)
                    if new_period:
                        await scheduler.announce_new_period(
                            new_period['id'],
                            new_period['start_date'],
                            new_period['end_date']
                        )
                
        except Exception as e:
            logger.error(f"Error in raffle period check task: {e}")
            import traceback
            traceback.print_exc()
    
    # Start the task
    check_raffle_period.start()
    logger.info("✅ Raffle scheduler task started (checks every 24 hours)")
    
    return scheduler
