"""
Research the correct Kick API endpoint by checking what headers/cookies might be needed
"""
import requests

TOKEN = "YTY5YTJLNGMTOTAWYI0ZNGFMLWE2YMMTM2YWMDQXMZY0NDLL"

# Let's try the v2 API or different combinations
print("Testing different API approaches...")
print("=" * 70)

# Test 1: Maybe we need to use v2?
print("\n1. Try v2 API")
response = requests.post(
    "https://api.kick.com/v2/chat",
    headers={
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
    },
    json={"content": "test", "type": "bot"}
)
print(f"Status: {response.status_code}, Response: {response.text[:200]}")

# Test 2: Maybe we need to specify channel in headers?
print("\n2. Try with X-Channel header")
response = requests.post(
    "https://api.kick.com/public/v1/chat",
    headers={
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
        "X-Channel": "maikelele"
    },
    json={"content": "test with channel header", "type": "bot"}
)
print(f"Status: {response.status_code}, Response: {response.text[:200]}")

# Test 3: Check if we can get channel info with the token
print("\n3. Get maikelele channel info with token")
response = requests.get(
    "https://api.kick.com/public/v1/channels/maikelele",
    headers={"Authorization": f"Bearer {TOKEN}"}
)
print(f"Status: {response.status_code}")
if response.status_code == 200:
    data = response.json()
    print(f"Channel ID: {data.get('id')}")
    print(f"Chatroom ID: {data.get('chatroom', {}).get('id')}")

# Test 4: Try sending to /channels/maikelele/messages or similar
print("\n4. Try /channels/{slug}/messages")
response = requests.post(
    "https://api.kick.com/public/v1/channels/maikelele/messages",
    headers={
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
    },
    json={"content": "test channels endpoint", "type": "bot"}
)
print(f"Status: {response.status_code}, Response: {response.text[:200]}")
