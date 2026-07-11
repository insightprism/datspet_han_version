#!/bin/bash

# Start only the ComfyUI engine (the GPU server pet_factory sends its workflows to)

# Default port. Pet Maker port group: 1995x — frontend :19955, backend :19954,
# ComfyUI :19953 (mirrors datsme_me's 19995/19994 frontend/backend convention).
# pet_env.sh points PET_FACTORY_COMFY_URL at this port for the pipeline side.
COMFYUI_PORT=${COMFYUI_PORT:-19953}

# Where ComfyUI is installed (its own venv + models live there, not in this repo).
# Default: peer directory of this repo, i.e. claude_code/ComfyUI.
COMFYUI_DIR=${COMFYUI_DIR:-"$(cd "$(dirname "$0")/.." && pwd)/ComfyUI"}

echo "Starting ComfyUI Engine"
echo "Port: $COMFYUI_PORT"
echo "Install dir: $COMFYUI_DIR"
echo "Web UI will be at: http://localhost:$COMFYUI_PORT"
echo ""

if [ ! -x "$COMFYUI_DIR/venv/bin/python" ]; then
    echo "Cannot start - no ComfyUI venv at $COMFYUI_DIR/venv"
    echo "(Set COMFYUI_DIR if ComfyUI is installed somewhere else)"
    exit 1
fi

# Function to kill ComfyUI on exit
cleanup() {
    echo ""
    echo "Shutting down ComfyUI..."
    exit
}
trap cleanup EXIT

# List PIDs listening on a TCP port. Uses ss (lsof is not installed here).
pids_on_port() {
    ss -ltnpH "sport = :$1" 2>/dev/null | grep -oP 'pid=\K[0-9]+' | sort -u
}

# Check if port is available
PORT_PIDS=$(pids_on_port $COMFYUI_PORT)
if [ -n "$PORT_PIDS" ]; then
    echo "Port $COMFYUI_PORT is already in use"
    echo "Current processes on port $COMFYUI_PORT:"
    ss -ltnp "sport = :$COMFYUI_PORT" 2>/dev/null
    echo ""
    read -p "Kill existing processes? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        # Graceful shutdown FIRST (SIGTERM), then escalate. A hard SIGKILL can
        # land while ComfyUI is mid-write to its output dir and pet_factory's
        # _wait_stable() would then be reading a truncated frame file.
        echo "Stopping processes on port $COMFYUI_PORT (graceful)..."
        kill $PORT_PIDS 2>/dev/null
        for _ in 1 2 3 4 5 6 7 8 9 10; do
            [ -z "$(pids_on_port $COMFYUI_PORT)" ] && break
            sleep 0.5
        done
        STILL=$(pids_on_port $COMFYUI_PORT)
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

echo "Starting ComfyUI..."
echo ""

# Change to the ComfyUI install directory (it resolves models/ relative to cwd)
cd "$COMFYUI_DIR" || exit 1

# Run ComfyUI (foreground; Ctrl+C stops it). Extra args pass through, e.g.
#   ./start_comfyui_only.sh --cuda-device 1
venv/bin/python main.py --listen 127.0.0.1 --port $COMFYUI_PORT "$@"

echo ""
echo "ComfyUI stopped"
