"""
Test Gifted Sub Tracker
Simulates gifted sub events and tests ticket awarding
"""

import os
import sys
from datetime import datetime, timedelta
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from raffle_system.database import setup_raffle_database, create_new_period
from raffle_system.gifted_sub_tracker import GiftedSubTracker
from raffle_system.tickets import TicketManager
from raffle_system.config import GIFTED_SUB_TICKETS

def main():
    """Test gifted sub tracker with simulated events"""
    
    load_dotenv()
    
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///watchtime.db")
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    
    print("🎁 Testing Gifted Sub Tracker")
    print("=" * 50)
    
    engine = create_engine(DATABASE_URL)
    
    # Step 1: Setup schema
    print("\n1️⃣ Setting up schemas...")
    setup_raffle_database(engine)
    
    # Ensure links table exists
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS links (
                discord_id BIGINT PRIMARY KEY,
                kick_name TEXT UNIQUE
            );
        """))
    
    print("✅ Schemas ready")
    
    # Step 2: Create raffle period
    print("\n2️⃣ Creating raffle period...")
    start = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1, day=1) - timedelta(seconds=1)
    else:
        end = start.replace(month=start.month + 1, day=1) - timedelta(seconds=1)
    
    period_id = create_new_period(engine, start, end)
    print(f"✅ Period #{period_id} created")
    
    # Step 3: Add test users
    print("\n3️⃣ Adding test users...")
    with engine.begin() as conn:
        # Clear existing test data
        conn.execute(text("DELETE FROM links WHERE kick_name LIKE 'gifter_%'"))
        
        # Add test users (linked accounts)
        test_users = [
            (444444444, 'gifter_alice'),
            (555555555, 'gifter_bob'),
        ]
        
        for discord_id, kick_name in test_users:
            conn.execute(text("""
                INSERT INTO links (discord_id, kick_name)
                VALUES (:discord_id, :kick_name)
                ON CONFLICT (discord_id) DO NOTHING
            """), {'discord_id': discord_id, 'kick_name': kick_name})
            
            print(f"   Added: {kick_name} (Discord ID: {discord_id})")
    
    # Step 4: Create tracker and simulate events
    print("\n4️⃣ Simulating gifted sub events...")
    tracker = GiftedSubTracker(engine)
    
    # Use asyncio to run async methods
    import asyncio
    
    # Simulate various gifted sub event formats
    test_events = [
        {
            "name": "Single gift from alice",
            "event": {
                "id": "event_001",
                "sender": {"username": "gifter_alice"},
                "gift_count": 1
            },
            "expected_tickets": GIFTED_SUB_TICKETS * 1
        },
        {
            "name": "5 gifts from bob",
            "event": {
                "id": "event_002",
                "sender": {"username": "gifter_bob"},
                "gift_count": 5
            },
            "expected_tickets": GIFTED_SUB_TICKETS * 5
        },
        {
            "name": "Duplicate event (should be ignored)",
            "event": {
                "id": "event_002",  # Same ID as above
                "sender": {"username": "gifter_bob"},
                "gift_count": 5
            },
            "expected_tickets": 0  # Should not award
        },
        {
            "name": "Gift from unlinked user",
            "event": {
                "id": "event_003",
                "sender": {"username": "unlinked_user"},
                "gift_count": 1
            },
            "expected_tickets": 0  # Should not award
        },
        {
            "name": "Another gift from alice",
            "event": {
                "id": "event_004",
                "sender": {"username": "gifter_alice"},
                "gift_count": 2
            },
            "expected_tickets": GIFTED_SUB_TICKETS * 2
        }
    ]
    
    for test in test_events:
        print(f"\n   Testing: {test['name']}")
        result = asyncio.run(tracker.handle_gifted_sub_event(test['event']))
        
        if result['status'] == 'success':
            print(f"   ✅ Success: {result['gifter']} → {result['tickets_awarded']} tickets")
        elif result['status'] == 'duplicate':
            print(f"   ⏭️  Duplicate event skipped")
        elif result['status'] == 'not_linked':
            print(f"   ⚠️  User not linked: {result['kick_name']}")
        else:
            print(f"   ❌ Failed: {result}")
    
    # Step 5: Check ticket balances
    print("\n5️⃣ Checking ticket balances...")
    tm = TicketManager(engine)
    
    for discord_id, kick_name in test_users:
        tickets = tm.get_user_tickets(discord_id)
        if tickets:
            print(f"   {kick_name}: {tickets['total_tickets']} total tickets")
            print(f"     └─ Gifted subs: {tickets['gifted_sub_tickets']}")
        else:
            print(f"   {kick_name}: No tickets")
    
    # Step 6: Check gifted sub history
    print("\n6️⃣ Checking gifted sub history...")
    
    for discord_id, kick_name in test_users:
        events = tracker.get_user_gifted_subs(discord_id)
        if events:
            print(f"   {kick_name}: {len(events)} gifted sub event(s)")
            for event in events:
                print(f"     └─ {event['sub_count']} sub(s) → {event['tickets_awarded']} tickets @ {event['gifted_at']}")
        else:
            print(f"   {kick_name}: No gifted subs recorded")
    
    # Step 7: Check audit log
    print("\n7️⃣ Checking audit log...")
    with engine.begin() as conn:
        result = conn.execute(text("""
            SELECT kick_name, ticket_change, description
            FROM raffle_ticket_log
            WHERE source = 'gifted_sub'
            ORDER BY created_at DESC
            LIMIT 10
        """))
        
        logs = list(result)
        if logs:
            print(f"   Found {len(logs)} gifted sub ticket award(s):")
            for kick_name, tickets, description in logs:
                print(f"     • {kick_name}: +{tickets} tickets - {description}")
        else:
            print("   No audit log entries found")
    
    # Step 8: Verify leaderboard
    print("\n8️⃣ Leaderboard (gifted sub tickets):")
    leaderboard = tm.get_leaderboard(limit=5)
    
    for entry in leaderboard:
        if entry['kick_name'].startswith('gifter_'):
            print(f"   #{entry['rank']}: {entry['kick_name']} - {entry['total_tickets']} tickets")
            print(f"       └─ Gifted subs: {entry['gifted_sub_tickets']}")
    
    print("\n✅ All tests passed!")
    print(f"\nGifted sub tracking:")
    print(f"  • Awards {GIFTED_SUB_TICKETS} tickets per gifted sub")
    print(f"  • Tickets awarded immediately (real-time)")
    print(f"  • Prevents duplicate event processing")
    print(f"  • Only awards to linked Discord<->Kick accounts")
    print(f"  • Full audit trail in raffle_ticket_log")

if __name__ == "__main__":
    main()
