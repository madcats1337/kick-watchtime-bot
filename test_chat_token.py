import requests
import json

# Your new token
TOKEN = "YTY5YTJLNGMTOTAWYI0ZNGFMLWE2YMMTM2YWMDQXMZY0NDLL"

# Test 1: Check what scopes the token actually has
print("=" * 60)
print("Test 1: Checking token info...")
print("=" * 60)

headers = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/json"
}

# Try to get user info (should work with user:read)
response = requests.get("https://api.kick.com/public/v1/users", headers=headers)
print(f"User info status: {response.status_code}")
if response.status_code == 200:
    data = response.json()
    print(f"Response: {json.dumps(data, indent=2)}")
else:
    print(f"Error: {response.text}")

# Test 2: Try to send a chat message
print("\n" + "=" * 60)
print("Test 2: Trying to send a test message to chat...")
print("=" * 60)

chat_url = "https://api.kick.com/public/v1/chat"
chat_headers = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "Accept": "*/*"
}

payload = {
    "content": "🤖 Test message from bot - checking if chat:write works!",
    "type": "bot"
}

response = requests.post(chat_url, headers=chat_headers, json=payload)
print(f"Chat message status: {response.status_code}")
print(f"Response: {response.text}")

if response.status_code == 200:
    print("\n✅ SUCCESS! The token works for sending messages!")
    print("Even though it only showed 'user:read', chat:write might be implicitly granted!")
elif response.status_code == 401:
    print("\n❌ Token doesn't have chat:write permission")
    print("The scope display was accurate - only user:read is granted")
elif response.status_code == 403:
    print("\n⚠️ Forbidden - might need to follow the channel or other requirements")
else:
    print(f"\n❓ Unexpected status code: {response.status_code}")
