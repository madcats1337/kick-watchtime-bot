#!/bin/bash
# Start both the Discord bot and OAuth web server

echo "🚀 Starting Kick Discord Bot with OAuth Server..."

# Start Flask OAuth server in background
echo "📡 Starting OAuth web server on port ${PORT:-8000}..."
python oauth_server.py &
FLASK_PID=$!

# Give Flask a moment to start
sleep 2

# Start Discord bot
echo "🤖 Starting Discord bot..."
python bot.py &
BOT_PID=$!

# Wait for both processes
wait $FLASK_PID $BOT_PID
