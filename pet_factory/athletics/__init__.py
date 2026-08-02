"""athletics — the Pet Games' stat vocabulary, event declarations and reference
integrator, as content (SPEC_PET_ARENA §2–§6).

Pure data + stdlib, deliberately: this package sits on the GPU-less tier beside
`tiers/` and `design_axes/` and is read by four parties — the build (Phase 4's
manifest stamp), the browser (web/src/arena/declarations.ts imports the same
JSON files), the guard tests, and — when rooms ship — the room server. One
declaration, four readers (§6.1a). Never import ML deps here.

What lives where:
  - movement_classes.json  base six-tuple per movement_class (§3.1)
  - modifiers.json         design-axis pick → attribute deltas (§3.2)
  - roll.json              the pet-roll range (§3.4)
  - tuning.json            stride_base_m + athletic_stride_spread (§2.3/§8.4)
  - bots.json              the bot answer-rate ladder (§7.3, Rev.6)
  - handicaps.json         the handicap ladder (§8.3.1, Rev.6)
  - events/*.json          Tier-1 event declarations + registry.json (§6.1a)

The resolver (`resolve_athletics`) never raises (§5.1): a manifest with a valid
stamped block returns it verbatim; a stale `table_version` recomputes reusing
the stored roll so identity survives a rebalance (§5.3); an absent block
derives from `movement_class` + `animations`, which every manifest ever written
by this repo carries (§5).

The integrator (`simulate_race`) is the REFERENCE implementation of the §6.1a
procedure — "integrate stride until the distance is covered", parameterised by
the declaration. web/src/arena/raceEngine.ts mirrors it operation-for-operation
and the shared fixture (tests/fixtures/race_vectors.json) keeps the two honest:
two implementations that drift are otherwise indistinguishable from a cheating
child. All randomness flows through `_mix32`, a 32-bit hash both languages can
reproduce bit-for-bit — never `random`, never `Math.random`.
"""
from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Optional

_DIR = Path(__file__).resolve().parent

SCHEMA_VERSION = "pet_athletics.v1"   # §4.1 — the block's shape contract
TABLE_VERSION = "athletics.v1"        # §5.3 — bump on rebalance; resolver re-derives
ATTRIBUTES = ("speed", "power", "endurance")   # §2.1
MEDIUMS = ("land", "water", "air")             # §2.2

_LOCK = threading.Lock()
_CACHE: dict[str, dict] = {}


def _data(name: str) -> dict:
    """Load + cache one JSON data file. Same pattern as motion_profiles: files
    ship read-only; the lock guards the lazy cache for the threaded webui."""
    cached = _CACHE.get(name)
    if cached is None:
        with _LOCK:
            cached = _CACHE.get(name)
            if cached is None:
                cached = json.loads((_DIR / name).read_text())
                _CACHE[name] = cached
    return cached


def movement_class_rows() -> dict:
    return _data("movement_classes.json")["classes"]


def base_row(movement_class: Optional[str]) -> dict:
    """The six-tuple for a movement class; unknown/absent classes land on the
    declared default row — the never-raises posture (§3.1)."""
    rows = movement_class_rows()
    if isinstance(movement_class, str) and movement_class in rows:
        return rows[movement_class]
    return rows[_data("movement_classes.json")["default"]]


def modifiers() -> dict:
    return _data("modifiers.json")["modifiers"]


def pet_roll_range() -> float:
    return float(_data("roll.json")["pet_roll_range"])


def bot_rungs() -> dict:
    return _data("bots.json")["rungs"]


def handicap_ladder() -> dict:
    return _data("handicaps.json")["handicap_ladder"]


def tuning() -> dict:
    return _data("tuning.json")


# ---------------------------------------------------------------------------
# Events (§6.1a — declaration is data; this module is also the Tier-1 procedure).
# ---------------------------------------------------------------------------
def list_events() -> list[dict]:
    """Every event declaration, in registry order."""
    registry = _data("events/registry.json")
    return [_data(f"events/{entry['file']}") for entry in registry["events"]]


def load_event(key: str) -> Optional[dict]:
    return next((e for e in list_events() if e["key"] == key), None)


# ---------------------------------------------------------------------------
# Eligibility (§6.3) — AND-of-ORs over the pose names the pet actually owns.
# ---------------------------------------------------------------------------
def qualifies(animations, requires) -> bool:
    """`requires` is a list of clauses, each a list of acceptable poses; all
    clauses must be satisfied, any one pose satisfies a clause. `animations`
    accepts the manifest dict (keys are pose names) or a plain list."""
    owned = set(animations or ())
    return all(any(pose in owned for pose in clause) for clause in requires)


