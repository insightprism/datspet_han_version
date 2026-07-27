"""motion_lab — the admin visual workbench for authoring pose_prompt clauses.

SPEC_MOTION_LAB. A GPU-dev-box tool that runs `factory.py`'s generation STEPS on a
chosen animal + pose so an admin can tune a pose clause and watch it move, then save
the clause to the profile via the EXISTING motion_admin write path.

**Design parity** (SPEC_MOTION_LAB_DESIGN_PARITY). The Lab draws what a BUILD draws,
which is a stronger claim than "something similar": the base still is step 1's txt2img
archetype or step 2's img2img redraw through the designer's own `compose_design`, and
every pose anchor is txt2img from the SUBJECT in the remix sentence — the typed phrase
until a design replaces it with the display name a build's record would then carry. The
composed design string is spent on the base redraw and nowhere else, because that is
exactly how much of a build it accounts for (§0.3) — a more-designed Lab would be a
less faithful one.

**The pack stage** (SPEC_MATTE_REPAIR_ORDER §12, F4). `/animate` runs the Wan loop and
then runs the SHIPPED packer on it, the way make_pet_zip runs Phase B and then packs — so
the Lab no longer stops one stage short of the bundle, which is where the opaque-black
hole-fill defect lives. Both results are served: the raw loop and the packed sheet, plus
that pose's damage numbers from the same function the probe prints. This is the first Lab
operation that runs GPU work IN THIS PROCESS, hence the eviction + GPU_LOCK in
`_pack_the_loop`.

**Async jobs.** A still/loop takes ~15–50 s, longer than the dev proxy holds a
connection, so generation is a JOB: POST /still + /animate return a job_id, a thread
runs the pipeline, the page polls GET /job/{id} (elapsed timer), POST /cancel/{id}
stops it. GET /asset/… serves the result.

**Multi-GPU dispatch.** ComfyUI is one-GPU-per-instance and serial, so the Lab
dispatches each job to the least-busy healthy ENABLED endpoint. Endpoint 0 is the
primary ComfyUI (GPU 0); endpoint 1 is a second ComfyUI on GPU 1 (conventional
:19963 + <ComfyUI>/output_gpu1, overridable via PET_LAB_COMFY_URL_2 /
PET_LAB_COMFY_OUTPUT_DIR_2 — start it with start_comfyui_gpu1.sh). With both up, two
jobs run at once (~2× on a batch). GET/PUT /config toggles which endpoints are used
(default: all). The main make_pet_zip pipeline is untouched — it still uses GPU 0.

Local backend ONLY (it drives ComfyUI through pet_factory); mounted only when
PET_GEN_BACKEND=local. pet_factory is imported LAZILY inside the job thread.
"""
from __future__ import annotations

import io
import os
import shutil
import threading
import time
import uuid
import zipfile
from pathlib import Path
from typing import Optional

import requests
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

import ai_engine
import datsme_integration
import design_calibration
from pet_factory import design_axes as design_axes_mod
from pet_factory import motion_profiles as mp

router = APIRouter(
    prefix="/api/admin/motion-lab",
    dependencies=[Depends(datsme_integration.require_admin_launch)],
)

_DEFAULT_SEED = 42   # MUST equal pet_factory.factory._ANCHOR_SEED — the build draws pose
                     # anchors at that seed, so the Lab is a faithful preview only when it
                     # authors at the same one (pinned by test_motion_lab). Change both or neither.
_MAX_ANIMAL = 240
_MAX_CLAUSE = 240
_JOB_TTL = 15 * 60
_ASSET_TTL_S = 6 * 3600   # scratch stills/loops live under _lab this long, then get swept (§9)
# How long the pack stage waits for GPU_LOCK before giving up and reporting busy (§12.3).
# Longer than the design preview's 1.5 s — a pack is the tail of a job that already spent
# ~40 s of GPU, so it is worth waiting out a short collision rather than discarding the
# packed tile; short enough that a real 3-minute build does not hold the job thread open.
_PACK_LOCK_TIMEOUT_S = 20.0
_CLIENT_ID = uuid.uuid4().hex

