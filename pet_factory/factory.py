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
import random
import shutil
import subprocess
import tempfile
import time
import uuid
import zipfile
from collections import deque
from pathlib import Path

import numpy as np
import requests
from PIL import Image, ImageSequence

# ── Config ───────────────────────────────────────────────────────────────────
COMFY_URL = os.environ.get("PET_FACTORY_COMFY_URL", "http://127.0.0.1:8188").rstrip("/")
COMFY_OUTPUT_DIR = Path(os.environ.get(
    "PET_FACTORY_COMFY_OUTPUT", os.path.expanduser("~/ComfyUI/output")))
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

NEG = ("oversaturated, neon, vibrant, hyper-colored, anime, blurry, photo, "
       "realistic, low quality, watermark, signature, multiple subjects, "
       "deformed, human, person, hands, text")

# Motion suffixes: keep the face still and the body anchored in place (the pet
# runtime handles horizontal movement), and ask for a clean looping cycle.
WALK_SUFFIX = (", mouth closed, no facial animation, no chewing, no talking, eyes still, "
               "performing a full walk cycle in place: legs and feet cycling through one "
               "complete stride, body bobbing naturally up and down with each step, classic "
               "looping sprite walk animation, no horizontal movement of the body, no camera "
               "movement, no panning")
IDLE_SUFFIX = (", mouth closed, no facial animation, no chewing, no talking, eyes still, "
               "gentle idle motion: soft breathing, slight sway, a small bob in place, "
               "no walking, no camera movement, no panning")

_REMBG = None


def _rembg():
    """Lazily create the birefnet cutout session. Prefers the GPU (CUDA, ~12x
    faster) and falls back to CPU automatically if the CUDA libraries aren't
    available — so it never breaks, just runs slower."""
    global _REMBG
    if _REMBG is None:
        from rembg import new_session
        try:
            _REMBG = new_session("birefnet-general-lite",
                                 providers=["CUDAExecutionProvider", "CPUExecutionProvider"])
            print(f"[pet_factory] rembg providers: {_REMBG.inner_session.get_providers()}", flush=True)
            return _REMBG
        except Exception as e:
            print(f"[pet_factory] CUDA cutout unavailable ({e}); using CPU", flush=True)
        _REMBG = new_session("birefnet-general-lite")
    return _REMBG


def _remove_bg(img: Image.Image) -> Image.Image:
    from rembg import remove
    return remove(img.convert("RGB"), session=_rembg())


# ── ComfyUI workflows ────────────────────────────────────────────────────────

