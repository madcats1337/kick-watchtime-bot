"""
Startup script to run both Discord bot and OAuth web server
"""
import os
import sys
import time
import subprocess
import signal

def main():
    print("🚀 Starting Kick Discord Bot with OAuth Server...")
    
    processes = []
    
    try:
        # Start Flask OAuth server
        print("📡 Starting OAuth web server...")
        flask_process = subprocess.Popen(
            [sys.executable, "oauth_server.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True
        )
        processes.append(("Flask", flask_process))
        print(f"✅ OAuth server started (PID: {flask_process.pid})")
        
        # Give Flask time to start
        time.sleep(3)
        
        # Start Discord bot
        print("🤖 Starting Discord bot...")
        bot_process = subprocess.Popen(
            [sys.executable, "bot.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True
        )
        processes.append(("Bot", bot_process))
        print(f"✅ Discord bot started (PID: {bot_process.pid})")
        
        print("✅ Both services running!")
        
        # Monitor both processes
        while True:
            for name, process in processes:
                if process.poll() is not None:
                    print(f"❌ {name} exited with code {process.returncode}")
                    # If one dies, kill the other
                    for other_name, other_process in processes:
                        if other_process != process and other_process.poll() is None:
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
