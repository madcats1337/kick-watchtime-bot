"""
Kick.com API Integration Module
Handles chatroom ID fetching and API interactions with Kick.com

This module provides two modes of operation:
1. Official API (when authenticated via OAuth) - uses api.kick.com endpoints
2. Unofficial API (fallback) - uses kick.com/api/v2 endpoints

For official API access, see core/kick_official_api.py
"""

import asyncio
import json
import random
import os
from typing import Optional, Dict, Any, List
import aiohttp

# Import official API client for authenticated requests
try:
    from .kick_official_api import KickOfficialAPI, KICK_API_PUBLIC
    HAS_OFFICIAL_API = True
except ImportError:
    HAS_OFFICIAL_API = False
    KickOfficialAPI = None

# User agents for rotation
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/118.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
]

# Referrers for realistic traffic
REFERRERS = [
    "https://www.google.com/",
    "https://twitter.com/",
    "https://www.youtube.com/",
    "https://kick.com/",
]

# Country codes for geolocation
COUNTRY_CODES = ["US", "GB", "CA", "AU", "DE", "FR"]

class KickAPI:
    """Simplified Kick API class using HTTP requests only (no Playwright)"""

    def __init__(self):
        pass

    async def setup(self):
        """No setup needed for HTTP-only mode"""
        pass

    async def close(self):
        """No cleanup needed for HTTP-only mode"""
        pass

    async def fetch_chatroom_id(self, channel_name: str, max_retries: int = 5) -> Optional[str]:
        """
        Fetch the chatroom ID for a given Kick channel using HTTP API.

        NOTE: This may be blocked by Cloudflare. If it fails, set the KICK_CHATROOM_ID
        environment variable to bypass this call.

        Args:
            channel_name: The Kick channel name
            max_retries: Maximum number of retry attempts

        Returns:
            Chatroom ID as string, or None if failed
        """
        for attempt in range(max_retries):
            try:
                print(f"[Kick] Attempt {attempt + 1}/{max_retries}: Fetching chatroom ID for {channel_name}")

                async with aiohttp.ClientSession() as session:
                    headers = {
                        'User-Agent': random.choice(USER_AGENTS),
                        'Accept': 'application/json',
                        'Referer': 'https://kick.com/',
                    }
                    async with session.get(
                        f'https://kick.com/api/v2/channels/{channel_name}',
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=10)
                    ) as response:
                        if response.status == 200:
                            data = await response.json()
                            chatroom_id = data.get('chatroom', {}).get('id')
                            if chatroom_id:
                                print(f"[Kick] ✅ Found chatroom ID: {chatroom_id}")
                                return str(chatroom_id)
                        elif response.status == 403:
                            print(f"[Kick] ⚠️ Cloudflare blocked request. Set KICK_CHATROOM_ID environment variable to bypass.")
                        else:
                            print(f"[Kick] HTTP request returned status: {response.status}")
            except Exception as e:
                print(f"[Kick] Error: {type(e).__name__}: {str(e)}")

            if attempt < max_retries - 1:
                delay = 2 * (attempt + 1) + random.uniform(1, 3)
                print(f"[Kick] Waiting {delay:.1f} seconds before next attempt...")
                await asyncio.sleep(delay)

        print(f"[Kick] ❌ Failed to fetch chatroom ID after {max_retries} attempts")
        print(f"[Kick] 💡 TIP: Set KICK_CHATROOM_ID environment variable to bypass Cloudflare")
        return None

# Global API instance
_api = None

async def fetch_chatroom_id(channel_name: str, max_retries: int = 5) -> Optional[str]:
    """
    Convenience function to fetch chatroom ID.
    Maintains a global KickAPI instance for reuse.

    Args:
        channel_name: The Kick channel name
        max_retries: Maximum number of retry attempts

    Returns:
        Chatroom ID as string, or None if failed
    """
    global _api

    if not _api:
        _api = KickAPI()

    try:
        return await _api.fetch_chatroom_id(channel_name, max_retries)
    except Exception as e:
        print(f"[Kick] Error in fetch_chatroom_id: {type(e).__name__}: {str(e)}")
        # Reset API instance on error
        if _api:
            await _api.close()
        _api = None
        return None

