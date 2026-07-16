"""design_calibration — the CPU-only staleness predicate for the design-axis
calibration record (SPEC_PET_DESIGN_AXES_CALIBRATION §2).

The one knower, three surfaces: the CLI tool (scripts/calibrate_design_axes.py),
the guard test (webui/tests/test_design_axes_calibration.py), and the admin
endpoint (design_admin) all call THESE functions — so "is this cell fresh?" has
exactly one answer no matter who asks.

What it does, all pure-CPU (no GPU, no ComfyUI, never pet_factory.factory):
  - build the EXPECTED matrix from the live registry + matrix.json (every
    non-default option per applicable surface, per representative animal, plus
    each animal's _base baseline and the combo cells);
  - recompute each expected cell's (description, strength) via compose_design +
    effective_strength;
  - diff against the committed manifest → per-cell verdict current/missing/stale.

Strength is a TWO-SOURCE formula (§0.1 / rev.4): base_strength raised by each
picked axis's declared min_strength, THEN max'd with compose_design's returned
min_strength (the colour-word/species conflict — why bluejay/color_only is 0.9
with no picks). effective_strength lives HERE and the render tool imports it, so
a rendered cell and a checked cell can never disagree on strength.

Import discipline (§2, load-bearing): app.py imports design_admin at module top
before compose_design is defined, so `import app` MUST be lazy (inside the
functions), never at module top — otherwise the cycle lands on a
partially-initialized app. design_axes is pure data and safe to import at top.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from pet_factory import design_axes as da

_CALIB_DIR = Path(da.__file__).resolve().parent / "calibration"
_MATRIX_FILE = _CALIB_DIR / "matrix.json"
_MANIFEST_FILE = _CALIB_DIR / "manifest.json"

# Float tolerance for the strength diff — values in play are 0.85 / 0.9 / null,
# exact in the data, but a tolerance keeps a re-serialization from flipping a
# cell stale on a 1e-16 wobble.
_EPS = 1e-6


# ---------------------------------------------------------------------------
# Data access (re-read each call — the guard test and the tool want live disk).
# ---------------------------------------------------------------------------
def load_matrix() -> dict:
    return json.loads(_MATRIX_FILE.read_text())


def load_manifest() -> dict:
    return json.loads(_MANIFEST_FILE.read_text())


# ---------------------------------------------------------------------------
# The strength formula (§0.1 / rev.4) — the ONE definition, imported by the tool.
# ---------------------------------------------------------------------------
def effective_strength(picks: Optional[dict], color: str, species: str) -> float:
    """Replicate /api/preview's clamp exactly: start at base_strength, raise to
    any picked axis's declared min_strength (ignoring default picks), then max
    with compose_design's returned min_strength (the colour-word/species
    conflict), clamped to ≤ 0.9. Pure-CPU."""
    import app  # lazy — see the module docstring
    base = load_matrix()["substrate"]["base_strength"]
    strength = float(base)
    for axis_key, option_key in (picks or {}).items():
        ms = da.axis_composition(axis_key)["min_strength"]
        if ms and not da.is_default(axis_key, option_key):
            strength = max(strength, float(ms))
    # The colour-word/species conflict lives in compose_design, not the axis data.
    _, _, conflict = app.compose_design(species, color, [], picks or {}, "")
    if conflict:
        strength = max(strength, float(conflict))
    return min(0.9, strength)


def compose_cell(species: str, color: str, accessories: list, picks: dict) -> tuple[str, float]:
    """The (description, strength) a cell composes to under the current code —
    the two staleness inputs. compose_design owns the description; effective_
    strength owns the clamp."""
    import app  # lazy
    description, _, _ = app.compose_design(species, color, list(accessories), picks or {}, "")
    return description, effective_strength(picks, color, species)


# ---------------------------------------------------------------------------
# The combo recipes (§3) — lifted VERBATIM from the preserved scratchpad
# scripts (calibration_snapshot_20260716/calibrate_axes.py), because the recipe
# that produced the measurement IS the recipe. A re-derived one that composes
# even one word differently marks every combo cell stale on day one.
# ---------------------------------------------------------------------------
def _first_surface_pick(surface: Optional[str]) -> dict:
    """The animal's first non-default surface option (the scratchpad's
    `first_surface_pick`) — {} for a surfaceless animal (the unknown probe)."""
    axis_key = da.surface_axis_key(surface)
    if not axis_key:
        return {}
    opts = [o for o in (da.public_axis(axis_key) or {}).get("options", [])
            if not o["is_default"]]
    return {axis_key: opts[0]["key"]} if opts else {}


def combo_spec(combo: str, surface: Optional[str]) -> dict:
    """{picks, color, accessories} for a named combo on a given surface."""
    stack_picks = {"pattern": "spotted", "expression": "grumpy", **_first_surface_pick(surface)}
    if combo == "color_only":
        return {"picks": {}, "color": "purple", "accessories": []}
    if combo == "stack":
        return {"picks": stack_picks, "color": "purple", "accessories": ["wizard hat"]}
    if combo == "stack_strong":
        return {"picks": {**stack_picks, "body": "fat"}, "color": "purple",
                "accessories": ["wizard hat"]}
    raise ValueError(f"unknown combo recipe {combo!r}")


# ---------------------------------------------------------------------------
# The expected matrix (§3) — derived from the live registry + matrix.json.
# ---------------------------------------------------------------------------
def _representatives(matrix: dict) -> list[dict]:
    """Every representative + the unknown probe, each as {animal, species,
    surface, base}. A surface in known_surfaces() with no representative is a
    half-formed matrix — the caller (expected_cells) raises."""
    reps = []
    for surface, rep in matrix.get("representatives", {}).items():
        reps.append({"animal": rep["key"], "species": rep["species"],
                     "surface": surface, "base": rep.get("base")})
    probe = matrix.get("unknown_probe")
    if probe:
        reps.append({"animal": probe["key"], "species": probe["species"],
                     "surface": None, "base": probe.get("base")})
    return reps


class MatrixError(ValueError):
    """A surface has no representative (or a representative names an unknown
    surface) — the half-formed-entry rule, applied to calibration."""


def expected_cells(matrix: Optional[dict] = None) -> list[dict]:
    """The full expected matrix: one cell dict per (animal × applicable
    non-default option) + one _base per animal + the combo cells. Each dict is
    everything needed to recompose: {animal, cell, species, surface, picks,
    color, accessories, is_base}.

    Raises MatrixError if known_surfaces() has a surface with no matrix
    representative — the "new surface class needs a representative" reminder."""
    matrix = matrix or load_matrix()
    reps = _representatives(matrix)

    have = {r["surface"] for r in reps if r["surface"]}
    missing = da.known_surfaces() - have
    if missing:
        raise MatrixError(
            f"surface(s) {sorted(missing)} have no representative in matrix.json — "
            f"add one under representatives[] so calibration can measure them")

    cells: list[dict] = []
    for rep in reps:
        animal, species, surface = rep["animal"], rep["species"], rep["surface"]
        # The undesigned baseline (§3): no composition ran, so description is the
        # species verbatim and strength is null — the one place a null is legal.
        cells.append({"animal": animal, "cell": "_base", "species": species,
                      "surface": surface, "picks": {}, "color": "", "accessories": [],
                      "is_base": True})
        # Every non-default option of every axis this animal is offered.
        for axis in da.axes_for_surface(surface):
            for opt in axis["options"]:
                if opt["is_default"]:
                    continue
                cells.append({
                    "animal": animal, "cell": f"{axis['axis']}-{opt['key']}",
                    "species": species, "surface": surface,
                    "picks": {axis["axis"]: opt["key"]},
                    "color": "", "accessories": [], "is_base": False})
        # The combos.
        for combo in matrix.get("combos", []):
            spec = combo_spec(combo, surface)
            cells.append({
                "animal": animal, "cell": f"combo-{combo}", "species": species,
                "surface": surface, "picks": spec["picks"], "color": spec["color"],
                "accessories": spec["accessories"], "is_base": False})
    return cells


# ---------------------------------------------------------------------------
# The staleness predicate (§0.2) — expected vs manifest, per cell.
# ---------------------------------------------------------------------------
def _strength_eq(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(float(a) - float(b)) < _EPS


def check(matrix: Optional[dict] = None, manifest: Optional[dict] = None) -> dict:
    """The whole verdict: per-cell current/missing/stale + the review-stamp
    status. CPU-only. Shape (§6): {reviewed, unreviewed_render_count, all_current,
    cells: [{animal, axis, option, cell, verdict, reason}]}."""
    matrix = matrix or load_matrix()
    manifest = manifest if manifest is not None else load_manifest()
    by_key = {(c["animal"], c["cell"]): c for c in manifest.get("cells", [])}
    reviewed = manifest.get("reviewed")
    reviewed_at = reviewed.get("at") if isinstance(reviewed, dict) else None

    results = []
    unreviewed = 0
    for exp in expected_cells(matrix):
        key = (exp["animal"], exp["cell"])
        axis, option = _split_cell(exp["cell"])
        got = by_key.get(key)
        if got is None:
            results.append({**_ident(exp, axis, option), "verdict": "missing",
                            "reason": "never measured"})
            continue
        if exp["is_base"]:
            exp_desc, exp_strength = exp["species"], None
        else:
            exp_desc, exp_strength = compose_cell(
                exp["species"], exp["color"], exp["accessories"], exp["picks"])
        reasons = []
        if got.get("description") != exp_desc:
            reasons.append(f"description: {got.get('description')!r} → {exp_desc!r}")
        if not _strength_eq(got.get("strength"), exp_strength):
            reasons.append(f"strength: {got.get('strength')} → {exp_strength}")
        verdict = "stale" if reasons else "current"
        if verdict == "current" and reviewed_at and got.get("rendered_at", "") > reviewed_at:
            unreviewed += 1
        results.append({**_ident(exp, axis, option), "verdict": verdict,
                        "reason": "; ".join(reasons)})

    return {
        "reviewed": reviewed,
        "unreviewed_render_count": unreviewed,
        "all_current": all(r["verdict"] == "current" for r in results),
        "cells": results,
    }


def _split_cell(cell: str) -> tuple[Optional[str], Optional[str]]:
    """cell key → (axis, option) for the badge mapping (§6). _base and combos
    carry no axis/option."""
    if cell == "_base" or cell.startswith("combo-"):
        return None, None
    axis, _, option = cell.partition("-")
    return (axis, option) if option else (None, None)


def _ident(exp: dict, axis, option) -> dict:
    return {"animal": exp["animal"], "cell": exp["cell"], "axis": axis, "option": option}
