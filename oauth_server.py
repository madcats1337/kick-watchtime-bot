"""
OAuth Web Server for Kick Authentication
Handles OAuth 2.0 PKCE flow for linking Kick accounts to Discord
"""

import os
import secrets
import hashlib
import base64
from flask import Flask, request, redirect, jsonify, render_template_string
from authlib.integrations.requests_client import OAuth2Session
from sqlalchemy import create_engine, text
from datetime import datetime, timezone
from urllib.parse import urlencode

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", secrets.token_hex(32))

# Global error handler
@app.errorhandler(Exception)
def handle_error(e):
    print(f"🚨 Unhandled error: {e}", flush=True)
    import traceback
    traceback.print_exc()
    return jsonify({"error": str(e), "type": type(e).__name__}), 500

# Kick OAuth Configuration
KICK_CLIENT_ID = os.getenv("KICK_CLIENT_ID")
KICK_CLIENT_SECRET = os.getenv("KICK_CLIENT_SECRET")
OAUTH_BASE_URL = os.getenv("OAUTH_BASE_URL", "")  # e.g., https://your-app.up.railway.app

if not KICK_CLIENT_ID or not KICK_CLIENT_SECRET:
    print("⚠️ WARNING: KICK_CLIENT_ID and KICK_CLIENT_SECRET not set!")
    print("⚠️ OAuth linking will not work until these are configured.")

# Kick OAuth endpoints - correct URLs confirmed from lele.gg
KICK_AUTHORIZE_URL = "https://id.kick.com/oauth/authorize"
KICK_TOKEN_URL = "https://id.kick.com/oauth/token"
KICK_USER_API_URL = "https://kick.com/api/v2/user"
KICK_OAUTH_USER_INFO_URL = "https://id.kick.com/oauth/userinfo"

# Database configuration (reuse from bot.py)
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///watchtime.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

# Initialize database tables
with engine.begin() as conn:
    # Create oauth_states table for storing OAuth state across workers
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS oauth_states (
            state TEXT PRIMARY KEY,
            discord_id BIGINT NOT NULL,
            code_verifier TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))

# Note: OAuth states are stored in database, not in-memory
# This is necessary because Gunicorn workers don't share memory


def generate_pkce_pair():
    """Generate PKCE code_verifier and code_challenge."""
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('utf-8').rstrip('=')
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode('utf-8')).digest()
    ).decode('utf-8').rstrip('=')
    return code_verifier, code_challenge


@app.route('/')
def index():
    """Simple homepage."""
    return """
    <html>
        <head>
            <title>Kick Discord Bot</title>
            <style>
                body {
                    font-family: Arial, sans-serif;
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    height: 100vh;
                    margin: 0;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                }
                .container {
                    text-align: center;
                    padding: 40px;
                    background: rgba(255, 255, 255, 0.1);
                    border-radius: 20px;
                    backdrop-filter: blur(10px);
                }
                h1 { margin: 0 0 20px 0; }
                p { font-size: 18px; }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>🎮 Kick Discord Bot</h1>
                <p>OAuth authentication server is running!</p>
                <p>Use the <code>!linkoauth</code> command in Discord to link your Kick account.</p>
            </div>
        </body>
    </html>
    """


@app.route('/health')
def health():
    """Health check endpoint for Railway."""
    return jsonify({"status": "healthy", "oauth_configured": bool(KICK_CLIENT_ID and KICK_CLIENT_SECRET)}), 200


