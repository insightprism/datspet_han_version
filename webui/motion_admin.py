"""motion_admin — the DatsPet admin API for motion-profile CRUD.

SPEC_MOTION_PROFILE_ADMIN §4. An APIRouter, every endpoint gated by
require_admin_launch (the adm-claim cookie). Thin over the pure-data write path
(pet_factory.motion_profiles.admin); this layer only does HTTP shaping, the
catalog-pin delete guard, the writability gate, and the audit line.

The validator (motion_profiles.admin.validate_profile) is the single definition
of "valid" — shared with the guard test — so the admin can never write a profile
the build would reject.
"""
from __future__ import annotations

import json
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

import admin_common
import datsme_integration
from pet_factory import animal_catalog as animal_catalog_mod
from pet_factory import motion_profiles as mp
from pet_factory.motion_profiles import admin as mp_admin

router = APIRouter(
    prefix="/api/admin/motions",
    dependencies=[Depends(datsme_integration.require_admin_launch)],
)


# ---------------------------------------------------------------------------
# Writability (§7.1) — the shared, parameterized policy (admin_common): writes
# on a writable/dev instance; prod refuses 409 unless MOTION_ADMIN_WRITABLE=1
# opts in. Reads/list always work. Kept as module-level functions so tests can
# monkeypatch them, exactly as before the extraction.
# ---------------------------------------------------------------------------
def _writable() -> bool:
    return admin_common.writable(mp._DIR, "MOTION_ADMIN_WRITABLE")


def _require_writable() -> None:
    admin_common.require_writable(_writable(), "MOTION_ADMIN_WRITABLE", "motion profiles")


# ---------------------------------------------------------------------------
# Catalog-pin delete guard (§6). A profile still pinned by a catalog entry can't
# be deleted (it would orphan the pin + red the catalog guard test).
# ---------------------------------------------------------------------------
def _catalog_pin_map() -> dict[str, list[str]]:
    """Map every pinned motion-profile key → the catalog references (animal or
    animal/breed) that pin it, in ONE catalog walk. The list endpoint uses this so
    it doesn't re-walk the whole catalog once per profile (§6)."""
    pins: dict[str, set[str]] = {}
    for a in animal_catalog_mod.list_animals():
        akey = a["key"]
        amp = a.get("motion_profile")
        if amp:
            pins.setdefault(amp, set()).add(akey)
        for b in a.get("breeds", []):
            resolved = animal_catalog_mod.resolved_motion_profile(akey, b["key"])
            if resolved:
                pins.setdefault(resolved, set()).add(f"{akey}/{b['key']}")
    return {k: sorted(v) for k, v in pins.items()}


def _catalog_pins_for(key: str) -> list[str]:
    """Catalog references that pin a single profile key (the delete-guard path,
    which needs just one key). The list endpoint uses _catalog_pin_map instead."""
    return _catalog_pin_map().get(key, [])


def _audit(request: Request, op: str, key: str) -> None:
    who = datsme_integration.admin_user_id(request) or "unknown"
    print(f"[motion-admin] {who} {op} profile {key!r}", flush=True)


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------
class ProfileBody(BaseModel):
    profile: dict         # the full <key>.json content
    label: str            # the registry label


class DuplicateBody(BaseModel):
    new_key: str
    new_label: str


def _summary(entry: dict, prof, *, default_key: str, pinned_by: list[str]) -> dict:
    """List-pane summary for one profile. `default_key` and `pinned_by` are passed
    in (computed once by the caller) so the list endpoint stays O(N), not O(N²)."""
    return {
        "key": entry["key"],
        "label": entry.get("label", entry["key"]),
        "level": entry.get("level"),
        "movement_class": prof.movement_class,
        "enabled_poses": prof.enabled_poses(),
        "keyword_count": len(prof.keywords),
        "is_default": entry["key"] == default_key,
        "pinned_by": pinned_by,
    }


# ---------------------------------------------------------------------------
# Read endpoints (always allowed — even on a read-only prod tier)
# ---------------------------------------------------------------------------
@router.get("")
def list_profiles():
    """Registry + a summary of every profile (drives the list pane)."""
    registry = mp_admin.load_registry()
    default_key = registry.get("default")
    pin_map = _catalog_pin_map()          # one catalog walk for the whole list
    profiles = []
    for entry in registry.get("profiles", []):
        prof = mp.load_motion_profile(entry["key"])
        profiles.append(_summary(
            entry, prof,
            default_key=default_key,
            pinned_by=pin_map.get(entry["key"], []),
        ))
    return {
        "default": default_key,
        "writable": _writable(),
        "profiles": sorted(profiles, key=lambda p: p["key"]),
    }


@router.get("/{key}")
def get_profile(key: str):
    """One profile's full JSON (the edit form's source)."""
    if not mp_admin._KEY_RE.match(key):
        raise HTTPException(404, "profile not found")
    registry = mp_admin.load_registry()
    entry = next((e for e in registry["profiles"] if e["key"] == key), None)
    if entry is None:
        raise HTTPException(404, "profile not found")
    raw = json.loads((mp._DIR / entry["file"]).read_text())
    return {"profile": raw, "label": entry.get("label", key),
            "is_default": key == registry.get("default"),
            "pinned_by": _catalog_pins_for(key), "writable": _writable()}


# ---------------------------------------------------------------------------
# Write endpoints (gated by _require_writable)
# ---------------------------------------------------------------------------
@router.post("")
def create_profile(body: ProfileBody, request: Request):
    _require_writable()
    try:
        entry = mp_admin.write_profile(body.profile, label=body.label, existing_key=None)
    except mp_admin.ProfileWriteError as e:
        raise HTTPException(422, {"error": "validation_failed", "errors": e.errors})
    _audit(request, "create", entry["key"])
    return {"created": entry}


@router.put("/{key}")
def update_profile(key: str, body: ProfileBody, request: Request):
    _require_writable()
    if not mp_admin._KEY_RE.match(key):
        raise HTTPException(404, "profile not found")
    try:
        entry = mp_admin.write_profile(body.profile, label=body.label, existing_key=key)
    except mp_admin.ProfileWriteError as e:
        raise HTTPException(422, {"error": "validation_failed", "errors": e.errors})
    _audit(request, "update", key)
    return {"updated": entry}


@router.delete("/{key}")
def delete_profile(key: str, request: Request):
    _require_writable()
    if not mp_admin._KEY_RE.match(key):
        raise HTTPException(404, "profile not found")
    try:
        mp_admin.delete_profile(key, pinned_by=_catalog_pins_for(key))
    except mp_admin.ProfileWriteError as e:
        # default / pinned / absent → 409 (a content-policy refusal, not bad input)
        raise HTTPException(409, str(e))
    _audit(request, "delete", key)
    return {"deleted": key}


@router.post("/{key}/duplicate")
def duplicate_profile(key: str, body: DuplicateBody, request: Request):
    _require_writable()
    if not mp_admin._KEY_RE.match(key):
        raise HTTPException(404, "source profile not found")
    try:
        clone = mp_admin.duplicate_profile(key, new_key=body.new_key, new_label=body.new_label)
    except mp_admin.ProfileWriteError as e:
        raise HTTPException(409, str(e))
    _audit(request, "duplicate", body.new_key)
    return {"created": {"key": body.new_key}, "profile": clone}
