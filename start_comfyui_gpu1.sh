#!/bin/bash

# Start a SECOND ComfyUI pinned to GPU 1, for the Motion Lab's 2-GPU dispatch
# (SPEC_MOTION_LAB). Its own port + output dir so it never collides with the
# primary ComfyUI on :19953 (GPU 0); the Lab load-balances jobs across the two.
#
# The Lab discovers this instance at the conventional :19963 + <ComfyUI>/output_gpu1
# by default, so once this is running the Lab's config shows "GPU 1" as healthy and
# starts using it — no env or backend restart needed. Override with
# PET_LAB_COMFY_URL_2 / PET_LAB_COMFY_OUTPUT_DIR_2 on the backend if you change these.

COMFYUI_PORT=${COMFYUI_GPU1_PORT:-19963}
COMFYUI_DIR=${COMFYUI_DIR:-"$(cd "$(dirname "$0")/.." && pwd)/ComfyUI"}
OUTPUT_DIR="$COMFYUI_DIR/output_gpu1"

if [ ! -x "$COMFYUI_DIR/venv/bin/python" ]; then
    echo "Cannot start - no ComfyUI venv at $COMFYUI_DIR/venv"
    echo "(Set COMFYUI_DIR if ComfyUI is installed somewhere else)"
    exit 1
fi
mkdir -p "$OUTPUT_DIR"

echo "Second ComfyUI — GPU 1"
echo "  Port:       $COMFYUI_PORT"
echo "  GPU:        1  (--cuda-device 1)"
echo "  Output dir: $OUTPUT_DIR"
echo "  Web UI:     http://localhost:$COMFYUI_PORT"
echo ""
echo "The Motion Lab will pick this up automatically (conventional :$COMFYUI_PORT)."
echo "Ctrl+C stops it."
echo ""

cd "$COMFYUI_DIR" || exit 1
exec venv/bin/python main.py --listen 127.0.0.1 --port "$COMFYUI_PORT" \
    --cuda-device 1 --output-directory "$OUTPUT_DIR" "$@"
