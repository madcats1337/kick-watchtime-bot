"""
Combined server that runs both Flask OAuth server and Discord bot
Runs Flask in main process, bot in background subprocess
"""
import os
import sys
import threading
import subprocess
import time

def run_discord_bot():
    """Run Discord bot in background subprocess"""
    print("🤖 Starting Discord bot subprocess...", flush=True)
    try:
        # Run bot.py and stream output
        process = subprocess.Popen(
            [sys.executable, "-u", "bot.py"],
            stdout=sys.stdout,
            stderr=sys.stderr
        )
        print(f"✅ Bot subprocess started (PID: {process.pid})", flush=True)
        process.wait()
        print(f"❌ Discord bot exited with code {process.returncode}", flush=True)
    except Exception as e:
        print(f"❌ Discord bot error: {e}", flush=True)
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    print("🚀 Starting combined OAuth + Discord Bot server...", flush=True)
    print(f"Python: {sys.version}", flush=True)
    print(f"Working directory: {os.getcwd()}", flush=True)
    
    # Start Discord bot in background thread
    bot_thread = threading.Thread(target=run_discord_bot, daemon=True)
    bot_thread.start()
    
    # Give bot a moment to start
    print("⏳ Waiting for bot to initialize...", flush=True)
    time.sleep(3)
    
    # Now run Flask OAuth server in main process using Gunicorn
    print("📡 Starting OAuth web server with Gunicorn...", flush=True)
    port = int(os.getenv('PORT', 8000))
    print(f"🌐 Port: {port}", flush=True)
    print(f"🌐 OAuth Base URL: {os.getenv('OAUTH_BASE_URL', 'Not set')}", flush=True)
    
    # Use Gunicorn for production
    try:
        os.execvp('gunicorn', [
            'gunicorn',
            '--bind', f'0.0.0.0:{port}',
            '--workers', '2',
            '--timeout', '120',
            '--access-logfile', '-',
            '--error-logfile', '-',
            'core.oauth_server:app'
        ])
    except Exception as e:
        print(f"❌ Failed to start Gunicorn: {e}", flush=True)
        import traceback
        traceback.print_exc()
        sys.exit(1)
