"""
Add expires_at column to existing bot_tokens table.
Run this to migrate the database schema without dropping existing data.
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
print("ADDING expires_at COLUMN TO bot_tokens TABLE")
print("="*70)

try:
    with engine.begin() as conn:
        # Check if column already exists
        result = conn.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'bot_tokens' AND column_name = 'expires_at'
        """)).fetchone()
        
        if result:
            print("\n✅ expires_at column already exists!")
        else:
            # Add the column
            conn.execute(text("""
                ALTER TABLE bot_tokens 
                ADD COLUMN expires_at TIMESTAMP
            """))
            print("\n✅ expires_at column added successfully!")
        
        # Show current table structure
        result = conn.execute(text("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns 
            WHERE table_name = 'bot_tokens'
            ORDER BY ordinal_position
        """)).fetchall()
        
        print("\n📋 Current table structure:")
        for column_name, data_type, is_nullable in result:
            nullable = "NULL" if is_nullable == "YES" else "NOT NULL"
            print(f"   - {column_name}: {data_type} ({nullable})")
        
        # Show existing tokens (count only)
        count = conn.execute(text("SELECT COUNT(*) FROM bot_tokens")).fetchone()[0]
        print(f"\n📊 Existing bot tokens: {count}")
        
        if count > 0:
            print("\n⚠️  Existing tokens don't have expiration time set.")
            print("They will be refreshed on-demand when needed, or you can re-authorize to set expiration.")

except Exception as e:
    print(f"\n❌ Error updating table: {e}")
    import traceback
    traceback.print_exc()
    exit(1)

print("\n" + "="*70)
print("✅ Migration complete!")
print("="*70 + "\n")
