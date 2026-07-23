"""Guard tests for the AI model catalog (SPEC_DATSPET_AI_ENGINE §2, §11).

Same posture as test_tiers / test_design_axes: the catalog is content, and these
are the tests that fail the build on a half-formed entry so an author can't ship
one. Rules 1–5 (§2) live in the shared validator `validate_catalog`, which the
loader ALSO calls — one definition of "valid" for the build and the runtime, so
they can never drift. (Rules 6–7 are cross-layer — they need to know the purposes
— and live in test_ai_purposes.py, which is where purposes are known.)

Run:  python3 -m pytest pet_factory/tests/test_ai_models.py
"""
import ast
import copy
import json
from pathlib import Path

import pytest

from pet_factory import ai_models as m

_DIR = Path(m.__file__).resolve().parent

# The five packages the engine must never import (§0.1 / §11 — dependency
# direction is one-way: a consumer imports the engine, never the reverse).
_FORBIDDEN_IMPORTS = {"animal_catalog", "design_axes", "motion_profiles", "tiers", "webui"}


def _imported_names(module_file: Path) -> set[str]:
    """The top-level module names an import statement pulls in — the ACTUAL
    imports, so a package named in a docstring or a string doesn't trip the
    seam check."""
    tree = ast.parse(module_file.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            parts = node.module.split(".")
            names.add(parts[0])
            # `from pet_factory import tiers` imports `tiers` as a name too.
            if parts[0] == "pet_factory":
                names.update(a.name for a in node.names)
    return names


def _catalog():
    return json.loads((_DIR / "catalog.json").read_text())


# ── the shipped catalog is valid, both ways ──────────────────────────────────

def test_shipped_catalog_loads_and_passes_the_validator():
    """The loader validates on first read; a malformed catalog would raise
    CatalogError here. And the validator — the same function the loader calls —
    reports no errors on the shipped file (parity: build rule == runtime rule)."""
    data = m.load_catalog()
    assert data["models"], "no models declared"
    assert m.validate_catalog(_catalog()) == []


def test_content_file_carries_its_rationale():
    """The GPU-less gate in miniature (CLAUDE.md): pure stdlib-parseable content,
    and — like the other registries — it carries its own _doc."""
    assert _catalog().get("_doc"), "content files carry their own rationale"


# ── rule 1: ids unique; provider / tier / status in their closed sets ────────

def test_ids_unique_and_fields_in_closed_sets():
    seen = set()
    for entry in m.list_models():
        mid = entry["id"]
        assert mid not in seen, f"duplicate id {mid}"
        seen.add(mid)
        assert entry["provider"] in m.PROVIDERS
        assert entry["tier"] in m.TIERS
        assert entry["status"] in m.STATUSES
        assert isinstance(entry["vision"], bool)


# ── rule 2: only available models may be a tier default ──────────────────────

def test_only_available_models_are_tier_defaults():
    for entry in m.list_models():
        if entry.get("default_for_tiers"):
            assert entry["status"] == "available", \
                f"{entry['id']} is a tier default but not available"


# ── rule 3: every tier has exactly one available default → resolve is total ──

def test_every_tier_resolves_to_exactly_one_available_model():
    for tier in m.TIERS:
        resolved = m.resolve(tier)
        assert resolved["status"] == "available"
        assert tier in resolved["default_for_tiers"]
    # The spec's §4 tier defaults, pinned so re-pointing one is a deliberate edit.
    assert m.resolve("fast")["id"] == "claude-haiku-4-5"
    assert m.resolve("balanced")["id"] == "claude-sonnet-5"
    assert m.resolve("capable")["id"] == "claude-opus-4-8"


# ── rule 5: every entry prices (a usage row must always price) ───────────────

def test_every_model_has_positive_costs():
    for entry in m.list_models():
        cost = entry["cost_per_mtok"]
        assert cost["input"] > 0 and cost["output"] > 0, f"{entry['id']}: non-positive cost"


def test_price_is_derived_from_cost_per_mtok():
    # Opus 4.8: $5/MTok in, $25/MTok out. 1M in + 1M out = $5 + $25 = $30.
    assert m.price("claude-opus-4-8", 1_000_000, 1_000_000) == pytest.approx(30.0)
    # Haiku: $1/$5. 200k in, 100k out = 0.2*1 + 0.1*5 = 0.7.
    assert m.price("claude-haiku-4-5", 200_000, 100_000) == pytest.approx(0.7)
    # A model absent from the catalog degrades to unpriced, never raises (§5).
    assert m.price("claude-since-removed", 1_000, 1_000) == 0.0


def test_entry_lookup():
    assert m.entry("claude-sonnet-5")["label"] == "Claude Sonnet 5"
    assert m.entry("no-such-model") is None


# ── the validator actually FAILS the failure classes (rules 1–5) ─────────────

def test_validator_catches_the_half_formed_entry_classes():
    """A validator that passed everything would green the parity test above while
    guarding nothing — so pin that each mutation is caught."""
    def errs(mutate):
        data = copy.deepcopy(_catalog())
        mutate(data)
        return m.validate_catalog(data)

    # rule 1
    assert errs(lambda d: d["models"][0].__setitem__("id", d["models"][1]["id"]))  # dup id
    assert errs(lambda d: d["models"][0].__setitem__("provider", "acme"))
    assert errs(lambda d: d["models"][0].__setitem__("tier", "supreme"))
    assert errs(lambda d: d["models"][0].__setitem__("status", "cooking"))
    # rule 5
    assert errs(lambda d: d["models"][0]["cost_per_mtok"].__setitem__("input", 0))
    assert errs(lambda d: d["models"][0].__delitem__("cost_per_mtok"))
    # rule 2 — a non-available model claiming a tier default
    assert errs(lambda d: d["models"][0].__setitem__("status", "deprecated"))
    # rule 3 — remove a tier's only default → that tier no longer resolves
    assert errs(lambda d: d["models"][2].__setitem__("default_for_tiers", []))
    # rule 3 — two models claiming the same tier default
    assert errs(lambda d: d["models"][1].__setitem__("default_for_tiers", ["fast", "balanced"]))


def test_validator_requires_replacement_id_for_deprecated_and_retired():
    """rule 4 — a deprecated/retired model MUST carry a replacement_id that
    resolves, so historical usage rows can point at a live successor."""
    data = copy.deepcopy(_catalog())
    # Add a fresh available model to keep every tier's default intact, then
    # deprecate one of the originals WITHOUT a replacement_id.
    data["models"].append({
        "id": "claude-opus-4-8b", "label": "x", "provider": "anthropic",
        "tier": "capable", "status": "available", "vision": True,
        "cost_per_mtok": {"input": 5.0, "output": 25.0},
        "default_for_tiers": ["capable"],
    })
    data["models"][0]["status"] = "deprecated"
    data["models"][0]["default_for_tiers"] = []
    assert any("replacement_id" in e for e in m.validate_catalog(data))
    # With a replacement_id that resolves, it validates.
    data["models"][0]["replacement_id"] = "claude-opus-4-8b"
    assert m.validate_catalog(data) == []
    # A replacement_id that names no model fails.
    data["models"][0]["replacement_id"] = "ghost"
    assert any("names no model" in e for e in m.validate_catalog(data))


# ── the seam (§11): the engine imports nothing from a consumer ───────────────

def test_ai_models_imports_no_consumer_package():
    """ai_models/ must IMPORT nothing from animal_catalog, design_axes,
    motion_profiles, tiers, or webui — a back-import is the boundary dissolving
    (§0.1). Prose in the docstring may name them; imports may not."""
    leaked = _imported_names(_DIR / "__init__.py") & _FORBIDDEN_IMPORTS
    assert not leaked, f"ai_models imports forbidden consumer packages: {leaked}"
