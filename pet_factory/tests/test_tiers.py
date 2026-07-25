"""Guard test for the tier / entitlement table (SPEC_PET_DESIGNER_PLATFORM §5).

Zero-GPU — pure JSON + loader checks. Protects the entitlement contract:
  1. Every tier stays UNDER the platform pose ceiling (motion MAX_POSES=10).
  2. resolve_tier is data-driven (capability→tier via the table) and picks the
     most generous match; unknown/absent capabilities → the default tier.
  3. entitlement() derives extra_pose_slots correctly (max_poses − walk/idle).

Run:  python3 -m pytest pet_factory/tests/test_tiers.py
"""
from pet_factory import tiers
from pet_factory import motion_profiles as mp


def test_tiers_parse_and_default_exists():
    data = tiers.load_tiers()
    assert "tiers" in data and data["tiers"], "no tiers declared"
    default = data.get("default_tier")
    assert default in data["tiers"], "default_tier not a declared tier"


def test_every_tier_under_the_platform_pose_ceiling():
    # 5 ≤ 10: the tier cap is UNDER the motion ceiling (§5.1). A tier that
    # exceeded MAX_POSES could request more poses than the engine allows.
    for key, t in tiers.load_tiers()["tiers"].items():
        assert t["max_poses"] <= mp.MAX_POSES, f"{key}: max_poses exceeds platform ceiling"
        assert t["max_poses"] >= 2, f"{key}: must allow at least walk+idle"


def test_base_and_plus_defaults():
    base = tiers.entitlement("base")
    assert base["max_poses"] == 2 and base["extra_pose_slots"] == 0
    assert base["price_per_extra_pose"] == 0
    plus = tiers.entitlement("plus")
    assert plus["max_poses"] == 8 and plus["extra_pose_slots"] == 6
    assert plus["price_per_extra_pose"] == 50


def test_launch_posture_default_is_plus():
    # LAUNCH POSTURE (SPEC_PET_DESIGNER_PLATFORM §5.2, tiers.json _doc): the default
    # tier is 'plus' so EVERY user (standalone + launched-without-a-premium-cap) gets
    # up to 8 poses, and extra poses monetize at 50 credits via the live host knob.
    # This pins that decision — flipping default_tier back to 'base' (once DatsMe
    # grants a real premium capability) is then a deliberate change that updates
    # THIS test, not an accidental regression.
    assert tiers.default_tier_key() == "plus"
    ent = tiers.resolve_entitlement([])           # standalone caller
    assert ent["tier"] == "plus" and ent["max_poses"] == 8
    assert ent["price_per_extra_pose"] == 50


def test_resolve_tier_is_data_driven():
    # Standalone (no caps) → the default tier (currently 'plus', see launch posture).
    assert tiers.resolve_tier([]) == tiers.default_tier_key()
    assert tiers.resolve_tier(None) == tiers.default_tier_key()
    # The mapped premium capability → plus.
    cap_map = tiers.load_tiers()["capability_tiers"]
    plus_cap = next(c for c, t in cap_map.items() if t == "plus")
    assert tiers.resolve_tier([plus_cap]) == "plus"
    # An unmapped capability → still the default.
    assert tiers.resolve_tier(["some_unrelated_capability"]) == tiers.default_tier_key()


def test_resolve_tier_prefers_most_generous():
    cap_map = tiers.load_tiers()["capability_tiers"]
    plus_cap = next(c for c, t in cap_map.items() if t == "plus")
    # A user with both an unmapped cap and the plus cap gets plus (higher cap wins).
    assert tiers.resolve_tier(["noise", plus_cap]) == "plus"


def test_entitlement_unknown_key_falls_to_default():
    ent = tiers.entitlement("nonesuch_tier")
    assert ent["tier"] == tiers.default_tier_key()


def test_resolve_entitlement_convenience():
    ent = tiers.resolve_entitlement([])
    assert ent["tier"] == tiers.default_tier_key()
    assert ent["max_poses"] == tiers.entitlement(tiers.default_tier_key())["max_poses"]
