"""pet_factory.factory — turn an animal name into a ready-to-use DatsMe pet.

    from pet_factory import make_pet_zip
    breed_id, zip_bytes = make_pet_zip("red panda")
    open(f"{breed_id}.zip", "wb").write(zip_bytes)   # -> a DatsMe pet bundle

The .zip is a DatsMe "breed bundle" (sprite sheet + manifest.json + package.json)
— exactly the shape DatsMe's `POST /api/pets/me/upload` accepts. See README.

Pipeline (all local on a CUDA GPU box running ComfyUI):
    animal -> Z-Image base sprite (side profile, facing right)
           -> Wan 2.2 I2V walk loop + idle loop (from the same base sprite)
           -> birefnet background removal (GPU) -> packed DatsMe .zip

Config via environment variables (all optional):
    PET_FACTORY_COMFY_URL     ComfyUI base URL         (default http://127.0.0.1:8188)
    PET_FACTORY_COMFY_OUTPUT  ComfyUI's output dir     (default ~/ComfyUI/output)
The factory reads generated files from ComfyUI's output dir, so it must run on
the same machine as ComfyUI (shared filesystem).
"""
import io
import json
import os
import gc
import random
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
import zipfile
from collections import deque
from pathlib import Path

import logging

import numpy as np
import requests
from PIL import Image, ImageSequence

from . import motion_profiles as mp
from . import prompt_templates

log = logging.getLogger(__name__)

# ── Config ───────────────────────────────────────────────────────────────────
COMFY_URL = os.environ.get("PET_FACTORY_COMFY_URL", "http://127.0.0.1:8188").rstrip("/")
# Resolve to an ABSOLUTE path: this dir is read from a worker thread whose CWD
# may differ from where the value was set (e.g. a relative "./ComfyUI/output"
# from a mis-sourced env would otherwise resolve against the backend's CWD and
# fail to find ComfyUI's real output). expanduser handles "~"; resolve() makes
# any relative value absolute against CWD at import time.
COMFY_OUTPUT_DIR = Path(os.path.expanduser(os.environ.get(
    "PET_FACTORY_COMFY_OUTPUT", "~/ComfyUI/output"))).resolve()
CLIENT_ID = uuid.uuid4().hex
VIDEO_EXTS = {".mp4", ".webm", ".mov", ".mkv", ".avi"}

# Model filenames as they appear in ComfyUI's models/ folders. The GPU box must
# have these installed (see README "Requirements").
ZIMAGE_UNET = "zImageTurbo_turbo.safetensors"
ZIMAGE_VAE = "zimage_ae.safetensors"
ZIMAGE_TE = "qwen_3_4b_fp8.safetensors"
WAN_UNET_HIGH = "wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors"
WAN_UNET_LOW = "wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors"
WAN_VAE = "wan_2.1_vae.safetensors"           # 14B I2V uses the Wan 2.1 VAE
WAN_TE = "umt5_xxl_fp8_e4m3fn_scaled.safetensors"
WAN_LORA_HIGH = "wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors"
WAN_LORA_LOW = "wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors"

# Every sampler below runs at cfg 1.0, because both models are distilled (Z-Image-Turbo
# 8-step, Wan + LightX2V 4-step LoRA) and are trained for it. At cfg 1.0 classifier-free
# guidance degenerates to `output = positive` and the negative conditioning cancels out
# entirely. MEASURED, not assumed (2026-07-26): one seed, one positive, three negatives —
# the authored one, empty, and one listing the subject itself — produced byte-identical
# PIXELS, while changing the positive changed them. So there is no negative prompt here;
# the graph still requires the input, and this is it. `test_samplers_run_at_cfg_one`
# fails if a future model raises cfg, which is when a negative would start mattering again.
CFG_DISABLES_NEGATIVE = 1.0
INERT_NEGATIVE = ""

# The seed the pose_prompt ANCHOR (and its loop) is drawn at — FIXED, not the build's
# random per-run seed. The Motion Lab authors pose clauses at this same seed
# (motion_lab._DEFAULT_SEED), so "looks good in the Lab" reproduces in the build: a subtle
# clause (a bird's mid-stride walk) that only reads at one seed would otherwise land as a
# standing bird under the build's random seed. The BASE sprite keeps the random seed — its
# variety is wanted, and for designer pets the base is the locked reference anyway.
_ANCHOR_SEED = 42

# Motion wording is now content, not code: each pose's action+suffix lives in the
# motion_profiles/*.json files and is composed by motion_profiles.compose_pose_prompt.
# The former WALK_SUFFIX/IDLE_SUFFIX constants were removed — quadruped.json carries
# their exact wording, and tests/test_motion_profiles.py pins it byte-for-byte (§6).

# ── GPU memory hygiene (SPEC_GPU_MEMORY_HYGIENE) ─────────────────────────────────────────
# Every value here is MEASURED, not chosen — §2.6 of that spec is the sweep that produced
# them, run against this repo's onnxruntime 1.23.2 / rembg 2.0.69 on a 3090. Re-measure (≥3
# frames — the arena's high-water lands on the SECOND inference, not the first) before
# changing any of them, and re-measure whenever the cutout model changes.

# The CUDA device the cutout runs on. Also the `/system_stats` device SELECTOR: a 2-GPU box
# reports both cards, and this need not be ComfyUI's primary device (§5.2).
_CUTOUT_DEVICE_ID = 0

# birefnet's measured working set. §2.6: 4 GiB fails outright (ORT raises on a single 822 MB
# activation in the ASPP decoder block); 6 GiB is the smallest cap measured to pass. 7 GiB is
# that floor plus headroom, and it costs nothing — peak is identical at 7 GiB and at 10 GiB.
# Input-size-independent: rembg normalizes every frame to birefnet's 1024² graph, so one value
# holds for every pet. F1 (deferred) will pass this as the ORT arena's `gpu_mem_limit`.
_CUTOUT_WORKING_SET_BYTES = 7 * 1024**3

