"""Guard tests for the athletics content package (SPEC_PET_ARENA §14).

Zero-GPU — pure JSON + stdlib. These are the enforcement tests every registry
in this repo carries: they fail the build on a half-formed entry, a stat table
that drifted from the motion profiles, an event no pet on earth could enter,
or an integrator that stopped matching the shared race-vector fixture.

Run:  python3 -m pytest pet_factory/tests/test_athletics.py
"""
import json
from pathlib import Path

import pytest

from pet_factory import athletics
from pet_factory import motion_profiles as mp

_ATHLETICS_DIR = Path(athletics.__file__).resolve().parent
_DESIGN_AXES_DIR = _ATHLETICS_DIR.parent / "design_axes"
_FIXTURES = _ATHLETICS_DIR / "tests" / "fixtures"


def _all_profiles():
    return [mp.load_motion_profile(e["key"]) for e in mp.list_profiles()]


# ---------------------------------------------------------------------------
# movement_classes.json — the cross-layer table (§14 bullet 1-2)
# ---------------------------------------------------------------------------
def test_movement_classes_bijection_with_motion_profiles():
    # Every declared movement_class has a row, and no row exists for a class
    # that is not declared — the test that stops a new body type silently
    # defaulting to average at everything.
    declared = {p.movement_class for p in _all_profiles()}
    rows = set(athletics.movement_class_rows())
    assert rows == declared, (
        f"movement_classes.json drifted from motion profiles: "
        f"missing={declared - rows} extra={rows - declared}")


def test_movement_class_default_row_resolves():
    default = json.loads((_ATHLETICS_DIR / "movement_classes.json").read_text())["default"]
    assert default in athletics.movement_class_rows()
    # base_row never raises: unknown and None land on the default row.
    assert athletics.base_row("no_such_class") == athletics.movement_class_rows()[default]
    assert athletics.base_row(None) == athletics.movement_class_rows()[default]


def test_every_row_is_complete_and_in_range():
    vocabulary = set(athletics.ATTRIBUTES + athletics.MEDIUMS)
    for cls, row in athletics.movement_class_rows().items():
        fields = {k for k in row if not k.startswith("_")}
        assert fields == vocabulary, f"{cls}: fields {fields} != vocabulary"
        for k in vocabulary:
            v = row[k]
            # No null — Rev.3 removed the ineligible semantics (§2.2).
            assert isinstance(v, (int, float)) and not isinstance(v, bool), f"{cls}.{k}"
            assert 0.0 <= v <= 1.0, f"{cls}.{k} = {v} out of 0..1"


# ---------------------------------------------------------------------------
# events/*.json — the registry enforcement (§14 bullets 3-7 + Tier-1 purity)
# ---------------------------------------------------------------------------
def test_event_registry_entries_are_fully_formed():
    events = athletics.list_events()
    assert events, "no events declared"
    registry = json.loads((_ATHLETICS_DIR / "events" / "registry.json").read_text())
    for entry, event in zip(registry["events"], events):
        assert entry["key"] == event["key"], f"registry key {entry['key']} != file key"
    required = {"key", "label", "medium", "distance_m", "decay", "race_roll",
                "time_limit_s", "weights", "requires", "team_size",
                "preferred_poses", "result_unit"}
    for event in events:
        missing = required - set(event)
        assert not missing, f"{event.get('key')}: missing {missing}"
        assert event["medium"] in athletics.MEDIUMS
        assert event["distance_m"] > 0
        assert event["time_limit_s"] > 0
        assert 0.0 <= event["decay"] < 1.0
        # The race roll is texture, not drama (§7.5) — keep it small.
        assert 0.0 <= event["race_roll"] <= 0.1
        assert set(event["weights"]) <= set(athletics.ATTRIBUTES)
        assert sum(event["weights"].values()) == pytest.approx(1.0)
        assert event["preferred_poses"], f"{event['key']}: no preferred_poses"
        for pose in event["preferred_poses"]:
            assert pose in mp.CANONICAL_POSES, f"{event['key']}: unknown pose {pose}"


