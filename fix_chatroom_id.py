#!/usr/bin/env python3
"""Fix kick_chatroom_id to be 151060 instead of broadcaster_user_id"""
import os
from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv('DATABASE_URL')
engine = create_engine(DATABASE_URL)

with engine.begin() as conn:
    # Update chatroom_id
    result = conn.execute(text("""
        UPDATE bot_settings 
        SET value = '151060' 
        WHERE key = 'kick_chatroom_id' 
        AND discord_server_id = 914986636629143562
    """))
    print(f"✅ Updated kick_chatroom_id to 151060 ({result.rowcount} rows)")
    
    # Verify
    result = conn.execute(text("""
        SELECT key, value 
        FROM bot_settings 
        WHERE discord_server_id = 914986636629143562 
        AND key IN ('kick_chatroom_id', 'kick_broadcaster_user_id', 'kick_channel')
    """))
    
    print("\n📋 Current settings:")
    for row in result:
        print(f"  {row[0]}: {row[1]}")
