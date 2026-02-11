"""
Redis Subscriber for Discord Bot
Listens for events from the Admin Dashboard and triggers bot actions

Add this to your bot's main file after the bot is initialized:

    from redis_subscriber import start_redis_subscriber

    @bot.event
    async def on_ready():
        print(f'Bot logged in as {bot.user}')
        # Start Redis subscriber
        asyncio.create_task(start_redis_subscriber(bot))
"""

import asyncio
import json
import os
import time
from datetime import datetime

import discord
import redis
from sqlalchemy import create_engine, text  # type: ignore

DATABASE_URL = os.getenv("DATABASE_URL", "")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = None
if DATABASE_URL:
    try:
        engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    except Exception as e:
        print(f"⚠️  Failed to initialize DB engine in redis_subscriber: {e}")
        engine = None

import discord
from sqlalchemy import create_engine, text

_engine = None


def get_engine():
    """Create (or return) a SQLAlchemy engine for the bot database."""
    global _engine
    if _engine is not None:
        return _engine

    database_url = os.getenv("DATABASE_URL", "")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set; cannot query point_settings")

    # SQLAlchemy expects postgresql://
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    _engine = create_engine(database_url, pool_pre_ping=True)
    return _engine


class RedisSubscriber:
    def __init__(self, bot, send_message_callback=None):
        self.bot = bot
        self.send_message_callback = send_message_callback
        self.redis_url = os.getenv("REDIS_URL")
        self.enabled = False
        self.last_shop_sync = 0  # Timestamp for debouncing shop sync

        # Ensure point_sales has columns for tracking Discord order notification messages
        try:
            if engine is not None:
                with engine.begin() as conn:
                    conn.execute(
                        text(
                            """
                        ALTER TABLE point_sales
                        ADD COLUMN IF NOT EXISTS discord_notification_channel_id BIGINT
                    """
                        )
                    )
                    conn.execute(
                        text(
                            """
                        ALTER TABLE point_sales
                        ADD COLUMN IF NOT EXISTS discord_notification_message_id BIGINT
                    """
                        )
                    )
        except Exception as e:
            print(f"⚠️  Failed to ensure point_sales notification columns: {e}")

        if self.redis_url:
            if "://" not in self.redis_url:
                self.redis_url = f"redis://{self.redis_url}"
            try:
                self.client = redis.from_url(
                    self.redis_url,
                    decode_responses=True,
                    socket_connect_timeout=5,
                    socket_timeout=5,
                )
                self.pubsub = self.client.pubsub()
                self.enabled = True
                print("✅ Redis subscriber initialized")
            except Exception as e:
                print(f"⚠️  Redis unavailable: {e}")
                self.enabled = False
        else:
            print("⚠️  REDIS_URL not set, dashboard events will not be received")

    async def announce_in_chat(self, message, guild_id=None):
        """Send a message to Kick chat using the callback function

        Args:
            message: Message to send
            guild_id: Discord server ID (if None, uses first available guild)
        """
        if self.send_message_callback:
            try:
                # If no guild_id provided, try to get from bot's first guild
                if guild_id is None and hasattr(self.bot, "guilds") and self.bot.guilds:
                    guild_id = self.bot.guilds[0].id

                # Ensure guild_id is an integer (may come as string from JSON)
                if guild_id is not None:
                    guild_id = int(guild_id)

                await self.send_message_callback(message, guild_id=guild_id)
                print(f"💬 Sent to Kick chat: {message}")
            except Exception as e:
                print(f"⚠️ Kick chat message not sent: {e}")
                print(f"   Message was: {message}")
                import traceback

                traceback.print_exc()
        else:
            print(f"ℹ️  Kick chat disabled: {message}")

    # ❌ WEBHOOK HANDLING DISABLED - Using direct Pusher WebSocket instead
    # NOTE: The previous webhook handler implementation was intentionally removed
    # because it was disabled and must not run at import/class-definition time.

    async def handle_slot_requests_event(self, action, data):
        """Handle slot request events from dashboard"""
        print(f"📥 Slot Requests Event: {action}")

        # Extract discord_server_id from event data and convert to int
        guild_id = data.get("discord_server_id")
        if guild_id is not None:
            guild_id = int(guild_id)

        if action == "toggle":
            enabled = data.get("enabled")
            # Announce in Kick chat
            if enabled:
                await self.announce_in_chat(
                    '✅ Slot requests are now ENABLED! Use !call "slot name" or !sr "slot name"', guild_id=guild_id
                )
            else:
                await self.announce_in_chat("❌ Slot requests have been DISABLED", guild_id=guild_id)

            # Post update to Discord slot calls channel if available
            if hasattr(self.bot, "slot_calls_channel_id") and self.bot.slot_calls_channel_id:
                try:
                    channel = self.bot.get_channel(self.bot.slot_calls_channel_id)
                    if channel:
                        emoji = "✅" if enabled else "❌"
                        status = "ENABLED" if enabled else "DISABLED"
                        await channel.send(f"{emoji} **Slot Requests {status}** (changed via dashboard)")
                except Exception as e:
                    print(f"Failed to send Discord notification: {e}")

            # Update tracker enabled state directly
            if hasattr(self.bot, "slot_call_tracker") and self.bot.slot_call_tracker:
                try:
                    tracker = self.bot.slot_call_tracker
                    # Store current server_id and switch to the guild that triggered this event
                    original_server_id = tracker.server_id
                    if guild_id:
                        tracker.server_id = guild_id

                    # Reload enabled state from database
                    tracker.enabled = tracker._load_enabled_state()
                    tracker.max_requests_per_user = tracker._load_max_requests()
                    print(f"✅ Updated slot_call_tracker enabled state to: {tracker.enabled} for server {guild_id}")

                    # Restore original server_id
                    if original_server_id:
                        tracker.server_id = original_server_id
                except Exception as e:
                    print(f"⚠️ Failed to update slot_call_tracker: {e}")

            # Update panel tracker (if panel exists for this guild)
            panel = None
            if guild_id and hasattr(self.bot, "slot_panels_by_guild"):
                panel = self.bot.slot_panels_by_guild.get(guild_id)
            
            if panel:
                try:
                    # Refresh tracker state from database before updating panel
                    if hasattr(panel, "tracker") and panel.tracker:
                        panel.tracker.enabled = panel.tracker._load_enabled_state()
                        panel.tracker.max_requests_per_user = panel.tracker._load_max_requests()
                        print(
                            f"✅ Updated panel tracker enabled state to: {panel.tracker.enabled} for server {guild_id}"
                        )
                except Exception as e:
                    print(f"⚠️ Failed to update tracker via panel: {e}")

            # Update Discord panel (if it exists for this guild)
            if panel:
                try:
                    print(f"🔍 Panel IDs: message_id={panel.panel_message_id}, channel_id={panel.panel_channel_id}")
                    success = await panel.update_panel(force=True)
                    if success:
                        print(f"✅ Slot request panel updated in Discord for guild {guild_id}")
                    else:
                        print(f"ℹ️  Slot panel not created yet for guild {guild_id} (Discord admin: use !slotpanel to create)")
                except Exception as e:
                    print(f"⚠️ Failed to update slot panel: {e}")
                    import traceback

                    traceback.print_exc()

        elif action == "pick":
            slot_id = data.get("id")
            slot_call = data.get("slot_call")
            username = data.get("username")
            guild_id = data.get("discord_server_id")
            if guild_id is not None:
                guild_id = int(guild_id)
            delay_announcement = data.get("delay_announcement", 0)

            print(f"📥 [BOT-REDIS] Received 'pick' event with delay_announcement={delay_announcement}")

            # If overlay is enabled, delay the announcement to allow animation to play
            if delay_announcement > 0:
                print(
                    f"⏰ [BOT-REDIS] Delaying Kick chat announcement by {delay_announcement} seconds for overlay animation"
                )
                await asyncio.sleep(delay_announcement)
                print(f"✅ [BOT-REDIS] Delay complete, announcing now")
            else:
                print(f"⚡ [BOT-REDIS] No delay, announcing immediately")

            # Announce the picked slot in Kick chat (tag the user)
            await self.announce_in_chat(f"🎰 PICKED: {slot_call} (requested by @{username})", guild_id=guild_id)

            # Post to Discord
            if hasattr(self.bot, "slot_calls_channel_id") and self.bot.slot_calls_channel_id:
                try:
                    channel = self.bot.get_channel(self.bot.slot_calls_channel_id)
                    if channel:
                        await channel.send(f"🎰 **PICKED**: {slot_call} (requested by {username})")
                except Exception as e:
                    print(f"Failed to send Discord notification: {e}")

            # Update Discord panel for this guild
            panel = None
            if guild_id and hasattr(self.bot, "slot_panels_by_guild"):
                panel = self.bot.slot_panels_by_guild.get(guild_id)
            
            if panel:
                try:
                    # Refresh tracker state from database before updating panel
                    if hasattr(panel, "tracker") and panel.tracker:
                        panel.tracker.enabled = panel.tracker._load_enabled_state()  # Reload enabled state from DB
                        panel.tracker.max_requests_per_user = (
                            panel.tracker._load_max_requests()
                        )  # Reload max requests too
                    success = await panel.update_panel(force=True)
                    if success:
                        print(f"✅ Slot request panel updated in Discord for guild {guild_id}")
                    else:
                        print(f"ℹ️  Slot panel not created yet for guild {guild_id}")
                except Exception as e:
                    print(f"⚠️ Failed to update slot panel: {e}")

        elif action == "pick_with_reward":
            slot_id = data.get("slot_id")
            slot_call = data.get("slot_call")
            username = data.get("username")
            reward_type = data.get("reward_type")
            reward_amount = data.get("reward_amount")
            guild_id = data.get("discord_server_id")
            if guild_id is not None:
                guild_id = int(guild_id)
            delay_announcement = data.get("delay_announcement", 0)

            print(f"📥 [BOT-REDIS] Received 'pick_with_reward' event with delay_announcement={delay_announcement}")

            # Format reward type for display
            reward_type_display = "Bonus Buy" if reward_type == "bonus_buy" else reward_type.capitalize()

            # If overlay is enabled, delay the announcement to allow animation to play
            if delay_announcement > 0:
                print(
                    f"⏰ [BOT-REDIS] Delaying Kick chat announcement by {delay_announcement} seconds for overlay animation"
                )
                await asyncio.sleep(delay_announcement)
                print(f"✅ [BOT-REDIS] Delay complete, announcing now")
            else:
                print(f"⚡ [BOT-REDIS] No delay, announcing immediately")

            # Announce the picked slot WITH reward in Kick chat (tag the user)
            amount = float(reward_amount)
            await self.announce_in_chat(
                f"🎰 PICKED: {slot_call} (requested by @{username}) 💰 WON ${amount:.2f} {reward_type_display}!",
                guild_id=guild_id,
            )

            # Post to Discord
            if hasattr(self.bot, "slot_calls_channel_id") and self.bot.slot_calls_channel_id:
                try:
                    channel = self.bot.get_channel(self.bot.slot_calls_channel_id)
                    if channel:
                        await channel.send(
                            f"🎰 **PICKED**: {slot_call} (requested by {username})\n💰 **WON**: ${amount:.2f} {reward_type_display}!"
                        )
                except Exception as e:
                    print(f"Failed to send Discord notification: {e}")

            # Update Discord panel for this guild
            panel = None
            if guild_id and hasattr(self.bot, "slot_panels_by_guild"):
                panel = self.bot.slot_panels_by_guild.get(guild_id)
            
            if panel:
                try:
                    # Refresh tracker state from database before updating panel
                    if hasattr(panel, "tracker") and panel.tracker:
                        panel.tracker.enabled = panel.tracker._load_enabled_state()  # Reload enabled state from DB
                        panel.tracker.max_requests_per_user = (
                            panel.tracker._load_max_requests()
                        )  # Reload max requests too
                    success = await panel.update_panel(force=True)
                    if success:
                        print(f"✅ Slot request panel updated in Discord for guild {guild_id}")
                    else:
                        print(f"ℹ️  Slot panel not created yet for guild {guild_id}")
                except Exception as e:
                    print(f"⚠️ Failed to update slot panel: {e}")

        elif action == "update_max":
            max_requests = data.get("max_requests")
            guild_id = data.get("discord_server_id")
            
            # Convert guild_id to int (may come as string from JSON)
            if guild_id is not None:
                guild_id = int(guild_id)
            
            print(f"📥 Updated max slot requests to {max_requests} for guild {guild_id}")

            # Update the per-guild tracker if available
            if guild_id and hasattr(self.bot, "slot_call_trackers_by_guild"):
                tracker = self.bot.slot_call_trackers_by_guild.get(guild_id)
                if tracker:
                    try:
                        tracker.max_requests_per_user = tracker._load_max_requests()
                        print(f"✅ Updated slot_call_tracker max_requests for guild {guild_id}: {tracker.max_requests_per_user}")
                    except Exception as e:
                        print(f"⚠️ Failed to update slot_call_tracker for guild {guild_id}: {e}")

            # Update Discord panel for the specific guild
            if guild_id and hasattr(self.bot, "slot_panels_by_guild"):
                panel = self.bot.slot_panels_by_guild.get(guild_id)
                if panel:
                    try:
                        # Refresh tracker state from database before updating panel
                        if hasattr(panel, "tracker") and panel.tracker:
                            panel.tracker.max_requests_per_user = panel.tracker._load_max_requests()
                            print(f"✅ Updated panel tracker max_requests for guild {guild_id}: {panel.tracker.max_requests_per_user}")
                        success = await panel.update_panel(force=True)
                        if success:
                            print(f"✅ Slot request panel updated in Discord for guild {guild_id}")
                        else:
                            print(f"ℹ️  Slot panel not created yet for guild {guild_id}")
                    except Exception as e:
                        print(f"⚠️ Failed to update slot panel for guild {guild_id}: {e}")

    async def handle_timed_messages_event(self, action, data):
        """Handle timed message events from dashboard"""
        print(f"📥 Timed Messages Event: {action}")

        # Extract discord_server_id from event data
        guild_id = data.get("discord_server_id")

        # Convert guild_id to int (may come as string from JSON)
        if guild_id is not None:
            guild_id = int(guild_id)

        # Reload timed messages from database for the specific guild
        if hasattr(self.bot, "timed_messages_managers") and guild_id:
            manager = self.bot.timed_messages_managers.get(guild_id)
            if manager:
                try:
                    manager.reload_messages()
                    print(f"✅ Timed messages reloaded for guild {guild_id}")
                except Exception as e:
                    print(f"⚠️ Failed to reload timed messages: {e}")
        elif hasattr(self.bot, "timed_messages_manager") and self.bot.timed_messages_manager:
            # Fallback for backwards compatibility (single global manager)
            try:
                self.bot.timed_messages_manager.reload_messages()
                print(f"✅ Timed messages reloaded from database")
            except Exception as e:
                print(f"⚠️ Failed to reload timed messages: {e}")

        if action == "create":
            message_id = data.get("id")
            message = data.get("message")
            interval = data.get("interval_minutes")
            print(f"✅ Created timed message #{message_id}: {message} (every {interval}m)")

        elif action == "update":
            message_id = data.get("id")
            print(f"✅ Updated timed message #{message_id}")

        elif action == "delete":
            message_id = data.get("id")
            print(f"✅ Deleted timed message #{message_id}")

        elif action == "toggle":
            message_id = data.get("id")
            enabled = data.get("enabled")
            status = "enabled" if enabled else "disabled"
            print(f"✅ Timed message #{message_id} {status}")

    async def handle_gtb_event(self, action, data):
        """Handle Guess the Balance events from dashboard"""
        print(f"📥 GTB Event: {action}")

        # Extract discord_server_id from event data and convert to int
        guild_id = data.get("discord_server_id")
        if guild_id is not None:
            guild_id = int(guild_id)

        if action == "open":
            session_id = data.get("session_id")
            opened_by = data.get("opened_by")
            # Announce in Kick chat
            await self.announce_in_chat(
                f"💰 Guess the Balance session #{session_id} is now OPEN! Use !gtb <amount> to guess!",
                guild_id=guild_id,
            )

            # Post to Discord GTB channel if available
            if hasattr(self.bot, "gtb_channel_id") and self.bot.gtb_channel_id:
                try:
                    channel = self.bot.get_channel(self.bot.gtb_channel_id)
                    if channel:
                        await channel.send(f"💰 **GTB Session #{session_id} OPENED** by {opened_by}")
                except Exception as e:
                    print(f"Failed to send Discord notification: {e}")

            # Update Discord GTB panel for this guild
            if guild_id and hasattr(self.bot, "gtb_panels_by_guild"):
                gtb_panel = self.bot.gtb_panels_by_guild.get(guild_id)
                if gtb_panel:
                    try:
                        success = await gtb_panel.update_panel(force=True)
                        if success:
                            print(f"✅ GTB panel updated in Discord for guild {guild_id}")
                        else:
                            print(f"ℹ️  GTB panel not created yet for guild {guild_id}")
                    except Exception as e:
                        print(f"⚠️ Failed to update GTB panel: {e}")

        elif action == "close":
            session_id = data.get("session_id")
            # Announce in Kick chat
            await self.announce_in_chat(
                f"🔒 Guess the Balance session #{session_id} is now CLOSED! No more guesses allowed.", guild_id=guild_id
            )

            # Post to Discord
            if hasattr(self.bot, "gtb_channel_id") and self.bot.gtb_channel_id:
                try:
                    channel = self.bot.get_channel(self.bot.gtb_channel_id)
                    if channel:
                        await channel.send(f"🔒 **GTB Session #{session_id} CLOSED** - Guessing is over!")
                except Exception as e:
                    print(f"Failed to send Discord notification: {e}")

            # Update Discord GTB panel for this guild
            if guild_id and hasattr(self.bot, "gtb_panels_by_guild"):
                gtb_panel = self.bot.gtb_panels_by_guild.get(guild_id)
                if gtb_panel:
                    try:
                        success = await gtb_panel.update_panel(force=True)
                        if success:
                            print(f"✅ GTB panel updated in Discord for guild {guild_id}")
                        else:
                            print(f"ℹ️  GTB panel not created yet for guild {guild_id}")
                    except Exception as e:
                        print(f"⚠️ Failed to update GTB panel: {e}")

        elif action == "set_result":
            session_id = data.get("session_id")
            result_amount = data.get("result_amount")
            winners = data.get("winners", [])  # Get winners from dashboard

            # Announce result in Kick chat
            await self.announce_in_chat(
                f"🎉 GTB Result: ${result_amount:,.2f}! Calculating winners...", guild_id=guild_id
            )

            # If winners were provided by dashboard, use them
            if winners and len(winners) > 0:
                # Small delay to ensure messages don't get combined
                await asyncio.sleep(1)

                # Announce top 3 winners
                winner_messages = []
                for winner in winners[:3]:
                    rank_emoji = "🥇" if winner["rank"] == 1 else "🥈" if winner["rank"] == 2 else "🥉"
                    winner_messages.append(
                        f"{rank_emoji} {winner['username']}: ${winner['guess']:,.2f} (${winner['difference']:,.2f} off)"
                    )

                # Announce all winners in one message
                winner_text = f"🏆 Winners: " + " | ".join(winner_messages)
                print(f"📢 Announcing winners in Kick chat: {winner_text}")
                await self.announce_in_chat(winner_text, guild_id=guild_id)
                print(f"✅ Announced {len(winners)} GTB winners in Kick chat")
            else:
                # Fallback: Calculate winners using GTB manager if available
                if hasattr(self.bot, "gtb_manager") and self.bot.gtb_manager:
                    try:
                        print(f"🔍 No winners provided, calling set_result with amount: ${result_amount:,.2f}")
                        success, message, calculated_winners = self.bot.gtb_manager.set_result(result_amount)
                        print(
                            f"🔍 set_result returned - success: {success}, message: {message}, winners: {calculated_winners}"
                        )

                        if success and calculated_winners and len(calculated_winners) > 0:
                            # Small delay to ensure messages don't get combined
                            await asyncio.sleep(1)

                            # Announce top 3 winners
                            winner_messages = []
                            for winner in calculated_winners[:3]:
                                rank_emoji = "🥇" if winner["rank"] == 1 else "🥈" if winner["rank"] == 2 else "🥉"
                                winner_messages.append(
                                    f"{rank_emoji} {winner['username']}: ${winner['guess']:,.2f} (${winner['difference']:,.2f} off)"
                                )

                            # Announce all winners in one message
                            winner_text = f"🏆 Winners: " + " | ".join(winner_messages)
                            print(f"📢 Announcing winners in Kick chat: {winner_text}")
                            await self.announce_in_chat(winner_text, guild_id=guild_id)
                            print(f"✅ Announced {len(calculated_winners)} GTB winners in Kick chat")
                        else:
                            print(
                                f"⚠️ GTB result set but no winners - success: {success}, message: {message}, winner count: {len(calculated_winners) if calculated_winners else 0}"
                            )
                    except Exception as e:
                        print(f"⚠️ Failed to calculate GTB winners: {e}")
                        import traceback

                        traceback.print_exc()
                else:
                    print(f"⚠️ GTB manager not available and no winners provided in message")

            # Post to Discord
            if hasattr(self.bot, "gtb_channel_id") and self.bot.gtb_channel_id:
                try:
                    channel = self.bot.get_channel(self.bot.gtb_channel_id)
                    if channel:
                        await channel.send(f"🎉 **GTB Result Set**: ${result_amount:,.2f}")
                except Exception as e:
                    print(f"Failed to send Discord notification: {e}")

            # Update Discord GTB panel for this guild
            if guild_id and hasattr(self.bot, "gtb_panels_by_guild"):
                gtb_panel = self.bot.gtb_panels_by_guild.get(guild_id)
                if gtb_panel:
                    try:
                        success = await gtb_panel.update_panel(force=True)
                        if success:
                            print(f"✅ GTB panel updated in Discord for guild {guild_id}")
                        else:
                            print(f"ℹ️  GTB panel not created yet for guild {guild_id}")
                    except Exception as e:
                        print(f"⚠️ Failed to update GTB panel: {e}")

    async def handle_management_event(self, action, data):
        """Handle management events from dashboard"""
        print(f"📥 Management Event: {action}")

        if action == "adjust_tickets":
            discord_id = data.get("discord_id")
            ticket_source = data.get("ticket_source")
            change = data.get("change")
            reason = data.get("reason")
            print(f"Tickets adjusted for {discord_id}: {change} {ticket_source} tickets ({reason})")

        elif action == "start_period":
            start_date = data.get("start_date")
            end_date = data.get("end_date")
            await self.announce_in_chat(f"🎟️ New raffle period started! {start_date} to {end_date}")

    async def handle_raffle_event(self, action, data):
        """Handle raffle events from dashboard"""
        print(f"📥 Raffle Event: {action}")

        if action == "draw":
            request_id = data.get("request_id")
            period_id = data.get("period_id")
            winner_count = data.get("winner_count", 1)
            prize_description = data.get("prize_description", "")
            drawn_by_discord_id = data.get("drawn_by_discord_id")
            server_id = data.get("server_id")
            # Support for rerolls - exclude specific discord IDs
            initial_excluded_ids = data.get("excluded_discord_ids", [])
            is_reroll = data.get("is_reroll", False)

            print(f"🎲 Processing raffle draw request {request_id} for period {period_id}")
            if is_reroll:
                print(f"🔄 This is a REROLL - excluding IDs: {initial_excluded_ids}")

            try:
                from sqlalchemy import create_engine

                from raffle_system.draw import RaffleDraw

                database_url = os.getenv("DATABASE_URL")
                engine = create_engine(database_url)
                draw_handler = RaffleDraw(engine)

                # Convert initial excluded IDs to integers
                excluded_discord_ids = [int(eid) for eid in initial_excluded_ids if eid]

                if winner_count == 1:
                    # Single winner (or reroll)
                    winner = draw_handler.draw_winner(
                        period_id=period_id,
                        drawn_by_discord_id=drawn_by_discord_id,
                        prize_description=prize_description,
                        excluded_discord_ids=excluded_discord_ids if excluded_discord_ids else None,
                    )

                    if not winner:
                        result = {"success": False, "error": "No eligible participants found"}
                    else:
                        result = {"success": True, "winner": winner, "winners": [winner], "is_reroll": is_reroll}
                else:
                    # Multiple winners
                    winners = []

                    for i in range(winner_count):
                        winner = draw_handler.draw_winner(
                            period_id=period_id,
                            drawn_by_discord_id=drawn_by_discord_id,
                            prize_description=f"{prize_description} (Winner {i+1}/{winner_count})",
                            excluded_discord_ids=excluded_discord_ids if excluded_discord_ids else None,
                            update_period=(i == 0),
                        )

                        if not winner:
                            if i == 0:
                                result = {"success": False, "error": "No eligible participants found"}
                                break
                            break

                        winners.append(winner)
                        excluded_discord_ids.append(winner["winner_discord_id"])

                    if winners:
                        result = {"success": True, "winners": winners, "winner": winners[0]}

                # Store result in Redis for dashboard to retrieve
                result_key = f"raffle_draw_result:{request_id}"
                self.client.setex(result_key, 30, json.dumps(result))  # Expire after 30 seconds
                print(f"✅ Raffle draw completed, result stored in Redis")

                # Store pending announcements as a QUEUE - each winner announced individually when their animation completes
                if result.get("success"):
                    winners_list = result.get("winners", [])
                    queue_key = f"raffle_announcement_queue:{server_id}"

                    # Store winners as a list (queue) - each animation_complete pops one
                    # Include server_id in queue for multi-server announcement channel lookup
                    self.client.setex(
                        queue_key,
                        600,
                        json.dumps(
                            {
                                "winners_queue": winners_list,
                                "prize_description": prize_description,
                                "total_winners": len(winners_list),
                                "announced_count": 0,
                                "server_id": server_id,  # Store server_id for channel lookup
                            }
                        ),
                    )  # Expire after 10 minutes (streamer may take time between draws)
                    print(
                        f"⏳ {len(winners_list)} winner(s) queued for announcement (server_id={server_id}), waiting for animation(s) to complete..."
                    )

            except Exception as e:
                print(f"❌ Raffle draw failed: {e}")
                import traceback

                traceback.print_exc()
                result = {"success": False, "error": str(e)}
                result_key = f"raffle_draw_result:{request_id}"
                self.client.setex(result_key, 30, json.dumps(result))

        elif action == "animation_complete":
            # OBS widget animation finished for ONE winner - announce that winner now
            winner_kick_name = data.get("winner_kick_name")
            server_id = data.get("server_id")
            print(f"🎬 [RAFFLE] Animation complete for winner: {winner_kick_name} (server_id={server_id})")

            try:
                # If server_id provided, use specific queue; otherwise search all (backwards compatibility)
                if server_id:
                    queue_keys = [f"raffle_announcement_queue:{server_id}"]
                else:
                    queue_keys = self.client.keys("raffle_announcement_queue:*")

                for key in queue_keys:
                    queue_data = self.client.get(key)
                    if queue_data:
                        queue = json.loads(queue_data)
                        winners_queue = queue.get("winners_queue", [])
                        prize_description = queue.get("prize_description", "")

                        if winners_queue:
                            # Pop the first winner from queue and announce
                            winner_to_announce = winners_queue.pop(0)
                            announced_count = queue.get("announced_count", 0) + 1
                            queue_server_id = queue.get("server_id", server_id)  # Get server_id from queue

                            print(
                                f"✅ Announcing winner {announced_count}/{queue['total_winners']}: {winner_to_announce.get('winner_kick_name')} (server_id={queue_server_id})"
                            )

                            # Announce this single winner (pass server_id for multi-server support)
                            await self.announce_raffle_winners(
                                [winner_to_announce], prize_description, guild_id=queue_server_id
                            )

                            # Update queue in Redis
                            if winners_queue:
                                # More winners remaining
                                queue["winners_queue"] = winners_queue
                                queue["announced_count"] = announced_count
                                self.client.setex(key, 300, json.dumps(queue))
                            else:
                                # All winners announced, delete queue
                                self.client.delete(key)
                                print(f"🎉 All {announced_count} winner(s) announced!")

                            break  # Only announce one winner per animation_complete event

            except Exception as e:
                print(f"❌ Error handling animation_complete: {e}")
                import traceback

                traceback.print_exc()

    async def handle_commands_event(self, action, data):
        """Handle custom commands events from dashboard"""
        guild_id = data.get("discord_server_id")
        print(f"📥 Commands Event: {action} (guild_id={guild_id})")

        if action == "reload":
            # Trigger custom commands reload for specific guild or all guilds
            if hasattr(self.bot, "custom_commands_managers"):
                try:
                    if guild_id:
                        # Reload commands for specific guild
                        if guild_id in self.bot.custom_commands_managers:
                            await self.bot.custom_commands_managers[guild_id].reload_commands()
                            print(f"✅ Custom commands reloaded for guild {guild_id}")
                        else:
                            print(f"⚠️ No custom commands manager found for guild {guild_id}")
                    else:
                        # Reload commands for all guilds
                        for gid, manager in self.bot.custom_commands_managers.items():
                            await manager.reload_commands()
                        print(f"✅ Custom commands reloaded for all {len(self.bot.custom_commands_managers)} guilds")
                except Exception as e:
                    print(f"⚠️ Failed to reload custom commands: {e}")
                    import traceback

                    traceback.print_exc()
            else:
                print("⚠️ Custom commands managers not initialized")

    async def handle_point_shop_event(self, action, data):
        """Handle point shop events from dashboard"""
        guild_id = data.get("discord_server_id")
        guild = self.bot.get_guild(int(guild_id)) if guild_id else None
        guild_name = guild.name if guild else "Unknown"
        print(f"📥 Point Shop Event: {action} (guild={guild_name}, guild_id={guild_id})")

        if action == "post_shop":
            channel_id = data.get("channel_id")

            # Import the post function from bot module
            try:
                from bot import post_point_shop_to_discord

                success = await post_point_shop_to_discord(self.bot, channel_id=channel_id, update_existing=True)
                if success:
                    print(f"✅ Point shop posted to Discord (guild={guild_name})")
                else:
                    print(f"⚠️  Failed to post point shop (guild={guild_name})")
            except ImportError:
                print(f"⚠️  post_point_shop_to_discord function not implemented yet (guild={guild_name})")
            except Exception as e:
                print(f"⚠️  Failed to post point shop (guild={guild_name}): {e}")
                import traceback

                traceback.print_exc()

        elif action == "sync_shop":
            # Debounce: prevent duplicate syncs within 3 seconds
            current_time = time.time()
            if current_time - self.last_shop_sync < 3:
                print(
                    f"⏭️  Ignoring duplicate sync_shop for {guild_name} (last sync {current_time - self.last_shop_sync:.1f}s ago)"
                )
                return

            self.last_shop_sync = current_time

            if not guild_id:
                print("❌ sync_shop event missing discord_server_id - cannot sync without guild context")
                return

            # Force update the shop message
            try:
                from bot import post_point_shop_to_discord

                success = await post_point_shop_to_discord(self.bot, guild_id=guild_id, update_existing=True)
                if success:
                    print(f"✅ Point shop force synced for {guild_name} (guild_id={guild_id})")
                else:
                    print(f"⚠️  Failed to sync point shop for {guild_name} (guild_id={guild_id})")
            except ImportError:
                print(
                    f"⚠️  post_point_shop_to_discord function not implemented yet (guild={guild_name}, guild_id={guild_id})"
                )
                print("💡 Tip: Implement this function in bot.py to auto-sync shop embeds to Discord")
            except Exception as e:
                print(f"⚠️  Failed to sync point shop for {guild_name} (guild_id={guild_id}): {e}")
                import traceback

                traceback.print_exc()

        elif action == "update_settings":
            print(f"✅ Point settings updated: {data}")
            # Settings are stored in DB, no action needed here

        elif action == "item_update":
            item_id = data.get("item_id")
            item_name = data.get("item_name")
            update_type = data.get("type", "update")  # create, update, delete
            guild_id = data.get("discord_server_id")
            print(f"✅ Point shop item {update_type}: {item_name} (ID: {item_id})")

            # Auto-update the shop message when items change
            try:
                from bot import post_point_shop_to_discord

                success = await post_point_shop_to_discord(self.bot, guild_id=guild_id, update_existing=True)
                if success:
                    print("✅ Point shop message auto-updated")
                else:
                    print("⚠️ Could not auto-update point shop (no channel configured?)")
            except Exception as e:
                print(f"⚠️ Failed to auto-update point shop: {e}")
                import traceback

                traceback.print_exc()

        elif action == "sale_status_updated":
            # Update the previously posted order notification message, if we have its message ID.
            try:
                sale_id = data.get("sale_id")
                new_status = data.get("new_status")
                if not sale_id or not new_status:
                    return

                if engine is None:
                    print("[Point Shop] DB engine not available; cannot update order message")
                    return

                with engine.connect() as conn:
                    row = conn.execute(
                        text(
                            """
                        SELECT discord_notification_channel_id, discord_notification_message_id
                        FROM point_sales
                        WHERE id = :sale_id
                    """
                        ),
                        {"sale_id": int(sale_id)},
                    ).fetchone()

                if not row or not row[0] or not row[1]:
                    print(f"[Point Shop] No stored Discord message for sale_id={sale_id}; skipping update")
                    return

                channel_id = int(row[0])
                message_id = int(row[1])

                channel = self.bot.get_channel(channel_id)
                if not channel:
                    print(f"[Point Shop] Channel not found for update: {channel_id}")
                    return

                try:
                    message = await channel.fetch_message(message_id)
                except Exception as e:
                    print(f"[Point Shop] Failed to fetch order message {message_id}: {e}")
                    return

                status_lower = str(new_status).lower()
                if status_lower == "completed":
                    color = discord.Color.green()
                    status_label = "Completed"
                elif status_lower == "cancelled":
                    color = discord.Color.red()
                    status_label = "Cancelled"
                else:
                    color = discord.Color.purple()
                    status_label = "Pending"

                embed = message.embeds[0] if message.embeds else discord.Embed(title="🛒 Point Shop Order", color=color)
                embed.color = color

                # Update (or add) the Status field
                status_field_index = None
                for i, f in enumerate(embed.fields):
                    if (f.name or "").strip().lower() == "status":
                        status_field_index = i
                        break
                if status_field_index is None:
                    embed.add_field(name="Status", value=status_label, inline=True)
                else:
                    embed.set_field_at(status_field_index, name="Status", value=status_label, inline=True)

                await message.edit(embed=embed)
                print(f"✅ Updated order embed for sale_id={sale_id} to status={status_lower}")
            except Exception as e:
                print(f"[Point Shop] Failed to update order message for status change: {e}")
                import traceback

                traceback.print_exc()

    async def handle_notifications_event(self, action, data):
        """Handle notifications events from dashboard and forward to Discord if configured."""
        try:
            if action != "new_notification":
                return

            notif_type = data.get("type")
            if notif_type != "new_sale":
                return

            source_server_id = data.get("discord_server_id")
            if not source_server_id:
                return

            try:
                source_server_id_int = int(source_server_id)
            except Exception:
                return

            notif_data = data.get("data") or {}

            if engine is None:
                print("[Notifications] DB engine not available; cannot lookup point_settings")
                return

            # Lookup target channel (and optional target server) from point_settings
            with engine.connect() as conn:
                notify_channel_row = conn.execute(
                    text(
                        """
                    SELECT value FROM point_settings
                    WHERE key = 'shop_notification_channel_id' AND discord_server_id = :guild_id
                """
                    ),
                    {"guild_id": source_server_id_int},
                ).fetchone()
                notify_channel_id = int(notify_channel_row[0]) if notify_channel_row and notify_channel_row[0] else None

                notify_server_row = conn.execute(
                    text(
                        """
                    SELECT value FROM point_settings
                    WHERE key = 'shop_order_notify_server_id' AND discord_server_id = :guild_id
                """
                    ),
                    {"guild_id": source_server_id_int},
                ).fetchone()
                notify_server_id = (
                    int(notify_server_row[0]) if notify_server_row and notify_server_row[0] else source_server_id_int
                )

            if not notify_channel_id:
                return

            channel = self.bot.get_channel(notify_channel_id)
            if not channel:
                guild = self.bot.get_guild(notify_server_id)
                channel = guild.get_channel(notify_channel_id) if guild else None

            if not channel:
                print(f"[Notifications] Channel not found: {notify_channel_id} (notify_server_id={notify_server_id})")
                return

            buyer = notif_data.get("buyer") or notif_data.get("username") or "Unknown"
            item_name = notif_data.get("item_name") or "Unknown"
            price = notif_data.get("price")
            sale_id = notif_data.get("sale_id")
            requirement_title = notif_data.get("requirement_title")
            requirement_footer = notif_data.get("requirement_footer")
            requirement_input = notif_data.get("requirement_input") or notif_data.get("requirement")
            note = notif_data.get("note")

            embed = discord.Embed(
                title="🛒 New Point Shop Order",
                description=f"**{buyer}** placed an order.",
                color=discord.Color.purple(),
            )

            if sale_id is not None:
                embed.add_field(name="Order ID", value=f"#{sale_id}", inline=True)
            embed.add_field(name="Item", value=str(item_name), inline=True)
            if price is not None:
                try:
                    embed.add_field(name="Price", value=f"{int(price):,} points", inline=True)
                except Exception:
                    embed.add_field(name="Price", value=f"{price} points", inline=True)
            embed.add_field(name="Status", value="Pending", inline=True)

            if requirement_title:
                embed.add_field(name="Requirement Title", value=str(requirement_title)[:1024], inline=False)
            if requirement_footer:
                embed.add_field(name="Requirement Footer", value=str(requirement_footer)[:1024], inline=False)

            details_parts = []
            if requirement_input:
                details_parts.append(str(requirement_input))
            if note:
                details_parts.append(f"Note: {note}")
            if details_parts:
                details = "\n".join(details_parts)
                if len(details) > 1000:
                    details = details[:1000] + "…"
                embed.add_field(name="Details", value=details, inline=False)

            sent_message = await channel.send(embed=embed)

            # Store message mapping so we can edit it on status changes
            try:
                if sale_id is not None and engine is not None:
                    with engine.begin() as conn:
                        conn.execute(
                            text(
                                """
                            UPDATE point_sales
                            SET discord_notification_channel_id = :channel_id,
                                discord_notification_message_id = :message_id
                            WHERE id = :sale_id
                        """
                            ),
                            {
                                "channel_id": int(channel.id),
                                "message_id": int(sent_message.id),
                                "sale_id": int(sale_id),
                            },
                        )
            except Exception as e:
                print(f"[Notifications] WARN: failed to store sale->message mapping: {e}")
        except Exception as e:
            print(f"[Notifications] Failed to forward notification: {e}")
            import traceback

            traceback.print_exc()

    async def handle_bot_settings_event(self, action, data):
        """Handle bot settings events from dashboard"""
        print(f"📥 Bot Settings Event: {action}")

        if action == "sync":
            # Refresh bot settings from database
            if hasattr(self.bot, "settings_manager") and self.bot.settings_manager:
                try:
                    self.bot.settings_manager.refresh()
                    print("✅ Bot settings refreshed from database")

                    # Log the updated values
                    settings = self.bot.settings_manager
                    print(f"   • kick_channel: {settings.kick_channel}")
                    print(f"   • kick_chatroom_id: {settings.kick_chatroom_id}")
                    print(f"   • slot_calls_channel_id: {settings.slot_calls_channel_id}")
                    print(f"   • raffle_auto_draw: {settings.raffle_auto_draw}")
                    print(f"   • raffle_announcement_channel_id: {settings.raffle_announcement_channel_id}")
                    print(f"   • raffle_leaderboard_channel_id: {settings.raffle_leaderboard_channel_id}")

                    # Update bot attributes for channel IDs that can be hot-reloaded
                    if settings.slot_calls_channel_id:
                        self.bot.slot_calls_channel_id = int(settings.slot_calls_channel_id)
                        print(f"   ✓ Updated bot.slot_calls_channel_id")
                    if settings.raffle_announcement_channel_id:
                        self.bot.raffle_announcement_channel_id = int(settings.raffle_announcement_channel_id)
                        print(f"   ✓ Updated bot.raffle_announcement_channel_id")
                    if settings.raffle_leaderboard_channel_id:
                        self.bot.raffle_leaderboard_channel_id = int(settings.raffle_leaderboard_channel_id)
                        print(f"   ✓ Updated bot.raffle_leaderboard_channel_id")

                    # Note: KICK_CHANNEL and KICK_CHATROOM_ID require bot restart
                    # as they're used in the kick_chat_loop that runs continuously
                    if settings.kick_channel:
                        print(f"   ⚠️ kick_channel updated - bot restart required for Kick chat to use new channel")

                except Exception as e:
                    print(f"⚠️ Failed to refresh bot settings: {e}")
                    import traceback

                    traceback.print_exc()
            else:
                print("⚠️ Bot settings manager not initialized")

        elif action == "update":
            key = data.get("key")
            value = data.get("value")
            print(f"✅ Bot setting updated: {key} = {value}")

            # Refresh settings to pick up the change
            if hasattr(self.bot, "settings_manager") and self.bot.settings_manager:
                try:
                    self.bot.settings_manager.refresh()
                    print("✅ Bot settings refreshed after update")
                except Exception as e:
                    print(f"⚠️ Failed to refresh bot settings: {e}")

        elif action == "reload":
            # Profile settings were updated - refresh for specific guild or all
            guild_id = data.get("guild_id")
            print(f"✅ Reload request for guild: {guild_id}")
            # Settings will be reloaded automatically on next access

    async def handle_giveaway_event(self, action, data):
        """Handle giveaway events from dashboard"""
        print(f"🎁 Giveaway event: {action}")

        try:
            guild_id = data.get("discord_server_id")
            giveaway_id = data.get("giveaway_id")

            if not guild_id:
                print("⚠️ No guild_id in giveaway event")
                return

            # Convert guild_id to int (may come as string from JSON)
            guild_id = int(guild_id)

            # Get giveaway manager for this guild
            if not hasattr(self.bot, "giveaway_managers"):
                print("⚠️ Giveaway managers not initialized on bot")
                return

            giveaway_manager = self.bot.giveaway_managers.get(guild_id)
            if not giveaway_manager:
                print(f"⚠️ No giveaway manager found for guild {guild_id}")
                print(f"   Available guilds: {list(self.bot.giveaway_managers.keys())}")
                return

            guild = self.bot.get_guild(guild_id)
            guild_name = guild.name if guild else str(guild_id)

            if action == "giveaway_started":
                print(f"[{guild_name}] ▶️  Starting giveaway {giveaway_id} for guild {guild_id}")

                # Reload active giveaway from database
                await giveaway_manager.load_active_giveaway()

                if giveaway_manager.active_giveaway:
                    giveaway_title = giveaway_manager.active_giveaway.get("title", "New Giveaway")
                    entry_method = giveaway_manager.active_giveaway.get("entry_method", "keyword")

                    # Announce in Discord
                    if hasattr(self.bot, "settings_manager"):
                        announcement_channel_id = getattr(
                            self.bot.settings_manager, "raffle_announcement_channel_id", None
                        )
                        if announcement_channel_id:
                            channel = self.bot.get_channel(announcement_channel_id)
                            if channel:
                                import discord

                                embed = discord.Embed(
                                    title="🎁 New Giveaway Started!", description=giveaway_title, color=0x00FF00
                                )

                                if entry_method == "keyword":
                                    keyword = giveaway_manager.active_giveaway.get("keyword", "")
                                    embed.add_field(
                                        name="How to Enter", value=f"Type `{keyword}` in Kick chat!", inline=False
                                    )
                                elif entry_method == "active_chatter":
                                    messages_required = giveaway_manager.active_giveaway.get("messages_required", 10)
                                    time_window = giveaway_manager.active_giveaway.get("time_window_minutes", 10)
                                    embed.add_field(
                                        name="How to Enter",
                                        value=f"Send {messages_required} unique messages in {time_window} minutes in Kick chat!",
                                        inline=False,
                                    )

                                allow_multiple = giveaway_manager.active_giveaway.get("allow_multiple_entries", False)
                                if allow_multiple:
                                    max_entries = giveaway_manager.active_giveaway.get("max_entries_per_user", 5)
                                    embed.add_field(
                                        name="Multiple Entries",
                                        value=f"You can enter up to {max_entries} times!",
                                        inline=False,
                                    )

                                await channel.send(embed=embed)
                                print(f"[{guild_name}] ✅ Announced giveaway start in Discord")

                    # Announce in Kick chat
                    if self.send_message_callback:
                        if entry_method == "keyword":
                            keyword = giveaway_manager.active_giveaway.get("keyword", "")
                            message = f"🎁 GIVEAWAY STARTED: {giveaway_title} | Type {keyword} to enter!"
                        else:
                            message = f"🎁 GIVEAWAY STARTED: {giveaway_title} | Be active in chat to enter!"

                        await self.announce_in_chat(message, guild_id=guild_id)
                        print(f"[{guild_name}] ✅ Announced giveaway start in Kick chat")

                    print(f"[{guild_name}] ✅ Giveaway {giveaway_id} started: {giveaway_title}")

            elif action == "giveaway_stopped":
                print(f"[{guild_name}] ⏹️  Stopping giveaway {giveaway_id} for guild {guild_id}")

                # Clear active giveaway
                giveaway_manager.active_giveaway = None
                print(f"[{guild_name}] ✅ Giveaway {giveaway_id} stopped")

                # Announce in Kick chat
                if self.send_message_callback:
                    await self.announce_in_chat("🎁 Giveaway has been stopped by moderators.", guild_id=guild_id)

            elif action == "giveaway_winner":
                winner = data.get("winner_username")
                giveaway_title = data.get("giveaway_title", "Giveaway")
                delay_announcement = data.get("delay_announcement", False)

                if not winner:
                    print("⚠️ No winner in giveaway_winner event")
                    return

                print(f"[{guild_name}] 🎉 Winner drawn: {winner}")

                # If delay requested, wait 7 seconds for OBS animation to complete (6s animation + 1s buffer)
                if delay_announcement:
                    print(f"[{guild_name}] ⏳ Waiting 7 seconds for animation to complete...")
                    await asyncio.sleep(7)

                # Announce in Discord
                if hasattr(self.bot, "settings_manager"):
                    announcement_channel_id = getattr(self.bot.settings_manager, "raffle_announcement_channel_id", None)
                    if announcement_channel_id:
                        channel = self.bot.get_channel(announcement_channel_id)
                        if channel:
                            import discord

                            embed = discord.Embed(
                                title="🎉 Giveaway Winner!", description=f"**{giveaway_title}**", color=0xFFD700
                            )
                            embed.add_field(name="Winner", value=f"🏆 **{winner}**", inline=False)
                            embed.add_field(name="", value="Congratulations! 🎊", inline=False)

                            await channel.send(embed=embed)
                            print(f"[{guild_name}] ✅ Announced giveaway winner in Discord: {winner}")

                # Announce in Kick chat
                if self.send_message_callback:
                    message = f"🎉 GIVEAWAY WINNER: @{winner} won {giveaway_title}! Congratulations! 🎊"
                    await self.announce_in_chat(message, guild_id=guild_id)
                    print(f"[{guild_name}] ✅ Announced giveaway winner in Kick chat: {winner}")

                # Clear active giveaway
                giveaway_manager.active_giveaway = None

        except Exception as e:
            print(f"❌ Error handling giveaway event: {e}")
            import traceback

            traceback.print_exc()

    async def handle_stream_notification_event(self, action, data):
        """Handle stream notification events from dashboard - send Discord message when stream goes live"""
        print(f"📺 Stream notification event: {action}")

        try:
            if action != "send":
                return

            channel_id = data.get("channel_id")
            streamer = data.get("streamer")
            discord_server_id = data.get("discord_server_id")
            is_test = data.get("test", False)

            if not channel_id or not streamer:
                print("⚠️ Missing channel_id or streamer in stream notification event")
                return

            import os

            import aiohttp

            stream_url = f"https://kick.com/{streamer}"
            # Use clkick.com for Discord video embed (proxy with proper oEmbed)
            embed_url = f"https://clkick.com/{streamer}"

            bot_token = os.getenv("DISCORD_TOKEN")

            if not bot_token:
                print("❌ DISCORD_TOKEN not configured")
                return

            # Fetch custom title, description, link text, and small text setting from database
            custom_title = None
            custom_description = None
            custom_link_text = None
            link_small = False
            custom_footer = None

            if discord_server_id and engine:
                try:
                    from sqlalchemy import text

                    with engine.connect() as conn:
                        result = conn.execute(
                            text(
                                """
                            SELECT key, value FROM bot_settings
                            WHERE discord_server_id = :guild_id
                            AND key IN ('stream_notification_title', 'stream_notification_description',
                                        'stream_notification_link_text', 'stream_notification_link_small',
                                        'stream_notification_footer')
                        """
                            ),
                            {"guild_id": discord_server_id},
                        ).fetchall()

                        for key, value in result:
                            if key == "stream_notification_title" and value:
                                custom_title = value
                            elif key == "stream_notification_description" and value:
                                custom_description = value
                            elif key == "stream_notification_link_text" and value:
                                custom_link_text = value
                            elif key == "stream_notification_link_small":
                                link_small = value == "true"
                            elif key == "stream_notification_footer" and value:
                                custom_footer = value
                except Exception as db_err:
                    print(f"⚠️ Failed to fetch notification settings: {db_err}")

            # Replace placeholders in custom title/description
            def replace_placeholders(text):
                if not text:
                    return text
                return text.replace("{streamer}", streamer).replace("{channel}", streamer)

            # Build message content using Discord markdown hyperlink to hide URL
            # Format: [Link Text](URL) - Discord may still show embed from oEmbed
            # Use -# prefix for small/subtext format if enabled
            link_text = custom_link_text or "Watch Preview"
            hidden_link = f"[{link_text}]({embed_url})"
            if link_small:
                hidden_link = f"-# {hidden_link}"

            if custom_title:
                title_text = replace_placeholders(custom_title)
            else:
                title_text = f"🔴 **{streamer}** is now LIVE on Kick!"

            if custom_description:
                desc_text = replace_placeholders(custom_description)
                message_content = f"{title_text}\n{desc_text}\n{hidden_link}"
            else:
                message_content = f"{title_text}\n{hidden_link}"

            # Add footer if set (appears after the button in the message)
            footer_text = None
            if custom_footer:
                footer_text = replace_placeholders(custom_footer)

            # Discord button component for "Watch Stream"
            components = [
                {
                    "type": 1,
                    "components": [
                        {"type": 2, "style": 5, "label": "Watch Stream", "url": stream_url, "emoji": {"name": "🔴"}}
                    ],
                }
            ]

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"https://discord.com/api/v10/channels/{channel_id}/messages",
                    headers={"Authorization": f"Bot {bot_token}", "Content-Type": "application/json"},
                    json={"content": message_content, "components": components},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status in [200, 201]:
                        # If footer is set, send it as a follow-up message
                        if footer_text:
                            await asyncio.sleep(0.5)
                            async with session.post(
                                f"https://discord.com/api/v10/channels/{channel_id}/messages",
                                headers={"Authorization": f"Bot {bot_token}", "Content-Type": "application/json"},
                                json={"content": f"-# {footer_text}"},
                                timeout=aiohttp.ClientTimeout(total=10),
                            ) as footer_resp:
                                if footer_resp.status not in [200, 201]:
                                    print(f"⚠️ Failed to send footer: {footer_resp.status}")

                        test_label = " (TEST)" if is_test else ""
                        print(f"✅ Discord stream notification sent to channel {channel_id}{test_label}")
                    else:
                        error_text = await resp.text()
                        print(f"❌ Failed to send Discord notification: {resp.status} - {error_text[:200]}")

        except Exception as e:
            print(f"❌ Error handling stream notification event: {e}")
            import traceback

            traceback.print_exc()

    async def announce_in_chat(self, message, guild_id=None):
        """Send a message to the Kick chat"""
        try:
            if self.send_message_callback:
                success = await self.send_message_callback(message, guild_id=guild_id)
                if success:
                    print(f"💬 Sent to Kick chat: {message}")
                else:
                    print(f"⚠️ Failed to send to Kick chat: {message}")
            else:
                print(f"💬 [No Kick callback] Would announce: {message}")
        except Exception as e:
            print(f"❌ Error sending to Kick chat: {e}")

    async def announce_raffle_winners(self, winners, prize_description, guild_id=None):
        """Announce raffle winner(s) to Discord raffle announcement channel

        Args:
            winners: List of winner data dicts
            prize_description: Description of the prize
            guild_id: Server ID for multi-server support (optional)
        """
        try:
            channel_id = None

            # Multi-server: Get channel from guild-specific settings
            if guild_id:
                try:
                    # Import get_guild_settings directly from bot module
                    from bot import get_guild_settings

                    guild_settings = get_guild_settings(int(guild_id))
                    if guild_settings:
                        channel_id = guild_settings.get_int("raffle_announcement_channel_id")
                        print(f"[Raffle] Got channel_id {channel_id} from guild settings for guild {guild_id}")
                except ImportError as ie:
                    print(f"[Raffle] Could not import get_guild_settings: {ie}")
                except Exception as e:
                    print(f"[Raffle] Error getting guild settings: {e}")

            # Fallback to global settings manager
            if not channel_id and hasattr(self.bot, "settings_manager"):
                channel_id = self.bot.settings_manager.get_int("raffle_announcement_channel_id")
                if channel_id:
                    print(f"[Raffle] Got channel_id {channel_id} from global settings_manager")

            if not channel_id:
                print(f"⚠️ Raffle announcement channel not configured for server {guild_id}, skipping announcement")
                return

            channel = self.bot.get_channel(channel_id)
            if not channel:
                # Try to fetch the channel if not in cache
                try:
                    channel = await self.bot.fetch_channel(channel_id)
                except Exception as e:
                    print(f"⚠️ Raffle announcement channel {channel_id} not found: {e}")
                    return

            # Single or multiple winners
            if len(winners) == 1:
                winner = winners[0]

                # Safely get winner data with defaults
                winner_discord_id = winner.get("winner_discord_id")
                winner_kick_name = winner.get("winner_kick_name", "Unknown")
                winning_ticket = winner.get("winning_ticket", "?")
                total_tickets = winner.get("total_tickets", 0)
                win_probability = winner.get("win_probability", 0)

                # Try to mention winner
                if winner_discord_id:
                    try:
                        discord_user = await self.bot.fetch_user(winner_discord_id)
                        mention = discord_user.mention
                    except:
                        mention = f"Discord ID: {winner_discord_id}"
                else:
                    mention = "Unknown User"

                message = f"""
🎉 **RAFFLE WINNER DRAWN!** 🎉

**Winner**: {winner_kick_name} ({mention})
**Winning Ticket**: #{winning_ticket} out of {total_tickets:,}
**Win Probability**: {win_probability:.2f}%
**Prize**: {prize_description or 'Monthly Raffle Prize'}

Congratulations! Please contact an admin to claim your prize! 🎊
                """.strip()

                await channel.send(message)
                print(f"✅ Raffle winner announced in Discord channel {channel_id}")
            else:
                # Multiple winners
                message = (
                    f"🎉 **RAFFLE WINNERS DRAWN!** 🎉\n\n**Prize**: {prize_description or 'Monthly Raffle Prize'}\n\n"
                )

                for i, winner in enumerate(winners, 1):
                    # Safely get winner data with defaults
                    winner_discord_id = winner.get("winner_discord_id")
                    winner_kick_name = winner.get("winner_kick_name", "Unknown")
                    winning_ticket = winner.get("winning_ticket", "?")
                    total_tickets = winner.get("total_tickets", 0)
                    win_probability = winner.get("win_probability", 0)

                    if winner_discord_id:
                        try:
                            discord_user = await self.bot.fetch_user(winner_discord_id)
                            mention = discord_user.mention
                        except:
                            mention = f"Discord ID: {winner_discord_id}"
                    else:
                        mention = "Unknown User"

                    message += f"**{i}. {winner_kick_name}** ({mention})\n"
                    message += f"   • Ticket #{winning_ticket}/{total_tickets:,} ({win_probability:.2f}%)\n\n"

                message += "Congratulations to all winners! Please contact an admin to claim your prizes! 🎊"

                await channel.send(message)
                print(f"✅ {len(winners)} raffle winners announced in Discord channel {channel_id}")

        except Exception as e:
            print(f"❌ Error announcing raffle winners to Discord: {e}")
            import traceback

            traceback.print_exc()

    async def listen(self):
        """Listen for events on all dashboard channels"""
        if not self.enabled:
            print("Redis subscriber not enabled, skipping...")
            return

        # Subscribe to all dashboard channels (webhook events disabled - using direct WebSocket)
        await asyncio.to_thread(
            self.pubsub.subscribe,
            "dashboard:slot_requests",
            "dashboard:timed_messages",
            "dashboard:gtb",
            "dashboard:management",
            "dashboard:raffle",
            "dashboard:commands",
            "dashboard:point_shop",
            "dashboard:notifications",
            "dashboard:bot_settings",
            "dashboard:giveaway",
            "dashboard:stream_notification",
            # 'bot_events' removed - no longer using webhooks for chat
        )

        print("🎧 Redis subscriber listening for dashboard events...")

        while True:
            try:
                # Run blocking listen() in a thread to avoid blocking event loop
                message = await asyncio.to_thread(self.pubsub.get_message, timeout=1.0)

                if message and message["type"] == "message":
                    channel = message["channel"]
                    try:
                        payload = json.loads(message["data"])
                        action = payload.get("action")
                        data = payload.get("data", {})

                        # Route to appropriate handler
                        if channel == "dashboard:slot_requests":
                            await self.handle_slot_requests_event(action, data)
                        elif channel == "dashboard:timed_messages":
                            await self.handle_timed_messages_event(action, data)
                        elif channel == "dashboard:gtb":
                            await self.handle_gtb_event(action, data)
                        elif channel == "dashboard:management":
                            await self.handle_management_event(action, data)
                        elif channel == "dashboard:raffle":
                            await self.handle_raffle_event(action, data)
                        elif channel == "dashboard:commands":
                            await self.handle_commands_event(action, data)
                        elif channel == "dashboard:point_shop":
                            await self.handle_point_shop_event(action, data)
                        elif channel == "dashboard:notifications":
                            await self.handle_notifications_event(action, data)
                        elif channel == "dashboard:bot_settings":
                            await self.handle_bot_settings_event(action, data)
                        elif channel == "dashboard:giveaway":
                            await self.handle_giveaway_event(action, data)
                        elif channel == "dashboard:stream_notification":
                            await self.handle_stream_notification_event(action, data)
                        # elif channel == 'bot_events':  # Disabled - using direct WebSocket
                        #     await self.handle_webhook_event(payload)

                    except json.JSONDecodeError as e:
                        print(f"Failed to decode message: {e}")
                    except Exception as e:
                        print(f"Error handling message: {e}")

                # Small delay to prevent busy loop
                await asyncio.sleep(0.01)

            except Exception as e:
                print(f"Redis listener error: {e}")
                # Reconnect after delay
                await asyncio.sleep(5)
                if self.enabled:
                    # Resubscribe after error
                    await asyncio.to_thread(
                        self.pubsub.subscribe,
                        "dashboard:slot_requests",
                        "dashboard:timed_messages",
                        "dashboard:gtb",
                        "dashboard:management",
                        "dashboard:raffle",
                        "dashboard:commands",
                        "dashboard:point_shop",
                        "dashboard:notifications",
                        "dashboard:bot_settings",
                        "dashboard:giveaway",
                        "dashboard:stream_notification",
                        # 'bot_events' removed - no longer using webhooks
                    )


