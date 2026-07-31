"""webui — Pet Maker backend (FastAPI, mirrors DatsMe's api conventions).

The React frontend (web/, Next.js on :19955) talks to this API (:19954).

The designer is three steps (SPEC_PET_DESIGNER_FLOW), and every way of starting a
pet ends in the SAME artifact — a reference still. Nothing downstream of the fill
step asks where the picture came from:

  POST /api/reference                a curated breed | an animal name | a photo
                                     → ONE reference record
  POST /api/preview                  reference + design → a NEW reference (§6.1)
  POST /api/generate                 {reference_id, name, poses, motion_profile}
                                     → job_id. Four fields: everything else was
                                     resolved at FILL time and rides the record.
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
import logging
import os
import shutil
import threading
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple, Optional

from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response

import db
import house_capacity
import pet_ownership
import pool_client
# design_calibration owns the design redraw's denoise band (effective_strength) and the
# calibration-staleness predicate. Safe at module top DESPITE the cycle: it imports `app`
# lazily, inside its functions, precisely so this direction works (its §2 import
# discipline). Pure-CPU — it reads design_axes, never pet_factory.factory.
import design_calibration
# ai_engine is web-tier + one HTTPS call, and imports anthropic LAZILY (inside its
# one call), so importing it here costs nothing and stays GPU-less-safe. It powers
# the upload captioner (SPEC_UPLOAD_LIKENESS §2.5); inert until DATSPET_AI_API_KEY.
import ai_engine
# motion_resolver bridges the two: AI body-type classification (fast/Haiku) with a
# keyword fallback, so the registry needs no exhaustive keyword list (§3.5). Inert-safe
# — with no API key it degrades to keyword resolution, like everything AI here.
import motion_resolver
# motion_profiles is pure data (no ML deps) — safe to import on the GPU-less web
# tier; it powers /api/motions and the pose menu (SPEC_MOTION_PROFILES §5.1).
from pet_factory import motion_profiles as motion_profiles_mod
# animal_catalog is likewise pure data (base-animal tree + curated base PNGs) — it
# powers step 1's gallery: the curated bases the user picks from, served as images
# (SPEC_PET_DESIGNER_FLOW §3.3). The landing tiles and themed-page breed pickers it
# used to feed are gone with the themed pages (§11).
from pet_factory import animal_catalog as animal_catalog_mod
# tiers is the entitlement table (pose caps + extra-pose price), also pure data —
# the pose selector caps + the resolved pricing hint come from it, and the server
# enforces the resolved cap on generate (SPEC_PET_DESIGNER_PLATFORM §5).
from pet_factory import tiers as tiers_mod
# design_axes is the step-2 design vocabulary registry (body/pattern/expression +
# the surface axes) — pure data, like the three above. It generalizes the old
# body_shapes subpackage (SPEC_PET_DESIGN_AXES §1, Phase 0). Fragments feed
# compose_design, never the archetype prompt: an axis pick is a DESIGN modifier,
# so picking one can never invalidate a curated base (SPEC_PET_DESIGNER_FLOW §0.1).
from pet_factory import design_axes as design_axes_mod

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

# ── Logging (SPEC_GPU_MEMORY_HYGIENE §5, §11.2) ────────────────────────────────────────
# Nothing here configured logging before, so the root logger had NO handler and Python's
# `logging.lastResort` applied: WARNING and above reached stderr, INFO was silently DROPPED.
# That voided every INFO-level report the factory makes — most importantly the verified-
# eviction line, whose whole job is to record what happened on a SUCCESSFUL build. A
# detector that only logs its failures cannot distinguish "it worked" from "it never ran",
# which is the exact false-green class of bug that spec exists to remove. Measured before
# this landed: the eviction's success line printed nothing at all.
#
# Safe against uvicorn: uvicorn's dictConfig defines only `uvicorn*` loggers (which do not
# propagate) and never touches root, so this neither fights it nor double-prints. And
# basicConfig is a documented no-op when the root logger already has handlers, so a host
# that embeds this app keeps its own configuration.
# Stdlib only — no ML import, so the GPU-less posture above is unaffected.
BACKEND_LOG_LEVEL = os.environ.get("DATSPET_LOG_LEVEL", "INFO").strip().upper()
logging.basicConfig(
    # A typo in the env var must not stop the backend booting — fall back, don't raise.
    level=getattr(logging, BACKEND_LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)

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

# Caller identity — the ONE door (SPEC_DATSPET_FEDERATED_SESSION §4.5). The
# middleware mints this browser's anonymous owner id on the first request that
# could need one; every handler reads its owner through owner_scope, never by
# parsing a cookie itself. Registered AFTER the DPP router so the exclusion set
# (/partner/*, /api/datsme/bundle/*) covers routes that already exist.
import owner_scope
app.middleware("http")(owner_scope.anon_owner_middleware)

# Motion-profile admin API (SPEC_MOTION_PROFILE_ADMIN §4). Every endpoint is gated
# by the adm-claim cookie; inert until an admin-launch sets it.
import motion_admin
app.include_router(motion_admin.router)

# Design admin (SPEC_PET_DESIGN_AXES_ADMIN): the same three-layer pattern as the
# motion admin, pointed at the design vocabulary + the catalog's design profiles.
import design_admin
app.include_router(design_admin.router)

# AI engine admin (SPEC_DATSPET_AI_ENGINE §6): the third admin router — the model
# catalog (read-only), the editable purpose registry, usage, and Test configuration.
# Pure web-tier + one HTTPS call; inert until DATSPET_AI_API_KEY is set (§4).
import ai_admin
app.include_router(ai_admin.router)

# Settings admin (SPEC_UPLOAD_LIKENESS §2.2, decision 6a): the fourth admin router — a
# small typed switchboard of runtime feature flags. The first is `upload_isolate` (Phase 3
# subject isolation, default OFF). DB-backed and runtime-writable, unlike the content admins.
import settings_admin
app.include_router(settings_admin.router)

# The Pet Store (SPEC_PET_STORE §3): the public shop router + the sixth admin
# surface. DB-backed inventory, so prod is stockable at runtime — which the
# file-based samples it replaced could never be (§8; prod content dirs are a
# read-only install).
import pet_store
app.include_router(pet_store.router)
import store_admin
app.include_router(store_admin.router)

# Donations (SPEC_PET_STORE §10) — the donate door and the donor's own record.
# Not admin-gated: this is a user surface, scoped by owner like the house.
import donations  # noqa: E402
app.include_router(donations.router)

# The Motion Lab (SPEC_MOTION_LAB): the fifth admin surface — a visual workbench for
# authoring pose_prompt clauses (§3.9.1) by running the generation STEPS. LOCAL backend
# only: it drives ComfyUI through pet_factory, so its router is mounted only here, never
# on the GPU-less prod tier (§5). Save is the existing motion_admin PUT.
if PET_GEN_BACKEND == "local":
    import motion_lab
    app.include_router(motion_lab.router)

MAX_UPLOAD_BYTES = 12 * 1024 * 1024
ALLOWED_IMAGE_MIMES = ("image/png", "image/jpeg", "image/webp", "image/gif")

# Shown when an upload arrives with no typed noun AND the captioner could not name it
# (engine off, or triage rejected the photo). The door asks instead of guessing — see the
# comment at the raise site for what guessing cost. Worded as an instruction, because the
# user can fix it in one action: the noun field is already on the form.
UNNAMED_UPLOAD_MESSAGE = (
    "We couldn't tell what this picture is. Type what it is — a dog, a red panda, "
    "a person — and upload it again."
)

# How hard to redraw an uploaded photo into a sprite (SPEC_PET_DESIGNER_FLOW §3.5).
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
    # NO `dir`. It carried a per-job scratch dir for the upload/remix-base files the
    # legacy contract wrote there. The reference layer resolves all of that at FILL
    # time (§7.3), so nothing has written a job scratch file since — the field was set
    # twice and read nowhere, and /api/generate was mkdir'ing an empty directory on
    # every single build for a 24 h sweep to find.
    status: str = "queued"          # queued | running | done | error | canceled
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
    pool_job_id: Optional[str] = None            # §11: the underlying pool job (set at submit) — for Stop
    last_client_poll_at: Optional[float] = None  # §C: last GET /api/job = the device-liveness beat

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "status": self.status,
            "progress": self.progress, "message": self.message,
            "breed_id": self.breed_id, "error": self.error,
            "created_at": self.created_at, "finished_at": self.finished_at,
        }


JOBS: dict[str, Job] = {}
JOBS_LOCK = threading.Lock()
_CLIENT_IDLE_TTL_S = 20.0   # §C: no /api/job poll for this long → user gone → stop renewing the lease


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


# The design-input widths. These are part of the COMPOSITION contract, not request
# hygiene (SPEC_MOTION_LAB_DESIGN_PARITY I2): two surfaces that cap differently compose
# DIFFERENT strings from the same picks, and the drift is invisible to any test that
# calls compose_design directly. Every surface that composes a design goes through
# normalize_design_inputs below — there is no second copy of these numbers.
MAX_SPECIES_CHARS = 60
MAX_COLOR_CHARS = 20
MAX_ACCESSORY_CHARS = 30
MAX_DESIGN_ACCESSORIES = 3
MAX_AXIS_TOKEN_CHARS = 30      # an axis key or an option key
MAX_EXTRA_CHARS = 120          # the free-text escape hatch (§4.3)


class DesignInputs(NamedTuple):
    """What compose_design is allowed to see, after the caps."""
    species: str
    color: str
    accessories: list[str]
    picks: dict[str, str]
    extra: str


def normalize_design_inputs(species: str, color: str, accessories: list[str],
                            axis_picks: Optional[dict] = None,
                            extra: str = "") -> DesignInputs:
    """Cap and lower-case step 2's raw inputs — the ONE gate every design passes
    through before it becomes a prompt (I2).

    TRANSPORT stays with the caller: /api/preview splits a comma-separated form
    field and json.loads a picks string, the Motion Lab receives a real list and a
    real object (§3.2). What must NOT differ is what survives the caps, so that is
    here and only here.

    Surface filtering is deliberately NOT done here: it needs the resolved surface,
    which each caller reads from its own place (the reference record vs the typed
    keyword map), and folding it in would make this function need one."""
    return DesignInputs(
        species=species.strip().lower()[:MAX_SPECIES_CHARS],
        color=color.strip().lower()[:MAX_COLOR_CHARS],
        accessories=[a.strip().lower()[:MAX_ACCESSORY_CHARS]
                     for a in accessories if a.strip()][:MAX_DESIGN_ACCESSORIES],
        picks={str(k).strip().lower()[:MAX_AXIS_TOKEN_CHARS]:
               str(v).strip().lower()[:MAX_AXIS_TOKEN_CHARS]
               for k, v in (axis_picks or {}).items() if isinstance(v, str)},
        extra=extra.strip()[:MAX_EXTRA_CHARS],
    )


def compose_design(species: str, color: str, accessories: list[str],
                   axis_picks: Optional[dict] = None,
                   extra: str = "") -> tuple[str, str, Optional[float]]:
    """Turn step 2's structured picks into (prompt_description, display_name,
    min_strength) — the ONE place a design becomes a prompt
    (SPEC_PET_DESIGNER_FLOW §4; slot-ordered per SPEC_PET_DESIGN_AXES §2).

    Every "what should it look like" input arrives here and nowhere else. Axis
    picks ({axis_key: option_key}, e.g. {"body": "fat", "pattern": "spotted"})
    compose into the DESIGN string, never into the archetype prompt (§0.1):
    step 1 draws "a corgi", step 2 makes it chubby. That placement is what lets
    a curated base.png survive any design choice (§3.3).

    Prompt wording follows the remix calibration: 'recolored entirely {color}' is
    what actually flips a color against the source image. min_strength is 0.9 when
    the redraw has to fight the source — a conflicting color word in the species
    name (see _COLOR_WORDS), or an axis that declares it (body's silhouette rule,
    now data on body.json). The display name stays short — color + species, not
    the accessory list, the picks, or the free text.
    """
    # Clause order matters (calibrated on stills): prefix-axis fragments lead
    # (they attach to the noun phrase; ascending clause_slot, lowest nearest the
    # noun), accessories directly after the species, suffix-axis fragments and
    # free text after those, and the recolor emphasis LAST. With the recolor
    # clause in the middle, the accessory gets dropped; with accessories last,
    # the color loses. This ordering keeps both.
    #
    # NOT YET CALIBRATED (SPEC_PET_DESIGN_AXES §8 Phase 3): the axis slots and
    # free-text positions are reasoned, not measured. The color and accessory
    # positions above were settled by running them; the rest deserve the same
    # GPU session before the axis controls go user-visible.
    min_strength = None
    description = f"vivid {color} {species}" if color else species

    prefixes: list[tuple[tuple[int, str], str]] = []
    suffixes: list[tuple[tuple[int, str], str]] = []
    for axis_key, option_key in (axis_picks or {}).items():
        fragment = design_axes_mod.prompt_fragment(axis_key, option_key)
        if not fragment:
            continue  # a default, an unknown axis, or a typo'd option: no words
        comp = design_axes_mod.axis_composition(axis_key)
        slot = (comp["clause_slot"], axis_key)  # axis_key breaks slot ties
        target = prefixes if comp["position"] == "prefix" else suffixes
        target.append((slot, fragment))
        if comp["min_strength"] is not None:
            # An axis that declares min_strength fights the source image exactly
            # like a conflicting color does (§4.4 reason 3) — the body silhouette
            # rule, moved from code here to data on the axis file.
            min_strength = max(min_strength or 0.0, comp["min_strength"])

    # Ascending clause_slot, prepended in order — so the LOWEST slot lands
    # immediately before the "vivid {color} {species}" noun phrase
    # (SPEC_PET_DESIGN_AXES §2: lower = nearer the species noun).
    for _, fragment in sorted(prefixes):
        description = f"{fragment} {description}"

    # Suffix-position axes append right after the species phrase (§2), before
    # accessories and free text, keeping the recolor clause the calibrated tail.
    for _, fragment in sorted(suffixes):
        description += f", {fragment}"

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
                       motion_profile: Optional[str] = None,
                       pose_anchor: bool = True) -> tuple[str, bytes]:
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
    # v4 (§3.9.1) — uploads opt OUT of the pose_prompt anchor. Sent ONLY when False, so
    # the common case (True) adds no param and an older fleet handler is untouched; only
    # uploads need the pose_anchor-aware handler (deploy the handler before this web tier).
    if not pose_anchor:
        params["pose_anchor"] = False

    # Persist the linkage BEFORE driving (Opt-1, §A.6): if this process dies
    # mid-generation, startup reattaches to the still-running pool job instead
    # of orphaning it. The row is deleted at either terminal state.
    pool_job_id = pool_client.submit("pet_factory", params, labels=job.pool_labels or None)
    with JOBS_LOCK:
        job.pool_job_id = pool_job_id            # §11: enable Stop for this build
        job.last_client_poll_at = time.time()    # §C: assume the user is present at submit
    db.record_pool_job(
        job_id=job.id, pool_job_id=pool_job_id, description=description,
        display_name=display_name, created_at=job.created_at,
        external_user_id=job.external_user_id)

    def on_tick():
        # §C decision D-1: renew the pool consumer lease while the user's device is still polling
        # /api/job; when they go quiet, STOP renewing → the pool lease lapses → consumer_abandoned.
        with JOBS_LOCK:
            last = job.last_client_poll_at or job.created_at
        if time.time() - last < _CLIENT_IDLE_TTL_S:
            try:
                pool_client.keepalive(pool_job_id)
            except pool_client.PoolError:
                pass

    zip_bytes = pool_client.drive_to_result(
        pool_job_id, on_progress=on_progress, on_tick=on_tick,
        poll_interval=4.0, timeout_s=900.0)
    # The bundle carries the breed_id in its manifest; the finalize reads it
    # back, so return "" and let the unpack fill it in.
    return "", zip_bytes


def run_pet_job(job: Job, *, description: str, reference_image: Optional[Path],
                remix_strength: Optional[float] = None,
                display_name: Optional[str] = None,
                poses: Optional[dict] = None,
                motion_profile: Optional[str] = None,
                pose_anchor: bool = True) -> None:
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
                poses=poses, motion_profile=motion_profile, pose_anchor=pose_anchor)
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
                    poses=poses, motion_profile=motion_profile, pose_anchor=pose_anchor)

        _finalize_pet_from_zip(job, description=description, breed_id=breed_id,
                               zip_bytes=zip_bytes)
    except pool_client.PoolCanceled:
        with JOBS_LOCK:
            job.status = "canceled"
            job.message = "Stopped."
            job.finished_at = time.time()
        db.delete_pool_job(job.id)   # web-terminal → drop the reattach row
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
    fresh-generation finalize and pool-job reattach (the store adopt builds its
    row from store_pets columns instead)."""
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

    # SPEC_PET_OWNER_FIELD §2.4 — stamp BEFORE insert_pet, which DERIVES
    # bundle_sha256/size_bytes from whatever bytes it is handed, so the digest
    # covers the stamped bytes by construction and nothing ever restamps a stored
    # row. A fresh pet is `factory`: it has to be somebody's before it is sold,
    # and it cannot be `individual` because "datspet" is not a DatsMe user — the
    # host would attempt that lookup for every pet in the pull channel (§1.1).
    # DatsPet writes ONLY this unsold state; the owner is stamped by the HOST at
    # the two places a transfer happens, checkout and gift (§2.5).
    zip_bytes, _ = pet_ownership.stamp_bundle_fingerprint(zip_bytes)
    zip_bytes, manifest_json = pet_ownership.transfer_pet_ownership(
        zip_bytes,
        category=pet_ownership.FACTORY_CATEGORY,
        name=pet_ownership.FACTORY_OWNER_NAME,
        at=pet_ownership.epoch_to_utc_iso(job.created_at))

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
        # The AI's guess at the subject (animal or person) for an upload
        # (SPEC_UPLOAD_LIKENESS §2.5), or None. The upload door prefills its noun
        # field with this — the human's typed word still wins, so it is only used
        # when that field was empty.
        "suggested_subject": meta.get("suggested_subject"),
    }


