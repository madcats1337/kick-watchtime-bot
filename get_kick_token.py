"""
Helper script to get a Kick User Access Token for the bot.

This script will:
1. Generate a PKCE code challenge
2. Open the Kick authorization URL in your browser
3. Wait for you to authorize the app
4. Exchange the code for an access token
5. Display the token to add to Railway

Run this script, log in as your bot account (Lelebot), and authorize the app.
"""

import os
import secrets
import hashlib
import base64
import webbrowser
from urllib.parse import urlencode, parse_qs, urlparse
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler

# Get your client credentials
CLIENT_ID = input("Enter your KICK_CLIENT_ID: ").strip()
CLIENT_SECRET = input("Enter your KICK_CLIENT_SECRET: ").strip()
REDIRECT_URI = input("Enter your redirect URI (e.g., http://localhost:8080/callback): ").strip() or "http://localhost:8080/callback"

# Generate PKCE code verifier and challenge
code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('utf-8').rstrip('=')
code_challenge = base64.urlsafe_b64encode(
    hashlib.sha256(code_verifier.encode('utf-8')).digest()
).decode('utf-8').rstrip('=')

state = secrets.token_urlsafe(16)

# Store the authorization code
auth_code = None

class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global auth_code
        query = urlparse(self.path).query
        params = parse_qs(query)
        
        if 'code' in params:
            auth_code = params['code'][0]
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b"<html><body><h1>Authorization successful!</h1><p>You can close this window and return to the terminal.</p></body></html>")
        else:
            self.send_response(400)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b"<html><body><h1>Authorization failed!</h1></body></html>")
    
    def log_message(self, format, *args):
        pass  # Suppress logging

# Build authorization URL
auth_params = {
    'response_type': 'code',
    'client_id': CLIENT_ID,
    'redirect_uri': REDIRECT_URI,
    'scope': 'chat:send',  # Request chat sending permission
    'code_challenge': code_challenge,
    'code_challenge_method': 'S256',
    'state': state
}

auth_url = f"https://kick.com/oauth/authorize?{urlencode(auth_params)}"

print("\n" + "="*60)
print("KICK BOT AUTHORIZATION")
print("="*60)
print("\n1. Opening authorization URL in your browser...")
print(f"   URL: {auth_url}")
print("\n2. Log in as your bot account (Lelebot)")
print("3. Click 'Authorize' to grant chat permissions")
print("\n4. Waiting for callback...\n")

# Open browser
webbrowser.open(auth_url)

# Start local server to receive callback
if REDIRECT_URI.startswith("http://localhost"):
    port = int(urlparse(REDIRECT_URI).port or 8080)
    server = HTTPServer(('localhost', port), CallbackHandler)
    print(f"   Local callback server running on port {port}...")
    server.handle_request()  # Wait for one request
    
    if auth_code:
        print("\n✅ Authorization code received!")
        print("\n5. Exchanging code for access token...")
        
        # Exchange code for token
        token_data = {
            'grant_type': 'authorization_code',
            'client_id': CLIENT_ID,
            'client_secret': CLIENT_SECRET,
            'redirect_uri': REDIRECT_URI,
            'code': auth_code,
            'code_verifier': code_verifier
        }
        
        token_response = requests.post(
            'https://id.kick.com/oauth/token',
            data=token_data,
            headers={'Content-Type': 'application/x-www-form-urlencoded'}
        )
        
        if token_response.status_code == 200:
            token_info = token_response.json()
            access_token = token_info.get('access_token')
            expires_in = token_info.get('expires_in', 'unknown')
            
            print("\n" + "="*60)
            print("✅ SUCCESS! Your Kick Bot User Access Token:")
            print("="*60)
            print(f"\n{access_token}\n")
            print("="*60)
            print(f"\nToken expires in: {expires_in} seconds")
            print("\nAdd this to your Railway environment variables:")
            print(f"KICK_BOT_USER_TOKEN={access_token}")
            print("\n" + "="*60)
        else:
            print(f"\n❌ Failed to get token: {token_response.text}")
    else:
        print("\n❌ No authorization code received")
else:
    print("\nFor non-localhost redirects:")
    print(f"1. Visit: {auth_url}")
    print("2. Authorize the app")
    print("3. Copy the 'code' parameter from the redirect URL")
    print("4. Run this script again with the code to exchange it for a token")
