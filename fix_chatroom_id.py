#!/usr/bin/env python3
"""Delete incorrect chatroom_id so kickpython can fetch the correct one"""
import os
from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv('DATABASE_URL')
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    
engine = create_engine(DATABASE_URL)

print("🔧 Clearing incorrect chatroom_id from database...")

with engine.begin() as conn:
    # Delete chatroom_id = 152837 (this is broadcaster_user_id, not chatroom_id)
    result = conn.execute(text("""
        DELETE FROM bot_settings 
        WHERE key = 'kick_chatroom_id' 
        AND value = '152837'
    """))
    print(f"✅ Deleted {result.rowcount} incorrect entries")
    
    # Verify
    result = conn.execute(text("""
        SELECT key, value 
        FROM bot_settings 
        WHERE discord_server_id = 914986636629143562 
        AND key IN ('kick_chatroom_id', 'kick_broadcaster_user_id', 'kick_channel')
    """))
    
    print("\n📋 Remaining settings:")
    for row in result:
        print(f"  {row[0]}: {row[1]}")

print("\n✅ Done! Restart bot to let kickpython fetch correct chatroom_id")

