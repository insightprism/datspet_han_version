"""design_admin — the DatsPet admin API for the design vocabulary + per-animal
design profiles.

SPEC_PET_DESIGN_AXES_ADMIN §2. An APIRouter, every endpoint gated by
require_admin_launch (the adm-claim cookie). Thin over the two pure-data write
paths (pet_factory.design_axes.admin for the vocabulary,
pet_factory.animal_catalog.admin for the per-animal profile); this layer only
does HTTP shaping, the surface-axis delete guard, the writability gate, and the
audit line — deliberately the motion admin, applied to design.

The validators (design_axes.admin.validate_axis,
animal_catalog.admin.validate_design_profile) are the single definitions of
"valid" — shared with the guard tests — so the admin can never write what the
build would reject (§0.2).
"""
from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict

import admin_common
import datsme_integration
from pet_factory import animal_catalog as animal_catalog_mod
from pet_factory import design_axes as da
from pet_factory.animal_catalog import admin as cat_admin
from pet_factory.design_axes import admin as da_admin

router = APIRouter(
    prefix="/api/admin/design",
    dependencies=[Depends(datsme_integration.require_admin_launch)],
)


def _writable() -> bool:
    return admin_common.writable(da._DIR, "DESIGN_ADMIN_WRITABLE")


def _require_writable() -> None:
    admin_common.require_writable(_writable(), "DESIGN_ADMIN_WRITABLE", "design axes")


def _audit(request: Request, op: str, what: str) -> None:
    admin_common.audit("design-admin", request, op, what)


# ---------------------------------------------------------------------------
# "Used by" (§2) — the design analog of motion's catalog-pin map, and the
# rev.2 delete guard's evidence: every surface axis → the catalog references
# whose RESOLVED surface maps to it, in one catalog walk.
# ---------------------------------------------------------------------------
def _axis_used_by_map() -> dict[str, list[str]]:
    used: dict[str, set[str]] = {}
    for a in animal_catalog_mod.list_animals():
        akey = a["key"]
        for ref, surface in (
            (akey, a.get("surface")),
            *((f"{akey}/{b['key']}",
               animal_catalog_mod.resolved_surface(akey, b["key"]))
              for b in a.get("breeds", [])),
        ):
            axis_key = da.surface_axis_key(surface)
            if axis_key:
                used.setdefault(axis_key, set()).add(ref)
    return {k: sorted(v) for k, v in used.items()}


def _used_by(axis_key: str) -> list[str]:
    return _axis_used_by_map().get(axis_key, [])


class AxisBody(BaseModel):
    axis: dict  # the full <key>.json content (label lives inside it)


class DesignProfileBody(BaseModel):
    # extra="forbid" IS the HTTP face of the allowed-field guard (§0.5): a body
    # carrying base_png / motion_profile / any unknown key is refused at parse,
    # before the write path is even reached.
    model_config = ConfigDict(extra="forbid")
    surface: Optional[str] = None
    surface_default: Optional[str] = None
    surface_options: Optional[list[str]] = None


# ---------------------------------------------------------------------------
# Axes — the vocabulary (§2 "Features"). Reads always work.
# ---------------------------------------------------------------------------
@router.get("/axes")
def list_axes():
    """Registry + a summary of every axis, in MENU ORDER (drives the list pane)."""
    registry = da_admin.load_registry()
    used_map = _axis_used_by_map()
    axes = []
    for entry in registry.get("axes", []):
        raw = json.loads((da._DIR / f"{entry['key']}.json").read_text())
        axes.append({
            "key": raw["axis"],
            "label": raw.get("label", raw["axis"]),
            "kind": raw.get("kind", "universal"),
            "applies_to": raw.get("applies_to"),
            "default": raw.get("default", ""),
            "option_count": len(raw.get("options", [])),
            "clause_slot": raw.get("clause_slot"),
            "position": raw.get("position"),
            "min_strength": raw.get("min_strength"),
            "used_by": used_map.get(raw["axis"], []),
        })
    return {"writable": _writable(),
            "max_concurrent_strong": registry.get("max_concurrent_strong"),
            "axes": axes}


@router.get("/calibration-status")
def calibration_status():
    """The design-axis freshness verdicts (SPEC_PET_DESIGN_AXES_CALIBRATION §6),
    so the Features tab can badge options that need recalibration. Read-only and
    CPU-only on any instance — prod displays status, it never renders.

    Imports design_calibration LAZILY (§2 import discipline): this router is
    imported by app.py before compose_design is defined, so a module-top import
    would land on a partially-initialized app. Degrades to an empty verdict set
    if the calibration record is absent (a fresh checkout before Phase 0) rather
    than 500-ing the admin list."""
    import design_calibration
    try:
        result = design_calibration.check()
    except (FileNotFoundError, design_calibration.MatrixError) as e:
        return {"available": False, "reason": str(e), "reviewed": None,
                "unreviewed_render_count": 0, "cells": []}
    return {"available": True, **result}


