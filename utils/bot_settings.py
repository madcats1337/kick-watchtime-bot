"""
Bot Settings Manager
Loads configuration from database with fallback to environment variables.
Supports real-time updates via Redis pub/sub.
"""

import os
from typing import Optional, Dict, Any, Union
from datetime import datetime, timezone
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


class BotSettingsManager:
    """
    Manages bot configuration settings from database.
    
    Settings are loaded from the bot_settings table with fallback to
    environment variables for backwards compatibility.
    
    Usage:
        settings = BotSettingsManager(engine)  # Pass SQLAlchemy engine
        # OR
        settings = BotSettingsManager(database_url)  # Pass connection string
        
        # Get a setting (with env var fallback)
        channel = settings.get('kick_channel', env_fallback='KICK_CHANNEL')
        
        # Get as specific type
        channel_id = settings.get_int('slot_calls_channel_id')
        auto_draw = settings.get_bool('raffle_auto_draw')
        
        # Reload from database
        settings.refresh()
    """
    
    def __init__(self, database_or_engine: Union[str, Engine]):
        """
        Initialize settings manager.
        
        Args:
            database_or_engine: Either a SQLAlchemy Engine or a database URL string
        """
        self._cache: Dict[str, str] = {}
        self._last_loaded: Optional[datetime] = None
        self._engine: Optional[Engine] = None
        
        # Accept either an Engine or a connection string
        if isinstance(database_or_engine, Engine):
            self._engine = database_or_engine
        elif database_or_engine:
            # It's a connection string
            database_url = database_or_engine
            if database_url.startswith('postgres://'):
                database_url = database_url.replace('postgres://', 'postgresql://', 1)
            self._engine = create_engine(database_url, pool_pre_ping=True)
        
        # Load settings
        self.refresh()
    
    def refresh(self) -> bool:
        """
        Refresh settings from database.
        
        Returns:
            True if successful, False otherwise
        """
        if not self._engine:
            print("[Settings] No database engine, using env vars only")
            return False
        
        try:
            with self._engine.connect() as conn:
                result = conn.execute(text("SELECT key, value FROM bot_settings"))
                rows = result.fetchall()
                
                self._cache = {row[0]: row[1] for row in rows}
                self._last_loaded = datetime.now(timezone.utc)
                
                print(f"[Settings] Loaded {len(self._cache)} settings from database")
                return True
        except Exception as e:
            print(f"[Settings] Error loading settings: {e}")
            return False
    
    # Alias for backwards compatibility
    reload = refresh
    
    def get(
        self,
        key: str,
        default: str = '',
        env_fallback: Optional[str] = None
    ) -> str:
        """
        Get a setting value.
        
        Priority:
        1. Database value (if not empty)
        2. Environment variable (if env_fallback specified)
        3. Default value
        
        Args:
            key: Setting key
            default: Default value if not found
            env_fallback: Environment variable name to check as fallback
            
        Returns:
            Setting value as string
        """
        # Check database cache
        db_value = self._cache.get(key, '')
        if db_value:
            return db_value
        
        # Check environment variable
        if env_fallback:
            env_value = os.getenv(env_fallback, '')
            if env_value:
                return env_value
        
        return default
    
    def get_int(
        self,
        key: str,
        default: int = 0,
        env_fallback: Optional[str] = None
    ) -> Optional[int]:
        """
        Get a setting as integer.
        
        Returns:
            Integer value or None if empty/invalid
        """
        value = self.get(key, '', env_fallback)
        if not value:
            return default if default != 0 else None
        
        try:
            return int(value)
        except (ValueError, TypeError):
            return default if default != 0 else None
    
    def get_bool(
        self,
        key: str,
        default: bool = False,
        env_fallback: Optional[str] = None
    ) -> bool:
        """
        Get a setting as boolean.
        
        Truthy values: 'true', '1', 'yes', 'on'
        """
        value = self.get(key, '', env_fallback).lower()
        if not value:
            return default
        return value in ('true', '1', 'yes', 'on')
    
    def set(self, key: str, value: Any) -> bool:
        """
        Update a setting in the database.
        
        Args:
            key: Setting key
            value: New value (will be converted to string)
            
        Returns:
            True if successful
        """
        if not self._engine:
            return False
        
        try:
            str_value = str(value) if value is not None else ''
            
            with self._engine.begin() as conn:
                conn.execute(text("""
                    INSERT INTO bot_settings (key, value, updated_at)
                    VALUES (:key, :value, CURRENT_TIMESTAMP)
                    ON CONFLICT (key) DO UPDATE 
                    SET value = :value, updated_at = CURRENT_TIMESTAMP
                """), {'key': key, 'value': str_value})
            
            # Update cache
            self._cache[key] = str_value
            return True
        except Exception as e:
            print(f"[Settings] Error setting {key}: {e}")
            return False
    
    @property
    def kick_channel(self) -> str:
        """Kick channel name (e.g., 'maikelele')"""
        return self.get('kick_channel', env_fallback='KICK_CHANNEL')
    
    @property
    def kick_chatroom_id(self) -> Optional[str]:
        """Kick chatroom ID (cached)"""
        return self.get('kick_chatroom_id', env_fallback='KICK_CHATROOM_ID') or None
    
    @property
    def kick_broadcaster_user_id(self) -> Optional[int]:
        """Kick broadcaster user ID from OAuth"""
        return self.get_int('kick_broadcaster_user_id')
    
    @property
    def slot_calls_channel_id(self) -> Optional[int]:
        """Discord channel ID for slot calls"""
        return self.get_int('slot_calls_channel_id', env_fallback='SLOT_CALLS_CHANNEL_ID')
    
    @property
    def raffle_announcement_channel_id(self) -> Optional[int]:
        """Discord channel ID for raffle announcements"""
        return self.get_int('raffle_announcement_channel_id', env_fallback='RAFFLE_ANNOUNCEMENT_CHANNEL_ID')
    
    @property
    def raffle_leaderboard_channel_id(self) -> Optional[int]:
        """Discord channel ID for raffle leaderboard"""
        return self.get_int('raffle_leaderboard_channel_id', env_fallback='RAFFLE_LEADERBOARD_CHANNEL_ID')
    
    @property
    def raffle_auto_draw(self) -> bool:
        """Whether to automatically draw raffle at period end"""
        return self.get_bool('raffle_auto_draw', env_fallback='RAFFLE_AUTO_DRAW')
    
    @property
    def gtb_channel_id(self) -> Optional[int]:
        """Discord channel ID for Guess The Balance"""
        # Falls back to slot_calls_channel_id if not set
        gtb = self.get_int('gtb_channel_id')
        if gtb:
            return gtb
        return self.slot_calls_channel_id
    
    @property
    def clip_duration(self) -> int:
        """Default clip duration in seconds"""
        return self.get_int('clip_duration', default=30)
    
    @property
    def dashboard_url(self) -> str:
        """Dashboard API URL for clip service etc."""
        return self.get('dashboard_url', env_fallback='DASHBOARD_API_URL') or self.get('dashboard_url', env_fallback='DASHBOARD_URL')
    
    @property
    def bot_api_key(self) -> str:
        """API key for authenticating with Dashboard"""
        return self.get('bot_api_key', env_fallback='BOT_API_KEY')
    
    def to_dict(self) -> Dict[str, Any]:
        """Get all settings as a dictionary"""
        return {
            'kick_channel': self.kick_channel,
            'kick_chatroom_id': self.kick_chatroom_id,
            'kick_broadcaster_user_id': self.kick_broadcaster_user_id,
            'slot_calls_channel_id': self.slot_calls_channel_id,
            'raffle_announcement_channel_id': self.raffle_announcement_channel_id,
            'raffle_leaderboard_channel_id': self.raffle_leaderboard_channel_id,
            'raffle_auto_draw': self.raffle_auto_draw,
            'gtb_channel_id': self.gtb_channel_id,
            'clip_duration': self.clip_duration,
            'dashboard_url': self.dashboard_url,
            'bot_api_key': '***' if self.bot_api_key else '',  # Don't expose key
        }


# Global settings instance (initialized in bot.py)
_settings: Optional[BotSettingsManager] = None


def get_settings() -> Optional[BotSettingsManager]:
    """Get the global settings manager instance"""
    return _settings


def init_settings(database_url: str) -> BotSettingsManager:
    """Initialize the global settings manager"""
    global _settings
    _settings = BotSettingsManager(database_url)
    return _settings
