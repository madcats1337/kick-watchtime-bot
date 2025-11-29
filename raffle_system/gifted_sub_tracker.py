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
    """Tracks gifted subs and awards raffle tickets for a specific server"""

    def __init__(self, engine, discord_server_id: int):
        self.engine = engine
        self.discord_server_id = discord_server_id
        self.ticket_manager = TicketManager(engine, discord_server_id)

    async def handle_gifted_sub_event(self, event_data):
        """
        Handle a subscription event from Kick websocket (gifted or regular)

        Expected event_data format from Kick:
        {
            "id": "unique_event_id",
            "sender": {
                "username": "generous_viewer",
                "id": 12345
            },
            "gift_count": 5,  # For gifted subs (optional)
            "months": 1        # For regular subs (optional)
        }

        OR for LuckyUsersWhoGotGiftSubscriptionsEvent:
        {
            "channel": {...},
            "usernames": ["user1", "user2", "user3"],
            "gifter_username": "generous_viewer"
        }

        Args:
            event_data: Parsed JSON data from the Kick websocket event

        Returns:
            dict: Result of ticket awarding
        """
        try:
            # Extract event details
            event_id = event_data.get("id")

            # Handle different event formats
            # LuckyUsersWhoGotGiftSubscriptionsEvent format
            if "gifter_username" in event_data:
                logger.info(f"[GiftedSubTracker] Processing LuckyUsersWhoGotGiftSubscriptionsEvent")
                gifter_kick_name = event_data.get("gifter_username")
                # usernames is an array of recipients
                recipients = event_data.get("usernames", [])
                # If recipients list is empty or None, default to 1 sub
                gift_count = len(recipients) if (recipients and len(recipients) > 0) else 1
                logger.info(f"[GiftedSubTracker] Gifter: {gifter_kick_name}, Recipients: {recipients}, Count: {gift_count}")
            else:
                # For regular subs, the subscriber might be in "sender" or directly in event
                sender = event_data.get("sender", {})
                gifter_kick_name = sender.get("username") or event_data.get("username")

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
                    # For regular subs (not gifted), count as 1
                    gift_count = 1

            if not gifter_kick_name:
                logger.warning("Gifted sub event missing gifter username")
                return {'status': 'error', 'error': 'missing_username'}

            if not event_id:
                # Generate a fallback ID if none provided
                event_id = f"{gifter_kick_name}_{int(datetime.now().timestamp())}"
                logger.info(f"[GiftedSubTracker] No event ID provided, generated: {event_id}")

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
                    # Still log the event but don't award tickets for this server
                    conn.execute(text("""
                        INSERT INTO raffle_gifted_subs
                            (period_id, gifter_kick_name, gifter_discord_id, sub_count,
                             tickets_awarded, kick_event_id, discord_server_id)
                        VALUES
                            (:period_id, :kick_name, NULL, :sub_count, 0, :event_id, :server_id)
                    """), {
                        'period_id': period_id,
                        'kick_name': gifter_kick_name,
                        'sub_count': gift_count,
                        'event_id': event_id,
                        'server_id': self.discord_server_id
                    })
                    return {'status': 'not_linked', 'kick_name': gifter_kick_name}

                # Calculate tickets
                tickets_to_award = gift_count * GIFTED_SUB_TICKETS

                # Award the tickets
                sub_description = "Subscribed" if gift_count == 1 else f"Gifted {gift_count} subs"
                success = self.ticket_manager.award_tickets(
                    discord_id=discord_id,
                    kick_name=gifter_kick_name,
                    tickets=tickets_to_award,
                    source='gifted_sub',
                    description=f"{sub_description} in chat",
                    period_id=period_id
                )

                if not success:
                    logger.error(f"Failed to award tickets to {gifter_kick_name}")
                    return {'status': 'award_failed'}

                # Log the gifted sub event for this server
                conn.execute(text("""
                    INSERT INTO raffle_gifted_subs
                        (period_id, gifter_kick_name, gifter_discord_id, sub_count,
                         tickets_awarded, kick_event_id, discord_server_id)
                    VALUES
                        (:period_id, :kick_name, :discord_id, :sub_count,
                         :tickets, :event_id, :server_id)
                """), {
                    'period_id': period_id,
                    'kick_name': gifter_kick_name,
                    'discord_id': discord_id,
                    'sub_count': gift_count,
                    'tickets': tickets_to_award,
                    'event_id': event_id,
                    'server_id': self.discord_server_id
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
                        AND discord_server_id = :server_id
                    ORDER BY gifted_at DESC
                """), {
                    'period_id': period_id,
                    'discord_id': discord_id,
                    'server_id': self.discord_server_id
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
        """Get the ID of the currently active raffle period for this server"""
        try:
            with self.engine.begin() as conn:
                result = conn.execute(text("""
                    SELECT id FROM raffle_periods
                    WHERE status = 'active' AND discord_server_id = :server_id
                    ORDER BY start_date DESC
                    LIMIT 1
                """), {'server_id': self.discord_server_id})
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
