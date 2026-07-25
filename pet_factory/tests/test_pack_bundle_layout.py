"""Layout + wire-shape pin for pack_datsme_bundle (SPEC_MOTION_PROFILES §10 gate 2,
SPEC_BUNDLE_MOTION_CONTRACT §3).

Locks the classic walk+idle case: frame indices, sheet geometry, per-pose
runtime_role, and the manifest/package fields the DatsMe runtime reads. The wire
format widened in the bundle-motion-contract work — every animation now carries a
`view` block and a data-driven `loop` — so the expectations below include those;
the frame layout and sheet fields are unchanged. Zero-GPU — factory._remove_bg is
stubbed to an identity alpha.
"""
import io
import json
import zipfile

from PIL import Image

from pet_factory import factory

_SIDE_VIEW = {"view_kind": "side", "native_facing": "right", "mirroring_policy": "flip"}


def _pack_walk_idle(monkeypatch):
    # Stub birefnet so no GPU/model is needed; keep the frame as-is with full alpha.
    monkeypatch.setattr(factory, "_remove_bg", lambda img: img.convert("RGBA"))
    walk = [Image.new("RGB", (256, 256), (200, 40, 40)) for _ in range(3)]
    idle = [Image.new("RGB", (256, 256), (40, 40, 200)) for _ in range(2)]
    zip_bytes = factory.pack_datsme_bundle(
        {"walk": walk, "idle": idle}, "test_breed", "Test Breed",
        pose_meta={"walk": {"runtime_role": "active"}, "idle": {"runtime_role": "rest"}})
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        names = set(z.namelist())
        manifest = json.loads(z.read("manifest.json"))
        package = json.loads(z.read("package.json"))
    return names, manifest, package


def test_walk_idle_layout(monkeypatch):
    names, m, pkg = _pack_walk_idle(monkeypatch)

    # The three bundle members, sprite named by breed_id.
    assert names == {"test_breed_sprite.png", "manifest.json", "package.json"}

    # Animations: walk on row 0 (frames 0,1,2), idle on a fresh row (8,9), roles intact.
    # Each animation carries a per-animation view block (§3.3) and data-driven loop (§3.1).
    assert m["animations"] == {
        "walk": {"frames": [0, 1, 2], "fps": 12, "loop": True,
                 "runtime_role": "active", "view": _SIDE_VIEW},
        "idle": {"frames": [8, 9], "fps": 12, "loop": True,
                 "runtime_role": "rest", "view": _SIDE_VIEW},
    }

    # Sheet geometry: 8 columns, 2 rows (idle's fresh row makes it 2), 256px cells.
    assert m["columns"] == 8
    assert m["rows"] == 2
    assert m["frame_width"] == 256 and m["frame_height"] == 256

    # Runtime fields the DatsMe engine reads — unchanged (view defaults to side/right/flip).
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
        pose_meta={"walk": {"runtime_role": "active"}, "idle": {"runtime_role": "rest"}},
        movement_class="avian_biped")
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        m = json.loads(z.read("manifest.json"))
        pkg = json.loads(z.read("package.json"))
    assert m["movement_class"] == "avian_biped"
    assert pkg["movement_class"] == "avian_biped"


def test_per_animation_view_loop_and_buffer_flow_through(monkeypatch):
    # §3.1/§3.2/§3.3: loop, timed_buffer_ms, and a profile-level view all reach the
    # manifest — sheet-level (view) and per-animation (loop, buffer, view).
    monkeypatch.setattr(factory, "_remove_bg", lambda img: img.convert("RGBA"))
    walk = [Image.new("RGB", (256, 256), (0, 0, 0)) for _ in range(2)]
    idle = [Image.new("RGB", (256, 256), (0, 0, 0)) for _ in range(2)]
    jump = [Image.new("RGB", (256, 256), (0, 0, 0)) for _ in range(2)]
    sleep = [Image.new("RGB", (256, 256), (0, 0, 0)) for _ in range(2)]
    top_view = {"view_kind": "top", "native_facing": "right", "mirroring_policy": "none"}
    profile_view = {"view_kind": "side", "native_facing": "left", "mirroring_policy": "flip"}
    zip_bytes = factory.pack_datsme_bundle(
        {"walk": walk, "idle": idle, "jump": jump, "sleep": sleep}, "b", "B",
        pose_meta={
            "walk": {"runtime_role": "active"},
            "idle": {"runtime_role": "rest"},
            "jump": {"runtime_role": "triggered", "loop": False},        # §3.1
            "sleep": {"runtime_role": "timed", "timed_buffer_ms": 6000,   # §3.2
                      "view": top_view},                                  # §3.3 per-pose override
        },
        view=profile_view)                                               # §3.3 sheet-level
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        m = json.loads(z.read("manifest.json"))
    anims = m["animations"]

    # Sheet-level view is the profile's, not the hardcoded constant.
    assert m["view_kind"] == "side" and m["native_facing"] == "left" and m["mirroring_policy"] == "flip"

    # loop is data now: a triggered clip is one-shot, others loop.
    assert anims["jump"]["loop"] is False
    assert anims["walk"]["loop"] is True and anims["idle"]["loop"] is True

    # timed_buffer_ms is emitted only where authored.
    assert anims["sleep"]["timed_buffer_ms"] == 6000
    assert "timed_buffer_ms" not in anims["walk"]

    # per-animation view: sleep overrides to top-down; the rest inherit the sheet view.
    assert anims["sleep"]["view"] == top_view
    assert anims["walk"]["view"] == profile_view
