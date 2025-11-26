"""
Kick.com API Integration Module
Handles chatroom ID fetching and API interactions with Kick.com
"""

import asyncio
import json
import random
from typing import Optional, Dict, Any
import aiohttp

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


async def create_clip(channel_name: str, duration_seconds: int = 30, title: str = None) -> Optional[Dict[str, Any]]:
    """
    Create a clip of the current livestream.
    
    This uses the Kick API's clip creation endpoints:
    1. GET /api/v2/channels/{channel}/clips/init - Initialize clip creation
    2. POST /api/v2/channels/{channel}/clips/finalize - Finalize the clip
    
    NOTE: This requires the stream to be live and may require authentication.
    The Kick clip API is not fully documented, so this is a best-effort implementation.
    
    Args:
        channel_name: The Kick channel name/slug
        duration_seconds: Duration of the clip in seconds (default 30)
        title: Custom title for the clip (optional)
        
    Returns:
        Dict with clip info (url, id, etc.) or None if failed
    """
    try:
        async with aiohttp.ClientSession() as session:
            headers = {
                'User-Agent': random.choice(USER_AGENTS),
                'Accept': 'application/json',
                'Content-Type': 'application/json',
                'Referer': f'https://kick.com/{channel_name}',
                'Origin': 'https://kick.com',
            }
            
            # Step 1: Initialize clip creation
            init_url = f'https://kick.com/api/v2/channels/{channel_name}/clips/init'
            async with session.get(init_url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as response:
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


# Export all public interfaces
__all__ = ['KickAPI', 'fetch_chatroom_id', 'check_stream_live', 'get_channel_info', 'create_clip', 'get_clips', 'USER_AGENTS', 'REFERRERS', 'COUNTRY_CODES']
