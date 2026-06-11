#!/bin/bash
# Startup script for the AI bot - with auto-restart on crash
set -e

BOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$BOT_DIR"

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

    EXIT_CODE=$?
    echo "Bot exited with code $EXIT_CODE at $(date)"
    echo "Restarting in 5 seconds..."
    sleep 5
done
