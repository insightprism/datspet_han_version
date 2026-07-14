"""Unit tests for the motion_profiles WRITE path (SPEC_MOTION_PROFILE_ADMIN §3).

Exercises write_profile / delete_profile / duplicate_profile against a TEMP copy
of the profiles dir (monkeypatched _DIR), so the real registry is never touched.
Pure data, no GPU.

Run:  python3 -m pytest pet_factory/tests/test_motion_admin.py
"""
import copy
import json
import shutil
from pathlib import Path

import pytest

from pet_factory import motion_profiles as mp
from pet_factory.motion_profiles import admin


@pytest.fixture()
def temp_profiles(tmp_path, monkeypatch):
    """A writable copy of the real profiles dir, wired into the loader + admin so
    every read/write hits the temp copy. Cache is reset around the test."""
    src = Path(mp.__file__).resolve().parent
    dst = tmp_path / "motion_profiles"
    dst.mkdir()
    for f in src.glob("*.json"):
        shutil.copy(f, dst / f.name)
    monkeypatch.setattr(mp, "_DIR", dst)
    monkeypatch.setattr(admin, "_DIR", dst)
    mp.reload()
    yield dst
    mp.reload()


def _valid_new_profile(key="testbeast"):
    """A minimal valid profile under a fresh key (clone quadruped, new key, no kws)."""
    base = copy.deepcopy(json.loads((Path(mp.__file__).resolve().parent / "quadruped.json").read_text()))
    base["key"] = key
    base["keywords"] = []
    return base


# --- write (create) --------------------------------------------------------
def test_create_writes_file_and_registers(temp_profiles):
    admin.write_profile(_valid_new_profile("testbeast"), label="Test Beast")
    assert (temp_profiles / "testbeast.json").is_file()
    reg = admin.load_registry()
    entry = next(e for e in reg["profiles"] if e["key"] == "testbeast")
    assert entry["file"] == "testbeast.json" and entry["label"] == "Test Beast"
    # Live immediately (reload was called) — the resolver loads it.
    assert mp.load_motion_profile("testbeast").key == "testbeast"


def test_create_rejects_duplicate_key(temp_profiles):
    with pytest.raises(admin.ProfileWriteError):
        admin.write_profile(_valid_new_profile("quadruped"), label="dup")  # already exists


def test_create_rejects_invalid_profile(temp_profiles):
    bad = _valid_new_profile("brokenone")
    bad["poses"].pop("run")   # missing a canonical pose
    with pytest.raises(admin.ProfileWriteError) as ei:
        admin.write_profile(bad, label="broken")
    assert any("run" in e or "canonical" in e for e in ei.value.errors)


# --- write (update) --------------------------------------------------------
def test_update_overwrites_existing(temp_profiles):
    admin.write_profile(_valid_new_profile("testbeast"), label="Test Beast")
    p = _valid_new_profile("testbeast")
    p["movement_class"] = "changed_class"
    admin.write_profile(p, label="Renamed Label", existing_key="testbeast")
    assert json.loads((temp_profiles / "testbeast.json").read_text())["movement_class"] == "changed_class"
    entry = next(e for e in admin.load_registry()["profiles"] if e["key"] == "testbeast")
    assert entry["label"] == "Renamed Label"


def test_update_refuses_key_change(temp_profiles):
    admin.write_profile(_valid_new_profile("testbeast"), label="x")
    p = _valid_new_profile("renamedbeast")   # different key than existing_key
    with pytest.raises(admin.ProfileWriteError):
        admin.write_profile(p, label="x", existing_key="testbeast")


# --- delete ----------------------------------------------------------------
def test_delete_removes_file_and_entry(temp_profiles):
    admin.write_profile(_valid_new_profile("testbeast"), label="x")
    admin.delete_profile("testbeast")
    assert not (temp_profiles / "testbeast.json").exists()
    assert "testbeast" not in {e["key"] for e in admin.load_registry()["profiles"]}


def test_delete_refuses_default(temp_profiles):
    default_key = admin.load_registry()["default"]
    with pytest.raises(admin.ProfileWriteError):
        admin.delete_profile(default_key)


def test_delete_refuses_when_pinned(temp_profiles):
    with pytest.raises(admin.ProfileWriteError) as ei:
        admin.delete_profile("avian", pinned_by=["bird"])
    assert "pinned" in str(ei.value)


# --- duplicate -------------------------------------------------------------
def test_duplicate_clones_under_new_key_and_clears_keywords(temp_profiles):
    clone = admin.duplicate_profile("quadruped", new_key="quadrupedfat", new_label="Fat Quadruped")
    assert clone["key"] == "quadrupedfat"
    assert clone["keywords"] == []                 # cleared (unique constraint)
    assert clone["movement_class"] == json.loads(
        (temp_profiles / "quadruped.json").read_text())["movement_class"]  # same poses/class
    assert (temp_profiles / "quadrupedfat.json").is_file()
    assert mp.load_motion_profile("quadrupedfat").key == "quadrupedfat"


def test_duplicate_rejects_existing_target(temp_profiles):
    with pytest.raises(admin.ProfileWriteError):
        admin.duplicate_profile("quadruped", new_key="avian", new_label="x")  # avian exists


def test_keyword_clash_rejected_on_create(temp_profiles):
    p = _valid_new_profile("testbeast")
    p["keywords"] = ["dog"]     # 'dog' belongs to quadruped
    with pytest.raises(admin.ProfileWriteError) as ei:
        admin.write_profile(p, label="x")
    assert any("dog" in e for e in ei.value.errors)
