"""Unit pins for the pool-backend wiring — the Finding-1 regression class.

These keep proven, after launch, the exact behaviors the spec revolves around
(§7 step 1, R5-6/R5-1). They mock the pool client and the handler's make_pet_zip,
so they need no network and no GPU:

  (a) with a reference image present, run_pet_job's pool submit carries
      reference_image_b64 + remix_strength + display_name — the params whose
      silent loss makes a text-only pet (Finding 1).
  (b) the v2 pet_factory handler decodes reference_image_b64 to a path and
      forwards it plus remix_strength + display_name to make_pet_zip.
  (c) the pool_client adapter maps dead→error (Finding 7) and hands the progress
      callback a FRACTION 0..1, not the pool's pct 0..100 (R5-1).
"""
import base64
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


def _fake_bundle(breed_id="a_red_panda", display_name="A Red Panda") -> bytes:
    """A minimal DatsMe-shaped bundle: sprite + manifest + package, the members
    run_pet_job unpacks. package.json is where breed_id/display_name are read."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(f"{breed_id}_sprite.png", b"\x89PNG\r\n\x1a\nDATA")
        z.writestr("manifest.json", json.dumps({"animations": {}}))
        z.writestr("package.json", json.dumps(
            {"breed_id": breed_id, "display_name": display_name}))
    return buf.getvalue()


@pytest.fixture()
def pool_app(tmp_path, monkeypatch):
    """A fresh app imported in POOL mode against a throwaway DB. pet_factory is
    NOT blocked here (the local box has it) — the point is that the pool branch
    never calls it; a separate import-isolation check covers §A.4."""
    out_dir = tmp_path / "out"; out_dir.mkdir()
    monkeypatch.setenv("PETMAKER_OUTPUT_DIR", str(out_dir))
    monkeypatch.setenv("PETMAKER_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("DATSME_HMAC_SECRET", "test-secret")
    monkeypatch.setenv("PET_GEN_BACKEND", "pool")

    import db as db_mod
    importlib.reload(db_mod)
    db_mod._conn = None
    db_mod.DB_PATH = tmp_path / "t.db"
    db_mod.OUTPUT_DIR = out_dir
    db_mod.init_db()

    import pool_client
    importlib.reload(pool_client)
    import app as app_mod
    importlib.reload(app_mod)
    return app_mod


# (a) run_pet_job's pool submit carries the reference image + strength + name -----
def test_pool_submit_carries_reference_image_and_params(pool_app, tmp_path, monkeypatch):
    captured = {}

    # Mock at the submit/drive seam (the app records the pool job id between
    # the two for Opt-1 reattach) — mocking run_to_result would let a REAL
    # submit through to the live pool.
    def fake_submit(task, params, *, labels=None):
        captured["task"] = task
        captured["params"] = params
        captured["labels"] = labels
        return "pool-jid-test1"

    def fake_drive(pool_job_id, **kw):
        # drive a couple of progress beats to exercise the callback plumbing
        cb = kw.get("on_progress")
        if cb:
            cb("working", 0.5)
        return _fake_bundle()

    monkeypatch.setattr(pool_app.pool_client, "submit", fake_submit)
    monkeypatch.setattr(pool_app.pool_client, "drive_to_result", fake_drive)

    ref = tmp_path / "ref.png"
    from PIL import Image
    Image.new("RGB", (32, 32), (200, 40, 40)).save(ref)

    job = pool_app.Job(id="job000000001", name="A Red Panda",
                       pool_labels={"user": "u-42", "device": "desktop"})
    pool_app.run_pet_job(
        job, description="red panda", reference_image=ref,
        remix_strength=0.85, display_name="A Red Panda")

    assert job.status == "done", job.error
    assert captured["task"] == "pet_factory"
    # The attribution labels captured on the Job travel through to the submit body.
    assert captured["labels"] == {"user": "u-42", "device": "desktop"}
    p = captured["params"]
    assert p["animal"] == "red panda"
    assert p["display_name"] == "A Red Panda"
    assert p["remix_strength"] == 0.85
    assert "reference_image_b64" in p and p["reference_image_b64"], "reference image dropped!"
    # the b64 decodes to a real PNG (round-trips through PIL)
    raw = base64.b64decode(p["reference_image_b64"])
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"
    # progress was stored as a fraction, and finished at 1.0
    assert job.progress == 1.0


def test_pool_submit_omits_reference_when_none(pool_app, tmp_path, monkeypatch):
    captured = {}
    monkeypatch.setattr(pool_app.pool_client, "submit",
                        lambda task, params, *, labels=None: (captured.update(params=params, labels=labels) or "pool-jid-test2"))
    monkeypatch.setattr(pool_app.pool_client, "drive_to_result",
                        lambda pool_job_id, **kw: _fake_bundle())

    job = pool_app.Job(id="job000000002", name="turtle")
    pool_app.run_pet_job(job, description="a green turtle", reference_image=None)

    assert job.status == "done", job.error
    assert "reference_image_b64" not in captured["params"]
    assert "remix_strength" not in captured["params"]  # None → omitted
    assert captured["params"]["animal"] == "a green turtle"
    # A Job with no attribution labels submits labels=None (additive/optional) —
    # the submit body carries no `labels` key, exactly as before this feature.
    assert captured["labels"] is None


# (b) the v2 handler decodes b64 and forwards to make_pet_zip --------------------
def test_v2_handler_decodes_b64_and_forwards(monkeypatch, tmp_path):
    import importlib.util
    hpath = os.path.join(REPO, "pool_handler", "pet_factory_handler.py")
    spec = importlib.util.spec_from_file_location("pet_factory_handler", hpath)
    handler = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(handler)

    # Stub pet_factory.make_pet_zip so no GPU/ComfyUI is needed.
    calls = {}
    import types
    fake_pf = types.ModuleType("pet_factory")

    def fake_make_pet_zip(animal, on_progress=None, breed_id=None,
                          reference_image=None, remix_strength=None, display_name=None,
                          poses=None, motion_profile=None):
        calls.update(animal=animal, reference_image=reference_image,
                     remix_strength=remix_strength, display_name=display_name,
                     poses=poses, motion_profile=motion_profile)
        if on_progress:
            on_progress("done", 1.0)
        return (breed_id or "a_red_panda", _fake_bundle())
    fake_pf.make_pet_zip = fake_make_pet_zip
    monkeypatch.setitem(sys.modules, "pet_factory", fake_pf)

    # A tiny ctx that records progress + the result path.
    class Ctx:
        def __init__(self, d): self.result_dir = str(d); self.result = None; self.beats = []
        def progress(self, pct, msg=""): self.beats.append((pct, msg))
        def result_file(self, path): self.result = path

    ctx = Ctx(tmp_path)
    img_b64 = base64.b64encode(b"\x89PNG\r\n\x1a\nIMG").decode()
    # v3: also carry poses + motion_profile and assert they forward through.
    handler.run({"animal": "red panda", "reference_image_b64": img_b64,
                 "remix_strength": 0.9, "display_name": "A Red Panda",
                 "poses": {"walk": True, "run": True}, "motion_profile": "corgi"}, ctx)

    assert calls["animal"] == "red panda"
    assert calls["remix_strength"] == 0.9
    assert calls["display_name"] == "A Red Panda"
    assert calls["poses"] == {"walk": True, "run": True}   # v3 pose package forwarded
    assert calls["motion_profile"] == "corgi"              # v3 pinned key forwarded
    # the handler wrote the decoded bytes to a real path inside result_dir and
    # forwarded THAT path (not the b64) to make_pet_zip
    assert calls["reference_image"] is not None
    assert calls["reference_image"].startswith(str(tmp_path))
    with open(calls["reference_image"], "rb") as f:
        assert f.read() == b"\x89PNG\r\n\x1a\nIMG"
    assert ctx.result is not None


def test_v2_handler_still_accepts_v1_shaped_params(monkeypatch, tmp_path):
    """A plain {animal} submit (v1 shape) must still work — the new fields are
    optional, which is what keeps the fleet cutover safe (§B.1)."""
    import importlib.util, types
    hpath = os.path.join(REPO, "pool_handler", "pet_factory_handler.py")
    spec = importlib.util.spec_from_file_location("pet_factory_handler2", hpath)
    handler = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(handler)

    fake_pf = types.ModuleType("pet_factory")
    seen = {}
    fake_pf.make_pet_zip = lambda animal, on_progress=None, breed_id=None, **kw: (
        seen.update(kw) or ("a_penguin", _fake_bundle("a_penguin", "A Penguin")))
    monkeypatch.setitem(sys.modules, "pet_factory", fake_pf)

    class Ctx:
        def __init__(self, d): self.result_dir = str(d); self.result = None
        def progress(self, *a, **k): pass
        def result_file(self, p): self.result = p

    ctx = Ctx(tmp_path)
    handler.run({"animal": "penguin"}, ctx)   # no b64, no strength, no name
    assert ctx.result is not None
    assert seen.get("reference_image") is None


# (c) the adapter maps dead→error and pct→fraction ------------------------------
def test_adapter_maps_dead_to_error(monkeypatch):
    import pool_client
    importlib.reload(pool_client)

    class Resp:
        def __init__(self, obj): self._b = json.dumps(obj).encode()
        def read(self): return self._b
    monkeypatch.setattr(pool_client, "_req",
                        lambda m, p, **k: Resp({"status": "dead", "pct": 40, "msg": "node died"}))

    s = pool_client.poll("j1")
    assert s["status"] == "error"          # dead → error (Finding 7)
    assert s["error"]                       # a reason is filled in


def test_adapter_hands_fraction_not_pct(monkeypatch):
    """run_to_result must feed on_progress a FRACTION 0..1 (pct÷100), or the UI
    bar pins at 100× (R5-1)."""
    import pool_client
    importlib.reload(pool_client)

    seq = iter([
        {"status": "running", "pct": 50.0, "msg": "half"},
        {"status": "done", "pct": 100.0, "msg": "done"},
    ])

    class Resp:
        def __init__(self, obj): self._b = json.dumps(obj).encode()
        def read(self): return self._b

    monkeypatch.setattr(pool_client, "submit", lambda task, params, *, labels=None: "jid")
    monkeypatch.setattr(pool_client, "poll", lambda jid: next(seq))
    monkeypatch.setattr(pool_client, "result_bytes", lambda jid: b"RESULT")
    monkeypatch.setattr(pool_client.time, "sleep", lambda *_: None)

    fractions = []
    out = pool_client.run_to_result(
        "pet_factory", {"animal": "x"},
        on_progress=lambda msg, frac: fractions.append(frac))

    assert out == b"RESULT"
    # Every beat is a 0..1 fraction (pct÷100), never the raw 0..100 pct — a pct of
    # 50 would arrive as 0.5, not 50. If this fed pct straight through, the UI bar
    # (which expects 0..1) would pin at 100× (R5-1).
    assert fractions == [0.5, 1.0], f"expected 0..1 fractions, got {fractions}"
    assert all(0.0 <= f <= 1.0 for f in fractions)


def test_adapter_beats_on_pct_change_with_same_msg(monkeypatch):
    """A handler may hold one message while its pct climbs; gating beats on the
    message alone would freeze the UI bar. Also: empty (still-queued) messages
    must not blank the caller's 'Waiting…' text."""
    import pool_client
    importlib.reload(pool_client)

    seq = iter([
        {"status": "queued", "pct": 0.0, "msg": ""},           # no beat: empty msg
        {"status": "running", "pct": 30.0, "msg": "rendering"},
        {"status": "running", "pct": 60.0, "msg": "rendering"},  # same msg, new pct
        {"status": "done", "pct": 100.0, "msg": "done"},
    ])
    monkeypatch.setattr(pool_client, "submit", lambda task, params, *, labels=None: "jid")
    monkeypatch.setattr(pool_client, "poll", lambda jid: next(seq))
    monkeypatch.setattr(pool_client, "result_bytes", lambda jid: b"RESULT")
    monkeypatch.setattr(pool_client.time, "sleep", lambda *_: None)

    beats = []
    pool_client.run_to_result("pet_factory", {"animal": "x"},
                              on_progress=lambda msg, frac: beats.append((msg, frac)))
    assert beats == [("rendering", 0.3), ("rendering", 0.6), ("done", 1.0)]


