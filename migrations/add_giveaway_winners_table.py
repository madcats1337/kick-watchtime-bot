"""
Migration: Add giveaway_winners table for multiple winners support
"""
import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

def run_migration():
    """Create giveaway_winners table"""
    try:
        conn = psycopg2.connect(os.getenv('DATABASE_URL'))
        cursor = conn.cursor()
        
        print("Creating giveaway_winners table...")
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS giveaway_winners (
                id SERIAL PRIMARY KEY,
                giveaway_id INTEGER NOT NULL,
                discord_server_id VARCHAR(50) NOT NULL,
                kick_username VARCHAR(255) NOT NULL,
                kick_user_id VARCHAR(50),
                drawn_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                announced BOOLEAN DEFAULT FALSE,
                FOREIGN KEY (giveaway_id, discord_server_id) 
                    REFERENCES giveaways(id, discord_server_id) 
                    ON DELETE CASCADE
            );
        """)
        
        print("✅ Created giveaway_winners table")
        
        # Create indexes
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_giveaway_winners_giveaway 
            ON giveaway_winners(giveaway_id, discord_server_id);
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_giveaway_winners_server 
            ON giveaway_winners(discord_server_id);
        """)
        
        print("✅ Created indexes")
        
        # Remove winner_kick_username column from giveaways (optional - keep for backward compatibility)
        # cursor.execute("""
        #     ALTER TABLE giveaways DROP COLUMN IF EXISTS winner_kick_username;
        # """)
        
        conn.commit()
        cursor.close()
        conn.close()
        
        print("\n✅ Migration completed successfully!")
        
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        raise

if __name__ == '__main__':
    run_migration()
