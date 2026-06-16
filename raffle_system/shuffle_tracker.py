"""
Multi-Platform Wager Tracker
Polls gambling affiliate APIs (Shuffle, Stake, etc.) and awards raffle tickets based on wager amounts

Settings loaded from database (bot_settings table) with env var fallbacks:
- wager_affiliate_url / WAGER_AFFILIATE_URL: Your affiliate stats API URL
- wager_campaign_code / WAGER_CAMPAIGN_CODE: Your affiliate/referral code to track
- wager_tickets_per_1000 / WAGER_TICKETS_PER_1000_USD: Tickets to award per $1000 wagered
"""

import asyncio
import logging
import os
from datetime import datetime

import aiohttp
from sqlalchemy import text

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

        logger.info(f"[Shuffle Tracker] 🎰 Initialized for platform: {self.platform_name}")
        # Show campaign codes (supports comma-separated multiple codes)
        codes = [c.strip() for c in self.campaign_code.split(",")]
        if len(codes) > 1:
            logger.info(f"[Shuffle Tracker] 📊 Campaign codes ({len(codes)}): {', '.join(codes)}")
        else:
            logger.info(f"[Shuffle Tracker] 📊 Campaign code: {self.campaign_code}")
        logger.info(f"[Shuffle Tracker] 🎫 Rate: {self.tickets_per_1000} tickets per $1000 wagered")
        if self.affiliate_url:
            logger.info(f"[Shuffle Tracker] 🔗 Affiliate URL configured: {self.affiliate_url[:50]}...")
        else:
            logger.info(f"[Shuffle Tracker] ⚠️ No affiliate URL configured!")

    # Default howl affiliate leaderboard endpoint (overridable per-server).
    HOWL_DEFAULT_LB_URL = "https://howl.gg/api/user/affiliate/lb"

    def _load_settings(self):
        """Load wager settings from bot_settings (database) or environment variables.

        The active affiliate is the server's `wager_platform_name` (single-select
        in Profile Settings). Because this runs before EVERY poll (refresh_settings)
        and on every dashboard settings save, switching the platform hot-swaps the
        SAME tracker object to the other API — no restart, no second tracker.
        """
        if self.bot_settings:
            # Refresh to get latest values
            self.bot_settings.refresh()

            platform = (self.bot_settings.get("wager_platform_name") or "shuffle").strip().lower()
            self.platform_name = platform

            if platform == "howl":
                self.howl_api_key = self.bot_settings.get("howl_api_key") or ""
                self.affiliate_url = self.bot_settings.get("howl_affiliate_url") or self.HOWL_DEFAULT_LB_URL
                self.campaign_code = self.bot_settings.get("howl_campaign_code") or ""
                # Reuse the shared ticket rate (no separate howl rate setting yet).
                self.tickets_per_1000 = self.bot_settings.shuffle_tickets_per_1000 or 20
            else:
                self.howl_api_key = ""
                self.affiliate_url = self.bot_settings.shuffle_affiliate_url or ""
                self.campaign_code = self.bot_settings.shuffle_campaign_code or "lele"
                self.tickets_per_1000 = self.bot_settings.shuffle_tickets_per_1000 or 20
        else:
            # Fallback to environment variables
            self.platform_name = os.getenv("WAGER_PLATFORM_NAME", "shuffle").lower()
            if self.platform_name == "howl":
                self.howl_api_key = os.getenv("HOWL_API_KEY", "")
                self.affiliate_url = os.getenv("HOWL_AFFILIATE_URL") or self.HOWL_DEFAULT_LB_URL
                self.campaign_code = os.getenv("HOWL_CAMPAIGN_CODE", "")
                self.tickets_per_1000 = int(os.getenv("WAGER_TICKETS_PER_1000_USD", "20"))
            else:
                self.howl_api_key = ""
                self.affiliate_url = os.getenv("WAGER_AFFILIATE_URL") or os.getenv("SHUFFLE_AFFILIATE_URL", "")
                self.campaign_code = os.getenv("WAGER_CAMPAIGN_CODE") or os.getenv("SHUFFLE_CAMPAIGN_CODE", "lele")
                self.tickets_per_1000 = int(os.getenv("WAGER_TICKETS_PER_1000_USD", "20"))

    def refresh_settings(self):
        """Reload settings from database"""
        self._load_settings()
        codes = [c.strip() for c in self.campaign_code.split(",")]
        codes_str = f"{len(codes)} codes" if len(codes) > 1 else self.campaign_code
        logger.info(f"[Shuffle Tracker] 🔄 Settings refreshed - URL: {bool(self.affiliate_url)}, Codes: {codes_str}")

    def _record_wager_history(self, conn, shuffle_username, total_wager_usd, wager_delta):
        """Append a row to shuffle_wager_history for the dashboard leaderboard.

        Only called when the tracker has detected a positive wager increase
        for a *known* user. The new-user onboarding path does NOT write
        history (those users haven't actually wagered anything on our watch
        yet — they came in already at some lifetime total).

        Each row stores:
          - total_wager_usd : the user's running cumulative total after this
                              update (useful for debugging / future audits)
          - wager_delta     : how much they wagered since the previous
                              observation. The leaderboard sums this column
                              across rows in [start, end) for each user.

        Wrapped in a nested transaction (SAVEPOINT) so an error here doesn't
        poison the surrounding wager-update transaction.
        """
        # Guard on the cent-rounded delta: a sub-cent residue (from comparing a
        # full-precision API value against the DECIMAL(15,2) stored wager) is > 0
        # but rounds to 0.00 in the wager_delta column, which would write a
        # meaningless $0.00 history row. Only record a genuine cent-or-more change.
        if not self.server_id or round(wager_delta, 2) <= 0:
            return

        try:
            with conn.begin_nested():  # per-user SAVEPOINT
                conn.execute(
                    text(
                        """
                        INSERT INTO shuffle_wager_history
                            (discord_server_id, shuffle_username, total_wager_usd, wager_delta)
                        VALUES
                            (:server_id, :username, :total, :delta)
                        """
                    ),
                    {
                        "server_id": self.server_id,
                        "username": shuffle_username,
                        "total": total_wager_usd,
                        "delta": wager_delta,
                    },
                )
        except Exception as e:
            logger.info(
                f"[Shuffle Tracker] ❌ shuffle_wager_history append failed "
                f"for server={self.server_id}, user={shuffle_username}: "
                f"{type(e).__name__}: {e}"
            )
            return

        # Publish to the dashboard's live "recent wagers" feed. This is the single
        # chokepoint for a real (cent-or-more) committed wager delta, so it covers
        # every update branch. Best-effort: a publish failure never affects ingestion.
        try:
            from utils.redis_publisher import bot_redis_publisher

            bot_redis_publisher.publish_wager(
                discord_server_id=str(self.server_id),
                shuffle_username=shuffle_username,
                kick_name=None,
                platform=self.platform_name,
                wager_delta=round(wager_delta, 2),
                total_wager_usd=round(total_wager_usd, 2) if total_wager_usd is not None else None,
            )
        except Exception as pub_err:
            logger.info(f"[Shuffle Tracker] wager publish failed: {pub_err}")

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
                return {"status": "no_active_period", "updates": 0}

            # Fetch current wager data from platform
            wager_data = await self._fetch_shuffle_data()

            if not wager_data:
                logger.error(f"Failed to fetch {self.platform_name} affiliate data")
                return {"status": "fetch_failed", "updates": 0}

            # Filter for campaign code(s) - supports multiple codes separated by comma.
            # Howl's affiliate API already returns ONLY your affiliates and has no
            # per-row campaign code to match on, so the campaign filter is both
            # meaningless and (with an empty howl_campaign_code) would drop every
            # row. Bypass it for howl; shuffle keeps the existing filter.
            if self.platform_name == "howl":
                filtered_data = wager_data
            else:
                campaign_codes = [code.strip().lower() for code in self.campaign_code.split(",")]
                filtered_data = [user for user in wager_data if user.get("campaignCode", "").lower() in campaign_codes]

            if not filtered_data:
                logger.warning(f"No users found with campaign codes '{self.campaign_code}' on {self.platform_name}")
                return {"status": "no_users", "updates": 0}

            logger.info(
                f"Found {len(filtered_data)} users with campaign codes '{self.campaign_code}' on {self.platform_name}"
            )

            updates = []
            tickets_to_award = []  # Store ticket awards to process after wager updates

            with self.engine.begin() as conn:
                for user_data in filtered_data:
                    shuffle_username = user_data.get("username")
                    current_wager = float(user_data.get("wagerAmount", 0))

                    if not shuffle_username:
                        continue

                    # Get previous wager amount for this period
                    prev_result = conn.execute(
                        text(
                            """
                        SELECT
                            last_known_wager,
                            tickets_awarded,
                            discord_id,
                            kick_name
                        FROM raffle_shuffle_wagers
                        WHERE period_id = :period_id AND shuffle_username = :username
                          AND platform = :platform
                    """
                        ),
                        {"period_id": period_id, "username": shuffle_username, "platform": self.platform_name},
                    )

                    prev_row = prev_result.fetchone()

                    if prev_row:
                        # Existing user - check for wager increase
                        last_known_wager = float(prev_row[0])
                        total_tickets_awarded = prev_row[1]
                        discord_id = prev_row[2]
                        kick_name = prev_row[3]

                        # Calculate new wager since last check.
                        #
                        # The Shuffle API returns wagerAmount as a high-precision
                        # float (e.g. 116301.04286432), but raffle_shuffle_wagers
                        # stores last_known_wager as DECIMAL(15,2), so it reads back
                        # rounded to cents (116301.04). Subtracting the rounded stored
                        # value from the full-precision API value yields a tiny
                        # positive residue (~0.0028) on EVERY poll even when the user
                        # has not wagered. That residue is > 0 (so it slips past a
                        # naive guard) but rounds to 0.00 in the NUMERIC(15,2)
                        # wager_delta column — producing one phantom $0.00 history row
                        # per user per poll. Round the delta to cents and require a
                        # real change so only genuine wagering is recorded.
                        wager_delta = round(current_wager - last_known_wager, 2)

                        if wager_delta <= 0:
                            # No increase (or a sub-cent/decrease change, which we ignore)
                            continue

                        # Calculate tickets for the new wager amount
                        # $1000 = configured tickets per 1000 USD
                        new_tickets = int((wager_delta / 1000.0) * self.tickets_per_1000)

                        if new_tickets == 0:
                            # Less than threshold, update wager but no tickets
                            conn.execute(
                                text(
                                    """
                                UPDATE raffle_shuffle_wagers
                                SET
                                    last_known_wager = :current_wager,
                                    total_wager_usd = :current_wager,
                                    last_checked = CURRENT_TIMESTAMP,
                                    last_updated = CURRENT_TIMESTAMP
                                WHERE period_id = :period_id AND shuffle_username = :username
                                  AND platform = :platform
                            """
                                ),
                                {
                                    "period_id": period_id,
                                    "username": shuffle_username,
                                    "current_wager": current_wager,
                                    "platform": self.platform_name,
                                },
                            )
                            self._record_wager_history(conn, shuffle_username, current_wager, wager_delta)
                            continue

                        # Award tickets if user is linked
                        if discord_id and kick_name:
                            # Queue ticket award to happen after wager update transaction
                            tickets_to_award.append(
                                {
                                    "discord_id": discord_id,
                                    "kick_name": kick_name,
                                    "tickets": new_tickets,
                                    "description": f"{self.platform_name.capitalize()} wager: ${wager_delta:.2f} (${last_known_wager:.2f} → ${current_wager:.2f})",
                                    "period_id": period_id,
                                    "shuffle_username": shuffle_username,
                                    "wager_delta": wager_delta,
                                    "current_wager": current_wager,
                                }
                            )

                            # Update wager tracking (will commit with transaction)
                            conn.execute(
                                text(
                                    """
                                UPDATE raffle_shuffle_wagers
                                SET
                                    last_known_wager = :current_wager,
                                    total_wager_usd = :current_wager,
                                    tickets_awarded = tickets_awarded + :new_tickets,
                                    last_checked = CURRENT_TIMESTAMP,
                                    last_updated = CURRENT_TIMESTAMP
                                WHERE period_id = :period_id AND shuffle_username = :username
                                  AND platform = :platform
                            """
                                ),
                                {
                                    "period_id": period_id,
                                    "username": shuffle_username,
                                    "current_wager": current_wager,
                                    "new_tickets": new_tickets,
                                    "platform": self.platform_name,
                                },
                            )
                            self._record_wager_history(conn, shuffle_username, current_wager, wager_delta)
                        else:
                            # User exists but not linked - just update wager
                            conn.execute(
                                text(
                                    """
                                UPDATE raffle_shuffle_wagers
                                SET
                                    last_known_wager = :current_wager,
                                    total_wager_usd = :current_wager,
                                    last_checked = CURRENT_TIMESTAMP,
                                    last_updated = CURRENT_TIMESTAMP
                                WHERE period_id = :period_id AND shuffle_username = :username
                                  AND platform = :platform
                            """
                                ),
                                {
                                    "period_id": period_id,
                                    "username": shuffle_username,
                                    "current_wager": current_wager,
                                    "platform": self.platform_name,
                                },
                            )
                            self._record_wager_history(conn, shuffle_username, current_wager, wager_delta)
                    else:
                        # New user - check if they're linked (scoped to THIS platform
                        # so a shuffle link can't match a howl wager username or vice-versa)
                        link_result = conn.execute(
                            text(
                                """
                            SELECT discord_id, kick_name FROM raffle_shuffle_links
                            WHERE shuffle_username = :username AND verified = TRUE
                              AND platform = :platform
                        """
                            ),
                            {"username": shuffle_username, "platform": self.platform_name},
                        )

                        link_row = link_result.fetchone()
                        discord_id = link_row[0] if link_row else None
                        kick_name = link_row[1] if link_row else None

                        # Create wager tracking entry
                        # Set last_known_wager = total_wager so only FUTURE wagers earn tickets
                        conn.execute(
                            text(
                                """
                            INSERT INTO raffle_shuffle_wagers
                                (period_id, shuffle_username, kick_name, discord_id,
                                 total_wager_usd, last_known_wager, tickets_awarded, platform)
                            VALUES
                                (:period_id, :username, :kick_name, :discord_id,
                                 :wager, :wager, 0, :platform)
                        """
                            ),
                            {
                                "period_id": period_id,
                                "username": shuffle_username,
                                "kick_name": kick_name,
                                "discord_id": discord_id,
                                "wager": current_wager,
                                "platform": self.platform_name,
                            },
                        )
                        # No history row for new-user onboarding: this user
                        # came in already at $current_wager from before we
                        # were tracking them. Their next observed change is
                        # what counts toward the leaderboard.

                        # No tickets awarded for initial/existing wagers
                        logger.info(
                            f"📊 Tracking new Shuffle user: {shuffle_username} (${current_wager:.2f}) - "
                            f"{'Linked to ' + kick_name if kick_name else 'Not linked'}"
                        )

            # Wager transaction is complete, now award tickets in separate transactions
            for award in tickets_to_award:
                try:
                    success = self.ticket_manager.award_tickets(
                        discord_id=award["discord_id"],
                        kick_name=award["kick_name"],
                        tickets=award["tickets"],
                        source="shuffle_wager",
                        description=award["description"],
                        period_id=award["period_id"],
                    )

                    if success:
                        updates.append(
                            {
                                "shuffle_username": award["shuffle_username"],
                                "kick_name": award["kick_name"],
                                "wager_delta": award["wager_delta"],
                                "tickets_awarded": award["tickets"],
                                "total_wager": award["current_wager"],
                            }
                        )
                        logger.info(
                            f"💰 {award['kick_name']} ({award['shuffle_username']}): "
                            f"${award['wager_delta']:.2f} wagered → {award['tickets']} tickets"
                        )
                    else:
                        logger.error(f"Failed to award {award['tickets']} tickets to {award['kick_name']}")
                except Exception as e:
                    logger.error(f"Error awarding tickets to {award['kick_name']}: {e}")

            return {"status": "success", "updates": len(updates), "details": updates}

        except Exception as e:
            logger.error(f"Failed to update Shuffle wagers: {e}")
            import traceback

            traceback.print_exc()
            return {"status": "error", "error": str(e), "updates": 0}

    def _get_active_period_id(self):
        """Get the ID of the currently active raffle period"""
        try:
            with self.engine.begin() as conn:
                if self.server_id:
                    # Multiserver: filter by discord_server_id
                    result = conn.execute(
                        text(
                            """
                        SELECT id FROM raffle_periods
                        WHERE status = 'active' AND discord_server_id = :sid
                        ORDER BY start_date DESC
                        LIMIT 1
                    """
                        ),
                        {"sid": self.server_id},
                    )
                else:
                    # Backwards compatible: no server filter
                    result = conn.execute(
                        text(
                            """
                        SELECT id FROM raffle_periods
                        WHERE status = 'active'
                        ORDER BY start_date DESC
                        LIMIT 1
                    """
                        )
                    )
                row = result.fetchone()
                return row[0] if row else None
        except Exception as e:
            logger.error(f"Failed to get active period: {e}")
            return None

    def _normalize_rows(self, raw):
        """Normalize a platform's raw affiliate response into the row shape the
        update loop consumes: dicts with `username`, `wagerAmount`, `campaignCode`.

        - Shuffle: a bare JSON list already in that shape — passed through.
        - Howl: `{success, data:[{name, wageredUSD, userId, ...}]}` (see
          leaderboard-howl-data.md). `name`→username, `wageredUSD`→wagerAmount.
          Howl rows carry no per-row campaign code, so we stamp the configured
          one (or "*") so the existing campaign-code filter passes — howl scopes
          by API params/account, not per-row matching.
        """
        if self.platform_name == "howl":
            if not isinstance(raw, dict) or not raw.get("success"):
                logger.error(f"Unexpected howl API response: {str(raw)[:200]}")
                return None
            rows = raw.get("data") or []
            stamp = self.campaign_code.split(",")[0].strip().lower() if self.campaign_code else "*"
            normalized = []
            for r in rows:
                name = r.get("name")
                if not name:
                    continue
                normalized.append(
                    {
                        "username": name,
                        "wagerAmount": r.get("wageredUSD", 0),
                        "campaignCode": stamp,
                    }
                )
            return normalized

        # Shuffle (and other bare-list platforms)
        if not isinstance(raw, list):
            logger.error(f"Unexpected {self.platform_name} API response format: {type(raw)}")
            return None
        return raw

    async def _fetch_shuffle_data(self):
        """
        Fetch wager data from the active platform's affiliate API and normalize it.

        Returns:
            list: Array of normalized user wager objects, or None on failure.
        """
        headers = {}
        params = None
        if self.platform_name == "howl":
            if not self.howl_api_key:
                logger.error("Howl selected but no howl_api_key configured")
                return None
            # Howl requires an Authorization header (raw key) and a date window.
            # We query the current calendar month: howl returns a *period total*
            # for [from, to). Within a month this grows monotonically, so the
            # tracker's `current - last_known` delta works exactly like Shuffle's
            # lifetime total. At a month rollover the period total drops, making
            # the delta <= 0 → the row is skipped (no negative tickets) — safe.
            headers["Authorization"] = self.howl_api_key
            now = datetime.utcnow()
            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            params = {
                "from": month_start.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                "to": now.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                "limit": "1000",
            }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.affiliate_url, headers=headers, params=params, timeout=30) as response:
                    if response.status != 200:
                        logger.error(f"{self.platform_name.capitalize()} API returned status {response.status}")
                        return None

                    data = await response.json()
                    return self._normalize_rows(data)

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
                # Check if shuffle username already linked.
                # Scoped to platform='shuffle' so a user's howl link (now allowed
                # to coexist via UNIQUE(shuffle_username, platform)) doesn't make
                # this report a false "already linked".
                existing = conn.execute(
                    text(
                        """
                    SELECT discord_id, kick_name FROM raffle_shuffle_links
                    WHERE shuffle_username = :username AND platform = 'shuffle'
                """
                    ),
                    {"username": shuffle_username},
                )

                existing_row = existing.fetchone()

                if existing_row:
                    return {
                        "status": "already_linked",
                        "existing_discord_id": existing_row[0],
                        "existing_kick_name": existing_row[1],
                    }

                # Check if discord_id already has a shuffle link (scoped to
                # platform='shuffle' — a user may also hold a howl link under
                # UNIQUE(discord_id, platform); that must not block this).
                discord_check = conn.execute(
                    text(
                        """
                    SELECT shuffle_username FROM raffle_shuffle_links
                    WHERE discord_id = :discord_id AND platform = 'shuffle'
                """
                    ),
                    {"discord_id": discord_id},
                )

                discord_row = discord_check.fetchone()

                if discord_row:
                    return {"status": "discord_already_linked", "existing_shuffle_username": discord_row[0]}

                # Create the link (platform explicit for clarity, though the
                # column also defaults to 'shuffle')
                conn.execute(
                    text(
                        """
                    INSERT INTO raffle_shuffle_links
                        (shuffle_username, kick_name, discord_id, platform, verified, verified_by_discord_id, verified_at)
                    VALUES
                        (:shuffle_username, :kick_name, :discord_id, 'shuffle', :verified, :verified_by,
                         CASE WHEN :verified THEN CURRENT_TIMESTAMP ELSE NULL END)
                """
                    ),
                    {
                        "shuffle_username": shuffle_username,
                        "kick_name": kick_name,
                        "discord_id": discord_id,
                        "verified": verified,
                        "verified_by": verified_by,
                    },
                )

            logger.info(
                f"🔗 Linked Shuffle account: {shuffle_username} → {kick_name} (Discord: {discord_id}, verified: {verified})"
            )

            return {
                "status": "success",
                "shuffle_username": shuffle_username,
                "kick_name": kick_name,
                "discord_id": discord_id,
                "verified": verified,
            }

        except Exception as e:
            logger.error(f"Failed to link Shuffle account: {e}")
            return {"status": "error", "error": str(e)}

    def _get_active_period_id(self):
        """Get the ID of the currently active raffle period"""
        try:
            with self.engine.begin() as conn:
                if self.server_id is not None:
                    result = conn.execute(
                        text(
                            """
                        SELECT id FROM raffle_periods
                        WHERE status = 'active' AND discord_server_id = :server_id
                        ORDER BY start_date DESC
                        LIMIT 1
                    """
                        ),
                        {"server_id": self.server_id},
                    )
                else:
                    result = conn.execute(
                        text(
                            """
                        SELECT id FROM raffle_periods
                        WHERE status = 'active'
                        ORDER BY start_date DESC
                        LIMIT 1
                    """
                        )
                    )
                row = result.fetchone()
                return row[0] if row else None
        except Exception as e:
            logger.error(f"Failed to get active period: {e}")
            return None


