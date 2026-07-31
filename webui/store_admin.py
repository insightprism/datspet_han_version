"""store_admin — the Pet Store's admin CRUD (SPEC_PET_STORE §3.2, §5).

The sixth admin surface, on the motion_admin template: an APIRouter gated by
require_admin_launch, audited via admin_common. DB-backed with NO writability
gate — the settings_admin posture, and the store's whole reason to exist:
stocking prod must not require a deploy (§0 / §8).

The stocking door is publish-from-pet (§5.1): the admin designs a pet through
the NORMAL designer, then this copies her house pet's bundle into an
`intake` store row, extracts the portrait and seeds the facts. The listing
text starts EMPTY — she writes it, or taps the sparkle to have the AI write it
(§4, the ai-tag door). The AI never runs as a side effect of stocking. She then
moves it to `shelf`, which the shared sellability validator gates (§5.3) so
the admin can never shelve a listing the build would reject. Every other
transition is free (§1.4).
"""
from __future__ import annotations

import io
import json
import time
import uuid
import zipfile
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
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

#: A preview is immutable per id, so it caches as hard as the shopper's does —
#: but `private`, because this copy is served from behind the admin gate and
#: must never be held by a shared proxy.
ADMIN_PREVIEW_CACHE_CONTROL = "private, max-age=86400"


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
    last word. The admin confirms or corrects it until it first reaches the
    shelf (§1.3) —
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


def _draft_listing(preview_png: bytes, animal: str, poses: list[str],
                   owner: Optional[str]) -> tuple[str, list[str], Optional[str]]:
    """One AI draft: (description, tags, display_name_suggestion). Raises the
    engine's typed errors — the CALLER decides whether to degrade (publish is
    best-effort) or surface (the ai-tag door is an explicit ask).

    The model is shown ONE frame (the portrait), so the pose names are the only
    way it can know what the pet does. They are already a fact of the bundle —
    `manifest["animations"]`, the same list the listing serves as `poses` — so
    handing them over costs nothing and is what lets a shopper search "sleepy"
    or "pounces" and find a pet that actually has that pose.
    """
    animal_clause = f" The pet is a {animal}." if animal else ""
    poses_clause = (f" It can animate these poses: {', '.join(poses)}."
                    if poses else "")
    result, _ = ai_engine.call_purpose(
        LISTING_PURPOSE_KEY, image=preview_png, media_type="image/png",
        variables={"animal_clause": animal_clause,
                   "poses_clause": poses_clause}, external_user_id=owner)
    description = (result.get("description") or "").strip()
    tags = _normalize_tags(result.get("tags") or [])
    suggestion = (result.get("display_name_suggestion") or "").strip() or None
    return description, tags, suggestion


def _admin_view(row) -> dict:
    """The admin's slice: the listing plus what the editor needs — shelf
    state and the live sellability verdict (so a broken row is visibly broken
    on the shelf, not first discovered at the publish click)."""
    listing = db.store_listing_view(row)
    # The ADMIN route, not the shopper's: hers serves every shelf state, and
    # most of what this surface shows is off the shelf.
    listing["preview_url"] = f"{router.prefix}/{row['id']}/preview.png"
    # §10.4 — the admin's one new thing: a read-time badge saying this arrived
    # as a gift. Never a column on store_pets, and never on the shopper's
    # listing: who gave it is the shop's business, not the buyer's.
    donation = db.donation_for_store_pet(row["id"])
    listing["donated_by"] = donation["external_user_id"] if donation else None
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
    """The AUTHORED fields — what a human wrote about a listing.

    Deliberately carries no `status`: moving a listing between shelf states is
    a different job on a different clock (see StatusBody). Folding them into
    one call meant every status change was a read-modify-write of the whole
    listing, which is both a clobber risk and hostile to a script.
    """
    display_name: str
    description: str = ""
    tags: list[str] = []
    animal: str
    # None = KEEP what is stored. A client that omits the field must not erase
    # the reason someone wrote for archiving a listing months ago; only an
    # explicit value overwrites it.
    admin_note: Optional[str] = None


class StatusBody(BaseModel):
    """One shelf move. The whole payload is the destination.

    This is the surface an admin triaging a hundred donations uses, and the one
    an agent scripts, so it takes the smallest input that can express the job
    and needs no prior read of the row.
    """
    status: str
    #: Optional, and only meaningful on the way to `archived` — the transition
    #: whose reason nobody remembers in three months (§1.4). None keeps what is
    #: stored, exactly as it does on ListingBody.
    admin_note: Optional[str] = None


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------
@router.get("")
def list_inventory():
    """The whole inventory in every state, newest first — which is what makes
    `intake` an inbox without a queue (§1.4).

    Every row goes through `_admin_view`, the same builder the detail route
    uses. It used to serve the raw byteless projection, which silently dropped
    the two fields the list is the ONLY place that renders: the §10.4 donated
    badge and the sellability warning. Neither could ever appear, and no test
    saw it because both were populated on the routes that return a single row.
    """
    return {"pets": [_admin_view(row) for row in db.list_store_rows()]}


