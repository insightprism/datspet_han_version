"""House-scaling: immutable asset caching, the pet cap, and pagination.

The pet house grows without bound over time, and the real cost is on the CLIENT
(a phone): every card + the wandering PetStage decode a full sprite sheet, so an
unbounded house crashes a mobile tab on memory. The server stays cheap
(list_saved_pets is metadata-only; blobs are read one at a time on demand), so
these are the three defenses that keep a phone healthy:

  1. Immutable caching of per-pet assets, so a sheet is fetched once ever.
  2. A configurable cap (default 50), enforced at creation — block, never evict.
  3. Configurable page size (default 10) so only a page is ever mounted.

This file covers the server half of all three. The client half (paging the
display, feeding only a page to PetStage, visibility-pausing) is in web/.
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

from conftest import ANON_OWNER, anon_cookies, make_pet  # noqa: E402


@pytest.fixture()
def app_client(dpp_env):
    from fastapi.testclient import TestClient
    import app as app_mod
    importlib.reload(app_mod)
    app_mod.db = dpp_env["db"]
    app_mod.datsme_integration = dpp_env["di"]
    # An anonymous BROWSER, which is what a cookieless caller is in integrated mode
    # (SPEC_DATSPET_FEDERATED_SESSION §4.5). Pinned rather than middleware-minted so
    # the pets these tests create can be owned by the same id.
    return TestClient(app_mod.app, cookies=anon_cookies())


# ---------------------------------------------------------------------------
# 1. Immutable asset caching
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("suffix", ["sheet.png", "manifest.json"])
def test_pet_assets_are_immutably_cacheable(app_client, dpp_env, suffix):
    """A pet's sheet/manifest never change under its (uuid) id, so the browser
    must be told it may cache them hard — otherwise the house re-downloads ~1 MB
    per pet on every reload and page-flip, which is what blanks cards behind 429s
    on a phone. `private`, never `public`: access is ownership-scoped."""
    make_pet(dpp_env["db"], pet_id="assetpet0001", external_user_id=ANON_OWNER, draft=False)
    r = app_client.get(f"/api/pets/assetpet0001/{suffix}")
    assert r.status_code == 200
    cc = r.headers.get("cache-control", "")
    assert "immutable" in cc and "max-age=" in cc
    # Ownership-scoped content must never land in a shared proxy cache.
    assert "private" in cc and "public" not in cc


# ---------------------------------------------------------------------------
# 2. The cap + config
# ---------------------------------------------------------------------------

def test_house_config_reports_cap_page_size_and_count(app_client, dpp_env, monkeypatch):
    monkeypatch.setenv("PETMAKER_HOUSE_MAX_PETS", "3")
    monkeypatch.setenv("PETMAKER_HOUSE_PAGE_SIZE", "2")
    for i in range(2):
        make_pet(dpp_env["db"], pet_id=f"cfgpet{i:06}", external_user_id=ANON_OWNER, draft=False)
    cfg = app_client.get("/api/house").json()
    assert cfg == {"max_pets": 3, "page_size": 2, "count": 2}


def test_config_falls_back_on_garbage_env(app_client, monkeypatch):
    monkeypatch.setenv("PETMAKER_HOUSE_MAX_PETS", "not-a-number")
    monkeypatch.setenv("PETMAKER_HOUSE_PAGE_SIZE", "")
    cfg = app_client.get("/api/house").json()
    assert cfg["max_pets"] == 50 and cfg["page_size"] == 10


def test_keep_blocks_at_the_cap_but_never_evicts(app_client, dpp_env, monkeypatch):
    """A full house rejects the pet trying to join. The existing pets are
    untouched — we block, never evict (a bundle is irreplaceable)."""
    monkeypatch.setenv("PETMAKER_HOUSE_MAX_PETS", "2")
    db = dpp_env["db"]
    make_pet(db, pet_id="full00000001", external_user_id=ANON_OWNER, draft=False)
    make_pet(db, pet_id="full00000002", external_user_id=ANON_OWNER, draft=False)
    make_pet(db, pet_id="draft0000001", external_user_id=ANON_OWNER, draft=True)  # wants in

    r = app_client.post("/api/pets/draft0000001/keep")
    assert r.status_code == 409 and "full" in r.json()["detail"].lower()
    assert db.count_saved_pets(ANON_OWNER) == 2    # nothing evicted
    assert db.get_pet("draft0000001")["draft"] == 1  # still a draft


def test_rekeeping_a_saved_pet_at_the_cap_is_not_blocked(app_client, dpp_env, monkeypatch):
    """The cap gate fires only for a DRAFT joining. Re-keeping a pet already in a
    full house is idempotent and must not 409."""
    monkeypatch.setenv("PETMAKER_HOUSE_MAX_PETS", "1")
    db = dpp_env["db"]
    make_pet(db, pet_id="saved0000001", external_user_id=ANON_OWNER, draft=False)
    r = app_client.post("/api/pets/saved0000001/keep")
    assert r.status_code == 200


def test_generate_prechecks_the_cap_before_burning_gpu(app_client, dpp_env, monkeypatch):
    """A full house 409s /api/generate up front, so no ~3-min build is wasted on
    a pet that could never be kept."""
    monkeypatch.setenv("PETMAKER_HOUSE_MAX_PETS", "1")
    make_pet(dpp_env["db"], pet_id="full00000001", external_user_id=ANON_OWNER, draft=False)
    r = app_client.post("/api/generate", data={"reference_id": "whatever"})
    assert r.status_code == 409 and "full" in r.json()["detail"].lower()


def test_cap_gate_does_not_leak_another_users_pet(app_client, dpp_env, monkeypatch):
    """A standalone caller keeping another user's draft gets 404 (not a cap 409),
    so the gate can't be used to probe existence."""
    monkeypatch.setenv("PETMAKER_HOUSE_MAX_PETS", "1")
    db = dpp_env["db"]
    make_pet(db, pet_id="mine00000001", external_user_id=ANON_OWNER, draft=False)  # fills the cap
    make_pet(db, pet_id="theirs000001", external_user_id="user-B", draft=True)
    # standalone caller (no cookie) cannot access user-B's pet -> 404, never 409
    r = app_client.post("/api/pets/theirs000001/keep")
    assert r.status_code == 404
