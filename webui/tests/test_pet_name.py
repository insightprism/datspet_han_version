"""Pet naming (owner ask 2026-08-02) — the child's first name for a pet.

The stored value is the FIRST name only; the frontend composes
"«pet_name» «animal»" ("Joe Leopard") at display time. These pin the three
things that matter: the rename is owner-scoped exactly like keep/delete, an
empty name clears back to the breed display name, and nothing else on the row
(and nothing in the bundle) is touched by a rename.
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

from conftest import ANON_OWNER, ANON_OWNER_2, anon_cookies, make_pet  # noqa: E402


@pytest.fixture()
def app_client(dpp_env):
    """Full webui app sharing the temp DB, the test_scoping pattern."""
    from fastapi.testclient import TestClient
    import app as app_mod
    importlib.reload(app_mod)
    app_mod.db = dpp_env["db"]
    app_mod.datsme_integration = dpp_env["di"]
    return TestClient(app_mod.app)


def test_rename_persists_and_lists(app_client, dpp_env):
    db = dpp_env["db"]
    make_pet(db, pet_id="namedpet0001", external_user_id=ANON_OWNER,
             display_name="White Snow Leopard")

    r = app_client.post("/api/pets/namedpet0001/name",
                        json={"name": "Joe"}, cookies=anon_cookies())
    assert r.status_code == 200
    assert r.json() == {"id": "namedpet0001", "pet_name": "Joe"}

    listed = app_client.get("/api/pets", cookies=anon_cookies()).json()
    row = next(p for p in listed if p["id"] == "namedpet0001")
    assert row["pet_name"] == "Joe"
    # display_name is untouched — the compose happens at read time, client-side.
    assert row["display_name"] == "White Snow Leopard"


def test_empty_name_clears(app_client, dpp_env):
    db = dpp_env["db"]
    make_pet(db, pet_id="namedpet0002", external_user_id=ANON_OWNER)
    app_client.post("/api/pets/namedpet0002/name",
                    json={"name": "Momo"}, cookies=anon_cookies())
    r = app_client.post("/api/pets/namedpet0002/name",
                        json={"name": "   "}, cookies=anon_cookies())
    assert r.status_code == 200
    assert r.json()["pet_name"] is None


def test_rename_is_owner_scoped(app_client, dpp_env):
    # Another browser's anonymous identity must 404, exactly like delete/keep —
    # extend-test_scoping-not-trust-a-review (SPEC_PET_STORE §1.2 posture).
    db = dpp_env["db"]
    make_pet(db, pet_id="namedpet0003", external_user_id=ANON_OWNER)
    r = app_client.post("/api/pets/namedpet0003/name",
                        json={"name": "Mine"},
                        cookies=anon_cookies(ANON_OWNER_2))
    assert r.status_code == 404
    listed = app_client.get("/api/pets", cookies=anon_cookies()).json()
    assert next(p for p in listed if p["id"] == "namedpet0003")["pet_name"] is None


def test_name_bounds(app_client, dpp_env):
    db = dpp_env["db"]
    make_pet(db, pet_id="namedpet0004", external_user_id=ANON_OWNER)
    import app as app_mod
    too_long = "x" * (app_mod.PET_NAME_MAX_CHARS + 1)
    r = app_client.post("/api/pets/namedpet0004/name",
                        json={"name": too_long}, cookies=anon_cookies())
    assert r.status_code == 422
    # Whitespace runs collapse — "  Joe   Jr  " stores as "Joe Jr".
    r = app_client.post("/api/pets/namedpet0004/name",
                        json={"name": "  Joe   Jr  "}, cookies=anon_cookies())
    assert r.json()["pet_name"] == "Joe Jr"