@router.get("/axes/{key}")
def get_axis(key: str):
    """One axis's full JSON (the edit form's source — fragments included; this
    surface is the gated place calibrated wording IS the business)."""
    if not da_admin._KEY_RE.match(key):
        raise HTTPException(404, "axis not found")
    registry = da_admin.load_registry()
    if key not in {e["key"] for e in registry.get("axes", [])}:
        raise HTTPException(404, "axis not found")
    raw = json.loads((da._DIR / f"{key}.json").read_text())
    return {"axis": raw, "used_by": _used_by(key), "writable": _writable()}


@router.post("/axes")
def create_axis(body: AxisBody, request: Request):
    _require_writable()
    try:
        entry = da_admin.write_axis(body.axis, existing_key=None)
    except da_admin.AxisWriteError as e:
        raise HTTPException(422, {"error": "validation_failed", "errors": e.errors})
    _audit(request, "wrote", f"axis {entry['key']!r}")
    return {"created": entry}


@router.put("/axes/{key}")
def update_axis(key: str, body: AxisBody, request: Request):
    _require_writable()
    if not da_admin._KEY_RE.match(key):
        raise HTTPException(404, "axis not found")
    try:
        entry = da_admin.write_axis(body.axis, existing_key=key)
    except da_admin.AxisWriteError as e:
        raise HTTPException(422, {"error": "validation_failed", "errors": e.errors})
    _audit(request, "wrote", f"axis {key!r}")
    return {"updated": entry}


@router.delete("/axes/{key}")
def delete_axis(key: str, request: Request):
    """Delete an axis. The rev.2 guard (§0.2 applied to deletes): a surface axis
    still referenced by any catalog entry's resolved surface refuses with 409
    naming the blockers — deleting plumage while a bird tags feathers would
    create exactly the state the build guard rejects."""
    _require_writable()
    if not da_admin._KEY_RE.match(key):
        raise HTTPException(404, "axis not found")
    try:
        da_admin.delete_axis(key, used_by=_used_by(key))
    except da_admin.AxisWriteError as e:
        # absent / still-referenced → 409 (a content-policy refusal, not bad input)
        raise HTTPException(409, str(e))
    _audit(request, "deleted", f"axis {key!r}")
    return {"deleted": key}


# ---------------------------------------------------------------------------
# Animals — the per-animal design profile (§3.2 "Animals"). The tab writes the
# classification; the design step reads it.
# ---------------------------------------------------------------------------
@router.get("/animals")
def list_animal_profiles():
    """The animal/breed tree with each entry's authored + resolved design
    profile, plus the surface vocabulary the dropdowns offer."""
    animals = []
    for a in animal_catalog_mod.list_animals():
        akey = a["key"]
        animals.append({
            "key": akey,
            "label": a.get("label", akey),
            "surface": a.get("surface"),
            "surface_default": a.get("surface_default"),
            "surface_options": a.get("surface_options"),
            "breeds": [{
                "key": b["key"],
                "label": b.get("label", b["key"]),
                "surface": b.get("surface"),
                "surface_default": b.get("surface_default"),
                "surface_options": b.get("surface_options"),
                "resolved_surface": animal_catalog_mod.resolved_surface(akey, b["key"]),
            } for b in a.get("breeds", [])],
        })
    surfaces = sorted(da.known_surfaces())
    return {
        "writable": _writable(),
        "surfaces": surfaces,
        # Every surface's option vocabulary, so the tab's dropdowns need no
        # second round trip. Admin-gated, so labels+keys are fine to hand over.
        "surface_axis_options": {
            s: (da.public_axis(da.surface_axis_key(s)) or {}).get("options", [])
            for s in surfaces
        },
        "animals": animals,
    }


@router.put("/animals/{animal_key}")
@router.put("/animals/{animal_key}/{breed_key}")
def set_animal_profile(animal_key: str, body: DesignProfileBody, request: Request,
                       breed_key: Optional[str] = None):
    _require_writable()
    try:
        profile = cat_admin.set_design_profile(
            animal_key, breed_key,
            surface=body.surface,
            surface_default=body.surface_default,
            surface_options=body.surface_options,
        )
    except cat_admin.CatalogWriteError as e:
        if len(e.errors) == 1 and "not in the catalog" in e.errors[0]:
            raise HTTPException(404, e.errors[0])
        raise HTTPException(422, {"error": "validation_failed", "errors": e.errors})
    ref = f"{animal_key}/{breed_key}" if breed_key else animal_key
    _audit(request, "wrote", f"design profile for {ref!r}")
    return {"updated": ref, "profile": profile}