_JOBS: dict[str, dict] = {}
_JOBS_LOCK = threading.Lock()

# Endpoints: index 0 = primary ComfyUI (GPU 0); index 1 = second ComfyUI (GPU 1).
_ENDPOINTS: Optional[list] = None
_ACTIVE: Optional[set] = None
_INFLIGHT: dict[int, int] = {}
_EP_LOCK = threading.Lock()


class _Canceled(Exception):
    pass


def _pf():
    from pet_factory import factory as pf
    return pf


def _build_endpoints() -> list:
    pf = _pf()
    out0 = Path(pf.COMFY_OUTPUT_DIR)
    eps = [{"url": pf.COMFY_URL.rstrip("/"), "out": out0, "label": "GPU 0"}]
    url2 = os.environ.get("PET_LAB_COMFY_URL_2", "").strip() or "http://127.0.0.1:19963"
    out2 = os.environ.get("PET_LAB_COMFY_OUTPUT_DIR_2", "").strip()
    eps.append({"url": url2.rstrip("/"),
                "out": Path(out2).expanduser() if out2 else out0.parent / "output_gpu1",
                "label": "GPU 1"})
    return eps


def _endpoints() -> list:
    global _ENDPOINTS, _ACTIVE
    with _EP_LOCK:
        if _ENDPOINTS is None:
            _ENDPOINTS = _build_endpoints()
            _ACTIVE = set(range(len(_ENDPOINTS)))
        return _ENDPOINTS


def _active_set() -> set:
    _endpoints()
    with _EP_LOCK:
        return set(_ACTIVE or set())


def _healthy(url: str) -> bool:
    try:
        return requests.get(f"{url}/queue", timeout=3).status_code == 200
    except Exception:
        return False


def _reserve_endpoint() -> int:
    """Pick the least-busy healthy ENABLED endpoint AND reserve it (bump its in-flight
    count) in one lock hold, so N jobs fired at once spread across GPUs instead of all
    racing onto endpoint 0. Health is probed outside the lock (it does network I/O)."""
    eps = _endpoints()
    healthy = [i for i in sorted(_active_set()) if _healthy(eps[i]["url"])]
    if not healthy:
        raise RuntimeError("no ComfyUI endpoint is reachable — is it running?")
    with _JOBS_LOCK:
        idx = min(healthy, key=lambda i: (_INFLIGHT.get(i, 0), i))
        _INFLIGHT[idx] = _INFLIGHT.get(idx, 0) + 1   # reserve here, not in _new_job
        return idx


def _lab_dir() -> Path:
    """The ONE asset store (under GPU 0's output dir), served by /asset and read by
    every ComfyUI as an animate input over the shared filesystem."""
    d = _endpoints()[0]["out"] / "_lab"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _prune_lab_assets() -> None:
    """Sweep scratch stills/loops older than _ASSET_TTL_S (SPEC_MOTION_LAB §9). The only
    durable output is the JSON clause a Save writes, so these files are pure scratch — the
    dir stays bounded per authoring session. Best-effort, never raises; called opportunistically
    on each new job alongside _prune_jobs."""
    try:
        cutoff = time.time() - _ASSET_TTL_S
        for f in _lab_dir().glob("*"):
            if f.is_file() and f.stat().st_mtime < cutoff:
                f.unlink(missing_ok=True)
    except Exception:
        pass


def _clean_seed(seed: Optional[int]) -> int:
    try:
        s = int(seed)
    except (TypeError, ValueError):
        return _DEFAULT_SEED
    return s if 1 <= s <= 2**31 else _DEFAULT_SEED


