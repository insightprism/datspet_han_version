"""The store admin surface (SPEC_PET_STORE §3.2, §4, §5).

What each case protects:
- the gate — every route 401s without an admin launch;
- publish-from-pet reads its source through the CALLER'S OWN owner scope
  (§3.2): someone else's pet 404s exactly like an absent one;
- the mechanical facts a publish derives match the bundle, and publish NEVER
  invokes the AI — listing text is written only through the ai-tag door (§4);
- the publish flip runs the shared sellability validator (§5.3), so the admin
  cannot ship a listing the build would reject;
- tags are normalized on write, and `animal` is fixed once published (§1.3).
"""
import importlib
import io
import json
import os
import sys
import zipfile

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WEBUI = os.path.join(REPO, "webui")
for p in (WEBUI, REPO):
    if p not in sys.path:
        sys.path.insert(0, p)

from conftest import (ANON_OWNER, ANON_OWNER_2, anon_cookies,  # noqa: E402
                      make_bundle_zip)

WALK_IDLE = {"walk": {"frames": [0]}, "idle": {"frames": [1]}}
FAKE_PNG = b"\x89PNG\r\n\x1a\nDATA"


def _real_sheet_png() -> bytes:
    """A genuinely decodable PNG — publish-from-pet CROPS the sheet with PIL,
    so the conftest's fake PNG bytes are not enough here."""
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGBA", (16, 16), (200, 120, 40, 255)).save(buf, "PNG")
    return buf.getvalue()


def make_croppable_pet(db_mod, pet_id="adminpet0001", external_user_id=ANON_OWNER,
                       breed_id="white_snow_leopard",
                       display_name="White Snow Leopard"):
    """A house pet whose bundle publish-from-pet can actually open and crop."""
    sheet = _real_sheet_png()
    manifest = {"animations": dict(WALK_IDLE), "columns": 8,
                "frame_width": 256, "frame_height": 256}
    manifest_json = json.dumps(manifest)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("manifest.json", manifest_json)
        z.writestr("package.json", json.dumps({"breed_id": breed_id,
                                               "display_name": display_name}))
        z.writestr(f"{breed_id}_sprite.png", sheet)
    db_mod.insert_pet(
        pet_id=pet_id, breed_id=breed_id, display_name=display_name,
        created_at=1783800000.0, draft=False, sheet_png=sheet,
        manifest_json=manifest_json, package_json=None,
        bundle_zip=buf.getvalue(), external_user_id=external_user_id)
    return pet_id


def make_store_row(db_mod, store_id="storerow0001", published=False,
                   animal="cat", animations=None, display_name="Shelf Cat"):
    zip_bytes, manifest_json = make_bundle_zip(
        breed_id="shelfcat",
        animations=animations if animations is not None else dict(WALK_IDLE))
    db_mod.insert_store_pet(
        store_id=store_id, display_name=display_name, breed_id="shelfcat",
        animal=animal, description="", tags=[], created_at=1783800000.0,
        preview_png=FAKE_PNG, sheet_png=FAKE_PNG, manifest_json=manifest_json,
        package_json=None, bundle_zip=zip_bytes, published=published)
    return store_id


def _fresh_admin_app(dpp_env, *, gate_open: bool):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import store_admin
    importlib.reload(store_admin)
    app = FastAPI()
    app.include_router(store_admin.router)
    if gate_open:
        app.dependency_overrides[
            store_admin.datsme_integration.require_admin_launch] = lambda: None
    client = TestClient(app)
    client._store_admin = store_admin
    return client


@pytest.fixture()
def admin_client(dpp_env, monkeypatch):
    client = _fresh_admin_app(dpp_env, gate_open=True)
    monkeypatch.setattr(client._store_admin.datsme_integration,
                        "admin_user_id", lambda request: "admin-1")
    return client


