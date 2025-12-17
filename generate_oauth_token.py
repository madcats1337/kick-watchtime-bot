#!/usr/bin/env python3
"""
Generate OAuth 2.1 User Access Token for Kick Bot
Docs: https://docs.kick.com/getting-started/generating-tokens-oauth2-flow
"""
import os
import secrets
import hashlib
import base64
import webbrowser
from urllib.parse import urlencode, parse_qs, urlparse
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import requests
import psycopg2

# Load from environment or set here
CLIENT_ID = os.getenv('KICK_CLIENT_ID', '01K8QWJTACWW0YCG57W3P09T49')
CLIENT_SECRET = os.getenv('KICK_CLIENT_SECRET', '9a952a04aa3a04fa817e8d2ccbf88866bb0d877b49fd9e699fa43a41aa0dc491')
REDIRECT_URI = 'http://localhost:8888/callback'
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://postgres:QzzlAELgpwfZtHIVCuIHpuGxhXorXTZv@shinkansen.proxy.rlwy.net:57221/railway')

# Global state for callback
callback_data = {'code': None, 'state': None, 'error': None, 'done': False}

# Scopes required for the bot
SCOPES = ' '.join([
    'user:read',
    'channel:read',
    'channel:rewards:read',
    'chat:write',
    'events:subscribe',
    'kicks:read',
    'webhook:subscribe',
    'moderator:execute',
    'channel_points_rewards:read',
    'channel_points_rewards:write',
])

def generate_pkce_pair():
    """Generate code_verifier and code_challenge for PKCE"""
    # Generate random code_verifier (43-128 characters)
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('utf-8').rstrip('=')
    
    # Generate code_challenge (SHA256 hash of verifier)
    challenge = hashlib.sha256(code_verifier.encode('utf-8')).digest()
    code_challenge = base64.urlsafe_b64encode(challenge).decode('utf-8').rstrip('=')
    
    return code_verifier, code_challenge

class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """HTTP handler for OAuth callback"""
    
    def log_message(self, format, *args):
        """Suppress default logging"""
        pass
    
    def do_GET(self):
        """Handle GET request to /callback"""
        parsed = urlparse(self.path)
        
        if parsed.path == '/callback':
            params = parse_qs(parsed.query)
            
            if 'error' in params:
                callback_data['error'] = params['error'][0]
                callback_data['done'] = True
                self.send_response(400)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                self.wfile.write(f"""
                    <html>
                    <body style="font-family: Arial; padding: 50px; text-align: center;">
                        <h1 style="color: red;">❌ Authorization Failed</h1>
                        <p>Error: {params['error'][0]}</p>
                        <p>You can close this window.</p>
                    </body>
                    </html>
                """.encode())
            elif 'code' in params:
                callback_data['code'] = params['code'][0]
                callback_data['state'] = params.get('state', [None])[0]
                callback_data['done'] = True
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                self.wfile.write("""
                    <html>
                    <body style="font-family: Arial; padding: 50px; text-align: center;">
                        <h1 style="color: green;">✅ Authorization Successful!</h1>
                        <p>Processing tokens...</p>
                        <p><em>You can close this window.</em></p>
                    </body>
                    </html>
                """.encode())
            else:
                self.send_response(400)
                self.send_header('Content-type', 'text/plain')
                self.end_headers()
                self.wfile.write(b'Invalid callback')
        else:
            self.send_response(404)
            self.end_headers()

def start_callback_server():
    """Start HTTP server for OAuth callback"""
    server = HTTPServer(('localhost', 8888), OAuthCallbackHandler)
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    return server

