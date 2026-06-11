#!/bin/bash
# Startup script for the AI bot — auto-restart loop
# Called by botctl.sh; not intended for direct use.
set -e

BOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$BOT_DIR"

echo "🤖 Starting $NAME"
echo "=================================="
echo "Model: $(grep '^model' config.toml | head -1 | cut -d'"' -f2)"
echo "Time: $(date)"
echo "=================================="

while true; do
    source venv/bin/activate
    python main.py || true
    deactivate
    echo "Bot exited at $(date), restarting in 5 seconds..."
    sleep 5
done