@app.route('/auth/kick')
def auth_kick():
    """
    Initiate Kick OAuth flow.
    Query params: discord_id (required)
    """
    discord_id = request.args.get('discord_id')
    
    if not discord_id:
        return "❌ Missing discord_id parameter", 400
    
    if not KICK_CLIENT_ID or not KICK_CLIENT_SECRET:
        return "❌ OAuth not configured. Please set KICK_CLIENT_ID and KICK_CLIENT_SECRET.", 500
    
    # Generate PKCE pair
    code_verifier, code_challenge = generate_pkce_pair()
    
    # Generate state for CSRF protection
    state = secrets.token_urlsafe(32)
    
    # Store state in database (survives across Gunicorn workers)
    with engine.begin() as conn:
        # Clean up old states (older than 10 minutes)
        conn.execute(text("""
            DELETE FROM oauth_states 
            WHERE created_at < CURRENT_TIMESTAMP - INTERVAL '10 minutes'
        """))
        
        # Store new state
        conn.execute(text("""
            INSERT INTO oauth_states (state, discord_id, code_verifier, created_at)
            VALUES (:state, :discord_id, :code_verifier, CURRENT_TIMESTAMP)
        """), {"state": state, "discord_id": int(discord_id), "code_verifier": code_verifier})
    
    # Build authorization URL with user:read scope and PKCE
    redirect_uri = f"{OAUTH_BASE_URL}/auth/kick/callback"
    
    auth_params = {
        'client_id': KICK_CLIENT_ID,
        'response_type': 'code',
        'redirect_uri': redirect_uri,
        'state': state,
        'scope': 'user:read',  # Kick scope format (confirmed from lele.gg)
        'code_challenge': code_challenge,
        'code_challenge_method': 'S256'
    }
    
    print(f"🔗 Authorization URL: {KICK_AUTHORIZE_URL}?{urlencode(auth_params)}", flush=True)
    
    auth_url = f"{KICK_AUTHORIZE_URL}?{urlencode(auth_params)}"
    
    return redirect(auth_url)