# ---------------------------------------------------------------------------
# Job store
# ---------------------------------------------------------------------------
def _new_job(ep_idx: int) -> str:
    _prune_jobs()
    _prune_lab_assets()
    jid = uuid.uuid4().hex[:16]
    with _JOBS_LOCK:
        # in-flight was already reserved by _reserve_endpoint (kept atomic there)
        _JOBS[jid] = {"state": "running", "phase": "pending", "asset_id": None, "url": None,
                      "ms": None, "error": None, "cancel": False, "t0": time.time(), "ep": ep_idx,
                      # F4's slots (§12.2). `pack_error` is deliberately NOT `error`: a pack
                      # that fails still leaves a job that produced a loop.
                      "packed_asset_id": None, "packed_url": None, "packed_manifest_url": None,
                      "packed_zip_url": None, "metrics": None, "pack_error": None}
    return jid


def _get_job(jid: str) -> dict:
    with _JOBS_LOCK:
        return dict(_JOBS.get(jid) or {})


def _update_job(jid: str, **kw) -> None:
    with _JOBS_LOCK:
        if jid in _JOBS:
            _JOBS[jid].update(kw)


def _prune_jobs() -> None:
    now = time.time()
    with _JOBS_LOCK:
        for jid in [j for j, v in _JOBS.items()
                    if v["state"] != "running" and now - v["t0"] > _JOB_TTL]:
            _JOBS.pop(jid, None)


def _phase_of(url: str, pid: str) -> str:
    try:
        q = requests.get(f"{url}/queue", timeout=5).json()
    except Exception:
        return "running"
    if any(len(it) > 1 and it[1] == pid for it in q.get("queue_running", [])):
        return "running"
    if any(len(it) > 1 and it[1] == pid for it in q.get("queue_pending", [])):
        return "pending"
    return "running"


def _submit_and_wait(ep: dict, wf: dict, jid: str, timeout: int = 300) -> str:
    """Submit to ONE endpoint's ComfyUI, poll its /history, honoring cancel + phase."""
    url = ep["url"]
    r = requests.post(f"{url}/prompt", json={"prompt": wf, "client_id": _CLIENT_ID}, timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f"ComfyUI rejected workflow: {r.text[:200]}")
    pid = r.json()["prompt_id"]
    t0 = time.time()
    while time.time() - t0 < timeout:
        if _get_job(jid).get("cancel"):
            try:
                requests.post(f"{url}/interrupt", timeout=10)
            except Exception:
                pass
            raise _Canceled()
        try:
            h = requests.get(f"{url}/history/{pid}", timeout=10).json()
        except Exception:
            h = {}
        for o in h.get(pid, {}).get("outputs", {}).values():
            picks = (o.get("gifs") or []) + (o.get("images") or [])
            if picks:
                return picks[0]["filename"]
        _update_job(jid, phase=_phase_of(url, pid))
        time.sleep(1.0)
    raise TimeoutError("generation timed out")


def _run_job(jid: str, wf: dict, ext: str, ep_idx: int, pack: Optional[dict] = None) -> None:
    """Run one ComfyUI job, then — for an animate with `pack` — run the shipped packer on
    the loop it produced (SPEC_MATTE_REPAIR_ORDER §12.2).

    THE LOOP IS PUBLISHED FIRST, before the pack is attempted. It cost ~40 s of GPU, and a
    pack failure, a busy GPU_LOCK or a CutoutFailed must never discard it — "which stage
    broke" is the answer this instrument exists to give, and you cannot give it from a job
    that threw away half its evidence. `state` stays "running" with `phase="packing"` until
    the pack settles, so a client polling for the terminal state gets BOTH results, while
    one watching `url` can render the raw tile the moment it lands."""
    ep = _endpoints()[ep_idx]
    try:
        t0 = time.time()
        fn = _submit_and_wait(ep, wf, jid)
        asset_id = uuid.uuid4().hex[:16]
        loop_path = _lab_dir() / f"{asset_id}.{ext}"
        shutil.copy(ep["out"] / fn, loop_path)                          # → the one shared store
        _update_job(jid, asset_id=asset_id,
                    url=f"/api/admin/motion-lab/asset/{asset_id}.{ext}",
                    ms=round((time.time() - t0) * 1000))
        if pack:
            _update_job(jid, phase="packing")
            _pack_the_loop(jid, loop_path, pack)
        _update_job(jid, state="done")
    except _Canceled:
        _update_job(jid, state="canceled")
    except Exception as e:
        _update_job(jid, state="error", error=str(e)[:200])
    finally:
        with _JOBS_LOCK:
            _INFLIGHT[ep_idx] = max(0, _INFLIGHT.get(ep_idx, 0) - 1)


