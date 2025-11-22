"""
Combined server that runs both Flask OAuth server and Discord bot
Runs Flask in main process, bot in background subprocess
"""
import os
import sys
import threading
import subprocess
import time

def run_database_migration():
    """Run database migration before starting services"""
    print("📋 Running database migration...", flush=True)
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(os.getenv('DATABASE_URL'))
        
        with engine.begin() as conn:
            # Check if composite unique constraint exists
            result = conn.execute(text("""
                SELECT constraint_name 
                FROM information_schema.table_constraints 
                WHERE table_name = 'links' 
                AND constraint_type = 'UNIQUE'
                AND constraint_name = 'links_discord_server_unique'
            """))
            
            if not result.fetchone():
                print("   Adding unique constraint on (discord_id, discord_server_id)...", flush=True)
                
                # Remove old single-column unique constraint if it exists
                conn.execute(text("""
                    ALTER TABLE links 
                    DROP CONSTRAINT IF EXISTS links_discord_id_key
                """))
                
                # Remove any duplicates, keeping most recent per (discord_id, discord_server_id)
                # Note: links table uses composite PRIMARY KEY (discord_id, discord_server_id), no id column
                conn.execute(text("""
                    DELETE FROM links a 
                    WHERE a.linked_at < (
                        SELECT MAX(b.linked_at) 
                        FROM links b 
                        WHERE b.discord_id = a.discord_id 
                        AND b.discord_server_id = a.discord_server_id
                    )
                """))
                
                # Add composite unique constraint
                conn.execute(text("""
                    ALTER TABLE links 
                    ADD CONSTRAINT links_discord_server_unique 
                    UNIQUE (discord_id, discord_server_id)
                """))
                
                print("   ✅ Migration complete!", flush=True)
            else:
                print("   ✅ Database schema is up to date", flush=True)
                
    except Exception as e:
        print(f"   ⚠️ Migration warning: {e}", flush=True)
        print("   Continuing startup anyway...", flush=True)

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
    
    # Run database migration first
    run_database_migration()

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