def test_every_required_pose_exists_in_the_live_canonical_set():
    # §6.3.2 — imported, never copied. A typo'd or not-yet-authored pose makes
    # an event permanently unenterable by every pet on earth, silently.
    for event in athletics.list_events():
        for clause in event["requires"]:
            for pose in clause:
                assert pose in mp.CANONICAL_POSES, (
                    f"{event['key']}: pose {pose!r} not in CANONICAL_POSES")


def test_no_empty_clause_and_no_empty_requires():
    # An empty clause qualifies nobody; an empty requires qualifies everybody.
    # Both are silent, and both are what a half-finished JSON edit produces.
    for event in athletics.list_events():
        assert event["requires"], f"{event['key']}: empty requires"
        for clause in event["requires"]:
            assert clause, f"{event['key']}: empty clause"


def test_every_requires_is_satisfiable_by_a_shipped_profile():
    # A clause combination no single profile enables is an event nobody can
    # ever enter — it passes every other check (§14). Computed, not asserted.
    profiles = _all_profiles()
    for event in athletics.list_events():
        satisfiable = any(
            athletics.qualifies(p.enabled_poses(), event["requires"])
            for p in profiles)
        assert satisfiable, f"{event['key']}: no shipped profile can enter"


def test_the_universal_event_exists():
    # §6.3.3 — at least one event requires only walk, so no child's pet is
    # ever locked out of everything. Deleting the racewalk fails the build.
    assert any(e["requires"] == [["walk"]] for e in athletics.list_events())


def test_every_body_type_at_the_two_pose_minimum_has_an_event():
    # The structural guarantee behind §6.3.3, asserted rather than assumed:
    # a 2-pose pet (walk+idle, the base-tier floor) of ANY body type qualifies
    # somewhere. Holds only while some event requires walk alone.
    events = athletics.list_events()
    for profile in _all_profiles():
        minimum = [p for p in ("walk", "idle") if p in profile.enabled_poses()]
        assert any(athletics.qualifies(minimum, e["requires"]) for e in events), (
            f"{profile.key}: a 2-pose pet has zero enterable events")


def test_team_size_is_a_positive_integer_on_every_event():
    # §6.5 — singles are 1, never absent: an absent value is how a team event
    # silently becomes a solo one.
    for event in athletics.list_events():
        assert isinstance(event["team_size"], int) and event["team_size"] >= 1


def test_tier1_events_carry_no_code():
    # §6.1a tripwire — every event is pure JSON with no companion module. The
    # first "just a little" custom logic must promote to Tier 2 honestly.
    stray = [p.name for p in (_ATHLETICS_DIR / "events").iterdir()
             if p.suffix != ".json"]
    assert not stray, f"non-JSON files in events/: {stray}"


# ---------------------------------------------------------------------------
# modifiers.json — resolves against design_axes (§14)
# ---------------------------------------------------------------------------
def test_every_modifier_resolves_against_design_axes():
    registry = json.loads((_DESIGN_AXES_DIR / "registry.json").read_text())
    axis_keys = {a["key"] for a in registry["axes"]}
    for axis, options in athletics.modifiers().items():
        assert axis in axis_keys, f"modifier axis {axis!r} not a design axis"
        declared = {o["key"] for o in
                    json.loads((_DESIGN_AXES_DIR / f"{axis}.json").read_text())["options"]}
        for option, deltas in options.items():
            assert option in declared, f"modifiers.{axis}.{option}: no such option"
            for attr, delta in deltas.items():
                # Deltas touch attributes only, never a medium affinity.
                assert attr in athletics.ATTRIBUTES, f"{axis}.{option}.{attr}"
                assert abs(delta) < 1.0


# ---------------------------------------------------------------------------
# handicaps + bots (Rev.6, §8.3.1/§7.3)
# ---------------------------------------------------------------------------
def test_handicap_ladder_includes_none_and_only_helps():
    ladder = athletics.handicap_ladder()
    assert 1.0 in ladder.values(), "'no handicap' must be expressible"
    for name, value in ladder.items():
        assert value >= 1.0, f"handicap {name!r} = {value}: a handicap may only help"


