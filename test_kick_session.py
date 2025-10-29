"""
Test Kick session-based authentication.
Loads tokens from database and sends a test message.
"""

import os
import asyncio
import aiohttp
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
KICK_CHANNEL = os.getenv("KICK_CHANNEL", "maikelele")

if not DATABASE_URL:
    print("❌ DATABASE_URL not found in environment variables")
    exit(1)

# Fix postgres:// to postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)

async def test_session():
    print("\n" + "="*70)
    print("TESTING KICK SESSION AUTHENTICATION")
    print("="*70)
    
    # Load tokens from database
    print("\n1️⃣ Loading session tokens from database...")
    try:
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT bearer_token, xsrf_token, cookies 
                FROM bot_tokens 
                WHERE bot_username = 'maikelele'
            """)).fetchone()
            
            if not result:
                print("❌ No session tokens found in database")
                print("💡 Run: python update_session_tokens.py")
                return
            
            bearer_token, xsrf_token, cookies = result
            print(f"✅ Bearer token: {bearer_token[:30]}...")
            print(f"✅ XSRF token: {xsrf_token[:30]}...")
            print(f"✅ Cookies loaded ({len(cookies)} chars)")
    except Exception as e:
        print(f"❌ Database error: {e}")
        return
    
    # Fetch chatroom ID
    print(f"\n2️⃣ Fetching chatroom ID for channel: {KICK_CHANNEL}...")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://kick.com/api/v2/channels/{KICK_CHANNEL}", timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    chatroom_id = data.get("chatroom", {}).get("id")
                    if not chatroom_id:
                        print("❌ Could not find chatroom ID in response")
                        return
                    print(f"✅ Chatroom ID: {chatroom_id}")
                else:
                    error = await response.text()
                    print(f"❌ Failed to fetch channel data (HTTP {response.status}): {error}")
                    return
    except Exception as e:
        print(f"❌ Error fetching chatroom ID: {e}")
        return
    
    # Send test message
    print(f"\n3️⃣ Sending test message to chatroom {chatroom_id}...")
    url = f"https://kick.com/api/v2/messages/send/{chatroom_id}"
    
    headers = {
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "Authorization": f"Bearer {bearer_token}",
        "X-CSRF-Token": xsrf_token,
        "Cache-Control": "max-age=0",
        "Cluster": "v2",
        "Content-Type": "application/json",
        "Cookie": cookies,
        "Referer": f"https://kick.com/{KICK_CHANNEL}",
        "Referrer-Policy": "strict-origin-when-cross-origin"
    }
    
    payload = {
        "content": "🤖 Test message from session-based auth",
        "type": "message"
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload, timeout=10) as response:
                if response.status == 200:
                    print("✅ Message sent successfully!")
                    print("\n" + "="*70)
                    print("SUCCESS! Session-based authentication is working! 🎉")
                    print("="*70)
                    print("\nYou should see the test message in the chat.")
                    print("The bot is ready to send Kick messages!")
                else:
                    error = await response.text()
                    print(f"❌ Failed to send message (HTTP {response.status}): {error}")
                    
                    if response.status == 401:
                        print("\n💡 Session expired. Get fresh tokens:")
                        print("   1. Log into kick.com in browser")
                        print("   2. Open DevTools (F12) → Network tab")
                        print("   3. Send a chat message")
                        print("   4. Copy headers from /messages/send/ request")
                        print("   5. Run: python update_session_tokens.py")
    except Exception as e:
        print(f"❌ Error sending message: {e}")

if __name__ == "__main__":
    asyncio.run(test_session())