# The CUDA context lives OUTSIDE the ORT arena (measured 264 MiB bare, 526–554 MiB with the
# session loaded), so a process's VRAM total can legitimately exceed the working set. Anything
# comparing measured peak against the budget must allow this much (§2.5).
_CUTOUT_PEAK_TOLERANCE_BYTES = 1 * 1024**3

# Opaque fallback frames tolerated in a build: NONE. One opaque frame in a walk cycle is a
# visible white flash, so there is no threshold worth tuning — the name exists to make the
# decision visible and revisitable, not because a nonzero value is expected (§3.2).
_CUTOUT_MAX_FALLBACK_FRAMES = 0

# The free-VRAM watermark that means ComfyUI's eviction actually landed. Derived from the
# REQUIREMENT (the cutout must fit), never from an observation of current free VRAM — a
# watermark read off today's behavior would certify whatever it found, including a broken
# eviction (§5.2).
_FREE_TARGET_VRAM_BYTES = _CUTOUT_WORKING_SET_BYTES + _CUTOUT_PEAK_TOLERANCE_BYTES
_FREE_POLL_TIMEOUT_S = 20        # bounded wait, replaces a blind sleep(1.5) that verified nothing
_FREE_POLL_INTERVAL_S = 0.5      # poll cadence
_COMFY_HTTP_TIMEOUT_S = 10       # per-request timeout for the eviction POST and each stats read


class CutoutFailed(RuntimeError):
    """The birefnet matte failed on a frame, so this build has no transparent sprite to ship
    (SPEC_GPU_MEMORY_HYGIENE §3).

    Raised in place of the historical silent fallback to a fully-opaque alpha. The product IS
    the transparency — an opaque sprite is unusable in DatsMe — so a failed matte is a FAILED
    build, not a degraded one. The old fallback also made every other measurement in the
    pipeline untrustworthy: a build that silently shipped a white rectangle reported the same
    `done` at progress 1.0 as a perfect one."""

    def __init__(self, pose_name, frame_index, cause):
        self.pose_name = pose_name
        self.frame_index = frame_index
        self.cause = cause
        super().__init__(
            f"birefnet cutout failed on pose {pose_name!r} frame {frame_index} "
            f"({type(cause).__name__}: {cause}) — refusing to ship an opaque sprite")


# ── birefnet cutout session — single-instance, GPU-bounded lifetime ─────────────────────
# onnxruntime's CUDA arena NEVER returns memory to the GPU while the session lives (it
# caches for reuse), so a persistent global session permanently holds its high-water-mark
# footprint — measured ~6–15 GB depending on how much was free when the arena grew — and
# starves the NEXT build's Wan generation on the same 24 GB card. The permanent fix is to
# make the cutout session a MANAGED, single-instance resource that dies when its work ends:
#   • created lazily on a build's cutout, with the GPU-node fail-fast (§4.B item A);
#   • DESTROYED the instant that cutout finishes (make_pet_zip's finally → release()),
#     returning the arena to the GPU — verified empirically: 6.4 GB → 0.26 GB after gc;
#   • killed by an idle watchdog after IDLE_TIMEOUT_S if a release was ever missed (a crash,
#     or a caller that used pack_datsme_bundle directly), so the GPU is never held idle.
# A lock serialises create/get/destroy: there is only ever ONE session, and the watchdog
# can't reclaim it mid-cutout (every frame's get() bumps the idle clock).
class _CutoutSession:
    IDLE_TIMEOUT_S = 300   # kill an idle cutout session after 5 min (the safety net)
    _POLL_S = 30           # how often the watchdog checks (a knob so tests can run it fast)

    def __init__(self):
        self._lock = threading.RLock()
        self._session = None
        self._last_used = 0.0
        self._watchdog = None

    def _new_session(self):
        """Build the birefnet session + the GPU-node fail-fast. Prefers CUDA (~12x faster). On a
        declared GPU node (PET_FACTORY_REQUIRE_GPU=1) a SILENT CPU fallback is a misconfiguration
        that blows the pool watchdog (2026-07-21 incident; shared_gpu_cpu §4.B) — onnxruntime
        drops a provider it can't load without raising, so we inspect the ACTUAL providers and
        fail fast HERE, once, never inside prep()'s per-frame try/except. CPU-only nodes keep the
        graceful fallback."""
        import onnxruntime as ort
        try:
            # onnxruntime 1.22+ ships CUDA/cuDNN as separate nvidia-*-cu12 wheels but does NOT add
            # them to the loader path on import — without this preload the CUDA provider .so can't
            # dlopen libcublasLt.so.12 etc. and silently falls back to CPU (§4.A). Harmless on CPU.
            ort.preload_dlls()
        except Exception:
            pass
        from rembg import new_session
        session = new_session("birefnet-general-lite",
                              providers=["CUDAExecutionProvider", "CPUExecutionProvider"])
        providers = session.inner_session.get_providers()
        print(f"[pet_factory] rembg providers: {providers}", flush=True)
        require_gpu = os.environ.get("PET_FACTORY_REQUIRE_GPU", "").strip() in ("1", "true", "on")
        if require_gpu and "CUDAExecutionProvider" not in providers:
            raise RuntimeError(
                f"birefnet CUDA provider failed to load on a GPU node (providers={providers}); "
                "check onnxruntime CUDA libs, e.g. libcublasLt.so.12 — refusing to run the cutout "
                "on CPU where it would exceed the pool watchdog")
        return session

    def get(self):
        """The live cutout session, created on first use (fail-fast on a mis-set GPU node).
        Bumps the idle clock so the watchdog never reclaims a session mid-cutout."""
        with self._lock:
            if self._session is None:
                self._session = self._new_session()   # may raise (fail-fast) — stays None then
                self._start_watchdog()
            self._last_used = time.time()
            return self._session

    def release(self):
        """Destroy the session NOW and hand its GPU memory back (onnxruntime frees the CUDA
        arena when the session is GC'd). Called the instant a build's cutout finishes; a no-op
        if none exists. The lock makes it safe against the watchdog and a concurrent get()."""
        with self._lock:
            if self._session is not None:
                self._session = None
                gc.collect()

    def _start_watchdog(self):
        if self._watchdog is None or not self._watchdog.is_alive():
            self._watchdog = threading.Thread(
                target=self._watch, name="cutout-idle-watchdog", daemon=True)
            self._watchdog.start()

    def _watch(self):
        while True:
            time.sleep(self._POLL_S)
            with self._lock:
                if (self._session is not None
                        and time.time() - self._last_used >= self.IDLE_TIMEOUT_S):
                    self._session = None
                    gc.collect()


