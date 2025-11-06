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
    def __init__(self, bot):
        self.bot = bot
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
            # Update your bot's internal state
            # self.bot.slot_requests_enabled = enabled
            if enabled:
                await self.announce_in_chat("✅ Slot requests are now ENABLED! Use !slotrequest <slot_name>")
            else:
                await self.announce_in_chat("❌ Slot requests have been DISABLED")
        
        elif action == 'pick':
            slot_call = data.get('slot_call')
            username = data.get('username')
            # Announce the picked slot in chat
            await self.announce_in_chat(f"🎰 Picked slot: {slot_call} (requested by {username})")
        
        elif action == 'update_max':
            max_requests = data.get('max_requests')
            # Update bot's max requests setting
            # self.bot.max_slot_requests = max_requests
            print(f"Updated max slot requests to {max_requests}")
    
    async def handle_timed_messages_event(self, action, data):
        """Handle timed message events from dashboard"""
        print(f"📥 Timed Messages Event: {action}")
        
        if action == 'create':
            message_id = data.get('id')
            message = data.get('message')
            interval = data.get('interval_minutes')
            # Add to bot's timed messages schedule
            print(f"Created timed message {message_id}: {message} (every {interval}m)")
        
        elif action == 'update':
            message_id = data.get('id')
            # Update existing timed message
            print(f"Updated timed message {message_id}")
        
        elif action == 'delete':
            message_id = data.get('id')
            # Remove from bot's timed messages schedule
            print(f"Deleted timed message {message_id}")
        
        elif action == 'toggle':
            message_id = data.get('id')
            enabled = data.get('enabled')
            # Enable/disable timed message
            print(f"Toggled timed message {message_id}: {enabled}")
    
    async def handle_gtb_event(self, action, data):
        """Handle Guess the Balance events from dashboard"""
        print(f"📥 GTB Event: {action}")
        
        if action == 'open':
            session_id = data.get('session_id')
            opened_by = data.get('opened_by')
            # Open GTB session in bot
            await self.announce_in_chat(f"💰 Guess the Balance session #{session_id} is now OPEN! Use !gtb <amount> to guess!")
        
        elif action == 'close':
            session_id = data.get('session_id')
            # Close GTB session
            await self.announce_in_chat(f"🔒 Guess the Balance session #{session_id} is now CLOSED! No more guesses allowed.")
        
        elif action == 'set_result':
            session_id = data.get('session_id')
            result_amount = data.get('result_amount')
            # Process winners and announce
            await self.announce_in_chat(f"🎉 GTB Result: ${result_amount:,.2f}! Calculating winners...")
            # Your bot should calculate winners from gtb_guesses table and update gtb_winners
    
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
            # Replace with your actual Kick API send message method
            # Example: await self.bot.kick_api.send_message(message)
            print(f"💬 Would announce in chat: {message}")
            # If you have a kick_api instance in your bot:
            # if hasattr(self.bot, 'kick_api') and hasattr(self.bot.kick_api, 'send_message'):
            #     await self.bot.kick_api.send_message(message)
        except Exception as e:
            print(f"Failed to announce in chat: {e}")
    
    async def listen(self):
        """Listen for events on all dashboard channels"""
        if not self.enabled:
            print("Redis subscriber not enabled, skipping...")
            return
        
        # Subscribe to all dashboard channels
        self.pubsub.subscribe(
            'dashboard:slot_requests',
            'dashboard:timed_messages',
            'dashboard:gtb',
            'dashboard:management'
        )
        
        print("🎧 Redis subscriber listening for dashboard events...")
        
        try:
            for message in self.pubsub.listen():
                if message['type'] == 'message':
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
        
        except Exception as e:
            print(f"Redis listener error: {e}")
            # Reconnect after delay
            await asyncio.sleep(5)
            if self.enabled:
                await self.listen()

async def start_redis_subscriber(bot):
    """Start the Redis subscriber in the background"""
    subscriber = RedisSubscriber(bot)
    
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