def test_bot_rungs_named_positive_strictly_ascending():
    rungs = athletics.bot_rungs()
    values = list(rungs.values())
    assert all(isinstance(k, str) and k for k in rungs)
    assert all(v > 0 for v in values)
    assert values == sorted(values) and len(set(values)) == len(values), (
        "a flat or descending ladder means beating the bot has no next step")


# ---------------------------------------------------------------------------
# The resolver (§5, §14: never raises + precedence)
# ---------------------------------------------------------------------------
def _assert_usable(block):
    for k in athletics.ATTRIBUTES + athletics.MEDIUMS:
        assert isinstance(block[k], float) and 0.0 <= block[k] <= 1.0


def test_resolver_never_raises():
    for manifest in (None, {}, {"movement_class": "no_such_class"},
                     {"animations": None}, {"athletics": "garbage"},
                     {"athletics": {"schema_version": "future.v9"}},
                     {"design": {"picks": {"body": "unknown_option"}}}):
        _assert_usable(athletics.resolve_athletics(manifest))


def test_precedence_valid_block_verbatim():
    block = {"schema_version": athletics.SCHEMA_VERSION,
             "table_version": athletics.TABLE_VERSION,
             "speed": 0.71, "power": 0.42, "endurance": 0.63,
             "land": 0.95, "water": 0.30, "air": 0.05,
             "identity_nudges": {"speed": 0.031, "power": -0.02, "endurance": 0.0},
             "poses": ["walk", "idle", "run"]}
    resolved = athletics.resolve_athletics({"athletics": block,
                                            "movement_class": "aquatic_swimmer"})
    assert resolved is block, "a valid block must be used verbatim (§5.1)"


def test_precedence_stale_table_version_recomputes_reusing_nudges():
    # §5.3/§4.1 — identity survives a rebalance (and even a nudge-algorithm
    # change): the re-mint keeps the stored nudges. This is the one that will
    # actually catch a regression.
    stale = {"schema_version": athletics.SCHEMA_VERSION,
             "table_version": "athletics.v0",
             "speed": 0.99, "power": 0.99, "endurance": 0.99,
             "land": 0.99, "water": 0.99, "air": 0.99,
             "identity_nudges": {"speed": 0.05, "power": -0.03, "endurance": 0.01}}
    resolved = athletics.resolve_athletics(
        {"athletics": stale, "movement_class": "mammalian_quadruped",
         "animations": {"walk": {}, "idle": {}}},
        pet_id="a-different-identity-entirely")
    assert resolved["table_version"] == athletics.TABLE_VERSION
    assert resolved["identity_nudges"] == stale["identity_nudges"]
    row = athletics.base_row("mammalian_quadruped")
    assert resolved["speed"] == pytest.approx(min(row["speed"] + 0.05, 1.0))
    assert resolved["power"] == pytest.approx(row["power"] - 0.03)


def test_absent_block_derives_from_manifest_facts():
    resolved = athletics.resolve_athletics(
        {"movement_class": "aquatic_swimmer",
         "animations": {"walk": {}, "idle": {}, "swim": {}}})
    row = athletics.base_row("aquatic_swimmer")
    assert resolved["water"] == row["water"]
    assert resolved["poses"] == ["walk", "idle", "swim"]
    # No pet id offered → neutral identity, still a usable athlete.
    assert resolved["identity_nudges"] == {a: 0.0 for a in athletics.ATTRIBUTES}


def test_design_modifiers_move_the_derived_attributes():
    thin = athletics.resolve_athletics(
        {"movement_class": "mammalian_quadruped",
         "design": {"picks": {"body": "thin"}}})
    fat = athletics.resolve_athletics(
        {"movement_class": "mammalian_quadruped",
         "design": {"picks": {"body": "fat"}}})
    assert thin["speed"] > fat["speed"]
    assert thin["power"] < fat["power"]


