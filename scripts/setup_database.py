"""
Database initialization and migration script.
Run this script to create all necessary database tables.
"""

import os
import sys
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///watchtime.db")

# Convert postgres:// to postgresql:// for SQLAlchemy
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

print(f"Connecting to database: {DATABASE_URL.split('@')[0]}@..." if '@' in DATABASE_URL else DATABASE_URL)

try:
    # Create engine
    engine = create_engine(DATABASE_URL, echo=True)
    
    # Create tables
    with engine.begin() as conn:
        print("\n=== Creating tables ===\n")
        
        # Links table
        print("Creating 'links' table...")
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS links (
                discord_id BIGINT PRIMARY KEY,
                kick_name TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        
        # Watchtime table
        print("Creating 'watchtime' table...")
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS watchtime (
                discord_id BIGINT PRIMARY KEY,
                minutes INTEGER NOT NULL DEFAULT 0,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        
        # Pending links table
        print("Creating 'pending_links' table...")
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS pending_links (
                discord_id BIGINT PRIMARY KEY,
                code TEXT NOT NULL,
                expires_at TIMESTAMP NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        
        # Slot call blacklist table
        print("Creating 'slot_call_blacklist' table...")
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS slot_call_blacklist (
                kick_username TEXT PRIMARY KEY,
                reason TEXT,
                blacklisted_by BIGINT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        
        # Create indexes for better performance
        print("\nCreating indexes...")
        
        try:
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_links_kick_name ON links(kick_name)
            """))
        except Exception as e:
            print(f"Index idx_links_kick_name might already exist: {e}")
        
        try:
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_pending_expires ON pending_links(expires_at)
            """))
        except Exception as e:
            print(f"Index idx_pending_expires might already exist: {e}")
        
        try:
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_watchtime_minutes ON watchtime(minutes)
            """))
        except Exception as e:
            print(f"Index idx_watchtime_minutes might already exist: {e}")
    
    print("\n=== Database setup complete! ===\n")
    
    # Verify tables
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
        """))
        print("Tables in database:")
        for row in result:
            print(f"  - {row[0]}")
    
    print("\n✅ Database is ready for use!")
    
except Exception as e:
    print(f"\n❌ Error setting up database: {e}")
    sys.exit(1)
