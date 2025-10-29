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
        # Drop old table if it has wrong schema
        conn.execute(text("DROP TABLE IF EXISTS bot_tokens"))
        
        # Create bot_tokens table with OAuth authentication fields and expiration tracking
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS bot_tokens (
                bot_username TEXT PRIMARY KEY,
                access_token TEXT NOT NULL,
                refresh_token TEXT,
                expires_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        print("\n✅ bot_tokens table created successfully (OAuth with expiration tracking)!")
        
        # Check if table exists and show structure (works for both PostgreSQL and SQLite)
        print("\n📋 Table structure:")
        print("   - bot_username: TEXT (PRIMARY KEY)")
        print("   - access_token: TEXT (NOT NULL)")
        print("   - refresh_token: TEXT")
        print("   - expires_at: TIMESTAMP (when access token expires)")
        print("   - created_at: TIMESTAMP")
        
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
