"""
Test different API call formats for Kick chat
"""

import os
import requests
from dotenv import load_dotenv

load_dotenv()

token = "MDUWNMEWNTUTYJM3MS0ZNMJLLTK4YWITNZKWZMQ3MDEYMZC2"
channel_name = os.getenv("KICK_CHANNEL", "madcats")

print("\n" + "="*70)
print("TESTING DIFFERENT KICK CHAT API FORMATS")
print("="*70 + "\n")

# First, get the channel/broadcaster info
print(f"Getting channel info for: {channel_name}")
response = requests.get(f"https://kick.com/api/v2/channels/{channel_name}")
if response.status_code == 200:
    channel_data = response.json()
    broadcaster_id = channel_data.get("user_id") or channel_data.get("id")
    chatroom_id = channel_data.get("chatroom", {}).get("id")
    print(f"✅ Broadcaster ID: {broadcaster_id}")
    print(f"✅ Chatroom ID: {chatroom_id}\n")
else:
    print(f"❌ Failed to get channel info: {response.status_code}\n")
    broadcaster_id = None
    chatroom_id = None

# Test different payload formats
test_cases = [
    {
        "name": "Bot type only",
        "payload": {
            "content": "Test 1: Bot type only",
            "type": "bot"
        }
    },
    {
        "name": "Bot type + broadcaster_user_id",
        "payload": {
            "content": "Test 2: With broadcaster_user_id",
            "type": "bot",
            "broadcaster_user_id": broadcaster_id
        }
    },
    {
        "name": "User type + broadcaster_user_id",
        "payload": {
            "content": "Test 3: User type",
            "type": "user",
            "broadcaster_user_id": broadcaster_id
        }
    }
]

headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json",
    "Accept": "*/*"
}

for test in test_cases:
    print(f"Test: {test['name']}")
    print(f"Payload: {test['payload']}")
    
    response = requests.post(
        "https://api.kick.com/public/v1/chat",
        headers=headers,
        json=test['payload']
    )
    
    print(f"Status: {response.status_code}")
    print(f"Response: {response.text}")
    print("-" * 70 + "\n")

print("="*70 + "\n")
