"""Guard tests for the design-axis calibration record
(SPEC_PET_DESIGN_AXES_CALIBRATION §8).

The freshness gate is the CI-enforced reminder: adding an axis, option, or
surface without recalibrating turns the build red with the heal command, exactly
like a half-formed registry entry (§4). Everything here is pure-CPU — the whole
point is that the reminder needs no GPU.
"""
import copy
import importlib
import importlib.util
import json
import os
import sys
import warnings
from pathlib import Path

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WEBUI = os.path.join(REPO, "webui")
for p in (WEBUI, REPO):
    if p not in sys.path:
        sys.path.insert(0, p)


@pytest.fixture(scope="module", autouse=True)
def _app_env(tmp_path_factory):
    """design_calibration recomputes descriptions via a LAZY `import app`
    (§2 import discipline), and importing app runs db.init_db(); point it at a
    throwaway dir so the import is side-effect-free."""
    out = tmp_path_factory.mktemp("calib_app")
    os.environ.setdefault("PETMAKER_OUTPUT_DIR", str(out))
    os.environ.setdefault("PETMAKER_DB_PATH", str(out / "t.db"))
    yield


import design_calibration as dc  # noqa: E402  (after sys.path is set)


# ── the freshness gate (§4) — the reminder itself ────────────────────────────
def test_all_expected_cells_are_current():
    """The committed manifest must measure every expected cell from the CURRENT
    composition. Missing/stale ⇒ fail with the heal command — unless
    DESIGN_CALIBRATION_GATE=warn (the spike-branch escape, §4.1)."""
    result = dc.check()
    bad = [c for c in result["cells"] if c["verdict"] != "current"]
    msg = ("design-axis calibration is stale — "
           f"{len(bad)} cell(s) not current:\n"
           + "\n".join(f"  {c['verdict'].upper()} {c['animal']}/{c['cell']}"
                       f"{(' — ' + c['reason']) if c['reason'] else ''}" for c in bad)
           + "\n  heal: source pet_env.sh && "
             ".venv/bin/python scripts/calibrate_design_axes.py")
    if os.environ.get("DESIGN_CALIBRATION_GATE", "").strip().lower() == "warn":
        if bad:
            warnings.warn(msg)
    else:
        assert not bad, msg


def test_manifest_is_reviewed():
    """A softer companion: the record should be human-reviewed. Not the hard
    gate (a human looking can't be CI-verified, §0.5) — but an unreviewed or
    stale-review manifest is worth surfacing."""
    result = dc.check()
    if result["reviewed"] is None:
        warnings.warn("calibration manifest has never been --mark-reviewed")
    elif result["unreviewed_render_count"]:
        warnings.warn(f"{result['unreviewed_render_count']} cell(s) rendered since "
                      "the last review — re-review and --mark-reviewed")


# ── predicate coverage (§8) ──────────────────────────────────────────────────
def test_expected_matrix_covers_every_option_base_and_combo():
    from pet_factory import design_axes as da

    cells = dc.expected_cells()
    by_animal: dict[str, set] = {}
    for c in cells:
        by_animal.setdefault(c["animal"], set()).add(c["cell"])

    matrix = dc.load_matrix()
    combos = {f"combo-{c}" for c in matrix["combos"]}
    reps = {**{r["key"]: s for s, r in matrix["representatives"].items()},
            matrix["unknown_probe"]["key"]: None}

    for animal, surface in reps.items():
        got = by_animal[animal]
        assert "_base" in got, f"{animal} missing its _base baseline cell"
        assert combos <= got, f"{animal} missing combo cells {combos - got}"
        for axis in da.axes_for_surface(surface):
            for opt in axis["options"]:
                key = f"{axis['axis']}-{opt['key']}"
                if opt["is_default"]:
                    assert key not in got, f"{animal}: default {key} must NOT be a cell"
                else:
                    assert key in got, f"{animal}: missing option cell {key}"


def test_surface_without_a_representative_raises():
    """The half-formed-matrix rule (§0.3): a known surface with no representative
    fails with the add-a-representative message — the 'new surface class'
    reminder, mechanically."""
    matrix = copy.deepcopy(dc.load_matrix())
    matrix["representatives"].pop("scales")     # a surface the registry still has
    with pytest.raises(dc.MatrixError) as ei:
        dc.expected_cells(matrix)
    assert "scales" in str(ei.value) and "representative" in str(ei.value)


