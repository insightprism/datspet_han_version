"""Layout-identity pin for pack_datsme_bundle (SPEC_MOTION_PROFILES §10 gate 2).

The pose-loop refactor generalized pack_datsme_bundle from (walk_frames, idle_frames)
to a {pose: frames} dict. This test locks the byte-for-byte identity of the classic
walk+idle case: frame indices, per-pose runtime_role, sheet geometry, and the manifest/
package fields the DatsMe runtime reads must be exactly what the pre-refactor packer
produced. Zero-GPU — factory._remove_bg is stubbed to an identity alpha.
"""
import io
import json
import zipfile

from PIL import Image

from pet_factory import factory


def _pack_walk_idle(monkeypatch):
    # Stub birefnet so no GPU/model is needed; keep the frame as-is with full alpha.
    monkeypatch.setattr(factory, "_remove_bg", lambda img: img.convert("RGBA"))
    walk = [Image.new("RGB", (256, 256), (200, 40, 40)) for _ in range(3)]
    idle = [Image.new("RGB", (256, 256), (40, 40, 200)) for _ in range(2)]
    zip_bytes = factory.pack_datsme_bundle(
        {"walk": walk, "idle": idle}, "test_breed", "Test Breed",
        pose_roles={"walk": "active", "idle": "rest"})
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        names = set(z.namelist())
        manifest = json.loads(z.read("manifest.json"))
        package = json.loads(z.read("package.json"))
    return names, manifest, package


def test_walk_idle_layout_is_byte_identical(monkeypatch):
    names, m, pkg = _pack_walk_idle(monkeypatch)

    # The three bundle members, sprite named by breed_id.
    assert names == {"test_breed_sprite.png", "manifest.json", "package.json"}

    # Animations: walk on row 0 (frames 0,1,2), idle on a fresh row (8,9), roles intact.
    assert m["animations"] == {
        "walk": {"frames": [0, 1, 2], "fps": 12, "loop": True, "runtime_role": "active"},
        "idle": {"frames": [8, 9], "fps": 12, "loop": True, "runtime_role": "rest"},
    }

    # Sheet geometry: 8 columns, 2 rows (idle's fresh row makes it 2), 256px cells.
    assert m["columns"] == 8
    assert m["rows"] == 2
    assert m["frame_width"] == 256 and m["frame_height"] == 256

    # Runtime fields the DatsMe engine reads — unchanged.
    assert m["schema_version"] == "pet_manifest.v1"
    assert m["view_kind"] == "side"
    assert m["native_facing"] == "right"
    assert m["mirroring_policy"] == "flip"
    assert m["movement_class"] == "mammalian_quadruped"   # the packer default, preserved

    # package.json contents.
    assert pkg == {
        "breed_id": "test_breed",
        "display_name": "Test Breed",
        "movement_class": "mammalian_quadruped",
    }


def test_movement_class_override_flows_through(monkeypatch):
    # A non-default movement_class (from a resolved profile) must reach both files.
    monkeypatch.setattr(factory, "_remove_bg", lambda img: img.convert("RGBA"))
    walk = [Image.new("RGB", (256, 256), (0, 0, 0)) for _ in range(2)]
    idle = [Image.new("RGB", (256, 256), (0, 0, 0)) for _ in range(2)]
    zip_bytes = factory.pack_datsme_bundle(
        {"walk": walk, "idle": idle}, "b", "B",
        pose_roles={"walk": "active", "idle": "rest"},
        movement_class="avian_biped")
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        m = json.loads(z.read("manifest.json"))
        pkg = json.loads(z.read("package.json"))
    assert m["movement_class"] == "avian_biped"
    assert pkg["movement_class"] == "avian_biped"
