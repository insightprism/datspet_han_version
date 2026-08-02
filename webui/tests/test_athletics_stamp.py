"""Guard tests for the build-time athletics stamp (SPEC_PET_ARENA §14,
`webui/tests/test_athletics_stamp.py` — the build seam).

Zero-GPU. The stamp is the fourth patch at `_finalize_pet_from_zip`; these pin
the four §14 promises: the block is present with inputs matching the pet's own
facts, it survives the ownership stamps in any order, every other manifest key
passes through untouched, and a re-mint under a bumped table version preserves
the identity nudges — identity survives a rebalance.
"""
import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from conftest import make_bundle_zip, make_pet  # noqa: E402,F401  (fixtures)

import pet_athletics  # noqa: E402
import pet_ownership  # noqa: E402
from pet_factory import athletics  # noqa: E402

MINTED_AT = "2026-08-02T12:00:00Z"

ANIMS = {"walk": {"frames": [0]}, "idle": {"frames": [1]}, "run": {"frames": [2]}}


def _manifest_in(zip_bytes):
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        return json.loads(z.read("manifest.json").decode("utf-8"))


PET_ID = "stamppet0001"


def test_stamped_block_matches_the_pets_own_facts():
    zip_bytes, _ = make_bundle_zip(animations=ANIMS,
                                   movement_class="aquatic_swimmer")
    stamped, manifest_json = pet_athletics.stamp_pet_athletics(
        zip_bytes, pet_id=PET_ID, at=MINTED_AT)

    block = json.loads(manifest_json)["athletics"]
    assert block["schema_version"] == athletics.SCHEMA_VERSION
    assert block["table_version"] == athletics.TABLE_VERSION
    assert block["poses"] == list(ANIMS)               # §3.3 — the pose set
    assert block["minted_at"] == MINTED_AT
    # §3.4 (Rev.7) — the nudges are the id derivation, so a stamped and an
    # unstamped copy of the same pet are the same athlete.
    assert block["identity_nudges"] == athletics.identity_nudges_from_pet_id(PET_ID)
    # §3.1 — attributes come from the declared movement_class row (+ nudge).
    row = athletics.base_row("aquatic_swimmer")
    assert block["water"] == row["water"]
    assert abs(block["speed"]
               - (row["speed"] + block["identity_nudges"]["speed"])) < 1e-12
    # The zip's manifest and the returned column agree — the pair that must.
    assert _manifest_in(stamped)["athletics"] == block


def test_every_other_manifest_key_passes_through_untouched():
    zip_bytes, _ = make_bundle_zip(
        animations=ANIMS, movement_class="mammalian_quadruped",
        view_kind="side", custom_future_key={"nested": True})
    before = _manifest_in(zip_bytes)
    _, manifest_json = pet_athletics.stamp_pet_athletics(zip_bytes, pet_id=PET_ID, at=MINTED_AT)
    after = json.loads(manifest_json)
    after.pop("athletics")
    assert after == before, "the stamp may add its key and touch nothing else"


def test_stamp_survives_ownership_stamps_in_any_order():
    zip_bytes, _ = make_bundle_zip(animations=ANIMS,
                                   movement_class="mammalian_quadruped")

    # athletics → fingerprint → ownership
    a, _ = pet_athletics.stamp_pet_athletics(zip_bytes, pet_id=PET_ID, at=MINTED_AT)
    a, _ = pet_ownership.stamp_bundle_fingerprint(a)
    a, a_manifest = pet_ownership.transfer_pet_ownership(
        a, category=pet_ownership.FACTORY_CATEGORY,
        name=pet_ownership.FACTORY_OWNER_NAME, at=MINTED_AT)

    # fingerprint → ownership → athletics
    b, _ = pet_ownership.stamp_bundle_fingerprint(zip_bytes)
    b, _ = pet_ownership.transfer_pet_ownership(
        b, category=pet_ownership.FACTORY_CATEGORY,
        name=pet_ownership.FACTORY_OWNER_NAME, at=MINTED_AT)
    b, b_manifest = pet_athletics.stamp_pet_athletics(b, pet_id=PET_ID, at=MINTED_AT)

    for manifest_json in (a_manifest, b_manifest):
        manifest = json.loads(manifest_json)
        assert manifest["athletics"]["table_version"] == athletics.TABLE_VERSION
        assert manifest["fingerprint"] == pet_ownership.BUNDLE_FINGERPRINT
        assert manifest["owner_category"] == pet_ownership.FACTORY_CATEGORY
    assert json.loads(a_manifest)["athletics"] == json.loads(b_manifest)["athletics"]


