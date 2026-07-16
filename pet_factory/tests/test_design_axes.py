"""Guard tests for the design-axis registry (SPEC_PET_DESIGN_AXES §10).

Replaces test_body_shapes.py: the body axis migrated into this registry
(Phase 0), and every invariant it pinned is generalized here across all axes.
Same posture as test_tiers / test_motion_profiles: the data is content, and
these are the tests that fail the build on a half-formed entry so an author
can't ship one.
"""
import json
from pathlib import Path

import pytest

from pet_factory import design_axes as da

_DIR = Path(da.__file__).resolve().parent

VALID_KINDS = {"universal", "surface"}
VALID_POSITIONS = {"prefix", "suffix"}


def _axis_keys():
    return da._load()["order"]


def _axes():
    return [da._load()["axes"][k] for k in _axis_keys()]


# ── registry ↔ file parity (the half-formed-entry rule, §1) ──────────────────

def test_registry_and_axis_files_are_one_to_one():
    """A registry entry without its file, or an axis file without its entry,
    fails the build — the runtime skips silently (never-raises), so THIS is
    where a half-formed entry dies."""
    registry = json.loads((_DIR / "registry.json").read_text())
    registered = [e["key"] for e in registry.get("axes", [])]
    assert registered, "registry.json declares no axes"
    assert len(registered) == len(set(registered)), "duplicate axis keys in registry"
    for key in registered:
        assert (_DIR / f"{key}.json").is_file(), \
            f"registry names {key!r} but {key}.json is missing"
    on_disk = {p.stem for p in _DIR.glob("*.json")} - {"registry", "surface_keywords"}
    assert on_disk == set(registered), \
        f"axis files and registry entries disagree: {on_disk ^ set(registered)}"


# ── validator parity (SPEC_PET_DESIGN_AXES_ADMIN §0.2/§8 — the load-bearing one)

def test_every_shipped_axis_passes_the_admin_validator():
    """The admin's validate_axis IS the definition of a valid axis, and this
    build guard calls THAT function — one rule for the editor and the build,
    so they can never drift. Everything the per-field tests used to assert
    inline (fully-formed axis, one default, empty default fragment, no dead
    options, applies_to uniqueness) lives in the validator now."""
    from pet_factory.design_axes import admin

    registry = admin.load_registry()
    for entry in registry.get("axes", []):
        raw = json.loads((_DIR / f"{entry['key']}.json").read_text())
        assert raw.get("axis") == entry["key"], \
            f"{entry['key']}.json's axis field does not match its registry key"
        errors = admin.validate_axis(raw, registry=registry, existing_key=entry["key"])
        assert errors == [], f"{entry['key']}: validate_axis reported {errors}"


def test_validator_catches_the_half_formed_entry_classes():
    """The validator must actually FAIL the failure classes the old inline
    tests covered — a validator that passes everything would green the parity
    test above while guarding nothing."""
    from pet_factory.design_axes import admin

    registry = admin.load_registry()

    def errs(mutate):
        raw = json.loads((_DIR / "pattern.json").read_text())
        mutate(raw)
        return admin.validate_axis(raw, registry=registry, existing_key="pattern")

    assert errs(lambda r: r.__setitem__("kind", "vibes"))
    assert errs(lambda r: r.__setitem__("position", "middle"))
    assert errs(lambda r: r.__setitem__("clause_slot", "twenty"))
    assert errs(lambda r: r.__setitem__("default", "no_such_option"))
    assert errs(lambda r: r["options"][0].__setitem__("prompt_fragment", "sneaky words"))  # default gains words
    assert errs(lambda r: r["options"][1].__setitem__("prompt_fragment", ""))  # dead control
    assert errs(lambda r: r.__setitem__("min_strength", 1.5))  # unreachable clamp
    assert errs(lambda r: r.__setitem__("applies_to", "fur"))  # universal claiming a surface
    # A second axis claiming an already-served surface:
    def claim_feathers(r):
        r["kind"] = "surface"
        r["applies_to"] = "feathers"
    assert errs(claim_feathers)


