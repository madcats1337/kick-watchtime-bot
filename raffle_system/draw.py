"""
Raffle Draw Logic
Implements provably fair random drawing using cryptographic randomness
"""

from sqlalchemy import text
from datetime import datetime
import secrets
import logging

logger = logging.getLogger(__name__)


class RaffleDraw:
    """Handles raffle drawing and winner selection"""
    
    def __init__(self, engine):
        self.engine = engine
    
    def draw_winner(self, period_id, drawn_by_discord_id=None, prize_description=None):
        """
        Draw a random winner for the raffle period using cryptographic randomness
        
        Each user's tickets represent sequential entries in the raffle.
        Example: User A (10 tickets) = entries 1-10, User B (25 tickets) = entries 11-35
        
        Args:
            period_id: Raffle period ID to draw from
            drawn_by_discord_id: Discord ID of admin who triggered draw (optional)
            prize_description: Description of the prize (optional)
            
        Returns:
            dict: Winner info or None if no participants
        """
        try:
            with self.engine.begin() as conn:
                # Get all participants with tickets
                result = conn.execute(text("""
                    SELECT discord_id, kick_name, total_tickets
                    FROM raffle_tickets
                    WHERE period_id = :period_id AND total_tickets > 0
                    ORDER BY id  -- Deterministic ordering for reproducibility
                """), {'period_id': period_id})
                
                participants = list(result)
                
                if not participants:
                    logger.warning(f"No participants found for period {period_id}")
                    return None
                
                # Build ticket number ranges
                ticket_ranges = []
                current_ticket = 1
                
                for discord_id, kick_name, ticket_count in participants:
                    ticket_ranges.append({
                        'discord_id': discord_id,
                        'kick_name': kick_name,
                        'ticket_count': ticket_count,
                        'start_ticket': current_ticket,
                        'end_ticket': current_ticket + ticket_count - 1
                    })
                    current_ticket += ticket_count
                
                total_tickets = current_ticket - 1
                total_participants = len(participants)
                
                # Draw winning ticket using cryptographic randomness
                winning_ticket = secrets.randbelow(total_tickets) + 1
                
                logger.info(f"🎲 Drawing raffle for period {period_id}")
                logger.info(f"   Total tickets: {total_tickets}")
                logger.info(f"   Total participants: {total_participants}")
                logger.info(f"   Winning ticket: #{winning_ticket}")
                
                # Find the winner
                winner = None
                for entry in ticket_ranges:
                    if entry['start_ticket'] <= winning_ticket <= entry['end_ticket']:
                        winner = entry
                        break
                
                if not winner:
                    logger.error("Failed to determine winner (should never happen)")
                    return None
                
                # Get Shuffle username if linked
                shuffle_result = conn.execute(text("""
                    SELECT shuffle_username FROM raffle_shuffle_links
                    WHERE discord_id = :discord_id
                """), {'discord_id': winner['discord_id']})
                shuffle_row = shuffle_result.fetchone()
                shuffle_username = shuffle_row[0] if shuffle_row else None
                
                # Record the draw
                conn.execute(text("""
                    INSERT INTO raffle_draws
                        (period_id, total_tickets, total_participants, winner_discord_id, 
                         winner_kick_name, winner_shuffle_name, winning_ticket, 
                         prize_description, drawn_by_discord_id)
                    VALUES
                        (:period_id, :total_tickets, :total_participants, :winner_discord_id,
                         :winner_kick_name, :winner_shuffle_name, :winning_ticket,
                         :prize_description, :drawn_by_discord_id)
                """), {
                    'period_id': period_id,
                    'total_tickets': total_tickets,
                    'total_participants': total_participants,
                    'winner_discord_id': winner['discord_id'],
                    'winner_kick_name': winner['kick_name'],
                    'winner_shuffle_name': shuffle_username,
                    'winning_ticket': winning_ticket,
                    'prize_description': prize_description,
                    'drawn_by_discord_id': drawn_by_discord_id
                })
                
                # Update the raffle period with winner info
                conn.execute(text("""
                    UPDATE raffle_periods
                    SET 
                        winner_discord_id = :winner_discord_id,
                        winner_kick_name = :winner_kick_name,
                        winning_ticket_number = :winning_ticket,
                        total_tickets = :total_tickets,
                        status = 'ended'
                    WHERE id = :period_id
                """), {
                    'period_id': period_id,
                    'winner_discord_id': winner['discord_id'],
                    'winner_kick_name': winner['kick_name'],
                    'winning_ticket': winning_ticket,
                    'total_tickets': total_tickets
                })
            
            result = {
                'winner_discord_id': winner['discord_id'],
                'winner_kick_name': winner['kick_name'],
                'winner_shuffle_name': shuffle_username,
                'winner_tickets': winner['ticket_count'],
                'winning_ticket': winning_ticket,
                'total_tickets': total_tickets,
                'total_participants': total_participants,
                'win_probability': (winner['ticket_count'] / total_tickets * 100)
            }
            
            logger.info(f"🎉 Winner: {winner['kick_name']} (Discord ID: {winner['discord_id']})")
            logger.info(f"   Winner's tickets: {winner['ticket_count']}/{total_tickets} ({result['win_probability']:.2f}%)")
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to draw winner: {e}")
            return None
    
    def get_draw_history(self, limit=5):
        """
        Get recent raffle draw results
        
        Args:
            limit: Number of draws to return
            
        Returns:
            list: List of draw results
        """
        try:
            with self.engine.begin() as conn:
                result = conn.execute(text("""
                    SELECT 
                        rd.period_id,
                        rd.winner_discord_id,
                        rd.winner_kick_name,
                        rd.winner_shuffle_name,
                        rd.winning_ticket,
                        rd.total_tickets,
                        rd.total_participants,
                        rd.prize_description,
                        rd.drawn_at,
                        rp.start_date,
                        rp.end_date
                    FROM raffle_draws rd
                    JOIN raffle_periods rp ON rp.id = rd.period_id
                    ORDER BY rd.drawn_at DESC
                    LIMIT :limit
                """), {'limit': limit})
                
                history = []
                for row in result:
                    history.append({
                        'period_id': row[0],
                        'winner_discord_id': row[1],
                        'winner_kick_name': row[2],
                        'winner_shuffle_name': row[3],
                        'winning_ticket': row[4],
                        'total_tickets': row[5],
                        'total_participants': row[6],
                        'prize_description': row[7],
                        'drawn_at': row[8],
                        'period_start': row[9],
                        'period_end': row[10]
                    })
                
                return history
                
        except Exception as e:
            logger.error(f"Failed to get draw history: {e}")
            return []
    
    def get_user_win_probability(self, discord_id, period_id):
        """
        Calculate a user's probability of winning
        
        Args:
            discord_id: Discord user ID
            period_id: Raffle period ID
            
        Returns:
            dict: Win probability info or None
        """
        try:
            with self.engine.begin() as conn:
                # Get user's tickets
                user_result = conn.execute(text("""
                    SELECT total_tickets FROM raffle_tickets
                    WHERE period_id = :period_id AND discord_id = :discord_id
                """), {
                    'period_id': period_id,
                    'discord_id': discord_id
                })
                user_row = user_result.fetchone()
                
                if not user_row or user_row[0] == 0:
                    return None
                
                user_tickets = user_row[0]
                
                # Get total tickets
                total_result = conn.execute(text("""
                    SELECT COALESCE(SUM(total_tickets), 0) FROM raffle_tickets
                    WHERE period_id = :period_id
                """), {'period_id': period_id})
                total_tickets = total_result.scalar()
                
                if total_tickets == 0:
                    return None
                
                probability = (user_tickets / total_tickets) * 100
                
                return {
                    'user_tickets': user_tickets,
                    'total_tickets': total_tickets,
                    'probability_percent': probability,
                    'odds': f"{user_tickets}/{total_tickets}"
                }
                
        except Exception as e:
            logger.error(f"Failed to calculate win probability: {e}")
            return None
    
    def simulate_draw(self, period_id, num_simulations=1000):
        """
        Simulate multiple draws to verify fairness (testing purposes)
        
        Args:
            period_id: Raffle period ID
            num_simulations: Number of simulations to run
            
        Returns:
            dict: Simulation results
        """
        try:
            with self.engine.begin() as conn:
                result = conn.execute(text("""
                    SELECT discord_id, kick_name, total_tickets
                    FROM raffle_tickets
                    WHERE period_id = :period_id AND total_tickets > 0
                    ORDER BY id
                """), {'period_id': period_id})
                
                participants = list(result)
                
                if not participants:
                    return None
                
                # Build ticket ranges
                ticket_ranges = []
                current_ticket = 1
                
                for discord_id, kick_name, ticket_count in participants:
                    ticket_ranges.append({
                        'discord_id': discord_id,
                        'kick_name': kick_name,
                        'ticket_count': ticket_count,
                        'start_ticket': current_ticket,
                        'end_ticket': current_ticket + ticket_count - 1,
                        'wins': 0
                    })
                    current_ticket += ticket_count
                
                total_tickets = current_ticket - 1
                
                # Run simulations
                for _ in range(num_simulations):
                    winning_ticket = secrets.randbelow(total_tickets) + 1
                    
                    for entry in ticket_ranges:
                        if entry['start_ticket'] <= winning_ticket <= entry['end_ticket']:
                            entry['wins'] += 1
                            break
                
                # Calculate results
                results = []
                for entry in ticket_ranges:
                    expected_wins = (entry['ticket_count'] / total_tickets) * num_simulations
                    actual_wins = entry['wins']
                    variance = ((actual_wins - expected_wins) / expected_wins * 100) if expected_wins > 0 else 0
                    
                    results.append({
                        'kick_name': entry['kick_name'],
                        'tickets': entry['ticket_count'],
                        'expected_wins': expected_wins,
                        'actual_wins': actual_wins,
                        'variance_percent': variance
                    })
                
                return {
                    'num_simulations': num_simulations,
                    'total_tickets': total_tickets,
                    'participants': len(participants),
                    'results': results
                }
                
        except Exception as e:
            logger.error(f"Failed to simulate draw: {e}")
            return None
