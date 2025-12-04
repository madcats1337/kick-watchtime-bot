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

class RedisSubscriber:
    def __init__(self, bot, send_message_callback=None):
        self.bot = bot
        self.send_message_callback = send_message_callback
        self.redis_url = os.getenv('REDIS_URL')
        self.enabled = False

        if self.redis_url:
            if '://' not in self.redis_url:
                self.redis_url = f'redis://{self.redis_url}'
            try:
                self.client = redis.from_url(self.redis_url, decode_responses=True)
                self.pubsub = self.client.pubsub()
                self.enabled = True
                print("✅ Redis subscriber initialized")
            except Exception as e:
                print(f"⚠️  Redis unavailable: {e}")
                self.enabled = False
        else:
            print("⚠️  REDIS_URL not set, dashboard events will not be received")

    async def handle_slot_requests_event(self, action, data):
        """Handle slot request events from dashboard"""
        print(f"📥 Slot Requests Event: {action}")

        if action == 'toggle':
            enabled = data.get('enabled')
            # Announce in Kick chat
            if enabled:
                await self.announce_in_chat("✅ Slot requests are now ENABLED! Use !call <slot_name> or !sr <slot_name>")
            else:
                await self.announce_in_chat("❌ Slot requests have been DISABLED")

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

            # Update Discord panel
            if hasattr(self.bot, 'slot_request_panel') and self.bot.slot_request_panel:
                try:
                    panel = self.bot.slot_request_panel
                    # Refresh tracker state from database before updating panel
                    if hasattr(panel, 'tracker') and panel.tracker:
                        panel.tracker.enabled = panel.tracker._load_enabled_state()  # Reload enabled state from DB
                        panel.tracker.max_requests_per_user = panel.tracker._load_max_requests()  # Reload max requests too
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
            # Announce the picked slot in Kick chat
            await self.announce_in_chat(f"🎰 PICKED: {slot_call} (requested by {username})")

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

            # Format reward type for display
            reward_type_display = 'Bonus Buy' if reward_type == 'bonus_buy' else reward_type.capitalize()

            # Announce the picked slot WITH reward in Kick chat
            amount = float(reward_amount)
            await self.announce_in_chat(f"🎰 PICKED: {slot_call} (requested by {username}) 💰 WON ${amount:.2f} {reward_type_display}!")

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

        # Reload timed messages from database to pick up changes
        if hasattr(self.bot, 'timed_messages_manager') and self.bot.timed_messages_manager:
            try:
                await self.bot.timed_messages_manager.reload_messages()
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

        if action == 'open':
            session_id = data.get('session_id')
            opened_by = data.get('opened_by')
            # Announce in Kick chat
            await self.announce_in_chat(f"💰 Guess the Balance session #{session_id} is now OPEN! Use !gtb <amount> to guess!")

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
            await self.announce_in_chat(f"🔒 Guess the Balance session #{session_id} is now CLOSED! No more guesses allowed.")

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
            await self.announce_in_chat(f"🎉 GTB Result: ${result_amount:,.2f}! Calculating winners...")

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
                await self.announce_in_chat(winner_text)
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
                            await self.announce_in_chat(winner_text)
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
        print(f"📥 Point Shop Event: {action}")

        if action == 'post_shop':
            channel_id = data.get('channel_id')

            # Import the post function from bot module
            try:
                from bot import post_point_shop_to_discord
                success = await post_point_shop_to_discord(self.bot, channel_id=channel_id, update_existing=True)
                if success:
                    print("✅ Point shop posted to Discord")
                else:
                    print("⚠️ Failed to post point shop")
            except Exception as e:
                print(f"⚠️ Failed to post point shop: {e}")
                import traceback
                traceback.print_exc()

        elif action == 'sync_shop':
            # Force update the shop message
            try:
                from bot import post_point_shop_to_discord
                success = await post_point_shop_to_discord(self.bot, update_existing=True)
                if success:
                    print("✅ Point shop force synced to Discord")
                else:
                    print("⚠️ Failed to sync point shop")
            except Exception as e:
                print(f"⚠️ Failed to sync point shop: {e}")
                import traceback
                traceback.print_exc()

        elif action == 'update_settings':
            print(f"✅ Point settings updated: {data}")
            # Settings are stored in DB, no action needed here

        elif action == 'item_update':
            item_id = data.get('item_id')
            item_name = data.get('item_name')
            update_type = data.get('type', 'update')  # create, update, delete
            print(f"✅ Point shop item {update_type}: {item_name} (ID: {item_id})")

            # Auto-update the shop message when items change
            try:
                from bot import update_point_shop_message
                success = await update_point_shop_message(self.bot)
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

        elif action == 'kick_channel_synced':
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

    async def announce_in_chat(self, message):
        """Send a message to the Kick chat"""
        try:
            if self.send_message_callback:
                success = await self.send_message_callback(message)
                if success:
                    print(f"💬 Sent to Kick chat: {message}")
                else:
                    print(f"⚠️ Failed to send to Kick chat: {message}")
            else:
                print(f"💬 [No Kick callback] Would announce: {message}")
        except Exception as e:
            print(f"❌ Error sending to Kick chat: {e}")

    async def listen(self):
        """Listen for events on all dashboard channels"""
        if not self.enabled:
            print("Redis subscriber not enabled, skipping...")
            return

        # Subscribe to all dashboard channels
        await asyncio.to_thread(
            self.pubsub.subscribe,
            'dashboard:slot_requests',
            'dashboard:timed_messages',
            'dashboard:gtb',
            'dashboard:management',
            'dashboard:commands',
            'dashboard:point_shop',
            'dashboard:bot_settings'
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
                        server_id = payload.get('server_id')

                        # Filter events by server_id - only process events for servers this bot is connected to
                        if server_id:
                            bot_guild_ids = [guild.id for guild in self.bot.guilds]
                            if server_id not in bot_guild_ids:
                                # Skip events from servers this bot doesn't manage
                                continue

                        # Route to appropriate handler
                        if channel == 'dashboard:slot_requests':
                            await self.handle_slot_requests_event(action, data)
                        elif channel == 'dashboard:timed_messages':
                            await self.handle_timed_messages_event(action, data)
                        elif channel == 'dashboard:gtb':
                            await self.handle_gtb_event(action, data)
                        elif channel == 'dashboard:management':
                            await self.handle_management_event(action, data)
                        elif channel == 'dashboard:commands':
                            await self.handle_commands_event(action, data)
                        elif channel == 'dashboard:point_shop':
                            await self.handle_point_shop_event(action, data)
                        elif channel == 'dashboard:bot_settings':
                            await self.handle_bot_settings_event(action, data)

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
                        'dashboard:commands',
                        'dashboard:point_shop',
                        'dashboard:bot_settings'
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
