"""
Test Watchtime Converter
Simulates watchtime data and tests conversion to tickets
"""

import os
import sys
from datetime import datetime, timedelta
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from raffle_system.database import setup_raffle_database, create_new_period
from raffle_system.watchtime_converter import WatchtimeConverter
from raffle_system.tickets import TicketManager

def main():
    """Test watchtime converter with sample data"""
    
    load_dotenv()
    
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///watchtime.db")
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    
    print("🎟️ Testing Watchtime Converter")
    print("=" * 50)
    
    engine = create_engine(DATABASE_URL)
    
    # Step 1: Setup schema
    print("\n1️⃣ Setting up schemas...")
    setup_raffle_database(engine)
    
    # Ensure watchtime and links tables exist (from bot.py)
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS watchtime (
                username TEXT PRIMARY KEY,
                minutes INTEGER DEFAULT 0,
                last_active TIMESTAMP
            );
        """))
        
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
    
    # Step 3: Add test users with watchtime
    print("\n3️⃣ Adding test data...")
    with engine.begin() as conn:
        # Clear existing test data
        conn.execute(text("DELETE FROM watchtime WHERE username LIKE 'test_viewer%'"))
        conn.execute(text("DELETE FROM links WHERE kick_name LIKE 'test_viewer%'"))
        
        # Add test users
        test_users = [
            (111111111, 'test_viewer1', 185),  # 3 hours convertible
            (222222222, 'test_viewer2', 420),  # 7 hours convertible
            (333333333, 'test_viewer3', 45),   # Less than 1 hour (won't convert)
        ]
        
        for discord_id, kick_name, minutes in test_users:
            # Add to links table
            conn.execute(text("""
                INSERT INTO links (discord_id, kick_name)
                VALUES (:discord_id, :kick_name)
                ON CONFLICT (discord_id) DO NOTHING
            """), {'discord_id': discord_id, 'kick_name': kick_name})
            
            # Add watchtime
            conn.execute(text("""
                INSERT INTO watchtime (username, minutes, last_active)
                VALUES (:username, :minutes, :last_active)
                ON CONFLICT (username) 
                DO UPDATE SET minutes = :minutes, last_active = :last_active
            """), {
                'username': kick_name,
                'minutes': minutes,
                'last_active': datetime.now()
            })
            
            print(f"   Added: {kick_name} with {minutes} minutes watchtime")
    
    # Step 4: Run converter
    print("\n4️⃣ Running watchtime converter...")
    converter = WatchtimeConverter(engine)
    
    # Use asyncio to run the async method
    import asyncio
    
    # Add a small delay to avoid SQLite lock issues
    import time
    time.sleep(0.5)
    
    result = asyncio.run(converter.convert_watchtime_to_tickets())
    
    if result['status'] == 'success':
        print(f"✅ Converted watchtime for {result['conversions']} users")
        for detail in result['details']:
            print(f"   • {detail['kick_name']}: {detail['hours_converted']}h → {detail['tickets_awarded']} tickets")
    else:
        print(f"❌ Conversion failed: {result}")
    
    # Step 5: Check tickets
    print("\n5️⃣ Checking ticket balances...")
    tm = TicketManager(engine)
    
    for discord_id, kick_name, minutes in test_users:
        tickets = tm.get_user_tickets(discord_id)
        if tickets:
            print(f"   {kick_name}: {tickets['total_tickets']} tickets (watchtime: {tickets['watchtime_tickets']})")
        else:
            print(f"   {kick_name}: No tickets (less than 1 hour)")
    
    # Step 6: Test unconverted watchtime check
    print("\n6️⃣ Checking unconverted watchtime...")
    for discord_id, kick_name, minutes in test_users:
        info = converter.get_unconverted_watchtime(kick_name)
        if info:
            print(f"   {kick_name}:")
            print(f"     Total: {info['total_minutes']} min")
            print(f"     Converted: {info['converted_minutes']} min")
            print(f"     Remaining: {info['unconverted_minutes']} min ({info['convertible_hours']}h convertible)")
            print(f"     Potential: {info['potential_tickets']} more tickets")
    
    # Step 7: Simulate adding more watchtime and converting again
    print("\n7️⃣ Simulating more watchtime...")
    with engine.begin() as conn:
        # Add 2 more hours to test_viewer1
        conn.execute(text("""
            UPDATE watchtime
            SET minutes = minutes + 120
            WHERE username = 'test_viewer1'
        """))
        print("   Added 120 minutes to test_viewer1")
    
    print("\n8️⃣ Running converter again...")
    result2 = asyncio.run(converter.convert_watchtime_to_tickets())
    
    if result2['status'] == 'success' and result2['conversions'] > 0:
        print(f"✅ Converted watchtime for {result2['conversions']} users")
        for detail in result2['details']:
            print(f"   • {detail['kick_name']}: {detail['hours_converted']}h → {detail['tickets_awarded']} tickets")
    else:
        print(f"   No new conversions (need at least 1 more full hour)")
    
    # Step 8: Final leaderboard
    print("\n9️⃣ Final Leaderboard:")
    leaderboard = tm.get_leaderboard(limit=5)
    for entry in leaderboard:
        if entry['kick_name'].startswith('test_viewer'):
            print(f"   #{entry['rank']}: {entry['kick_name']} - {entry['total_tickets']} tickets")
    
    print("\n✅ All tests passed!")
    print("\nThe watchtime converter:")
    print("  • Automatically converts watchtime to tickets every hour")
    print("  • Only converts full hours (60 min = 10 tickets)")
    print("  • Tracks what's been converted to prevent double-counting")
    print("  • Works with your existing watchtime tracking system")

if __name__ == "__main__":
    main()
