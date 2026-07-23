"""Settings admin + store (SPEC_UPLOAD_LIKENESS §2.2, decision 6a).

Exercises the runtime feature-flag switchboard: the db.get_setting/set_setting KV
store, and webui/settings_admin.py against an isolated temp DB (dpp_env) with the
admin gate satisfied. No network, no GPU.
"""
import importlib

import pytest


# ── the KV store ─────────────────────────────────────────────────────────────

def test_settings_store_round_trips_and_defaults(dpp_env):
    import db
    # Unset key → the supplied default (never raises).
    assert db.get_setting("upload_isolate", "false") == "false"
    assert db.get_setting("no_such_key") is None
    # Set, read back.
    db.set_setting("upload_isolate", "true")
    assert db.get_setting("upload_isolate") == "true"
    # Upsert, not a second row — the value replaces in place.
    db.set_setting("upload_isolate", "false")
    assert db.get_setting("upload_isolate") == "false"
    rows = db._connect().execute(
        "SELECT COUNT(*) c FROM app_settings WHERE key='upload_isolate'").fetchone()
    assert rows["c"] == 1


# ── the admin API ────────────────────────────────────────────────────────────

@pytest.fixture()
def settings_client(dpp_env, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import settings_admin
    importlib.reload(settings_admin)

    app = FastAPI()
    app.include_router(settings_admin.router)
    app.dependency_overrides[settings_admin.datsme_integration.require_admin_launch] = lambda: None
    return TestClient(app)


def test_list_shows_upload_isolate_defaulting_off(settings_client):
    body = settings_client.get("/api/admin/settings").json()
    by_key = {s["key"]: s for s in body["settings"]}
    assert "upload_isolate" in by_key
    s = by_key["upload_isolate"]
    assert s["type"] == "bool"
    assert s["value"] is False and s["default"] is False   # default OFF (decision 6a)


def test_put_flips_the_flag_and_persists(settings_client):
    r = settings_client.put("/api/admin/settings/upload_isolate", json={"value": True})
    assert r.status_code == 200, r.text
    assert r.json()["updated"]["value"] is True
    # A fresh GET reflects it...
    body = settings_client.get("/api/admin/settings").json()
    assert next(s for s in body["settings"] if s["key"] == "upload_isolate")["value"] is True
    # ...and the store agrees (what app.py reads via bool_setting).
    import db
    assert db.get_setting("upload_isolate") == "true"


def test_put_unknown_key_is_404(settings_client):
    r = settings_client.put("/api/admin/settings/no_such_flag", json={"value": True})
    assert r.status_code == 404


def test_put_non_bool_value_is_rejected(settings_client):
    """Only declared settings, only their declared type — not an open KV from the web.
    A non-bool body is refused by the request model before it reaches the handler."""
    r = settings_client.put("/api/admin/settings/upload_isolate", json={"value": "banana"})
    assert r.status_code == 422
