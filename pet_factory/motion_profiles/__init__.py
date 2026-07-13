"""motion_profiles — the species-aware motion vocabulary as content, not code.

A body type (and, later, a species or breed) is one self-contained JSON file in this
directory; `registry.json` indexes them. The engine (`make_pet_zip`) reads whichever
poses a resolved profile enables and never names a species — the engine-vs-content
boundary (SPEC_MOTION_PROFILES §3).

Resolution has two entry points, both returning the identical `MotionProfile`:
  - resolve_motion_profile(animal)         — KEYWORD path: classify to the most-specific
                                             LEVEL keyword match, load that file whole (§3.5/§3.7).
  - load_motion_profile(key, fallback_animal=...) — PINNED path: load the profile whose
                                             registry key == key; on an unknown key (profile-set
                                             skew, §5.2) fall back to keyword resolution + a
                                             logged warning. Never raises on a miss.

There is NO inheritance: a matched profile's poses are exactly what its file lists (§3.7).
Every profile independently declares the full canonical pose key set; a pose the body can't
do is `{"enabled": false}`.

The one guarantee callers rely on: `resolve_motion_profile` and `load_motion_profile` always
return a usable profile — an unmatched animal or an unknown key lands on `registry.default`
(`quadruped`), which reproduces today's exact walk/idle wording (the backward-compat pin, §6).
"""
from __future__ import annotations

import json
import logging
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

_DIR = Path(__file__).resolve().parent

# The canonical pose keys (§3.4). Every profile file must declare all of them.
CANONICAL_POSES = (
    "walk", "idle", "run", "sleep", "sit", "eat", "jump", "play", "swim", "fly",
)
# walk+idle are required-enabled in every profile (the auto state machine needs one
# active + one rest — §3.4). start_job/make_pet_zip always union these in.
REQUIRED_POSES = ("walk", "idle")
# Allowed runtime_role values (must match datsme_me RuntimeRole, types.ts:10).
ALLOWED_ROLES = frozenset({"rest", "active", "timed", "triggered"})
# Hard platform ceiling on poses per build (§8). Realized builds are tier-bounded lower.
MAX_POSES = 10


@dataclass(frozen=True)
class Pose:
    """One pose within a profile. `action`/`suffix` compose the motion prompt.
    A disabled pose may carry only `enabled=False` (the rest defaults are inert)."""
    enabled: bool
    runtime_role: Optional[str] = None
    action: Optional[str] = None
    suffix: str = ""
    control: Optional[dict] = None   # §3.9 skeleton/depth placeholder — None at launch


@dataclass(frozen=True)
class MotionProfile:
    """A resolved motion profile — one whole file, no merging (§3.7)."""
    key: str
    level: int
    movement_class: str
    poses: dict          # pose name -> Pose (the file's own full canonical set)

    def pose(self, name: str) -> Optional[Pose]:
        return self.poses.get(name)

    def enabled_poses(self) -> list[str]:
        """Canonical-order list of the pose names this profile enables."""
        return [p for p in CANONICAL_POSES if self.poses.get(p) and self.poses[p].enabled]


# ---------------------------------------------------------------------------
# Loading + caching. Registry and files are read once (they ship read-only with
# the handler); a lock guards the lazy caches for the threaded webui.
# ---------------------------------------------------------------------------
_LOCK = threading.Lock()
_REGISTRY: Optional[dict] = None                 # {"default": key, "profiles": [entry, ...]}
_PROFILE_CACHE: dict[str, MotionProfile] = {}    # key -> MotionProfile


def _registry() -> dict:
    global _REGISTRY
    if _REGISTRY is None:
        with _LOCK:
            if _REGISTRY is None:
                _REGISTRY = json.loads((_DIR / "registry.json").read_text())
    return _REGISTRY


def _entry_for(key: str) -> Optional[dict]:
    return next((e for e in _registry()["profiles"] if e["key"] == key), None)


