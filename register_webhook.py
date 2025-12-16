"""
Register webhook subscription with Kick API
"""
import os
import requests
import json

# Get access token from environment or database
KICK_ACCESS_TOKEN = os.getenv("KICK_BOT_USER_TOKEN")  # Your bot's access token
WEBHOOK_URL = "https://bot.lelebot.xyz/webhooks/kick"

if not KICK_ACCESS_TOKEN:
    print("❌ KICK_BOT_USER_TOKEN not set")
    print("Please set it as an environment variable or get it from the database")
    exit(1)

# Kick API endpoint for creating event subscriptions
url = "https://api.kick.com/public/v1/events/subscriptions"

headers = {
    "Authorization": f"Bearer {KICK_ACCESS_TOKEN}",
    "Content-Type": "application/json",
    "Accept": "application/json"
}

# Subscribe to chat.message.sent event
payload = {
    "type": "chat.message.sent",
    "callback_url": WEBHOOK_URL,
    "secret": os.getenv("KICK_WEBHOOK_SECRET", "")
}

print(f"📡 Registering webhook subscription...")
print(f"   Event: chat.message.sent")
print(f"   Callback URL: {WEBHOOK_URL}")
print(f"   Secret: {'Set' if payload['secret'] else 'Not set'}")

try:
    response = requests.post(url, headers=headers, json=payload)
    
    print(f"\n📥 Response Status: {response.status_code}")
    print(f"📥 Response Body:")
    print(json.dumps(response.json(), indent=2))
    
    if response.status_code in [200, 201]:
        print("\n✅ Webhook subscription created successfully!")
    else:
        print(f"\n❌ Failed to create webhook subscription")
        
except Exception as e:
    print(f"\n❌ Error: {e}")
    import traceback
    traceback.print_exc()
