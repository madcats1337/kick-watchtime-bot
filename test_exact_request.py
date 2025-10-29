"""
Test the EXACT request with X-Channel header to maikelele
"""
import requests

TOKEN = "YTY5YTJLNGMTOTAWYI0ZNGFMLWE2YMMTM2YWMDQXMZY0NDLL"

print("Testing exact message to maikelele channel...")
print("=" * 70)

headers = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "Accept": "*/*",
    "X-Channel": "maikelele"
}

payload = {
    "content": "@madcats Your slot request for Book of Dead has been received! ✅",
    "type": "bot"
}

print("Request details:")
print(f"URL: https://api.kick.com/public/v1/chat")
print(f"Headers: {headers}")
print(f"Payload: {payload}")
print()

response = requests.post(
    "https://api.kick.com/public/v1/chat",
    headers=headers,
    json=payload
)

print(f"Status: {response.status_code}")
print(f"Response: {response.text}")

if response.status_code == 200:
    print("\n✅ Message sent successfully!")
    print("This EXACT format works locally. The issue must be:")
    print("1. Token on Railway is different/expired")
    print("2. Railway's IP is blocked/rate-limited by Kick")
    print("3. Environment variable not set correctly on Railway")
elif response.status_code == 401:
    print("\n❌ 401 even locally - token issue")
    print("Need to get a new token")
else:
    print(f"\n❓ Unexpected status: {response.status_code}")
