"""
Custom Commands Manager
Handles dynamic custom commands loaded from database
"""

import os
import psycopg2
import asyncio
from datetime import datetime, timedelta

class CustomCommandsManager:
    def __init__(self, bot, send_message_callback=None):
        """
        Initialize custom commands manager

        Args:
            bot: The Discord bot instance
            send_message_callback: Async function to send messages to Kick chat
        """
        self.bot = bot
        self.send_message_callback = send_message_callback
        self.commands = {}  # {command_name: {response, cooldown, enabled, use_count}}
        self.last_used = {}  # {command_name: last_used_timestamp}
        self.database_url = os.getenv('DATABASE_URL')

        print("🔧 Custom Commands Manager initialized")

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

        cursor.execute("""
            SELECT id, command_name, response_text, 0 as cooldown, true as enabled, 0 as use_count
            FROM custom_commands
            ORDER BY command_name
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

        # Send response
        try:
            if self.send_message_callback:
                await self.send_message_callback(cmd_data['response'])
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
