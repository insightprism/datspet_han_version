"""MEDIUM regression tests — retry/token correctness (data-loss guards).

- purge_drafts must NEVER delete a pet with a pending writeback (routed to
  DatsMe but not yet acked) — the retry needs it to survive.
- the bundle token is burned only AFTER the bytes are sent (single-successful-
  download), so a failed transfer leaves it usable for the queued retry.
"""
import time

from conftest import make_pet


def test_purge_spares_pending_writeback_pet(dpp_env):
    db = dpp_env["db"]
    # A normal draft (should be purged) and a pending-writeback pet (must survive).
    make_pet(db, pet_id="plaindraft01", external_user_id="user-A", draft=True)
    make_pet(db, pet_id="pendingwb001", external_user_id="user-A", draft=True)
    # Mark the second as routed-to-DatsMe-but-unacked (what Accept's _bind_pending does).
    db.stamp_writeback_acked  # (no-op ref)
    with db._lock:
        db._connect().execute(
            "UPDATE pets SET datsme_activity_id='design_a_pet', writeback_acked_at=NULL WHERE id=?",
            ("pendingwb001",))
        db._connect().commit()

    dropped = db.purge_drafts("user-A")
    assert "plaindraft01" in dropped
    assert "pendingwb001" not in dropped
    assert db.get_pet("plaindraft01") is None       # purged
    assert db.get_pet("pendingwb001") is not None    # SURVIVED — retry can still land it


def test_purge_all_scope_also_spares_pending(dpp_env):
    db = dpp_env["db"]
    make_pet(db, pet_id="pendingwb002", external_user_id=None, draft=True)
    with db._lock:
        db._connect().execute(
            "UPDATE pets SET datsme_activity_id='design_a_pet', writeback_acked_at=NULL WHERE id=?",
            ("pendingwb002",))
        db._connect().commit()
    db.purge_drafts("__all__")  # startup purge
    assert db.get_pet("pendingwb002") is not None


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
