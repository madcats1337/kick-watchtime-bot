"""
Custom Commands Manager
Handles dynamic custom commands loaded from database
"""

import os
import psycopg2
import asyncio
from datetime import datetime, timedelta

class CustomCommandsManager:
    def __init__(self, bot, send_message_callback=None, discord_server_id=None):
        """
        Initialize custom commands manager

        Args:
            bot: The Discord bot instance
            send_message_callback: Async function to send messages to Kick chat
            discord_server_id: Discord server ID for multiserver support
        """
        self.bot = bot
        self.send_message_callback = send_message_callback
        self.discord_server_id = discord_server_id
        self.commands = {}  # {command_name: {response, cooldown, enabled, use_count}}
        self.last_used = {}  # {command_name: last_used_timestamp}
        self.database_url = os.getenv('DATABASE_URL')

        print(f"🔧 Custom Commands Manager initialized for server {discord_server_id}")

    async def load_commands(self):
        """Load all custom commands from database"""
        if not self.database_url:
            print("⚠️ DATABASE_URL not set, custom commands disabled")
            return

        try:
            # Run DB query in thread pool to avoid blocking
            commands = await asyncio.to_thread(self._fetch_commands_from_db)

            self.commands = {}
            for cmd in commands:
                self.commands[cmd['command']] = {
                    'id': cmd['id'],
                    'response': cmd['response'],
                    'cooldown': cmd['cooldown'],
                    'enabled': cmd['enabled'],
                    'use_count': cmd['use_count']
                }

            enabled_count = sum(1 for cmd in self.commands.values() if cmd['enabled'])
            print(f"✅ Loaded {len(self.commands)} custom commands ({enabled_count} enabled)")

        except Exception as e:
            print(f"❌ Error loading custom commands: {e}")

    def _fetch_commands_from_db(self):
        """Fetch commands from database (blocking - run in thread pool)"""
        conn = psycopg2.connect(self.database_url)
        cursor = conn.cursor()

        if self.discord_server_id:
            cursor.execute("""
                SELECT id, command, response, cooldown, enabled, use_count
                FROM custom_commands
                WHERE discord_server_id = %s
                ORDER BY command
            """, (self.discord_server_id,))
        else:
            # Fallback for backward compatibility
            cursor.execute("""
                SELECT id, command, response, cooldown, enabled, use_count
                FROM custom_commands
                ORDER BY command
            """)

        commands = []
        for row in cursor.fetchall():
            commands.append({
                'id': row[0],
                'command': row[1],
                'response': row[2],
                'cooldown': row[3],
                'enabled': row[4],
                'use_count': row[5] or 0
            })

        cursor.close()
        conn.close()

        return commands

    async def reload_commands(self):
        """Reload commands from database (called when dashboard updates)"""
        print("🔄 Reloading custom commands from database...")
        await self.load_commands()

    async def handle_message(self, message_content, username):
        """
        Check if message is a custom command and respond

        Args:
            message_content: The message text
            username: Username who sent the message

        Returns:
            bool: True if command was handled, False otherwise
        """
        # Check if message starts with !
        if not message_content.startswith('!'):
            return False

        # Extract command (remove ! and get first word)
        parts = message_content[1:].split()
        if not parts:
            return False

        command = parts[0].lower()

        # Check if command exists and is enabled
        if command not in self.commands:
            return False

        cmd_data = self.commands[command]

        if not cmd_data['enabled']:
            return False

        # Check cooldown
        if command in self.last_used:
            cooldown = cmd_data['cooldown']
            time_since_last = (datetime.now() - self.last_used[command]).total_seconds()

            if time_since_last < cooldown:
                remaining = int(cooldown - time_since_last)
                print(f"⏱️  Command !{command} on cooldown ({remaining}s remaining)")
                return True  # Still handled, just on cooldown

        # Send response with variable replacements
        try:
            if self.send_message_callback:
                response = cmd_data['response']
                
                # Apply variable replacements
                response = await self._replace_variables(response, username, command)
                
                await self.send_message_callback(response)
                print(f"✅ Custom command !{command} executed by {username}")

                # Update last used
                self.last_used[command] = datetime.now()

                # Increment use count in database (don't wait for it)
                asyncio.create_task(self._increment_use_count(cmd_data['id']))

                return True
            else:
                print(f"⚠️ No send callback available for command !{command}")
                return False

        except Exception as e:
            print(f"❌ Error executing custom command !{command}: {e}")
            return False
    
    async def _replace_variables(self, text: str, username: str, command: str) -> str:
        """
        Replace custom variables in command response text
        
        Available variables:
        - {user} - Username who triggered the command
        - {channel} - Kick channel name
        - {tickets} - User's raffle ticket count (if linked)
        - {points} - User's points balance (if they have points)
        - {watchtime} - User's total watchtime in hours (if linked)
        
        Args:
            text: The response text with variables
            username: Username who triggered the command
            command: Command name (for logging)
            
        Returns:
            Text with variables replaced
        """
        try:
            # Basic replacements
            text = text.replace('{user}', username)
            
            # Get channel name and user data if we have discord_server_id
            if self.discord_server_id and self.database_url:
                try:
                    conn = psycopg2.connect(self.database_url)
                    cursor = conn.cursor()
                    
                    # Get channel name
                    cursor.execute("""
                        SELECT value FROM bot_settings 
                        WHERE key = 'kick_channel' AND discord_server_id = %s
                    """, (self.discord_server_id,))
                    result = cursor.fetchone()
                    if result:
                        text = text.replace('{channel}', result[0])
                    
                    # Get user's ticket count if linked
                    if '{tickets}' in text:
                        cursor.execute("""
                            SELECT rt.total_tickets
                            FROM raffle_tickets rt
                            JOIN links l ON rt.discord_id = l.discord_id AND rt.discord_server_id = l.discord_server_id
                            WHERE LOWER(l.kick_name) = %s 
                            AND rt.discord_server_id = %s
                            AND rt.period_id = (SELECT id FROM raffle_periods WHERE status = 'active' AND discord_server_id = %s LIMIT 1)
                        """, (username.lower(), self.discord_server_id, self.discord_server_id))
                        result = cursor.fetchone()
                        tickets = int(result[0]) if result and result[0] else 0
                        text = text.replace('{tickets}', f"{tickets:,}")
                    
                    # Get user's points
                    if '{points}' in text:
                        cursor.execute("""
                            SELECT points FROM user_points
                            WHERE LOWER(kick_username) = %s AND discord_server_id = %s
                        """, (username.lower(), self.discord_server_id))
                        result = cursor.fetchone()
                        points = int(result[0]) if result and result[0] else 0
                        text = text.replace('{points}', f"{points:,}")
                    
                    # Get user's watchtime in hours
                    if '{watchtime}' in text:
                        cursor.execute("""
                            SELECT minutes FROM watchtime
                            WHERE LOWER(username) = %s AND discord_server_id = %s
                        """, (username.lower(), self.discord_server_id))
                        result = cursor.fetchone()
                        minutes = result[0] if result and result[0] else 0
                        hours = minutes / 60
                        text = text.replace('{watchtime}', f"{hours:.1f}")
                        print(f"✅ Replaced {{watchtime}} for {username}: {hours:.1f} hours ({minutes} minutes)")
                    
                    cursor.close()
                    conn.close()
                    
                except Exception as e:
                    print(f"⚠️ Error fetching variable data for {username}: {e}")
                    import traceback
                    traceback.print_exc()
            
            return text
        except Exception as e:
            print(f"❌ Error replacing variables: {e}")
            return text  # Return original text if error

    async def _increment_use_count(self, command_id):
        """Increment use count in database"""
        try:
            await asyncio.to_thread(self._increment_use_count_db, command_id)
        except Exception as e:
            print(f"⚠️ Failed to increment use count: {e}")

    def _increment_use_count_db(self, command_id):
        """Increment use count in database (blocking)"""
        conn = psycopg2.connect(self.database_url)
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE custom_commands
            SET use_count = use_count + 1
            WHERE id = %s
        """, (command_id,))

        conn.commit()
        cursor.close()
        conn.close()

    def get_all_commands(self):
        """Get list of all enabled commands"""
        return [
            cmd for cmd, data in self.commands.items()
            if data['enabled']
        ]

    async def start(self):
        """Start the custom commands manager"""
        await self.load_commands()
        print("🎮 Custom Commands Manager started")
