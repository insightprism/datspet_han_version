"""webui — Pet Maker backend (FastAPI, mirrors DatsMe's api conventions).

The React frontend (web/, Next.js on :19955) talks to this API (:19954):

  POST /api/generate                 text and/or reference image → job_id
  GET  /api/job/{job_id}             live job status + progress
  GET  /api/pets                     every pet ever generated here (persisted)
  GET  /api/pets/{pet_id}/sheet.png  sprite sheet for the engine
  GET  /api/pets/{pet_id}/manifest.json
  GET  /api/pets/{pet_id}/zip        the DatsMe breed bundle download

Generation runs make_pet_zip() (pet_factory → local ComfyUI) in a worker
thread, one job at a time (the pipeline owns the whole GPU). Each finished
pet persists as a row in one SQLite store (datspet.db) — sprite sheet,
manifest, package.json and the .zip bundle live in-row as blobs (see
webui/db.py), so the pet house survives restarts. pet_id == job_id. The DB
location follows PETMAKER_OUTPUT_DIR (PETMAKER_DB_PATH to override).

Run via ./start_petmaker_backend_only.sh (sets the pet_factory env).
Needs ComfyUI up (./start_comfyui_only.sh).
"""
import io
import json
import os
import shutil
import threading
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response

import db
import pool_client
# motion_profiles is pure data (no ML deps) — safe to import on the GPU-less web
# tier; it powers /api/motions and the pose menu (SPEC_MOTION_PROFILES §5.1).
from pet_factory import motion_profiles as motion_profiles_mod
# animal_catalog is likewise pure data (base-animal tree + curated base PNGs) — it
# powers the landing-page tiles, the themed pages' breed picker + instant base
# image, and the catalog img2img source (SPEC_PET_DESIGNER_PLATFORM §4).
from pet_factory import animal_catalog as animal_catalog_mod
# tiers is the entitlement table (pose caps + extra-pose price), also pure data —
# the pose selector caps + the resolved pricing hint come from it, and the server
# enforces the resolved cap on generate (SPEC_PET_DESIGNER_PLATFORM §5).
from pet_factory import tiers as tiers_mod
# body_shapes is the step-2 body vocabulary (thin/normal/chubby) — pure data, like
# the three above. It feeds compose_design, never the archetype prompt: shape is a
# DESIGN modifier, so picking one can never invalidate a curated base
# (SPEC_PET_DESIGNER_FLOW §0.1/§7.2).
from pet_factory import body_shapes as body_shapes_mod

# Generation backend (spec §A.6): "local" runs the on-box GPU directly (dev / break-
# glass); "pool" routes generation to the shared_gpu_cpu pool (prod, GPU-less box).
# The web tier is otherwise identical either way — only the generation SOURCE changes.
PET_GEN_BACKEND = os.environ.get("PET_GEN_BACKEND", "local").strip().lower()

# Startup guard: in local mode, generation drives ComfyUI at PET_FACTORY_COMFY_URL.
# If that env isn't set, pet_factory.factory falls back to its upstream default
# :8188 — which is NOT where our ComfyUI runs (:19953, per pet_env.sh). That
# mismatch fails silently until the first "Create my design" with a confusing
# "connection refused :8188". Warn LOUDLY at boot instead, so a backend started
# without sourcing pet_env.sh (e.g. only pet_env.local.sh) is caught immediately.
if PET_GEN_BACKEND == "local" and not os.environ.get("PET_FACTORY_COMFY_URL"):
    print("[webui] WARNING: PET_GEN_BACKEND=local but PET_FACTORY_COMFY_URL is unset — "
          "generation will try ComfyUI at the :8188 default, NOT our :19953. "
          "Source pet_env.sh (which sets it) before starting the backend.", flush=True)

# pet_factory (and its ML stack: rembg → onnxruntime-CUDA, the ComfyUI-driving code) is
# imported ONLY in the local branch, lazily (spec §A.4). This is what keeps the GPU-less
# Hetzner venv free of the ML deps — importing it at module top would drag them onto a box
# that has no GPU to use them.
def _local_pet_factory():
    from pet_factory import make_pet_zip, render_design_still
    return make_pet_zip, render_design_still


app = FastAPI(title="Pet Maker API")

# The Next.js dev server is a separate origin in development (same pattern
# as DatsMe's :19995 frontend ↔ :19994 api split; ours is :19955 ↔ :19954).
FRONTEND_PORT = int(os.environ.get("PETMAKER_FRONTEND_PORT", 19955))
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        f"http://localhost:{FRONTEND_PORT}",
        f"http://127.0.0.1:{FRONTEND_PORT}",
        # Covers a tab explicitly opened at http://[::1]:PORT. The Origin header
        # reflects the page URL's hostname AS TYPED (never the resolved IP), so
        # only a [::1]-typed page sends a [::1] Origin — localhost pages don't.
        f"http://[::1]:{FRONTEND_PORT}",
    ],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
    # The DatsMe launch cookie (httponly) rides on /api/datsme/* calls from the
    # frontend, so credentialed requests must be allowed.
    allow_credentials=True,
)

# Pets are stored in the SQLite DB (webui/db.py), not one-folder-per-pet.
# OUTPUT_DIR still exists as the DB's home and the transient-scratch root
# (preview stills, generation reference images); point PETMAKER_OUTPUT_DIR
# elsewhere to move the whole collection — the .db and this dir move together.
OUTPUT_DIR = db.OUTPUT_DIR

# Design-page preview stills + per-job scratch (reference uploads, remix base
# frames). These are transient working files, not pets — pets live in the DB.
PREVIEW_DIR = OUTPUT_DIR / "_previews"
PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
SCRATCH_DIR = OUTPUT_DIR / "_scratch"
SCRATCH_DIR.mkdir(parents=True, exist_ok=True)

db.init_db()  # create tables + one-time-migrate any legacy pet.json folders

# DatsMe partner surface (DPP). Standalone-first: this router is inert in local
# mode — its manifest 503s without DATSME_HMAC_SECRET and nothing here runs
# unless a launch cookie / host request arrives. See webui/datsme_integration.py.
import datsme_integration
app.include_router(datsme_integration.router)

# Motion-profile admin API (SPEC_MOTION_PROFILE_ADMIN §4). Every endpoint is gated
# by the adm-claim cookie; inert until an admin-launch sets it.
import motion_admin
app.include_router(motion_admin.router)

MAX_UPLOAD_BYTES = 12 * 1024 * 1024
ALLOWED_IMAGE_MIMES = ("image/png", "image/jpeg", "image/webp", "image/gif")

# How hard to redraw an uploaded photo into a sprite (SPEC_PET_DESIGNER_FLOW §3.4).
# High on purpose: a photograph is far from the side-profile, flat-shaded, white-
# background still Wan I2V needs, and the gap is what makes today's raw-photo
# animations unreliable. This is the ONE knob of the upload door, and it is a
# starting value, not a calibrated one — it deserves the same GPU session §4.4
# gives body shape.
UPLOAD_REDRAW_STRENGTH = 0.85

# The pipeline owns the whole GPU (ComfyUI + birefnet); run one job at a
# time. Queued jobs wait here and report "Waiting for the GPU…" meanwhile.
GPU_LOCK = threading.Lock()


@dataclass
class Job:
    id: str
    name: str
    dir: Path                       # transient scratch dir (uploads/remix base)
    status: str = "queued"          # queued | running | done | error
    progress: float = 0.0           # 0..1
    message: str = "Waiting for the GPU…"
    breed_id: Optional[str] = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    external_user_id: Optional[str] = None  # NULL = standalone; set when DatsMe-launched
    # Advisory pool "requested by" labels ({user, device}), captured from the
    # request AT SUBMIT-HANDLER TIME — generation runs on a background thread
    # where the request (and its User-Agent) is gone, so it must be carried here.
    pool_labels: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "status": self.status,
            "progress": self.progress, "message": self.message,
            "breed_id": self.breed_id, "error": self.error,
            "created_at": self.created_at, "finished_at": self.finished_at,
        }


JOBS: dict[str, Job] = {}
JOBS_LOCK = threading.Lock()


# Accessories that read as plural/paired — no "a/an" article in the prompt.
_PLURAL_ACCESSORIES = {
    "sneakers", "rain boots", "cowboy boots", "headphones",
    "sunglasses", "round glasses",
}

