"""The donate door and the reward's delivery (SPEC_PET_STORE §10).

A donation is a gift and it is final (§0.5): the pet becomes store inventory at
the click, the donor is thanked, and she does not get it back.

What each case protects:
- every gate refuses for its OWN reason, so a refusal is legible;
- **an unstamped legacy pet is refused, not assumed** — paying out for
  provenance nobody knows is worse than declining;
- a donation writes the store row, the ledger row and removes the house row —
  and the new store pet is INVISIBLE on the shelf until an admin moves it,
  which is what proves donations cannot self-shelve;
- DatsPet awards nothing: it sends a request with NO amount, and records
  whatever the host answers, including a refusal;
- a `capped` or `disabled` answer is terminal — the donor was thanked once,
  deliberately, and asking again would only annoy the host.
"""
import importlib
import json
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WEBUI = os.path.join(REPO, "webui")
for p in (WEBUI, REPO):
    if p not in sys.path:
        sys.path.insert(0, p)

from conftest import ANON_OWNER, anon_cookies, make_bundle_zip  # noqa: E402

import pet_ownership  # noqa: E402

DONOR = "user-A"


@pytest.fixture()
def donate_client(dpp_env, monkeypatch):
    """The donate router alone, with the owner resolved to a named DatsMe user
    unless a test overrides it."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import donations
    importlib.reload(donations)
    monkeypatch.setattr(donations.owner_scope, "require_owner",
                        lambda request: DONOR)
    monkeypatch.setattr(donations.datsme_integration,
                        "resolve_launch_capabilities", lambda request: [])
    monkeypatch.setattr(donations.datsme_integration,
                        "_read_launch_cookie", lambda request: None)
    app = FastAPI()
    app.include_router(donations.router)
    client = TestClient(app)
    client._donations = donations
    return client


def _designed_pet(db, pet_id="mypet0000001", owner=DONOR):
    """A pet stamped the way a real build stamps it: factory/datspet."""
    zip_bytes, manifest_json = make_bundle_zip(
        breed_id="red_panda",
        animations={"walk": {"frames": [0]}, "idle": {"frames": [1]}},
        columns=8, frame_width=256, frame_height=256)
    zip_bytes, _ = pet_ownership.stamp_bundle_fingerprint(zip_bytes)
    zip_bytes, manifest_json = pet_ownership.transfer_pet_ownership(
        zip_bytes, category=pet_ownership.FACTORY_CATEGORY,
        name=pet_ownership.FACTORY_OWNER_NAME, at="2026-07-31T10:00:00Z")
    from PIL import Image
    import io
    buf = io.BytesIO()
    Image.new("RGBA", (2048, 256), (200, 120, 40, 255)).save(buf, "PNG")
    sheet = buf.getvalue()
    # The bundle the portrait crop reads must carry a real sheet.
    import zipfile
    rebuilt = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as src:
        names = src.namelist()
        with zipfile.ZipFile(rebuilt, "w") as out:
            for n in names:
                out.writestr(n, sheet if n.endswith("_sprite.png") else src.read(n))
    zip_bytes = rebuilt.getvalue()
    db.insert_pet(pet_id=pet_id, breed_id="red_panda", display_name="Red Panda",
                  created_at=1783800000.0, draft=False, sheet_png=sheet,
                  manifest_json=manifest_json, package_json=None,
                  bundle_zip=zip_bytes, external_user_id=owner)
    return pet_id


# --- the gates -------------------------------------------------------------
def test_an_anonymous_owner_cannot_donate(donate_client, dpp_env, monkeypatch):
    """A donation earns social points, and those need an account to land in."""
    monkeypatch.setattr(donate_client._donations.owner_scope, "require_owner",
                        lambda request: ANON_OWNER)
    _designed_pet(dpp_env["db"], owner=ANON_OWNER)
    r = donate_client.post("/api/pets/mypet0000001/donate")
    assert r.status_code == 403


def test_the_entitlement_gates_the_door(donate_client, dpp_env, monkeypatch):
    _designed_pet(dpp_env["db"])
    monkeypatch.setattr(donate_client._donations.tiers_mod, "resolve_entitlement",
                        lambda caps: {"can_donate": False})
    r = donate_client.post("/api/pets/mypet0000001/donate")
    assert r.status_code == 403


def test_someone_elses_pet_404s_exactly_like_an_absent_one(donate_client, dpp_env):
    """No existence oracle: 'not yours' and 'not there' are indistinguishable."""
    _designed_pet(dpp_env["db"], pet_id="notmine00001", owner="user-B")
    for pet_id in ("notmine00001", "absent000001"):
        assert donate_client.post(f"/api/pets/{pet_id}/donate").status_code == 404


def test_a_store_adopted_pet_is_refused(donate_client, dpp_env):
    """The laundering loop — adopt cheap, donate back, collect — closed by one
    check with no new bookkeeping."""
    db = dpp_env["db"]
    zip_bytes, manifest_json = make_bundle_zip(breed_id="shelfcat")
    zip_bytes, manifest_json = pet_ownership.transfer_pet_ownership(
        zip_bytes, category=pet_ownership.PUBLIC_CATEGORY, name="",
        at="2026-07-31T10:00:00Z")
    db.insert_pet(pet_id="bought000001", breed_id="shelfcat",
                  display_name="Shelf Cat", created_at=1783800000.0, draft=False,
                  sheet_png=b"x", manifest_json=manifest_json, package_json=None,
                  bundle_zip=zip_bytes, external_user_id=DONOR)
    r = donate_client.post("/api/pets/bought000001/donate")
    assert r.status_code == 422
    assert "not_donatable" in json.dumps(r.json())


def test_an_UNSTAMPED_legacy_pet_is_refused_not_assumed(donate_client, dpp_env):
    """Absence is never coerced into a category. A pet built before owner
    stamping has provenance nobody knows, and paying out for that is worse than
    declining — she can rebuild it."""
    db = dpp_env["db"]
    zip_bytes, manifest_json = make_bundle_zip(breed_id="oldpet")
    db.insert_pet(pet_id="legacy000001", breed_id="oldpet",
                  display_name="Old Pet", created_at=1783800000.0, draft=False,
                  sheet_png=b"x", manifest_json=manifest_json, package_json=None,
                  bundle_zip=zip_bytes, external_user_id=DONOR)
    assert pet_ownership.read_pet_ownership(manifest_json)[0] is None
    r = donate_client.post("/api/pets/legacy000001/donate")
    assert r.status_code == 422


# --- the donation itself ---------------------------------------------------
def test_donating_moves_the_pet_into_intake_and_frees_the_slot(
        donate_client, dpp_env):
    db = dpp_env["db"]
    _designed_pet(db)

    r = donate_client.post("/api/pets/mypet0000001/donate")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["display_name"] == "Red Panda"
    # The thank-you claims NO number — only DatsMe can say what it gave, and it
    # has not been asked yet.
    assert "point" not in body["thanks"].lower()

    # The house row is gone — the slot frees at once, which is the product point.
    assert db.get_pet("mypet0000001") is None

    # It is inventory, in intake, and INVISIBLE to shoppers until an admin acts.
    inventory = db.list_store_pets(shelf_only=False)
    assert len(inventory) == 1 and inventory[0]["status"] == "intake"
    assert db.list_store_pets(shelf_only=True) == []
    # Listing text starts empty: the AI is never run by a user's action (§4).
    assert inventory[0]["description"] == "" and inventory[0]["tags"] == []

    # And the ledger names the donor, with the reward owed.
    ledger = db.donations_for_donor(DONOR)
    assert len(ledger) == 1
    assert ledger[0]["reward_state"] == "owed"
    assert ledger[0]["points_awarded"] is None
    assert ledger[0]["store_pet_id"] == inventory[0]["id"]


def test_a_donor_sees_only_her_own_donations(donate_client, dpp_env, monkeypatch):
    db = dpp_env["db"]
    _designed_pet(db)
    donate_client.post("/api/pets/mypet0000001/donate")

    assert len(donate_client.get("/api/donations").json()["donations"]) == 1
    monkeypatch.setattr(donate_client._donations.owner_scope, "require_owner",
                        lambda request: "user-B")
    assert donate_client.get("/api/donations").json()["donations"] == []


# --- delivery: DatsPet asks, the host decides ------------------------------
def _fake_post(status_code=200, results=None, captured=None):
    class _Resp:
        def __init__(self):
            self.status_code = status_code
            self.text = ""

        def json(self):
            return {"results": results or []}

    def _post(**kwargs):
        if captured is not None:
            captured.update(kwargs)
        return _Resp()
    return _post


def test_the_request_carries_no_amount(dpp_env, monkeypatch):
    """DatsPet never names a figure — one that could name a figure could name a
    bigger one. The host reads its own knob."""
    import reward_delivery
    importlib.reload(reward_delivery)
    db = dpp_env["db"]
    db.insert_donation(donation_id="don1", external_user_id=DONOR,
                       store_pet_id="sp1", display_name="P", donated_at=1.0)
    captured = {}
    monkeypatch.setattr("datsme_partner_sdk.writeback.post_writeback",
                        _fake_post(results=[{"award_key": "don1",
                                             "outcome": "awarded",
                                             "points_awarded": 1}],
                                   captured=captured))
    settled = reward_delivery.deliver_owed_rewards(DONOR, "tok")
    assert settled == 1

    # §10.11 — the body must carry the RAW launch token from the cookie. It is
    # what the host authenticates against; without it every delivery 401s and
    # the rewards sit owed forever.
    assert captured["body"]["launch_token"] == "tok"
    assert captured["body"]["target"] == reward_delivery.AWARD_TARGET

    payload = captured["body"]["payload"]
    blob = json.dumps(payload)
    for money_word in ("points", "amount", "credits"):
        assert money_word not in blob, f"the request must not name {money_word}"
    assert payload["awards"] == [{"award_key": "don1", "reason": "pet_donation"}]


def test_the_hosts_figure_is_recorded_so_the_donor_can_be_thanked(
        dpp_env, monkeypatch):
    import reward_delivery
    importlib.reload(reward_delivery)
    db = dpp_env["db"]
    db.insert_donation(donation_id="don1", external_user_id=DONOR,
                       store_pet_id="sp1", display_name="P", donated_at=1.0)
    monkeypatch.setattr("datsme_partner_sdk.writeback.post_writeback",
                        _fake_post(results=[{"award_key": "don1",
                                             "outcome": "awarded",
                                             "points_awarded": 3}]))
    reward_delivery.deliver_owed_rewards(DONOR, "tok")
    row = db.donations_for_donor(DONOR)[0]
    assert row["reward_state"] == "delivered"
    assert row["points_awarded"] == 3, "the donor is thanked with the HOST's number"


@pytest.mark.parametrize("outcome,state", [
    ("capped", "capped"), ("disabled", "disabled"), ("duplicate", "delivered"),
])
def test_a_refusal_is_recorded_and_never_retried(dpp_env, monkeypatch,
                                                 outcome, state):
    """Declining is an answer, not an error — and a terminal one: asking again
    would only annoy the host and could change what the donor was told."""
    import reward_delivery
    importlib.reload(reward_delivery)
    db = dpp_env["db"]
    db.insert_donation(donation_id="don1", external_user_id=DONOR,
                       store_pet_id="sp1", display_name="P", donated_at=1.0)
    monkeypatch.setattr("datsme_partner_sdk.writeback.post_writeback",
                        _fake_post(results=[{"award_key": "don1",
                                             "outcome": outcome,
                                             "points_awarded": 0}]))
    reward_delivery.deliver_owed_rewards(DONOR, "tok")
    assert db.donations_for_donor(DONOR)[0]["reward_state"] == state
    # Nothing is owed any more, so the next launch sends nothing.
    assert db.owed_donations(DONOR) == []


def test_a_transient_failure_leaves_it_OWED_for_the_next_launch(
        dpp_env, monkeypatch):
    import reward_delivery
    importlib.reload(reward_delivery)
    db = dpp_env["db"]
    db.insert_donation(donation_id="don1", external_user_id=DONOR,
                       store_pet_id="sp1", display_name="P", donated_at=1.0)
    monkeypatch.setattr("datsme_partner_sdk.writeback.post_writeback",
                        _fake_post(status_code=503))
    assert reward_delivery.deliver_owed_rewards(DONOR, "tok") == 0
    assert db.donations_for_donor(DONOR)[0]["reward_state"] == "owed"
    assert len(db.owed_donations(DONOR)) == 1


def test_a_permanent_refusal_is_terminal_not_a_retry_loop(dpp_env, monkeypatch):
    """A 4xx the partner retries forever is the failure mode that turns a bug
    into a loop."""
    import reward_delivery
    importlib.reload(reward_delivery)
    db = dpp_env["db"]
    db.insert_donation(donation_id="don1", external_user_id=DONOR,
                       store_pet_id="sp1", display_name="P", donated_at=1.0)
    monkeypatch.setattr("datsme_partner_sdk.writeback.post_writeback",
                        _fake_post(status_code=403))
    reward_delivery.deliver_owed_rewards(DONOR, "tok")
    assert db.donations_for_donor(DONOR)[0]["reward_state"] == "declined"
    assert db.owed_donations(DONOR) == []


def test_owed_rewards_batch_into_one_request(dpp_env, monkeypatch):
    """A launch carries ONE writeback (the nonce burns), so three owed awards
    travel together rather than needing three launches."""
    import reward_delivery
    importlib.reload(reward_delivery)
    db = dpp_env["db"]
    for i in range(3):
        db.insert_donation(donation_id=f"don{i}", external_user_id=DONOR,
                           store_pet_id=f"sp{i}", display_name="P",
                           donated_at=float(i))
    calls = []
    results = [{"award_key": f"don{i}", "outcome": "awarded" if i == 0 else "capped",
                "points_awarded": 1 if i == 0 else 0} for i in range(3)]

    def _post(**kwargs):
        calls.append(kwargs)
        class _R:
            status_code = 200
            text = ""
            def json(self):
                return {"results": results}
        return _R()

    monkeypatch.setattr("datsme_partner_sdk.writeback.post_writeback", _post)
    assert reward_delivery.deliver_owed_rewards(DONOR, "tok") == 3
    assert len(calls) == 1, "one launch, one writeback"
    assert len(calls[0]["body"]["payload"]["awards"]) == 3


def test_the_idempotency_key_is_stable_per_launch_and_differs_across_them():
    """The signed body embeds the CURRENT launch JWT, so two attempts from
    different launches have different bytes. A key derived from the donation
    ids alone would present the host with same-key/different-digest — which it
    answers `idempotency_key_reuse` 409, AFTER having already paid."""
    import reward_delivery
    importlib.reload(reward_delivery)
    k = reward_delivery._idempotency_key
    # Within one launch: order-independent and identical, so a retry replays.
    assert k(["b", "a"], "tok-1") == k(["a", "b"], "tok-1")
    # Across launches: different, so the cache never sees a false conflict.
    assert k(["a"], "tok-1") != k(["a"], "tok-2")


@pytest.mark.parametrize("status", [401, 409, 429])
def test_a_retriable_refusal_leaves_the_reward_OWED(dpp_env, monkeypatch, status):
    """§10.0 constraint 1 made this the NORMAL case, not an edge one: a launch
    carries ONE writeback because the nonce burns, so the second donation of a
    session posts with a spent nonce and gets a 401 — as does any session past
    the 60-minute token TTL. Treating that as permanent destroys a reward the
    donor earned."""
    import reward_delivery
    importlib.reload(reward_delivery)
    db = dpp_env["db"]
    db.insert_donation(donation_id="don1", external_user_id=DONOR,
                       store_pet_id="sp1", display_name="P", donated_at=1.0)
    monkeypatch.setattr("datsme_partner_sdk.writeback.post_writeback",
                        _fake_post(status_code=status))
    assert reward_delivery.deliver_owed_rewards(DONOR, "spent-token") == 0
    assert db.donations_for_donor(DONOR)[0]["reward_state"] == "owed"

    # ...and a later launch with a fresh token settles it.
    monkeypatch.setattr("datsme_partner_sdk.writeback.post_writeback",
                        _fake_post(results=[{"award_key": "don1",
                                             "outcome": "awarded",
                                             "points_awarded": 1}]))
    assert reward_delivery.deliver_owed_rewards(DONOR, "fresh-token") == 1
    assert db.donations_for_donor(DONOR)[0]["reward_state"] == "delivered"


def test_a_lost_response_settles_on_the_retry_via_duplicate(dpp_env, monkeypatch):
    """The host paid, the answer never arrived. The retry must settle the rows
    off the `duplicate` verdict its business key produces — never mark them
    declined, which would strand a reward the donor was already given."""
    import reward_delivery
    importlib.reload(reward_delivery)
    db = dpp_env["db"]
    db.insert_donation(donation_id="don1", external_user_id=DONOR,
                       store_pet_id="sp1", display_name="P", donated_at=1.0)

    def _timeout(**kwargs):
        raise RuntimeError("read timeout")
    monkeypatch.setattr("datsme_partner_sdk.writeback.post_writeback", _timeout)
    assert reward_delivery.deliver_owed_rewards(DONOR, "tok-1") == 0
    assert db.donations_for_donor(DONOR)[0]["reward_state"] == "owed"

    monkeypatch.setattr("datsme_partner_sdk.writeback.post_writeback",
                        _fake_post(results=[{"award_key": "don1",
                                             "outcome": "duplicate",
                                             "points_awarded": 1}]))
    assert reward_delivery.deliver_owed_rewards(DONOR, "tok-2") == 1
    row = db.donations_for_donor(DONOR)[0]
    assert row["reward_state"] == "delivered"
    assert row["points_awarded"] == 1, "the ORIGINAL figure, reported back"


def test_delivery_without_a_launch_token_is_a_no_op(dpp_env):
    """No token, nothing to authenticate with — the rows simply stay owed."""
    import reward_delivery
    importlib.reload(reward_delivery)
    db = dpp_env["db"]
    db.insert_donation(donation_id="don1", external_user_id=DONOR,
                       store_pet_id="sp1", display_name="P", donated_at=1.0)
    assert reward_delivery.deliver_owed_rewards(DONOR, None) == 0
    assert reward_delivery.deliver_owed_rewards(None, "tok") == 0
    assert len(db.owed_donations(DONOR)) == 1


def test_donating_the_same_pet_twice_leaves_exactly_one_donation(
        donate_client, dpp_env):
    """Two POSTs for one pet. The second must not create a second listing and a
    second reward claim for a pet that only ever existed once — `delete_pet`
    returning False is how the loser finds out."""
    db = dpp_env["db"]
    _designed_pet(db)
    assert donate_client.post("/api/pets/mypet0000001/donate").status_code == 200
    r = donate_client.post("/api/pets/mypet0000001/donate")
    assert r.status_code in (404, 409), r.text
    assert len(db.donations_for_donor(DONOR)) == 1
    assert len(db.list_store_pets(shelf_only=False)) == 1


# --- M3: a donated row is an ordinary listing from here on -----------------
def test_a_donated_row_is_handled_by_the_ORDINARY_phase_1_admin_routes(
        donate_client, dpp_env, monkeypatch):
    """§10.4's claim, pinned: donations add no admin workflow. The row an
    ordinary donation produces must be editable and shelvable through the
    routes that already existed — and deleting the listing must leave the
    donation ledger alone, because that is audit."""
    import importlib
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import store_admin
    importlib.reload(store_admin)

    db = dpp_env["db"]
    _designed_pet(db)
    donate_client.post("/api/pets/mypet0000001/donate")
    store_pet_id = db.list_store_pets(shelf_only=False)[0]["id"]

    admin = FastAPI()
    admin.include_router(store_admin.router)
    admin.dependency_overrides[
        store_admin.datsme_integration.require_admin_launch] = lambda: None
    monkeypatch.setattr(store_admin.datsme_integration, "admin_user_id",
                        lambda request: "admin-1")
    monkeypatch.setattr(store_admin.owner_scope, "require_owner",
                        lambda request: DONOR)
    client = TestClient(admin)

    # The read-time "donated by" badge — a JOIN, never a column (§1.2).
    got = client.get(f"/api/admin/store/{store_pet_id}").json()
    assert got["donated_by"] == DONOR

    # Editable and shelvable through the ordinary PUT.
    r = client.put(f"/api/admin/store/{store_pet_id}", json={
        "display_name": "Rescued Panda", "description": "A gift.",
        "tags": ["red panda"], "animal": "panda"})
    assert r.status_code == 200, r.text
    r = client.post(f"/api/admin/store/{store_pet_id}/status",
                    json={"status": "shelf"})
    assert r.status_code == 200, r.text
    assert db.get_store_pet(store_pet_id)["status"] == "shelf"

    # §1.2 — the ENGINE must never be able to ask where a listing came from.
    # The badge above is a read-time join; a column here would let a query, a
    # filter or a price branch on provenance, which is the whole prohibition.
    cols = {r["name"] for r in
            db._connect().execute("PRAGMA table_info(store_pets)")}
    assert not (cols & {"donated_by", "donor", "external_user_id",
                        "source", "donation_id"}), \
        f"store_pets grew a provenance column: {cols}"

    # Deleting the listing leaves the ledger — history is not tidied.
    assert client.delete(f"/api/admin/store/{store_pet_id}").status_code == 200
    assert db.get_store_pet(store_pet_id) is None
    assert len(db.donations_for_donor(DONOR)) == 1


# --- the consent hint (SPEC_PET_STORE §10.8) -------------------------------
def test_the_session_says_whether_the_donor_can_be_thanked(dpp_env, monkeypatch):
    """A donation is irreversible, so the donor must know BEFORE giving a pet
    away whether a thank-you can actually arrive. `social.award` is optional and
    optional caps are auto-granted at NO partner tier, so a user who has never
    been asked simply does not have it — and the door has to say so rather than
    take the pet and quietly fail to pay for it."""
    import importlib
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    di = dpp_env["di"]
    importlib.reload(di)

    app = FastAPI()
    app.include_router(di.router)
    client = TestClient(app)

    class _Verified:
        raw_claims = {"nm": "Sara", "sadm": False}

        def __init__(self, caps):
            self.capabilities = caps

    def _session_with(cookie_caps, verified_caps=None):
        monkeypatch.setattr(di, "_read_launch_cookie",
                            lambda request: {"token": "t", "user_id": "u",
                                             "capabilities": cookie_caps})
        monkeypatch.setattr(di, "verify_launch_token",
                            lambda tok, secret: _Verified(
                                cookie_caps if verified_caps is None
                                else verified_caps))
        monkeypatch.setattr(di, "_token_expires_in", lambda v: 3600)
        return client.get("/api/datsme/session").json()

    without = _session_with(["pets.write"])
    assert without["can_be_thanked"] is False
    # ...and the door offers somewhere to FIX it, built server-side so the
    # browser never assembles a DatsMe origin.
    assert without["consent_url"] and "/integrations/consent" in without["consent_url"]

    assert _session_with(["pets.write", di.CAP_SOCIAL_AWARD])["can_be_thanked"] is True

    # The hint reads the VERIFIED token, never the cookie blob — a tampered
    # cookie must not be able to claim a capability the host never granted.
    spoofed = _session_with([di.CAP_SOCIAL_AWARD], verified_caps=["pets.write"])
    assert spoofed["can_be_thanked"] is False


def test_a_donation_of_bytes_the_store_already_holds_is_refused(
        donate_client, dpp_env, monkeypatch):
    """§5.4 — the store never holds the same bundle twice, whichever door it
    arrives through. Refused BEFORE anything is written: a donation is final,
    so a duplicate caught after the transfer would cost her the pet."""
    db = dpp_env["db"]
    _designed_pet(db)
    pet = db.get_pet("mypet0000001")
    # The exact bytes are already on the shelf.
    db.insert_store_pet(
        store_id="already000001", display_name="Already Here",
        breed_id=pet["breed_id"], animal="panda", description="", tags=[],
        created_at=1783800000.0, preview_png=b"\x89PNG\r\n\x1a\nDATA",
        sheet_png=pet["sheet_png"], manifest_json=pet["manifest_json"],
        package_json=pet["package_json"], bundle_zip=pet["bundle_zip"],
        status=db.STORE_STATUS_SHELF)

    r = donate_client.post("/api/pets/mypet0000001/donate")
    assert r.status_code == 409, r.text

    # She still has her pet, and no ledger row was written.
    assert db.get_pet("mypet0000001") is not None
    assert db.donations_for_donor(DONOR) == []
    assert len(db.list_store_pets(shelf_only=False)) == 1
