"""
Test if message type affects visibility
"""
import requests
import time

TOKEN = "YTY5YTJLNGMTOTAWYI0ZNGFMLWE2YMMTM2YWMDQXMZY0NDLL"

headers = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "Accept": "*/*",
    "X-Channel": "maikelele"
}

tests = [
    ("type: bot", {"content": "🔵 Test 1: type=bot", "type": "bot"}),
    ("type: message", {"content": "🟢 Test 2: type=message", "type": "message"}),
    ("no type field", {"content": "🟡 Test 3: no type"}),
]

print("Testing different message types...")
print("Check maikelele's chat to see which ones appear!")
print("=" * 70)

for name, payload in tests:
    print(f"\nSending: {name}")
    print(f"Payload: {payload}")
    
    response = requests.post(
        "https://api.kick.com/public/v1/chat",
        headers=headers,
        json=payload
    )
    
    print(f"Status: {response.status_code}")
    print(f"Response: {response.text}")
    
    time.sleep(2)  # Wait between tests

print("\n" + "=" * 70)
print("Check maikelele's chat - which colored messages appeared?")
