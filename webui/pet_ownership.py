"""webui/pet_ownership.py — who owns a pet bundle (SPEC_PET_OWNER_FIELD).

THE one place in this repo that writes an `owner_*` field into a bundle, and the
one place that reads one back (spec §0.3, §2.1, §2.2).

WHAT DATSPET WRITES, AND WHAT IT DOES NOT (§2.4). DatsPet never sells and never
gifts, so it never writes an owner. It writes the UNSOLD state — `factory` at
mint, `public` for a curated sample — and stops. **Every ownership change happens
on DatsMe**, at the two places a transfer actually occurs: the checkout
(`handle_target_user_pet`) and the gift (`accept_offer`). The host holds the
`User` at both, so the owner's slug costs it nothing.

That boundary is the whole design (§8, "things that change for the same reason
live together"). An earlier revision had DatsPet stamp the buyer at `keep`, which
forced it to learn the buyer's slug over the network on the purchase path and
created an ordering trap: DatsPet would have been rewriting a bundle whose digest
it had already advertised. Moving the stamp to the host deleted both problems.
**Do not reintroduce an owner write here.**

THE NAME IS A NAME (§0.5). `owner_name` holds the DatsMe slug (`sara.1`) or a
group's normalized tag (`#black#zebra`) — never a display name, never an internal
id. A portable record has to be readable by the person holding the file, and a
slug resolves at `GET /api/profiles/{name_slug}` for anyone. Slugs are unique and
minted once at signup, with no rename path in the host tree; if that ever changes,
§7.2 is the section to revisit.

Imports are `json` + `zipfile` + `datetime` and nothing else — this module sits on
the GPU-less web tier and must never drag in the ML stack (CLAUDE.md).
"""
from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timezone
from typing import Optional, Tuple

# ---------------------------------------------------------------------------
# The vocabulary (§1.1). Named constants, never strings typed at a call site (§8).
# ---------------------------------------------------------------------------

FACTORY_CATEGORY = "factory"
INDIVIDUAL_CATEGORY = "individual"
GROUP_CATEGORY = "group"
PUBLIC_CATEGORY = "public"

#: Closed set. An unknown category is REFUSED, never treated as `public`, so a
#: future fifth value cannot fail open on a reader that predates it.
OWNER_CATEGORIES = frozenset({
    FACTORY_CATEGORY, INDIVIDUAL_CATEGORY, GROUP_CATEGORY, PUBLIC_CATEGORY,
})

#: `owner_name` while a pet is minted-but-unsold. NOT `individual` with this name:
#: `individual` means "resolve this against User.name_slug", and datspet is not a
#: DatsMe user — the host would attempt that lookup for EVERY pet in the pull
#: channel (they are all `factory`) and log a phantom missing-user error each time
#: (§1.1).
FACTORY_OWNER_NAME = "datspet"

#: The issuer mark (§1.7). Stamped ONCE, at mint, by DatsPet only — the host never
#: writes it and every host-side transfer must preserve it. DELIBERATELY a separate
#: constant from FACTORY_OWNER_NAME even though both are "datspet" today: they mean
#: different things, and the whole point of a placeholder is that its value will
#: change. Sharing one constant would couple two facts that only coincidentally
#: agree.
BUNDLE_FINGERPRINT = "datspet"

# Manifest keys.
FINGERPRINT_KEY = "fingerprint"
CATEGORY_KEY = "owner_category"
NAME_KEY = "owner_name"
TRANSFERRED_AT_KEY = "owner_transferred_at"

#: The bundle member every stamp patches. The other members (the sprite sheet,
#: package.json) are copied through byte-for-byte under their original names —
#: `app._unpack_bundle` matches on those names, so renaming one breaks rendering.
MANIFEST_MEMBER = "manifest.json"

#: The wire datetime format (§1.3). UTC, ISO-8601, `Z` suffix. The store keeps
#: unix epoch floats, so the stamp converts at the bundle boundary rather than
#: leaking the storage format into the artifact.
_ISO_Z = "%Y-%m-%dT%H:%M:%SZ"


def utc_now_iso() -> str:
    """Now, as the bundle wire format."""
    return datetime.now(timezone.utc).strftime(_ISO_Z)