def _pack_the_loop(jid: str, loop_path: Path, spec: dict) -> None:
    """The stage the Lab used to stop one short of (SPEC_MATTE_REPAIR_ORDER §12).

    Runs the SHIPPED `pack_datsme_bundle` on this pose's frames — never a copy. A Lab that
    re-implements the stage stops being evidence about the build; the Lab is a surface, not
    a second engine. A one-pose bundle is faithful, not an approximation: the packer's
    `prep()` is entirely per-frame (`_remove_bg` per frame, `_fit_square` from that frame's
    own size, `_fill_holes_alpha` flooding from that cell's own border), so a pose packed
    alone produces byte-identical cells to the same pose inside an eight-pose build.

    NEVER RAISES. Every failure lands in `pack_error` on a job that still serves its loop.
    """
    pf = _pf()
    import app as app_mod                       # lazy: app imports THIS module at startup
    try:
        frames = pf._frames_rgba(loop_path)
        # Drop the duplicated final loop frame, exactly as make_pet_zip does. A Wan loop's
        # last frame repeats its first; keeping it would put an extra cell on the sheet and
        # shift every later frame index, so a Lab frame number and a probe frame number
        # would refer to different pictures — the one disagreement §12.4 exists to forbid.
        if len(frames) > 1:
            frames = frames[:-1]

        animal, pose_name = spec["animal"], spec["pose_name"]
        profile = mp.load_motion_profile(spec["profile_key"], fallback_animal=animal)
        pose = profile.pose(pose_name)
        # Pass what make_pet_zip passes — same values, from the profile the loop already
        # resolved. PosePlayer reads fps/frames/columns straight out of this manifest, so
        # a Lab bundle that skimped here would render differently from a real pet's.
        pose_meta = {pose_name: {"runtime_role": pose.runtime_role, "loop": pose.loop,
                                 "timed_buffer_ms": pose.timed_buffer_ms, "view": pose.view}}

        # THE GPU DISCIPLINE (§12.3), both halves — neither substitutes for the other.
        # GPU_LOCK is process-local: it serializes this pack against a real build or a
        # design preview in THIS backend. The eviction is what handles a ComfyUI in
        # ANOTHER process still holding the Wan stack; without it birefnet's ~7 GiB
        # working set meets a full card, which is the documented OOM.
        if not app_mod.GPU_LOCK.acquire(timeout=_PACK_LOCK_TIMEOUT_S):
            raise RuntimeError("the GPU is busy generating a pet — the loop is above; "
                               "re-run Animate for the packed tile")
        try:
            pf._evict_comfy_models_for_cutout()
            zip_bytes = pf.pack_datsme_bundle(
                {pose_name: frames}, pf._slug(animal), animal.title(),
                pose_meta=pose_meta, movement_class=profile.movement_class,
                view=profile.view)
        finally:
            app_mod.GPU_LOCK.release()

        # A FRESH id: the job still serves the loop alongside this. Both the .zip (so
        # scripts/probe_matte_fill.py runs on the Lab's output unchanged — one instrument,
        # both surfaces) and its sheet .png (so the existing asset route can display it).
        packed_id = uuid.uuid4().hex[:16]
        (_lab_dir() / f"{packed_id}.zip").write_bytes(zip_bytes)
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
            sheet_png = z.read(next(n for n in z.namelist() if n.endswith("_sprite.png")))
            manifest = z.read("manifest.json")
        (_lab_dir() / f"{packed_id}.png").write_bytes(sheet_png)
        # The manifest is served BESIDE the sheet, as a saved pet's is, because PosePlayer
        # reads fps/frames/columns out of it. Unpacking the bundle into the two URLs the
        # player already speaks is what lets the Lab's tile be the same component the
        # user's result panel uses — the strongest answer to "does this imitate production".
        (_lab_dir() / f"{packed_id}.json").write_bytes(manifest)

        from PIL import Image as PILImage
        damage = pf.matte_fill_damage(PILImage.open(io.BytesIO(sheet_png)))
        _update_job(jid, packed_asset_id=packed_id,
                    packed_url=f"{router.prefix}/asset/{packed_id}.png",
                    packed_manifest_url=f"{router.prefix}/asset/{packed_id}.json",
                    packed_zip_url=f"{router.prefix}/asset/{packed_id}.zip",
                    metrics={"hard_zero_px": damage.hard_zero_px,
                             "filled_pct": round(damage.filled_pct, 4),
                             "glaring_pct": round(damage.glaring_pct, 4),
                             "line": damage.line()})
    except Exception as e:
        # `pack_error` is a distinct field from `error` precisely so "which step caused it"
        # is READ off the record rather than inferred. The job stays done and keeps its loop.
        _update_job(jid, pack_error=f"{type(e).__name__}: {e}"[:200])


