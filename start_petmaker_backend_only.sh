#!/bin/bash

# Start only the Pet Maker backend (FastAPI on :19954 — generate/job/pets API)
# Needs ComfyUI running first: ./start_comfyui_only.sh

# Default port (Pet Maker port group 1995x: frontend 5, backend 4, ComfyUI 3)
PETMAKER_BACKEND_PORT=${PETMAKER_BACKEND_PORT:-19954}

echo "Starting Pet Maker Backend (FastAPI)"
echo "Port: $PETMAKER_BACKEND_PORT"
echo "API Docs will be at: http://localhost:$PETMAKER_BACKEND_PORT/docs"
echo ""

REPO="$(cd "$(dirname "$0")" && pwd)"
source "$REPO/pet_env.sh"

if [ ! -x "$REPO/.venv/bin/python" ]; then
    echo "Cannot start - no venv at $REPO/.venv (run: python3 -m venv .venv && .venv/bin/pip install -e '.[gpu,examples]' fastapi 'uvicorn[standard]' python-multipart)"
    exit 1
fi

# Warn (don't block) if the ComfyUI engine isn't up yet
if ! curl -s -m 2 "$PET_FACTORY_COMFY_URL/system_stats" >/dev/null; then
    echo "Warning: ComfyUI is not responding — start it with ./start_comfyui_only.sh"
    echo "         (the API will serve existing pets, but generations will fail until the engine is up)"
    echo ""
fi

# Track the GPU-1 ComfyUI we may auto-start below, so it stops with this backend.
GPU1_COMFY_PID=""

# Function to kill backend on exit
cleanup() {
    echo ""
    echo "Shutting down backend..."
    # Stop the second ComfyUI only if WE started it (leave a pre-existing one running).
    if [ -n "$GPU1_COMFY_PID" ] && kill -0 "$GPU1_COMFY_PID" 2>/dev/null; then
        echo "Stopping the GPU 1 ComfyUI (pid $GPU1_COMFY_PID)..."
        kill "$GPU1_COMFY_PID" 2>/dev/null
    fi
    exit
}
trap cleanup EXIT

# List PIDs listening on a TCP port. Uses ss (lsof is not installed here).
pids_on_port() {
    ss -ltnpH "sport = :$1" 2>/dev/null | grep -oP 'pid=\K[0-9]+' | sort -u
}

# Check if port is available
PORT_PIDS=$(pids_on_port $PETMAKER_BACKEND_PORT)
if [ -n "$PORT_PIDS" ]; then
    echo "Port $PETMAKER_BACKEND_PORT is already in use"
    echo "Current processes on port $PETMAKER_BACKEND_PORT:"
    ss -ltnp "sport = :$PETMAKER_BACKEND_PORT" 2>/dev/null
    echo ""
    read -p "Kill existing processes? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        # Graceful shutdown FIRST (SIGTERM), then escalate — a hard kill can
        # orphan a generation mid-run on the GPU.
        echo "Stopping processes on port $PETMAKER_BACKEND_PORT (graceful)..."
        kill $PORT_PIDS 2>/dev/null
        for _ in 1 2 3 4 5 6 7 8 9 10; do
            [ -z "$(pids_on_port $PETMAKER_BACKEND_PORT)" ] && break
            sleep 0.5
        done
        STILL=$(pids_on_port $PETMAKER_BACKEND_PORT)
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

# ---------------------------------------------------------------------------
# Second GPU: auto-start a ComfyUI on GPU 1 for the Motion Lab's 2-GPU dispatch
# (SPEC_MOTION_LAB §13). Skipped if there is no 2nd GPU, if one is already up on
# :19963, or if PET_LAB_GPU1_AUTOSTART=0. It shuts down with this backend (cleanup).
# ---------------------------------------------------------------------------
GPU1_PORT=${COMFYUI_GPU1_PORT:-19963}
GPU_COUNT=$(nvidia-smi --query-gpu=index --format=csv,noheader 2>/dev/null | wc -l)
if [ "${PET_LAB_GPU1_AUTOSTART:-1}" = "1" ] && [ "${GPU_COUNT:-0}" -ge 2 ]; then
    if curl -s -m 2 "http://127.0.0.1:$GPU1_PORT/system_stats" >/dev/null 2>&1; then
        echo "Second ComfyUI (GPU 1) already up on :$GPU1_PORT — the Motion Lab will use it."
    else
        echo "Starting a second ComfyUI on GPU 1 (:$GPU1_PORT) for the Motion Lab..."
        mkdir -p "$REPO/logs"
        COMFYUI_GPU1_PORT=$GPU1_PORT nohup "$REPO/start_comfyui_gpu1.sh" > "$REPO/logs/comfyui_gpu1.log" 2>&1 &
        GPU1_COMFY_PID=$!
        echo "  (pid $GPU1_COMFY_PID - log: logs/comfyui_gpu1.log - loads models on first use)"
    fi
    echo ""
fi

echo "Starting FastAPI backend..."
echo ""

cd "$REPO/webui" || exit 1

# Run backend (foreground; Ctrl+C stops it)
#
# Bind IPv4 loopback 127.0.0.1. On this box /etc/hosts maps "localhost" to
# 127.0.0.1 only (no ::1 entry for the bare name "localhost"), so the frontend's
# http://localhost:PORT fetch() resolves here cleanly. The whole stack — this
# bind, NEXT_PUBLIC_API_URL, DATSPET_PUBLIC_URL, DATSPET_FRONTEND_URL — must use
# the SAME hostname ("localhost" in dev) so the DPP launch cookie (set on the
# frontend host) is sent on API calls; a 127.0.0.1/localhost split would be a
# cross-origin cookie mismatch and the Accept-to-DatsMe button would never show.
PETMAKER_BACKEND_PORT=$PETMAKER_BACKEND_PORT \
    "$REPO/.venv/bin/python" -m uvicorn app:app --host 127.0.0.1 --port $PETMAKER_BACKEND_PORT

echo ""
echo "Backend stopped"
