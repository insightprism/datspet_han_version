#!/bin/bash
# Generate one DatsMe pet bundle locally: ./make_pet.sh "red panda" [-o out.zip]
# Needs ComfyUI running first: ./start_comfyui_only.sh
REPO="$(cd "$(dirname "$0")" && pwd)"
source "$REPO/pet_env.sh"
exec "$REPO/.venv/bin/python" "$REPO/examples/cli.py" "$@"
