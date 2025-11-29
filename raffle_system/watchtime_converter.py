"""
Watchtime to Tickets Converter
Automatically converts accumulated watchtime into raffle tickets
"""

from sqlalchemy import text
from datetime import datetime
import logging

from .config import WATCHTIME_TICKETS_PER_HOUR
from .tickets import TicketManager

logger = logging.getLogger(__name__)

class WatchtimeConverter:
    """Converts watchtime tracking into raffle tickets for a specific server"""

    def __init__(self, engine, discord_server_id: int):
        self.engine = engine
        self.discord_server_id = discord_server_id
        self.ticket_manager = TicketManager(engine, discord_server_id)

    async def convert_watchtime_to_tickets(self):
        """
        Convert accumulated watchtime into raffle tickets

        This runs periodically (every hour) and:
        1. Queries the watchtime table for all users
        2. Checks what watchtime has already been converted
        3. Converts new minutes to tickets (60 minutes = WATCHTIME_TICKETS_PER_HOUR tickets)
        4. Updates the raffle_tickets table
        5. Logs the conversion in raffle_watchtime_converted

        Returns:
            dict: Summary of conversions performed
        """
        try:
            # Get active raffle period
            period_id = self._get_active_period_id()
            if not period_id:
                logger.warning("No active raffle period - skipping watchtime conversion")
                return {'status': 'no_active_period', 'conversions': 0}

            conversions = []

            with self.engine.begin() as conn:
                # Get all users with watchtime for this server and their Discord IDs from links table
                # Use LOWER() for case-insensitive comparison
                result = conn.execute(text("""
                    SELECT
                        w.username as kick_name,
                        w.minutes as total_minutes,
                        l.discord_id
                    FROM watchtime w
                    JOIN links l ON LOWER(l.kick_name) = LOWER(w.username)
                    WHERE w.minutes > 0 AND w.discord_server_id = :server_id
                """), {"server_id": self.discord_server_id})

                users = list(result)

                print(f"🔍 [WATCHTIME] Found {len(users)} linked users with watchtime")

                if not users:
                    logger.info("No linked users with watchtime found")
                    return {'status': 'no_users', 'conversions': 0}

                for kick_name, total_minutes, discord_id in users:
                    # Check how much watchtime has already been converted this period for this server
                    converted_result = conn.execute(text("""
                        SELECT COALESCE(SUM(minutes_converted), 0)
                        FROM raffle_watchtime_converted
                        WHERE period_id = :period_id AND kick_name = :kick_name AND discord_server_id = :server_id
                    """), {
                        'period_id': period_id,
                        'kick_name': kick_name,
                        'server_id': self.discord_server_id
                    })

                    minutes_already_converted = converted_result.scalar() or 0

                    # Calculate new minutes to convert
                    new_minutes = total_minutes - minutes_already_converted

                    print(f"🔍 [WATCHTIME] {kick_name}: {total_minutes} total - {minutes_already_converted} converted = {new_minutes} new")

                    if new_minutes < 60:
                        # Need at least 1 hour to convert
                        continue

                    # Convert to tickets (floor to whole hours)
                    hours_to_convert = new_minutes // 60
                    minutes_to_convert = hours_to_convert * 60
                    tickets_to_award = hours_to_convert * WATCHTIME_TICKETS_PER_HOUR

                    if tickets_to_award == 0:
                        continue

                    # Award the tickets
                    success = self.ticket_manager.award_tickets(
                        discord_id=discord_id,
                        kick_name=kick_name,
                        tickets=tickets_to_award,
                        source='watchtime',
                        description=f"Converted {hours_to_convert}h watchtime to {tickets_to_award} tickets",
                        period_id=period_id
                    )

                    if success:
                        # Log the conversion to prevent double-counting for this server
                        conn.execute(text("""
                            INSERT INTO raffle_watchtime_converted
                                (period_id, kick_name, minutes_converted, tickets_awarded, discord_server_id)
                            VALUES
                                (:period_id, :kick_name, :minutes, :tickets, :server_id)
                        """), {
                            'period_id': period_id,
                            'kick_name': kick_name,
                            'minutes': minutes_to_convert,
                            'tickets': tickets_to_award,
                            'server_id': self.discord_server_id
                        })

                        conversions.append({
                            'kick_name': kick_name,
                            'discord_id': discord_id,
                            'hours_converted': hours_to_convert,
                            'tickets_awarded': tickets_to_award
                        })

                        logger.info(f"✅ Converted {hours_to_convert}h watchtime → {tickets_to_award} tickets for {kick_name}")

            return {
                'status': 'success',
                'conversions': len(conversions),
                'details': conversions
            }

        except Exception as e:
            logger.error(f"Failed to convert watchtime to tickets: {e}")
            return {'status': 'error', 'error': str(e), 'conversions': 0}

    def get_unconverted_watchtime(self, kick_name, period_id=None):
        """
        Get how much watchtime a user has that hasn't been converted yet

        Args:
            kick_name: Kick username
            period_id: Raffle period ID (None = current active period)

        Returns:
            dict: Unconverted watchtime info or None
        """
        try:
            if period_id is None:
                period_id = self._get_active_period_id()
                if not period_id:
                    return None

            with self.engine.begin() as conn:
                # Get total watchtime
                watchtime_result = conn.execute(text("""
                    SELECT minutes FROM watchtime
                    WHERE username = :kick_name
                """), {'kick_name': kick_name})

                row = watchtime_result.fetchone()
                if not row:
                    return None

                total_minutes = row[0]

                # Get converted watchtime
                converted_result = conn.execute(text("""
                    SELECT COALESCE(SUM(minutes_converted), 0)
                    FROM raffle_watchtime_converted
                    WHERE period_id = :period_id AND kick_name = :kick_name
                """), {
                    'period_id': period_id,
                    'kick_name': kick_name
                })

                minutes_converted = converted_result.scalar() or 0

                # Calculate unconverted
                unconverted_minutes = total_minutes - minutes_converted
                convertible_hours = unconverted_minutes // 60
                potential_tickets = convertible_hours * WATCHTIME_TICKETS_PER_HOUR

                return {
                    'kick_name': kick_name,
                    'total_minutes': total_minutes,
                    'converted_minutes': minutes_converted,
                    'unconverted_minutes': unconverted_minutes,
                    'convertible_hours': convertible_hours,
                    'potential_tickets': potential_tickets
                }

        except Exception as e:
            logger.error(f"Failed to get unconverted watchtime: {e}")
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

