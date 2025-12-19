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

import redis
import json
import os
import asyncio
from datetime import datetime
import time

class RedisSubscriber:
    def __init__(self, bot, send_message_callback=None):
        self.bot = bot
        self.send_message_callback = send_message_callback
        self.redis_url = os.getenv('REDIS_URL')
        self.enabled = False
        self.last_shop_sync = 0  # Timestamp for debouncing shop sync

        if self.redis_url:
            if '://' not in self.redis_url:
                self.redis_url = f'redis://{self.redis_url}'
            try:
                self.client = redis.from_url(self.redis_url, decode_responses=True)
                self.pubsub = self.client.pubsub()
                self.enabled = True
                print("✅ Redis subscriber initialized")
            except Exception as e:
                print("⚠️  Redis unavailable: {e}")
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
                if guild_id is None and hasattr(self.bot, 'guilds') and self.bot.guilds:
                    guild_id = self.bot.guilds[0].id
                
                await self.send_message_callback(message, guild_id=guild_id)
                print(f"💬 Sent to Kick chat: {message}")
            except Exception as e:
                print(f"ℹ️  Kick chat message not sent (configure Kick channel in dashboard): {message}")
        else:
            print(f"ℹ️  Kick chat disabled: {message}")

    # ❌ WEBHOOK HANDLING DISABLED - Using direct Pusher WebSocket instead
    # async def handle_webhook_event(self, payload):
    #     """Handle Kick webhook events forwarded via Redis"""
    #     try:
    #         event_type = payload.get('type')
    #         if event_type != 'kick_chat_message':
    #             return
            
            data = payload.get('data', {})
            channel_slug = data.get('channel_slug', '')
            username = data.get('username', '')
            content = data.get('content', '')
            
            # Import bot utilities
            from bot import send_kick_message, engine, parse_amount, active_viewers_by_guild, last_chat_activity_by_guild, recent_chatters_by_guild, bot
            from sqlalchemy import text
            from datetime import datetime, timezone
            
            # Use guild_id from webhook routing (already looked up in kick_webhooks.py)
            guild_id = data.get('_server_id')
            
            # Get guild name for logging
            guild_name = "Unknown"
            if guild_id:
                guild = bot.get_guild(guild_id)
                guild_name = guild.name if guild else str(guild_id)
            
            if not guild_id:
                # Fallback: Lookup guild_id from channel_slug (shouldn't happen with webhooks)
                with engine.connect() as conn:
                    result = conn.execute(text("""
                        SELECT discord_server_id FROM servers
                        WHERE kick_channel = :channel_slug
                        LIMIT 1
                    """), {"channel_slug": channel_slug}).fetchone()
                    
                    if result:
                        guild_id = result[0]
                        guild = bot.get_guild(guild_id)
                        guild_name = guild.name if guild else str(guild_id)
                        print(f"[{guild_name}] 🎯 Webhook: Matched via channel lookup")
                    else:
                        print(f"[Webhook] ⚠️ No server found for channel: {channel_slug}")
                        return
            
            print(f"[{guild_name}] 💬 Webhook: {username}: {content}")
            
            # ✅ UPDATE ACTIVE VIEWERS FOR WATCHTIME TRACKING
            if username:
                now = datetime.now(timezone.utc)
                username_lower = username.lower()
                
                # Update last chat activity for this guild
                last_chat_activity_by_guild[guild_id] = now
                
                # Track per-guild active viewers
                guild_active_viewers = active_viewers_by_guild.get(guild_id, {})
                is_new_viewer = username_lower not in guild_active_viewers
                guild_active_viewers[username_lower] = now
                active_viewers_by_guild[guild_id] = guild_active_viewers
                
                # Track per-guild recent chatters for stream-live detection
                guild_recent_chatters = recent_chatters_by_guild.get(guild_id, {})
                guild_recent_chatters[username_lower] = now
                recent_chatters_by_guild[guild_id] = guild_recent_chatters
                
                print(f"[{guild_name}] ✅ Webhook: Updated active viewers: {username_lower} (total: {len(guild_active_viewers)})")
                if is_new_viewer:
                    print(f"[{guild_name}] 🆕 Webhook: New viewer tracked: {username_lower}")
            
            content_stripped = content.strip()
            username_lower = username.lower()
            
            # Check for custom commands first
            if hasattr(self.bot, 'custom_commands_manager') and self.bot.custom_commands_manager:
                try:
                    original_guild_id = getattr(self.bot.custom_commands_manager, 'discord_server_id', None)
                    original_callback = self.bot.custom_commands_manager.send_message_callback
                    
                    # Set guild context
                    self.bot.custom_commands_manager.discord_server_id = guild_id
                    self.bot.custom_commands_manager.send_message_callback = lambda msg: send_kick_message(msg, guild_id=guild_id)
                    
                    handled = await self.bot.custom_commands_manager.handle_message(content, username)
                    
                    # Restore
                    self.bot.custom_commands_manager.discord_server_id = original_guild_id
                    self.bot.custom_commands_manager.send_message_callback = original_callback
                    
                    if handled:
                        print(f"[Redis] ✅ Custom command handled")
                        return
                except Exception as e:
                    print(f"[Redis] ⚠️ Custom command error: {e}")
            
            # Handle slot commands
            if hasattr(self.bot, 'slot_call_tracker') and self.bot.slot_call_tracker and (content_stripped.startswith("!call") or content_stripped.startswith("!sr")):
                # Set guild context for slot tracker
                original_guild_id = getattr(self.bot.slot_call_tracker, 'discord_server_id', None)
                print(f"[REDIS DEBUG] Setting slot_call_tracker.discord_server_id to: {guild_id}")
                self.bot.slot_call_tracker.discord_server_id = guild_id
                
                try:
                    # Check if slot requests are enabled for this guild
                    if not self.bot.slot_call_tracker.is_enabled():
                        await send_kick_message(f"@{username} Slot requests are not open at the moment.", guild_id=guild_id)
                        print(f"[Redis] ❌ Slot requests disabled - rejected {username}'s request")
                        return
                    
                    # Check blacklist
                    is_blacklisted = False
                    with engine.begin() as check_conn:
                        result = check_conn.execute(text("""
                            SELECT 1 FROM slot_call_blacklist 
                            WHERE kick_username = :username AND discord_server_id = :guild_id
                        """), {"username": username_lower, "guild_id": guild_id}).fetchone()
                        is_blacklisted = result is not None
                    
                    if not is_blacklisted:
                        slot_call = content_stripped[5:].strip()[:200] if content_stripped.startswith("!call") else content_stripped[3:].strip()[:200]
                        
                        if slot_call:
                            await self.bot.slot_call_tracker.handle_slot_call(username, slot_call)
                            print(f"[Redis] ✅ Slot call processed")
                        else:
                            await send_kick_message(f"@{username} Please specify a slot!", guild_id=guild_id)
                finally:
                    if original_guild_id:
                        self.bot.slot_call_tracker.discord_server_id = original_guild_id
            
            # Handle !raffle
            elif content_stripped.lower() == "!raffle":
                await send_kick_message(
                    "Do you want to win a $100 super buy on Sweet Bonanza 1000? "
                    "All you gotta do is join my discord, verify with lelebot and follow the instructions -> "
                    "https://discord.gg/k7CXJtfrPY",
                    guild_id=guild_id
                )
                print(f"[Redis] ✅ Raffle message sent")
            
            # Handle !gtb
            elif content_stripped.lower().startswith("!gtb"):
                if hasattr(self.bot, 'gtb_manager') and hasattr(self.bot, 'slot_call_tracker'):
                    # Check if slot requests are enabled (GTB is part of slot system)
                    original_guild_id = getattr(self.bot.slot_call_tracker, 'discord_server_id', None)
                    self.bot.slot_call_tracker.discord_server_id = guild_id
                    
                    try:
                        if not self.bot.slot_call_tracker.is_enabled():
                            await send_kick_message(f"@{username} Slot requests are not open at the moment.", guild_id=guild_id)
                            print(f"[Redis] ❌ GTB disabled - rejected {username}'s guess")
                            return
                        
                        parts = content_stripped.split(maxsplit=1)
                        if len(parts) == 2:
                            amount = parse_amount(parts[1])
                            if amount is not None:
                                success, message = self.bot.gtb_manager.add_guess(username, amount)
                                response = f"@{username} {message}" + (" Good luck! 🎰" if success else "")
                                await send_kick_message(response, guild_id=guild_id)
                            else:
                                await send_kick_message(f"@{username} Invalid amount. Use: !gtb <amount>", guild_id=guild_id)
                        else:
                            await send_kick_message(f"@{username} Usage: !gtb <amount>", guild_id=guild_id)
                        print(f"[Redis] ✅ GTB command processed")
                    finally:
                        if original_guild_id:
                            self.bot.slot_call_tracker.discord_server_id = original_guild_id
            
    #     except Exception as e:
    #         print(f"[Redis] ❌ Webhook event error: {e}")
    #         import traceback
    #         traceback.print_exc()

    async def handle_slot_requests_event(self, action, data):
        """Handle slot request events from dashboard"""
        print(f"📥 Slot Requests Event: {action}")
        
        # Extract discord_server_id from event data
        guild_id = data.get('discord_server_id')

        if action == 'toggle':
            enabled = data.get('enabled')
            # Announce in Kick chat
            if enabled:
                await self.announce_in_chat('✅ Slot requests are now ENABLED! Use !call "slot name" or !sr "slot name"', guild_id=guild_id)
            else:
                await self.announce_in_chat("❌ Slot requests have been DISABLED", guild_id=guild_id)

            # Post update to Discord slot calls channel if available
            if hasattr(self.bot, 'slot_calls_channel_id') and self.bot.slot_calls_channel_id:
                try:
                    channel = self.bot.get_channel(self.bot.slot_calls_channel_id)
                    if channel:
                        emoji = "✅" if enabled else "❌"
                        status = "ENABLED" if enabled else "DISABLED"
                        await channel.send(f"{emoji} **Slot Requests {status}** (changed via dashboard)")
                except Exception as e:
                    print(f"Failed to send Discord notification: {e}")

            # Update tracker enabled state directly
            if hasattr(self.bot, 'slot_call_tracker') and self.bot.slot_call_tracker:
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
            
            # Update panel tracker (if panel exists)
            if hasattr(self.bot, 'slot_request_panel') and self.bot.slot_request_panel:
                try:
                    panel = self.bot.slot_request_panel
                    # Refresh tracker state from database before updating panel
                    if hasattr(panel, 'tracker') and panel.tracker:
                        # Store current server_id and switch to the guild that triggered this event
                        original_server_id = panel.tracker.server_id
                        if guild_id:
                            panel.tracker.server_id = guild_id
                        
                        panel.tracker.enabled = panel.tracker._load_enabled_state()
                        panel.tracker.max_requests_per_user = panel.tracker._load_max_requests()
                        print(f"✅ Updated panel tracker enabled state to: {panel.tracker.enabled} for server {guild_id}")
                        
                        # Restore original server_id
                        if original_server_id:
                            panel.tracker.server_id = original_server_id
                except Exception as e:
                    print(f"⚠️ Failed to update tracker via panel: {e}")
            
            # Update Discord panel (if it exists)
            if hasattr(self.bot, 'slot_request_panel') and self.bot.slot_request_panel:
                try:
                    panel = self.bot.slot_request_panel
                    print(f"🔍 Panel IDs: message_id={panel.panel_message_id}, channel_id={panel.panel_channel_id}")
                    success = await panel.update_panel(force=True)
                    if success:
                        print("✅ Slot request panel updated in Discord")
                    else:
                        print("ℹ️  Slot panel not created yet (Discord admin: use !slotpanel to create)")
                except Exception as e:
                    print(f"⚠️ Failed to update slot panel: {e}")
                    import traceback
                    traceback.print_exc()

        elif action == 'pick':
            slot_id = data.get('id')
            slot_call = data.get('slot_call')
            username = data.get('username')
            guild_id = data.get('discord_server_id')
            # Announce the picked slot in Kick chat
            await self.announce_in_chat(f"🎰 PICKED: {slot_call} (requested by {username})", guild_id=guild_id)

            # Post to Discord
            if hasattr(self.bot, 'slot_calls_channel_id') and self.bot.slot_calls_channel_id:
                try:
                    channel = self.bot.get_channel(self.bot.slot_calls_channel_id)
                    if channel:
                        await channel.send(f"🎰 **PICKED**: {slot_call} (requested by {username})")
                except Exception as e:
                    print(f"Failed to send Discord notification: {e}")

            # Update Discord panel
            if hasattr(self.bot, 'slot_request_panel') and self.bot.slot_request_panel:
                try:
                    panel = self.bot.slot_request_panel
                    # Refresh tracker state from database before updating panel
                    if hasattr(panel, 'tracker') and panel.tracker:
                        panel.tracker.enabled = panel.tracker._load_enabled_state()  # Reload enabled state from DB
                        panel.tracker.max_requests_per_user = panel.tracker._load_max_requests()  # Reload max requests too
                    success = await panel.update_panel(force=True)
                    if success:
                        print("✅ Slot request panel updated in Discord")
                    else:
                        print("ℹ️  Slot panel not created yet (Discord admin: use !slotpanel to create)")
                except Exception as e:
                    print(f"⚠️ Failed to update slot panel: {e}")

        elif action == 'pick_with_reward':
            slot_id = data.get('slot_id')
            slot_call = data.get('slot_call')
            username = data.get('username')
            reward_type = data.get('reward_type')
            reward_amount = data.get('reward_amount')
            guild_id = data.get('discord_server_id')

            # Format reward type for display
            reward_type_display = 'Bonus Buy' if reward_type == 'bonus_buy' else reward_type.capitalize()

            # Announce the picked slot WITH reward in Kick chat
            amount = float(reward_amount)
            await self.announce_in_chat(f"🎰 PICKED: {slot_call} (requested by {username}) 💰 WON ${amount:.2f} {reward_type_display}!", guild_id=guild_id)

            # Post to Discord
            if hasattr(self.bot, 'slot_calls_channel_id') and self.bot.slot_calls_channel_id:
                try:
                    channel = self.bot.get_channel(self.bot.slot_calls_channel_id)
                    if channel:
                        await channel.send(f"🎰 **PICKED**: {slot_call} (requested by {username})\n💰 **WON**: ${amount:.2f} {reward_type_display}!")
                except Exception as e:
                    print(f"Failed to send Discord notification: {e}")

            # Update Discord panel
            if hasattr(self.bot, 'slot_request_panel') and self.bot.slot_request_panel:
                try:
                    panel = self.bot.slot_request_panel
                    # Refresh tracker state from database before updating panel
                    if hasattr(panel, 'tracker') and panel.tracker:
                        panel.tracker.enabled = panel.tracker._load_enabled_state()  # Reload enabled state from DB
                        panel.tracker.max_requests_per_user = panel.tracker._load_max_requests()  # Reload max requests too
                    success = await panel.update_panel(force=True)
                    if success:
                        print("✅ Slot request panel updated in Discord")
                    else:
                        print("ℹ️  Slot panel not created yet (Discord admin: use !slotpanel to create)")
                except Exception as e:
                    print(f"⚠️ Failed to update slot panel: {e}")

        elif action == 'update_max':
            max_requests = data.get('max_requests')
            print(f"Updated max slot requests to {max_requests}")

            # Update Discord panel
            if hasattr(self.bot, 'slot_request_panel') and self.bot.slot_request_panel:
                try:
                    panel = self.bot.slot_request_panel
                    # Refresh tracker state from database before updating panel
                    if hasattr(panel, 'tracker') and panel.tracker:
                        panel.tracker.enabled = panel.tracker._load_enabled_state()  # Reload enabled state from DB
                        panel.tracker.max_requests_per_user = panel.tracker._load_max_requests()  # Reload max requests too
                    success = await panel.update_panel(force=True)
                    if success:
                        print("✅ Slot request panel updated in Discord")
                    else:
                        print("ℹ️  Slot panel not created yet (Discord admin: use !slotpanel to create)")
                except Exception as e:
                    print(f"⚠️ Failed to update slot panel: {e}")

    async def handle_timed_messages_event(self, action, data):
        """Handle timed message events from dashboard"""
        print(f"📥 Timed Messages Event: {action}")
        
        # Extract discord_server_id from event data
        guild_id = data.get('discord_server_id')

        # Reload timed messages from database for the specific guild
        if hasattr(self.bot, 'timed_messages_managers') and guild_id:
            manager = self.bot.timed_messages_managers.get(guild_id)
            if manager:
                try:
                    manager.reload_messages()
                    print(f"✅ Timed messages reloaded for guild {guild_id}")
                except Exception as e:
                    print(f"⚠️ Failed to reload timed messages: {e}")
        elif hasattr(self.bot, 'timed_messages_manager') and self.bot.timed_messages_manager:
            # Fallback for backwards compatibility (single global manager)
            try:
                self.bot.timed_messages_manager.reload_messages()
                print(f"✅ Timed messages reloaded from database")
            except Exception as e:
                print(f"⚠️ Failed to reload timed messages: {e}")

        if action == 'create':
            message_id = data.get('id')
            message = data.get('message')
            interval = data.get('interval_minutes')
            print(f"✅ Created timed message #{message_id}: {message} (every {interval}m)")

        elif action == 'update':
            message_id = data.get('id')
            print(f"✅ Updated timed message #{message_id}")

        elif action == 'delete':
            message_id = data.get('id')
            print(f"✅ Deleted timed message #{message_id}")

        elif action == 'toggle':
            message_id = data.get('id')
            enabled = data.get('enabled')
            status = "enabled" if enabled else "disabled"
            print(f"✅ Timed message #{message_id} {status}")

    async def handle_gtb_event(self, action, data):
        """Handle Guess the Balance events from dashboard"""
        print(f"📥 GTB Event: {action}")
        
        # Extract discord_server_id from event data
        guild_id = data.get('discord_server_id')

        if action == 'open':
            session_id = data.get('session_id')
            opened_by = data.get('opened_by')
            # Announce in Kick chat
            await self.announce_in_chat(f"💰 Guess the Balance session #{session_id} is now OPEN! Use !gtb <amount> to guess!", guild_id=guild_id)

            # Post to Discord GTB channel if available
            if hasattr(self.bot, 'gtb_channel_id') and self.bot.gtb_channel_id:
                try:
                    channel = self.bot.get_channel(self.bot.gtb_channel_id)
                    if channel:
                        await channel.send(f"💰 **GTB Session #{session_id} OPENED** by {opened_by}")
                except Exception as e:
                    print(f"Failed to send Discord notification: {e}")

            # Update Discord GTB panel
            if hasattr(self.bot, 'gtb_panel') and self.bot.gtb_panel:
                try:
                    success = await self.bot.gtb_panel.update_panel(force=True)
                    if success:
                        print("✅ GTB panel updated in Discord")
                    else:
                        print("ℹ️  GTB panel not created yet (Discord admin: use !creategtbpanel to create)")
                except Exception as e:
                    print(f"⚠️ Failed to update GTB panel: {e}")

        elif action == 'close':
            session_id = data.get('session_id')
            # Announce in Kick chat
            await self.announce_in_chat(f"🔒 Guess the Balance session #{session_id} is now CLOSED! No more guesses allowed.", guild_id=guild_id)

            # Post to Discord
            if hasattr(self.bot, 'gtb_channel_id') and self.bot.gtb_channel_id:
                try:
                    channel = self.bot.get_channel(self.bot.gtb_channel_id)
                    if channel:
                        await channel.send(f"🔒 **GTB Session #{session_id} CLOSED** - Guessing is over!")
                except Exception as e:
                    print(f"Failed to send Discord notification: {e}")

            # Update Discord GTB panel
            if hasattr(self.bot, 'gtb_panel') and self.bot.gtb_panel:
                try:
                    success = await self.bot.gtb_panel.update_panel(force=True)
                    if success:
                        print("✅ GTB panel updated in Discord")
                    else:
                        print("ℹ️  GTB panel not created yet (Discord admin: use !creategtbpanel to create)")
                except Exception as e:
                    print(f"⚠️ Failed to update GTB panel: {e}")

        elif action == 'set_result':
            session_id = data.get('session_id')
            result_amount = data.get('result_amount')
            winners = data.get('winners', [])  # Get winners from dashboard

            # Announce result in Kick chat
            await self.announce_in_chat(f"🎉 GTB Result: ${result_amount:,.2f}! Calculating winners...", guild_id=guild_id)

            # If winners were provided by dashboard, use them
            if winners and len(winners) > 0:
                # Small delay to ensure messages don't get combined
                await asyncio.sleep(1)

                # Announce top 3 winners
                winner_messages = []
                for winner in winners[:3]:
                    rank_emoji = "🥇" if winner['rank'] == 1 else "🥈" if winner['rank'] == 2 else "🥉"
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
                if hasattr(self.bot, 'gtb_manager') and self.bot.gtb_manager:
                    try:
                        print(f"🔍 No winners provided, calling set_result with amount: ${result_amount:,.2f}")
                        success, message, calculated_winners = self.bot.gtb_manager.set_result(result_amount)
                        print(f"🔍 set_result returned - success: {success}, message: {message}, winners: {calculated_winners}")

                        if success and calculated_winners and len(calculated_winners) > 0:
                            # Small delay to ensure messages don't get combined
                            await asyncio.sleep(1)

                            # Announce top 3 winners
                            winner_messages = []
                            for winner in calculated_winners[:3]:
                                rank_emoji = "🥇" if winner['rank'] == 1 else "🥈" if winner['rank'] == 2 else "🥉"
                                winner_messages.append(
                                    f"{rank_emoji} {winner['username']}: ${winner['guess']:,.2f} (${winner['difference']:,.2f} off)"
                                )

                            # Announce all winners in one message
                            winner_text = f"🏆 Winners: " + " | ".join(winner_messages)
                            print(f"📢 Announcing winners in Kick chat: {winner_text}")
                            await self.announce_in_chat(winner_text, guild_id=guild_id)
                            print(f"✅ Announced {len(calculated_winners)} GTB winners in Kick chat")
                        else:
                            print(f"⚠️ GTB result set but no winners - success: {success}, message: {message}, winner count: {len(calculated_winners) if calculated_winners else 0}")
                    except Exception as e:
                        print(f"⚠️ Failed to calculate GTB winners: {e}")
                        import traceback
                        traceback.print_exc()
                else:
                    print(f"⚠️ GTB manager not available and no winners provided in message")

            # Post to Discord
            if hasattr(self.bot, 'gtb_channel_id') and self.bot.gtb_channel_id:
                try:
                    channel = self.bot.get_channel(self.bot.gtb_channel_id)
                    if channel:
                        await channel.send(f"🎉 **GTB Result Set**: ${result_amount:,.2f}")
                except Exception as e:
                    print(f"Failed to send Discord notification: {e}")

            # Update Discord GTB panel
            if hasattr(self.bot, 'gtb_panel') and self.bot.gtb_panel:
                try:
                    success = await self.bot.gtb_panel.update_panel(force=True)
                    if success:
                        print("✅ GTB panel updated in Discord")
                    else:
                        print("ℹ️  GTB panel not created yet (Discord admin: use !creategtbpanel to create)")
                except Exception as e:
                    print(f"⚠️ Failed to update GTB panel: {e}")

    async def handle_management_event(self, action, data):
        """Handle management events from dashboard"""
        print(f"📥 Management Event: {action}")

        if action == 'adjust_tickets':
            discord_id = data.get('discord_id')
            ticket_source = data.get('ticket_source')
            change = data.get('change')
            reason = data.get('reason')
            print(f"Tickets adjusted for {discord_id}: {change} {ticket_source} tickets ({reason})")

        elif action == 'start_period':
            start_date = data.get('start_date')
            end_date = data.get('end_date')
            await self.announce_in_chat(f"🎟️ New raffle period started! {start_date} to {end_date}")

    async def handle_raffle_event(self, action, data):
        """Handle raffle events from dashboard"""
        print(f"📥 Raffle Event: {action}")

        if action == 'draw':
            request_id = data.get('request_id')
            period_id = data.get('period_id')
            winner_count = data.get('winner_count', 1)
            prize_description = data.get('prize_description', '')
            drawn_by_discord_id = data.get('drawn_by_discord_id')
            server_id = data.get('server_id')

            print(f"🎲 Processing raffle draw request {request_id} for period {period_id}")

            try:
                from sqlalchemy import create_engine
                from raffle_system.draw import RaffleDraw
                
                database_url = os.getenv('DATABASE_URL')
                engine = create_engine(database_url)
                draw_handler = RaffleDraw(engine)

                if winner_count == 1:
                    # Single winner
                    winner = draw_handler.draw_winner(
                        period_id=period_id,
                        drawn_by_discord_id=drawn_by_discord_id,
                        prize_description=prize_description
                    )

                    if not winner:
                        result = {'success': False, 'error': 'No eligible participants found'}
                    else:
                        result = {
                            'success': True,
                            'winner': winner,
                            'winners': [winner]
                        }
                else:
                    # Multiple winners
                    winners = []
                    excluded_discord_ids = []

                    for i in range(winner_count):
                        winner = draw_handler.draw_winner(
                            period_id=period_id,
                            drawn_by_discord_id=drawn_by_discord_id,
                            prize_description=f"{prize_description} (Winner {i+1}/{winner_count})",
                            excluded_discord_ids=excluded_discord_ids,
                            update_period=(i == 0)
                        )

                        if not winner:
                            if i == 0:
                                result = {'success': False, 'error': 'No eligible participants found'}
                                break
                            break

                        winners.append(winner)
                        excluded_discord_ids.append(winner['winner_discord_id'])

                    if winners:
                        result = {
                            'success': True,
                            'winners': winners,
                            'winner': winners[0]
                        }

                # Store result in Redis for dashboard to retrieve
                result_key = f'raffle_draw_result:{request_id}'
                self.client.setex(result_key, 30, json.dumps(result))  # Expire after 30 seconds
                print(f"✅ Raffle draw completed, result stored in Redis")

                # Announce winner(s) in Discord raffle announcement channel
                if result.get('success'):
                    await self.announce_raffle_winners(result.get('winners', []), prize_description)

            except Exception as e:
                print(f"❌ Raffle draw failed: {e}")
                import traceback
                traceback.print_exc()
                result = {'success': False, 'error': str(e)}
                result_key = f'raffle_draw_result:{request_id}'
                self.client.setex(result_key, 30, json.dumps(result))

    async def handle_commands_event(self, action, data):
        """Handle custom commands events from dashboard"""
        print(f"📥 Commands Event: {action}")

        if action == 'reload':
            # Trigger custom commands reload
            if hasattr(self.bot, 'custom_commands_manager'):
                try:
                    await self.bot.custom_commands_manager.reload_commands()
                    print("✅ Custom commands reloaded")
                except Exception as e:
                    print(f"⚠️ Failed to reload custom commands: {e}")
            else:
                print("⚠️ Custom commands manager not initialized")

    async def handle_point_shop_event(self, action, data):
        """Handle point shop events from dashboard"""
        guild_id = data.get('discord_server_id')
        guild = self.bot.get_guild(int(guild_id)) if guild_id else None
        guild_name = guild.name if guild else "Unknown"
        print(f"📥 Point Shop Event: {action} (guild={guild_name}, guild_id={guild_id})")

        if action == 'post_shop':
            channel_id = data.get('channel_id')

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

        elif action == 'sync_shop':
            # Debounce: prevent duplicate syncs within 3 seconds
            current_time = time.time()
            if current_time - self.last_shop_sync < 3:
                print(f"⏭️  Ignoring duplicate sync_shop for {guild_name} (last sync {current_time - self.last_shop_sync:.1f}s ago)")
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
                print(f"⚠️  post_point_shop_to_discord function not implemented yet (guild={guild_name}, guild_id={guild_id})")
                print("💡 Tip: Implement this function in bot.py to auto-sync shop embeds to Discord")
            except Exception as e:
                print(f"⚠️  Failed to sync point shop for {guild_name} (guild_id={guild_id}): {e}")
                import traceback
                traceback.print_exc()

        elif action == 'update_settings':
            print(f"✅ Point settings updated: {data}")
            # Settings are stored in DB, no action needed here

        elif action == 'item_update':
            item_id = data.get('item_id')
            item_name = data.get('item_name')
            update_type = data.get('type', 'update')  # create, update, delete
            guild_id = data.get('discord_server_id')
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

    async def handle_bot_settings_event(self, action, data):
        """Handle bot settings events from dashboard"""
        print(f"📥 Bot Settings Event: {action}")

        if action == 'sync':
            # Refresh bot settings from database
            if hasattr(self.bot, 'settings_manager') and self.bot.settings_manager:
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

        elif action == 'update':
            key = data.get('key')
            value = data.get('value')
            print(f"✅ Bot setting updated: {key} = {value}")

            # Refresh settings to pick up the change
            if hasattr(self.bot, 'settings_manager') and self.bot.settings_manager:
                try:
                    self.bot.settings_manager.refresh()
                    print("✅ Bot settings refreshed after update")
                except Exception as e:
                    print(f"⚠️ Failed to refresh bot settings: {e}")

        elif action == 'reload':
            # Profile settings were updated - refresh for specific guild or all
            guild_id = data.get('guild_id')
            print(f"✅ Reload request for guild: {guild_id}")
            # Settings will be reloaded automatically on next access
            
    async def handle_giveaway_event(self, action, data):
        """Handle giveaway events from dashboard"""
        print(f"🎁 Giveaway event: {action}")
        
        try:
            guild_id = data.get('discord_server_id')
            giveaway_id = data.get('giveaway_id')
            
            if not guild_id:
                print("⚠️ No guild_id in giveaway event")
                return
            
            # Get giveaway manager for this guild
            if not hasattr(self.bot, 'giveaway_managers'):
                print("⚠️ Giveaway managers not initialized on bot")
                return
            
            giveaway_manager = self.bot.giveaway_managers.get(guild_id)
            if not giveaway_manager:
                print(f"⚠️ No giveaway manager found for guild {guild_id}")
                return
            
            guild = self.bot.get_guild(guild_id)
            guild_name = guild.name if guild else str(guild_id)
            
            if action == 'giveaway_started':
                # Reload active giveaway from database
                await giveaway_manager.load_active_giveaway()
                
                if giveaway_manager.active_giveaway:
                    giveaway_title = giveaway_manager.active_giveaway.get('title', 'New Giveaway')
                    entry_method = giveaway_manager.active_giveaway.get('entry_method', 'keyword')
                    
                    # Announce in Discord
                    if hasattr(self.bot, 'settings_manager'):
                        announcement_channel_id = getattr(self.bot.settings_manager, 'raffle_announcement_channel_id', None)
                        if announcement_channel_id:
                            channel = self.bot.get_channel(announcement_channel_id)
                            if channel:
                                import discord
                                embed = discord.Embed(
                                    title="🎁 New Giveaway Started!",
                                    description=giveaway_title,
                                    color=0x00ff00
                                )
                                
                                if entry_method == 'keyword':
                                    keyword = giveaway_manager.active_giveaway.get('keyword', '')
                                    embed.add_field(
                                        name="How to Enter",
                                        value=f"Type `{keyword}` in Kick chat!",
                                        inline=False
                                    )
                                elif entry_method == 'active_chatter':
                                    messages_required = giveaway_manager.active_giveaway.get('messages_required', 10)
                                    time_window = giveaway_manager.active_giveaway.get('time_window_minutes', 10)
                                    embed.add_field(
                                        name="How to Enter",
                                        value=f"Send {messages_required} unique messages in {time_window} minutes in Kick chat!",
                                        inline=False
                                    )
                                
                                allow_multiple = giveaway_manager.active_giveaway.get('allow_multiple_entries', False)
                                if allow_multiple:
                                    max_entries = giveaway_manager.active_giveaway.get('max_entries_per_user', 5)
                                    embed.add_field(
                                        name="Multiple Entries",
                                        value=f"You can enter up to {max_entries} times!",
                                        inline=False
                                    )
                                
                                await channel.send(embed=embed)
                                print(f"[{guild_name}] ✅ Announced giveaway start in Discord")
                    
                    # Announce in Kick chat
                    if self.send_message_callback:
                        if entry_method == 'keyword':
                            keyword = giveaway_manager.active_giveaway.get('keyword', '')
                            message = f"🎁 GIVEAWAY STARTED: {giveaway_title} | Type {keyword} to enter!"
                        else:
                            message = f"🎁 GIVEAWAY STARTED: {giveaway_title} | Be active in chat to enter!"
                        
                        await self.announce_in_chat(message, guild_id=guild_id)
                        print(f"[{guild_name}] ✅ Announced giveaway start in Kick chat")
                    
                    print(f"[{guild_name}] ✅ Giveaway {giveaway_id} started: {giveaway_title}")
            
            elif action == 'giveaway_stopped':
                # Clear active giveaway
                giveaway_manager.active_giveaway = None
                print(f"[{guild_name}] ✅ Giveaway {giveaway_id} stopped")
                
                # Announce in Kick chat
                if self.send_message_callback:
                    await self.announce_in_chat("🎁 Giveaway has been stopped by moderators.", guild_id=guild_id)
            
            elif action == 'giveaway_winner':
                winner = data.get('winner_username')
                giveaway_title = data.get('giveaway_title', 'Giveaway')
                delay_announcement = data.get('delay_announcement', False)
                
                if not winner:
                    print("⚠️ No winner in giveaway_winner event")
                    return
                
                print(f"[{guild_name}] 🎉 Winner drawn: {winner}")
                
                # If delay requested, wait 7 seconds for OBS animation to complete (6s animation + 1s buffer)
                if delay_announcement:
                    print(f"[{guild_name}] ⏳ Waiting 7 seconds for animation to complete...")
                    await asyncio.sleep(7)
                
                # Announce in Discord
                if hasattr(self.bot, 'settings_manager'):
                    announcement_channel_id = getattr(self.bot.settings_manager, 'raffle_announcement_channel_id', None)
                    if announcement_channel_id:
                        channel = self.bot.get_channel(announcement_channel_id)
                        if channel:
                            import discord
                            embed = discord.Embed(
                                title="🎉 Giveaway Winner!",
                                description=f"**{giveaway_title}**",
                                color=0xffd700
                            )
                            embed.add_field(
                                name="Winner",
                                value=f"🏆 **{winner}**",
                                inline=False
                            )
                            embed.add_field(
                                name="",
                                value="Congratulations! 🎊",
                                inline=False
                            )
                            
                            await channel.send(embed=embed)
                            print(f"[{guild_name}] ✅ Announced giveaway winner in Discord: {winner}")
                
                # Announce in Kick chat
                if self.send_message_callback:
                    message = f"🎉 GIVEAWAY WINNER: {winner} won {giveaway_title}! Congratulations! 🎊"
                    await self.announce_in_chat(message, guild_id=guild_id)
                    print(f"[{guild_name}] ✅ Announced giveaway winner in Kick chat: {winner}")
                
                # Clear active giveaway
                giveaway_manager.active_giveaway = None
            
        except Exception as e:
            print(f"❌ Error handling giveaway event: {e}")
            import traceback
            traceback.print_exc()

    async def announce_in_chat(self, message, guild_id=None):
            # Kick channel was synced from dashboard - refresh to pick up new chatroom_id
            kick_channel = data.get('kick_channel')
            chatroom_id = data.get('chatroom_id')
            broadcaster_user_id = data.get('broadcaster_user_id')
            print(f"✅ Kick channel synced: {kick_channel} (chatroom: {chatroom_id}, broadcaster: {broadcaster_user_id})")

            if hasattr(self.bot, 'settings_manager') and self.bot.settings_manager:
                try:
                    self.bot.settings_manager.refresh()
                    print("✅ Bot settings refreshed after Kick sync")
                except Exception as e:
                    print(f"⚠️ Failed to refresh bot settings: {e}")

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

    async def announce_raffle_winners(self, winners, prize_description):
        """Announce raffle winner(s) to Discord raffle announcement channel"""
        try:
            # Get announcement channel from bot settings
            if not hasattr(self.bot, 'settings_manager'):
                print("⚠️ Bot settings manager not available, cannot announce raffle winners")
                return

            channel_id = self.bot.settings_manager.raffle_announcement_channel_id
            if not channel_id:
                print("⚠️ Raffle announcement channel not configured, skipping announcement")
                return

            channel = self.bot.get_channel(channel_id)
            if not channel:
                print(f"⚠️ Raffle announcement channel {channel_id} not found")
                return

            # Single or multiple winners
            if len(winners) == 1:
                winner = winners[0]
                
                # Try to mention winner
                try:
                    discord_user = await self.bot.fetch_user(winner['winner_discord_id'])
                    mention = discord_user.mention
                except:
                    mention = f"Discord ID: {winner['winner_discord_id']}"

                message = f"""
🎉 **RAFFLE WINNER DRAWN!** 🎉

**Winner**: {winner['winner_kick_name']} ({mention})
**Winning Ticket**: #{winner['winning_ticket']} out of {winner['total_tickets']:,}
**Win Probability**: {winner['win_probability']:.2f}%
**Prize**: {prize_description or 'Monthly Raffle Prize'}

Congratulations! Please contact an admin to claim your prize! 🎊
                """.strip()
                
                await channel.send(message)
                print(f"✅ Raffle winner announced in Discord channel {channel_id}")
            else:
                # Multiple winners
                message = f"🎉 **RAFFLE WINNERS DRAWN!** 🎉\n\n**Prize**: {prize_description or 'Monthly Raffle Prize'}\n\n"
                
                for i, winner in enumerate(winners, 1):
                    try:
                        discord_user = await self.bot.fetch_user(winner['winner_discord_id'])
                        mention = discord_user.mention
                    except:
                        mention = f"Discord ID: {winner['winner_discord_id']}"
                    
                    message += f"**{i}. {winner['winner_kick_name']}** ({mention})\n"
                    message += f"   • Ticket #{winner['winning_ticket']}/{winner['total_tickets']:,} ({winner['win_probability']:.2f}%)\n\n"
                
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
            'dashboard:slot_requests',
            'dashboard:timed_messages',
            'dashboard:gtb',
            'dashboard:management',
            'dashboard:raffle',
            'dashboard:commands',
            'dashboard:point_shop',
            'dashboard:bot_settings',
            'dashboard:giveaway'
            # 'bot_events' removed - no longer using webhooks for chat
        )

        print("🎧 Redis subscriber listening for dashboard events...")

        while True:
            try:
                # Run blocking listen() in a thread to avoid blocking event loop
                message = await asyncio.to_thread(self.pubsub.get_message, timeout=1.0)

                if message and message['type'] == 'message':
                    channel = message['channel']
                    try:
                        payload = json.loads(message['data'])
                        action = payload.get('action')
                        data = payload.get('data', {})

                        # Route to appropriate handler
                        if channel == 'dashboard:slot_requests':
                            await self.handle_slot_requests_event(action, data)
                        elif channel == 'dashboard:timed_messages':
                            await self.handle_timed_messages_event(action, data)
                        elif channel == 'dashboard:gtb':
                            await self.handle_gtb_event(action, data)
                        elif channel == 'dashboard:management':
                            await self.handle_management_event(action, data)
                        elif channel == 'dashboard:raffle':
                            await self.handle_raffle_event(action, data)
                        elif channel == 'dashboard:commands':
                            await self.handle_commands_event(action, data)
                        elif channel == 'dashboard:point_shop':
                            await self.handle_point_shop_event(action, data)
                        elif channel == 'dashboard:bot_settings':
                            await self.handle_bot_settings_event(action, data)
                        elif channel == 'dashboard:giveaway':
                            await self.handle_giveaway_event(action, data)
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
                        'dashboard:slot_requests',
                        'dashboard:timed_messages',
                        'dashboard:gtb',
                        'dashboard:management',
                        'dashboard:raffle',
                        'dashboard:commands',
                        'dashboard:point_shop',
                        'dashboard:bot_settings',
                        'dashboard:giveaway'
                        # 'bot_events' removed - no longer using webhooks
                    )

async def start_redis_subscriber(bot, send_message_callback=None):
    """
    Start the Redis subscriber in the background

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
        
        # Run the listener in the background
        await subscriber.listen()
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
