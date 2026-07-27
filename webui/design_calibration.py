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

# The denoise band a design redraw is held inside. The CAP is calibrated (above 0.9
# the redraw stops resembling the source at all); the FLOOR is what keeps a redraw
# from being a no-op that returns the base image and reads as "the design did
# nothing". `_base_sprite` clamps the same band on the engine side.
MIN_DENOISE = 0.3
MAX_DENOISE = 0.9


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
def effective_strength(picks: Optional[dict], color: str, species: str,
                       base_strength: Optional[float] = None) -> float:
    """THE denoise a design redraw runs at: start at base_strength, raise it by
    compose_design's returned min_strength, and hold the result inside
    [MIN_DENOISE, MAX_DENOISE]. Pure-CPU, and the only copy of that arithmetic —
    /api/preview and the Motion Lab both call it (SPEC_MOTION_LAB_DESIGN_PARITY
    I4/I11).

    compose_design's min_strength ALREADY folds every non-default picked axis's
    declared min_strength (it maxes them as it composes, skipping default picks)
    AND the colour-word/species conflict — so ONE max covers both. An earlier
    version also looped the picked axes here to re-derive the axis half; that
    duplicated compose_design's own folding (Finding 4e) and is gone.

    The FLOOR is part of the formula, not the caller's business (I11). Both
    surfaces used to clamp `min(0.9, max(0.3, s))` inline while this function
    stopped at the cap — because its only callers passed the calibration
    substrate (0.85) and never a number a user chose. Adopting it as "the one
    knower" without moving the floor in would have deleted the lower bound from
    both surfaces at once, in a refactor whose whole purpose was to have one.

    `base_strength` overrides the disk matrix's value — the caller (check) passes
    the matrix it was handed, so a test can vary the substrate as an ARGUMENT
    without writing to disk (Finding 3); None falls back to the disk matrix."""
    import app  # lazy — see the module docstring
    base = base_strength if base_strength is not None else load_matrix()["substrate"]["base_strength"]
    _, _, conflict = app.compose_design(species, color, [], picks or {}, "")
    strength = float(base)
    if conflict:
        strength = max(strength, float(conflict))
    return min(MAX_DENOISE, max(MIN_DENOISE, strength))


def compose_cell(species: str, color: str, accessories: list, picks: dict,
                 base_strength: Optional[float] = None) -> tuple[str, float]:
    """The (description, strength) a cell composes to under the current code —
    the two staleness inputs. compose_design owns the description; effective_
    strength owns the clamp. `base_strength` threads the caller's matrix through
    (Finding 3) rather than re-reading disk."""
    import app  # lazy
    description, _, _ = app.compose_design(species, color, list(accessories), picks or {}, "")
    return description, effective_strength(picks, color, species, base_strength)


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
        animal, species, surface, base = rep["animal"], rep["species"], rep["surface"], rep["base"]
        # `base` rides on EVERY cell (Finding 1): the render tool reads it off the
        # cell dict to choose the baseline (a curated catalog copy vs a txt2img
        # archetype). Dropping it here made the tool's `catalog:` branch dead code,
        # so a --full/fresh heal would txt2img the tabby base instead of the vetted
        # one — invisible to the predicate (a _base composes to species/null either
        # way), but it changes what the fur row MEASURES against.
        # The undesigned baseline (§3): no composition ran, so description is the
        # species verbatim and strength is null — the one place a null is legal.
        cells.append({"animal": animal, "cell": "_base", "species": species,
                      "surface": surface, "base": base, "picks": {}, "color": "",
                      "accessories": [], "is_base": True})
        # Every non-default option of every axis this animal is offered.
        for axis in da.axes_for_surface(surface):
            for opt in axis["options"]:
                if opt["is_default"]:
                    continue
                cells.append({
                    "animal": animal, "cell": f"{axis['axis']}-{opt['key']}",
                    "species": species, "surface": surface, "base": base,
                    "picks": {axis["axis"]: opt["key"]},
                    "color": "", "accessories": [], "is_base": False})
        # The combos.
        for combo in matrix.get("combos", []):
            spec = combo_spec(combo, surface)
            cells.append({
                "animal": animal, "cell": f"combo-{combo}", "species": species,
                "surface": surface, "base": base, "picks": spec["picks"],
                "color": spec["color"], "accessories": spec["accessories"],
                "is_base": False})
    return cells


