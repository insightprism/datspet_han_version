"""MEDIUM regression tests — purge/token correctness (data-loss guards).

- purge_drafts deletes exactly what "draft" means — scratch the user never saved
  — and nothing else. It used to carry a `not_pending` exemption for a pet whose
  QUEUED writeback had not drained yet; that queue went with the push path, and
  the exemption had to go with it or claimed work would have become unpurgeable
  forever (SPEC_DATSPET_FEDERATED_SESSION §4.6 b).
- the bundle token is burned only AFTER the bytes are sent (single-successful-
  download), so a failed transfer leaves it usable for the host's next attempt.
"""
import time

from conftest import make_pet


def test_purge_drops_a_claimed_but_unkept_draft(dpp_env):
    """The §4.6 (b) inversion, and why it matters.

    claim_anon_pets stamps `datsme_activity_id` on everything it moves. Under the
    old `not_pending` exemption — "activity stamped AND not acked" — every pet a
    sign-in claimed would have matched, and every claimed-but-unkept draft would
    have been exempt from EVERY purge scope, permanently. Anonymous scratch would
    accumulate forever, and the owner-scope migration note leaned on the very purge
    this clause disabled.

    Deleting the clause is safe because the hand-off calls keep() before navigating
    to the checkout, so a pet in a live checkout is already draft=0.
    """
    db = dpp_env["db"]
    make_pet(db, pet_id="plaindraft01", external_user_id="user-A", draft=True)
    make_pet(db, pet_id="claimeddraft", external_user_id="user-A", draft=True)
    with db._lock:
        db._connect().execute(
            "UPDATE pets SET datsme_activity_id='design_a_pet', writeback_acked_at=NULL WHERE id=?",
            ("claimeddraft",))
        db._connect().commit()

    dropped = db.purge_drafts("user-A")
    assert set(dropped) == {"plaindraft01", "claimeddraft"}
    assert db.get_pet("plaindraft01") is None
    assert db.get_pet("claimeddraft") is None


def test_purge_never_touches_a_kept_pet(dpp_env):
    """The other half: keeping is what takes a pet out of every purge scope, and
    it is what the hand-off does before a checkout. An activity stamp is not, and
    never was, what protects a pet — being saved is."""
    db = dpp_env["db"]
    make_pet(db, pet_id="keptpet00001", external_user_id="user-A", draft=False)
    with db._lock:
        db._connect().execute(
            "UPDATE pets SET datsme_activity_id='design_a_pet' WHERE id=?",
            ("keptpet00001",))
        db._connect().commit()

    assert db.purge_drafts("user-A") == []
    assert db.get_pet("keptpet00001") is not None
    assert db.purge_drafts("__all__") == []
    assert db.get_pet("keptpet00001") is not None


def test_bundle_token_single_successful_download(client, dpp_env):
    # A successful fetch returns the bytes and burns the token (via a post-send
    # BackgroundTask), so a second fetch is 404. NOTE: this asserts the
    # single-use property on the SUCCESS path; the "survives a FAILED transfer"
    # property (burn-after not burn-before) can't be exercised through
    # TestClient, which never fails mid-stream — it's covered by the code +
    # the SDK retry design, not this test.
    db = dpp_env["db"]
    make_pet(db, pet_id="bundlepet001", external_user_id="user-A", draft=False)
    db.create_bundle_token("tok-abc", "bundlepet001", time.time() + 3600)

    r = client.get("/api/datsme/bundle/tok-abc")
    assert r.status_code == 200
    assert r.content == b"PK\x03\x04zip"
    r2 = client.get("/api/datsme/bundle/tok-abc")
    assert r2.status_code == 404, "token should be burned after a successful download"


def test_bundle_unknown_token_404(client, dpp_env):
    assert client.get("/api/datsme/bundle/does-not-exist").status_code == 404
