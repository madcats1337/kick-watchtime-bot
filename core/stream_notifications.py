"""
Shared stream go-live notification sender (platform-agnostic).

Both the Kick webhook (livestream.status.updated) and the Twitch EventSub webhook
(stream.online/offline) call send_stream_notification() so the "X is now LIVE"
Discord post, the Redis publish, and the clip-buffer trigger behave identically
across platforms. Only the stream URL, the embed-proxy URL, and the platform
label differ per platform.

Extracted from the original Kick on_stream_status handler in core/kick_webhooks.py
so there is a single source of truth for go-live behavior.
"""

import asyncio
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


# Per-platform URL builders. Kick uses clkick.com as a Discord-unfurl video proxy;
# Twitch HLS is locked down so we fall back to the channel page (the dashboard
# /stream/live embed for Twitch is deferred — see the plan §D).
def _stream_url(platform: str, streamer: str) -> str:
    if platform == "twitch":
        return f"https://twitch.tv/{streamer}"
    return f"https://kick.com/{streamer}"


def _embed_url(platform: str, streamer: str) -> str:
    if platform == "twitch":
        # No video-unfurl proxy yet for Twitch; link the channel directly.
        return f"https://twitch.tv/{streamer}"
    return f"https://clkick.com/{streamer}"


def _platform_label(platform: str) -> str:
    return "Twitch" if platform == "twitch" else "Kick"


async def send_stream_notification(
    discord_server_id,
    streamer: str,
    is_live: bool,
    title: str = "",
    category: str = "",
    platform: str = "kick",
):
    """
    Post the go-live notification to Discord (if enabled for the server), publish
    the stream status to Redis, and trigger the clip buffer.

    Mirrors the original Kick behavior exactly; `platform` selects the URLs/label.
    """
    if not discord_server_id:
        return

    # ---- 1. Discord notification (only on go-live) ----
    if is_live:
        await _post_discord_notification(discord_server_id, streamer, title, category, platform)

    # ---- 2. Redis publish (dashboard) ----
    try:
        from utils.redis_publisher import bot_redis_publisher

        if is_live:
            bot_redis_publisher.publish_stream_live(
                discord_server_id=str(discord_server_id),
                streamer=streamer,
                stream_url=_stream_url(platform, streamer),
            )
        else:
            bot_redis_publisher.publish_stream_offline(discord_server_id=str(discord_server_id), streamer=streamer)
        logger.info(f"[StreamNotify] 📤 Published stream_{'live' if is_live else 'offline'} ({platform})")
    except Exception as e:
        logger.info(f"[StreamNotify] ⚠️ Failed to publish stream status to Redis: {e}")

    # ---- 3. Clip buffer start/stop (reuses dashboard clip API) ----
    await _control_clip_buffer(discord_server_id, streamer, is_live, platform)


