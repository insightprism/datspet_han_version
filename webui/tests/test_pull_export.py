"""Phase 2d — the DPP pull channel's partner half (SPEC_DATSPET_HOUSE_ADOPT §3).

The load-bearing test here is the FIRST one. The host quotes a user from our
DECLARED `pose_count` before it fetches anything, then re-derives the count from
the bundle our `pointer_url` served and 409s `pricing_basis_mismatch` on any
disagreement (SPEC_DPP_DATA_TRANSFER_CHANNEL §0.6). So our declaration and their
derivation must be the same number for the same pet, always — a drift is not a
degraded quote, it is EVERY import failing.

They agree by construction: `_unpack_bundle` reads `manifest.json` verbatim out of
the zip and stores that exact string as the `manifest_json` column, which is what
`db.pose_count` counts. "By construction" is precisely the kind of claim that
stops being true when someone rewrites a bundle without rewriting the column, so
it is pinned here rather than trusted.

These tests build REAL zips, with the pose sets they need. conftest's `make_pet`
also builds one now (it must — `keep` stamps the owner fields inside the bundle,
SPEC_PET_OWNER_FIELD §2.4c), but always with an empty animation set; `_bundle`
below is the parameterized version this file's pricing-basis cases need.
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

from conftest import (ANON_OWNER, TEST_SECRET, anon_cookies,  # noqa: E402
                      make_bundle_zip, make_pet)


def _bundle(poses=("walk", "idle"), breed_id="phoenix_red"):
    """A real bundle with a chosen pose set. One zip builder, kept in conftest."""
    return make_bundle_zip(breed_id=breed_id,
                           animations={p: {"frames": 4} for p in poses})


def _zip_with_manifest(manifest_text):
    """A zip carrying an arbitrary manifest.json — for the edge cases where the
    manifest is not something _bundle() would ever produce."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("manifest.json", manifest_text)
    return buf.getvalue()


def _host_pose_count(zip_bytes):
    """The HOST's derivation, reproduced exactly: _pose_count_in_bundle reads
    len(manifest["animations"]) from the manifest.json inside the FETCHED zip
    (datsme_me/api/apps/dpp/pet_writeback.py:68). If this and db.pose_count ever
    disagree, every import 409s."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        manifest = json.loads(z.read("manifest.json").decode("utf-8"))
    animations = manifest.get("animations", {})
    return len(animations) if isinstance(animations, dict) else 0


@pytest.fixture()
def app_client(dpp_env):
    from fastapi.testclient import TestClient
    import app as app_mod
    importlib.reload(app_mod)
    app_mod.db = dpp_env["db"]
    app_mod.datsme_integration = dpp_env["di"]
    return TestClient(app_mod.app)


def _cookie_for(user_id):
    from datsme_partner_sdk.testkit import make_test_launch_token
    token = make_test_launch_token(
        hmac_secret=TEST_SECRET, user_id=user_id, activity_id="design_a_pet",
        partner_slug="datspet", capabilities=["pets.write"], ttl_seconds=3600)
    return json.dumps({"token": token, "user_id": user_id,
                       "activity_id": "design_a_pet", "jti": "t",
                       "capabilities": ["pets.write"]})


# ---------------------------------------------------------------------------
# The pricing basis — our declaration vs the host's derivation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("poses", [
    ("walk", "idle"),                                  # base build, 0 extra poses
    ("walk", "idle", "sit", "jump", "sleep", "eat"),   # 4 extra → priced higher
    (),                                                # empty is LEGAL and quotable
])
def test_declared_pose_count_equals_the_hosts_derivation(dpp_env, poses):
    """Our `pose_count` == len(manifest.animations) of the bundle we serve.

    A disagreement here is 409 pricing_basis_mismatch on every import of this pet.
    """
    db = dpp_env["db"]
    import app as app_mod
    zip_bytes, _ = _bundle(poses=poses)
    # Insert through the REAL unpack path — the column must come from the zip.
    sheet, manifest_json, package_json, name, breed = app_mod._unpack_bundle(
        zip_bytes, default_display_name="X")
    db.insert_pet(pet_id="posepet0001", breed_id=breed, display_name=name,
                  created_at=1783800000.0, draft=False, sheet_png=sheet,
                  manifest_json=manifest_json, package_json=package_json,
                  bundle_zip=zip_bytes, external_user_id="user-A")

    row = db.get_pet("posepet0001")
    assert db.pose_count(row["manifest_json"]) == _host_pose_count(row["bundle_zip"])
    assert db.pose_count(row["manifest_json"]) == len(poses)


def test_pose_count_is_none_not_zero_when_unknowable(dpp_env):
    """Missing is not zero. The host refuses to quote an item with no declared
    basis; a fabricated 0 would quote the BASE price for a pet that may have six
    poses, and the handler would then charge from the bytes — the exact overcharge
    the host's quote_user_pet_import fix closed."""
    db = dpp_env["db"]
    assert db.pose_count(None) is None
    assert db.pose_count("not json") is None
    assert db.pose_count('{"animations": "not a dict"}') is None
    # But a genuinely empty animations map is a real answer, not an absence.
    assert db.pose_count('{"animations": {}}') == 0


