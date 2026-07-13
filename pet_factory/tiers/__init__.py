"""tiers — the entitlement table as content, not code (SPEC_PET_DESIGNER_PLATFORM §5).

A tier is an ENTITLEMENT — a pose-count cap + extra-pose price — orthogonal to
which animal you design (§5.1). It lives in `tiers.json`, a pure-data config so it
imports on the GPU-less web tier with no ML dependency (the same posture as
motion_profiles / animal_catalog).

What it provides:
  - load_tiers()                          — the parsed tiers.json, cached.
  - resolve_tier(capabilities)            — the tier KEY for a caller, from their
                                            DPP launch capabilities (data-driven via
                                            `capability_tiers`), else the default.
  - entitlement(tier_key)                 — the resolved {max_poses, price_per_extra_pose,
                                            can_adopt, upsell, …} for a tier.

Boundary (§0/§5.3): this module decides WHAT a tier grants; it never decides WHO a
caller is (the web tier resolves identity → capabilities) and never charges (the
host does, §5.2). The browser only ever learns its OWN resolved entitlement, never
the whole table (§5.3) — the API layer returns entitlement(resolve_tier(caps)).

Design note: `resolve_tier` maps capability→tier through the DATA table, so adding a
premium capability is a tiers.json edit, never an engine change (no `if cap == …`).
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Iterable, Optional

_DIR = Path(__file__).resolve().parent
_TIERS_FILE = _DIR / "tiers.json"

_LOCK = threading.Lock()
_TIERS: Optional[dict] = None

# walk+idle are always built (SPEC_MOTION_PROFILES §3.4), so they never count
# against the paid slots — the extra-pose price applies only beyond these two.
_ALWAYS_INCLUDED_POSES = 2


def load_tiers() -> dict:
    """The parsed tiers.json, read once and cached (it ships read-only)."""
    global _TIERS
    if _TIERS is None:
        with _LOCK:
            if _TIERS is None:
                _TIERS = json.loads(_TIERS_FILE.read_text())
    return _TIERS


def default_tier_key() -> str:
    return load_tiers().get("default_tier", "base")


def resolve_tier(capabilities: Optional[Iterable[str]] = None) -> str:
    """The tier KEY for a caller, from their DPP launch capabilities. Most
    generous match wins if several map (by max_poses), so a user with multiple
    premium capabilities gets the best. A caller with no mapped capability — and
    every standalone caller (capabilities is None/empty) — gets the default.
    Data-driven: the capability→tier map is in tiers.json, never in code."""
    data = load_tiers()
    cap_map = data.get("capability_tiers", {})
    tiers = data.get("tiers", {})
    caps = set(capabilities or ())
    best_key = default_tier_key()
    best_cap = tiers.get(best_key, {}).get("max_poses", 0)
    for cap in caps:
        tier_key = cap_map.get(cap)
        if tier_key and tier_key in tiers:
            cap_poses = tiers[tier_key].get("max_poses", 0)
            if cap_poses > best_cap:
                best_key, best_cap = tier_key, cap_poses
    return best_key


def entitlement(tier_key: str) -> dict:
    """The resolved entitlement for a tier key — the exact shape the browser
    receives (§5.3). `extra_pose_slots` is the derived number of OPTIONAL poses
    the tier allows (max_poses minus the always-included walk+idle). An unknown
    key resolves to the default tier (never raises)."""
    data = load_tiers()
    tiers = data.get("tiers", {})
    key = tier_key if tier_key in tiers else default_tier_key()
    t = tiers.get(key, {})
    max_poses = int(t.get("max_poses", _ALWAYS_INCLUDED_POSES))
    return {
        "tier": key,
        "label": t.get("label", key.title()),
        "max_poses": max_poses,
        "extra_pose_slots": max(0, max_poses - _ALWAYS_INCLUDED_POSES),
        "price_per_extra_pose": int(t.get("price_per_extra_pose", 0)),
        "can_generate": bool(t.get("can_generate", True)),
        "can_adopt_samples": bool(t.get("can_adopt_samples", True)),
        "upsell": t.get("upsell", ""),
    }


def resolve_entitlement(capabilities: Optional[Iterable[str]] = None) -> dict:
    """Convenience: resolve_tier then entitlement — the caller's own resolved
    entitlement, ready to hand to the browser."""
    return entitlement(resolve_tier(capabilities))
