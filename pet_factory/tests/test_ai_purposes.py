"""Guard tests for the AI purpose registry (SPEC_DATSPET_AI_ENGINE §3, §11).

Same posture as test_design_axes: the admin's validate_purpose IS the definition
of a valid purpose, and this build guard calls THAT function — one rule for the
editor and the build. This file ALSO owns the cross-layer rules 6–7 (§2): a
purpose names a tier, so "the tier resolves to an available model" and "an image
purpose resolves to a vision model" are checked HERE, where both ai_purposes and
ai_models are known — the animal_catalog discipline (cross-layer validity is a
guard test, not a runtime import).

Run:  python3 -m pytest pet_factory/tests/test_ai_purposes.py
"""
import ast
import copy
import json
from pathlib import Path

from pet_factory import ai_models
from pet_factory import ai_purposes as ap
from pet_factory.ai_purposes import admin

_DIR = Path(ap.__file__).resolve().parent

_FORBIDDEN_IMPORTS = {"animal_catalog", "design_axes", "motion_profiles", "tiers", "webui"}
_ML_IMPORTS = {"numpy", "torch", "rembg", "onnxruntime", "cv2", "PIL"}

_VALID_TIERS = ai_models.tier_keys()


def _imported_names(module_file: Path) -> set[str]:
    tree = ast.parse(module_file.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            parts = node.module.split(".")
            names.add(parts[0])
            if parts[0] == "pet_factory":
                names.update(a.name for a in node.names)
    return names


# ── registry ↔ file parity (the half-formed-entry rule) ──────────────────────

def test_registry_and_purpose_files_are_one_to_one():
    registry = json.loads((_DIR / "registry.json").read_text())
    registered = [e["key"] for e in registry.get("purposes", [])]
    assert registered, "registry.json declares no purposes"
    assert len(registered) == len(set(registered)), "duplicate purpose keys"
    for key in registered:
        assert (_DIR / f"{key}.json").is_file(), f"registry names {key!r} but {key}.json is missing"
    on_disk = {p.stem for p in _DIR.glob("*.json")} - {"registry"}
    assert on_disk == set(registered), \
        f"purpose files and registry entries disagree: {on_disk ^ set(registered)}"


# ── validator parity (§0.2 — the load-bearing one) ───────────────────────────

def test_every_shipped_purpose_passes_the_validator():
    registry = admin.load_registry()
    for entry in registry.get("purposes", []):
        raw = json.loads((_DIR / f"{entry['key']}.json").read_text())
        assert raw.get("purpose_key") == entry["key"], \
            f"{entry['key']}.json's purpose_key does not match its registry key"
        errors = admin.validate_purpose(raw, valid_tiers=_VALID_TIERS, existing_key=entry["key"])
        assert errors == [], f"{entry['key']}: validate_purpose reported {errors}"


def test_validator_catches_the_half_formed_entry_classes():
    def errs(mutate):
        raw = json.loads((_DIR / "connectivity_check.json").read_text())
        mutate(raw)
        return admin.validate_purpose(raw, valid_tiers=_VALID_TIERS,
                                      existing_key="connectivity_check")

    assert errs(lambda r: r.__setitem__("purpose_key", "Bad-Key"))
    assert errs(lambda r: r.__setitem__("display_name", ""))
    assert errs(lambda r: r.__setitem__("description", ""))
    assert errs(lambda r: r.__setitem__("tier", "supreme"))          # unknown tier
    assert errs(lambda r: r.__setitem__("max_tokens", 0))            # non-positive
    assert errs(lambda r: r.__setitem__("max_tokens", True))         # bool is not an int here
    assert errs(lambda r: r.__setitem__("input", "audio"))           # bad enum
    assert errs(lambda r: r.__setitem__("system_prompt", ""))        # empty prompt
    assert errs(lambda r: r.__setitem__("is_active", "yes"))         # not a bool
    assert errs(lambda r: r.__delitem__("_doc"))                     # missing rationale
    # An undeclared placeholder — the literal-{hint_clause} class (§11).
    assert errs(lambda r: r.__setitem__("user_prompt_template", "Describe this.{hint_clause}"))


def test_validator_rejects_output_schema_keywords_the_api_ignores():
    """§11 — the one with no DatsMe equivalent: minimum/maximum/minLength/maxLength
    et al. are silently ignored by structured outputs, so a purpose that declares
    one ships a bound the model will not honor. The validator refuses it."""
    def with_schema(schema):
        raw = json.loads((_DIR / "connectivity_check.json").read_text())
        raw["output_schema"] = schema
        return admin.validate_purpose(raw, valid_tiers=_VALID_TIERS,
                                      existing_key="connectivity_check")

    base = {"type": "object", "additionalProperties": False, "required": ["n"],
            "properties": {"n": {"type": "integer"}}}
    assert with_schema(base) == []
    # A numeric bound (the deferred likeness_score 0–100 case) is refused.
    bad = copy.deepcopy(base)
    bad["properties"]["n"] = {"type": "integer", "minimum": 0, "maximum": 100}
    e = with_schema(bad)
    assert any("minimum" in x for x in e) and any("maximum" in x for x in e)
    # A string-length bound is refused.
    bad2 = copy.deepcopy(base)
    bad2["properties"]["n"] = {"type": "string", "maxLength": 20}
    assert any("maxLength" in x for x in with_schema(bad2))
    # An object without additionalProperties:false is refused.
    bad3 = copy.deepcopy(base)
    del bad3["additionalProperties"]
    assert any("additionalProperties" in x for x in with_schema(bad3))


# ── rules 6–7 (§2): cross-layer — the tier resolves, image ⇒ vision ──────────

def test_every_purpose_tier_resolves_to_an_available_model():
    """Rule 6: the tier a purpose names resolves through the catalog to an
    available (non-retired) model. This is why the purpose can carry a tier
    string and not a pinned model id (§3)."""
    for p in ap.list_purposes():
        model = ai_models.resolve(p["tier"])
        assert model["status"] == "available", \
            f"{p['purpose_key']}: tier {p['tier']!r} resolved to a non-available model"


def test_image_purposes_resolve_to_a_vision_model():
    """Rule 7 (DatsPet-specific): a purpose whose input is an image must resolve
    to a model with vision:true — a text-only model is a build error, not a
    runtime surprise."""
    for p in ap.list_purposes():
        if p.get("input") == "image":
            model = ai_models.resolve(p["tier"])
            assert model.get("vision") is True, \
                f"{p['purpose_key']} takes an image but tier {p['tier']!r} → non-vision model"


# ── never-raises resolution ──────────────────────────────────────────────────

def test_get_unknown_purpose_returns_none():
    assert ap.get("no_such_purpose") is None
    assert isinstance(ap.list_purposes(), list) and ap.list_purposes()
    assert "connectivity_check" in ap.keys()


# ── the seam (§11) ───────────────────────────────────────────────────────────

def test_the_engine_retains_its_own_connectivity_check_purpose():
    """§3.1 — connectivity_check is the engine's OWN purpose (it tests the engine),
    so it must always be present for the admin's Test button. Other purposes here
    are CONSUMER contributions (SPEC_UPLOAD_LIKENESS §2.5 adds image_triage +
    pet_likeness); the ENGINE names none of them — that seam is pinned in
    test_ai_engine.py (webui/ai_engine.py holds no purpose-key literal), and
    registry↔file parity is pinned above. So this asserts the invariant that
    survives every consumer contribution, not a frozen count."""
    assert "connectivity_check" in ap.keys()


def test_ai_purposes_imports_no_consumer_or_ml_package():
    """ai_purposes/ imports nothing from animal_catalog, design_axes,
    motion_profiles, tiers, or webui (the seam), and nothing from the ML stack
    (the GPU-less gate) — checked across both module files."""
    for name in ("__init__.py", "admin.py"):
        imported = _imported_names(_DIR / name)
        assert not (imported & _FORBIDDEN_IMPORTS), \
            f"{name} imports forbidden consumer packages: {imported & _FORBIDDEN_IMPORTS}"
        assert not (imported & _ML_IMPORTS), \
            f"{name} imports ML packages: {imported & _ML_IMPORTS}"
