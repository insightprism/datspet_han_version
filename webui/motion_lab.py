"""motion_lab — the admin visual workbench for authoring pose_prompt clauses.

SPEC_MOTION_LAB. A GPU-dev-box tool: it runs `factory.py`'s generation STEPS on a
chosen animal + pose so an admin can tune a pose clause and watch it move, then
save the clause to the profile via the EXISTING motion_admin write path.

**Async job model (§ animation-cancel).** A still or a loop takes ~15–45 s, longer
than the dev proxy will hold a connection open — a synchronous endpoint's result is
generated but never reaches the browser. So generation is a JOB: `POST /still` /
`POST /animate` return a `job_id` immediately, a background thread runs the pipeline,
and the page polls `GET /job/{id}` (which carries an elapsed timer). `POST /cancel/{id}`
sets a flag the poll loop honors and interrupts ComfyUI, so a slow generation can be
stopped cleanly. `GET /asset/…` serves the finished PNG/WebP back.

Save is the existing PUT /api/admin/motions/{key}. Local backend ONLY (it drives
ComfyUI through pet_factory); the router is mounted only when PET_GEN_BACKEND=local.
pet_factory is imported LAZILY inside the job thread, so importing THIS module stays
GPU-less-safe.
"""
from __future__ import annotations

import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

import requests
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

import datsme_integration
from pet_factory import motion_profiles as mp

router = APIRouter(
    prefix="/api/admin/motion-lab",
    dependencies=[Depends(datsme_integration.require_admin_launch)],
)

_DEFAULT_SEED = 42
_MAX_ANIMAL = 240      # matches the pool handler's transport cap
_MAX_CLAUSE = 240
_JOB_TTL = 15 * 60     # forget finished jobs after 15 min (dev tool, in-memory)

# job_id -> {state, asset_id, url, ms, error, cancel, t0}. state: running|done|error|canceled.
_JOBS: dict[str, dict] = {}
_JOBS_LOCK = threading.Lock()


class _Canceled(Exception):
    pass


def _pf():
    """Lazy factory import (local-only, drags the ML stack)."""
    from pet_factory import factory as pf
    return pf


def _lab_dir() -> Path:
    """Scratch dir for Lab assets, UNDER ComfyUI's output dir so the loop step can
    read an anchor still back by absolute path (VHS_LoadImagePath)."""
    d = _pf().COMFY_OUTPUT_DIR / "_lab"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _clean_seed(seed: Optional[int]) -> int:
    try:
        s = int(seed)
    except (TypeError, ValueError):
        return _DEFAULT_SEED
    return s if 1 <= s <= 2**31 else _DEFAULT_SEED


# ---------------------------------------------------------------------------
# Job store
# ---------------------------------------------------------------------------
def _new_job() -> str:
    _prune_jobs()
    jid = uuid.uuid4().hex[:16]
    with _JOBS_LOCK:
        # phase distinguishes waiting in ComfyUI's serial queue ("pending") from
        # actually generating ("running"), so several queued jobs read honestly.
        _JOBS[jid] = {"state": "running", "phase": "pending", "asset_id": None,
                      "url": None, "ms": None, "error": None, "cancel": False, "t0": time.time()}
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


def _phase_of(pf, pid: str) -> str:
    """Is our prompt actively generating ('running') or waiting behind others in
    ComfyUI's serial queue ('pending')? Falls back to 'running' on any error."""
    try:
        q = requests.get(f"{pf.COMFY_URL}/queue", timeout=5).json()
    except Exception:
        return "running"
    if any(len(it) > 1 and it[1] == pid for it in q.get("queue_running", [])):
        return "running"
    if any(len(it) > 1 and it[1] == pid for it in q.get("queue_pending", [])):
        return "pending"
    return "running"


