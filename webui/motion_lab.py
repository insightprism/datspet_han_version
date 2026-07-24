"""motion_lab — the admin visual workbench for authoring pose_prompt clauses.

SPEC_MOTION_LAB. A GPU-dev-box tool that runs `factory.py`'s generation STEPS on a
chosen animal + pose so an admin can tune a pose clause and watch it move, then save
the clause to the profile via the EXISTING motion_admin write path.

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

import os
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
_MAX_ANIMAL = 240
_MAX_CLAUSE = 240
_JOB_TTL = 15 * 60
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


def _pick_endpoint() -> int:
    """The least-busy healthy ENABLED endpoint (ties → lowest index)."""
    eps = _endpoints()
    healthy = [i for i in sorted(_active_set()) if _healthy(eps[i]["url"])]
    if not healthy:
        raise RuntimeError("no ComfyUI endpoint is reachable — is it running?")
    with _JOBS_LOCK:
        return min(healthy, key=lambda i: (_INFLIGHT.get(i, 0), i))


def _lab_dir() -> Path:
    """The ONE asset store (under GPU 0's output dir), served by /asset and read by
    every ComfyUI as an animate input over the shared filesystem."""
    d = _endpoints()[0]["out"] / "_lab"
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
def _new_job(ep_idx: int) -> str:
    _prune_jobs()
    jid = uuid.uuid4().hex[:16]
    with _JOBS_LOCK:
        _JOBS[jid] = {"state": "running", "phase": "pending", "asset_id": None, "url": None,
                      "ms": None, "error": None, "cancel": False, "t0": time.time(), "ep": ep_idx}
        _INFLIGHT[ep_idx] = _INFLIGHT.get(ep_idx, 0) + 1
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


def _run_job(jid: str, wf: dict, ext: str, ep_idx: int) -> None:
    ep = _endpoints()[ep_idx]
    try:
        t0 = time.time()
        fn = _submit_and_wait(ep, wf, jid)
        asset_id = uuid.uuid4().hex[:16]
        shutil.copy(ep["out"] / fn, _lab_dir() / f"{asset_id}.{ext}")   # → the one shared store
        _update_job(jid, state="done", asset_id=asset_id,
                    url=f"/api/admin/motion-lab/asset/{asset_id}.{ext}",
                    ms=round((time.time() - t0) * 1000))
    except _Canceled:
        _update_job(jid, state="canceled")
    except Exception as e:
        _update_job(jid, state="error", error=str(e)[:200])
    finally:
        with _JOBS_LOCK:
            _INFLIGHT[ep_idx] = max(0, _INFLIGHT.get(ep_idx, 0) - 1)


def _start(wf: dict, ext: str) -> dict:
    try:
        ep_idx = _pick_endpoint()
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    jid = _new_job(ep_idx)
    threading.Thread(target=_run_job, args=(jid, wf, ext, ep_idx), daemon=True).start()
    return {"job_id": jid}


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------
class StillBody(BaseModel):
    animal: str
    clause: str = ""
    seed: int = _DEFAULT_SEED


class AnimateBody(BaseModel):
    asset_id: str
    animal: str
    profile_key: str
    pose_name: str
    seed: int = _DEFAULT_SEED


class ConfigBody(BaseModel):
    active: list[int]


# ---------------------------------------------------------------------------
# Endpoints
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
    if not asset_id.isalnum() or ext not in ("png", "webp"):
        raise HTTPException(404, "not found")
    path = _lab_dir() / f"{asset_id}.{ext}"
    if not path.exists():
        raise HTTPException(404, "not found")
    return FileResponse(path, media_type=f"image/{ext}")
