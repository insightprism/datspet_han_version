"""donations — giving a pet to the store (SPEC_PET_STORE §10).

A donation is a GIFT and it is final (§0.5). The model is a charity shop: the
donor hands the pet over, is thanked on the spot, and the shop decides what
goes on the shelf. She does not get it back, and there is no verdict she is
waiting on.

That one rule is what makes this module small. There is no review queue, no
four-state lifecycle, no approve/reject pair, no return path — the pet becomes
inventory at the click, and the admin's tools are the Phase 1 ones it already
shares with every other listing.

Imports are web-tier only (the GPU-less posture): db + the shared policy
modules + the admin's portrait helper. No ML, no filesystem content.
"""
from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

import datsme_integration
import db
import owner_scope
import pet_ownership
import store_admin
import store_validation
from pet_factory import tiers as tiers_mod

router = APIRouter(tags=["donations"])


def _require_named_donor(request: Request) -> str:
    """§10.1 gate 1 — a donation needs a DatsMe identity.

    An anonymous owner has no account for a reward to land in, so the door
    refuses rather than accepting a gift it can never thank anyone for. This is
    also why the donation ledger registers no claim handler: a donation can
    never be created under an anon id, so there is nothing for one to move.
    """
    owner = owner_scope.require_owner(request)
    if owner_scope.is_anon_owner(owner):
        raise HTTPException(
            403, "Sign in with DatsMe to donate — a donation earns social "
                 "points, and those need an account to land in.")
    return owner


def _require_can_donate(request: Request) -> None:
    """§10.1 gate 2 — the entitlement, resolved exactly like can_adopt_samples."""
    caps = datsme_integration.resolve_launch_capabilities(request)
    entitlement = tiers_mod.resolve_entitlement(caps)
    # Fails OPEN on a missing key, deliberately and consistently with
    # pet_store.py's can_adopt_samples. The default is now unreachable —
    # test_tiers pins that every tier declares the flag and that entitlement()
    # surfaces it — so this only fires if the tier table is malformed, and in
    # that case a silent platform-wide donation outage is a worse failure than
    # a donation. The gates that actually protect anything (a DatsMe identity,
    # her own designed pet, and the host's own cap) are all still in front.
    if not entitlement.get("can_donate", True):
        raise HTTPException(403, "Your plan does not include donating pets.")


