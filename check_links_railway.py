import os
from sqlalchemy import create_engine, text

# Running inside Railway environment
engine = create_engine(os.getenv('DATABASE_URL'))

with engine.begin() as conn:
    print("=== Links Table Indexes ===")
    result = conn.execute(text("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'links'"))
    for row in result:
        print(f"{row[0]}:")
        print(f"  {row[1]}\n")
    
    print("\n=== Links Table Constraints ===")
    result = conn.execute(text("""
        SELECT conname, contype, pg_get_constraintdef(oid) 
        FROM pg_constraint 
        WHERE conrelid = 'links'::regclass
    """))
    for row in result:
        constraint_type = {'p': 'PRIMARY KEY', 'u': 'UNIQUE', 'f': 'FOREIGN KEY', 'c': 'CHECK'}.get(row[1], row[1])
        print(f"{row[0]} ({constraint_type}):")
        print(f"  {row[2]}\n")
    
    print("\n=== Links Table Structure ===")
    result = conn.execute(text("""
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_name = 'links'
        ORDER BY ordinal_position
    """))
    for row in result:
        nullable = "NULL" if row[2] == 'YES' else "NOT NULL"
        print(f"{row[0]}: {row[1]} ({nullable})")
