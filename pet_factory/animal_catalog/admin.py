"""animal_catalog.admin — the per-animal DESIGN-PROFILE write path.

The read path lives in `__init__.py` (the catalog tree, resolvers, cached).
This module is the narrow mutation side the design admin's Animals tab uses
(SPEC_PET_DESIGN_AXES_ADMIN §1.2): it may write ONLY the design-profile fields
— `surface`, `surface_default`, `surface_options` — onto a catalog entry,
leaving `base.png`, breed identity, `motion_profile`, and everything a promote
script owns untouched (§0.5). The allowed-field guard is structural: the write
takes exactly those three as keyword arguments, and the whole-entry rewrite
preserves every other key verbatim, so a design edit physically cannot corrupt
a vetted base.

`validate_design_profile` is shared with the catalog guard test
(tests/test_animal_catalog.py — "catalog surface integrity"): the admin is
blocked at save, the build is blocked at test, by the same function (§0.2).

Cross-layer note: this WRITE path imports design_axes to validate that a
surface has an axis and the option keys are real — deliberately. The READ path
(`__init__.py`) stays uncoupled ("the catalog declares a key; validating it is
a guard test's job"); the write path is exactly where save-time validation must
live, per the admin spec's load-bearing invariant.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from . import _CATALOG_FILE, _LOCK, reload as _reload_cache
from .. import design_axes

ALLOWED_FIELDS = ("surface", "surface_default", "surface_options")

# The sentinel for "leave this field as it is" — distinct from None, which
# means "unset it (a breed falls back to inheriting the animal's value)".
KEEP = object()


class CatalogWriteError(ValueError):
    """A write refused for a content reason. `errors` carries the
    validate_design_profile list when the cause was validation."""

    def __init__(self, message: str, errors: Optional[list[str]] = None):
        super().__init__(message)
        self.errors = errors or [message]


def load_catalog_raw() -> dict:
    """The raw catalog.json, re-read from disk each call (the admin needs the
    live state, not the cached view)."""
    return json.loads(_CATALOG_FILE.read_text())


def validate_design_profile(
    *,
    surface: Optional[str],
    surface_default: Optional[str],
    surface_options: Optional[list],
    effective_surface: Optional[str],
) -> list[str]:
    """Return errors for a candidate design profile (empty = valid). Shared
    with the catalog guard test — one definition of valid (§0.2).

    `surface` None is legal only when something is still inherited
    (`effective_surface` — what the entry resolves to AFTER this write — is
    non-null): a curated entry must always resolve a surface (§3.1), or the
    design step degrades a vetted animal to the unknown-animal posture.
    `surface_default` / each `surface_options` entry must be a real option key
    of the effective surface's axis, so a typo can't ship a breed whose menu
    silently never appears."""
    errors: list[str] = []

    known = design_axes.known_surfaces()
    if surface is not None and surface not in known:
        errors.append(
            f"surface {surface!r} matches no surface axis's applies_to ({sorted(known)})"
        )
    if not effective_surface:
        errors.append(
            "the entry must still resolve a surface after this write — a curated "
            "animal is the confident tier (SPEC_PET_DESIGN_AXES §3.1)"
        )
        return errors  # option checks below need an effective surface

    axis_key = design_axes.surface_axis_key(effective_surface)
    axis = design_axes.public_axis(axis_key) if axis_key else None
    option_keys = {o["key"] for o in axis["options"]} if axis else set()

    if surface_default is not None:
        if surface_default not in option_keys:
            errors.append(
                f"surface_default {surface_default!r} is not an option of the "
                f"{axis_key!r} axis ({sorted(option_keys)})"
            )
        elif surface_options is not None and surface_default not in surface_options \
                and axis and surface_default != axis["default"]:
            errors.append(
                f"surface_default {surface_default!r} is excluded by surface_options — "
                "a default the menu can't offer is unpickable"
            )

    if surface_options is not None:
        if not isinstance(surface_options, list) or \
                not all(isinstance(k, str) for k in surface_options):
            errors.append("surface_options must be a list of option-key strings")
        else:
            for k in surface_options:
                if k not in option_keys:
                    errors.append(
                        f"surface_options entry {k!r} is not an option of the "
                        f"{axis_key!r} axis ({sorted(option_keys)})"
                    )

    return errors


def set_design_profile(
    animal_key: str,
    breed_key: Optional[str] = None,
    *,
    surface=KEEP,
    surface_default=KEEP,
    surface_options=KEEP,
) -> dict:
    """Write the design-profile fields onto one catalog entry and reload.

    `breed_key` unset → the animal-level default all breeds inherit; set → one
    breed's override. Each field: KEEP (untouched), None (unset — a breed falls
    back to inheritance; refused if it would leave nothing resolved), or a
    value. Only the ALLOWED_FIELDS keys are ever written; every other key on
    the entry is preserved verbatim (§0.5). Returns the resolved profile after
    the write. Raises CatalogWriteError on validation failure or unknown entry.
    """
    with _LOCK:
        catalog = load_catalog_raw()
        animal = next((a for a in catalog.get("animals", [])
                       if a.get("key") == animal_key), None)
        if animal is None:
            raise CatalogWriteError(f"animal {animal_key!r} is not in the catalog")
        target = animal
        if breed_key:
            target = next((b for b in animal.get("breeds", [])
                           if b.get("key") == breed_key), None)
            if target is None:
                raise CatalogWriteError(
                    f"breed {animal_key}/{breed_key} is not in the catalog")

        new = {
            "surface": target.get("surface") if surface is KEEP else surface,
            "surface_default": target.get("surface_default")
                if surface_default is KEEP else surface_default,
            "surface_options": target.get("surface_options")
                if surface_options is KEEP else surface_options,
        }
        # What the entry resolves to AFTER the write (breed → animal fallback).
        effective_surface = new["surface"] or (
            animal.get("surface") if breed_key else None)

        errs = validate_design_profile(
            surface=new["surface"],
            surface_default=new["surface_default"],
            surface_options=new["surface_options"],
            effective_surface=effective_surface,
        )
        if errs:
            raise CatalogWriteError("design profile failed validation", errs)

        # Apply ONLY the allowed fields; absent-when-None keeps entries lean and
        # keeps inheritance visible in the file (a breed with no `surface` key
        # inherits — exactly how `motion_profile` reads today).
        for field, value in new.items():
            if value is None:
                target.pop(field, None)
            else:
                target[field] = value

        tmp = _CATALOG_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n")
        tmp.replace(_CATALOG_FILE)

    _reload_cache()
    return new
