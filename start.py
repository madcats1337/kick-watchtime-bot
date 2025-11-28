"""
Startup script to run both Discord bot and OAuth web server
"""
import os
import sys
import time
import subprocess
import signal
import threading

def stream_output(process, name):
    """Stream process output to stdout in real-time"""
    try:
        for line in iter(process.stdout.readline, ''):
            if line:
                print(f"[{name}] {line.rstrip()}", flush=True)
    except Exception as e:
        print(f"[{name}] Stream error: {e}", flush=True)
    finally:
        if process.stdout:
            process.stdout.close()

def main():
    print("🚀 Starting Kick Discord Bot with OAuth Server...", flush=True)
    print(f"Python: {sys.executable}", flush=True)
    print(f"Python version: {sys.version}", flush=True)
    print(f"Working directory: {os.getcwd()}", flush=True)
    print(f"Port: {os.getenv('PORT', '8000')}", flush=True)
    print(f"Files in directory: {os.listdir('.')}", flush=True)

    # Check if critical files exist
    if not os.path.exists('core/oauth_server.py'):
        print("❌ ERROR: core/oauth_server.py not found!", flush=True)
        sys.exit(1)
    if not os.path.exists('bot.py'):
        print("❌ ERROR: bot.py not found!", flush=True)
        sys.exit(1)

    print("✅ Critical files found", flush=True)

    processes = []
    threads = []

    try:
        # Start Flask OAuth server
        print("📡 Starting OAuth web server...", flush=True)
        try:
            flask_process = subprocess.Popen(
                [sys.executable, "core/oauth_server.py"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1
            )
            processes.append(("Flask", flask_process))

            # Stream Flask output
            flask_thread = threading.Thread(target=stream_output, args=(flask_process, "Flask"))
            flask_thread.daemon = True
            flask_thread.start()
            threads.append(flask_thread)

            print(f"✅ OAuth server process started (PID: {flask_process.pid})", flush=True)
        except Exception as e:
            print(f"❌ Failed to start Flask: {e}", flush=True)
            raise

        # Give Flask time to start
        time.sleep(3)

        # Check if Flask is still running
        if flask_process.poll() is not None:
            print(f"❌ Flask died immediately with code {flask_process.returncode}", flush=True)
            remaining = flask_process.stdout.read()
            if remaining:
                print(f"[Flask] {remaining}", flush=True)
            sys.exit(flask_process.returncode)

        # Start Discord bot
        print("🤖 Starting Discord bot...", flush=True)
        try:
            bot_process = subprocess.Popen(
                [sys.executable, "bot.py"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1
            )
            processes.append(("Bot", bot_process))

            # Stream bot output
            bot_thread = threading.Thread(target=stream_output, args=(bot_process, "Bot"))
            bot_thread.daemon = True
            bot_thread.start()
            threads.append(bot_thread)

            print(f"✅ Discord bot process started (PID: {bot_process.pid})", flush=True)
        except Exception as e:
            print(f"❌ Failed to start bot: {e}", flush=True)
            if flask_process.poll() is None:
                flask_process.terminate()
            raise

        print("✅ Both services started! Monitoring...", flush=True)

        # Monitor both processes
        while True:
            for name, process in processes:
                if process.poll() is not None:
                    print(f"❌ {name} exited with code {process.returncode}", flush=True)
                    # Print any remaining output
                    try:
                        remaining = process.stdout.read()
                        if remaining:
                            print(f"[{name}] {remaining}", flush=True)
                    except:
                        pass
                    # If one dies, kill the other
                    for other_name, other_process in processes:
                        if other_process != process and other_process.poll() is None:
                            print(f"🛑 Terminating {other_name}...", flush=True)
                            other_process.terminate()
                    sys.exit(process.returncode if process.returncode else 1)

            time.sleep(1)

    except KeyboardInterrupt:
        print("\n🛑 Shutting down...", flush=True)
        for name, process in processes:
            if process.poll() is None:
                print(f"Stopping {name}...", flush=True)
                process.terminate()
                process.wait()
        sys.exit(0)
    except Exception as e:
        print(f"❌ Fatal error: {e}", flush=True)
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
        print(f"❌ Startup failed: {e}", flush=True)
        import traceback
        traceback.print_exc()
        sys.exit(1)