# ── the staleness predicate detects the two failure classes ──────────────────
def test_a_changed_description_reads_stale():
    matrix = dc.load_matrix()
    manifest = copy.deepcopy(dc.load_manifest())
    victim = next(c for c in manifest["cells"] if c["cell"] == "pattern-spotted")
    victim["description"] = "something the current code would never compose"
    result = dc.check(matrix, manifest)
    verdict = next(c for c in result["cells"]
                   if (c["animal"], c["cell"]) == (victim["animal"], "pattern-spotted"))
    assert verdict["verdict"] == "stale" and "description" in verdict["reason"]


def test_a_removed_manifest_entry_reads_missing():
    matrix = dc.load_matrix()
    manifest = copy.deepcopy(dc.load_manifest())
    manifest["cells"] = [c for c in manifest["cells"]
                         if not (c["animal"] == "tabby" and c["cell"] == "coat-fluffy")]
    result = dc.check(matrix, manifest)
    verdict = next(c for c in result["cells"]
                   if (c["animal"], c["cell"]) == ("tabby", "coat-fluffy"))
    assert verdict["verdict"] == "missing"


# ── the two-source strength formula (§0.1 / rev.4) ───────────────────────────
def test_effective_strength_includes_the_colorword_conflict():
    """The bug rev.4 exists to prevent: getting only the axis half. "blue" in
    "blue jay" fights the recolor, so color_only is 0.9 with NO picks — a
    predicate that missed this would mark bluejay/color_only perpetually stale."""
    assert dc.effective_strength({}, "purple", "blue jay") == 0.9
    assert dc.effective_strength({}, "purple", "tabby") == 0.85       # no conflict
    assert dc.effective_strength({"coat": "fluffy"}, "", "tabby") == 0.9  # axis min_strength
    assert dc.effective_strength({"pattern": "spotted"}, "", "tabby") == 0.85  # null min


def test_render_tool_shares_the_predicate_strength_function():
    """Parity: the render tool computes strength through the SAME
    effective_strength (§8), so a rendered cell and a checked cell can't
    disagree. Asserted by identity of the imported symbol."""
    spec = importlib.util.spec_from_file_location(
        "calibrate_design_axes_toolcheck",
        os.path.join(REPO, "scripts", "calibrate_design_axes.py"))
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    assert tool.dc.effective_strength is dc.effective_strength


# ── manifest schema (§8) ─────────────────────────────────────────────────────
def test_manifest_schema_is_well_formed():
    manifest = dc.load_manifest()
    sub = manifest["substrate"]
    for field in ("seed", "base_strength", "zimage_unet"):
        assert field in sub, f"substrate header missing {field}"
    assert sub["zimage_unet"] == dc.load_matrix()["substrate"]["zimage_unet"], \
        "manifest substrate model must match matrix.json's declaration"
    for c in manifest["cells"]:
        ref = f"{c['animal']}/{c['cell']}"
        for field in ("description", "picks", "color", "accessories", "rendered_at"):
            assert field in c, f"{ref} missing {field}"
        assert "strength" in c, f"{ref} missing strength"
        # A null strength is legal ONLY on a truly undesigned cell (§3).
        if c["strength"] is None:
            assert not c["picks"] and not c["color"] and not c["accessories"], \
                f"{ref} has null strength but is a designed cell — half-formed"
        assert c["rendered_at"].endswith("Z"), f"{ref} rendered_at is not UTC-Z"


# ── purity (§8): CPU-only, never the ML factory ──────────────────────────────
def test_predicate_never_imports_the_ml_factory(monkeypatch):
    """The CPU-only guarantee the guard test's whole value rests on: computing
    freshness must never drag in pet_factory.factory (numpy/PIL/rembg/ComfyUI),
    not even to read a model constant — the expected model comes from
    matrix.json. Mirrors test_pool_mode_never_imports_the_ml_factory."""
    monkeypatch.delitem(sys.modules, "pet_factory.factory", raising=False)

    class _Poison:
        def find_spec(self, name, path=None, target=None):
            if name == "pet_factory.factory":
                raise AssertionError(
                    "design_calibration imported the ML factory — CPU-only violation")

    monkeypatch.setattr(sys, "meta_path", [_Poison()] + sys.meta_path)
    importlib.reload(dc)
    dc.check()                       # the full predicate path
    dc.effective_strength({"coat": "fluffy"}, "purple", "blue jay")
    assert "pet_factory.factory" not in sys.modules
