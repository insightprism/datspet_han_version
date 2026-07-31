"""store_admin — the Pet Store's admin CRUD (SPEC_PET_STORE §3.2, §5).

The sixth admin surface, on the motion_admin template: an APIRouter gated by
require_admin_launch, audited via admin_common. DB-backed with NO writability
gate — the settings_admin posture, and the store's whole reason to exist:
stocking prod must not require a deploy (§0 / §8).

The stocking door is publish-from-pet (§5.1): the admin designs a pet through
the NORMAL designer, then this copies her house pet's bundle into an
unpublished store row, extracts the portrait and seeds the facts. The listing
text starts EMPTY — she writes it, or taps the sparkle to have the AI write it
(§4, the ai-tag door). The AI never runs as a side effect of stocking. She then
flips `published`, which the shared sellability validator gates (§5.3) so the
admin can never ship a listing the build would reject.
"""
from __future__ import annotations

import io
import json
import time
import uuid
import zipfile
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

import admin_common
import ai_engine
import datsme_integration
import db
import owner_scope
import store_validation
from pet_factory import animal_catalog as animal_catalog_mod

router = APIRouter(
    prefix="/api/admin/store",
    dependencies=[Depends(datsme_integration.require_admin_launch)],
)

AUDIT_TAG = "store-admin"

#: The AI purpose that drafts listing text (§4) — a content file in
#: pet_factory/ai_purposes, named only here (the engine names no purpose key).
LISTING_PURPOSE_KEY = "store_listing"

# Tag normalization bounds (§3.2). Named constants, never inline literals.
STORE_MAX_TAGS = 16
STORE_MAX_TAG_LEN = 32


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _normalize_tags(tags: list) -> list[str]:
    """Lowercase, trim, dedupe (order kept), drop empties and overlong strings,
    cap the count — applied on EVERY write path (admin PUT and the AI draft),
    so the stored shape has one definition."""
    out: list[str] = []
    seen: set[str] = set()
    for tag in tags or []:
        if not isinstance(tag, str):
            continue
        t = tag.strip().lower()
        if not t or len(t) > STORE_MAX_TAG_LEN or t in seen:
            continue
        seen.add(t)
        out.append(t)
        if len(out) >= STORE_MAX_TAGS:
            break
    return out


def _seed_animal(breed_id: str) -> str:
    """Best-effort species seed (§1.3, Rev.3): a catalog breed resolves to its
    animal; a typed-animal breed_id ('white_snow_leopard') falls back to its
    last word. The admin confirms or corrects it while the row is unpublished —
    this is a SEED, not a derivation, because the bundle carries no canonical
    species key."""
    for a in animal_catalog_mod.list_animals():
        if breed_id == a["key"]:
            return a["key"]
        for b in a.get("breeds", []):
            if b["key"] == breed_id:
                return a["key"]
    parts = [p for p in (breed_id or "").split("_") if p]
    return parts[-1].lower() if parts else ""


