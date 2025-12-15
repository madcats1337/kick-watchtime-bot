"""
Multi-Platform Wager Tracker
Polls gambling affiliate APIs (Shuffle, Stake, etc.) and awards raffle tickets based on wager amounts

Settings loaded from database (bot_settings table) with env var fallbacks:
- wager_affiliate_url / WAGER_AFFILIATE_URL: Your affiliate stats API URL
- wager_campaign_code / WAGER_CAMPAIGN_CODE: Your affiliate/referral code to track
- wager_tickets_per_1000 / WAGER_TICKETS_PER_1000_USD: Tickets to award per $1000 wagered
"""

from sqlalchemy import text
from datetime import datetime
import logging
import aiohttp
import asyncio
import os

from .tickets import TicketManager

logger = logging.getLogger(__name__)

class ShuffleWagerTracker:
    """
    Tracks gambling platform wagers and awards raffle tickets

    Despite the class name, this now supports multiple platforms (Shuffle, Stake, Stake.us, etc.)
    Settings are loaded from database (bot_settings) with env var fallbacks.
    """

    def __init__(self, engine, bot_settings=None, server_id=None):
        self.engine = engine
        self.server_id = server_id
        self.ticket_manager = TicketManager(engine, server_id=server_id)
        self.bot_settings = bot_settings

        # Load settings from bot_settings (database) or fall back to env vars
        self._load_settings()

        print(f"[Shuffle Tracker] 🎰 Initialized for platform: {self.platform_name}")
        # Show campaign codes (supports comma-separated multiple codes)
        codes = [c.strip() for c in self.campaign_code.split(',')]
        if len(codes) > 1:
            print(f"[Shuffle Tracker] 📊 Campaign codes ({len(codes)}): {', '.join(codes)}")
        else:
            print(f"[Shuffle Tracker] 📊 Campaign code: {self.campaign_code}")
        print(f"[Shuffle Tracker] 🎫 Rate: {self.tickets_per_1000} tickets per $1000 wagered")
        if self.affiliate_url:
            print(f"[Shuffle Tracker] 🔗 Affiliate URL configured: {self.affiliate_url[:50]}...")
        else:
            print(f"[Shuffle Tracker] ⚠️ No affiliate URL configured!")

    def _load_settings(self):
        """Load wager settings from bot_settings (database) or environment variables"""
        if self.bot_settings:
            # Refresh to get latest values
            self.bot_settings.refresh()

            self.affiliate_url = self.bot_settings.shuffle_affiliate_url or ''
            self.campaign_code = self.bot_settings.shuffle_campaign_code or 'lele'
            self.tickets_per_1000 = self.bot_settings.shuffle_tickets_per_1000 or 20
            self.platform_name = self.bot_settings.get('wager_platform_name') or 'shuffle'
        else:
            # Fallback to environment variables
            self.affiliate_url = os.getenv("WAGER_AFFILIATE_URL") or os.getenv("SHUFFLE_AFFILIATE_URL", "")
            self.campaign_code = os.getenv("WAGER_CAMPAIGN_CODE") or os.getenv("SHUFFLE_CAMPAIGN_CODE", "lele")
            self.tickets_per_1000 = int(os.getenv("WAGER_TICKETS_PER_1000_USD", "20"))
            self.platform_name = os.getenv("WAGER_PLATFORM_NAME", "shuffle").lower()

    def refresh_settings(self):
        """Reload settings from database"""
        self._load_settings()
        codes = [c.strip() for c in self.campaign_code.split(',')]
        codes_str = f"{len(codes)} codes" if len(codes) > 1 else self.campaign_code
        print(f"[Shuffle Tracker] 🔄 Settings refreshed - URL: {bool(self.affiliate_url)}, Codes: {codes_str}")

    async def update_shuffle_wagers(self):
        """
        Poll gambling platform affiliate API and update wager tracking

        Fetches the latest wager data from the configured affiliate page,
        compares with previous values, and awards tickets for new wagers.

        Returns:
            dict: Summary of updates performed
        """
        try:
            # Get active raffle period
            period_id = self._get_active_period_id()
            if not period_id:
                logger.warning(f"No active raffle period - skipping {self.platform_name} wager update")
                return {'status': 'no_active_period', 'updates': 0}

            # Fetch current wager data from platform
            wager_data = await self._fetch_shuffle_data()

            if not wager_data:
                logger.error(f"Failed to fetch {self.platform_name} affiliate data")
                return {'status': 'fetch_failed', 'updates': 0}

            # Filter for campaign code(s) - supports multiple codes separated by comma
            campaign_codes = [code.strip().lower() for code in self.campaign_code.split(',')]
            filtered_data = [
                user for user in wager_data
                if user.get('campaignCode', '').lower() in campaign_codes
            ]

            if not filtered_data:
                logger.warning(f"No users found with campaign codes '{self.campaign_code}' on {self.platform_name}")
                return {'status': 'no_users', 'updates': 0}

            logger.info(f"Found {len(filtered_data)} users with campaign codes '{self.campaign_code}' on {self.platform_name}")

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
                        # $1000 = configured tickets per 1000 USD
                        new_tickets = int((wager_delta / 1000.0) * self.tickets_per_1000)

                        if new_tickets == 0:
                            # Less than threshold, update wager but no tickets
                            conn.execute(text("""
                                UPDATE raffle_shuffle_wagers
                                SET
                                    last_known_wager = :current_wager,
                                    total_wager_usd = :current_wager,
                                    last_checked = CURRENT_TIMESTAMP,
                                    last_updated = CURRENT_TIMESTAMP
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
                                source='shuffle_wager',  # Keep source name for backwards compatibility
                                description=f"{self.platform_name.capitalize()} wager: ${wager_delta:.2f} (${last_known_wager:.2f} → ${current_wager:.2f})",
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
                                    last_checked = CURRENT_TIMESTAMP,
                                    last_updated = CURRENT_TIMESTAMP
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
                                 total_wager_usd, last_known_wager, tickets_awarded, platform)
                            VALUES
                                (:period_id, :username, :kick_name, :discord_id,
                                 :wager, :wager, 0, :platform)
                        """), {
                            'period_id': period_id,
                            'username': shuffle_username,
                            'kick_name': kick_name,
                            'discord_id': discord_id,
                            'wager': current_wager,
                            'platform': self.platform_name
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

    def _get_active_period_id(self):
        """Get the ID of the currently active raffle period"""
        try:
            with self.engine.begin() as conn:
                if self.server_id:
                    # Multiserver: filter by discord_server_id
                    result = conn.execute(text("""
                        SELECT id FROM raffle_periods
                        WHERE status = 'active' AND discord_server_id = :sid
                        ORDER BY start_date DESC
                        LIMIT 1
                    """), {"sid": self.server_id})
                else:
                    # Backwards compatible: no server filter
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

    async def _fetch_shuffle_data(self):
        """
        Fetch wager data from gambling platform affiliate page

        Returns:
            list: Array of user wager objects or None on failure
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.affiliate_url, timeout=30) as response:
                    if response.status != 200:
                        logger.error(f"{self.platform_name.capitalize()} API returned status {response.status}")
                        return None

                    # The page returns JSON array directly
                    data = await response.json()

                    if not isinstance(data, list):
                        logger.error(f"Unexpected {self.platform_name} API response format: {type(data)}")
                        return None

                    return data

        except asyncio.TimeoutError:
            logger.error(f"Timeout fetching {self.platform_name} affiliate data")
            return None
        except Exception as e:
            logger.error(f"Error fetching {self.platform_name} data: {e}")
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

async def setup_shuffle_tracker(bot, engine, server_id=None):
    """
    Setup the Shuffle wager tracker as a Discord bot task

    Args:
        bot: Discord bot instance
        engine: SQLAlchemy engine
        server_id: Discord server/guild ID for multi-server support (optional)
    """
    from discord.ext import tasks

    # Get bot_settings from bot if available
    bot_settings = None
    if hasattr(bot, 'settings_manager') and bot.settings_manager:
        bot_settings = bot.settings_manager

    tracker = ShuffleWagerTracker(engine, bot_settings=bot_settings, server_id=server_id)

    @tasks.loop(minutes=15)  # Run every 15 minutes
    async def update_shuffle_task():
        """Periodic task to update Shuffle wagers and award tickets"""
        # Refresh settings before each update to get latest from database
        tracker.refresh_settings()

        if not tracker.affiliate_url:
            print("[Shuffle Tracker] ⚠️ No affiliate URL configured - skipping update")
            return

        print("[Shuffle Tracker] 🔄 Checking wagers...")
        result = await tracker.update_shuffle_wagers()

        if result['status'] == 'success' and result['updates'] > 0:
            print(f"[Shuffle Tracker] ✅ Updated {result['updates']} wager(s)")
        elif result['status'] == 'no_active_period':
            print("[Shuffle Tracker] ⏸️ No active raffle period")
        elif result['status'] == 'error':
            print(f"[Shuffle Tracker] ❌ Update failed: {result.get('error')}")

    @update_shuffle_task.before_loop
    async def before_shuffle_task():
        """Wait for bot to be ready before starting the task"""
        await bot.wait_until_ready()
        print("[Shuffle Tracker] ✅ Started (runs every 15 minutes)")

    # Start the task
    update_shuffle_task.start()

    return tracker
