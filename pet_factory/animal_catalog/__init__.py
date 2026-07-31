"""animal_catalog — the curated base-animal library as content, not code.

The catalog is the "base image + breed" layer of the designer platform
(SPEC_PET_DESIGNER_PLATFORM §4). It is pure data — a `catalog.json` index plus
one `base.png` per animal/breed — so it imports on the GPU-less web tier with no
ML dependency (the same `--no-deps -e` deploy posture the motion profiles
established, §4.2 "Deploy posture").

What it provides:
  - load_catalog()                     — the parsed catalog.json, cached.
  - list_animals()                     — the animal/breed tree for /api/catalog.
  - base_image_path(animal, breed)     — the on-disk base.png for a breed, or None.
  - resolved_motion_profile(animal, breed) — the pinned motion_profile key for a
                                         breed (§4.2): the breed's own key if it
                                         declares one, else the animal's key.

Boundary (§0): the catalog declares WHICH base image + WHICH motion_profile key;
it does NOT know how motion resolves (that's motion_profiles) or how generation
works (that's factory). A themed page reads this tree; the engine never does.

There is NO cross-layer coupling in the resolver: `resolved_motion_profile`
returns a *key string* — validating that the key exists in the motion registry is
a guard test's job (tests/test_animal_catalog.py), not a runtime import, so a bad
catalog entry fails the build, never a user request.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Optional

_DIR = Path(__file__).resolve().parent
_CATALOG_FILE = _DIR / "catalog.json"

_LOCK = threading.Lock()
_CATALOG: Optional[dict] = None


def load_catalog() -> dict:
    """The parsed catalog.json, read once and cached (it ships read-only)."""
    global _CATALOG
    if _CATALOG is None:
        with _LOCK:
            if _CATALOG is None:
                _CATALOG = json.loads(_CATALOG_FILE.read_text())
    return _CATALOG


def reload() -> None:
    """Drop the in-memory catalog cache so the next read re-reads disk. Called
    by the admin write path (animal_catalog.admin) after a design-profile write
    (SPEC_PET_DESIGN_AXES_ADMIN §1.2) so /api/catalog and /api/design-axes
    reflect the change with no restart."""
    global _CATALOG
    with _LOCK:
        _CATALOG = None


def list_animals() -> list[dict]:
    """The animal list (each with its breeds) — the source for /api/catalog and
    the landing-page tiles. Returns the raw catalog entries; the API layer shapes
    the response (it decides which fields the browser sees)."""
    return load_catalog().get("animals", [])


def _animal(animal_key: str) -> Optional[dict]:
    return next((a for a in list_animals() if a.get("key") == animal_key), None)


def _breed(animal_key: str, breed_key: str) -> Optional[dict]:
    animal = _animal(animal_key)
    if animal is None:
        return None
    return next((b for b in animal.get("breeds", []) if b.get("key") == breed_key), None)


def resolved_motion_profile(animal_key: str, breed_key: Optional[str] = None) -> Optional[str]:
    """The pinned motion_profile key for a breed (§4.2), most-specific-wins:
    the breed's own `motion_profile` if it declares one (a level-1 file exists),
    else the animal row's key. Returns None if the animal isn't in the catalog.
    NO inference — the key is authored; whether it *resolves* is a guard test."""
    animal = _animal(animal_key)
    if animal is None:
        return None
    if breed_key:
        breed = _breed(animal_key, breed_key)
        if breed and breed.get("motion_profile"):
            return breed["motion_profile"]
    return animal.get("motion_profile")


def resolved_surface(animal_key: str, breed_key: Optional[str] = None) -> Optional[str]:
    """The authored `surface` tag for a breed (SPEC_PET_DESIGN_AXES §3.1),
    most-specific-wins exactly like resolved_motion_profile: the breed's own
    `surface` if it declares one (a Sphynx diverging from `cat`), else the
    animal row's. Returns None if the animal isn't in the catalog. NO inference
    — the tag is authored; that it matches a surface axis's `applies_to` is a
    guard test's job (tests/test_animal_catalog.py), not a runtime import."""
    animal = _animal(animal_key)
    if animal is None:
        return None
    if breed_key:
        breed = _breed(animal_key, breed_key)
        if breed and breed.get("surface"):
            return breed["surface"]
    return animal.get("surface")


def resolved_surface_options(animal_key: str, breed_key: Optional[str] = None) -> Optional[list[str]]:
    """The per-breed `surface_options` restriction (SPEC_PET_DESIGN_AXES_ADMIN
    §3.2: "Sphynx offers only hairless"), most-specific-wins like the other
    resolvers. None means unrestricted — the surface axis offers its full
    vocabulary. The axis's own default is ALWAYS offered regardless (the read
    layer enforces that; a menu must always offer "leave it alone")."""
    animal = _animal(animal_key)
    if animal is None:
        return None
    if breed_key:
        breed = _breed(animal_key, breed_key)
        if breed and breed.get("surface_options") is not None:
            return breed["surface_options"]
    return animal.get("surface_options")


def resolved_surface_default(animal_key: str, breed_key: Optional[str] = None) -> Optional[str]:
    """The per-breed `surface_default` ("Persian defaults to long-haired"),
    most-specific-wins. PERSISTED and validated but READ-INERT for now: whether
    a breed default means "preselect it" or "treat it as the no-op" is an
    unresolved semantic (SPEC_PET_DESIGN_AXES_ADMIN §9.5) — the field exists so
    resolving it later is a read-layer change, not a data migration."""
    animal = _animal(animal_key)
    if animal is None:
        return None
    if breed_key:
        breed = _breed(animal_key, breed_key)
        if breed and breed.get("surface_default"):
            return breed["surface_default"]
    return animal.get("surface_default")


def base_image_path(animal_key: str, breed_key: str) -> Optional[Path]:
    """The on-disk curated base.png for an animal/breed, or None if the entry or
    the file is absent. The file layout is `<animal>/<breed>/base.png` (§4.2).
    A missing base is not an error here — the caller (API) turns it into a 404,
    and the un-curated long tail falls back to the General path (§4.5)."""
    if _breed(animal_key, breed_key) is None:
        return None
    path = _DIR / animal_key / breed_key / "base.png"
    return path if path.is_file() else None


# The samples/adopt-a-premade surface that stood here (list_samples,
# sample_bundle_path, sample_preview_path) was retired by SPEC_PET_STORE §8:
# premade pets are DB-backed store inventory now (webui/pet_store.py), stocked
# at runtime through the store admin. The `<animal>/samples/` content files
# that outlived the code by one deploy cycle are gone too (every environment
# migrated 2026-07-31, §14.4) — nothing under this package reads samples.
