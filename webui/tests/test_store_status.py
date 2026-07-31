"""The shelf lifecycle (SPEC_PET_STORE §1.4) — Phase 1b.

A `published` boolean could not tell apart the three different reasons a pet is
not for sale, and those three are exactly what an admin acts on: the inbox, the
thing held back deliberately, and the thing decided against.

What each case protects:
- a shopper sees `shelf` and ONLY `shelf` — the other three are invisible, not
  merely unlisted (they 404 on preview AND adopt, like an absent id);
- the sellability gate moved with the meaning: it guards the way ONTO the
  shelf, and nothing else — you may keep something you cannot sell;
- `animal` freezes on the FIRST shelving and stays frozen, which is the case
  the boolean could not express (shelf → backroom → re-animal → shelf);
- `archived` is reversible, because a terminal state is what pushes people
  toward hard deletes;
- the migration backfills a real pre-1b database and is a no-op on re-run.
"""
import json
import os
import sqlite3
import sys
import tempfile

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WEBUI = os.path.join(REPO, "webui")
for p in (WEBUI, REPO):
    if p not in sys.path:
        sys.path.insert(0, p)

from conftest import anon_cookies, make_bundle_zip  # noqa: E402


@pytest.fixture()
def store_client(dpp_env):
    """The public shop router alone, reloaded so it binds THIS test's env."""
    import importlib
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import pet_store
    importlib.reload(pet_store)
    app = FastAPI()
    app.include_router(pet_store.router)
    return TestClient(app)


@pytest.fixture()
def admin_client(dpp_env, monkeypatch):
    """The admin router with the gate overridden — the gate itself is pinned
    by test_store_admin; this file is about what happens behind it."""
    import importlib
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import store_admin
    importlib.reload(store_admin)
    app = FastAPI()
    app.include_router(store_admin.router)
    app.dependency_overrides[
        store_admin.datsme_integration.require_admin_launch] = lambda: None
    monkeypatch.setattr(store_admin.datsme_integration, "admin_user_id",
                        lambda request: "admin-1")
    return TestClient(app)

WALK_IDLE = {"walk": {"frames": [0]}, "idle": {"frames": [1]}}
FAKE_PNG = b"\x89PNG\r\n\x1a\nDATA"

OFF_SHELF = ("intake", "backroom", "archived")


def _row(db_mod, store_id, status="intake", animations=None, animal="cat"):
    zip_bytes, manifest_json = make_bundle_zip(
        breed_id="shelfcat",
        animations=animations if animations is not None else dict(WALK_IDLE))
    db_mod.insert_store_pet(
        store_id=store_id, display_name="Shelf Cat", breed_id="shelfcat",
        animal=animal, description="", tags=[], created_at=1783800000.0,
        preview_png=FAKE_PNG, sheet_png=FAKE_PNG, manifest_json=manifest_json,
        package_json=None, bundle_zip=zip_bytes, status=status)
    return store_id


# --- the shopper's view ----------------------------------------------------
@pytest.mark.parametrize("status", OFF_SHELF)
def test_only_shelf_rows_are_visible_to_a_shopper(store_client, dpp_env, status):
    """Invisible, not unlisted. An off-shelf id must be indistinguishable from
    one that never existed — otherwise the shelf leaks what is staged."""
    db = dpp_env["db"]
    _row(db, "offshelf0001", status=status)
    _row(db, "onshelf00001", status="shelf")

    listed = store_client.get("/api/store").json()["pets"]
    assert [p["id"] for p in listed] == ["onshelf00001"]
    assert store_client.get("/api/store/offshelf0001/preview.png").status_code == 404
    assert store_client.post("/api/store/offshelf0001/adopt",
                             cookies=anon_cookies()).status_code == 404


def test_the_listing_never_leaks_admin_state(store_client, dpp_env):
    """On this surface `status` has exactly one possible value, so shipping it
    would be a field that says nothing — and `admin_note` is not shoppers'."""
    _row(dpp_env["db"], "onshelf00001", status="shelf")
    listing = store_client.get("/api/store").json()["pets"][0]
    for admin_only in ("status", "admin_note", "first_shelved_at"):
        assert admin_only not in listing


# --- the admin's transitions -----------------------------------------------
def _put(client, store_id, **over):
    """The CONTENT door — authored fields only. Carries no status by design."""
    body = {"display_name": "Shelf Cat", "description": "", "tags": [],
            "animal": "cat", "admin_note": ""}
    body.update(over)
    return client.put(f"/api/admin/store/{store_id}", json=body)