def step1_authorize():
    """Step 1: Open authorization URL in browser"""
    code_verifier, code_challenge = generate_pkce_pair()
    state = secrets.token_urlsafe(16)
    
    # Build authorization URL
    params = {
        'response_type': 'code',
        'client_id': CLIENT_ID,
        'redirect_uri': REDIRECT_URI,
        'scope': SCOPES,
        'code_challenge': code_challenge,
        'code_challenge_method': 'S256',
        'state': state,
    }
    
    auth_url = f"https://id.kick.com/oauth/authorize?{urlencode(params)}"
    
    print("=" * 80)
    print("STEP 1: Authorize the Bot Application")
    print("=" * 80)
    print(f"\n1. Log in to Kick as MAIKELELE (the streamer account)")
    print(f"2. Authorize the BOT APPLICATION to act on maikelele's behalf")
    print(f"3. Opening authorization URL in browser...\n")
    print(f"URL: {auth_url}\n")
    print(f"3. After authorizing, you'll be redirected to:")
    print(f"   {REDIRECT_URI}?code=<CODE>&state=<STATE>")
    print(f"\n4. Copy the 'code' parameter from the URL\n")
    
    # Save for step 2
    with open('oauth_verifier.txt', 'w') as f:
        f.write(code_verifier)
    
    # Open browser
    webbrowser.open(auth_url)
    
    return code_verifier

def step2_exchange_code(code, code_verifier, discord_server_id=None):
    """Step 2: Exchange authorization code for access token"""
    print("\n" + "=" * 80)
    print("STEP 2: Exchange Code for Access Token")
    print("=" * 80)
    
    # Exchange code for token
    data = {
        'grant_type': 'authorization_code',
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'redirect_uri': REDIRECT_URI,
        'code_verifier': code_verifier,
        'code': code,
    }
    
    print(f"\nExchanging authorization code for token...")
    response = requests.post(
        'https://id.kick.com/oauth/token',
        data=data,
        headers={'Content-Type': 'application/x-www-form-urlencoded'}
    )
    
    if response.status_code == 200:
        token_data = response.json()
        print(f"\n✅ SUCCESS! Token generated:\n")
        print(f"Access Token:  {token_data['access_token']}")
        print(f"Token Type:    {token_data['token_type']}")
        print(f"Expires In:    {token_data['expires_in']} seconds")
        print(f"Refresh Token: {token_data['refresh_token']}")
        print(f"Scopes:        {token_data.get('scope', 'N/A')}")
        
        # Save to database if discord_server_id provided
        if discord_server_id:
            save_to_database(discord_server_id, token_data)
        else:
            print("\n⚠️  No discord_server_id provided - tokens not saved to database")
            print("Run script again and provide discord_server_id to save tokens")
        
        print("\n" + "=" * 80)
        print("TOKENS GENERATED SUCCESSFULLY")
        print("=" * 80)
        
        return token_data
    else:
        print(f"\n❌ ERROR: {response.status_code}")
        print(response.text)
        return None

def save_to_database(discord_server_id, token_data):
    """Save OAuth tokens to database"""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        
        # Update or insert kick_oauth_token
        cur.execute("""
            INSERT INTO bot_settings (discord_server_id, key, value)
            VALUES (%s, 'kick_oauth_token', %s)
            ON CONFLICT (discord_server_id, key)
            DO UPDATE SET value = EXCLUDED.value
        """, (discord_server_id, token_data['access_token']))
        
        # Update or insert kick_refresh_token
        cur.execute("""
            INSERT INTO bot_settings (discord_server_id, key, value)
            VALUES (%s, 'kick_refresh_token', %s)
            ON CONFLICT (discord_server_id, key)
            DO UPDATE SET value = EXCLUDED.value
        """, (discord_server_id, token_data['refresh_token']))
        
        conn.commit()
        cur.close()
        conn.close()
        
        print(f"\n✅ OAuth 2.1 tokens securely saved to database for discord_server_id={discord_server_id}")
        print(f"✅ Access token expires in {token_data['expires_in']} seconds")
        print(f"✅ Refresh token can be used to get new access tokens")
    except Exception as e:
        print(f"\n⚠️  Failed to save to database: {e}")
        print("You'll need to update the tokens manually or run the dashboard OAuth flow.")

