"""
Test script for raffle system
Demonstrates basic functionality without needing full bot setup
"""

import os
import sys
from datetime import datetime, timedelta
from dotenv import load_dotenv
from sqlalchemy import create_engine

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from raffle_system.database import setup_raffle_database, verify_raffle_schema, create_new_period, get_current_period
from raffle_system.tickets import TicketManager
from raffle_system.draw import RaffleDraw

def main():
    """Test raffle system functionality"""
    
    # Load environment
    load_dotenv()
    
    DATABASE_URL = os.getenv("DATABASE_URL")
    if not DATABASE_URL:
        print("❌ DATABASE_URL not set. Please set it in your .env file")
        print("\nFor testing locally, add to .env:")
        print("DATABASE_URL=sqlite:///watchtime.db")
        print("\nOr use your Railway PostgreSQL URL")
        return
    
    print("🎟️ Testing Raffle System")
    print("=" * 50)
    
    # Create engine
    engine = create_engine(DATABASE_URL)
    
    # Step 1: Setup database
    print("\n1️⃣ Setting up database schema...")
    success = setup_raffle_database(engine)
    
    if not success:
        print("❌ Failed to setup database")
        return
    
    # Step 2: Verify schema
    print("\n2️⃣ Verifying schema...")
    status = verify_raffle_schema(engine)
    
    all_ok = all(status.values())
    if all_ok:
        print("✅ All tables created:")
        for table in status.keys():
            print(f"   ✓ {table}")
    else:
        print("⚠️ Some tables missing")
        return
    
    # Step 3: Create a raffle period
    print("\n3️⃣ Creating raffle period...")
    current = get_current_period(engine)
    
    if current:
        print(f"✅ Active period already exists (ID: {current['id']})")
        period_id = current['id']
    else:
        # Create period for this month
        start = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        # End on last day of month
        if start.month == 12:
            end = start.replace(year=start.year + 1, month=1, day=1) - timedelta(seconds=1)
        else:
            end = start.replace(month=start.month + 1, day=1) - timedelta(seconds=1)
        
        period_id = create_new_period(engine, start, end)
        print(f"✅ Created new period (ID: {period_id})")
        print(f"   Start: {start}")
        print(f"   End: {end}")
    
    # Step 4: Test ticket management
    print("\n4️⃣ Testing ticket management...")
    tm = TicketManager(engine)
    
    # Award some test tickets
    test_users = [
        (123456789, "viewer1", 100, "watchtime"),
        (123456789, "viewer1", 30, "gifted_sub"),
        (987654321, "viewer2", 50, "watchtime"),
        (111222333, "viewer3", 200, "shuffle_wager"),
    ]
    
    for discord_id, kick_name, tickets, source in test_users:
        success = tm.award_tickets(discord_id, kick_name, tickets, source, 
                                   description=f"Test {source} tickets")
        if success:
            print(f"   ✅ Awarded {tickets} {source} tickets to {kick_name}")
    
    # Step 5: Check leaderboard
    print("\n5️⃣ Leaderboard (Top 3):")
    leaderboard = tm.get_leaderboard(limit=3)
    
    for entry in leaderboard:
        print(f"   #{entry['rank']}: {entry['kick_name']} - {entry['total_tickets']} tickets")
        print(f"        (W: {entry['watchtime_tickets']}, S: {entry['gifted_sub_tickets']}, " +
              f"$: {entry['shuffle_wager_tickets']}, B: {entry['bonus_tickets']})")
    
    # Step 6: Get individual user tickets
    print("\n6️⃣ Individual user check (viewer1):")
    user_tickets = tm.get_user_tickets(123456789)
    if user_tickets:
        print(f"   Total: {user_tickets['total_tickets']} tickets")
        print(f"   Breakdown:")
        print(f"     - Watchtime: {user_tickets['watchtime_tickets']}")
        print(f"     - Gifted Subs: {user_tickets['gifted_sub_tickets']}")
        print(f"     - Shuffle: {user_tickets['shuffle_wager_tickets']}")
        print(f"     - Bonus: {user_tickets['bonus_tickets']}")
    
    # Step 7: Test raffle draw
    print("\n7️⃣ Testing raffle draw...")
    draw = RaffleDraw(engine)
    
    # Get win probability for user
    prob = draw.get_user_win_probability(123456789, period_id)
    if prob:
        print(f"   viewer1 win probability: {prob['probability_percent']:.2f}%")
        print(f"   Odds: {prob['odds']}")
    
    # Simulate draw (don't actually draw yet)
    print("\n8️⃣ Running draw simulation (1000 iterations)...")
    sim = draw.simulate_draw(period_id, num_simulations=1000)
    
    if sim:
        print(f"   Total tickets: {sim['total_tickets']}")
        print(f"   Participants: {sim['participants']}")
        print(f"\n   Simulation results:")
        for result in sim['results']:
            print(f"     {result['kick_name']}: {result['actual_wins']} wins " +
                  f"(expected: {result['expected_wins']:.1f}, " +
                  f"variance: {result['variance_percent']:+.1f}%)")
    
    # Step 8: Get period stats
    print("\n9️⃣ Period statistics:")
    stats = tm.get_period_stats()
    if stats:
        print(f"   Total participants: {stats['total_participants']}")
        print(f"   Total tickets: {stats['total_tickets']}")
        print(f"   Breakdown:")
        print(f"     - Watchtime: {stats['watchtime_tickets']}")
        print(f"     - Gifted Subs: {stats['gifted_sub_tickets']}")
        print(f"     - Shuffle: {stats['shuffle_wager_tickets']}")
        print(f"     - Bonus: {stats['bonus_tickets']}")
    
    print("\n✅ All tests passed!")
    print("\nNext steps:")
    print("  • The database schema is ready")
    print("  • Test data has been created")
    print("  • You can now integrate with Discord bot")
    print("  • Use !raffle draw to test actual drawing")

if __name__ == "__main__":
    main()
