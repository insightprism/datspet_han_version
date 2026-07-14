"""pool_client.py — the one adapter between the web tier and the shared_gpu_cpu pool.

Every pool endpoint URL lives here and nowhere else (the "one client adapter per
backend" rule). The web tier calls this instead of importing `pet_factory`, so the
identical backend runs on a GPU box (dev) or a GPU-less box (Hetzner) with only a
`PET_GEN_BACKEND` flip (see app.py). Mirrors the proven `created_pets/make_pet.py`
contract — POST /api/jobs → poll GET /api/jobs/{id} → GET /api/jobs/{id}/result —
but as a reusable module with a progress callback so the existing job/preview UX is
preserved.

Two translations the web tier depends on (spec §A.1):
  - pool status `dead` → web `error` (the web tier's Job has no `dead` state; Finding 7).
  - pool `pct` is 0..100, but the web tier's `Job.progress` is a fraction 0..1, and
    make_pet_zip's local `on_progress(msg, fraction)` is also 0..1 — so this adapter
    hands the callback a FRACTION (÷100), matching the local path exactly (R5-1).
    Wiring the raw pct through would pin the UI progress bar at 100× instantly.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Optional


def _pool_url() -> str:
    return os.environ.get("POOL_URL", "https://pool.datsme.me").rstrip("/")


def _app_key() -> str:
    """The datspet pool app key — from POOL_APP_KEY, else ~/.pool/datspet_key.
    Raised (not exited) so the backend surfaces a clean job error, never a crash."""
    key = os.environ.get("POOL_APP_KEY")
    if key:
        return key.strip()
    keyfile = Path.home() / ".pool" / "datspet_key"
    if keyfile.is_file():
        return keyfile.read_text().strip()
    raise PoolError(
        "no pool app key — set POOL_APP_KEY, or save it to ~/.pool/datspet_key "
        "(server copy: /var/www/pool/app_key_datspet)."
    )


class PoolError(RuntimeError):
    """Any pool-side failure the web tier should surface as a job error."""


def _req(method: str, path: str, *, body: Optional[dict] = None, timeout: int = 60):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        _pool_url() + path, data=data, method=method,
        headers={"X-App-Key": _app_key(), "Content-Type": "application/json"},
    )
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        raise PoolError(f"pool {method} {path} failed [{e.code}]: {detail}") from e
    except urllib.error.URLError as e:
        raise PoolError(f"pool {method} {path} unreachable: {e.reason}") from e


def submit(task: str, params: dict, *, labels: Optional[dict] = None) -> str:
    """Submit {task, params} to the pool; return the pool job id.

    `labels` is an OPTIONAL flat string→string dict of advisory attribution
    metadata (e.g. {"user": ..., "device": ...}) for the pool's "requested by"
    dashboard column. It's additive: sent only when non-empty, and its absence
    changes nothing (a submit without labels behaves exactly as before). The
    values are display metadata, never secrets. This adapter forwards them
    verbatim — building/classifying them is the web tier's job."""
    body: dict = {"task": task, "params": params}
    if labels:
        body["labels"] = labels
    resp = json.load(_req("POST", "/api/jobs", body=body))
    job_id = resp.get("job_id")
    if not job_id:
        raise PoolError(f"pool accepted the job but returned no job_id: {resp!r}")
    return job_id


def poll(job_id: str) -> dict:
    """One status read. Returns {status, pct, msg, error} with `dead` already
    mapped to `error` (Finding 7). `pct` stays 0..100 here — the fraction
    conversion happens in run_to_result's callback (R5-1)."""
    s = json.load(_req("GET", f"/api/jobs/{job_id}"))
    status = s.get("status", "")
    if status == "dead":
        status = "error"
        if not s.get("error"):
            s["error"] = "the pool gave up on this job (node died and it was not reclaimed)"
    return {
        "status": status,
        "pct": float(s.get("pct", 0.0)),
        "msg": s.get("msg", ""),
        "error": s.get("error"),
    }


def result_bytes(job_id: str) -> bytes:
    """The finished result bytes — the `.zip` for pet_factory, the PNG for
    pet_preview. Call only after poll() reports `done`."""
    return _req("GET", f"/api/jobs/{job_id}/result").read()


def run_to_result(
    task: str,
    params: dict,
    *,
    labels: Optional[dict] = None,
    on_progress: Optional[Callable[[str, float], None]] = None,
    poll_interval: float = 4.0,
    timeout_s: float = 900.0,
) -> bytes:
    """Submit → poll to completion → return the result bytes, driving a progress
    callback along the way.

    on_progress(msg, fraction) receives a FRACTION 0..1 (pct ÷ 100), so it plugs
    straight into the same code the local make_pet_zip callback feeds (R5-1).
    Raises PoolError on error/dead/timeout — the caller turns that into a failed Job.

    `labels`: optional attribution metadata forwarded to submit() (see submit()).
    poll_interval: 4 s suits ~3-min builds; the preview path passes ~1 s (§A.3).
    timeout_s: a client-side ceiling; the pool's own watchdog is authoritative,
    this just stops an unbounded wait if the dispatcher goes away.
    """
    return drive_to_result(submit(task, params, labels=labels), on_progress=on_progress,
                           poll_interval=poll_interval, timeout_s=timeout_s)


def drive_to_result(
    job_id: str,
    *,
    on_progress: Optional[Callable[[str, float], None]] = None,
    poll_interval: float = 4.0,
    timeout_s: float = 900.0,
) -> bytes:
    """Poll an ALREADY-SUBMITTED pool job to completion and return its bytes.
    Split out of run_to_result so the web tier can persist the pool job id
    between submit and drive — that persisted id is what lets a restarted web
    tier REATTACH to a job still generating on a worker (Opt-1, spec §A.6)."""
    deadline = time.monotonic() + timeout_s
    last_beat = None
    while True:
        s = poll(job_id)
        # Beat on any (msg, pct) change — a handler may hold one message while
        # its pct climbs, and gating on the message alone would freeze the bar.
        # Skip empty messages (a still-queued job reports msg "") so the
        # caller's "Waiting…" text isn't blanked before the first real beat.
        beat = (s["msg"], s["pct"])
        if on_progress is not None and s["msg"] and beat != last_beat:
            on_progress(s["msg"], s["pct"] / 100.0)
            last_beat = beat
        if s["status"] == "done":
            return result_bytes(job_id)
        if s["status"] == "error":
            raise PoolError(s.get("error") or "generation failed on the pool")
        if time.monotonic() >= deadline:
            raise PoolError(f"pool job {job_id} did not finish within {int(timeout_s)}s")
        time.sleep(poll_interval)


def workshop_status(task: str = "pet_factory") -> dict:
    """Reduced pet-worker liveness for the 'workshop offline/busy' UI (§C.1a).
    Reads /api/pool server-side (the app key never reaches the browser) and returns
    {online: bool, busy: bool}: online = at least one node advertises `task`; busy =
    every node advertising it is currently busy. On any pool error, reports offline
    (fail-safe: the UI shows 'workshop offline' rather than a hard error)."""
    try:
        nodes = json.load(_req("GET", "/api/pool", timeout=8))
    except PoolError:
        return {"online": False, "busy": False}
    if isinstance(nodes, dict):
        nodes = nodes.get("nodes", [])
    capable = [n for n in nodes if task in (n.get("tasks") or []) and n.get("online")]
    if not capable:
        return {"online": False, "busy": False}
    return {"online": True, "busy": all(n.get("busy") for n in capable)}
