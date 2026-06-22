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


# Per-platform live-alert settings live under these prefixes. Kick falls back to
# the legacy shared `stream_notification_*` keys so existing servers keep working.
_ALERT_SUFFIXES = ("enabled", "channel_id", "title", "description", "link_text", "link_small", "footer")


def _alert_columns(platform: str) -> list:
    """The bot_settings keys to SELECT for a platform's live alert (new + legacy)."""
    prefix = "twitch_live_alert_" if platform == "twitch" else "kick_live_alert_"
    keys = [f"{prefix}{s}" for s in _ALERT_SUFFIXES]
    if platform != "twitch":
        keys += [f"stream_notification_{s}" for s in _ALERT_SUFFIXES]
    return keys


def alert_setting(settings: dict, platform: str, suffix: str):
    """Resolve a live-alert setting for a platform: the per-platform key, falling
    back to the legacy `stream_notification_*` key for Kick."""
    prefix = "twitch_live_alert_" if platform == "twitch" else "kick_live_alert_"
    val = settings.get(f"{prefix}{suffix}")
    if (val is None or val == "") and platform != "twitch":
        val = settings.get(f"stream_notification_{suffix}")
    return val


def _build_live_message(settings: dict, platform: str, streamer: str, title: str, category: str):
    """Build the (content, footer) for a go-live message from a platform's alert
    settings. Kick includes the clkick video-unfurl link; Twitch has no video
    proxy, so it omits the hidden link (the Watch Stream button links the channel).
    """

    def repl(t):
        if not t:
            return t
        return (
            t.replace("{streamer}", streamer)
            .replace("{channel}", streamer)
            .replace("{title}", title or "")
            .replace("{category}", category or "")
        )

    custom_title = alert_setting(settings, platform, "title")
    title_text = (
        repl(custom_title) if custom_title else f"🔴 **{streamer}** is now LIVE on {_platform_label(platform)}!"
    )

    custom_description = alert_setting(settings, platform, "description")
    parts = [title_text]
    if custom_description:
        parts.append(repl(custom_description))

    if platform == "twitch":
        # Twitch has no video-unfurl proxy — include a plain clickable channel link
        # (auto-built from the connected handle) so the alert body links the stream.
        link_text = alert_setting(settings, platform, "link_text") or "Watch on Twitch"
        parts.append(f"[{link_text}]({_embed_url(platform, streamer)})")
    else:
        # Kick: the clkick unfurl link that Discord turns into the video preview.
        link_text = alert_setting(settings, platform, "link_text") or "Watch Preview"
        hidden_link = f"[{link_text}]({_embed_url(platform, streamer)})"
        if alert_setting(settings, platform, "link_small") == "true":
            hidden_link = f"-# {hidden_link}"
        parts.append(hidden_link)

    message_content = "\n".join(parts)
    footer_text = repl(alert_setting(settings, platform, "footer"))
    return message_content, footer_text


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
        # Read this platform's live-alert settings (new keys; Kick falls back to
        # the legacy shared stream_notification_* keys).
        cols = _alert_columns(platform)
        placeholders = ", ".join(f":k{i}" for i in range(len(cols)))
        params = {"guild_id": discord_server_id}
        params.update({f"k{i}": c for i, c in enumerate(cols)})
        engine = create_engine(db_url, pool_pre_ping=True)
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    f"SELECT key, value FROM bot_settings "
                    f"WHERE discord_server_id = :guild_id AND key IN ({placeholders})"
                ),
                params,
            ).fetchall()
        settings = {key: value for key, value in rows}

        # Gate on this platform's OWN enabled flag.
        if alert_setting(settings, platform, "enabled") != "true":
            return
        notification_channel_id = alert_setting(settings, platform, "channel_id")
        if not notification_channel_id:
            logger.info(f"[StreamNotify] {platform} live alert has no channel — skipping")
            return

        stream_url = _stream_url(platform, streamer)
        message_content, footer_text = _build_live_message(settings, platform, streamer, title, category)

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
