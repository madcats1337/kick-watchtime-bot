import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
engine = create_engine(os.getenv('DATABASE_URL'))
conn = engine.connect()

# Check current indexes
print("Current indexes on links table:")
result = conn.execute(text("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'links'"))
for row in result:
    print(f"{row[0]}: {row[1]}")

print("\n" + "="*80 + "\n")

# Check current constraints
print("Current constraints on links table:")
result = conn.execute(text("""
    SELECT conname, contype, pg_get_constraintdef(oid) 
    FROM pg_constraint 
    WHERE conrelid = 'links'::regclass
"""))
for row in result:
    print(f"{row[0]} ({row[1]}): {row[2]}")

print("\n" + "="*80 + "\n")

# Check table structure
print("Table structure:")
result = conn.execute(text("""
    SELECT column_name, data_type, is_nullable
    FROM information_schema.columns
    WHERE table_name = 'links'
    ORDER BY ordinal_position
"""))
for row in result:
    print(f"{row[0]}: {row[1]} (NULL: {row[2]})")

conn.close()
