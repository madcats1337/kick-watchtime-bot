"""Diagnostic script to verify multi-server linking integrity.

Runs checks against the `links` table:
1. Schema columns present (discord_server_id, linked_at)
2. Distribution of rows per discord_server_id
3. Rows with NULL / 0 discord_server_id (should be none after migration)
4. Duplicate kick_name across different servers
5. Sample rows for a target server (optional)

Usage (PowerShell):
    $env:DATABASE_URL="postgresql://user:pass@host:port/db"  # if not already set
    python test_links_multi_server.py 914986636629143562      # (optional server id to focus)

Exit codes:
    0 = All good (no missing server IDs)
    1 = Found rows needing backfill (NULL/0 server ids)
    2 = Critical schema issue
"""

import os
import sys
import psycopg2
from psycopg2.extras import RealDictCursor

TARGET_SERVER_ID = None
if len(sys.argv) > 1:
    try:
        TARGET_SERVER_ID = int(sys.argv[1])
    except ValueError:
        print(f"⚠️ Invalid server id argument: {sys.argv[1]}")

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("❌ DATABASE_URL not set. Set env variable first.")
    sys.exit(2)

def connect():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def column_exists(cur, table, column):
    cur.execute(
        "SELECT 1 FROM information_schema.columns WHERE table_name=%s AND column_name=%s",
        (table, column)
    )
    return cur.fetchone() is not None

def main():
    print("=== Multi-Server Links Table Diagnostic ===\n")
    conn = connect()
    cur = conn.cursor()

    # 1. Schema validation
    required_columns = ["discord_id", "kick_name", "discord_server_id", "linked_at"]
    missing = [c for c in required_columns if not column_exists(cur, "links", c)]
    if missing:
        print(f"❌ Missing columns: {', '.join(missing)}")
        print("Run latest bot startup to auto-migrate or manually ALTER TABLE.")
        sys.exit(2)
    print("✅ Schema columns present.")

    # 2. Row distribution per server
    cur.execute("""
        SELECT COALESCE(discord_server_id, 0) as server_id, COUNT(*) as cnt
        FROM links
        GROUP BY COALESCE(discord_server_id, 0)
        ORDER BY cnt DESC
    """)
    dist = cur.fetchall()
    print("\nServer distribution:")
    for row in dist:
        sid = row['server_id']
        label = 'MISSING/0' if sid in (0, None) else str(sid)
        print(f"  {label}: {row['cnt']} links")

    # 3. Rows needing backfill
    cur.execute("SELECT discord_id, kick_name FROM links WHERE discord_server_id IS NULL OR discord_server_id = 0 LIMIT 25")
    missing_rows = cur.fetchall()
    if missing_rows:
        print(f"\n❌ Found {len(missing_rows)} rows with NULL/0 discord_server_id (showing up to 25):")
        for r in missing_rows:
            print(f"   discord_id={r['discord_id']} kick_name={r['kick_name']}")
    else:
        print("\n✅ No rows with NULL/0 discord_server_id.")

    # 4. Duplicate kick_name across servers
    cur.execute("""
        SELECT kick_name, COUNT(DISTINCT discord_server_id) as server_count
        FROM links
        GROUP BY kick_name
        HAVING COUNT(DISTINCT discord_server_id) > 1
        ORDER BY server_count DESC, kick_name
        LIMIT 25
    """)
    dupes = cur.fetchall()
    if dupes:
        print("\n⚠️ Duplicate kick_name across servers (possible shared accounts):")
        for d in dupes:
            print(f"   {d['kick_name']} on {d['server_count']} servers")
    else:
        print("\n✅ No duplicate kick_name across servers detected.")

    # 5. Sample rows for target server
    if TARGET_SERVER_ID:
        cur.execute(
            "SELECT discord_id, kick_name, linked_at FROM links WHERE discord_server_id = %s ORDER BY linked_at DESC LIMIT 10",
            (TARGET_SERVER_ID,)
        )
        sample = cur.fetchall()
        print(f"\nSample (latest 10) for server {TARGET_SERVER_ID}:")
        if not sample:
            print("  (No rows)")
        else:
            for s in sample:
                print(f"  {s['discord_id']} -> {s['kick_name']} at {s['linked_at']}")

    # Suggested fix commands if issues found
    if missing_rows:
        print("\n=== Suggested Fix ===")
        if TARGET_SERVER_ID:
            print("Use this SQL to backfill missing server ids:")
            print(f"UPDATE links SET discord_server_id = {TARGET_SERVER_ID} WHERE discord_server_id IS NULL OR discord_server_id = 0;")
        else:
            print("Provide a server id argument to generate backfill SQL (e.g., python test_links_multi_server.py 914986636629143562)")
        exit_code = 1
    else:
        exit_code = 0

    cur.close()
    conn.close()
    print("\nDiagnostics complete.")
    sys.exit(exit_code)

if __name__ == "__main__":
    main()
