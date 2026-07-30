"""adopt-a-sample — the endpoint's first tests (SPEC_DATSPET_CATALOG_PURCHASE §4 step 2).

`POST /api/catalog/{animal}/samples/{sample}/adopt` has existed and been reachable
since the platform work, and until now **nothing executed it but a manual curl** —
`api.ts`'s own note said so in capitals. The catalog page is its first real
consumer, so this is the file that has to exist before that page does.

What each case is actually protecting:

- **The happy path** proves the copy is a real pet, not a row: the bundle bytes
  round-trip, so the thing the user adopted is the thing the host will later fetch
  and price. A pet whose zip did not survive is invisible at checkout with no error
  (`import_routes.py` skips an item it cannot quote).
- **Owner scoping** is the whole identity model. adopt writes with the caller's
  owner id, and a second browser must not see it. This is the same WHERE-clause
  rule as everything else, and the reason it gets its own test here is that adopt
  is the one write path that never went through the designer.
- **The cap 409s BEFORE the insert**, not after. Handing a user a draft they cannot
  keep is the failure `_enforce_house_not_full` was added to prevent, and "did it
  insert anyway" is invisible from the status code alone.
- **Unknown animal / sample → 404**, and
- **a non-alnum key → 404 without touching the filesystem.** The key becomes a path
  segment; the validation is what stops `../` from being one.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WEBUI = os.path.join(REPO, "webui")
for p in (WEBUI, REPO):
    if p not in sys.path:
        sys.path.insert(0, p)

import pytest  # noqa: E402

from conftest import ANON_OWNER, ANON_OWNER_2, anon_cookies  # noqa: E402

# The one promoted sample (SPEC_DATSPET_CATALOG_PURCHASE §0.1). If this pair stops
# existing the tests below fail loudly rather than skipping — a sample that quietly
# vanished is exactly what the content guard test in pet_factory/tests is for.
ANIMAL, SAMPLE = "cat", "snowleopard"


@pytest.fixture()
def app_client(dpp_env):
    import importlib
    from fastapi.testclient import TestClient
    import app as app_mod
    importlib.reload(app_mod)
    app_mod.db = dpp_env["db"]
    app_mod.datsme_integration = dpp_env["di"]
    return TestClient(app_mod.app)


def _adopt(client, animal=ANIMAL, sample=SAMPLE, **kw):
    return client.post(f"/api/catalog/{animal}/samples/{sample}/adopt", **kw)


def test_the_promoted_sample_is_actually_offered(app_client):
    """Guards the fixture the rest of this file rests on: /api/catalog really
    serves the sample, so a failure below is the endpoint's fault, not missing
    content."""
    animals = app_client.get("/api/catalog").json()["animals"]
    cat = next(a for a in animals if a["key"] == ANIMAL)
    keys = [s["key"] for s in cat["samples"]]
    assert SAMPLE in keys, f"{ANIMAL}/{SAMPLE} is not promoted — see §0.1"
    assert cat["samples"][keys.index(SAMPLE)]["preview_url"]


def test_adopt_copies_the_bundle_into_the_callers_house(app_client, dpp_env):
    """Zero GPU, same insert path a generated pet takes, minus the build."""
    r = _adopt(app_client, cookies=anon_cookies())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["pet_id"] and body["display_name"]

    row = dpp_env["db"].get_pet(body["pet_id"])
    assert row is not None
    assert row["external_user_id"] == ANON_OWNER      # the caller's own scope
    assert row["draft"] == 1                          # a draft until they keep it
    # The BYTES round-tripped. Without this the pet exists and is unsellable: the
    # host cannot price what it cannot fetch.
    assert row["bundle_zip"] and len(row["bundle_zip"]) > 1000
    assert row["sheet_png"] and row["manifest_json"]


def test_an_adopted_pet_belongs_to_the_adopter_alone(app_client, dpp_env):
    """The identity model, on the one write path that never went through the
    designer. A second browser must not see it — 404, not 403, so the reply does
    not confirm the pet exists."""
    pet_id = _adopt(app_client, cookies=anon_cookies()).json()["pet_id"]

    other = anon_cookies(ANON_OWNER_2)
    assert app_client.get(f"/api/pets/{pet_id}/zip", cookies=other).status_code == 404
    assert app_client.delete(f"/api/pets/{pet_id}", cookies=other).status_code == 404
    assert dpp_env["db"].get_pet(pet_id) is not None          # survived the attempt

    # And it is not in the other browser's house at all.
    assert app_client.get("/api/pets", cookies=other).json() == []


def test_a_full_house_409s_BEFORE_inserting(app_client, dpp_env, monkeypatch):
    """Block, never hand over a draft that cannot be kept. The status code alone
    cannot tell you whether the row went in anyway, so count the rows."""
    monkeypatch.setenv("PETMAKER_HOUSE_MAX_PETS", "1")
    from conftest import make_pet
    make_pet(dpp_env["db"], pet_id="fillsthehouse", external_user_id=ANON_OWNER,
             draft=False)
    before = dpp_env["db"].count_saved_pets(external_user_id=ANON_OWNER)

    r = _adopt(app_client, cookies=anon_cookies())
    assert r.status_code == 409, r.text
    assert "full" in r.json()["detail"].lower()
    assert dpp_env["db"].count_saved_pets(external_user_id=ANON_OWNER) == before
    # Nothing was inserted — not even a draft the cap check would later have to
    # clean up.
    assert len(dpp_env["db"].list_unsaved_pets(external_user_id=ANON_OWNER)) == 0


@pytest.mark.parametrize("animal,sample", [
    ("cat", "nosuchsample"),
    ("nosuchanimal", "snowleopard"),
    ("dog", "snowleopard"),          # right sample, wrong animal
])
def test_unknown_animal_or_sample_404s(app_client, animal, sample):
    assert _adopt(app_client, animal, sample, cookies=anon_cookies()).status_code == 404


@pytest.mark.parametrize("bad", ["../../etc/passwd", "snow leopard", "snow.leopard", "a/b"])
def test_a_non_alnum_key_404s_without_touching_the_filesystem(app_client, bad, monkeypatch):
    """The key becomes a path segment. `isalnum()` is what stops that being a
    traversal, and the assertion that matters is that nothing was READ — a 404
    produced after opening a file is a different bug wearing the same status code."""
    import pet_factory.animal_catalog as ac
    opened = []
    real = ac.sample_bundle_path
    monkeypatch.setattr(ac, "sample_bundle_path",
                        lambda a, s: (opened.append((a, s)), real(a, s))[1])

    r = _adopt(app_client, ANIMAL, bad, cookies=anon_cookies())
    assert r.status_code == 404
    assert opened == [], f"validation ran AFTER a path lookup: {opened}"

    # Prove the INSTRUMENT, not just the result: a valid key must reach the very
    # lookup the assertion above says a bad one never gets to. Without this the
    # test passes just as happily against a spy that could never fire — which is
    # how a decorative test looks from the outside.
    assert _adopt(app_client, ANIMAL, SAMPLE, cookies=anon_cookies()).status_code == 200
    assert opened == [(ANIMAL, SAMPLE)], "the spy never fired for a VALID key"
