"""
Migration: Add guild_id column to timed_messages table

This migration adds multiserver support to timed_messages by adding a guild_id column.
Existing messages will be assigned to NULL (or can be assigned to a default guild).

Run with: python migrations/add_guild_id_to_timed_messages.py
"""

import os
import sys
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def run_migration():
    """Run the migration"""
    DATABASE_URL = os.getenv('DATABASE_URL')
    if not DATABASE_URL:
        print("❌ DATABASE_URL environment variable not set")
        return False

    engine = create_engine(DATABASE_URL)
    db_url = str(engine.url)
    is_postgres = 'postgresql' in db_url.lower()

    try:
        with engine.begin() as conn:
            # Check if guild_id column already exists
            if is_postgres:
                result = conn.execute(text("""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name = 'timed_messages' AND column_name = 'guild_id'
                """)).fetchone()
            else:  # SQLite
                result = conn.execute(text("""
                    SELECT COUNT(*) as col_exists
                    FROM pragma_table_info('timed_messages')
                    WHERE name = 'guild_id'
                """)).fetchone()
                result = None if result[0] == 0 else result

            if result:
                print("✅ guild_id column already exists, skipping migration")
                return True

            print("🔄 Adding guild_id column to timed_messages table...")

            # Add guild_id column (nullable for backwards compatibility with existing rows)
            conn.execute(text("""
                ALTER TABLE timed_messages
                ADD COLUMN guild_id BIGINT
            """))

            print("✅ Migration completed successfully")
            print("ℹ️  Existing timed messages have guild_id = NULL")
            print("ℹ️  New messages will be assigned to the guild that created them")
            return True

    except Exception as e:
        print(f"❌ Migration failed: {e}")
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("Migration: Add guild_id to timed_messages")
    print("=" * 60)
    
    success = run_migration()
    
    if success:
        print("\n✅ Migration completed successfully!")
    else:
        print("\n❌ Migration failed!")
        sys.exit(1)
