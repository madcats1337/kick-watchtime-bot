"""
Add unique constraint to links table for ON CONFLICT to work
"""
import os
from sqlalchemy import create_engine, text

engine = create_engine(os.getenv('DATABASE_URL'))

with engine.begin() as conn:
    print("Checking current constraints...")
    
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
    else:
        print("Removing any duplicate entries...")
        # Remove duplicates, keeping the most recent
        conn.execute(text("""
            DELETE FROM links a USING links b
            WHERE a.id < b.id 
            AND a.discord_id = b.discord_id 
            AND a.discord_server_id = b.discord_server_id
        """))
        
        print("Adding unique constraint...")
        conn.execute(text("""
            ALTER TABLE links 
            ADD CONSTRAINT links_discord_server_unique 
            UNIQUE (discord_id, discord_server_id)
        """))
        
        print("✅ Migration complete!")
    
    # Verify
    result = conn.execute(text("""
        SELECT conname, pg_get_constraintdef(oid)
        FROM pg_constraint 
        WHERE conrelid = 'links'::regclass
    """))
    
    print("\nCurrent constraints on links table:")
    for row in result:
        print(f"  {row[0]}: {row[1]}")
