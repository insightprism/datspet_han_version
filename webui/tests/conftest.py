"""Shared fixtures for the DatsPet partner-surface tests.

Every test runs against an ISOLATED SQLite DB (a temp file) and a fresh app
instance, so tests never touch the real pet house and don't depend on ordering.
The DPP env is set to known test values before webui modules import.
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

TEST_SECRET = "test-hmac-secret-0123456789abcdef"

# Cookie attributes are module-level constants read at first import, so this must
# be set HERE — at conftest import, before any test module imports the webui —
# rather than in a fixture.
#
# Why `lax` for the whole suite: the anonymous-owner cookie
# (SPEC_DATSPET_FEDERATED_SESSION §4.5) defaults to SameSite=None; Secure, and
# TestClient speaks http://testserver, which httpx will not send a Secure cookie
# over. Any test that creates something and reads it back on a LATER request would
# silently see a DIFFERENT anonymous owner. `lax` is the documented same-origin
# override (datsme_integration.py:76-83) and is what pet_env.local.sh already sets
# for the http dev box. Production is unaffected — it is https and same-origin.
os.environ.setdefault("DATSPET_COOKIE_SAMESITE", "lax")


@pytest.fixture()
def dpp_env(tmp_path, monkeypatch):
    """Point the webui at a throwaway DB + known DPP env, then (re)import db and
    datsme_integration fresh so module-level config picks up the env."""
    db_path = tmp_path / "datspet_test.db"
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    monkeypatch.setenv("PETMAKER_OUTPUT_DIR", str(out_dir))
    monkeypatch.setenv("PETMAKER_DB_PATH", str(db_path))
    monkeypatch.setenv("DATSME_HMAC_SECRET", TEST_SECRET)
    monkeypatch.setenv("DATSME_PARTNER_SLUG", "datspet")
    monkeypatch.setenv("DATSPET_PUBLIC_URL", "http://127.0.0.1:19954")
    monkeypatch.setenv("DATSPET_FRONTEND_URL", "http://127.0.0.1:19955")
    monkeypatch.setenv("DATSME_BASE_URL", "http://127.0.0.1:19994")
    monkeypatch.setenv("DATSME_PUBLIC_URL", "http://127.0.0.1:19995")

    # Fresh module state bound to the temp DB.
    import db as db_mod
    importlib.reload(db_mod)
    db_mod._conn = None  # force a new connection to the temp path
    db_mod.DB_PATH = db_path
    db_mod.OUTPUT_DIR = out_dir
    db_mod.init_db()

    import datsme_integration as di
    importlib.reload(di)

    yield {"db": db_mod, "di": di, "secret": TEST_SECRET}


@pytest.fixture()
def client(dpp_env):
    """A TestClient over a fresh app that mounts the reloaded router + shares
    the temp DB."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(dpp_env["di"].router)
    return TestClient(app)


# A fixed per-browser anonymous owner id (SPEC_DATSPET_FEDERATED_SESSION §4.5).
# In INTEGRATED mode — which every dpp_env test runs in — there is no such thing as
# a cookieless "standalone" caller any more: a browser with no launch cookie owns
# its work under an anon id minted by the middleware. Tests pin the value rather
# than let the middleware mint a random one, so assertions stay deterministic.
ANON_OWNER = "anon:testbrowser00000000000000000a"
ANON_OWNER_2 = "anon:testbrowser00000000000000000b"


def anon_cookies(owner_id=ANON_OWNER):
    """Cookie jar for a specific anonymous browser."""
    return {"datspet_anon": owner_id}


def launch_cookie(user_id):
    """The launch cookie /launch would set for a signed-in DatsMe user — a REAL
    signed token via the SDK testkit, because resolve_launch_identity verifies
    it. Shared by the scoping tests and every signed-in-only surface (lounges)."""
    from datsme_partner_sdk.testkit import make_test_launch_token
    token = make_test_launch_token(
        hmac_secret=TEST_SECRET, user_id=user_id,
        activity_id="design_a_pet", partner_slug="datspet",
        capabilities=["pets.write"], ttl_seconds=3600)
    return json.dumps({"token": token, "user_id": user_id,
                       "activity_id": "design_a_pet", "jti": "t",
                       "capabilities": ["pets.write"]})


def launch_cookies(user_id):
    """Cookie jar for a signed-in DatsMe user."""
    return {"datsme_launch": launch_cookie(user_id)}


def make_bundle_zip(breed_id="test_breed", animations=None, **extra_manifest):
    """A REAL pet bundle .zip, shaped like the pipeline's output.

    Returns `(zip_bytes, manifest_json)` — the pair `insert_pet` wants, and the
    pair that must agree: `db.pose_count` reads the COLUMN while the host counts
    the poses in the BYTES, so a row whose two halves disagree is an import that
    409s `pricing_basis_mismatch` (SPEC_DPP_DATA_TRANSFER_CHANNEL §0.6).

    Not deterministic across calls — `zipfile.writestr` stamps each member with
    the current local time. Assert against what was STORED, never against a
    recomputed zip.
    """
    manifest = {"animations": animations if animations is not None else {},
                **extra_manifest}
    manifest_json = json.dumps(manifest)
    package = {"breed_id": breed_id,
               "display_name": breed_id.replace("_", " ").title()}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("manifest.json", manifest_json)
        z.writestr("package.json", json.dumps(package))
        z.writestr(f"{breed_id}_sprite.png", b"\x89PNG\r\n\x1a\nDATA")
    return buf.getvalue(), manifest_json


def make_pet(db_mod, pet_id="testpet00001", external_user_id=None, draft=False,
             breed_id="test_breed", display_name="Test Pet", animations=None):
    """Insert a minimal valid pet row for tests.

    The bundle is a REAL zip (SPEC_PET_OWNER_FIELD §2.4c). It used to be the
    stub `b"PK\\x03\\x04zip"`, which was fine while nothing opened it — but `keep`
    now stamps the owner fields INSIDE the bundle, so a row whose blob is not a
    zip is a row no endpoint can handle. A fixture that lies about its shape only
    postpones the failure to whichever test first exercises the real path.
    """
    zip_bytes, manifest_json = make_bundle_zip(breed_id=breed_id,
                                               animations=animations)
    db_mod.insert_pet(
        pet_id=pet_id, breed_id=breed_id, display_name=display_name,
        created_at=1783800000.0, draft=draft,
        sheet_png=b"\x89PNG\r\n\x1a\nDATA", manifest_json=manifest_json,
        package_json=None, bundle_zip=zip_bytes,
        external_user_id=external_user_id,
    )
    return pet_id
