#!/bin/bash
# botctl.sh — clean start/stop/restart/status for gemmabot
# Usage: ./botctl.sh {start|stop|restart|status}

set -e

BOT_DIR="$(cd "$(dirname "$0")" && pwd)"
PIDFILE="$BOT_DIR/bot.pid"
LOGFILE="$BOT_DIR/bot.log"
NAME="gemmabot"

_get_pid() {
    local pid=""
    if [ -f "$PIDFILE" ]; then
        pid=$(cat "$PIDFILE" 2>/dev/null || echo "")
        if [ -n "$pid" ] && ps -p "$pid" -o comm= 2>/dev/null | grep -q "[Pp]ython"; then
            echo "$pid"
            return 0
        fi
        # Stale PID file
        rm -f "$PIDFILE"
    fi
    # Fallback: search for running bot
    pid=$(pgrep -f "[Pp]ython.*main\.py" 2>/dev/null | head -1)
    if [ -n "$pid" ]; then
        echo "$pid"
        return 0
    fi
    echo ""
}

_start() {
    local pid
    pid=$(_get_pid)
    if [ -n "$pid" ]; then
        echo "$NAME is already running (PID $pid)"
        return 0
    fi

    cd "$BOT_DIR"
    nohup bash "$BOT_DIR/start_bot.sh" >> "$LOGFILE" 2>&1 &
    local wrapper_pid=$!
    echo "$wrapper_pid" > "$PIDFILE"

    # Wait until python main.py is actually running (up to 10 seconds)
    for i in $(seq 1 20); do
        pid=$(pgrep -f "[Pp]ython.*main\.py" 2>/dev/null | head -1)
        if [ -n "$pid" ]; then
            echo "$NAME started (PID $pid, wrapper $wrapper_pid)"
            return 0
        fi
        sleep 0.5
    done
    echo "Warning: $NAME started but python process not yet visible. Watch $LOGFILE."
}

_stop() {
    local pid wrapper_pid

    # Find the wrapper (start_bot.sh) and pause it so it can't respawn
    wrapper_pid=$(cat "$PIDFILE" 2>/dev/null || echo "")
    if [ -z "$wrapper_pid" ] || ! ps -p "$wrapper_pid" > /dev/null 2>&1; then
        # PID file is stale; find wrapper manually
        wrapper_pid=$(pgrep -f "start_bot\.sh" 2>/dev/null | head -1)
    fi

    # SIGSTOP the wrapper so it can't restart python while we kill it
    if [ -n "$wrapper_pid" ]; then
        kill -SIGSTOP "$wrapper_pid" 2>/dev/null || true
    fi

    # Now kill the python process safely
    pid=$(_get_pid)
    if [ -n "$pid" ]; then
        echo "Stopping $NAME (PID $pid)..."
        kill "$pid" 2>/dev/null || true

        for i in $(seq 1 16); do
            if ! ps -p "$pid" > /dev/null 2>&1; then
                break
            fi
            sleep 0.5
        done

        # Force kill if lingering
        if ps -p "$pid" > /dev/null 2>&1; then
            kill -9 "$pid" 2>/dev/null || true
            sleep 0.5
        fi
    fi

    # Now kill the wrapper for real
    if [ -n "$wrapper_pid" ] && ps -p "$wrapper_pid" > /dev/null 2>&1; then
        kill -SIGTERM "$wrapper_pid" 2>/dev/null || true
        sleep 0.5
        if ps -p "$wrapper_pid" > /dev/null 2>&1; then
            kill -9 "$wrapper_pid" 2>/dev/null || true
        fi
    fi

    # Clean up any orphaned wrappers
    for wpid in $(pgrep -f "start_bot\.sh" 2>/dev/null); do
        kill "$wpid" 2>/dev/null || true
    done

    rm -f "$PIDFILE"
    echo "$NAME stopped"
}

_restart() {
    _stop
    sleep 1
    _start
}

_status() {
    local pid
    pid=$(_get_pid)
    if [ -z "$pid" ]; then
        echo "$NAME is NOT running"
        return 1
    fi
    local uptime_seconds=$(( $(date +%s) - $(ps -o lstart= -p "$pid" 2>/dev/null | date -f - +%s 2>/dev/null || echo $(date +%s)) ))
    echo "$NAME is running (PID $pid, up ~${uptime_seconds}s)"
    return 0
}

case "${1:-status}" in
    start|launch)
        _start
        ;;
    stop|kill)
        _stop
        ;;
    restart|reload)
        _restart
        ;;
    status|info|check)
        _status
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status}"
        exit 1
        ;;
esac
