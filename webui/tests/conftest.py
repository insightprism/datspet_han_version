"""Shared fixtures for the DatsPet partner-surface tests.

Every test runs against an ISOLATED SQLite DB (a temp file) and a fresh app
instance, so tests never touch the real pet house and don't depend on ordering.
The DPP env is set to known test values before webui modules import.
"""
import importlib
import os
import sys
import tempfile

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WEBUI = os.path.join(REPO, "webui")
for p in (WEBUI, REPO):
    if p not in sys.path:
        sys.path.insert(0, p)

TEST_SECRET = "test-hmac-secret-0123456789abcdef"


@pytest.fixture()
def dpp_env(tmp_path, monkeypatch):
    """Point the webui at a throwaway DB + known DPP env, then (re)import db and
    datsme_integration fresh so module-level config picks up the env."""
    db_path = tmp_path / "datspet_test.db"
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    monkeypatch.setenv("PETMAKER_OUTPUT_DIR", str(out_dir))
    monkeypatch.setenv("PETMAKER_DB_PATH", str(db_path))
    monkeypatch.setenv("DATSME_HMAC_SECRET", TEST_SECRET)
    monkeypatch.setenv("DATSME_PARTNER_SLUG", "datspet")
    monkeypatch.setenv("DATSPET_PUBLIC_URL", "http://127.0.0.1:19954")
    monkeypatch.setenv("DATSPET_FRONTEND_URL", "http://127.0.0.1:19955")
    monkeypatch.setenv("DATSME_BASE_URL", "http://127.0.0.1:19994")
    monkeypatch.setenv("DATSME_PUBLIC_URL", "http://127.0.0.1:19995")

    # Fresh module state bound to the temp DB.
    import db as db_mod
    importlib.reload(db_mod)
    db_mod._conn = None  # force a new connection to the temp path
    db_mod.DB_PATH = db_path
    db_mod.OUTPUT_DIR = out_dir
    db_mod.init_db()

    import datsme_integration as di
    importlib.reload(di)

    yield {"db": db_mod, "di": di, "secret": TEST_SECRET}


@pytest.fixture()
def client(dpp_env):
    """A TestClient over a fresh app that mounts the reloaded router + shares
    the temp DB."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(dpp_env["di"].router)
    return TestClient(app)


def make_pet(db_mod, pet_id="testpet00001", external_user_id=None, draft=False,
             breed_id="test_breed", display_name="Test Pet"):
    """Insert a minimal valid pet row for tests."""
    db_mod.insert_pet(
        pet_id=pet_id, breed_id=breed_id, display_name=display_name,
        created_at=1783800000.0, draft=draft,
        sheet_png=b"\x89PNG\r\n\x1a\nDATA", manifest_json='{"animations":{}}',
        package_json=None, bundle_zip=b"PK\x03\x04zip",
        external_user_id=external_user_id,
    )
    return pet_id
