#!/bin/bash
# botctl.sh — Docker-backed control for the single gemmabot IRC identity.
# Usage: ./botctl.sh {start|stop|restart|status|logs}

set -euo pipefail

BOT_DIR="$(cd "$(dirname "$0")" && pwd)"
COMPOSE_FILE="$BOT_DIR/docker-compose.yml"
NAME="gemmabot"

_compose() {
    docker compose -f "$COMPOSE_FILE" "$@"
}

_start() {
    cd "$BOT_DIR"
    touch message_history.json bot.log
    if [ ! -s message_history.json ]; then
        printf '[]\n' > message_history.json
    fi
    _compose up -d --build
    _status
}

_stop() {
    _compose down
    echo "$NAME stopped"
}

_restart() {
    _compose up -d --build --force-recreate
    _status
}

_status() {
    if docker ps --format '{{.Names}}' | grep -qx "$NAME"; then
        docker ps --filter "name=^${NAME}$" --format '{{.Names}} is {{.Status}}'
        return 0
    fi
    echo "$NAME is NOT running"
    return 1
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
    logs|tail)
        _compose logs --tail=100 -f gemmabot
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|logs}"
        exit 1
        ;;
esac
