"""pet_athletics — mint the athletics block at build (SPEC_PET_ARENA §4).

Placement follows the pet_ownership.py precedent: not db.py (record view), not
app.py (HTTP surface). The block is the FOURTH patch at the `_finalize_pet_from_zip`
seam — upstream of insert_pet so the derived bundle_sha256 covers the stamped
bytes, and NOT in the packer (§4.2): the packer runs on pool GPU nodes, cannot
see the design inputs, and game balance must not require a fleet roll to change.

The roll is minted from the sheet bytes with §5.2's algorithm — the same one the
read-time derivation uses for legacy pets — so stamping is a PRECOMPUTATION of
the derivation, not a fork of it: a stamped and an unstamped copy of the same
bundle are the same athlete. (The stamp still matters: it freezes the numbers
under the table version that minted them, which is what makes a later rebalance
detectable and identity-preserving — §5.3.)

Design modifiers (§3.2) fold in automatically once the design block exists in
the manifest: `resolve_athletics` reads `design.picks` when present. Until
SPEC_PET_DESIGN_PROVENANCE Phase 2 stamps it, modifiers are simply inert — the
§4.2 dependency, stated there.

GPU-less posture: `pet_factory.athletics` is a pure-stdlib data package; nothing
here may import the ML stack.
"""
from __future__ import annotations

import io
import json
import zipfile
from typing import Optional, Tuple

from pet_factory import athletics

#: The manifest key the stamp owns (§4.1).
ATHLETICS_KEY = "athletics"
#: §4.1 — when the block was minted; bundle wire format (UTC ISO-8601 `Z`).
MINTED_AT_KEY = "minted_at"

#: Bundle member names — same contract as pet_ownership: everything except
#: manifest.json is carried through byte-for-byte under its original name.
MANIFEST_MEMBER = "manifest.json"
SPRITE_MEMBER_SUFFIX = "_sprite.png"


class AthleticsStampError(ValueError):
    """A caller tried to stamp a bundle no reader could have produced."""


def set_pet_athletics(manifest_json: str, *, sheet_png: Optional[bytes],
                      at: str) -> str:
    """Write the athletics block onto a MANIFEST (§4.1). The manifest-level
    writer, mirroring `pet_ownership.set_pet_ownership`.

    NO-OP WHEN CURRENT: a manifest already carrying a valid block under the
    current table version returns the input string unchanged — same object — so
    re-running the seam (a pool reattach, a future re-stamp path) never churns
    bytes or timestamps. A STALE block (bumped table version) is recomputed
    reusing its stored roll, so identity survives the rebalance (§5.3).

    It PATCHES the manifest and never rebuilds one — every other key passes
    through untouched, the same rule that keeps `fingerprint` alive across
    ownership transfers.
    """
    if not isinstance(at, str) or not at.endswith("Z"):
        raise AthleticsStampError(
            f"minted_at must be a UTC ISO-8601 string ending in 'Z', got {at!r} "
            f"— use pet_ownership.utc_now_iso()/epoch_to_utc_iso()")
    manifest = json.loads(manifest_json)
    if athletics.block_is_current(manifest.get(ATHLETICS_KEY)):
        return manifest_json
    block = dict(athletics.resolve_athletics(manifest, sheet_png))
    block[MINTED_AT_KEY] = at
    manifest[ATHLETICS_KEY] = block
    # indent=2 matches the packer's own manifest formatting (factory.py).
    return json.dumps(manifest, indent=2)


def stamp_pet_athletics(zip_bytes: bytes, *, at: str) -> Tuple[bytes, str]:
    """`set_pet_athletics` applied to a bundle — reads the sprite sheet out of
    the zip for the roll (§5.2: the bytes ARE the identity source), patches
    manifest.json, carries every other member across byte-for-byte.

    Returns `(zip_bytes, manifest_json)`, the pair insert_pet stores together.
    Inherits the no-op rule: a bundle already stamped under the current table
    returns the ORIGINAL zip object.
    """
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as src:
        names = src.namelist()
        if MANIFEST_MEMBER not in names:
            raise AthleticsStampError(f"bundle has no {MANIFEST_MEMBER}")
        members = {name: src.read(name) for name in names}

    sheet_png = next(
        (members[name] for name in names if name.endswith(SPRITE_MEMBER_SUFFIX)),
        None)
    before = members[MANIFEST_MEMBER].decode("utf-8")
    after = set_pet_athletics(before, sheet_png=sheet_png, at=at)
    if after is before:
        return zip_bytes, before

    members[MANIFEST_MEMBER] = after.encode("utf-8")
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for name in names:
            dst.writestr(name, members[name])
    return out.getvalue(), after
