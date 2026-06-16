"""
Startup script to run both Discord bot and OAuth web server
"""

import logging
import os
import signal
import subprocess
import sys
import threading
import time

# Configure logging early so this launcher's own logs are formatted/visible.
from utils.logging_config import setup_logging

setup_logging("kick_start", log_level=os.getenv("LOG_LEVEL", "INFO"), source_tag="BOT")
logger = logging.getLogger(__name__)


def stream_output(process, name):
    """Relay subprocess output to our stdout in real-time.

    Subprocess lines are already formatted by their own setup_logging, so we pass
    them through VERBATIM — re-logging via `logger` would double-wrap each line.
    """
    try:
        for line in iter(process.stdout.readline, ""):
            if line:
                sys.stdout.write(line if line.endswith("\n") else line + "\n")
                sys.stdout.flush()
    except Exception as e:
        logger.warning(f"[{name}] output stream ended: {e}")
    finally:
        if process.stdout:
            process.stdout.close()


def main():
    logger.info("🚀 Starting Kick Discord Bot with OAuth Server...")
    logger.info(f"Python: {sys.executable}")
    logger.info(f"Python version: {sys.version}")
    logger.info(f"Working directory: {os.getcwd()}")
    logger.info(f"Port: {os.getenv('PORT', '8000')}")
    logger.info(f"Files in directory: {os.listdir('.')}")

    # Check if critical files exist
    if not os.path.exists("core/oauth_server.py"):
        logger.error("❌ ERROR: core/oauth_server.py not found!")
        sys.exit(1)
    if not os.path.exists("bot.py"):
        logger.error("❌ ERROR: bot.py not found!")
        sys.exit(1)

    logger.info("✅ Critical files found")

    processes = []
    threads = []

    try:
        # Start Flask OAuth server
        logger.info("📡 Starting OAuth web server...")
        try:
            flask_process = subprocess.Popen(
                [sys.executable, "core/oauth_server.py"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1,
            )
            processes.append(("Flask", flask_process))

            # Stream Flask output
            flask_thread = threading.Thread(target=stream_output, args=(flask_process, "Flask"))
            flask_thread.daemon = True
            flask_thread.start()
            threads.append(flask_thread)

            logger.info(f"✅ OAuth server process started (PID: {flask_process.pid})")
        except Exception as e:
            logger.error(f"❌ Failed to start Flask: {e}")
            raise

        # Give Flask time to start
        time.sleep(3)

        # Check if Flask is still running
        if flask_process.poll() is not None:
            logger.error(f"❌ Flask died immediately with code {flask_process.returncode}")
            remaining = flask_process.stdout.read()
            if remaining:
                logger.info(f"[Flask] {remaining}")
            sys.exit(flask_process.returncode)

        # Start Discord bot
        logger.info("🤖 Starting Discord bot...")
        try:
            bot_process = subprocess.Popen(
                [sys.executable, "bot.py"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1,
            )
            processes.append(("Bot", bot_process))

            # Stream bot output
            bot_thread = threading.Thread(target=stream_output, args=(bot_process, "Bot"))
            bot_thread.daemon = True
            bot_thread.start()
            threads.append(bot_thread)

            logger.info(f"✅ Discord bot process started (PID: {bot_process.pid})")
        except Exception as e:
            logger.error(f"❌ Failed to start bot: {e}")
            if flask_process.poll() is None:
                flask_process.terminate()
            raise

        logger.info("✅ Both services started! Monitoring...")

        # Monitor both processes
        while True:
            for name, process in processes:
                if process.poll() is not None:
                    logger.error(f"❌ {name} exited with code {process.returncode}")
                    # Print any remaining output
                    try:
                        remaining = process.stdout.read()
                        if remaining:
                            logger.info(f"[{name}] {remaining}")
                    except:
                        pass
                    # If one dies, kill the other
                    for other_name, other_process in processes:
                        if other_process != process and other_process.poll() is None:
                            logger.info(f"🛑 Terminating {other_name}...")
                            other_process.terminate()
                    sys.exit(process.returncode if process.returncode else 1)

            time.sleep(1)

    except KeyboardInterrupt:
        logger.info("\n🛑 Shutting down...")
        for name, process in processes:
            if process.poll() is None:
                logger.info(f"Stopping {name}...")
                process.terminate()
                process.wait()
        sys.exit(0)
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        import traceback

        traceback.print_exc()
        for name, process in processes:
            if process.poll() is None:
                process.terminate()
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error(f"❌ Startup failed: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
