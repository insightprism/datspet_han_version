"""The Pet Store's public surface (SPEC_PET_STORE §3.1, §7.2, §8, §9, §12).

Replaces test_adopt_sample.py: the adopt primitive is the same shape (copy
into the caller's house as a draft, public stamp, cap 409 before insert), but
the inventory is DB rows now, the entitlement is enforced server-side, and the
adopted copy records where it came from (source_store_pet_id) — the declared
price basis the DPP export reads.
"""
import hashlib
import importlib
import importlib.util
import os
import sys
from pathlib import Path

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WEBUI = os.path.join(REPO, "webui")
for p in (WEBUI, REPO):
    if p not in sys.path:
        sys.path.insert(0, p)

from conftest import (ANON_OWNER, ANON_OWNER_2, anon_cookies,  # noqa: E402
                      make_bundle_zip, make_pet)

WALK_IDLE = {"walk": {"frames": [0]}, "idle": {"frames": [1]}}
FAKE_PNG = b"\x89PNG\r\n\x1a\nDATA"


def make_store_pet(db_mod, store_id="store0000001", published=True,
                   animal="cat", display_name="Snowy The Leopard",
                   breed_id="white_snow_leopard",
                   description="A fluffy mountain cat.", tags=("cat", "fluffy"),
                   animations=None):
    zip_bytes, manifest_json = make_bundle_zip(
        breed_id=breed_id,
        animations=animations if animations is not None else dict(WALK_IDLE))
    db_mod.insert_store_pet(
        store_id=store_id, display_name=display_name, breed_id=breed_id,
        animal=animal, description=description, tags=list(tags),
        created_at=1783800000.0, preview_png=FAKE_PNG, sheet_png=FAKE_PNG,
        manifest_json=manifest_json, package_json=None, bundle_zip=zip_bytes,
        published=published)
    return store_id


