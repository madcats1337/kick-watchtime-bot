"""
Quick script to generate a Kick OAuth URL for bot authorization.
This generates the URL you need to visit to authorize your bot account.
"""

import secrets
import hashlib
import base64
from urllib.parse import urlencode

print("\n" + "="*70)
print("KICK BOT OAUTH URL GENERATOR")
print("="*70)

# Get credentials
client_id = input("\nEnter your KICK_CLIENT_ID: ").strip()
redirect_uri = input("Enter your REDIRECT_URI (from Kick app settings): ").strip()

# Generate PKCE code verifier and challenge
code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('utf-8').rstrip('=')
code_challenge = base64.urlsafe_b64encode(
    hashlib.sha256(code_verifier.encode('utf-8')).digest()
).decode('utf-8').rstrip('=')

# Generate random state
state = secrets.token_urlsafe(16)

# Build OAuth URL
params = {
    'response_type': 'code',
    'client_id': client_id,
    'redirect_uri': redirect_uri,
    'scope': 'chat:send',
    'code_challenge': code_challenge,
    'code_challenge_method': 'S256',
    'state': state
}

oauth_url = f"https://kick.com/oauth/authorize?{urlencode(params)}"

print("\n" + "="*70)
print("YOUR OAUTH AUTHORIZATION URL:")
print("="*70)
print(f"\n{oauth_url}\n")
print("="*70)

print("\n📋 INSTRUCTIONS:")
print("1. Open the URL above in your browser")
print("2. Log in as your bot account (Lelebot)")
print("3. Click 'Authorize' to grant chat:send permission")
print("4. Copy the 'code' from the redirect URL")
print("5. Run get_kick_token.py OR use curl to exchange the code for a token")

print("\n🔐 SAVE THIS CODE VERIFIER (needed for token exchange):")
print(f"   {code_verifier}")

print("\n💡 TIP: Use get_kick_token.py for the full automated flow!")
print("="*70 + "\n")
