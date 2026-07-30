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


def test_accept_with_expired_token_is_permanent_401_not_queued(client, dpp_env):
    """A launch token that expired during a long design session must surface a
    relaunch prompt (401), NOT be queued — the retry queue would re-send the
    same dead token forever."""
    db = dpp_env["db"]
    db.insert_pet(pet_id="pet00000001", breed_id="b", display_name="P",
                  created_at=1783800000.0, draft=False,
                  sheet_png=b"x", manifest_json="{}", package_json=None,
                  bundle_zip=b"PK", external_user_id="user-A")
    expired = _launch_token(user_id="user-A", ttl=-10)  # already expired
    cookie = json.dumps({"token": expired, "user_id": "user-A",
                         "activity_id": "design_a_pet", "jti": "t",
                         "capabilities": ["pets.write"]})
    r = client.post("/api/datsme/accept", json={"pet_id": "pet00000001"},
                    cookies={"datsme_launch": cookie})
    assert r.status_code == 401, r.text
    # Must NOT be a "queued" success.
    body = r.json()
    assert body.get("queued") is not True
    assert "expired" in (body.get("detail", "")).lower()


def test_accept_without_cookie_is_401(client, dpp_env):
    r = client.post("/api/datsme/accept", json={"pet_id": "x"})
    assert r.status_code == 401