# ---------------------------------------------------------------------------
# Digests — derived, never supplied
# ---------------------------------------------------------------------------

def test_insert_derives_sha256_and_size_from_the_bytes(dpp_env):
    """The export publishes sha256 as the integrity claim the host verifies the
    fetched bytes against. It is a pure function of the blob, so insert_pet
    derives it — no caller may pass a wrong one, and no new call site can forget."""
    import hashlib
    db = dpp_env["db"]
    zip_bytes, manifest_json = _bundle()
    db.insert_pet(pet_id="shapet000001", breed_id="b", display_name="B",
                  created_at=1.0, draft=False, sheet_png=b"png",
                  manifest_json=manifest_json, package_json=None,
                  bundle_zip=zip_bytes, external_user_id="user-A")
    row = db.get_pet("shapet000001")
    assert row["bundle_sha256"] == hashlib.sha256(zip_bytes).hexdigest()
    assert row["size_bytes"] == len(zip_bytes)


def test_backfill_fills_rows_written_before_the_digest_existed(dpp_env):
    """Every row predating this change has a NULL digest, and a row we cannot hash
    cannot be offered for transfer at all. The backfill is what makes existing
    houses importable rather than silently empty."""
    db = dpp_env["db"]
    zip_bytes, manifest_json = _bundle()
    make_pet(db, pet_id="oldpet000001", external_user_id="user-A")
    # Simulate a pre-change row: digest nulled out behind insert_pet's back.
    with db._lock:
        conn = db._connect()
        conn.execute("UPDATE pets SET bundle_sha256=NULL, size_bytes=NULL, "
                     "bundle_zip=? WHERE id=?", (zip_bytes, "oldpet000001"))
        conn.commit()
    assert db.get_pet("oldpet000001")["bundle_sha256"] is None

    db._backfill_bundle_digests()

    import hashlib
    row = db.get_pet("oldpet000001")
    assert row["bundle_sha256"] == hashlib.sha256(zip_bytes).hexdigest()
    assert row["size_bytes"] == len(zip_bytes)


# ---------------------------------------------------------------------------
# The export's transfer block
# ---------------------------------------------------------------------------

def test_export_item_carries_transfer_and_pose_count(dpp_env):
    """The three fields the host's build_user_pet_import_payload reads off
    `transfer`, plus the top-level pose_count it quotes from."""
    db, di = dpp_env["db"], dpp_env["di"]
    import app as app_mod
    zip_bytes, _ = _bundle(poses=("walk", "idle", "sit"))
    sheet, manifest_json, package_json, name, breed = app_mod._unpack_bundle(
        zip_bytes, default_display_name="X")
    db.insert_pet(pet_id="exppet000001", breed_id=breed, display_name=name,
                  created_at=1.0, draft=False, sheet_png=sheet,
                  manifest_json=manifest_json, package_json=package_json,
                  bundle_zip=zip_bytes, external_user_id="user-A")

    item = di._export_item(db.export_pets("user-A")[0])

    assert item["pose_count"] == 3          # top-level: pricing is schema semantics
    t = item["transfer"]                    # nested: transport is bytes/size/hash
    assert t["pointer_url"].startswith("http://127.0.0.1:19954/api/datsme/bundle/")
    assert t["sha256"] == db.get_pet("exppet000001")["bundle_sha256"]
    assert t["size_bytes"] == len(zip_bytes)
    assert t["content_type"] == "application/zip"


def test_export_omits_transfer_when_it_cannot_be_honest(dpp_env):
    """A row we cannot count is not offered. Half a block would be listed, quoted,
    fetched, and only then fail at ingest — better absent than broken.

    Note this is the ONE place our derivation and the host's deliberately diverge:
    on an unparseable manifest the host fail-safes to 0 (it must never OVERcharge),
    while we return None. Divergence is safe precisely because None means we never
    offer the item, so the host never counts it. If we "helpfully" declared 0 here
    we would offer a pet at the base price whose real pose count is unknown.
    """
    db, di = dpp_env["db"], dpp_env["di"]
    make_pet(db, pet_id="badpet000001", external_user_id="user-A")
    with db._lock:
        conn = db._connect()
        conn.execute("UPDATE pets SET manifest_json='not json' WHERE id=?",
                     ("badpet000001",))
        conn.commit()
    item = di._export_item(db.export_pets("user-A")[0])
    assert item["pose_count"] is None
    assert "transfer" not in item


