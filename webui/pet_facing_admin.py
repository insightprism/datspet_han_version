"""Admin repair door for a pet's FACING metadata.

The generation prompt demands "side profile view, facing right"
(pet_factory/prompt_templates.py — documented as load-bearing) and the packer
stamps the motion profile's declared view without ever looking at the pixels
(pack_datsme_bundle). When the image model disobeys — observed 2026-08-02 on
two humanoid builds — the manifest asserts right/flip over left-facing
artwork and every runtime dutifully shows the pet running backwards.
Nothing in the pipeline can SEE which way the artwork faces, so the
correction is a human judgement, which makes this admin data repair, not
engine code: the door rewrites the view metadata and the runtimes keep
honoring the manifest exactly as they already do.

Facing is PER ANIMATION, not per pet: each pose is its own I2V loop off the
base still, and the model picks a direction per loop (measured on both
humanoid builds: `run` came out facing left while the other seven poses face
right). The body therefore carries a base view — written at sheet level and
onto every animation — plus optional per-animation overrides for the poses
that disagree with it.

One repair covers BOTH stored copies of the manifest — the manifest_json
column the web runtimes read AND manifest.json inside bundle_zip (what a
DatsMe adopt fetches) — and rederives the bundle digest, because the DPP
transfer pointer publishes it (db.repair_pet_bundle). A host copy adopted
BEFORE the repair is out of reach from here: the host holds its own bundle,
so the fix reaches the house only through a re-adopt.

Gate + audit follow motion_admin: every route requires the adm-claim cookie
and every successful write prints an audit line.
"""
from __future__ import annotations

import io
import json
import zipfile

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

import datsme_integration
import db

router = APIRouter(
    prefix="/api/admin/pets",
    dependencies=[Depends(datsme_integration.require_admin_launch)],
)

# The runtime's closed vocabularies — mirrors web/src/pet/types.ts
# (ViewKind / NativeFacing / MirroringPolicy). Unlike the motion-profile
# admin, which shape-checks only and leaves values to a build guard, this
# door enforces the enums at write time: it edits a REAL user's stored pet,
# and no build ever re-validates a pet row — an unknown policy string would
# ride to the browser and fall through resolveScaleX's default silently.
VIEW_KINDS = ("side", "front", "three_quarter", "top_down")
NATIVE_FACINGS = ("right", "left", "none")
MIRRORING_POLICIES = ("flip", "none", "flip-from-left")


class FacingBody(BaseModel):
    """One complete view block (SPEC_BUNDLE_MOTION_CONTRACT §3.3) — the three
    fields travel as a unit; a partial repair would leave the block lying in
    a new way. `animations` holds per-pose overrides (same three-field shape)
    for the poses whose artwork disagrees with the base view."""
    view_kind: str
    native_facing: str
    mirroring_policy: str
    animations: dict[str, dict] | None = None


def _view_errors(view: dict, where: str) -> list[str]:
    errs = []
    if view.get("view_kind") not in VIEW_KINDS:
        errs.append(f"{where}.view_kind must be one of {list(VIEW_KINDS)}")
    if view.get("native_facing") not in NATIVE_FACINGS:
        errs.append(f"{where}.native_facing must be one of {list(NATIVE_FACINGS)}")
    if view.get("mirroring_policy") not in MIRRORING_POLICIES:
        errs.append(
            f"{where}.mirroring_policy must be one of {list(MIRRORING_POLICIES)}")
    return errs


def _validate(body: FacingBody, manifest_poses: set[str]) -> None:
    errs = _view_errors(body.model_dump(exclude={"animations"}), "view")
    for pose, view in (body.animations or {}).items():
        if pose not in manifest_poses:
            errs.append(f"animations.{pose}: no such pose "
                        f"(manifest has {sorted(manifest_poses)})")
        elif isinstance(view, dict):
            errs.extend(_view_errors(view, f"animations.{pose}"))
        else:
            errs.append(f"animations.{pose} must be a view object")
    if errs:
        raise HTTPException(status_code=422, detail="; ".join(errs))


def _rewrite_manifest(manifest_json: str, view: dict,
                      per_animation: dict | None = None) -> str:
    """Set the sheet-level view keys and every animation's view block — the
    base view everywhere, a per-animation override where given. A
    per-animation description (human prose) survives; the three machine
    fields are replaced — the repair is about what the runtime reads."""
    manifest = json.loads(manifest_json)
    manifest.update(view)
    for name, anim in manifest.get("animations", {}).items():
        existing = anim.get("view") or {}
        block = dict((per_animation or {}).get(name, view))
        if isinstance(existing, dict) and "description" in existing:
            block.setdefault("description", existing["description"])
        anim["view"] = block
    return json.dumps(manifest, indent=2)


def _rewrite_bundle(bundle_zip: bytes, manifest_json: str) -> bytes:
    """The same manifest, inside the zip — members copied byte-for-byte so
    the sprite sheet and package.json are untouched."""
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(bundle_zip)) as src, \
         zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for member in src.namelist():
            if member == "manifest.json":
                dst.writestr(member, manifest_json)
            else:
                dst.writestr(member, src.read(member))
    return out.getvalue()


@router.post("/{pet_id}/facing")
def set_pet_facing(pet_id: str, request: Request, body: FacingBody):
    row = db.get_pet(pet_id)
    if row is None:
        raise HTTPException(status_code=404, detail="no such pet")
    manifest_poses = set(json.loads(row["manifest_json"]).get("animations", {}))
    _validate(body, manifest_poses)

    view = {"view_kind": body.view_kind, "native_facing": body.native_facing,
            "mirroring_policy": body.mirroring_policy}
    manifest_json = _rewrite_manifest(row["manifest_json"], view,
                                      body.animations)
    bundle_zip = _rewrite_bundle(row["bundle_zip"], manifest_json)
    db.repair_pet_bundle(pet_id, manifest_json=manifest_json,
                         bundle_zip=bundle_zip)

    who = datsme_integration.admin_user_id(request) or "unknown"
    overrides = ", ".join(
        f"{k}={v.get('native_facing')}/{v.get('mirroring_policy')}"
        for k, v in (body.animations or {}).items()) or "none"
    print(f"[pet-facing-admin] {who} set facing on pet {pet_id!r}: "
          f"{body.view_kind}/{body.native_facing}/{body.mirroring_policy} "
          f"overrides: {overrides}", flush=True)
    repaired = db.get_pet(pet_id)
    return {"id": pet_id, "view": view,
            "bundle_sha256": repaired["bundle_sha256"]}
