"""
Redis Publisher for Bot Events
Publishes events to Redis channels for dashboard notifications
"""

import redis
import json
import os

class BotRedisPublisher:
    def __init__(self):
        redis_url = os.getenv('REDIS_URL')
        if redis_url:
            if '://' not in redis_url:
                redis_url = f'redis://{redis_url}'
            try:
                self.client = redis.from_url(redis_url, decode_responses=True)
                self.client.ping()
                self.enabled = True
                print("✅ Bot Redis publisher connected")
            except Exception as e:
                print(f"⚠️ Redis unavailable for bot publisher: {e}")
                self.enabled = False
        else:
            print("⚠️ REDIS_URL not set, bot events will not be published")
            self.enabled = False

    def publish(self, channel, action, data=None):
        """Publish an event to a Redis channel"""
        if not self.enabled:
            return False

        try:
            message = json.dumps({
                'action': action,
                'data': data or {}
            })
            self.client.publish(channel, message)
            print(f"📤 Bot published to {channel}: {action}")
            return True
        except Exception as e:
            print(f"❌ Failed to publish to {channel}: {e}")
            return False

    def publish_raffle_draw(self, discord_server_id, winner_kick_name, winner_shuffle_name, prize_description, period_id):
        """Publish raffle draw event to dashboard"""
        return self.publish('bot:raffle_draw', 'winner_drawn', {
            'discord_server_id': discord_server_id,
            'winner_kick_name': winner_kick_name,
            'winner_shuffle_name': winner_shuffle_name,
            'prize_description': prize_description,
            'period_id': period_id
        })

    def publish_stream_live(self, discord_server_id, streamer, stream_url):
        """Publish stream live event to dashboard"""
        return self.publish('bot:stream_status', 'stream_live', {
            'discord_server_id': discord_server_id,
            'streamer': streamer,
            'stream_url': stream_url
        })

    def publish_stream_offline(self, discord_server_id, streamer):
        """Publish stream offline event to dashboard"""
        return self.publish('bot:stream_status', 'stream_offline', {
            'discord_server_id': discord_server_id,
            'streamer': streamer
        })

# Global instance
bot_redis_publisher = BotRedisPublisher()