def _start(wf: dict, ext: str, pack: Optional[dict] = None) -> dict:
    try:
        ep_idx = _reserve_endpoint()
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    jid = _new_job(ep_idx)
    threading.Thread(target=_run_job, args=(jid, wf, ext, ep_idx, pack), daemon=True).start()
    return {"job_id": jid}


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------
class StillBody(BaseModel):
    animal: str
    clause: str = ""
    seed: int = _DEFAULT_SEED
    # The still to redraw FROM: an uploaded photo (/reference) or a previous Lab still,
    # whose asset_id is itself a valid reference_id. It decides img2img vs txt2img and
    # NOTHING else — the prompt template follows the build stage, not this field (§2.6).
    # An anchor draw does not send it at all: a build's anchor knows nothing about the
    # reference.
    reference_id: str = ""
    # `base` distinguishes the shared base still from a pose anchor. The backend cannot
    # infer it: BOTH arrive with a non-empty clause (the base card sends base_pose). It
    # is load-bearing on BOTH paths now (§2.6) — a base draw that forgets it gets an
    # anchor's sentence — which is why the page sends it on every base draw.
    base: bool = False
    # base-only: the img2img denoise. ONE strength field, not a second `design_strength`
    # beside it (I1) — this already means "how hard to redraw the base", which is what a
    # design strength is; two would create a which-wins question at every call site.
    strength: float = 0.85
    # Step 2's structured design (§2.2). Composed SERVER-side by the designer's own
    # compose_design, and spent on the base img2img redraw ONLY — an anchor that carried
    # the ~240-char design string would draw a still no build has ever drawn (§0.3), so
    # the fields are refused anywhere else (I13).
    color: str = ""
    accessories: list[str] = []
    axis_picks: dict[str, str] = {}
    extra: str = ""

    def has_design(self) -> bool:
        return bool(self.color.strip() or self.extra.strip()
                    or any(a.strip() for a in self.accessories)
                    or any(v.strip() for v in self.axis_picks.values()))


class AnimateBody(BaseModel):
    asset_id: str
    animal: str
    profile_key: str
    pose_name: str
    seed: int = _DEFAULT_SEED
    # F4 (SPEC_MATTE_REPAIR_ORDER §12) — run the SHIPPED packer on the loop, as the last
    # stage of this job, exactly as make_pet_zip runs Phase B and then packs. Default ON
    # because production packs and the Lab's job is to show what production does; a build
    # never asks whether to pack. `false` is the bisection lever: it skips the eviction tax
    # on a batch (§12.3), and it still gets you a loop when the packer is the broken thing.
    pack: bool = True


class ConfigBody(BaseModel):
    active: list[int]