def _load_profile_by_key(key: str) -> Optional[MotionProfile]:
    """Load and cache the profile with this registry key, or None if the key is
    not in the registry."""
    cached = _PROFILE_CACHE.get(key)
    if cached is not None:
        return cached
    entry = _entry_for(key)
    if entry is None:
        return None
    with _LOCK:
        cached = _PROFILE_CACHE.get(key)
        if cached is not None:
            return cached
        raw = json.loads((_DIR / entry["file"]).read_text())
        poses = {
            name: Pose(
                enabled=bool(spec.get("enabled", False)),
                runtime_role=spec.get("runtime_role"),
                action=spec.get("action"),
                suffix=spec.get("suffix", ""),
                control=spec.get("control"),
            )
            for name, spec in raw["poses"].items()
        }
        profile = MotionProfile(
            key=raw["key"], level=int(raw["level"]),
            movement_class=raw["movement_class"], poses=poses,
        )
        _PROFILE_CACHE[key] = profile
        return profile


def _default_profile() -> MotionProfile:
    prof = _load_profile_by_key(_registry()["default"])
    if prof is None:  # a broken registry is a build error the guard test catches
        raise RuntimeError("motion_profiles registry.default does not resolve")
    return prof


# ---------------------------------------------------------------------------
# Classification — most-specific-level-wins, longest-keyword within a level (§3.5/§3.7).
# ---------------------------------------------------------------------------
def _classify(animal: str) -> str:
    """Return the winning profile key for `animal`, or the registry default.

    A lower `level` number is more specific (1 breed < 2 species < 3 animal type).
    Across all profiles' keywords, the best match is: lowest level first, then
    longest matching keyword within that level. Word-boundary, case-insensitive.
    """
    text = (animal or "").lower()
    best_key = None
    best_level = None        # lower is more specific
    best_len = -1
    for entry in _registry()["profiles"]:
        prof = _load_profile_by_key(entry["key"])
        if prof is None:
            continue
        raw = json.loads((_DIR / entry["file"]).read_text())
        for kw in raw.get("keywords", []):
            if not re.search(r"\b" + re.escape(kw.lower()) + r"\b", text):
                continue
            level = prof.level
            klen = len(kw)
            # More specific (lower level) wins; within a level, the longest keyword.
            if best_key is None or level < best_level or (level == best_level and klen > best_len):
                best_key, best_level, best_len = entry["key"], level, klen
    return best_key or _registry()["default"]


# ---------------------------------------------------------------------------
# The two public loaders (§3.6).
# ---------------------------------------------------------------------------
def resolve_motion_profile(animal: str) -> MotionProfile:
    """KEYWORD path: classify `animal` to the most-specific matching profile and
    return it whole. Never raises — an unmatched animal lands on the default."""
    key = _classify(animal)
    return _load_profile_by_key(key) or _default_profile()


def load_motion_profile(key: str, *, fallback_animal: Optional[str] = None) -> MotionProfile:
    """PINNED path (§5.2): load the profile named `key`. On an unknown key
    (profile-set skew across a rollout), fall back to keyword resolution of
    `fallback_animal` (or the default) and log a warning. Never raises on a miss —
    a skewed fleet degrades to coarser-but-correct motion, never a failure."""
    prof = _load_profile_by_key(key)
    if prof is not None:
        return prof
    log.warning(
        "pinned motion_profile %r not found, falling back to keyword resolution of %r",
        key, fallback_animal,
    )
    if fallback_animal:
        return resolve_motion_profile(fallback_animal)
    return _default_profile()


def compose_pose_prompt(animal: str, pose: Pose) -> str:
    """Build the Wan I2V motion prompt for one pose. The template matches today's
    hardcoded form exactly — `cute cartoon {animal} {action}, side profile, facing
    right{suffix}` — so the `quadruped` walk/idle poses (action="walking" /
    "sitting calmly", suffix=the old WALK/IDLE_SUFFIX) reproduce today's prompts
    byte-for-byte. This is the backward-compat pin (§6)."""
    return f"cute cartoon {animal} {pose.action}, side profile, facing right{pose.suffix}"
