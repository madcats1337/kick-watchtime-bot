"""
Migration: Add provably fair columns to raffle_draws table
Adds: server_seed, client_seed, nonce, proof_hash
"""

import psycopg2
import os

def migrate_add_provably_fair_to_draws(engine):
    """Add provably fair columns to raffle_draws table"""
    try:
        # Get connection from SQLAlchemy engine
        raw_conn = engine.raw_connection()
        cursor = raw_conn.cursor()
        
        print("🔄 Checking raffle_draws table for provably fair columns...")
        
        # Check if columns already exist
        cursor.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'raffle_draws' 
            AND column_name IN ('server_seed', 'client_seed', 'nonce', 'proof_hash')
        """)
        existing_columns = [row[0] for row in cursor.fetchall()]
        
        columns_to_add = []
        if 'server_seed' not in existing_columns:
            columns_to_add.append(('server_seed', 'TEXT'))
        if 'client_seed' not in existing_columns:
            columns_to_add.append(('client_seed', 'TEXT'))
        if 'nonce' not in existing_columns:
            columns_to_add.append(('nonce', 'TEXT'))
        if 'proof_hash' not in existing_columns:
            columns_to_add.append(('proof_hash', 'TEXT'))
        
        if not columns_to_add:
            print("✅ All provably fair columns already exist")
            cursor.close()
            raw_conn.close()
            return
        
        # Add missing columns
        for column_name, column_type in columns_to_add:
            print(f"   Adding column: {column_name} {column_type}")
            cursor.execute(f"ALTER TABLE raffle_draws ADD COLUMN IF NOT EXISTS {column_name} {column_type}")
        
        raw_conn.commit()
        cursor.close()
        raw_conn.close()
        
        print(f"✅ Added {len(columns_to_add)} provably fair column(s) to raffle_draws table")
        
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        raise

if __name__ == "__main__":
    from sqlalchemy import create_engine
    
    DATABASE_URL = os.getenv('DATABASE_URL')
    if not DATABASE_URL:
        print("ERROR: DATABASE_URL environment variable not set")
        exit(1)
    
    engine = create_engine(DATABASE_URL)
    migrate_add_provably_fair_to_draws(engine)