class SuggestBody(BaseModel):
    animal: str
    pose: str
    movement_class: str = ""


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.post("/reference")
async def upload_reference(image: UploadFile = File(...)):
    """Take a photo into the Lab and run it through the REAL upload door's captioner.

    The Lab could have kept the image raw and let the admin type the noun — one variable
    at a time is usually the Lab's whole discipline. Running triage + pet_likeness instead
    is deliberate: that path decides what a real upload is called, and getting it wrong is
    what drew a dog from a photograph of a person (2026-07-26). Exercising it here, beside
    the poses it feeds, is cheaper than discovering it in a 3-minute build.

    Returns the caption as DATA, never as a decision: the browser fills the animal field
    with `subject` and the admin overrides it freely. `usable: false` means triage rejected
    the photo — surfaced rather than swallowed, because that rejection is the failure mode
    worth being able to see.
    """
    import app as app_mod          # lazy: app imports THIS module at startup (design_calibration §2)

    if image.content_type not in app_mod.ALLOWED_IMAGE_MIMES:
        raise HTTPException(400, f"unsupported image type: {image.content_type}")
    body = await image.read()
    if len(body) > app_mod.MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Image exceeds 12 MB limit")

    # Normalize to PNG so /asset can serve it and ComfyUI can read it, whatever came in.
    from PIL import Image as PILImage
    asset_id = uuid.uuid4().hex[:12]
    path = _lab_dir() / f"{asset_id}.png"
    PILImage.open(io.BytesIO(body)).convert("RGB").save(path, "PNG")

    caption = app_mod._caption_upload(body, image.content_type, "", None)
    return {
        "reference_id": asset_id,
        "url": f"{router.prefix}/asset/{asset_id}.png",
        "usable": bool(caption),
        "subject": (caption or {}).get("subject") or "",
        "features": (caption or {}).get("features") or "",
        "description": (caption or {}).get("description") or "",
    }


def _compose_lab_design(animal: str, body: StillBody) -> tuple[str, str, float, Optional[float]]:
    """Step 2's picks → (description, subject, denoise, min_strength), through the
    DESIGNER's own functions (SPEC_MOTION_LAB_DESIGN_PARITY §2.2).

    TWO strings come out, and confusing them is the whole subject of §0.3:

      description  the ~240-char composed design. Spent on THIS redraw and never again.
      subject      `display_name.lower()` — "white snow leopard". This is what
                   /api/preview SAVES as the new reference's `description`, so it is
                   what /api/generate hands make_pet_zip, so it is what every pose
                   anchor and every loop prompt of a designed build carries. The COLOUR
                   rides along in it; the body shape, accessories, free text and the
                   recolor clause do not — they lived in `description` and are now spent.

    Every line here is a call into shared code, and that is the point: a second composer,
    a retyped input cap or a re-implemented clamp would make the Lab's stills subtly not
    the app's, and a workbench that draws something else is not evidence about a build.

      normalize_design_inputs  the caps ARE part of the composition contract (I2)
      filter_picks BEFORE composing  as step 2 does — skip it and a fur fragment lands
                   on a bird. The surface resolves from the TYPED name here, since the
                   Lab has no reference record to read one off (§2.1)
      compose_design  the one composer, whose clause ORDER is still under calibration
      effective_strength  the one clamp (I4/I11) — never a local min/max

    Imports are lazy because app.py imports THIS module at startup; `from app import
    compose_design` at module top is circular (design_calibration §2 documents the trap).
    """
    import app as app_mod

    design = app_mod.normalize_design_inputs(
        animal, body.color, body.accessories, body.axis_picks, body.extra)
    picks = design_axes_mod.filter_picks(
        design.picks, app_mod._resolve_typed_surface(design.species))
    description, display_name, min_strength = app_mod.compose_design(
        design.species, design.color, design.accessories, picks, design.extra)
    strength = design_calibration.effective_strength(
        picks, design.color, design.species, float(body.strength))
    return description, display_name.lower(), strength, min_strength


def _lab_reference(reference_id: str) -> Path:
    if not reference_id.isalnum():
        raise HTTPException(400, "bad reference_id")
    path = _lab_dir() / f"{reference_id}.png"
    if not path.exists():
        raise HTTPException(404, "reference not found — upload it again")
    return path


