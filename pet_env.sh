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

# ComfyUI's output dir. MUST be absolute — factory.py reads it from a worker
# thread whose CWD is webui/, so a relative value (e.g. a stale "./ComfyUI/
# output" inherited in the env) resolves wrong and every generation fails with
# FileNotFoundError. Derive REPO from this script's own location if unset, and
# always emit an absolute path (ignore any relative inherited value).
if [ -z "${REPO:-}" ]; then
    REPO="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
fi
_PF_COMFY_OUT="${PET_FACTORY_COMFY_OUTPUT:-$(dirname "$REPO")/ComfyUI/output}"
case "$_PF_COMFY_OUT" in
    /*) : ;;                                  # already absolute — keep
    *)  _PF_COMFY_OUT="$(dirname "$REPO")/ComfyUI/output" ;;  # relative → force absolute
esac
export PET_FACTORY_COMFY_OUTPUT="$_PF_COMFY_OUT"
unset _PF_COMFY_OUT

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

# ---------------------------------------------------------------------------
# 5) DatsMe partner integration (DPP). Only needed when running DatsPet as a
#    DatsMe partner app (the /partner/* and /api/datsme/* endpoints). In pure
#    standalone mode none of these are required — the partner surface stays
#    inert (manifest 503s without DATSME_HMAC_SECRET). See
#    docs/SPEC_DATSPET_DPP_INTEGRATION.md.
# ---------------------------------------------------------------------------
# The HMAC secret DatsMe prints ONCE at registration (scripts/register_datspet.sh)
# is a SECRET, so it never lives in this tracked file. Paste it into
# pet_env.local.sh (gitignored, same directory), which is sourced here:
#   export DATSME_HMAC_SECRET="<the once-printed secret>"
# Until it's set, the partner surface is off.
# (Registered 2026-07-11 for partner slug 'datspet'.)
if [ -f "$REPO/pet_env.local.sh" ]; then
    # shellcheck disable=SC1091
    . "$REPO/pet_env.local.sh"
fi

# The partner slug DatsPet registers under (must match the registration --slug).
export DATSME_PARTNER_SLUG="${DATSME_PARTNER_SLUG:-datspet}"

# DatsMe host URLs. BASE = the API the writeback POSTs to; PUBLIC = the
# browser-facing origin the user is redirected back to. Dev defaults:
export DATSME_BASE_URL="${DATSME_BASE_URL:-http://localhost:19994}"
export DATSME_PUBLIC_URL="${DATSME_PUBLIC_URL:-http://localhost:19995}"

# DatsPet's own public URLs. PUBLIC_URL must be reachable BY THE DATSME HOST
# (it fetches the pet bundle server-to-server), and is embedded in the manifest
# + writeback. FRONTEND_URL is where /launch redirects the browser to design.
export DATSPET_PUBLIC_URL="${DATSPET_PUBLIC_URL:-http://localhost:19954}"
export DATSPET_FRONTEND_URL="${DATSPET_FRONTEND_URL:-http://localhost:19955}"

# Optional: show the credit cost on the Accept button before the user commits.
# Set this to the host's credit_pet_design_cost (default 100) so the UI can
# display "(N credits)". Leave unset to omit the number.
# export DATSPET_DESIGN_COST="100"
