import os

import psycopg2

# Connect to database — credentials come from the environment only. A hardcoded
# production URL used to live here and leaked into git history; rotate that
# password if it was ever committed. Set DATABASE_URL before running.
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise SystemExit("❌ DATABASE_URL must be set in the environment.")

conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()

# Check current value
cur.execute(
    """
    SELECT key, value, discord_server_id
    FROM bot_settings
    WHERE key = 'kick_chatroom_id' AND discord_server_id = 914986636629143562
"""
)
result = cur.fetchone()

if result:
    print(f"Current: {result}")

    if result[1] == "152837":
        print("Deleting incorrect chatroom_id (152837 is broadcaster_user_id, not chatroom_id)")
        cur.execute(
            """
            DELETE FROM bot_settings
            WHERE key = 'kick_chatroom_id' AND discord_server_id = 914986636629143562
        """
        )
        conn.commit()
        print("✅ Deleted! kickpython will fetch the correct chatroom_id (151060) on next connection")
    else:
        print(f"Chatroom ID is: {result[1]}")
else:
    print("No chatroom_id found in database")

cur.close()
conn.close()
