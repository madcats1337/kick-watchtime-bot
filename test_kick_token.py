"""
Test the Kick bot token to see which account it belongs to
"""

import os
import requests
from dotenv import load_dotenv

load_dotenv()

token = "MDUWNMEWNTUTYJM3MS0ZNMJLLTK4YWITNZKWZMQ3MDEYMZC2"

print("\n" + "="*70)
print("TESTING KICK BOT TOKEN")
print("="*70 + "\n")

# Test 1: Get user info
print("Test 1: Getting user info...")
headers = {
    "Authorization": f"Bearer {token}",
    "Accept": "application/json"
}

response = requests.get("https://api.kick.com/public/v1/users", headers=headers)
print(f"Status: {response.status_code}")
print(f"Response: {response.text}\n")

# Test 2: Try to send a test message
print("Test 2: Trying to send test message...")
headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json",
    "Accept": "*/*"
}

payload = {
    "content": "Test message from bot",
    "type": "bot"
}

response = requests.post("https://api.kick.com/public/v1/chat", headers=headers, json=payload)
print(f"Status: {response.status_code}")
print(f"Response: {response.text}\n")

print("="*70 + "\n")
