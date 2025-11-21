import os
import json
from sqlalchemy import create_engine, text
from datetime import datetime

# Get DATABASE_URL from Railway environment
DATABASE_URL = os.environ.get('DATABASE_URL')
if not DATABASE_URL:
    print("❌ DATABASE_URL not found. Run this with: railway run python insert_gtb_guesses.py")
    exit(1)

# Connect to database
engine = create_engine(DATABASE_URL)

print("Connected to database")
print("=" * 80)

# Find the session opened by madcats around 17:39:56
with engine.connect() as conn:
    result = conn.execute(text("""
        SELECT id, opened_by, opened_at, status, discord_server_id
        FROM gtb_sessions
        WHERE opened_by = 'madcats'
        AND opened_at >= '2025-11-19 17:39:00'
        AND opened_at <= '2025-11-19 17:40:00'
        ORDER BY opened_at DESC
        LIMIT 1
    """))
    
    session = result.fetchone()
    
    if not session:
        print("❌ Session not found!")
        print("\nSearching all recent sessions...")
        result = conn.execute(text("""
            SELECT id, opened_by, opened_at, status, discord_server_id
            FROM gtb_sessions
            ORDER BY opened_at DESC
            LIMIT 10
        """))
        for row in result:
            print(f"  Session {row[0]}: opened by {row[1]} at {row[2]} - status: {row[3]} - server: {row[4]}")
        exit(1)
    
    session_id = session[0]
    server_id = session[4]
    
    print(f"✅ Found session:")
    print(f"   Session ID: {session_id}")
    print(f"   Opened by: {session[1]}")
    print(f"   Opened at: {session[2]}")
    print(f"   Status: {session[3]}")
    print(f"   Server ID: {server_id}")
    print()
    
    # Load guesses from JSON
    with open('gtb_guesses_to_insert.json', 'r') as f:
        guesses = json.load(f)
    
    print(f"Inserting {len(guesses)} guesses...")
    print("=" * 80)
    
    inserted = 0
    skipped = 0
    
    for guess in guesses:
        username = guess['username']
        amount = guess['amount']
        timestamp = guess['timestamp']
        
        # Convert timestamp to datetime
        guessed_at = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        
        # Check if guess already exists
        check = conn.execute(text("""
            SELECT id FROM gtb_guesses
            WHERE session_id = :session_id
            AND kick_username = :username
        """), {"session_id": session_id, "username": username})
        
        if check.fetchone():
            print(f"⏭️  {username}: ${amount} - already exists")
            skipped += 1
            continue
        
        # Insert guess
        conn.execute(text("""
            INSERT INTO gtb_guesses (session_id, kick_username, guess_amount, discord_server_id, guessed_at)
            VALUES (:session_id, :username, :amount, :server_id, :guessed_at)
        """), {
            "session_id": session_id,
            "username": username,
            "amount": amount,
            "server_id": server_id,
            "guessed_at": guessed_at
        })
        
        print(f"✅ {username}: ${amount}")
        inserted += 1
    
    conn.commit()
    
    print("\n" + "=" * 80)
    print(f"✅ Inserted: {inserted}")
    print(f"⏭️  Skipped (duplicates): {skipped}")
    print(f"📊 Total: {len(guesses)}")
    
    # Verify
    result = conn.execute(text("""
        SELECT COUNT(*) FROM gtb_guesses
        WHERE session_id = :session_id
    """), {"session_id": session_id})
    
    total_guesses = result.fetchone()[0]
    print(f"\n✅ Session {session_id} now has {total_guesses} total guesses")
