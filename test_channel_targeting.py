"""
Test if we need to specify which channel/chatroom to send to
"""
import requests
import json

TOKEN = "YTY5YTJLNGMTOTAWYI0ZNGFMLWE2YMMTM2YWMDQXMZY0NDLL"

# First, let's see if there's documentation or if we need chatroom_id
# Let's try getting maikelele's chatroom info

print("Getting maikelele channel info...")
response = requests.get("https://kick.com/api/v2/channels/maikelele")
if response.status_code == 200:
    data = response.json()
    chatroom_id = data.get("chatroom", {}).get("id")
    print(f"Maikelele chatroom_id: {chatroom_id}")
    
    # Now test with chatroom_id in the payload
    print("\nTest 1: Sending with chatroom_id in payload...")
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
        "Accept": "*/*"
    }
    
    payload = {
        "content": "🤖 Test with chatroom_id",
        "type": "bot",
        "chatroom_id": chatroom_id
    }
    
    response = requests.post("https://api.kick.com/public/v1/chat", headers=headers, json=payload)
    print(f"Status: {response.status_code}")
    print(f"Response: {response.text}")
    
    # Test 2: Try URL with chatroom ID
    print(f"\nTest 2: Sending to /chat/{chatroom_id}...")
    response = requests.post(f"https://api.kick.com/public/v1/chat/{chatroom_id}", headers=headers, json={"content": "🤖 Test with URL", "type": "bot"})
    print(f"Status: {response.status_code}")
    print(f"Response: {response.text}")
    
    # Test 3: Try /channels endpoint
    print(f"\nTest 3: Sending to /channels/maikelele/chat...")
    response = requests.post(f"https://api.kick.com/public/v1/channels/maikelele/chat", headers=headers, json={"content": "🤖 Test channels endpoint", "type": "bot"})
    print(f"Status: {response.status_code}")
    print(f"Response: {response.text}")
