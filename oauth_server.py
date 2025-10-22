"""
OAuth Web Server for Kick Authentication
Handles OAuth 2.0 PKCE flow for linking Kick accounts to Discord
"""

import os
import secrets
import hashlib
import base64
import hmac
from flask import Flask, request, redirect, jsonify, render_template_string
from authlib.integrations.requests_client import OAuth2Session
from sqlalchemy import create_engine, text
from datetime import datetime, timezone
from urllib.parse import urlencode

# -------------------------
# 🔒 Security: OAuth Token Signing
# -------------------------
OAUTH_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", secrets.token_hex(32))

# Debug: Log secret key status at startup (don't log the actual key!)
if os.getenv("FLASK_SECRET_KEY"):
    print(f"[OAuth] FLASK_SECRET_KEY loaded: {len(OAUTH_SECRET_KEY)} chars, hash={hash(OAUTH_SECRET_KEY) % 10000}", flush=True)
else:
    print(f"[OAuth] ⚠️ WARNING: FLASK_SECRET_KEY not set, using random key!", flush=True)

def sign_discord_id(discord_id: str, timestamp: int) -> str:
    """
    Create HMAC signature for Discord ID to prevent OAuth initiation spoofing.
    Returns: base64url-encoded signature
    """
    message = f"{discord_id}:{timestamp}"
    signature = hmac.new(
        OAUTH_SECRET_KEY.encode(),
        message.encode(),
        hashlib.sha256
    ).digest()
    return base64.urlsafe_b64encode(signature).decode().rstrip('=')

def verify_discord_id_signature(discord_id: str, timestamp: int, signature: str) -> bool:
    """
    Verify HMAC signature to ensure OAuth was initiated by the bot.
    Returns: True if valid, False otherwise
    """
    # Check timestamp is not too old (max 1 hour)
    now = int(datetime.now(timezone.utc).timestamp())
    age_seconds = abs(now - timestamp)
    if age_seconds > 3600:  # 1 hour expiry
        print(f"⚠️ OAuth signature expired: {age_seconds}s old (max 3600s)", flush=True)
        return False
    
    expected_sig = sign_discord_id(discord_id, timestamp)
    is_valid = hmac.compare_digest(expected_sig, signature)
    
    if not is_valid:
        print(f"🔍 Debug - Signature mismatch:", flush=True)
        print(f"   Discord ID: {discord_id}", flush=True)
        print(f"   Timestamp: {timestamp} (age: {age_seconds}s)", flush=True)
        print(f"   Received sig: {signature}", flush=True)
        print(f"   Expected sig: {expected_sig}", flush=True)
        print(f"   Secret key set: {'Yes' if OAUTH_SECRET_KEY else 'No'}", flush=True)
    
    return is_valid

# -------------------------
# 🔒 OPSEC: Data Sanitization
# -------------------------
def sanitize_for_logs(value, field_name=None):
    """
    Sanitize sensitive data for logging.
    Redacts emails, tokens, codes while keeping debug info.
    """
    if value is None:
        return None
    
    # Sensitive field names to redact
    sensitive_fields = ['email', 'token', 'access_token', 'refresh_token', 'code', 'code_verifier']
    
    # If field name indicates sensitive data, redact
    if field_name and any(s in field_name.lower() for s in sensitive_fields):
        if isinstance(value, str) and len(value) > 8:
            return f"{value[:4]}...{value[-4:]}"
        return "***REDACTED***"
    
    # If value looks like an email, redact
    if isinstance(value, str) and '@' in value:
        parts = value.split('@')
        if len(parts) == 2:
            return f"{parts[0][:2]}***@{parts[1]}"
    
    # If dict, sanitize each field
    if isinstance(value, dict):
        return {k: sanitize_for_logs(v, k) for k, v in value.items()}
    
    # If list, sanitize each item
    if isinstance(value, list):
        return [sanitize_for_logs(item) for item in value]
    
    return value

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", secrets.token_hex(32))

