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
from pet_factory import make_pet_zip, render_design_still

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


def run_pet_job(job: Job, *, description: str, reference_image: Optional[Path],
                remix_strength: Optional[float] = None,
                display_name: Optional[str] = None) -> None:
    """Runs in a daemon thread. Mutates `job` as it goes; never raises.
    On success the finished pet is persisted as one DB row (sheet/manifest/
    package/zip as blobs), born a DRAFT — it joins the house only when the
    user saves (POST /api/pets/{id}/keep)."""
    try:
        with GPU_LOCK:
            with JOBS_LOCK:
                job.status = "running"

            def on_progress(msg, pct):
                with JOBS_LOCK:
                    job.message = msg
                    job.progress = pct

            breed_id, zip_bytes = make_pet_zip(
                description, on_progress=on_progress,
                reference_image=str(reference_image) if reference_image else None,
                remix_strength=remix_strength, display_name=display_name)

        # Unpack sheet/manifest/package out of the bundle so the engine can
        # render the pet without unzipping in the browser. Bytes go in the DB.
        sheet_png = None
        manifest_json = None
        package_json = None
        display_name = description.title()
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
            for member in z.namelist():
                if member.endswith("_sprite.png"):
                    sheet_png = z.read(member)
                elif member == "manifest.json":
                    manifest_json = z.read(member).decode("utf-8")
                elif member == "package.json":
                    package_json = z.read(member).decode("utf-8")
                    display_name = json.loads(package_json).get("display_name", display_name)

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
    except Exception as e:
        with JOBS_LOCK:
            job.status = "error"
            job.error = str(e)
            job.message = f"Error: {e}"
            job.finished_at = time.time()


@app.post("/api/preview")
def preview_design(
    request: Request,
    base_pet_id: str = Form(...),
    strength: float = Form(0.85),
    color: str = Form(""),
    accessories: str = Form(""),
    name: str = Form(""),
):
    """Run ONLY the redraw stage (~10 s) and return a preview id. The design
    page shows the image next to the original; /api/generate can then be
    given the preview_id to animate this exact still."""
    owner = datsme_integration.resolve_launch_identity(request)
    base_pet_id = base_pet_id.strip()
    color = color.strip().lower()[:20]
    accessory_list = [a.strip().lower()[:30] for a in accessories.split(",") if a.strip()][:3]
    if not color and not accessory_list:
        raise HTTPException(400, "Pick a color or at least one accessory to preview.")

    base_row = db.get_pet(base_pet_id)
    if base_row is None or not _can_access(base_row, owner):
        raise HTTPException(404, "base pet not found")
    species = base_row["display_name"].lower()
    species = name.strip().lower()[:60] or species
    description, _display, min_strength = compose_design(species, color, accessory_list)
    strength = min(0.9, max(0.3, strength))
    if min_strength:
        strength = max(strength, min_strength)

    preview_id = uuid.uuid4().hex[:12]
    base_frame = extract_base_frame(base_pet_id, PREVIEW_DIR / f"{preview_id}_base.png")

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


@app.post("/api/generate")
async def start_job(
    request: Request,
    name: str = Form(""),
    text: str = Form(""),
    image: Optional[UploadFile] = File(None),
    base_pet_id: str = Form(""),
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
    text = text.strip()[:200]
    base_pet_id = base_pet_id.strip()
    preview_id = preview_id.strip()
    color = color.strip().lower()[:20]
    accessory_list = [a.strip().lower()[:30] for a in accessories.split(",") if a.strip()][:3]

    has_image = image is not None and bool(image.filename)
    has_design = bool(color or accessory_list)
    if has_image and image.content_type not in ALLOWED_IMAGE_MIMES:
        raise HTTPException(400, f"unsupported image type: {image.content_type}")
    if base_pet_id and has_image:
        raise HTTPException(400, "Redesign a house pet OR upload an image — not both.")
    if base_pet_id and not (name or text or has_design):
        raise HTTPException(400, "Pick a color/accessories or describe the new look.")
    if not base_pet_id and not text and not name and not has_image:
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
    if base_pet_id and preview_id and preview_id.isalnum() \
            and (PREVIEW_DIR / f"{preview_id}.png").exists():
        # The user previewed this design — animate the EXACT still they saw
        # (no second redraw, no re-roll of the look).
        reference_image = PREVIEW_DIR / f"{preview_id}.png"
    elif base_pet_id:
        # Redesign path: the base pet's own resting frame is the starting
        # image, redrawn toward the new description at the requested strength.
        reference_image = extract_base_frame(base_pet_id, job_dir / "remix_base.png")
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
                "remix_strength": remix_strength, "display_name": display_name},
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


_purge_drafts()  # startup cleanup — "__all__" scope


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


if __name__ == "__main__":
    import uvicorn
    # Bind IPv4 loopback 127.0.0.1. "localhost" resolves here on this box, and the
    # whole stack (this bind, NEXT_PUBLIC_API_URL, DATSPET_PUBLIC_URL,
    # DATSPET_FRONTEND_URL) must share ONE hostname so the DPP launch cookie is
    # sent on API calls — a 127.0.0.1/localhost split drops the cookie and hides
    # the Accept-to-DatsMe button. Mirrors start_petmaker_backend_only.sh.
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PETMAKER_BACKEND_PORT", 19954)))
