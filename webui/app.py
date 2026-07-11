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
pet persists under datspet_output/<job_id>/ — pet.zip, sheet.png,
manifest.json, pet.json — so the pet house survives restarts (location
configurable via PETMAKER_OUTPUT_DIR). pet_id == job_id.

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

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

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
    ],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)

# Where generated pets live (one folder per pet). Defaults inside the repo;
# point PETMAKER_OUTPUT_DIR elsewhere (e.g. ~/datspet_output) to move the
# whole collection out of the repository — set it in pet_env.sh, move the
# existing folder, restart. The name stays meaningful outside the repo.
OUTPUT_DIR = Path(os.environ.get(
    "PETMAKER_OUTPUT_DIR", str(Path(__file__).parent / "datspet_output"))).expanduser()
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Design-page preview stills. Underscore prefix keeps it out of the pets
# listing (list_pets globs */pet.json; previews have none).
PREVIEW_DIR = OUTPUT_DIR / "_previews"
PREVIEW_DIR.mkdir(parents=True, exist_ok=True)

MAX_UPLOAD_BYTES = 12 * 1024 * 1024
ALLOWED_IMAGE_MIMES = ("image/png", "image/jpeg", "image/webp", "image/gif")

# The pipeline owns the whole GPU (ComfyUI + birefnet); run one job at a
# time. Queued jobs wait here and report "Waiting for the GPU…" meanwhile.
GPU_LOCK = threading.Lock()


@dataclass
class Job:
    id: str
    name: str
    dir: Path
    status: str = "queued"          # queued | running | done | error
    progress: float = 0.0           # 0..1
    message: str = "Waiting for the GPU…"
    breed_id: Optional[str] = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None

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
    manifest = json.loads(_pet_file(pet_id, "manifest.json").read_text())
    sheet = Image.open(_pet_file(pet_id, "sheet.png"))
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
    """Runs in a daemon thread. Mutates `job` as it goes; never raises."""
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

        (job.dir / "pet.zip").write_bytes(zip_bytes)
        # Unpack the sheet + manifest next to the zip so the engine can
        # render the pet without unzipping in the browser, and persist a
        # pet.json record so /api/pets survives restarts.
        display_name = description.title()
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
            for member in z.namelist():
                if member.endswith("_sprite.png"):
                    (job.dir / "sheet.png").write_bytes(z.read(member))
                elif member == "manifest.json":
                    (job.dir / "manifest.json").write_bytes(z.read(member))
                elif member == "package.json":
                    display_name = json.loads(z.read(member)).get("display_name", display_name)
        # Born as a DRAFT: the pet only joins the house when the user clicks
        # "Save" (POST /api/pets/{id}/keep). Unsaved drafts are purged when
        # the next generation starts and at backend startup.
        (job.dir / "pet.json").write_text(json.dumps({
            "id": job.id, "breed_id": breed_id,
            "display_name": display_name, "created_at": job.created_at,
            "draft": True,
        }))

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
    base_pet_id: str = Form(...),
    strength: float = Form(0.85),
    color: str = Form(""),
    accessories: str = Form(""),
    name: str = Form(""),
):
    """Run ONLY the redraw stage (~10 s) and return a preview id. The design
    page shows the image next to the original; /api/generate can then be
    given the preview_id to animate this exact still."""
    base_pet_id = base_pet_id.strip()
    color = color.strip().lower()[:20]
    accessory_list = [a.strip().lower()[:30] for a in accessories.split(",") if a.strip()][:3]
    if not color and not accessory_list:
        raise HTTPException(400, "Pick a color or at least one accessory to preview.")

    try:
        species = json.loads(_pet_file(base_pet_id, "pet.json").read_text())["display_name"].lower()
    except Exception:
        raise HTTPException(404, "base pet not found")
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
    name: str = Form(""),
    text: str = Form(""),
    image: Optional[UploadFile] = File(None),
    base_pet_id: str = Form(""),
    strength: float = Form(0.85),
    color: str = Form(""),
    accessories: str = Form(""),
    preview_id: str = Form(""),
):
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
        # is the base pet's own name unless the user overrode it.
        try:
            species = json.loads(_pet_file(base_pet_id, "pet.json").read_text())["display_name"].lower()
        except Exception:
            raise HTTPException(404, "base pet not found")
        species = name.lower() or species
        description, display_name, min_strength = compose_design(species, color, accessory_list)
        if min_strength:
            strength = max(strength, min_strength)
    else:
        # Free-text paths: explicit name > description > generic. This string
        # also steers the motion prompts, so a short species-ish phrase works
        # best.
        description = name or text or "pet"

    # Starting a new generation supersedes any unsaved draft from the last one.
    _purge_drafts()

    job_id = uuid.uuid4().hex[:12]
    job_dir = OUTPUT_DIR / job_id
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

    job = Job(id=job_id, name=display_name or description, dir=job_dir)
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


