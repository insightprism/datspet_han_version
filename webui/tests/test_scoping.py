"""BLOCKER 2 regression tests — per-user scoping of generation + ownership.

These FAIL if scoping is reverted (unscoped list_pets, missing Accept ownership
check, or a global draft purge). They drive the real app and read the DB.

Identity note: resolve_launch_identity VERIFIES the launch JWT, so tests mint a
real signed token via the SDK testkit (a nonce isn't needed — that only matters
for the writeback burn, not for identity/scoping). The cookie is the JSON blob
/launch sets: {token, user_id, ...}.
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

from conftest import TEST_SECRET, make_pet  # noqa: E402


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


def _cookie_for(user_id):
    """The launch cookie /launch would set for a user (real signed token)."""
    from datsme_partner_sdk.testkit import make_test_launch_token
    token = make_test_launch_token(
        hmac_secret=TEST_SECRET, user_id=user_id,
        activity_id="design_a_pet", partner_slug="datspet",
        capabilities=["pets.write"], ttl_seconds=3600)
    return json.dumps({"token": token, "user_id": user_id,
                       "activity_id": "design_a_pet", "jti": "t",
                       "capabilities": ["pets.write"]})


def test_two_users_see_only_their_own_saved_pets(app_client, dpp_env):
    db = dpp_env["db"]
    make_pet(db, pet_id="petA00000001", external_user_id="user-A", draft=False)
    make_pet(db, pet_id="petB00000001", external_user_id="user-B", draft=False)
    make_pet(db, pet_id="petLocal0001", external_user_id=None, draft=False)

    # user A sees their own + the local (unclaimed) pet, NEVER user B's.
    ra = app_client.get("/api/pets", cookies={"datsme_launch": _cookie_for("user-A")})
    ids_a = {p["id"] for p in ra.json()}
    assert "petA00000001" in ids_a
    assert "petLocal0001" in ids_a       # unclaimed local pets are shared/actionable
    assert "petB00000001" not in ids_a   # but NEVER another user's

    rb = app_client.get("/api/pets", cookies={"datsme_launch": _cookie_for("user-B")})
    ids_b = {p["id"] for p in rb.json()}
    assert "petB00000001" in ids_b
    assert "petA00000001" not in ids_b

    # standalone (no cookie) sees only the local pet.
    rs = app_client.get("/api/pets")
    ids_s = {p["id"] for p in rs.json()}
    assert ids_s == {"petLocal0001"}


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


def test_accept_rejects_another_users_pet(app_client, dpp_env):
    db = dpp_env["db"]
    make_pet(db, pet_id="petA00000003", external_user_id="user-A", draft=False)
    # user B tries to Accept user A's pet_id → 404, no writeback attempted.
    r = app_client.post("/api/datsme/accept", json={"pet_id": "petA00000003"},
                        cookies={"datsme_launch": _cookie_for("user-B")})
    assert r.status_code == 404, r.text
    # A's pet is untouched (still A's, not acked).
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

    # user A generates (free-text). Their purge must NOT remove user B's draft
    # nor the local draft (A's scope is user-A, which has no drafts here).
    r = app_client.post("/api/generate", data={"text": "a red fox"},
                        cookies={"datsme_launch": _cookie_for("user-A")})
    assert r.status_code == 200, r.text
    assert db.get_pet("draftB000001") is not None, "user B's draft was wrongly purged"
    assert db.get_pet("draftLocal01") is not None, "local draft was wrongly purged"
