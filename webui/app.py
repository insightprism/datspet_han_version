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

# Generation backend (spec §A.6): "local" runs the on-box GPU directly (dev / break-
# glass); "pool" routes generation to the shared_gpu_cpu pool (prod, GPU-less box).
# The web tier is otherwise identical either way — only the generation SOURCE changes.
PET_GEN_BACKEND = os.environ.get("PET_GEN_BACKEND", "local").strip().lower()

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


def compose_design(species: str, color: str, accessories: list[str]) -> tuple[str, str, Optional[float]]:
    """Turn the design page's structured picks into (prompt_description,
    display_name, min_strength). Prompt wording follows the remix calibration:
    'recolored entirely {color}' is what actually flips a color against the
    source image. min_strength is 0.9 when the species name itself contains a
    conflicting color word (see _COLOR_WORDS), else None. The display name
    stays short — color + species, not the accessory list."""
    # Clause order matters (calibrated on stills): accessories directly after
    # the species, the recolor emphasis LAST. With the recolor clause in the
    # middle, the accessory gets dropped; with accessories last, the color
    # loses. This ordering keeps both.
    min_strength = None
    description = f"vivid {color} {species}" if color else species
    if accessories:
        worn = []
        for acc in accessories:
            if acc in _PLURAL_ACCESSORIES:
                worn.append(acc)
            else:
                worn.append(("an " if acc[0] in "aeiou" else "a ") + acc)
        description += " wearing " + ", ".join(worn)
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
    pool_job_id = pool_client.submit("pet_factory", params)
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


@app.post("/api/preview")
def preview_design(
    request: Request,
    base_pet_id: str = Form(""),
    catalog_animal: str = Form(""),
    catalog_breed: str = Form(""),
    strength: float = Form(0.85),
    color: str = Form(""),
    accessories: str = Form(""),
    name: str = Form(""),
):
    """Run ONLY the redraw stage (~10 s) and return a preview id. The design
    page shows the image next to the original; /api/generate can then be
    given the preview_id to animate this exact still. Two base sources
    (§4.3): a house pet (`base_pet_id`) or a curated catalog breed
    (`catalog_animal`+`catalog_breed`)."""
    owner = datsme_integration.resolve_launch_identity(request)
    base_pet_id = base_pet_id.strip()
    catalog_animal = catalog_animal.strip().lower()[:40]
    catalog_breed = catalog_breed.strip().lower()[:40]
    color = color.strip().lower()[:20]
    accessory_list = [a.strip().lower()[:30] for a in accessories.split(",") if a.strip()][:3]
    if not color and not accessory_list:
        raise HTTPException(400, "Pick a color or at least one accessory to preview.")

    preview_id = uuid.uuid4().hex[:12]
    if base_pet_id:
        base_row = db.get_pet(base_pet_id)
        if base_row is None or not _can_access(base_row, owner):
            raise HTTPException(404, "base pet not found")
        species = base_row["display_name"].lower()
        base_frame = extract_base_frame(base_pet_id, PREVIEW_DIR / f"{preview_id}_base.png")
    elif catalog_animal and catalog_breed:
        catalog_base = animal_catalog_mod.base_image_path(catalog_animal, catalog_breed)
        if catalog_base is None:
            raise HTTPException(404, "catalog base image not found")
        species = catalog_breed
        base_frame = PREVIEW_DIR / f"{preview_id}_base.png"
        shutil.copyfile(catalog_base, base_frame)
    else:
        raise HTTPException(400, "Pick a base pet or a catalog breed to preview.")
    species = name.strip().lower()[:60] or species
    description, _display, min_strength = compose_design(species, color, accessory_list)
    strength = min(0.9, max(0.3, strength))
    if min_strength:
        strength = max(strength, min_strength)

    if PET_GEN_BACKEND == "pool":
        # Best-effort fast-fail (§A.3, R5-5): the pool has no per-task admission
        # control, so a preview would otherwise queue silently behind a 3-min
        # build. Check pet-worker busy-state first and return the same 423 the
        # local path does. NOT a hard guarantee — the check and the submit are two
        # steps, so an occasional preview can still queue behind a concurrent build.
        status = pool_client.workshop_status("pet_preview")
        if not status["online"]:
            raise HTTPException(423, "The workshop is offline right now — try again in a bit.")
        if status["busy"]:
            raise HTTPException(423, "The workshop is busy generating a pet — try again in a bit.")
        try:
            png = pool_client.run_to_result(
                "pet_preview",
                {"reference_image_b64": _encode_reference_image(base_frame),
                 "description": description, "strength": strength},
                poll_interval=1.0, timeout_s=180.0)
        except pool_client.PoolError as e:
            # Surface the real cause in the server log — a missing app key or a
            # schema 422 must be distinguishable from "actually busy" for ops.
            print(f"[webui] pet_preview pool error: {e}", flush=True)
            raise HTTPException(423, "The workshop couldn't preview that just now — try again in a bit.") from e
    else:
        _, render_design_still = _local_pet_factory()
        # Fail fast instead of stalling the page behind a 3-minute generation.
        if not GPU_LOCK.acquire(timeout=1.5):
            raise HTTPException(423, "The GPU is busy generating a pet — try again in a bit.")
        try:
            png = render_design_still(description, base_frame, strength)
        finally:
            GPU_LOCK.release()

    (PREVIEW_DIR / f"{preview_id}.png").write_bytes(png)
    return {"preview_id": preview_id}


