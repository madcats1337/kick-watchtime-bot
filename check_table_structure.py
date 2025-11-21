from sqlalchemy import create_engine, text

database_url = "postgresql://postgres:qlCUFZaNzxnkRdqKYKmkrwFloDArkYqS@shinkansen.proxy.rlwy.net:57221/railway"
engine = create_engine(database_url)

with engine.connect() as conn:
    result = conn.execute(text("""
        SELECT column_name, data_type 
        FROM information_schema.columns 
        WHERE table_name = 'raffle_tickets' 
        ORDER BY ordinal_position
    """))
    print("raffle_tickets columns:")
    for row in result:
        print(f"  - {row[0]}: {row[1]}")