def _portrait_from_bundle(zip_bytes: bytes) -> bytes:
    """Crop the idle (else walk, else first) frame out of the sprite sheet — the
    store card's portrait. Moved from animal_catalog/generate_sample.py when the
    sample scripts retired (SPEC_PET_STORE §5.2); pure PIL, using webui's own
    Pillow pin — never the lazy ML boundary."""
    from PIL import Image
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        sheet_name = next(n for n in z.namelist() if n.endswith(
            store_validation.SPRITE_SUFFIX))
        manifest = json.loads(z.read(store_validation.MANIFEST_MEMBER).decode())
        sheet = Image.open(io.BytesIO(z.read(sheet_name)))
    anims = manifest.get("animations", {})
    frames = (anims.get("idle") or anims.get("walk") or {}).get("frames") or [0]
    idx = frames[0]
    cols = manifest.get("columns", 8)
    fw = manifest.get("frame_width", 256)
    fh = manifest.get("frame_height", 256)
    cell = sheet.crop(((idx % cols) * fw, (idx // cols) * fh,
                       (idx % cols + 1) * fw, (idx // cols + 1) * fh))
    buf = io.BytesIO()
    cell.save(buf, "PNG")
    return buf.getvalue()


def _draft_listing(preview_png: bytes, animal: str,
                   owner: Optional[str]) -> tuple[str, list[str], Optional[str]]:
    """One AI draft: (description, tags, display_name_suggestion). Raises the
    engine's typed errors — the CALLER decides whether to degrade (publish is
    best-effort) or surface (the ai-tag door is an explicit ask)."""
    clause = f" The pet is a {animal}." if animal else ""
    result, _ = ai_engine.call_purpose(
        LISTING_PURPOSE_KEY, image=preview_png, media_type="image/png",
        variables={"animal_clause": clause}, external_user_id=owner)
    description = (result.get("description") or "").strip()
    tags = _normalize_tags(result.get("tags") or [])
    suggestion = (result.get("display_name_suggestion") or "").strip() or None
    return description, tags, suggestion


def _admin_view(row) -> dict:
    """The admin's slice: the listing plus what the editor needs — published
    state and the live sellability verdict (so a broken row is visibly broken
    on the shelf, not first discovered at the publish click)."""
    listing = db.store_listing_view(row)
    listing["preview_url"] = f"/api/store/{row['id']}/preview.png"
    listing["sellability_errors"] = store_validation.sellability_errors(
        bundle_zip=row["bundle_zip"], preview_png=row["preview_png"],
        display_name=row["display_name"], animal=row["animal"])
    return listing


def _store_row_or_404(store_id: str):
    row = db.get_store_pet(store_id)
    if row is None:
        raise HTTPException(404, "store pet not found")
    return row


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------
class PublishFromPetBody(BaseModel):
    pet_id: str


class ListingBody(BaseModel):
    display_name: str
    description: str = ""
    tags: list[str] = []
    animal: str
    published: bool


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------
@router.get("")
def list_inventory():
    """The whole shelf — published AND staging — for the admin table."""
    listings = db.list_store_pets(published_only=False)
    for item in listings:
        item["preview_url"] = f"/api/store/{item['id']}/preview.png"
    return {"pets": listings}


@router.get("/{store_id}")
def get_listing(store_id: str):
    return _admin_view(_store_row_or_404(store_id))


# ---------------------------------------------------------------------------
# Writes (no writability gate — DB-backed, runtime-writable on prod by design)
# ---------------------------------------------------------------------------
@router.post("/publish-from-pet")
def publish_from_pet(body: PublishFromPetBody, request: Request):
    """The stocking door (§5.1). COPIES the admin's own house pet into a new
    UNPUBLISHED store row — her house copy remains hers, the two lifecycles
    stay separate. The source pet is read through the caller's OWN owner scope
    (§3.2): an arbitrary pet id that isn't hers 404s exactly like an absent one.
    """
    owner = owner_scope.require_owner(request)
    pet = db.get_pet_for_owner(body.pet_id, external_user_id=owner)
    if pet is None:
        raise HTTPException(404, "pet not found")

    try:
        preview_png = _portrait_from_bundle(pet["bundle_zip"])
    except Exception:
        raise HTTPException(
            422, "could not extract a portrait from this pet's bundle — "
                 "the sprite sheet or manifest is unreadable")

    animal = _seed_animal(pet["breed_id"])

    # §4 — the row arrives with EMPTY listing text. The AI is never run here:
    # it is an explicit invocation (the ai-tag door below), never a side effect
    # of stocking, so no admin is billed attention or tokens for text she did
    # not ask for and a model outage can never make stocking fail.
    store_id = uuid.uuid4().hex[:12]
    db.insert_store_pet(
        store_id=store_id, display_name=pet["display_name"],
        breed_id=pet["breed_id"], animal=animal, description="",
        tags=[], created_at=time.time(), preview_png=preview_png,
        sheet_png=pet["sheet_png"], manifest_json=pet["manifest_json"],
        package_json=pet["package_json"], bundle_zip=pet["bundle_zip"],
        published=False,
    )
    admin_common.audit(AUDIT_TAG, request, "publish-from-pet",
                       f"{body.pet_id} -> store {store_id}")
    return {
        "listing": _admin_view(db.get_store_pet(store_id)),
        # No text was generated, so there is no name idea to offer. The key
        # stays in the response shape because the ai-tag door fills it.
        "display_name_suggestion": None,
    }


@router.put("/{store_id}")
def update_listing(store_id: str, body: ListingBody, request: Request):
    """Edit the authored fields (§1.3) and the published state. Publishing runs
    the shared sellability validator — refused listings stay unpublished."""
    row = _store_row_or_404(store_id)

    display_name = body.display_name.strip()
    animal = body.animal.strip().lower()
    tags = _normalize_tags(body.tags)

    # §1.3 (Rev.3): once published, `animal` is fixed — the filter chips
    # depend on it, and re-speciating a live listing would strand shoppers'
    # filters. Unpublish is not an escape hatch worth building until needed.
    if row["published"] and animal != row["animal"]:
        raise HTTPException(409, "animal is fixed once published")

    if body.published:
        errors = store_validation.sellability_errors(
            bundle_zip=row["bundle_zip"], preview_png=row["preview_png"],
            display_name=display_name, animal=animal)
        if errors:
            raise HTTPException(422, {"error": "not_sellable", "errors": errors})

    db.update_store_listing(store_id, display_name=display_name,
                            description=body.description.strip(), tags=tags,
                            animal=animal)
    db.set_store_published(store_id, body.published)
    admin_common.audit(AUDIT_TAG, request, "update",
                       f"{store_id} published={body.published}")
    return {"listing": _admin_view(db.get_store_pet(store_id))}


@router.post("/{store_id}/ai-tag")
def ai_tag_listing(store_id: str, request: Request):
    """Write description + tags with AI — the ONE way listing text is ever
    generated (§4), and always an explicit ask.

    Modelled on the host's AI-tag door (`POST /api/ai-tag/{kind}/{id}`): one
    call returns caption AND tags together, it OVERWRITES rather than merging,
    and because it overwrites, the browser puts a confirm in front of it. The
    result is persisted here and then re-read into the editor, so the admin
    edits the AI's text as ordinary text — a draft, not a verdict.

    UNPUBLISHED rows only (§3.2): a live listing is the admin's text, and
    regenerating it would change what shoppers are reading. Failures surface
    (503/502) rather than degrading — an explicit ask deserves an explicit
    answer.
    """
    row = _store_row_or_404(store_id)
    if row["published"]:
        raise HTTPException(409, "a published listing is the admin's text — "
                                 "unpublish is not a thing; edit it directly")
    owner = owner_scope.require_owner(request)
    try:
        description, tags, suggestion = _draft_listing(
            row["preview_png"], row["animal"], owner)
    except ai_engine.AIUnavailable as e:
        raise HTTPException(503, f"AI engine unavailable: {e}")
    except ai_engine.AIError as e:
        raise HTTPException(502, f"listing draft failed: {e}")

    db.update_store_listing(store_id, display_name=row["display_name"],
                            description=description, tags=tags,
                            animal=row["animal"])
    admin_common.audit(AUDIT_TAG, request, "ai-tag", store_id)
    return {
        "listing": _admin_view(db.get_store_pet(store_id)),
        "display_name_suggestion": suggestion,
    }


@router.delete("/{store_id}")
def delete_listing(store_id: str, request: Request):
    """Remove from inventory. Copies already adopted into houses are pets rows
    and are deliberately unaffected — they are copies (§3.2)."""
    if not db.delete_store_pet(store_id):
        raise HTTPException(404, "store pet not found")
    admin_common.audit(AUDIT_TAG, request, "delete", store_id)
    return {"deleted": store_id}
