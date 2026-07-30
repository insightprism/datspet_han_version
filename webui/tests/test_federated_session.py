"""Federated sign-out, silent renewal, and the claim sweep.

SPEC_DATSPET_FEDERATED_SESSION. The acceptance criterion is "user A signs in,
designs, signs out; user B signs in on the SAME browser and sees an empty house".
test_scoping covers the read rule that makes B's house empty; this file covers the
machinery that gets the browser from A to B, and the sign-in sweep that stops a
user losing their own work on the way in.

Why each of these is here rather than assumed:

- Sign-out must clear ALL THREE cookies. Leaving the anonymous owner id behind
  hands user B whatever user A made before signing in — the same leak the read
  rule fixed, arriving through the back door.
- Sign-out must be a redirect to the HOST, because DatsPet cannot clear a cookie
  on another origin. A local-only sign-out leaves the DatsMe session alive and the
  next sign-in silently re-mints the same person.
- The signed-out hop must land on the FRONTEND origin. The host can only redirect
  to the origin it has registered for us, which is our API origin; in production
  one vhost serves both and the bug is invisible.
- The session endpoint must never 401 on a stale token — it is what tells the
  client to renew.
- Signing in must move the browser's anonymous work, all of it. A pet-id list
  cannot express that: at launch there is no list, and two of the three stores are
  not pets.
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

from conftest import ANON_OWNER, TEST_SECRET, anon_cookies, make_pet  # noqa: E402


def _token(user_id="user-A", ttl=3600):
    from datsme_partner_sdk.testkit import make_test_launch_token
    return make_test_launch_token(
        hmac_secret=TEST_SECRET, user_id=user_id, activity_id="design_a_pet",
        partner_slug="datspet", capabilities=["pets.write"], ttl_seconds=ttl)


def _launch_cookie(user_id="user-A", ttl=3600):
    return json.dumps({"token": _token(user_id, ttl), "user_id": user_id,
                       "activity_id": "design_a_pet", "jti": "t",
                       "capabilities": ["pets.write"]})


def _deleted_cookies(response) -> set:
    """Cookie names this response deletes (Max-Age=0 / empty value)."""
    names = set()
    for header in response.headers.get_list("set-cookie"):
        name, _, rest = header.partition("=")
        if 'Max-Age=0' in header or rest.startswith(';') or rest.startswith('";'):
            names.add(name.strip())
    return names


# ---------------------------------------------------------------------------
# Sign-out (§4.1) — the hop, and everything it clears
# ---------------------------------------------------------------------------

def test_signout_redirects_to_the_host_and_clears_all_three_cookies(client, dpp_env):
    """The single response both ends our session and sends the browser to end the
    host's, so the two cannot half-fail."""
    r = client.get("/api/datsme/signout", follow_redirects=False,
                   cookies={"datsme_launch": _launch_cookie(),
                            "datspet_anon": ANON_OWNER})
    assert r.status_code == 303, r.text
    assert "/api/integrations/logout-launch" in r.headers["location"]
    assert "token=" in r.headers["location"]
    # The host must be told where to send the browser back — and it must be a
    # DatsPet BACKEND path, because that is the only origin the host has for us.
    assert "return=/api/datsme/signed-out" in r.headers["location"]

    cleared = _deleted_cookies(r)
    assert {"datsme_launch", "datspet_admin", "datspet_anon"} <= cleared, cleared


def test_signout_clears_the_anon_cookie_so_the_next_user_inherits_nothing(client, dpp_env):
    """Half the acceptance criterion. If the anonymous owner id survives sign-out,
    user B inherits everything user A made before signing in."""
    r = client.get("/api/datsme/signout", follow_redirects=False,
                   cookies={"datsme_launch": _launch_cookie(),
                            "datspet_anon": ANON_OWNER})
    assert "datspet_anon" in _deleted_cookies(r)


