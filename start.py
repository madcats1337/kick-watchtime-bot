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
    for line in iter(process.stdout.readline, ''):
        if line:
            print(f"[{name}] {line.rstrip()}")
    process.stdout.close()

def main():
    print("🚀 Starting Kick Discord Bot with OAuth Server...")
    print(f"Python: {sys.executable}")
    print(f"Port: {os.getenv('PORT', '8000')}")
    
    processes = []
    threads = []
    
    try:
        # Start Flask OAuth server
        print("📡 Starting OAuth web server...")
        flask_process = subprocess.Popen(
            [sys.executable, "oauth_server.py"],
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
        
        print(f"✅ OAuth server started (PID: {flask_process.pid})")
        
        # Give Flask time to start
        time.sleep(3)
        
        # Start Discord bot
        print("🤖 Starting Discord bot...")
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
        
        print(f"✅ Discord bot started (PID: {bot_process.pid})")
        print("✅ Both services running! Monitoring...")
        
        # Monitor both processes
        while True:
            for name, process in processes:
                if process.poll() is not None:
                    print(f"❌ {name} exited with code {process.returncode}")
                    # Print any remaining output
                    remaining = process.stdout.read()
                    if remaining:
                        print(f"[{name}] {remaining}")
                    # If one dies, kill the other
                    for other_name, other_process in processes:
                        if other_process != process and other_process.poll() is None:
                            print(f"🛑 Terminating {other_name}...")
                            other_process.terminate()
                    sys.exit(process.returncode)
            
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\n🛑 Shutting down...")
        for name, process in processes:
            if process.poll() is None:
                print(f"Stopping {name}...")
                process.terminate()
                process.wait()
        sys.exit(0)
    except Exception as e:
        print(f"❌ Error: {e}")
        for name, process in processes:
            if process.poll() is None:
                process.terminate()
        sys.exit(1)

if __name__ == "__main__":
    main()
