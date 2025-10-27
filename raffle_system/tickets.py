"""
Core Ticket Management Logic
Handles all ticket operations (award, remove, query, transfer)
"""

from sqlalchemy import text
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class TicketManager:
    """Manages raffle tickets for all users"""
    
    def __init__(self, engine):
        self.engine = engine
    
    def get_user_tickets(self, discord_id, period_id=None):
        """
        Get ticket balance for a user
        
        Args:
            discord_id: Discord user ID
            period_id: Raffle period ID (None = current active period)
            
        Returns:
            dict: Ticket breakdown or None
        """
        try:
            # Get current period if not specified
            if period_id is None:
                period_id = self._get_active_period_id()
                if not period_id:
                    return None
            
            with self.engine.begin() as conn:
                result = conn.execute(text("""
                    SELECT 
                        kick_name,
                        watchtime_tickets,
                        gifted_sub_tickets,
                        shuffle_wager_tickets,
                        bonus_tickets,
                        total_tickets,
                        last_updated
                    FROM raffle_tickets
                    WHERE period_id = :period_id AND discord_id = :discord_id
                """), {
                    'period_id': period_id,
                    'discord_id': discord_id
                })
                
                row = result.fetchone()
                if row:
                    return {
                        'discord_id': discord_id,
                        'kick_name': row[0],
                        'watchtime_tickets': row[1],
                        'gifted_sub_tickets': row[2],
                        'shuffle_wager_tickets': row[3],
                        'bonus_tickets': row[4],
                        'total_tickets': row[5],
                        'last_updated': row[6],
                        'period_id': period_id
                    }
                return None
                
        except Exception as e:
            logger.error(f"Failed to get tickets for user {discord_id}: {e}")
            return None
    
    def award_tickets(self, discord_id, kick_name, tickets, source, description=None, period_id=None):
        """
        Award tickets to a user
        
        Args:
            discord_id: Discord user ID
            kick_name: Kick username
            tickets: Number of tickets to award
            source: Source of tickets ('watchtime', 'gifted_sub', 'shuffle_wager', 'bonus')
            description: Optional description for audit log
            period_id: Raffle period ID (None = current active period)
            
        Returns:
            bool: True if successful
        """
        if tickets <= 0:
            logger.warning(f"Attempted to award {tickets} tickets (must be > 0)")
            return False
        
        try:
            # Get current period if not specified
            if period_id is None:
                period_id = self._get_active_period_id()
                if not period_id:
                    logger.error("No active raffle period found")
                    return False
            
            # Determine which column to update based on source
            source_column_map = {
                'watchtime': 'watchtime_tickets',
                'gifted_sub': 'gifted_sub_tickets',
                'shuffle_wager': 'shuffle_wager_tickets',
                'bonus': 'bonus_tickets'
            }
            
            source_column = source_column_map.get(source)
            if not source_column:
                logger.error(f"Invalid ticket source: {source}")
                return False
            
            with self.engine.begin() as conn:
                # Insert or update user's ticket balance
                conn.execute(text(f"""
                    INSERT INTO raffle_tickets 
                        (period_id, discord_id, kick_name, {source_column}, total_tickets, last_updated)
                    VALUES 
                        (:period_id, :discord_id, :kick_name, :tickets, :tickets, CURRENT_TIMESTAMP)
                    ON CONFLICT (period_id, discord_id) 
                    DO UPDATE SET
                        {source_column} = raffle_tickets.{source_column} + :tickets,
                        total_tickets = raffle_tickets.total_tickets + :tickets,
                        last_updated = CURRENT_TIMESTAMP
                """), {
                    'period_id': period_id,
                    'discord_id': discord_id,
                    'kick_name': kick_name,
                    'tickets': tickets
                })
                
                # Log the transaction
                conn.execute(text("""
                    INSERT INTO raffle_ticket_log
                        (period_id, discord_id, kick_name, ticket_change, source, description)
                    VALUES
                        (:period_id, :discord_id, :kick_name, :change, :source, :desc)
                """), {
                    'period_id': period_id,
                    'discord_id': discord_id,
                    'kick_name': kick_name,
                    'change': tickets,
                    'source': source,
                    'desc': description or f"Awarded {tickets} tickets from {source}"
                })
            
            logger.info(f"✅ Awarded {tickets} {source} tickets to {kick_name} (Discord ID: {discord_id})")
            return True
            
        except Exception as e:
            logger.error(f"Failed to award tickets: {e}")
            return False
    
    def remove_tickets(self, discord_id, kick_name, tickets, reason, period_id=None):
        """
        Remove tickets from a user (for violations, etc.)
        
        Args:
            discord_id: Discord user ID
            kick_name: Kick username
            tickets: Number of tickets to remove
            reason: Reason for removal
            period_id: Raffle period ID (None = current active period)
            
        Returns:
            bool: True if successful
        """
        if tickets <= 0:
            logger.warning(f"Attempted to remove {tickets} tickets (must be > 0)")
            return False
        
        try:
            # Get current period if not specified
            if period_id is None:
                period_id = self._get_active_period_id()
                if not period_id:
                    logger.error("No active raffle period found")
                    return False
            
            with self.engine.begin() as conn:
                # Get current balance
                result = conn.execute(text("""
                    SELECT total_tickets FROM raffle_tickets
                    WHERE period_id = :period_id AND discord_id = :discord_id
                """), {
                    'period_id': period_id,
                    'discord_id': discord_id
                })
                row = result.fetchone()
                
                if not row:
                    logger.warning(f"User {discord_id} has no tickets to remove")
                    return False
                
                current_total = row[0]
                new_total = max(0, current_total - tickets)  # Don't go negative
                actual_removed = current_total - new_total
                
                # Update total tickets (proportionally reduce all sources)
                # Use MAX instead of GREATEST for SQLite compatibility
                conn.execute(text("""
                    UPDATE raffle_tickets
                    SET 
                        watchtime_tickets = MAX(0, CAST(watchtime_tickets * :ratio AS INTEGER)),
                        gifted_sub_tickets = MAX(0, CAST(gifted_sub_tickets * :ratio AS INTEGER)),
                        shuffle_wager_tickets = MAX(0, CAST(shuffle_wager_tickets * :ratio AS INTEGER)),
                        bonus_tickets = MAX(0, CAST(bonus_tickets * :ratio AS INTEGER)),
                        total_tickets = :new_total,
                        last_updated = CURRENT_TIMESTAMP
                    WHERE period_id = :period_id AND discord_id = :discord_id
                """), {
                    'period_id': period_id,
                    'discord_id': discord_id,
                    'ratio': new_total / current_total if current_total > 0 else 0,
                    'new_total': new_total
                })
                
                # Log the removal
                conn.execute(text("""
                    INSERT INTO raffle_ticket_log
                        (period_id, discord_id, kick_name, ticket_change, source, description)
                    VALUES
                        (:period_id, :discord_id, :kick_name, :change, 'admin_removal', :reason)
                """), {
                    'period_id': period_id,
                    'discord_id': discord_id,
                    'kick_name': kick_name,
                    'change': -actual_removed,
                    'reason': reason
                })
            
            logger.info(f"✅ Removed {actual_removed} tickets from {kick_name} (Discord ID: {discord_id}). Reason: {reason}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to remove tickets: {e}")
            return False
    
    def get_leaderboard(self, limit=10, period_id=None):
        """
        Get top ticket holders
        
        Args:
            limit: Number of users to return
            period_id: Raffle period ID (None = current active period)
            
        Returns:
            list: List of dicts with user info and tickets
        """
        try:
            # Get current period if not specified
            if period_id is None:
                period_id = self._get_active_period_id()
                if not period_id:
                    return []
            
            with self.engine.begin() as conn:
                result = conn.execute(text("""
                    SELECT 
                        discord_id,
                        kick_name,
                        watchtime_tickets,
                        gifted_sub_tickets,
                        shuffle_wager_tickets,
                        bonus_tickets,
                        total_tickets,
                        RANK() OVER (ORDER BY total_tickets DESC) as rank
                    FROM raffle_tickets
                    WHERE period_id = :period_id AND total_tickets > 0
                    ORDER BY total_tickets DESC
                    LIMIT :limit
                """), {
                    'period_id': period_id,
                    'limit': limit
                })
                
                leaderboard = []
                for row in result:
                    leaderboard.append({
                        'discord_id': row[0],
                        'kick_name': row[1],
                        'watchtime_tickets': row[2],
                        'gifted_sub_tickets': row[3],
                        'shuffle_wager_tickets': row[4],
                        'bonus_tickets': row[5],
                        'total_tickets': row[6],
                        'rank': row[7]
                    })
                
                return leaderboard
                
        except Exception as e:
            logger.error(f"Failed to get leaderboard: {e}")
            return []
    
    def get_user_rank(self, discord_id, period_id=None):
        """
        Get a user's rank in the current period
        
        Args:
            discord_id: Discord user ID
            period_id: Raffle period ID (None = current active period)
            
        Returns:
            int: Rank (1-indexed) or None
        """
        try:
            # Get current period if not specified
            if period_id is None:
                period_id = self._get_active_period_id()
                if not period_id:
                    return None
            
            with self.engine.begin() as conn:
                result = conn.execute(text("""
                    SELECT rank FROM raffle_leaderboard
                    WHERE period_id = :period_id AND discord_id = :discord_id
                """), {
                    'period_id': period_id,
                    'discord_id': discord_id
                })
                
                row = result.fetchone()
                return row[0] if row else None
                
        except Exception as e:
            logger.error(f"Failed to get user rank: {e}")
            return None
    
    def get_period_stats(self, period_id=None):
        """
        Get statistics for a raffle period
        
        Args:
            period_id: Raffle period ID (None = current active period)
            
        Returns:
            dict: Period statistics
        """
        try:
            # Get current period if not specified
            if period_id is None:
                period_id = self._get_active_period_id()
                if not period_id:
                    return None
            
            with self.engine.begin() as conn:
                result = conn.execute(text("""
                    SELECT * FROM raffle_current_stats
                    WHERE period_id = :period_id
                """), {'period_id': period_id})
                
                row = result.fetchone()
                if row:
                    return {
                        'period_id': row[0],
                        'start_date': row[1],
                        'end_date': row[2],
                        'status': row[3],
                        'total_participants': row[4],
                        'total_tickets': row[5],
                        'watchtime_tickets': row[6],
                        'gifted_sub_tickets': row[7],
                        'shuffle_wager_tickets': row[8],
                        'bonus_tickets': row[9]
                    }
                return None
                
        except Exception as e:
            logger.error(f"Failed to get period stats: {e}")
            return None
    
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
