"""Guard test for the motion_profiles registry (SPEC_MOTION_PROFILES §3.6).

Fails the build on a half-formed profile. Zero-GPU — pure JSON + loader checks.
Run:  python3 -m pytest pet_factory/tests/test_motion_profiles.py
"""
import json
import logging
from pathlib import Path

import pytest

from pet_factory import motion_profiles as mp

_DIR = Path(mp.__file__).resolve().parent


def _all_entries():
    return json.loads((_DIR / "registry.json").read_text())["profiles"]


# --- registry + files ------------------------------------------------------
def test_registry_parses_and_default_resolves():
    reg = json.loads((_DIR / "registry.json").read_text())
    assert "default" in reg and "profiles" in reg
    default_key = reg["default"]
    assert any(e["key"] == default_key for e in reg["profiles"]), "default not listed"
    prof = mp.load_motion_profile(default_key)
    assert prof.key == default_key


def test_every_file_parses_and_key_matches_registry():
    for entry in _all_entries():
        raw = json.loads((_DIR / entry["file"]).read_text())
        assert raw["key"] == entry["key"], f"{entry['file']}: key mismatch"
        assert int(raw["level"]) == int(entry["level"]), f"{entry['file']}: level mismatch"


def test_every_profile_declares_full_canonical_pose_set():
    # No inheritance (§3.7) — each file must list ALL canonical poses itself.
    for entry in _all_entries():
        raw = json.loads((_DIR / entry["file"]).read_text())
        keys = set(raw["poses"].keys())
        assert keys == set(mp.CANONICAL_POSES), (
            f"{entry['file']}: pose keys {sorted(keys)} != canonical {sorted(mp.CANONICAL_POSES)}"
        )


def test_valid_level_in_allowed_range():
    for entry in _all_entries():
        assert 1 <= int(entry["level"]) <= 4, f"{entry['key']}: level out of 1..4"


def test_walk_and_idle_enabled_in_every_profile():
    # Every file must be independently runnable: one active + one rest (§3.4).
    for entry in _all_entries():
        prof = mp.load_motion_profile(entry["key"])
        for req in mp.REQUIRED_POSES:
            p = prof.pose(req)
            assert p is not None and p.enabled, f"{entry['key']}: {req} must be enabled"


def test_enabled_poses_have_action_and_valid_role():
    for entry in _all_entries():
        prof = mp.load_motion_profile(entry["key"])
        for name in prof.enabled_poses():
            p = prof.pose(name)
            assert p.action, f"{entry['key']}.{name}: enabled pose needs a non-empty action"
            assert p.runtime_role in mp.ALLOWED_ROLES, (
                f"{entry['key']}.{name}: runtime_role {p.runtime_role!r} not allowed"
            )


def test_keywords_unique_across_all_profiles():
    seen = {}
    for entry in _all_entries():
        raw = json.loads((_DIR / entry["file"]).read_text())
        for kw in raw.get("keywords", []):
            k = kw.lower()
            assert k not in seen, f"keyword {kw!r} claimed by both {seen[k]} and {entry['key']}"
            seen[k] = entry["key"]


# --- backward-compat pin (§6): quadruped walk/idle reproduce today's prompts --
# These are the exact strings the pre-motion-profiles factory.py composed, kept
# here as literals so the test catches drift in EITHER the profile or the factory.
_TODAY_WALK = (
    "cute cartoon {animal} walking, side profile, facing right"
    ", mouth closed, no facial animation, no chewing, no talking, eyes still, "
    "performing a full walk cycle in place: legs and feet cycling through one "
    "complete stride, body bobbing naturally up and down with each step, classic "
    "looping sprite walk animation, no horizontal movement of the body, no camera "
    "movement, no panning"
)
_TODAY_IDLE = (
    "cute cartoon {animal} sitting calmly, side profile, facing right"
    ", mouth closed, no facial animation, no chewing, no talking, eyes still, "
    "gentle idle motion: soft breathing, slight sway, a small bob in place, "
    "no walking, no camera movement, no panning"
)


def test_quadruped_walk_idle_reproduce_today_verbatim():
    prof = mp.load_motion_profile("quadruped")
    animal = "red panda"
    walk = mp.compose_pose_prompt(animal, prof.pose("walk"))
    idle = mp.compose_pose_prompt(animal, prof.pose("idle"))
    assert walk == _TODAY_WALK.format(animal=animal), "quadruped walk drifted from today's prompt"
    assert idle == _TODAY_IDLE.format(animal=animal), "quadruped idle drifted from today's prompt"


# --- resolution behavior ---------------------------------------------------
def test_keyword_resolution_lands_expected_profiles():
    assert mp.resolve_motion_profile("golden retriever dog").key == "quadruped"
    assert mp.resolve_motion_profile("a red cardinal bird").key == "avian"
    assert mp.resolve_motion_profile("green cobra").key == "serpentine"
    assert mp.resolve_motion_profile("blue betta fish").key == "aquatic"
    assert mp.resolve_motion_profile("baby dragon").key == "winged_flyer"


def test_unmatched_animal_lands_on_default():
    assert mp.resolve_motion_profile("zxqwv nonsense").key == mp.load_motion_profile(
        json.loads((_DIR / "registry.json").read_text())["default"]).key


def test_pinned_load_and_skew_fallback(caplog):
    # Exact key loads directly.
    assert mp.load_motion_profile("avian").key == "avian"
    # Unknown key + fallback_animal → keyword resolution, warning, no raise (§5.2).
    with caplog.at_level(logging.WARNING):
        prof = mp.load_motion_profile("corgi", fallback_animal="a small dog")
    assert prof.key == "quadruped"       # keyword fallback landed the animal-type
    assert any("not found" in r.message for r in caplog.records)
    # Unknown key, no fallback → the default, still no raise.
    assert mp.load_motion_profile("nonesuch").key == "quadruped"


def test_disabled_poses_excluded_from_enabled_list():
    # A snake can't jump/fly/sit-less... serpentine disables jump/play/fly.
    prof = mp.load_motion_profile("serpentine")
    enabled = set(prof.enabled_poses())
    assert "jump" not in enabled and "fly" not in enabled
    assert "walk" in enabled and "swim" in enabled
