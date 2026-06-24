#!/bin/bash
# Startup script for the AI bot — auto-restart loop
# Called by botctl.sh; not intended for direct use.
set -e

BOT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOCKDIR="$BOT_DIR/.run.lock"
cd "$BOT_DIR"

if ! mkdir "$LOCKDIR" 2>/dev/null; then
    echo "Another gemmabot launcher is already running; refusing to start a duplicate."
    exit 1
fi
trap 'rmdir "$LOCKDIR" 2>/dev/null || true' EXIT

echo "🤖 Starting $NAME"
echo "=================================="
echo "Model: $(grep '^model' config.toml | head -1 | cut -d'"' -f2)"
echo "Time: $(date)"
echo "=================================="

while true; do
    source venv/bin/activate
    python "$BOT_DIR/main.py" || true
    deactivate
    echo "Bot exited at $(date), restarting in 5 seconds..."
    sleep 5
done