# Color words that can appear inside a species name ("BLUE jay", "RED panda").
# When the user asks for a different color, the name-color fights the request
# hard enough that the redraw needs full strength (0.9) to win — calibrated
# empirically 2026-07-11 (emerald blue jay stayed blue at 0.85, flipped at 0.9).
_COLOR_WORDS = {
    "red", "orange", "yellow", "golden", "green", "blue", "purple", "pink",
    "brown", "black", "white", "gray", "grey", "emerald", "teal", "rose",
    "indigo", "violet", "crimson", "scarlet", "azure",
}


def compose_design(species: str, color: str, accessories: list[str],
                   body_shape: str = "", extra: str = "") -> tuple[str, str, Optional[float]]:
    """Turn step 2's structured picks into (prompt_description, display_name,
    min_strength) — the ONE place a design becomes a prompt
    (SPEC_PET_DESIGNER_FLOW §4).

    Every "what should it look like" input arrives here and nowhere else. In
    particular `body_shape` composes into the DESIGN string, never into the
    archetype prompt (§0.1): step 1 draws "a corgi", step 2 makes it chubby. That
    placement is what lets a curated base.png survive any design choice (§3.3).

    Prompt wording follows the remix calibration: 'recolored entirely {color}' is
    what actually flips a color against the source image. min_strength is 0.9 when
    the redraw has to fight the source — a conflicting color word in the species
    name (see _COLOR_WORDS), or a silhouette change (§4.4). The display name stays
    short — color + species, not the accessory list, the shape, or the free text.
    """
    # Clause order matters (calibrated on stills): shape adjectives lead (they
    # attach to the noun phrase), accessories directly after the species, free
    # text after those, and the recolor emphasis LAST. With the recolor clause in
    # the middle, the accessory gets dropped; with accessories last, the color
    # loses. This ordering keeps both.
    #
    # NOT YET CALIBRATED (§4.3/§4.4): the shape and free-text positions are
    # reasoned, not measured. The color and accessory positions above were settled
    # by running them; these two deserve the same GPU session before launch.
    min_strength = None
    description = f"vivid {color} {species}" if color else species

    shape_fragment = body_shapes_mod.prompt_fragment(body_shape)
    if shape_fragment:
        description = f"{shape_fragment} {description}"
        # A silhouette change fights the source image exactly like a conflicting
        # color does (§4.4 reason 3) — same class of conflict, same trigger. The
        # curated corgi is normal-shaped and will win at a gentle denoise.
        min_strength = 0.9

    if accessories:
        worn = []
        for acc in accessories:
            if acc in _PLURAL_ACCESSORIES:
                worn.append(acc)
            else:
                worn.append(("an " if acc[0] in "aeiou" else "a ") + acc)
        description += " wearing " + ", ".join(worn)

    if extra:
        # The unbounded escape hatch (§4.3, decision #4). It sits BEFORE the
        # recolor clause so that clause stays last and the color still wins — the
        # calibration above is load-bearing and free text must not displace it.
        description += f", {extra}"

    if color:
        description += f", recolored entirely {color}"
        if any(w in _COLOR_WORDS and w != color for w in species.split()):
            min_strength = 0.9

    display_name = (f"{color} {species}" if color else species).title()
    return description, display_name, min_strength