def test_restamp_is_a_same_object_noop():
    zip_bytes, _ = make_bundle_zip(animations=ANIMS,
                                   movement_class="mammalian_quadruped")
    once, once_manifest = pet_athletics.stamp_pet_athletics(
        zip_bytes, pet_id=PET_ID, at=MINTED_AT)
    twice, twice_manifest = pet_athletics.stamp_pet_athletics(
        once, pet_id="a-totally-different-id", at="2027-01-01T00:00:00Z")
    assert twice is once, "a current block must not re-compress the bundle"
    assert twice_manifest == once_manifest
    # And the original mint date survives the attempted re-stamp.
    assert json.loads(twice_manifest)["athletics"]["minted_at"] == MINTED_AT


def test_remint_under_bumped_table_version_preserves_identity():
    # §4.1/§5.3 — the one that will actually catch a regression: a balance
    # patch must not silently give every pet a new personality.
    stale_block = {
        "schema_version": athletics.SCHEMA_VERSION,
        "table_version": "athletics.v0",
        "speed": 0.9, "power": 0.9, "endurance": 0.9,
        "land": 0.9, "water": 0.9, "air": 0.9,
        "identity_nudges": {"speed": 0.05, "power": -0.03, "endurance": 0.01},
        "poses": ["walk", "idle"],
        "minted_at": "2026-01-01T00:00:00Z",
    }
    zip_bytes, _ = make_bundle_zip(animations=ANIMS,
                                   movement_class="mammalian_quadruped",
                                   athletics=stale_block)
    _, manifest_json = pet_athletics.stamp_pet_athletics(zip_bytes, pet_id=PET_ID, at=MINTED_AT)
    block = json.loads(manifest_json)["athletics"]
    assert block["table_version"] == athletics.TABLE_VERSION
    assert block["identity_nudges"]["speed"] == 0.05, \
        "identity must survive the rebalance"
    row = athletics.base_row("mammalian_quadruped")
    assert abs(block["speed"] - min(row["speed"] + 0.05, 1.0)) < 1e-12


def test_a_bad_minted_at_or_missing_pet_id_raises_at_the_call_site():
    zip_bytes, _ = make_bundle_zip(animations=ANIMS)
    try:
        pet_athletics.stamp_pet_athletics(zip_bytes, pet_id=PET_ID,
                                          at="not-a-timestamp")
        assert False, "expected AthleticsStampError"
    except pet_athletics.AthleticsStampError:
        pass
    try:
        pet_athletics.stamp_pet_athletics(zip_bytes, pet_id="", at=MINTED_AT)
        assert False, "expected AthleticsStampError"
    except pet_athletics.AthleticsStampError:
        pass


def test_finalize_stamps_athletics_and_digest_covers_it(dpp_env):
    """The integration promise (§4.2): the stamp runs upstream of insert_pet,
    so the stored digest is a digest of athletics-stamped bytes."""
    import importlib

    db = dpp_env["db"]
    import app as app_mod
    importlib.reload(app_mod)
    app_mod.db = db
    app_mod.datsme_integration = dpp_env["di"]

    zip_bytes, _ = make_bundle_zip(breed_id="athlete", animations=ANIMS,
                                   movement_class="avian_biped")
    job = app_mod.Job(id="athlete00001", name="Athlete",
                      created_at=1783800000.0)
    app_mod._finalize_pet_from_zip(job, description="athlete",
                                   breed_id="athlete", zip_bytes=zip_bytes)

    row = db.get_pet("athlete00001")
    stored = json.loads(row["manifest_json"])
    assert stored["athletics"]["table_version"] == athletics.TABLE_VERSION
    assert stored["athletics"]["poses"] == list(ANIMS)
    assert stored["athletics"]["minted_at"].endswith("Z")
    # The nudges decode the pet id the row was inserted under — the identity.
    assert stored["athletics"]["identity_nudges"] == \
        athletics.identity_nudges_from_pet_id("athlete00001")
    # Column and bundle agree, and the digest covers the stamped bytes.
    assert _manifest_in(row["bundle_zip"])["athletics"] == stored["athletics"]
    assert row["bundle_sha256"] == hashlib.sha256(row["bundle_zip"]).hexdigest()