def _state(client, store_id, status, **over):
    """The LIFECYCLE door — one shelf move, no prior read (§3.2)."""
    body = {"status": status}
    body.update(over)
    return client.post(f"/api/admin/store/{store_id}/status", json=body)


@pytest.mark.parametrize("status", OFF_SHELF)
def test_every_transition_is_free_except_the_way_onto_the_shelf(
        admin_client, dpp_env, status):
    """There is no ordering an admin could violate, so there is no state
    machine to encode — including archived → backroom, because a terminal
    state is what makes people reach for delete instead."""
    db = dpp_env["db"]
    _row(db, "storerow0001", status="archived")
    r = _state(admin_client, "storerow0001", status)
    assert r.status_code == 200, r.text
    assert db.get_store_pet("storerow0001")["status"] == status


def test_an_unsellable_bundle_may_be_KEPT_but_not_shelved(admin_client, dpp_env):
    """The gate guards the way onto the shelf and nothing else: you may keep
    something you cannot sell, you may not sell it."""
    db = dpp_env["db"]
    _row(db, "storerow0001", status="intake", animations={})   # no poses

    r = _state(admin_client, "storerow0001", "shelf")
    assert r.status_code == 422
    assert db.get_store_pet("storerow0001")["status"] == "intake"

    for keep in ("backroom", "archived"):
        assert _state(admin_client, "storerow0001", keep).status_code == 200


def test_an_unknown_status_is_refused_with_the_allowed_set(admin_client, dpp_env):
    _row(dpp_env["db"], "storerow0001")
    r = _state(admin_client, "storerow0001", "banana")
    assert r.status_code == 422
    assert "intake" in json.dumps(r.json())


def test_animal_freezes_on_the_FIRST_shelving_and_stays_frozen(
        admin_client, dpp_env):
    """The case the boolean could not express. Under `published` a row taken
    off the shelf looked identical to one never on it, so a shelf → backroom →
    re-animal → shelf round trip would change a listing shoppers had already
    filtered on."""
    db = dpp_env["db"]
    _row(db, "storerow0001", status="intake")

    # Free before it has ever been shelved.
    assert _put(admin_client, "storerow0001", animal="dog").status_code == 200
    assert _state(admin_client, "storerow0001", "shelf").status_code == 200
    stamped = db.get_store_pet("storerow0001")["first_shelved_at"]
    assert stamped is not None

    # Frozen on the shelf...
    assert _put(admin_client, "storerow0001", animal="cat").status_code == 409
    # ...and STILL frozen after moving off it — the whole point.
    assert _state(admin_client, "storerow0001", "backroom").status_code == 200
    assert _put(admin_client, "storerow0001", animal="dog").status_code == 200
    assert _put(admin_client, "storerow0001", animal="cat").status_code == 409
    # Re-shelving never re-stamps the timestamp.
    _state(admin_client, "storerow0001", "shelf")
    assert db.get_store_pet("storerow0001")["first_shelved_at"] == stamped


def test_the_admin_note_is_stored_for_whoever_reads_it_later(admin_client, dpp_env):
    db = dpp_env["db"]
    _row(db, "storerow0001")
    _state(admin_client, "storerow0001", "archived",
           admin_note="muddy colours, never sold")
    assert db.get_store_pet("storerow0001")["admin_note"] == \
        "muddy colours, never sold"