def epoch_to_utc_iso(epoch: float) -> str:
    """A stored epoch float as the bundle wire format."""
    return datetime.fromtimestamp(epoch, timezone.utc).strftime(_ISO_Z)


class OwnerFieldError(ValueError):
    """A caller tried to write owner fields that no reader would accept."""


# ---------------------------------------------------------------------------
# The writer (§2.1) and the reader (§2.2)
# ---------------------------------------------------------------------------

def set_pet_ownership(manifest_json: str, *, category: str, name: str,
                      at: str) -> str:
    """Set the three owner fields on a MANIFEST. **THE ownership writer** (§2.1).

    Takes and returns `manifest.json` as a string — the level both repos share,
    and the ONLY level DatsMe needs. The host stores a pet's parts, not its zip
    (`write_assets(manifest_json=…)`), and rebuilds bundles on demand with
    `build_bundle_zip`, so its two stamp sites are one line each:

        parsed["manifest_json"] = set_pet_ownership(
            parsed["manifest_json"], category=INDIVIDUAL, name=user_slug,
            at=ownership_created_at)

    DatsPet needs the zip wrapper below because its stored artifact IS the zip.
    That asymmetry is why this split exists: the ~20 lines each repo duplicates
    (§2.3a) are these, not the zip plumbing.

    NO-OP WHEN NOTHING CHANGED. If the manifest already carries this
    `(category, name)`, **the input string is returned unchanged — same object**,
    so a caller can test `result is manifest_json` to know nothing was written.
    Both host stamp sites re-run for one pet (a re-checkout, a re-gift), and
    without this rule "since when do you own this" would drift to "when you last
    clicked buy". Note it is keyed on `(category, name)` only: a re-run with a
    later `at` for the same owner is exactly the case being suppressed.

    It PATCHES the manifest and never rebuilds one. Every other key —
    `fingerprint`, the animations, the geometry, the view blocks, anything a
    future spec adds — passes through untouched. Rebuilding from a known field
    list is how `fingerprint` vanishes on the first sale, and how the next
    additive field would too.
    """
    _validate(category=category, name=name, at=at)
    manifest = json.loads(manifest_json)
    if (manifest.get(CATEGORY_KEY), manifest.get(NAME_KEY)) == (category, name):
        return manifest_json
    manifest[CATEGORY_KEY] = category
    manifest[NAME_KEY] = name
    manifest[TRANSFERRED_AT_KEY] = at
    return _dump(manifest)


def set_bundle_fingerprint(manifest_json: str) -> str:
    """Mark a manifest as DatsPet-issued (§1.7). Stamped once, at mint.

    A SEPARATE writer from `set_pet_ownership` on purpose: the owner fields change
    at every transfer AND are written by the host, while the fingerprint never
    changes and the host never writes it. Different cadence, different writer,
    different repo — so no transfer can disturb it, and a reader can trust it
    means "who issued this" rather than "who last touched this".

    Nothing reads it today. It is stamped now because bundles are immutable
    artifacts: a pet minted before the field exists can never carry it, and
    back-filling means regenerating pets at GPU cost. DO NOT DELETE IT for being
    unused — see §1.7, which is where its reader gets specified when one exists.

    Idempotent, with the same same-object contract as `set_pet_ownership`.
    """
    manifest = json.loads(manifest_json)
    if manifest.get(FINGERPRINT_KEY) == BUNDLE_FINGERPRINT:
        return manifest_json
    manifest[FINGERPRINT_KEY] = BUNDLE_FINGERPRINT
    return _dump(manifest)


# ---------------------------------------------------------------------------
# The zip wrappers — DatsPet only (§2.4). DatsMe stores parts, not bundles, and
# calls the two functions above directly.
# ---------------------------------------------------------------------------