@app.get("/api/preview/{preview_id}")
def preview_image(preview_id: str):
    if not preview_id.isalnum():
        raise HTTPException(404, "preview not found")
    path = PREVIEW_DIR / f"{preview_id}.png"
    if not path.exists():
        raise HTTPException(404, "preview not found")
    return FileResponse(path, media_type="image/png")


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


@app.post("/api/generate")
async def start_job(
    request: Request,
    name: str = Form(""),
    text: str = Form(""),
    image: Optional[UploadFile] = File(None),
    base_pet_id: str = Form(""),
    catalog_animal: str = Form(""),
    catalog_breed: str = Form(""),
    strength: float = Form(0.85),
    color: str = Form(""),
    accessories: str = Form(""),
    preview_id: str = Form(""),
    poses: str = Form(""),
    motion_profile: str = Form(""),
):
    # Who is generating? DatsMe-launched user (verified) or None (standalone).
    # This scopes the generated pet, the draft purge, and any base-pet lookup
    # so one user's Generate never touches another user's (or the local) pets.
    owner = datsme_integration.resolve_launch_identity(request)
    name = name.strip()[:60]
    text = text.strip()[:200]
    base_pet_id = base_pet_id.strip()
    catalog_animal = catalog_animal.strip().lower()[:40]
    catalog_breed = catalog_breed.strip().lower()[:40]
    preview_id = preview_id.strip()
    color = color.strip().lower()[:20]
    accessory_list = [a.strip().lower()[:30] for a in accessories.split(",") if a.strip()][:3]

    # Catalog base source (SPEC_PET_DESIGNER_PLATFORM §4.3): a themed page sends
    # the chosen animal/breed instead of a house base_pet_id. The curated base.png
    # is the img2img source (no cold-start Z-Image), and the catalog's pinned
    # motion_profile governs the build unless the caller overrode it. Resolve it
    # up front so the same design/prompt path handles catalog and house bases.
    catalog_base_path = None
    catalog_species = None
    if catalog_animal and catalog_breed and not base_pet_id:
        catalog_base_path = animal_catalog_mod.base_image_path(catalog_animal, catalog_breed)
        if catalog_base_path is None:
            raise HTTPException(404, "catalog base image not found")
        # Species for the prompt = the breed label ("Corgi"), animal as fallback.
        catalog_species = catalog_breed or catalog_animal

    # Motion-profile package (SPEC_MOTION_PROFILES §4.3/§5.1). `poses` is a JSON
    # {name: bool} string in the form body; malformed → None (walk+idle default).
    # `motion_profile` is the catalog's pinned profile key (empty → keyword
    # resolution from the description). make_pet_zip does the enabled-∩-requested-∪-
    # required intersection, so the web tier only parses safely and forwards.
    poses_pkg = None
    if poses.strip():
        try:
            parsed = json.loads(poses)
            if isinstance(parsed, dict):
                poses_pkg = {str(k): bool(v) for k, v in parsed.items()}
        except (json.JSONDecodeError, TypeError, ValueError):
            poses_pkg = None   # malformed → safe default (walk+idle)
    motion_profile = motion_profile.strip()[:60] or None
    # A catalog build pins its motion_profile from the catalog entry (§4.2) unless
    # the caller supplied one — so the curated path always animates at ≥ the
    # fidelity free-text keyword matching would find (the Rev.3 guarantee).
    if motion_profile is None and catalog_base_path is not None:
        motion_profile = animal_catalog_mod.resolved_motion_profile(catalog_animal, catalog_breed)

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
        # Design page: compose the prompt from structured picks. The species
        # is the base pet's own name unless the user overrode it. The base pet
        # must be visible to this caller (their own or a local pet), else 404.
        base_row = db.get_pet(base_pet_id)
        if base_row is None or not _can_access(base_row, owner):
            raise HTTPException(404, "base pet not found")
        species = base_row["display_name"].lower()
        species = name.lower() or species
        description, display_name, min_strength = compose_design(species, color, accessory_list)
        if min_strength:
            strength = max(strength, min_strength)
    elif on_catalog:
        # Themed/catalog path: same structured-prompt composition as the house
        # design path, but the species is the curated breed (overridable by name)
        # and the starting image is the curated base.png (set below).
        species = name.lower() or catalog_species
        description, display_name, min_strength = compose_design(species, color, accessory_list)
        if min_strength:
            strength = max(strength, min_strength)
    else:
        # Free-text paths: explicit name > description > generic. This string
        # also steers the motion prompts, so a short species-ish phrase works
        # best.
        description = name or text or "pet"

    # Starting a new generation supersedes THIS caller's unsaved draft. Scope
    # the purge to the caller so a launched user's Generate never deletes
    # another user's (or the local user's) draft.
    _purge_drafts(owner)

    job_id = uuid.uuid4().hex[:12]
    job_dir = SCRATCH_DIR / job_id   # transient: reference upload, remix base
    job_dir.mkdir(parents=True, exist_ok=True)

    reference_image = None
    remix_strength = None
    if (base_pet_id or on_catalog) and preview_id and preview_id.isalnum() \
            and (PREVIEW_DIR / f"{preview_id}.png").exists():
        # The user previewed this design — animate the EXACT still they saw
        # (no second redraw, no re-roll of the look). Same for house and catalog.
        reference_image = PREVIEW_DIR / f"{preview_id}.png"
    elif base_pet_id:
        # Redesign path: the base pet's own resting frame is the starting
        # image, redrawn toward the new description at the requested strength.
        reference_image = extract_base_frame(base_pet_id, job_dir / "remix_base.png")
        remix_strength = min(0.9, max(0.3, strength))
    elif on_catalog:
        # Catalog path (§4.3): the curated base.png is the img2img source —
        # copied into the job scratch dir so it's a plain local path the local
        # and pool backends both consume identically (the pool encoder base64s
        # it as reference_image_b64, the existing v2 transport — no new field).
        reference_image = job_dir / "catalog_base.png"
        shutil.copyfile(catalog_base_path, reference_image)
        remix_strength = min(0.9, max(0.3, strength))
    elif has_image:
        body = await image.read()
        if len(body) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "Image exceeds 12 MB limit")
        reference_image = job_dir / "reference_upload"
        reference_image.write_bytes(body)

    job = Job(id=job_id, name=display_name or description, dir=job_dir,
              external_user_id=owner)
    with JOBS_LOCK:
        JOBS[job_id] = job

    threading.Thread(
        target=run_pet_job, args=(job,),
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
