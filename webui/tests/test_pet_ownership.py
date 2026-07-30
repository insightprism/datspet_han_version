"""The bundle owner fields — SPEC_PET_OWNER_FIELD Phase 1 (§6 tests 1-11).

Phase 1 is DatsPet's half, and DatsPet's half is deliberately small: it stamps the
UNSOLD state and nothing else. `factory` at mint, `public` for a curated sample,
plus the `fingerprint` mark. **Every ownership change happens on DatsMe** — the
checkout and the gift — so there is no buyer stamp here to test, and no identity
plumbing to get wrong.

What these pin, in one sentence each:

  the primitive   write→read round-trips, and a transfer loses NO other key
  the mint sites  both stamp, and stamp upstream of the digest
  the NON-rule    `_export_item` still has no owner condition (§2.5) — under this
                  design EVERY pet DatsPet exports is `factory`, so that filter
                  would suppress the entire pull channel, not an edge case

Test 2 is the cross-repo one: it is the promise that the host's later stamps do
not drop `fingerprint`, made from the side that writes it.
"""
import hashlib
import importlib
import io
import json
import os
import sys
import zipfile
from pathlib import Path

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WEBUI = os.path.join(REPO, "webui")
for p in (WEBUI, REPO):
    if p not in sys.path:
        sys.path.insert(0, p)

from conftest import ANON_OWNER, anon_cookies, make_bundle_zip, make_pet  # noqa: E402

import pet_ownership  # noqa: E402

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "owner_fields.json").read_text())


@pytest.fixture()
def app_client(dpp_env):
    from fastapi.testclient import TestClient
    import app as app_mod
    importlib.reload(app_mod)
    app_mod.db = dpp_env["db"]
    app_mod.datsme_integration = dpp_env["di"]
    return TestClient(app_mod.app)


def _manifest_in(zip_bytes):
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        return json.loads(z.read("manifest.json").decode("utf-8"))


# ---------------------------------------------------------------------------
# 1-4. The primitive (the half DatsMe vendors a copy of the fixture for)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("case", FIXTURE["cases"],
                         ids=[c["case"][:40] for c in FIXTURE["cases"]])
def test_read_returns_exactly_what_transfer_wrote(case):
    """§6 t1 — read(write(x)) == x over every category in the owned fixture."""
    w = case["write"]
    zip_bytes, _ = make_bundle_zip()
    stamped, manifest_json = pet_ownership.transfer_pet_ownership(
        zip_bytes, category=w["category"], name=w["name"], at=w["at"])

    assert pet_ownership.read_pet_ownership(manifest_json) == (
        w["category"], w["name"], w["at"])
    # And the manifest INSIDE the returned zip agrees with the returned string —
    # they are persisted as two columns and a disagreement is invisible until
    # the host counts poses in the bytes and we quoted from the column.
    assert _manifest_in(stamped) == json.loads(manifest_json)


def test_a_transfer_preserves_every_key_it_does_not_own():
    """§6 t2 — the test that stops `fingerprint` vanishing on the first sale.

    A manifest rebuilt from a known field list passes every owner assertion and
    silently drops everything else. Only an explicit preservation check catches
    it, which is why the fixture carries a deliberately unknown nested key.

    Cross-repo: DatsPet stamps `fingerprint` at mint and the HOST does every
    later stamp, so this is the promise that the host's copy of the primitive
    must also keep. The vendored fixture is how that promise is enforced there.
    """
    preserved = {k: v for k, v in FIXTURE["preserved_manifest"].items()
                 if not k.startswith("_")}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("manifest.json", json.dumps(preserved))
        z.writestr("package.json", json.dumps({"breed_id": "b"}))
        z.writestr("b_sprite.png", b"\x89PNG\r\n\x1a\nDATA")

    _, manifest_json = pet_ownership.transfer_pet_ownership(
        buf.getvalue(), category="individual", name="sara.1",
        at="2026-07-30T18:00:00Z")

    after = json.loads(manifest_json)
    for key, value in preserved.items():
        assert after[key] == value, f"transfer lost or changed {key!r}"
    assert after["fingerprint"] == pet_ownership.BUNDLE_FINGERPRINT
    assert after["owner_name"] == "sara.1"