def transfer_pet_ownership(zip_bytes: bytes, *, category: str, name: str,
                           at: str) -> Tuple[bytes, str]:
    """`set_pet_ownership` applied to a bundle.

    Returns `(zip_bytes, manifest_json)` — both, because a caller storing them
    must store them together: `manifest_json` is a separate column from
    `bundle_zip`, and `db.pose_count` reads the column while the host counts the
    poses in the bytes. A row whose two halves disagree is an import that 409s.

    Inherits the no-op rule: an unchanged owner returns the ORIGINAL zip object,
    so nothing is re-compressed and `result is zip_bytes` still answers "did
    anything change".
    """
    return _apply_to_bundle(zip_bytes, lambda m: set_pet_ownership(
        m, category=category, name=name, at=at))


def stamp_bundle_fingerprint(zip_bytes: bytes) -> Tuple[bytes, str]:
    """`set_bundle_fingerprint` applied to a bundle. Mint only, DatsPet only."""
    return _apply_to_bundle(zip_bytes, set_bundle_fingerprint)


def read_pet_ownership(
    manifest_json: Optional[str],
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """`(category, name, at)` from a manifest, or all-None when absent.

    Absence is NEVER coerced into a category — the caller decides what missing
    means (the host's ingest ladder refuses; a display shows "unknown"). An
    unparseable manifest reads the same as a missing one: this is a display and
    gating helper, not a validator, and it must not raise into either.
    """
    if not manifest_json:
        return (None, None, None)
    try:
        manifest = json.loads(manifest_json)
    except (ValueError, TypeError):
        return (None, None, None)
    if not isinstance(manifest, dict):
        return (None, None, None)
    return (manifest.get(CATEGORY_KEY), manifest.get(NAME_KEY),
            manifest.get(TRANSFERRED_AT_KEY))


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _validate(*, category: str, name: str, at: str) -> None:
    """Fail loudly at the call site rather than writing a bundle the host refuses.

    A bad stamp is silent until ingest, where it surfaces as "this pet is licensed
    to someone else" on a pet the buyer just paid for. Cheaper to raise here.
    """
    if category not in OWNER_CATEGORIES:
        raise OwnerFieldError(
            f"unknown owner_category {category!r} — expected one of "
            f"{sorted(OWNER_CATEGORIES)}")
    # `public` needs no subject; every other category IS a subject (§1.1).
    if category == PUBLIC_CATEGORY:
        if name:
            raise OwnerFieldError(
                f"owner_name must be empty for {PUBLIC_CATEGORY!r}, got {name!r}")
    elif not name:
        raise OwnerFieldError(f"owner_name is required for category {category!r}")
    if not isinstance(at, str) or not at.endswith("Z"):
        raise OwnerFieldError(
            f"owner_transferred_at must be a UTC ISO-8601 string ending in 'Z', "
            f"got {at!r} — use utc_now_iso()")


def _dump(manifest: dict) -> str:
    """`indent=2` matches what the packer writes (`pet_factory/factory.py`), so a
    stamped manifest and a fresh one are formatted alike."""
    return json.dumps(manifest, indent=2)


def _apply_to_bundle(zip_bytes: bytes, patch) -> Tuple[bytes, str]:
    """Run a manifest-level writer over a bundle, rewriting the zip only if the
    writer actually changed something.

    Every member is carried across under its ORIGINAL NAME and in its original
    order; only manifest.json's bytes change. `app._unpack_bundle` matches members
    by name (`*_sprite.png`, `manifest.json`, `package.json`), so a renamed member
    is an unrenderable pet.

    A missing manifest RAISES, and that must not be softened into a skip: every
    row in the store was written through `_unpack_bundle`, which already fails on
    a bundle with no readable manifest — so this can only fire on a genuinely
    broken artifact, and silently leaving one unstamped would surface far away, as
    a refusal at the host's ingest door (§4.1).
    """
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as src:
        names = src.namelist()
        if MANIFEST_MEMBER not in names:
            raise OwnerFieldError(f"bundle has no {MANIFEST_MEMBER}")
        members = {name: src.read(name) for name in names}

    before = members[MANIFEST_MEMBER].decode("utf-8")
    after = patch(before)
    if after is before:
        return zip_bytes, before          # no-op: don't re-compress 3.5 MB

    members[MANIFEST_MEMBER] = after.encode("utf-8")
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for name in names:
            dst.writestr(name, members[name])
    return out.getvalue(), after