def test_signout_without_a_launch_cookie_stays_local(client, dpp_env):
    """Nothing to end on the host — land on our own page rather than bounce."""
    r = client.get("/api/datsme/signout", follow_redirects=False)
    assert r.status_code == 303
    assert "logout-launch" not in r.headers["location"]
    assert r.headers["location"].startswith("http://127.0.0.1:19955")


def test_signed_out_hop_lands_on_the_FRONTEND_origin(client, dpp_env):
    """The dev/prod parity seam this endpoint exists for.

    The host redirects to the origin it has registered for us, which is our API
    origin (:19954 in the test env). The landing page is on the frontend origin
    (:19955). They coincide in production behind one nginx vhost, so a `return=/`
    would pass a production-only test and drop a dev user on the FastAPI root.
    """
    r = client.get("/api/datsme/signed-out", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("http://127.0.0.1:19955")
    assert "19954" not in r.headers["location"]


# ---------------------------------------------------------------------------
# The session endpoint (§4.2 / §4.7)
# ---------------------------------------------------------------------------

def test_session_reports_signout_url_and_expiry_when_launched(client, dpp_env):
    r = client.get("/api/datsme/session", cookies={"datsme_launch": _launch_cookie()})
    body = r.json()
    assert body["launched"] is True and body["stale"] is False
    assert "/api/integrations/logout-launch" in body["signout_url"]
    # Prebuilt server-side, like signin_url and import_url — the browser never
    # assembles a DatsMe origin.
    assert body["signout_url"].startswith("http://127.0.0.1:19995")
    assert 0 < body["token_expires_in"] <= 3600


def test_session_never_401s_on_a_stale_token(client, dpp_env):
    """It is the endpoint that TELLS the client to renew, so a 401 here would
    deadlock the renewal it is supposed to trigger (§4.7)."""
    r = client.get("/api/datsme/session",
                   cookies={"datsme_launch": _launch_cookie(ttl=-3600)})
    assert r.status_code == 200
    body = r.json()
    assert body["launched"] is False
    assert body["stale"] is True
    assert body["signout_url"] is None   # no usable assertion to sign out with


def test_session_is_inert_without_a_cookie(client, dpp_env):
    body = client.get("/api/datsme/session").json()
    assert body["launched"] is False
    assert body.get("stale") is not True   # signed out, not stale — different states
    assert body["signout_url"] is None


# ---------------------------------------------------------------------------
# The stale contract, on a real endpoint (§4.7)
# ---------------------------------------------------------------------------

@pytest.fixture()
def app_client(dpp_env):
    import importlib
    from fastapi.testclient import TestClient
    import app as app_mod
    importlib.reload(app_mod)
    app_mod.db = dpp_env["db"]
    app_mod.datsme_integration = dpp_env["di"]
    return TestClient(app_mod.app)


def test_a_stale_cookie_401s_a_json_endpoint_with_a_structured_code(app_client, dpp_env):
    """Never a silent downgrade to the anonymous scope — that is what put a
    signed-in user's minute-61 pet into a pool other users could see."""
    r = app_client.get("/api/pets",
                       cookies={"datsme_launch": _launch_cookie(ttl=-3600)})
    assert r.status_code == 401, r.text
    # A CODE, not a message: the client branches on it, and matching a message
    # would break the moment the copy is edited.
    assert r.json()["detail"]["code"] == "session_stale"


def test_a_stale_cookie_404s_an_image_rather_than_401ing(app_client, dpp_env):
    """<img> has no 401 handler, so a broken image is the honest outcome and the
    page's next JSON call is what starts the renewal (§4.7)."""
    make_pet(dpp_env["db"], pet_id="stalepet0001", external_user_id="user-A",
             draft=False)
    r = app_client.get("/api/pets/stalepet0001/sheet.png",
                       cookies={"datsme_launch": _launch_cookie(ttl=-3600)})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# The claim sweep at launch (§4.5 c)
# ---------------------------------------------------------------------------

def test_launch_claims_this_browsers_anonymous_pets(client, dpp_env):
    """Design first, sign in to adopt — the front door's headline flow."""
    db = dpp_env["db"]
    make_pet(db, pet_id="anonpet00001", external_user_id=ANON_OWNER, draft=False)

    r = client.get(f"/launch?token={_token()}", follow_redirects=False,
                   cookies=anon_cookies())
    assert r.status_code == 303, r.text
    row = db.get_pet("anonpet00001")
    assert row["external_user_id"] == "user-A"
    assert row["datsme_activity_id"] == "design_a_pet"   # provenance stamped


def test_launch_never_claims_another_browsers_anonymous_pets(client, dpp_env):
    db = dpp_env["db"]
    make_pet(db, pet_id="otherbrowser", external_user_id="anon:adifferentbrowser000000000000",
             draft=False)
    client.get(f"/launch?token={_token()}", follow_redirects=False,
               cookies=anon_cookies())
    assert db.get_pet("otherbrowser")["external_user_id"] == "anon:adifferentbrowser000000000000"


def test_launch_with_no_anonymous_work_is_a_noop(client, dpp_env):
    """The normal case for a user who signed in before designing anything."""
    r = client.get(f"/launch?token={_token()}", follow_redirects=False)
    assert r.status_code == 303


def test_launch_ignores_an_rsx_claim_instead_of_erroring(client, dpp_env):
    """The push path's resync channel is retired (§6.2a), but the HOST is unchanged
    and may still mint a resync launch from a stale row. A user who clicks that
    recovery link deserves a working page, not a 404 — and nothing is posted."""
    import time as _t
    from jose import jwt
    # Minted directly: the testkit has no extra_claims hook, and rsx is a shape the
    # host mints but a partner test otherwise cannot produce.
    token = jwt.encode({
        "iss": "datsme", "sub": "user-A", "aid": "design_a_pet", "pid": "datspet",
        "jti": "rsx-test", "iat": int(_t.time()), "exp": int(_t.time()) + 3600,
        "cap": ["pets.write"], "rsx": "somepetid0001",
    }, TEST_SECRET, algorithm="HS256")
    r = client.get(f"/launch?token={token}", follow_redirects=False)
    assert r.status_code == 303, r.text
    assert r.headers["location"].startswith("http://127.0.0.1:19955")


def test_the_pending_list_is_empty_by_construction(client, dpp_env):
    """What opts DatsPet out of the host's resync channel with no host change.

    The old query — activity-stamped and unacked — describes every
    kept-but-unadopted pet once nothing is ever pushed. Left alone, the host would
    mint a resync launch for each and re-open the path §6 closed.
    """
    from datsme_partner_sdk import sign_host_request
    db = dpp_env["db"]
    make_pet(db, pet_id="keptnotsent1", external_user_id="user-A", draft=False)
    with db._lock:
        db._connect().execute(
            "UPDATE pets SET datsme_activity_id='design_a_pet' WHERE id=?",
            ("keptnotsent1",))
        db._connect().commit()

    path = "/partner/results/user-A/pending"
    r = client.get(path, headers={
        "X-DatsMe-Partner": "datspet",
        "X-DatsMe-Signature": sign_host_request(TEST_SECRET, "GET", path),
    })
    assert r.status_code == 200, r.text
    assert r.json() == {"pending": []}


# ---------------------------------------------------------------------------
# The return path carries the in-flight build (SPEC_PET_DESIGNER_FLOW resume)
# ---------------------------------------------------------------------------

def test_a_return_path_may_carry_the_running_job(dpp_env):
    """Signing in mid-build must come back to the build.

    The designer keeps its running job in `?job=<id>`, and sign-in returns to the
    current path INCLUDING that query. This validator is the last gate that path
    passes through, so if it rejected `?` the pet would be lost — which is exactly
    what happened on staging 2026-07-30 (pet 332793aaaa66: 828 KB of finished
    bundle, correctly re-owned, reachable from nowhere) before the resume existed.

    The host's own `_safe_return` (datsme_me routes.py) uses the same charset and
    `_append_return` quotes with safe='/?=&', so the path survives the full round
    trip. Both halves are asserted — here for ours, and by the staging round trip
    for theirs.
    """
    di = dpp_env["di"]
    for path in ("/design/general?job=332793aaaa66",
                 "/design/general?job=332793aaaa66&renewed=1",
                 "/house"):
        assert di._safe_return_path(path) == path, path


def test_the_return_path_is_still_an_open_redirect_guard(dpp_env):
    """Widening it to admit a query must not have widened it to admit a host."""
    di = dpp_env["di"]
    for bad in ("https://evil.example/steal", "//evil.example/steal",
                "/design?x=<script>", "javascript:alert(1)"):
        assert di._safe_return_path(bad) is None, bad


# ---------------------------------------------------------------------------
# The way back to an unanswered build (SPEC_PET_DESIGNER_FLOW resume)
# ---------------------------------------------------------------------------

def test_unsaved_lists_a_finished_build_the_user_never_answered(app_client, dpp_env):
    """The window this closes: a build finishes, and anything that navigates the
    page before the user presses Save leaves the pet reachable from nowhere. The
    house shows only saved pets; the job id lives in memory and dies with the
    backend. Signing out is how it was found — the sign-out chain lands on the
    landing page — but a closed tab does the same thing."""
    db = dpp_env["db"]
    make_pet(db, pet_id="unanswered01", external_user_id="user-A", draft=True)
    make_pet(db, pet_id="alreadysaved", external_user_id="user-A", draft=False)

    r = app_client.get("/api/pets/unsaved",
                       cookies={"datsme_launch": _launch_cookie("user-A")})
    assert r.status_code == 200, r.text
    assert [p["id"] for p in r.json()] == ["unanswered01"]

    # And it stays OUT of the house, which is "pets I decided to keep".
    house = app_client.get("/api/pets",
                           cookies={"datsme_launch": _launch_cookie("user-A")}).json()
    assert [p["id"] for p in house] == ["alreadysaved"]


def test_unsaved_is_owner_scoped_like_everything_else(app_client, dpp_env):
    """A recovery route is still a read: it may not become a way to see another
    user's work, nor another browser's anonymous work."""
    db = dpp_env["db"]
    make_pet(db, pet_id="usersAdraft1", external_user_id="user-A", draft=True)
    make_pet(db, pet_id="anonsdraft01", external_user_id=ANON_OWNER, draft=True)

    seen = app_client.get("/api/pets/unsaved",
                          cookies={"datsme_launch": _launch_cookie("user-B")}).json()
    assert seen == []

    anon = app_client.get("/api/pets/unsaved", cookies=anon_cookies()).json()
    assert [p["id"] for p in anon] == ["anonsdraft01"]


def test_unsaved_survives_the_signout_that_loses_the_job_id(app_client, dpp_env):
    """The reported case, end to end at the data layer.

    Sign-out lands on the landing page, so the `?job=` the designer was carrying is
    gone by the time the user signs back in. The PET is what survives — same id as
    the job, still owned by them — so the route back is to ask for it.
    """
    db = dpp_env["db"]
    make_pet(db, pet_id="midbuild0001", external_user_id="user-A", draft=True)

    # sign out: every DatsPet cookie cleared, landing page, no job id anywhere
    out = app_client.get("/api/datsme/signout", follow_redirects=False,
                         cookies={"datsme_launch": _launch_cookie("user-A")})
    assert "job" not in out.headers["location"]

    # sign back in: the pet is offered again
    back = app_client.get("/api/pets/unsaved",
                          cookies={"datsme_launch": _launch_cookie("user-A")}).json()
    assert [p["id"] for p in back] == ["midbuild0001"]
