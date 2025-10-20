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
        token_data = exchange_code_for_token(code, code_verifier=code_verifier)
        access_token = token_data.get('access_token')
        
        if not access_token:
            return render_error("Failed to obtain access token from Kick")
        
        print(f"✅ Got access token", flush=True)
        
        # Get user info from Kick's public API
        try:
            kick_user = get_kick_user_info(access_token)
            print(f"📊 Got user info: {kick_user}", flush=True)
        except Exception as e:
            print(f"❌ Failed to get user info: {e}", flush=True)
            return render_error(f"Failed to get your Kick username: {str(e)}")
        
        if not kick_user or not kick_user.get('username'):
            return render_error("Could not retrieve your Kick username. Please try again.")
        
        kick_username = kick_user['username']
        print(f"👤 Kick username: {kick_username}", flush=True)
        
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
            
            # Update existing notification with kick_username (was created when !link command was used)
            # If no existing notification exists, create a new one
            result = conn.execute(text("""
                UPDATE oauth_notifications 
                SET kick_username = :k, processed = FALSE
                WHERE discord_id = :d AND kick_username = ''
                RETURNING id
            """), {"d": discord_id, "k": kick_username}).fetchone()
            
            # If no pending notification found, create new one
            if not result:
                conn.execute(text("""
                    INSERT INTO oauth_notifications (discord_id, kick_username)
                    VALUES (:d, :k)
                """), {"d": discord_id, "k": kick_username})
        
        print(f"✅ OAuth link successful: Discord {discord_id} -> Kick {kick_username}", flush=True)
        return render_success(kick_username, discord_id)
        
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


def get_kick_user_info(access_token):
    """Get user information from Kick OAuth access token.
    
    Uses Kick's public API endpoint that works with OAuth Bearer tokens.
    Reference: https://arcticjs.dev/providers/kick
    """
    import requests
    
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Accept': 'application/json'
    }
    
    try:
        # Use Kick's public API endpoint (documented in Arctic.js OAuth library)
        print(f"🔍 Getting user info from Kick public API...", flush=True)
        response = requests.get('https://api.kick.com/public/v1/users', headers=headers, timeout=10)
        
        print(f"📊 Response status: {response.status_code}", flush=True)
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Got user data: {data}", flush=True)
            
            # Kick's API returns: {"data": [{"user_id": ..., "name": "...", "email": "..."}], "message": "OK"}
            if 'data' in data and isinstance(data['data'], list) and len(data['data']) > 0:
                user = data['data'][0]
                return {
                    'username': user.get('name'),
                    'id': user.get('user_id'),
                    'email': user.get('email'),
                    'profile_picture': user.get('profile_picture')
                }
        
        # If we get here, the API didn't return expected data
        print(f"⚠️ Unexpected response format: {response.text[:200]}", flush=True)
        raise Exception(f"Kick API returned status {response.status_code}")
        
    except Exception as e:
        print(f"❌ Failed to get user info: {e}", flush=True)
        raise Exception(f"Could not get user info from Kick API: {str(e)}")


def render_success(kick_username, discord_id):
    """Render success page with auto-close."""
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
            <script>
                // Try to close window immediately
                function tryClose() {{
                    window.close();
                    // If we're still here after 100ms, the close was blocked
                    setTimeout(function() {{
                        // Check if window is still open (it will be if close was blocked)
                        document.getElementById('manualClose').style.display = 'block';
                        document.getElementById('autoClose').style.display = 'none';
                    }}, 100);
                }}
                // Try to close after page loads
                window.onload = function() {{
                    setTimeout(tryClose, 2000);
                }};
            </script>
        </head>
        <body>
            <div class="container">
                <h1>✅</h1>
                <h2>Account Linked Successfully!</h2>
                <div class="username">{kick_username}</div>
                <p>Your Discord account is now linked to your Kick account.</p>
                <p id="autoClose">Window will close automatically...</p>
                <p id="manualClose" style="display:none;">You can now close this tab and return to Discord.</p>
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