@router.post("/still")
def start_still(body: StillBody):
    """Draw the shared base still, or one pose anchor, exactly as the build stage it
    mirrors draws it (SPEC_MOTION_LAB_DESIGN_PARITY §2.3/§2.6).

    Two decisions, made SEPARATELY, because a build makes them separately:

      which SENTENCE   an ANCHOR is always the remix template — `/api/generate` requires
                       a reference_id, so `reference_image` is never None in the web tier
                       and `anchor_prompt = _remix_prompt` on every pet the app has ever
                       built (§2.6). `_base_prompt` is the CLI's branch. Only the
                       from-scratch BASE draw (step 1's txt2img archetype) uses it.
      img2img or txt2img   the reference decides, and ONLY the base is redrawn from it.
                       An anchor is never img2img in a build — a fresh still is the whole
                       point of the pose_prompt tier — so drawing one that way here would
                       flatter the Lab and lie about the build.

    Until Rev.3 of the spec those were one decision by accident: `reference_id` picked
    both, so the Lab's default flow drew anchors through the PALER base template, biased
    toward the very matte defect the Lab is pointed at.
    """
    animal = (body.animal or "").strip()[:_MAX_ANIMAL]
    if not animal:
        raise HTTPException(400, "animal is required")
    clause = (body.clause or "").strip()[:_MAX_CLAUSE]
    pf = _pf()
    seed = _clean_seed(body.seed)
    reference = _lab_reference(body.reference_id) if body.reference_id else None
    redraw = body.base and reference is not None         # step 2's img2img: the design lands here
    from_scratch = body.base and reference is None       # step 1's archetype draw

    if body.has_design() and not redraw:
        # I13. The composed string has exactly one legitimate destination; a request that
        # attaches one anywhere else is refused rather than silently composed (which would
        # draw a still no build draws) or silently dropped (which would look like it worked).
        raise HTTPException(400, "a design is a redraw of a base still — send it with "
                                 "base + reference_id, or draw the base first")

    # The SUBJECT is what a build's `description` carries — the short phrase that feeds the
    # pose anchors, the loop prompts, the profile keyword match and the breed slug. Without
    # a design it is the typed animal; a design REPLACES it with the display name
    # ("white snow leopard"), because that is what /api/preview saves on the new reference
    # and therefore what /api/generate hands the engine. The composed `description` is a
    # per-draw input to this one img2img and is never that subject.
    description, subject, strength, min_strength = animal, animal, float(body.strength), None
    if redraw:
        description, subject, strength, min_strength = _compose_lab_design(animal, body)

    template = pf._base_prompt if from_scratch else pf._remix_prompt
    prompt = template(description, clause) if clause else template(description)

    if redraw:
        started = _start(pf._img2img_wf(prompt, str(reference), seed, strength), "png")
    else:
        started = _start(pf._static_image_wf(prompt, seed), "png")
    # The composed string, the SUBJECT it leaves behind, and the clamp the server applied
    # all ride the START response (I5): each is known now, so none needs to survive the
    # ~15–50 s job, and LabJob stays a job-status shape. `subject` is the one the caller
    # must carry into its next anchor draw — it is the record a build would be holding.
    return {**started, "description": description, "subject": subject,
            "min_strength": min_strength}


@router.post("/animate")
def start_animate(body: AnimateBody):
    animal = (body.animal or "").strip()[:_MAX_ANIMAL]
    if not animal:
        raise HTTPException(400, "animal is required")
    if not (body.asset_id or "").isalnum():
        raise HTTPException(400, "bad asset_id")
    still = _lab_dir() / f"{body.asset_id}.png"
    if not still.exists():
        raise HTTPException(404, "still not found — generate it first")
    profile = mp.load_motion_profile(body.profile_key, fallback_animal=animal)
    pose = profile.pose(body.pose_name)
    if pose is None or not pose.enabled:
        raise HTTPException(400, f"pose {body.pose_name!r} is not enabled in {profile.key!r}")
    pf = _pf()
    wf = pf._loop_wf(mp.compose_pose_prompt(animal, pose), str(still), _clean_seed(body.seed))
    # …and then PACK it, as the last stage of this same job (§12.2). The spec the pack
    # needs is resolved here, on the request thread, where a bad profile_key is still a
    # clean 400 — the job thread's only job is to run stages.
    pack = {"animal": animal, "profile_key": body.profile_key,
            "pose_name": body.pose_name} if body.pack else None
    return _start(wf, "webp", pack)


