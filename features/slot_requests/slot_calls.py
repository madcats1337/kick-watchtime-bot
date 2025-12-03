"""
Slot Call Tracker - Monitor Kick chat for !call commands and post to Discord
"""

import logging
import re
from datetime import datetime, timedelta
from typing import Optional, Dict
import discord
from discord.ext import commands
from sqlalchemy import text

logger = logging.getLogger(__name__)

class SlotCallTracker:
    """Track slot calls from Kick chat and post to Discord"""

    def __init__(self, bot, discord_channel_id: Optional[int] = None, kick_send_callback=None, engine=None):
        self.bot = bot
        self.discord_channel_id = discord_channel_id
        self.engine = engine
        self.last_call_time: Dict[str, datetime] = {}  # Track per-user cooldown
        self.cooldown_seconds = 30  # Default 30 second cooldown per user (loaded from DB)
        self.max_username_length = 50  # Maximum username length
        self.max_slot_call_length = 200  # Maximum slot call text length
        self.kick_send_callback = kick_send_callback  # Callback to send messages to Kick chat
        self.panel = None  # Reference to SlotRequestPanel (set externally)

        # Initialize database and load enabled state
        self._init_database()
        self.enabled = self._load_enabled_state()
        self.max_requests_per_user = self._load_max_requests()
        self.cooldown_seconds = self._load_cooldown()  # Load from database

    def _init_database(self):
        """Create feature_settings and slot_requests tables if they don't exist"""
        if not self.engine:
            logger.warning("No database engine provided - slot call state won't persist")
            return

        try:
            with self.engine.begin() as conn:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS feature_settings (
                        feature_name TEXT PRIMARY KEY,
                        enabled BOOLEAN NOT NULL DEFAULT TRUE,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """))

                # Create slot_requests table to store all slot requests
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS slot_requests (
                        id SERIAL PRIMARY KEY,
                        kick_username TEXT NOT NULL,
                        slot_call TEXT NOT NULL,
                        requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        picked BOOLEAN DEFAULT FALSE,
                        picked_at TIMESTAMP
                    )
                """))

                # Add performance index for requested_at ordering
                conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_slot_requests_requested_at
                    ON slot_requests(requested_at DESC)
                """))
            logger.info("Slot call tables initialized")
        except Exception as e:
            logger.error(f"Failed to initialize slot call tables: {e}")

    def _load_enabled_state(self) -> bool:
        """Load enabled state from database, default to True if not found"""
        if not self.engine:
            return True  # Default to enabled if no database

        try:
            with self.engine.connect() as conn:
                result = conn.execute(text("""
                    SELECT enabled FROM feature_settings
                    WHERE feature_name = 'slot_calls'
                """)).fetchone()

                if result:
                    enabled = result[0]
                    logger.info(f"Loaded slot call state from database: {'enabled' if enabled else 'disabled'}")
                    return enabled
                else:
                    # First time - set default to enabled
                    with self.engine.begin() as conn:
                        conn.execute(text("""
                            INSERT INTO feature_settings (feature_name, enabled)
                            VALUES ('slot_calls', TRUE)
                        """))
                    logger.info("Initialized slot call state in database: enabled")
                    return True
        except Exception as e:
            logger.error(f"Failed to load slot call state from database: {e}")
            return True  # Default to enabled on error

    def _load_max_requests(self) -> int:
        """Load max requests per user from database, default to 0 (unlimited)"""
        if not self.engine:
            return 0  # 0 = unlimited

        try:
            with self.engine.connect() as conn:
                result = conn.execute(text("""
                    SELECT value FROM bot_settings
                    WHERE key = 'slot_max_requests_per_user'
                """)).fetchone()

                if result:
                    max_requests = int(result[0])
                    logger.info(f"Loaded max slot requests per user: {max_requests if max_requests > 0 else 'unlimited'}")
                    return max_requests
                else:
                    return 0  # Default to unlimited
        except Exception as e:
            logger.error(f"Failed to load max requests setting: {e}")
            return 0  # Default to unlimited on error

    def _load_cooldown(self) -> int:
        """Load cooldown seconds from database, default to 30"""
        if not self.engine:
            return 30  # Default 30 second cooldown

        try:
            with self.engine.connect() as conn:
                result = conn.execute(text("""
                    SELECT value FROM bot_settings
                    WHERE key = 'slot_request_cooldown_seconds'
                      AND (discord_server_id = :server_id OR discord_server_id IS NULL)
                    ORDER BY discord_server_id NULLS LAST
                    LIMIT 1
                """), {"server_id": self.bot.server_id if hasattr(self.bot, 'server_id') else None}).fetchone()

                if result and result[0]:
                    cooldown = int(result[0])
                    logger.info(f"Loaded slot request cooldown: {cooldown} seconds")
                    return cooldown if cooldown > 0 else 30  # Min 30 seconds
                else:
                    return 30  # Default to 30 seconds
        except Exception as e:
            logger.error(f"Failed to load cooldown setting: {e}")
            return 30  # Default to 30 seconds on error

    def set_max_requests(self, max_requests: int) -> bool:
        """Set maximum requests per user (0 = unlimited)"""
        if not self.engine:
            return False

        try:
            with self.engine.begin() as conn:
                conn.execute(text("""
                    INSERT INTO bot_settings (key, value)
                    VALUES ('slot_max_requests_per_user', :max_requests)
                    ON CONFLICT (key)
                    DO UPDATE SET value = :max_requests
                """), {"max_requests": str(max_requests)})

            self.max_requests_per_user = max_requests
            logger.info(f"Set max slot requests per user to: {max_requests if max_requests > 0 else 'unlimited'}")
            return True
        except Exception as e:
            logger.error(f"Failed to set max requests: {e}")
            return False

    def is_enabled(self) -> bool:
        """Check if slot call tracking is enabled"""
        return self.enabled

    async def set_enabled(self, enabled: bool):
        """Enable or disable slot call tracking and persist to database"""
        was_disabled = not self.enabled
        self.enabled = enabled
        logger.info(f"Slot call tracking {'enabled' if enabled else 'disabled'}")

        # Persist to database
        if self.engine:
            try:
                with self.engine.begin() as conn:
                    conn.execute(text("""
                        INSERT INTO feature_settings (feature_name, enabled, updated_at)
                        VALUES ('slot_calls', :enabled, CURRENT_TIMESTAMP)
                        ON CONFLICT (feature_name)
                        DO UPDATE SET enabled = :enabled, updated_at = CURRENT_TIMESTAMP
                    """), {"enabled": enabled})

                    # Clear slot requests table when enabled after being disabled
                    if enabled and was_disabled:
                        result = conn.execute(text("DELETE FROM slot_requests"))
                        deleted_count = result.rowcount
                        logger.info(f"Cleared {deleted_count} old slot requests (slot requests re-enabled)")

                logger.info(f"Persisted slot call state to database")
            except Exception as e:
                logger.error(f"Failed to persist slot call state to database: {e}")

        # Update panel if available
        if self.panel:
            try:
                await self.panel.update_panel()
                logger.info("Updated slot request panel after status change")
            except Exception as e:
                logger.error(f"Failed to update panel: {e}")

    async def handle_slot_call(self, kick_username: str, slot_call: str):
        """
        Handle a slot call from Kick chat

        Args:
            kick_username: Username from Kick chat
            slot_call: The slot call text (everything after !call)
        """
        # 🔒 SECURITY: Check if user is blacklisted (defensive check)
        if self.engine:
            try:
                username_lower = kick_username.lower()
                with self.engine.connect() as conn:
                    blacklist_check = conn.execute(text("""
                        SELECT 1 FROM slot_call_blacklist WHERE kick_username = :username
                    """), {"username": username_lower}).fetchone()
                    if blacklist_check:
                        logger.info(f"[Slot Call] Blocked blacklisted user in handle_slot_call: {kick_username}")
                        return  # Silently block - no response to blacklisted users
            except Exception as e:
                logger.error(f"Error checking slot call blacklist: {e}")
        
        if not self.enabled:
            # Send "slot requests not open" message to Kick chat
            if self.kick_send_callback:
                try:
                    await self.kick_send_callback(f"@{kick_username} Slot requests are not open at the moment.")
                    logger.info(f"Sent 'slot requests not open' message to {kick_username}")
                except Exception as e:
                    logger.error(f"Failed to send disabled message to Kick: {e}")
            return

        if not self.discord_channel_id:
            logger.warning("Slot call received but no Discord channel configured")
            return

        # 🔒 SECURITY: Rate limiting - prevent spam
        now = datetime.utcnow()
        username_lower = kick_username.lower()

        if username_lower in self.last_call_time:
            time_since_last = (now - self.last_call_time[username_lower]).total_seconds()
            if time_since_last < self.cooldown_seconds:
                logger.debug(f"Rate limit: {kick_username} must wait {self.cooldown_seconds - time_since_last:.1f}s")
                return  # Silently ignore - don't spam the user

        # Update last call time
        self.last_call_time[username_lower] = now

        # Check per-user request limit (if enabled)
        # This counts picked + unpicked (available) requests - NOT added_to_hunt
        # Using SELECT FOR UPDATE to prevent race conditions
        if self.max_requests_per_user > 0 and self.engine:
            try:
                with self.engine.begin() as conn:
                    # Lock the user's rows to prevent concurrent requests
                    result = conn.execute(text("""
                        SELECT COUNT(*) FROM slot_requests
                        WHERE LOWER(kick_username) = LOWER(:username)
                        AND (picked = FALSE OR (picked = TRUE AND added_to_hunt = FALSE))
                        FOR UPDATE
                    """), {"username": kick_username}).fetchone()

                    active_requests = result[0] if result else 0

                    if active_requests >= self.max_requests_per_user:
                        # User has reached their active request limit
                        if self.kick_send_callback:
                            try:
                                await self.kick_send_callback(
                                    f"@{kick_username} You have reached the maximum of {self.max_requests_per_user} active slot request(s). "
                                    f"Please wait for your slots to be added to the hunt."
                                )
                                logger.info(f"User {kick_username} blocked: {active_requests}/{self.max_requests_per_user} active requests")
                            except Exception as e:
                                logger.error(f"Failed to send limit message to Kick: {e}")
                        return
            except Exception as e:
                logger.error(f"Failed to check user request limit: {e}")
                # Continue anyway to not block legitimate requests on DB errors

        # Check max added to hunt limit (if enabled) - blocks new requests if user already has max in hunt
        # Using transaction with locking to prevent race conditions
        if self.engine:
            try:
                with self.engine.begin() as conn:
                    max_added_result = conn.execute(text("""
                        SELECT value FROM bot_settings
                        WHERE key = 'slot_max_added_requests'
                    """)).fetchone()

                    max_added = int(max_added_result[0]) if max_added_result else 0

                    if max_added > 0:
                        # Count how many added_to_hunt requests this user already has (with lock)
                        added_count_result = conn.execute(text("""
                            SELECT COUNT(*) FROM slot_requests
                            WHERE LOWER(kick_username) = LOWER(:username)
                            AND added_to_hunt = TRUE
                            FOR UPDATE
                        """), {"username": kick_username}).fetchone()

                        added_count = added_count_result[0] if added_count_result else 0

                        if added_count >= max_added:
                            # User has reached their added to hunt limit - block new requests
                            if self.kick_send_callback:
                                try:
                                    await self.kick_send_callback(
                                        f"@{kick_username} You already have {max_added} slot(s) in the active bonus hunt. "
                                        f"Please wait for the hunt to complete before requesting more."
                                    )
                                    logger.info(f"User {kick_username} blocked: {added_count}/{max_added} slots in active hunt")
                                except Exception as e:
                                    logger.error(f"Failed to send max added message to Kick: {e}")
                            return
            except Exception as e:
                logger.error(f"Failed to check max added to hunt limit: {e}")
                # Continue anyway to not block legitimate requests on DB errors

        # 🔒 SECURITY: Input validation - prevent excessively long inputs
        kick_username_safe = kick_username[:self.max_username_length]
        slot_call_safe = slot_call[:self.max_slot_call_length]

        # Check if slot is banned or provider is disabled (supports name or slug match, basic slug normalization)
        if self.engine:
            try:
                # Normalize to a slug candidate (lowercase, non-alphanumeric -> '-')
                slot_slug_candidate = re.sub(r"[^a-z0-9]+", "-", slot_call_safe.lower()).strip('-')
                with self.engine.connect() as conn:
                    slot_check = conn.execute(text("""
                        SELECT banned, is_active
                        FROM shuffle_slots
                        WHERE (
                                LOWER(name) = LOWER(:slot_name)
                             OR LOWER(slug) = LOWER(:slot_slug)
                             OR LOWER(REPLACE(name,' ','-')) = LOWER(:slot_slug)
                          )
                        LIMIT 1
                    """), {"slot_name": slot_call_safe, "slot_slug": slot_slug_candidate}).fetchone()

                if slot_check:
                    is_banned, is_active = slot_check

                    # Block if slot is banned
                    if is_banned:
                        if self.kick_send_callback:
                            try:
                                await self.kick_send_callback(
                                    f"@{kick_username_safe} Sorry, {slot_call_safe} is currently banned."
                                )
                                logger.info(f"Blocked banned slot request: {slot_call_safe}")
                            except Exception as e:
                                logger.error(f"Failed to send banned slot message to Kick: {e}")
                        return

                    # Block if provider is disabled (inactive)
                    if not is_active:
                        if self.kick_send_callback:
                            try:
                                await self.kick_send_callback(
                                    f"@{kick_username_safe} Sorry, {slot_call_safe} is currently unavailable."
                                )
                                logger.info(f"Blocked slot request for disabled provider: {slot_call_safe}")
                            except Exception as e:
                                logger.error(f"Failed to send disabled provider message to Kick: {e}")
                        return
            except Exception as e:
                logger.error(f"Failed to check slot availability: {e}")
                # Continue anyway to not block legitimate requests on DB errors

        # Check for duplicate slot requests (if enabled)
        if self.engine:
            try:
                with self.engine.connect() as conn:
                    # Check if duplicate prevention is enabled
                    prevent_result = conn.execute(text("""
                        SELECT value FROM bot_settings
                        WHERE key = 'slot_prevent_duplicates'
                    """)).fetchone()

                    prevent_duplicates = prevent_result and prevent_result[0] == 'true'

                    if prevent_duplicates:
                        # Check if this slot has already been requested (unpicked OR added to hunt)
                        dup_result = conn.execute(text("""
                            SELECT COUNT(*) FROM slot_requests
                            WHERE LOWER(slot_call) = LOWER(:slot_call)
                            AND (picked = FALSE OR added_to_hunt = TRUE)
                        """), {"slot_call": slot_call_safe}).fetchone()

                        if dup_result and dup_result[0] > 0:
                            # Slot already requested or in active hunt
                            if self.kick_send_callback:
                                try:
                                    await self.kick_send_callback(
                                        f"@{kick_username_safe} Sorry, {slot_call_safe} has already been requested."
                                    )
                                    logger.info(f"Blocked duplicate slot request: {slot_call_safe} by {kick_username_safe}")
                                except Exception as e:
                                    logger.error(f"Failed to send duplicate message to Kick: {e}")
                            return
            except Exception as e:
                logger.error(f"Failed to check for duplicate slot requests: {e}")
                # Continue anyway to not block legitimate requests on DB errors

        # Get the Discord channel
        channel = self.bot.get_channel(self.discord_channel_id)
        if not channel:
            logger.error(f"Could not find Discord channel {self.discord_channel_id}")
            return

        # Create embed for the slot call
        embed = discord.Embed(
            title="🎰 Slot Call",
            description=f"**{kick_username_safe}** requested **{slot_call_safe}**",
            color=discord.Color.gold(),
            timestamp=datetime.utcnow()
        )
        embed.set_footer(text=f"From Kick chat • {kick_username_safe}")

        try:
            await channel.send(embed=embed)
            logger.info(f"Posted slot call from {kick_username_safe}: {slot_call_safe}")

            # Save slot request to database
            if self.engine:
                try:
                    with self.engine.begin() as conn:
                        conn.execute(text("""
                            INSERT INTO slot_requests (kick_username, slot_call, requested_at)
                            VALUES (:username, :slot_call, CURRENT_TIMESTAMP)
                        """), {"username": kick_username_safe, "slot_call": slot_call_safe})
                    logger.debug(f"Saved slot request to database")

                    # Publish event for real-time dashboard updates
                    try:
                        from bot import publish_redis_event
                        publish_redis_event('dashboard:slot_requests', {
                            'action': 'new_request',
                            'data': {
                                'username': kick_username_safe,
                                'slot_call': slot_call_safe
                            }
                        })
                    except Exception as redis_err:
                        logger.debug(f"Redis publish failed (non-critical): {redis_err}")
                except Exception as e:
                    logger.error(f"Failed to save slot request to database: {e}")

            # Send confirmation message to Kick chat if callback is available
            if self.kick_send_callback:
                kick_response = f"@{kick_username_safe} Your slot request for {slot_call_safe} has been received! ✅"
                try:
                    await self.kick_send_callback(kick_response)
                    logger.info(f"Sent Kick chat response to {kick_username_safe}")
                except Exception as kick_error:
                    logger.error(f"Failed to send Kick chat response: {kick_error}")

            # Update panel if available
            if self.panel:
                try:
                    await self.panel.update_panel()
                    logger.debug("Updated slot request panel after new request")
                except Exception as panel_error:
                    logger.error(f"Failed to update panel: {panel_error}")

        except Exception as e:
            logger.error(f"Failed to post slot call to Discord: {e}")

class SlotCallCommands(commands.Cog):
    """Discord commands for managing slot call tracking"""

    def __init__(self, bot, tracker: SlotCallTracker):
        self.bot = bot
        self.tracker = tracker

    @commands.command(name='slotcalls')
    @commands.has_permissions(administrator=True)
    async def toggle_slot_calls(self, ctx, action: str = None):
        """
        [ADMIN] Toggle slot call tracking on/off or check status
        Usage: !slotcalls [on|off|status]
        """
        if action is None or action.lower() == "status":
            status = "✅ **enabled**" if self.tracker.is_enabled() else "❌ **disabled**"
            channel_id = self.tracker.discord_channel_id
            channel_mention = f"<#{channel_id}>" if channel_id else "Not configured"

            embed = discord.Embed(
                title="🎰 Slot Call Tracker Status",
                color=discord.Color.green() if self.tracker.is_enabled() else discord.Color.red()
            )
            embed.add_field(name="Status", value=status, inline=True)
            embed.add_field(name="Channel", value=channel_mention, inline=True)
            embed.add_field(
                name="🔒 Security",
                value=f"• Rate limit: {self.tracker.cooldown_seconds}s cooldown per user\n"
                      f"• Max username: {self.tracker.max_username_length} chars\n"
                      f"• Max slot call: {self.tracker.max_slot_call_length} chars",
                inline=False
            )
            embed.add_field(
                name="How it works",
                value="When users type `!call <slot>` or `!sr <slot>` in Kick chat, it posts to the configured Discord channel.",
                inline=False
            )

            await ctx.send(embed=embed)
            return

        if action.lower() == "on":
            await self.tracker.set_enabled(True)
            await ctx.send("✅ Slot call tracking **enabled**! Users can now use `!call <slot>` or `!sr <slot>` in Kick chat.")
        elif action.lower() == "off":
            await self.tracker.set_enabled(False)
            await ctx.send("❌ Slot call tracking **disabled**. `!call` and `!sr` commands will be ignored.")
        else:
            await ctx.send("❌ Invalid action. Use `!slotcalls on`, `!slotcalls off`, or `!slotcalls status`")

    @commands.command(name='pickslot', aliases=['randomslot', 'slotpick'])
    @commands.has_permissions(administrator=True)
    async def pick_random_slot(self, ctx):
        """
        [ADMIN] Pick a random slot request from the list
        Usage: !pickslot
        """
        if not self.tracker.engine:
            await ctx.send("❌ Database not available")
            return

        try:
            with self.tracker.engine.connect() as conn:
                # Get a random unpicked slot request
                result = conn.execute(text("""
                    SELECT id, kick_username, slot_call, requested_at
                    FROM slot_requests
                    WHERE picked = FALSE
                    ORDER BY RANDOM()
                    LIMIT 1
                """)).fetchone()

                if not result:
                    await ctx.send("❌ No slot requests available. The list may be empty or all requests have been picked.")
                    return

                request_id, username, slot_call, requested_at = result

                # Mark as picked
                with self.tracker.engine.begin() as update_conn:
                    update_conn.execute(text("""
                        UPDATE slot_requests
                        SET picked = TRUE, picked_at = CURRENT_TIMESTAMP
                        WHERE id = :id
                    """), {"id": request_id})

                # Create embed
                embed = discord.Embed(
                    title="🎰 Random Slot Picked!",
                    description=f"**{slot_call}**",
                    color=discord.Color.gold()
                )
                embed.add_field(name="Requested by", value=username, inline=True)
                embed.add_field(name="Requested at", value=requested_at.strftime("%Y-%m-%d %H:%M:%S UTC") if requested_at else "Unknown", inline=True)
                embed.set_footer(text=f"Request ID: {request_id}")

                await ctx.send(embed=embed)
                logger.info(f"Picked random slot: {slot_call} by {username}")

                # Send message to Kick chat
                if self.tracker.kick_send_callback:
                    try:
                        kick_message = f"🎰 Random slot picked: {slot_call} (requested by @{username})"
                        await self.tracker.kick_send_callback(kick_message)
                        logger.info(f"Sent pick notification to Kick chat")
                    except Exception as kick_error:
                        logger.error(f"Failed to send pick notification to Kick: {kick_error}")

                # Update panel if available
                if self.tracker.panel:
                    try:
                        await self.tracker.panel.update_panel()
                        logger.info("Updated slot request panel after pick")
                    except Exception as panel_error:
                        logger.error(f"Failed to update panel: {panel_error}")

        except Exception as e:
            logger.error(f"Failed to pick random slot: {e}")
            await ctx.send(f"❌ Error picking random slot: {e}")

    @commands.command(name='slotlist', aliases=['listslots', 'slots'])
    @commands.has_permissions(administrator=True)
    async def list_slot_requests(self, ctx):
        """
        [ADMIN] Show statistics about slot requests
        Usage: !slotlist
        """
        if not self.tracker.engine:
            await ctx.send("❌ Database not available")
            return

        try:
            with self.tracker.engine.connect() as conn:
                # Get counts
                total = conn.execute(text("SELECT COUNT(*) FROM slot_requests")).fetchone()[0]
                unpicked = conn.execute(text("SELECT COUNT(*) FROM slot_requests WHERE picked = FALSE")).fetchone()[0]
                picked = conn.execute(text("SELECT COUNT(*) FROM slot_requests WHERE picked = TRUE")).fetchone()[0]

                embed = discord.Embed(
                    title="🎰 Slot Request Statistics",
                    color=discord.Color.blue()
                )
                embed.add_field(name="Total Requests", value=str(total), inline=True)
                embed.add_field(name="Available", value=str(unpicked), inline=True)
                embed.add_field(name="Already Picked", value=str(picked), inline=True)

                if unpicked > 0:
                    embed.set_footer(text=f"Use !pickslot to pick a random slot from {unpicked} available requests")
                else:
                    embed.set_footer(text="No unpicked requests available")

                await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f"Failed to get slot request stats: {e}")
            await ctx.send(f"❌ Error getting slot list: {e}")

    @toggle_slot_calls.error
    async def toggle_slot_calls_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("❌ You need administrator permission to use this command.")

async def setup_slot_call_tracker(bot, discord_channel_id: Optional[int] = None, kick_send_callback=None, engine=None):
    """
    Setup slot call tracker

    Args:
        bot: Discord bot instance
        discord_channel_id: Discord channel ID to post slot calls to
        kick_send_callback: Optional callback function to send messages to Kick chat
        engine: SQLAlchemy engine for persisting state

    Returns:
        SlotCallTracker instance
    """
    tracker = SlotCallTracker(bot, discord_channel_id, kick_send_callback, engine)

    # Add commands
    await bot.add_cog(SlotCallCommands(bot, tracker))

    logger.info(f"✅ Slot call tracker initialized (channel: {discord_channel_id or 'Not set'})")

    return tracker
