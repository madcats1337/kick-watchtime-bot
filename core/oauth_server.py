"""
OAuth Web Server for Kick Authentication
Handles OAuth 2.0 PKCE flow for linking Kick accounts to Discord

Now includes official Kick API integration with:
- User account linking (user:read scope)
- Bot chat messaging (chat:write scope)  
- Webhook subscriptions (events:subscribe scope)
- Stream notifications
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

# Import webhook handlers
try:
    from .kick_webhooks import register_webhook_routes, WebhookEventHandler
    from .kick_official_api import KickOfficialAPI, OAUTH_SCOPES, WEBHOOK_EVENTS
    HAS_KICK_OFFICIAL = True
except ImportError:
    HAS_KICK_OFFICIAL = False
    register_webhook_routes = None
    WebhookEventHandler = None

# -------------------------
# 🔒 Security: OAuth Token Signing
# -------------------------
OAUTH_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", secrets.token_hex(32))

# Debug: Log secret key status at startup (don't log the actual key!)
if os.getenv("FLASK_SECRET_KEY"):
    print(f"[OAuth] FLASK_SECRET_KEY loaded: {len(OAUTH_SECRET_KEY)} chars, hash={hash(OAUTH_SECRET_KEY) % 10000}", flush=True)
else:
    print(f"[OAuth] WARNING: FLASK_SECRET_KEY not set, using random key!", flush=True)

def sign_discord_id(discord_id: str, timestamp: int, guild_id: str = "0") -> str:
    """
    Create HMAC signature for Discord ID to prevent OAuth initiation spoofing.
    Returns: base64url-encoded signature
    """
    message = f"{discord_id}:{guild_id}:{timestamp}"
    signature = hmac.new(
        OAUTH_SECRET_KEY.encode(),
        message.encode(),
        hashlib.sha256
    ).digest()
    return base64.urlsafe_b64encode(signature).decode().rstrip('=')

def verify_discord_id_signature(discord_id: str, timestamp: int, signature: str, guild_id: str = "0") -> bool:
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
    
    expected_sig = sign_discord_id(discord_id, timestamp, guild_id)
    is_valid = hmac.compare_digest(expected_sig, signature)
    
    if not is_valid:
        print(f"🔍 Debug - Signature mismatch:", flush=True)
        print(f"   Discord ID: {discord_id}", flush=True)
        print(f"   Guild ID: {guild_id}", flush=True)
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

# Register Kick webhook routes if available
if HAS_KICK_OFFICIAL and register_webhook_routes:
    # Create event handler (can be customized later)
    webhook_handler = WebhookEventHandler()
    
    @webhook_handler.set_default_handler
    def default_webhook_handler(event_data):
        """Default handler logs all events"""
        import json
        print(f"[Webhook] Received event data: {json.dumps(event_data, indent=2, default=str)}")
    
    register_webhook_routes(app, webhook_handler)
    print("[OAuth] ✅ Kick webhook routes registered")
else:
    print("[OAuth] ℹ️ Kick webhook routes not available")

# 404 handler - ignore not found errors (bots/scanners)
@app.errorhandler(404)
def handle_404(e):
    # Silently log but don't spam with full traceback
    print(f"ℹ️ 404: {request.method} {request.path}", flush=True)
    return jsonify({"error": "Not Found"}), 404

# 405 handler - method not allowed (wrong HTTP method)
@app.errorhandler(405)
def handle_405(e):
    # Log method not allowed errors without full traceback
    print(f"ℹ️ 405 Method Not Allowed: {request.method} {request.path}", flush=True)
    print(f"   Allowed methods: {e.valid_methods}", flush=True)
    return jsonify({
        "error": "Method Not Allowed",
        "message": f"The method {request.method} is not allowed for this endpoint",
        "allowed_methods": list(e.valid_methods)
    }), 405

# Global error handler
@app.errorhandler(Exception)
def handle_error(e):
    print(f"🚨 Unhandled error: {e}", flush=True)
    import traceback
    traceback.print_exc()
    return jsonify({"error": str(e), "type": type(e).__name__}), 500

# -------------------------
# 🎬 Clip Serving Endpoint
# -------------------------
from flask import send_from_directory
from pathlib import Path

CLIPS_DIR = Path("clips")
CLIPS_DIR.mkdir(exist_ok=True)

@app.route('/clips/<filename>')
def serve_clip(filename):
    """Serve clip files from the clips directory"""
    # Security: only allow .mp4 files and prevent path traversal
    if not filename.endswith('.mp4') or '..' in filename or '/' in filename:
        return jsonify({"error": "Invalid filename"}), 400
    
    filepath = CLIPS_DIR / filename
    if not filepath.exists():
        return jsonify({"error": "Clip not found"}), 404
    
    return send_from_directory(CLIPS_DIR, filename, mimetype='video/mp4')

@app.route('/clips')
def list_clips():
    """List available clips"""
    clips = []
    for filepath in sorted(CLIPS_DIR.glob("clip_*.mp4"), reverse=True)[:50]:
        stat = filepath.stat()
        clips.append({
            'filename': filepath.name,
            'url': f"/clips/{filepath.name}",
            'size_mb': round(stat.st_size / 1024 / 1024, 2),
            'created': datetime.fromtimestamp(stat.st_mtime).isoformat()
        })
    return jsonify(clips)

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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            guild_id BIGINT DEFAULT 0
        )
    """))
    
    # Add guild_id column if it doesn't exist (migration)
    try:
        conn.execute(text("""
            ALTER TABLE oauth_states ADD COLUMN IF NOT EXISTS guild_id BIGINT DEFAULT 0
        """))
    except Exception:
        pass  # Column already exists or database doesn't support IF NOT EXISTS
    
    # Create bot_tokens table for securely storing bot access tokens
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS bot_tokens (
            bot_username TEXT PRIMARY KEY,
            access_token TEXT NOT NULL,
            refresh_token TEXT,
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


@app.route('/api/status')
def api_status():
    """
    Get detailed API status including official Kick API availability.
    """
    status = {
        "status": "healthy",
        "oauth_configured": bool(KICK_CLIENT_ID and KICK_CLIENT_SECRET),
        "official_api_available": HAS_KICK_OFFICIAL,
        "webhook_secret_configured": bool(os.getenv("KICK_WEBHOOK_SECRET")),
        "available_scopes": OAUTH_SCOPES if HAS_KICK_OFFICIAL else [],
        "available_webhook_events": WEBHOOK_EVENTS if HAS_KICK_OFFICIAL else [],
        "endpoints": {
            "oauth_authorize": "/auth/kick",
            "oauth_callback": "/auth/kick/callback",
            "bot_authorize": "/bot/authorize",
            "webhooks": "/webhooks/kick",
            "webhook_subscriptions": "/api/webhooks",
        }
    }
    return jsonify(status), 200


@app.route('/api/webhooks', methods=['GET'])
def list_webhook_subscriptions():
    """
    List all active webhook subscriptions.
    Requires bot access token.
    """
    auth_header = request.headers.get('Authorization', '')
    
    if not auth_header.startswith('Bearer '):
        return jsonify({"error": "Missing or invalid Authorization header"}), 401
    
    access_token = auth_header.replace('Bearer ', '')
    
    if not HAS_KICK_OFFICIAL:
        return jsonify({"error": "Official Kick API not available"}), 503
    
    try:
        import asyncio
        
        async def get_subscriptions():
            api = KickOfficialAPI(
                client_id=KICK_CLIENT_ID,
                client_secret=KICK_CLIENT_SECRET,
                access_token=access_token,
            )
            try:
                subs = await api.get_webhook_subscriptions()
                return [s.__dict__ if hasattr(s, '__dict__') else s for s in subs]
            finally:
                await api.close()
        
        loop = asyncio.new_event_loop()
        try:
            subscriptions = loop.run_until_complete(get_subscriptions())
        finally:
            loop.close()
        
        return jsonify({"subscriptions": subscriptions}), 200
        
    except Exception as e:
        print(f"[API] Error listing webhooks: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/webhooks', methods=['POST'])
def create_webhook_subscription():
    """
    Create a new webhook subscription.
    
    Requires:
    - Authorization: Bearer <access_token>
    - JSON body: { "event": "channel.subscription.gifts", "callback_url": "https://..." }
    """
    auth_header = request.headers.get('Authorization', '')
    
    if not auth_header.startswith('Bearer '):
        return jsonify({"error": "Missing or invalid Authorization header"}), 401
    
    access_token = auth_header.replace('Bearer ', '')
    
    if not HAS_KICK_OFFICIAL:
        return jsonify({"error": "Official Kick API not available"}), 503
    
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400
    
    event = data.get('event')
    callback_url = data.get('callback_url')
    broadcaster_user_id = data.get('broadcaster_user_id')
    
    if not event or not callback_url:
        return jsonify({"error": "event and callback_url are required"}), 400
    
    try:
        import asyncio
        
        async def subscribe():
            api = KickOfficialAPI(
                client_id=KICK_CLIENT_ID,
                client_secret=KICK_CLIENT_SECRET,
                access_token=access_token,
            )
            try:
                sub = await api.subscribe_webhook(
                    event=event,
                    callback_url=callback_url,
                    broadcaster_user_id=broadcaster_user_id,
                )
                return sub.__dict__ if hasattr(sub, '__dict__') else sub
            finally:
                await api.close()
        
        loop = asyncio.new_event_loop()
        try:
            subscription = loop.run_until_complete(subscribe())
        finally:
            loop.close()
        
        return jsonify({"subscription": subscription}), 201
        
    except Exception as e:
        print(f"[API] Error creating webhook: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/webhooks/<subscription_id>', methods=['DELETE'])
def delete_webhook_subscription(subscription_id):
    """
    Delete a webhook subscription.
    Requires Authorization: Bearer <access_token>
    """
    auth_header = request.headers.get('Authorization', '')
    
    if not auth_header.startswith('Bearer '):
        return jsonify({"error": "Missing or invalid Authorization header"}), 401
    
    access_token = auth_header.replace('Bearer ', '')
    
    if not HAS_KICK_OFFICIAL:
        return jsonify({"error": "Official Kick API not available"}), 503
    
    try:
        import asyncio
        
        async def delete():
            api = KickOfficialAPI(
                client_id=KICK_CLIENT_ID,
                client_secret=KICK_CLIENT_SECRET,
                access_token=access_token,
            )
            try:
                return await api.delete_webhook_subscription(subscription_id)
            finally:
                await api.close()
        
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(delete())
        finally:
            loop.close()
        
        return jsonify({"status": "deleted", "id": subscription_id}), 200
        
    except Exception as e:
        print(f"[API] Error deleting webhook: {e}")
        return jsonify({"error": str(e)}), 500


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
            <link rel="preconnect" href="https://fonts.googleapis.com">
            <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
            <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
            <style>
                * {{ margin: 0; padding: 0; box-sizing: border-box; }}
                :root {{
                    --background: #1a2332;
                    --foreground: #f9fafb;
                    --card: #242d3d;
                    --card-foreground: #f9fafb;
                    --primary: #3b82f6;
                    --primary-foreground: #f9fafb;
                    --muted: #374151;
                    --muted-foreground: #9ca3af;
                    --border: #374151;
                    --radius: 0.625rem;
                }}
                body {{
                    font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                    line-height: 1.6;
                    color: var(--foreground);
                    background: var(--background);
                    min-height: 100vh;
                    padding: 20px;
                    -webkit-font-smoothing: antialiased;
                    -moz-osx-font-smoothing: grayscale;
                }}
                .container {{
                    max-width: 900px;
                    margin: 0 auto;
                    background: var(--card);
                    padding: 48px;
                    border-radius: var(--radius);
                    box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.3), 0 10px 10px -5px rgba(0, 0, 0, 0.2);
                    border: 1px solid var(--border);
                }}
                h1 {{
                    color: var(--foreground);
                    font-size: 2.5em;
                    font-weight: 700;
                    margin-bottom: 24px;
                    padding-bottom: 16px;
                    border-bottom: 2px solid var(--primary);
                    letter-spacing: -0.025em;
                }}
                h2 {{
                    color: var(--foreground);
                    font-size: 1.8em;
                    font-weight: 600;
                    margin-top: 36px;
                    margin-bottom: 16px;
                    letter-spacing: -0.015em;
                }}
                h3 {{
                    color: var(--card-foreground);
                    font-size: 1.4em;
                    font-weight: 600;
                    margin-top: 24px;
                    margin-bottom: 12px;
                }}
                p {{
                    margin-bottom: 16px;
                    color: var(--muted-foreground);
                    font-size: 1em;
                }}
                strong {{
                    color: var(--foreground);
                    font-weight: 600;
                }}
                .footer {{
                    margin-top: 48px;
                    padding-top: 24px;
                    border-top: 1px solid var(--border);
                    text-align: center;
                }}
                .footer a {{
                    color: var(--primary);
                    text-decoration: none;
                    margin: 0 16px;
                    font-weight: 500;
                    transition: all 0.2s ease;
                }}
                .footer a:hover {{
                    color: #60a5fa;
                    text-decoration: underline;
                }}
                .footer p {{
                    color: var(--muted-foreground);
                }}
                @media (max-width: 768px) {{
                    .container {{
                        padding: 32px 24px;
                    }}
                    h1 {{
                        font-size: 2em;
                    }}
                    h2 {{
                        font-size: 1.5em;
                    }}
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
                    <p style="font-size: 0.9em; margin-top: 12px;">
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
            <link rel="preconnect" href="https://fonts.googleapis.com">
            <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
            <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
            <style>
                * {{ margin: 0; padding: 0; box-sizing: border-box; }}
                :root {{
                    --background: #1a2332;
                    --foreground: #f9fafb;
                    --card: #242d3d;
                    --card-foreground: #f9fafb;
                    --primary: #3b82f6;
                    --primary-foreground: #f9fafb;
                    --muted: #374151;
                    --muted-foreground: #9ca3af;
                    --border: #374151;
                    --radius: 0.625rem;
                }}
                body {{
                    font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                    line-height: 1.6;
                    color: var(--foreground);
                    background: var(--background);
                    min-height: 100vh;
                    padding: 20px;
                    -webkit-font-smoothing: antialiased;
                    -moz-osx-font-smoothing: grayscale;
                }}
                .container {{
                    max-width: 900px;
                    margin: 0 auto;
                    background: var(--card);
                    padding: 48px;
                    border-radius: var(--radius);
                    box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.3), 0 10px 10px -5px rgba(0, 0, 0, 0.2);
                    border: 1px solid var(--border);
                }}
                h1 {{
                    color: var(--foreground);
                    font-size: 2.5em;
                    font-weight: 700;
                    margin-bottom: 24px;
                    padding-bottom: 16px;
                    border-bottom: 2px solid var(--primary);
                    letter-spacing: -0.025em;
                }}
                h2 {{
                    color: var(--foreground);
                    font-size: 1.8em;
                    font-weight: 600;
                    margin-top: 36px;
                    margin-bottom: 16px;
                    letter-spacing: -0.015em;
                }}
                h3 {{
                    color: var(--card-foreground);
                    font-size: 1.4em;
                    font-weight: 600;
                    margin-top: 24px;
                    margin-bottom: 12px;
                }}
                p {{
                    margin-bottom: 16px;
                    color: var(--muted-foreground);
                    font-size: 1em;
                }}
                strong {{
                    color: var(--foreground);
                    font-weight: 600;
                }}
                .footer {{
                    margin-top: 48px;
                    padding-top: 24px;
                    border-top: 1px solid var(--border);
                    text-align: center;
                }}
                .footer a {{
                    color: var(--primary);
                    text-decoration: none;
                    margin: 0 16px;
                    font-weight: 500;
                    transition: all 0.2s ease;
                }}
                .footer a:hover {{
                    color: #60a5fa;
                    text-decoration: underline;
                }}
                .footer p {{
                    color: var(--muted-foreground);
                }}
                @media (max-width: 768px) {{
                    .container {{
                        padding: 32px 24px;
                    }}
                    h1 {{
                        font-size: 2em;
                    }}
                    h2 {{
                        font-size: 1.5em;
                    }}
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
                    <p style="font-size: 0.9em; margin-top: 12px;">
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
    Query params: discord_id (required), guild_id (optional), timestamp (required), signature (required)
    
    🔒 Security: Requires cryptographic signature to prevent OAuth initiation spoofing.
    Only URLs generated by the Discord bot will have valid signatures.
    """
    discord_id = request.args.get('discord_id')
    guild_id = request.args.get('guild_id', '0')  # Default to 0 if not provided (for backwards compatibility)
    timestamp_str = request.args.get('timestamp')
    signature = request.args.get('signature')
    
    if not discord_id or not timestamp_str or not signature:
        return "❌ Missing required parameters (discord_id, timestamp, signature)", 400
    
    try:
        timestamp = int(timestamp_str)
    except ValueError:
        return "❌ Invalid timestamp format", 400
    
    # 🔒 SECURITY: Verify signature to ensure request came from Discord bot
    if not verify_discord_id_signature(discord_id, timestamp, signature, guild_id):
        print(f"🚨 SECURITY: Invalid OAuth signature for Discord ID {discord_id}, Guild ID {guild_id}", flush=True)
        return "❌ Invalid or expired authentication token. Please use the !link command in Discord to generate a new link.", 403
    
    if not KICK_CLIENT_ID or not KICK_CLIENT_SECRET:
        return "❌ OAuth not configured. Please set KICK_CLIENT_ID and KICK_CLIENT_SECRET.", 500
    
    print(f"✅ Valid OAuth signature for Discord ID: {discord_id}, Guild ID: {guild_id}", flush=True)
    
    # Generate PKCE pair
    code_verifier, code_challenge = generate_pkce_pair()
    
    # Generate state for CSRF protection
    state = secrets.token_urlsafe(32)
    print(f"🔑 Generated new state for Discord ID: {discord_id}, Guild ID: {guild_id}", flush=True)
    
    # Store state in database (survives across Gunicorn workers)
    with engine.begin() as conn:
        # Clean up old states (older than 30 minutes)
        deleted_count = conn.execute(text("""
            DELETE FROM oauth_states 
            WHERE created_at < CURRENT_TIMESTAMP - INTERVAL '30 minutes'
        """)).rowcount
        print(f"🧹 Cleaned up {deleted_count} expired state(s)", flush=True)
        
        # Store new state with guild_id
        conn.execute(text("""
            INSERT INTO oauth_states (state, discord_id, code_verifier, created_at, guild_id)
            VALUES (:state, :discord_id, :code_verifier, CURRENT_TIMESTAMP, :guild_id)
        """), {"state": state, "discord_id": int(discord_id), "code_verifier": code_verifier, "guild_id": int(guild_id)})
        print(f"✅ State saved to database with guild_id: {guild_id}", flush=True)
    
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
    """Handle OAuth callback from Kick (supports both user linking and bot authorization)."""
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
            SELECT discord_id, code_verifier, created_at, guild_id FROM oauth_states WHERE state = :state
        """), {"state": state}).fetchone()
    
    if not result:
        print(f"❌ State not found or expired", flush=True)
        
        # Debug: Check if state exists at all and show recent states
        with engine.connect() as conn:
            count = conn.execute(text("SELECT COUNT(*) FROM oauth_states")).fetchone()[0]
            recent_states = conn.execute(text("""
                SELECT state, discord_id, created_at, guild_id
                FROM oauth_states 
                ORDER BY created_at DESC 
                LIMIT 5
            """)).fetchall()
            print(f"📊 Total states in database: {count}", flush=True)
            print(f"📋 Recent states:", flush=True)
            for s in recent_states:
                # 🔒 OPSEC: Sanitize state tokens in debug output
                print(f"   - State: {sanitize_for_logs(s[0], 'state')}, Discord ID: {s[1]}, Created: {s[2]}, Guild ID: {s[3] if len(s) > 3 else 0}", flush=True)
        return render_error("Invalid or expired state. Please try linking again. The link expires after 30 minutes.")
    
    discord_id = result[0]
    code_verifier = result[1]
    created_at = result[2]
    guild_id = result[3] if len(result) > 3 else 0  # Default to 0 for backwards compatibility
    
    print(f"✅ State valid, Discord ID: {discord_id}, Guild ID: {guild_id}, Created: {created_at}", flush=True)
    
    # Check if this is a bot authorization (discord_id == 0) or regular user linking
    if discord_id == 0:
        print(f"🤖 Detected bot authorization flow", flush=True)
        return handle_bot_authorization_callback(code, code_verifier, state)
    else:
        print(f"👤 Detected user linking flow", flush=True)
        return handle_user_linking_callback(code, code_verifier, state, discord_id, created_at, guild_id)


def handle_bot_authorization_callback(code, code_verifier, state):
    """Handle bot authorization callback."""
    try:
        # Ensure bot_tokens table exists with expires_at column
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS bot_tokens (
                    bot_username TEXT PRIMARY KEY,
                    access_token TEXT NOT NULL,
                    refresh_token TEXT,
                    expires_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
        
        # Exchange code for access token
        print(f"🔄 Exchanging code for bot token...", flush=True)
        token_data = exchange_code_for_token(code, code_verifier=code_verifier)
        access_token = token_data.get('access_token')
        expires_in = token_data.get('expires_in', 3600)  # Default to 1 hour if not provided
        
        if not access_token:
            print(f"❌ No access token in response: {list(token_data.keys())}", flush=True)
            return render_error("Failed to obtain access token from Kick")
        
        print(f"✅ Got bot access token (expires in {expires_in} seconds)", flush=True)
        
        # Get bot user info
        try:
            kick_user = get_kick_user_info(access_token)
            kick_username = kick_user.get('username', 'Unknown')
            print(f"🤖 Bot username: {kick_username}", flush=True)
        except Exception as e:
            print(f"⚠️ Could not get bot user info: {e}", flush=True)
            kick_username = "Unknown"
        
        # Store token in database with expiration time
        # Calculate expiration time in Python (works with both SQLite and PostgreSQL)
        from datetime import datetime, timedelta, timezone
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        
        with engine.begin() as conn:
            conn.execute(text("""
                DELETE FROM bot_tokens WHERE bot_username = :username
            """), {"username": kick_username})
            
            conn.execute(text("""
                INSERT INTO bot_tokens (bot_username, access_token, refresh_token, expires_at, created_at)
                VALUES (:username, :access_token, :refresh_token, :expires_at, CURRENT_TIMESTAMP)
            """), {
                "username": kick_username,
                "access_token": access_token,
                "refresh_token": token_data.get('refresh_token', ''),
                "expires_at": expires_at
            })
            
            # Clean up state
            conn.execute(text("DELETE FROM oauth_states WHERE state = :state"), {"state": state})
            
            print(f"✅ Bot token stored securely", flush=True)
        
        # Return success page
        return f"""
        <html>
            <head>
                <title>Bot Authorized</title>
                <style>
                    body {{
                        font-family: Arial, sans-serif;
                        padding: 40px;
                        max-width: 800px;
                        margin: 0 auto;
                        background: #f5f5f5;
                    }}
                    .container {{
                        background: white;
                        padding: 30px;
                        border-radius: 10px;
                        box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                    }}
                    h1 {{ color: #53fc18; }}
                    .instructions {{
                        background: #e3f2fd;
                        padding: 15px;
                        border-radius: 5px;
                        margin-top: 20px;
                    }}
                    .command {{
                        background: #2d2d2d;
                        color: #f8f8f2;
                        padding: 15px;
                        border-radius: 5px;
                        font-family: monospace;
                        margin: 15px 0;
                        overflow-x: auto;
                    }}
                    code {{
                        background: #f0f0f0;
                        padding: 2px 6px;
                        border-radius: 3px;
                        font-family: monospace;
                    }}
                    .success {{
                        background: #d4edda;
                        padding: 15px;
                        border-radius: 5px;
                        border-left: 4px solid #28a745;
                        margin-bottom: 20px;
                    }}
                </style>
            </head>
            <body>
                <div class="container">
                    <h1>✅ Bot Successfully Authorized!</h1>
                    
                    <div class="success">
                        <strong>Bot Account:</strong> {kick_username}<br>
                        <strong>Status:</strong> Token stored securely in database
                    </div>
                    
                    <div class="instructions">
                        <h3>📋 Next Steps:</h3>
                        <p><strong>Run this command locally to retrieve the token:</strong></p>
                        <div class="command">python get_bot_token_from_db.py</div>
                        
                        <p>This script will:</p>
                        <ol>
                            <li>Connect to your database securely</li>
                            <li>Retrieve the bot token for {kick_username}</li>
                            <li>Display it in your local terminal only</li>
                        </ol>
                        
                        <p><strong>Then add it to Railway:</strong></p>
                        <ol>
                            <li>Copy the token from your terminal</li>
                            <li>Go to Railway project settings</li>
                            <li>Add environment variable: <code>KICK_BOT_USER_TOKEN</code></li>
                            <li>Paste the token as the value</li>
                            <li>Redeploy your bot</li>
                        </ol>
                    </div>
                    
                    <p style="margin-top: 30px; color: #666; font-size: 14px;">
                        🔒 For security, the token is not displayed in your browser.<br>
                        It's stored in your database and can only be retrieved using the script above.
                    </p>
                </div>
            </body>
        </html>
        """
    
    except Exception as e:
        print(f"❌ Bot authorization error: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return render_error(f"Bot authorization failed: {str(e)}")


def handle_user_linking_callback(code, code_verifier, state, discord_id, created_at, guild_id=0):
    """Handle regular user linking callback."""
    
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
        
        # Check if Kick account is already linked to another Discord user on this server
        with engine.connect() as conn:
            existing = conn.execute(text(
                "SELECT discord_id FROM links WHERE kick_name = :k AND discord_server_id = :gid"
            ), {"k": kick_username.lower(), "gid": guild_id}).fetchone()
            
            if existing and existing[0] != discord_id:
                # Store failed attempt for logging
                conn.execute(text("""
                    INSERT INTO oauth_notifications (discord_id, kick_username, processed)
                    VALUES (:d, :k, FALSE)
                """), {"d": discord_id, "k": f"FAILED:{kick_username}:already_linked"})
                return render_error(
                    f"Kick account '{kick_username}' is already linked to another Discord user on this server."
                )
        
        # Link accounts in database
        with engine.begin() as conn:
            # Use UPSERT with composite unique key (discord_id, discord_server_id)
            conn.execute(text("""
                INSERT INTO links (discord_id, kick_name, discord_server_id)
                VALUES (:d, :k, :gid)
                ON CONFLICT(discord_id, discord_server_id) DO UPDATE 
                SET kick_name = excluded.kick_name, linked_at = CURRENT_TIMESTAMP
            """), {"d": discord_id, "k": kick_username.lower(), "gid": guild_id})
            
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


def exchange_code_for_token(code, code_verifier=None, redirect_uri=None):
    """Exchange authorization code for access token."""
    import requests
    
    # Use provided redirect_uri or default to auth/kick/callback
    if redirect_uri is None:
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


@app.route('/bot/authorize')
def bot_authorize():
    """
    Special route for getting bot access token without Discord account requirement.
    This initiates OAuth flow specifically for the bot account.
    Requires admin authentication via token.
    """
    try:
        # Check for admin authorization token
        auth_token = request.args.get('token')
        expected_token = os.getenv('BOT_AUTH_TOKEN')
        
        if not expected_token:
            print(f"⚠️ BOT_AUTH_TOKEN not configured - bot authorization disabled", flush=True)
            return render_error("Bot authorization is not configured. Contact the administrator.")
        
        if not auth_token or auth_token != expected_token:
            print(f"❌ Invalid or missing bot authorization token", flush=True)
            return render_error("Unauthorized. Invalid or missing authentication token.")
        
        print(f"🤖 Bot authorization initiated with valid token", flush=True)
        
        # Ensure bot_tokens table exists
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS bot_tokens (
                    bot_username TEXT PRIMARY KEY,
                    access_token TEXT NOT NULL,
                    refresh_token TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
        
        # Generate PKCE pair
        code_verifier, code_challenge = generate_pkce_pair()
        
        # Generate state for CSRF protection
        state = secrets.token_urlsafe(32)
        print(f"🔑 Generated state for bot authorization", flush=True)
        
        # Store state in database with special discord_id = 0 for bot
        with engine.begin() as conn:
            # Clean up old states
            deleted_count = conn.execute(text("""
                DELETE FROM oauth_states 
                WHERE created_at < CURRENT_TIMESTAMP - INTERVAL '30 minutes'
            """)).rowcount
            print(f"🧹 Cleaned up {deleted_count} expired state(s)", flush=True)
            
            # Store new state with discord_id = 0 to indicate bot authorization
            conn.execute(text("""
                INSERT INTO oauth_states (state, discord_id, code_verifier, created_at)
                VALUES (:state, :discord_id, :code_verifier, CURRENT_TIMESTAMP)
            """), {"state": state, "discord_id": 0, "code_verifier": code_verifier})
            print(f"✅ Bot state saved to database", flush=True)
        
        # Build authorization URL with chat:write scope
        # Use same callback as regular OAuth to avoid needing multiple redirect URIs
        redirect_uri = f"{OAUTH_BASE_URL}/auth/kick/callback"
        
        auth_params = {
            'client_id': KICK_CLIENT_ID,
            'response_type': 'code',
            'redirect_uri': redirect_uri,
            'state': state,
            'scope': 'chat:write chat:read channel:read user:read events:subscribe',  # Match Botrix scopes
            'code_challenge': code_challenge,
            'code_challenge_method': 'S256'
        }
        
        print(f"🔗 Bot authorization URL: {KICK_AUTHORIZE_URL}?{urlencode(auth_params)}", flush=True)
        
        auth_url = f"{KICK_AUTHORIZE_URL}?{urlencode(auth_params)}"
        
        return redirect(auth_url)
    except Exception as e:
        print(f"❌ Error in bot_authorize: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return render_error(f"Failed to initiate bot authorization: {str(e)}")


if __name__ == '__main__':
    # Use OAUTH_PORT if set, otherwise use PORT, otherwise default to 8000
    # This allows Flask to run on a different port than Railway's main PORT
    port = int(os.getenv('OAUTH_PORT', os.getenv('PORT', 8000)))
    print(f"🚀 Starting OAuth server on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
