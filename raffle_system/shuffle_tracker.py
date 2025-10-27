"""
Shuffle.com Wager Tracker
Polls Shuffle affiliate API and awards raffle tickets based on wager amounts
"""

from sqlalchemy import text
from datetime import datetime
import logging
import aiohttp
import asyncio

from .config import SHUFFLE_TICKETS_PER_1000_USD, SHUFFLE_AFFILIATE_URL, SHUFFLE_CAMPAIGN_CODE
from .tickets import TicketManager

logger = logging.getLogger(__name__)


class ShuffleWagerTracker:
    """Tracks Shuffle.com wagers and awards raffle tickets"""
    
    def __init__(self, engine):
        self.engine = engine
        self.ticket_manager = TicketManager(engine)
    
    async def update_shuffle_wagers(self):
        """
        Poll Shuffle affiliate API and update wager tracking
        
        Fetches the latest wager data from Shuffle.com affiliate page,
        compares with previous values, and awards tickets for new wagers.
        
        Returns:
            dict: Summary of updates performed
        """
        try:
            # Get active raffle period
            period_id = self._get_active_period_id()
            if not period_id:
                logger.warning("No active raffle period - skipping Shuffle wager update")
                return {'status': 'no_active_period', 'updates': 0}
            
            # Fetch current wager data from Shuffle
            wager_data = await self._fetch_shuffle_data()
            
            if not wager_data:
                logger.error("Failed to fetch Shuffle affiliate data")
                return {'status': 'fetch_failed', 'updates': 0}
            
            # Filter for campaign code "lele"
            filtered_data = [
                user for user in wager_data 
                if user.get('campaignCode', '').lower() == SHUFFLE_CAMPAIGN_CODE.lower()
            ]
            
            if not filtered_data:
                logger.warning(f"No users found with campaign code '{SHUFFLE_CAMPAIGN_CODE}'")
                return {'status': 'no_users', 'updates': 0}
            
            logger.info(f"Found {len(filtered_data)} users with campaign code '{SHUFFLE_CAMPAIGN_CODE}'")
            
            updates = []
            
            with self.engine.begin() as conn:
                for user_data in filtered_data:
                    shuffle_username = user_data.get('username')
                    current_wager = float(user_data.get('wagerAmount', 0))
                    
                    if not shuffle_username:
                        continue
                    
                    # Get previous wager amount for this period
                    prev_result = conn.execute(text("""
                        SELECT 
                            last_known_wager,
                            tickets_awarded,
                            discord_id,
                            kick_name
                        FROM raffle_shuffle_wagers
                        WHERE period_id = :period_id AND shuffle_username = :username
                    """), {
                        'period_id': period_id,
                        'username': shuffle_username
                    })
                    
                    prev_row = prev_result.fetchone()
                    
                    if prev_row:
                        # Existing user - check for wager increase
                        last_known_wager = float(prev_row[0])
                        total_tickets_awarded = prev_row[1]
                        discord_id = prev_row[2]
                        kick_name = prev_row[3]
                        
                        # Calculate new wager since last check
                        wager_delta = current_wager - last_known_wager
                        
                        if wager_delta <= 0:
                            # No increase (or decrease, which we ignore)
                            continue
                        
                        # Calculate tickets for the new wager amount
                        # $1000 = SHUFFLE_TICKETS_PER_1000_USD tickets
                        new_tickets = int((wager_delta / 1000.0) * SHUFFLE_TICKETS_PER_1000_USD)
                        
                        if new_tickets == 0:
                            # Less than threshold, update wager but no tickets
                            conn.execute(text("""
                                UPDATE raffle_shuffle_wagers
                                SET 
                                    last_known_wager = :current_wager,
                                    last_checked = CURRENT_TIMESTAMP
                                WHERE period_id = :period_id AND shuffle_username = :username
                            """), {
                                'period_id': period_id,
                                'username': shuffle_username,
                                'current_wager': current_wager
                            })
                            continue
                        
                        # Award tickets if user is linked
                        if discord_id and kick_name:
                            success = self.ticket_manager.award_tickets(
                                discord_id=discord_id,
                                kick_name=kick_name,
                                tickets=new_tickets,
                                source='shuffle_wager',
                                description=f"Shuffle wager: ${wager_delta:.2f} (${last_known_wager:.2f} → ${current_wager:.2f})",
                                period_id=period_id
                            )
                            
                            if success:
                                # Update wager tracking
                                conn.execute(text("""
                                    UPDATE raffle_shuffle_wagers
                                    SET 
                                        last_known_wager = :current_wager,
                                        total_wager_usd = :current_wager,
                                        tickets_awarded = tickets_awarded + :new_tickets,
                                        last_checked = CURRENT_TIMESTAMP,
                                        last_updated = CURRENT_TIMESTAMP
                                    WHERE period_id = :period_id AND shuffle_username = :username
                                """), {
                                    'period_id': period_id,
                                    'username': shuffle_username,
                                    'current_wager': current_wager,
                                    'new_tickets': new_tickets
                                })
                                
                                updates.append({
                                    'shuffle_username': shuffle_username,
                                    'kick_name': kick_name,
                                    'wager_delta': wager_delta,
                                    'tickets_awarded': new_tickets,
                                    'total_wager': current_wager
                                })
                                
                                logger.info(f"💰 {kick_name} ({shuffle_username}): ${wager_delta:.2f} wagered → {new_tickets} tickets")
                        else:
                            # User exists but not linked - just update wager
                            conn.execute(text("""
                                UPDATE raffle_shuffle_wagers
                                SET 
                                    last_known_wager = :current_wager,
                                    total_wager_usd = :current_wager,
                                    last_checked = CURRENT_TIMESTAMP
                                WHERE period_id = :period_id AND shuffle_username = :username
                            """), {
                                'period_id': period_id,
                                'username': shuffle_username,
                                'current_wager': current_wager
                            })
                    else:
                        # New user - check if they're linked
                        link_result = conn.execute(text("""
                            SELECT discord_id, kick_name FROM raffle_shuffle_links
                            WHERE shuffle_username = :username AND verified = TRUE
                        """), {'username': shuffle_username})
                        
                        link_row = link_result.fetchone()
                        discord_id = link_row[0] if link_row else None
                        kick_name = link_row[1] if link_row else None
                        
                        # Create wager tracking entry
                        # Set last_known_wager = total_wager so only FUTURE wagers earn tickets
                        conn.execute(text("""
                            INSERT INTO raffle_shuffle_wagers
                                (period_id, shuffle_username, kick_name, discord_id,
                                 total_wager_usd, last_known_wager, tickets_awarded)
                            VALUES
                                (:period_id, :username, :kick_name, :discord_id,
                                 :wager, :wager, 0)
                        """), {
                            'period_id': period_id,
                            'username': shuffle_username,
                            'kick_name': kick_name,
                            'discord_id': discord_id,
                            'wager': current_wager
                        })
                        
                        # No tickets awarded for initial/existing wagers
                        logger.info(f"📊 Tracking new Shuffle user: {shuffle_username} (${current_wager:.2f}) - "
                                  f"{'Linked to ' + kick_name if kick_name else 'Not linked'}")
            
            return {
                'status': 'success',
                'updates': len(updates),
                'details': updates
            }
            
        except Exception as e:
            logger.error(f"Failed to update Shuffle wagers: {e}")
            import traceback
            traceback.print_exc()
            return {'status': 'error', 'error': str(e), 'updates': 0}
    
    async def _fetch_shuffle_data(self):
        """
        Fetch wager data from Shuffle affiliate page
        
        Returns:
            list: Array of user wager objects or None on failure
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(SHUFFLE_AFFILIATE_URL, timeout=30) as response:
                    if response.status != 200:
                        logger.error(f"Shuffle API returned status {response.status}")
                        return None
                    
                    # The page returns JSON array directly
                    data = await response.json()
                    
                    if not isinstance(data, list):
                        logger.error(f"Unexpected Shuffle API response format: {type(data)}")
                        return None
                    
                    return data
                    
        except asyncio.TimeoutError:
            logger.error("Timeout fetching Shuffle affiliate data")
            return None
        except Exception as e:
            logger.error(f"Error fetching Shuffle data: {e}")
            return None
    
    def link_shuffle_account(self, shuffle_username, kick_name, discord_id, verified=False, verified_by=None):
        """
        Link a Shuffle username to a Kick/Discord account
        
        Args:
            shuffle_username: Shuffle.com username
            kick_name: Kick username
            discord_id: Discord user ID
            verified: Whether admin has verified this link
            verified_by: Discord ID of admin who verified
            
        Returns:
            dict: Result of linking operation
        """
        try:
            with self.engine.begin() as conn:
                # Check if shuffle username already linked
                existing = conn.execute(text("""
                    SELECT discord_id, kick_name FROM raffle_shuffle_links
                    WHERE shuffle_username = :username
                """), {'username': shuffle_username})
                
                existing_row = existing.fetchone()
                
                if existing_row:
                    return {
                        'status': 'already_linked',
                        'existing_discord_id': existing_row[0],
                        'existing_kick_name': existing_row[1]
                    }
                
                # Check if discord_id already has a shuffle link
                discord_check = conn.execute(text("""
                    SELECT shuffle_username FROM raffle_shuffle_links
                    WHERE discord_id = :discord_id
                """), {'discord_id': discord_id})
                
                discord_row = discord_check.fetchone()
                
                if discord_row:
                    return {
                        'status': 'discord_already_linked',
                        'existing_shuffle_username': discord_row[0]
                    }
                
                # Create the link
                conn.execute(text("""
                    INSERT INTO raffle_shuffle_links
                        (shuffle_username, kick_name, discord_id, verified, verified_by_discord_id, verified_at)
                    VALUES
                        (:shuffle_username, :kick_name, :discord_id, :verified, :verified_by, 
                         CASE WHEN :verified THEN CURRENT_TIMESTAMP ELSE NULL END)
                """), {
                    'shuffle_username': shuffle_username,
                    'kick_name': kick_name,
                    'discord_id': discord_id,
                    'verified': verified,
                    'verified_by': verified_by
                })
            
            logger.info(f"🔗 Linked Shuffle account: {shuffle_username} → {kick_name} (Discord: {discord_id}, verified: {verified})")
            
            return {
                'status': 'success',
                'shuffle_username': shuffle_username,
                'kick_name': kick_name,
                'discord_id': discord_id,
                'verified': verified
            }
            
        except Exception as e:
            logger.error(f"Failed to link Shuffle account: {e}")
            return {'status': 'error', 'error': str(e)}
    
    def _get_active_period_id(self):
        """Get the ID of the currently active raffle period"""
        try:
            with self.engine.begin() as conn:
                result = conn.execute(text("""
                    SELECT id FROM raffle_periods
                    WHERE status = 'active'
                    ORDER BY start_date DESC
                    LIMIT 1
                """))
                row = result.fetchone()
                return row[0] if row else None
        except Exception as e:
            logger.error(f"Failed to get active period: {e}")
            return None


async def setup_shuffle_tracker(bot, engine):
    """
    Setup the Shuffle wager tracker as a Discord bot task
    
    Args:
        bot: Discord bot instance
        engine: SQLAlchemy engine
    """
    from discord.ext import tasks
    
    tracker = ShuffleWagerTracker(engine)
    
    @tasks.loop(minutes=15)  # Run every 15 minutes
    async def update_shuffle_task():
        """Periodic task to update Shuffle wagers and award tickets"""
        logger.info("🔄 Checking Shuffle.com wagers...")
        result = await tracker.update_shuffle_wagers()
        
        if result['status'] == 'success' and result['updates'] > 0:
            logger.info(f"✅ Updated {result['updates']} Shuffle wager(s)")
        elif result['status'] == 'no_active_period':
            logger.debug("No active raffle period")
        elif result['status'] == 'error':
            logger.error(f"Shuffle update failed: {result.get('error')}")
    
    @update_shuffle_task.before_loop
    async def before_shuffle_task():
        """Wait for bot to be ready before starting the task"""
        await bot.wait_until_ready()
        logger.info("✅ Shuffle wager tracker started (runs every 15 minutes)")
    
    # Start the task
    update_shuffle_task.start()
    
    return tracker
