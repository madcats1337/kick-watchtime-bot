"""
Stream Monitor Service

Watches for stream live/offline status and manages the rolling buffer.
Automatically starts recording when stream goes live and stops when offline.
"""

import asyncio
import aiohttp
from typing import Optional, Callable, Any
from datetime import datetime
import random

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
]


class StreamMonitor:
    """
    Monitors a Kick channel for live status and manages the stream buffer.
    
    Usage:
        from features.stream_buffer import StreamBuffer
        
        buffer = StreamBuffer("channelname")
        monitor = StreamMonitor("channelname", buffer)
        
        # Start monitoring (runs in background)
        asyncio.create_task(monitor.start())
        
        # Stop monitoring
        await monitor.stop()
    """
    
    def __init__(
        self,
        channel_name: str,
        buffer: Any = None,  # StreamBuffer instance
        check_interval: int = 30,
        on_live: Optional[Callable] = None,
        on_offline: Optional[Callable] = None
    ):
        """
        Initialize stream monitor.
        
        Args:
            channel_name: Kick channel to monitor
            buffer: StreamBuffer instance to control
            check_interval: Seconds between live checks
            on_live: Callback when stream goes live
            on_offline: Callback when stream goes offline
        """
        self.channel_name = channel_name
        self.buffer = buffer
        self.check_interval = check_interval
        self.on_live = on_live
        self.on_offline = on_offline
        
        self.is_monitoring = False
        self.is_live = False
        self.stream_title: Optional[str] = None
        self.stream_started_at: Optional[datetime] = None
        self.last_check: Optional[datetime] = None
        
        print(f"[Monitor] Initialized for {channel_name}, checking every {check_interval}s")
    
    async def check_stream_status(self) -> dict:
        """
        Check current stream status from Kick API.
        
        Returns:
            Dict with is_live, title, stream_url, etc.
        """
        try:
            async with aiohttp.ClientSession() as session:
                headers = {
                    'User-Agent': random.choice(USER_AGENTS),
                    'Accept': 'application/json',
                }
                
                # Use v1 API - it has playback_url, v2 doesn't
                url = f'https://kick.com/api/v1/channels/{self.channel_name}'
                async with session.get(url, headers=headers, timeout=10) as response:
                    if response.status != 200:
                        return {'is_live': False, 'error': f'HTTP {response.status}'}
                    
                    data = await response.json()
                    livestream = data.get('livestream')
                    
                    if not livestream:
                        return {'is_live': False}
                    
                    # v1 API has playback_url at root level
                    stream_url = data.get('playback_url') or livestream.get('playback_url')
                    
                    # Extract stream info
                    return {
                        'is_live': True,
                        'title': livestream.get('session_title', ''),
                        'started_at': livestream.get('created_at'),
                        'viewer_count': livestream.get('viewer_count', 0),
                        'stream_url': stream_url,
                        'thumbnail': livestream.get('thumbnail', {}).get('url'),
                    }
                    
        except asyncio.TimeoutError:
            return {'is_live': False, 'error': 'timeout'}
        except Exception as e:
            return {'is_live': False, 'error': str(e)}
    
    async def start(self):
        """Start monitoring the stream (runs continuously)."""
        if self.is_monitoring:
            print(f"[Monitor] Already monitoring {self.channel_name}")
            return
        
        self.is_monitoring = True
        print(f"[Monitor] ▶️ Started monitoring {self.channel_name}")
        
        while self.is_monitoring:
            try:
                status = await self.check_stream_status()
                self.last_check = datetime.now()
                
                was_live = self.is_live
                is_now_live = status.get('is_live', False)
                
                # Stream went LIVE
                if is_now_live and not was_live:
                    self.is_live = True
                    self.stream_title = status.get('title')
                    self.stream_started_at = datetime.now()
                    
                    print(f"[Monitor] 🔴 Stream is LIVE: {self.stream_title}")
                    
                    # Start buffer recording
                    if self.buffer:
                        stream_url = status.get('stream_url')
                        await self.buffer.start(stream_url)
                    
                    # Call live callback
                    if self.on_live:
                        try:
                            result = self.on_live(status)
                            if asyncio.iscoroutine(result):
                                await result
                        except Exception as e:
                            print(f"[Monitor] on_live callback error: {e}")
                
                # Stream went OFFLINE
                elif not is_now_live and was_live:
                    self.is_live = False
                    duration = None
                    if self.stream_started_at:
                        duration = (datetime.now() - self.stream_started_at).total_seconds()
                    
                    print(f"[Monitor] ⚫ Stream is OFFLINE (was live for {duration/60:.1f} min)" if duration else "[Monitor] ⚫ Stream is OFFLINE")
                    
                    # Stop buffer recording
                    if self.buffer:
                        await self.buffer.stop()
                    
                    # Call offline callback
                    if self.on_offline:
                        try:
                            result = self.on_offline({'duration': duration})
                            if asyncio.iscoroutine(result):
                                await result
                        except Exception as e:
                            print(f"[Monitor] on_offline callback error: {e}")
                    
                    self.stream_title = None
                    self.stream_started_at = None
                
                # Still live - update viewer count etc
                elif is_now_live:
                    viewer_count = status.get('viewer_count', 0)
                    # Only log occasionally to reduce spam
                    if hasattr(self, '_last_viewer_log'):
                        if (datetime.now() - self._last_viewer_log).total_seconds() > 300:
                            print(f"[Monitor] 🔴 Live: {viewer_count} viewers")
                            self._last_viewer_log = datetime.now()
                    else:
                        self._last_viewer_log = datetime.now()
                
            except Exception as e:
                print(f"[Monitor] Error during check: {e}")
            
            # Wait before next check
            await asyncio.sleep(self.check_interval)
        
        print(f"[Monitor] Stopped monitoring {self.channel_name}")
    
    async def stop(self):
        """Stop monitoring."""
        self.is_monitoring = False
        
        # Also stop buffer if running
        if self.buffer and self.buffer.is_recording:
            await self.buffer.stop()
        
        print(f"[Monitor] ⏹️ Monitoring stopped for {self.channel_name}")
    
    def get_status(self) -> dict:
        """Get current monitor status."""
        return {
            'channel': self.channel_name,
            'is_monitoring': self.is_monitoring,
            'is_live': self.is_live,
            'stream_title': self.stream_title,
            'stream_started_at': self.stream_started_at.isoformat() if self.stream_started_at else None,
            'last_check': self.last_check.isoformat() if self.last_check else None,
            'buffer_active': self.buffer.is_recording if self.buffer else False,
        }


# Global monitor instance
_stream_monitor: Optional[StreamMonitor] = None


def get_monitor() -> Optional[StreamMonitor]:
    """Get the global stream monitor instance."""
    return _stream_monitor


def init_monitor(channel_name: str, buffer: Any = None, check_interval: int = 30) -> StreamMonitor:
    """Initialize the global stream monitor."""
    global _stream_monitor
    _stream_monitor = StreamMonitor(channel_name, buffer, check_interval)
    return _stream_monitor
