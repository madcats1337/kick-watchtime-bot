"""
Diagnostic script to check bot command configuration
Run this to see if commands are properly set up
"""
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)

print("=" * 60)
print("🔍 LeleBot Command Configuration Diagnostic")
print("=" * 60)
print()

with engine.connect() as conn:
    # Get all guilds
    guilds = conn.execute(text("""
        SELECT DISTINCT discord_server_id 
        FROM bot_settings 
        WHERE discord_server_id IS NOT NULL
        ORDER BY discord_server_id
    """)).fetchall()
    
    print(f"Found {len(guilds)} Discord server(s) in database\n")
    
    for (guild_id,) in guilds:
        print(f"{'='*60}")
        print(f"Discord Server ID: {guild_id}")
        print(f"{'='*60}")
        
        # Get all settings for this guild
        settings = conn.execute(text("""
            SELECT key, value 
            FROM bot_settings 
            WHERE discord_server_id = :guild_id
            ORDER BY key
        """), {"guild_id": guild_id}).fetchall()
        
        print(f"\n📋 Bot Settings ({len(settings)} total):")
        for key, value in settings:
            if 'token' in key.lower() or 'secret' in key.lower():
                value = value[:20] + "..." if value and len(value) > 20 else value
            print(f"  • {key}: {value}")
        
        # Check slot requests configuration
        print(f"\n🎰 Slot Requests Configuration:")
        slot_enabled = conn.execute(text("""
            SELECT value FROM bot_settings 
            WHERE key = 'slot_requests_enabled' AND discord_server_id = :guild_id
        """), {"guild_id": guild_id}).fetchone()
        print(f"  • Enabled: {slot_enabled[0] if slot_enabled else 'NOT SET (defaults to true)'}")
        
        slot_channel = conn.execute(text("""
            SELECT value FROM bot_settings 
            WHERE key = 'slot_calls_channel_id' AND discord_server_id = :guild_id
        """), {"guild_id": guild_id}).fetchone()
        print(f"  • Discord Channel: {slot_channel[0] if slot_channel else 'NOT SET'}")
        
        # Check Kick connection
        print(f"\n🎥 Kick Integration:")
        kick_channel = conn.execute(text("""
            SELECT value FROM bot_settings 
            WHERE key = 'kick_channel' AND discord_server_id = :guild_id
        """), {"guild_id": guild_id}).fetchone()
        print(f"  • Kick Channel: {kick_channel[0] if kick_channel else 'NOT SET'}")
        
        kick_token = conn.execute(text("""
            SELECT value FROM bot_settings 
            WHERE key = 'kick_oauth_token' AND discord_server_id = :guild_id
        """), {"guild_id": guild_id}).fetchone()
        print(f"  • OAuth Token: {'✅ SET (' + kick_token[0][:20] + '...)' if kick_token and kick_token[0] else '❌ NOT SET'}")
        
        chatroom_id = conn.execute(text("""
            SELECT value FROM bot_settings 
            WHERE key = 'kick_chatroom_id' AND discord_server_id = :guild_id
        """), {"guild_id": guild_id}).fetchone()
        print(f"  • Chatroom ID: {chatroom_id[0] if chatroom_id else 'NOT SET'}")
        
        broadcaster_id = conn.execute(text("""
            SELECT value FROM bot_settings 
            WHERE key = 'kick_broadcaster_user_id' AND discord_server_id = :guild_id
        """), {"guild_id": guild_id}).fetchone()
        print(f"  • Broadcaster ID: {broadcaster_id[0] if broadcaster_id else 'NOT SET'}")
        
        # Check recent slot requests
        recent_requests = conn.execute(text("""
            SELECT COUNT(*) FROM slot_requests 
            WHERE discord_server_id = :guild_id
        """), {"guild_id": guild_id}).fetchone()
        print(f"\n📊 Slot Requests: {recent_requests[0] if recent_requests else 0} total")
        
        print()

print("=" * 60)
print("✅ Diagnostic complete!")
print("=" * 60)
print()
print("💡 To fix command issues:")
print("1. Restart the bot to initialize slot tracker")
print("2. Check logs for 'Slot tracker initialized' messages")
print("3. Verify Kick OAuth token is set in dashboard")
print("4. Test with: !call test slot")
