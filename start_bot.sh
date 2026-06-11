#!/bin/bash
# Startup script for the AI bot - with auto-restart on crash
set -e

BOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$BOT_DIR"

# Kill any existing gemmabot processes before starting
pkill -f "[Pp]ython.*main\.py" 2>/dev/null || true
sleep 3

# Double-check nothing remains
if pgrep -f "[Pp]ython.*main\.py" > /dev/null 2>&1; then
    kill -9 $(pgrep -f "[Pp]ython.*main\.py") 2>/dev/null || true
    sleep 2
fi

while true; do
    echo "🤖 Starting AI Multi-Platform Bot"
    echo "=================================="
    echo "Model: $(grep '^model' config.toml | head -1 | cut -d'"' -f2)"
    echo "Time: $(date)"
    echo "=================================="

    # Activate virtual environment
    source venv/bin/activate

    # Start the bot
    python main.py || true

    # Deactivate when done
    deactivate

    echo "Bot exited at $(date)"
    echo "Restarting in 5 seconds..."
    sleep 5
done
