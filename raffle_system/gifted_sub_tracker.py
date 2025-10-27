"""
Gifted Sub Tracker
Listens for Kick gifted subscription events and awards raffle tickets
"""

from sqlalchemy import text
from datetime import datetime
import logging
import json

from .config import GIFTED_SUB_TICKETS
from .tickets import TicketManager

logger = logging.getLogger(__name__)


class GiftedSubTracker:
    """Tracks gifted subs and awards raffle tickets"""
    
    def __init__(self, engine):
        self.engine = engine
        self.ticket_manager = TicketManager(engine)
    
    async def handle_gifted_sub_event(self, event_data):
        """
        Handle a gifted subscription event from Kick websocket
        
        Expected event_data format from Kick:
        {
            "id": "unique_event_id",
            "sender": {
                "username": "generous_viewer",
                "id": 12345
            },
            "gift_count": 5  # or "quantity" or similar
        }
        
        Args:
            event_data: Parsed JSON data from the Kick websocket event
            
        Returns:
            dict: Result of ticket awarding
        """
        try:
            # Extract event details
            event_id = event_data.get("id")
            sender = event_data.get("sender", {})
            gifter_kick_name = sender.get("username")
            
            # Try different possible field names for gift count
            gift_count = (
                event_data.get("gift_count") or
                event_data.get("quantity") or
                event_data.get("count") or
                event_data.get("gifted_usernames", [])  # If it's an array of recipients
            )
            
            # If gift_count is a list (recipients), count the length
            if isinstance(gift_count, list):
                gift_count = len(gift_count)
            elif gift_count is None:
                gift_count = 1  # Default to 1 if not specified
            
            if not gifter_kick_name:
                logger.warning("Gifted sub event missing gifter username")
                return {'status': 'error', 'error': 'missing_username'}
            
            if not event_id:
                # Generate a fallback ID if none provided
                event_id = f"{gifter_kick_name}_{int(datetime.now().timestamp())}"
            
            # Get active raffle period
            period_id = self._get_active_period_id()
            if not period_id:
                logger.warning("No active raffle period - cannot award tickets for gifted sub")
                return {'status': 'no_active_period'}
            
            # Check if this event has already been processed (prevent duplicates)
            with self.engine.begin() as conn:
                existing = conn.execute(text("""
                    SELECT id FROM raffle_gifted_subs
                    WHERE kick_event_id = :event_id
                """), {'event_id': event_id})
                
                if existing.fetchone():
                    logger.debug(f"Gifted sub event {event_id} already processed - skipping")
                    return {'status': 'duplicate', 'event_id': event_id}
                
                # Look up Discord ID from links table
                discord_result = conn.execute(text("""
                    SELECT discord_id FROM links
                    WHERE kick_name = :kick_name
                """), {'kick_name': gifter_kick_name})
                
                discord_row = discord_result.fetchone()
                discord_id = discord_row[0] if discord_row else None
                
                if not discord_id:
                    logger.warning(f"User {gifter_kick_name} not linked - cannot award tickets")
                    # Still log the event but don't award tickets
                    conn.execute(text("""
                        INSERT INTO raffle_gifted_subs
                            (period_id, gifter_kick_name, gifter_discord_id, sub_count, 
                             tickets_awarded, kick_event_id)
                        VALUES
                            (:period_id, :kick_name, NULL, :sub_count, 0, :event_id)
                    """), {
                        'period_id': period_id,
                        'kick_name': gifter_kick_name,
                        'sub_count': gift_count,
                        'event_id': event_id
                    })
                    return {'status': 'not_linked', 'kick_name': gifter_kick_name}
                
                # Calculate tickets
                tickets_to_award = gift_count * GIFTED_SUB_TICKETS
                
                # Award the tickets
                success = self.ticket_manager.award_tickets(
                    discord_id=discord_id,
                    kick_name=gifter_kick_name,
                    tickets=tickets_to_award,
                    source='gifted_sub',
                    description=f"Gifted {gift_count} sub{'s' if gift_count > 1 else ''} in chat",
                    period_id=period_id
                )
                
                if not success:
                    logger.error(f"Failed to award tickets to {gifter_kick_name}")
                    return {'status': 'award_failed'}
                
                # Log the gifted sub event
                conn.execute(text("""
                    INSERT INTO raffle_gifted_subs
                        (period_id, gifter_kick_name, gifter_discord_id, sub_count,
                         tickets_awarded, kick_event_id)
                    VALUES
                        (:period_id, :kick_name, :discord_id, :sub_count, 
                         :tickets, :event_id)
                """), {
                    'period_id': period_id,
                    'kick_name': gifter_kick_name,
                    'discord_id': discord_id,
                    'sub_count': gift_count,
                    'tickets': tickets_to_award,
                    'event_id': event_id
                })
            
            logger.info(f"🎁 {gifter_kick_name} gifted {gift_count} sub(s) → {tickets_to_award} tickets")
            
            return {
                'status': 'success',
                'gifter': gifter_kick_name,
                'discord_id': discord_id,
                'gift_count': gift_count,
                'tickets_awarded': tickets_to_award
            }
            
        except Exception as e:
            logger.error(f"Failed to handle gifted sub event: {e}")
            return {'status': 'error', 'error': str(e)}
    
    def get_user_gifted_subs(self, discord_id, period_id=None):
        """
        Get gifted sub history for a user
        
        Args:
            discord_id: Discord user ID
            period_id: Raffle period ID (None = current active period)
            
        Returns:
            list: List of gifted sub events
        """
        try:
            if period_id is None:
                period_id = self._get_active_period_id()
                if not period_id:
                    return []
            
            with self.engine.begin() as conn:
                result = conn.execute(text("""
                    SELECT 
                        sub_count,
                        tickets_awarded,
                        gifted_at
                    FROM raffle_gifted_subs
                    WHERE period_id = :period_id AND gifter_discord_id = :discord_id
                    ORDER BY gifted_at DESC
                """), {
                    'period_id': period_id,
                    'discord_id': discord_id
                })
                
                events = []
                for row in result:
                    events.append({
                        'sub_count': row[0],
                        'tickets_awarded': row[1],
                        'gifted_at': row[2]
                    })
                
                return events
                
        except Exception as e:
            logger.error(f"Failed to get gifted subs: {e}")
            return []
    
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


def setup_gifted_sub_handler(engine):
    """
    Create a gifted sub tracker instance
    
    Args:
        engine: SQLAlchemy engine
        
    Returns:
        GiftedSubTracker: Initialized tracker
    """
    tracker = GiftedSubTracker(engine)
    logger.info("✅ Gifted sub tracker initialized")
    return tracker