def test_a_manifest_with_no_animations_key_is_zero_not_unknown(dpp_env):
    """`{}` is 0 poses, and the host derives 0 from it too (`.get("animations", {})`
    on both sides). Agreeing on 0 is correct — returning None here would refuse to
    offer a pet the host would happily have quoted at the base price."""
    db = dpp_env["db"]
    assert db.pose_count("{}") == 0
    assert _host_pose_count(_zip_with_manifest("{}")) == 0


def test_export_is_still_byteless(dpp_env):
    """The export carries a POINTER, never bytes — the 64 KB writeback cap is why
    this channel exists at all. A regression here would put megabytes in a JSON
    body."""
    db, di = dpp_env["db"], dpp_env["di"]
    zip_bytes, manifest_json = _bundle()
    db.insert_pet(pet_id="bytepet00001", breed_id="b", display_name="B",
                  created_at=1.0, draft=False, sheet_png=b"png",
                  manifest_json=manifest_json, package_json=None,
                  bundle_zip=zip_bytes, external_user_id="user-A")
    blob = json.dumps([di._export_item(r) for r in db.export_pets("user-A")])
    assert "bundle_zip" not in blob and "sheet_png" not in blob
    assert len(blob) < 2000


# ---------------------------------------------------------------------------
# Claim — the export/house scoping asymmetry (§2)
# ---------------------------------------------------------------------------

def test_claim_makes_this_browsers_anon_pet_visible_to_the_export(app_client, dpp_env):
    """A pet designed before signing in is held under this BROWSER's anonymous
    owner id; export_pets is exact-match on the DatsMe id. Without the claim,
    adopting one links to an import page where it silently is not listed. That is
    the whole reason the claim exists (SPEC_DATSPET_FEDERATED_SESSION §4.5 c).

    Claim-at-launch normally does this; the endpoint is the backstop for a row
    written after that sweep, so it is owner-keyed too — the body's pet_ids are
    accepted and ignored."""
    db = dpp_env["db"]
    make_pet(db, pet_id="petAnon00001", external_user_id=ANON_OWNER, draft=False)

    assert db.export_pets("user-A") == []          # invisible to the host
    listed = app_client.get("/api/pets", cookies=anon_cookies()).json()
    assert [p["id"] for p in listed] == ["petAnon00001"]   # visible to that browser
    assert listed[0]["claimable"] is True

    r = app_client.post("/api/pets/claim", json={"pet_ids": ["petAnon00001"]},
                        cookies={"datsme_launch": _cookie_for("user-A"),
                                 "datspet_anon": ANON_OWNER})
    assert r.status_code == 200 and r.json()["claimed"] == 1

    assert [p["id"] for p in db.export_pets("user-A")] == ["petAnon00001"]
    row = db.get_pet("petAnon00001")
    assert row["external_user_id"] == "user-A"
    assert row["datsme_activity_id"] == "design_a_pet"   # provenance, as _bind_pending did


def test_claim_never_takes_another_browsers_anon_pet(app_client, dpp_env):
    """Keyed by THIS browser's anon id, in the WHERE (atomic). Before exact-match
    scoping, "unowned" meant anyone's anonymous pet and a signed-in user could
    claim one they had merely seen in a shared house."""
    db = dpp_env["db"]
    make_pet(db, pet_id="petOther0001", external_user_id="anon:someoneelsesbrowser000000000",
             draft=False)
    r = app_client.post("/api/pets/claim", json={"pet_ids": ["petOther0001"]},
                        cookies={"datsme_launch": _cookie_for("user-A"),
                                 "datspet_anon": ANON_OWNER})
    assert r.status_code == 200 and r.json()["claimed"] == 0
    assert db.get_pet("petOther0001")["external_user_id"] == "anon:someoneelsesbrowser000000000"


def test_claim_never_takes_another_users_pet(app_client, dpp_env):
    """A pet already bound to a DatsMe user is not anon-owned, so no sweep reaches
    it whatever cookies the caller presents."""
    db = dpp_env["db"]
    make_pet(db, pet_id="petB00000001", external_user_id="user-B", draft=False)
    r = app_client.post("/api/pets/claim", json={"pet_ids": ["petB00000001"]},
                        cookies={"datsme_launch": _cookie_for("user-A"),
                                 "datspet_anon": ANON_OWNER})
    assert r.status_code == 200 and r.json()["claimed"] == 0
    assert db.get_pet("petB00000001")["external_user_id"] == "user-B"