def _static_image_wf(prompt, seed):
    """Z-Image-Turbo text-to-image (1024², 8-step turbo, CFG 1.0)."""
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": ZIMAGE_UNET, "weight_dtype": "default"}},
        "2": {"class_type": "VAELoader", "inputs": {"vae_name": ZIMAGE_VAE}},
        "3": {"class_type": "CLIPLoader", "inputs": {"clip_name": ZIMAGE_TE, "type": "lumina2"}},
        "4": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["1", 0], "shift": 3.0}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["3", 0], "text": prompt}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["3", 0], "text": NEG}},
        "8": {"class_type": "EmptySD3LatentImage", "inputs": {"width": 1024, "height": 1024, "batch_size": 1}},
        "9": {"class_type": "KSampler", "inputs": {
            "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["8", 0],
            "seed": seed, "steps": 8, "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}},
        "10": {"class_type": "VAEDecode", "inputs": {"samples": ["9", 0], "vae": ["2", 0]}},
        "11": {"class_type": "SaveImage", "inputs": {"images": ["10", 0], "filename_prefix": "petfactory_still"}},
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
        "11": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["3", 0], "text": ""}},
        "12": {"class_type": "WanFirstLastFrameToVideo", "inputs": {
            "positive": ["10", 0], "negative": ["11", 0], "vae": ["4", 0],
            "width": width, "height": height, "length": length, "batch_size": 1,
            "start_image": ["9", 0], "end_image": ["9", 0]}},
        "13": {"class_type": "KSamplerAdvanced", "inputs": {
            "model": ["7", 0], "add_noise": "enable", "noise_seed": seed, "steps": 4, "cfg": 1.0,
            "sampler_name": "euler", "scheduler": "simple", "positive": ["12", 0], "negative": ["12", 1],
            "latent_image": ["12", 2], "start_at_step": 0, "end_at_step": 2, "return_with_leftover_noise": "enable"}},
        "14": {"class_type": "KSamplerAdvanced", "inputs": {
            "model": ["8", 0], "add_noise": "disable", "noise_seed": seed, "steps": 4, "cfg": 1.0,
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


def _base_prompt(animal: str) -> str:
    # "facing right" matters: DatsMe authors pets facing right and mirrors them
    # for leftward movement, so the source must face right.
    return (f"a cute cartoon {animal}, side profile view, facing right, standing, "
            "soft pastel colors, muted palette, simple flat shading, white background, "
            "storybook style")


def pack_datsme_bundle(walk_frames, idle_frames, breed_id, display_name,
                       frame_size=256, columns=8, fps=12,
                       movement_class="mammalian_quadruped") -> bytes:
    """Pack two frame lists (RGB or RGBA PIL images) into a DatsMe breed bundle
    (.zip bytes): a transparent sprite sheet + manifest.json + package.json.

    Each frame is background-removed (birefnet) and fit into a square cell. The
    walk animation gets frame indices 0..N-1, idle starts on a fresh grid row.
    Returns the .zip as bytes — post it to DatsMe's /api/pets/me/upload."""
    def prep(frames):
        out = []
        for fr in frames:
            orig = fr.convert("RGB")
            try:
                a = _remove_bg(orig).convert("RGBA").split()[3]     # birefnet alpha matte
            except Exception:
                a = Image.new("L", orig.size, 255)
            result = orig.convert("RGBA")
            result.putalpha(a)                                     # original colors + matte
            cell = _fit_square(result, frame_size)
            cell.putalpha(_fill_holes_alpha(cell.split()[3]))      # close interior holes
            out.append(cell)
        return out

    A, B = prep(walk_frames), prep(idle_frames)
    idx_a = list(range(len(A)))
    start_b = ((len(A) + columns - 1) // columns) * columns        # idle starts on a new row
    idx_b = list(range(start_b, start_b + len(B)))
    rows = (start_b + len(B) + columns - 1) // columns

    sheet = Image.new("RGBA", (columns * frame_size, rows * frame_size), (0, 0, 0, 0))
    for i, fr in zip(idx_a, A):
        sheet.paste(fr, ((i % columns) * frame_size, (i // columns) * frame_size), fr)
    for i, fr in zip(idx_b, B):
        sheet.paste(fr, ((i % columns) * frame_size, (i // columns) * frame_size), fr)

    manifest = {
        "columns": columns, "rows": rows, "frame_width": frame_size, "frame_height": frame_size,
        "animations": {
            "walk": {"frames": idx_a, "fps": fps, "loop": True, "runtime_role": "active"},
            "idle": {"frames": idx_b, "fps": fps, "loop": True, "runtime_role": "rest"},
        },
        "view_kind": "side", "native_facing": "right",
        "mirroring_policy": "flip", "movement_class": movement_class,
    }
    package = {"breed_id": breed_id, "display_name": display_name, "movement_class": movement_class}

    sbuf = io.BytesIO(); sheet.save(sbuf, "PNG")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{breed_id}_sprite.png", sbuf.getvalue())
        z.writestr("manifest.json", json.dumps(manifest, indent=2))
        z.writestr("package.json", json.dumps(package, indent=2))
    return buf.getvalue()


def make_pet_zip(animal: str, on_progress=None, breed_id=None):
    """Generate a complete DatsMe pet from an animal name.

    Args:
        animal:       e.g. "red panda", "penguin", "baby dragon".
        on_progress:  optional callback(message: str, fraction: float in 0..1).
        breed_id:     optional slug override (else derived from `animal`).

    Returns (breed_id, zip_bytes). Takes ~3 min on an RTX 3090. The .zip is a
    DatsMe breed bundle — upload it via DatsMe's POST /api/pets/me/upload.
    """
    def prog(msg, pct):
        if on_progress:
            on_progress(msg, pct)

    animal = (animal or "").strip()[:60] or "pet"
    seed = random.randint(1, 2**31)

    prog("Drawing the base sprite…", 0.10)
    base = COMFY_OUTPUT_DIR / _run(_static_image_wf(_base_prompt(animal), seed))
    _wait_stable(base)

    prog("Animating the walk…", 0.35)
    walk_fn = _run(_loop_wf(f"cute cartoon {animal} walking, side profile, facing right" + WALK_SUFFIX,
                            str(base), seed))

    prog("Animating the idle…", 0.60)
    idle_fn = _run(_loop_wf(f"cute cartoon {animal} sitting calmly, side profile, facing right" + IDLE_SUFFIX,
                            str(base), seed))

    prog("Cutting out backgrounds & packing…", 0.85)
    # Unload ComfyUI's Wan models so the GPU has room for birefnet (the next job
    # reloads them). Harmless if the endpoint isn't available.
    try:
        requests.post(f"{COMFY_URL}/free", json={"unload_models": True, "free_memory": True}, timeout=10)
        time.sleep(1.5)
    except Exception:
        pass

    walk_frames = _frames_rgba(COMFY_OUTPUT_DIR / walk_fn)
    idle_frames = _frames_rgba(COMFY_OUTPUT_DIR / idle_fn)
    if len(walk_frames) > 1:                 # drop the duplicated final loop frame
        walk_frames = walk_frames[:-1]
    if len(idle_frames) > 1:
        idle_frames = idle_frames[:-1]

    breed_id = breed_id or _slug(animal)
    zip_bytes = pack_datsme_bundle(walk_frames, idle_frames, breed_id, animal.title())
    prog("Done!", 1.0)
    return breed_id, zip_bytes