# --- the migration ---------------------------------------------------------
def test_the_migration_backfills_a_real_pre_1b_database_and_re_runs_clean(
        monkeypatch):
    """Built against the OLD schema by hand, because the risk being tested is
    an existing production table, not a fresh one."""
    import importlib
    tmp = tempfile.mkdtemp()
    monkeypatch.setenv("PETMAKER_OUTPUT_DIR", tmp)
    monkeypatch.setenv("PETMAKER_DB_PATH", os.path.join(tmp, "datspet.db"))

    conn = sqlite3.connect(os.path.join(tmp, "datspet.db"))
    conn.execute("""CREATE TABLE store_pets (
        id TEXT PRIMARY KEY, display_name TEXT NOT NULL, breed_id TEXT NOT NULL,
        animal TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
        tags_json TEXT NOT NULL DEFAULT '[]', pose_count INTEGER NOT NULL,
        published INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL,
        bundle_sha256 TEXT NOT NULL, size_bytes INTEGER NOT NULL,
        preview_png BLOB NOT NULL, sheet_png BLOB NOT NULL,
        manifest_json TEXT NOT NULL, package_json TEXT, bundle_zip BLOB NOT NULL)""")
    manifest = json.dumps({"animations": {"walk": {}, "idle": {}}})
    for sid, published in (("live0001", 1), ("stage001", 0)):
        conn.execute(
            "INSERT INTO store_pets VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (sid, "N", "b", "cat", "", "[]", 2, published, 1783800000.0,
             "sha", 1, b"p", b"s", manifest, None, b"z"))
    conn.commit()
    conn.close()

    import db as db_mod
    importlib.reload(db_mod)
    db_mod.init_db()
    db_mod.init_db()          # a second boot must change nothing

    cols = {r["name"] for r in
            db_mod._connect().execute("PRAGMA table_info(store_pets)")}
    assert "published" not in cols, "two sources of truth is the bug being removed"
    assert {"status", "admin_note", "first_shelved_at"} <= cols

    rows = {r["id"]: r for r in db_mod._connect().execute(
        "SELECT id, status, first_shelved_at FROM store_pets")}
    assert rows["live0001"]["status"] == "shelf"
    assert rows["live0001"]["first_shelved_at"] == 1783800000.0
    assert rows["stage001"]["status"] == "intake"
    assert rows["stage001"]["first_shelved_at"] is None


def test_a_PARTIAL_migration_completes_on_the_next_boot(monkeypatch):
    """The crash window B3 names: sqlite autocommits each ALTER, so a crash
    after the columns are added but before the backfill leaves `status`
    present. A once-only guard keyed on `status` reads that as "done" and skips
    the backfill forever — every listing stuck in `intake`, a silently empty
    shop with no error anywhere."""
    import importlib
    tmp = tempfile.mkdtemp()
    monkeypatch.setenv("PETMAKER_OUTPUT_DIR", tmp)
    monkeypatch.setenv("PETMAKER_DB_PATH", os.path.join(tmp, "datspet.db"))

    conn = sqlite3.connect(os.path.join(tmp, "datspet.db"))
    conn.execute("""CREATE TABLE store_pets (
        id TEXT PRIMARY KEY, display_name TEXT NOT NULL, breed_id TEXT NOT NULL,
        animal TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
        tags_json TEXT NOT NULL DEFAULT '[]', pose_count INTEGER NOT NULL,
        published INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL,
        bundle_sha256 TEXT NOT NULL, size_bytes INTEGER NOT NULL,
        preview_png BLOB NOT NULL, sheet_png BLOB NOT NULL,
        manifest_json TEXT NOT NULL, package_json TEXT, bundle_zip BLOB NOT NULL)""")
    manifest = json.dumps({"animations": {"walk": {}, "idle": {}}})
    conn.execute("INSERT INTO store_pets VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 ("live0001", "N", "b", "cat", "", "[]", 2, 1, 1783800000.0,
                  "sha", 1, b"p", b"s", manifest, None, b"z"))
    # THE PARTIAL STATE: columns added, backfill never ran, published still here.
    conn.execute("ALTER TABLE store_pets ADD COLUMN status TEXT NOT NULL DEFAULT 'intake'")
    conn.execute("ALTER TABLE store_pets ADD COLUMN admin_note TEXT NOT NULL DEFAULT ''")
    conn.execute("ALTER TABLE store_pets ADD COLUMN first_shelved_at REAL")
    conn.commit()
    conn.close()

    import db as db_mod
    importlib.reload(db_mod)
    db_mod.init_db()

    cols = {r["name"] for r in
            db_mod._connect().execute("PRAGMA table_info(store_pets)")}
    assert "published" not in cols, "the interrupted step must complete"
    row = db_mod._connect().execute(
        "SELECT status, first_shelved_at FROM store_pets").fetchone()
    assert row["status"] == "shelf", "the shelved listing must not be stranded"
    assert row["first_shelved_at"] == 1783800000.0


def test_a_PUT_without_admin_note_preserves_the_stored_one(admin_client, dpp_env):
    """Someone wrote why this was archived months ago. A client that simply
    does not send the field must not erase it."""
    db = dpp_env["db"]
    _row(db, "storerow0001")
    _state(admin_client, "storerow0001", "archived",
           admin_note="muddy colours, never sold")

    body = {"display_name": "Shelf Cat", "description": "", "tags": [],
            "animal": "cat"}                                # no admin_note
    assert admin_client.put("/api/admin/store/storerow0001",
                            json=body).status_code == 200
    assert db.get_store_pet("storerow0001")["admin_note"] == \
        "muddy colours, never sold"