_CUTOUT = _CutoutSession()


def _rembg():
    """The live birefnet session (see _CutoutSession) — a thin accessor so the fail-fast
    contract and its tests read the same as before the session became managed."""
    return _CUTOUT.get()


def _remove_bg(img: Image.Image) -> Image.Image:
    from rembg import remove
    return remove(img.convert("RGB"), session=_CUTOUT.get())


# Subject-crop geometry (SPEC_UPLOAD_LIKENESS §2.2). Tuned so a cropped subject
# still DOMINATES the frame — a 0.85-denoise redraw follows composition, so the
# subject filling the frame is the entire point.
_CROP_MARGIN = 0.05      # per side, as a fraction of the bbox. 5% keeps subject ≥ ~82% of
                         # the result; the spec's illustrative "~8%" would drop that to ~74%.
_CROP_MIN_FRAC = 0.05    # bbox area below this fraction of the frame → too small; upscaling
                         # a sub-5%-area crop toward 1024 turns it to mush. Return the input.
_CROP_MAX_FRAC = 0.95    # bbox already fills the frame → the crop is a no-op; skip the work.


def _crop_to_subject(rgba: Image.Image) -> Image.Image:
    """Crop an RGBA image to its alpha bounding box plus a margin — or return it
    UNCHANGED in every failure case (SPEC_UPLOAD_LIKENESS §2.2).

    Pure PIL, no GPU, no ML import: the failure rules live here precisely so they
    are testable on this repo's no-GPU test gate (§7). It never composites and
    never pads — `_prep_reference_image`'s tail already does both, so "return the
    input" makes the caller byte-identical to today by construction.

    Returns the input OBJECT (identity) on every non-crop path, so a guard test can
    assert `result is rgba`.
    """
    w, h = rgba.size
    bbox = rgba.getchannel("A").getbbox()      # alpha bounds, or None if fully transparent
    if bbox is None:
        return rgba                            # nothing found — a wall, a screenshot
    left, top, right, bottom = bbox
    frac = ((right - left) * (bottom - top)) / (w * h or 1)
    if frac < _CROP_MIN_FRAC:
        return rgba                            # too small — a tiny crop upscaled to 1024 is mush
    if frac > _CROP_MAX_FRAC:
        return rgba                            # already fills the frame — nothing to gain
    mx = round((right - left) * _CROP_MARGIN)
    my = round((bottom - top) * _CROP_MARGIN)
    box = (max(0, left - mx), max(0, top - my), min(w, right + mx), min(h, bottom + my))
    return rgba.crop(box)


# ── ComfyUI workflows ────────────────────────────────────────────────────────

def _static_image_wf(prompt, seed):
    """Z-Image-Turbo text-to-image (1024², 8-step turbo, CFG 1.0)."""
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": ZIMAGE_UNET, "weight_dtype": "default"}},
        "2": {"class_type": "VAELoader", "inputs": {"vae_name": ZIMAGE_VAE}},
        "3": {"class_type": "CLIPLoader", "inputs": {"clip_name": ZIMAGE_TE, "type": "lumina2"}},
        "4": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["1", 0], "shift": 3.0}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["3", 0], "text": prompt}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["3", 0], "text": INERT_NEGATIVE}},
        "8": {"class_type": "EmptySD3LatentImage", "inputs": {"width": 1024, "height": 1024, "batch_size": 1}},
        "9": {"class_type": "KSampler", "inputs": {
            "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["8", 0],
            "seed": seed, "steps": 8, "cfg": CFG_DISABLES_NEGATIVE, "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}},
        "10": {"class_type": "VAEDecode", "inputs": {"samples": ["9", 0], "vae": ["2", 0]}},
        "11": {"class_type": "SaveImage", "inputs": {"images": ["10", 0], "filename_prefix": "petfactory_still"}},
    }


def _img2img_wf(prompt, image_path, seed, denoise=0.6):
    """Z-Image-Turbo image-to-image (pet remix): redraw an existing sprite
    toward a new description while keeping its overall shape and identity.
    `denoise` is how far to drift from the source (0.45 subtle recolor …
    0.8 near-redesign); at 1.0 the source image would be ignored entirely."""
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": ZIMAGE_UNET, "weight_dtype": "default"}},
        "2": {"class_type": "VAELoader", "inputs": {"vae_name": ZIMAGE_VAE}},
        "3": {"class_type": "CLIPLoader", "inputs": {"clip_name": ZIMAGE_TE, "type": "lumina2"}},
        "4": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["1", 0], "shift": 3.0}},
        "5": {"class_type": "VHS_LoadImagePath", "inputs": {"image": image_path, "custom_width": 1024, "custom_height": 1024}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["3", 0], "text": prompt}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["3", 0], "text": INERT_NEGATIVE}},
        "8": {"class_type": "VAEEncode", "inputs": {"pixels": ["5", 0], "vae": ["2", 0]}},
        "9": {"class_type": "KSampler", "inputs": {
            "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["8", 0],
            "seed": seed, "steps": 8, "cfg": CFG_DISABLES_NEGATIVE, "sampler_name": "euler", "scheduler": "simple", "denoise": denoise}},
        "10": {"class_type": "VAEDecode", "inputs": {"samples": ["9", 0], "vae": ["2", 0]}},
        "11": {"class_type": "SaveImage", "inputs": {"images": ["10", 0], "filename_prefix": "petfactory_remix"}},
    }


