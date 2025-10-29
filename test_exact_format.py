"""
Test the exact endpoint and payload that works
"""
import requests
import json

TOKEN = "YTY5YTJLNGMTOTAWYI0ZNGFMLWE2YMMTM2YWMDQXMZY0NDLL"

print("Testing different endpoint formats for sending chat messages...")
print("=" * 70)

# The endpoint that worked in our first test
print("\n1. Testing: POST https://api.kick.com/public/v1/chat (no chatroom)")
headers = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "Accept": "*/*"
}

payload = {"content": "🤖 Test 1: No chatroom specified", "type": "bot"}
response = requests.post("https://api.kick.com/public/v1/chat", headers=headers, json=payload)
print(f"   Status: {response.status_code}")
print(f"   Response: {response.text}")

# Try with message type instead of bot
print("\n2. Testing: Same endpoint with type='message'")
payload = {"content": "🤖 Test 2: type=message", "type": "message"}
response = requests.post("https://api.kick.com/public/v1/chat", headers=headers, json=payload)
print(f"   Status: {response.status_code}")
print(f"   Response: {response.text}")

# Try with no type
print("\n3. Testing: Same endpoint with no type field")
payload = {"content": "🤖 Test 3: no type field"}
response = requests.post("https://api.kick.com/public/v1/chat", headers=headers, json=payload)
print(f"   Status: {response.status_code}")
print(f"   Response: {response.text}")

print("\n" + "=" * 70)
print("Which one worked? We'll use that format in the bot.")
