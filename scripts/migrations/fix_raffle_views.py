"""
Migration: Fix raffle_leaderboard and raffle_current_stats views to include discord_server_id

This script recreates the raffle views to include the discord_server_id column
that was added to the base tables but missing from the views.
"""

import psycopg2
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

DATABASE_URL = os.getenv('DATABASE_URL')

if not DATABASE_URL:
    print("❌ DATABASE_URL not found in environment variables!")
    exit(1)

print("=" * 70)
print("RAFFLE VIEWS FIX - Add discord_server_id to views")
print("=" * 70)

conn = None
cursor = None

try:
    # Connect
    print("\n📡 Connecting to database...")
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    print("✅ Connected successfully")
    
    # 1. Check if base tables have discord_server_id
    print("\n1. Verifying base tables have discord_server_id...")
    
    cursor.execute("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'raffle_tickets' AND column_name = 'discord_server_id'
    """)
    if not cursor.fetchone():
        print("❌ ERROR: raffle_tickets table missing discord_server_id column!")
        print("   Please run run_migration_1.py first to add this column.")
        raise Exception("Base table missing required column")
    
    cursor.execute("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'raffle_periods' AND column_name = 'discord_server_id'
    """)
    if not cursor.fetchone():
        print("❌ ERROR: raffle_periods table missing discord_server_id column!")
        print("   Please run run_migration_1.py first to add this column.")
        raise Exception("Base table missing required column")
    
    print("✅ Base tables have discord_server_id column")
    
    # 2. Drop and recreate raffle_leaderboard view
    print("\n2. Recreating raffle_leaderboard view...")
    cursor.execute("""
        DROP VIEW IF EXISTS raffle_leaderboard CASCADE;
    """)
    
    cursor.execute("""
        CREATE VIEW raffle_leaderboard AS
        SELECT
            rt.period_id,
            rt.discord_server_id,
            rt.discord_id,
            rt.kick_name,
            rt.total_tickets,
            rt.watchtime_tickets,
            rt.gifted_sub_tickets,
            rt.shuffle_wager_tickets,
            rt.bonus_tickets,
            RANK() OVER (PARTITION BY rt.period_id, rt.discord_server_id ORDER BY rt.total_tickets DESC) as rank
        FROM raffle_tickets rt
        WHERE rt.total_tickets > 0
        ORDER BY rt.period_id DESC, rt.discord_server_id, rt.total_tickets DESC;
    """)
    print("✅ raffle_leaderboard view recreated with discord_server_id")
    
    # 3. Drop and recreate raffle_current_stats view
    print("\n3. Recreating raffle_current_stats view...")
    cursor.execute("""
        DROP VIEW IF EXISTS raffle_current_stats CASCADE;
    """)
    
    cursor.execute("""
        CREATE VIEW raffle_current_stats AS
        SELECT
            rp.id as period_id,
            rp.discord_server_id,
            rp.start_date,
            rp.end_date,
            rp.status,
            COUNT(DISTINCT rt.discord_id) as total_participants,
            COALESCE(SUM(rt.total_tickets), 0) as total_tickets,
            COALESCE(SUM(rt.watchtime_tickets), 0) as watchtime_tickets,
            COALESCE(SUM(rt.gifted_sub_tickets), 0) as gifted_sub_tickets,
            COALESCE(SUM(rt.shuffle_wager_tickets), 0) as shuffle_wager_tickets,
            COALESCE(SUM(rt.bonus_tickets), 0) as bonus_tickets
        FROM raffle_periods rp
        LEFT JOIN raffle_tickets rt ON rt.period_id = rp.id AND rt.discord_server_id = rp.discord_server_id
        WHERE rp.status = 'active'
        GROUP BY rp.id, rp.discord_server_id;
    """)
    print("✅ raffle_current_stats view recreated with discord_server_id")
    
    # 4. Verify views
    print("\n4. Verifying views...")
    
    cursor.execute("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'raffle_leaderboard' AND column_name = 'discord_server_id'
    """)
    if cursor.fetchone():
        print("✅ raffle_leaderboard has discord_server_id column")
    else:
        print("❌ raffle_leaderboard missing discord_server_id column")
    
    cursor.execute("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'raffle_current_stats' AND column_name = 'discord_server_id'
    """)
    if cursor.fetchone():
        print("✅ raffle_current_stats has discord_server_id column")
    else:
        print("❌ raffle_current_stats missing discord_server_id column")
    
    # 5. Test queries
    print("\n5. Testing view queries...")
    
    cursor.execute("""
        SELECT COUNT(*) FROM raffle_leaderboard WHERE discord_server_id IS NOT NULL
    """)
    count = cursor.fetchone()[0]
    print(f"✅ raffle_leaderboard: {count} rows with discord_server_id")
    
    cursor.execute("""
        SELECT COUNT(*) FROM raffle_current_stats WHERE discord_server_id IS NOT NULL
    """)
    count = cursor.fetchone()[0]
    print(f"✅ raffle_current_stats: {count} rows with discord_server_id")
    
    # Commit
    conn.commit()
    print("\n✅ Migration completed successfully!")
    print("\n📊 The raffle views now include discord_server_id and support multi-server queries.")

except Exception as e:
    print(f"\n❌ Migration failed: {e}")
    import traceback
    traceback.print_exc()
    if conn:
        conn.rollback()
    raise
finally:
    if cursor:
        cursor.close()
    if conn:
        conn.close()

print("\n" + "=" * 70)