async def _post_discord_notification(discord_server_id, streamer, title, category, platform):
    try:
        import aiohttp
        from sqlalchemy import create_engine, text

        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            return
        engine = create_engine(db_url, pool_pre_ping=True)
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT key, value FROM bot_settings
                    WHERE discord_server_id = :guild_id
                    AND key IN ('stream_notification_enabled', 'stream_notification_channel_id',
                                'stream_notification_title', 'stream_notification_description',
                                'stream_notification_link_text', 'stream_notification_link_small',
                                'stream_notification_footer')
                    """
                ),
                {"guild_id": discord_server_id},
            ).fetchall()
        settings = {key: value for key, value in rows}

        if settings.get("stream_notification_enabled") != "true":
            return
        notification_channel_id = settings.get("stream_notification_channel_id")
        if not notification_channel_id:
            return

        stream_url = _stream_url(platform, streamer)
        embed_url = _embed_url(platform, streamer)

        def replace_placeholders(t):
            if not t:
                return t
            return (
                t.replace("{streamer}", streamer)
                .replace("{channel}", streamer)
                .replace("{title}", title or "")
                .replace("{category}", category or "")
            )

        link_text = settings.get("stream_notification_link_text") or "Watch Preview"
        hidden_link = f"[{link_text}]({embed_url})"
        if settings.get("stream_notification_link_small") == "true":
            hidden_link = f"-# {hidden_link}"

        custom_title = settings.get("stream_notification_title")
        if custom_title:
            title_text = replace_placeholders(custom_title)
        else:
            title_text = f"🔴 **{streamer}** is now LIVE on {_platform_label(platform)}!"

        custom_description = settings.get("stream_notification_description")
        if custom_description:
            message_content = f"{title_text}\n{replace_placeholders(custom_description)}\n{hidden_link}"
        else:
            message_content = f"{title_text}\n{hidden_link}"

        footer_text = replace_placeholders(settings.get("stream_notification_footer"))

        components = [
            {
                "type": 1,
                "components": [
                    {
                        "type": 2,
                        "style": 5,
                        "label": "Watch Stream",
                        "url": stream_url,
                        "emoji": {"name": "🔴"},
                    }
                ],
            }
        ]

        bot_token = os.getenv("DISCORD_TOKEN")
        if not bot_token:
            return
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"https://discord.com/api/v10/channels/{notification_channel_id}/messages",
                headers={"Authorization": f"Bot {bot_token}", "Content-Type": "application/json"},
                json={"content": message_content, "components": components},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status in (200, 201):
                    if footer_text:
                        await asyncio.sleep(0.5)
                        async with session.post(
                            f"https://discord.com/api/v10/channels/{notification_channel_id}/messages",
                            headers={"Authorization": f"Bot {bot_token}", "Content-Type": "application/json"},
                            json={"content": f"-# {footer_text}"},
                            timeout=aiohttp.ClientTimeout(total=10),
                        ) as footer_resp:
                            if footer_resp.status not in (200, 201):
                                logger.info(f"[StreamNotify] ⚠️ Failed to send footer: {footer_resp.status}")
                    logger.info(f"[StreamNotify] ✅ Notification sent to channel {notification_channel_id}")
                else:
                    error_text = await resp.text()
                    logger.info(f"[StreamNotify] ⚠️ Failed to send notification: {resp.status} - {error_text[:200]}")
    except Exception as e:
        logger.info(f"[StreamNotify] ⚠️ Failed to send Discord stream notification: {e}")


async def _control_clip_buffer(discord_server_id, streamer, is_live, platform):
    """Start/stop the dashboard clip buffer on go-live/offline. Clips currently
    target Kick HLS only; for Twitch this is a no-op until clip support lands."""
    if platform != "kick":
        return
    try:
        import aiohttp
        from sqlalchemy import create_engine, text

        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            return
        engine = create_engine(db_url, pool_pre_ping=True)
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT key, value FROM bot_settings
                    WHERE discord_server_id = :guild_id
                    AND key IN ('kick_channel', 'dashboard_url', 'bot_api_key', 'clips_auto_start_on_live')
                    """
                ),
                {"guild_id": discord_server_id},
            ).fetchall()
        settings = {key: value for key, value in rows}
        kick_channel = settings.get("kick_channel")
        dashboard_url = settings.get("dashboard_url")
        api_key = settings.get("bot_api_key")
        auto_start_buffer = str(settings.get("clips_auto_start_on_live", "true")).lower() != "false"

        if not (dashboard_url and api_key and kick_channel):
            return
        async with aiohttp.ClientSession() as session:
            if is_live:
                if not auto_start_buffer:
                    logger.info(f"[StreamNotify] ⏸️ Auto-start disabled — skipping clip buffer for {streamer}")
                    return
                async with session.post(
                    f"{dashboard_url}/api/clips/buffer/start",
                    headers={"X-API-Key": api_key, "Content-Type": "application/json"},
                    json={"channel": kick_channel, "buffer_minutes": 4},
                    timeout=30,
                ) as resp:
                    if resp.status == 200:
                        logger.info(f"[StreamNotify] ✅ Clip buffer started for {streamer}")
                    else:
                        logger.info(f"[StreamNotify] ⚠️ Failed to start clip buffer: {resp.status}")
            else:
                async with session.post(
                    f"{dashboard_url}/api/clips/buffer/stop",
                    headers={"X-API-Key": api_key, "Content-Type": "application/json"},
                    json={"channel": kick_channel},
                    timeout=10,
                ) as resp:
                    if resp.status == 200:
                        logger.info(f"[StreamNotify] ✅ Clip buffer stopped for {streamer}")
                    else:
                        logger.info(f"[StreamNotify] ⚠️ Failed to stop clip buffer: {resp.status}")
    except Exception as e:
        logger.info(f"[StreamNotify] ⚠️ Failed to control clip buffer: {e}")