@app.route('/auth/kick/callback')
def auth_kick_callback():
    """Handle OAuth callback from Kick."""
    print(f"🔔 Callback received! Query params: {dict(request.args)}", flush=True)
    
    code = request.args.get('code')
    state = request.args.get('state')
    error = request.args.get('error')
    
    print(f"📥 Code: {code[:20] if code else None}..., State: {state}, Error: {error}", flush=True)
    
    if error:
        print(f"❌ Kick returned error: {error}", flush=True)
        return render_error(f"Kick authorization failed: {error}")
    
    if not code or not state:
        print(f"❌ Missing code or state", flush=True)
        return render_error("Missing authorization code or state")
    
    # Verify state from database
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT discord_id, code_verifier FROM oauth_states WHERE state = :state
        """), {"state": state}).fetchone()
    
    print(f"🔍 Checking state in database...", flush=True)
    if not result:
        print(f"❌ State not found or expired", flush=True)
        return render_error("Invalid or expired state. Please try linking again.")
    
    discord_id = result[0]
    code_verifier = result[1]
    
    print(f"✅ State valid, Discord ID: {discord_id}", flush=True)
    
    # Exchange code for access token
    try:
        token_data = exchange_code_for_token(code, code_verifier=code_verifier)  # Use PKCE
        access_token = token_data.get('access_token')
        id_token = token_data.get('id_token')  # OpenID Connect ID token
        
        print(f"📝 Token data keys: {token_data.keys()}", flush=True)
        
        if not access_token:
            return render_error("Failed to obtain access token")
        
        # Try to decode access token if it's a JWT (might contain user info)
        kick_user = None
        try:
            import json
            import base64
            # Check if access_token is a JWT (has 3 parts separated by dots)
            parts = access_token.split('.')
            if len(parts) == 3:
                print(f"🔍 Access token appears to be JWT, attempting to decode...", flush=True)
                # Decode the payload (middle part)
                payload = parts[1]
                # Add padding if needed
                payload += '=' * (4 - len(payload) % 4)
                decoded = base64.urlsafe_b64decode(payload)
                jwt_data = json.loads(decoded)
                print(f"✅ Decoded JWT payload: {jwt_data}", flush=True)
                
                # Extract username from JWT
                if 'username' in jwt_data or 'sub' in jwt_data or 'name' in jwt_data:
                    kick_user = jwt_data
        except Exception as e:
            print(f"⚠️ Failed to decode access token as JWT: {e}", flush=True)
        
        # Try to get user info from ID token first (OpenID Connect)
        if not kick_user and id_token:
            try:
                import json
                import base64
                # Decode ID token (JWT) - middle part contains claims
                parts = id_token.split('.')
                if len(parts) >= 2:
                    # Add padding if needed
                    payload = parts[1]
                    payload += '=' * (4 - len(payload) % 4)
                    decoded = base64.urlsafe_b64decode(payload)
                    kick_user = json.loads(decoded)
                    print(f"✅ Got user from ID token: {kick_user}", flush=True)
            except Exception as e:
                print(f"❌ Failed to decode ID token: {e}", flush=True)
                import traceback
                traceback.print_exc()
        
        # Fallback: Get user info from API
        if not kick_user:
            print(f"⚠️ No user info available from token/ID token, trying API...", flush=True)
            try:
                kick_user = get_kick_user_info(access_token)
                print(f"📊 API response: {kick_user}", flush=True)
            except Exception as e:
                print(f"⚠️ API call failed: {e}", flush=True)
                # API failed, ask user for username manually
                kick_user = None
        
        # If we still don't have user info, redirect to username input page
        if not kick_user:
            print(f"⚠️ Could not get user info automatically, asking user to input username", flush=True)
            return render_username_form(state, discord_id)
        
        # Extract username from various possible fields
        kick_username = (
            kick_user.get('username') or 
            kick_user.get('preferred_username') or 
            kick_user.get('name') or
            kick_user.get('sub')  # OpenID subject identifier
        )
        
        print(f"👤 Extracted username: {kick_username}", flush=True)
        
        if not kick_username:
            print(f"❌ Could not find username. User data: {kick_user}", flush=True)
            return render_error(f"Could not find username in Kick response. Data: {list(kick_user.keys())}")
        
        # Check if Kick account is already linked to another Discord user
        with engine.connect() as conn:
            existing = conn.execute(text(
                "SELECT discord_id FROM links WHERE kick_name = :k"
            ), {"k": kick_username.lower()}).fetchone()
            
            if existing and existing[0] != discord_id:
                return render_error(
                    f"Kick account '{kick_username}' is already linked to another Discord user."
                )
        
        # Link accounts in database
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO links (discord_id, kick_name)
                VALUES (:d, :k)
                ON CONFLICT(discord_id) DO UPDATE SET kick_name = excluded.kick_name
            """), {"d": discord_id, "k": kick_username.lower()})
            
            # Clean up pending bio verifications if any
            conn.execute(text("DELETE FROM pending_links WHERE discord_id = :d"), {"d": discord_id})
            
            # Clean up used OAuth state
            conn.execute(text("DELETE FROM oauth_states WHERE state = :state"), {"state": state})
        
        return render_success(kick_username)
        
    except Exception as e:
        print(f"❌ [OAuth] Error during callback: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return render_error(f"An error occurred: {str(e)}")


def exchange_code_for_token(code, code_verifier=None):
    """Exchange authorization code for access token."""
    import requests
    
    redirect_uri = f"{OAUTH_BASE_URL}/auth/kick/callback"
    
    token_data = {
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': redirect_uri,
        'client_id': KICK_CLIENT_ID,
        'client_secret': KICK_CLIENT_SECRET
    }
    
    # Only include code_verifier if PKCE was used
    if code_verifier:
        token_data['code_verifier'] = code_verifier
    
    print(f"🔄 Exchanging code for token...", flush=True)
    response = requests.post(KICK_TOKEN_URL, data=token_data, timeout=10)
    print(f"📊 Token response status: {response.status_code}", flush=True)
    response.raise_for_status()
    
    token_json = response.json()
    print(f"✅ Got token response with keys: {list(token_json.keys())}", flush=True)
    return token_json


def decode_jwt_token(token):
    """Decode JWT token to extract user information without verification.
    
    This is safe because:
    1. We got the token directly from Kick's OAuth server over HTTPS
    2. We're only reading data, not verifying authenticity for auth purposes
    3. The token was obtained through proper OAuth flow with our client secret
    """
    import base64
    import json
    
    try:
        # JWT format: header.payload.signature
        parts = token.split('.')
        if len(parts) != 3:
            print(f"⚠️ Token doesn't look like a JWT (expected 3 parts, got {len(parts)})", flush=True)
            return None
        
        # Decode the payload (second part)
        payload = parts[1]
        # Add padding if needed (JWT base64 doesn't use padding)
        padding = 4 - len(payload) % 4
        if padding != 4:
            payload += '=' * padding
        
        decoded = base64.urlsafe_b64decode(payload)
        user_data = json.loads(decoded)
        print(f"🔓 Decoded JWT payload: {user_data}", flush=True)
        return user_data
    except Exception as e:
        print(f"❌ Failed to decode JWT: {e}", flush=True)
        return None


def get_kick_user_info(access_token):
    """Get user information from Kick OAuth access token."""
    import requests
    
    # First, try to decode the access token as a JWT
    # Many OAuth providers include user info directly in the JWT
    print(f"🔍 Attempting to decode access token as JWT...", flush=True)
    jwt_data = decode_jwt_token(access_token)
    
    if jwt_data:
        # Check if we got username from JWT
        username = None
        user_id = None
        
        # Try different possible fields
        if 'username' in jwt_data:
            username = jwt_data['username']
        elif 'preferred_username' in jwt_data:
            username = jwt_data['preferred_username']
        elif 'name' in jwt_data:
            username = jwt_data['name']
        elif 'slug' in jwt_data:
            username = jwt_data['slug']
        
        # Try to get user ID
        if 'sub' in jwt_data:
            user_id = jwt_data['sub']
        elif 'id' in jwt_data:
            user_id = jwt_data['id']
        elif 'user_id' in jwt_data:
            user_id = jwt_data['user_id']
        
        if username:
            print(f"✅ Extracted username from JWT: {username}", flush=True)
            return {'username': username, 'id': user_id, 'jwt_data': jwt_data}
        else:
            print(f"⚠️ JWT decoded but no username field found. Available fields: {list(jwt_data.keys())}", flush=True)
    
    # If JWT decode didn't work or didn't contain username, try API endpoints
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Accept': 'application/json'
    }
    
    # Try multiple endpoints to find one that works with the OAuth token
    endpoints_to_try = [
        ('OAuth userinfo', KICK_OAUTH_USER_INFO_URL),
        ('API v2 user', 'https://kick.com/api/v2/user'),
        ('API v1 user', 'https://kick.com/api/v1/user'),
        ('API user/me', 'https://kick.com/api/user/me'),
        ('API v2 me', 'https://kick.com/api/v2/me'),
    ]
    
    for name, url in endpoints_to_try:
        try:
            print(f"🔍 Trying {name}: {url}", flush=True)
            response = requests.get(url, headers=headers, timeout=10)
            print(f"📊 {name} response status: {response.status_code}", flush=True)
            
            if response.status_code == 200:
                user_data = response.json()
                print(f"✅ Got user data from {name}: {user_data}", flush=True)
                
                # Try to extract username from various possible fields
                if isinstance(user_data, dict):
                    if 'username' in user_data:
                        return user_data
                    elif 'name' in user_data:
                        return {'username': user_data['name'], 'id': user_data.get('sub') or user_data.get('id')}
                    elif 'preferred_username' in user_data:
                        return {'username': user_data['preferred_username'], 'id': user_data.get('sub') or user_data.get('id')}
                    elif 'slug' in user_data:
                        return {'username': user_data['slug'], 'id': user_data.get('id')}
                    else:
                        # Return whatever we got
                        return user_data
            else:
                print(f"⚠️ {name} returned {response.status_code}: {response.text[:200]}", flush=True)
        except Exception as e:
            print(f"❌ {name} failed: {e}", flush=True)
    
    raise Exception(f"Could not get user info from Kick OAuth. JWT decode didn't contain username and tried {len(endpoints_to_try)} API endpoints.")


