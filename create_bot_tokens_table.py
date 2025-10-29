"""
Create bot_tokens table in the database.
Run this once to ensure the table exists.
"""

import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("❌ DATABASE_URL not found in environment variables")
    exit(1)

# Fix postgres:// to postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)

print("\n" + "="*70)
print("CREATING BOT_TOKENS TABLE")
print("="*70)

try:
    with engine.begin() as conn:
        # Create bot_tokens table
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS bot_tokens (
                bot_username TEXT PRIMARY KEY,
                access_token TEXT NOT NULL,
                refresh_token TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        print("\n✅ bot_tokens table created successfully!")
        
        # Check if table exists and show structure
        result = conn.execute(text("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'bot_tokens'
            ORDER BY ordinal_position
        """)).fetchall()
        
        print("\n📋 Table structure:")
        for column_name, data_type in result:
            print(f"   - {column_name}: {data_type}")
        
        # Show any existing bot tokens (just count, not the actual tokens)
        count = conn.execute(text("SELECT COUNT(*) FROM bot_tokens")).fetchone()[0]
        print(f"\n📊 Existing bot tokens: {count}")
        
except Exception as e:
    print(f"\n❌ Error creating table: {e}")
    import traceback
    traceback.print_exc()
    exit(1)

print("\n" + "="*70)
print("✅ Database is ready for bot authorization!")
print("="*70)
print("\nYou can now visit:")
print("https://kick-dicord-bot-test-production.up.railway.app/bot/authorize")
print("="*70 + "\n")
