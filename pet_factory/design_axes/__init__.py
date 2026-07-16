"""design_axes — the design-axis vocabulary as content, not code
(SPEC_PET_DESIGN_AXES §1).

A design AXIS is a curated vocabulary of {key, label, prompt_fragment} whose
default means "change nothing" (fragment exactly ""). This package generalizes
what body_shapes/ pioneered for one axis into the registry the spec's Tier 1
set needs (body + pattern + expression + the surface axes), structured like
motion_profiles/: one JSON per axis plus a registry.json naming them in menu
order. Adding an axis is one file + one registry line; nothing else changes
(§9 — the four test questions).

Axes come in two kinds (§0.3 — the animal-awareness):
  - "universal"  shown for every animal (body, pattern, expression).
  - "surface"    fur/feathers/scales vocabularies: mutually exclusive, exactly
                 ONE shows, chosen by the animal's resolved surface. A cat sees
                 coat; a bird sees plumage; an unknown creature sees neither
                 (§3.3 — never a wrong guess; free text is the escape hatch).

What it provides:
  list_axes()                  — every axis, public shape, menu order.
  axes_for_surface(surface)    — the §4 filter: universal axes + the one
                                 matching surface axis (none when surface=None).
  default_key(axis)            — the key meaning "leave it alone".
  prompt_fragment(axis, key)   — the words a pick contributes; "" for defaults,
                                 unknowns, and typos. NEVER reaches the browser.
  is_default(axis, key)        — True for the default and for anything unknown.
  axis_composition(axis)       — clause_slot / position / min_strength, the
                                 compose_design metadata (§2).
  filter_picks(picks, surface) — drop unknown axes + surface-mismatched picks.
  resolve_surface(animal)      — the §3.2 keyword tier for uncatalogued names;
                                 None when nothing matches (§3.3).
  known_surfaces() / surface_axis_key(surface) — the catalog guard's vocabulary.
  max_concurrent_strong()      — the §11.6 soft-cap (data; null until Phase 3).

Boundary: this module owns vocabularies; it never composes a prompt (the web
tier's compose_design does) and never renders (the engine does). The engine
never learns the word "fluffy" — it receives an opaque composed string.

Posture: pure stdlib. Imported by the GPU-less web tier, so it must never grow
an ML dependency (CLAUDE.md; pinned by test_pool_mode_never_imports_the_ml_factory).

Never raises: unknown axes and option keys resolve to "no fragment" rather than
an error — the body_shapes posture, kept. A typo in a request must degrade to
"no change", never 500 a design. A registry entry whose file is missing is
skipped at runtime and FAILS THE BUILD in test_design_axes.py; runtime
resilience is not permission to ship a half-formed entry.
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Optional

_DIR = Path(__file__).resolve().parent
_REGISTRY_FILE = _DIR / "registry.json"
_SURFACE_KEYWORDS_FILE = _DIR / "surface_keywords.json"

_LOCK = threading.Lock()
_CACHE: Optional[dict] = None
_KEYWORDS: Optional[dict] = None


def _load() -> dict:
    """registry.json + every registered axis file, read once and cached
    (they ship read-only)."""
    global _CACHE
    if _CACHE is None:
        with _LOCK:
            if _CACHE is None:
                registry = json.loads(_REGISTRY_FILE.read_text())
                order: list[str] = []
                axes: dict[str, dict] = {}
                for entry in registry.get("axes", []):
                    key = entry.get("key")
                    if not key:
                        continue
                    path = _DIR / f"{key}.json"
                    if not path.is_file():
                        # Runtime degrades (the never-raises posture); the build
                        # does not — the guard test asserts file↔registry parity.
                        continue
                    axes[key] = json.loads(path.read_text())
                    order.append(key)
                _CACHE = {"registry": registry, "axes": axes, "order": order}
    return _CACHE


def _axis(key: Optional[str]) -> Optional[dict]:
    return _load()["axes"].get(key or "")


def _public(axis: dict) -> dict:
    """The browser's view of one axis: {axis, label, kind, default, options},
    options as {key, label, is_default} ONLY. `prompt_fragment` is deliberately
    withheld — calibrated server-side wording, the tier-table posture (§4)."""
    default = axis.get("default", "")
    return {
        "axis": axis["axis"],
        "label": axis.get("label", axis["axis"]),
        "kind": axis.get("kind", "universal"),
        "default": default,
        "options": [
            {"key": o["key"], "label": o.get("label", o["key"].title()),
             "is_default": o["key"] == default}
            for o in axis.get("options", [])
        ],
    }


def list_axes() -> list[dict]:
    """Every axis in menu order, public shape (fragments withheld)."""
    data = _load()
    return [_public(data["axes"][k]) for k in data["order"]]


def public_axis(key: str) -> Optional[dict]:
    """One axis, public shape, or None — the /api/body-shapes alias reads this."""
    a = _axis(key)
    return _public(a) if a else None


def axes_for_surface(surface: Optional[str]) -> list[dict]:
    """The §4 server-owned filter: the universal axes plus the ONE surface axis
    whose applies_to matches, in menu order. surface=None (uncatalogued,
    unmatched, or upload — §3.3) returns only the universal axes: never a wrong
    surface, never an error."""
    data = _load()
    out = []
    for key in data["order"]:
        a = data["axes"][key]
        if a.get("kind") == "surface" and (not surface or a.get("applies_to") != surface):
            continue
        out.append(_public(a))
    return out


def default_key(axis: str) -> str:
    a = _axis(axis)
    return a.get("default", "") if a else ""


def _option(axis: str, key: Optional[str]) -> Optional[dict]:
    a = _axis(axis)
    if a is None or not key:
        return None
    return next((o for o in a.get("options", []) if o.get("key") == key), None)


def prompt_fragment(axis: str, key: Optional[str]) -> str:
    """The words a pick contributes to the composed DESIGN string. "" for the
    default, for None/empty, for an unknown option, and for an unknown AXIS —
    so compose_design can iterate picks unconditionally."""
    o = _option(axis, key)
    return o.get("prompt_fragment", "") if o else ""


def is_default(axis: str, key: Optional[str]) -> bool:
    """True when this pick asks for no change. Empty/None → True, an unknown
    axis or option → True as well: it contributes no fragment, so treating it
    as a change would let a typo claim the design was modified."""
    if not key:
        return True
    if _option(axis, key) is None:
        return True
    return key == default_key(axis)


def axis_composition(axis: str) -> dict:
    """The compose_design metadata (§2): where the fragment goes and what it
    costs. Unknown axis → inert defaults, same never-raises posture."""
    a = _axis(axis) or {}
    return {
        "clause_slot": a.get("clause_slot", 100),
        "position": a.get("position", "prefix"),
        "min_strength": a.get("min_strength"),
    }


def known_surfaces() -> set[str]:
    """Every applies_to value a surface axis serves — the vocabulary the catalog
    guard validates `surface` tags against (§1)."""
    return {
        a["applies_to"]
        for a in _load()["axes"].values()
        if a.get("kind") == "surface" and a.get("applies_to")
    }


def surface_axis_key(surface: Optional[str]) -> Optional[str]:
    """The one axis serving a surface, or None."""
    if not surface:
        return None
    data = _load()
    for key in data["order"]:
        a = data["axes"][key]
        if a.get("kind") == "surface" and a.get("applies_to") == surface:
            return key
    return None


def filter_picks(picks: Optional[dict], surface: Optional[str]) -> dict:
    """§4 defense in depth for /api/preview's axis_picks: drop picks for axes
    the registry doesn't know, and for surface axes that don't match the
    reference's resolved surface (the menu already hid them; a hand-crafted
    request must not get further). Unknown OPTION keys survive — is_default /
    prompt_fragment treat them as no-ops, the body_shapes typo posture."""
    out: dict[str, str] = {}
    for axis_key, option_key in (picks or {}).items():
        a = _axis(axis_key)
        if a is None:
            continue
        if a.get("kind") == "surface" and a.get("applies_to") != surface:
            continue
        out[a["axis"]] = option_key
    return out


def max_concurrent_strong() -> Optional[int]:
    """The §11.6 soft-cap on concurrently-selected strong modifiers. Data from
    Phase 0, null until the Phase 3 calibration pass measures the ceiling."""
    v = _load()["registry"].get("max_concurrent_strong")
    return v if isinstance(v, int) and not isinstance(v, bool) else None


# ---------------------------------------------------------------------------
# Surface resolution — the §3.2 keyword tier for uncatalogued animals.
# Catalogued animals resolve from their catalog tag (animal_catalog.
# resolved_surface); this map answers for the typed long tail. It is seeded
# per-WORD from the motion registry's keyword lists — never per movement class,
# because winged_flyer (dragon=scales, bat=fur) and aquatic (fish=scales,
# dolphin=skin) are mixed-surface classes; that mix is exactly why surface is
# not a motion field (§0.4).
# ---------------------------------------------------------------------------
def _keywords() -> dict:
    global _KEYWORDS
    if _KEYWORDS is None:
        with _LOCK:
            if _KEYWORDS is None:
                _KEYWORDS = json.loads(_SURFACE_KEYWORDS_FILE.read_text())
    return _KEYWORDS


def resolve_surface(animal: Optional[str]) -> Optional[str]:
    """Resolve a typed animal name to a surface, or None (§3.2/§3.3).

    Word-boundary, case-insensitive; the LONGEST matching keyword wins across
    all surfaces (mirroring motion's classifier tie-break), so "guinea pig"
    beats "pig" if both are ever mapped. None means "not confident": the design
    step then shows only the universal axes — it never guesses fur onto a
    clockwork octopus. Typed animals that resolve to None are the keyword map's
    growth list; the caller logs them (§3.2)."""
    if not animal:
        return None
    name = animal.strip().lower()
    if not name:
        return None
    best_len, best_surface = 0, None
    for surface, words in _keywords().get("surfaces", {}).items():
        for kw in words:
            if len(kw) > best_len and re.search(rf"\b{re.escape(kw)}\b", name):
                best_len, best_surface = len(kw), surface
    return best_surface
