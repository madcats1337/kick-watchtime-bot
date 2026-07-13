import os

import psycopg2

# Credentials come from the environment only. A hardcoded production URL used to
# live here and leaked into git history — rotate that password if it was ever
# committed. Set DATABASE_URL before running (PowerShell: $env:DATABASE_URL = '...').
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise SystemExit("❌ DATABASE_URL must be set in the environment.")

conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()
cur.execute("SELECT key, value, discord_server_id FROM bot_settings WHERE key = 'kick_channel';")
results = cur.fetchall()
print("kick_channel entries in bot_settings:")
for row in results:
    print(f"  key={row[0]}, value={row[1]}, discord_server_id={row[2]}")
cur.close()
conn.close()