@pytest.fixture()
def store_client(dpp_env):
    """A TestClient over the public store router alone — reloaded so its
    dependencies bind THIS test's dpp_env module state."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import pet_store
    importlib.reload(pet_store)
    app = FastAPI()
    app.include_router(pet_store.router)
    client = TestClient(app)
    client._pet_store = pet_store
    return client


# --- the listing -----------------------------------------------------------
def test_listing_shows_published_rows_only(store_client, dpp_env):
    make_store_pet(dpp_env["db"], store_id="pubpet000001", published=True)
    make_store_pet(dpp_env["db"], store_id="stagepet0001", published=False,
                   display_name="Not Ready Yet")

    body = store_client.get("/api/store").json()
    ids = [p["id"] for p in body["pets"]]
    assert ids == ["pubpet000001"]

    listing = body["pets"][0]
    assert listing["display_name"] == "Snowy The Leopard"
    assert listing["animal"] == "cat"
    assert listing["description"] == "A fluffy mountain cat."
    assert listing["tags"] == ["cat", "fluffy"]
    assert listing["pose_count"] == 2
    assert listing["poses"] == ["walk", "idle"]
    assert listing["preview_url"] == "/api/store/pubpet000001/preview.png"
    # Always true on this surface — not a browser fact (§3.1).
    assert "published" not in listing


def test_unpublished_is_invisible_not_just_unlisted(store_client, dpp_env):
    """§3.1: the staging shelf 404s exactly like an absent id, on the preview
    AND on adopt — being unlisted is not the same as being invisible."""
    make_store_pet(dpp_env["db"], store_id="stagepet0001", published=False)
    for sid in ("stagepet0001", "nosuchpet001"):
        assert store_client.get(f"/api/store/{sid}/preview.png").status_code == 404
        assert store_client.post(f"/api/store/{sid}/adopt",
                                 cookies=anon_cookies()).status_code == 404


def test_preview_serves_the_stored_portrait(store_client, dpp_env):
    make_store_pet(dpp_env["db"])
    r = store_client.get("/api/store/store0000001/preview.png")
    assert r.status_code == 200
    assert r.content == FAKE_PNG
    assert r.headers["content-type"] == "image/png"
    assert "max-age" in r.headers.get("cache-control", "")


# --- adopt -----------------------------------------------------------------
def test_adopt_copies_into_the_callers_house(store_client, dpp_env):
    import pet_ownership
    make_store_pet(dpp_env["db"])
    r = store_client.post("/api/store/store0000001/adopt",
                          cookies=anon_cookies())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["display_name"] == "Snowy The Leopard"

    row = dpp_env["db"].get_pet(body["pet_id"])
    assert row is not None
    assert row["external_user_id"] == ANON_OWNER
    assert row["draft"] == 1
    # §7.2 — the record of how the pet came to be: the export's price basis.
    assert row["source_store_pet_id"] == "store0000001"
    # The copy is a real pet: bytes round-tripped and the digest covers them.
    assert row["bundle_zip"] and row["sheet_png"] and row["manifest_json"]
    assert row["bundle_sha256"] == hashlib.sha256(row["bundle_zip"]).hexdigest()
    # Stamped `public` upstream of insert (SPEC_PET_OWNER_FIELD §2.4).
    category, name, _ = pet_ownership.read_pet_ownership(row["manifest_json"])
    assert (category, name) == (pet_ownership.PUBLIC_CATEGORY, "")


def test_two_adopts_are_two_pets(store_client, dpp_env):
    """A store pet is a template, not a licence (§3.1) — each adopt is its own
    pet id and therefore its own purchase at the host."""
    make_store_pet(dpp_env["db"])
    a = store_client.post("/api/store/store0000001/adopt", cookies=anon_cookies())
    b = store_client.post("/api/store/store0000001/adopt", cookies=anon_cookies())
    assert a.json()["pet_id"] != b.json()["pet_id"]


def test_an_adopted_copy_belongs_to_the_adopter_alone(store_client, dpp_env):
    make_store_pet(dpp_env["db"])
    pet_id = store_client.post("/api/store/store0000001/adopt",
                               cookies=anon_cookies()).json()["pet_id"]
    db = dpp_env["db"]
    assert db.get_pet_for_owner(pet_id, external_user_id=ANON_OWNER) is not None
    assert db.get_pet_for_owner(pet_id, external_user_id=ANON_OWNER_2) is None
    assert db.list_unsaved_pets(external_user_id=ANON_OWNER_2) == []


def test_a_full_house_409s_BEFORE_inserting(store_client, dpp_env, monkeypatch):
    monkeypatch.setenv("PETMAKER_HOUSE_MAX_PETS", "1")
    make_store_pet(dpp_env["db"])
    make_pet(dpp_env["db"], pet_id="fillsthehouse", external_user_id=ANON_OWNER,
             draft=False)

    r = store_client.post("/api/store/store0000001/adopt", cookies=anon_cookies())
    assert r.status_code == 409, r.text
    assert "full" in r.json()["detail"].lower()
    assert dpp_env["db"].list_unsaved_pets(external_user_id=ANON_OWNER) == []


def test_entitlement_is_enforced_server_side(store_client, dpp_env, monkeypatch):
    """§9 — the fix for the catalog spec's §0.6 hole: a tier without
    can_adopt_samples is refused by the SERVER, not just hidden by the page."""
    make_store_pet(dpp_env["db"])
    pet_store = store_client._pet_store
    monkeypatch.setattr(
        pet_store.tiers_mod, "resolve_entitlement",
        lambda caps: {"tier": "base", "can_adopt_samples": False})

    r = store_client.post("/api/store/store0000001/adopt", cookies=anon_cookies())
    assert r.status_code == 403, r.text
    assert dpp_env["db"].list_unsaved_pets(external_user_id=ANON_OWNER) == []


# --- the export's declared price basis (§7.2) ------------------------------
def test_export_declares_the_price_basis_per_item(dpp_env):
    """A store-adopted pet exports `store_flat`; a designed pet `per_pose` —
    and pose_count stays declared either way (the host still validates the
    artifact against it). Forgetting this seam silently prices every store
    pet per-pose, which is why it gets its own test."""
    db_mod, di = dpp_env["db"], dpp_env["di"]
    make_pet(db_mod, pet_id="designedpet1", external_user_id="user-1",
             draft=False, animations=dict(WALK_IDLE))
    zip_bytes, manifest_json = make_bundle_zip(breed_id="white_snow_leopard",
                                               animations=dict(WALK_IDLE))
    db_mod.insert_pet(
        pet_id="storeadopted", breed_id="white_snow_leopard",
        display_name="Snowy", created_at=1783800001.0, draft=False,
        sheet_png=FAKE_PNG, manifest_json=manifest_json, package_json=None,
        bundle_zip=zip_bytes, external_user_id="user-1",
        source_store_pet_id="store0000001")

    items = {r["id"]: di._export_item(r) for r in db_mod.export_pets("user-1")}
    assert items["storeadopted"]["price_basis"] == di.PRICE_BASIS_STORE_FLAT
    assert items["designedpet1"]["price_basis"] == di.PRICE_BASIS_PER_POSE
    assert items["storeadopted"]["pose_count"] == 2


# --- the §8 migration ------------------------------------------------------
def _load_migration_module():
    path = Path(REPO) / "scripts" / "migrate_samples_to_store.py"
    spec = importlib.util.spec_from_file_location("migrate_samples_to_store", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_migration_floor_the_store_cannot_launch_empty(dpp_env, tmp_path,
                                                       monkeypatch):
    """§12 floor test: after the migration runs against a samples fixture, at
    least one PUBLISHED store pet exists — the shop never replaces the sample
    grid with an empty shelf. Runs against a fixture (not the repo files),
    because the physical sample files are deleted once every environment has
    migrated (§8 Rev.3)."""
    mig = _load_migration_module()
    samples = tmp_path / "cat" / "samples"
    samples.mkdir(parents=True)
    zip_bytes, _ = make_bundle_zip(breed_id="snowleopard",
                                   animations=dict(WALK_IDLE))
    (samples / "snowleopard.zip").write_bytes(zip_bytes)
    (samples / "snowleopard.png").write_bytes(FAKE_PNG)
    monkeypatch.setattr(mig, "CATALOG_DIR", tmp_path)

    assert mig.migrate() == 1
    listings = dpp_env["db"].list_store_pets(published_only=True)
    assert len(listings) == 1
    assert listings[0]["animal"] == "cat"
    assert listings[0]["pose_count"] == 2

    # Idempotent on bundle_sha256 — a re-run is a no-op, not a duplicate shelf.
    assert mig.migrate() == 0
    assert len(dpp_env["db"].list_store_pets(published_only=False)) == 1