async def setup_shuffle_tracker(bot, engine, server_id=None, bot_settings=None):
    """
    Setup the Shuffle wager tracker as a Discord bot task

    Args:
        bot: Discord bot instance
        engine: SQLAlchemy engine
        server_id: Discord server/guild ID for multi-server support (optional)
        bot_settings: Guild-specific bot settings manager (optional)
    """
    from discord.ext import tasks

    tracker = ShuffleWagerTracker(engine, bot_settings=bot_settings, server_id=server_id)

    @tasks.loop(minutes=15)  # Run every 15 minutes
    async def update_shuffle_task():
        """Periodic task to update Shuffle wagers and award tickets"""
        try:
            # Refresh settings before each update to get latest from database
            tracker.refresh_settings()

            if not tracker.affiliate_url:
                logger.info("[Shuffle Tracker] ⚠️ No affiliate URL configured - skipping update")
                return

            logger.info("[Shuffle Tracker] 🔄 Checking wagers...")
            result = await tracker.update_shuffle_wagers()

            if result["status"] == "success" and result["updates"] > 0:
                logger.info(f"[Shuffle Tracker] ✅ Updated {result['updates']} wager(s)")
                # Print details of each update
                for detail in result.get("details", []):
                    logger.info(
                        f"  💰 {detail['kick_name']} ({detail['shuffle_username']}): "
                        f"${detail['wager_delta']:.2f} → +{detail['tickets_awarded']} tickets"
                    )
            elif result["status"] == "success":
                logger.info(f"[Shuffle Tracker] ℹ️ No new wagers found")
            elif result["status"] == "no_active_period":
                logger.info("[Shuffle Tracker] ⏸️ No active raffle period")
            elif result["status"] == "no_users":
                logger.info(f"[Shuffle Tracker] ℹ️ No users found with campaign code(s): {tracker.campaign_code}")
            elif result["status"] == "fetch_failed":
                logger.info(f"[Shuffle Tracker] ❌ Failed to fetch data from affiliate URL")
            elif result["status"] == "error":
                logger.info(f"[Shuffle Tracker] ❌ Update failed: {result.get('error')}")
        except Exception as e:
            logger.info(f"[Shuffle Tracker] ❌ Task error: {e}")
            import traceback

            traceback.print_exc()

    @update_shuffle_task.before_loop
    async def before_shuffle_task():
        """Wait for bot to be ready before starting the task"""
        await bot.wait_until_ready()
        logger.info("[Shuffle Tracker] ✅ Started (runs every 15 minutes)")

    # Start the task
    update_shuffle_task.start()

    return tracker
