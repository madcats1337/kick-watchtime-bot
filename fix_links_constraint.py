"""
Migration: Add unique constraint to links table for multi-server support
Fixes: ON CONFLICT error in OAuth linking
"""
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

def migrate():
    engine = create_engine(os.getenv('DATABASE_URL'))
    
    with engine.begin() as conn:
        print("Checking current constraints on links table...")
        
        # Check if constraint already exists
        result = conn.execute(text("""
            SELECT constraint_name 
            FROM information_schema.table_constraints 
            WHERE table_name = 'links' 
            AND constraint_type = 'UNIQUE'
            AND constraint_name = 'links_discord_server_unique'
        """))
        
        if result.fetchone():
            print("✅ Constraint already exists!")
            return
        
        print("Creating unique constraint on (discord_id, discord_server_id)...")
        
        # First, remove any duplicate entries (keep the most recent one)
        print("Removing duplicate entries...")
        conn.execute(text("""
            DELETE FROM links a USING links b
            WHERE a.id < b.id 
            AND a.discord_id = b.discord_id 
            AND a.discord_server_id = b.discord_server_id
        """))
        
        # Add the unique constraint
        print("Adding unique constraint...")
        conn.execute(text("""
            ALTER TABLE links 
            ADD CONSTRAINT links_discord_server_unique 
            UNIQUE (discord_id, discord_server_id)
        """))
        
        print("✅ Migration complete!")
        
        # Verify
        result = conn.execute(text("""
            SELECT indexname, indexdef 
            FROM pg_indexes 
            WHERE tablename = 'links'
        """))
        
        print("\nCurrent indexes:")
        for row in result:
            print(f"  {row[0]}: {row[1]}")

if __name__ == '__main__':
    migrate()
