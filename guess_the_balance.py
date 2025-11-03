"""
Guess the Balance - Game where users guess the final balance amount
Admins open/close sessions and set the result to determine winners
"""

import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Optional, List, Dict, Tuple
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


class GuessTheBalanceManager:
    """Manages Guess the Balance game sessions and guesses"""
    
    def __init__(self, engine: Engine):
        self.engine = engine
        logger.info("GuessTheBalanceManager initialized")
    
    def get_active_session(self) -> Optional[Dict]:
        """Get the currently active (open) session if one exists"""
        if not self.engine:
            return None
        
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text("""
                    SELECT id, opened_by, opened_at, status
                    FROM gtb_sessions
                    WHERE status = 'open'
                    ORDER BY opened_at DESC
                    LIMIT 1
                """)).fetchone()
                
                if result:
                    return {
                        "id": result[0],
                        "opened_by": result[1],
                        "opened_at": result[2],
                        "status": result[3]
                    }
                return None
        except Exception as e:
            logger.error(f"Failed to get active session: {e}")
            return None
    
    def open_session(self, opened_by: str) -> Tuple[bool, str]:
        """
        Open a new GTB session
        
        Returns:
            (success, message)
        """
        if not self.engine:
            return False, "Database not available"
        
        # Check if there's already an active session
        active = self.get_active_session()
        if active:
            return False, f"A session is already open (opened by {active['opened_by']})"
        
        try:
            with self.engine.begin() as conn:
                result = conn.execute(text("""
                    INSERT INTO gtb_sessions (opened_by, status)
                    VALUES (:opened_by, 'open')
                    RETURNING id
                """), {"opened_by": opened_by})
                
                session_id = result.fetchone()[0]
                logger.info(f"GTB session #{session_id} opened by {opened_by}")
                return True, f"Session #{session_id} opened! Users can now guess with !gtb <amount>"
        except Exception as e:
            logger.error(f"Failed to open session: {e}")
            return False, f"Failed to open session: {str(e)}"
    
    def close_session(self) -> Tuple[bool, str, Optional[int]]:
        """
        Close the active session (stop accepting guesses)
        
        Returns:
            (success, message, session_id)
        """
        if not self.engine:
            return False, "Database not available", None
        
        active = self.get_active_session()
        if not active:
            return False, "No active session to close", None
        
        session_id = active["id"]
        
        try:
            with self.engine.begin() as conn:
                conn.execute(text("""
                    UPDATE gtb_sessions
                    SET status = 'closed', closed_at = CURRENT_TIMESTAMP
                    WHERE id = :session_id
                """), {"session_id": session_id})
                
                # Get guess count
                guess_count = conn.execute(text("""
                    SELECT COUNT(*) FROM gtb_guesses WHERE session_id = :session_id
                """), {"session_id": session_id}).fetchone()[0]
                
                logger.info(f"GTB session #{session_id} closed with {guess_count} guesses")
                return True, f"Session #{session_id} closed with {guess_count} guesses. Use !gtbresult <amount> to set the result.", session_id
        except Exception as e:
            logger.error(f"Failed to close session: {e}")
            return False, f"Failed to close session: {str(e)}", None
    
    def add_guess(self, kick_username: str, guess_amount: float) -> Tuple[bool, str]:
        """
        Add a user's guess to the active session
        
        Returns:
            (success, message)
        """
        if not self.engine:
            return False, "Database not available"
        
        # Check if there's an active session
        active = self.get_active_session()
        if not active:
            return False, "No active GTB session. Wait for an admin to start one!"
        
        session_id = active["id"]
        
        # Validate amount
        if guess_amount <= 0:
            return False, "Guess amount must be greater than 0"
        
        if guess_amount > 999999999999.99:  # 12 digits total, 2 decimals
            return False, "Guess amount is too large"
        
        try:
            with self.engine.begin() as conn:
                # Try to insert (will fail if user already guessed)
                conn.execute(text("""
                    INSERT INTO gtb_guesses (session_id, kick_username, guess_amount)
                    VALUES (:session_id, :username, :amount)
                    ON CONFLICT (session_id, kick_username)
                    DO UPDATE SET guess_amount = :amount, guessed_at = CURRENT_TIMESTAMP
                """), {
                    "session_id": session_id,
                    "username": kick_username,
                    "amount": guess_amount
                })
                
                logger.info(f"GTB: {kick_username} guessed ${guess_amount:,.2f} in session #{session_id}")
                return True, f"Guess recorded: ${guess_amount:,.2f}"
        except Exception as e:
            logger.error(f"Failed to add guess: {e}")
            return False, f"Failed to record guess: {str(e)}"
    
    def set_result(self, result_amount: float) -> Tuple[bool, str, Optional[List[Dict]]]:
        """
        Set the result for the most recent closed session and calculate winners
        
        Returns:
            (success, message, winners_list)
        """
        if not self.engine:
            return False, "Database not available", None
        
        # Validate amount
        if result_amount <= 0:
            return False, "Result amount must be greater than 0", None
        
        try:
            with self.engine.begin() as conn:
                # Get the most recent closed session
                session = conn.execute(text("""
                    SELECT id FROM gtb_sessions
                    WHERE status = 'closed'
                    ORDER BY closed_at DESC
                    LIMIT 1
                """)).fetchone()
                
                if not session:
                    return False, "No closed session found. Close a session first with !gtbclose", None
                
                session_id = session[0]
                
                # Update session with result
                conn.execute(text("""
                    UPDATE gtb_sessions
                    SET result_amount = :amount, status = 'completed'
                    WHERE id = :session_id
                """), {"amount": result_amount, "session_id": session_id})
                
                # Get all guesses with calculated differences
                guesses = conn.execute(text("""
                    SELECT kick_username, guess_amount, 
                           ABS(guess_amount - :result) as difference
                    FROM gtb_guesses
                    WHERE session_id = :session_id
                    ORDER BY difference ASC, guessed_at ASC
                    LIMIT 3
                """), {"result": result_amount, "session_id": session_id}).fetchall()
                
                if not guesses:
                    return False, f"Session #{session_id} has no guesses!", None
                
                # Clear any existing winners for this session (in case of re-calculation)
                conn.execute(text("""
                    DELETE FROM gtb_winners WHERE session_id = :session_id
                """), {"session_id": session_id})
                
                # Insert winners
                winners = []
                for rank, (username, guess, diff) in enumerate(guesses, 1):
                    conn.execute(text("""
                        INSERT INTO gtb_winners 
                        (session_id, kick_username, rank, guess_amount, result_amount, difference)
                        VALUES (:session_id, :username, :rank, :guess, :result, :diff)
                    """), {
                        "session_id": session_id,
                        "username": username,
                        "rank": rank,
                        "guess": guess,
                        "result": result_amount,
                        "diff": diff
                    })
                    
                    winners.append({
                        "rank": rank,
                        "username": username,
                        "guess": float(guess),
                        "difference": float(diff)
                    })
                
                logger.info(f"GTB session #{session_id} completed with result ${result_amount:,.2f}")
                return True, f"Results set! Winners calculated.", winners
                
        except Exception as e:
            logger.error(f"Failed to set result: {e}")
            return False, f"Failed to set result: {str(e)}", None
    
    def get_session_stats(self, session_id: int) -> Optional[Dict]:
        """Get statistics for a specific session"""
        if not self.engine:
            return None
        
        try:
            with self.engine.connect() as conn:
                session = conn.execute(text("""
                    SELECT id, opened_by, opened_at, closed_at, result_amount, status
                    FROM gtb_sessions
                    WHERE id = :session_id
                """), {"session_id": session_id}).fetchone()
                
                if not session:
                    return None
                
                guess_count = conn.execute(text("""
                    SELECT COUNT(*) FROM gtb_guesses WHERE session_id = :session_id
                """), {"session_id": session_id}).fetchone()[0]
                
                return {
                    "id": session[0],
                    "opened_by": session[1],
                    "opened_at": session[2],
                    "closed_at": session[3],
                    "result_amount": float(session[4]) if session[4] else None,
                    "status": session[5],
                    "guess_count": guess_count
                }
        except Exception as e:
            logger.error(f"Failed to get session stats: {e}")
            return None


def parse_amount(amount_str: str) -> Optional[float]:
    """
    Parse amount string to float, handling commas and dollar signs
    
    Examples:
        "$1234.56" -> 1234.56
        "1,234.56" -> 1234.56
        "1234" -> 1234.0
    """
    try:
        # Remove dollar signs, commas, and spaces
        cleaned = amount_str.replace("$", "").replace(",", "").replace(" ", "").strip()
        
        # Convert to float
        amount = float(cleaned)
        
        # Validate
        if amount <= 0:
            return None
        
        return amount
    except (ValueError, InvalidOperation):
        return None