def test_the_sprite_and_package_members_survive_a_transfer_byte_for_byte():
    """§6 t7 — `app._unpack_bundle` matches members BY NAME, so a stamp that
    renamed or dropped one would produce a pet that stores fine and never
    renders."""
    zip_bytes, _ = make_bundle_zip(breed_id="phoenix_red")
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        before = {n: z.read(n) for n in z.namelist()}

    stamped, _ = pet_ownership.transfer_pet_ownership(
        zip_bytes, category="public", name="", at="2026-07-30T18:00:00Z")

    with zipfile.ZipFile(io.BytesIO(stamped)) as z:
        assert set(z.namelist()) == set(before)
        for name in before:
            if name != "manifest.json":
                assert z.read(name) == before[name], f"{name} was not preserved"


@pytest.mark.parametrize("case", FIXTURE["rejected"],
                         ids=[c["case"][:40] for c in FIXTURE["rejected"]])
def test_a_stamp_no_reader_would_accept_fails_at_the_call_site(case):
    """§6 t3 — a bad stamp is silent until ingest, where it surfaces as
    'licensed to someone else' on a pet the buyer just paid for. Raise here."""
    w = case["write"]
    zip_bytes, _ = make_bundle_zip()
    with pytest.raises(pet_ownership.OwnerFieldError):
        pet_ownership.transfer_pet_ownership(
            zip_bytes, category=w["category"], name=w["name"], at=w["at"])


def test_a_second_identical_stamp_writes_nothing():
    """§6 t4 — the no-op rule (§2.1).

    DatsPet no longer restamps anything, but the HOST's checkout stamp runs again
    on every re-checkout. Without this rule a re-run would rewrite the bundle and
    relabel `owner_transferred_at`, so "since when do you own this" would become
    "when you last clicked buy". Pinned on the side that owns the primitive.
    """
    zip_bytes, _ = make_bundle_zip()
    first, first_manifest = pet_ownership.transfer_pet_ownership(
        zip_bytes, category="individual", name="sara.1",
        at="2026-07-30T15:01:44Z")
    second, second_manifest = pet_ownership.transfer_pet_ownership(
        first, category="individual", name="sara.1",
        at="2026-08-01T09:00:00Z")           # a LATER date, deliberately

    assert second is first, "an unchanged owner must not rewrite the bundle"
    assert pet_ownership.read_pet_ownership(second_manifest)[2] == \
        "2026-07-30T15:01:44Z"
    assert json.loads(second_manifest) == json.loads(first_manifest)


def test_the_manifest_level_writer_is_the_whole_contract_datsme_needs():
    """§2.1 — `set_pet_ownership` is str→str, and that is ALL the host needs.

    DatsMe stores a pet's parts, not its zip (`write_assets(manifest_json=…)`),
    and rebuilds bundles with `build_bundle_zip`. So its checkout and gift stamps
    are one line each and never open an archive. This test is that call, written
    the way the host will write it — if it ever stops holding, Phase 2 breaks.
    """
    _, minted = make_bundle_zip()
    minted = pet_ownership.set_bundle_fingerprint(minted)
    minted = pet_ownership.set_pet_ownership(
        minted, category=pet_ownership.FACTORY_CATEGORY,
        name=pet_ownership.FACTORY_OWNER_NAME, at="2026-07-30T14:22:05Z")

    # The host at checkout: sara.1 buys it.
    sold = pet_ownership.set_pet_ownership(
        minted, category="individual", name="sara.1", at="2026-07-30T15:01:44Z")
    assert pet_ownership.read_pet_ownership(sold) == (
        "individual", "sara.1", "2026-07-30T15:01:44Z")

    # A re-checkout of the same pet: same owner, later clock. Must not relabel.
    again = pet_ownership.set_pet_ownership(
        sold, category="individual", name="sara.1", at="2026-08-01T09:00:00Z")
    assert again is sold, "a re-run must return the input unchanged"

    # The host at gift accept: sara.1 gives it to wu.1.
    gifted = pet_ownership.set_pet_ownership(
        sold, category="individual", name="wu.1", at="2026-07-30T16:12:09Z")
    assert pet_ownership.read_pet_ownership(gifted) == (
        "individual", "wu.1", "2026-07-30T16:12:09Z")

    # DatsPet's mark survived both host-side transfers — the cross-repo promise.
    assert json.loads(gifted)["fingerprint"] == pet_ownership.BUNDLE_FINGERPRINT


