"""Web-tier tests for the motion-profile feature (SPEC_MOTION_PROFILES §4.1/§5.1).

Covers the /api/motions menu (both lookup modes) and start_job's pose-package
parsing. Uses a fresh app instance; no GPU (the pose menu is pure data).
"""
import importlib
import json
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WEBUI = os.path.join(REPO, "webui")
for p in (WEBUI, REPO):
    if p not in sys.path:
        sys.path.insert(0, p)


@pytest.fixture()
def app_mod(tmp_path, monkeypatch):
    out_dir = tmp_path / "out"; out_dir.mkdir()
    monkeypatch.setenv("PETMAKER_OUTPUT_DIR", str(out_dir))
    monkeypatch.setenv("PETMAKER_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("DATSME_HMAC_SECRET", "test-secret")
    import db as db_mod
    importlib.reload(db_mod)
    db_mod._conn = None
    db_mod.DB_PATH = tmp_path / "t.db"
    db_mod.OUTPUT_DIR = out_dir
    db_mod.init_db()
    import app as a
    importlib.reload(a)
    return a


# --- /api/motions keyword mode ---------------------------------------------
def test_motions_keyword_returns_species_correct_menu(app_mod):
    dog = app_mod.motions(animal="golden retriever dog")
    assert dog["profile"] == "quadruped"
    assert dog["level"] == 3
    names = [p["name"] for p in dog["poses"]]
    assert "walk" in names and "idle" in names          # required present
    assert "swim" not in names                          # quadruped disables swim

    snake = app_mod.motions(animal="a green cobra")
    assert snake["profile"] == "serpentine"
    snames = [p["name"] for p in snake["poses"]]
    assert "swim" in snames                             # serpentine enables swim
    assert "jump" not in snames                         # serpentine disables jump


def test_motions_hides_triggered_poses(app_mod):
    # jump/play are triggered (§7) — authored but hidden from the launch menu.
    dog = app_mod.motions(animal="dog")
    names = [p["name"] for p in dog["poses"]]
    assert "jump" not in names and "play" not in names


def test_motions_required_flag_on_walk_idle(app_mod):
    dog = app_mod.motions(animal="dog")
    req = {p["name"]: p["required"] for p in dog["poses"]}
    assert req["walk"] is True and req["idle"] is True
    assert req.get("run") is False


def test_motions_unmatched_animal_falls_to_default(app_mod):
    r = app_mod.motions(animal="zzzz gibberish")
    assert r["profile"] == "quadruped"                  # registry default


# --- /api/motions pinned mode ----------------------------------------------
def test_motions_pinned_loads_directly(app_mod):
    r = app_mod.motions(profile="avian")
    assert r["profile"] == "avian" and r["level"] == 3


def test_motions_pinned_unknown_key_404(app_mod):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as ei:
        app_mod.motions(profile="nonesuch_profile")
    assert ei.value.status_code == 404


# --- start_job pose-package parsing (through the real form parser) ----------
# We POST via TestClient so FastAPI parses the multipart form exactly as prod
# does, then stub run_pet_job so no thread/GPU runs — capturing the kwargs the
# endpoint would have handed generation.
def _client_capturing_run(app_mod, monkeypatch):
    from fastapi.testclient import TestClient
    captured = {}

    def fake_run_pet_job(job, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(app_mod, "run_pet_job", fake_run_pet_job)

    # Thread(target=run_pet_job, ...) — run the target inline so capture happens
    # before the response returns (deterministic in the test).
    real_thread = app_mod.threading.Thread

    def inline_thread(target=None, args=(), kwargs=None, daemon=None):
        class _T:
            def start(self_):
                target(*args, **(kwargs or {}))
        return _T()

    monkeypatch.setattr(app_mod.threading, "Thread", inline_thread)
    return TestClient(app_mod.app), captured


def _reference(client, app_mod, monkeypatch, animal="a red fox"):
    """Mint a reference the way the designer does, and return its id.

    /api/generate takes ONE base field now (SPEC_PET_DESIGNER_FLOW §8): everything
    else is resolved at fill time and carried on the record. So a generate test has to
    go through step 1 first — which is the contract working, not ceremony.

    The renderer is stubbed: these tests are about pose parsing and cap clipping, and
    a GPU would not make them truer.
    """
    import io
    from PIL import Image

    def fake_render(description, request, owner, reference_path=None, strength=None):
        buf = io.BytesIO()
        Image.new("RGB", (32, 32), (7, 7, 7)).save(buf, "PNG")
        return buf.getvalue()

    monkeypatch.setattr(app_mod, "_render_still", fake_render)
    r = client.post("/api/reference", data={"animal": animal})
    assert r.status_code == 200, r.text
    return r.json()["reference_id"]


def test_start_job_parses_valid_poses_json(app_mod, monkeypatch):
    client, captured = _client_capturing_run(app_mod, monkeypatch)
    # This test targets pose-JSON PARSING + motion_profile forwarding — grant the
    # plus capability so tier clipping (tested separately) doesn't drop `run`.
    monkeypatch.setattr(app_mod.datsme_integration, "resolve_launch_capabilities",
                        lambda request: ["pet_designer_plus"])
    ref = _reference(client, app_mod, monkeypatch)
    r = client.post("/api/generate", data={
        "reference_id": ref,
        "poses": '{"walk": true, "idle": true, "run": true}',
        "motion_profile": "corgi",
    })
    assert r.status_code == 200, r.text
    assert {k for k, v in captured["poses"].items() if v} == {"walk", "idle", "run"}
    assert captured["motion_profile"] == "corgi"


def test_start_job_malformed_poses_becomes_none(app_mod, monkeypatch):
    client, captured = _client_capturing_run(app_mod, monkeypatch)
    ref = _reference(client, app_mod, monkeypatch)
    r = client.post("/api/generate", data={"reference_id": ref, "poses": "not json{{"})
    assert r.status_code == 200, r.text
    assert captured["poses"] is None                    # safe default (walk+idle)
    # None: a typed animal carries no pinned profile, so the engine keyword-resolves
    # it from the description at build time (§3.4's long-tail branch).
    assert captured["motion_profile"] is None


# --- catalog base source (SPEC_PET_DESIGNER_PLATFORM §4.3) -------------------
def test_catalog_endpoint_returns_animal_tree(app_mod):
    body = app_mod.catalog()
    keys = [a["key"] for a in body["animals"]]
    assert "cat" in keys and "dog" in keys
    dog = next(a for a in body["animals"] if a["key"] == "dog")
    # Real bases have been promoted (§4.5), so the launch gate is lifted and
    # themed_page is restored — the landing page shows the Dog World tile again.
    assert dog["themed_page"] == "dog"
    corgi = next(b for b in dog["breeds"] if b["key"] == "corgi")
    # Every breed pins a motion_profile that resolves (§4.2) and a base image URL.
    assert corgi["motion_profile"]
    assert corgi["base_image_url"] == "/api/catalog/dog/corgi/base.png"


def test_catalog_base_image_serves_and_404s(app_mod):
    from fastapi.testclient import TestClient
    client = TestClient(app_mod.app)
    ok = client.get("/api/catalog/dog/corgi/base.png")
    assert ok.status_code == 200 and ok.headers["content-type"] == "image/png"
    missing = client.get("/api/catalog/cat/nonexistent/base.png")
    assert missing.status_code == 404


def test_catalog_reference_pins_the_profile_through_to_the_build(app_mod, monkeypatch):
    # The curated path must animate at >= the fidelity free-text keyword matching would
    # find (SPEC_PET_DESIGNER_PLATFORM §4.2) — the Rev.3 guarantee. That pinning now
    # happens at FILL time and rides the record, so this asserts it survives the trip.
    #
    # This test used to post catalog_animal+catalog_breed straight at /api/generate and
    # assert remix_strength was not None. Both halves are gone: the catalog is a step-1
    # door now, and generate NEVER remixes — it animates a still the user already saw
    # and locked (§8). Asserting a remix here would pin the bug the spec removed.
    client, captured = _client_capturing_run(app_mod, monkeypatch)
    r = client.post("/api/reference", data={"catalog_animal": "dog", "catalog_breed": "corgi"})
    assert r.status_code == 200, r.text
    ref = r.json()
    assert ref["motion_profile"] == "quadruped"        # dog's pinned profile
    assert ref["generated"] is False                   # a curated file, no GPU

    r = client.post("/api/generate", data={"reference_id": ref["reference_id"]})
    assert r.status_code == 200, r.text
    assert captured["motion_profile"] == "quadruped"
    assert captured["reference_image"] is not None and captured["reference_image"].exists()
    assert captured["remix_strength"] is None          # always as-is (§8)


def test_catalog_generate_explicit_profile_overrides_pin(app_mod, monkeypatch):
    client, captured = _client_capturing_run(app_mod, monkeypatch)
    ref = client.post("/api/reference", data={
        "catalog_animal": "dog", "catalog_breed": "corgi"}).json()["reference_id"]
    r = client.post("/api/generate", data={
        "reference_id": ref, "motion_profile": "avian",
    })
    assert r.status_code == 200, r.text
    assert captured["motion_profile"] == "avian"        # caller override beats the pin


def test_generate_requires_a_reference(app_mod, monkeypatch):
    # The design guard moved to fill time — /api/preview owns "pick a colour, an
    # accessory, a body shape, or describe a change" (§4.1), and test_reference_flow
    # covers it. What generate must refuse is running with no base at all.
    #
    # 400, not 404: an empty/expired reference is "start over", never a stack trace
    # (§7.3). This used to be a catalog-shaped request with nothing to redraw toward.
    client, _ = _client_capturing_run(app_mod, monkeypatch)
    assert client.post("/api/generate", data={}).status_code == 400


def test_generate_refuses_the_deleted_legacy_contract(app_mod, monkeypatch):
    # Build step 7: the pre-reference params are GONE, not deprecated. A request in the
    # old shape must fail loudly rather than quietly build something — a silently
    # ignored `catalog_animal` would produce a pet from the wrong base.
    client, _ = _client_capturing_run(app_mod, monkeypatch)
    r = client.post("/api/generate", data={
        "catalog_animal": "dog", "catalog_breed": "corgi", "color": "blue",
        "text": "a red fox",
    })
    assert r.status_code == 400


def test_server_clips_poses_over_cap(app_mod, monkeypatch):
    # The server clips an over-cap request to the caller's tier cap, authoritative
    # (§8.6) — the UI cap is mirrored here but never trusted.
    #
    # The cap is STUBBED to 5 rather than read from the launch default, the way the
    # base-cap test below already does. This test is about the clipping MECHANISM, and
    # tying it to `default_tier`'s current number made it hostage to a config knob: when
    # plus.max_poses moved to 10 for testing, a quadruped's 6 poses all fit and there
    # was nothing left to clip — the test would have passed vacuously while proving
    # nothing. A guard that goes quiet when the config moves is not a guard.
    client, captured = _client_capturing_run(app_mod, monkeypatch)
    ref = _reference(client, app_mod, monkeypatch)
    monkeypatch.setattr(app_mod.tiers_mod, "resolve_entitlement",
                        lambda caps: {"max_poses": 5})
    r = client.post("/api/generate", data={
        "reference_id": ref,
        # 6 poses requested (walk+idle + 4 optional) — one over the cap of 5.
        "poses": '{"walk": true, "idle": true, "run": true, "sleep": true, "sit": true, "eat": true}',
    })
    assert r.status_code == 200, r.text
    enabled = {k for k, v in captured["poses"].items() if v}
    assert len(enabled) == 5, f"cap 5 must clip 6→5, got {enabled}"
    assert {"walk", "idle"} <= enabled            # required always kept


def test_server_clips_to_base_when_capability_maps_base(app_mod, monkeypatch):
    # Enforcement still bites for a base-capped caller: stub the resolved tier to
    # base (cap 2) and confirm a 5-pose request clips to walk+idle. This is the
    # posture once default_tier flips back to 'base' + a premium cap gates plus.
    client, captured = _client_capturing_run(app_mod, monkeypatch)
    ref = _reference(client, app_mod, monkeypatch)
    monkeypatch.setattr(app_mod.tiers_mod, "resolve_entitlement",
                        lambda caps: {"max_poses": 2})
    r = client.post("/api/generate", data={
        "reference_id": ref,
        "poses": '{"walk": true, "idle": true, "run": true, "sleep": true, "sit": true}',
    })
    assert r.status_code == 200, r.text
    enabled = {k for k, v in captured["poses"].items() if v}
    assert enabled == {"walk", "idle"}, f"base cap 2 should clip to walk+idle, got {enabled}"


def test_clip_helper_keeps_required_and_fills_canonical_order(app_mod):
    # Unit-level: cap 4 keeps walk+idle + the first 2 optional in canonical order.
    clipped = app_mod._clip_poses_to_cap(
        {"walk": True, "idle": True, "sit": True, "run": True, "eat": True}, 4)
    enabled = {k for k, v in clipped.items() if v}
    # canonical order is walk, idle, run, sleep, sit, eat → run + sit fill first.
    assert "walk" in enabled and "idle" in enabled
    assert len(enabled) == 4
    assert "run" in enabled and "sit" in enabled and "eat" not in enabled


def test_clip_always_ensures_required_present(app_mod):
    # Even if the request omits walk/idle, the clip guarantees them.
    clipped = app_mod._clip_poses_to_cap({"run": True}, 5)
    assert clipped["walk"] is True and clipped["idle"] is True


def test_clip_omitting_required_never_exceeds_cap(app_mod):
    # Regression: a crafted request that OMITS walk/idle must still not produce
    # more than max_poses enabled — walk+idle are force-added, so they must be
    # reserved against the cap, not stacked on top. (base cap=2 → walk+idle only.)
    clipped = app_mod._clip_poses_to_cap({"run": True, "sleep": True, "sit": True}, 2)
    enabled = {k for k, v in clipped.items() if v}
    assert enabled == {"walk", "idle"}, f"cap 2 must be walk+idle only, got {enabled}"
    # cap=3, request omits idle → walk+idle + exactly ONE optional = 3 total.
    clipped3 = app_mod._clip_poses_to_cap(
        {"walk": True, "run": True, "sleep": True, "sit": True}, 3)
    enabled3 = {k for k, v in clipped3.items() if v}
    assert len(enabled3) == 3 and {"walk", "idle"} <= enabled3


def test_plus_capability_raises_the_cap(app_mod, monkeypatch):
    # A launched user carrying the plus capability keeps up to 5 poses. Stub the
    # verified capabilities so no real JWT is needed.
    client, captured = _client_capturing_run(app_mod, monkeypatch)
    monkeypatch.setattr(app_mod.datsme_integration, "resolve_launch_capabilities",
                        lambda request: ["pet_designer_plus"])
    ref = _reference(client, app_mod, monkeypatch)
    r = client.post("/api/generate", data={
        "reference_id": ref,
        "poses": '{"walk": true, "idle": true, "run": true, "sleep": true, "sit": true}',
    })
    assert r.status_code == 200, r.text
    enabled = {k for k, v in captured["poses"].items() if v}
    assert enabled == {"walk", "idle", "run", "sleep", "sit"}, f"plus cap should keep all, got {enabled}"
