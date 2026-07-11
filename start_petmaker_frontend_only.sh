#!/bin/bash

# Start only the Pet Maker frontend (Next.js on :19955 — maker + pet house pages)

# Default port (Pet Maker port group 1995x: frontend 5, backend 4, ComfyUI 3)
PETMAKER_FRONTEND_PORT=${PETMAKER_FRONTEND_PORT:-19955}

echo "Starting Pet Maker Frontend (Next.js)"
echo "Port: $PETMAKER_FRONTEND_PORT"
echo "URL: http://localhost:$PETMAKER_FRONTEND_PORT"
echo ""

# Function to kill frontend on exit
cleanup() {
    echo ""
    echo "Shutting down frontend..."
    exit
}
trap cleanup EXIT

# List PIDs listening on a TCP port. Uses ss (lsof is not installed here).
pids_on_port() {
    ss -ltnpH "sport = :$1" 2>/dev/null | grep -oP 'pid=\K[0-9]+' | sort -u
}

# Check if port is available
PORT_PIDS=$(pids_on_port $PETMAKER_FRONTEND_PORT)
if [ -n "$PORT_PIDS" ]; then
    echo "Port $PETMAKER_FRONTEND_PORT is already in use"
    echo "Current processes on port $PETMAKER_FRONTEND_PORT:"
    ss -ltnp "sport = :$PETMAKER_FRONTEND_PORT" 2>/dev/null
    echo ""
    read -p "Kill existing processes? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        # Graceful shutdown FIRST (SIGTERM), then escalate. A bare `kill -9`
        # can poison Next's webpack cache mid-flush (see datsme_me's
        # start_frontend_only.sh for the full story).
        echo "Stopping processes on port $PETMAKER_FRONTEND_PORT (graceful)..."
        kill $PORT_PIDS 2>/dev/null
        for _ in 1 2 3 4 5 6 7 8 9 10; do
            [ -z "$(pids_on_port $PETMAKER_FRONTEND_PORT)" ] && break
            sleep 0.5
        done
        STILL=$(pids_on_port $PETMAKER_FRONTEND_PORT)
        if [ -n "$STILL" ]; then
            echo "Still alive after grace period; forcing (SIGKILL)..."
            kill -9 $STILL 2>/dev/null
            sleep 1
        fi
        echo "Port cleared"
    else
        echo "Cannot start - port is busy"
        exit 1
    fi
fi

echo "Starting Next.js dev server..."
echo ""

# Load nvm if available
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"

# Change to web directory
cd "$(dirname "$0")/web" || exit 1

# ---- Self-heal the webpack cache before starting (same guard as datsme) --
WEBPACK_CACHE=".next/cache/webpack"
if compgen -G "$WEBPACK_CACHE/*/*.pack.gz_" > /dev/null 2>&1; then
    echo "Detected orphaned webpack cache temp files from a hard-killed run."
    echo "Clearing $WEBPACK_CACHE to prevent a poisoned-cache blank screen..."
    rm -rf "$WEBPACK_CACHE"
    echo "Webpack cache cleared (next compile will be a clean cold build)."
    echo ""
fi

# Run frontend
npm run dev -- --port $PETMAKER_FRONTEND_PORT

echo ""
echo "Frontend stopped"
