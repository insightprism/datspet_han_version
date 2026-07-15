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
def _launch_token(secret, *, adm=False, nm=None, ttl=1800):
    """A signed launch token in DatsMe's shape; optionally adm=true. The SDK
    testkit has no adm param, so add the claim and re-sign with the same secret.
    Uses python-jose (the SDK's JWT lib), not PyJWT."""
    from jose import jwt  # same lib the SDK signs/verifies with
    from datsme_partner_sdk.testkit import make_test_launch_token
    tok = make_test_launch_token(
        hmac_secret=secret, user_id="user-A", activity_id="design_a_pet",
        partner_slug="datspet", capabilities=["pets.write"], ttl_seconds=ttl)
    if not adm and nm is None:
        return tok
    claims = jwt.decode(tok, secret, algorithms=["HS256"])
    if adm:
        claims["adm"] = True
    if nm is not None:
        claims["nm"] = nm
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


def _launch_cookie(secret, *, nm=None):
    """The datsme_launch cookie blob /launch would set for a token — built directly
    (the TestClient won't store the Secure cookie over the non-HTTPS test transport,
    same pattern as test_scoping)."""
    import json
    tok = _launch_token(secret, nm=nm)
    return json.dumps({"token": tok, "user_id": "user-A", "activity_id": "design_a_pet",
                       "jti": "t", "capabilities": ["pets.write"], "display_name": nm})


def test_session_exposes_display_name_from_nm_claim(client, dpp_env):
    # A launched user's session carries the display name from the token's nm claim,
    # re-read from the VERIFIED token (not the cookie blob) so it can't be spoofed.
    cookie = _launch_cookie(dpp_env["secret"], nm="Mark")
    body = client.get("/api/datsme/session", cookies={"datsme_launch": cookie}).json()
    assert body["launched"] is True
    assert body["display_name"] == "Mark"


def test_session_display_name_none_when_token_has_no_nm(client, dpp_env):
    # A token minted by an older host (no nm claim) → display_name is None, not an error.
    cookie = _launch_cookie(dpp_env["secret"], nm=None)
    body = client.get("/api/datsme/session", cookies={"datsme_launch": cookie}).json()
    assert body["launched"] is True
    assert body.get("display_name") is None


def test_session_display_name_from_verified_token_not_cookie_blob(client, dpp_env):
    # Security: a tampered cookie blob claiming a different name must NOT spoof the
    # greeting — display_name comes from the VERIFIED token's nm claim.
    import json
    tok = _launch_token(dpp_env["secret"], nm="RealName")
    tampered = json.dumps({"token": tok, "user_id": "user-A", "activity_id": "design_a_pet",
                           "jti": "t", "capabilities": [], "display_name": "SpoofedName"})
    body = client.get("/api/datsme/session", cookies={"datsme_launch": tampered}).json()
    assert body["display_name"] == "RealName"    # from the token, not the blob


# --- /design must survive the trip to prod (SPEC_PET_DESIGNER_FLOW §11) ---------
# The tests above prove the BACKEND sends a launch to /design. Nothing proved anything
# serves it — which is exactly why the gap below stayed green while /design became a
# blank page in prod.
#
# The designer moved to /design/general and /design redirects. Under `next dev` that
# redirect is server-side; in the STATIC EXPORT it is not. Verified by building it:
# out/design.html is emitted, but its body is empty and the hop rides a
# NEXT_REDIRECT flight payload with no meta-refresh — nginx serves a 200 blank page
# and the redirect happens in JS, after a paint.
#
# So prod's redirect is an nginx exact-match location. These tests pin it, because it
# is the only thing standing between a DPP launch and a blank screen, and it lives in
# a file no other test reads.
def _nginx_conf() -> str:
    import pathlib
    return (pathlib.Path(REPO) / "deploy" / "nginx-default.conf").read_text()


def test_nginx_redirects_design_to_the_designer():
    conf = _nginx_conf()
    assert "location = /design {" in conf, \
        "the DPP deep-link target has no nginx redirect — /design would serve a blank page"
    # EXACT match, not a prefix: `location /design` would also swallow /design/general
    # and loop. The `=` is the whole thing working.
    assert "return 307 /design/general" in conf


def test_nginx_design_redirect_keeps_the_query():
    # ?from=datsme rides the launch. Nothing reads it today, but a redirect that
    # quietly eats its query is a trap for whoever adds the first thing that does.
    conf = _nginx_conf()
    i = conf.index("location = /design {")
    assert "$is_args$args" in conf[i:i + 200]


def test_design_route_and_nginx_agree_on_the_target():
    # Dev redirects in the Next route, prod redirects in nginx. Two halves of one
    # behaviour, in two files — so they can drift, and dev would look fine while prod
    # sent launches somewhere else. Pin that they name the same destination.
    import pathlib
    route = (pathlib.Path(REPO) / "web" / "src" / "app" / "design" / "page.tsx").read_text()
    assert 'redirect("/design/general")' in route
    assert "return 307 /design/general" in _nginx_conf()