def test_default_fragment_is_exactly_empty():
    """The one invariant that carries meaning: a default must contribute NO
    words. If it ever gained a fragment, the design string for a user who
    touched nothing would stop matching the string for a user who never saw
    the control. The default is the absence of a choice; it must read as the
    absence of words."""
    for key in _axis_keys():
        assert da.prompt_fragment(key, da.default_key(key)) == "", \
            f"{key}: the default option must have fragment exactly \"\""


def test_non_default_options_actually_contribute_words():
    """The mirror invariant, and §12 Tier C's build-time face: an option that
    isn't the default MUST carry a fragment, or the control is a dead control
    the user can still click — the bug class users report."""
    for key in _axis_keys():
        non_default = [o for o in da._axis(key)["options"]
                       if o["key"] != da.default_key(key)]
        assert non_default, f"{key}: a vocabulary with only a default is not a vocabulary"
        for o in non_default:
            assert o["prompt_fragment"], \
                f"{key}/{o['key']} is selectable but changes nothing"
            assert da.is_default(key, o["key"]) is False


@pytest.mark.parametrize("option_key", ["nonsense", "", None, "NORMAL"])
def test_unknown_option_keys_resolve_rather_than_raise(option_key):
    """Never-raises, like motion-profile resolution: a typo degrades to "no
    change", it does not 500 a design. "NORMAL" pins case-sensitivity."""
    for key in _axis_keys():
        assert da.prompt_fragment(key, option_key) == ""
        assert da.is_default(key, option_key) is True


def test_unknown_axis_keys_resolve_rather_than_raise():
    assert da.prompt_fragment("no_such_axis", "anything") == ""
    assert da.is_default("no_such_axis", "anything") is True
    assert da.default_key("no_such_axis") == ""
    assert da.public_axis("no_such_axis") is None
    comp = da.axis_composition("no_such_axis")
    assert comp["min_strength"] is None


# ── the public shapes (§4: fragments withheld from the browser) ──────────────

def test_public_shapes_never_leak_prompt_wording():
    """prompt_fragment is calibrated server-side content and must not reach the
    browser — the same posture as the tier table. Leaking it invites a client
    to compose its own prompt, which is how the server stops being
    authoritative."""
    for surface in (None, *sorted(da.known_surfaces())):
        for axis in da.axes_for_surface(surface):
            assert set(axis) == {"axis", "label", "kind", "default", "options"}
            for o in axis["options"]:
                assert set(o) == {"key", "label", "is_default"}
            assert sum(1 for o in axis["options"] if o["is_default"]) == 1
    for axis in da.list_axes():
        for o in axis["options"]:
            assert set(o) == {"key", "label", "is_default"}


# ── surface gating (§0.3 / §3.3 / §4) ────────────────────────────────────────

def test_exactly_one_surface_axis_per_surface():
    """Two axes claiming the same applies_to would make axes_for_surface
    ambiguous — 'exactly one shows' is the §0.3 contract."""
    claimed = [a["applies_to"] for a in _axes() if a["kind"] == "surface"]
    assert len(claimed) == len(set(claimed)), f"duplicate applies_to among {claimed}"
    assert claimed, "no surface axes — the animal-awareness has nothing to gate"


def test_axes_for_surface_serves_the_matching_axis_and_only_it():
    universal = {a["axis"] for a in _axes() if a["kind"] == "universal"}
    for surface in sorted(da.known_surfaces()):
        served = {a["axis"] for a in da.axes_for_surface(surface)}
        expected_surface_axis = da.surface_axis_key(surface)
        assert served == universal | {expected_surface_axis}, \
            f"surface {surface!r} served {served}"


def test_unknown_surface_gets_universal_axes_only():
    """§3.3 — the clockwork-octopus rule: never a wrong surface, never an error."""
    universal = {a["axis"] for a in _axes() if a["kind"] == "universal"}
    for surface in (None, "", "granite"):
        assert {a["axis"] for a in da.axes_for_surface(surface)} == universal


