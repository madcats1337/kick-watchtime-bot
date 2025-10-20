"""
Combined server that runs both Flask OAuth server and Discord bot
This approach works better with Railway's single-port expectation
"""
import os
import sys
import threading
import subprocess

# Import the Flask app from oauth_server
import oauth_server

def run_discord_bot():
    """Run Discord bot in a separate thread using subprocess"""
    print("🤖 Starting Discord bot in background thread...")
    try:
        # Run bot.py as subprocess so it doesn't block Flask
        result = subprocess.run([sys.executable, "bot.py"], 
                              capture_output=False, 
                              text=True)
        print(f"❌ Discord bot exited with code {result.returncode}")
    except Exception as e:
        print(f"❌ Discord bot error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    print("🚀 Starting combined OAuth + Discord Bot server...")
    
    # Start Discord bot in background thread
    bot_thread = threading.Thread(target=run_discord_bot, daemon=False)
    bot_thread.start()
    
    # Give bot a moment to start
    import time
    time.sleep(2)
    
    # Run Flask in main thread (Railway expects this to bind to PORT)
    port = int(os.getenv('PORT', 8000))
    print(f"📡 Starting OAuth web server on port {port}")
    print(f"🌐 OAuth callback URL: {os.getenv('OAUTH_BASE_URL', 'Not set')}/auth/kick/callback")
    oauth_server.app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
