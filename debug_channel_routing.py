"""
Debug exactly where messages are going
"""
import requests

TOKEN = "YTY5YTJLNGMTOTAWYI0ZNGFMLWE2YMMTM2YWMDQXMZY0NDLL"

# Test 1: Try with channel slug
print("Test 1: X-Channel: maikelele")
response = requests.post(
    "https://api.kick.com/public/v1/chat",
    headers={
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
        "X-Channel": "maikelele"
    },
    json={"content": "Test to maikelele chat", "type": "bot"}
)
print(f"Status: {response.status_code}, Response: {response.text}")

# Test 2: Try with uppercase
print("\nTest 2: X-Channel: Maikelele")
response = requests.post(
    "https://api.kick.com/public/v1/chat",
    headers={
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
        "X-Channel": "Maikelele"
    },
    json={"content": "Test with capital M", "type": "bot"}
)
print(f"Status: {response.status_code}, Response: {response.text}")

# Test 3: Without X-Channel (goes to bot's own channel)
print("\nTest 3: No X-Channel header")
response = requests.post(
    "https://api.kick.com/public/v1/chat",
    headers={
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json"
    },
    json={"content": "Test without channel header", "type": "bot"}
)
print(f"Status: {response.status_code}, Response: {response.text}")

print("\n" + "="*70)
print("Check both maikelele's chat AND Lelebot's chat/DMs")
print("to see where each message appeared!")
