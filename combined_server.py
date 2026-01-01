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
            # First check if table exists
            table_exists = conn.execute(text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'links'
                )
            """)).scalar()
            
            if not table_exists:
                print("   ℹ️ links table doesn't exist yet, will be created by bot.py", flush=True)
                return
            
            # Check current primary key structure
            pk_result = conn.execute(text("""
                SELECT a.attname
                FROM pg_index i
                JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                WHERE i.indrelid = 'links'::regclass AND i.indisprimary
                ORDER BY a.attnum
            """))
            pk_columns = [row[0] for row in pk_result]
            print(f"   📊 Current primary key columns: {pk_columns}", flush=True)
            
            # If PK is only discord_id (old schema), we need to recreate it
            if pk_columns == ['discord_id'] or 'discord_server_id' not in pk_columns:
                print("   🔄 Migrating links table to composite primary key...", flush=True)
                
                # First, handle any NULL discord_server_id values
                # Set them to 0 as a default server
                null_count = conn.execute(text("""
                    SELECT COUNT(*) FROM links WHERE discord_server_id IS NULL
                """)).scalar()
                if null_count > 0:
                    print(f"   📝 Setting {null_count} NULL discord_server_id values to 0...", flush=True)
                    conn.execute(text("""
                        UPDATE links SET discord_server_id = 0 WHERE discord_server_id IS NULL
                    """))
                
                # Remove duplicates - keep most recent link per discord_id + server combo
                # For rows with same discord_id, keep the one with most recent linked_at
                conn.execute(text("""
                    DELETE FROM links a
                    WHERE EXISTS (
                        SELECT 1 FROM links b
                        WHERE b.discord_id = a.discord_id
                        AND b.discord_server_id = a.discord_server_id
                        AND b.linked_at > a.linked_at
                    )
                """))
                
                # Also remove strict duplicates (same discord_id + server_id)
                conn.execute(text("""
                    DELETE FROM links a
                    WHERE a.ctid <> (
                        SELECT MIN(b.ctid)
                        FROM links b
                        WHERE b.discord_id = a.discord_id
                        AND b.discord_server_id = a.discord_server_id
                    )
                """))
                
                # Drop old primary key
                conn.execute(text("""
                    ALTER TABLE links DROP CONSTRAINT IF EXISTS links_pkey
                """))
                
                # Make discord_server_id NOT NULL
                conn.execute(text("""
                    ALTER TABLE links ALTER COLUMN discord_server_id SET NOT NULL
                """))
                
                # Add new composite primary key
                conn.execute(text("""
                    ALTER TABLE links ADD PRIMARY KEY (discord_id, discord_server_id)
                """))
                
                print("   ✅ Primary key migrated to composite (discord_id, discord_server_id)!", flush=True)
            
            # Check if kick_name unique constraint exists
            result = conn.execute(text("""
                SELECT constraint_name
                FROM information_schema.table_constraints
                WHERE table_name = 'links'
                AND constraint_type = 'UNIQUE'
                AND constraint_name = 'links_kick_name_server_unique'
            """))
            
            if not result.fetchone():
                print("   Adding unique constraint on (kick_name, discord_server_id)...", flush=True)
                
                # Remove old single-column unique constraint if it exists
                conn.execute(text("""
                    ALTER TABLE links DROP CONSTRAINT IF EXISTS links_kick_name_key
                """))
                conn.execute(text("""
                    ALTER TABLE links DROP CONSTRAINT IF EXISTS links_discord_id_key
                """))
                
                # Add composite unique constraint for kick_name per server
                try:
                    conn.execute(text("""
                        ALTER TABLE links
                        ADD CONSTRAINT links_kick_name_server_unique
                        UNIQUE (kick_name, discord_server_id)
                    """))
                except Exception as e:
                    print(f"   ⚠️ Could not add kick_name constraint: {e}", flush=True)
                
                print("   ✅ Unique constraints configured!", flush=True)
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