def test_identity_nudges_stable_bounded_and_per_attribute():
    # §3.4 (Rev.7) — same id, same athlete, forever; a different id is a
    # different athlete; every nudge inside ±identity_nudge_range; and the
    # three nudges are INDEPENDENT — identity has shape, not just level.
    a = athletics.identity_nudges_from_pet_id("11111111-2222-3333-4444-555555555555")
    b = athletics.identity_nudges_from_pet_id("11111111-2222-3333-4444-555555555555")
    c = athletics.identity_nudges_from_pet_id("99999999-8888-7777-6666-000000000000")
    assert a == b
    assert a != c
    limit = athletics.identity_nudge_range()
    for nudges in (a, c):
        assert set(nudges) == set(athletics.ATTRIBUTES)
        for value in nudges.values():
            assert -limit <= value <= limit
    # Per-attribute independence: this id's three segments differ (a flat
    # profile from three independent 32-bit folds would be astonishing).
    assert len({round(v, 6) for v in a.values()}) > 1


def test_adopted_twins_are_distinct_athletes():
    # Rev.7's product win: two copies of the SAME artifact (identical manifest,
    # identical sheet bytes) under different pet ids are different athletes.
    manifest = {"movement_class": "mammalian_quadruped",
                "animations": {"walk": {}, "idle": {}, "run": {}}}
    yours = athletics.resolve_athletics(manifest, pet_id="adopted-copy-one")
    mine = athletics.resolve_athletics(manifest, pet_id="adopted-copy-two")
    assert yours["identity_nudges"] != mine["identity_nudges"]
    assert (yours["speed"], yours["power"], yours["endurance"]) != \
           (mine["speed"], mine["power"], mine["endurance"])


# ---------------------------------------------------------------------------
# Stride (§2.3 — pinned) and the integrator (§7)
# ---------------------------------------------------------------------------
_EVEN_WEIGHTS_EVENT = {"medium": "land", "distance_m": 100, "decay": 0.0,
                       "race_roll": 0.0,
                       "weights": {"speed": 0.5, "power": 0.3, "endurance": 0.2}}


def _flat_stats(value, land=1.0):
    return {"speed": value, "power": value, "endurance": value,
            "land": land, "water": 0.0, "air": 0.0}


def test_stride_formula_is_pinned():
    knobs = athletics.tuning()
    # score 0.5 → exactly stride_base_m (§2.3).
    mid = athletics.stride_m(_flat_stats(0.5), _EVEN_WEIGHTS_EVENT)
    assert mid == pytest.approx(knobs["stride_base_m"], rel=1e-12)
    # best ÷ worst == the spread, exactly — the §8.4 knob means what it says.
    best = athletics.stride_m(_flat_stats(1.0), _EVEN_WEIGHTS_EVENT)
    worst = athletics.stride_m(_flat_stats(0.0), _EVEN_WEIGHTS_EVENT)
    assert best / worst == pytest.approx(knobs["athletic_stride_spread"], rel=1e-12)


def test_handicap_multiplies_stride_exactly():
    plain = athletics.stride_m(_flat_stats(0.5), _EVEN_WEIGHTS_EVENT, handicap=1.0)
    boosted = athletics.stride_m(_flat_stats(0.5), _EVEN_WEIGHTS_EVENT, handicap=2.0)
    assert boosted == pytest.approx(plain * 2.0, rel=1e-12)


def test_replay_determinism():
    # §7.4 — the impulse log IS the race: replaying it produces identical
    # results. Without this nothing else in the game is debuggable.
    event = athletics.load_event("sprint_100")
    impulses = [{"at": 500.0 * (i + 1), "quality": 1.0} for i in range(90)]
    entrants = [{"stats": _flat_stats(0.7, land=0.9), "impulses": impulses}]
    first = athletics.simulate_race(event, entrants, race_seed=99)
    second = athletics.simulate_race(event, entrants, race_seed=99)
    assert first == second