# --- the gate --------------------------------------------------------------
def test_every_route_requires_the_admin_gate(dpp_env):
    client = _fresh_admin_app(dpp_env, gate_open=False)
    assert client.get("/api/admin/store").status_code == 401
    assert client.get("/api/admin/store/x").status_code == 401
    assert client.post("/api/admin/store/publish-from-pet",
                       json={"pet_id": "x"}).status_code == 401
    assert client.put("/api/admin/store/x", json={
        "display_name": "X", "animal": "cat", "published": False,
    }).status_code == 401
    assert client.post("/api/admin/store/x/ai-tag").status_code == 401
    assert client.delete("/api/admin/store/x").status_code == 401


# --- publish-from-pet ------------------------------------------------------
def test_publish_from_pet_copies_and_seeds(admin_client, dpp_env):
    make_croppable_pet(dpp_env["db"])
    r = admin_client.post("/api/admin/store/publish-from-pet",
                          json={"pet_id": "adminpet0001"},
                          cookies=anon_cookies())
    assert r.status_code == 200, r.text
    listing = r.json()["listing"]

    # Mechanical facts derived from the bundle (§1.3).
    assert listing["breed_id"] == "white_snow_leopard"
    assert listing["pose_count"] == 2
    assert listing["poses"] == ["walk", "idle"]
    # `animal` SEEDED from the breed_id's last word (no catalog match).
    assert listing["animal"] == "leopard"
    # display_name seeded from the house pet; born UNPUBLISHED.
    assert listing["display_name"] == "White Snow Leopard"
    assert listing["published"] is False
    assert listing["sellability_errors"] == []
    # No AI key in tests → best-effort draft degrades to empty text (§4).
    assert listing["description"] == ""

    # The house copy remains the admin's — publish COPIES, never moves (§5.1).
    assert dpp_env["db"].get_pet("adminpet0001") is not None
    # And the shopper cannot see it until the admin publishes.
    assert dpp_env["db"].list_store_pets(published_only=True) == []


def test_publish_from_pet_reads_through_the_callers_own_scope(admin_client,
                                                              dpp_env):
    """§3.2: an admin publishes only a pet she can see in her house. Another
    owner's pet 404s exactly like an absent one — no existence oracle."""
    make_croppable_pet(dpp_env["db"], pet_id="notmine00001",
                       external_user_id=ANON_OWNER_2)
    for pet_id in ("notmine00001", "absent000001"):
        r = admin_client.post("/api/admin/store/publish-from-pet",
                              json={"pet_id": pet_id}, cookies=anon_cookies())
        assert r.status_code == 404, (pet_id, r.text)


def test_publish_from_pet_NEVER_calls_the_ai(admin_client, dpp_env, monkeypatch):
    """§4 — stocking never generates listing text. The AI is an explicit
    invocation (the ai-tag door), never a side effect: an admin who stocks ten
    pets spends no tokens and reads no prose she did not ask for, and a model
    outage can never make stocking fail. The row arrives empty and stays empty
    until she taps the sparkle."""
    make_croppable_pet(dpp_env["db"])
    sa = admin_client._store_admin

    def _boom(*a, **kw):                      # noqa: ANN001 - test double
        raise AssertionError("publish-from-pet must not invoke the AI")

    monkeypatch.setattr(sa.ai_engine, "is_available", lambda: True)
    monkeypatch.setattr(sa.ai_engine, "call_purpose", _boom)

    r = admin_client.post("/api/admin/store/publish-from-pet",
                          json={"pet_id": "adminpet0001"},
                          cookies=anon_cookies())
    body = r.json()
    assert body["listing"]["description"] == ""
    assert body["listing"]["tags"] == []
    assert body["display_name_suggestion"] is None
    # The pet's own name carries over — that is a fact about the bundle, not
    # generated text.
    assert body["listing"]["display_name"] == "White Snow Leopard"


