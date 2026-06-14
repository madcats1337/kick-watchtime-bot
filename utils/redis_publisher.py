"""
Redis Publisher for Bot Events
Publishes events to Redis channels for dashboard notifications
"""

import json
import os

import redis


class BotRedisPublisher:
    def __init__(self):
        self.redis_url = os.getenv("REDIS_URL")
        self.client = None
        self.enabled = False
        if self.redis_url:
            if "://" not in self.redis_url:
                self.redis_url = f"redis://{self.redis_url}"
            self._connect()
        else:
            print("⚠️ REDIS_URL not set, bot events will not be published")

    def _connect(self):
        """Attempt to connect/reconnect to Redis"""
        try:
            self.client = redis.from_url(
                self.redis_url,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
            )
            self.client.ping()
            self.enabled = True
            print("✅ Bot Redis publisher connected")
        except Exception as e:
            print(f"⚠️ Redis unavailable for bot publisher: {e}")
            self.client = None
            self.enabled = False

    def publish(self, channel, action, data=None):
        """Publish an event to a Redis channel, reconnecting if needed"""
        if not self.redis_url:
            return False

        # Lazy reconnect if not connected
        if not self.enabled or not self.client:
            self._connect()
            if not self.enabled:
                return False

        try:
            message = json.dumps({"action": action, "data": data or {}})
            self.client.publish(channel, message)
            print(f"📤 Bot published to {channel}: {action}")
            return True
        except Exception as e:
            print(f"❌ Failed to publish to {channel}: {e}")
            # Mark as disconnected so next call will reconnect
            self.enabled = False
            return False

    def publish_raffle_draw(
        self, discord_server_id, winner_kick_name, winner_shuffle_name, prize_description, period_id
    ):
        """Publish raffle draw event to dashboard"""
        return self.publish(
            "bot:raffle_draw",
            "winner_drawn",
            {
                "discord_server_id": discord_server_id,
                "winner_kick_name": winner_kick_name,
                "winner_shuffle_name": winner_shuffle_name,
                "prize_description": prize_description,
                "period_id": period_id,
            },
        )

    def publish_stream_live(self, discord_server_id, streamer, stream_url):
        """Publish stream live event to dashboard"""
        return self.publish(
            "bot:stream_status",
            "stream_live",
            {"discord_server_id": discord_server_id, "streamer": streamer, "stream_url": stream_url},
        )

    def publish_stream_offline(self, discord_server_id, streamer):
        """Publish stream offline event to dashboard"""
        return self.publish(
            "bot:stream_status", "stream_offline", {"discord_server_id": discord_server_id, "streamer": streamer}
        )

    def publish_wager(self, discord_server_id, shuffle_username, kick_name, platform, wager_delta, total_wager_usd):
        """Publish a recorded wager to the dashboard live feed.

        Consumed by the dashboard's /api/events/wager SSE stream, which filters
        by discord_server_id — so it MUST be present in the payload.
        """
        return self.publish(
            "dashboard:wager",
            "wager_recorded",
            {
                "discord_server_id": discord_server_id,
                "shuffle_username": shuffle_username,
                "kick_name": kick_name,
                "platform": platform,
                "wager_delta": wager_delta,
                "total_wager_usd": total_wager_usd,
            },
        )


# Global instance
bot_redis_publisher = BotRedisPublisher()