# ---------------------------------------------------------------------------
# The staleness predicate (§0.2) — expected vs manifest, per cell.
# ---------------------------------------------------------------------------
def _strength_eq(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(float(a) - float(b)) < _EPS


_SUBSTRATE_FIELDS = ("seed", "base_strength", "zimage_unet")


def substrate_mismatch(manifest: dict, matrix: dict) -> list[str]:
    """Field-by-field diff of the manifest's substrate header against
    matrix.json's declaration (Finding 2). Non-empty ⇒ the record was measured
    on a different substrate; spec §1 says that stales EVERYTHING, and — unlike
    the render-tool's live-model check — it is CPU-detectable, so the predicate,
    the guard test, and the admin badge all see it here (one knower)."""
    header = manifest.get("substrate", {}) or {}
    decl = matrix.get("substrate", {}) or {}
    return [f"{f} {header.get(f)} → {decl.get(f)}"
            for f in _SUBSTRATE_FIELDS if header.get(f) != decl.get(f)]


def check(matrix: Optional[dict] = None, manifest: Optional[dict] = None) -> dict:
    """The whole verdict: per-cell current/missing/stale + orphans + the
    substrate/review status. CPU-only. Shape (§6): {reviewed,
    unreviewed_render_count, all_current, substrate_mismatch, orphans,
    cells: [{animal, axis, option, cell, verdict, reason}]}."""
    matrix = matrix or load_matrix()
    manifest = manifest if manifest is not None else load_manifest()
    by_key = {(c["animal"], c["cell"]): c for c in manifest.get("cells", [])}
    reviewed = manifest.get("reviewed")
    reviewed_at = reviewed.get("at") if isinstance(reviewed, dict) else None
    base_strength = matrix.get("substrate", {}).get("base_strength")

    # A substrate change stales every measured cell at once (§1). It reads from
    # the passed matrix, so a caller can vary the substrate as an argument.
    sub_diffs = substrate_mismatch(manifest, matrix)
    sub_reason = f"substrate changed: {'; '.join(sub_diffs)}" if sub_diffs else ""

    results = []
    expected_keys = set()
    unreviewed = 0
    for exp in expected_cells(matrix):
        key = (exp["animal"], exp["cell"])
        expected_keys.add(key)
        axis, option = _split_cell(exp["cell"])
        got = by_key.get(key)
        if got is None:
            results.append({**_ident(exp, axis, option), "verdict": "missing",
                            "reason": "never measured"})
            continue
        if sub_diffs:
            # The whole record was measured on a different substrate — every
            # present cell is stale regardless of its recomposed values.
            results.append({**_ident(exp, axis, option), "verdict": "stale",
                            "reason": sub_reason})
            continue
        if exp["is_base"]:
            exp_desc, exp_strength = exp["species"], None
        else:
            exp_desc, exp_strength = compose_cell(
                exp["species"], exp["color"], exp["accessories"], exp["picks"],
                base_strength)
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

    # Orphans (Finding 4a): manifest entries with no expected cell — a removed
    # option/axis leaves dead weight (+ a zombie in the sheet). Reported as
    # cleanup advice; NOT counted against freshness (removing a control is a
    # valid edit, not a stale measurement). cmd_render prunes them.
    orphans = [{"animal": c["animal"], "cell": c["cell"]}
               for c in manifest.get("cells", [])
               if (c["animal"], c["cell"]) not in expected_keys]

    return {
        "reviewed": reviewed,
        "unreviewed_render_count": unreviewed,
        "substrate_mismatch": sub_diffs,
        "orphans": orphans,
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
