#!/usr/bin/env bash
set -e

echo "🚀 Starting Kick Discord Bot with OAuth Server..."

# Start Flask OAuth server in background
echo "📡 Starting OAuth web server on port ${PORT:-8000}..."
python3 oauth_server.py &
FLASK_PID=$!

# Give Flask a moment to start
sleep 3

# Start Discord bot
echo "🤖 Starting Discord bot..."
python3 bot.py &
BOT_PID=$!

echo "✅ Both services started"
echo "Flask PID: $FLASK_PID"
echo "Bot PID: $BOT_PID"

# Function to handle shutdown
cleanup() {
    echo "🛑 Shutting down services..."
    kill $FLASK_PID $BOT_PID 2>/dev/null || true
    exit
}

trap cleanup SIGTERM SIGINT

# Wait for both processes
wait $FLASK_PID $BOT_PID