def unsatisfied_clauses(animations, requires) -> list[list[str]]:
    """The clauses this pet fails — for presentation (§6.3.3: show locked
    events with every unsatisfied clause named, alternatives and all)."""
    owned = set(animations or ())
    return [list(clause) for clause in requires
            if not any(pose in owned for pose in clause)]


# ---------------------------------------------------------------------------
# The resolver (§5) — manifest in, six numbers + roll + poses out. Never raises.
# ---------------------------------------------------------------------------
def _clamp01(v: float) -> float:
    return 0.0 if v < 0.0 else 1.0 if v > 1.0 else v


def derive_roll_from_sheet(sheet_bytes: bytes) -> float:
    """§5.2 — a stable roll for a pet that never got one, derived from the
    sprite sheet bytes the arena has already fetched. Same pet → same bytes →
    same roll, on any device, forever. NOT stable across a rebuild of the same
    design — which is correct, because that is a different pet.

    Algorithm (mirrored exactly in web/src/arena/athletics.ts): sha256 of the
    bytes, first 8 hex chars as an unsigned int, mapped onto ±pet_roll_range."""
    digest = hashlib.sha256(sheet_bytes).hexdigest()
    unit = int(digest[:8], 16) / 0xFFFFFFFF
    return (2.0 * unit - 1.0) * pet_roll_range()


def _block_is_valid(block) -> bool:
    if not isinstance(block, dict):
        return False
    if block.get("schema_version") != SCHEMA_VERSION:
        return False
    if block.get("table_version") != TABLE_VERSION:
        return False
    return all(isinstance(block.get(k), (int, float)) and not isinstance(block.get(k), bool)
               for k in ATTRIBUTES + MEDIUMS)


def block_is_current(block) -> bool:
    """True when a stored athletics block is valid under the CURRENT schema and
    table versions — the no-op test the build stamp uses (§4.2): a bundle whose
    block is current is returned unchanged, same-object, so nothing re-compresses
    3.5 MB to write what is already there."""
    return _block_is_valid(block)


def resolve_athletics(manifest: Optional[dict],
                      sheet_bytes: Optional[bytes] = None) -> dict:
    """§5.1 precedence, strictly: a present, valid block is used VERBATIM; a
    stale or malformed block is re-derived reusing its stored `roll` (§5.3 —
    identity survives a rebalance); an absent block derives from facts every
    manifest already carries. Nothing downstream may branch on which path ran —
    that would be a provenance branch, which §0.14 forbids."""
    manifest = manifest if isinstance(manifest, dict) else {}
    block = manifest.get("athletics")
    if _block_is_valid(block):
        return block
    stored_roll = block.get("roll") if isinstance(block, dict) else None
    if isinstance(stored_roll, bool) or not isinstance(stored_roll, (int, float)):
        stored_roll = None
    return _derive(manifest, sheet_bytes, stored_roll)


def _derive(manifest: dict, sheet_bytes: Optional[bytes],
            stored_roll: Optional[float]) -> dict:
    row = base_row(manifest.get("movement_class")
                   if isinstance(manifest.get("movement_class"), str) else None)
    animations = manifest.get("animations")
    poses = list(animations.keys()) if isinstance(animations, dict) else []

    if stored_roll is not None:
        roll = float(stored_roll)
    elif sheet_bytes:
        roll = derive_roll_from_sheet(sheet_bytes)
    else:
        roll = 0.0

    design = manifest.get("design")
    picks = design.get("picks") if isinstance(design, dict) else None
    picks = picks if isinstance(picks, dict) else {}
    mods = modifiers()

    stats: dict = {}
    for attr in ATTRIBUTES:
        value = float(row[attr]) + roll
        for axis, option in picks.items():
            delta = mods.get(axis, {}).get(option, {}).get(attr)
            if isinstance(delta, (int, float)):
                value += float(delta)
        stats[attr] = _clamp01(value)
    for medium in MEDIUMS:
        stats[medium] = _clamp01(float(row[medium]))

    return {
        "schema_version": SCHEMA_VERSION,
        "table_version": TABLE_VERSION,
        **stats,
        "roll": roll,
        "poses": poses,
    }


