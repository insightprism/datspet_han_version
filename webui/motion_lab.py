"""motion_lab — the admin visual workbench for authoring pose_prompt clauses.

SPEC_MOTION_LAB. A GPU-dev-box tool: it runs `factory.py`'s generation STEPS on a
chosen animal + pose so an admin can tune a pose clause and watch it move, then
save the clause to the profile via the EXISTING motion_admin write path (no new
store). Two generation endpoints wrap functions that already exist:

  POST /still    → a fresh still: the standing base (no clause) or the pose anchor
                   (with a clause), from `_base_prompt(animal, clause)` at a fixed
                   seed so base and anchor are the SAME animal (§1 steps 1–3).
  POST /animate  → the Wan loop from a still, using the pose's own action/suffix
                   as the motion prompt (compose_pose_prompt) (§1 step 4).
  GET  /asset/…  → serve a generated PNG/WebP back to the browser.

Save is the existing PUT /api/admin/motions/{key} (the page adds the `control`
block to the pose and writes the profile back through the shared validator, §3).

Local-backend ONLY: it drives ComfyUI through pet_factory (the ML stack), so its
router is mounted only when PET_GEN_BACKEND=local — never on the GPU-less prod tier
(§5). pet_factory is imported LAZILY inside the endpoints, so importing THIS module
stays GPU-less-safe (the module can load anywhere; only a real call needs the deps).
"""
from __future__ import annotations

import shutil
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

import datsme_integration
from pet_factory import motion_profiles as mp

router = APIRouter(
    prefix="/api/admin/motion-lab",
    dependencies=[Depends(datsme_integration.require_admin_launch)],
)

# A fixed default seed so a base and its anchor land on the same animal (the whole
# point — the walk pose and the fly pose must be the same pet). The admin can vary
# it to reroll. Bounded to a sane 31-bit range.
_DEFAULT_SEED = 42
_MAX_ANIMAL = 240      # matches the pool handler's transport cap
_MAX_CLAUSE = 240


def _pf():
    """Lazy factory import (local-only, drags the ML stack). Isolated here so the
    module imports fine on any tier and only a real generation touches the deps."""
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
# Generation endpoints (sync `def` — each blocks ~15–40 s on the GPU, like the
# reference-render endpoints; the admin runs one at a time)
# ---------------------------------------------------------------------------
@router.post("/still")
def make_still(body: StillBody):
    animal = (body.animal or "").strip()[:_MAX_ANIMAL]
    if not animal:
        raise HTTPException(400, "animal is required")
    clause = (body.clause or "").strip()[:_MAX_CLAUSE]
    pf = _pf()
    seed = _clean_seed(body.seed)
    # base = the standing house-style still; anchor = the same, with the pose clause
    # swapped in for "standing" — exactly the pose_prompt mechanism (§3.9.1).
    prompt = pf._base_prompt(animal, clause) if clause else pf._base_prompt(animal)
    t0 = time.time()
    fn = pf._run(pf._static_image_wf(prompt, seed))
    asset_id = uuid.uuid4().hex[:16]
    shutil.copy(pf.COMFY_OUTPUT_DIR / fn, _lab_dir() / f"{asset_id}.png")
    return {"asset_id": asset_id, "kind": "anchor" if clause else "base",
            "url": f"/api/admin/motion-lab/asset/{asset_id}.png",
            "ms": round((time.time() - t0) * 1000)}


@router.post("/animate")
def animate(body: AnimateBody):
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
    seed = _clean_seed(body.seed)
    t0 = time.time()
    fn = pf._run(pf._loop_wf(mp.compose_pose_prompt(animal, pose), str(still), seed))
    asset_id = uuid.uuid4().hex[:16]
    shutil.copy(pf.COMFY_OUTPUT_DIR / fn, _lab_dir() / f"{asset_id}.webp")
    return {"asset_id": asset_id,
            "url": f"/api/admin/motion-lab/asset/{asset_id}.webp",
            "ms": round((time.time() - t0) * 1000)}


@router.get("/asset/{asset_id}.{ext}")
def asset(asset_id: str, ext: str):
    if not asset_id.isalnum() or ext not in ("png", "webp"):
        raise HTTPException(404, "not found")
    path = _lab_dir() / f"{asset_id}.{ext}"
    if not path.exists():
        raise HTTPException(404, "not found")
    return FileResponse(path, media_type=f"image/{ext}")
