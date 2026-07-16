"""Unit tests for the design_axes WRITE path (SPEC_PET_DESIGN_AXES_ADMIN §1.1).

Exercises write_axis / delete_axis against a TEMP copy of the axes dir
(monkeypatched _DIR), so the real registry is never touched. Pure data, no GPU.
Mirrors test_motion_admin.py.
"""
import copy
import json
import shutil
from pathlib import Path

import pytest

from pet_factory import design_axes as da
from pet_factory.design_axes import admin


@pytest.fixture()
def temp_axes(tmp_path, monkeypatch):
    """A writable copy of the real axes dir, wired into the loader + admin so
    every read/write hits the temp copy. Cache is reset around the test."""
    src = Path(da.__file__).resolve().parent
    dst = tmp_path / "design_axes"
    dst.mkdir()
    for f in src.glob("*.json"):
        shutil.copy(f, dst / f.name)
    monkeypatch.setattr(da, "_DIR", dst)
    monkeypatch.setattr(admin, "_DIR", dst)
    da.reload()
    yield dst
    da.reload()


def _valid_new_axis(key="material", kind="universal", applies_to=None):
    """A minimal valid axis under a fresh key (clone pattern, re-key)."""
    base = copy.deepcopy(json.loads(
        (Path(da.__file__).resolve().parent / "pattern.json").read_text()))
    base["axis"] = key
    base["kind"] = kind
    base.pop("applies_to", None)
    if applies_to is not None:
        base["applies_to"] = applies_to
    return base


# --- write (create) ----------------------------------------------------------
def test_create_writes_file_registers_last_and_goes_live(temp_axes):
    admin.write_axis(_valid_new_axis("material"))
    assert (temp_axes / "material.json").is_file()
    reg = admin.load_registry()
    assert reg["axes"][-1] == {"key": "material"}, \
        "a create must APPEND — registry order is menu order (§1)"
    # Live immediately (reload was called) — the resolver serves it.
    assert any(a["axis"] == "material" for a in da.list_axes())
    assert da.prompt_fragment("material", "spotted") != ""


def test_create_preserves_menu_order_and_registry_metadata(temp_axes):
    before = [e["key"] for e in admin.load_registry()["axes"]]
    admin.write_axis(_valid_new_axis("material"))
    reg = admin.load_registry()
    assert [e["key"] for e in reg["axes"]] == before + ["material"]
    assert "_doc" in reg and "max_concurrent_strong" in reg, \
        "registry metadata must ride through a write untouched"


def test_create_rejects_duplicate_key(temp_axes):
    with pytest.raises(admin.AxisWriteError):
        admin.write_axis(_valid_new_axis("pattern"))


def test_create_rejects_invalid_axis_with_the_validator_errors(temp_axes):
    bad = _valid_new_axis("brokenone")
    bad["options"][1]["prompt_fragment"] = ""       # a dead control
    with pytest.raises(admin.AxisWriteError) as ei:
        admin.write_axis(bad)
    assert any("changes nothing" in e for e in ei.value.errors)


def test_create_rejects_second_axis_for_a_served_surface(temp_axes):
    with pytest.raises(admin.AxisWriteError) as ei:
        admin.write_axis(_valid_new_axis("feathering", kind="surface",
                                         applies_to="feathers"))
    assert any("already served" in e for e in ei.value.errors)


# --- write (update) ----------------------------------------------------------
def test_update_overwrites_and_busts_the_cache(temp_axes):
    raw = json.loads((temp_axes / "pattern.json").read_text())
    raw["options"].append(
        {"key": "brindle", "label": "Brindle", "prompt_fragment": "brindle-marked"})
    admin.write_axis(raw, existing_key="pattern")
    assert da.prompt_fragment("pattern", "brindle") == "brindle-marked", \
        "the design step must reflect an admin edit with no restart"


def test_update_refuses_key_change(temp_axes):
    raw = _valid_new_axis("renamed_pattern")
    with pytest.raises(admin.AxisWriteError):
        admin.write_axis(raw, existing_key="pattern")


# --- delete -------------------------------------------------------------------
def test_delete_removes_file_and_entry(temp_axes):
    admin.write_axis(_valid_new_axis("material"))
    admin.delete_axis("material")
    assert not (temp_axes / "material.json").exists()
    assert "material" not in {e["key"] for e in admin.load_registry()["axes"]}
    assert not any(a["axis"] == "material" for a in da.list_axes())


def test_delete_refuses_when_used_by_catalog_entries(temp_axes):
    """The rev.2 guard (§0.2 applied to deletes): deleting plumage while a bird
    tags feathers would create exactly the state the build guard rejects."""
    with pytest.raises(admin.AxisWriteError) as ei:
        admin.delete_axis("plumage", used_by=["bird/jay"])
    assert "used by" in str(ei.value) and (temp_axes / "plumage.json").exists()


def test_delete_unknown_refused(temp_axes):
    with pytest.raises(admin.AxisWriteError):
        admin.delete_axis("no_such_axis")
