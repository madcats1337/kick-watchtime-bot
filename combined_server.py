"""
Combined server that runs both Flask OAuth server and Discord bot
Runs Flask in main process, bot in background subprocess
"""

import os
import subprocess
import sys
import threading
import time


def run_database_migration():
    """Run database migration before starting services"""
    print("📋 Running database migration...", flush=True)
    try:
        from sqlalchemy import create_engine, text

        engine = create_engine(os.getenv("DATABASE_URL"))

        with engine.begin() as conn:
            # First check if table exists
            table_exists = conn.execute(
                text(
                    """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_name = 'links'
                )
            """
                )
            ).scalar()

            if not table_exists:
                print("   ℹ️ links table doesn't exist yet, will be created by bot.py", flush=True)
                return

            # Check current primary key structure
            pk_result = conn.execute(
                text(
                    """
                SELECT a.attname
                FROM pg_index i
                JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                WHERE i.indrelid = 'links'::regclass AND i.indisprimary
                ORDER BY a.attnum
            """
                )
            )
            pk_columns = [row[0] for row in pk_result]
            print(f"   📊 Current primary key columns: {pk_columns}", flush=True)

            # If PK is only discord_id (old schema), we need to recreate it
            if pk_columns == ["discord_id"] or "discord_server_id" not in pk_columns:
                print("   🔄 Migrating links table to composite primary key...", flush=True)

                # First, handle any NULL discord_server_id values
                # Set them to 0 as a default server
                null_count = conn.execute(
                    text(
                        """
                    SELECT COUNT(*) FROM links WHERE discord_server_id IS NULL
                """
                    )
                ).scalar()
                if null_count > 0:
                    print(f"   📝 Setting {null_count} NULL discord_server_id values to 0...", flush=True)
                    conn.execute(
                        text(
                            """
                        UPDATE links SET discord_server_id = 0 WHERE discord_server_id IS NULL
                    """
                        )
                    )

                # Remove duplicates - keep most recent link per discord_id + server combo
                # For rows with same discord_id, keep the one with most recent linked_at
                conn.execute(
                    text(
                        """
                    DELETE FROM links a
                    WHERE EXISTS (
                        SELECT 1 FROM links b
                        WHERE b.discord_id = a.discord_id
                        AND b.discord_server_id = a.discord_server_id
                        AND b.linked_at > a.linked_at
                    )
                """
                    )
                )

                # Also remove strict duplicates (same discord_id + server_id)
                conn.execute(
                    text(
                        """
                    DELETE FROM links a
                    WHERE a.ctid <> (
                        SELECT MIN(b.ctid)
                        FROM links b
                        WHERE b.discord_id = a.discord_id
                        AND b.discord_server_id = a.discord_server_id
                    )
                """
                    )
                )

                # Drop old primary key
                conn.execute(
                    text(
                        """
                    ALTER TABLE links DROP CONSTRAINT IF EXISTS links_pkey
                """
                    )
                )

                # Make discord_server_id NOT NULL
                conn.execute(
                    text(
                        """
                    ALTER TABLE links ALTER COLUMN discord_server_id SET NOT NULL
                """
                    )
                )

                # Add new composite primary key
                conn.execute(
                    text(
                        """
                    ALTER TABLE links ADD PRIMARY KEY (discord_id, discord_server_id)
                """
                    )
                )

                print("   ✅ Primary key migrated to composite (discord_id, discord_server_id)!", flush=True)

            # Check if kick_name unique constraint exists
            result = conn.execute(
                text(
                    """
                SELECT constraint_name
                FROM information_schema.table_constraints
                WHERE table_name = 'links'
                AND constraint_type = 'UNIQUE'
                AND constraint_name = 'links_kick_name_server_unique'
            """
                )
            )

            if not result.fetchone():
                print("   Adding unique constraint on (kick_name, discord_server_id)...", flush=True)

                # Remove old single-column unique constraint if it exists
                conn.execute(
                    text(
                        """
                    ALTER TABLE links DROP CONSTRAINT IF EXISTS links_kick_name_key
                """
                    )
                )
                conn.execute(
                    text(
                        """
                    ALTER TABLE links DROP CONSTRAINT IF EXISTS links_discord_id_key
                """
                    )
                )

                # Add composite unique constraint for kick_name per server
                try:
                    conn.execute(
                        text(
                            """
                        ALTER TABLE links
                        ADD CONSTRAINT links_kick_name_server_unique
                        UNIQUE (kick_name, discord_server_id)
                    """
                        )
                    )
                except Exception as e:
                    print(f"   ⚠️ Could not add kick_name constraint: {e}", flush=True)

                print("   ✅ Unique constraints configured!", flush=True)
            else:
                print("   ✅ Database schema is up to date", flush=True)

    except Exception as e:
        print(f"   ⚠️ Migration warning: {e}", flush=True)
        print("   Continuing startup anyway...", flush=True)


