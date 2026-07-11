# pet_env.sh — the runtime environment every pet_factory entry point needs.
# Source this (don't execute it): `source "$REPO/pet_env.sh"` after setting REPO.
# Used by make_pet.sh (CLI) and start_webui_only.sh (web UI).
#
# 1) ComfyUI lives as a peer of this repo (claude_code/ComfyUI); factory.py's
#    built-in default output dir is ~/ComfyUI/output, so point it at the real one.
# 2) LD_LIBRARY_PATH points onnxruntime-gpu at the CUDA-12 runtime wheels
#    installed in this repo's .venv (the ComfyUI venv's torch bundles CUDA 13,
#    which onnxruntime-gpu can't use), so the birefnet cutout runs on the GPU
#    (~12x faster than the silent CPU fallback).

export PET_FACTORY_COMFY_OUTPUT="${PET_FACTORY_COMFY_OUTPUT:-$(dirname "$REPO")/ComfyUI/output}"

# 3) Our ComfyUI runs on the Pet Maker port group (:19953 — see start_all.sh),
#    not factory.py's built-in default of :8188.
export PET_FACTORY_COMFY_URL="${PET_FACTORY_COMFY_URL:-http://127.0.0.1:19953}"

# 4) Where generated pets are stored (one folder per pet; the pet house).
#    Default: webui/datspet_output inside the repo (gitignored). To move the
#    collection outside the repo, uncomment + adjust, move the existing
#    folder, and restart the backend:
# export PETMAKER_OUTPUT_DIR="$HOME/datspet_output"

_PF_NV="$REPO/.venv/lib/python3.10/site-packages/nvidia"
export LD_LIBRARY_PATH="$_PF_NV/cublas/lib:$_PF_NV/cudnn/lib:$_PF_NV/cuda_runtime/lib:$_PF_NV/cufft/lib:$_PF_NV/curand/lib:$_PF_NV/cuda_nvrtc/lib:$_PF_NV/nvjitlink/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
unset _PF_NV
