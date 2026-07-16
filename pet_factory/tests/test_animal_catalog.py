"""Guard test for the base-animal catalog (SPEC_PET_DESIGNER_PLATFORM §4.2/§4.5).

Fails the build on a half-formed catalog entry. Zero-GPU — pure JSON + loader
checks, no ML stack. The load-bearing guarantees this protects:

  1. Every pinned `motion_profile` key resolves in the motion registry — a catalog
     entry cannot point at a missing profile (§4.2). This is the cross-layer
     contract: the catalog declares a key; the motion registry must own it.
  2. Every declared breed has a curated base.png on disk (§4.3) — no broken
     instant-base-image. (Placeholder bases still count as present; the
     generate-then-curate pass replaces them, §4.5.)
  3. The resolver returns the most-specific pinned key (breed key > animal key).

Run:  python3 -m pytest pet_factory/tests/test_animal_catalog.py
"""
from pathlib import Path

from pet_factory import animal_catalog as cat
from pet_factory import motion_profiles as mp

_DIR = Path(cat.__file__).resolve().parent


def _all_animals():
    return cat.list_animals()


# --- structure -------------------------------------------------------------
def test_catalog_parses_and_has_animals():
    animals = _all_animals()
    assert animals, "catalog.json declares no animals"
    for a in animals:
        assert a.get("key"), "an animal is missing its key"
        assert a.get("motion_profile"), f"{a['key']}: animal must pin a motion_profile"
        assert a.get("breeds"), f"{a['key']}: animal must declare at least one breed"


def test_animal_and_breed_keys_are_path_safe():
    # Keys become filesystem path segments (<animal>/<breed>/base.png) AND ride the
    # /api/catalog/{animal}/{breed}/base.png route, whose handler enforces isalnum.
    for a in _all_animals():
        assert a["key"].isalnum(), f"animal key {a['key']!r} not alphanumeric"
        for b in a["breeds"]:
            assert b["key"].isalnum(), f"breed key {b['key']!r} not alphanumeric"


# --- the cross-layer contract (§4.2) ---------------------------------------
def test_every_pinned_motion_profile_resolves_in_the_registry():
    # The core guarantee: no catalog entry points at a profile the motion registry
    # doesn't own. load_motion_profile falls back silently on skew, so assert the
    # RESOLVED key equals the pinned key — an exact hit, not a fallback.
    for a in _all_animals():
        for b in a["breeds"]:
            key = cat.resolved_motion_profile(a["key"], b["key"])
            assert key, f"{a['key']}/{b['key']}: resolved to no profile"
            prof = mp.load_motion_profile(key)
            assert prof.key == key, (
                f"{a['key']}/{b['key']}: pinned motion_profile {key!r} is not in the "
                f"motion registry (load fell back to {prof.key!r})"
            )


def test_resolver_prefers_the_breed_key_over_the_animal_key():
    # Most-specific-wins (§4.2): a breed that declares its own motion_profile
    # overrides the animal's; a breed that doesn't inherits the animal's.
    for a in _all_animals():
        for b in a["breeds"]:
            expected = b.get("motion_profile") or a["motion_profile"]
            assert cat.resolved_motion_profile(a["key"], b["key"]) == expected


# --- the base-image guarantee (§4.3) ---------------------------------------
def test_every_breed_has_a_base_image_on_disk():
    for a in _all_animals():
        for b in a["breeds"]:
            path = cat.base_image_path(a["key"], b["key"])
            assert path is not None and path.is_file(), (
                f"{a['key']}/{b['key']}: missing curated base.png "
                f"(expected {_DIR / a['key'] / b['key'] / 'base.png'})"
            )


def test_missing_breed_resolves_to_none_not_a_crash():
    assert cat.base_image_path("cat", "does_not_exist") is None
    assert cat.base_image_path("no_such_animal", "tabby") is None
    assert cat.resolved_motion_profile("no_such_animal") is None
    assert cat.resolved_surface("no_such_animal") is None


# --- the design-surface contract (SPEC_PET_DESIGN_AXES §1/§3.1) --------------
def test_every_resolved_surface_matches_a_surface_axis():
    """Catalog surface integrity (SPEC_PET_DESIGN_AXES §10): every catalog
    entry's RESOLVED surface must match a design_axes surface axis's
    applies_to — a typo can't ship a breed whose surface axis silently never
    appears. Every entry must also BE tagged: the catalog door is the confident
    tier (§3.1), and an untagged curated breed would degrade a vetted animal to
    the unknown-animal posture."""
    from pet_factory import design_axes as da
    known = da.known_surfaces()
    for a in _all_animals():
        for b in a["breeds"]:
            surface = cat.resolved_surface(a["key"], b["key"])
            assert surface, (
                f"{a['key']}/{b['key']}: no surface tag — a curated breed must "
                f"resolve one (SPEC_PET_DESIGN_AXES §3.1)")
            assert surface in known, (
                f"{a['key']}/{b['key']}: surface {surface!r} matches no surface "
                f"axis's applies_to ({sorted(known)})")


def test_surface_resolver_prefers_the_breed_tag_over_the_animal_tag():
    # Most-specific-wins, mirroring resolved_motion_profile: a breed that
    # declares its own surface (a Sphynx) overrides the animal's; a breed that
    # doesn't inherits it.
    for a in _all_animals():
        for b in a["breeds"]:
            expected = b.get("surface") or a.get("surface")
            assert cat.resolved_surface(a["key"], b["key"]) == expected
