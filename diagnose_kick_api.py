"""
Diagnostic script to test Kick API behavior with different configurations
"""
import requests
import json
import os

TOKEN = os.getenv("KICK_BOT_USER_TOKEN", "YTY5YTJLNGMTOTAWYI0ZNGFMLWE2YMMTM2YWMDQXMZY0NDLL")
CHANNEL = os.getenv("KICK_CHANNEL", "maikelele")

print("=" * 70)
print("KICK API DIAGNOSTIC")
print("=" * 70)
print(f"Token (first 20 chars): {TOKEN[:20]}...")
print(f"Channel: {CHANNEL}")
print()

# Test 1: Verify token with user endpoint
print("Test 1: Verifying token...")
print("-" * 70)
headers = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/json"
}

response = requests.get("https://api.kick.com/public/v1/users", headers=headers)
print(f"Status: {response.status_code}")
if response.status_code == 200:
    data = response.json()
    user_info = data.get("data", [{}])[0]
    print(f"✅ Token valid - User: {user_info.get('name')} (ID: {user_info.get('user_id')})")
else:
    print(f"❌ Token invalid: {response.text}")
    exit(1)

# Test 2: Get channel information
print("\nTest 2: Getting channel information...")
print("-" * 70)
response = requests.get(f"https://kick.com/api/v2/channels/{CHANNEL}")
print(f"Status: {response.status_code}")
if response.status_code == 200:
    channel_data = response.json()
    chatroom_id = channel_data.get("chatroom", {}).get("id")
    channel_id = channel_data.get("id")
    print(f"✅ Channel ID: {channel_id}")
    print(f"✅ Chatroom ID: {chatroom_id}")
    print(f"   Follower mode: {channel_data.get('chatroom', {}).get('followers_mode')}")
    print(f"   Subscriber mode: {channel_data.get('chatroom', {}).get('subscribers_mode')}")
else:
    print(f"⚠️ Could not fetch channel info: {response.text}")

# Test 3: Try different chat API endpoints and payloads
print("\nTest 3: Testing chat message API...")
print("-" * 70)

test_cases = [
    {
        "name": "Standard bot message",
        "url": "https://api.kick.com/public/v1/chat",
        "payload": {
            "content": "🤖 Test from diagnostic script",
            "type": "bot"
        }
    },
    {
        "name": "User type message",
        "url": "https://api.kick.com/public/v1/chat",
        "payload": {
            "content": "🤖 Test from diagnostic script",
            "type": "user"
        }
    },
    {
        "name": "Message without type",
        "url": "https://api.kick.com/public/v1/chat",
        "payload": {
            "content": "🤖 Test from diagnostic script"
        }
    }
]

chat_headers = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "Accept": "*/*",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

for i, test in enumerate(test_cases, 1):
    print(f"\nTest 3.{i}: {test['name']}")
    response = requests.post(test["url"], headers=chat_headers, json=test["payload"])
    print(f"   Status: {response.status_code}")
    print(f"   Response: {response.text[:200]}")
    if response.status_code == 200:
        print(f"   ✅ SUCCESS!")
        break

# Test 4: Check if there's a different endpoint format
print("\n\nTest 4: Alternative endpoints...")
print("-" * 70)

alt_endpoints = [
    "https://api.kick.com/v1/chat",
    "https://kick.com/api/v1/chat",
    "https://kick.com/api/public/v1/chat"
]

for endpoint in alt_endpoints:
    print(f"\nTrying: {endpoint}")
    response = requests.post(endpoint, headers=chat_headers, json={"content": "test", "type": "bot"})
    print(f"   Status: {response.status_code}")
    if response.status_code not in [404, 401]:
        print(f"   Response: {response.text[:200]}")

print("\n" + "=" * 70)
print("DIAGNOSTIC COMPLETE")
print("=" * 70)
