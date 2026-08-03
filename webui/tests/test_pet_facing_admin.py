"""The facing repair door (pet_facing_admin) — admin data repair for a pet
whose artwork faces the opposite of what its manifest claims.

What each case protects:
- the gate — the route 401s without an admin launch;
- one repair rewrites BOTH stored copies of the manifest (the column and the
  manifest.json inside bundle_zip) and rederives bundle_sha256/size_bytes,
  because the DPP transfer pointer publishes them;
- everything else on the row and in the zip survives byte-for-byte — the
  sprite sheet, package.json, and any unrelated manifest keys (the athletics
  block rides through a repair untouched);
- the vocabularies are CLOSED at write time: no build re-validates a pet row,
  so an unknown policy string would reach resolveScaleX silently.
"""
import hashlib
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

from conftest import make_bundle_zip  # noqa: E402

WRONG_FACING = {"view_kind": "side", "native_facing": "right",
                "mirroring_policy": "flip"}
REPAIRED = {"view_kind": "side", "native_facing": "left",
            "mirroring_policy": "flip-from-left"}


def make_misfaced_pet(db_mod, pet_id="moonwalk0001"):
    """A pet whose manifest claims right/flip (the packer's stamp) plus the
    stowaways a repair must not disturb: a per-anim description and an
    unrelated stamped block."""
    zip_bytes, manifest_json = make_bundle_zip(
        breed_id="chinese_girl",
        animations={
            "walk": {"frames": [0, 1], "fps": 8, "loop": True,
                     "view": {**WRONG_FACING, "description": "side walk"}},
            "run": {"frames": [2, 3], "fps": 12, "loop": True},
        },
        **WRONG_FACING,
        pet_athletics={"schema_version": "pet_athletics.v1", "speed": 0.6},
    )
    db_mod.insert_pet(
        pet_id=pet_id, breed_id="chinese_girl", display_name="Chinese Girl",
        created_at=1783800000.0, draft=False,
        sheet_png=b"\x89PNG\r\n\x1a\nDATA", manifest_json=manifest_json,
        package_json=None, bundle_zip=zip_bytes,
    )
    return pet_id


