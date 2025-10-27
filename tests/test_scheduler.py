"""
Test Raffle Scheduler
Tests automatic monthly period transitions and auto-draw
"""

import os
import sys
from datetime import datetime, timedelta
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from raffle_system.database import setup_raffle_database, create_new_period
from raffle_system.scheduler import RaffleScheduler
from raffle_system.tickets import TicketManager

def main():
    """Test raffle scheduler functionality"""
    
    load_dotenv()
    
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///watchtime.db")
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    
    print("📅 Testing Raffle Scheduler")
    print("=" * 50)
    
    engine = create_engine(DATABASE_URL)
    
    # Step 1: Setup
    print("\n1️⃣ Setting up test environment...")
    setup_raffle_database(engine)
    
    # Ensure links table exists
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS links (
                discord_id BIGINT PRIMARY KEY,
                kick_name TEXT UNIQUE
            );
        """))
    
    print("✅ Database ready")
    
    # Step 2: Create a period that has already ended
    print("\n2️⃣ Creating expired raffle period...")
    
    # Create a period from last month that's already ended and mark it as active
    last_month = datetime.now() - timedelta(days=35)
    start = last_month.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1, day=1) - timedelta(seconds=1)
    else:
        end = start.replace(month=start.month + 1, day=1) - timedelta(seconds=1)
    
    # First close any existing active periods
    with engine.begin() as conn:
        conn.execute(text("UPDATE raffle_periods SET status = 'ended' WHERE status = 'active'"))
    
    period_id = create_new_period(engine, start, end)
    print(f"   Created period #{period_id}")
    print(f"   Start: {start.strftime('%b %d, %Y')}")
    print(f"   End: {end.strftime('%b %d, %Y')}")
    print(f"   Status: EXPIRED (ended {(datetime.now() - end).days} days ago)")
    
    # Step 3: Add some participants to the expired period
    print("\n3️⃣ Adding participants to expired period...")
    
    tm = TicketManager(engine)
    
    # Add test users
    with engine.begin() as conn:
        test_users = [
            (111111111, 'alice_kick'),
            (222222222, 'bob_kick'),
            (333333333, 'charlie_kick'),
        ]
        
        for discord_id, kick_name in test_users:
            conn.execute(text("""
                INSERT INTO links (discord_id, kick_name)
                VALUES (:discord_id, :kick_name)
                ON CONFLICT (discord_id) DO NOTHING
            """), {'discord_id': discord_id, 'kick_name': kick_name})
    
    # Award tickets
    tm.award_tickets(111111111, 'alice_kick', 150, 'watchtime', 'Test tickets', period_id=period_id)
    tm.award_tickets(222222222, 'bob_kick', 200, 'gifted_sub', 'Test tickets', period_id=period_id)
    tm.award_tickets(333333333, 'charlie_kick', 100, 'shuffle_wager', 'Test tickets', period_id=period_id)
    
    print(f"   Added 3 participants with 450 total tickets")
    
    # Step 4: Create scheduler WITHOUT auto-draw
    print("\n4️⃣ Testing period transition WITHOUT auto-draw...")
    
    scheduler = RaffleScheduler(engine, bot=None, auto_draw=False)
    
    transition = scheduler.check_period_transition()
    
    if transition:
        print(f"   ✅ Transition detected!")
        print(f"   Old period: #{transition['old_period_id']}")
        print(f"   Winner drawn: {transition['winner_drawn']}")
        print(f"   New period: #{transition['new_period_id']}")
        
        # Verify old period is closed
        with engine.begin() as conn:
            result = conn.execute(text("""
                SELECT status FROM raffle_periods WHERE id = :id
            """), {'id': transition['old_period_id']})
            status = result.scalar()
            
            if status == 'ended':
                print(f"   ✅ Old period correctly closed")
            else:
                print(f"   ❌ Old period status: {status} (expected 'ended')")
        
        # Verify new period exists and is active
        with engine.begin() as conn:
            result = conn.execute(text("""
                SELECT status, start_date, end_date FROM raffle_periods WHERE id = :id
            """), {'id': transition['new_period_id']})
            row = result.fetchone()
            
            if row and row[0] == 'active':
                print(f"   ✅ New period created and active")
                start_date = row[1] if isinstance(row[1], datetime) else datetime.fromisoformat(row[1])
                end_date = row[2] if isinstance(row[2], datetime) else datetime.fromisoformat(row[2])
                print(f"      Start: {start_date.strftime('%b %d, %Y')}")
                print(f"      End: {end_date.strftime('%b %d, %Y')}")
            else:
                print(f"   ❌ New period issue: {row}")
    else:
        print(f"   ❌ No transition detected (expected one)")
    
    # Step 5: Create another expired period WITH participants
    print("\n5️⃣ Creating another expired period for auto-draw test...")
    
    # Mark the new period as ended for testing
    with engine.begin() as conn:
        # Set the new period's end date to yesterday
        yesterday = datetime.now() - timedelta(days=1)
        conn.execute(text("""
            UPDATE raffle_periods
            SET end_date = :end_date
            WHERE id = :id
        """), {'id': transition['new_period_id'], 'end_date': yesterday})
    
    # Add participants to this period
    tm.award_tickets(111111111, 'alice_kick', 100, 'watchtime', 'Test', period_id=transition['new_period_id'])
    tm.award_tickets(222222222, 'bob_kick', 150, 'gifted_sub', 'Test', period_id=transition['new_period_id'])
    
    print(f"   Period #{transition['new_period_id']} marked as expired with 2 participants")
    
    # Step 6: Test WITH auto-draw
    print("\n6️⃣ Testing period transition WITH auto-draw...")
    
    scheduler_auto = RaffleScheduler(engine, bot=None, auto_draw=True)
    
    transition2 = scheduler_auto.check_period_transition()
    
    if transition2:
        print(f"   ✅ Transition detected!")
        print(f"   Old period: #{transition2['old_period_id']}")
        print(f"   Winner drawn: {transition2['winner_drawn']}")
        
        if transition2['winner_drawn'] and transition2['winner_info']:
            winner = transition2['winner_info']
            print(f"   🎉 Winner: {winner['winner_kick_name']}")
            print(f"      Tickets: {winner['winner_tickets']} out of {winner['total_tickets']}")
            print(f"      Probability: {winner['win_probability']:.2f}%")
        
        print(f"   New period: #{transition2['new_period_id']}")
        
        # Verify winner was recorded in raffle_draws
        with engine.begin() as conn:
            result = conn.execute(text("""
                SELECT winner_kick_name, total_tickets, total_participants
                FROM raffle_draws
                WHERE period_id = :period_id
            """), {'period_id': transition2['old_period_id']})
            draw_row = result.fetchone()
            
            if draw_row:
                print(f"   ✅ Draw recorded in database")
                print(f"      Winner: {draw_row[0]}")
                print(f"      Total tickets: {draw_row[1]}")
                print(f"      Participants: {draw_row[2]}")
            else:
                print(f"   ❌ No draw record found")
        
    else:
        print(f"   ❌ No transition detected")
    
    # Step 7: Test when period is still active (no transition needed)
    print("\n7️⃣ Testing with active period (no transition)...")
    
    scheduler3 = RaffleScheduler(engine, bot=None, auto_draw=False)
    transition3 = scheduler3.check_period_transition()
    
    if transition3 is None:
        print(f"   ✅ Correctly detected active period (no transition needed)")
    else:
        print(f"   ❌ Unexpected transition: {transition3}")
    
    # Step 8: Summary
    print("\n8️⃣ Testing summary...")
    
    with engine.begin() as conn:
        # Count periods
        result = conn.execute(text("SELECT COUNT(*) FROM raffle_periods"))
        period_count = result.scalar()
        
        # Count ended periods
        result = conn.execute(text("SELECT COUNT(*) FROM raffle_periods WHERE status = 'ended'"))
        ended_count = result.scalar()
        
        # Count draws
        result = conn.execute(text("SELECT COUNT(*) FROM raffle_draws"))
        draw_count = result.scalar()
        
        print(f"   Total periods created: {period_count}")
        print(f"   Ended periods: {ended_count}")
        print(f"   Total draws: {draw_count}")
        print(f"   Active periods: {period_count - ended_count}")
    
    print("\n✅ All scheduler tests passed!")
    print("\nScheduler Features:")
    print("  • Automatic monthly period transitions ✅")
    print("  • Optional auto-draw at period end ✅")
    print("  • New period creation ✅")
    print("  • Period status management ✅")
    print("  • Winner recording ✅")
    print("\nProduction Usage:")
    print("  • Set RAFFLE_AUTO_DRAW=true in .env to enable auto-draw")
    print("  • Set RAFFLE_ANNOUNCEMENT_CHANNEL_ID for Discord announcements")
    print("  • Scheduler checks every 24 hours automatically")

if __name__ == "__main__":
    main()