def extract_base_frame(pet_id: str, dest: Path) -> Path:
    """Crop a pet's first resting frame out of its stored sprite sheet — the
    starting image for the remix pipeline. Works for every pet in the house,
    however old, because the sheet + manifest are what we persist."""
    from PIL import Image
    row = db.get_pet(pet_id)
    if row is None:
        raise HTTPException(404, "base pet not found")
    manifest = json.loads(row["manifest_json"])
    sheet = Image.open(io.BytesIO(row["sheet_png"]))
    anims = manifest.get("animations", {})
    frames = (anims.get("idle") or anims.get("walk") or {}).get("frames") or [0]
    idx = frames[0]
    cols = manifest.get("columns", 8)
    fw = manifest.get("frame_width", 256)
    fh = manifest.get("frame_height", 256)
    cell = sheet.crop(((idx % cols) * fw, (idx // cols) * fh,
                       (idx % cols + 1) * fw, (idx // cols + 1) * fh))
    cell.save(dest, "PNG")
    return dest


def _encode_reference_image(path: Path, max_px: int = 1024) -> str:
    """Read a reference image, downscale its longest side to ≤max_px, and return
    it base64-encoded as PNG — the transport that carries the image to a pool
    worker on another machine (spec §A.2). The downscale keeps the dispatcher DB
    small and stays well under the body cap; it is loss-safe because the worker's
    _prep_reference_image re-pads/normalizes to a square canvas anyway."""
    import base64
    from PIL import Image

    with Image.open(path) as im:
        # ALWAYS carry alpha (RGBA): sprite-sheet crops sit on a transparent
        # background, and convert("RGB") would land them on BLACK — while the
        # local path's _prep_reference_image composites alpha onto WHITE. The
        # worker stays the one flattening authority; PNG transport keeps alpha,
        # so pool and local generations see the identical reference.
        im = im.convert("RGBA")
        if max(im.size) > max_px:
            im.thumbnail((max_px, max_px), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _generate_via_pool(job: Job, *, description: str, reference_image: Optional[Path],
                       remix_strength: Optional[float],
                       display_name: Optional[str],
                       poses: Optional[dict] = None,
                       motion_profile: Optional[str] = None) -> tuple[str, bytes]:
    """Pool backend (§A.2): submit the SAME params the local call used — carrying
    the reference image as base64 so it travels to the worker — and drive the job
    to its .zip result. Concurrency is the pool's job (no GPU_LOCK here)."""
    def on_progress(msg, fraction):     # adapter hands a FRACTION 0..1 (R5-1)
        with JOBS_LOCK:
            job.message = msg
            job.progress = fraction

    params: dict = {"animal": description}
    if display_name:
        params["display_name"] = display_name
    if remix_strength is not None:
        params["remix_strength"] = remix_strength
    if reference_image is not None:
        params["reference_image_b64"] = _encode_reference_image(reference_image)
    if poses is not None:                          # v3 (§5.2) — which poses to build
        params["poses"] = poses
    if motion_profile:                             # v3 — the catalog's pinned profile key
        params["motion_profile"] = motion_profile

    # Persist the linkage BEFORE driving (Opt-1, §A.6): if this process dies
    # mid-generation, startup reattaches to the still-running pool job instead
    # of orphaning it. The row is deleted at either terminal state.
    pool_job_id = pool_client.submit("pet_factory", params, labels=job.pool_labels or None)
    db.record_pool_job(
        job_id=job.id, pool_job_id=pool_job_id, description=description,
        display_name=display_name, created_at=job.created_at,
        external_user_id=job.external_user_id)
    zip_bytes = pool_client.drive_to_result(
        pool_job_id, on_progress=on_progress, poll_interval=4.0, timeout_s=900.0)
    # The bundle carries the breed_id in its manifest; the finalize reads it
    # back, so return "" and let the unpack fill it in.
    return "", zip_bytes


def run_pet_job(job: Job, *, description: str, reference_image: Optional[Path],
                remix_strength: Optional[float] = None,
                display_name: Optional[str] = None,
                poses: Optional[dict] = None,
                motion_profile: Optional[str] = None) -> None:
    """Runs in a daemon thread. Mutates `job` as it goes; never raises.
    On success the finished pet is persisted as one DB row (sheet/manifest/
    package/zip as blobs), born a DRAFT — it joins the house only when the
    user saves (POST /api/pets/{id}/keep)."""
    try:
        if PET_GEN_BACKEND == "pool":
            with JOBS_LOCK:
                job.status = "running"
            breed_id, zip_bytes = _generate_via_pool(
                job, description=description, reference_image=reference_image,
                remix_strength=remix_strength, display_name=display_name,
                poses=poses, motion_profile=motion_profile)
        else:
            make_pet_zip, _ = _local_pet_factory()
            with GPU_LOCK:
                # "running" only once the GPU is actually ours — a job waiting on
                # the lock stays "queued" ("Waiting for the GPU…"), exactly as
                # before the pool backend existed. The pool branch marks running
                # at submit: queueing is the pool's job there.
                with JOBS_LOCK:
                    job.status = "running"

                def on_progress(msg, pct):
                    with JOBS_LOCK:
                        job.message = msg
                        job.progress = pct

                breed_id, zip_bytes = make_pet_zip(
                    description, on_progress=on_progress,
                    reference_image=str(reference_image) if reference_image else None,
                    remix_strength=remix_strength, display_name=display_name,
                    poses=poses, motion_profile=motion_profile)

        _finalize_pet_from_zip(job, description=description, breed_id=breed_id,
                               zip_bytes=zip_bytes)
    except Exception as e:
        with JOBS_LOCK:
            job.status = "error"
            job.error = str(e)
            job.message = f"Error: {e}"
            job.finished_at = time.time()
        db.delete_pool_job(job.id)   # web-terminal → drop the reattach row


def _unpack_bundle(zip_bytes: bytes, *, default_display_name: str,
                   breed_id: str = "") -> tuple[Optional[bytes], Optional[str], Optional[str], str, str]:
    """Read sheet/manifest/package out of a pet bundle .zip so the engine can
    render the pet without unzipping in the browser. Returns
    (sheet_png, manifest_json, package_json, display_name, breed_id) — display
    name + breed id are authoritative from package.json when present. Shared by
    fresh-generation finalize, pool-job reattach, and sample adopt (§4.4)."""
    sheet_png = None
    manifest_json = None
    package_json = None
    display_name = default_display_name
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        for member in z.namelist():
            if member.endswith("_sprite.png"):
                sheet_png = z.read(member)
            elif member == "manifest.json":
                manifest_json = z.read(member).decode("utf-8")
            elif member == "package.json":
                package_json = z.read(member).decode("utf-8")
                pkg = json.loads(package_json)
                display_name = pkg.get("display_name", display_name)
                breed_id = breed_id or pkg.get("breed_id", breed_id)
    return sheet_png, manifest_json, package_json, display_name, breed_id


def _finalize_pet_from_zip(job: Job, *, description: str, breed_id: str,
                           zip_bytes: bytes) -> None:
    """Unpack the bundle, persist the pet row (born a DRAFT), and mark the job
    done. Shared by a fresh generation and a reattached pool job (Opt-1).
    breed_id and display_name are authoritative from package.json — the pool
    path passes breed_id="" (the worker minted it); the local backend's return
    value agrees with package.json anyway."""
    sheet_png, manifest_json, package_json, display_name, breed_id = _unpack_bundle(
        zip_bytes, default_display_name=description.title(), breed_id=breed_id)

    db.insert_pet(
        pet_id=job.id, breed_id=breed_id, display_name=display_name,
        created_at=job.created_at, draft=True,
        sheet_png=sheet_png, manifest_json=manifest_json,
        package_json=package_json, bundle_zip=zip_bytes,
        external_user_id=job.external_user_id,
    )

    with JOBS_LOCK:
        job.status = "done"
        job.breed_id = breed_id
        job.name = display_name
        job.message = "Done!"
        job.progress = 1.0
        job.finished_at = time.time()
    db.delete_pool_job(job.id)   # no-op for local jobs


def _resume_pool_job(job: Job, pool_job_id: str, description: str) -> None:
    """Drive a reattached pool job to its result (Opt-1). Same terminal
    behavior as run_pet_job — the generation itself never stopped; only the
    web tier restarted around it."""
    try:
        def on_progress(msg, fraction):
            with JOBS_LOCK:
                job.message = msg
                job.progress = fraction

        zip_bytes = pool_client.drive_to_result(
            pool_job_id, on_progress=on_progress, poll_interval=4.0, timeout_s=900.0)
        _finalize_pet_from_zip(job, description=description, breed_id="",
                               zip_bytes=zip_bytes)
    except Exception as e:
        with JOBS_LOCK:
            job.status = "error"
            job.error = str(e)
            job.message = f"Error: {e}"
            job.finished_at = time.time()
        db.delete_pool_job(job.id)


def _reattach_pool_jobs() -> None:
    """Opt-1 (spec §A.6): a restart used to orphan the in-memory job tracker
    while the pool job kept generating server-side. Rebuild a live Job for
    every persisted in-flight pool job and resume polling it."""
    if PET_GEN_BACKEND != "pool":
        return
    for row in db.list_pool_jobs():
        job = Job(
            id=row["id"],
            name=row["display_name"] or row["description"] or "pet",
            dir=SCRATCH_DIR / row["id"],
            status="running",
            message="Reattached after a restart — still generating…",
            created_at=row["created_at"],
            external_user_id=row["external_user_id"],
        )
        with JOBS_LOCK:
            JOBS[job.id] = job
        threading.Thread(
            target=_resume_pool_job,
            args=(job, row["pool_job_id"], row["description"] or ""),
            daemon=True,
        ).start()


# ── The reference store (SPEC_PET_DESIGNER_FLOW §7.3) ────────────────────────
#
# A reference is a still plus a sidecar of what the fill step resolved about it.
# It lives on the filesystem, not in the DB: these are transient scratch bytes,
# not pets (db.py's stated boundary). PREVIEW_DIR holds the pair:
#
#     {id}.png    the still
#     {id}.json   {id, owner, created_at, description, display_name,
#                  motion_profile, source, min_strength, generated}
#
# _cleanup_transients already sweeps PREVIEW_DIR by mtime at 24 h, so the sidecar
# inherits expiry for free — no migration, no new dependency.
#
# `source` is recorded for support and telemetry ONLY. No runtime path may branch
# on it (§4.2/§6): the engine reads the record and acts. Rev.1 of the spec relaxed
# the design guard on source == "txt2img" and thereby violated its own rule.

def _reference_paths(reference_id: str) -> tuple[Path, Path]:
    return PREVIEW_DIR / f"{reference_id}.png", PREVIEW_DIR / f"{reference_id}.json"


def _reference_record(meta: dict) -> dict:
    """The one record shape all three endpoints return (§7.4). `owner` is
    deliberately NOT in it — it is an access-control fact, not the caller's data."""
    return {
        "reference_id": meta["id"],
        "image_url": f"/api/reference/{meta['id']}.png",
        "description": meta.get("description", ""),
        "display_name": meta.get("display_name", ""),
        "motion_profile": meta.get("motion_profile"),
        "source": meta.get("source", ""),
        "min_strength": meta.get("min_strength"),
        "generated": bool(meta.get("generated", False)),
    }


def _save_reference(png: bytes, *, owner: Optional[str], description: str,
                    display_name: str, motion_profile: Optional[str], source: str,
                    min_strength: Optional[float] = None,
                    generated: bool = False) -> dict:
    """Mint one reference. EVERY door ends here, which is the whole design: past
    this point nothing downstream asks where the picture came from (§6)."""
    reference_id = uuid.uuid4().hex[:12]
    png_path, meta_path = _reference_paths(reference_id)
    meta = {
        "id": reference_id, "owner": owner, "created_at": time.time(),
        "description": description, "display_name": display_name,
        "motion_profile": motion_profile, "source": source,
        "min_strength": min_strength, "generated": generated,
    }
    png_path.write_bytes(png)
    meta_path.write_text(json.dumps(meta))
    return meta


def _reference_visible(meta: dict, owner: Optional[str]) -> bool:
    """Mirrors _can_access: a reference is visible iff it is unowned (standalone)
    or the caller's own. A reference can now be a user's uploaded PHOTO, so this
    gives file-backed content the rule db._scope_clause gives rows (§7.3)."""
    ref_owner = meta.get("owner")
    return ref_owner is None or ref_owner == owner


def _load_reference(reference_id: str, owner: Optional[str]) -> dict:
    """Resolve a reference for this caller, or raise.

    404 for malformed / not-yours — never 403, which would confirm it exists.
    400 for swept-or-missing, so a user whose reference aged out is told to start
    over rather than handed a 500 (§7.3). The two are distinguishable in principle,
    but ids are 48 bits of uuid4 — enumeration is not the threat; a confusing dead
    end for a real user is.
    """
    reference_id = (reference_id or "").strip()
    if not reference_id or not reference_id.isalnum():
        raise HTTPException(404, "reference not found")
    png_path, meta_path = _reference_paths(reference_id)
    if not png_path.exists() or not meta_path.exists():
        raise HTTPException(400, "Your reference expired — start over.")
    try:
        meta = json.loads(meta_path.read_text())
    except (OSError, json.JSONDecodeError):
        raise HTTPException(400, "Your reference expired — start over.")
    if not _reference_visible(meta, owner):
        raise HTTPException(404, "reference not found")
    return meta


def _render_still(description: str, request: Request, owner: Optional[str],
                  reference_path: Optional[Path] = None,
                  strength: Optional[float] = None) -> bytes:
    """Render one still — the ~10 s GPU step, and the ONE place that knows how to
    reach a renderer.

    Mirrors render_design_still's own two shapes (§7.1) so pool and local stay one
    decision rather than two:

        reference_path=None → txt2img an archetype  (step 1's long-tail door)
        reference_path set  → img2img redraw        (step 1's upload door, step 3)

    Both /api/reference and /api/preview call this. Callers must be sync `def`
    handlers (§5.3) — this blocks ~10 s and FastAPI runs sync paths in a threadpool;
    an `async def` caller would stall the event loop and freeze /api/job polling for
    every concurrent user.
    """
    if PET_GEN_BACKEND == "pool":
        # Best-effort fast-fail (§A.3, R5-5): the pool has no per-task admission
        # control, so a still would otherwise queue silently behind a 3-min build.
        # NOT a hard guarantee — the check and the submit are two steps.
        status = pool_client.workshop_status("pet_preview")
        if not status["online"]:
            raise HTTPException(423, "The workshop is offline right now — try again in a bit.")
        if status["busy"]:
            raise HTTPException(423, "The workshop is busy generating a pet — try again in a bit.")
        params = {"description": description}
        if reference_path is not None:
            # The v1 shape. Omitting these two IS the v2 shape — it hard-fails 422
            # on a v1 node, which is why both nodes must be v2 first (§10.1).
            params["reference_image_b64"] = _encode_reference_image(reference_path)
            params["strength"] = strength
        try:
            return pool_client.run_to_result(
                "pet_preview", params,
                labels=datsme_integration.pool_labels(request, owner) or None,
                poll_interval=1.0, timeout_s=180.0)
        except pool_client.PoolError as e:
            # Surface the real cause in the server log — a missing app key or a
            # schema 422 must be distinguishable from "actually busy" for ops.
            print(f"[webui] pet_preview pool error: {e}", flush=True)
            raise HTTPException(423, "The workshop couldn't draw that just now — try again in a bit.") from e

    _, render_design_still = _local_pet_factory()
    # Fail fast instead of stalling the page behind a 3-minute generation.
    if not GPU_LOCK.acquire(timeout=1.5):
        raise HTTPException(423, "The GPU is busy generating a pet — try again in a bit.")
    try:
        if reference_path is None:
            return render_design_still(description)
        return render_design_still(description, str(reference_path), strength)
    except Exception as e:
        # The local renderer drives ComfyUI over HTTP. When it isn't up — or is on a
        # port other than PET_FACTORY_COMFY_URL claims — this raises a bare
        # ConnectionError that escapes as an opaque 500, and under a button that reads
        # as "the button is broken". The pool branch above already does the right
        # thing (log the real cause for ops, hand the user something actionable); the
        # local branch had NO handler at all. Mirror it.
        #
        # Note the boot-time warning at the top of this module covers the same
        # failure — this is the same class of problem caught at request time, where
        # the user actually meets it.
        print(f"[webui] local render failed: {e!r}", flush=True)
        raise HTTPException(
            503, "The drawing engine isn't responding — is ComfyUI running "
                 "(./start_comfyui_only.sh)?") from e
    finally:
        GPU_LOCK.release()


def _resolve_reference_door(on_catalog: bool, has_image: bool, animal: str) -> str:
    """Which door filled the box — decided ONCE, here (§7.4).

    Today start_job guards base_pet_id+image (:825-826) but nothing guards
    catalog_*+image, and its elif chain lets catalog silently win and DROP the
    upload. Deciding the door in one place closes every conflicting pair by
    construction, instead of by remembering to enumerate each new one.

    `animal` alongside an upload is a HINT ("what is this a photo of?"), not a
    second door — it names the animal without supplying a picture, which is what
    a door is.
    """
    chosen = [name for name, on in (
        ("catalog", on_catalog), ("upload", has_image), ("txt2img", bool(animal)),
    ) if on]
    if chosen == ["upload", "txt2img"]:
        return "upload"
    if len(chosen) > 1:
        raise HTTPException(400, "Pick a curated animal, name your own, or upload a "
                                 "photo — one of the three.")
    if not chosen:
        raise HTTPException(400, "Name an animal or upload a photo to start.")
    return chosen[0]


@app.post("/api/reference")
def create_reference(
    request: Request,
    catalog_animal: str = Form(""),
    catalog_breed: str = Form(""),
    animal: str = Form(""),
    image: Optional[UploadFile] = File(None),
    strength: float = Form(UPLOAD_REDRAW_STRENGTH),
):
    """Step 1: fill the box (§3). Returns one reference record.

    Three ways in, ONE artifact out — an archetype, carrying no design this flow
    applied (§2.1). Adding a fourth way (a webcam, a DatsMe avatar) is a branch
    here and nothing else: preview, generate, the engine and the pool never learn
    of it.

        catalog_animal+catalog_breed  a curated base.png     free, instant, vetted
        animal                        _base_prompt(animal)   ~10 s, the long tail
        image (+ optional animal)     an img2img redraw      ~10 s

    Sync `def`, not `async def` (§5.3): this blocks ~10 s in _render_still, so it
    must run in FastAPI's threadpool. The upload is read with image.file.read(),
    NOT `await image.read()` — the await is what would stall the event loop.
    """
    owner = datsme_integration.resolve_launch_identity(request)
    catalog_animal = catalog_animal.strip().lower()[:40]
    catalog_breed = catalog_breed.strip().lower()[:40]
    animal = animal.strip()[:60]
    has_image = image is not None and bool(image.filename)
    on_catalog = bool(catalog_animal and catalog_breed)

    door = _resolve_reference_door(on_catalog, has_image, animal)

    if door == "catalog":
        # Free, instant, vetted — a cache hit (§3.3). The curated base.png is a
        # HUMAN-APPROVED best-of-N from this same _base_prompt path
        # (animal_catalog/generate_candidates.py + promote_candidate.py). No design
        # input can reach this branch, so a hit can never degrade into a miss.
        base = animal_catalog_mod.base_image_path(catalog_animal, catalog_breed)
        if base is None:
            raise HTTPException(404, "catalog base image not found")
        return _reference_record(_save_reference(
            Path(base).read_bytes(), owner=owner,
            description=catalog_breed or catalog_animal,
            display_name=(catalog_breed or catalog_animal).title(),
            # Pinned from the catalog entry (§4.2), so the curated path always
            # animates at ≥ the fidelity free-text keyword matching would find.
            motion_profile=animal_catalog_mod.resolved_motion_profile(
                catalog_animal, catalog_breed),
            source="catalog", generated=False))

    if door == "txt2img":
        # The long tail — a cache MISS (§3.3). ~10 s and unvetted, and that is
        # honest: there was never a curated blue jay to lose. motion_profile stays
        # None so the engine keyword-resolves it from the name at build time.
        png = _render_still(animal, request, owner)
        return _reference_record(_save_reference(
            png, owner=owner, description=animal.lower(),
            display_name=animal.title(), motion_profile=None,
            source="txt2img", generated=True))

    # door == "upload": redraw it (§3.4). THIS is the change of behaviour — today
    # an uploaded photo reaches Wan I2V raw and animates unreliably, because a
    # photo is not the side-profile flat-shaded sprite make_pet_zip's docstring
    # requires. Redrawing at FILL time is what lets the user see the sprite before
    # paying for a 3-minute build.
    if image.content_type not in ALLOWED_IMAGE_MIMES:
        raise HTTPException(400, f"unsupported image type: {image.content_type}")
    body = image.file.read()          # sync — see the docstring
    if len(body) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Image exceeds 12 MB limit")

    subject = animal or "pet"
    # The user chooses how hard to redraw (§3.4): "faithful" keeps their photo's look
    # but preserves the photographic pose/lighting Wan I2V animates badly; "sprite"
    # animates reliably but looks redrawn. Only they know which side of that they
    # want, so the server takes the number and clamps it rather than deciding.
    redraw_strength = min(0.9, max(0.3, strength))
    tmp = PREVIEW_DIR / f"_upload_{uuid.uuid4().hex[:12]}"
    tmp.write_bytes(body)
    try:
        png = _render_still(subject, request, owner, reference_path=tmp,
                            strength=redraw_strength)
    finally:
        tmp.unlink(missing_ok=True)
    return _reference_record(_save_reference(
        png, owner=owner, description=subject.lower(),
        display_name=subject.title(), motion_profile=None,
        source="upload", generated=True))


@app.get("/api/reference/{reference_id}.png")
def reference_image(reference_id: str, request: Request):
    """The still. Owner-scoped, unlike the /api/preview/{id} it replaces — a
    reference can be a user's uploaded photo, so it needs the rule rows get."""
    owner = datsme_integration.resolve_launch_identity(request)
    try:
        _load_reference(reference_id, owner)
    except HTTPException as e:
        # An image endpoint has one honest failure: it isn't there. Collapse the
        # 400-expired case to 404 so a broken <img> is the whole story.
        raise HTTPException(404, "reference not found") from e
    png_path, _ = _reference_paths(reference_id)
    return FileResponse(png_path, media_type="image/png")


@app.get("/api/body-shapes")
def body_shapes_menu():
    """Step 2's body vocabulary (§7.2). Separate from /api/catalog because
    fetchCatalog discards the envelope (`data.animals ?? []`), so folding it in
    would churn every catalog consumer. Mirrors /api/motions' precedent.

    Returns {key,label,is_default} only — `prompt_fragment` is calibrated
    server-side wording and never reaches the browser, same posture as the tier
    table."""
    return {"shapes": body_shapes_mod.list_shapes(),
            "default": body_shapes_mod.default_shape_key()}


def _legacy_preview(request, owner, *, base_pet_id, catalog_animal, catalog_breed,
                    strength, color, accessories, name):
    """The pre-reference preview contract. **DELETE IN BUILD STEP 7**, whole.

    Serves /design/general, /design/cat and /design/dog until they move to the
    reference contract (step 8). It resolves a base from a house pet or a catalog
    breed — the two origins `POST /api/reference` now resolves once, at fill time.

    It mints a real reference under the hood and returns only its id as
    `preview_id`, so there is ONE store and one sweep even during the transition —
    the legacy `GET /api/preview/{id}` and the legacy generate path both read the
    same file the new endpoints do.
    """
    base_pet_id = base_pet_id.strip()
    catalog_animal = catalog_animal.strip().lower()[:40]
    catalog_breed = catalog_breed.strip().lower()[:40]
    color = color.strip().lower()[:20]
    accessory_list = [a.strip().lower()[:30] for a in accessories.split(",") if a.strip()][:3]
    if not color and not accessory_list:
        raise HTTPException(400, "Pick a color or at least one accessory to preview.")

    scratch = PREVIEW_DIR / f"_legacy_{uuid.uuid4().hex[:12]}.png"
    try:
        if base_pet_id:
            base_row = db.get_pet(base_pet_id)
            if base_row is None or not _can_access(base_row, owner):
                raise HTTPException(404, "base pet not found")
            species = base_row["display_name"].lower()
            base_frame = extract_base_frame(base_pet_id, scratch)
        elif catalog_animal and catalog_breed:
            catalog_base = animal_catalog_mod.base_image_path(catalog_animal, catalog_breed)
            if catalog_base is None:
                raise HTTPException(404, "catalog base image not found")
            species = catalog_breed
            shutil.copyfile(catalog_base, scratch)
            base_frame = scratch
        else:
            raise HTTPException(400, "Pick a base pet or a catalog breed to preview.")

        species = name.strip().lower()[:60] or species
        description, display_name, min_strength = compose_design(species, color, accessory_list)
        strength = min(0.9, max(0.3, strength))
        if min_strength:
            strength = max(strength, min_strength)
        png = _render_still(description, request, owner,
                            reference_path=base_frame, strength=strength)
    finally:
        scratch.unlink(missing_ok=True)

    meta = _save_reference(
        png, owner=owner, description=display_name.lower(), display_name=display_name,
        motion_profile=(animal_catalog_mod.resolved_motion_profile(catalog_animal, catalog_breed)
                        if catalog_animal and catalog_breed and not base_pet_id else None),
        source="design", min_strength=min_strength, generated=True)
    return {"preview_id": meta["id"]}


@app.get("/api/preview/{preview_id}")
def preview_image(preview_id: str):
    """**LEGACY, DELETE IN BUILD STEP 7.** The unscoped still-server the live pages
    still use. Deliberately left exactly as buggy as it is today — no owner check —
    rather than "fixed" here: its replacement, GET /api/reference/{id}.png, IS the
    fix (§7.3), and hardening a doomed endpoint would only make step 7 look risky.
    Nothing new may point at this."""
    if not preview_id.isalnum():
        raise HTTPException(404, "preview not found")
    path = PREVIEW_DIR / f"{preview_id}.png"
    if not path.exists():
        raise HTTPException(404, "preview not found")
    return FileResponse(path, media_type="image/png")


@app.post("/api/preview")
def preview_design(
    request: Request,
    reference_id: str = Form(""),
    strength: float = Form(0.85),
    color: str = Form(""),
    accessories: str = Form(""),
    body_shape: str = Form(""),
    extra: str = Form(""),
    name: str = Form(""),
    # ── LEGACY, DELETE IN BUILD STEP 7 — see _legacy_preview ────────────────
    base_pet_id: str = Form(""),
    catalog_animal: str = Form(""),
    catalog_breed: str = Form(""),
):
    """Step 3: see it (§5). Takes a reference, returns a REFERENCE — not a
    different kind of handle (§6.1):

        archetype ──(colour/shape/accessories/text/strength)──▶ your pet's look
        reference₁ ──────────────────────────────────────────▶ reference₂

    Two handle types would force this endpoint, the frontend, and start_job to
    branch on which kind they hold — exactly the source-agnosticism the reference
    layer buys. One store, one TTL, one URL shape, one record.

    Sync `def`, not `async def` (§5.3) — see _render_still.
    """
    owner = datsme_integration.resolve_launch_identity(request)
    if not reference_id.strip():
        return _legacy_preview(request, owner, base_pet_id=base_pet_id,
                               catalog_animal=catalog_animal, catalog_breed=catalog_breed,
                               strength=strength, color=color, accessories=accessories,
                               name=name)
    ref = _load_reference(reference_id, owner)

    color = color.strip().lower()[:20]
    accessory_list = [a.strip().lower()[:30] for a in accessories.split(",") if a.strip()][:3]
    body_shape = body_shape.strip().lower()[:20]
    extra = extra.strip()[:120]
    shaped = not body_shapes_mod.is_default(body_shape)
    if not (color or accessory_list or shaped or extra):
        # §4.1, widened from "colour or accessory" now that shape and free text
        # are design inputs too. Designing nothing is adopting, and the zero-GPU
        # adopt path exists for that.
        raise HTTPException(400, "Pick a colour, an accessory, a body shape, or "
                                 "describe a change.")

    species = name.strip().lower()[:60] or ref["description"]
    description, display_name, min_strength = compose_design(
        species, color, accessory_list, body_shape, extra)
    strength = min(0.9, max(0.3, strength))
    if min_strength:
        strength = max(strength, min_strength)

    png_path, _ = _reference_paths(ref["id"])
    png = _render_still(description, request, owner,
                        reference_path=png_path, strength=strength)

    # The new record carries the SHORT species phrase ("purple corgi"), NOT the
    # ~240-char composed design string (§7.3). Generate is always as-is now, so
    # this steers only the motion prompts, the breed_id slug and the default
    # display name — and make_pet_zip truncates at [:60] anyway. The long prompt
    # did its job here, in the redraw.
    return _reference_record(_save_reference(
        png, owner=owner, description=display_name.lower(),
        display_name=display_name,
        # A design never changes the animal, so the profile rides along unchanged.
        motion_profile=ref.get("motion_profile"),
        source="design", min_strength=min_strength, generated=True))


# Poses NOT offered in the selector at launch: triggered roles that only play if a
# DatsMe interaction behavior fires them (SPEC_MOTION_PROFILES §7/§9.1). They stay
# authored in the profiles but hidden so no user pays GPU for a pose that won't move.
_HIDDEN_POSE_ROLES = frozenset({"triggered"})


def _clip_poses_to_cap(poses_pkg: dict, max_poses: int) -> dict:
    """Clip a requested pose package to the caller's tier cap (§8.6), server-side
    and authoritative. Required poses (walk+idle) are always kept; the remaining
    slots up to max_poses are filled from the requested optional poses in
    CANONICAL order (deterministic — the same over-cap request always yields the
    same clipped set). Poses set False stay untouched (they carry no cost). This
    is the enforcement the UI cap mirrors but does not replace."""
    mp = motion_profiles_mod
    enabled = {name for name, on in poses_pkg.items() if on}
    # Required poses (walk+idle) are ALWAYS built and always count against the
    # cap — seed them unconditionally so the total can never exceed max_poses even
    # if the request omitted them. (Seeding only the *requested* required poses and
    # force-adding the rest later would let an omit-walk/idle request reach cap+2.)
    kept = set(mp.REQUIRED_POSES)
    # Fill the remaining slots from the requested OPTIONAL poses, canonical order.
    slots_left = max(0, max_poses - len(kept))
    for name in mp.CANONICAL_POSES:
        if slots_left <= 0:
            break
        if name in enabled and name not in kept:
            kept.add(name)
            slots_left -= 1
    # Rebuild: kept poses True, every other key present in the request False. The
    # required poses are guaranteed present+True (they were seeded into `kept`).
    clipped = {name: (name in kept) for name in poses_pkg}
    for req in mp.REQUIRED_POSES:
        clipped[req] = True
    return clipped


@app.get("/api/motions")
def motions(animal: str = "", profile: str = ""):
    """The pose menu for the design page (SPEC_MOTION_PROFILES §4.1). Two modes:
    - ?animal=<species>  keyword path (General free-text page) — most-specific-level match.
    - ?profile=<key>     pinned path (catalog/themed pages) — load that profile directly;
                         an unknown key is a 404 (the catalog guard test prevents shipping one).
    Returns the resolved identity (key + level) and the enabled, offerable poses."""
    mp = motion_profiles_mod
    if profile.strip():
        prof = mp.load_motion_profile(profile.strip())
        if prof.key != profile.strip():
            # load_motion_profile falls back on skew; on the MENU an unknown key is a 404.
            raise HTTPException(404, f"unknown motion profile: {profile!r}")
    else:
        prof = mp.resolve_motion_profile(animal)

    poses = []
    for name in prof.enabled_poses():
        pose = prof.pose(name)
        if pose.runtime_role in _HIDDEN_POSE_ROLES:
            continue   # authored but not offered at launch (§7)
        poses.append({
            "name": name,
            "required": name in mp.REQUIRED_POSES,
            "enabled": True,
        })
    return {
        "profile": prof.key,
        "level": prof.level,
        "movement_class": prof.movement_class,
        "poses": poses,
    }


@app.get("/api/catalog")
def catalog():
    """The base-animal tree (SPEC_PET_DESIGNER_PLATFORM §4.3): animals, each with
    its breeds, the pinned motion_profile key, and whether it has a themed page.
    Drives the landing-page tiles (§2) and each themed page's breed picker (§3.1).
    Read-only + cacheable. The browser sees only what it needs to render + route —
    the base_image_url per breed is a stable path it can <img src> directly."""
    animals = []
    for a in animal_catalog_mod.list_animals():
        breeds = []
        for b in a.get("breeds", []):
            breeds.append({
                "key": b["key"],
                "label": b.get("label", b["key"]),
                # Most-specific pinned profile for THIS breed (§4.2).
                "motion_profile": animal_catalog_mod.resolved_motion_profile(a["key"], b["key"]),
                "base_image_url": f"/api/catalog/{a['key']}/{b['key']}/base.png",
            })
        samples = [
            {
                "key": s["key"],
                "preview_url": (f"/api/catalog/{a['key']}/samples/{s['key']}/preview.png"
                                if s["has_preview"] else None),
            }
            for s in animal_catalog_mod.list_samples(a["key"])
        ]
        animals.append({
            "key": a["key"],
            "label": a.get("label", a["key"]),
            "tagline": a.get("tagline", ""),
            "motion_profile": a.get("motion_profile"),
            "themed_page": a.get("themed_page"),
            "breeds": breeds,
            "samples": samples,
        })
    return {"animals": animals}


@app.get("/api/catalog/{animal}/{breed}/base.png")
def catalog_base_image(animal: str, breed: str):
    """Serve a breed's curated base sprite (§4.3) — a static file load, so the
    themed page can show the base the moment animal→breed is chosen, no
    generation. 404 for an un-curated breed (the long tail falls back to the
    General path, §4.5). Keys are catalog-validated so no path traversal reaches
    the filesystem, but re-guard defensively."""
    if not (animal.isalnum() and breed.isalnum()):
        raise HTTPException(404, "base image not found")
    path = animal_catalog_mod.base_image_path(animal, breed)
    if path is None:
        raise HTTPException(404, "base image not found")
    # Curated bases ship read-only with the package; cache aggressively.
    return FileResponse(path, media_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400"})


@app.get("/api/entitlement")
def entitlement(request: Request):
    """The caller's OWN resolved entitlement (SPEC_PET_DESIGNER_PLATFORM §5.3):
    max poses, extra-pose price, adopt permission, upsell copy. Resolved from the
    DPP launch capabilities (standalone → the default 'base' tier). The browser
    never sees the whole tier table — only this, its own slice — so the pose
    selector caps + pricing hint come from the server, not a client constant."""
    caps = datsme_integration.resolve_launch_capabilities(request)
    ent = tiers_mod.resolve_entitlement(caps)
    # The base credit cost the host charges (the extra-pose price is per-pose on
    # top); surface both so the UI can show the full resolved price up front.
    ent["base_design_cost"] = datsme_integration.pet_design_cost()
    return ent


@app.get("/api/catalog/{animal}/samples/{sample}/preview.png")
def catalog_sample_preview(animal: str, sample: str):
    """The gallery portrait for an adoptable sample (§4.4). 404 if absent."""
    if not (animal.isalnum() and sample.isalnum()):
        raise HTTPException(404, "sample preview not found")
    path = animal_catalog_mod.sample_preview_path(animal, sample)
    if path is None:
        raise HTTPException(404, "sample preview not found")
    return FileResponse(path, media_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400"})


@app.post("/api/catalog/{animal}/samples/{sample}/adopt")
def adopt_sample(animal: str, sample: str, request: Request):
    """Adopt a pre-made sample pet directly (§4.4) — generation-free (zero GPU).
    Copies the stored sample bundle into the caller's house as a DRAFT via the
    SAME insert path a generated pet takes (minus the build), then returns the
    new pet id so the frontend runs its normal Save/Accept flow. Scoped to the
    caller's identity exactly like a generated pet."""
    if not (animal.isalnum() and sample.isalnum()):
        raise HTTPException(404, "sample not found")
    bundle_path = animal_catalog_mod.sample_bundle_path(animal, sample)
    if bundle_path is None:
        raise HTTPException(404, "sample not found")
    owner = datsme_integration.resolve_launch_identity(request)

    zip_bytes = bundle_path.read_bytes()
    sheet_png, manifest_json, package_json, display_name, breed_id = _unpack_bundle(
        zip_bytes, default_display_name=sample.title())
    if sheet_png is None or manifest_json is None:
        raise HTTPException(500, "sample bundle is malformed")

    pet_id = uuid.uuid4().hex[:12]
    db.insert_pet(
        pet_id=pet_id, breed_id=breed_id or sample, display_name=display_name,
        created_at=time.time(), draft=True,
        sheet_png=sheet_png, manifest_json=manifest_json,
        package_json=package_json, bundle_zip=zip_bytes,
        external_user_id=owner,
    )
    return {"pet_id": pet_id, "display_name": display_name, "breed_id": breed_id or sample}


@app.get("/api/workshop-status")
def workshop_status():
    """Pet-worker liveness for the 'workshop offline/busy' UI (§C.1a). The SERVER
    calls the pool's /api/pool with the app key and returns only the two booleans
    the frontend needs — the key never reaches the browser (Finding 9). In local
    mode there is no pool, so report online + not-busy (the on-box GPU is the
    'workshop', and the preview path's own GPU_LOCK handles busy)."""
    if PET_GEN_BACKEND != "pool":
        return {"online": True, "busy": False}
    return pool_client.workshop_status("pet_preview")


@app.get("/api/health")
def health():
    """Liveness + dependency summary for monitoring (§7 step 9). Cheap enough
    to poll: at most one /api/pool read (8 s timeout, fail-safe offline)."""
    with JOBS_LOCK:
        active = sum(1 for j in JOBS.values() if j.status in ("queued", "running"))
    out = {"status": "ok", "backend": PET_GEN_BACKEND, "active_jobs": active}
    if PET_GEN_BACKEND == "pool":
        out["workshop"] = pool_client.workshop_status("pet_factory")
    return out


async def _legacy_resolve_base(request, owner, *, name, text, image, base_pet_id,
                               catalog_animal, catalog_breed, strength, color,
                               accessories, preview_id):
    """The pre-reference contract, quarantined. **DELETE IN BUILD STEP 7**, whole.

    This is the code SPEC_PET_DESIGNER_FLOW exists to remove: three per-origin
    chains that re-derive the description, the reference image and the strength
    from "which origin was this?" at BUILD time — the thing `reference_id` resolves
    once at FILL time instead. It is lifted here verbatim rather than left inline so
    that (a) the new path above reads as the whole story, and (b) step 7 is one
    deletion, not an archaeology exercise.

    It serves /design/general, /design/cat, /design/dog and /make until those move
    to the reference contract (step 8). Nothing new may call it.
    """
    text = text.strip()[:200]
    base_pet_id = base_pet_id.strip()
    catalog_animal = catalog_animal.strip().lower()[:40]
    catalog_breed = catalog_breed.strip().lower()[:40]
    preview_id = preview_id.strip()
    color = color.strip().lower()[:20]
    accessory_list = [a.strip().lower()[:30] for a in accessories.split(",") if a.strip()][:3]

    catalog_base_path = None
    catalog_species = None
    if catalog_animal and catalog_breed and not base_pet_id:
        catalog_base_path = animal_catalog_mod.base_image_path(catalog_animal, catalog_breed)
        if catalog_base_path is None:
            raise HTTPException(404, "catalog base image not found")
        catalog_species = catalog_breed or catalog_animal

    has_image = image is not None and bool(image.filename)
    has_design = bool(color or accessory_list)
    on_catalog = catalog_base_path is not None
    if has_image and image.content_type not in ALLOWED_IMAGE_MIMES:
        raise HTTPException(400, f"unsupported image type: {image.content_type}")
    if base_pet_id and has_image:
        raise HTTPException(400, "Redesign a house pet OR upload an image — not both.")
    if base_pet_id and not (name or text or has_design):
        raise HTTPException(400, "Pick a color/accessories or describe the new look.")
    if on_catalog and not (name or has_design):
        raise HTTPException(400, "Pick a color/accessories or a name for your design.")
    if not base_pet_id and not on_catalog and not text and not name and not has_image:
        raise HTTPException(400, "Describe the pet OR drop in a reference image.")

    display_name = None
    if base_pet_id and has_design:
        base_row = db.get_pet(base_pet_id)
        if base_row is None or not _can_access(base_row, owner):
            raise HTTPException(404, "base pet not found")
        species = name.lower() or base_row["display_name"].lower()
        description, display_name, min_strength = compose_design(species, color, accessory_list)
        if min_strength:
            strength = max(strength, min_strength)
    elif on_catalog:
        species = name.lower() or catalog_species
        description, display_name, min_strength = compose_design(species, color, accessory_list)
        if min_strength:
            strength = max(strength, min_strength)
    else:
        description = name or text or "pet"

    motion_profile = None
    if catalog_base_path is not None:
        motion_profile = animal_catalog_mod.resolved_motion_profile(catalog_animal, catalog_breed)

    job_dir = SCRATCH_DIR / uuid.uuid4().hex[:12]
    job_dir.mkdir(parents=True, exist_ok=True)
    reference_image = None
    remix_strength = None
    if (base_pet_id or on_catalog) and preview_id and preview_id.isalnum() \
            and (PREVIEW_DIR / f"{preview_id}.png").exists():
        reference_image = PREVIEW_DIR / f"{preview_id}.png"
    elif base_pet_id:
        reference_image = extract_base_frame(base_pet_id, job_dir / "remix_base.png")
        remix_strength = min(0.9, max(0.3, strength))
    elif on_catalog:
        reference_image = job_dir / "catalog_base.png"
        shutil.copyfile(catalog_base_path, reference_image)
        remix_strength = min(0.9, max(0.3, strength))
    elif has_image:
        body = await image.read()
        if len(body) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "Image exceeds 12 MB limit")
        reference_image = job_dir / "reference_upload"
        reference_image.write_bytes(body)

    return (description, display_name or description, reference_image,
            remix_strength, motion_profile)


@app.post("/api/generate")
async def start_job(
    request: Request,
    reference_id: str = Form(""),
    name: str = Form(""),
    poses: str = Form(""),
    motion_profile: str = Form(""),
    # ── LEGACY, DELETE IN BUILD STEP 7 ──────────────────────────────────────
    # The pre-reference contract, still served so /design/general, /design/cat,
    # /design/dog and /make keep working while /design/general2 is built on the
    # new one (build order step 5: "legacy fields still accepted"). Every one of
    # these is resolved at FILL time under `reference_id`. They come out together
    # with the old frontends, in step 7 — this fork is time-boxed on purpose.
    text: str = Form(""),
    image: Optional[UploadFile] = File(None),
    base_pet_id: str = Form(""),
    catalog_animal: str = Form(""),
    catalog_breed: str = Form(""),
    strength: float = Form(0.85),
    color: str = Form(""),
    accessories: str = Form(""),
    preview_id: str = Form(""),
):
    # Who is generating? DatsMe-launched user (verified) or None (standalone).
    # This scopes the generated pet, the draft purge, and any base-pet lookup
    # so one user's Generate never touches another user's (or the local) pets.
    owner = datsme_integration.resolve_launch_identity(request)
    name = name.strip()[:60]
    reference_id = reference_id.strip()

    if reference_id:
        # THE PAYOFF (§6, §7.3). Three per-origin chains used to live below — the
        # motion profile, the description, and the reference image + strength were
        # each re-derived from "which origin was this?" at build time. The record
        # already carries all of it, resolved once at FILL time where the animal and
        # breed were actually known. So the chains are not relocated; they are gone.
        ref = _load_reference(reference_id, owner)      # 404 not-yours · 400 expired
        reference_image, _ = _reference_paths(ref["id"])
        description = ref.get("description") or "pet"
        display_name = name or ref.get("display_name") or description.title()
        remix_strength = None       # ALWAYS as-is — see the thread kwargs below
        legacy_motion_profile = ref.get("motion_profile")
    else:
        (description, display_name, reference_image, remix_strength,
         legacy_motion_profile) = await _legacy_resolve_base(
            request, owner, name=name, text=text, image=image,
            base_pet_id=base_pet_id, catalog_animal=catalog_animal,
            catalog_breed=catalog_breed, strength=strength, color=color,
            accessories=accessories, preview_id=preview_id)

    # Motion-profile package (SPEC_MOTION_PROFILES §4.3/§5.1). `poses` is a JSON
    # {name: bool} string in the form body; malformed → None (walk+idle default).
    # make_pet_zip does the enabled-∩-requested-∪-required intersection, so the web
    # tier only parses safely and forwards.
    poses_pkg = None
    if poses.strip():
        try:
            parsed = json.loads(poses)
            if isinstance(parsed, dict):
                poses_pkg = {str(k): bool(v) for k, v in parsed.items()}
        except (json.JSONDecodeError, TypeError, ValueError):
            poses_pkg = None   # malformed → safe default (walk+idle)
    # An explicit override wins; otherwise the pinned key resolved at fill time from
    # the catalog entry (§4.2) — so the curated path always animates at ≥ the
    # fidelity free-text keyword matching would find. None → the engine keyword-
    # resolves from `description`, which is the long tail's path.
    motion_profile = motion_profile.strip()[:60] or legacy_motion_profile or None

    # SERVER-SIDE tier enforcement (§8.6): the UI caps the pose selector, but the
    # server is authoritative — a request over the caller's cap is CLIPPED here,
    # not trusted. Resolve the caller's entitlement (standalone → base = 2 poses)
    # and clip the requested set to max_poses, always keeping walk+idle. Without
    # this, the only server cap is the global MAX_POSES=10 and every user gets the
    # plus cap unpriced. Clip (don't 400) so a legitimate over-cap UI never hard-errors.
    if poses_pkg is not None:
        caps = datsme_integration.resolve_launch_capabilities(request)
        max_poses = tiers_mod.resolve_entitlement(caps)["max_poses"]
        poses_pkg = _clip_poses_to_cap(poses_pkg, max_poses)

    # Starting a new generation supersedes THIS caller's unsaved draft. Scope
    # the purge to the caller so a launched user's Generate never deletes
    # another user's (or the local user's) draft.
    _purge_drafts(owner)

    job_id = uuid.uuid4().hex[:12]
    job_dir = SCRATCH_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    job = Job(id=job_id, name=display_name, dir=job_dir,
              external_user_id=owner,
              # Capture attribution NOW, in the request context — the generation
              # thread below can't see the request's User-Agent.
              pool_labels=datsme_integration.pool_labels(request, owner))
    with JOBS_LOCK:
        JOBS[job_id] = job

    threading.Thread(
        target=run_pet_job, args=(job,),
        # On the reference path remix_strength is ALWAYS None: the still is one the
        # user has already seen and approved, so the build animates it AS-IS (§1).
        # Redrawing here would re-roll the look after they said yes to it. The engine
        # keeps its remix and text branches for the CLI (§7.1) — and, until step 7,
        # for _legacy_resolve_base, which is the only thing that still sets this.
        kwargs={"description": description, "reference_image": reference_image,
                "remix_strength": remix_strength, "display_name": display_name,
                "poses": poses_pkg, "motion_profile": motion_profile},
        daemon=True,
    ).start()
    return {"job_id": job_id}


@app.get("/api/job/{job_id}")
def job_status(job_id: str):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            raise HTTPException(404, "job not found")
        return job.to_dict()


def _can_access(row, owner: Optional[str]) -> bool:
    """A pet is visible to a caller iff it is local (unowned) or theirs.
    `owner` is the caller's DatsMe user_id, or None for standalone."""
    ext = row["external_user_id"]
    return ext is None or ext == owner


def _purge_drafts(external_user_id: Optional[str] = "__all__") -> None:
    """Remove unsaved drafts. Default "__all__" (startup: clears leftovers from
    every user). Pass a user_id (or None for standalone) to purge ONLY that
    caller's drafts — so one user's new generation never deletes another
    user's or the local user's in-progress draft."""
    dropped = db.purge_drafts(external_user_id)
    with JOBS_LOCK:
        for pet_id in dropped:
            JOBS.pop(pet_id, None)


_purge_drafts()        # startup cleanup — "__all__" scope
_reattach_pool_jobs()  # Opt-1: resume pool jobs orphaned by a restart


@app.get("/api/pets")
def list_pets(request: Request):
    """Every SAVED pet the caller may see, newest first. A DatsMe-launched
    user sees only their own pets; a standalone caller sees the local
    (external_user_id IS NULL) pets. Drafts are excluded (join via /keep)."""
    owner = datsme_integration.resolve_launch_identity(request)
    return db.list_saved_pets(external_user_id=owner)


@app.post("/api/pets/{pet_id}/keep")
def keep_pet(pet_id: str, request: Request):
    """The user's explicit 'save this pet' — clears the draft flag so the pet
    joins the house. Scoped: you can only keep a pet you may access."""
    if not pet_id.isalnum():
        raise HTTPException(404, "pet not found")
    owner = datsme_integration.resolve_launch_identity(request)
    record = db.keep_pet(pet_id, external_user_id=owner)
    if record is None:
        raise HTTPException(404, "pet not found")
    return record


def _require_pet(pet_id: str, owner: Optional[str]):
    # pet_id is always one of our uuid4 hex job ids — reject anything that
    # could traverse / injection-shape, load the row, then enforce access
    # (404, not 403 — don't leak that a pet exists for another user).
    if not pet_id.isalnum():
        raise HTTPException(404, "pet not found")
    row = db.get_pet(pet_id)
    if row is None or not _can_access(row, owner):
        raise HTTPException(404, "pet not found")
    return row


@app.get("/api/pets/{pet_id}/sheet.png")
def pet_sheet(pet_id: str, request: Request):
    row = _require_pet(pet_id, datsme_integration.resolve_launch_identity(request))
    return Response(content=row["sheet_png"], media_type="image/png")


@app.get("/api/pets/{pet_id}/manifest.json")
def pet_manifest(pet_id: str, request: Request):
    row = _require_pet(pet_id, datsme_integration.resolve_launch_identity(request))
    return Response(content=row["manifest_json"], media_type="application/json")


@app.delete("/api/pets/{pet_id}")
def delete_pet(pet_id: str, request: Request):
    """Remove a pet from the house permanently. 404 if it isn't a stored pet
    the caller may access."""
    if not pet_id.isalnum():
        raise HTTPException(404, "pet not found")
    owner = datsme_integration.resolve_launch_identity(request)
    if not db.delete_pet(pet_id, external_user_id=owner):
        raise HTTPException(404, "pet not found")
    with JOBS_LOCK:
        JOBS.pop(pet_id, None)
    return {"deleted": pet_id}


@app.get("/api/pets/{pet_id}/zip")
def pet_zip(pet_id: str, request: Request):
    row = _require_pet(pet_id, datsme_integration.resolve_launch_identity(request))
    return Response(
        content=row["bundle_zip"], media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{row["breed_id"]}.zip"'},
    )


# ---------------------------------------------------------------------------
# Production posture (§7 step 9): one maintenance thread owns the periodic
# work — the DPP retry-queue drain (queued writebacks deliver without waiting
# for user traffic) and transient retention (preview stills, job scratch dirs,
# long-expired bundle tokens). Started from the ASGI startup hook, so plain
# imports (tests, tooling) never spawn it.
# ---------------------------------------------------------------------------
MAINTENANCE_TICK_S = 60
RETRY_DRAIN_EVERY_S = 5 * 60
TRANSIENT_SWEEP_EVERY_S = 60 * 60
TRANSIENT_MAX_AGE_S = 24 * 60 * 60


def _cleanup_transients(max_age_s: float = TRANSIENT_MAX_AGE_S) -> int:
    """Remove preview stills and job scratch dirs older than max_age_s — they
    are working files; pets live in the DB — plus long-expired bundle tokens.
    Scratch dirs of still-active jobs are never touched. Returns items removed."""
    cutoff = time.time() - max_age_s
    removed = 0
    for f in PREVIEW_DIR.iterdir():
        try:
            if f.is_file() and f.stat().st_mtime < cutoff:
                f.unlink()
                removed += 1
        except OSError:
            continue
    for d in SCRATCH_DIR.iterdir():
        with JOBS_LOCK:
            job = JOBS.get(d.name)
            active = job is not None and job.status in ("queued", "running")
        try:
            if not active and d.stat().st_mtime < cutoff:
                shutil.rmtree(d, ignore_errors=True)
                removed += 1
        except OSError:
            continue
    removed += db.purge_expired_bundle_tokens()
    return removed


def _maintenance_loop() -> None:
    last_drain = 0.0
    last_sweep = 0.0
    while True:
        now = time.monotonic()
        # Drain only when DPP is configured — an unconfigured standalone
        # install has no secret and nothing queued worth warning about.
        if os.environ.get("DATSME_HMAC_SECRET") and now - last_drain >= RETRY_DRAIN_EVERY_S:
            last_drain = now
            try:
                drained = datsme_integration.drain_retry_queue()
                if drained:
                    print(f"[webui] retry-drain attempted {len(drained)} writeback(s)", flush=True)
            except Exception as e:
                print(f"[webui] retry-drain failed: {e}", flush=True)
        if now - last_sweep >= TRANSIENT_SWEEP_EVERY_S:
            last_sweep = now
            try:
                n = _cleanup_transients()
                if n:
                    print(f"[webui] transient sweep removed {n} item(s)", flush=True)
            except Exception as e:
                print(f"[webui] transient sweep failed: {e}", flush=True)
        time.sleep(MAINTENANCE_TICK_S)


@app.on_event("startup")
def _start_maintenance() -> None:
    threading.Thread(target=_maintenance_loop, daemon=True,
                     name="datspet-maintenance").start()


if __name__ == "__main__":
    import uvicorn
    # Bind IPv4 loopback 127.0.0.1. "localhost" resolves here on this box, and the
    # whole stack (this bind, NEXT_PUBLIC_API_URL, DATSPET_PUBLIC_URL,
    # DATSPET_FRONTEND_URL) must share ONE hostname so the DPP launch cookie is
    # sent on API calls — a 127.0.0.1/localhost split drops the cookie and hides
    # the Accept-to-DatsMe button. Mirrors start_petmaker_backend_only.sh.
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PETMAKER_BACKEND_PORT", 19954)))
