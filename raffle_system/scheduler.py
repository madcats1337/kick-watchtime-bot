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
        Also checks if it's time to draw winner (10 minutes before end)
        
        Returns:
            dict: Transition info or None if no transition needed
        """
        try:
            current_period = get_current_period(self.engine)
            
            if not current_period:
                logger.warning("No active raffle period found - creating monthly period!")
                # Auto-create monthly period starting on 1st of current month
                return self._create_monthly_period()
            
            now = datetime.now()
            end_date = current_period['end_date']
            start_date = current_period['start_date']
            
            # Ensure dates are datetime objects
            if isinstance(end_date, str):
                end_date = datetime.fromisoformat(end_date)
            if isinstance(start_date, str):
                start_date = datetime.fromisoformat(start_date)
            
            # ONE-TIME CLEANUP: Delete tickets that shouldn't exist yet
            # This handles tickets created before the period officially started
            if now < start_date + timedelta(hours=1):  # Within first hour of period
                from sqlalchemy import text
                with self.engine.begin() as conn:
                    # Check if there are any tickets
                    result = conn.execute(text("SELECT COUNT(*) FROM raffle_tickets WHERE period_id = :period_id"), 
                                         {'period_id': current_period['id']})
                    ticket_count = result.scalar()
                    
                    if ticket_count > 0:
                        logger.warning(f"⚠️ Found {ticket_count} tickets at period start - clearing...")
                        # Delete all tickets for this period
                        deleted_tickets = conn.execute(text("DELETE FROM raffle_tickets WHERE period_id = :period_id"), 
                                                      {'period_id': current_period['id']}).rowcount
                        deleted_watchtime = conn.execute(text("DELETE FROM raffle_watchtime_converted")).rowcount
                        deleted_subs = conn.execute(text("DELETE FROM raffle_gifted_subs")).rowcount
                        deleted_wagers = conn.execute(text("DELETE FROM raffle_shuffle_wagers")).rowcount
                        
                        logger.info(f"✅ Period start cleanup: Deleted {deleted_tickets} tickets, {deleted_watchtime} watchtime, {deleted_subs} subs, {deleted_wagers} wagers")
                        
                        # Update leaderboard immediately
                        if hasattr(self.bot, 'auto_leaderboard') and self.bot.auto_leaderboard:
                            await self.bot.auto_leaderboard.update_leaderboard()
                            logger.info("📊 Updated leaderboard after cleanup")
            
            # Check if it's 10 minutes before period ends and winner not drawn yet
            time_until_end = (end_date - now).total_seconds()
            if 0 < time_until_end <= 600 and not current_period.get('winner_discord_id'):  # 600 seconds = 10 minutes
                logger.info(f"⏰ 10 minutes until period end - drawing winner now!")
                self._draw_winner_for_period(current_period)
            
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
    
    def _create_monthly_period(self):
        """Create a new monthly raffle period starting on 1st of current month"""
        try:
            now = datetime.now()
            
            # Start on 1st of current month at midnight
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            
            # End on last day of month at 23:59:59
            # Get first day of next month, then subtract 1 second
            if start.month == 12:
                next_month = start.replace(year=start.year + 1, month=1)
            else:
                next_month = start.replace(month=start.month + 1)
            
            end = next_month - timedelta(seconds=1)
            
            period_id = create_new_period(self.engine, start, end)
            logger.info(f"✅ Auto-created monthly period #{period_id} ({start.strftime('%b %d')} - {end.strftime('%b %d, %Y')})")
            
            return {
                'old_period_id': None,
                'old_period_start': None,
                'old_period_end': None,
                'winner_drawn': False,
                'winner_info': None,
                'new_period_id': period_id,
                'transition_time': now
            }
        except Exception as e:
            logger.error(f"Failed to create monthly period: {e}")
            return None
    
    def _draw_winner_for_period(self, period):
        """Draw winner for the given period"""
        try:
            winner = self.raffle_draw.draw_winner(
                period_id=period['id'],
                prize_description="Monthly Raffle Prize",
                drawn_by_discord_id=None  # Automatic draw
            )
            
            if winner:
                logger.info(f"🎉 Winner drawn for period #{period['id']}: {winner['winner_kick_name']}")
                return winner
            else:
                logger.warning(f"No participants to draw from for period #{period['id']}")
                return None
        except Exception as e:
            logger.error(f"Failed to draw winner: {e}")
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
            
            # Step 3: Create new monthly period
            # New period starts on 1st of next month
            old_end = old_period['end_date']
            if isinstance(old_end, str):
                old_end = datetime.fromisoformat(old_end)
            
            # Calculate next month
            if old_end.month == 12:
                start = old_end.replace(year=old_end.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            else:
                start = old_end.replace(month=old_end.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
            
            # End on last day of that month at 23:59:59
            if start.month == 12:
                next_month = start.replace(year=start.year + 1, month=1)
            else:
                next_month = start.replace(month=start.month + 1)
            
            end = next_month - timedelta(seconds=1)
            
            new_period_id = create_new_period(self.engine, start, end)
            transition_info['new_period_id'] = new_period_id
            
            logger.info(f"✅ New monthly period #{new_period_id} created ({start.strftime('%b %d')} - {end.strftime('%b %d, %Y')})")
            logger.info("� Next period will auto-start on 1st of next month")
            
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
    
    @tasks.loop(minutes=1)  # Check every minute
    async def check_raffle_period():
        """Check every minute for: winner drawing (10 min before end) and period transitions (midnight on 1st)"""
        try:
            now = datetime.now()
            
            # Always check for winner drawing and period transitions
            transition = scheduler.check_period_transition()
            
            # If midnight on 1st of month, handle period transition
            if now.hour == 0 and now.minute == 0 and now.day == 1:
                logger.info("🕛 It's midnight on the 1st - monthly raffle transition time!")
                
                if transition:
                    logger.info(f"📊 Period transition completed (tickets automatically reset):")
                    if transition['old_period_id']:
                        logger.info(f"   Old period: #{transition['old_period_id']}")
                    logger.info(f"   New period: #{transition['new_period_id']}")
                    
                    # Announce winner if drawn
                    if transition['winner_drawn'] and transition['winner_info']:
                        await scheduler.announce_winner(transition['winner_info'])
                    
                    # Announce new period (tickets already reset by create_new_period)
                    if transition['new_period_id']:
                        # Get new period details
                        new_period = get_current_period(engine)
                        if new_period:
                            await scheduler.announce_new_period(
                                new_period['id'],
                                new_period['start_date'],
                                new_period['end_date']
                            )
                    
                    # Update the leaderboard immediately after period transition
                    if hasattr(bot, 'auto_leaderboard') and bot.auto_leaderboard:
                        logger.info("🔄 Updating leaderboard after period transition...")
                        await bot.auto_leaderboard.update_leaderboard()
                
        except Exception as e:
            logger.error(f"Error in raffle period check task: {e}")
            import traceback
            traceback.print_exc()
    
    # Start the task
    check_raffle_period.start()
    logger.info("✅ Raffle scheduler task started (checks every minute for midnight period transition)")
    
    return scheduler