async def start_redis_subscriber(bot, send_message_callback=None):
    """
    Start the Redis subscriber in the background with retry logic.

    Args:
        bot: Discord bot instance
        send_message_callback: Async function to send messages to Kick chat (e.g., send_kick_message)
    """
    subscriber = RedisSubscriber(bot, send_message_callback)

    if subscriber.enabled:
        # Auto-sync point shop embeds on bot startup for all guilds
        print("🔄 Auto-syncing point shop embeds on startup...")
        for guild in bot.guilds:
            try:
                from bot import post_point_shop_to_discord

                await post_point_shop_to_discord(bot, guild_id=guild.id, update_existing=True)
                print(f"✅ Synced shop for {guild.name} (ID: {guild.id})")
            except ImportError:
                print(f"⚠️  post_point_shop_to_discord not available - skipping auto-sync for {guild.name}")
                break  # Don't try other guilds if function doesn't exist
            except Exception as e:
                print(f"⚠️  Failed to auto-sync shop for {guild.name}: {e}")

        # Run the listener with automatic retry on connection failures
        retry_delay = 5
        max_delay = 60
        while True:
            try:
                await subscriber.listen()
            except Exception as e:
                print(f"⚠️  Redis subscriber error: {e} — retrying in {retry_delay}s", flush=True)
                # Fully recreate the Redis client and pubsub for a clean reconnect
                try:
                    subscriber.pubsub.close()
                except Exception:
                    pass
                try:
                    subscriber.client.close()
                except Exception:
                    pass
                try:
                    subscriber.client = redis.from_url(
                        subscriber.redis_url,
                        decode_responses=True,
                        socket_connect_timeout=5,
                        socket_timeout=5,
                    )
                    subscriber.pubsub = subscriber.client.pubsub()
                    subscriber.enabled = True
                    print("🔄 Redis subscriber client recreated", flush=True)
                except Exception as re:
                    print(f"⚠️  Failed to recreate Redis client: {re}", flush=True)
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, max_delay)
            else:
                # listen() returned normally (shouldn't happen), reset delay
                retry_delay = 5
    else:
        print("⚠️  Redis subscriber disabled, bot will poll database instead")


# Example integration in your bot's main file:
"""
import asyncio
from redis_subscriber import start_redis_subscriber

# After your bot is defined and ready
@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')

    # Start Redis subscriber for dashboard events
    asyncio.create_task(start_redis_subscriber(bot))

    # Your other startup tasks...
"""
