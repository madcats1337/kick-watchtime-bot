"""
Extract Kick access token for bot from the database.
Run this after authorizing the bot through /bot/authorize endpoint.
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
print("EXTRACT BOT ACCESS TOKEN")
print("="*70)

kick_username = input("\nEnter the Kick bot username (e.g., 'Lelebot'): ").strip()

with engine.connect() as conn:
    result = conn.execute(text("""
        SELECT bot_username, access_token, refresh_token, created_at 
        FROM bot_tokens 
        WHERE LOWER(bot_username) = LOWER(:username)
    """), {"username": kick_username}).fetchone()

if not result:
    print(f"\n❌ No bot token found for: {kick_username}")
    print("\n💡 Steps to get the token:")
    print("1. Go to: https://kick-dicord-bot-test-production.up.railway.app/bot/authorize")
    print("2. Log in to Kick as your bot account (Lelebot)")
    print("3. Authorize the app with chat:send permission")
    print("4. Run this script again")
    exit(1)

username, access_token, refresh_token, created_at = result

print(f"\n✅ Found bot token!")
print(f"   Bot Username: {username}")
print(f"   Created: {created_at}")
print(f"   Has Refresh Token: {'Yes' if refresh_token else 'No'}")

print("\n" + "="*70)
print("KICK_BOT_USER_TOKEN (Add this to Railway environment variables):")
print("="*70)
print(f"\n{access_token}\n")
print("="*70)

if refresh_token:
    print("\n" + "="*70)
    print("KICK_BOT_REFRESH_TOKEN (Optional - for automatic token refresh):")
    print("="*70)
    print(f"\n{refresh_token}\n")
    print("="*70)

print("\n📋 Next steps:")
print("1. Copy the KICK_BOT_USER_TOKEN above")
print("2. Go to your Railway project settings")
print("3. Add/update environment variable: KICK_BOT_USER_TOKEN")
print("4. Paste the token as the value")
print("5. Redeploy your bot")
print("="*70 + "\n")