# 404 handler - ignore not found errors (bots/scanners)
@app.errorhandler(404)
def handle_404(e):
    # Silently log but don't spam with full traceback
    print(f"ℹ️ 404: {request.method} {request.path}", flush=True)
    return jsonify({"error": "Not Found"}), 404

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


@app.route('/terms')
@app.route('/terms-of-service')
def terms_of_service():
    """Serve Terms of Service page."""
    try:
        with open('TERMS_OF_SERVICE.md', 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Simple markdown to HTML conversion
        lines = content.split('\n')
        html_parts = []
        
        for line in lines:
            if line.startswith('# '):
                html_parts.append(f'<h1>{line[2:]}</h1>')
            elif line.startswith('## '):
                html_parts.append(f'<h2>{line[3:]}</h2>')
            elif line.startswith('### '):
                html_parts.append(f'<h3>{line[4:]}</h3>')
            elif line.strip():
                # Bold text
                line = line.replace('**', '<strong>', 1)
                line = line.replace('**', '</strong>', 1)
                html_parts.append(f'<p>{line}</p>')
            else:
                html_parts.append('<br>')
        
        html_content = '\n'.join(html_parts)
        
        return f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Terms of Service - Kick Watchtime Bot</title>
            <style>
                * {{ margin: 0; padding: 0; box-sizing: border-box; }}
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                    line-height: 1.6;
                    color: #2c3e50;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    min-height: 100vh;
                    padding: 20px;
                }}
                .container {{
                    max-width: 900px;
                    margin: 0 auto;
                    background: white;
                    padding: 40px;
                    border-radius: 15px;
                    box-shadow: 0 10px 40px rgba(0, 0, 0, 0.2);
                }}
                h1 {{
                    color: #5865F2;
                    font-size: 2.5em;
                    margin-bottom: 20px;
                    padding-bottom: 15px;
                    border-bottom: 3px solid #5865F2;
                }}
                h2 {{
                    color: #2c3e50;
                    font-size: 1.8em;
                    margin-top: 30px;
                    margin-bottom: 15px;
                }}
                h3 {{
                    color: #34495e;
                    font-size: 1.3em;
                    margin-top: 20px;
                    margin-bottom: 10px;
                }}
                p {{
                    margin-bottom: 15px;
                    color: #555;
                }}
                strong {{
                    color: #2c3e50;
                }}
                .footer {{
                    margin-top: 40px;
                    padding-top: 20px;
                    border-top: 2px solid #ecf0f1;
                    text-align: center;
                }}
                .footer a {{
                    color: #5865F2;
                    text-decoration: none;
                    margin: 0 15px;
                    font-weight: 500;
                    transition: color 0.3s;
                }}
                .footer a:hover {{
                    color: #4752c4;
                    text-decoration: underline;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                {html_content}
                <div class="footer">
                    <p>
                        <a href="/privacy">Privacy Policy</a> |
                        <a href="/terms">Terms of Service</a> |
                        <a href="https://github.com/madcats1337/kick-watchtime-bot">GitHub</a>
                    </p>
                    <p style="color: #7f8c8d; font-size: 0.9em; margin-top: 10px;">
                        Kick Watchtime Bot &copy; 2025
                    </p>
                </div>
            </div>
        </body>
        </html>
        """
    except FileNotFoundError:
        return "<h1>Terms of Service</h1><p>Document not found.</p>", 404
    except Exception as e:
        return f"<h1>Error</h1><p>Error loading Terms of Service: {{str(e)}}</p>", 500


@app.route('/privacy')
@app.route('/privacy-policy')
def privacy_policy():
    """Serve Privacy Policy page."""
    try:
        with open('PRIVACY_POLICY.md', 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Simple markdown to HTML conversion
        lines = content.split('\n')
        html_parts = []
        
        for line in lines:
            if line.startswith('# '):
                html_parts.append(f'<h1>{line[2:]}</h1>')
            elif line.startswith('## '):
                html_parts.append(f'<h2>{line[3:]}</h2>')
            elif line.startswith('### '):
                html_parts.append(f'<h3>{line[4:]}</h3>')
            elif line.strip():
                # Bold text
                line = line.replace('**', '<strong>', 1)
                line = line.replace('**', '</strong>', 1)
                html_parts.append(f'<p>{line}</p>')
            else:
                html_parts.append('<br>')
        
        html_content = '\n'.join(html_parts)
        
        return f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Privacy Policy - Kick Watchtime Bot</title>
            <style>
                * {{ margin: 0; padding: 0; box-sizing: border-box; }}
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                    line-height: 1.6;
                    color: #2c3e50;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    min-height: 100vh;
                    padding: 20px;
                }}
                .container {{
                    max-width: 900px;
                    margin: 0 auto;
                    background: white;
                    padding: 40px;
                    border-radius: 15px;
                    box-shadow: 0 10px 40px rgba(0, 0, 0, 0.2);
                }}
                h1 {{
                    color: #5865F2;
                    font-size: 2.5em;
                    margin-bottom: 20px;
                    padding-bottom: 15px;
                    border-bottom: 3px solid #5865F2;
                }}
                h2 {{
                    color: #2c3e50;
                    font-size: 1.8em;
                    margin-top: 30px;
                    margin-bottom: 15px;
                }}
                h3 {{
                    color: #34495e;
                    font-size: 1.3em;
                    margin-top: 20px;
                    margin-bottom: 10px;
                }}
                p {{
                    margin-bottom: 15px;
                    color: #555;
                }}
                strong {{
                    color: #2c3e50;
                }}
                .footer {{
                    margin-top: 40px;
                    padding-top: 20px;
                    border-top: 2px solid #ecf0f1;
                    text-align: center;
                }}
                .footer a {{
                    color: #5865F2;
                    text-decoration: none;
                    margin: 0 15px;
                    font-weight: 500;
                    transition: color 0.3s;
                }}
                .footer a:hover {{
                    color: #4752c4;
                    text-decoration: underline;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                {html_content}
                <div class="footer">
                    <p>
                        <a href="/privacy">Privacy Policy</a> |
                        <a href="/terms">Terms of Service</a> |
                        <a href="https://github.com/madcats1337/kick-watchtime-bot">GitHub</a>
                    </p>
                    <p style="color: #7f8c8d; font-size: 0.9em; margin-top: 10px;">
                        Kick Watchtime Bot &copy; 2025
                    </p>
                </div>
            </div>
        </body>
        </html>
        """
    except FileNotFoundError:
        return "<h1>Privacy Policy</h1><p>Document not found.</p>", 404
    except Exception as e:
        return f"<h1>Error</h1><p>Error loading Privacy Policy: {{str(e)}}</p>", 500


@app.route('/auth/kick')
def auth_kick():
    """
    Initiate Kick OAuth flow.
    Query params: discord_id (required), timestamp (required), signature (required)
    
    🔒 Security: Requires cryptographic signature to prevent OAuth initiation spoofing.
    Only URLs generated by the Discord bot will have valid signatures.
    """
    discord_id = request.args.get('discord_id')
    timestamp_str = request.args.get('timestamp')
    signature = request.args.get('signature')
    
    if not discord_id or not timestamp_str or not signature:
        return "❌ Missing required parameters (discord_id, timestamp, signature)", 400
    
    try:
        timestamp = int(timestamp_str)
    except ValueError:
        return "❌ Invalid timestamp format", 400
    
    # 🔒 SECURITY: Verify signature to ensure request came from Discord bot
    if not verify_discord_id_signature(discord_id, timestamp, signature):
        print(f"🚨 SECURITY: Invalid OAuth signature for Discord ID {discord_id}", flush=True)
        return "❌ Invalid or expired authentication token. Please use the !link command in Discord to generate a new link.", 403
    
    if not KICK_CLIENT_ID or not KICK_CLIENT_SECRET:
        return "❌ OAuth not configured. Please set KICK_CLIENT_ID and KICK_CLIENT_SECRET.", 500
    
    print(f"✅ Valid OAuth signature for Discord ID: {discord_id}", flush=True)
    
    # Generate PKCE pair
    code_verifier, code_challenge = generate_pkce_pair()
    
    # Generate state for CSRF protection
    state = secrets.token_urlsafe(32)
    print(f"🔑 Generated new state for Discord ID: {discord_id}", flush=True)
    
    # Store state in database (survives across Gunicorn workers)
    with engine.begin() as conn:
        # Clean up old states (older than 30 minutes)
        deleted_count = conn.execute(text("""
            DELETE FROM oauth_states 
            WHERE created_at < CURRENT_TIMESTAMP - INTERVAL '30 minutes'
        """)).rowcount
        print(f"🧹 Cleaned up {deleted_count} expired state(s)", flush=True)
        
        # Store new state
        conn.execute(text("""
            INSERT INTO oauth_states (state, discord_id, code_verifier, created_at)
            VALUES (:state, :discord_id, :code_verifier, CURRENT_TIMESTAMP)
        """), {"state": state, "discord_id": int(discord_id), "code_verifier": code_verifier})
        print(f"✅ State saved to database", flush=True)
    
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
    print(f"🔔 Callback received!", flush=True)
    
    code = request.args.get('code')
    state = request.args.get('state')
    error = request.args.get('error')
    
    print(f"📥 Code: {sanitize_for_logs(code, 'code')}, State: {sanitize_for_logs(state, 'state')}, Error: {error}", flush=True)
    
    if error:
        print(f"❌ Kick returned error: {error}", flush=True)
        return render_error(f"Kick authorization failed: {error}")
    
    if not code or not state:
        print(f"❌ Missing code or state", flush=True)
        return render_error("Missing authorization code or state")
    
    # Verify state from database
    print(f"🔍 Checking state in database...", flush=True)
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT discord_id, code_verifier, created_at FROM oauth_states WHERE state = :state
        """), {"state": state}).fetchone()
    
    if not result:
        print(f"❌ State not found or expired", flush=True)
        
        # Debug: Check if state exists at all and show recent states
        with engine.connect() as conn:
            count = conn.execute(text("SELECT COUNT(*) FROM oauth_states")).fetchone()[0]
            recent_states = conn.execute(text("""
                SELECT state, discord_id, created_at 
                FROM oauth_states 
                ORDER BY created_at DESC 
                LIMIT 5
            """)).fetchall()
            print(f"📊 Total states in database: {count}", flush=True)
            print(f"📋 Recent states:", flush=True)
            for s in recent_states:
                # 🔒 OPSEC: Sanitize state tokens in debug output
                print(f"   - State: {sanitize_for_logs(s[0], 'state')}, Discord ID: {s[1]}, Created: {s[2]}", flush=True)
        return render_error("Invalid or expired state. Please try linking again. The link expires after 30 minutes.")
    
    discord_id = result[0]
    code_verifier = result[1]
    created_at = result[2]
    
    print(f"✅ State valid, Discord ID: {discord_id}, Created: {created_at}", flush=True)
    
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
            # 🔒 OPSEC: Sanitize user info before logging
            print(f"📊 Got user info: {sanitize_for_logs(kick_user)}", flush=True)
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
                # Store failed attempt for logging
                conn.execute(text("""
                    INSERT INTO oauth_notifications (discord_id, kick_username, processed)
                    VALUES (:d, :k, FALSE)
                """), {"d": discord_id, "k": f"FAILED:{kick_username}:already_linked"})
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
            # 🔒 OPSEC: Sanitize user data before logging
            print(f"✅ Got user data: {sanitize_for_logs(data)}", flush=True)
            
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