def _loop_wf(prompt, start_image_path, seed, length=17, fps=16, width=704, height=704):
    """Wan 2.2-I2V-14B looping sprite (two-expert MoE + LightX2V 4-step LoRA).
    Same image as first AND last frame -> seamless loop. Saved as animated WebP."""
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": WAN_UNET_HIGH, "weight_dtype": "default"}},
        "2": {"class_type": "UNETLoader", "inputs": {"unet_name": WAN_UNET_LOW, "weight_dtype": "default"}},
        "3": {"class_type": "CLIPLoader", "inputs": {"clip_name": WAN_TE, "type": "wan"}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": WAN_VAE}},
        "5": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["1", 0], "lora_name": WAN_LORA_HIGH, "strength_model": 1.0}},
        "6": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["2", 0], "lora_name": WAN_LORA_LOW, "strength_model": 1.0}},
        "7": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["5", 0], "shift": 8.0}},
        "8": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["6", 0], "shift": 8.0}},
        "9": {"class_type": "VHS_LoadImagePath", "inputs": {"image": start_image_path, "custom_width": 0, "custom_height": 0}},
        "10": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["3", 0], "text": prompt}},
        "11": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["3", 0], "text": INERT_NEGATIVE}},
        "12": {"class_type": "WanFirstLastFrameToVideo", "inputs": {
            "positive": ["10", 0], "negative": ["11", 0], "vae": ["4", 0],
            "width": width, "height": height, "length": length, "batch_size": 1,
            "start_image": ["9", 0], "end_image": ["9", 0]}},
        "13": {"class_type": "KSamplerAdvanced", "inputs": {
            "model": ["7", 0], "add_noise": "enable", "noise_seed": seed, "steps": 4, "cfg": CFG_DISABLES_NEGATIVE,
            "sampler_name": "euler", "scheduler": "simple", "positive": ["12", 0], "negative": ["12", 1],
            "latent_image": ["12", 2], "start_at_step": 0, "end_at_step": 2, "return_with_leftover_noise": "enable"}},
        "14": {"class_type": "KSamplerAdvanced", "inputs": {
            "model": ["8", 0], "add_noise": "disable", "noise_seed": seed, "steps": 4, "cfg": CFG_DISABLES_NEGATIVE,
            "sampler_name": "euler", "scheduler": "simple", "positive": ["12", 0], "negative": ["12", 1],
            "latent_image": ["13", 0], "start_at_step": 2, "end_at_step": 4, "return_with_leftover_noise": "disable"}},
        "15": {"class_type": "VAEDecode", "inputs": {"samples": ["14", 0], "vae": ["4", 0]}},
        "16": {"class_type": "SaveAnimatedWEBP", "inputs": {
            "images": ["15", 0], "filename_prefix": "petfactory_loop", "fps": float(fps),
            "lossless": False, "quality": 90, "method": "default"}},
    }


def _run(wf: dict, timeout: int = 360) -> str:
    """Queue a workflow on ComfyUI, wait for it, return the output filename."""
    r = requests.post(f"{COMFY_URL}/prompt", json={"prompt": wf, "client_id": CLIENT_ID}, timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f"ComfyUI rejected workflow: {r.text[:200]}")
    pid = r.json()["prompt_id"]
    t0 = time.time()
    while time.time() - t0 < timeout:
        h = requests.get(f"{COMFY_URL}/history/{pid}", timeout=10).json()
        for o in h.get(pid, {}).get("outputs", {}).values():
            picks = (o.get("gifs") or []) + (o.get("images") or [])
            if picks:
                return picks[0]["filename"]
        time.sleep(1.5)
    raise TimeoutError("ComfyUI generation timed out")


def _mib(n) -> str:
    """Bytes as a MiB string for logs; `None` (unreadable) stays visibly unknown rather
    than silently becoming 0."""
    return "unknown" if n is None else f"{n // (1024 * 1024)} MiB"


def _comfy_vram_free(device_id: int = _CUTOUT_DEVICE_ID):
    """Free VRAM in bytes on `device_id` as ComfyUI reports it, or None if unreadable.

    Selects the device by its `index`, NOT `devices[0]` (SPEC_GPU_MEMORY_HYGIENE §5.2). A
    2-GPU box reports BOTH cards, and the card we care about is the one the CUTOUT runs on —
    which need not be ComfyUI's primary device. ComfyUI happens to sort its primary first
    today, so devices[0] would usually work; relying on that would silently couple the cutout's
    device to ComfyUI's, which is exactly the coupling a per-card build fan-out has to break."""
    try:
        stats = requests.get(f"{COMFY_URL}/system_stats", timeout=_COMFY_HTTP_TIMEOUT_S).json()
    except Exception:
        return None
    for dev in stats.get("devices", []):
        if dev.get("index") == device_id:
            return dev.get("vram_free")
    return None


def _evict_comfy_models_for_cutout():
    """Ask ComfyUI to drop its Wan models, then VERIFY the eviction actually landed
    (SPEC_GPU_MEMORY_HYGIENE §5).

    ComfyUI's `/free` only sets a flag on its prompt queue and returns 200 **unconditionally**
    — the real `unload_all_models()` runs later, on the prompt worker. So neither the 200 nor
    the fixed `sleep(1.5)` this replaced carried any information: an unreachable endpoint, a
    200 that unloaded nothing, and a real eviction all looked identical in the log. Poll
    `/system_stats` until the cutout's budget fits, and say what happened either way.

    Measured against the live instance 2026-07-26: 5535 MiB free → 23874 MiB in 0.5 s, i.e.
    ~18 GB reclaimed, one poll interval. The `sleep(1.5)` was 3x longer than needed AND proved
    nothing; this is shorter AND says what happened.

    NEVER raises, and never gates the build (§0.5): a stubborn cache or a stopped ComfyUI is a
    logged WARNING, not a failed pet. Missing the target does not mean the cutout will fail —
    free VRAM on this box also moves with processes we do not control (a foreign job was seen
    holding 23 GB of cuda:0), and `/free` cannot reclaim what ComfyUI never held. So the honest
    posture is: try, report, continue, and let F2 raise a REAL error if the cutout actually
    dies. A pre-emptive abort here would fail builds that would have succeeded."""
    started = time.time()
    before = _comfy_vram_free()
    try:
        requests.post(f"{COMFY_URL}/free", json={"unload_models": True, "free_memory": True},
                      timeout=_COMFY_HTTP_TIMEOUT_S)
    except Exception as e:
        log.warning("ComfyUI /free unreachable (%s: %s) — proceeding to the cutout unevicted",
                    type(e).__name__, e)

    # Start the poll budget HERE, not at `started`: the two hops above (the `before` read and
    # the POST) can each burn a full _COMFY_HTTP_TIMEOUT_S, so a `started`-based deadline is
    # already blown by the time we get here — and the loop then never re-reads at all. That
    # fails exactly when a sluggish ComfyUI makes the read-back most valuable. `started` still
    # measures the whole operation for the report below.
    deadline = time.time() + _FREE_POLL_TIMEOUT_S
    after = _comfy_vram_free()
    while (after is None or after < _FREE_TARGET_VRAM_BYTES) and time.time() < deadline:
        time.sleep(_FREE_POLL_INTERVAL_S)
        after = _comfy_vram_free()

    landed = after is not None and after >= _FREE_TARGET_VRAM_BYTES
    report = log.info if landed else log.warning
    report("ComfyUI eviction %s: vram_free %s → %s (target %s) after %.1fs",
           "landed" if landed else "did NOT reach the target, proceeding anyway",
           _mib(before), _mib(after), _mib(_FREE_TARGET_VRAM_BYTES), time.time() - started)


