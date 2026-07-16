"""API tests for the design admin CRUD (SPEC_PET_DESIGN_AXES_ADMIN §2/§8).

Exercises webui/design_admin.py against TEMP copies of the axes dir + the
catalog, with the admin gate satisfied (dependency override) — mirroring
test_motion_admin_api.py. No GPU.
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
    """A TestClient over the design_admin router, with temp writable copies of
    the axes dir AND catalog.json, and the admin gate open."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from pet_factory import animal_catalog as cat
    from pet_factory import design_axes as da
    from pet_factory.animal_catalog import admin as cat_admin
    from pet_factory.design_axes import admin as da_admin

    axes_src = Path(da.__file__).resolve().parent
    axes_dst = tmp_path / "design_axes"
    axes_dst.mkdir()
    for f in axes_src.glob("*.json"):
        shutil.copy(f, axes_dst / f.name)
    monkeypatch.setattr(da, "_DIR", axes_dst)
    monkeypatch.setattr(da_admin, "_DIR", axes_dst)
    da.reload()

    catalog_dst = tmp_path / "catalog.json"
    shutil.copy(Path(cat.__file__).resolve().parent / "catalog.json", catalog_dst)
    monkeypatch.setattr(cat, "_CATALOG_FILE", catalog_dst)
    monkeypatch.setattr(cat_admin, "_CATALOG_FILE", catalog_dst)
    cat.reload()

    import design_admin
    importlib.reload(design_admin)
    monkeypatch.setattr(design_admin.datsme_integration, "admin_user_id",
                        lambda request: "admin-1")
    monkeypatch.setattr(design_admin, "_writable", lambda: True)

    app = FastAPI()
    app.include_router(design_admin.router)
    app.dependency_overrides[design_admin.datsme_integration.require_admin_launch] = lambda: None
    client = TestClient(app)
    client._axes_dst = axes_dst
    yield client
    da.reload()
    cat.reload()


def _new_axis(key="material"):
    from pet_factory import design_axes as da
    base = copy.deepcopy(json.loads(
        (Path(da.__file__).resolve().parent.parent / "design_axes" / "pattern.json").read_text()))
    # ^ read from the REAL source for a valid template, then re-key
    base["axis"] = key
    return base


# --- axes: read ---------------------------------------------------------------
def test_list_returns_axes_in_menu_order_with_used_by(admin_client):
    r = admin_client.get("/api/admin/design/axes")
    assert r.status_code == 200, r.text
    body = r.json()
    keys = [a["key"] for a in body["axes"]]
    assert keys == ["body", "pattern", "coat", "plumage", "scales", "expression"], \
        "the list pane shows MENU order, not sorted order"
    coat = next(a for a in body["axes"] if a["key"] == "coat")
    assert set(coat["used_by"]) == {"cat", "cat/tabby", "cat/siamese",
                                    "dog", "dog/corgi", "dog/labrador"}
    assert next(a for a in body["axes"] if a["key"] == "plumage")["used_by"] == []


def test_get_one_returns_full_json_fragments_included(admin_client):
    r = admin_client.get("/api/admin/design/axes/coat")
    assert r.status_code == 200
    axis = r.json()["axis"]
    assert axis["axis"] == "coat"
    assert any(o["prompt_fragment"] for o in axis["options"]), \
        "the gated admin surface DOES see fragments — it edits them"


def test_get_unknown_404(admin_client):
    assert admin_client.get("/api/admin/design/axes/nope").status_code == 404


# --- axes: create / update / delete --------------------------------------------
def test_create_then_the_design_menu_serves_it(admin_client):
    from pet_factory import design_axes as da
    r = admin_client.post("/api/admin/design/axes", json={"axis": _new_axis("material")})
    assert r.status_code == 200, r.text
    assert [a["key"] for a in admin_client.get("/api/admin/design/axes").json()["axes"]][-1] == "material"
    # Round-trip (§8): the design step's own filter serves the new axis at once.
    assert any(a["axis"] == "material" for a in da.axes_for_surface(None))


def test_create_invalid_422_with_the_guard_tests_errors(admin_client):
    bad = _new_axis("brokenone")
    bad["options"][1]["prompt_fragment"] = ""       # the dead-control class
    r = admin_client.post("/api/admin/design/axes", json={"axis": bad})
    assert r.status_code == 422
    assert r.json()["detail"]["error"] == "validation_failed"
    assert any("changes nothing" in e for e in r.json()["detail"]["errors"])