def test_claim_with_nothing_anonymous_is_a_noop_not_an_error(app_client, dpp_env):
    """The hand-off calls this every time, and for a user who signed in before
    designing anything there is nothing to move. That must not fail."""
    db = dpp_env["db"]
    make_pet(db, pet_id="petA00000001", external_user_id="user-A", draft=False)
    r = app_client.post("/api/pets/claim", json={"pet_ids": ["petA00000001"]},
                        cookies={"datsme_launch": _cookie_for("user-A")})
    assert r.status_code == 200 and r.json()["claimed"] == 0
    assert db.get_pet("petA00000001")["external_user_id"] == "user-A"


def test_claim_requires_a_launch(app_client, dpp_env):
    """An anonymous caller has nobody to claim TO. 401, and nothing moves."""
    db = dpp_env["db"]
    make_pet(db, pet_id="petAnon00001", external_user_id=ANON_OWNER, draft=False)
    r = app_client.post("/api/pets/claim", json={"pet_ids": ["petAnon00001"]},
                        cookies=anon_cookies())
    assert r.status_code == 401
    assert db.get_pet("petAnon00001")["external_user_id"] == ANON_OWNER


# ---------------------------------------------------------------------------
# The host's post-import ack (§3.4)
# ---------------------------------------------------------------------------

def _imported(client, user_id, body_obj, sign_with=TEST_SECRET):
    from datsme_partner_sdk import sign_host_request
    path = f"/partner/imported/{user_id}"
    body = json.dumps(body_obj, separators=(",", ":")).encode()
    headers = {"Content-Type": "application/json", "X-DatsMe-Partner": "datspet"}
    if sign_with:
        headers["X-DatsMe-Signature"] = sign_host_request(sign_with, "POST", path, body)
    return client.post(path, content=body, headers=headers)


def test_imported_ack_stamps_in_datsme(client, dpp_env):
    """A pull deletes the push's acknowledgment channel — this is how the house
    learns a pulled pet landed, and without it `in_datsme` reads false forever."""
    db = dpp_env["db"]
    make_pet(db, pet_id="pullpet00001", external_user_id="user-A", draft=False)
    assert db.get_pet("pullpet00001")["writeback_acked_at"] is None

    r = _imported(client, "user-A", {"export_type": "pets", "item_ids": ["pullpet00001"]})
    assert r.status_code == 200 and r.json()["acked"] == ["pullpet00001"]

    row = db.get_pet("pullpet00001")
    assert row["writeback_acked_at"] is not None
    # A pull has no activity. NULL is the truth; an invented id would be a lie.
    assert row["datsme_activity_id"] is None


def test_imported_ack_requires_a_host_signature(client, dpp_env):
    """This marks pets delivered — unsigned, it would let anyone mark the whole
    house adopted."""
    db = dpp_env["db"]
    make_pet(db, pet_id="pullpet00001", external_user_id="user-A", draft=False)
    r = _imported(client, "user-A", {"export_type": "pets", "item_ids": ["pullpet00001"]},
                  sign_with=None)
    assert r.status_code == 401
    assert db.get_pet("pullpet00001")["writeback_acked_at"] is None

    r = _imported(client, "user-A", {"export_type": "pets", "item_ids": ["pullpet00001"]},
                  sign_with="wrong-secret")
    assert r.status_code == 401
    assert db.get_pet("pullpet00001")["writeback_acked_at"] is None


def test_imported_ack_cannot_stamp_another_users_pet(client, dpp_env):
    """The host is trusted, but a bug there must not let one user's import stamp
    another user's pet."""
    db = dpp_env["db"]
    make_pet(db, pet_id="petB00000001", external_user_id="user-B", draft=False)
    r = _imported(client, "user-A", {"export_type": "pets", "item_ids": ["petB00000001"]})
    assert r.status_code == 200 and r.json()["acked"] == []
    assert db.get_pet("petB00000001")["writeback_acked_at"] is None


# ---------------------------------------------------------------------------
# The manifest opt-in (§5)
# ---------------------------------------------------------------------------

def test_manifest_declares_the_export_transferable(dpp_env):
    """All three keys together — the host's conformance check fails a manifest
    that declares transferable without ingest_target and max_bytes."""
    di = dpp_env["di"]
    body = di._build_manifest_body()
    # The SDK emits add_data_export(export_type=...) as "type" — the manifest's
    # wire name, not the builder's kwarg.
    export = next(e for e in body["data_exports"] if e["type"] == "pets")
    assert export["transferable"] is True
    assert export["ingest_target"] == "user.pet"
    assert export["max_bytes"] == 10 * 1024 * 1024
    # The host's registry independently decides ingestibility; this is a request,
    # not a grant. But a half-formed declaration fails its conformance check, so
    # all three must travel together.
    assert export["schema"] == "datspet_pets.v1"
