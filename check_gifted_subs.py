"""Quick script to check gifted subs in the database"""
import os
from sqlalchemy import create_engine, text

# Get database URL from environment
database_url = os.getenv('DATABASE_URL')
if not database_url:
    raise ValueError("DATABASE_URL environment variable not set")

print(f"Connecting to database...")
engine = create_engine(database_url)

print("=" * 80)
print("CHECKING RAFFLE_GIFTED_SUBS TABLE")
print("=" * 80)

with engine.begin() as conn:
    # Check table structure
    print("\n1. TABLE STRUCTURE:")
    result = conn.execute(text("""
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_name = 'raffle_gifted_subs'
        ORDER BY ordinal_position;
    """))
    for row in result:
        print(f"  - {row[0]}: {row[1]} (nullable: {row[2]})")
    
    # Check total count
    print("\n2. TOTAL RECORDS:")
    result = conn.execute(text("SELECT COUNT(*) FROM raffle_gifted_subs"))
    count = result.fetchone()[0]
    print(f"  Total: {count} records")
    
    # Check last 10 records
    print("\n3. LAST 10 RECORDS:")
    result = conn.execute(text("""
        SELECT id, period_id, gifter_kick_name, gifter_discord_id, 
               sub_count, tickets_awarded, kick_event_id, gifted_at
        FROM raffle_gifted_subs
        ORDER BY gifted_at DESC
        LIMIT 10;
    """))
    
    rows = result.fetchall()
    if rows:
        print(f"  {'ID':<5} {'Period':<8} {'Kick Name':<20} {'Discord ID':<20} {'Subs':<6} {'Tickets':<8} {'Event ID':<30} {'Gifted At'}")
        print("  " + "-" * 130)
        for row in rows:
            print(f"  {row[0]:<5} {row[1]:<8} {row[2]:<20} {str(row[3]):<20} {row[4]:<6} {row[5]:<8} {str(row[6]):<30} {row[7]}")
    else:
        print("  No records found")
    
    # Check for records without Discord ID (not linked users)
    print("\n4. RECORDS WITHOUT DISCORD ID (NOT LINKED):")
    result = conn.execute(text("""
        SELECT gifter_kick_name, sub_count, kick_event_id, gifted_at
        FROM raffle_gifted_subs
        WHERE gifter_discord_id IS NULL
        ORDER BY gifted_at DESC
        LIMIT 5;
    """))
    
    rows = result.fetchall()
    if rows:
        for row in rows:
            print(f"  - {row[0]}: {row[1]} subs (event: {row[2]}, at: {row[3]})")
    else:
        print("  All records have Discord IDs")
    
    # Check active raffle period
    print("\n5. ACTIVE RAFFLE PERIOD:")
    result = conn.execute(text("""
        SELECT id, start_date, end_date, status
        FROM raffle_periods
        WHERE status = 'active'
        ORDER BY start_date DESC
        LIMIT 1;
    """))
    
    row = result.fetchone()
    if row:
        print(f"  ID: {row[0]}")
        print(f"  Start: {row[1]}")
        print(f"  End: {row[2]}")
        print(f"  Status: {row[3]}")
    else:
        print("  No active raffle period!")
    
    # Check for LuckyUsersWhoGotGiftSubscriptionsEvent patterns
    print("\n6. CHECKING FOR EVENT ID PATTERNS:")
    result = conn.execute(text("""
        SELECT kick_event_id, COUNT(*) as count
        FROM raffle_gifted_subs
        GROUP BY kick_event_id
        ORDER BY count DESC
        LIMIT 5;
    """))
    
    rows = result.fetchall()
    if rows:
        print("  Most common event ID patterns:")
        for row in rows:
            event_id = row[0] if row[0] else "NULL"
            print(f"  - {event_id}: {row[1]} occurrences")

print("\n" + "=" * 80)
print("DONE")
print("=" * 80)
