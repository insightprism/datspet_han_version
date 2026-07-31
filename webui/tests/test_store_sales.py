"""The store's transaction ledger (SPEC_PET_STORE §1.5.3).

A store is a store: who bought a pet, how much the host charged, when, and
which listing. The sale is recorded where the host CONFIRMS it — the signed
`/partner/imported` notification, which fires only after its checkout charged.

What each case protects:
- the four facts land, from a notification that carries them;
- the ledger is append-only and idempotent on `pet_id`, because that
  notification is at-least-once and WILL arrive twice;
- an unknown amount is NULL, never 0 — a free re-import delta makes zero a
  legitimate value, so collapsing the two would put a lie in the books;
- a retry that arrives after the buyer deleted the pet STILL records the sale
  (the case the pet-row guard would otherwise drop — and the whole reason
  retries exist);
- designed pets write nothing: they were not sold by the store;
- the sale outlives the buyer, the listing, and being forgotten.
"""
import json
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WEBUI = os.path.join(REPO, "webui")
for p in (WEBUI, REPO):
    if p not in sys.path:
        sys.path.insert(0, p)

from conftest import TEST_SECRET, make_bundle_zip, make_pet  # noqa: E402

WALK_IDLE = {"walk": {"frames": [0]}, "idle": {"frames": [1]}}
FAKE_PNG = b"\x89PNG\r\n\x1a\nDATA"


def _imported(client, user_id, body_obj, sign_with=TEST_SECRET):
    from datsme_partner_sdk import sign_host_request
    path = f"/partner/imported/{user_id}"
    body = json.dumps(body_obj, separators=(",", ":")).encode()
    headers = {"Content-Type": "application/json", "X-DatsMe-Partner": "datspet"}
    if sign_with:
        headers["X-DatsMe-Signature"] = sign_host_request(
            sign_with, "POST", path, body)
    return client.post(path, content=body, headers=headers)


def _store_adopted_pet(db, pet_id="soldpet00001", owner="user-A",
                       store_pet_id="smpl93036181"):
    """A pet in someone's house that came from the shelf — what adopt writes."""
    zip_bytes, manifest_json = make_bundle_zip(breed_id="shelfcat",
                                               animations=dict(WALK_IDLE))
    db.insert_pet(pet_id=pet_id, breed_id="shelfcat", display_name="Shelf Cat",
                  created_at=1783800000.0, draft=False, sheet_png=FAKE_PNG,
                  manifest_json=manifest_json, package_json=None,
                  bundle_zip=zip_bytes, external_user_id=owner,
                  source_store_pet_id=store_pet_id)
    return pet_id


def _sale(db, pet_id):
    with db._lock:
        return db._connect().execute(
            "SELECT * FROM store_sales WHERE pet_id=?", (pet_id,)).fetchone()


def test_the_ack_records_all_four_facts(client, dpp_env):
    """Who, how much, when, which pet — from the one message that knows."""
    db = dpp_env["db"]
    _store_adopted_pet(db)

    r = _imported(client, "user-A", {
        "export_type": "datspet_pets.v1",
        "item_ids": ["soldpet00001"],
        "items": [{"id": "soldpet00001", "store_pet_id": "smpl93036181",
                   "credits_charged": 50}],
    })
    assert r.status_code == 200, r.text

    row = _sale(db, "soldpet00001")
    assert row["store_pet_id"] == "smpl93036181"   # WHAT
    assert row["buyer_user_id"] == "user-A"        # WHO
    assert row["credits_paid"] == 50               # HOW MUCH
    assert row["sold_at"] > 0                      # WHEN
    # And the pet is stamped as before — the ledger is additive, not a
    # replacement for the ack that drives `in_datsme`.
    assert db.get_pet("soldpet00001")["writeback_acked_at"] is not None


def test_a_redelivered_notification_writes_no_second_sale(client, dpp_env):
    """The notification is at-least-once, so this WILL happen. `pet_id` is the
    primary key and that is the entire idempotency story."""
    db = dpp_env["db"]
    _store_adopted_pet(db)
    body = {"export_type": "datspet_pets.v1", "item_ids": ["soldpet00001"],
            "items": [{"id": "soldpet00001", "store_pet_id": "smpl93036181",
                       "credits_charged": 50}]}
    assert _imported(client, "user-A", body).status_code == 200
    assert _imported(client, "user-A", body).status_code == 200

    with db._lock:
        n = db._connect().execute(
            "SELECT COUNT(*) c FROM store_sales").fetchone()["c"]
    assert n == 1
    assert db.sales_for_store_pet("smpl93036181") == {"count": 1, "credits": 50}