def _fresh_admin_app(dpp_env, *, gate_open: bool):
    """A fresh app over just the facing router — the store_admin test pattern:
    reload the module so its router captures the CURRENT (per-test) db and
    datsme_integration, then override that same captured gate."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import pet_facing_admin
    importlib.reload(pet_facing_admin)
    app = FastAPI()
    app.include_router(pet_facing_admin.router)
    if gate_open:
        app.dependency_overrides[
            pet_facing_admin.datsme_integration.require_admin_launch] = lambda: None
    return TestClient(app)


@pytest.fixture()
def admin_client(dpp_env):
    return _fresh_admin_app(dpp_env, gate_open=True)


def test_gate_401_without_admin(dpp_env):
    make_misfaced_pet(dpp_env["db"])
    client = _fresh_admin_app(dpp_env, gate_open=False)
    r = client.post("/api/admin/pets/moonwalk0001/facing", json=REPAIRED)
    assert r.status_code == 401


def test_repair_rewrites_both_copies_and_rederives_digest(admin_client, dpp_env):
    db = dpp_env["db"]
    make_misfaced_pet(db)
    before = db.get_pet("moonwalk0001")

    r = admin_client.post("/api/admin/pets/moonwalk0001/facing", json=REPAIRED)
    assert r.status_code == 200
    assert r.json()["view"] == REPAIRED

    row = db.get_pet("moonwalk0001")

    # The column copy: sheet level + EVERY animation, including the one that
    # had no view block at all.
    m = json.loads(row["manifest_json"])
    assert {k: m[k] for k in REPAIRED} == REPAIRED
    assert m["animations"]["run"]["view"] == REPAIRED
    assert m["animations"]["walk"]["view"] == {**REPAIRED,
                                               "description": "side walk"}
    # Stowaways survive.
    assert m["pet_athletics"] == {"schema_version": "pet_athletics.v1",
                                  "speed": 0.6}

    # The zip copy agrees with the column, and untouched members are
    # byte-identical.
    with zipfile.ZipFile(io.BytesIO(row["bundle_zip"])) as z:
        assert z.read("manifest.json").decode() == row["manifest_json"]
        with zipfile.ZipFile(io.BytesIO(before["bundle_zip"])) as old:
            assert z.read("chinese_girl_sprite.png") == old.read(
                "chinese_girl_sprite.png")
            assert z.read("package.json") == old.read("package.json")

    # Derived columns track the new bytes (the DPP pointer publishes these).
    assert row["bundle_sha256"] == hashlib.sha256(row["bundle_zip"]).hexdigest()
    assert row["bundle_sha256"] != before["bundle_sha256"]
    assert row["size_bytes"] == len(row["bundle_zip"])
    assert r.json()["bundle_sha256"] == row["bundle_sha256"]


def test_unknown_vocabulary_is_rejected(admin_client, dpp_env):
    make_misfaced_pet(dpp_env["db"])
    r = admin_client.post(
        "/api/admin/pets/moonwalk0001/facing",
        json={"view_kind": "side", "native_facing": "backwards",
              "mirroring_policy": "flip"})
    assert r.status_code == 422
    assert "native_facing" in r.json()["detail"]
    # The row is untouched by a rejected write.
    m = json.loads(dpp_env["db"].get_pet("moonwalk0001")["manifest_json"])
    assert m["native_facing"] == "right"


def test_unknown_pet_404s(admin_client):
    r = admin_client.post("/api/admin/pets/nosuchpet000/facing", json=REPAIRED)
    assert r.status_code == 404


def test_per_animation_override(admin_client, dpp_env):
    """Facing is per animation — each pose is its own I2V loop and can come
    out facing its own way (the real repair: run left, everything else
    right). The base view lands everywhere EXCEPT the overridden pose."""
    db = dpp_env["db"]
    make_misfaced_pet(db)
    base = {"view_kind": "side", "native_facing": "right",
            "mirroring_policy": "flip"}
    run_view = {"view_kind": "side", "native_facing": "left",
                "mirroring_policy": "flip-from-left"}

    r = admin_client.post(
        "/api/admin/pets/moonwalk0001/facing",
        json={**base, "animations": {"run": run_view}})
    assert r.status_code == 200

    m = json.loads(db.get_pet("moonwalk0001")["manifest_json"])
    assert {k: m[k] for k in base} == base
    assert m["animations"]["run"]["view"] == run_view
    assert m["animations"]["walk"]["view"] == {**base,
                                               "description": "side walk"}


def test_override_for_unknown_pose_is_rejected(admin_client, dpp_env):
    make_misfaced_pet(dpp_env["db"])
    r = admin_client.post(
        "/api/admin/pets/moonwalk0001/facing",
        json={**REPAIRED, "animations": {"moonwalk": REPAIRED}})
    assert r.status_code == 422
    assert "no such pose" in r.json()["detail"]


def test_flip_sheet_frames_mirrors_only_the_named_frames():
    """The pixel repair for a loop that TURNS mid-animation: the named
    pose-relative frames are mirrored in place, every other cell of the
    sheet is untouched, and out-of-range indices refuse loudly."""
    from PIL import Image
    import io as _io
    import pet_facing_admin as pfa

    fw = 8
    manifest = {"columns": 2, "frame_width": fw, "frame_height": fw,
                "animations": {"run": {"frames": [0, 1, 2], "fps": 8,
                                       "loop": True}}}
    # Frame cells with a single marker pixel at x=1 so a mirror moves it
    # to x=fw-2. Grid is 2 columns: frames 0,1 on row 0; frame 2 on row 1.
    sheet = Image.new("RGBA", (fw * 2, fw * 2), (0, 0, 0, 0))
    for fi in (0, 1, 2):
        x, y = (fi % 2) * fw, (fi // 2) * fw
        sheet.putpixel((x + 1, y + 3), (255, 0, 0, 255))
    buf = _io.BytesIO()
    sheet.save(buf, "PNG")

    out = pfa.flip_sheet_frames(buf.getvalue(), json.dumps(manifest),
                                "run", [1, 2])
    got = Image.open(_io.BytesIO(out)).convert("RGBA")
    # Frame 0 untouched: marker still at x=1. Frames 1,2 mirrored: x=fw-2.
    assert got.getpixel((1, 3))[3] == 255
    assert got.getpixel((fw + fw - 2, 3))[3] == 255
    assert got.getpixel((fw + 1, 3))[3] == 0
    assert got.getpixel((fw - 2, fw + 3))[3] == 255

    with pytest.raises(ValueError, match="out of range"):
        pfa.flip_sheet_frames(buf.getvalue(), json.dumps(manifest), "run", [3])
    with pytest.raises(ValueError, match="no such pose"):
        pfa.flip_sheet_frames(buf.getvalue(), json.dumps(manifest), "fly", [0])


def test_repair_pet_bundle_carries_the_sheet(dpp_env):
    """A pixel repair must land in BOTH sheet copies: the column the runtimes
    fetch and the sprite member inside the bundle zip."""
    import pet_facing_admin as pfa
    db = dpp_env["db"]
    make_misfaced_pet(db, pet_id="pixelfix0001")
    row = db.get_pet("pixelfix0001")

    new_sheet = b"\x89PNG\r\n\x1a\nREPAIRED"
    new_zip = pfa._rewrite_bundle(row["bundle_zip"], row["manifest_json"],
                                  sheet_png=new_sheet)
    db.repair_pet_bundle("pixelfix0001", manifest_json=row["manifest_json"],
                         bundle_zip=new_zip, sheet_png=new_sheet)

    fresh = db.get_pet("pixelfix0001")
    assert fresh["sheet_png"] == new_sheet
    with zipfile.ZipFile(io.BytesIO(fresh["bundle_zip"])) as z:
        assert z.read("chinese_girl_sprite.png") == new_sheet
    assert fresh["bundle_sha256"] == hashlib.sha256(fresh["bundle_zip"]).hexdigest()
