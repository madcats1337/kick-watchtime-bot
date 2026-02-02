"""
Raffle Draw Logic
Implements provably fair random drawing using SHA-256 hashing
"""

import hashlib
import logging
import os
import secrets
from datetime import datetime

from sqlalchemy import text

# Import bot redis publisher for notifications
try:
    from utils.redis_publisher import bot_redis_publisher
except ImportError:
    bot_redis_publisher = None

logger = logging.getLogger(__name__)


class RaffleDraw:
    """Handles raffle drawing and winner selection"""

    def __init__(self, engine):
        self.engine = engine

    def draw_winner(
        self, period_id, drawn_by_discord_id=None, prize_description=None, excluded_discord_ids=None, update_period=True
    ):
        """
        Draw a random winner for the raffle period using cryptographic randomness

        Each user's tickets represent sequential entries in the raffle.
        Example: User A (10 tickets) = entries 1-10, User B (25 tickets) = entries 11-35

        Exclusions: Users in raffle_exclusions table are excluded from winning

        Args:
            period_id: Raffle period ID to draw from
            drawn_by_discord_id: Discord ID of admin who triggered draw (optional)
            prize_description: Description of the prize (optional)
            excluded_discord_ids: List of discord IDs to exclude (for multiple winner draws)
            update_period: Whether to mark raffle_periods as 'ended' (True only for first winner)

        Returns:
            dict: Winner info or None if no participants
        """
        try:
            excluded_discord_ids = excluded_discord_ids or []

            with self.engine.begin() as conn:
                # Get server_id from the period
                period_result = conn.execute(
                    text(
                        """
                    SELECT discord_server_id FROM raffle_periods WHERE id = :period_id
                """
                    ),
                    {"period_id": period_id},
                )
                period_row = period_result.fetchone()
                if not period_row:
                    logger.error(f"Period {period_id} not found")
                    return None
                server_id = period_row[0]

                # Get all participants with tickets (excluding those in raffle_exclusions and excluded_discord_ids)
                query = """
                    SELECT rt.discord_id, rt.kick_name, rt.total_tickets
                    FROM raffle_tickets rt
                    WHERE rt.period_id = :period_id
                      AND rt.total_tickets > 0
                      AND NOT EXISTS (
                          SELECT 1 FROM raffle_exclusions re
                          WHERE re.discord_server_id = :server_id
                            AND (
                                (re.kick_username IS NOT NULL AND LOWER(re.kick_username) = LOWER(rt.kick_name))
                                OR (re.discord_id IS NOT NULL AND re.discord_id != '' AND re.discord_id = CAST(rt.discord_id AS TEXT))
                            )
                      )
                """

                params = {"period_id": period_id, "server_id": server_id}

                # Add exclusion for already drawn winners
                if excluded_discord_ids:
                    placeholders = ", ".join([f":excluded_{i}" for i in range(len(excluded_discord_ids))])
                    query += f" AND rt.discord_id NOT IN ({placeholders})"
                    for i, discord_id in enumerate(excluded_discord_ids):
                        params[f"excluded_{i}"] = discord_id

                query += " ORDER BY rt.id"  # Deterministic ordering for reproducibility

                result = conn.execute(text(query), params)

                participants = list(result)

                if not participants:
                    logger.warning(f"No participants found for period {period_id}")
                    return None

                # Build ticket number ranges
                ticket_ranges = []
                current_ticket = 1

                for discord_id, kick_name, ticket_count in participants:
                    ticket_ranges.append(
                        {
                            "discord_id": discord_id,
                            "kick_name": kick_name,
                            "ticket_count": ticket_count,
                            "start_ticket": current_ticket,
                            "end_ticket": current_ticket + ticket_count - 1,
                        }
                    )
                    current_ticket += ticket_count

                total_tickets = current_ticket - 1
                total_participants = len(participants)

                # Draw winning ticket using provably fair SHA-256 hashing
                # Generate server seed
                server_seed = secrets.token_hex(32)  # 64 character hex string

                # Client seed: period_id:total_tickets:total_participants
                client_seed = f"{period_id}:{total_tickets}:{total_participants}"

                # Nonce: period_id
                nonce = str(period_id)

                # Create hash for provable fairness
                combined = f"{server_seed}:{client_seed}:{nonce}"
                hash_result = hashlib.sha256(combined.encode()).hexdigest()

                # Convert first 16 hex chars to integer for larger range
                random_int = int(hash_result[:16], 16)

                # Map to winning ticket (1 to total_tickets)
                winning_ticket = (random_int % total_tickets) + 1

                proof_hash = hash_result

                logger.info(f"🎲 Drawing raffle for period {period_id}")
                logger.info(f"   Total tickets: {total_tickets}")
                logger.info(f"   Total participants: {total_participants}")
                logger.info(f"   Server seed: {server_seed}")
                logger.info(f"   Client seed: {client_seed}")
                logger.info(f"   Proof hash: {proof_hash}")
                logger.info(f"   Winning ticket: #{winning_ticket}")

                # Find the winner
                winner = None
                for entry in ticket_ranges:
                    if entry["start_ticket"] <= winning_ticket <= entry["end_ticket"]:
                        winner = entry
                        break

                if not winner:
                    logger.error("Failed to determine winner (should never happen)")
                    return None

                # Get Shuffle username if linked
                shuffle_result = conn.execute(
                    text(
                        """
                    SELECT shuffle_username FROM raffle_shuffle_links
                    WHERE discord_id = :discord_id
                """
                    ),
                    {"discord_id": winner["discord_id"]},
                )
                shuffle_row = shuffle_result.fetchone()
                shuffle_username = shuffle_row[0] if shuffle_row else None

                # Record the draw
                conn.execute(
                    text(
                        """
                    INSERT INTO raffle_draws
                        (period_id, discord_server_id, total_tickets, total_participants, winner_discord_id,
                         winner_kick_name, winner_shuffle_name, winning_ticket,
                         prize_description, drawn_by_discord_id,
                         server_seed, client_seed, nonce, proof_hash)
                    VALUES
                        (:period_id, :server_id, :total_tickets, :total_participants, :winner_discord_id,
                         :winner_kick_name, :winner_shuffle_name, :winning_ticket,
                         :prize_description, :drawn_by_discord_id,
                         :server_seed, :client_seed, :nonce, :proof_hash)
                """
                    ),
                    {
                        "period_id": period_id,
                        "server_id": server_id,
                        "total_tickets": total_tickets,
                        "total_participants": total_participants,
                        "winner_discord_id": winner["discord_id"],
                        "winner_kick_name": winner["kick_name"],
                        "winner_shuffle_name": shuffle_username,
                        "winning_ticket": winning_ticket,
                        "prize_description": prize_description,
                        "drawn_by_discord_id": drawn_by_discord_id,
                        "server_seed": server_seed,
                        "client_seed": client_seed,
                        "nonce": nonce,
                        "proof_hash": proof_hash,
                    },
                )

                # Mark the raffle period as ended (only once for first winner)
                if update_period:
                    conn.execute(
                        text(
                            """
                        UPDATE raffle_periods
                        SET
                            status = 'ended',
                            total_tickets = :total_tickets
                        WHERE id = :period_id
                    """
                        ),
                        {"period_id": period_id, "total_tickets": total_tickets},
                    )

            # Publish notification to dashboard
            if bot_redis_publisher and bot_redis_publisher.enabled and update_period:
                try:
                    bot_redis_publisher.publish_raffle_draw(
                        discord_server_id=server_id,
                        winner_kick_name=winner["kick_name"],
                        winner_shuffle_name=shuffle_username,
                        prize_description=prize_description or "Raffle Prize",
                        period_id=period_id,
                    )
                except Exception as e:
                    logger.error(f"Failed to publish raffle draw notification: {e}")

            result = {
                "winner_discord_id": winner["discord_id"],
                "winner_kick_name": winner["kick_name"],
                "winner_shuffle_name": shuffle_username,
                "winner_tickets": winner["ticket_count"],
                "winning_ticket": winning_ticket,
                "total_tickets": total_tickets,
                "total_participants": total_participants,
                "win_probability": (winner["ticket_count"] / total_tickets * 100),
                "server_seed": server_seed,
                "client_seed": client_seed,
                "nonce": nonce,
                "proof_hash": proof_hash,
            }

            # NOTE: Draw events are NO LONGER published automatically here.
            # The reveal animation should ONLY be triggered by the dashboard's "Reveal Next Winner" button
            # which calls /api/raffle/reveal-winner. This ensures:
            # 1. The first winner isn't revealed instantly before pressing the button
            # 2. Discord announcements are synced to the reveal animation (via animation_complete event)
            # 3. Streamers have full control over when each winner is revealed

            logger.info(f"🎉 Winner: {winner['kick_name']} (Discord ID: {winner['discord_id']})")
            logger.info(
                f"   Winner's tickets: {winner['ticket_count']}/{total_tickets} ({result['win_probability']:.2f}%)"
            )

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
                result = conn.execute(
                    text(
                        """
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
                """
                    ),
                    {"limit": limit},
                )

                history = []
                for row in result:
                    history.append(
                        {
                            "period_id": row[0],
                            "winner_discord_id": row[1],
                            "winner_kick_name": row[2],
                            "winner_shuffle_name": row[3],
                            "winning_ticket": row[4],
                            "total_tickets": row[5],
                            "total_participants": row[6],
                            "prize_description": row[7],
                            "drawn_at": row[8],
                            "period_start": row[9],
                            "period_end": row[10],
                        }
                    )

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
                user_result = conn.execute(
                    text(
                        """
                    SELECT total_tickets FROM raffle_tickets
                    WHERE period_id = :period_id AND discord_id = :discord_id
                """
                    ),
                    {"period_id": period_id, "discord_id": discord_id},
                )
                user_row = user_result.fetchone()

                if not user_row or user_row[0] == 0:
                    return None

                user_tickets = user_row[0]

                # Get total tickets
                total_result = conn.execute(
                    text(
                        """
                    SELECT COALESCE(SUM(total_tickets), 0) FROM raffle_tickets
                    WHERE period_id = :period_id
                """
                    ),
                    {"period_id": period_id},
                )
                total_tickets = total_result.scalar()

                if total_tickets == 0:
                    return None

                probability = (user_tickets / total_tickets) * 100

                return {
                    "user_tickets": user_tickets,
                    "total_tickets": total_tickets,
                    "probability_percent": probability,
                    "odds": f"{user_tickets}/{total_tickets}",
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
                # Get server_id from the period
                period_result = conn.execute(
                    text(
                        """
                    SELECT discord_server_id FROM raffle_periods WHERE id = :period_id
                """
                    ),
                    {"period_id": period_id},
                )
                period_row = period_result.fetchone()
                if not period_row:
                    return None
                server_id = period_row[0]

                # Get participants excluding those in raffle_exclusions
                result = conn.execute(
                    text(
                        """
                    SELECT rt.discord_id, rt.kick_name, rt.total_tickets
                    FROM raffle_tickets rt
                    WHERE rt.period_id = :period_id
                      AND rt.total_tickets > 0
                      AND NOT EXISTS (
                          SELECT 1 FROM raffle_exclusions re
                          WHERE re.discord_server_id = :server_id
                            AND (
                                (re.kick_username IS NOT NULL AND LOWER(re.kick_username) = LOWER(rt.kick_name))
                                OR (re.discord_id IS NOT NULL AND re.discord_id != '' AND re.discord_id = CAST(rt.discord_id AS TEXT))
                            )
                      )
                    ORDER BY rt.id
                """
                    ),
                    {"period_id": period_id, "server_id": server_id},
                )

                participants = list(result)

                if not participants:
                    return None

                # Build ticket ranges
                ticket_ranges = []
                current_ticket = 1

                for discord_id, kick_name, ticket_count in participants:
                    ticket_ranges.append(
                        {
                            "discord_id": discord_id,
                            "kick_name": kick_name,
                            "ticket_count": ticket_count,
                            "start_ticket": current_ticket,
                            "end_ticket": current_ticket + ticket_count - 1,
                            "wins": 0,
                        }
                    )
                    current_ticket += ticket_count

                total_tickets = current_ticket - 1

                # Run simulations
                for _ in range(num_simulations):
                    winning_ticket = secrets.randbelow(total_tickets) + 1

                    for entry in ticket_ranges:
                        if entry["start_ticket"] <= winning_ticket <= entry["end_ticket"]:
                            entry["wins"] += 1
                            break

                # Calculate results
                results = []
                for entry in ticket_ranges:
                    expected_wins = (entry["ticket_count"] / total_tickets) * num_simulations
                    actual_wins = entry["wins"]
                    variance = ((actual_wins - expected_wins) / expected_wins * 100) if expected_wins > 0 else 0

                    results.append(
                        {
                            "kick_name": entry["kick_name"],
                            "tickets": entry["ticket_count"],
                            "expected_wins": expected_wins,
                            "actual_wins": actual_wins,
                            "variance_percent": variance,
                        }
                    )

                return {
                    "num_simulations": num_simulations,
                    "total_tickets": total_tickets,
                    "participants": len(participants),
                    "results": results,
                }

        except Exception as e:
            logger.error(f"Failed to simulate draw: {e}")
            return None
