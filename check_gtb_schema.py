import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)

print("Checking GTB table schemas...\n")

with engine.connect() as conn:
    # Check gtb_sessions columns
    result = conn.execute(text("""
        SELECT column_name, data_type 
        FROM information_schema.columns 
        WHERE table_name = 'gtb_sessions'
        ORDER BY ordinal_position
    """))
    print("gtb_sessions columns:")
    for row in result:
        print(f"  - {row[0]}: {row[1]}")
    
    # Check gtb_guesses columns
    result = conn.execute(text("""
        SELECT column_name, data_type 
        FROM information_schema.columns 
        WHERE table_name = 'gtb_guesses'
        ORDER BY ordinal_position
    """))
    print("\ngtb_guesses columns:")
    for row in result:
        print(f"  - {row[0]}: {row[1]}")
    
    # Check recent guesses
    result = conn.execute(text("""
        SELECT id, session_id, kick_username, guess_amount, discord_server_id, guessed_at
        FROM gtb_guesses
        ORDER BY guessed_at DESC
        LIMIT 5
    """))
    print("\nRecent guesses:")
    for row in result:
        print(f"  ID={row[0]}, Session={row[1]}, User={row[2]}, Amount=${row[3]}, Server={row[4]}, Time={row[5]}")
    
    # Check active sessions
    result = conn.execute(text("""
        SELECT id, opened_by, status, discord_server_id, opened_at
        FROM gtb_sessions
        ORDER BY opened_at DESC
        LIMIT 3
    """))
    print("\nRecent sessions:")
    for row in result:
        print(f"  ID={row[0]}, By={row[1]}, Status={row[2]}, Server={row[3]}, Time={row[4]}")
