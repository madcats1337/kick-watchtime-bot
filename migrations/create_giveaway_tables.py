"""
Migration: Create giveaway system tables

Creates tables for keyword-based giveaway system separate from raffle:
- giveaways: Giveaway configurations and status
- giveaway_entries: Participant entries
- giveaway_chat_activity: Message tracking for active chatter detection
"""

import os
import sys
from sqlalchemy import create_engine, text

# Get database URL from environment
DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///watchtime.db')

def run_migration():
    """Run the migration"""
    engine = create_engine(DATABASE_URL)
    
    with engine.connect() as conn:
        print("Creating giveaway system tables...")
        
        # Create giveaways table
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS giveaways (
                id SERIAL PRIMARY KEY,
                discord_server_id BIGINT NOT NULL,
                title VARCHAR(255) NOT NULL,
                description TEXT,
                entry_method VARCHAR(20) NOT NULL DEFAULT 'keyword',
                keyword VARCHAR(50),
                messages_required INTEGER DEFAULT 5,
                time_window_minutes INTEGER DEFAULT 10,
                allow_multiple_entries BOOLEAN DEFAULT FALSE,
                max_entries_per_user INTEGER DEFAULT 1,
                status VARCHAR(20) NOT NULL DEFAULT 'pending',
                winner_discord_id BIGINT,
                winner_kick_username VARCHAR(255),
                started_at TIMESTAMP,
                ended_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_by VARCHAR(255),
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        print("✅ Created giveaways table")
        
        # Create giveaway_entries table
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS giveaway_entries (
                id SERIAL PRIMARY KEY,
                giveaway_id INTEGER NOT NULL,
                discord_server_id BIGINT NOT NULL,
                discord_id BIGINT,
                kick_username VARCHAR(255) NOT NULL,
                kick_user_id INTEGER,
                entry_method VARCHAR(20) NOT NULL,
                entry_count INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (giveaway_id) REFERENCES giveaways(id) ON DELETE CASCADE
            )
        """))
        print("✅ Created giveaway_entries table")
        
        # Create giveaway_chat_activity table
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS giveaway_chat_activity (
                id SERIAL PRIMARY KEY,
                giveaway_id INTEGER NOT NULL,
                discord_server_id BIGINT NOT NULL,
                kick_username VARCHAR(255) NOT NULL,
                message TEXT NOT NULL,
                message_hash VARCHAR(64) NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (giveaway_id) REFERENCES giveaways(id) ON DELETE CASCADE
            )
        """))
        print("✅ Created giveaway_chat_activity table")
        
        # Create indexes for performance
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_giveaways_server_status 
            ON giveaways(discord_server_id, status)
        """))
        
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_giveaway_entries_giveaway 
            ON giveaway_entries(giveaway_id, kick_username)
        """))
        
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_giveaway_chat_activity_tracking 
            ON giveaway_chat_activity(giveaway_id, kick_username, timestamp)
        """))
        
        print("✅ Created indexes")
        
        conn.commit()
        print("\n✅ Migration completed successfully!")

if __name__ == "__main__":
    try:
        run_migration()
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        sys.exit(1)
