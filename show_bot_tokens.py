"""
Show all bot tokens in the database
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
print("ALL BOT TOKENS IN DATABASE")
print("="*70 + "\n")

try:
    with engine.connect() as conn:
        # Show all bot tokens
        result = conn.execute(text("""
            SELECT bot_username, access_token, refresh_token, created_at 
            FROM bot_tokens 
            ORDER BY created_at DESC
        """)).fetchall()
        
        if not result:
            print("❌ No bot tokens found in bot_tokens table\n")
        else:
            for row in result:
                username, access_token, refresh_token, created_at = row
                print(f"Bot Username: {username}")
                print(f"Created: {created_at}")
                print(f"Has Refresh Token: {'Yes' if refresh_token else 'No'}")
                print(f"\nAccess Token:")
                print(f"{access_token}")
                print("\n" + "-"*70 + "\n")
                
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()

print("="*70 + "\n")
