import psycopg2

conn = psycopg2.connect('postgresql://postgres:QzzlAELgpwfZtHIVCuIHpuGxhXorXTZv@shinkansen.proxy.rlwy.net:57221/railway')
cur = conn.cursor()
cur.execute("SELECT key, value, discord_server_id FROM bot_settings WHERE key = 'kick_channel';")
results = cur.fetchall()
print("kick_channel entries in bot_settings:")
for row in results:
    print(f"  key={row[0]}, value={row[1]}, discord_server_id={row[2]}")
cur.close()
conn.close()