def test_read_never_raises_on_a_manifest_it_cannot_parse():
    """Absence is never coerced into a category — the caller decides what
    missing means (the host refuses; a display shows 'unknown')."""
    for bad in (None, "", "not json", "[]", '{"animations":{}}'):
        assert pet_ownership.read_pet_ownership(bad) == (None, None, None)


def test_name_is_empty_exactly_when_the_category_is_public():
    """`public` is the one category with no subject (§1.1)."""
    for case in FIXTURE["cases"]:
        w = case["write"]
        assert (w["name"] == "") == (w["category"] == pet_ownership.PUBLIC_CATEGORY)


# ---------------------------------------------------------------------------
# 5-6. DatsPet's two stamp sites — both at mint, both write the UNSOLD state
# ---------------------------------------------------------------------------

def test_a_freshly_built_pet_is_factory_owned_and_fingerprinted(app_client, dpp_env):
    """§6 t5 — mint stamps `factory`/`datspet` + the fingerprint, and the STORED
    digest is a digest of the STAMPED bytes.

    The digest assertion is the one that matters: it proves the stamp ran
    upstream of `insert_pet` (§2.4). Because DatsPet never restamps a stored row,
    that ordering is the only thing standing between the bytes we serve and the
    `bundle_sha256` the pull channel advertises.
    """
    db = dpp_env["db"]
    import app as app_mod

    zip_bytes, _ = make_bundle_zip(breed_id="freshpet")
    job = app_mod.Job(id="mintpet00001", name="Fresh Pet",
                      created_at=1783800000.0)
    app_mod._finalize_pet_from_zip(job, description="fresh pet",
                                   breed_id="freshpet", zip_bytes=zip_bytes)

    row = db.get_pet("mintpet00001")
    category, name, at = pet_ownership.read_pet_ownership(row["manifest_json"])
    assert (category, name) == (pet_ownership.FACTORY_CATEGORY,
                                pet_ownership.FACTORY_OWNER_NAME)
    assert at.endswith("Z") and at.startswith("2026-")
    assert _manifest_in(row["bundle_zip"])["fingerprint"] == \
        pet_ownership.BUNDLE_FINGERPRINT

    assert row["bundle_sha256"] == hashlib.sha256(row["bundle_zip"]).hexdigest()
    assert row["size_bytes"] == len(row["bundle_zip"])


def test_adopting_a_curated_sample_stamps_it_public(app_client, dpp_env):
    """§6 t6 — a store sample belongs to nobody in particular, and `public` is
    the category that says so. Matters for a RE-UPLOAD of a store bundle."""
    db = dpp_env["db"]
    from pet_factory import animal_catalog as catalog

    sample = None
    for animal in catalog.list_animals():
        animal_key = animal.get("key", "")
        for candidate in catalog.list_samples(animal_key):
            if catalog.sample_bundle_path(animal_key, candidate["key"]):
                sample = (animal_key, candidate["key"])
                break
        if sample:
            break
    if sample is None:
        pytest.skip("no curated sample bundle ships in the catalog")

    r = app_client.post(f"/api/catalog/{sample[0]}/samples/{sample[1]}/adopt",
                        cookies=anon_cookies())
    assert r.status_code == 200, r.text

    row = db.get_pet(r.json()["pet_id"])
    category, name, _ = pet_ownership.read_pet_ownership(row["manifest_json"])
    assert (category, name) == (pet_ownership.PUBLIC_CATEGORY, "")
    assert _manifest_in(row["bundle_zip"])["fingerprint"] == \
        pet_ownership.BUNDLE_FINGERPRINT
    assert row["bundle_sha256"] == hashlib.sha256(row["bundle_zip"]).hexdigest()


def test_keeping_a_pet_does_not_touch_the_bundle(app_client, dpp_env):
    """`keep` is NOT a stamp site (§2.4). An earlier revision made it one, which
    forced DatsPet to learn the buyer's slug over the network and to rewrite a
    bundle whose digest it had already advertised. The owner is the host's to
    write, at checkout and gift. Pinned so the stamp does not creep back."""
    db = dpp_env["db"]
    make_pet(db, pet_id="keeppet00001", external_user_id="user-A", draft=True)
    before = db.get_pet("keeppet00001")
    before_zip, before_sha = bytes(before["bundle_zip"]), before["bundle_sha256"]

    r = app_client.post("/api/pets/keeppet00001/keep",
                        cookies=anon_cookies())
    assert r.status_code in (200, 404), r.text

    after = db.get_pet("keeppet00001")
    assert bytes(after["bundle_zip"]) == before_zip
    assert after["bundle_sha256"] == before_sha