def _save_reference(png: bytes, *, owner: Optional[str], description: str,
                    display_name: str, motion_profile: Optional[str], source: str,
                    min_strength: Optional[float] = None,
                    generated: bool = False,
                    surface: Optional[str] = None,
                    suggested_subject: Optional[str] = None,
                    catalog_animal: Optional[str] = None,
                    catalog_breed: Optional[str] = None) -> dict:
    """Mint one reference. EVERY door ends here, which is the whole design: past
    this point nothing downstream asks where the picture came from (§6).

    `surface` is the animal's resolved surface (fur/feathers/scales/None),
    resolved ONCE at fill time exactly like motion_profile and carried on the
    record (SPEC_PET_DESIGN_AXES §3) — /api/design-axes reads it to gate the
    surface axis; step 2 never re-derives it. `catalog_animal`/`catalog_breed`
    are the curated identity (catalog door only), carried so the design menu
    can honor per-breed profile restrictions (SPEC_PET_DESIGN_AXES_ADMIN §3.2)
    without re-deriving where the picture came from."""
    reference_id = uuid.uuid4().hex[:12]
    png_path, meta_path = _reference_paths(reference_id)
    meta = {
        "id": reference_id, "owner": owner, "created_at": time.time(),
        "description": description, "display_name": display_name,
        "motion_profile": motion_profile, "source": source,
        "min_strength": min_strength, "generated": generated,
        "surface": surface, "suggested_subject": suggested_subject,
        "catalog_animal": catalog_animal, "catalog_breed": catalog_breed,
    }
    png_path.write_bytes(png)
    meta_path.write_text(json.dumps(meta))
    return meta


