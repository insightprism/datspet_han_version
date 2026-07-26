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


# --- prompt templates (the editor's prompt preview) -------------------------
def test_prompt_templates_are_served_from_the_python_constants(admin_client):
    """The editor renders the assembled prompt from these, instead of restating the
    sentences in TypeScript — so an edit to either template can't leave the preview
    lying. Serving the constants verbatim is what makes that true."""
    from pet_factory import motion_profiles as mp
    from pet_factory import prompt_templates as pt

    r = admin_client.get("/api/admin/motions/prompt-templates")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["still"]["base"] == pt.BASE_STILL_TEMPLATE
    assert body["still"]["remix"] == pt.REMIX_STILL_TEMPLATE
    assert body["still"]["default_pose"] == pt.DEFAULT_POSE
    assert body["motion"]["template"] == mp.MOTION_PROMPT_TEMPLATE
    # The slots the frontend substitutes must be present, or the preview renders
    # a sentence with nothing of the profile in it.
    assert "{animal}" in body["still"]["base"] and "{pose}" in body["still"]["base"]
    for slot in ("{animal}", "{action}", "{suffix}"):
        assert slot in body["motion"]["template"]


def test_prompt_templates_serve_no_negatives(admin_client):
    """There is no negative prompt to serve — the samplers run at cfg 1.0, which cancels
    negative conditioning out (measured; see test_samplers_run_at_cfg_one...). Serving an
    empty/absent field beats serving a string the GPU throws away."""
    body = admin_client.get("/api/admin/motions/prompt-templates").json()
    assert "negative" not in body["still"]
    assert "negative" not in body["motion"]


def test_prompt_templates_route_is_not_shadowed_by_the_key_route(admin_client):
    """`/prompt-templates` sits under the same prefix as `/{key}`; FastAPI matches in
    declaration order, so the literal route must stay registered first. A regression
    here 404s as a missing profile rather than failing loudly."""
    r = admin_client.get("/api/admin/motions/prompt-templates")
    assert r.status_code == 200
    assert "profile" not in r.json()


# --- label = the AI classifier's description --------------------------------
def test_saving_a_profile_flushes_the_ai_classifier_cache(admin_client):
    """A profile's `label` IS the body-type description the AI classifier is shown
    (motion_resolver._profiles_block). The classifier caches animal → key per process,
    so without this flush an author could rewrite a label precisely to fix a
    misclassification, retest the same animal, and see the stale answer — concluding
    the label is unused. Every write endpoint goes through _after_write for this."""
    import motion_resolver

    motion_resolver._cache["pterodactyl"] = "quadruped"       # a stale classification
    r = admin_client.put("/api/admin/motions/quadruped",
                         json={"profile": _new_profile("quadruped"), "label": "New description"})
    assert r.status_code == 200, r.text
    assert motion_resolver._cache == {}


def test_profile_labels_describe_the_body_plan(admin_client):
    """The labels are prompt content, not list captions: they are the ONLY description
    of each body type the classifier receives (keywords are the offline path and never
    reach the AI). A one-word label starves the classifier on anything not already
    keyworded, so hold the line that each one actually describes limbs/gait."""
    body = admin_client.get("/api/admin/motions").json()
    labels = {p["key"]: p["label"] for p in body["profiles"]}
    for key, label in labels.items():
        assert len(label) > 60, f"{key} label is too terse to classify from: {label!r}"
    # The distinction the whole taxonomy turns on: a bird's wings ARE its forelimbs,
    # a winged_flyer's wings are extra. If these two read alike, dragons become birds.
    assert "forelimb" in labels["avian"].lower()
    assert "in addition" in labels["winged_flyer"].lower()
    # quadruped is the default every unmatched animal lands on — it must say "no wings"
    # or it swallows anything winged that the classifier is unsure about.
    assert "no wings" in labels["quadruped"].lower()


# --- gate + writability ----------------------------------------------------
def test_write_refused_when_not_writable(admin_client, monkeypatch):
    import motion_admin
    monkeypatch.setattr(motion_admin, "_writable", lambda: False)
    r = admin_client.post("/api/admin/motions", json={"profile": _new_profile("x"), "label": "x"})
    assert r.status_code == 409
    # reads still work
    assert admin_client.get("/api/admin/motions").status_code == 200
