"""The store admin surface (SPEC_PET_STORE §3.2, §4, §5).

What each case protects:
- the gate — every route 401s without an admin launch;
- publish-from-pet reads its source through the CALLER'S OWN owner scope
  (§3.2): someone else's pet 404s exactly like an absent one;
- the mechanical facts a publish derives match the bundle, and publish NEVER
  invokes the AI — listing text is written only through the ai-tag door (§4);
- the publish flip runs the shared sellability validator (§5.3), so the admin
  cannot ship a listing the build would reject;
- tags are normalized on write, and `animal` is fixed once a listing has
  first reached the shelf — not merely while it is on it (§1.3, §1.4).
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


def make_store_row(db_mod, store_id="storerow0001", shelved=False,
                   animal="cat", animations=None, display_name="Shelf Cat"):
    zip_bytes, manifest_json = make_bundle_zip(
        breed_id="shelfcat",
        animations=animations if animations is not None else dict(WALK_IDLE))
    db_mod.insert_store_pet(
        store_id=store_id, display_name=display_name, breed_id="shelfcat",
        animal=animal, description="", tags=[], created_at=1783800000.0,
        preview_png=FAKE_PNG, sheet_png=FAKE_PNG, manifest_json=manifest_json,
        package_json=None, bundle_zip=zip_bytes,
        status=db_mod.STORE_STATUS_SHELF if shelved
        else db_mod.STORE_STATUS_INTAKE)
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
    assert client.get("/api/admin/store/x/preview.png").status_code == 401
    assert client.post("/api/admin/store/publish-from-pet",
                       json={"pet_id": "x"}).status_code == 401
    assert client.put("/api/admin/store/x", json={
        "display_name": "X", "animal": "cat", "status": "intake",
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
    assert listing["status"] == "intake"
    assert listing["sellability_errors"] == []
    # No AI key in tests → best-effort draft degrades to empty text (§4).
    assert listing["description"] == ""

    # The house copy remains the admin's — publish COPIES, never moves (§5.1).
    assert dpp_env["db"].get_pet("adminpet0001") is not None
    # And the shopper cannot see it until the admin publishes.
    assert dpp_env["db"].list_store_pets(shelf_only=True) == []


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
        "animal": "Cat", "status": "shelf",
    })
    assert r.status_code == 200, r.text
    listing = r.json()["listing"]
    assert listing["tags"] == ["fluffy", "orange tabby"]
    assert listing["animal"] == "cat"
    assert listing["status"] == "shelf"
    assert dpp_env["db"].list_store_pets(shelf_only=True)[0]["id"] == \
        "storerow0001"


def test_publishing_an_unsellable_bundle_is_refused(admin_client, dpp_env):
    """§5.3 — the shared validator gates the move to `shelf`; the row stays
    where it was."""
    make_store_row(dpp_env["db"], store_id="brokenrow001", animations={})
    r = admin_client.put("/api/admin/store/brokenrow001", json={
        "display_name": "Broken", "animal": "cat", "status": "shelf",
    })
    assert r.status_code == 422, r.text
    assert "animations" in json.dumps(r.json())
    row = dpp_env["db"].get_store_pet("brokenrow001")
    assert row["status"] == "intake"


def test_animal_is_fixed_once_shelved(admin_client, dpp_env):
    make_store_row(dpp_env["db"], shelved=True)
    r = admin_client.put("/api/admin/store/storerow0001", json={
        "display_name": "Shelf Cat", "animal": "dog", "status": "shelf",
    })
    assert r.status_code == 409


# --- ai-tag ---------------------------------------------------------------
def test_ai_tag_is_refused_on_a_shelved_row(admin_client, dpp_env):
    make_store_row(dpp_env["db"], shelved=True)
    r = admin_client.post("/api/admin/store/storerow0001/ai-tag",
                          cookies=anon_cookies())
    assert r.status_code == 409


def test_ai_tag_overwrites_draft_text_and_surfaces_ai_failures(
        admin_client, dpp_env, monkeypatch):
    make_store_row(dpp_env["db"], shelved=False)
    sa = admin_client._store_admin

    monkeypatch.setattr(
        sa.ai_engine, "call_purpose",
        lambda key, **kw: ({"description": "Fresh words.", "tags": ["cat"],
                            "display_name_suggestion": None}, None))
    r = admin_client.post("/api/admin/store/storerow0001/ai-tag",
                          cookies=anon_cookies())
    assert r.status_code == 200, r.text
    assert r.json()["listing"]["description"] == "Fresh words."

    # An explicit ask — failures SURFACE (nothing here degrades silently).
    def _boom(key, **kw):
        raise sa.ai_engine.AIUnavailable("no key")
    monkeypatch.setattr(sa.ai_engine, "call_purpose", _boom)
    r = admin_client.post("/api/admin/store/storerow0001/ai-tag",
                          cookies=anon_cookies())
    assert r.status_code == 503


def test_ai_tag_tells_the_model_which_poses_the_pet_has(admin_client, dpp_env,
                                                        monkeypatch):
    """§4 — the model is shown ONE still frame, so the pose names are the only
    way it can know what the pet DOES. They ride the prompt as a clause, from
    the same listing view shoppers read, so a tag like 'pounces' can only be
    written for a pet that actually has that pose."""
    make_store_row(dpp_env["db"], shelved=False,
                   animations={"walk": {"frames": [0]}, "idle": {"frames": [1]},
                               "pounce": {"frames": [2]}})
    sa = admin_client._store_admin
    seen = {}

    def _capture(key, **kw):
        seen.update(kw.get("variables") or {})
        return ({"description": "d", "tags": ["cat"],
                 "display_name_suggestion": None}, None)

    monkeypatch.setattr(sa.ai_engine, "call_purpose", _capture)
    r = admin_client.post("/api/admin/store/storerow0001/ai-tag",
                          cookies=anon_cookies())
    assert r.status_code == 200, r.text
    assert "walk" in seen["poses_clause"]
    assert "pounce" in seen["poses_clause"]
    assert seen["animal_clause"].strip() == "The pet is a cat."


def test_ai_tag_omits_the_pose_clause_when_there_are_none(admin_client, dpp_env,
                                                          monkeypatch):
    """An empty clause, not the words 'no poses' — an absent fact is silence,
    never a claim the model has to reason about."""
    make_store_row(dpp_env["db"], shelved=False, animations={})
    sa = admin_client._store_admin
    seen = {}

    def _capture(key, **kw):
        seen.update(kw.get("variables") or {})
        return ({"description": "d", "tags": [], "display_name_suggestion": None},
                None)

    monkeypatch.setattr(sa.ai_engine, "call_purpose", _capture)
    admin_client.post("/api/admin/store/storerow0001/ai-tag",
                      cookies=anon_cookies())
    assert seen["poses_clause"] == ""


# --- delete ----------------------------------------------------------------
def test_delete_removes_inventory_but_not_adopted_copies(admin_client, dpp_env):
    make_store_row(dpp_env["db"], shelved=True)
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


# --- the inventory list ----------------------------------------------------
# All three cases below pin things that were broken in production while every
# gate was green, because the list route served the raw byteless projection
# and every existing assertion was made against the single-row routes.
def test_inventory_list_carries_what_only_the_list_renders(admin_client, dpp_env):
    """The list is the ONLY surface that draws the donated badge and the
    sellability warning, so serving it a shape without them makes both
    unreachable — which is what shipped (§10.4, §5.3)."""
    db = dpp_env["db"]
    make_store_row(db, store_id="gift00000001", display_name="Gifted Cat")
    make_store_row(db, store_id="stocked00001", display_name="Stocked Cat")
    # A row that cannot be sold: no animations at all.
    make_store_row(db, store_id="broken000001", display_name="Broken Cat",
                   animations={})
    db.insert_donation(donation_id="don000000001",
                       external_user_id="datsme-donor-1",
                       store_pet_id="gift00000001", display_name="Gifted Cat",
                       donated_at=1783800002.0)

    by_id = {p["id"]: p for p in
             admin_client.get("/api/admin/store").json()["pets"]}

    assert by_id["gift00000001"]["donated_by"] == "datsme-donor-1"
    # Present and null, not absent: the badge's absence has to be a fact the
    # list states, not a key the browser never received.
    assert by_id["stocked00001"]["donated_by"] is None
    assert by_id["stocked00001"]["sellability_errors"] == []
    assert by_id["broken000001"]["sellability_errors"] != []


def test_inventory_list_and_detail_agree_field_for_field(admin_client, dpp_env):
    """One builder for both routes. A list row that is a strict subset of the
    detail view is how the two silently drifted in the first place."""
    make_store_row(dpp_env["db"], store_id="storerow0001")
    listed = admin_client.get("/api/admin/store").json()["pets"][0]
    detail = admin_client.get("/api/admin/store/storerow0001").json()
    assert listed == detail


def test_admin_preview_serves_every_shelf_state(admin_client, dpp_env):
    """The admin's portraits must NOT resolve through the shopper's shelf gate.
    Pointing them there made every intake row — i.e. every donation, the rows
    she most needs to look at — a broken image (§1.4)."""
    make_store_row(dpp_env["db"], store_id="offshelf0001", shelved=False)
    make_store_row(dpp_env["db"], store_id="onshelf00001", shelved=True)

    for store_id in ("offshelf0001", "onshelf00001"):
        r = admin_client.get(f"/api/admin/store/{store_id}/preview.png")
        assert r.status_code == 200, f"{store_id}: {r.text}"
        assert r.content == FAKE_PNG
        # Behind the admin gate — never cacheable by a shared proxy.
        assert "private" in r.headers["cache-control"]

    assert admin_client.get(
        "/api/admin/store/nosuchrow0001/preview.png").status_code == 404
    # And the listing points at THAT route, not the shopper's.
    listing = admin_client.get("/api/admin/store/offshelf0001").json()
    assert listing["preview_url"] == "/api/admin/store/offshelf0001/preview.png"
