"""Unit tests for the animal_catalog DESIGN-PROFILE write path
(SPEC_PET_DESIGN_AXES_ADMIN §1.2).

Exercises set_design_profile against a TEMP copy of catalog.json, so the real
catalog is never touched. The load-bearing assertions: only the design-profile
fields ever change (§0.5 — a design edit cannot corrupt a vetted entry), and
the shared validator blocks at save what the build guard blocks at test.
"""
import json
import shutil
from pathlib import Path

import pytest

from pet_factory import animal_catalog as cat
from pet_factory.animal_catalog import admin


@pytest.fixture()
def temp_catalog(tmp_path, monkeypatch):
    src = Path(cat.__file__).resolve().parent / "catalog.json"
    dst = tmp_path / "catalog.json"
    shutil.copy(src, dst)
    monkeypatch.setattr(cat, "_CATALOG_FILE", dst)
    monkeypatch.setattr(admin, "_CATALOG_FILE", dst)
    cat.reload()
    yield dst
    cat.reload()


# --- the narrow write (§0.5) --------------------------------------------------
def test_write_touches_only_design_profile_fields(temp_catalog):
    before = json.loads(temp_catalog.read_text())
    admin.set_design_profile("cat", surface="scales")   # absurd but valid content
    after = json.loads(temp_catalog.read_text())

    cat_before = next(a for a in before["animals"] if a["key"] == "cat")
    cat_after = next(a for a in after["animals"] if a["key"] == "cat")
    assert cat_after["surface"] == "scales"
    for field in cat_before:
        if field not in admin.ALLOWED_FIELDS:
            assert cat_after[field] == cat_before[field], \
                f"{field} changed — a design write must never touch it (§0.5)"
    # …and the OTHER animal is byte-identical.
    assert next(a for a in after["animals"] if a["key"] == "dog") == \
        next(a for a in before["animals"] if a["key"] == "dog")


def test_write_goes_live_without_a_restart(temp_catalog):
    admin.set_design_profile("cat", "tabby", surface="feathers")
    assert cat.resolved_surface("cat", "tabby") == "feathers"
    assert cat.resolved_surface("cat", "siamese") == "fur", "siblings inherit, untouched"


def test_breed_override_and_unset_restores_inheritance(temp_catalog):
    admin.set_design_profile("cat", "tabby", surface="scales")
    assert cat.resolved_surface("cat", "tabby") == "scales"
    admin.set_design_profile("cat", "tabby", surface=None)   # unset → inherit
    assert cat.resolved_surface("cat", "tabby") == "fur"
    raw = json.loads(temp_catalog.read_text())
    tabby = next(b for a in raw["animals"] if a["key"] == "cat"
                 for b in a["breeds"] if b["key"] == "tabby")
    assert "surface" not in tabby, "inheritance stays VISIBLE in the file (no key)"


def test_surface_options_write_and_resolve(temp_catalog):
    admin.set_design_profile("cat", "tabby", surface_options=["fluffy", "curly"])
    assert cat.resolved_surface_options("cat", "tabby") == ["fluffy", "curly"]
    assert cat.resolved_surface_options("cat", "siamese") is None


# --- the shared validator blocks at save (§0.2) --------------------------------
def test_unknown_surface_refused_with_validator_errors(temp_catalog):
    with pytest.raises(admin.CatalogWriteError) as ei:
        admin.set_design_profile("cat", surface="granite")
    assert any("matches no surface axis" in e for e in ei.value.errors)


def test_out_of_range_option_keys_refused(temp_catalog):
    with pytest.raises(admin.CatalogWriteError) as ei:
        admin.set_design_profile("cat", "tabby", surface_options=["ruffled"])  # a plumage key
    assert any("ruffled" in e for e in ei.value.errors)
    with pytest.raises(admin.CatalogWriteError):
        admin.set_design_profile("cat", "tabby", surface_default="iridescent")


def test_animal_level_surface_cannot_be_unset(temp_catalog):
    """A curated entry must always resolve a surface (§3.1) — unsetting the
    animal-level tag would degrade every breed to the unknown-animal posture,
    which is exactly the state the build guard rejects."""
    with pytest.raises(admin.CatalogWriteError) as ei:
        admin.set_design_profile("cat", surface=None)
    assert any("must still resolve" in e for e in ei.value.errors)


def test_unknown_entry_refused(temp_catalog):
    with pytest.raises(admin.CatalogWriteError):
        admin.set_design_profile("axolotl", surface="fur")
    with pytest.raises(admin.CatalogWriteError):
        admin.set_design_profile("cat", "sphynx", surface="fur")
