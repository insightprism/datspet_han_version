"""pet_store — the public Pet Store surface (SPEC_PET_STORE §3.1).

Browse and adopt from the DB-backed inventory. Three routes: the listing
(anonymous browsing is fine — the catalog spec's §0.4 posture), the portrait
(an <img> load, so no auth — an image tag has no 401 handler), and adopt.

Adopt is the old adopt-a-sample primitive re-pointed at the DB, with one
addition: the entitlement is now enforced SERVER-SIDE (§9) instead of being an
advisory flag a direct POST could bypass. After adopt the flow is the normal
one — the draft appears, the user keeps it, handOffToDatsme prices and charges
on the host. No new checkout, no prices here (§0.5.1).

Imports are web-tier only (the GPU-less posture): db + the shared policy
modules, no ML, no filesystem content.
"""
from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

import datsme_integration
import db
import house_capacity
import owner_scope
import pet_ownership
from pet_factory import tiers as tiers_mod

router = APIRouter(prefix="/api/store")

#: A preview is immutable per id (derived once at insert; redraft touches only
#: text), so aggressive caching is safe (§3.1).
PREVIEW_CACHE_CONTROL = "public, max-age=86400"


def _published_store_pet(store_id: str):
    """Resolve a store id a SHOPPER may see. Unpublished rows 404 exactly like
    absent ones — the staging shelf must be invisible, not just unlisted."""
    row = db.get_store_pet(store_id)
    if row is None or not row["published"]:
        raise HTTPException(404, "store pet not found")
    return row


@router.get("")
def list_store():
    """The shelf: published listings only, newest first. Byteless — portraits
    load through the preview route, bundles never leave the server here."""
    listings = db.list_store_pets(published_only=True)
    for item in listings:
        # Always true on this surface — published is the admin's word, not a
        # browser fact.
        item.pop("published", None)
        item["preview_url"] = f"/api/store/{item['id']}/preview.png"
    return {"pets": listings}


@router.get("/{store_id}/preview.png")
def store_preview(store_id: str):
    """The card portrait. Deliberately no owner resolution (the catalog
    precedent, owner_scope.py: an <img> has no 401 handler)."""
    row = _published_store_pet(store_id)
    return Response(content=row["preview_png"], media_type="image/png",
                    headers={"Cache-Control": PREVIEW_CACHE_CONTROL})


@router.post("/{store_id}/adopt")
def adopt_store_pet(store_id: str, request: Request):
    """Copy a store pet into the caller's house as a DRAFT — instant, zero GPU.

    Order (the adopt-a-sample order, kept exactly): resolve → owner →
    entitlement → house cap 409 BEFORE any insert → stamp → insert. A fresh
    pet_id per adopt: two adopts = two pets = two charges at the host — the
    "template, not a licence" rule (§3.1).
    """
    row = _published_store_pet(store_id)
    owner = owner_scope.require_owner(request)

    # SPEC_PET_STORE §9 — the entitlement, enforced where it counts. The tier
    # table stays the one definition; this is the server-side check the old
    # sample endpoint documented as missing (catalog spec §0.6).
    caps = datsme_integration.resolve_launch_capabilities(request)
    entitlement = tiers_mod.resolve_entitlement(caps)
    if not entitlement.get("can_adopt_samples", True):
        raise HTTPException(
            403, "Your plan does not include adopting ready-made pets.")

    house_capacity.enforce_house_not_full(owner)

    # SPEC_PET_OWNER_FIELD §2.4 — stamp upstream of insert_pet so the derived
    # digest covers the stamped bytes. A store copy is `public`: the one
    # category with no subject; the HOST assigns the buyer at its checkout.
    created_at = time.time()
    bundle_zip = row["bundle_zip"]
    bundle_zip, _ = pet_ownership.stamp_bundle_fingerprint(bundle_zip)
    bundle_zip, manifest_json = pet_ownership.transfer_pet_ownership(
        bundle_zip,
        category=pet_ownership.PUBLIC_CATEGORY, name="",
        at=pet_ownership.epoch_to_utc_iso(created_at))

    pet_id = uuid.uuid4().hex[:12]
    db.insert_pet(
        pet_id=pet_id, breed_id=row["breed_id"],
        display_name=row["display_name"], created_at=created_at, draft=True,
        sheet_png=row["sheet_png"], manifest_json=manifest_json,
        package_json=row["package_json"], bundle_zip=bundle_zip,
        external_user_id=owner,
        # §7.2 — the record of how this pet came to be; the DPP export reads
        # it as the declared price basis (store_flat).
        source_store_pet_id=row["id"],
    )
    return {"pet_id": pet_id, "display_name": row["display_name"],
            "breed_id": row["breed_id"]}
