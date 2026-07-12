"""BLOCKER 1 regression tests — host→partner signed-request authentication.

These FAIL if _require_host_signature is reverted to the old permissive
behavior (which returned 200 on missing/wrong signatures). They assert both the
HTTP status AND that no data was mutated on the reject paths.
"""
from datsme_partner_sdk import sign_host_request

from conftest import TEST_SECRET, make_pet


def _revoke(client, body_bytes, sig_header=None):
    headers = {"Content-Type": "application/json"}
    if sig_header is not None:
        headers["X-DatsMe-Signature"] = sig_header
    return client.post("/partner/revoke", content=body_bytes, headers=headers)


def test_revoke_missing_signature_401_and_no_mutation(client, dpp_env):
    db = dpp_env["db"]
    make_pet(db, pet_id="ownedpet0001", external_user_id="user-A")
    body = b'{"user_id":"user-A","action":"anonymize"}'

    r = _revoke(client, body)  # no X-DatsMe-Signature
    assert r.status_code == 401, r.text
    # The pet must be untouched — still owned by user-A.
    assert db.get_pet("ownedpet0001")["external_user_id"] == "user-A"


def test_revoke_wrong_signature_401_and_no_mutation(client, dpp_env):
    db = dpp_env["db"]
    make_pet(db, pet_id="ownedpet0002", external_user_id="user-A")
    body = b'{"user_id":"user-A","action":"delete"}'
    # Signed with the WRONG secret.
    bad = sign_host_request("wrong-secret", "POST", "/partner/revoke", body)

    r = _revoke(client, body, bad)
    assert r.status_code == 401, r.text
    assert db.get_pet("ownedpet0002") is not None  # not deleted


def test_revoke_malformed_signature_401(client, dpp_env):
    body = b'{"user_id":"user-A","action":"delete"}'
    r = _revoke(client, body, "garbage-not-a-sig")
    assert r.status_code == 401, r.text


def test_revoke_stale_signature_401(client, dpp_env):
    db = dpp_env["db"]
    make_pet(db, pet_id="ownedpet0003", external_user_id="user-A")
    body = b'{"user_id":"user-A","action":"delete"}'
    # Correctly signed but 10 minutes old (drift cap is 5 min).
    stale = sign_host_request(TEST_SECRET, "POST", "/partner/revoke", body,
                              now=1000)  # ancient ts
    r = _revoke(client, body, stale)
    assert r.status_code == 401, r.text
    assert db.get_pet("ownedpet0003") is not None


def test_revoke_correct_signature_200_and_mutates(client, dpp_env):
    db = dpp_env["db"]
    make_pet(db, pet_id="ownedpet0004", external_user_id="user-A")
    body = b'{"user_id":"user-A","action":"anonymize"}'
    good = sign_host_request(TEST_SECRET, "POST", "/partner/revoke", body)

    r = _revoke(client, body, good)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ok"
    # anonymize nulls external_user_id
    assert db.get_pet("ownedpet0004")["external_user_id"] is None


def test_export_requires_host_signature(client, dpp_env):
    # No signature → 401.
    r = client.get("/partner/export/user-A")
    assert r.status_code == 401, r.text
    # Correct signature → 200.
    good = sign_host_request(TEST_SECRET, "GET", "/partner/export/user-A")
    r = client.get("/partner/export/user-A", headers={"X-DatsMe-Signature": good})
    assert r.status_code == 200, r.text
    assert r.json()["exports"][0]["schema"] == "datspet_pets.v1"


def test_pending_requires_host_signature(client, dpp_env):
    r = client.get("/partner/results/user-A/pending")
    assert r.status_code == 401, r.text
    good = sign_host_request(TEST_SECRET, "GET", "/partner/results/user-A/pending")
    r = client.get("/partner/results/user-A/pending",
                   headers={"X-DatsMe-Signature": good})
    assert r.status_code == 200, r.text


def test_signature_bound_to_path_cannot_be_replayed_cross_endpoint(client, dpp_env):
    # A signature minted for export must NOT authorize revoke (envelope binds
    # method+path). This is the whole point of signing the full envelope.
    db = dpp_env["db"]
    make_pet(db, pet_id="ownedpet0005", external_user_id="user-A")
    body = b'{"user_id":"user-A","action":"delete"}'
    export_sig = sign_host_request(TEST_SECRET, "GET", "/partner/export/user-A")
    r = _revoke(client, body, export_sig)
    assert r.status_code == 401, r.text
    assert db.get_pet("ownedpet0005") is not None
