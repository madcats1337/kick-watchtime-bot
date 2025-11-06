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
                    await self.bot.slot_request_panel.update_panel(force=True)
                    print("✅ Slot request panel updated")
                except Exception as e:
                    print(f"⚠️ Failed to update slot panel: {e}")
        
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
                    await self.bot.slot_request_panel.update_panel(force=True)
                    print("✅ Slot request panel updated")
                except Exception as e:
                    print(f"⚠️ Failed to update slot panel: {e}")
        
        elif action == 'update_max':
            max_requests = data.get('max_requests')
            print(f"Updated max slot requests to {max_requests}")
            
            # Update Discord panel
            if hasattr(self.bot, 'slot_request_panel') and self.bot.slot_request_panel:
                try:
                    await self.bot.slot_request_panel.update_panel(force=True)
                    print("✅ Slot request panel updated")
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
                    await self.bot.gtb_panel.update_panel(force=True)
                    print("✅ GTB panel updated")
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
                    await self.bot.gtb_panel.update_panel(force=True)
                    print("✅ GTB panel updated")
                except Exception as e:
                    print(f"⚠️ Failed to update GTB panel: {e}")
        
        elif action == 'set_result':
            session_id = data.get('session_id')
            result_amount = data.get('result_amount')
            # Announce result in Kick chat
            await self.announce_in_chat(f"🎉 GTB Result: ${result_amount:,.2f}! Calculating winners...")
            
            # Calculate winners using GTB manager if available
            if hasattr(self.bot, 'gtb_manager') and self.bot.gtb_manager:
                try:
                    winners = self.bot.gtb_manager.calculate_winners(session_id, result_amount)
                    if winners and len(winners) > 0:
                        winner_text = f"🥇 {winners[0]['username']}: ${winners[0]['guess_amount']:,.2f} (${winners[0]['difference']:,.2f} off)"
                        await self.announce_in_chat(f"🏆 Winner: {winner_text}")
                    print(f"✅ Calculated {len(winners)} winners for GTB #{session_id}")
                except Exception as e:
                    print(f"⚠️ Failed to calculate GTB winners: {e}")
            
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
                    await self.bot.gtb_panel.update_panel(force=True)
                    print("✅ GTB panel updated")
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
            'dashboard:management'
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
                        'dashboard:management'
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
