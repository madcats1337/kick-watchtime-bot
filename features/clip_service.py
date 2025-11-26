"""
Custom Clip Service for Kick Streams

This service creates clips by capturing the HLS stream directly,
similar to how KickBot implements their clip feature.

Architecture:
1. Get the HLS stream URL from Kick's channel API
2. Use FFmpeg to capture from the DVR/rewind segments (past content)
3. Store clip locally or upload to cloud storage
4. Return clip URL for sharing

Note: Kick's HLS streams support DVR, so we can capture past segments.
"""

import os
import asyncio
import aiohttp
import uuid
import subprocess
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List
import random

# User agents for requests
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
]

# Directory to store clips
CLIPS_DIR = Path("clips")
CLIPS_DIR.mkdir(exist_ok=True)

# Base URL for serving clips - uses OAUTH_BASE_URL since that's where the Flask server runs
# Falls back to CLIPS_BASE_URL if set explicitly
CLIPS_BASE_URL = os.getenv("CLIPS_BASE_URL", os.getenv("OAUTH_BASE_URL", ""))


async def get_stream_url(channel_name: str) -> Optional[str]:
    """
    Get the HLS stream URL for a Kick channel.
    
    Args:
        channel_name: The Kick channel slug
        
    Returns:
        HLS playlist URL or None if not live
    """
    try:
        async with aiohttp.ClientSession() as session:
            headers = {
                'User-Agent': random.choice(USER_AGENTS),
                'Accept': 'application/json',
                'Referer': 'https://kick.com/',
            }
            
            # Get channel info which includes livestream data
            async with session.get(
                f'https://kick.com/api/v2/channels/{channel_name}',
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status != 200:
                    print(f"[Clip] Failed to get channel info: HTTP {response.status}")
                    return None
                    
                data = await response.json()
                
                # Check if stream is live
                livestream = data.get('livestream')
                if not livestream:
                    print(f"[Clip] Channel {channel_name} is not live")
                    return None
                
                # Get playback URL from livestream data
                # Kick uses different structures, try multiple paths
                playback_url = None
                
                # Try direct playback_url
                if 'playback_url' in livestream:
                    playback_url = livestream['playback_url']
                
                # Try source array
                if not playback_url and 'source' in livestream:
                    sources = livestream['source']
                    if isinstance(sources, list) and sources:
                        playback_url = sources[0].get('src') or sources[0].get('url')
                    elif isinstance(sources, dict):
                        playback_url = sources.get('src') or sources.get('url')
                
                # Try video object
                if not playback_url and 'video' in livestream:
                    video = livestream['video']
                    if isinstance(video, dict):
                        playback_url = video.get('src') or video.get('url')
                
                # Try session data
                if not playback_url:
                    session_data = data.get('session') or livestream.get('session')
                    if session_data:
                        playback_url = session_data.get('playback_url')
                
                if playback_url:
                    print(f"[Clip] Found stream URL: {playback_url[:50]}...")
                    return playback_url
                else:
                    print(f"[Clip] Could not find playback URL in channel data")
                    # Log the structure to help debug
                    print(f"[Clip] Livestream keys: {livestream.keys() if livestream else 'None'}")
                    return None
                    
    except Exception as e:
        print(f"[Clip] Error getting stream URL: {type(e).__name__}: {str(e)}")
        return None


async def create_clip_ffmpeg(
    stream_url: str,
    duration: int = 30,
    channel_name: str = "",
    username: str = "",
    title: str = ""
) -> Optional[Dict[str, Any]]:
    """
    Create a clip using FFmpeg to capture from HLS stream.
    
    Uses the DVR/rewind capability of the HLS stream to capture
    the PAST N seconds rather than live content.
    
    Args:
        stream_url: HLS playlist URL
        duration: Clip duration in seconds
        channel_name: Channel name for metadata
        username: User who requested the clip
        title: Clip title
        
    Returns:
        Dict with clip info or None if failed
    """
    try:
        # Generate unique clip ID
        clip_id = str(uuid.uuid4())[:8]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"clip_{channel_name}_{timestamp}_{clip_id}.mp4"
        filepath = CLIPS_DIR / filename
        
        print(f"[Clip] Creating clip with FFmpeg: {filename} ({duration}s)")
        
        # FFmpeg command to capture the PAST N seconds from stream
        # -sseof: seek from end (negative = seconds before end)
        # -t: duration to capture
        # -c copy: copy streams without re-encoding (fast)
        # 
        # For HLS DVR streams, we use -live_start_index to go back
        cmd = [
            'ffmpeg',
            '-y',  # Overwrite output
            '-live_start_index', str(-duration // 2),  # Start from earlier segments
            '-i', stream_url,
            '-t', str(duration),
            '-c', 'copy',  # Copy without re-encoding
            '-movflags', '+faststart',  # Optimize for web playback
            '-avoid_negative_ts', 'make_zero',
            str(filepath)
        ]
        
        print(f"[Clip] Running FFmpeg command...")
        
        # Run FFmpeg asynchronously
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=duration + 60  # Give extra time for processing
        )
        
        if process.returncode != 0:
            error_output = stderr.decode()
            print(f"[Clip] FFmpeg error (code {process.returncode}): {error_output[:500]}")
            
            # Check for common errors
            if "Server returned 403 Forbidden" in error_output:
                return {'error': 'forbidden', 'message': 'Stream access denied'}
            if "Server returned 404 Not Found" in error_output:
                return {'error': 'not_found', 'message': 'Stream not found'}
                
            return None
        
        # Check if file was created
        if not filepath.exists():
            print(f"[Clip] Clip file was not created")
            return None
        
        file_size = filepath.stat().st_size
        print(f"[Clip] ✅ Clip created: {filename} ({file_size / 1024 / 1024:.2f} MB)")
        
        # Generate clip URL
        if CLIPS_BASE_URL:
            clip_url = f"{CLIPS_BASE_URL}/{filename}"
        else:
            clip_url = f"/clips/{filename}"
        
        return {
            'clip_id': clip_id,
            'filename': filename,
            'filepath': str(filepath),
            'clip_url': clip_url,
            'duration': duration,
            'channel': channel_name,
            'created_by': username,
            'title': title,
            'created_at': datetime.now().isoformat(),
            'file_size': file_size
        }
        
    except asyncio.TimeoutError:
        print(f"[Clip] FFmpeg timed out")
        return None
    except FileNotFoundError:
        print(f"[Clip] FFmpeg not found - please install FFmpeg")
        return {'error': 'ffmpeg_not_found', 'message': 'FFmpeg is not installed on the server'}
    except Exception as e:
        print(f"[Clip] Error creating clip: {type(e).__name__}: {str(e)}")
        return None


async def create_clip(
    channel_name: str,
    duration: int = 30,
    username: str = "",
    title: str = ""
) -> Optional[Dict[str, Any]]:
    """
    Main clip creation function.
    
    Args:
        channel_name: Kick channel slug
        duration: Clip duration in seconds (max 120)
        username: User who requested the clip
        title: Optional clip title
        
    Returns:
        Dict with clip info or error
    """
    # Validate duration
    duration = min(max(duration, 10), 120)  # 10-120 seconds
    
    # Get stream URL
    stream_url = await get_stream_url(channel_name)
    if not stream_url:
        return {'error': 'not_live', 'message': 'Stream must be live to create clips'}
    
    # Create the clip
    result = await create_clip_ffmpeg(
        stream_url=stream_url,
        duration=duration,
        channel_name=channel_name,
        username=username,
        title=title or f"Clip by {username}"
    )
    
    return result


def get_clip_path(filename: str) -> Optional[Path]:
    """Get the full path to a clip file."""
    filepath = CLIPS_DIR / filename
    if filepath.exists():
        return filepath
    return None


def list_clips(channel_name: str = None, limit: int = 20) -> list:
    """List available clips, optionally filtered by channel."""
    clips = []
    for filepath in sorted(CLIPS_DIR.glob("clip_*.mp4"), reverse=True)[:limit]:
        if channel_name and channel_name not in filepath.name:
            continue
        stat = filepath.stat()
        clips.append({
            'filename': filepath.name,
            'size': stat.st_size,
            'created': datetime.fromtimestamp(stat.st_mtime).isoformat()
        })
    return clips


def cleanup_old_clips(max_age_hours: int = 24):
    """Delete clips older than max_age_hours."""
    import time
    cutoff = time.time() - (max_age_hours * 3600)
    deleted = 0
    for filepath in CLIPS_DIR.glob("clip_*.mp4"):
        if filepath.stat().st_mtime < cutoff:
            filepath.unlink()
            deleted += 1
    if deleted:
        print(f"[Clip] Cleaned up {deleted} old clips")
    return deleted