def test_wrong_answers_never_move_the_pet():
    # §7.2 — a wrong answer emits no impulse, so an all-wrong run is an empty
    # log and position stays at exactly the start line, never behind it.
    event = athletics.load_event("sprint_100")
    result = athletics.simulate_race(
        event, [{"stats": _flat_stats(1.0), "impulses": []}], race_seed=1)[0]
    assert result["distance_m"] == 0.0
    assert not result["finished"]


def test_skill_beats_stats_at_double_the_answer_rate():
    # §8.4 — the headline test: the worst-stat pet driven at 2× the answer
    # rate beats the best-stat pet. If this fails, ATHLETIC_STRIDE_SPREAD is
    # too wide and the parents' reason for allowing the game is gone.
    event = athletics.load_event("sprint_100")
    fast_player = [{"at": 500.0 * (i + 1), "quality": 1.0} for i in range(400)]
    slow_player = [{"at": 1000.0 * (i + 1), "quality": 1.0} for i in range(400)]
    results = athletics.simulate_race(event, [
        {"stats": _flat_stats(0.0), "impulses": fast_player},   # worst pet, 2 ans/s
        {"stats": _flat_stats(1.0), "impulses": slow_player},   # best pet, 1 ans/s
    ], race_seed=7)
    assert results[0]["place"] == 1, (
        "worst pet at 2x answer rate must win — spread too wide (§8.4)")


def test_flopping_fish_qualifies_and_finishes_last():
    # §14 — an aquatic_swimmer that OWNS run is admitted to the 100 m and
    # finishes last; the same body type without run is refused. Two pets, one
    # species, opposite answers — the per-pet nature of §6.3.
    event = athletics.load_event("sprint_100")
    fish_with_run = {"walk": {}, "idle": {}, "run": {}}
    fish_without = {"walk": {}, "idle": {}, "swim": {}}
    assert athletics.qualifies(fish_with_run, event["requires"])
    assert not athletics.qualifies(fish_without, event["requires"])

    fish_stats = athletics.resolve_athletics(
        {"movement_class": "aquatic_swimmer", "animations": fish_with_run})
    dog_stats = athletics.resolve_athletics(
        {"movement_class": "mammalian_quadruped",
         "animations": {"walk": {}, "idle": {}, "run": {}}})
    same_effort = [{"at": 800.0 * (i + 1), "quality": 1.0} for i in range(200)]
    results = athletics.simulate_race(event, [
        {"stats": fish_stats, "impulses": same_effort},
        {"stats": dog_stats, "impulses": same_effort},
    ], race_seed=5)
    assert results[1]["place"] == 1 and results[0]["place"] == 2, (
        "the fish must flop down the track behind the dog — that is the joke")


def test_alternatives_within_a_clause_are_honoured():
    # The three cases that together are the whole clause evaluator (§6.3).
    hurdles = [["run"], ["jump", "play"]]
    assert athletics.qualifies(["run", "play"], hurdles)          # alternative ok
    assert not athletics.qualifies(["walk", "jump"], hurdles)     # missing run
    assert not athletics.qualifies(["run"], hurdles)              # missing both alts
    assert athletics.unsatisfied_clauses(["run"], hurdles) == [["jump", "play"]]


def test_the_shared_race_vector_fixture():
    # §6.1a — the fixture both integrators run. The TS side asserts the same
    # numbers (web/src/arena/raceEngine.test.ts); drift on either side fails.
    doc = json.loads((_FIXTURES / "race_vectors.json").read_text())
    assert doc["vectors"], "empty fixture"
    for vector in doc["vectors"]:
        results = athletics.simulate_race(
            vector["event"], vector["entrants"], vector["race_seed"],
            tuning_override=vector["tuning"])
        for got, want in zip(results, vector["expected"]):
            assert got["finished"] == want["finished"], vector["name"]
            assert got["place"] == want["place"], vector["name"]
            if want["finish_ms"] is None:
                assert got["finish_ms"] is None, vector["name"]
            else:
                assert got["finish_ms"] == pytest.approx(want["finish_ms"]), vector["name"]
            assert got["distance_m"] == pytest.approx(want["distance_m"], abs=1e-9), vector["name"]
