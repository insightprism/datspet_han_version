"""design_axes.admin — the WRITE path for the design-axis registry (content editing).

The read path lives in `__init__.py` (axes_for_surface/prompt_fragment, cached).
This module is the mutation side the admin surface uses
(SPEC_PET_DESIGN_AXES_ADMIN §1.1): validate an axis against the exact guard-test
contract, then write/delete the file + registry entry and bust the in-memory
cache. Pure data, no ML — imports on the GPU-less web tier like the rest of the
package.

Boundary (§0.2): `validate_axis` is the SINGLE definition of "a valid axis" —
the guard test (tests/test_design_axes.py) and the admin endpoint both call it,
so the admin can never write an axis the build would reject: an empty
non-default fragment (a dead control), a surface axis with no applies_to, a
second axis claiming an already-served surface — all die in one place.

Unlike motion's registry (sorted by key), the design registry's order is MENU
ORDER and load-bearing (§1) — writes PRESERVE it; a new axis appends last.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from . import _DIR, _LOCK, reload as _reload_cache

# An axis key becomes a filename AND a URL path segment — the same conservative
# slug motion admin uses: lowercase start, then lowercase/digits/underscore.
_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")
# Option keys ride form values (axis_picks) and the option-key sanitizer
# lowercases at 30 chars — pin the shape here so a key survives the round trip.
_OPTION_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,29}$")

VALID_KINDS = {"universal", "surface"}
VALID_POSITIONS = {"prefix", "suffix"}
# The web tier clamps strength to [0.3, 0.9], so a min_strength above 0.9 would
# be silently unreachable — a content error worth refusing at save.
_MIN_STRENGTH_RANGE = (0.3, 0.9)


def _registry_path() -> Path:
    return _DIR / "registry.json"


def load_registry() -> dict:
    """The raw registry.json (re-read from disk each call — the admin needs the
    live on-disk state, not the cached copy)."""
    return json.loads(_registry_path().read_text())


def _registry_keys(registry: dict) -> list[str]:
    return [e["key"] for e in registry.get("axes", []) if e.get("key")]


def validate_axis(
    raw: dict,
    *,
    registry: dict,
    existing_key: Optional[str] = None,
) -> list[str]:
    """Return a list of human-readable errors for a candidate axis (empty =
    valid). The EXACT contract the guard test asserts — the one definition of
    "valid", shared by the test and the admin endpoint (§0.2).

    `existing_key`: when editing, the key being written; the applies_to
    uniqueness check ignores that key's own current claim. None for a create.
    """
    errors: list[str] = []

    key = raw.get("axis")
    if not isinstance(key, str) or not _KEY_RE.match(key):
        errors.append(
            f"axis must match {_KEY_RE.pattern!r} (lowercase, digits, underscore) — got {key!r}"
        )

    if not isinstance(raw.get("label"), str) or not raw["label"].strip():
        errors.append("label is required and must be a non-empty string")

    kind = raw.get("kind")
    if kind not in VALID_KINDS:
        errors.append(f"kind must be one of {sorted(VALID_KINDS)} — got {kind!r}")

    # --- surface gating: applies_to required for surface, forbidden otherwise,
    # and unique across the registry (§0.3: exactly ONE axis serves a surface).
    applies_to = raw.get("applies_to")
    if kind == "surface":
        if not isinstance(applies_to, str) or not applies_to.strip():
            errors.append("a surface axis must declare a non-empty applies_to")
        else:
            for entry in registry.get("axes", []):
                if entry.get("key") == existing_key:
                    continue
                path = _DIR / f"{entry['key']}.json"
                try:
                    other = json.loads(path.read_text())
                except (OSError, json.JSONDecodeError):
                    continue
                if other.get("kind") == "surface" and other.get("applies_to") == applies_to:
                    errors.append(
                        f"applies_to {applies_to!r} already served by axis {entry['key']!r} "
                        "— exactly one axis per surface"
                    )
    elif applies_to is not None:
        errors.append("only a surface axis may declare applies_to")

    if not isinstance(raw.get("clause_slot"), int) or isinstance(raw.get("clause_slot"), bool):
        errors.append(f"clause_slot must be an integer — got {raw.get('clause_slot')!r}")

    if raw.get("position") not in VALID_POSITIONS:
        errors.append(
            f"position must be one of {sorted(VALID_POSITIONS)} — got {raw.get('position')!r}"
        )

    ms = raw.get("min_strength")
    if ms is not None:
        if isinstance(ms, bool) or not isinstance(ms, (int, float)):
            errors.append(f"min_strength must be a number or null — got {ms!r}")
        elif not (_MIN_STRENGTH_RANGE[0] <= float(ms) <= _MIN_STRENGTH_RANGE[1]):
            errors.append(
                f"min_strength must be within {_MIN_STRENGTH_RANGE} (the web tier's "
                f"strength clamp — above 0.9 is unreachable) — got {ms!r}"
            )

    if not isinstance(raw.get("_doc"), str) or not raw["_doc"].strip():
        errors.append("_doc is required — content files carry their own rationale")

    # --- options: the vocabulary itself ---
    options = raw.get("options")
    if not isinstance(options, list) or not options:
        errors.append("options must be a non-empty list")
        options = []
    seen_keys: set[str] = set()
    for o in options:
        if not isinstance(o, dict):
            errors.append(f"option {o!r} must be an object")
            continue
        okey = o.get("key")
        if not isinstance(okey, str) or not _OPTION_KEY_RE.match(okey):
            errors.append(
                f"option key must match {_OPTION_KEY_RE.pattern!r} — got {okey!r}"
            )
            continue
        if okey in seen_keys:
            errors.append(f"option key {okey!r} listed twice")
        seen_keys.add(okey)
        if not isinstance(o.get("label"), str) or not o["label"].strip():
            errors.append(f"option {okey!r} has no label")
        frag = o.get("prompt_fragment")
        if not isinstance(frag, str):
            errors.append(f"option {okey!r} has no prompt_fragment string")
        elif frag != frag.strip():
            errors.append(
                f"option {okey!r}'s fragment has loose whitespace — it composes verbatim"
            )

    # --- the default: exists, and the two load-bearing fragment rules ---
    default = raw.get("default")
    if not isinstance(default, str) or default not in seen_keys:
        errors.append(f"default must name an option in the list — got {default!r}")
    else:
        for o in options:
            if not isinstance(o, dict) or not isinstance(o.get("prompt_fragment"), str):
                continue
            if o.get("key") == default:
                if o["prompt_fragment"] != "":
                    errors.append(
                        f"the default option {default!r} must have fragment exactly \"\" — "
                        "a default contributes no words"
                    )
            elif o.get("key") in seen_keys and o["prompt_fragment"] == "":
                errors.append(
                    f"option {o['key']!r} is selectable but changes nothing — a non-default "
                    "option must carry a fragment (§12 Tier C: the dead-control class)"
                )

    return errors


# ---------------------------------------------------------------------------
# Write / delete primitives. Each validates, mutates file + registry, then
# busts the loader cache so the change is live immediately.
# ---------------------------------------------------------------------------
class AxisWriteError(ValueError):
    """A write/delete refused for a content reason. `errors` carries the
    validate_axis list when the cause was validation; else a single message."""

    def __init__(self, message: str, errors: Optional[list[str]] = None):
        super().__init__(message)
        self.errors = errors or [message]


def _axis_file(key: str) -> Path:
    return _DIR / f"{key}.json"


def _write_registry(registry: dict) -> None:
    """Persist registry.json PRESERVING axis order — order is menu order (§1),
    unlike motion's sorted-by-key registry. `_doc` and `max_concurrent_strong`
    ride along untouched."""
    tmp = _registry_path().with_suffix(".json.tmp")
    tmp.write_text(json.dumps(registry, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(_registry_path())


def write_axis(raw: dict, *, existing_key: Optional[str] = None) -> dict:
    """Validate + write an axis file and upsert its registry entry (order
    preserved; a create appends last), then reload the cache. `existing_key`
    set → an update (must already be registered); None → a create (must not).
    Returns the registry entry written. Raises AxisWriteError otherwise."""
    with _LOCK:
        registry = load_registry()
        keys = _registry_keys(registry)
        key = raw.get("axis")

        errs = validate_axis(raw, registry=registry, existing_key=existing_key)
        if errs:
            raise AxisWriteError("axis failed validation", errs)

        if existing_key is None:
            if key in keys:
                raise AxisWriteError(f"axis {key!r} already exists")
        else:
            if existing_key not in keys:
                raise AxisWriteError(f"axis {existing_key!r} does not exist")
            if key != existing_key:
                raise AxisWriteError(
                    f"key rename not supported here (got {key!r}, editing {existing_key!r}); "
                    "create under the new key + delete the old"
                )

        tmp = _axis_file(key).with_suffix(".json.tmp")
        tmp.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n")
        tmp.replace(_axis_file(key))

        if key not in keys:
            registry.setdefault("axes", []).append({"key": key})
            _write_registry(registry)

    _reload_cache()
    return {"key": key}


def delete_axis(key: str, *, used_by: Optional[list[str]] = None) -> None:
    """Remove an axis file + its registry entry, then reload. Refuses when the
    axis is a surface axis still referenced by the catalog (`used_by` is the
    list of catalog references the caller resolved — non-empty → refuse): the
    rev.2 delete guard, §0.2's invariant applied to deletes. Without it,
    deleting plumage while a bird tags feathers creates exactly the broken
    state the build guard rejects. Universal axes carry no catalog reference
    and delete freely."""
    with _LOCK:
        registry = load_registry()
        if key not in _registry_keys(registry):
            raise AxisWriteError(f"axis {key!r} does not exist")
        if used_by:
            raise AxisWriteError(
                f"axis {key!r} is still used by catalog entries: {used_by} — "
                "retag those animals first"
            )
        registry["axes"] = [e for e in registry["axes"] if e.get("key") != key]
        _write_registry(registry)
        f = _axis_file(key)
        if f.exists():
            f.unlink()
    _reload_cache()
