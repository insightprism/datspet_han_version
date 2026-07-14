"""Front-door DatsPet-side tests (SPEC_DATSPET_FRONT_DOOR).

Covers the open-redirect guard on /launch's `return` param, the session endpoint's
front-door fields, and logout clearing both cookies. Uses the shared dpp_env/client
fixtures (conftest). No host round-trip — the host bounce is verified on deploy.
"""
import importlib
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WEBUI = os.path.join(REPO, "webui")
for p in (WEBUI, REPO):
    if p not in sys.path:
        sys.path.insert(0, p)


# --- the open-redirect guard (_safe_return_path) — shared with the admin bounce ---
@pytest.mark.parametrize("value,expected", [
    ("/design", "/design"),
    ("/admin/motions", "/admin/motions"),
    ("/design?from=datsme", "/design?from=datsme"),
    ("/house", "/house"),
    ("/", "/"),
    # rejected: protocol-relative → off-origin
    ("//evil.com", None),
    ("//evil.com/path", None),
    # rejected: absolute URLs / schemes
    ("https://evil.com", None),
    ("http://evil.com/x", None),
    ("javascript:alert(1)", None),
    # rejected: not a path
    ("design", None),
    ("", None),
    (None, None),
    # rejected: disallowed chars (e.g. a fragment, backslash, space)
    ("/design#frag", None),
    ("/design\\x", None),
    ("/a b", None),
])
def test_safe_return_path_guard(dpp_env, value, expected):
    di = dpp_env["di"]
    assert di._safe_return_path(value) == expected


# --- session endpoint front-door fields ---
def test_session_integrated_reports_urls(client, dpp_env):
    # dpp_env sets DATSME_HMAC_SECRET → integrated: true, urls populated.
    r = client.get("/api/datsme/session")
    assert r.status_code == 200
    body = r.json()
    assert body["integrated"] is True
    assert body["signin_url"] and "login-launch" in body["signin_url"]
    assert body["signin_url"].endswith("activity=design_a_pet&return=/design")
    assert body["signup_url"] and body["signup_url"].endswith("/signup")
    assert body["admin"] is False          # no admin cookie present
    assert body["launched"] is False       # no launch cookie present


def test_session_standalone_hides_urls(dpp_env, monkeypatch):
    # Unset the secret → standalone: integrated false, urls null (no DatsMe buttons).
    monkeypatch.delenv("DATSME_HMAC_SECRET", raising=False)
    di = dpp_env["di"]
    importlib.reload(di)
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    app = FastAPI()
    app.include_router(di.router)
    body = TestClient(app).get("/api/datsme/session").json()
    assert body["integrated"] is False
    assert body["signin_url"] is None and body["signup_url"] is None
    assert body["admin"] is False


# --- logout clears both cookies ---
def test_logout_clears_launch_and_admin_cookies(client, dpp_env):
    r = client.post("/api/datsme/logout")
    assert r.status_code == 200 and r.json() == {"ok": True}
    # Both cookies are expired (Max-Age=0) in the Set-Cookie headers.
    set_cookies = r.headers.get_list("set-cookie") if hasattr(r.headers, "get_list") else [r.headers.get("set-cookie", "")]
    joined = " ".join(set_cookies)
    assert "datsme_launch=" in joined and "datspet_admin=" in joined


# --- require_admin_launch rejects a missing/forged admin cookie ---
def test_require_admin_launch_rejects_without_cookie(dpp_env):
    di = dpp_env["di"]
    from fastapi import HTTPException, Request

    # A bare request with no cookies → 401.
    scope = {"type": "http", "headers": []}
    req = Request(scope)
    with pytest.raises(HTTPException) as ei:
        di.require_admin_launch(req)
    assert ei.value.status_code == 401


# --- /launch return-redirect + adm-cookie branches, end to end (Item 5) ---
def _launch_token(secret, *, adm=False, ttl=1800):
    """A signed launch token in DatsMe's shape; optionally adm=true. The SDK
    testkit has no adm param, so add the claim and re-sign with the same secret.
    Uses python-jose (the SDK's JWT lib), not PyJWT."""
    from jose import jwt  # same lib the SDK signs/verifies with
    from datsme_partner_sdk.testkit import make_test_launch_token
    tok = make_test_launch_token(
        hmac_secret=secret, user_id="user-A", activity_id="design_a_pet",
        partner_slug="datspet", capabilities=["pets.write"], ttl_seconds=ttl)
    if not adm:
        return tok
    claims = jwt.decode(tok, secret, algorithms=["HS256"])
    claims["adm"] = True
    return jwt.encode(claims, secret, algorithm="HS256")


def test_launch_honors_return_and_no_admin_cookie_for_normal_token(client, dpp_env):
    # A normal launch with ?return=/house lands on {frontend}/house and does NOT
    # set the admin cookie (only an adm=true token does).
    tok = _launch_token(dpp_env["secret"])
    r = client.get(f"/launch?token={tok}&return=/house", follow_redirects=False)
    assert r.status_code == 303, r.text
    assert r.headers["location"].endswith("/house")
    cookies = " ".join(
        r.headers.get_list("set-cookie") if hasattr(r.headers, "get_list")
        else [r.headers.get("set-cookie", "")])
    assert "datsme_launch=" in cookies
    assert "datspet_admin=" not in cookies


def test_launch_adm_token_sets_admin_cookie_and_honors_return(client, dpp_env):
    # An adm=true token with ?return=/admin/motions sets BOTH cookies and lands
    # on the admin path.
    tok = _launch_token(dpp_env["secret"], adm=True)
    r = client.get(f"/launch?token={tok}&return=/admin/motions", follow_redirects=False)
    assert r.status_code == 303, r.text
    assert r.headers["location"].endswith("/admin/motions")
    cookies = " ".join(
        r.headers.get_list("set-cookie") if hasattr(r.headers, "get_list")
        else [r.headers.get("set-cookie", "")])
    assert "datsme_launch=" in cookies
    assert "datspet_admin=" in cookies


def test_launch_rejects_offorigin_return_falls_back_to_default(client, dpp_env):
    # A malicious return is ignored → the default /design?from=datsme, not the
    # attacker path.
    tok = _launch_token(dpp_env["secret"])
    r = client.get(f"/launch?token={tok}&return=//evil.com", follow_redirects=False)
    assert r.status_code == 303
    assert "evil.com" not in r.headers["location"]
    assert r.headers["location"].endswith("/design?from=datsme")