# ---------------------------------------------------------------------------
# Stride (§2.3) and the reference integrator (§6.1a / §7).
# ---------------------------------------------------------------------------
def stride_m(stats: dict, event: dict, handicap: float = 1.0,
             tuning_override: Optional[dict] = None) -> float:
    """§2.3: score = Σ weights·attrs, times the medium affinity; stride =
    stride_base_m × spread^(score − 0.5) × handicap (§8.3.1). At score 0.5 the
    stride is exactly stride_base_m; best ÷ worst is exactly the spread —
    both pinned by guard tests, because this is the equation the whole game
    reduces to and it must not drift on a refactor."""
    knobs = tuning_override or tuning()
    weights = event["weights"]
    score = sum(float(weights.get(a, 0.0)) * _clamp01(float(stats.get(a, 0.0)))
                for a in ATTRIBUTES)
    score = _clamp01(score) * _clamp01(float(stats.get(event["medium"], 0.0)))
    spread = float(knobs["athletic_stride_spread"])
    return float(knobs["stride_base_m"]) * (spread ** (score - 0.5)) * float(handicap)


def _mix32(a: int, b: int, c: int) -> int:
    """Deterministic 32-bit hash of (seed, lane, impulse index) — the ONLY
    randomness source in a race, so a replay reproduces the finish exactly
    (§7.4) in both languages. Mirrored bit-for-bit in web/src/arena/rng.ts
    (Math.imul + >>> there, masked multiply here)."""
    a &= 0xFFFFFFFF
    b &= 0xFFFFFFFF
    c &= 0xFFFFFFFF
    x = (a ^ ((b * 0x85EBCA6B) & 0xFFFFFFFF) ^ ((c * 0xC2B2AE35) & 0xFFFFFFFF)) & 0xFFFFFFFF
    x ^= x >> 16
    x = (x * 0x7FEB352D) & 0xFFFFFFFF
    x ^= x >> 15
    x = (x * 0x846CA68B) & 0xFFFFFFFF
    x ^= x >> 16
    return x


def _unit_interval(x: int) -> float:
    return x / 4294967296.0


def simulate_entrant(event: dict, stats: dict, handicap: float,
                     impulses: list, race_seed: int, lane: int,
                     tuning_override: Optional[dict] = None) -> dict:
    """Integrate one entrant's impulse log against one event declaration.

    §7.1: distance per impulse = quality × effective stride. §2.4: the stride
    decays with DISTANCE COVERED, not elapsed time — a slow player fatigues
    the player, never the pet. §7.5: the race roll perturbs each impulse's
    stride inside ±event.race_roll, seeded, so a race is not a metronome but a
    replay is still exact. §7.2: a wrong answer produced no impulse, so an
    all-wrong log leaves the pet at exactly the start line."""
    base = stride_m(stats, event, handicap, tuning_override)
    decay = float(event.get("decay", 0.0))
    race_roll = float(event.get("race_roll", 0.0))
    distance = float(event["distance_m"])
    endurance = _clamp01(float(stats.get("endurance", 0.0)))

    covered = 0.0
    finish_ms: Optional[float] = None
    for idx, impulse in enumerate(sorted(impulses, key=lambda i: float(i["at"]))):
        quality = float(impulse.get("quality", 1.0))
        jitter = 1.0 + race_roll * (
            2.0 * _unit_interval(_mix32(race_seed, lane, idx)) - 1.0)
        fatigue = 1.0 - decay * min(covered / distance, 1.0) * (1.0 - endurance)
        effective = base * fatigue * jitter
        covered += max(effective, 0.0) * quality
        if covered >= distance:
            finish_ms = float(impulse["at"])
            break

    return {
        "finished": finish_ms is not None,
        "finish_ms": finish_ms,
        "distance_m": min(covered, distance),
    }


def simulate_race(event: dict, entrants: list, race_seed: int,
                  tuning_override: Optional[dict] = None) -> list[dict]:
    """The whole race: one result per entrant (registry order preserved), with
    `place` assigned — finishers by finish time, then the unfinished by
    distance covered. Entrant shape: {"stats", "handicap", "impulses"}; lane
    is the list index, which is what seeds each lane's race roll."""
    results = [
        simulate_entrant(event, e["stats"], float(e.get("handicap", 1.0)),
                         e["impulses"], race_seed, lane, tuning_override)
        for lane, e in enumerate(entrants)
    ]
    order = sorted(
        range(len(results)),
        key=lambda i: ((0, results[i]["finish_ms"]) if results[i]["finished"]
                       else (1, -results[i]["distance_m"])),
    )
    for place, i in enumerate(order):
        results[i]["place"] = place + 1
    return results
