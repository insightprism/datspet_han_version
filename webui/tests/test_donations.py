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


def test_the_idempotency_key_is_derived_from_the_donations_not_the_launch(
        dpp_env, monkeypatch):
    """A retry happens on a LATER launch with a different jti, so keying on the
    jti would make the host see new work for the same donations."""
    import reward_delivery
    importlib.reload(reward_delivery)
    assert reward_delivery._idempotency_key(["b", "a"]) == \
        reward_delivery._idempotency_key(["a", "b"])
    assert "a" in reward_delivery._idempotency_key(["a"])


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