# --- the listing editor ----------------------------------------------------
def test_put_normalizes_tags_and_publishes(admin_client, dpp_env):
    make_store_row(dpp_env["db"])
    r = admin_client.put("/api/admin/store/storerow0001", json={
        "display_name": "Shelf Cat", "description": "A good cat.",
        "tags": [" Fluffy ", "fluffy", "", "x" * 40, "Orange Tabby"],
        "animal": "Cat", "published": True,
    })
    assert r.status_code == 200, r.text
    listing = r.json()["listing"]
    assert listing["tags"] == ["fluffy", "orange tabby"]
    assert listing["animal"] == "cat"
    assert listing["published"] is True
    assert dpp_env["db"].list_store_pets(published_only=True)[0]["id"] == \
        "storerow0001"


def test_publishing_an_unsellable_bundle_is_refused(admin_client, dpp_env):
    """§5.3 — the shared validator gates the flip; the row stays unpublished."""
    make_store_row(dpp_env["db"], store_id="brokenrow001", animations={})
    r = admin_client.put("/api/admin/store/brokenrow001", json={
        "display_name": "Broken", "animal": "cat", "published": True,
    })
    assert r.status_code == 422, r.text
    assert "animations" in json.dumps(r.json())
    row = dpp_env["db"].get_store_pet("brokenrow001")
    assert row["published"] == 0


def test_animal_is_fixed_once_published(admin_client, dpp_env):
    make_store_row(dpp_env["db"], published=True)
    r = admin_client.put("/api/admin/store/storerow0001", json={
        "display_name": "Shelf Cat", "animal": "dog", "published": True,
    })
    assert r.status_code == 409


# --- ai-tag ---------------------------------------------------------------
def test_ai_tag_is_refused_on_a_published_row(admin_client, dpp_env):
    make_store_row(dpp_env["db"], published=True)
    r = admin_client.post("/api/admin/store/storerow0001/ai-tag",
                          cookies=anon_cookies())
    assert r.status_code == 409


def test_ai_tag_overwrites_draft_text_and_surfaces_ai_failures(
        admin_client, dpp_env, monkeypatch):
    make_store_row(dpp_env["db"], published=False)
    sa = admin_client._store_admin

    monkeypatch.setattr(
        sa.ai_engine, "call_purpose",
        lambda key, **kw: ({"description": "Fresh words.", "tags": ["cat"],
                            "display_name_suggestion": None}, None))
    r = admin_client.post("/api/admin/store/storerow0001/ai-tag",
                          cookies=anon_cookies())
    assert r.status_code == 200, r.text
    assert r.json()["listing"]["description"] == "Fresh words."

    # Redraft is an explicit ask — failures SURFACE (unlike publish's degrade).
    def _boom(key, **kw):
        raise sa.ai_engine.AIUnavailable("no key")
    monkeypatch.setattr(sa.ai_engine, "call_purpose", _boom)
    r = admin_client.post("/api/admin/store/storerow0001/ai-tag",
                          cookies=anon_cookies())
    assert r.status_code == 503


# --- delete ----------------------------------------------------------------
def test_delete_removes_inventory_but_not_adopted_copies(admin_client, dpp_env):
    make_store_row(dpp_env["db"], published=True)
    # An adopted copy in somebody's house, pointing back at the store row.
    zip_bytes, manifest_json = make_bundle_zip(breed_id="shelfcat",
                                               animations=dict(WALK_IDLE))
    dpp_env["db"].insert_pet(
        pet_id="adoptedcopy1", breed_id="shelfcat", display_name="Shelf Cat",
        created_at=1783800001.0, draft=False, sheet_png=FAKE_PNG,
        manifest_json=manifest_json, package_json=None, bundle_zip=zip_bytes,
        external_user_id=ANON_OWNER, source_store_pet_id="storerow0001")

    assert admin_client.delete("/api/admin/store/storerow0001").status_code == 200
    assert admin_client.delete("/api/admin/store/storerow0001").status_code == 404
    assert dpp_env["db"].get_store_pet("storerow0001") is None
    # The copy is a copy (§3.2) — it survives its source.
    assert dpp_env["db"].get_pet("adoptedcopy1") is not None