def _wait_stable(path: Path, tries: int = 30):
    """Wait until the file size stops changing (guards against reading a file
    another process is still writing/re-encoding)."""
    last = -1
    for _ in range(tries):
        if path.exists():
            sz = path.stat().st_size
            if sz > 0 and sz == last:
                return
            last = sz
        time.sleep(0.4)


def _frames_rgba(path: Path) -> list:
    """Decode a webp/gif/video output into a list of RGBA frames."""
    _wait_stable(path)
    last_err = None
    for _ in range(6):
        try:
            if path.suffix.lower() in VIDEO_EXTS:
                tmp = Path(tempfile.mkdtemp(prefix="pff_"))
                try:
                    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(path),
                                    str(tmp / "f_%05d.png")], check=True)
                    return [Image.open(p).convert("RGBA") for p in sorted(tmp.glob("f_*.png"))]
                finally:
                    shutil.rmtree(tmp, ignore_errors=True)
            im = Image.open(path)
            return [fr.convert("RGBA") for fr in ImageSequence.Iterator(im)]
        except Exception as e:
            last_err = e
            time.sleep(0.6)
    raise last_err


def _fill_holes_alpha(alpha: Image.Image, thr: int = 160) -> Image.Image:
    """Make interior transparent regions (low alpha NOT connected to the image
    border) fully opaque — closes any hole the matting model punches inside the
    animal. Real background (reachable from the border) stays transparent."""
    a = np.array(alpha.convert("L"))
    h, w = a.shape
    transp = a < thr
    reached = np.zeros((h, w), bool)
    dq = deque()
    for x in range(w):
        for y in (0, h - 1):
            if transp[y, x] and not reached[y, x]:
                reached[y, x] = True; dq.append((y, x))
    for y in range(h):
        for x in (0, w - 1):
            if transp[y, x] and not reached[y, x]:
                reached[y, x] = True; dq.append((y, x))
    while dq:
        y, x = dq.popleft()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and transp[ny, nx] and not reached[ny, nx]:
                reached[ny, nx] = True; dq.append((ny, nx))
    holes = transp & ~reached
    if holes.any():
        a = a.copy()
        a[holes] = 255
    return Image.fromarray(a, "L")