@router.get("/{store_id}/preview.png")
def admin_store_preview(store_id: str):
    """The card portrait for the ADMIN, in any shelf state.

    The shopper's `/api/store/{id}/preview.png` resolves through the shelf gate
    and 404s anything off it (§1.4) — correct there, and exactly wrong here:
    the admin surface is mostly `intake`, so pointing it at the shopper route
    made every row she most needs to look at a broken image. Same bytes, same
    immutability, different audience; `private` because this one sits behind
    the admin gate the router already applies.
    """
    row = _store_row_or_404(store_id)
    return Response(content=row["preview_png"], media_type="image/png",
                    headers={"Cache-Control": ADMIN_PREVIEW_CACHE_CONTROL})


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
        status=db.STORE_STATUS_INTAKE,
    )
    admin_common.audit(AUDIT_TAG, request, "publish-from-pet",
                       f"{body.pet_id} -> store {store_id}")
    return {
        "listing": _admin_view(db.get_store_pet(store_id)),
        # No text was generated, so there is no name idea to offer. The key
        # stays in the response shape because the ai-tag door fills it.
        "display_name_suggestion": None,
    }


def _refuse_if_not_sellable(row, *, display_name: str, animal: str) -> None:
    """The §5.3 gate, shared by both write doors so there is one definition of
    what may sit on a shelf — the admin can never reach a state the build
    would reject, whichever door she came through."""
    errors = store_validation.sellability_errors(
        bundle_zip=row["bundle_zip"], preview_png=row["preview_png"],
        display_name=display_name, animal=animal)
    if errors:
        raise HTTPException(422, {"error": "not_sellable", "errors": errors})


@router.put("/{store_id}")
def update_listing(store_id: str, body: ListingBody, request: Request):
    """Edit the AUTHORED fields (§1.3). Shelf state moves through its own door.

    The two were one call until 2026-07-31, which made every status change a
    read-modify-write of the whole listing: the browser had to hold a full
    editor open to move a pet one state, and a script had to fetch a row before
    it could touch it. They change for different reasons — text is written
    once and rarely revisited, state moves on every triage pass — so they are
    two routes (§3.2).
    """
    row = _store_row_or_404(store_id)

    display_name = body.display_name.strip()
    animal = body.animal.strip().lower()
    tags = _normalize_tags(body.tags)

    # §1.3: `animal` freezes on the FIRST shelving and stays frozen — not
    # merely while the row is on the shelf. Under the old boolean those were
    # the same condition; under four states they are not, and the weaker rule
    # would let shelf -> backroom -> re-animal -> shelf change a listing
    # shoppers had already filtered on.
    if row["first_shelved_at"] is not None and animal != row["animal"]:
        raise HTTPException(409, "animal is fixed once a listing has been shelved")

    # The gate runs on any write that LEAVES the row shelved, not only on the
    # transition into it: a re-save of a live listing is the moment to catch a
    # row whose bytes went bad after shelving. Every other state accepts a
    # broken bundle — you may keep something you cannot sell.
    if row["status"] == db.STORE_STATUS_SHELF:
        _refuse_if_not_sellable(row, display_name=display_name, animal=animal)

    db.update_store_listing(store_id, display_name=display_name,
                            description=body.description.strip(), tags=tags,
                            animal=animal,
                            admin_note=(body.admin_note.strip()
                                        if body.admin_note is not None else None))
    admin_common.audit(AUDIT_TAG, request, "update", store_id)
    return {"listing": _admin_view(db.get_store_pet(store_id))}


@router.post("/{store_id}/status")
def set_listing_status(store_id: str, body: StatusBody, request: Request):
    """Move ONE listing between shelf states (§1.4) — the triage door.

    Two clicks in the browser (pick a state, save) and one call for a script,
    with no prior read: the payload is the destination and nothing else, so it
    can never clobber text somebody wrote while the row sat open in another
    tab. Sized for the day donations arrive by the hundred.

    Moving TO `shelf` runs the shared sellability gate (§5.3); every other
    transition is free — you may keep something you cannot sell.
    """
    row = _store_row_or_404(store_id)

    if body.status not in db.STORE_STATUSES:
        raise HTTPException(422, {
            "error": "unknown_status",
            "errors": [f"status must be one of {', '.join(db.STORE_STATUSES)}"]})

    if body.status == db.STORE_STATUS_SHELF:
        _refuse_if_not_sellable(row, display_name=row["display_name"],
                                animal=row["animal"])

    if body.admin_note is not None:
        db.update_store_listing(
            store_id, display_name=row["display_name"],
            description=row["description"], tags=db.store_listing_view(row)["tags"],
            animal=row["animal"], admin_note=body.admin_note.strip())
    db.set_store_status(store_id, body.status)
    admin_common.audit(AUDIT_TAG, request, "status",
                       f"{store_id} {row['status']} -> {body.status}")
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
    if row["status"] == db.STORE_STATUS_SHELF:
        raise HTTPException(409, "a shelved listing is the admin's text — "
                                 "regenerating it would change what shoppers "
                                 "are reading; edit it directly, or move it "
                                 "off the shelf first")
    owner = owner_scope.require_owner(request)
    # Poses come through the listing view, not a second manifest read — one
    # definition of "what poses this pet has", shared with what shoppers see.
    poses = db.store_listing_view(row)["poses"]
    try:
        description, tags, suggestion = _draft_listing(
            row["preview_png"], row["animal"], poses, owner)
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