def _submit_and_wait(pf, wf: dict, jid: str, timeout: int = 300) -> str:
    """Submit a workflow to ComfyUI and poll /history for its output, checking the
    job's cancel flag each tick (and interrupting ComfyUI on cancel), and reporting
    pending/running phase. Mirrors factory._run's loop but with the hooks it lacks.
    Several jobs may be in flight at once — ComfyUI runs them one at a time."""
    r = requests.post(f"{pf.COMFY_URL}/prompt", json={"prompt": wf, "client_id": pf.CLIENT_ID}, timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f"ComfyUI rejected workflow: {r.text[:200]}")
    pid = r.json()["prompt_id"]
    t0 = time.time()
    while time.time() - t0 < timeout:
        if _get_job(jid).get("cancel"):
            try:
                requests.post(f"{pf.COMFY_URL}/interrupt", timeout=10)
            except Exception:
                pass
            raise _Canceled()
        try:
            h = requests.get(f"{pf.COMFY_URL}/history/{pid}", timeout=10).json()
        except Exception:
            h = {}
        for o in h.get(pid, {}).get("outputs", {}).values():
            picks = (o.get("gifs") or []) + (o.get("images") or [])
            if picks:
                return picks[0]["filename"]
        _update_job(jid, phase=_phase_of(pf, pid))
        time.sleep(1.0)
    raise TimeoutError("generation timed out")


def _run_job(jid: str, wf: dict, ext: str) -> None:
    """Thread body: run the workflow, copy the output into the lab dir, update the job."""
    try:
        pf = _pf()
        t0 = time.time()
        fn = _submit_and_wait(pf, wf, jid)
        asset_id = uuid.uuid4().hex[:16]
        shutil.copy(pf.COMFY_OUTPUT_DIR / fn, _lab_dir() / f"{asset_id}.{ext}")
        _update_job(jid, state="done", asset_id=asset_id,
                    url=f"/api/admin/motion-lab/asset/{asset_id}.{ext}",
                    ms=round((time.time() - t0) * 1000))
    except _Canceled:
        _update_job(jid, state="canceled")
    except Exception as e:
        _update_job(jid, state="error", error=str(e)[:200])


def _start(wf: dict, ext: str) -> dict:
    jid = _new_job()
    threading.Thread(target=_run_job, args=(jid, wf, ext), daemon=True).start()
    return {"job_id": jid}


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------
class StillBody(BaseModel):
    animal: str
    clause: str = ""                      # empty → the standing base; set → the pose anchor
    seed: int = _DEFAULT_SEED


class AnimateBody(BaseModel):
    asset_id: str                         # a still minted by POST /still
    animal: str
    profile_key: str                      # the pose's profile (for compose_pose_prompt)
    pose_name: str
    seed: int = _DEFAULT_SEED


# ---------------------------------------------------------------------------
# Generation endpoints — return a job id immediately; the page polls /job/{id}
# ---------------------------------------------------------------------------
@router.post("/still")
def start_still(body: StillBody):
    animal = (body.animal or "").strip()[:_MAX_ANIMAL]
    if not animal:
        raise HTTPException(400, "animal is required")
    clause = (body.clause or "").strip()[:_MAX_CLAUSE]
    pf = _pf()
    prompt = pf._base_prompt(animal, clause) if clause else pf._base_prompt(animal)
    return _start(pf._static_image_wf(prompt, _clean_seed(body.seed)), "png")


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
    return _start(wf, "webp")


@router.get("/job/{job_id}")
def job_status(job_id: str):
    j = _get_job(job_id)
    if not j:
        raise HTTPException(404, "unknown job")
    return {"state": j["state"], "phase": j.get("phase", "running"),
            "asset_id": j["asset_id"], "url": j["url"], "ms": j["ms"],
            "error": j["error"], "elapsed": round(time.time() - j["t0"])}


@router.post("/cancel/{job_id}")
def cancel_job(job_id: str):
    with _JOBS_LOCK:
        if job_id in _JOBS:
            _JOBS[job_id]["cancel"] = True
    return {"canceling": True}


@router.get("/asset/{asset_id}.{ext}")
def asset(asset_id: str, ext: str):
    if not asset_id.isalnum() or ext not in ("png", "webp"):
        raise HTTPException(404, "not found")
    path = _lab_dir() / f"{asset_id}.{ext}"
    if not path.exists():
        raise HTTPException(404, "not found")
    return FileResponse(path, media_type=f"image/{ext}")
