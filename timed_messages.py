"""
Timed Messages System - Schedule recurring messages to Kick chat
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List
import discord
from discord.ext import commands, tasks
from sqlalchemy import text
import asyncio

logger = logging.getLogger(__name__)


class TimedMessage:
    """Represents a timed message"""
    
    def __init__(self, message_id: int, message: str, interval_minutes: int, 
                 enabled: bool = True, last_sent: Optional[datetime] = None):
        self.message_id = message_id
        self.message = message
        self.interval_minutes = interval_minutes
        self.enabled = enabled
        self.last_sent = last_sent


class TimedMessagesManager:
    """Manage timed messages to Kick chat"""
    
    def __init__(self, engine, kick_send_callback=None):
        self.engine = engine
        self.kick_send_callback = kick_send_callback
        self.messages: Dict[int, TimedMessage] = {}
        self._init_database()
        self._load_messages()
    
    def _init_database(self):
        """Create timed_messages table if it doesn't exist"""
        if not self.engine:
            logger.error("No database engine provided")
            return
        
        try:
            with self.engine.begin() as conn:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS timed_messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        message TEXT NOT NULL,
                        interval_minutes INTEGER NOT NULL,
                        enabled BOOLEAN DEFAULT TRUE,
                        last_sent TIMESTAMP,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        created_by BIGINT,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """))
            logger.info("timed_messages table initialized")
        except Exception as e:
            logger.error(f"Failed to initialize timed_messages table: {e}")
    
    def _load_messages(self):
        """Load all timed messages from database"""
        if not self.engine:
            return
        
        try:
            with self.engine.begin() as conn:
                result = conn.execute(text("""
                    SELECT id, message, interval_minutes, enabled, last_sent
                    FROM timed_messages
                    ORDER BY id
                """))
                
                self.messages.clear()
                for row in result:
                    msg = TimedMessage(
                        message_id=row[0],
                        message=row[1],
                        interval_minutes=row[2],
                        enabled=bool(row[3]),
                        last_sent=row[4]
                    )
                    self.messages[msg.message_id] = msg
                
                logger.info(f"Loaded {len(self.messages)} timed messages")
        except Exception as e:
            logger.error(f"Failed to load timed messages: {e}")
    
    def add_message(self, message: str, interval_minutes: int, created_by: int) -> Dict:
        """Add a new timed message"""
        if not self.engine:
            return {'status': 'error', 'message': 'No database connection'}
        
        if interval_minutes < 1:
            return {'status': 'error', 'message': 'Interval must be at least 1 minute'}
        
        if len(message) > 500:
            return {'status': 'error', 'message': 'Message too long (max 500 chars)'}
        
        try:
            with self.engine.begin() as conn:
                result = conn.execute(text("""
                    INSERT INTO timed_messages (message, interval_minutes, enabled, created_by)
                    VALUES (:message, :interval, TRUE, :created_by)
                """), {
                    'message': message,
                    'interval': interval_minutes,
                    'created_by': created_by
                })
                
                # Get the last inserted ID
                message_id = result.lastrowid
            
            # Reload messages
            self._load_messages()
            
            logger.info(f"Added timed message #{message_id}: {message[:50]}...")
            return {
                'status': 'success',
                'message': f'Added timed message #{message_id}',
                'message_id': message_id
            }
        except Exception as e:
            logger.error(f"Error adding timed message: {e}")
            return {'status': 'error', 'message': str(e)}
    
    def remove_message(self, message_id: int) -> Dict:
        """Remove a timed message"""
        if not self.engine:
            return {'status': 'error', 'message': 'No database connection'}
        
        try:
            with self.engine.begin() as conn:
                result = conn.execute(text("""
                    DELETE FROM timed_messages WHERE id = :id
                """), {'id': message_id})
                
                if result.rowcount == 0:
                    return {'status': 'error', 'message': f'Message #{message_id} not found'}
            
            # Reload messages
            self._load_messages()
            
            logger.info(f"Removed timed message #{message_id}")
            return {'status': 'success', 'message': f'Removed timed message #{message_id}'}
        except Exception as e:
            logger.error(f"Error removing timed message: {e}")
            return {'status': 'error', 'message': str(e)}
    
    def toggle_message(self, message_id: int, enabled: bool) -> Dict:
        """Enable or disable a timed message"""
        if not self.engine:
            return {'status': 'error', 'message': 'No database connection'}
        
        try:
            with self.engine.begin() as conn:
                result = conn.execute(text("""
                    UPDATE timed_messages
                    SET enabled = :enabled, updated_at = CURRENT_TIMESTAMP
                    WHERE id = :id
                """), {'id': message_id, 'enabled': enabled})
                
                if result.rowcount == 0:
                    return {'status': 'error', 'message': f'Message #{message_id} not found'}
            
            # Reload messages
            self._load_messages()
            
            status = "enabled" if enabled else "disabled"
            logger.info(f"Timed message #{message_id} {status}")
            return {'status': 'success', 'message': f'Message #{message_id} {status}'}
        except Exception as e:
            logger.error(f"Error toggling timed message: {e}")
            return {'status': 'error', 'message': str(e)}
    
    def update_interval(self, message_id: int, interval_minutes: int) -> Dict:
        """Update message interval"""
        if not self.engine:
            return {'status': 'error', 'message': 'No database connection'}
        
        if interval_minutes < 1:
            return {'status': 'error', 'message': 'Interval must be at least 1 minute'}
        
        try:
            with self.engine.begin() as conn:
                result = conn.execute(text("""
                    UPDATE timed_messages
                    SET interval_minutes = :interval, updated_at = CURRENT_TIMESTAMP
                    WHERE id = :id
                """), {'id': message_id, 'interval': interval_minutes})
                
                if result.rowcount == 0:
                    return {'status': 'error', 'message': f'Message #{message_id} not found'}
            
            # Reload messages
            self._load_messages()
            
            logger.info(f"Updated timed message #{message_id} interval to {interval_minutes}m")
            return {
                'status': 'success',
                'message': f'Updated message #{message_id} interval to {interval_minutes} minutes'
            }
        except Exception as e:
            logger.error(f"Error updating interval: {e}")
            return {'status': 'error', 'message': str(e)}
    
    def list_messages(self) -> List[TimedMessage]:
        """Get all timed messages"""
        return list(self.messages.values())
    
    def get_message(self, message_id: int) -> Optional[TimedMessage]:
        """Get a specific message"""
        return self.messages.get(message_id)
    
    async def check_and_send_messages(self):
        """Check if any messages need to be sent and send them"""
        if not self.kick_send_callback:
            return
        
        now = datetime.utcnow()
        
        for msg in self.messages.values():
            if not msg.enabled:
                continue
            
            # Check if it's time to send
            if msg.last_sent is None:
                should_send = True
            else:
                time_since_last = now - msg.last_sent
                should_send = time_since_last >= timedelta(minutes=msg.interval_minutes)
            
            if should_send:
                try:
                    # Send the message
                    await self.kick_send_callback(msg.message)
                    logger.info(f"Sent timed message #{msg.message_id}: {msg.message[:50]}...")
                    
                    # Update last_sent timestamp
                    if self.engine:
                        with self.engine.begin() as conn:
                            conn.execute(text("""
                                UPDATE timed_messages
                                SET last_sent = CURRENT_TIMESTAMP
                                WHERE id = :id
                            """), {'id': msg.message_id})
                        
                        # Update in memory
                        msg.last_sent = now
                    
                except Exception as e:
                    logger.error(f"Failed to send timed message #{msg.message_id}: {e}")


class TimedMessagesCommands(commands.Cog):
    """Discord commands for managing timed messages"""
    
    def __init__(self, bot, manager: TimedMessagesManager):
        self.bot = bot
        self.manager = manager
        self.check_messages_task.start()
    
    def cog_unload(self):
        """Clean up when cog is unloaded"""
        self.check_messages_task.cancel()
    
    @tasks.loop(minutes=1)
    async def check_messages_task(self):
        """Background task to check and send timed messages"""
        await self.manager.check_and_send_messages()
    
    @check_messages_task.before_loop
    async def before_check_messages(self):
        """Wait for bot to be ready before starting task"""
        await self.bot.wait_until_ready()
    
    @commands.command(name='addtimer', aliases=['addtimedmessage', 'timermessage'])
    @commands.has_permissions(administrator=True)
    async def add_timed_message(self, ctx, interval: int, *, message: str):
        """
        [ADMIN] Add a timed message to Kick chat
        Usage: !addtimer <minutes> <message>
        Example: !addtimer 30 Check out our Discord: discord.gg/example
        """
        result = self.manager.add_message(message, interval, ctx.author.id)
        
        if result['status'] == 'success':
            embed = discord.Embed(
                title="✅ Timed Message Added",
                description=f"Message #{result['message_id']} will be sent every {interval} minutes",
                color=discord.Color.green()
            )
            embed.add_field(name="Message", value=message, inline=False)
            await ctx.send(embed=embed)
        else:
            await ctx.send(f"❌ {result['message']}")
    
    @commands.command(name='removetimer', aliases=['deletetimer', 'rmtimer'])
    @commands.has_permissions(administrator=True)
    async def remove_timed_message(self, ctx, message_id: int):
        """
        [ADMIN] Remove a timed message
        Usage: !removetimer <message_id>
        Example: !removetimer 1
        """
        result = self.manager.remove_message(message_id)
        
        if result['status'] == 'success':
            await ctx.send(f"✅ {result['message']}")
        else:
            await ctx.send(f"❌ {result['message']}")
    
    @commands.command(name='toggletimer', aliases=['enabletimer', 'disabletimer'])
    @commands.has_permissions(administrator=True)
    async def toggle_timed_message(self, ctx, message_id: int, enabled: str = None):
        """
        [ADMIN] Enable or disable a timed message
        Usage: !toggletimer <message_id> <on|off>
        Example: !toggletimer 1 off
        """
        if enabled is None:
            # Toggle current state
            msg = self.manager.get_message(message_id)
            if not msg:
                await ctx.send(f"❌ Message #{message_id} not found")
                return
            enabled_bool = not msg.enabled
        else:
            enabled_bool = enabled.lower() in ['on', 'enable', 'enabled', 'true', 'yes']
        
        result = self.manager.toggle_message(message_id, enabled_bool)
        
        if result['status'] == 'success':
            await ctx.send(f"✅ {result['message']}")
        else:
            await ctx.send(f"❌ {result['message']}")
    
    @commands.command(name='updatetimer', aliases=['settimer'])
    @commands.has_permissions(administrator=True)
    async def update_timer_interval(self, ctx, message_id: int, interval: int):
        """
        [ADMIN] Update the interval of a timed message
        Usage: !updatetimer <message_id> <minutes>
        Example: !updatetimer 1 60
        """
        result = self.manager.update_interval(message_id, interval)
        
        if result['status'] == 'success':
            await ctx.send(f"✅ {result['message']}")
        else:
            await ctx.send(f"❌ {result['message']}")
    
    @commands.command(name='listtimers', aliases=['timers', 'timedmessages'])
    @commands.has_permissions(administrator=True)
    async def list_timed_messages(self, ctx):
        """
        [ADMIN] List all timed messages
        Usage: !listtimers
        """
        messages = self.manager.list_messages()
        
        if not messages:
            await ctx.send("📭 No timed messages configured")
            return
        
        embed = discord.Embed(
            title="⏰ Timed Messages",
            description=f"{len(messages)} message(s) configured",
            color=discord.Color.blue()
        )
        
        for msg in messages:
            status = "✅ Enabled" if msg.enabled else "❌ Disabled"
            last_sent = msg.last_sent.strftime('%Y-%m-%d %H:%M UTC') if msg.last_sent else "Never"
            
            # Calculate next send time
            if msg.enabled and msg.last_sent:
                next_send = msg.last_sent + timedelta(minutes=msg.interval_minutes)
                time_until = next_send - datetime.utcnow()
                if time_until.total_seconds() > 0:
                    minutes_left = int(time_until.total_seconds() / 60)
                    next_info = f"in {minutes_left}m"
                else:
                    next_info = "due now"
            else:
                next_info = "waiting to start"
            
            value = (
                f"{status}\n"
                f"**Interval:** {msg.interval_minutes} minutes\n"
                f"**Last sent:** {last_sent}\n"
                f"**Next:** {next_info}\n"
                f"**Message:** {msg.message[:100]}"
            )
            
            embed.add_field(
                name=f"Message #{msg.message_id}",
                value=value,
                inline=False
            )
        
        await ctx.send(embed=embed)
    
    @commands.command(name='timerpanel', aliases=['managetimers'])
    @commands.has_permissions(administrator=True)
    async def timer_control_panel(self, ctx):
        """
        [ADMIN] Open interactive timer management panel
        Usage: !timerpanel
        """
        messages = self.manager.list_messages()
        
        embed = discord.Embed(
            title="⏰ Timed Messages Control Panel",
            description="React to manage timed messages:\n\n"
                       "➕ Add new timer\n"
                       "📋 List all timers\n"
                       "🔄 Refresh this panel",
            color=discord.Color.blue()
        )
        
        if messages:
            status_text = ""
            for msg in messages[:5]:  # Show first 5
                status = "✅" if msg.enabled else "❌"
                status_text += f"{status} #{msg.message_id}: {msg.message[:40]}... ({msg.interval_minutes}m)\n"
            
            embed.add_field(name="Active Timers", value=status_text or "None", inline=False)
        
        embed.set_footer(text="Use !addtimer, !removetimer, !toggletimer, or !listtimers")
        
        panel = await ctx.send(embed=embed)
        
        # Add reaction buttons
        await panel.add_reaction("➕")
        await panel.add_reaction("📋")
        await panel.add_reaction("🔄")


async def setup_timed_messages(bot, engine, kick_send_callback=None):
    """
    Initialize timed messages system
    
    Args:
        bot: Discord bot instance
        engine: SQLAlchemy engine
        kick_send_callback: Callback function to send messages to Kick chat
    
    Returns:
        TimedMessagesManager instance
    """
    manager = TimedMessagesManager(engine, kick_send_callback)
    await bot.add_cog(TimedMessagesCommands(bot, manager))
    logger.info(f"✅ Timed messages system initialized ({len(manager.messages)} messages)")
    return manager