# (d) §A.4 import isolation: pool mode must never import pet_factory -------------
def test_pool_mode_never_imports_the_ml_factory(tmp_path, monkeypatch):
    """Importing the app with PET_GEN_BACKEND=pool must succeed WITHOUT touching
    the ML factory module — the property Part C's GPU-less 'no ML deps' venv gate
    rests on (§A.4). `pet_factory.factory` (numpy/PIL/rembg/ComfyUI) is poisoned so
    any import of it fails loudly.

    Note (SPEC_MOTION_PROFILES §5.1): the app DOES import `pet_factory.motion_profiles`
    at module top — that subpackage is pure JSON/data with no ML deps, and the
    lazy `pet_factory/__init__` (PEP 562) makes importing it NOT pull in factory.
    So the poison targets `pet_factory.factory` specifically, not the whole package."""
    out_dir = tmp_path / "out"; out_dir.mkdir()
    monkeypatch.setenv("PETMAKER_OUTPUT_DIR", str(out_dir))
    monkeypatch.setenv("PETMAKER_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("PET_GEN_BACKEND", "pool")

    import db as db_mod
    importlib.reload(db_mod)
    db_mod._conn = None
    db_mod.DB_PATH = tmp_path / "t.db"
    db_mod.OUTPUT_DIR = out_dir
    db_mod.init_db()

    monkeypatch.delitem(sys.modules, "pet_factory.factory", raising=False)

    class _Poison:
        def find_spec(self, name, path=None, target=None):
            if name == "pet_factory.factory":
                raise AssertionError("pool mode imported the ML factory (§A.4 violation)")

    monkeypatch.setattr(sys, "meta_path", [_Poison()] + sys.meta_path)

    import app as app_mod
    importlib.reload(app_mod)   # raises if anything at module top imports pet_factory.factory
    # motion_profiles is allowed and expected; the ML factory must be absent.
    assert "pet_factory.factory" not in sys.modules


# Parity pins for the review fixes (transparent references + composed prompts) ---
def test_encode_reference_image_preserves_alpha(pool_app, tmp_path):
    """A transparent reference (a sprite-sheet crop) must stay transparent in
    transport: convert('RGB') would land it on BLACK, while the worker's
    _prep_reference_image flattens alpha onto WHITE exactly like the local
    path. Alpha must survive the b64 round-trip so both backends see the
    identical reference (review Bug 1)."""
    from PIL import Image
    src = tmp_path / "src.png"
    Image.new("RGBA", (64, 64), (255, 0, 0, 0)).save(src)   # fully transparent
    b64 = pool_app._encode_reference_image(src)
    out = Image.open(io.BytesIO(base64.b64decode(b64)))
    assert out.mode == "RGBA"
    assert out.getpixel((0, 0))[3] == 0, "alpha channel lost in transport"


def test_handler_schemas_admit_composed_design_prompts():
    """The web tier submits the COMPOSED design string as `animal` / `description`.
    The schemas must not reject what the local backend accepts — make_pet_zip's
    own [:60] cut stays the single truncation authority, so pool and local
    truncate identically (review Bug 2).

    The worst case is COMPUTED from the live design_axes vocabulary
    (SPEC_PET_DESIGN_AXES §2) plus /api/preview's caps, so a longer fragment
    added to an axis file fails HERE, at build time — not as a pool-side 422
    the user sees as "the workshop couldn't draw that". Only ONE surface axis
    can ever apply to a single design (filter_picks), so the surface term is a
    max, not a sum."""
    import importlib.util

    from pet_factory import design_axes as da

    def load(fname, modname):
        spec = importlib.util.spec_from_file_location(
            modname, os.path.join(REPO, "pool_handler", fname))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    axes = da._load()["axes"].values()

    def longest_fragment(axis):
        return max(len(o.get("prompt_fragment", "")) for o in axis["options"])

    prefix_worst = sum(longest_fragment(a) + 1 for a in axes
                       if a["kind"] == "universal" and a["position"] == "prefix")
    suffix_worst = sum(2 + longest_fragment(a) for a in axes
                       if a["kind"] == "universal" and a["position"] == "suffix")
    surface_worst = max((longest_fragment(a) for a in axes if a["kind"] == "surface"),
                        default=0)
    worst = (prefix_worst                        # prefix axes, one space each
             + len("vivid ") + 20 + 1 + 60      # colour lead + species (caps)
             + (2 + surface_worst) + suffix_worst   # ", " + suffix fragments
             + len(" wearing an ") + 30         # 3 accessories at the 30 cap
             + 2 * (len(", an ") + 30)
             + 2 + 120                          # ", " + free text at its cap
             + len(", recolored entirely ") + 20)

    pf = load("pet_factory_handler.py", "pfh_schema_check")
    pv = load("pet_preview_handler.py", "pvh_schema_check")
    assert pf.METADATA["params_schema"]["properties"]["animal"]["maxLength"] >= worst
    assert pv.METADATA["params_schema"]["properties"]["description"]["maxLength"] >= worst


def _load_pool_handler(fname, modname):
    """Exec a handler straight off disk. The pool never imports app code — these files
    only ever run inside a worker's subprocess — so a metadata test loads them the same
    way `pool-install-handler` will."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        modname, os.path.join(REPO, "pool_handler", fname))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_pet_preview_handler_is_v2_with_reference_optional():
    """SPEC_PET_DESIGNER_FLOW §7.5: v2 makes reference_image_b64 optional so the ONE
    task serves both of the flow's stills — img2img redraw (step 3, "see my design")
    and txt2img archetype (step 1's long-tail cache miss, "what does a blue jay look
    like"). These two fields are exactly what the fleet gate (§10.1) probes for."""
    pv = _load_pool_handler("pet_preview_handler.py", "pvh_v2")
    assert pv.METADATA["version"] == "2"
    assert pv.METADATA["params_schema"]["required"] == []
    assert "reference_image_b64" in pv.METADATA["params_schema"]["properties"]


def test_pet_preview_v2_accepts_both_v1_shaped_and_reference_free_params():
    """The fleet gate's two probes (§10.1), pinned as a unit test.

    v2 ⊇ v1 is what makes ROLLBACK safe: a b64-carrying submit must still validate, so
    reverting a node to v1 can never strand in-flight traffic. The no-b64 submit is the
    new shape — it 422s on a v1 node, which is why both nodes must be v2 before the
    long-tail branch ships (the one place this cutover is NOT self-healing)."""
    import jsonschema

    pv = _load_pool_handler("pet_preview_handler.py", "pvh_v2_validate")
    schema = pv.METADATA["params_schema"]

    jsonschema.validate(                       # v1-shaped — must still pass
        {"reference_image_b64": "YWJj", "description": "purple corgi", "strength": 0.85},
        schema)
    jsonschema.validate({"description": "blue jay"}, schema)   # v2-only — the archetype


def test_pet_preview_v2_leaves_the_gpu_profile_and_watchdog_alone():
    """§7.5: txt2img is the same Z-Image model at the same resolution, and the 180 s
    already exists to cover a cold model load. A version bump that quietly widened
    `needs` would change which nodes can claim a preview; one that widened the watchdog
    would let a hung preview hold a GPU slot for 15 minutes instead of 3."""
    pv = _load_pool_handler("pet_preview_handler.py", "pvh_v2_profile")
    assert pv.METADATA["needs"] == {"gpu": 1, "vram_gb": 20, "gpu_backend": "cuda",
                                    "cpu": 2, "ram_gb": 8}
    assert pv.METADATA["timeout_s"] == 180
    assert pv.METADATA["preemptible"] == "abort"
    assert pv.METADATA["result_kind"] == "bytes"


# ---- Phase 4 — consumer heartbeat + user Stop (§C / §D / §11) ------------------------

def test_pool_client_cancel_and_keepalive_hit_the_right_endpoints(monkeypatch):
    import pool_client
    calls = []
    monkeypatch.setattr(pool_client, "_req",
                        lambda method, path, **kw: calls.append((method, path, kw.get("body"))))
    pool_client.cancel("abc123")
    pool_client.keepalive("abc123")
    assert calls[0] == ("POST", "/api/jobs/abc123/cancel", {"reason": "user_stopped"})
    assert calls[1] == ("POST", "/api/jobs/abc123/keepalive", None)


def test_drive_to_result_raises_pool_canceled_and_ticks(monkeypatch):
    import pool_client
    ticks = []
    monkeypatch.setattr(pool_client, "poll",
                        lambda jid: {"status": "canceled", "pct": 50.0, "msg": "Stopping…", "error": None})
    with pytest.raises(pool_client.PoolCanceled):
        pool_client.drive_to_result("abc123", on_tick=lambda: ticks.append(1), poll_interval=0)
    assert ticks, "on_tick must run each poll iteration (the keepalive / abandonment hook)"


def test_run_pet_job_maps_pool_canceled_to_canceled(pool_app, monkeypatch):
    monkeypatch.setattr(pool_app.pool_client, "submit", lambda *a, **k: "pool-jid-cancel")

    def fake_drive(pool_job_id, **kw):
        raise pool_app.pool_client.PoolCanceled("the build was stopped")

    monkeypatch.setattr(pool_app.pool_client, "drive_to_result", fake_drive)
    job = pool_app.Job(id="jobcancel0001", name="X")
    pool_app.run_pet_job(job, description="corgi", reference_image=None)
    assert job.status == "canceled"          # a stop is a clean terminal state, NOT "error"
    assert job.message == "Stopped."


def test_stop_endpoint_cancels_owned_job(pool_app, monkeypatch):
    from fastapi.testclient import TestClient
    captured = {}
    monkeypatch.setattr(pool_app.pool_client, "cancel",
                        lambda jid, reason="user_stopped": captured.update(jid=jid, reason=reason))
    monkeypatch.setattr(pool_app.datsme_integration, "resolve_launch_identity", lambda req: None)
    job = pool_app.Job(id="jobstop000001", name="X")
    job.pool_job_id = "pool-jid-stop"
    job.status = "running"
    with pool_app.JOBS_LOCK:
        pool_app.JOBS[job.id] = job
    r = TestClient(pool_app.app).post(f"/api/job/{job.id}/stop")
    assert r.status_code == 200 and r.json()["status"] == "canceled"
    assert captured == {"jid": "pool-jid-stop", "reason": "user_stopped"}
    assert job.status == "canceled"


def test_stop_endpoint_is_owner_scoped(pool_app, monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setattr(pool_app.datsme_integration, "resolve_launch_identity", lambda req: "user-Y")
    job = pool_app.Job(id="jobstop000002", name="X", external_user_id="user-X")
    job.pool_job_id = "p"
    job.status = "running"
    with pool_app.JOBS_LOCK:
        pool_app.JOBS[job.id] = job
    r = TestClient(pool_app.app).post(f"/api/job/{job.id}/stop")
    assert r.status_code == 403