def run_discord_bot():
    """Start Discord bot as a subprocess, return the process handle"""
    print("🤖 Starting Discord bot subprocess...", flush=True)
    try:
        # Run bot.py with unbuffered output, piped through reader threads
        process = subprocess.Popen(
            [sys.executable, "-u", "bot.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,  # Line buffered
        )
        print(f"✅ Bot subprocess started (PID: {process.pid})", flush=True)
        return process
    except Exception as e:
        print(f"❌ Discord bot error: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return None


def stream_subprocess_output(process, prefix="[BOT]"):
    """Read and print subprocess output line by line"""
    try:
        for line in iter(process.stdout.readline, ""):
            if line:
                print(f"{prefix} {line.rstrip()}", flush=True)
    except Exception as e:
        print(f"{prefix} Stream ended: {e}", flush=True)
    finally:
        if process.stdout:
            process.stdout.close()


if __name__ == "__main__":
    print("🚀 Starting combined OAuth + Discord Bot server...", flush=True)
    print(f"Python: {sys.version}", flush=True)
    print(f"Working directory: {os.getcwd()}", flush=True)

    # Run database migration first
    run_database_migration()

    # Start Discord bot subprocess
    bot_process = run_discord_bot()

    # Stream bot output in a background thread
    if bot_process:
        bot_output_thread = threading.Thread(
            target=stream_subprocess_output,
            args=(bot_process, "[BOT]"),
            daemon=True,
        )
        bot_output_thread.start()

    # Give bot a moment to start
    print("⏳ Waiting for bot to initialize...", flush=True)
    time.sleep(3)

    # Now run Flask OAuth server in main process using Gunicorn
    print("📡 Starting OAuth web server with Gunicorn...", flush=True)
    port = int(os.getenv("PORT", 8000))
    print(f"🌐 Port: {port}", flush=True)
    print(f"🌐 OAuth Base URL: {os.getenv('OAUTH_BASE_URL', 'Not set')}", flush=True)

    # Use Gunicorn for production
    # IMPORTANT: Use subprocess.Popen (NOT os.execvp) so the bot process stays alive.
    # os.execvp replaces the entire process image, killing all subprocesses.
    try:
        gunicorn_process = subprocess.Popen(
            [
                "gunicorn",
                "--bind",
                f"0.0.0.0:{port}",
                "--workers",
                "2",
                "--timeout",
                "120",
                "--access-logfile",
                "-",
                "--error-logfile",
                "-",
                "core.oauth_server:app",
            ],
        )
        print(f"✅ Gunicorn started (PID: {gunicorn_process.pid})", flush=True)

        # Monitor both processes - if either dies, restart or exit
        while True:
            # Check bot process
            if bot_process and bot_process.poll() is not None:
                print(f"❌ Discord bot exited with code {bot_process.returncode}", flush=True)
                # Restart bot
                print("🔄 Restarting Discord bot...", flush=True)
                bot_process = run_discord_bot()
                if bot_process:
                    bot_output_thread = threading.Thread(
                        target=stream_subprocess_output,
                        args=(bot_process, "[BOT]"),
                        daemon=True,
                    )
                    bot_output_thread.start()

            # Check gunicorn process
            if gunicorn_process.poll() is not None:
                print(f"❌ Gunicorn exited with code {gunicorn_process.returncode}", flush=True)
                # Kill bot and exit so Railway can restart everything
                if bot_process:
                    bot_process.terminate()
                sys.exit(gunicorn_process.returncode)

            time.sleep(5)

    except KeyboardInterrupt:
        print("🛑 Shutting down...", flush=True)
        if bot_process:
            bot_process.terminate()
        gunicorn_process.terminate()
        sys.exit(0)
    except Exception as e:
        print(f"❌ Failed to start Gunicorn: {e}", flush=True)
        import traceback
        traceback.print_exc()
        if bot_process:
            bot_process.terminate()
        sys.exit(1)
