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

from conftest import make_pet  # noqa: E402


@pytest.fixture()
def app_client(dpp_env):
    from fastapi.testclient import TestClient
    import app as app_mod
    importlib.reload(app_mod)
    app_mod.db = dpp_env["db"]
    app_mod.datsme_integration = dpp_env["di"]
    return TestClient(app_mod.app)


# ---------------------------------------------------------------------------
# 1. Immutable asset caching
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("suffix", ["sheet.png", "manifest.json"])
def test_pet_assets_are_immutably_cacheable(app_client, dpp_env, suffix):
    """A pet's sheet/manifest never change under its (uuid) id, so the browser
    must be told it may cache them hard — otherwise the house re-downloads ~1 MB
    per pet on every reload and page-flip, which is what blanks cards behind 429s
    on a phone. `private`, never `public`: access is ownership-scoped."""
    make_pet(dpp_env["db"], pet_id="assetpet0001", external_user_id=None, draft=False)
    r = app_client.get(f"/api/pets/assetpet0001/{suffix}")
    assert r.status_code == 200
    cc = r.headers.get("cache-control", "")
    assert "immutable" in cc and "max-age=" in cc
    # Ownership-scoped content must never land in a shared proxy cache.
    assert "private" in cc and "public" not in cc