def _reference_visible(meta: dict, owner: Optional[str]) -> bool:
    """Mirrors _can_access: a reference is visible iff it is the caller's own.

    EXACT match, like db._scope_clause (SPEC_DATSPET_FEDERATED_SESSION §4.5 b). The
    old rule also admitted `ref_owner is None`, which on an integrated box handed
    every signed-in user every anonymous visitor's reference — including uploaded
    photos of real people. A standalone box still matches, because there both sides
    are None.
    """
    return meta.get("owner") == owner


def _claim_references(from_owner: str, to_owner: str, activity_id: Optional[str]) -> int:
    """Move one anonymous owner's references onto a real user (§4.5 c).

    Without this, signing in mid-design orphans the reference the designer is
    holding: step 2 and the Generate button both resolve it through
    _load_reference, which would start 404ing the moment the owner changed. That is
    the front door's headline flow — design first, sign in to adopt.

    A directory scan, which is affordable because it runs ONCE per sign-in and
    PREVIEW_DIR is already bounded by the 24 h transient sweep. Do not build an
    index for it until the scan is measured to matter.
    """
    moved = 0
    for meta_path in PREVIEW_DIR.glob("*.json"):
        try:
            meta = json.loads(meta_path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if meta.get("owner") != from_owner:
            continue
        meta["owner"] = to_owner
        try:
            meta_path.write_text(json.dumps(meta))
            moved += 1
        except OSError:
            continue
    return moved


owner_scope.register_claim_handler("references", _claim_references)


def _claim_pets_and_jobs(from_owner: str, to_owner: str,
                         activity_id: Optional[str]) -> int:
    """Move the DB-backed stores, plus the in-memory Job objects that shadow the
    jobs table. JOBS is the live status object a running build mutates; the row is
    what a restart reattaches from. Both are read after a build finishes — the
    finished pet is stamped from Job.external_user_id — so signing in mid-build
    has to move both or the pet lands somewhere its own owner cannot see."""
    moved = db.claim_anon_pets(from_owner, to_owner, activity_id)
    moved += db.claim_anon_jobs(from_owner, to_owner)
    for job in JOBS.values():
        if job.external_user_id == from_owner:
            job.external_user_id = to_owner
    return moved


owner_scope.register_claim_handler("pets_and_jobs", _claim_pets_and_jobs)


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


def _base_pose_for(motion_profile_key: Optional[str], animal: str = "") -> str:
    """The base still's posture for a resolved motion profile (SPEC_BUNDLE_MOTION_CONTRACT
    §3.1) — e.g. aquatic → "swimming, body horizontal". Pure data (motion_profiles), safe
    on the GPU-less tier. Prefers the pinned key (skew-safe), else keyword-resolves `animal`,
    else "standing". Threaded into _render_still so the design-page still matches the build."""
    if motion_profile_key:
        return motion_profiles_mod.load_motion_profile(motion_profile_key, fallback_animal=animal).base_pose
    if animal:
        return motion_profiles_mod.resolve_motion_profile(animal).base_pose
    return "standing"


def _render_still(description: str, request: Request, owner: Optional[str],
                  reference_path: Optional[Path] = None,
                  strength: Optional[float] = None,
                  isolate: bool = False,
                  base_pose: str = "standing") -> bytes:
    """Render one still — the ~10 s GPU step, and the ONE place that knows how to
    reach a renderer.

    Mirrors render_design_still's own two shapes (§7.1) so pool and local stay one
    decision rather than two:

        reference_path=None → txt2img an archetype  (step 1's long-tail door)
        reference_path set  → img2img redraw        (step 1's upload door, step 2's preview)

    isolate (SPEC_UPLOAD_LIKENESS §2.2): cut the subject out before the redraw.
    The upload door sets it from the runtime `upload_isolate` flag (default OFF); step 2's
    preview leaves it False (its reference is already a clean sprite). BOTH backends honour
    it: the local path passes `isolate=` to render_design_still; the pool path forwards
    `params["isolate_subject"]` — but ONLY when `isolate` is on, so a default-OFF deploy
    never sends the v3 param to a v2 node (the switch is the fleet gate — Phase 3).

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
        # NOTE (base_pose parity): the pool preview handler (pet_preview) does not yet
        # accept a base_pose param, so a POOL preview still draws the profile's default
        # posture. The local path below honours base_pose. Reaching prod parity needs a
        # pet_preview handler that takes base_pose + a fleet roll (like the pose_anchor v4
        # change) — real BUILDS already honour it via make_pet_zip. Do NOT send an unknown
        # param here: the pool validates strictly and would 422 on a handler without it.
        if reference_path is not None:
            # The v1 shape. Omitting these two IS the v2 shape — it hard-fails 422
            # on a v1 node, which is why both nodes must be v2 first (§10.1).
            params["reference_image_b64"] = _encode_reference_image(reference_path)
            params["strength"] = strength
        if isolate:
            # Phase 3 (SPEC_UPLOAD_LIKENESS §2.2): the v3 param, sent ONLY when the
            # `upload_isolate` switch is on. Default OFF means a default-OFF deploy never
            # sends it — so a v2 node never 422s, and the switch IS the fleet gate. Roll
            # pet_preview to v3 on every node before flipping the switch in prod.
            params["isolate_subject"] = True
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
            return render_design_still(description, base_pose=base_pose)
        return render_design_still(description, str(reference_path), strength,
                                   isolate=isolate, base_pose=base_pose)
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


def _resolve_typed_surface(animal: str) -> Optional[str]:
    """The §3.2 keyword tier for a TYPED animal name, with the miss log the spec
    requires: a name that resolves to no surface is the keyword map's growth
    list — each logged miss is a one-line edit to surface_keywords.json. Null is
    the honest answer, never a guess (§3.3): the design step then shows only the
    universal axes, and free text covers 'with fluffy fur' by hand."""
    surface = design_axes_mod.resolve_surface(animal)
    if surface is None and animal.strip():
        print(f"[webui] surface unresolved for typed animal {animal!r} — "
              f"universal axes only (surface_keywords.json is the growth list)",
              flush=True)
    return surface


def _caption_upload(body: bytes, media_type: str, typed_noun: str,
                    owner: Optional[str]) -> Optional[dict]:
    """The upload captioner (SPEC_UPLOAD_LIKENESS §2.5 / Phase 2.1, lever E): read
    an uploaded photo with the AI so the noun no longer has to be typed. image_triage
    gates first ('is this a usable subject — an animal or a person?'), then pet_likeness
    names it and describes it. Returns {subject, description, features} or None.

    The subject may be an ANIMAL or a PERSON: users animate pets, themselves, and other
    people, so this is deliberately not animal-only.

    None means DEGRADE to the manual field (Phase 1): the engine is inert (no key), the
    photo is not a usable subject, or any call failed. This is best-effort by design —
    it NEVER raises, so a captioner hiccup can never break the upload door, and the
    human's typed noun is always the fallback. The engine (SPEC_DATSPET_AI_ENGINE)
    names none of this; the two purpose keys are this call site's arguments (§11).
    """
    if not ai_engine.is_available():
        return None
    try:
        triage, _ = ai_engine.call_purpose(
            "image_triage", image=body, media_type=media_type, external_user_id=owner)
        if not (triage.get("is_subject") and triage.get("usable")):
            return None
        hint = (f" The uploader says it is a {typed_noun.strip()}."
                if typed_noun.strip() else "")
        like, _ = ai_engine.call_purpose(
            "pet_likeness", image=body, media_type=media_type,
            variables={"hint_clause": hint}, external_user_id=owner)
        subject = (like.get("subject") or "").strip()
        if not subject:
            return None
        return {"subject": subject, "description": like.get("description") or "",
                "features": like.get("features")}
    except (ai_engine.AIUnavailable, ai_engine.AIError):
        return None
    except Exception as e:  # defensive — the upload door must survive any AI failure
        print(f"[webui] upload captioner failed: {e}", flush=True)
        return None


@app.post("/api/reference")
def create_reference(
    request: Request,
    catalog_animal: str = Form(""),
    catalog_breed: str = Form(""),
    animal: str = Form(""),
    image: Optional[UploadFile] = File(None),
    strength: float = Form(UPLOAD_REDRAW_STRENGTH),
    # The upload door's "AI enabled" toggle (SPEC_UPLOAD_LIKENESS §2.5): when on
    # (default) an empty noun is captioned by the AI; when the user turns it OFF to
    # type the noun themselves, this is false so an empty field draws "pet" rather
    # than silently captioning anyway. Defaults True → the API stays backward-compatible.
    ai_caption: bool = Form(True),
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
    owner = owner_scope.require_owner(request)
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
            # Confident by construction (SPEC_PET_DESIGN_AXES §3.1): the breed's
            # authored surface tag, resolved like motion_profile is.
            surface=animal_catalog_mod.resolved_surface(catalog_animal, catalog_breed),
            catalog_animal=catalog_animal, catalog_breed=catalog_breed,
            source="catalog", generated=False))

    if door == "txt2img":
        # The long tail — a cache MISS (§3.3). ~10 s and unvetted, and that is
        # honest: there was never a curated blue jay to lose. The motion profile is
        # AI-classified from the name here at fill time (motion_resolver: Haiku, with
        # a keyword fallback — SPEC_MOTION_PROFILES §3.5) and pinned on the record, so
        # "blue jay" lands on `avian` without an exhaustive keyword list.
        profile_key = motion_resolver.resolve_motion_key(animal)
        png = _render_still(animal, request, owner, base_pose=_base_pose_for(profile_key, animal))
        return _reference_record(_save_reference(
            png, owner=owner, description=animal.lower(),
            display_name=animal.title(),
            motion_profile=profile_key,
            source="txt2img", generated=True,
            surface=_resolve_typed_surface(animal)))

    # door == "upload": redraw it (§3.5). THIS is the change of behaviour — today
    # an uploaded photo reaches Wan I2V raw and animates unreliably, because a
    # photo is not the side-profile flat-shaded sprite make_pet_zip's docstring
    # requires. Redrawing at FILL time is what lets the user see the sprite before
    # paying for a 3-minute build.
    if image.content_type not in ALLOWED_IMAGE_MIMES:
        raise HTTPException(400, f"unsupported image type: {image.content_type}")
    body = image.file.read()          # sync — see the docstring
    if len(body) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Image exceeds 12 MB limit")

    # The captioner (SPEC_UPLOAD_LIKENESS §2.5, lever E). The human's typed word wins
    # (decision 3), so the AI only runs when the noun field is EMPTY — no reason to
    # spend two calls to name what the user already named. When the engine is inert or
    # the photo isn't a usable animal, `caption` is None → today's manual-field
    # behaviour ("pet"), unchanged.
    caption = (_caption_upload(body, image.content_type, "", owner)
               if (ai_caption and not animal) else None)
    suggested = None
    if caption and caption.get("subject"):
        suggested = caption["subject"].strip()[:60]

    # Nothing named it → ASK, never guess. The old fallback substituted the literal noun
    # "pet", which is not a neutral default but a species assertion: it drew a cartoon DOG
    # from a photograph of a person (2026-07-26), and because the profile was resolved from
    # a deliberately-blanked noun it also pinned motion_profile null, so the build would
    # have animated that person on all fours. A confident wrong subject is worse than a
    # question — the noun field the answer belongs in is already on the form.
    subject = animal or suggested
    if not subject:
        raise HTTPException(422, UNNAMED_UPLOAD_MESSAGE)
    # Resolve the motion profile ONCE from the subject noun — used both for the base pose
    # the redraw is drawn in (SPEC_BUNDLE_MOTION_CONTRACT §3.1) and pinned on the record
    # below. Unconditional now that `subject` is guaranteed: an upload can no longer reach
    # the build with motion_profile null and keyword-resolve from whatever the fallback was.
    upload_profile_key = motion_resolver.resolve_motion_key(subject)
    # Extend the redraw prompt with the AI's short visual cue, but ONLY when the AI
    # supplied the noun (the field was empty) — _remix_prompt repeats the description
    # to win over the source's colours, so a features hint reinforces the redraw.
    render_description = subject
    if suggested and caption and caption.get("features"):
        render_description = f"{subject}, {caption['features']}"

    # The user chooses how hard to redraw (§3.5): "faithful" keeps their photo's look
    # but preserves the photographic pose/lighting Wan I2V animates badly; "sprite"
    # animates reliably but looks redrawn. Only they know which side of that they
    # want, so the server takes the number and clamps it rather than deciding.
    redraw_strength = min(0.9, max(0.3, strength))
    tmp = PREVIEW_DIR / f"_upload_{uuid.uuid4().hex[:12]}"
    tmp.write_bytes(body)
    try:
        # isolate — the ONE call site that sets it (SPEC_UPLOAD_LIKENESS §2.2). A photo
        # is a dog-in-a-garden; cutting the subject out before the redraw makes the
        # img2img follow the animal, not the lawn. Gated by the runtime `upload_isolate`
        # flag (decision 6a, default OFF): the switch is the A/B harness, the fleet gate
        # (the pool param ships only when on), and the kill-switch. Step 2's preview never
        # reaches here — its reference is already a clean sprite.
        isolate = settings_admin.bool_setting("upload_isolate")
        png = _render_still(render_description, request, owner, reference_path=tmp,
                            strength=redraw_strength, isolate=isolate,
                            base_pose=_base_pose_for(upload_profile_key, subject))
    finally:
        tmp.unlink(missing_ok=True)
    # §3.4: a photo carries no reliable surface signal → universal axes only; but a
    # NAME (typed OR captioned) may promote via the keyword map — which is how an
    # upload recovers the coat/plumage axis it used to lose (app.py comment above).
    return _reference_record(_save_reference(
        png, owner=owner, description=subject.lower(),
        display_name=subject.title(),
        # Classify from the subject noun (typed or captioned) so an uploaded pet still
        # gets the right pose menu + body type (resolved once above; motion_resolver: AI,
        # keyword fallback). No noun at all → leave it to keyword-resolve at build.
        motion_profile=upload_profile_key,
        source="upload", generated=True, suggested_subject=suggested,
        surface=_resolve_typed_surface(subject)))


@app.get("/api/reference/{reference_id}.png")
def reference_image(reference_id: str, request: Request):
    """The still. Owner-scoped, unlike the /api/preview/{id} it replaces — a
    reference can be a user's uploaded photo, so it needs the rule rows get.

    resolve_owner_scope, NOT require_owner: a stale launch session must not 401 an
    <img> (SPEC_DATSPET_FEDERATED_SESSION §4.7). <img> has no 401 handler, so a
    broken image is the honest outcome here and the page's next JSON call is what
    raises the 401 that starts the renewal."""
    owner = owner_scope.resolve_owner_scope(request).owner_id
    try:
        ref = _load_reference(reference_id, owner)
    except HTTPException as e:
        # An image endpoint has one honest failure: it isn't there. Collapse the
        # 400-expired case to 404 so a broken <img> is the whole story.
        raise HTTPException(404, "reference not found") from e
    # ref["id"], NOT the raw param. _load_reference validates the STRIPPED id, so
    # "/api/reference/%20abc.png" passed validation and then rebuilt the path from the
    # padded string — a file that does not exist, and an unhandled 500 on the one
    # endpoint whose whole contract is "404, and nothing else". Reading the id back off
    # the record is what preview_design and start_job already do; this was the odd one.
    png_path, _ = _reference_paths(ref["id"])
    return FileResponse(png_path, media_type="image/png")


@app.get("/api/design-axes")
def design_axes_menu(request: Request, reference_id: str = "", animal: str = ""):
    """Step 2's design vocabulary (SPEC_PET_DESIGN_AXES §4). The SERVER reads the
    resolved surface and returns only the applicable axes — the universal ones
    plus the single matching surface axis (or none): a bird is offered feathers,
    never fur, and the browser renders what it is handed with no animal logic of
    its own. A new axis or surface appears here with no endpoint change.

    TWO ways to name the animal, never merged (SPEC_MOTION_LAB_DESIGN_PARITY §2.1):

        reference_id   the designer, which holds a reference by step 2. WINS when
                       both are given — one source of surface, not a blend.
        animal         free text, for a surface that has no reference to read:
                       the Motion Lab. Resolved through _resolve_typed_surface,
                       the same keyword path the typed door uses, so the Lab's
                       menu and a typed pet's menu cannot drift. A curated
                       animal's `resolved_surface_options` RESTRICTION is not
                       applied here — that is per-breed data, and a typed name
                       is not a curated breed.

    Neither (or one that doesn't resolve) degrades to the universal axes — the
    §3.3 unknown-animal posture, and the safe answer for a menu endpoint, which
    must not dead-end the design step over a swept reference or an animal the
    keyword map has never seen. `prompt_fragment` is calibrated server-side
    wording and never reaches the browser, same posture as the tier table."""
    surface = None
    restriction = None
    if not reference_id.strip() and animal.strip():
        surface = _resolve_typed_surface(animal.strip()[:MAX_SPECIES_CHARS])
    if reference_id.strip():
        owner = owner_scope.require_owner(request)
        try:
            ref = _load_reference(reference_id, owner)
        except HTTPException:
            ref = {}
        surface = ref.get("surface")
        # A curated animal may restrict its surface vocabulary (the admin's
        # Animals tab, SPEC_PET_DESIGN_AXES_ADMIN §3.2). The axis's own default
        # is always offered regardless.
        if ref.get("catalog_animal"):
            options = animal_catalog_mod.resolved_surface_options(
                ref["catalog_animal"], ref.get("catalog_breed"))
            restriction = set(options) if options is not None else None
    return {"axes": design_axes_mod.axes_for_surface(surface, restriction)}


@app.get("/api/body-shapes")
def body_shapes_menu():
    """DEPRECATED alias for one deprecation cycle (SPEC_PET_DESIGN_AXES §4):
    the body axis of /api/design-axes, in the old envelope. Same fragment-
    withholding posture; remove once no shipped frontend calls it."""
    body = design_axes_mod.public_axis("body") or {"options": [], "default": ""}
    return {"shapes": body["options"], "default": body["default"]}


@app.post("/api/preview")
def preview_design(
    request: Request,
    reference_id: str = Form(""),
    strength: float = Form(0.85),
    color: str = Form(""),
    accessories: str = Form(""),
    axis_picks: str = Form(""),
    body_shape: str = Form(""),
    extra: str = Form(""),
    name: str = Form(""),
):
    """Step 2's answer: see it (§5). Takes a reference, returns a REFERENCE — not a
    different kind of handle (§6.1):

        archetype ──(colour/shape/accessories/text/strength)──▶ your pet's look
        reference₁ ──────────────────────────────────────────▶ reference₂

    Two handle types would force this endpoint, the frontend, and start_job to
    branch on which kind they hold — exactly the source-agnosticism the reference
    layer buys. One store, one TTL, one URL shape, one record.

    Sync `def`, not `async def` (§5.3) — see _render_still.
    """
    owner = owner_scope.require_owner(request)
    if not reference_id.strip():
        raise HTTPException(400, "Pick a base animal first.")
    ref = _load_reference(reference_id, owner)

    # Axis picks arrive as ONE JSON object {axis_key: option_key}
    # (SPEC_PET_DESIGN_AXES §4) — a new axis adds no Form field. Malformed JSON
    # degrades to "no picks" (the body_shapes typo posture: a broken request
    # must not 500 a design); unknown axes and surface-mismatched picks are
    # dropped by filter_picks (defense in depth — the menu already hid them).
    raw_picks = {}
    if axis_picks.strip():
        try:
            parsed = json.loads(axis_picks)
        except ValueError:
            parsed = {}
        if isinstance(parsed, dict):
            raw_picks = parsed
    # `body_shape` stays a server-side alias for axis_picks["body"] for one
    # deprecation cycle, mirroring the /api/body-shapes alias (§4).
    if body_shape.strip() and "body" not in raw_picks:
        raw_picks["body"] = body_shape

    # Parsing the TRANSPORT is this endpoint's business (form fields, comma lists,
    # a JSON string); what survives the caps is the composition contract's, so it
    # goes through the shared normalizer the Motion Lab also calls (I2).
    # `.strip()` before the `or`: a whitespace-only name must fall back to the
    # reference's description, not normalize to an empty species.
    design = normalize_design_inputs(
        name.strip() or ref["description"], color,
        accessories.split(","), raw_picks, extra)
    picks = design_axes_mod.filter_picks(design.picks, ref.get("surface"))

    axis_touched = any(not design_axes_mod.is_default(a, k) for a, k in picks.items())
    if not (design.color or design.accessories or axis_touched or design.extra):
        # §4.1, widened to count a non-default pick on ANY axis. Designing
        # nothing is adopting, and the zero-GPU adopt path exists for that.
        raise HTTPException(400, "Pick a colour, an accessory, a body shape, or "
                                 "describe a change.")

    species = design.species
    description, display_name, min_strength = compose_design(
        species, design.color, design.accessories, picks, design.extra)
    # The clamp is design_calibration's, not a local copy (I4): the calibration
    # tool, the staleness check, this endpoint and the Motion Lab all read the same
    # band, so "the one knower" is a fact rather than an aspiration.
    strength = design_calibration.effective_strength(picks, design.color, species, strength)

    png_path, _ = _reference_paths(ref["id"])
    png = _render_still(description, request, owner,
                        reference_path=png_path, strength=strength,
                        base_pose=_base_pose_for(ref.get("motion_profile"), species))

    # The new record carries the SHORT species phrase ("purple corgi"), NOT the
    # ~240-char composed design string (§7.3). Generate is always as-is now, so
    # this steers only the motion prompts, the breed_id slug and the default
    # display name — and make_pet_zip truncates at [:60] anyway. The long prompt
    # did its job here, in the redraw.
    return _reference_record(_save_reference(
        png, owner=owner, description=display_name.lower(),
        display_name=display_name,
        # A design never changes the animal, so the profile — and the surface,
        # and the curated identity — ride along unchanged.
        motion_profile=ref.get("motion_profile"),
        surface=ref.get("surface"),
        catalog_animal=ref.get("catalog_animal"), catalog_breed=ref.get("catalog_breed"),
        source="design", min_strength=min_strength, generated=True))



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

    # Every pose the profile ENABLES is offerable — including triggered ones (play, jump).
    # A triggered pose the user picks ships in the bundle and DatsMe force-plays it on
    # interaction (its manifest runtime_role/loop say so); the auto state machine still
    # skips it. The rule is simply: configured for this motion ⇒ selectable.
    poses = [
        {"name": name, "required": name in mp.REQUIRED_POSES, "enabled": True}
        for name in prof.enabled_poses()
    ]
    return {
        "profile": prof.key,
        "level": prof.level,
        "movement_class": prof.movement_class,
        "poses": poses,
    }


@app.get("/api/catalog")
def catalog():
    """The base-animal tree (SPEC_PET_DESIGNER_PLATFORM §4.3): animals, each with
    its breeds and the pinned motion_profile key.
    Drives step 1's gallery — the curated bases, shown as images (§3.3).
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
        animals.append({
            "key": a["key"],
            "label": a.get("label", a["key"]),
            "tagline": a.get("tagline", ""),
            "motion_profile": a.get("motion_profile"),
            "breeds": breeds,
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


# The file-sample surface (/api/catalog/.../samples/...) that stood here was
# retired by SPEC_PET_STORE §8 — the DB-backed store (webui/pet_store.py) is
# the one premade-pet system.


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
    reference_id: str = Form(""),
    name: str = Form(""),
    poses: str = Form(""),
    motion_profile: str = Form(""),
):
    """Step 3: build the pet (§8).

    Four fields. That is the whole contract, and it is the point: `image`, `text`,
    `base_pet_id`, `catalog_animal`, `catalog_breed`, `strength`, `color`,
    `accessories` and `preview_id` are all GONE — resolved once at fill time and
    carried on the record (§7.3).
    """
    # Who is generating? DatsMe-launched user (verified) or None (standalone).
    # This scopes the generated pet and the draft purge, so one user's Generate never
    # touches another user's (or the local) pets.
    owner = owner_scope.require_owner(request)
    # Fail fast, before ~3 min of GPU: a full house can't accept the pet this
    # build would produce, so don't build it (SPEC house-scaling).
    house_capacity.enforce_house_not_full(owner)
    name = name.strip()[:60]
    if not reference_id.strip():
        # No base at all — a bad request, not a missing reference. This is also what a
        # caller using the DELETED legacy contract now gets (build step 7): the old
        # params are gone, so a catalog_animal/text-shaped request arrives with nothing
        # here and fails LOUDLY. Silently ignoring them would build the wrong pet.
        raise HTTPException(400, "Pick a base animal first.")

    # THE PAYOFF (§6, §7.3). Three per-origin chains used to live here — the motion
    # profile, the description, and the reference image + strength were each re-derived
    # from "which origin was this?" at BUILD time. The record already carries all of it,
    # resolved once at FILL time where the animal and breed were actually known. So the
    # chains are not relocated; they are gone.
    ref = _load_reference(reference_id, owner)          # 404 not-yours · 400 expired
    reference_image, _ = _reference_paths(ref["id"])
    description = ref.get("description") or "pet"
    display_name = name or ref.get("display_name") or description.title()

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
    motion_profile = motion_profile.strip()[:60] or ref.get("motion_profile") or None

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
    job = Job(id=job_id, name=display_name,
              external_user_id=owner,
              # Capture attribution NOW, in the request context — the generation
              # thread below can't see the request's User-Agent.
              pool_labels=datsme_integration.pool_labels(request, owner))
    with JOBS_LOCK:
        JOBS[job_id] = job

    threading.Thread(
        target=run_pet_job, args=(job,),
        # remix_strength is ALWAYS None — not "usually", not "on this path". The still
        # is one the user has already SEEN and locked (§4.7), so the build animates it
        # as-is; redrawing here would re-roll the look after they said yes to it. With
        # the legacy contract gone this is a fact rather than a branch, which is what
        # makes test_generate_is_always_as_is a real guard and not a coincidence.
        #
        # The engine keeps its remix and text branches for the CLI (§7.1): make_pet.sh
        # and examples/cli.py still need them. The web tier simply never uses them.
        # pose_anchor (§3.9.1): fire the fresh-anchor motion path for prompt-derived
        # pets (typed / designer / catalog — their description carries identity), but
        # NOT for photo uploads, whose stored description is a bare noun a fresh still
        # can't match to the specific photo (those await the `depth` kind).
        kwargs={"description": description, "reference_image": reference_image,
                "remix_strength": None, "display_name": display_name,
                "poses": poses_pkg, "motion_profile": motion_profile,
                "pose_anchor": ref.get("source") != "upload"},
        daemon=True,
    ).start()
    return {"job_id": job_id}


@app.get("/api/job/{job_id}")
def job_status(job_id: str):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            raise HTTPException(404, "job not found")
        job.last_client_poll_at = time.time()   # §C: this poll IS the device-liveness heartbeat
        return job.to_dict()


@app.post("/api/job/{job_id}/stop")
def stop_job(job_id: str, request: Request):
    """§11 user Stop — cancel a build the caller owns. Owner-scoped by DatsMe identity (D-3): a
    job with no owner (standalone) is stoppable by the standalone caller. Best-effort + idempotent;
    the drive loop also observes 'canceled' and exits cleanly (mapped to a canceled job)."""
    owner = owner_scope.require_owner(request)
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if job is None:
            raise HTTPException(404, "job not found")
        if job.external_user_id is not None and job.external_user_id != owner:
            raise HTTPException(403, "not your build")
        pool_job_id = job.pool_job_id
    if pool_job_id:
        try:
            pool_client.cancel(pool_job_id, reason="user_stopped")
        except pool_client.PoolError:
            pass
    with JOBS_LOCK:
        if job.status in ("queued", "running"):
            job.status = "canceled"
            job.message = "Stopping…"
    return {"ok": True, "status": "canceled"}


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


@app.get("/api/house")
def house_config(request: Request):
    """The caller's house shape: the cap, the display page size, and how many
    saved pets they currently hold (SPEC house-scaling). Drives the "N / max"
    readout, the client-side pager, and the disabled state when full. Config, not
    collection — the pets themselves come from /api/pets, which changes for a
    different reason (a new pet) than these knobs (an ops tuning)."""
    owner = owner_scope.require_owner(request)
    return {
        "max_pets": house_capacity.house_max_pets(),
        "page_size": house_capacity.house_page_size(),
        "count": db.count_saved_pets(external_user_id=owner),
    }


@app.get("/api/pets")
def list_pets(request: Request):
    """Every SAVED pet the caller may see, newest first. A DatsMe-launched
    user sees only their own pets; a standalone caller sees the local
    (external_user_id IS NULL) pets. Drafts are excluded (join via /keep)."""
    owner = owner_scope.require_owner(request)
    return db.list_saved_pets(external_user_id=owner)


@app.get("/api/pets/unsaved")
def list_unsaved_pets(request: Request):
    """Finished builds this caller never answered — the way back to one.

    The designer asks on mount, so a user who was navigated away mid-decision is
    offered their pet instead of an empty page. Signing out is the case that
    surfaced this (the sign-out chain lands on the landing page, which discards the
    `?job=` the designer was carrying), but the same window opens for a closed tab,
    a stray link, or a crash — so the answer is a route back to the PET, not a way
    to carry a job id through one particular navigation.

    Newest first; the designer offers the newest and ignores the rest. Deliberately
    NOT merged into /api/pets: the house is "pets I decided to keep", and an
    undecided build appearing there would make Adopt and the house cap mean
    something different. Different question, different endpoint.
    """
    owner = owner_scope.require_owner(request)
    return db.list_unsaved_pets(external_user_id=owner)


@app.post("/api/pets/claim")
def claim_pets(request: Request, body: dict = Body(...)):
    """Move this browser's still-anonymous work onto the launched caller — the
    hand-off's idempotent BACKSTOP (SPEC_DATSPET_FEDERATED_SESSION §4.5 c).

    The real claim happens at LAUNCH, the moment the browser gains a DatsMe
    identity, so the house and designer inherit it without asking. This endpoint
    exists for the narrow race the launch sweep cannot cover: a row written after
    the sweep by a build that was already running. It is therefore owner-keyed too,
    not a list of ids — the body's `pet_ids` is accepted and ignored for
    compatibility with the client's existing call shape.

    Why it must happen before the hand-off at all: /partner/export/{user_id} is
    exact-match on the DatsMe id, so a pet still under an anon owner is visible in
    the house yet invisible to the host — it would silently vanish from the
    checkout with no error.

    Standalone callers get 401: with no DatsMe identity there is nobody to claim
    TO, and the pets are already theirs to see.
    """
    owner = owner_scope.require_owner(request)
    if owner is None or owner_scope.is_anon_owner(owner):
        raise HTTPException(401, "Not launched from DatsMe — sign in to adopt.")
    anon_owner = request.cookies.get(owner_scope.ANON_COOKIE)
    activity_id = datsme_integration.resolve_launch_activity(request)
    moved = owner_scope.claim_anon_owner(anon_owner, owner, activity_id)
    return {"claimed": sum(moved.values()), "stores": moved}


@app.post("/api/pets/{pet_id}/keep")
def keep_pet(pet_id: str, request: Request):
    """The user's explicit 'save this pet' — clears the draft flag so the pet
    joins the house. Scoped: you can only keep a pet you may access."""
    if not pet_id.isalnum():
        raise HTTPException(404, "pet not found")
    owner = owner_scope.require_owner(request)
    # The true cap chokepoint: this is the moment a pet joins the house. Enforce
    # ONLY for a draft actually joining — re-keeping an already-saved pet is
    # idempotent and must not 409 a house that is legitimately at its cap. Access
    # is checked first (_require_pet 404s, no existence leak) so the cap 409 can
    # never reveal another user's pet (SPEC house-scaling).
    row = _require_pet(pet_id, owner)
    if row["draft"]:
        house_capacity.enforce_house_not_full(owner)
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


# A pet's sprite sheet and manifest are IMMUTABLE per pet id: the id is a uuid4
# minted once at generation and the bytes never change under it. So the browser
# may cache them hard — every house reload, page-flip, and PetStage re-mount then
# hits cache instead of re-fetching ~1 MB per pet. On mobile that is the whole
# difference between a house that reloads instantly and one that re-downloads
# megabytes over cellular, and it retires the 429 blanks caused by the house
# firing ~4 asset requests per pet at once (SPEC per house-scaling work).
# `private`, not `public`: access is ownership-scoped (_require_pet), so only the
# owning browser may cache — never a shared proxy that could serve another user.
_IMMUTABLE_ASSET_CACHE = "private, max-age=604800, immutable"  # 1 week


# Both pet-asset endpoints use resolve_owner_scope, NOT require_owner: they are
# fetched by <img> and by the canvas engine, which have no 401 handler, so a stale
# launch session must degrade to the same 404 _require_pet already gives an
# unknown pet (SPEC_DATSPET_FEDERATED_SESSION §4.7). The page's next JSON call is
# what raises the 401 that starts the renewal.
@app.get("/api/pets/{pet_id}/sheet.png")
def pet_sheet(pet_id: str, request: Request):
    row = _require_pet(pet_id, owner_scope.resolve_owner_scope(request).owner_id)
    return Response(content=row["sheet_png"], media_type="image/png",
                    headers={"Cache-Control": _IMMUTABLE_ASSET_CACHE})


@app.get("/api/pets/{pet_id}/manifest.json")
def pet_manifest(pet_id: str, request: Request):
    row = _require_pet(pet_id, owner_scope.resolve_owner_scope(request).owner_id)
    return Response(content=row["manifest_json"], media_type="application/json",
                    headers={"Cache-Control": _IMMUTABLE_ASSET_CACHE})


@app.delete("/api/pets/{pet_id}")
def delete_pet(pet_id: str, request: Request):
    """Remove a pet from the house permanently. 404 if it isn't a stored pet
    the caller may access."""
    if not pet_id.isalnum():
        raise HTTPException(404, "pet not found")
    owner = owner_scope.require_owner(request)
    if not db.delete_pet(pet_id, external_user_id=owner):
        raise HTTPException(404, "pet not found")
    with JOBS_LOCK:
        JOBS.pop(pet_id, None)
    return {"deleted": pet_id}


@app.get("/api/pets/{pet_id}/zip")
def pet_zip(pet_id: str, request: Request):
    row = _require_pet(pet_id, owner_scope.require_owner(request))
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
    # LEGACY DRAIN. Nothing writes job scratch dirs any more — the reference layer
    # resolves uploads and remix bases at fill time, so /api/generate stopped creating
    # these. This stays to clear what pre-refactor builds left on a deployed box; it is
    # a no-op on a fresh install and can go once the boxes have swept themselves.
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
    # The writeback retry drain used to live here too. It went with the push path
    # (SPEC_DATSPET_FEDERATED_SESSION §6.2): a pull has no queued delivery to
    # retry. The loop survives for the transient sweep, which is a different job
    # on a different cadence.
    last_sweep = 0.0
    while True:
        now = time.monotonic()
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
