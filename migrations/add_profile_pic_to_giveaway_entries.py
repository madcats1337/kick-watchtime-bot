"""
Migration: Add profile_pic_url column to giveaway_entries

This allows storing Kick user profile pictures for use in the overlay
"""

import os
import psycopg2
from urllib.parse import urlparse


def run_migration():
    """Add profile_pic_url column to giveaway_entries table"""
    database_url = os.getenv('DATABASE_URL')
    
    if not database_url:
        print("❌ ERROR: DATABASE_URL not found in environment variables")
        return False
    
    try:
        # Parse connection string
        result = urlparse(database_url)
        conn = psycopg2.connect(
            database=result.path[1:],
            user=result.username,
            password=result.password,
            host=result.hostname,
            port=result.port
        )
        conn.autocommit = True
        cursor = conn.cursor()
        
        print("🔄 Adding profile_pic_url column to giveaway_entries...")
        
        # Add profile_pic_url column
        cursor.execute("""
            ALTER TABLE giveaway_entries 
            ADD COLUMN IF NOT EXISTS profile_pic_url TEXT;
        """)
        
        print("✅ Migration completed successfully!")
        
        cursor.close()
        conn.close()
        return True
        
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        return False


if __name__ == "__main__":
    run_migration()