async def setup_watchtime_converter(bot, engine):
    """
    Setup the watchtime converter as a Discord bot task

    Args:
        bot: Discord bot instance
        engine: SQLAlchemy engine
    """
    from discord.ext import tasks

    converter = WatchtimeConverter(engine)

    @tasks.loop(minutes=10)  # Run every 10 minutes
    async def convert_watchtime_task():
        """Periodic task to convert watchtime to tickets"""
        print("🔄 [WATCHTIME] Running watchtime → tickets conversion...")
        logger.info("🔄 Running watchtime → tickets conversion...")
        result = await converter.convert_watchtime_to_tickets()

        print(f"🔄 [WATCHTIME] Result: {result}")

        if result['status'] == 'success' and result['conversions'] > 0:
            print(f"✅ [WATCHTIME] Converted watchtime for {result['conversions']} users")
            logger.info(f"✅ Converted watchtime for {result['conversions']} users")
        elif result['status'] == 'no_users':
            print(f"ℹ️ [WATCHTIME] No users with 60+ minutes of unconverted watchtime")
        elif result['status'] == 'no_active_period':
            print(f"⚠️ [WATCHTIME] No active raffle period found!")

            # Optional: Send notification to raffle announcement channel
            # You can uncomment this if you want Discord notifications
            # channel_id = os.getenv("RAFFLE_ANNOUNCEMENT_CHANNEL_ID")
            # if channel_id:
            #     channel = bot.get_channel(int(channel_id))
            #     if channel:
            #         summary = "\n".join([
            #             f"• {d['kick_name']}: {d['hours_converted']}h → {d['tickets_awarded']} tickets"
            #             for d in result['details'][:5]  # Show first 5
            #         ])
            #         await channel.send(f"🎟️ **Watchtime Converted**\n{summary}")

        elif result['status'] == 'no_active_period':
            logger.debug("No active raffle period")
        elif result['status'] == 'error':
            logger.error(f"Watchtime conversion failed: {result.get('error')}")

    @convert_watchtime_task.before_loop
    async def before_convert_watchtime():
        """Wait for bot to be ready before starting the task"""
        await bot.wait_until_ready()
        logger.info("✅ Watchtime converter task started (runs every 10 minutes)")

    # Start the task
    convert_watchtime_task.start()

    return converter
