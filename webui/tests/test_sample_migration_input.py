"""The REAL migration input, guarded while it still exists (SPEC_PET_STORE §8).

pet_factory/tests/test_catalog_samples.py pinned the shipped sample bundles and
retired with the sample surface. But the files under
pet_factory/animal_catalog/<animal>/samples/ remain the input of
scripts/migrate_samples_to_store.py until the LAST environment has migrated —
and in that window nothing else in CI asserts that the artifact actually on
disk is still sellable. This file is that guard.

DELETE THIS FILE together with the sample content files (deploy/CHECKLIST.md B9
names both). Until then: if the files are already gone, the parametrize set is
empty and pytest reports the test as skipped — a lingering copy can never fail
the build after the deletion step ran.
"""
import os
import sys
from pathlib import Path

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WEBUI = os.path.join(REPO, "webui")
for p in (WEBUI, REPO):
    if p not in sys.path:
        sys.path.insert(0, p)

import store_validation  # noqa: E402

SAMPLES = sorted(
    Path(REPO, "pet_factory", "animal_catalog").glob("*/samples/*.zip"))


@pytest.mark.parametrize(
    "zip_path", SAMPLES,
    ids=[f"{p.parent.parent.name}/{p.stem}" for p in SAMPLES])
def test_the_shipped_sample_is_still_migratable(zip_path):
    """Exactly what migrate_samples_to_store.py will check per file: a sibling
    portrait, and a sellable bundle under the seed name/animal it will use."""
    preview_path = zip_path.with_suffix(".png")
    assert preview_path.is_file(), (
        f"{zip_path.name} has no {preview_path.name} portrait — the migration "
        f"would SKIP it and the store would launch without it")
    errors = store_validation.sellability_errors(
        bundle_zip=zip_path.read_bytes(),
        preview_png=preview_path.read_bytes(),
        display_name=zip_path.stem.title(),
        animal=zip_path.parent.parent.name)
    assert errors == [], (
        f"{zip_path} is no longer sellable: {'; '.join(errors)}")