# ---------------------------------------------------------------------------
# 8. The rule this spec explicitly FORBIDS
# ---------------------------------------------------------------------------

def test_export_still_offers_a_factory_pet(dpp_env):
    """§6 t8 — `_export_item` must gain NO owner condition (§2.5).

    An earlier revision specified suppressing the `transfer` block for a
    `factory` pet. Under this design that would suppress the ENTIRE pull channel,
    because every pet DatsPet exports is `factory` — unsold is the normal state
    of a pet that is for sale. Pinned so it cannot be reintroduced.
    """
    db, di = dpp_env["db"], dpp_env["di"]
    make_pet(db, pet_id="factorypet01", external_user_id="user-A", draft=False)
    zip_bytes, manifest_json = pet_ownership.transfer_pet_ownership(
        db.get_pet("factorypet01")["bundle_zip"],
        category=pet_ownership.FACTORY_CATEGORY,
        name=pet_ownership.FACTORY_OWNER_NAME, at=pet_ownership.utc_now_iso())
    with db._lock:
        conn = db._connect()
        conn.execute("UPDATE pets SET bundle_zip=?, manifest_json=?, "
                     "bundle_sha256=?, size_bytes=? WHERE id=?",
                     (zip_bytes, manifest_json,
                      hashlib.sha256(zip_bytes).hexdigest(), len(zip_bytes),
                      "factorypet01"))
        conn.commit()

    item = di._export_item(db.export_pets("user-A")[0])
    assert "transfer" in item, "the owner fields must not gate the export"
    assert item["transfer"]["sha256"] == hashlib.sha256(zip_bytes).hexdigest()


# ---------------------------------------------------------------------------
# 9-10. No DatsMe identity — `factory` is already the answer
# ---------------------------------------------------------------------------

def test_an_anonymous_build_is_factory_and_reaches_no_export(app_client, dpp_env):
    """§6 t9 — an anonymous pet is an unsold pet, same as every other unsold pet.
    Not a gap: `export_pets` is exact-match on the DatsMe id, so an anon row
    reaches no user's export at all and there is nothing to suppress."""
    db = dpp_env["db"]
    import app as app_mod

    zip_bytes, _ = make_bundle_zip(breed_id="anonpet")
    job = app_mod.Job(id="anonpet00001", name="Anon Pet", created_at=1783800000.0)
    job.external_user_id = ANON_OWNER
    app_mod._finalize_pet_from_zip(job, description="anon pet",
                                   breed_id="anonpet", zip_bytes=zip_bytes)

    row = db.get_pet("anonpet00001")
    assert pet_ownership.read_pet_ownership(row["manifest_json"])[:2] == (
        pet_ownership.FACTORY_CATEGORY, pet_ownership.FACTORY_OWNER_NAME)
    assert all(p["id"] != "anonpet00001" for p in db.export_pets("user-A"))


def test_a_standalone_build_is_factory_and_needs_no_host(app_client, dpp_env):
    """§6 t10 — the standalone posture. DatsPet's stamp requires no DatsMe
    identity, no host call and no secret, which is precisely why Phase 1 ships
    with no host work at all."""
    db = dpp_env["db"]
    import app as app_mod

    zip_bytes, _ = make_bundle_zip(breed_id="alonepet")
    job = app_mod.Job(id="alonepet0001", name="Alone Pet", created_at=1783800000.0)
    job.external_user_id = None
    app_mod._finalize_pet_from_zip(job, description="alone pet",
                                   breed_id="alonepet", zip_bytes=zip_bytes)

    row = db.get_pet("alonepet0001")
    assert pet_ownership.read_pet_ownership(row["manifest_json"])[:2] == (
        pet_ownership.FACTORY_CATEGORY, pet_ownership.FACTORY_OWNER_NAME)
    assert row["external_user_id"] is None
    assert row["bundle_sha256"] == hashlib.sha256(row["bundle_zip"]).hexdigest()