def render_success(kick_username):
    """Render success page."""
    return f"""
    <html>
        <head>
            <title>✅ Account Linked!</title>
            <style>
                body {{
                    font-family: Arial, sans-serif;
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    height: 100vh;
                    margin: 0;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                }}
                .container {{
                    text-align: center;
                    padding: 40px;
                    background: rgba(255, 255, 255, 0.1);
                    border-radius: 20px;
                    backdrop-filter: blur(10px);
                    max-width: 500px;
                }}
                h1 {{ margin: 0 0 20px 0; font-size: 48px; }}
                .username {{ 
                    font-size: 24px; 
                    font-weight: bold; 
                    color: #53FC18;
                    margin: 20px 0;
                }}
                p {{ font-size: 18px; line-height: 1.6; }}
                .close-btn {{
                    margin-top: 30px;
                    padding: 12px 30px;
                    background: #53FC18;
                    color: #000;
                    border: none;
                    border-radius: 8px;
                    font-size: 16px;
                    font-weight: bold;
                    cursor: pointer;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>✅</h1>
                <h2>Account Linked Successfully!</h2>
                <div class="username">{kick_username}</div>
                <p>Your Discord account is now linked to your Kick account.</p>
                <p>You can close this window and return to Discord.</p>
                <button class="close-btn" onclick="window.close()">Close Window</button>
            </div>
        </body>
    </html>
    """