def test_an_unreported_amount_is_NULL_not_zero(client, dpp_env):
    """Zero is a real price (a re-import delta can be free), so "we were not
    told" must not read as "it was free"."""
    db = dpp_env["db"]
    _store_adopted_pet(db)
    # No `items` at all — an older host, or a partner deployed ahead of one.
    _imported(client, "user-A", {"export_type": "datspet_pets.v1",
                                 "item_ids": ["soldpet00001"]})
    assert _sale(db, "soldpet00001")["credits_paid"] is None

    # A genuinely free re-import records 0, and 0 is not NULL.
    _store_adopted_pet(db, pet_id="freepet00001", store_pet_id="smplfree")
    _imported(client, "user-A", {
        "export_type": "datspet_pets.v1", "item_ids": ["freepet00001"],
        "items": [{"id": "freepet00001", "store_pet_id": "smplfree",
                   "credits_charged": 0}]})
    assert _sale(db, "freepet00001")["credits_paid"] == 0


def test_a_late_retry_records_the_sale_after_the_buyer_deleted_the_pet(
        client, dpp_env):
    """The case retries exist for. The stamp has nothing to stamp and is
    skipped; the SALE is still recorded, from the listing id on the wire."""
    db = dpp_env["db"]
    _store_adopted_pet(db)
    db.delete_pet("soldpet00001", external_user_id="user-A")
    assert db.get_pet("soldpet00001") is None

    r = _imported(client, "user-A", {
        "export_type": "datspet_pets.v1", "item_ids": ["soldpet00001"],
        "items": [{"id": "soldpet00001", "store_pet_id": "smpl93036181",
                   "credits_charged": 50}]})
    assert r.status_code == 200
    assert r.json()["acked"] == []          # nothing to stamp
    row = _sale(db, "soldpet00001")         # ...but the sale is not lost
    assert row is not None and row["credits_paid"] == 50


def test_a_designed_pet_records_no_sale(client, dpp_env):
    """It was not sold by the store. No listing id anywhere means no row."""
    db = dpp_env["db"]
    make_pet(db, pet_id="madepet00001", external_user_id="user-A", draft=False)
    _imported(client, "user-A", {"export_type": "datspet_pets.v1",
                                 "item_ids": ["madepet00001"]})
    assert _sale(db, "madepet00001") is None


def test_a_junk_items_entry_degrades_to_an_unknown_amount(client, dpp_env):
    """Lenient validation: a reporting problem must never become a lost
    acknowledgement, so the sale still lands with the amount unknown."""
    db = dpp_env["db"]
    _store_adopted_pet(db)
    r = _imported(client, "user-A", {
        "export_type": "datspet_pets.v1", "item_ids": ["soldpet00001"],
        "items": [{"id": "soldpet00001", "store_pet_id": "smpl93036181",
                   "credits_charged": "fifty"},
                  {"id": "not-in-item-ids", "credits_charged": 999},
                  "not even a dict"]})
    assert r.status_code == 200
    assert r.json()["acked"] == ["soldpet00001"]
    assert _sale(db, "soldpet00001")["credits_paid"] is None
    assert _sale(db, "not-in-item-ids") is None


def test_the_sale_outlives_the_buyer_the_listing_and_being_forgotten(
        client, dpp_env):
    """History is not tidied. Revoke un-NAMES the buyer; it does not delete the
    transaction, because a shop's books are not a personal record."""
    db = dpp_env["db"]
    _store_adopted_pet(db)
    db.insert_store_pet(
        store_id="smpl93036181", display_name="Shelf Cat", breed_id="shelfcat",
        animal="cat", description="", tags=[], created_at=1783800000.0,
        preview_png=FAKE_PNG, sheet_png=FAKE_PNG,
        manifest_json=make_bundle_zip(breed_id="shelfcat",
                                      animations=dict(WALK_IDLE))[1],
        package_json=None,
        bundle_zip=make_bundle_zip(breed_id="shelfcat",
                                   animations=dict(WALK_IDLE))[0])
    _imported(client, "user-A", {
        "export_type": "datspet_pets.v1", "item_ids": ["soldpet00001"],
        "items": [{"id": "soldpet00001", "store_pet_id": "smpl93036181",
                   "credits_charged": 50}]})

    db.delete_store_pet("smpl93036181")          # listing withdrawn
    db.delete_pet("soldpet00001", external_user_id="user-A")   # house cleaned
    db.revoke_user("user-A", "delete")           # buyer forgotten

    row = _sale(db, "soldpet00001")
    assert row is not None
    assert row["credits_paid"] == 50             # the revenue survives
    assert row["buyer_user_id"] == ""            # the person does not