def refresh_token(refresh_token):
    """Refresh an expired access token"""
    print("\n" + "=" * 80)
    print("REFRESH ACCESS TOKEN")
    print("=" * 80)
    
    data = {
        'grant_type': 'refresh_token',
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'refresh_token': refresh_token,
    }
    
    print(f"\nRefreshing access token...")
    response = requests.post(
        'https://id.kick.com/oauth/token',
        data=data,
        headers={'Content-Type': 'application/x-www-form-urlencoded'}
    )
    
    if response.status_code == 200:
        token_data = response.json()
        print(f"\n✅ SUCCESS! Token refreshed:\n")
        print(f"New Access Token expires in: {token_data['expires_in']} seconds")
        
        print("\n⚠️  IMPORTANT: Update tokens in database manually")
        print("Tokens are NOT saved to files for security reasons")
        return token_data
    else:
        print(f"\n❌ ERROR: {response.status_code}")
        print(response.text)
        return None

if __name__ == '__main__':
    import sys
    import time
    
    if len(sys.argv) == 1:
        # Automatic flow with callback server
        print("=" * 80)
        print("AUTOMATIC OAUTH 2.1 TOKEN GENERATION")
        print("=" * 80)
        
        # Ask for discord_server_id
        discord_server_id = input("\nEnter discord_server_id (or press Enter to skip database save): ").strip()
        if discord_server_id:
            try:
                discord_server_id = int(discord_server_id)
            except ValueError:
                print("Invalid discord_server_id, skipping database save")
                discord_server_id = None
        else:
            discord_server_id = None
        
        # Start callback server
        print("\n🌐 Starting local callback server on http://localhost:8888...")
        server = start_callback_server()
        
        # Generate PKCE pair
        code_verifier, code_challenge = generate_pkce_pair()
        state = secrets.token_urlsafe(16)
        
        # Build authorization URL
        params = {
            'response_type': 'code',
            'client_id': CLIENT_ID,
            'redirect_uri': REDIRECT_URI,
            'scope': SCOPES,
            'code_challenge': code_challenge,
            'code_challenge_method': 'S256',
            'state': state,
        }
        
        auth_url = f"https://id.kick.com/oauth/authorize?{urlencode(params)}"
        
        print("\n" + "=" * 80)
        print("STEP 1: Authorize the Bot Application")
        print("=" * 80)
        print(f"\n1. Log in to Kick as MAIKELELE (the streamer account)")
        print(f"2. Authorize the BOT APPLICATION to act on maikelele's behalf")
        print(f"3. Opening authorization URL in browser...\n")
        print(f"URL: {auth_url}\n")
        print(f"⏳ Waiting for authorization...\n")
        
        # Open browser
        webbrowser.open(auth_url)
        
        # Wait for callback
        while not callback_data['done']:
            time.sleep(0.5)
        
        # Stop server
        server.shutdown()
        
        # Check for errors
        if callback_data['error']:
            print(f"\n❌ Authorization failed: {callback_data['error']}")
            sys.exit(1)
        
        # Exchange code for token
        if callback_data['code']:
            step2_exchange_code(callback_data['code'], code_verifier, discord_server_id)
        else:
            print("\n❌ No authorization code received")
            sys.exit(1)
        
    elif len(sys.argv) == 2:
        # Manual flow: Step 2 only
        code = sys.argv[1]
        
        # Load code_verifier from file
        try:
            with open('oauth_verifier.txt', 'r') as f:
                code_verifier = f.read().strip()
        except FileNotFoundError:
            print("❌ ERROR: oauth_verifier.txt not found")
            print("Run the script without arguments to use automatic flow")
            sys.exit(1)
        
        step2_exchange_code(code, code_verifier)
        
    elif len(sys.argv) == 3 and sys.argv[1] == '--refresh':
        # Refresh token
        refresh_token_value = sys.argv[2]
        refresh_token(refresh_token_value)
    
    else:
        print("Usage:")
        print("  Automatic flow:  python generate_oauth_token.py")
        print("  Manual exchange: python generate_oauth_token.py <CODE>")
        print("  Refresh token:   python generate_oauth_token.py --refresh <REFRESH_TOKEN>")