@router.post("/suggest-clause")
def suggest_clause(body: SuggestBody):
    """AI draft of a pose_prompt clause (SPEC_MOTION_LAB §2). Best-effort: the admin
    edits and re-runs before saving. Degrades to a clear error when the engine is
    inert (no DATSPET_AI_API_KEY) — the whole Lab stays usable without it."""
    animal = (body.animal or "").strip()[:_MAX_ANIMAL]
    pose = (body.pose or "").strip()[:40]
    if not animal or not pose:
        raise HTTPException(400, "animal and pose are required")
    try:
        result, _ = ai_engine.call_purpose("pose_clause", variables={
            "animal": animal, "pose": pose,
            "movement_class": (body.movement_class or "").strip() or "unknown",
        })
    except ai_engine.AIUnavailable:
        raise HTTPException(503, "AI is not configured — set DATSPET_AI_API_KEY to use suggest.")
    except ai_engine.AIError as e:
        raise HTTPException(502, f"AI draft failed: {e}")
    clause = (result.get("clause") or "").strip()
    if not clause:
        raise HTTPException(502, "the AI returned an empty clause — try again")
    return {"clause": clause}


@router.get("/job/{job_id}")
def job_status(job_id: str):
    j = _get_job(job_id)
    if not j:
        raise HTTPException(404, "unknown job")
    return {"state": j["state"], "phase": j.get("phase", "running"),
            "asset_id": j["asset_id"], "url": j["url"], "ms": j["ms"],
            "error": j["error"], "elapsed": round(time.time() - j["t0"]),
            # F4 (§12.2): the packed sheet, its bundle, and this pose's damage numbers.
            # All None on an unpacked run; `pack_error` names the stage when the pack alone failed.
            "packed_asset_id": j.get("packed_asset_id"), "packed_url": j.get("packed_url"),
            "packed_manifest_url": j.get("packed_manifest_url"),
            "packed_zip_url": j.get("packed_zip_url"), "metrics": j.get("metrics"),
            "pack_error": j.get("pack_error")}


@router.post("/cancel/{job_id}")
def cancel_job(job_id: str):
    with _JOBS_LOCK:
        if job_id in _JOBS:
            _JOBS[job_id]["cancel"] = True
    return {"canceling": True}


@router.get("/config")
def get_config():
    """The GPU endpoints + their health + which are enabled (the Lab's GPU toggle)."""
    eps = _endpoints()
    active = _active_set()
    with _JOBS_LOCK:
        inflight = dict(_INFLIGHT)
    return {"endpoints": [
        {"index": i, "label": e["label"], "url": e["url"],
         "healthy": _healthy(e["url"]), "active": i in active, "inflight": inflight.get(i, 0)}
        for i, e in enumerate(eps)]}


@router.put("/config")
def set_config(body: ConfigBody):
    eps = _endpoints()
    valid = {i for i in body.active if 0 <= i < len(eps)}
    if not valid:
        raise HTTPException(400, "at least one endpoint must be active")
    global _ACTIVE
    with _EP_LOCK:
        _ACTIVE = valid
    return {"active": sorted(valid)}


@router.get("/asset/{asset_id}.{ext}")
def asset(asset_id: str, ext: str):
    # `zip` is here so the operator can pull the Lab's own bundle and run
    # scripts/probe_matte_fill.py on it unchanged — one instrument, both surfaces (§12.2).
    if not asset_id.isalnum() or ext not in ("png", "webp", "zip", "json"):
        raise HTTPException(404, "not found")
    path = _lab_dir() / f"{asset_id}.{ext}"
    if not path.exists():
        raise HTTPException(404, "not found")
    media = {"zip": "application/zip", "json": "application/json"}.get(ext, f"image/{ext}")
    return FileResponse(path, media_type=media)
