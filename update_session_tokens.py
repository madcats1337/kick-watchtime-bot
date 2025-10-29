"""
Update Kick session tokens in the database.

This script updates the bot_tokens table with session-based authentication tokens
(bearer_token, xsrf_token, cookies) instead of OAuth tokens.

HOW TO GET SESSION TOKENS:
1. Log into kick.com in your browser (as the bot account)
2. Open Developer Tools (F12)
3. Go to the Network tab
4. Send a chat message in any channel
5. Find the request to "https://kick.com/api/v2/messages/send/{chatroom_id}"
6. Click on it and go to the "Headers" tab
7. Copy the following values:
   - Authorization: Bearer {token} → copy everything after "Bearer "
   - X-CSRF-Token: {xsrf_token} → copy the full value
   - Cookie: {full_cookie_string} → copy the entire cookie header value

Then run this script and paste the values when prompted.
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
print("UPDATE KICK SESSION TOKENS")
print("="*70)
print("\nTo get these tokens:")
print("1. Log into kick.com as 'maikelele' in your browser")
print("2. Open DevTools (F12) → Network tab")
print("3. Send a chat message")
print("4. Find request to /messages/send/ and copy headers")
print("="*70 + "\n")

# Get tokens from user
bearer_token = input("Enter Bearer Token (without 'Bearer ' prefix): ").strip()
xsrf_token = input("Enter XSRF-Token: ").strip()
cookies = input("Enter full Cookie string: ").strip()

if not all([bearer_token, xsrf_token, cookies]):
    print("\n❌ All three tokens are required!")
    exit(1)

# Validate tokens
if len(bearer_token) < 20:
    print("\n⚠️  Warning: Bearer token seems too short")
if len(xsrf_token) < 20:
    print("\n⚠️  Warning: XSRF token seems too short")
if "XSRF-TOKEN=" not in cookies:
    print("\n⚠️  Warning: Cookie string doesn't contain XSRF-TOKEN")

print("\n" + "="*70)
print("UPDATING DATABASE")
print("="*70)

try:
    with engine.begin() as conn:
        # Check if the bot_tokens table has the new schema
        result = conn.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'bot_tokens'
        """)).fetchall()
        
        columns = [row[0] for row in result]
        
        if 'bearer_token' not in columns:
            print("\n⚠️  Database schema needs updating!")
            print("Dropping old table and creating new one with session-based fields...")
            
            # Drop old table and create new one
            conn.execute(text("DROP TABLE IF EXISTS bot_tokens"))
            conn.execute(text("""
                CREATE TABLE bot_tokens (
                    bot_username TEXT PRIMARY KEY,
                    bearer_token TEXT NOT NULL,
                    xsrf_token TEXT NOT NULL,
                    cookies TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            print("✅ Table recreated with new schema")
        
        # Insert or update the tokens
        conn.execute(text("""
            INSERT INTO bot_tokens (bot_username, bearer_token, xsrf_token, cookies, created_at, last_used)
            VALUES (:username, :bearer, :xsrf, :cookies, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT (bot_username) 
            DO UPDATE SET 
                bearer_token = EXCLUDED.bearer_token,
                xsrf_token = EXCLUDED.xsrf_token,
                cookies = EXCLUDED.cookies,
                last_used = CURRENT_TIMESTAMP
        """), {
            "username": "maikelele",
            "bearer": bearer_token,
            "xsrf": xsrf_token,
            "cookies": cookies
        })
        
    print("\n✅ Session tokens updated successfully!")
    print("\n" + "="*70)
    print("VERIFICATION")
    print("="*70)
    
    # Verify the tokens were stored
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT 
                bot_username,
                LEFT(bearer_token, 20) || '...' as bearer_preview,
                LEFT(xsrf_token, 20) || '...' as xsrf_preview,
                created_at,
                last_used
            FROM bot_tokens 
            WHERE bot_username = 'maikelele'
        """)).fetchone()
        
        if result:
            print(f"\nBot Username: {result[0]}")
            print(f"Bearer Token: {result[1]}")
            print(f"XSRF Token: {result[2]}")
            print(f"Created At: {result[3]}")
            print(f"Last Used: {result[4]}")
            print("\n✅ Tokens stored successfully!")
            print("\n💡 The bot can now send messages using session-based authentication")
        else:
            print("\n❌ Could not verify tokens in database")

except Exception as e:
    print(f"\n❌ Error updating database: {e}")
    exit(1)

print("\n" + "="*70)
