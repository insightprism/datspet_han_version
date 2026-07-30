"""Partner-side regression tests for the launch/cookie fixes that previously
rested on manual inspection: the SameSite=None cookie flags and the token-expiry
handling. (Name truncation + DetachedInstance are host-side concerns, covered by
datsme_me/api/tests/test_user_pet_writeback.py's happy path.)
"""
import json

from datsme_partner_sdk.testkit import make_test_launch_token

from conftest import TEST_SECRET


def _launch_token(user_id="user-A", ttl=1800):
    return make_test_launch_token(
        hmac_secret=TEST_SECRET, user_id=user_id, activity_id="design_a_pet",
        partner_slug="datspet", capabilities=["pets.write"], ttl_seconds=ttl)


def test_launch_cookie_is_samesite_none_secure(tmp_path, monkeypatch):
    """Cross-origin XHR (frontend :19955 -> backend :19954) only sends the cookie
    if it is SameSite=None; Secure. Lax would make the Adopt button never show.

    Builds its own app rather than using the shared `client`: the suite pins
    DATSPET_COOKIE_SAMESITE=lax so the anonymous-owner cookie can round-trip over
    TestClient's http (see conftest), and this test's whole subject is the OTHER
    setting. Reading the ambient value would make it assert whatever the
    environment happened to be — which is how it would pass vacuously on the dev
    box, where pet_env.local.sh also sets lax.
    """
    import importlib
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    monkeypatch.setenv("DATSPET_COOKIE_SAMESITE", "none")
    monkeypatch.setenv("DATSME_HMAC_SECRET", TEST_SECRET)
    monkeypatch.setenv("DATSME_PARTNER_SLUG", "datspet")
    monkeypatch.setenv("PETMAKER_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("PETMAKER_DB_PATH", str(tmp_path / "t.db"))
    import datsme_integration as di
    importlib.reload(di)
    try:
        app = FastAPI()
        app.include_router(di.router)
        r = TestClient(app).get(f"/launch?token={_launch_token()}",
                                follow_redirects=False)
        assert r.status_code == 303, r.text
        set_cookie = r.headers.get("set-cookie", "")
        assert "datsme_launch=" in set_cookie
        assert "samesite=none" in set_cookie.lower()
        assert "secure" in set_cookie.lower()
        assert "httponly" in set_cookie.lower()
    finally:
        # Restore the suite-wide module state; monkeypatch only undoes the env.
        monkeypatch.undo()
        importlib.reload(di)


def test_the_push_accept_endpoint_is_gone(client, dpp_env):
    """POST /api/datsme/accept is retired (SPEC_DATSPET_FEDERATED_SESSION §6.2).

    It was the push: DatsPet held a launch token, posted a pointer writeback, and
    the host fetched and charged. Purchases now run entirely on the pull checkout,
    authenticated by the user's own 30-day DatsMe session, so DatsPet no longer
    holds any credential that can trigger a charge.

    Pinned as a test because a re-added push would silently restore two purchase
    paths with two auth lifetimes and two places pricing can drift — which is the
    thing the consolidation exists to prevent, not a style preference.
    """
    r = client.post("/api/datsme/accept", json={"pet_id": "pet00000001"})
    assert r.status_code == 404, r.text


def test_an_expired_launch_token_no_longer_costs_a_purchase(client, dpp_env):
    """The failure class the consolidation removed outright.

    A launch token that lapsed during a long design session used to 401 the Accept
    action — "your DatsMe session expired while designing". There is nothing
    token-authenticated at the end of a build any more, so the pet is simply still
    there, still exportable, and the checkout authenticates against the host's own
    session. What a lapsed token costs now is a silent re-launch, not a purchase.
    """
    db = dpp_env["db"]
    db.insert_pet(pet_id="pet00000001", breed_id="b", display_name="P",
                  created_at=1783800000.0, draft=False,
                  sheet_png=b"x", manifest_json='{"animations":{"walk":{}}}',
                  package_json=None, bundle_zip=b"PK", external_user_id="user-A")

    # Well past the SDK's 30 s clock-drift leeway — a token that lapsed 10 s ago
    # still verifies, deliberately, and would make this assert nothing.
    expired = _launch_token(user_id="user-A", ttl=-3600)
    cookie = json.dumps({"token": expired, "user_id": "user-A",
                         "activity_id": "design_a_pet", "jti": "t",
                         "capabilities": ["pets.write"]})

    # The session endpoint reports the lapse instead of 401ing — it is what tells
    # the client to renew, so it must always answer (§4.7).
    r = client.get("/api/datsme/session", cookies={"datsme_launch": cookie})
    assert r.status_code == 200, r.text
    assert r.json()["launched"] is False
    assert r.json()["stale"] is True

    # And the pet is untouched: still the user's, still offered to the host.
    assert [p["id"] for p in db.export_pets("user-A")] == ["pet00000001"]
