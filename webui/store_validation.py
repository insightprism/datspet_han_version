"""store_validation — the ONE definition of "sellable" (SPEC_PET_STORE §5.3).

A store pet is sellable iff its bundle unpacks, carries a sprite sheet and a
parseable manifest with at least one animation, has a portrait, a non-empty
display name, and a non-empty animal (the shop's filter chips depend on it).

Three callers, one function (the validate_design_profile pattern): the admin
publish gate refuses at save, the guard tests refuse at build, and Phase 2's
donation-approval door will refuse at review — all with the same code, so the
admin can never ship a listing the build would reject.

This is the current guard-test checklist (formerly
pet_factory/tests/test_catalog_samples.py) lifted into a shared function.
Imports are stdlib only — the GPU-less posture.
"""
from __future__ import annotations

import io
import json
import zipfile

#: The bundle member names the checks look for — the same contract
#: app._unpack_bundle matches on (a renamed member is an unrenderable pet).
SPRITE_SUFFIX = "_sprite.png"
MANIFEST_MEMBER = "manifest.json"


def sellability_errors(*, bundle_zip: bytes, preview_png: bytes,
                       display_name: str, animal: str) -> list[str]:
    """Every reason this store pet may not be sold, in human-readable form.
    Empty list = sellable. Never raises — a broken artifact is a REPORT here;
    refusing is the caller's move (422 at the admin door, assert in the guard)."""
    errors: list[str] = []

    if not (display_name or "").strip():
        errors.append("display_name is empty")
    if not (animal or "").strip():
        errors.append("animal is empty — the shop's filter chips depend on it")
    if not preview_png:
        errors.append("preview portrait is missing")

    if not bundle_zip:
        errors.append("bundle is empty")
        return errors

    try:
        with zipfile.ZipFile(io.BytesIO(bundle_zip)) as z:
            names = z.namelist()
            if not any(n.endswith(SPRITE_SUFFIX) for n in names):
                errors.append(f"bundle has no *{SPRITE_SUFFIX} sprite sheet")
            if MANIFEST_MEMBER not in names:
                errors.append(f"bundle has no {MANIFEST_MEMBER}")
                return errors
            manifest_raw = z.read(MANIFEST_MEMBER).decode("utf-8")
    except (zipfile.BadZipFile, OSError, UnicodeDecodeError):
        errors.append("bundle is not a readable zip")
        return errors

    try:
        manifest = json.loads(manifest_raw)
    except json.JSONDecodeError:
        errors.append("manifest.json is not valid JSON")
        return errors
    animations = manifest.get("animations") if isinstance(manifest, dict) else None
    if not (isinstance(animations, dict) and animations):
        errors.append("manifest declares no animations — the pet has no poses "
                      "and could never be priced")
    return errors