def _fit_square(img: Image.Image, size: int) -> Image.Image:
    """Scale-to-fit into a transparent size×size cell, centered (keeps aspect)."""
    img = img.convert("RGBA")
    w, h = img.size
    scale = size / max(w, h)
    nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
    img = img.resize((nw, nh), Image.LANCZOS)
    cell = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    cell.paste(img, ((size - nw) // 2, (size - nh) // 2), img)
    return cell


def _slug(animal: str) -> str:
    s = "_".join(animal.lower().split())
    return ("".join(c for c in s if c.isalnum() or c in "_-")[:40]) or "pet"


def _prep_reference_image(src, *, isolate: bool = False) -> Path:
    """Normalize a caller-supplied reference image for the Wan I2V stage:
    flatten any transparency onto white and pad to a square canvas (the video
    canvas is square; padding preserves the animal's proportions where
    stretching would distort them). Returns the path of a PNG that ComfyUI can
    load. `src` is a path or anything PIL.Image.open accepts.

    isolate (SPEC_UPLOAD_LIKENESS §2.2): when True, cut the subject out of its
    background and crop to it BEFORE the flatten+pad — so an uploaded photo of a
    dog-in-a-garden redraws as a dog, not a garden. OFF by default and opt-in per
    call (never sniffed): step 2's preview reference is already a clean sprite,
    where a cutout is wasted work and a real risk of eating the subject. Only the
    upload door passes isolate=True.

    A cutout FAILURE — including `_remove_bg` raising on a GPU-required node whose
    CUDA provider didn't load (the 2026-07-21 watchdog incident, factory.py:107) —
    degrades to the raw photo. Lever B is the first thing to put rembg on the
    upload door; without this catch a misconfigured node would turn a working door
    into a broken one. The eager build-time fail-fast (make_pet_zip) stays loud;
    the door degrades quiet. Both are correct in their own place.
    """
    img = Image.open(src).convert("RGBA")
    if isolate:
        try:
            img = _crop_to_subject(_remove_bg(img).convert("RGBA"))
        except Exception as e:
            print(f"[pet_factory] subject isolation failed, using the raw photo: {e!r}",
                  flush=True)
    side = max(img.size)
    canvas = Image.new("RGBA", (side, side), (255, 255, 255, 255))
    canvas.paste(img, ((side - img.width) // 2, (side - img.height) // 2), img)
    fd, out = tempfile.mkstemp(prefix="pf_ref_", suffix=".png")
    os.close(fd)
    canvas.convert("RGB").save(out, "PNG")
    return Path(out)


# The two still templates live in the pure `prompt_templates` module so the GPU-less
# web tier can read them for the admin's prompt preview without importing this module
# (numpy/PIL at the top). These stay the generation-side entry points; the sentences
# themselves have exactly one definition.
_base_prompt = prompt_templates.base_still_prompt
_remix_prompt = prompt_templates.remix_still_prompt


# The historical sheet-level view — the constants the packer emitted before view
# became profile data (SPEC_BUNDLE_MOTION_CONTRACT §3.3). The fallback when a
# profile (or a direct caller) supplies no view, so output stays byte-identical
# for the default case.
_DEFAULT_VIEW = {"view_kind": "side", "native_facing": "right", "mirroring_policy": "flip"}


def pack_datsme_bundle(pose_frames, breed_id, display_name,
                       frame_size=256, columns=8, fps=12,
                       pose_meta=None, movement_class="mammalian_quadruped",
                       view=None, on_frame=None) -> bytes:
    """Pack an ordered {pose_name: frame_list} dict into a DatsMe breed bundle
    (.zip bytes): a transparent sprite sheet + manifest.json + package.json.

    Each frame is background-removed (birefnet) and fit into a square cell. Each
    pose occupies its own row-band on the sheet (the next pose always starts on a
    fresh grid row), so frame indices never straddle two animations.

    `pose_meta` is {pose_name: {runtime_role, loop, timed_buffer_ms, view}} — the
    per-animation metadata the host reads (SPEC_BUNDLE_MOTION_CONTRACT §3). Every
    key is optional: `loop` defaults True, `timed_buffer_ms` is emitted only when
    present, and `view` falls back to the sheet-level `view` block. `view` is the
    profile-level view ({view_kind, native_facing, mirroring_policy}); absent, the
    historical side/right/flip constants apply, so output is unchanged for callers
    that pass neither. Returns the .zip bytes — post it to /api/pets/me/upload."""
    pose_meta = pose_meta or {}
    sheet_view = view or _DEFAULT_VIEW
    _CUTOUT.get()   # create the cutout session + GPU-node fail-fast HERE (§4.B item A), before
                    # the loop — never inside prep()'s per-frame try/except which would swallow it.
    total_frames = sum(len(f) for f in pose_frames.values()) or 1
    done_frames = 0
    # BUILD-wide, deliberately outside prep(): _CUTOUT_MAX_FALLBACK_FRAMES is a budget for the
    # whole bundle, and prep() runs once PER POSE. Scoped inside, a tolerance of N would silently
    # mean N *per pose* — up to 8N opaque frames in an 8-pose build — which is not what the
    # constant says. Invisible at today's value of 0; a trap the moment anyone raises it.
    fallbacks = 0

    def prep(pose_name, frames):
        nonlocal done_frames, fallbacks
        out = []
        for i, fr in enumerate(frames):
            orig = fr.convert("RGB")
            try:
                a = _remove_bg(orig).convert("RGBA").split()[3]     # birefnet alpha matte
            except Exception as e:
                # A per-frame raise from a PIL RGB input means the SESSION is broken (a CUDA
                # OOM, a provider that failed to load), not that one frame is odd. There is no
                # realistic transient here, and spending GPU time on the remaining ~127 frames
                # after the session dies is waste — so fail the build (§3.2).
                fallbacks += 1
                if fallbacks > _CUTOUT_MAX_FALLBACK_FRAMES:
                    log.error("cutout failed on pose %r frame %d (%s: %s) — failing the build "
                              "instead of shipping an opaque sprite",
                              pose_name, i, type(e).__name__, e)
                    raise CutoutFailed(pose_name, i, e) from e
                log.warning("cutout fell back to an opaque alpha on pose %r frame %d (%s: %s) — "
                            "%d/%d tolerated", pose_name, i, type(e).__name__, e,
                            fallbacks, _CUTOUT_MAX_FALLBACK_FRAMES)
                a = Image.new("L", orig.size, 255)
            result = orig.convert("RGBA")
            result.putalpha(a)                                     # original colors + matte
            cell = _fit_square(result, frame_size)
            cell.putalpha(_fill_holes_alpha(cell.split()[3]))      # close interior holes
            out.append(cell)
            done_frames += 1
            if on_frame:                                           # B: per-frame progress so the
                on_frame(done_frames, total_frames)                # bar moves + the stall timer resets
        return out

    # Lay each pose on its own row band; compute its frame indices. Preserves the
    # original walk-row-0 / idle-fresh-row layout when the dict is {walk, idle}.
    placed = []          # (pose_name, [cells], [indices])
    cursor = 0
    animations = {}
    for name, frames in pose_frames.items():
        cells = prep(name, frames)
        start = ((cursor + columns - 1) // columns) * columns      # next pose starts on a new row
        idx = list(range(start, start + len(cells)))
        placed.append((name, cells, idx))
        meta = pose_meta.get(name) or {}
        entry = {"frames": idx, "fps": fps, "loop": bool(meta.get("loop", True))}
        role = meta.get("runtime_role")
        if role:
            entry["runtime_role"] = role
        buf = meta.get("timed_buffer_ms")
        if buf is not None:                       # §3.2 — emitted only when authored
            entry["timed_buffer_ms"] = buf
        entry["view"] = meta.get("view") or sheet_view   # §3.3 — per-animation view block
        animations[name] = entry
        cursor = start + len(cells)

    rows = (cursor + columns - 1) // columns
    sheet = Image.new("RGBA", (columns * frame_size, max(rows, 1) * frame_size), (0, 0, 0, 0))
    for _name, cells, idx in placed:
        for i, fr in zip(idx, cells):
            sheet.paste(fr, ((i % columns) * frame_size, (i // columns) * frame_size), fr)

    manifest = {
        "schema_version": "pet_manifest.v1",
        "columns": columns, "rows": rows, "frame_width": frame_size, "frame_height": frame_size,
        "animations": animations,
        **sheet_view,                            # view_kind / native_facing / mirroring_policy
        "movement_class": movement_class,
    }
    package = {"breed_id": breed_id, "display_name": display_name, "movement_class": movement_class}

    sbuf = io.BytesIO(); sheet.save(sbuf, "PNG")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{breed_id}_sprite.png", sbuf.getvalue())
        z.writestr("manifest.json", json.dumps(manifest, indent=2))
        z.writestr("package.json", json.dumps(package, indent=2))
    return buf.getvalue()


def _base_sprite(animal, reference_image=None, remix_strength=None,
                 seed=None, on_stage=None, isolate=False, base_pose="standing") -> Path:
    """THE base-sprite selector — the one place the pipeline's starting image is
    decided (SPEC_PET_DESIGNER_FLOW §7.1).

    Three branches, keyed on CAPABILITY (which inputs the caller has), never on
    provenance (§6 — the engine never asks where a record came from):

        remix   reference_image + remix_strength  → img2img redraw toward `animal`
        as-is   reference_image alone             → the reference, normalized, unchanged
        text    neither                           → txt2img a fresh base from `animal`

    Both entry points (`render_design_still`, `make_pet_zip`) call this, so the
    parity contract (§5.1 — "the previewed still IS the base sprite make_pet_zip
    would have produced") holds structurally instead of by duplication.

    seed:     None → a fresh random seed. Pass one to make the workflow
              reproducible; the parity pin (§10.2) needs that seam.
    on_stage: optional callback(msg) naming the branch that ran, for callers
              that report progress.
    isolate:  cut the subject out of a photographic reference before the redraw
              (SPEC_UPLOAD_LIKENESS §2.2). Only meaningful on the two reference
              branches; the text branch has no reference to isolate.
    base_pose: the posture the base still is drawn in (the resolved motion profile's
              base_pose — "standing" for land animals, "swimming, body horizontal" for
              aquatic). Swaps in for the prompt's pose word on the two DRAWN branches
              (remix + text); the as-is branch has no prompt so it is inert there.
    """
    def stage(msg):
        if on_stage:
            on_stage(msg)

    if seed is None:
        seed = random.randint(1, 2**31)

    if reference_image and remix_strength:
        stage("Redrawing your design…")
        prepped = _prep_reference_image(reference_image, isolate=isolate)
        denoise = min(0.9, max(0.3, float(remix_strength)))
        base = COMFY_OUTPUT_DIR / _run(_img2img_wf(_remix_prompt(animal, base_pose), str(prepped), seed, denoise))
        _wait_stable(base)
        return base

    if reference_image:
        stage("Preparing the reference image…")
        return _prep_reference_image(reference_image, isolate=isolate)

    stage("Drawing the base sprite…")
    base = COMFY_OUTPUT_DIR / _run(_static_image_wf(_base_prompt(animal, base_pose), seed))
    _wait_stable(base)
    return base


def render_design_still(description: str, reference_image=None, strength=None,
                        seed=None, isolate=False, base_pose="standing") -> bytes:
    """Render one still and return it as PNG bytes — the design page's ~10 s step
    (SPEC_PET_DESIGNER_FLOW §2). Two shapes, both delegating to `_base_sprite`:

      - reference_image + strength → an img2img redraw toward `description`.
        This is step 2's answer: the archetype redrawn toward the user's design.
      - neither                    → txt2img a fresh base from `description`.
        This is step 1's long-tail branch (§3.3): "what does a blue jay look like"
        when no curated base.png is cached for it.

    Save the result and hand it back to make_pet_zip(reference_image=...) WITHOUT
    remix_strength to animate exactly what was previewed.

    Raises ValueError for reference_image without strength: as-is is meaningless
    for a *still* renderer — the caller already holds those bytes (§7.1).
    """
    # `not strength`, NOT `strength is None`. The guard and the dispatch have to agree
    # on what "no strength" means, and _base_sprite branches on TRUTHINESS — so a 0.0
    # passed the `is None` check, fell into the as-is branch, and handed the caller back
    # their own bytes with no render and no error. Exactly what the line below says is
    # impossible. Unreachable from the web tier (it clamps to [0.3, 0.9]) and from the
    # pool (schema minimum 0.3), but a contract that only holds because every caller
    # happens to be careful is not a contract.
    if reference_image is not None and not strength:
        raise ValueError(
            "render_design_still(reference_image=…) requires a non-zero strength — "
            "rendering a reference as-is would just return the caller's own bytes."
        )
    out = _base_sprite(description, reference_image=reference_image,
                       remix_strength=strength, seed=seed, isolate=isolate,
                       base_pose=base_pose)
    return out.read_bytes()


def _effective_poses(profile, poses):
    """The ordered list of pose names to actually generate (SPEC_MOTION_PROFILES §5.1/§5.3):
    the profile's enabled poses, intersected with the request (if any), always unioned
    with the required poses (walk+idle), in canonical order, capped at MAX_POSES.

    - poses is None → the profile's required set only (walk+idle) — today's 2-pose behavior.
    - poses is a {name: bool} package → the enabled poses the caller selected, plus required.
    """
    enabled = profile.enabled_poses()                      # canonical order, enabled only
    required = [p for p in mp.REQUIRED_POSES if p in enabled]
    if poses is None:
        selected = list(required)
    else:
        want = {name for name, on in poses.items() if on}
        selected = [p for p in enabled if p in want]
        for p in required:                                 # required always included
            if p not in selected:
                selected.append(p)
    # canonical order + de-dupe, then clamp to the hard ceiling
    ordered = [p for p in mp.CANONICAL_POSES if p in set(selected)]
    if len(ordered) > mp.MAX_POSES:
        log.warning("pose selection %d exceeds MAX_POSES=%d; clipping", len(ordered), mp.MAX_POSES)
        ordered = ordered[:mp.MAX_POSES]
    return ordered


def make_pet_zip(animal: str, on_progress=None, breed_id=None, reference_image=None,
                 remix_strength=None, display_name=None, poses=None, motion_profile=None,
                 pose_anchor=True):
    """Generate a complete DatsMe pet from an animal name.

    Args:
        animal:          e.g. "red panda", "penguin", "baby dragon".
        on_progress:     optional callback(message: str, fraction: float in 0..1).
        breed_id:        optional slug override (else derived from `animal`).
        reference_image: optional path to an image to use INSTEAD of generating
                         a base sprite from `animal`. Without remix_strength the
                         animations are built from this exact image, so it should
                         show one animal, side profile, facing right (DatsMe
                         mirrors pets for leftward movement). `animal` still
                         names the pet and steers the motion prompts.
        remix_strength:  with reference_image, redraw the image toward `animal`'s
                         description first (img2img) instead of animating it
                         as-is — the pet-remix path ("same monkey, but purple").
                         0.45 = subtle recolor … 0.8 = near-redesign.
        display_name:    optional human-facing name for the bundle. Defaults to
                         animal.title() — override when `animal` is a long
                         composed design prompt that would make an ugly name.
        poses:           optional {pose_name: bool} package of which poses to
                         generate (SPEC_MOTION_PROFILES §4.3). None → walk+idle
                         only, byte-identical to the pre-motion-profiles behavior.
                         walk+idle are always included regardless of the request.
        motion_profile:  optional pinned profile key (§5.2). When set, the profile
                         is loaded by key (skew-safe); else it is resolved from
                         `animal` by keyword. Either way the engine loops the
                         resolved profile's poses and never names a species.

    Returns (breed_id, zip_bytes). Takes ~3 min on an RTX 3090. The .zip is a
    DatsMe breed bundle — upload it via DatsMe's POST /api/pets/me/upload.
    """
    def prog(msg, pct):
        if on_progress:
            on_progress(msg, pct)

    animal = (animal or "").strip()[:60] or "pet"
    seed = random.randint(1, 2**31)

    # Resolve the motion profile: pinned key (skew-safe) or keyword from the animal.
    if motion_profile:
        profile = mp.load_motion_profile(motion_profile, fallback_animal=animal)
    else:
        profile = mp.resolve_motion_profile(animal)
    pose_names = _effective_poses(profile, poses)

    # The base image is chosen in exactly one place (§7.1) — this call and
    # render_design_still's are the same code, which is what makes the previewed
    # still and this build's base sprite provably identical (§5.1).
    base = _base_sprite(animal, reference_image=reference_image,
                        remix_strength=remix_strength, seed=seed,
                        on_stage=lambda msg: prog(msg, 0.10),
                        base_pose=profile.base_pose)

    # Generate the poses in TWO PHASES so ComfyUI doesn't thrash its ~12 GB models.
    # Phase A draws every pose's anchor still (all Z-Image txt2img); Phase B runs every
    # Wan I2V loop. Batching by model means Z-Image loads ONCE (base + all anchors) and
    # Wan loads ONCE — a single model switch for the whole build, instead of reloading a
    # model between the anchor and the loop on EVERY pose. Once every pose carries a clause,
    # the interleaved order spent ~5 min of an 8-pose build in model reloads alone. Output
    # is byte-identical: each loop still starts from its own anchor at the same _ANCHOR_SEED.
    #
    # §3.9.1 pose_prompt anchor: a fresh still in the pose (a wings-spread bird flaps where a
    # standing one only twitches), drawn from the DESCRIPTION so it works for typed animals and
    # designer pets (§7.1/§7.2/§7.3). `pose_anchor=False` (photo UPLOADS, whose stored noun a
    # fresh still can't match) keeps the shared base. The anchor's style prompt mirrors how the
    # base was drawn — the remix prompt for reference pets, the base prompt for typed.
    anchor_prompt = _remix_prompt if reference_image is not None else _base_prompt
    n = len(pose_names)

    # Phase A — all anchor stills up front (Z-Image stays loaded across base + every anchor).
    # A pose with no clause reuses the shared base. Fixed _ANCHOR_SEED so the anchor reproduces
    # what the Motion Lab drew while the clause was authored (§3.9.1 — a faithful Lab preview).
    pose_starts = {}
    for i, name in enumerate(pose_names):
        clause = mp.anchor_clause(profile.pose(name)) if pose_anchor else None
        if not clause:
            pose_starts[name] = base
            continue
        prog(f"Sketching the {name} pose…", round(0.10 + 0.12 * i / max(1, n), 3))
        start = COMFY_OUTPUT_DIR / _run(_static_image_wf(anchor_prompt(animal, clause), _ANCHOR_SEED))
        _wait_stable(start)
        pose_starts[name] = start

    # Phase B — all Wan I2V loops (Wan loads once), each from its own anchor. This band
    # [0.22, 0.85] is the bulk of the wall time; the 0.85→1.0 tail is the cutout + pack step.
    pose_files = {}
    for i, name in enumerate(pose_names):
        prog(f"Animating the {name}…", round(0.22 + 0.63 * i / max(1, n), 3))
        pose_files[name] = _run(_loop_wf(mp.compose_pose_prompt(animal, profile.pose(name)),
                                         str(pose_starts[name]), _ANCHOR_SEED))

    prog("Cutting out backgrounds & packing…", 0.85)
    _evict_comfy_models_for_cutout()

    pose_frames = {}
    pose_meta = {}
    for name in pose_names:
        frames = _frames_rgba(COMFY_OUTPUT_DIR / pose_files[name])
        if len(frames) > 1:                  # drop the duplicated final loop frame
            frames = frames[:-1]
        pose_frames[name] = frames
        p = profile.pose(name)
        pose_meta[name] = {"runtime_role": p.runtime_role, "loop": p.loop,
                           "timed_buffer_ms": p.timed_buffer_ms, "view": p.view}

    breed_id = breed_id or _slug(animal)
    try:
        zip_bytes = pack_datsme_bundle(pose_frames, breed_id,
                                       display_name or animal.title(),
                                       pose_meta=pose_meta,
                                       movement_class=profile.movement_class,
                                       view=profile.view,
                                       on_frame=lambda done, total: prog(
                                           "Cutting out backgrounds & packing…",
                                           round(0.85 + 0.14 * done / total, 3)))
    finally:
        # The cutout is the build's last GPU step — free birefnet's ~14 GB the instant it's
        # done (or errored) so the next build's generation gets the whole card. onnxruntime
        # never releases the arena while the session lives, so we destroy the session here.
        _CUTOUT.release()
    prog("Done!", 1.0)
    return breed_id, zip_bytes