def _purge_drafts() -> None:
    """Remove every unsaved draft. Called at startup (leftovers from a
    previous session) and when a new generation starts (the user iterated
    without saving — the old draft is superseded)."""
    for record in OUTPUT_DIR.glob("*/pet.json"):
        try:
            if json.loads(record.read_text()).get("draft"):
                shutil.rmtree(record.parent)
                with JOBS_LOCK:
                    JOBS.pop(record.parent.name, None)
        except (json.JSONDecodeError, OSError):
            continue


_purge_drafts()  # startup cleanup


@app.get("/api/pets")
def list_pets():
    """Every SAVED pet, newest first. Drafts (generated but not yet saved by
    the user) are excluded — they only join the house via /keep. Records
    written before the draft flag existed have no key and count as saved."""
    pets = []
    for record in OUTPUT_DIR.glob("*/pet.json"):
        try:
            data = json.loads(record.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if not data.get("draft"):
            pets.append(data)
    pets.sort(key=lambda p: p.get("created_at", 0), reverse=True)
    return pets


@app.post("/api/pets/{pet_id}/keep")
def keep_pet(pet_id: str):
    """The user's explicit 'save this pet' — clears the draft flag so the
    pet joins the house and survives draft purges."""
    record_path = _pet_file(pet_id, "pet.json")
    record = json.loads(record_path.read_text())
    record["draft"] = False
    record_path.write_text(json.dumps(record))
    return record


def _pet_file(pet_id: str, filename: str) -> Path:
    # pet_id is always one of our uuid4 hex job ids — reject anything that
    # could traverse out of the output dir.
    if not pet_id.isalnum():
        raise HTTPException(404, "pet not found")
    path = OUTPUT_DIR / pet_id / filename
    if not path.exists():
        raise HTTPException(404, "pet not found")
    return path


@app.get("/api/pets/{pet_id}/sheet.png")
def pet_sheet(pet_id: str):
    return FileResponse(_pet_file(pet_id, "sheet.png"), media_type="image/png")


@app.get("/api/pets/{pet_id}/manifest.json")
def pet_manifest(pet_id: str):
    return FileResponse(_pet_file(pet_id, "manifest.json"), media_type="application/json")


@app.delete("/api/pets/{pet_id}")
def delete_pet(pet_id: str):
    """Remove a pet from the house permanently — its whole output dir
    (bundle, sheet, manifest, record) goes away. 404 if it isn't a
    completed pet (half-finished jobs have no pet.json)."""
    if not pet_id.isalnum():
        raise HTTPException(404, "pet not found")
    pet_dir = OUTPUT_DIR / pet_id
    if not (pet_dir / "pet.json").exists():
        raise HTTPException(404, "pet not found")
    shutil.rmtree(pet_dir)
    with JOBS_LOCK:
        JOBS.pop(pet_id, None)
    return {"deleted": pet_id}


@app.get("/api/pets/{pet_id}/zip")
def pet_zip(pet_id: str):
    path = _pet_file(pet_id, "pet.zip")
    breed = pet_id
    try:
        breed = json.loads(_pet_file(pet_id, "pet.json").read_text())["breed_id"]
    except Exception:
        pass
    return FileResponse(path, media_type="application/zip", filename=f"{breed}.zip")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PETMAKER_BACKEND_PORT", 19954)))
