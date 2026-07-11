#!/bin/bash

# Start the whole Pet Maker stack in one shot:
#   ComfyUI (:19953) → backend FastAPI (:19954) → frontend Next.js (:19955)
#
# Each service runs via its start_*_only.sh in the background, logging to
# logs/<name>.log. Services already running on their port are left alone
# (so this script is safe to re-run). Ctrl+C stops everything THIS script
# started — pre-existing services are never touched.

# Pet Maker port group 1995x (mirrors datsme_me's 19995/19994 convention):
# frontend ends in 5, backend in 4, ComfyUI takes 3.
COMFYUI_PORT=${COMFYUI_PORT:-19953}
PETMAKER_BACKEND_PORT=${PETMAKER_BACKEND_PORT:-19954}
PETMAKER_FRONTEND_PORT=${PETMAKER_FRONTEND_PORT:-19955}

REPO="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$REPO/logs"
mkdir -p "$LOG_DIR"

# List PIDs listening on a TCP port. Uses ss (lsof is not installed here).
pids_on_port() {
    ss -ltnpH "sport = :$1" 2>/dev/null | grep -oP 'pid=\K[0-9]+' | sort -u
}

STARTED_PGIDS=()
STARTED_NAMES=()

# launch <name> <port> <script> — skip if the port is already served.
# setsid gives each service its own process group so cleanup can signal
# the whole tree (script + python/npm children) in one kill.
launch() {
    local name=$1 port=$2 script=$3
    if [ -n "$(pids_on_port $port)" ]; then
        echo "• $name: already running on :$port — leaving it as is"
        return
    fi
    setsid bash "$REPO/$script" > "$LOG_DIR/$name.log" 2>&1 &
    STARTED_PGIDS+=("$!")
    STARTED_NAMES+=("$name")
    echo "• $name: starting on :$port (log: logs/$name.log)"
}

cleanup() {
    echo ""
    if [ ${#STARTED_PGIDS[@]} -eq 0 ]; then
        exit 0
    fi
    echo "Stopping ${STARTED_NAMES[*]}..."
    # Graceful first (uvicorn, next, and ComfyUI all handle SIGTERM),
    # then force whatever is left after a grace period.
    for pg in "${STARTED_PGIDS[@]}"; do
        kill -TERM -- "-$pg" 2>/dev/null
    done
    sleep 3
    for pg in "${STARTED_PGIDS[@]}"; do
        kill -KILL -- "-$pg" 2>/dev/null
    done
    echo "All stopped."
    exit 0
}
trap cleanup INT TERM

echo "Starting the Pet Maker stack"
echo ""
launch comfyui  "$COMFYUI_PORT"           start_comfyui_only.sh
launch backend  "$PETMAKER_BACKEND_PORT"  start_petmaker_backend_only.sh
launch frontend "$PETMAKER_FRONTEND_PORT" start_petmaker_frontend_only.sh

# wait_ready <name> <url> <timeout_s>
wait_ready() {
    local name=$1 url=$2 timeout=$3 waited=0
    while ! curl -s -m 2 "$url" >/dev/null; do
        sleep 2
        waited=$((waited + 2))
        if [ "$waited" -ge "$timeout" ]; then
            echo "✗ $name not responding after ${timeout}s — check logs/$name.log"
            return 1
        fi
    done
    echo "✓ $name ready"
}

echo ""
echo "Waiting for services (ComfyUI loads ~30s cold)..."
wait_ready comfyui  "http://127.0.0.1:$COMFYUI_PORT/system_stats"        120
wait_ready backend  "http://127.0.0.1:$PETMAKER_BACKEND_PORT/api/pets"    60
wait_ready frontend "http://localhost:$PETMAKER_FRONTEND_PORT/"           90

echo ""
echo "Pet Maker is up:"
echo "  Maker:      http://localhost:$PETMAKER_FRONTEND_PORT"
echo "  Pet house:  http://localhost:$PETMAKER_FRONTEND_PORT/house"
echo "  API docs:   http://localhost:$PETMAKER_BACKEND_PORT/docs"
echo "  ComfyUI:    http://localhost:$COMFYUI_PORT"

if [ ${#STARTED_PGIDS[@]} -eq 0 ]; then
    echo ""
    echo "Everything was already running — nothing to supervise."
    exit 0
fi

echo ""
echo "Press Ctrl+C to stop the services this script started (${STARTED_NAMES[*]})."
wait
