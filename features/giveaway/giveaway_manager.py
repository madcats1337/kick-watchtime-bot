"""
Giveaway Manager - Core giveaway logic

Handles giveaway lifecycle, entry tracking, and winner selection.
"""

import asyncio
import hashlib
from datetime import datetime, timedelta
from sqlalchemy import text
import logging

logger = logging.getLogger(__name__)


class GiveawayManager:
    """Manages giveaway system for a specific Discord server"""
    
    def __init__(self, engine, guild_id=None):
        self.engine = engine
        self.guild_id = guild_id
        self.active_giveaway = None
        self.chat_tracker = None
        
    async def load_active_giveaway(self):
        """Load currently active giveaway for this server"""
        with self.engine.connect() as conn:
            result = conn.execute(text("""
                SELECT * FROM giveaways 
                WHERE discord_server_id = :server_id 
                AND status = 'active'
                LIMIT 1
            """), {"server_id": self.guild_id}).fetchone()
            
            if result:
                self.active_giveaway = dict(result._mapping)
                logger.info(f"Loaded active giveaway {self.active_giveaway['id']} for server {self.guild_id}")
            else:
                self.active_giveaway = None
                
        return self.active_giveaway
    
    async def start_giveaway(self, giveaway_id):
        """Start a giveaway"""
        with self.engine.connect() as conn:
            # Update giveaway status
            conn.execute(text("""
                UPDATE giveaways 
                SET status = 'active', 
                    started_at = :now,
                    updated_at = :now
                WHERE id = :giveaway_id 
                AND discord_server_id = :server_id
            """), {
                "giveaway_id": giveaway_id,
                "server_id": self.guild_id,
                "now": datetime.utcnow()
            })
            conn.commit()
            
        # Reload active giveaway
        await self.load_active_giveaway()
        logger.info(f"Started giveaway {giveaway_id}")
        return True
    
    async def stop_giveaway(self, giveaway_id):
        """Stop a giveaway"""
        with self.engine.connect() as conn:
            conn.execute(text("""
                UPDATE giveaways 
                SET status = 'ended', 
                    ended_at = :now,
                    updated_at = :now
                WHERE id = :giveaway_id 
                AND discord_server_id = :server_id
            """), {
                "giveaway_id": giveaway_id,
                "server_id": self.guild_id,
                "now": datetime.utcnow()
            })
            conn.commit()
            
        if self.active_giveaway and self.active_giveaway['id'] == giveaway_id:
            self.active_giveaway = None
            
        logger.info(f"Stopped giveaway {giveaway_id}")
        return True
    
    async def add_entry(self, kick_username, kick_user_id=None, discord_id=None, entry_method='keyword'):
        """Add an entry to the active giveaway"""
        if not self.active_giveaway:
            logger.warning(f"No active giveaway for entry from {kick_username}")
            return False
        
        giveaway_id = self.active_giveaway['id']
        allow_multiple = self.active_giveaway['allow_multiple_entries']
        max_entries = self.active_giveaway['max_entries_per_user']
        
        # Fetch profile picture from Kick API
        profile_pic_url = None
        try:
            from core.kick_api import get_channel_info
            channel_data = await get_channel_info(kick_username)
            if channel_data and 'user' in channel_data:
                profile_pic_url = channel_data['user'].get('profile_pic')
                logger.debug(f"Fetched profile pic for {kick_username}: {profile_pic_url}")
        except Exception as e:
            logger.warning(f"Failed to fetch profile pic for {kick_username}: {e}")
        
        with self.engine.connect() as conn:
            # Check existing entries
            existing = conn.execute(text("""
                SELECT entry_count FROM giveaway_entries
                WHERE giveaway_id = :giveaway_id 
                AND kick_username = :username
            """), {
                "giveaway_id": giveaway_id,
                "username": kick_username
            }).fetchone()
            
            if existing:
                if not allow_multiple:
                    logger.debug(f"{kick_username} already entered giveaway {giveaway_id}")
                    return False
                    
                current_count = existing[0]
                if current_count >= max_entries:
                    logger.debug(f"{kick_username} reached max entries ({max_entries}) for giveaway {giveaway_id}")
                    return False
                
                # Increment entry count
                conn.execute(text("""
                    UPDATE giveaway_entries
                    SET entry_count = entry_count + 1
                    WHERE giveaway_id = :giveaway_id 
                    AND kick_username = :username
                """), {
                    "giveaway_id": giveaway_id,
                    "username": kick_username
                })
                logger.info(f"Added additional entry for {kick_username} in giveaway {giveaway_id}")
            else:
                # Create new entry
                conn.execute(text("""
                    INSERT INTO giveaway_entries 
                    (giveaway_id, discord_server_id, discord_id, kick_username, kick_user_id, entry_method, entry_count, profile_pic_url)
                    VALUES (:giveaway_id, :server_id, :discord_id, :username, :user_id, :method, 1, :profile_pic)
                """), {
                    "giveaway_id": giveaway_id,
                    "server_id": self.guild_id,
                    "discord_id": discord_id,
                    "username": kick_username,
                    "user_id": kick_user_id,
                    "method": entry_method,
                    "profile_pic": profile_pic_url
                })
                logger.info(f"Added new entry for {kick_username} in giveaway {giveaway_id} via {entry_method}")
            
            conn.commit()
            return True
    
    async def track_message(self, kick_username, message):
        """Track a chat message for active chatter detection"""
        if not self.active_giveaway:
            return
        
        giveaway = self.active_giveaway
        
        # Only track if using active_chatter entry method
        if giveaway['entry_method'] != 'active_chatter':
            return
        
        giveaway_id = giveaway['id']
        messages_required = giveaway['messages_required']
        time_window = giveaway['time_window_minutes']
        
        # Create message hash for duplicate detection
        message_hash = hashlib.sha256(message.encode()).hexdigest()
        
        with self.engine.connect() as conn:
            # Check if this exact message was already sent by this user
            existing = conn.execute(text("""
                SELECT id FROM giveaway_chat_activity
                WHERE giveaway_id = :giveaway_id 
                AND kick_username = :username
                AND message_hash = :hash
            """), {
                "giveaway_id": giveaway_id,
                "username": kick_username,
                "hash": message_hash
            }).fetchone()
            
            if existing:
                logger.debug(f"Duplicate message from {kick_username}, not tracking")
                return
            
            # Track the message
            conn.execute(text("""
                INSERT INTO giveaway_chat_activity 
                (giveaway_id, discord_server_id, kick_username, message, message_hash)
                VALUES (:giveaway_id, :server_id, :username, :message, :hash)
            """), {
                "giveaway_id": giveaway_id,
                "server_id": self.guild_id,
                "username": kick_username,
                "message": message[:500],  # Limit message length
                "hash": message_hash
            })
            
            # Check if user qualifies for auto-entry
            cutoff_time = datetime.utcnow() - timedelta(minutes=time_window)
            message_count = conn.execute(text("""
                SELECT COUNT(DISTINCT message_hash) as count
                FROM giveaway_chat_activity
                WHERE giveaway_id = :giveaway_id 
                AND kick_username = :username
                AND timestamp >= :cutoff
            """), {
                "giveaway_id": giveaway_id,
                "username": kick_username,
                "cutoff": cutoff_time
            }).fetchone()
            
            conn.commit()
            
            if message_count and message_count[0] >= messages_required:
                # User qualifies! Add entry
                logger.info(f"{kick_username} qualified for auto-entry with {message_count[0]} unique messages")
                await self.add_entry(kick_username, entry_method='active_chatter')
    
    async def get_entries(self):
        """Get all entries for active giveaway"""
        if not self.active_giveaway:
            return []
        
        with self.engine.connect() as conn:
            results = conn.execute(text("""
                SELECT kick_username, kick_user_id, entry_count, entry_method, created_at
                FROM giveaway_entries
                WHERE giveaway_id = :giveaway_id
                ORDER BY created_at ASC
            """), {"giveaway_id": self.active_giveaway['id']}).fetchall()
            
            return [dict(row._mapping) for row in results]
    
    async def draw_winner(self):
        """Randomly select a winner (weighted by entry_count if multiple entries allowed)"""
        import random
        
        if not self.active_giveaway:
            return None
        
        entries = await self.get_entries()
        if not entries:
            logger.warning("No entries to draw winner from")
            return None
        
        # Build weighted list based on entry_count
        weighted_entries = []
        for entry in entries:
            for _ in range(entry['entry_count']):
                weighted_entries.append(entry['kick_username'])
        
        # Random selection
        winner_username = random.choice(weighted_entries)
        
        # Save winner to database
        with self.engine.connect() as conn:
            conn.execute(text("""
                UPDATE giveaways 
                SET winner_kick_username = :winner,
                    status = 'completed',
                    ended_at = :now,
                    updated_at = :now
                WHERE id = :giveaway_id
            """), {
                "winner": winner_username,
                "giveaway_id": self.active_giveaway['id'],
                "now": datetime.utcnow()
            })
            conn.commit()
        
        logger.info(f"Drew winner: {winner_username} for giveaway {self.active_giveaway['id']}")
        self.active_giveaway = None
        return winner_username


async def setup_giveaway_managers(bot, engine):
    """Create giveaway manager for each guild"""
    managers = {}
    
    for guild in bot.guilds:
        manager = GiveawayManager(engine, guild_id=guild.id)
        await manager.load_active_giveaway()
        managers[guild.id] = manager
        logger.info(f"Set up giveaway manager for guild {guild.id}")
    
    return managers