def render_error(message):
    """Render error page."""
    return f"""
    <html>
        <head>
            <title>❌ Error</title>
            <style>
                body {{
                    font-family: Arial, sans-serif;
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    height: 100vh;
                    margin: 0;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                }}
                .container {{
                    text-align: center;
                    padding: 40px;
                    background: rgba(255, 255, 255, 0.1);
                    border-radius: 20px;
                    backdrop-filter: blur(10px);
                    max-width: 500px;
                }}
                h1 {{ margin: 0 0 20px 0; font-size: 48px; }}
                .error-message {{ 
                    font-size: 18px; 
                    color: #ff6b6b;
                    margin: 20px 0;
                    padding: 20px;
                    background: rgba(255, 107, 107, 0.1);
                    border-radius: 10px;
                }}
                p {{ font-size: 16px; line-height: 1.6; }}
                .retry-btn {{
                    margin-top: 20px;
                    padding: 12px 30px;
                    background: #53FC18;
                    color: #000;
                    border: none;
                    border-radius: 8px;
                    font-size: 16px;
                    font-weight: bold;
                    cursor: pointer;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>❌</h1>
                <h2>Something Went Wrong</h2>
                <div class="error-message">{message}</div>
                <p>Please return to Discord and try the <code>!linkoauth</code> command again.</p>
                <button class="retry-btn" onclick="window.close()">Close Window</button>
            </div>
        </body>
    </html>
    """, 400