def test_axes_for_surface_honors_the_catalog_restriction():
    """The Animals tab's surface_options read side (SPEC_PET_DESIGN_AXES_ADMIN
    §3.2): the surface axis offers only the restricted options — plus its file
    default, ALWAYS, because a menu must always offer 'leave it alone'."""
    axes = {a["axis"]: a for a in da.axes_for_surface("fur", {"fluffy"})}
    assert [o["key"] for o in axes["coat"]["options"]] == ["natural", "fluffy"]
    # Unknown keys in the restriction are ignored, never an error.
    axes = {a["axis"]: a for a in da.axes_for_surface("fur", {"no_such_option"})}
    assert [o["key"] for o in axes["coat"]["options"]] == ["natural"]
    # Universal axes are never restricted by it.
    assert len(axes["pattern"]["options"]) == 6


def test_filter_picks_drops_unknown_axes_and_surface_mismatches():
    fur_axis = da.surface_axis_key("fur")
    feather_axis = da.surface_axis_key("feathers")
    picks = {"body": "fat", "no_such_axis": "x",
             fur_axis: "fluffy", feather_axis: "ruffled"}
    filtered = da.filter_picks(picks, "fur")
    assert filtered == {"body": "fat", fur_axis: "fluffy"}, \
        "a fur animal must keep body + coat and lose the feather pick"
    assert da.filter_picks(picks, None) == {"body": "fat"}, \
        "an unknown-surface animal keeps only universal picks (§3.3)"
    assert da.filter_picks(None, "fur") == {}


# ── surface keyword resolution (§3.2 / §3.3) ─────────────────────────────────

@pytest.mark.parametrize("name,expected", [
    ("blue jay", "feathers"),
    ("penguin", "feathers"),
    ("python", "scales"),
    ("dragon", "scales"),          # the green-dragon case: scales, never fur
    ("corgi", "fur"),
    ("red panda", "fur"),
    ("a clockwork octopus", None),  # §3.3 — the answer is null, not a guess
    ("griffin", "feathers"),
    ("", None),
    (None, None),
])
def test_resolve_surface_keyword_tiers(name, expected):
    assert da.resolve_surface(name) == expected


def test_resolved_surfaces_all_have_an_axis():
    """Every surface the keyword map can produce must be served by a surface
    axis — otherwise a typed animal resolves to a surface whose axis silently
    never appears (the same rule the catalog guard enforces for tags)."""
    keyword_surfaces = set(da._keywords()["surfaces"].keys())
    assert keyword_surfaces == da.known_surfaces(), \
        f"keyword map and surface axes disagree: {keyword_surfaces ^ da.known_surfaces()}"


def test_surface_keywords_are_unique_across_surfaces():
    """A word under two surfaces would make resolution order-dependent."""
    seen: dict[str, str] = {}
    for surface, words in da._keywords()["surfaces"].items():
        for w in words:
            assert w not in seen, f"{w!r} mapped to both {seen[w]!r} and {surface!r}"
            seen[w] = surface


# ── registry metadata ────────────────────────────────────────────────────────

def test_max_concurrent_strong_is_int_or_none():
    v = da.max_concurrent_strong()
    assert v is None or (isinstance(v, int) and v > 0)


def test_content_files_are_pure_data():
    """The GPU-less gate in miniature (CLAUDE.md): this subpackage ships to a
    web tier with no ML stack, so it must stay stdlib-parseable content."""
    registry = json.loads((_DIR / "registry.json").read_text())
    assert registry.get("_doc"), "content files carry their own rationale"
    assert "max_concurrent_strong" in registry, \
        "the §11.6 soft-cap field exists from Phase 0 so calibration lands as data"
    keywords = json.loads((_DIR / "surface_keywords.json").read_text())
    assert keywords.get("_doc")
