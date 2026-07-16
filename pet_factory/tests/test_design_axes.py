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


def test_every_axis_is_fully_formed():
    for a in _axes():
        key = a.get("axis")
        assert key, "an axis file has no 'axis' key"
        assert (_DIR / f"{key}.json").is_file(), \
            f"axis {key!r} does not match its filename"
        assert a.get("label"), f"{key} has no label"
        assert a.get("kind") in VALID_KINDS, f"{key}: kind must be one of {VALID_KINDS}"
        if a["kind"] == "surface":
            assert a.get("applies_to"), f"{key}: a surface axis must declare applies_to"
        assert isinstance(a.get("clause_slot"), int), f"{key}: clause_slot must be an int"
        assert a.get("position") in VALID_POSITIONS, \
            f"{key}: position must be one of {VALID_POSITIONS}"
        ms = a.get("min_strength")
        assert ms is None or isinstance(ms, (int, float)), \
            f"{key}: min_strength must be a number or null"
        assert a.get("_doc"), f"{key}: content files carry their own rationale"


# ── options (generalized from test_body_shapes) ──────────────────────────────

def test_exactly_one_default_per_axis_and_it_exists():
    for a in _axes():
        keys = [o["key"] for o in a["options"]]
        assert len(keys) == len(set(keys)), f"{a['axis']}: duplicate option keys"
        assert a["default"] in keys, \
            f"{a['axis']}: default names an option that isn't in the list"


def test_every_option_is_fully_formed():
    """A half-formed entry fails the build, not a user's design."""
    for a in _axes():
        for o in a["options"]:
            assert o.get("key"), f"{a['axis']}: an option has no key"
            assert o.get("label"), f"{a['axis']}/{o['key']} has no label"
            assert "prompt_fragment" in o, f"{a['axis']}/{o['key']} has no prompt_fragment"
            assert isinstance(o["prompt_fragment"], str)
            assert o["prompt_fragment"] == o["prompt_fragment"].strip(), \
                f"{a['axis']}/{o['key']}'s fragment has loose whitespace — it composes verbatim"


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