def render_username_form(state, discord_id):
    """Render form for user to input their Kick username."""
    return f"""
    <html>
        <head>
            <title>Enter Your Kick Username</title>
            <style>
                body {{
                    font-family: Arial, sans-serif;
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    min-height: 100vh;
                    margin: 0;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                }}
                .container {{
                    text-align: center;
                    padding: 40px;
                    background: rgba(255, 255, 255, 0.1);
                    border-radius: 20px;
                    backdrop-filter: blur(10px);
                    max-width: 500px;
                }}
                h1 {{ margin: 0 0 10px 0; font-size: 48px; }}
                h2 {{ margin: 0 0 20px 0; }}
                p {{ font-size: 16px; line-height: 1.6; margin-bottom: 30px; }}
                form {{
                    display: flex;
                    flex-direction: column;
                    gap: 15px;
                }}
                input[type="text"] {{
                    padding: 15px;
                    font-size: 16px;
                    border: 2px solid #53FC18;
                    border-radius: 8px;
                    background: rgba(255, 255, 255, 0.9);
                    color: #000;
                }}
                button {{
                    padding: 15px 30px;
                    background: #53FC18;
                    color: #000;
                    border: none;
                    border-radius: 8px;
                    font-size: 18px;
                    font-weight: bold;
                    cursor: pointer;
                }}
                button:hover {{
                    background: #45d914;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>🎮</h1>
                <h2>Enter Your Kick Username</h2>
                <p>We couldn't automatically retrieve your username. Please enter your Kick username below to complete the linking:</p>
                <form method="POST" action="/auth/kick/complete">
                    <input type="hidden" name="state" value="{state}">
                    <input type="hidden" name="discord_id" value="{discord_id}">
                    <input type="text" name="kick_username" placeholder="Your Kick username" required pattern="[a-zA-Z0-9_]+" title="Username can only contain letters, numbers, and underscores">
                    <button type="submit">Link Account</button>
                </form>
            </div>
        </body>
    </html>
    """


@app.route('/auth/kick/complete', methods=['POST'])
def auth_kick_complete():
    """Complete OAuth linking with manual username input."""
    state = request.form.get('state')
    discord_id = request.form.get('discord_id')
    kick_username = request.form.get('kick_username')
    
    print(f"📝 Manual username submission: {kick_username} for Discord {discord_id}", flush=True)
    
    if not state or not discord_id or not kick_username:
        return render_error("Missing required information")
    
    # Verify state still exists in database
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT discord_id FROM oauth_states WHERE state = :state
        """), {"state": state}).fetchone()
    
    if not result or str(result[0]) != str(discord_id):
        return render_error("Invalid or expired session. Please try linking again.")
    
    # Link accounts in database
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO links (discord_id, kick_name)
                VALUES (:d, :k)
                ON CONFLICT(discord_id) DO UPDATE SET kick_name = excluded.kick_name
            """), {"d": int(discord_id), "k": kick_username.lower()})
            
            # Clean up pending bio verifications if any
            conn.execute(text("DELETE FROM pending_links WHERE discord_id = :d"), {"d": int(discord_id)})
            
            # Clean up used OAuth state
            conn.execute(text("DELETE FROM oauth_states WHERE state = :state"), {"state": state})
        
        print(f"✅ Manually linked Discord {discord_id} to Kick {kick_username}", flush=True)
        return render_success(kick_username)
    except Exception as e:
        print(f"❌ Error linking accounts: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return render_error(f"Failed to link accounts: {str(e)}")


def render_error(message):
    """Render error page."""
    return f"""
    <html>
        <head>
            <title>❌ Error</title>
            <style>
                body {{
                    font-family: Arial, sans-serif;
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    min-height: 100vh;
                    margin: 0;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                }}
                .container {{
                    text-align: center;
                    padding: 40px;
                    background: rgba(255, 255, 255, 0.1);
                    border-radius: 20px;
                    backdrop-filter: blur(10px);
                }}
                h1 {{ margin: 0 0 20px 0; font-size: 48px; }}
                p {{ font-size: 18px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>❌</h1>
                <h2>Oops!</h2>
                <p>{message}</p>
            </div>
        </body>
    </html>
    """, 400


if __name__ == '__main__':
    # Use OAUTH_PORT if set, otherwise use PORT, otherwise default to 8000
    # This allows Flask to run on a different port than Railway's main PORT
    port = int(os.getenv('OAUTH_PORT', os.getenv('PORT', 8000)))
    print(f"🚀 Starting OAuth server on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