@router.post("/api/pets/{pet_id}/donate")
def donate_pet(pet_id: str, request: Request,
               background: BackgroundTasks):
    """Give a pet to the store. FINAL — she does not get it back (§10.5).

    Order matters at the end: the store row is inserted, THEN the ledger row,
    THEN the house row is deleted. A crash between them leaves a duplicate,
    which is recoverable, rather than a vaporised pet, which is not.
    """
    owner = _require_named_donor(request)
    _require_can_donate(request)

    pet = db.get_pet_for_owner(pet_id, external_user_id=owner)
    if pet is None:
        raise HTTPException(404, "pet not found")
    # Unreachable from the house (which lists kept pets only), but a direct
    # POST could otherwise give away a build the user never decided to keep —
    # and drafts are swept, so she would lose it either way without ever
    # choosing to.
    if pet["draft"]:
        raise HTTPException(422, {
            "error": "not_donatable",
            "errors": ["Keep this pet first — an unsaved build cannot be "
                       "donated."]})

    # §10.1 gate 3 — her OWN designed pet. A store-adopted pet carries `public`
    # and is refused, which closes the laundering loop (adopt cheap, donate
    # back, collect) with no new bookkeeping. A pet with NO owner fields is
    # refused too, not assumed: absence is never coerced into a category, and
    # paying out for provenance nobody knows is worse than declining.
    category, _name, _at = pet_ownership.read_pet_ownership(pet["manifest_json"])
    if category != pet_ownership.FACTORY_CATEGORY:
        raise HTTPException(422, {
            "error": "not_donatable",
            "errors": ["Only a pet you designed can be donated. This one came "
                       "from somewhere else."]})

    try:
        preview_png = store_admin._portrait_from_bundle(pet["bundle_zip"])
    except Exception:
        raise HTTPException(422, {
            "error": "not_donatable",
            "errors": ["This pet's bundle has no readable portrait."]})

    animal = store_admin._seed_animal(pet["breed_id"])
    display_name = pet["display_name"]

    # Refused at the door rather than accepted and quietly unshelvable. Under
    # "donation is final" the cost of accepting junk lands on the admin AND on
    # a donor who paid a real pet for it, so the honest answer is to decline
    # and let her keep it.
    errors = store_validation.sellability_errors(
        bundle_zip=pet["bundle_zip"], preview_png=preview_png,
        display_name=display_name, animal=animal)
    if errors:
        raise HTTPException(422, {"error": "not_donatable", "errors": errors})

    now = time.time()
    store_pet_id = uuid.uuid4().hex[:12]
    donation_id = uuid.uuid4().hex[:16]

    # 1. It becomes inventory immediately — `intake`, the same inbox an admin's
    #    own freshly stocked pet lands in, and indistinguishable from one at
    #    runtime (§1.2). Description and tags start EMPTY: the AI is never run
    #    by a user's action (§4).
    db.insert_store_pet(
        store_id=store_pet_id, display_name=display_name,
        breed_id=pet["breed_id"], animal=animal, description="", tags=[],
        created_at=now, preview_png=preview_png, sheet_png=pet["sheet_png"],
        manifest_json=pet["manifest_json"], package_json=pet["package_json"],
        bundle_zip=pet["bundle_zip"], status=db.STORE_STATUS_INTAKE)

    # 2. The ledger row — who gave it, and the key the host dedupes the award
    #    on. The reward is EARNED now; delivery is a separate clock (§10.7).
    db.insert_donation(
        donation_id=donation_id, external_user_id=owner,
        store_pet_id=store_pet_id, display_name=display_name, donated_at=now)

    # 3. The slot frees at once — that is the product point. The in-memory
    #    JOBS entry goes with it, exactly as the Remove route does: a leaked
    #    entry keeps an unauthenticated GET /api/job/{id} serving a result
    #    panel whose links now 404, and leaks the object besides.
    if not db.delete_pet(pet_id, external_user_id=owner):
        # Lost the race: a concurrent POST for this same pet already donated
        # it and removed the row. Undo ours rather than leaving a second
        # listing and a second reward claim for one pet. The ledger row is
        # removed here and ONLY here — before it has been reported to anyone,
        # so nothing has been told a donation happened.
        db.delete_store_pet(store_pet_id)
        db.delete_donation(donation_id)
        raise HTTPException(409, "That pet has already been donated.")
    _drop_job_entry(pet_id)

    # She is right here, in a launched session, so the token needed to speak to
    # the host exists NOW — the common case is that the point lands before she
    # reloads the page (§10.7.1). In the background because a slow host may not
    # make a donation appear to fail when the pet has already changed hands;
    # anything undelivered stays owed and rides her next launch.
    launch = datsme_integration._read_launch_cookie(request) or {}
    token = launch.get("token")
    if token:
        background.add_task(_deliver_quietly, owner, token)

    return {
        "donation_id": donation_id,
        "display_name": display_name,
        # The thank-you the browser shows immediately. The NUMBER is not here:
        # only DatsMe can say what it gave, and it has not been asked yet
        # (§10.8). The Donations section fills it in once the host answers.
        "thanks": f"Thank you — {display_name} is with the store now.",
    }


@router.get("/api/donations")
def list_my_donations(request: Request):
    """What this donor gave, and how she was thanked (§10.8).

    Nothing here is actionable — no restore, no appeal, no verdict — which is
    the point of the model. Anonymous callers get an empty list rather than a
    401: they cannot have donated, and a house page should not error for it.
    """
    owner = owner_scope.require_owner(request)
    if owner_scope.is_anon_owner(owner):
        return {"donations": []}
    return {"donations": db.donations_for_donor(owner)}


def _drop_job_entry(pet_id: str) -> None:
    """Mirror app.py's delete route. Imported at call time because `app`
    imports THIS module to mount its router — a module-level import would be a
    cycle."""
    try:
        import app as app_mod
        with app_mod.JOBS_LOCK:
            app_mod.JOBS.pop(pet_id, None)
    except Exception:                            # noqa: BLE001
        pass


def _deliver_quietly(owner: str, launch_token: str) -> None:
    """Never raises — an undelivered reward is a retry, not a failure."""
    import logging
    import reward_delivery
    try:
        reward_delivery.deliver_owed_rewards(owner, launch_token)
    except Exception as e:                       # noqa: BLE001
        logging.getLogger(__name__).info(
            "donate: reward delivery deferred: %s", e)
