"""
Combined server that runs both Flask OAuth server and Discord bot
Runs Flask in main process, bot in background subprocess
"""

import logging
import os
import subprocess
import sys
import threading
import time

logger = logging.getLogger(__name__)


def run_database_migration():
    """Run database migration before starting services"""
    logger.info("📋 Running database migration...")
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
                logger.info("   ℹ️ links table doesn't exist yet, will be created by bot.py")
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
            logger.info(f"   📊 Current primary key columns: {pk_columns}")

            # If PK is only discord_id (old schema), we need to recreate it
            if pk_columns == ["discord_id"] or "discord_server_id" not in pk_columns:
                logger.info("   🔄 Migrating links table to composite primary key...")

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
                    logger.info(f"   📝 Setting {null_count} NULL discord_server_id values to 0...")
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

                logger.info("   ✅ Primary key migrated to composite (discord_id, discord_server_id)!")

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
                logger.info("   Adding unique constraint on (kick_name, discord_server_id)...")

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
                    logger.warning(f"   ⚠️ Could not add kick_name constraint: {e}")

                logger.info("   ✅ Unique constraints configured!")
            else:
                logger.info("   ✅ Database schema is up to date")

    except Exception as e:
        logger.warning(f"   ⚠️ Migration warning: {e}")
        logger.info("   Continuing startup anyway...")


def run_discord_bot():
    """Start Discord bot as a subprocess, return the process handle"""
    logger.info("🤖 Starting Discord bot subprocess...")
    try:
        # Run bot.py with unbuffered output, piped through reader threads
        process = subprocess.Popen(
            [sys.executable, "-u", "bot.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,  # Line buffered
        )
        logger.info(f"✅ Bot subprocess started (PID: {process.pid})")
        return process
    except Exception as e:
        logger.error(f"❌ Discord bot error: {e}")
        import traceback

        traceback.print_exc()
        return None


def stream_subprocess_output(process, prefix="[BOT]"):
    """Read and print subprocess output line by line"""
    try:
        for line in iter(process.stdout.readline, ""):
            if line:
                logger.info(f"{prefix} {line.rstrip()}")
    except Exception as e:
        logger.info(f"{prefix} Stream ended: {e}")
    finally:
        if process.stdout:
            process.stdout.close()


if __name__ == "__main__":
    logger.info("🚀 Starting combined OAuth + Discord Bot server...")
    logger.info(f"Python: {sys.version}")
    logger.info(f"Working directory: {os.getcwd()}")

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
    logger.info("⏳ Waiting for bot to initialize...")
    time.sleep(3)

    # Now run Flask OAuth server in main process using Gunicorn
    logger.info("📡 Starting OAuth web server with Gunicorn...")
    port = int(os.getenv("PORT", 8000))
    logger.info(f"🌐 Port: {port}")
    logger.info(f"🌐 OAuth Base URL: {os.getenv('OAUTH_BASE_URL', 'Not set')}")

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
        logger.info(f"✅ Gunicorn started (PID: {gunicorn_process.pid})")

        # Monitor both processes - if either dies, restart or exit
        while True:
            # Check bot process
            if bot_process and bot_process.poll() is not None:
                logger.error(f"❌ Discord bot exited with code {bot_process.returncode}")
                # Restart bot
                logger.info("🔄 Restarting Discord bot...")
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
                logger.error(f"❌ Gunicorn exited with code {gunicorn_process.returncode}")
                # Kill bot and exit so Railway can restart everything
                if bot_process:
                    bot_process.terminate()
                sys.exit(gunicorn_process.returncode)

            time.sleep(5)

    except KeyboardInterrupt:
        logger.info("🛑 Shutting down...")
        if bot_process:
            bot_process.terminate()
        gunicorn_process.terminate()
        sys.exit(0)
    except Exception as e:
        logger.error(f"❌ Failed to start Gunicorn: {e}")
        import traceback

        traceback.print_exc()
        if bot_process:
            bot_process.terminate()
        sys.exit(1)
