"""
Database health check script.
Run this to verify database connectivity.
"""

import os
import sys
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///watchtime.db")

# Convert postgres:// to postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

print("🔍 Testing database connection...")
print(f"URL: {DATABASE_URL.split('@')[0] if '@' in DATABASE_URL else DATABASE_URL}")

try:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)

    with engine.connect() as conn:
        # Test connection
        result = conn.execute(text("SELECT 1"))
        result.fetchone()
        print("✅ Database connection successful!")

        # Check tables
        print("\n📋 Checking tables...")
        tables = ['watchtime', 'links', 'pending_links']
        for table in tables:
            try:
                result = conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
                count = result.fetchone()[0]
                print(f"  ✅ {table}: {count} rows")
            except Exception as e:
                print(f"  ❌ {table}: {e}")

        print("\n✅ Database health check passed!")

except Exception as e:
    print(f"\n❌ Database health check failed: {e}")
    sys.exit(1)