def test_update_edits_a_fragment_and_it_goes_live(admin_client):
    from pet_factory import design_axes as da
    axis = admin_client.get("/api/admin/design/axes/plumage").json()["axis"]
    downy = next(o for o in axis["options"] if o["key"] == "downy")
    downy["prompt_fragment"] = "with impossibly soft downy feathers"
    r = admin_client.put("/api/admin/design/axes/plumage", json={"axis": axis})
    assert r.status_code == 200, r.text
    assert da.prompt_fragment("plumage", "downy") == "with impossibly soft downy feathers"


def test_delete_referenced_surface_axis_409s_naming_blockers(admin_client):
    """The rev.2 guard: coat is referenced by every catalog entry's resolved
    surface, so deleting it must refuse and say who blocks it."""
    r = admin_client.delete("/api/admin/design/axes/coat")
    assert r.status_code == 409
    assert "cat/tabby" in r.json()["detail"]
    assert admin_client.get("/api/admin/design/axes/coat").status_code == 200


def test_delete_becomes_refused_the_moment_the_catalog_references_it(admin_client):
    """plumage starts unreferenced (an all-fur catalog); retagging one breed to
    feathers through the Animals tab must flip its delete to a 409 — the two
    tabs enforcing one rule."""
    assert admin_client.put("/api/admin/design/animals/cat/tabby",
                            json={"surface": "feathers"}).status_code == 200, \
        "retag failed"
    r = admin_client.delete("/api/admin/design/axes/plumage")
    assert r.status_code == 409 and "cat/tabby" in r.json()["detail"]


def test_delete_unreferenced_axis_succeeds(admin_client):
    admin_client.post("/api/admin/design/axes", json={"axis": _new_axis("material")})
    assert admin_client.delete("/api/admin/design/axes/material").status_code == 200
    assert admin_client.get("/api/admin/design/axes/material").status_code == 404


# --- animals -------------------------------------------------------------------
def test_animals_tree_carries_authored_and_resolved_profiles(admin_client):
    r = admin_client.get("/api/admin/design/animals")
    assert r.status_code == 200
    body = r.json()
    assert set(body["surfaces"]) == {"fur", "feathers", "scales"}
    assert {o["key"] for o in body["surface_axis_options"]["fur"]} >= {"natural", "fluffy"}
    cat_row = next(a for a in body["animals"] if a["key"] == "cat")
    assert cat_row["surface"] == "fur"
    tabby = next(b for b in cat_row["breeds"] if b["key"] == "tabby")
    assert tabby["surface"] is None and tabby["resolved_surface"] == "fur", \
        "authored vs resolved must both be visible (inheritance is the UI's story)"


def test_put_animal_profile_round_trips_to_the_design_read_side(admin_client):
    from pet_factory import animal_catalog as cat
    r = admin_client.put("/api/admin/design/animals/cat/tabby",
                         json={"surface_options": ["fluffy", "curly"]})
    assert r.status_code == 200, r.text
    assert cat.resolved_surface_options("cat", "tabby") == ["fluffy", "curly"]


def test_put_invalid_surface_422_with_validator_errors(admin_client):
    r = admin_client.put("/api/admin/design/animals/cat",
                         json={"surface": "granite"})
    assert r.status_code == 422
    assert any("matches no surface axis" in e for e in r.json()["detail"]["errors"])


def test_put_non_design_field_is_refused(admin_client):
    """The allowed-field guard's HTTP face (§0.5): a write carrying
    motion_profile / base_png / anything unknown dies at parse — a design edit
    can never reach a curated field."""
    for body in ({"motion_profile": "avian"}, {"base_png": "x"}, {"tagline": "y"}):
        r = admin_client.put("/api/admin/design/animals/cat", json=body)
        assert r.status_code == 422, f"{body} was not refused"


def test_put_unknown_entry_404(admin_client):
    assert admin_client.put("/api/admin/design/animals/axolotl",
                            json={"surface": "fur"}).status_code == 404


# --- writability -----------------------------------------------------------------
def test_writes_refused_409_when_read_only(admin_client, monkeypatch):
    import design_admin
    monkeypatch.setattr(design_admin, "_writable", lambda: False)
    assert admin_client.post("/api/admin/design/axes",
                             json={"axis": _new_axis("x")}).status_code == 409
    assert admin_client.put("/api/admin/design/animals/cat",
                            json={"surface": "fur"}).status_code == 409
    # reads still work
    assert admin_client.get("/api/admin/design/axes").status_code == 200
    assert admin_client.get("/api/admin/design/animals").status_code == 200
