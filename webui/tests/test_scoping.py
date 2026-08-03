"""BLOCKER 2 regression tests — per-user scoping of generation + ownership.

These FAIL if scoping is reverted (unscoped list_pets, missing Accept ownership
check, or a global draft purge). They drive the real app and read the DB.

Identity note: resolve_launch_identity VERIFIES the launch JWT, so tests mint a
real signed token via the SDK testkit (a nonce isn't needed — that only matters
for the writeback burn, not for identity/scoping). The cookie is the JSON blob
/launch sets: {token, user_id, ...}.
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

from conftest import (ANON_OWNER, ANON_OWNER_2,  # noqa: E402
                      anon_cookies, launch_cookie, make_pet)


@pytest.fixture()
def app_client(dpp_env, monkeypatch):
    """Full webui app (not just the DPP router) so app.py scoping is exercised,
    sharing the temp DB from dpp_env."""
    from fastapi.testclient import TestClient
    import app as app_mod
    importlib.reload(app_mod)
    # app.py re-imports db + datsme_integration at module load; rebind them to
    # the already-initialized temp-DB instances from dpp_env.
    app_mod.db = dpp_env["db"]
    app_mod.datsme_integration = dpp_env["di"]
    return TestClient(app_mod.app)


# The launch cookie now lives in conftest (lounges need it too); the local
# name survives so every call site below reads unchanged.
_cookie_for = launch_cookie


def test_two_users_see_only_their_own_saved_pets(app_client, dpp_env):
    """THE ACCEPTANCE CRITERION, at the data layer
    (SPEC_DATSPET_FEDERATED_SESSION §4.5 b).

    User B, freshly signed in on a browser user A used, must see an EMPTY house —
    not A's pets, and not the anonymous pets anyone left behind either. Until this
    changed, `_scope_clause` unioned every unowned row into every signed-in
    caller's view and stamped it `claimable`, so B could see and buy work that was
    never theirs. No amount of correct sign-out fixed that; the read rule had to.
    """
    db = dpp_env["db"]
    make_pet(db, pet_id="petA00000001", external_user_id="user-A", draft=False)
    make_pet(db, pet_id="petB00000001", external_user_id="user-B", draft=False)
    make_pet(db, pet_id="petAnon00001", external_user_id=ANON_OWNER, draft=False)

    # user A sees their own — never user B's, and never a browser's anonymous work.
    ra = app_client.get("/api/pets", cookies={"datsme_launch": _cookie_for("user-A")})
    assert {p["id"] for p in ra.json()} == {"petA00000001"}

    # user B, on the same browser, sees an empty house of their own pets only.
    rb = app_client.get("/api/pets", cookies={"datsme_launch": _cookie_for("user-B")})
    assert {p["id"] for p in rb.json()} == {"petB00000001"}

    # The anonymous browser sees ITS OWN work, and nobody else's.
    ranon = app_client.get("/api/pets", cookies=anon_cookies())
    assert {p["id"] for p in ranon.json()} == {"petAnon00001"}
    assert ranon.json()[0]["claimable"] is True   # its own, not yet bound to a user

    # A DIFFERENT anonymous browser shares nothing with the first.
    rother = app_client.get("/api/pets", cookies=anon_cookies(ANON_OWNER_2))
    assert rother.json() == []


def test_user_cannot_read_or_delete_another_users_pet(app_client, dpp_env):
    db = dpp_env["db"]
    make_pet(db, pet_id="petA00000002", external_user_id="user-A")
    cookieB = {"datsme_launch": _cookie_for("user-B")}

    # B cannot read A's sheet/zip (404, not 403 — no existence leak).
    assert app_client.get("/api/pets/petA00000002/sheet.png", cookies=cookieB).status_code == 404
    assert app_client.get("/api/pets/petA00000002/zip", cookies=cookieB).status_code == 404
    # B cannot delete A's pet, and it survives.
    assert app_client.delete("/api/pets/petA00000002", cookies=cookieB).status_code == 404
    assert db.get_pet("petA00000002") is not None
    # B cannot keep (claim) A's pet.
    assert app_client.post("/api/pets/petA00000002/keep", cookies=cookieB).status_code == 404


def test_the_export_never_offers_another_users_pet(app_client, dpp_env):
    """B cannot get A's pet into their DatsMe house.

    This used to POST /api/datsme/accept and assert 404. That endpoint is gone
    (SPEC_DATSPET_FEDERATED_SESSION §6.2), so the test kept passing while asserting
    nothing about scoping — a 404 from a deleted route looks exactly like a 404 from
    an ownership check. Rewritten against the path that actually carries pets now:
    the host's pull reads /partner/export/{user_id}, which is exact-match, so A's
    pet is simply not in B's export and there is nothing for B to check out.
    """
    db = dpp_env["db"]
    make_pet(db, pet_id="petA00000003", external_user_id="user-A", draft=False)

    assert [p["id"] for p in db.export_pets("user-A")] == ["petA00000003"]
    assert db.export_pets("user-B") == []

    # And B cannot reach it directly either — 404, no existence leak.
    cookieB = {"datsme_launch": _cookie_for("user-B")}
    assert app_client.get("/api/pets/petA00000003/zip", cookies=cookieB).status_code == 404
    row = db.get_pet("petA00000003")
    assert row["external_user_id"] == "user-A"
    assert row["writeback_acked_at"] is None


def test_generate_purges_only_the_callers_draft(app_client, dpp_env, monkeypatch):
    db = dpp_env["db"]
    # user B has an in-progress draft; user A has a local draft.
    make_pet(db, pet_id="draftB000001", external_user_id="user-B", draft=True)
    make_pet(db, pet_id="draftLocal01", external_user_id=None, draft=True)

    # Stub the GPU path so /api/generate returns fast without ComfyUI.
    import app as app_mod
    monkeypatch.setattr(app_mod.threading, "Thread",
                        lambda *a, **k: type("T", (), {"start": lambda self: None})())

    # Generate needs a reference now (SPEC_PET_DESIGNER_FLOW §8) — one base field, and
    # everything else resolved at fill time. Stub the renderer and mint one as user A.
    import io
    from PIL import Image

    def fake_render(description, request, owner, reference_path=None, strength=None,
                    isolate=False, base_pose="standing"):
        buf = io.BytesIO()
        Image.new("RGB", (32, 32), (9, 9, 9)).save(buf, "PNG")
        return buf.getvalue()

    monkeypatch.setattr(app_mod, "_render_still", fake_render)
    cookies = {"datsme_launch": _cookie_for("user-A")}
    ref = app_client.post("/api/reference", data={"animal": "a red fox"}, cookies=cookies)
    assert ref.status_code == 200, ref.text

    # user A generates. Their purge must NOT remove user B's draft nor the local draft
    # (A's scope is user-A, which has no drafts here).
    r = app_client.post("/api/generate",
                        data={"reference_id": ref.json()["reference_id"]},
                        cookies=cookies)
    assert r.status_code == 200, r.text
    assert db.get_pet("draftB000001") is not None, "user B's draft was wrongly purged"
    assert db.get_pet("draftLocal01") is not None, "local draft was wrongly purged"


def test_arena_room_membership_never_widens_owner_scope(app_client, dpp_env):
    """SPEC_PET_ARENA_ROOMS §10: '_scope_clause is unchanged — extend
    test_scoping.py rather than trusting a review.' Behaviorally: a pet
    ENTERED in a live arena room stays exactly as invisible to other owners
    through every owner-scoped surface as it was before. The room's OWN
    asset routes are a separate, deliberate capability (membership + the
    room code) and widen nothing here."""
    import importlib
    import arena_rooms
    importlib.reload(arena_rooms)
    arena_rooms.db = dpp_env["db"]

    db = dpp_env["db"]
    make_pet(db, pet_id="scopedracer1", external_user_id=ANON_OWNER, draft=False)

    r = app_client.post("/api/arena/rooms", json={
        "event_key": "sprint_100", "challenge_key": "arithmetic",
        "difficulty": "sums_10", "pet_id": "scopedracer1"},
        cookies=anon_cookies())
    assert r.status_code == 200

    # The OTHER owner's world is unchanged: no listing, no read, no export.
    assert db.get_pet_for_owner("scopedracer1", ANON_OWNER_2) is None
    listed = app_client.get("/api/pets",
                            cookies=anon_cookies(ANON_OWNER_2)).json()
    assert all(p["id"] != "scopedracer1" for p in listed)
    assert app_client.get("/api/pets/scopedracer1/manifest.json",
                          cookies=anon_cookies(ANON_OWNER_2)).status_code == 404
