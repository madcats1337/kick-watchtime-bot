"""
Fix for bot.py health command issues:
1. Remove asyncio.to_thread() since fetch_chatroom_id is already async
2. Change permission from manage_guild to administrator check

Changes needed in bot.py:

Line 3034: Change from:
    @commands.has_permissions(manage_guild=True)
To:
    @commands.has_permissions(administrator=True)

Line 3094: Change from:
    chatroom_id = await asyncio.to_thread(fetch_chatroom_id, KICK_CHANNEL)
To:
    chatroom_id = await fetch_chatroom_id(KICK_CHANNEL)

The first fix ensures admins can use the command.
The second fix properly awaits the async fetch_chatroom_id function.
"""

import re

# Read bot.py
with open('bot.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix 1: Change permission decorator
content = content.replace(
    '@bot.command(name="health")\n@commands.has_permissions(manage_guild=True)',
    '@bot.command(name="health")\n@commands.has_permissions(administrator=True)'
)

# Fix 2: Remove asyncio.to_thread wrapper since fetch_chatroom_id is async
content = content.replace(
    'chatroom_id = await asyncio.to_thread(fetch_chatroom_id, KICK_CHANNEL)',
    'chatroom_id = await fetch_chatroom_id(KICK_CHANNEL)'
)

# Write back
with open('bot.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ Fixed health command:")
print("  - Changed permission to administrator=True")
print("  - Fixed async fetch_chatroom_id call")
print("\nCommit and push to deploy the fix!")