async def check_stream_live(channel_name: str) -> bool:
    """
    Check if a Kick channel is currently live streaming.

    NOTE: This may be blocked by Cloudflare. If it fails, the bot will
    continue operating and rely on admin manual control via !tracking command.

    Args:
        channel_name: The Kick channel name

    Returns:
        True if stream is live, False if offline

    Raises:
        Exception: If API request fails (Cloudflare block, timeout, etc.)
    """
    try:
        async with aiohttp.ClientSession() as session:
            headers = {
                'User-Agent': random.choice(USER_AGENTS),
                'Accept': 'application/json',
                'Referer': 'https://kick.com/',
            }
            async with session.get(
                f'https://kick.com/api/v2/channels/{channel_name}',
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    # Check if livestream exists and is active
                    livestream = data.get('livestream')
                    if livestream and isinstance(livestream, dict):
                        # If livestream object exists and has data, stream is live
                        return True
                    return False
                elif response.status == 403:
                    # Cloudflare block - raise exception so caller can handle gracefully
                    raise Exception(f"Cloudflare blocked stream status check (403)")
                else:
                    # Other error status - raise exception
                    raise Exception(f"HTTP {response.status}")
    except asyncio.TimeoutError:
        raise Exception("API request timed out")
    except Exception as e:
        # Re-raise with context
        raise Exception(f"Stream status check failed: {type(e).__name__}: {str(e)}")

async def get_channel_info(channel_name: str) -> Optional[Dict[str, Any]]:
    """
    Get full channel information from Kick API.

    Args:
        channel_name: The Kick channel name/slug

    Returns:
        Channel data dict or None if failed
    """
    try:
        async with aiohttp.ClientSession() as session:
            headers = {
                'User-Agent': random.choice(USER_AGENTS),
                'Accept': 'application/json',
                'Referer': 'https://kick.com/',
            }
            async with session.get(
                f'https://kick.com/api/v2/channels/{channel_name}',
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    print(f"[Kick] Failed to get channel info: HTTP {response.status}")
                    return None
    except Exception as e:
        print(f"[Kick] Error getting channel info: {type(e).__name__}: {str(e)}")
        return None

async def create_clip(channel_name: str, duration_seconds: int = 30, title: str = None, access_token: str = None) -> Optional[Dict[str, Any]]:
    """
    Create a clip of the current livestream.

    This uses the Kick API's clip creation endpoints:
    1. GET /api/v2/channels/{channel}/clips/init - Initialize clip creation
    2. POST /api/v2/channels/{channel}/clips/finalize - Finalize the clip

    NOTE: This requires the stream to be live AND authentication.

    Args:
        channel_name: The Kick channel name/slug
        duration_seconds: Duration of the clip in seconds (default 30)
        title: Custom title for the clip (optional)
        access_token: OAuth access token for authentication (required)

    Returns:
        Dict with clip info (url, id, etc.) or None if failed
    """
    # Get access token from environment if not provided
    if not access_token:
        access_token = os.getenv("KICK_BOT_USER_TOKEN", "")

    if not access_token:
        print("[Kick] ❌ No access token provided for clip creation")
        return {'error': 'authentication_required', 'message': 'No OAuth token available for clip creation'}

    try:
        async with aiohttp.ClientSession() as session:
            headers = {
                'User-Agent': random.choice(USER_AGENTS),
                'Accept': 'application/json',
                'Content-Type': 'application/json',
                'Referer': f'https://kick.com/{channel_name}',
                'Origin': 'https://kick.com',
                'Authorization': f'Bearer {access_token}',
            }

            # Step 1: Initialize clip creation
            init_url = f'https://kick.com/api/v2/channels/{channel_name}/clips/init'
            async with session.get(init_url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as response:
                content_type = response.headers.get('Content-Type', '')

                # Check if we got HTML instead of JSON (Cloudflare block)
                if 'text/html' in content_type:
                    print(f"[Kick] ❌ Clip API blocked by Cloudflare (got HTML response)")
                    return {'error': 'cloudflare_blocked', 'message': 'Clip API blocked - use Kick website to clip'}

                if response.status == 200:
                    init_data = await response.json()
                    print(f"[Kick] Clip init response: {init_data}")

                    # Step 2: Finalize the clip with duration
                    finalize_url = f'https://kick.com/api/v2/channels/{channel_name}/clips/finalize'
                    finalize_data = {
                        'duration': duration_seconds,
                        'title': title or f'Clip from {channel_name}',
                    }

                    # Add any required fields from init response
                    if 'clip_id' in init_data:
                        finalize_data['clip_id'] = init_data['clip_id']

                    async with session.post(
                        finalize_url,
                        headers=headers,
                        json=finalize_data,
                        timeout=aiohttp.ClientTimeout(total=15)
                    ) as finalize_response:
                        if finalize_response.status == 200:
                            clip_data = await finalize_response.json()
                            print(f"[Kick] ✅ Clip created successfully: {clip_data}")
                            return clip_data
                        else:
                            error_text = await finalize_response.text()
                            print(f"[Kick] ❌ Clip finalize failed: HTTP {finalize_response.status} - {error_text}")
                            return None

                elif response.status == 401:
                    print(f"[Kick] ❌ Authentication required for clip creation")
                    return {'error': 'authentication_required', 'message': 'Clip creation requires authentication'}
                elif response.status == 403:
                    print(f"[Kick] ❌ Cloudflare blocked clip creation")
                    return {'error': 'cloudflare_blocked', 'message': 'Request blocked by Cloudflare'}
                elif response.status == 404:
                    print(f"[Kick] ❌ Channel not found or not live")
                    return {'error': 'not_found', 'message': 'Channel not found or stream not live'}
                else:
                    error_text = await response.text()
                    print(f"[Kick] ❌ Clip init failed: HTTP {response.status} - {error_text}")
                    return None

    except asyncio.TimeoutError:
        print(f"[Kick] ❌ Clip creation timed out")
        return {'error': 'timeout', 'message': 'Request timed out'}
    except Exception as e:
        print(f"[Kick] ❌ Error creating clip: {type(e).__name__}: {str(e)}")
        return None

async def get_clips(channel_name: str, limit: int = 10) -> Optional[list]:
    """
    Get recent clips from a Kick channel.

    Args:
        channel_name: The Kick channel name/slug
        limit: Maximum number of clips to return

    Returns:
        List of clip dicts or None if failed
    """
    try:
        async with aiohttp.ClientSession() as session:
            headers = {
                'User-Agent': random.choice(USER_AGENTS),
                'Accept': 'application/json',
                'Referer': 'https://kick.com/',
            }
            async with session.get(
                f'https://kick.com/api/v2/channels/{channel_name}/clips',
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    clips = data.get('clips', [])[:limit]
                    return clips
                else:
                    print(f"[Kick] Failed to get clips: HTTP {response.status}")
                    return None
    except Exception as e:
        print(f"[Kick] Error getting clips: {type(e).__name__}: {str(e)}")
        return None

class KickHybridAPI:
    """
    Hybrid Kick API client that uses official API when authenticated,
    with fallback to unofficial API for unauthenticated requests.

    This is the recommended class to use for maximum compatibility.

    Usage:
        api = KickHybridAPI(access_token="your_oauth_token")
        await api.setup()

        # Official API (with auth)
        await api.send_message("Hello!", broadcaster_id=123)

        # Unofficial API (fallback)
        channel_info = await api.get_channel_info("channelname")
    """

    def __init__(
        self,
        access_token: str = None,
        refresh_token: str = None,
        client_id: str = None,
        client_secret: str = None,
    ):
        self.access_token = access_token or os.getenv("KICK_BOT_USER_TOKEN")
        self.refresh_token = refresh_token
        self.client_id = client_id or os.getenv("KICK_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("KICK_CLIENT_SECRET")

        self._official_api: Optional[KickOfficialAPI] = None
        self._session: Optional[aiohttp.ClientSession] = None

    @property
    def is_authenticated(self) -> bool:
        """Check if we have valid OAuth credentials"""
        return bool(self.access_token) and HAS_OFFICIAL_API

    async def setup(self):
        """Initialize API clients"""
        if self.is_authenticated:
            self._official_api = KickOfficialAPI(
                client_id=self.client_id,
                client_secret=self.client_secret,
                access_token=self.access_token,
                refresh_token=self.refresh_token,
            )
            print("[KickHybrid] ✅ Official API client initialized with OAuth token")
        else:
            print("[KickHybrid] ℹ️  Running in unauthenticated mode (unofficial API only)")

    async def close(self):
        """Cleanup resources"""
        if self._official_api:
            await self._official_api.close()
        if self._session and not self._session.closed:
            await self._session.close()

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session for unofficial API"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    # -------------------------
    # Chat Methods
    # -------------------------

    async def send_message(
        self,
        content: str,
        broadcaster_user_id: int = None,
        reply_to_message_id: str = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Send a chat message using Official API.
        Requires OAuth token with chat:write scope.

        Args:
            content: Message content (max 500 chars)
            broadcaster_user_id: Target channel's broadcaster ID
            reply_to_message_id: Message ID to reply to

        Returns:
            API response or None if failed
        """
        if not self.is_authenticated:
            print("[KickHybrid] ❌ Cannot send message: No OAuth token")
            return None

        try:
            return await self._official_api.send_chat_message(
                content=content,
                broadcaster_user_id=broadcaster_user_id,
                reply_to_message_id=reply_to_message_id,
            )
        except Exception as e:
            print(f"[KickHybrid] ❌ Failed to send message: {e}")
            return None

    # -------------------------
    # Channel Methods (Hybrid)
    # -------------------------

    async def get_channel_info(self, channel_name: str) -> Optional[Dict[str, Any]]:
        """
        Get channel information. Uses unofficial API for this.

        Args:
            channel_name: The Kick channel name/slug

        Returns:
            Channel data dict or None if failed
        """
        # Unofficial API works fine for channel info
        return await get_channel_info(channel_name)

    async def check_stream_live(self, channel_name: str) -> bool:
        """
        Check if a channel is currently live.

        Args:
            channel_name: The Kick channel name/slug

        Returns:
            True if live, False otherwise
        """
        # Use official API if authenticated, otherwise unofficial
        if self.is_authenticated:
            try:
                # Would need broadcaster_user_id for official API
                # Fall back to unofficial for now
                return await check_stream_live(channel_name)
            except Exception:
                pass

        return await check_stream_live(channel_name)

    async def fetch_chatroom_id(self, channel_name: str, max_retries: int = 5) -> Optional[str]:
        """
        Fetch chatroom ID for a channel.

        Args:
            channel_name: The Kick channel name
            max_retries: Maximum retry attempts

        Returns:
            Chatroom ID string or None
        """
        return await fetch_chatroom_id(channel_name, max_retries)

    # -------------------------
    # Webhook Methods (Official API only)
    # -------------------------

    async def subscribe_to_webhooks(
        self,
        callback_url: str,
        events: List[str] = None,
        broadcaster_user_id: int = None,
    ) -> List[Dict]:
        """
        Subscribe to webhook events. Requires OAuth with events:subscribe scope.

        Args:
            callback_url: HTTPS URL to receive webhooks
            events: List of event types to subscribe to
            broadcaster_user_id: Filter to specific broadcaster

        Returns:
            List of subscription results
        """
        if not self.is_authenticated:
            print("[KickHybrid] ❌ Cannot subscribe to webhooks: No OAuth token")
            return []

        if events is None:
            # Default to useful events for a bot
            events = [
                "chat.message.sent",
                "channel.subscription.new",
                "channel.subscription.gifts",
                "livestream.status.updated",
                "kicks.gifted",
            ]

        results = []
        for event in events:
            try:
                sub = await self._official_api.subscribe_webhook(
                    event=event,
                    callback_url=callback_url,
                    broadcaster_user_id=broadcaster_user_id,
                )
                results.append({"event": event, "success": True, "subscription": sub})
                print(f"[KickHybrid] ✅ Subscribed to {event}")
            except Exception as e:
                results.append({"event": event, "success": False, "error": str(e)})
                print(f"[KickHybrid] ❌ Failed to subscribe to {event}: {e}")

        return results

    async def get_webhook_subscriptions(self) -> List:
        """
        Get all active webhook subscriptions.

        Returns:
            List of WebhookSubscription objects
        """
        if not self.is_authenticated:
            return []

        try:
            return await self._official_api.get_webhook_subscriptions()
        except Exception as e:
            print(f"[KickHybrid] ❌ Failed to get webhooks: {e}")
            return []

    # -------------------------
    # Moderation Methods (Official API only)
    # -------------------------

    async def ban_user(
        self,
        broadcaster_user_id: int,
        user_id: int,
        duration_minutes: int = None,
        reason: str = None,
    ) -> bool:
        """
        Ban a user from chat. Requires OAuth with moderation:ban scope.

        Args:
            broadcaster_user_id: The broadcaster's user ID
            user_id: User ID to ban
            duration_minutes: Ban duration (None = permanent)
            reason: Ban reason

        Returns:
            True if successful
        """
        if not self.is_authenticated:
            print("[KickHybrid] ❌ Cannot ban user: No OAuth token")
            return False

        try:
            await self._official_api.ban_user(
                broadcaster_user_id=broadcaster_user_id,
                user_id=user_id,
                duration_minutes=duration_minutes,
                reason=reason,
            )
            return True
        except Exception as e:
            print(f"[KickHybrid] ❌ Failed to ban user: {e}")
            return False

    async def unban_user(
        self,
        broadcaster_user_id: int,
        user_id: int,
    ) -> bool:
        """
        Unban a user from chat. Requires OAuth with moderation:ban scope.

        Args:
            broadcaster_user_id: The broadcaster's user ID
            user_id: User ID to unban

        Returns:
            True if successful
        """
        if not self.is_authenticated:
            print("[KickHybrid] ❌ Cannot unban user: No OAuth token")
            return False

        try:
            await self._official_api.unban_user(
                broadcaster_user_id=broadcaster_user_id,
                user_id=user_id,
            )
            return True
        except Exception as e:
            print(f"[KickHybrid] ❌ Failed to unban user: {e}")
            return False

    # -------------------------
    # Kicks (Tips) Methods
    # -------------------------

    async def get_kicks_leaderboard(
        self,
        broadcaster_user_id: int,
        range_type: str = "all_time",
    ) -> Optional[Dict]:
        """
        Get the Kicks (tips) leaderboard. Requires OAuth with kicks:read scope.

        Args:
            broadcaster_user_id: The broadcaster's user ID
            range_type: "all_time", "month", or "week"

        Returns:
            Leaderboard data or None
        """
        if not self.is_authenticated:
            print("[KickHybrid] ❌ Cannot get kicks leaderboard: No OAuth token")
            return None

        try:
            return await self._official_api.get_kicks_leaderboard(
                broadcaster_user_id=broadcaster_user_id,
                range_type=range_type,
            )
        except Exception as e:
            print(f"[KickHybrid] ❌ Failed to get kicks leaderboard: {e}")
            return None

# Export all public interfaces
__all__ = [
    'KickAPI',
    'KickHybridAPI',
    'fetch_chatroom_id',
    'check_stream_live',
    'get_channel_info',
    'create_clip',
    'get_clips',
    'USER_AGENTS',
    'REFERRERS',
    'COUNTRY_CODES',
    'HAS_OFFICIAL_API',
]
