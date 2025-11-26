"""
Stream Rolling Buffer Service

Continuously records the livestream to rotating segment files,
allowing clips of the PAST N seconds to be created on demand.

Architecture:
- FFmpeg writes 10-second .ts segments
- Segments rotate after max_segments (e.g., 24 = 4 minutes)
- When !clip is called, recent segments are concatenated into MP4
"""

import os
import asyncio
import aiohttp
from pathlib import Path
from datetime import datetime
from typing import Optional, List
import random

# Buffer configuration
BUFFER_DIR = Path("buffer")
BUFFER_DIR.mkdir(exist_ok=True)

CLIPS_DIR = Path("clips")
CLIPS_DIR.mkdir(exist_ok=True)

# User agents for API requests
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
]


class StreamBuffer:
    """
    Rolling buffer that continuously records the livestream.
    
    Usage:
        buffer = StreamBuffer("channelname", buffer_minutes=4)
        await buffer.start()  # Call when stream goes live
        
        # Later, when !clip is called:
        clip_path = await buffer.create_clip(duration=30)
        
        await buffer.stop()  # Call when stream goes offline
    """
    
    def __init__(self, channel_name: str, buffer_minutes: int = 4):
        self.channel_name = channel_name
        self.buffer_minutes = buffer_minutes
        self.segment_duration = 10  # seconds per segment
        self.max_segments = (buffer_minutes * 60) // self.segment_duration
        
        self.ffmpeg_process: Optional[asyncio.subprocess.Process] = None
        self.is_recording = False
        self.stream_url: Optional[str] = None
        self.started_at: Optional[datetime] = None
        
        # Segment tracking
        self.segment_list_file = BUFFER_DIR / "segments.txt"
        
        print(f"[Buffer] Initialized for {channel_name}: {buffer_minutes}min buffer, {self.max_segments} segments")
    
    async def get_stream_url(self) -> Optional[str]:
        """Fetch the HLS stream URL from Kick API."""
        try:
            async with aiohttp.ClientSession() as session:
                headers = {
                    'User-Agent': random.choice(USER_AGENTS),
                    'Accept': 'application/json',
                }
                
                url = f'https://kick.com/api/v2/channels/{self.channel_name}'
                async with session.get(url, headers=headers, timeout=10) as response:
                    if response.status != 200:
                        return None
                    
                    data = await response.json()
                    livestream = data.get('livestream')
                    
                    if not livestream:
                        return None
                    
                    # Try to find playback URL
                    playback_url = (
                        livestream.get('playback_url') or
                        livestream.get('source', [{}])[0].get('src') if isinstance(livestream.get('source'), list) else None
                    )
                    
                    return playback_url
                    
        except Exception as e:
            print(f"[Buffer] Error getting stream URL: {e}")
            return None
    
    async def check_stream_live(self) -> bool:
        """Check if the stream is currently live."""
        try:
            async with aiohttp.ClientSession() as session:
                headers = {'User-Agent': random.choice(USER_AGENTS)}
                url = f'https://kick.com/api/v2/channels/{self.channel_name}'
                
                async with session.get(url, headers=headers, timeout=10) as response:
                    if response.status != 200:
                        return False
                    
                    data = await response.json()
                    return data.get('livestream') is not None
                    
        except Exception:
            return False
    
    async def start(self, stream_url: Optional[str] = None) -> bool:
        """
        Start recording the stream to rolling buffer.
        
        Args:
            stream_url: Optional HLS URL. If not provided, will fetch from API.
            
        Returns:
            True if recording started successfully.
        """
        if self.is_recording:
            print(f"[Buffer] Already recording")
            return True
        
        # Get stream URL if not provided
        if not stream_url:
            stream_url = await self.get_stream_url()
        
        if not stream_url:
            print(f"[Buffer] No stream URL available - stream may not be live")
            return False
        
        self.stream_url = stream_url
        
        # Clean old buffer files
        await self._cleanup_buffer()
        
        # Build FFmpeg command for rolling buffer
        # -segment_wrap: number of segments before wrapping (overwriting oldest)
        # -segment_list: file listing current segments
        # -segment_list_type flat: simple list format
        segment_pattern = str(BUFFER_DIR / "seg_%04d.ts")
        
        cmd = [
            'ffmpeg',
            '-y',  # Overwrite
            '-i', stream_url,
            '-c', 'copy',  # No re-encoding
            '-f', 'segment',
            '-segment_time', str(self.segment_duration),
            '-segment_wrap', str(self.max_segments),
            '-segment_list', str(self.segment_list_file),
            '-segment_list_type', 'flat',
            '-segment_list_size', str(self.max_segments),
            '-reset_timestamps', '1',
            segment_pattern
        ]
        
        try:
            print(f"[Buffer] Starting FFmpeg recording...")
            print(f"[Buffer] Stream URL: {stream_url[:60]}...")
            
            self.ffmpeg_process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE
            )
            
            self.is_recording = True
            self.started_at = datetime.now()
            
            # Start background task to monitor FFmpeg
            asyncio.create_task(self._monitor_ffmpeg())
            
            print(f"[Buffer] ✅ Recording started for {self.channel_name}")
            return True
            
        except FileNotFoundError:
            print(f"[Buffer] ❌ FFmpeg not found - please install FFmpeg")
            return False
        except Exception as e:
            print(f"[Buffer] ❌ Failed to start recording: {e}")
            return False
    
    async def stop(self):
        """Stop recording."""
        if not self.is_recording:
            return
        
        self.is_recording = False
        
        if self.ffmpeg_process:
            try:
                self.ffmpeg_process.terminate()
                await asyncio.wait_for(self.ffmpeg_process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self.ffmpeg_process.kill()
            except Exception as e:
                print(f"[Buffer] Error stopping FFmpeg: {e}")
            
            self.ffmpeg_process = None
        
        print(f"[Buffer] Recording stopped")
    
    async def _monitor_ffmpeg(self):
        """Monitor FFmpeg process and restart if needed."""
        while self.is_recording and self.ffmpeg_process:
            try:
                # Check if process is still running
                if self.ffmpeg_process.returncode is not None:
                    stderr = await self.ffmpeg_process.stderr.read()
                    print(f"[Buffer] FFmpeg exited with code {self.ffmpeg_process.returncode}")
                    if stderr:
                        print(f"[Buffer] FFmpeg stderr: {stderr.decode()[:500]}")
                    
                    # Try to restart if still supposed to be recording
                    if self.is_recording:
                        print(f"[Buffer] Attempting to restart recording...")
                        self.ffmpeg_process = None
                        await asyncio.sleep(5)
                        await self.start()
                    break
                
                await asyncio.sleep(10)
                
            except Exception as e:
                print(f"[Buffer] Monitor error: {e}")
                await asyncio.sleep(10)
    
    async def _cleanup_buffer(self):
        """Remove old buffer files."""
        try:
            for f in BUFFER_DIR.glob("seg_*.ts"):
                f.unlink()
            if self.segment_list_file.exists():
                self.segment_list_file.unlink()
            print(f"[Buffer] Cleaned up old buffer files")
        except Exception as e:
            print(f"[Buffer] Cleanup error: {e}")
    
    def get_recent_segments(self, duration_seconds: int) -> List[Path]:
        """
        Get the most recent segment files for the requested duration.
        
        Args:
            duration_seconds: How many seconds of video to get
            
        Returns:
            List of segment file paths, oldest to newest
        """
        if not self.segment_list_file.exists():
            return []
        
        # Read segment list
        try:
            with open(self.segment_list_file, 'r') as f:
                segments = [line.strip() for line in f if line.strip()]
        except Exception:
            return []
        
        # Calculate how many segments we need
        num_segments = (duration_seconds // self.segment_duration) + 1
        num_segments = min(num_segments, len(segments))
        
        # Get the last N segments
        recent = segments[-num_segments:]
        
        # Convert to full paths and verify they exist
        paths = []
        for seg in recent:
            # Segment list contains just filenames
            path = BUFFER_DIR / seg
            if path.exists():
                paths.append(path)
        
        return paths
    
    async def create_clip(self, duration: int = 30, username: str = "", title: str = "") -> Optional[dict]:
        """
        Create a clip from the rolling buffer.
        
        Args:
            duration: Clip duration in seconds (max = buffer_minutes * 60)
            username: Who requested the clip
            title: Optional clip title
            
        Returns:
            Dict with clip info or None if failed
        """
        if not self.is_recording:
            print(f"[Buffer] Cannot create clip - not recording")
            return {'error': 'not_recording', 'message': 'Stream buffer not active'}
        
        # Limit duration to buffer size
        max_duration = self.buffer_minutes * 60
        duration = min(duration, max_duration)
        
        # Get recent segments
        segments = self.get_recent_segments(duration)
        
        if not segments:
            print(f"[Buffer] No segments available for clip")
            return {'error': 'no_segments', 'message': 'No buffer data available yet'}
        
        print(f"[Buffer] Creating clip from {len(segments)} segments ({duration}s requested)")
        
        # Generate clip filename
        import uuid
        clip_id = str(uuid.uuid4())[:8]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"clip_{self.channel_name}_{timestamp}_{clip_id}.mp4"
        output_path = CLIPS_DIR / filename
        
        # Create concat file for FFmpeg
        concat_file = BUFFER_DIR / f"concat_{clip_id}.txt"
        try:
            with open(concat_file, 'w') as f:
                for seg in segments:
                    # FFmpeg concat requires 'file' prefix
                    f.write(f"file '{seg.absolute()}'\n")
            
            # Concatenate segments into MP4
            cmd = [
                'ffmpeg',
                '-y',
                '-f', 'concat',
                '-safe', '0',
                '-i', str(concat_file),
                '-c', 'copy',
                '-movflags', '+faststart',
                str(output_path)
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=30
            )
            
            # Clean up concat file
            concat_file.unlink()
            
            if process.returncode != 0:
                print(f"[Buffer] FFmpeg concat error: {stderr.decode()[:300]}")
                return None
            
            if not output_path.exists():
                print(f"[Buffer] Clip file not created")
                return None
            
            file_size = output_path.stat().st_size
            
            # Calculate actual duration from segments
            actual_duration = len(segments) * self.segment_duration
            
            # Get base URL for clips
            clips_base_url = os.getenv("CLIPS_BASE_URL", os.getenv("OAUTH_BASE_URL", ""))
            if clips_base_url:
                clip_url = f"{clips_base_url}/clips/{filename}"
            else:
                clip_url = f"/clips/{filename}"
            
            print(f"[Buffer] ✅ Clip created: {filename} ({file_size / 1024 / 1024:.2f} MB)")
            
            return {
                'clip_id': clip_id,
                'filename': filename,
                'filepath': str(output_path),
                'clip_url': clip_url,
                'duration': actual_duration,
                'channel': self.channel_name,
                'created_by': username,
                'title': title or f"Clip by {username}",
                'created_at': datetime.now().isoformat(),
                'file_size': file_size
            }
            
        except asyncio.TimeoutError:
            print(f"[Buffer] Clip creation timed out")
            return None
        except Exception as e:
            print(f"[Buffer] Error creating clip: {e}")
            return None


# Global buffer instance (initialized by bot)
_stream_buffer: Optional[StreamBuffer] = None


def get_buffer() -> Optional[StreamBuffer]:
    """Get the global stream buffer instance."""
    return _stream_buffer


def init_buffer(channel_name: str, buffer_minutes: int = 4) -> StreamBuffer:
    """Initialize the global stream buffer."""
    global _stream_buffer
    _stream_buffer = StreamBuffer(channel_name, buffer_minutes)
    return _stream_buffer
