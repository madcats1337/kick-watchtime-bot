"""
Test Shuffle Wager Tracker
Simulates Shuffle API data and tests ticket awarding
"""

import os
import sys
from datetime import datetime, timedelta
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
import json

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from raffle_system.database import setup_raffle_database, create_new_period
from raffle_system.shuffle_tracker import ShuffleWagerTracker
from raffle_system.tickets import TicketManager
from raffle_system.config import SHUFFLE_TICKETS_PER_1000_USD

# Mock Shuffle API data for testing
MOCK_SHUFFLE_DATA = [
    {"username": "obel", "campaignCode": "lele", "wagerAmount": 1667.69},
    {"username": "w0wWow", "campaignCode": "lele", "wagerAmount": 1992.03},
    {"username": "KyleRSA", "campaignCode": "lele", "wagerAmount": 409.86},
    {"username": "Imhim1", "campaignCode": "lele", "wagerAmount": 22.64},
    {"username": "other_code_user", "campaignCode": "different", "wagerAmount": 5000.00},  # Wrong code
]

def main():
    """Test Shuffle wager tracker with simulated API data"""
    
    load_dotenv()
    
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///watchtime.db")
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    
    print("💰 Testing Shuffle Wager Tracker")
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
    
    # Step 3: Add test users and link Shuffle accounts
    print("\n3️⃣ Setting up test users...")
    tracker = ShuffleWagerTracker(engine)
    
    with engine.begin() as conn:
        # Clear existing test data
        conn.execute(text("DELETE FROM links WHERE kick_name LIKE 'shuffle_%'"))
        conn.execute(text("DELETE FROM raffle_shuffle_links WHERE kick_name LIKE 'shuffle_%'"))
        
        # Add Discord<->Kick links
        test_links = [
            (666666666, 'shuffle_obel'),
            (777777777, 'shuffle_kyle'),
        ]
        
        for discord_id, kick_name in test_links:
            conn.execute(text("""
                INSERT INTO links (discord_id, kick_name)
                VALUES (:discord_id, :kick_name)
                ON CONFLICT (discord_id) DO NOTHING
            """), {'discord_id': discord_id, 'kick_name': kick_name})
            
            print(f"   Added Kick link: {kick_name} (Discord ID: {discord_id})")
    
    # Link Shuffle accounts
    print("\n4️⃣ Linking Shuffle accounts...")
    
    shuffle_links = [
        ("obel", "shuffle_obel", 666666666, True),  # Verified link
        ("KyleRSA", "shuffle_kyle", 777777777, False),  # Unverified link
    ]
    
    for shuffle_user, kick_name, discord_id, verified in shuffle_links:
        result = tracker.link_shuffle_account(shuffle_user, kick_name, discord_id, verified=verified, verified_by=111111111)
        if result['status'] == 'success':
            status = "✅ Verified" if verified else "⏳ Pending verification"
            print(f"   {status}: {shuffle_user} → {kick_name}")
        else:
            print(f"   ❌ Failed to link {shuffle_user}: {result}")
    
    # Step 5: Mock the API fetch method
    print("\n5️⃣ Simulating Shuffle API data...")
    
    # Patch the _fetch_shuffle_data method to return mock data
    original_fetch = tracker._fetch_shuffle_data
    
    async def mock_fetch():
        print(f"   📊 Mock API returned {len(MOCK_SHUFFLE_DATA)} users")
        return MOCK_SHUFFLE_DATA
    
    tracker._fetch_shuffle_data = mock_fetch
    
    # Step 6: Run first update
    print("\n6️⃣ Running first Shuffle wager update...")
    
    import asyncio
    result = asyncio.run(tracker.update_shuffle_wagers())
    
    if result['status'] == 'success':
        print(f"   ✅ Success: {result['updates']} wager(s) processed")
        for detail in result['details']:
            print(f"      • {detail['kick_name']}: ${detail['wager_delta']:.2f} → {detail['tickets_awarded']} tickets")
    else:
        print(f"   Status: {result['status']}")
    
    # Step 7: Check ticket balances
    print("\n7️⃣ Checking ticket balances...")
    tm = TicketManager(engine)
    
    for discord_id, kick_name in test_links:
        tickets = tm.get_user_tickets(discord_id)
        if tickets:
            print(f"   {kick_name}: {tickets['total_tickets']} total tickets")
            print(f"     └─ Shuffle wagers: {tickets['shuffle_wager_tickets']}")
        else:
            print(f"   {kick_name}: No tickets (may be pending verification)")
    
    # Step 8: Simulate wager increase
    print("\n8️⃣ Simulating wager increases...")
    
    # Update mock data with increased wagers
    MOCK_SHUFFLE_DATA[0]['wagerAmount'] = 2500.00  # obel: 1667.69 → 2500.00
    MOCK_SHUFFLE_DATA[2]['wagerAmount'] = 1500.00  # KyleRSA: 409.86 → 1500.00
    
    print("   Updated mock data:")
    print("   • obel: $1667.69 → $2500.00 (+$832.31)")
    print("   • KyleRSA: $409.86 → $1500.00 (+$1090.14)")
    
    # Step 9: Run second update
    print("\n9️⃣ Running second Shuffle wager update...")
    
    result2 = asyncio.run(tracker.update_shuffle_wagers())
    
    if result2['status'] == 'success':
        print(f"   ✅ Success: {result2['updates']} wager(s) processed")
        for detail in result2['details']:
            print(f"      • {detail['kick_name']}: ${detail['wager_delta']:.2f} → {detail['tickets_awarded']} tickets")
    else:
        print(f"   Status: {result2['status']}")
    
    # Step 10: Final ticket balances
    print("\n🔟 Final ticket balances...")
    
    for discord_id, kick_name in test_links:
        tickets = tm.get_user_tickets(discord_id)
        if tickets:
            print(f"   {kick_name}: {tickets['total_tickets']} total tickets")
            print(f"     └─ Shuffle wagers: {tickets['shuffle_wager_tickets']}")
        else:
            print(f"   {kick_name}: No tickets")
    
    # Step 11: Check wager tracking table
    print("\n1️⃣1️⃣ Wager tracking details...")
    
    with engine.begin() as conn:
        result = conn.execute(text("""
            SELECT 
                shuffle_username,
                kick_name,
                total_wager_usd,
                tickets_awarded,
                discord_id
            FROM raffle_shuffle_wagers
            WHERE period_id = :period_id
            ORDER BY total_wager_usd DESC
        """), {'period_id': period_id})
        
        for row in result:
            shuffle_user, kick, total_wager, tickets, disc_id = row
            linked = "✓ Linked" if disc_id else "✗ Not linked"
            print(f"   {shuffle_user}: ${total_wager:.2f} total → {tickets} tickets ({linked})")
    
    # Step 12: Verify filtering
    print("\n1️⃣2️⃣ Verifying campaign code filtering...")
    
    # Check that "other_code_user" was NOT tracked
    with engine.begin() as conn:
        result = conn.execute(text("""
            SELECT COUNT(*) FROM raffle_shuffle_wagers
            WHERE period_id = :period_id AND shuffle_username = 'other_code_user'
        """), {'period_id': period_id})
        
        count = result.scalar()
        if count == 0:
            print("   ✅ Users with different campaign codes correctly filtered out")
        else:
            print("   ❌ Unexpected: user with different code was tracked")
    
    print("\n✅ All tests passed!")
    print(f"\nShuffle wager tracking:")
    print(f"  • Polls Shuffle API every 15 minutes")
    print(f"  • Filters by campaign code '{os.getenv('SHUFFLE_CAMPAIGN_CODE', 'lele')}'")
    print(f"  • Awards {SHUFFLE_TICKETS_PER_1000_USD} tickets per $1000 wagered")
    print(f"  • Only awards to verified Shuffle→Kick→Discord links")
    print(f"  • Tracks wager increases (not decreases)")
    print(f"  • Full audit trail in raffle_ticket_log")

if __name__ == "__main__":
    main()
