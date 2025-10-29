"""
Test timed messages system
"""

import asyncio
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import os

# Add parent directory to path
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from timed_messages import TimedMessagesManager

load_dotenv()

DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///watchtime.db')


async def mock_send_message(message):
    """Mock Kick send callback"""
    print(f"📤 Would send to Kick: {message}")


async def main():
    """Test the timed messages system"""
    
    print("🧪 Testing Timed Messages System")
    print("=" * 60)
    
    # Create engine
    engine = create_engine(DATABASE_URL)
    
    # Initialize manager
    manager = TimedMessagesManager(engine, kick_send_callback=mock_send_message)
    
    print(f"\n✅ Manager initialized with {len(manager.messages)} existing messages")
    
    # Test: Add a message
    print("\n📝 Test 1: Add a new timed message")
    result = manager.add_message("Test message - Join our Discord!", 5, 123456789)
    print(f"   Result: {result}")
    
    # Test: List messages
    print("\n📋 Test 2: List all messages")
    messages = manager.list_messages()
    for msg in messages:
        print(f"   #{msg.message_id}: {msg.message[:50]} (every {msg.interval_minutes}m, enabled={msg.enabled})")
    
    # Test: Toggle message
    if messages:
        print(f"\n🔄 Test 3: Disable message #{messages[0].message_id}")
        result = manager.toggle_message(messages[0].message_id, False)
        print(f"   Result: {result}")
        
        # Check it was disabled
        msg = manager.get_message(messages[0].message_id)
        print(f"   Verified: enabled = {msg.enabled}")
    
    # Test: Update interval
    if messages:
        print(f"\n⏱️ Test 4: Update interval of message #{messages[0].message_id} to 10 minutes")
        result = manager.update_interval(messages[0].message_id, 10)
        print(f"   Result: {result}")
        
        # Check it was updated
        msg = manager.get_message(messages[0].message_id)
        print(f"   Verified: interval = {msg.interval_minutes} minutes")
    
    # Test: Check and send messages
    print("\n📨 Test 5: Check and send due messages")
    await manager.check_and_send_messages()
    
    # Test: Remove message (cleanup)
    if result['status'] == 'success' and 'message_id' in result:
        print(f"\n🗑️ Test 6: Remove test message #{result['message_id']}")
        remove_result = manager.remove_message(result['message_id'])
        print(f"   Result: {remove_result}")
    
    print("\n" + "=" * 60)
    print("✅ All tests completed!")
    
    # Show database contents
    print("\n📊 Current database state:")
    with engine.begin() as conn:
        result = conn.execute(text("SELECT id, message, interval_minutes, enabled FROM timed_messages"))
        rows = result.fetchall()
        if rows:
            for row in rows:
                status = "✅" if row[3] else "❌"
                print(f"   {status} #{row[0]}: {row[1][:40]}... ({row[2]}m)")
        else:
            print("   (empty)")


if __name__ == "__main__":
    asyncio.run(main())
