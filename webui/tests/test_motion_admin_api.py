"""API tests for the motion-profile admin CRUD (SPEC_MOTION_PROFILE_ADMIN §4).

Exercises webui/motion_admin.py against a TEMP copy of the profiles dir, with the
admin gate satisfied (a stubbed require_admin_launch). No GPU.
"""
import copy
import importlib
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WEBUI = os.path.join(REPO, "webui")
for p in (WEBUI, REPO):
    if p not in sys.path:
        sys.path.insert(0, p)


@pytest.fixture()
def admin_client(tmp_path, monkeypatch):
    """A TestClient over the motion_admin router, with a temp writable profiles
    dir and the admin gate open."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from pet_factory import motion_profiles as mp
    from pet_factory.motion_profiles import admin as mp_admin

    src = Path(mp.__file__).resolve().parent
    dst = tmp_path / "motion_profiles"
    dst.mkdir()
    for f in src.glob("*.json"):
        shutil.copy(f, dst / f.name)
    monkeypatch.setattr(mp, "_DIR", dst)
    monkeypatch.setattr(mp_admin, "_DIR", dst)
    mp.reload()

    import motion_admin
    importlib.reload(motion_admin)
    # Make the instance writable + stub the audit identity.
    monkeypatch.setattr(motion_admin.datsme_integration, "admin_user_id", lambda request: "admin-1")
    monkeypatch.setattr(motion_admin, "_writable", lambda: True)
    monkeypatch.setenv("MOTION_ADMIN_WRITABLE", "1")

    app = FastAPI()
    app.include_router(motion_admin.router)
    # Open the admin gate via dependency_overrides (the router bound the dependency
    # at import, so override the callable FastAPI resolves, not the module attr).
    app.dependency_overrides[motion_admin.datsme_integration.require_admin_launch] = lambda: None
    client = TestClient(app)
    client._dst = dst  # expose for assertions
    yield client
    mp.reload()


def _new_profile(key="testbeast"):
    from pet_factory import motion_profiles as mp
    base = copy.deepcopy(json.loads((Path(mp.__file__).resolve().parent.parent /
                                     "motion_profiles" / "quadruped.json").read_text()))
    # ^ read from the REAL source for a valid template, then re-key
    base["key"] = key
    base["keywords"] = []
    return base


# --- read ------------------------------------------------------------------
def test_list_returns_all_profiles(admin_client):
    r = admin_client.get("/api/admin/motions")
    assert r.status_code == 200
    body = r.json()
    keys = {p["key"] for p in body["profiles"]}
    assert {"quadruped", "avian", "serpentine", "aquatic", "winged_flyer"} <= keys
    assert body["default"] == "quadruped"
    quad = next(p for p in body["profiles"] if p["key"] == "quadruped")
    assert quad["is_default"] is True
    assert "walk" in quad["enabled_poses"]


def test_get_one_returns_full_json(admin_client):
    r = admin_client.get("/api/admin/motions/quadruped")
    assert r.status_code == 200
    assert r.json()["profile"]["key"] == "quadruped"


def test_get_unknown_404(admin_client):
    assert admin_client.get("/api/admin/motions/nope").status_code == 404


# --- create / update / delete / duplicate ----------------------------------
def test_create_then_list_shows_it(admin_client):
    r = admin_client.post("/api/admin/motions",
                          json={"profile": _new_profile("testbeast"), "label": "Test Beast"})
    assert r.status_code == 200, r.text
    keys = {p["key"] for p in admin_client.get("/api/admin/motions").json()["profiles"]}
    assert "testbeast" in keys


def test_create_invalid_422_with_errors(admin_client):
    bad = _new_profile("brokenone")
    bad["poses"].pop("run")
    r = admin_client.post("/api/admin/motions", json={"profile": bad, "label": "x"})
    assert r.status_code == 422
    assert r.json()["detail"]["error"] == "validation_failed"
    assert any("run" in e or "canonical" in e for e in r.json()["detail"]["errors"])


def test_update_changes_the_file(admin_client):
    admin_client.post("/api/admin/motions", json={"profile": _new_profile("testbeast"), "label": "x"})
    p = _new_profile("testbeast")
    p["movement_class"] = "updated_class"
    r = admin_client.put("/api/admin/motions/testbeast", json={"profile": p, "label": "New Label"})
    assert r.status_code == 200, r.text
    assert admin_client.get("/api/admin/motions/testbeast").json()["profile"]["movement_class"] == "updated_class"


def test_delete_default_409(admin_client):
    r = admin_client.delete("/api/admin/motions/quadruped")
    assert r.status_code == 409


def test_delete_ok_for_unpinned(admin_client):
    admin_client.post("/api/admin/motions", json={"profile": _new_profile("testbeast"), "label": "x"})
    r = admin_client.delete("/api/admin/motions/testbeast")
    assert r.status_code == 200
    assert "testbeast" not in {p["key"] for p in admin_client.get("/api/admin/motions").json()["profiles"]}


def test_duplicate_creates_clone(admin_client):
    r = admin_client.post("/api/admin/motions/quadruped/duplicate",
                          json={"new_key": "quadrupedfat", "new_label": "Fat"})
    assert r.status_code == 200, r.text
    assert r.json()["profile"]["key"] == "quadrupedfat"
    assert r.json()["profile"]["keywords"] == []


# --- gate + writability ----------------------------------------------------
def test_write_refused_when_not_writable(admin_client, monkeypatch):
    import motion_admin
    monkeypatch.setattr(motion_admin, "_writable", lambda: False)
    r = admin_client.post("/api/admin/motions", json={"profile": _new_profile("x"), "label": "x"})
    assert r.status_code == 409
    # reads still work
    assert admin_client.get("/api/admin/motions").status_code == 200
