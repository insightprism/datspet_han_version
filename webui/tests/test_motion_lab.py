"""API tests for the Motion Lab (SPEC_MOTION_LAB), async job model + endpoint dispatch.

No GPU/ComfyUI: one fake endpoint, `_healthy` forced True, and `_submit_and_wait`
writes a placeholder output, so a job completes near-instantly and the
start → poll(/job) → /asset chain runs. The admin gate is overridden.
"""
import io
import json
import time
from pathlib import Path

import pytest


class _FakePF:
    def _base_prompt(self, animal, pose="standing"):
        return f"cute cartoon {animal}, {pose}"

    def _static_image_wf(self, prompt, seed):
        return {"kind": "still", "prompt": prompt, "seed": seed}

    def _remix_prompt(self, animal, pose="standing"):
        return f"cute cartoon {animal}, exactly {animal}, {pose}"

    def _img2img_wf(self, prompt, image_path, seed, denoise=0.6):
        return {"kind": "img2img", "prompt": prompt, "src": image_path,
                "seed": seed, "denoise": denoise}

    def _loop_wf(self, prompt, path, seed):
        return {"kind": "loop", "prompt": prompt, "src": path, "seed": seed}


@pytest.fixture()
def lab_client(tmp_path, monkeypatch):
    import importlib

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import motion_lab

    importlib.reload(motion_lab)
    monkeypatch.setattr(motion_lab, "_pf", lambda: _FakePF())
    ep = {"url": "http://fake", "out": tmp_path, "label": "GPU 0"}
    monkeypatch.setattr(motion_lab, "_endpoints", lambda: [ep])
    monkeypatch.setattr(motion_lab, "_active_set", lambda: {0})
    monkeypatch.setattr(motion_lab, "_healthy", lambda url: True)

    def fake_submit(e, wf, jid, timeout=300):
        (Path(e["out"]) / "raw_output").write_bytes(b"\x89PNG\r\n\x1a\n fake")
        return "raw_output"
    monkeypatch.setattr(motion_lab, "_submit_and_wait", fake_submit)

    app = FastAPI()
    app.include_router(motion_lab.router)
    app.dependency_overrides[motion_lab.datsme_integration.require_admin_launch] = lambda: None
    return TestClient(app)


def _wait_done(client, job_id, tries=100):
    for _ in range(tries):
        j = client.get(f"/api/admin/motion-lab/job/{job_id}").json()
        if j["state"] != "running":
            return j
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} never finished")


def test_still_job_completes_and_is_served(lab_client):
    for clause in ("", "wings spread wide open"):
        jid = lab_client.post("/api/admin/motion-lab/still", json={"animal": "robin", "clause": clause}).json()["job_id"]
        j = _wait_done(lab_client, jid)
        assert j["state"] == "done" and j["url"].endswith(".png")
        r = lab_client.get(j["url"])
        assert r.status_code == 200 and r.headers["content-type"] == "image/png"


def test_still_requires_an_animal(lab_client):
    assert lab_client.post("/api/admin/motion-lab/still", json={"animal": "  "}).status_code == 400


def test_animate_job_from_a_still(lab_client):
    still = _wait_done(lab_client, lab_client.post(
        "/api/admin/motion-lab/still", json={"animal": "robin", "clause": "flying"}).json()["job_id"])
    jid = lab_client.post("/api/admin/motion-lab/animate", json={
        "asset_id": still["asset_id"], "animal": "robin",
        "profile_key": "avian", "pose_name": "fly"}).json()["job_id"]
    loop = _wait_done(lab_client, jid)
    assert loop["state"] == "done" and loop["url"].endswith(".webp")
    assert lab_client.get(loop["url"]).status_code == 200


def test_animate_rejects_missing_still_and_disabled_pose(lab_client):
    r = lab_client.post("/api/admin/motion-lab/animate", json={
        "asset_id": "deadbeefdeadbeef", "animal": "robin", "profile_key": "avian", "pose_name": "fly"})
    assert r.status_code == 404
    still = _wait_done(lab_client, lab_client.post(
        "/api/admin/motion-lab/still", json={"animal": "robin", "clause": "swimming"}).json()["job_id"])
    r = lab_client.post("/api/admin/motion-lab/animate", json={
        "asset_id": still["asset_id"], "animal": "robin", "profile_key": "avian", "pose_name": "swim"})
    assert r.status_code == 400


def test_job_and_cancel_endpoints(lab_client):
    assert lab_client.get("/api/admin/motion-lab/job/nope").status_code == 404
    assert lab_client.post("/api/admin/motion-lab/cancel/nope").json() == {"canceling": True}


def test_config_lists_endpoints_and_validates(lab_client):
    body = lab_client.get("/api/admin/motion-lab/config").json()
    assert [e["label"] for e in body["endpoints"]] == ["GPU 0"]
    assert body["endpoints"][0]["healthy"] is True
    assert lab_client.put("/api/admin/motion-lab/config", json={"active": [0]}).json() == {"active": [0]}
    assert lab_client.put("/api/admin/motion-lab/config", json={"active": []}).status_code == 400


def test_asset_rejects_bad_ext_and_unknown_id(lab_client):
    assert lab_client.get("/api/admin/motion-lab/asset/abc123.gif").status_code == 404
    assert lab_client.get("/api/admin/motion-lab/asset/nonexistent99.png").status_code == 404


def test_lab_and_build_author_at_the_same_seed():
    """The Lab is a faithful preview only if the build draws pose anchors at the SAME seed
    the clause was authored at — factory._ANCHOR_SEED must equal motion_lab._DEFAULT_SEED."""
    import motion_lab
    from pet_factory import factory
    assert factory._ANCHOR_SEED == motion_lab._DEFAULT_SEED


def test_prune_lab_assets_sweeps_stale_scratch(lab_client):
    """§9: scratch stills/loops older than the TTL are swept; fresh ones are kept."""
    import os
    import motion_lab
    d = motion_lab._lab_dir()
    old, new = d / "old.png", d / "new.webp"
    old.write_bytes(b"x"); new.write_bytes(b"y")
    stale = time.time() - motion_lab._ASSET_TTL_S - 60
    os.utime(old, (stale, stale))
    motion_lab._prune_lab_assets()
    assert not old.exists(), "a scratch asset past the TTL should be swept"
    assert new.exists(), "a fresh scratch asset should be kept"


# --- upload door parity (the reference path) --------------------------------
def _png_bytes():
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), (9, 9, 9)).save(buf, "PNG")
    return buf.getvalue()


def _upload_reference(lab_client, monkeypatch, *, caption):
    """Upload a photo, with the REAL upload door's captioner stubbed at its call site —
    the Lab runs `app._caption_upload`, deliberately, so that path is exercised here."""
    import app as app_mod
    monkeypatch.setattr(app_mod, "_caption_upload", lambda *a, **k: caption)
    r = lab_client.post("/api/admin/motion-lab/reference",
                        files={"image": ("p.png", _png_bytes(), "image/png")})
    assert r.status_code == 200, r.text
    return r.json()


def test_upload_reference_reports_the_captioners_verdict(lab_client, monkeypatch):
    """The caption is DATA, not a decision: the browser fills the animal field from it.
    A triage rejection surfaces as usable=false rather than being swallowed — that
    rejection is what silently drew a dog from a photo of a person (2026-07-26)."""
    ok = _upload_reference(lab_client, monkeypatch,
                           caption={"subject": "lion", "features": "golden mane", "description": "a lion"})
    assert ok["usable"] is True and ok["subject"] == "lion" and ok["features"] == "golden mane"
    assert lab_client.get(f"/api/admin/motion-lab/asset/{ok['reference_id']}.png").status_code == 200

    rejected = _upload_reference(lab_client, monkeypatch, caption=None)
    assert rejected["usable"] is False and rejected["subject"] == ""


def test_a_reference_switches_the_template_and_only_the_base_is_img2img(lab_client, monkeypatch):
    """A reference decides IMG2IMG vs txt2img — and, for the BASE draw only, the template.

    Only the shared base is redrawn img2img: a build never img2img's a pose anchor, so
    drawing one that way here would flatter the Lab and lie about the build. The template
    half of this test now covers the base draw ALONE — an anchor's sentence no longer hangs
    off this field at all (§2.6, and test_lab_anchors_always_use_the_remix_template)."""
    ref = _upload_reference(lab_client, monkeypatch,
                            caption={"subject": "lion", "features": "", "description": ""})
    rid = ref["reference_id"]
    sent = []
    import motion_lab
    real_start = motion_lab._start
    monkeypatch.setattr(motion_lab, "_start", lambda wf, ext, pack=None: (sent.append(wf), real_start(wf, ext, pack))[1])

    base = lab_client.post("/api/admin/motion-lab/still", json={
        "animal": "lion", "clause": "standing", "seed": 42,
        "reference_id": rid, "base": True, "strength": 0.55})
    assert base.status_code == 200, base.text
    assert sent[-1]["kind"] == "img2img"
    assert sent[-1]["denoise"] == 0.55
    assert "exactly lion" in sent[-1]["prompt"]          # the REMIX template

    anchor = lab_client.post("/api/admin/motion-lab/still", json={
        "animal": "lion", "clause": "mid-stride", "seed": 42, "reference_id": rid})
    assert anchor.status_code == 200, anchor.text
    assert sent[-1]["kind"] == "still", "an anchor must stay txt2img even with a reference"
    assert "exactly lion" in sent[-1]["prompt"] and "mid-stride" in sent[-1]["prompt"]


def test_without_a_reference_the_lab_draws_from_text_as_before(lab_client, monkeypatch):
    """The from-scratch BASE draw is unchanged: no reference → the base template, txt2img.

    This mirrors step 1 (`/api/reference` → render_design_still's text branch → _base_sprite's
    txt2img branch), which is the one place production still draws that sentence. It needed
    `base: true` ADDED, not its assertion weakened (§2.6): the flag now selects the sentence,
    so a base draw that omits it IS an anchor as far as the server can tell."""
    sent = []
    import motion_lab
    real_start = motion_lab._start
    monkeypatch.setattr(motion_lab, "_start", lambda wf, ext, pack=None: (sent.append(wf), real_start(wf, ext, pack))[1])
    r = lab_client.post("/api/admin/motion-lab/still",
                        json={"animal": "lion", "clause": "", "seed": 42, "base": True})
    assert r.status_code == 200
    assert sent[-1]["kind"] == "still" and "exactly" not in sent[-1]["prompt"]


def test_lab_anchors_always_use_the_remix_template(lab_client, monkeypatch):
    """§2.6 — every app build draws its pose anchors from the REMIX sentence.

    `/api/generate` requires a reference_id, so `reference_image` is never None in the web
    tier and `anchor_prompt = _remix_prompt` on every pet the app has ever built; the Lab
    used to fall back to `_base_prompt` whenever no reference was loaded — a paler, less
    saturated animal than production has ever drawn, biased toward the very matte defect
    the Lab gets pointed at.

    THE ASYMMETRY IS THE ASSERTION. A test that only exercised the reference case passes
    on the old code and proves nothing, which is how this survived two revisions of the
    spec: an anchor with NO reference must carry `exactly {animal}`, while a base with no
    reference must still carry the base template."""
    sent = []
    import motion_lab
    real_start = motion_lab._start
    monkeypatch.setattr(motion_lab, "_start", lambda wf, ext, pack=None: (sent.append(wf), real_start(wf, ext, pack))[1])

    anchor = lab_client.post("/api/admin/motion-lab/still", json={
        "animal": "lion", "clause": "mid-stride", "seed": 42})
    assert anchor.status_code == 200, anchor.text
    assert sent[-1]["kind"] == "still", "an anchor is txt2img with or without a reference"
    assert "exactly lion" in sent[-1]["prompt"], "an anchor draws the remix sentence, always"
    assert "mid-stride" in sent[-1]["prompt"]

    base = lab_client.post("/api/admin/motion-lab/still", json={
        "animal": "lion", "clause": "standing", "seed": 42, "base": True})
    assert base.status_code == 200, base.text
    assert "exactly" not in sent[-1]["prompt"], \
        "the from-scratch base still draws step 1's sentence — that branch was always right"


def test_an_unknown_reference_id_is_a_clean_404(lab_client):
    r = lab_client.post("/api/admin/motion-lab/still", json={
        "animal": "lion", "clause": "", "seed": 42, "reference_id": "deadbeef1234", "base": True})
    assert r.status_code == 404


# ── design parity (SPEC_MOTION_LAB_DESIGN_PARITY §5) ─────────────────────────
#
# These run against the REAL app, not the bare lab router, because the property under
# test is a relationship BETWEEN two handlers (I3). Comparing two direct compose_design
# calls would prove only that one function is deterministic — it would pass before any
# of this was written, and it could not see a retyped input cap (I2) at all.

@pytest.fixture()
def parity_client(tmp_path, monkeypatch):
    """The whole app (so /api/reference and /api/preview exist) with the Lab's ComfyUI
    stubbed. No GPU on either path: `_render_still` is stubbed for the designer and
    `_submit_and_wait` for the Lab, and both call logs are returned so a test can assert
    on what each handler PASSED rather than on pixels."""
    import importlib
    from fastapi.testclient import TestClient
    from PIL import Image

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
    import app as app_mod
    importlib.reload(app_mod)
    import motion_lab

    rendered = []

    def fake_render(description, request, owner, reference_path=None, strength=None,
                    isolate=False, base_pose="standing"):
        rendered.append({"description": description, "strength": strength})
        buf = io.BytesIO()
        Image.new("RGB", (64, 64), (10, 20, 30)).save(buf, "PNG")
        return buf.getvalue()
    monkeypatch.setattr(app_mod, "_render_still", fake_render)

    ep = {"url": "http://fake", "out": tmp_path, "label": "GPU 0"}
    monkeypatch.setattr(motion_lab, "_pf", lambda: _FakePF())
    monkeypatch.setattr(motion_lab, "_endpoints", lambda: [ep])
    monkeypatch.setattr(motion_lab, "_active_set", lambda: {0})
    monkeypatch.setattr(motion_lab, "_healthy", lambda url: True)

    def fake_submit(e, wf, jid, timeout=300):
        (Path(e["out"]) / "raw_output").write_bytes(b"\x89PNG\r\n\x1a\n fake")
        return "raw_output"
    monkeypatch.setattr(motion_lab, "_submit_and_wait", fake_submit)

    sent = []
    real_start = motion_lab._start
    monkeypatch.setattr(motion_lab, "_start",
                        lambda wf, ext, pack=None: (sent.append(wf), real_start(wf, ext, pack))[1])

    app_mod.app.dependency_overrides[motion_lab.datsme_integration.require_admin_launch] = lambda: None
    client = TestClient(app_mod.app)
    yield {"client": client, "rendered": rendered, "sent": sent, "app": app_mod}
    app_mod.app.dependency_overrides.clear()


def _lab_still_source(name="labref000001"):
    """A Lab still to redraw FROM. A Lab still's asset_id IS a usable reference_id —
    `_lab_reference` only stats `_lab_dir()/{id}.png` — which is what lets "Apply design"
    redraw the base that is on screen with no new plumbing."""
    import motion_lab
    from PIL import Image
    Image.new("RGB", (64, 64), (200, 180, 160)).save(motion_lab._lab_dir() / f"{name}.png", "PNG")
    return name


def _lab_design(parity, **overrides):
    body = {"animal": "cat", "clause": "standing", "seed": 42, "base": True,
            "reference_id": _lab_still_source(), "strength": 0.85,
            "color": "", "accessories": [], "axis_picks": {}, "extra": ""}
    body.update(overrides)
    return parity["client"].post("/api/admin/motion-lab/still", json=body)


# The picks BOTH surfaces get, deliberately over every cap (I3): a species past 60
# chars, a colour past 20, a FOURTH accessory, and free text past 120. A test that
# stayed inside the caps could not see them being retyped in the Lab.
_OVER_CAP_SPECIES = "persian cat " + "x" * 60
_OVER_CAP_COLOR = "iridescent chartreuse"          # 21 chars
_OVER_CAP_ACCESSORIES = ["crown", "cape", "bow tie", "top hat"]
_OVER_CAP_EXTRA = "y" * 130
_PICKS = {"body": "fat", "coat": "fluffy"}


def test_lab_and_designer_compose_the_same_description(parity_client):
    """THE test that makes the Lab evidence rather than decoration (§5.1).

    The same picks through the Lab's endpoint and through /api/preview must produce a
    BYTE-IDENTICAL description and the same denoise. Asserted at the two HANDLERS, with
    inputs past every cap — the only version of this test that can see the caps drift."""
    client = parity_client["client"]
    ref = client.post("/api/reference", data={"animal": "cat"}).json()

    preview = client.post("/api/preview", data={
        "reference_id": ref["reference_id"], "name": _OVER_CAP_SPECIES,
        "color": _OVER_CAP_COLOR, "accessories": ",".join(_OVER_CAP_ACCESSORIES),
        "axis_picks": json.dumps(_PICKS), "extra": _OVER_CAP_EXTRA, "strength": 0.85})
    assert preview.status_code == 200, preview.text
    designer = parity_client["rendered"][-1]

    lab = _lab_design(parity_client, animal=_OVER_CAP_SPECIES, color=_OVER_CAP_COLOR,
                      accessories=_OVER_CAP_ACCESSORIES, axis_picks=_PICKS,
                      extra=_OVER_CAP_EXTRA)
    assert lab.status_code == 200, lab.text

    assert lab.json()["description"] == designer["description"]
    assert parity_client["sent"][-1]["denoise"] == designer["strength"]
    # …and the composed string is what the Lab actually DREW with, not just what it
    # reported back: the description lands inside the remix sentence.
    assert designer["description"] in parity_client["sent"][-1]["prompt"]


def test_a_design_hands_back_the_subject_a_build_would_carry(parity_client):
    """The bug this pins (found in live testing, 2026-07-27): the Lab drew a designed
    white snow leopard and then drew TAN pose anchors, because it kept using the typed
    noun. A build does not do that.

    `/api/preview` saves its redraw with `description = display_name.lower()`, and
    `/api/generate` reads exactly that field — so a designed pet's anchors and loops are
    drawn from "white snow leopard". §0.3's table always said `ref["description"]`; it was
    READ as "the typed phrase", and the two only agree until someone designs something.

    The split is the assertion: the COLOUR rides into the subject (it is in display_name),
    while the body shape, the accessory and the recolor clause stay in the composed
    description and are spent on the redraw. A build never sees them again either."""
    r = _lab_design(parity_client, animal="snow leopard", color="white",
                    accessories=["crown"], axis_picks={"body": "fat"})
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["subject"] == "white snow leopard"
    for spent_on_the_redraw in ("chubby", "crown", "recolored entirely"):
        assert spent_on_the_redraw in body["description"]
        assert spent_on_the_redraw not in body["subject"]

    # An UNDESIGNED draw leaves the subject exactly as typed — the two agree until a
    # design exists, which is precisely why the bug was invisible.
    plain = _lab_design(parity_client, animal="snow leopard")
    assert plain.json()["subject"] == "snow leopard"


def test_the_designed_subject_matches_what_the_designer_saves(parity_client):
    """Parity for the subject, not just the description (the §5.1 test's other half):
    the reference /api/preview writes must carry the same string the Lab hands back, or
    the Lab's anchors are drawn from a pet the app would never have built."""
    client = parity_client["client"]
    ref = client.post("/api/reference", data={"animal": "snow leopard"}).json()
    preview = client.post("/api/preview", data={
        "reference_id": ref["reference_id"], "name": "snow leopard", "color": "white",
        "accessories": "crown", "axis_picks": json.dumps({"body": "fat"}), "extra": "",
        "strength": 0.85})
    assert preview.status_code == 200, preview.text

    lab = _lab_design(parity_client, animal="snow leopard", color="white",
                      accessories=["crown"], axis_picks={"body": "fat"})
    assert lab.json()["subject"] == preview.json()["description"]


def test_lab_anchors_and_loops_never_receive_the_composed_string(parity_client):
    """§0.3's failure mode, asserted. Wiring the composed description into the Lab's
    `animal` field would put a ~240-char design string on every anchor and every loop —
    stills no build has ever drawn, in exactly the investigation the Lab exists to serve.
    A more-designed Lab is not a safer Lab."""
    client = parity_client["client"]
    # An anchor drawn while a design is set carries the SHORT phrase…
    anchor = client.post("/api/admin/motion-lab/still", json={
        "animal": "cat", "clause": "mid-stride", "seed": 42})
    assert anchor.status_code == 200
    assert "recolored entirely" not in parity_client["sent"][-1]["prompt"]
    assert "exactly cat" in parity_client["sent"][-1]["prompt"]

    still = _wait_done(client, anchor.json()["job_id"])
    loop = client.post("/api/admin/motion-lab/animate", json={
        "asset_id": still["asset_id"], "animal": "cat",
        "profile_key": "quadruped", "pose_name": "walk"})
    assert loop.status_code == 200, loop.text
    assert "recolored entirely" not in parity_client["sent"][-1]["prompt"]

    # …and a request that tries to attach one is REFUSED, not quietly composed or
    # quietly dropped (I13). The rule is structural, not a convention callers keep.
    for body in ({"clause": "mid-stride"},                       # an anchor
                 {"clause": "", "base": True, "reference_id": ""}):   # a txt2img base
        r = client.post("/api/admin/motion-lab/still",
                        json={"animal": "cat", "seed": 42, "color": "purple", **body})
        assert r.status_code == 400, r.text


def test_lab_filters_picks_by_surface_before_composing(parity_client):
    """No fur fragment on a bird (§2.2). Step 2 filters by the resolved surface BEFORE
    composing; skipping that in the Lab would compose wording the designer never can."""
    from pet_factory import design_axes as da
    fur = da.prompt_fragment("coat", "fluffy")
    assert fur, "the fixture pick must actually carry wording, or this proves nothing"

    bird = _lab_design(parity_client, animal="robin", axis_picks={"coat": "fluffy"})
    assert bird.status_code == 200, bird.text
    assert fur not in bird.json()["description"]

    cat = _lab_design(parity_client, animal="cat", axis_picks={"coat": "fluffy"})
    assert fur in cat.json()["description"], "…and the same pick DOES apply to a cat"


def test_lab_applies_the_shared_strength_clamp(parity_client):
    """§2.2/I4/I11: one clamp, two surfaces, floor AND cap.

    The floor is the half a refactor deletes silently — it lived inline in both handlers
    while `effective_strength` had only a cap, so adopting "the one knower" without moving
    it in would have let a sub-floor denoise reach ComfyUI from both."""
    client = parity_client["client"]
    ref = client.post("/api/reference", data={"animal": "cat"}).json()

    for sent_strength, expected in ((0.05, 0.3), (2.0, 0.9)):
        client.post("/api/preview", data={
            "reference_id": ref["reference_id"], "name": "cat", "color": "purple",
            "accessories": "", "axis_picks": "{}", "extra": "", "strength": sent_strength})
        assert parity_client["rendered"][-1]["strength"] == expected

        assert _lab_design(parity_client, color="purple", strength=sent_strength).status_code == 200
        assert parity_client["sent"][-1]["denoise"] == expected

    # An axis that declares min_strength raises BOTH surfaces the same way.
    client.post("/api/preview", data={
        "reference_id": ref["reference_id"], "name": "cat", "color": "",
        "accessories": "", "axis_picks": json.dumps({"coat": "fluffy"}), "extra": "",
        "strength": 0.78})
    _lab_design(parity_client, axis_picks={"coat": "fluffy"}, strength=0.78)
    assert parity_client["sent"][-1]["denoise"] == parity_client["rendered"][-1]["strength"]


def test_lab_allows_an_undesigned_draw(parity_client):
    """§3.1 — the ONE gate the Lab deliberately does not inherit. /api/preview 400s a
    request that designs nothing ("designing nothing is adopting"); drawing the
    un-designed baseline to compare against is a workbench's whole job. Pinned so nobody
    "fixes" the divergence by copying the designer's gate over."""
    r = _lab_design(parity_client)
    assert r.status_code == 200, r.text
    assert r.json()["description"] == "cat", "an empty design composes to the bare species"
    assert r.json()["min_strength"] is None


# ── F4: the pack stage (SPEC_MATTE_REPAIR_ORDER §12.6) ───────────────────────
#
# The Lab covers still → loop and used to stop one stage short of the bundle, which is
# where the opaque-black hole fill lives — so it could not reproduce the defect it was
# being pointed at. These pin the stage that closes that gap.

class _FakePacker:
    """Stands in for the packer + its GPU discipline, recording the ORDER of what ran.

    Order is the assertion in test 2: `_evict_comfy_models_for_cutout` is called by
    `make_pet_zip`, NOT by `pack_datsme_bundle`, so a direct caller that forgets it runs
    birefnet's ~7 GiB working set against a card still holding ComfyUI's Wan stack."""

    def __init__(self, sheet_alpha=255, raises=None):
        self.calls = []
        self.raises = raises
        self.packed_frames = None
        self.pack_kwargs = None
        self.sheet_alpha = sheet_alpha

    def _frames_rgba(self, path):
        self.calls.append("decode")
        from PIL import Image
        # 5 frames, the last a duplicate of the first — a Wan loop's actual shape.
        return [Image.new("RGBA", (64, 64), (200, 200, 200, 255)) for _ in range(5)]

    def _evict_comfy_models_for_cutout(self):
        self.calls.append("evict")

    def _slug(self, animal):
        return "_".join(animal.lower().split())

    def pack_datsme_bundle(self, pose_frames, breed_id, display_name, **kw):
        self.calls.append("pack")
        self.packed_frames = pose_frames
        self.pack_kwargs = {"breed_id": breed_id, "display_name": display_name, **kw}
        if self.raises:
            raise self.raises
        import io as _io
        import json as _json
        import zipfile as _zip
        from PIL import Image
        sheet = Image.new("RGBA", (64, 64), (0, 0, 0, self.sheet_alpha))
        sbuf = _io.BytesIO(); sheet.save(sbuf, "PNG")
        buf = _io.BytesIO()
        with _zip.ZipFile(buf, "w") as z:
            z.writestr(f"{breed_id}_sprite.png", sbuf.getvalue())
            z.writestr("manifest.json", _json.dumps({"columns": 8, "animations": {}}))
            z.writestr("package.json", "{}")
        return buf.getvalue()

    def matte_fill_damage(self, sheet):
        self.calls.append("measure")
        from pet_factory import factory
        return factory.matte_fill_damage(sheet)   # the REAL metric — never a stand-in


def _animate(lab_client, monkeypatch, packer=None, **body):
    """Draw a still, then animate it — returning the finished job record."""
    import motion_lab
    if packer is not None:
        base = _FakePF()
        for name in ("_frames_rgba", "_evict_comfy_models_for_cutout", "_slug",
                     "pack_datsme_bundle", "matte_fill_damage"):
            setattr(base, name, getattr(packer, name))
        monkeypatch.setattr(motion_lab, "_pf", lambda: base)
    still = _wait_done(lab_client, lab_client.post(
        "/api/admin/motion-lab/still", json={"animal": "robin", "clause": "flying"}).json()["job_id"])
    payload = {"asset_id": still["asset_id"], "animal": "robin",
               "profile_key": "avian", "pose_name": "fly", **body}
    jid = lab_client.post("/api/admin/motion-lab/animate", json=payload).json()["job_id"]
    return _wait_done(lab_client, jid)


def test_animate_calls_the_shipped_packer(lab_client, monkeypatch):
    """§12.6 test 1 — the SHIPPED `pack_datsme_bundle`, never a copy. A Lab that
    re-implements the stage stops being evidence about the build."""
    packer = _FakePacker()
    job = _animate(lab_client, monkeypatch, packer)
    assert "pack" in packer.calls
    assert job["state"] == "done" and job["pack_error"] is None
    assert job["packed_url"] and job["packed_url"].endswith(".png")
    assert job["packed_zip_url"] and job["packed_zip_url"].endswith(".zip")
    # A one-pose bundle, keyed by the pose — legal input, no packer change needed.
    assert list(packer.packed_frames) == ["fly"]
    # …and it is passed what make_pet_zip passes, or the sheet PosePlayer renders would
    # differ from a real pet's (§12.2).
    assert packer.pack_kwargs["breed_id"] == "robin"
    assert packer.pack_kwargs["movement_class"]
    assert "fly" in packer.pack_kwargs["pose_meta"]


def test_pack_evicts_comfy_before_the_cutout(lab_client, monkeypatch):
    """§12.6 test 2 — ORDER, because §12.3's whole point is that a direct caller does not
    get the eviction for free: `make_pet_zip` calls it, `pack_datsme_bundle` does not."""
    packer = _FakePacker()
    _animate(lab_client, monkeypatch, packer)
    assert packer.calls.index("evict") < packer.calls.index("pack")


def test_pack_takes_the_gpu_lock_and_reports_busy(lab_client, monkeypatch):
    """§12.6 test 3 — a held lock costs you the PACKED tile and nothing else. The loop
    cost ~40 s of GPU; a collision must never be a lost animation."""
    import app as app_mod
    import motion_lab
    packer = _FakePacker()
    monkeypatch.setattr(motion_lab, "_PACK_LOCK_TIMEOUT_S", 0.05)   # don't stall the suite
    app_mod.GPU_LOCK.acquire()
    try:
        job = _animate(lab_client, monkeypatch, packer)
    finally:
        app_mod.GPU_LOCK.release()
    assert "pack" not in packer.calls, "a busy lock must not let the cutout collide"
    assert job["state"] == "done" and job["url"], "the loop survives a busy lock"
    assert job["packed_url"] is None
    assert "busy" in (job["pack_error"] or "").lower()


def test_a_pack_failure_keeps_the_loop(lab_client, monkeypatch):
    """§12.6 test 4 — the packer raising leaves state=done, the loop served, and the
    failing STAGE named in `pack_error` rather than inferred from a generic error."""
    packer = _FakePacker(raises=RuntimeError("cutout session died"))
    job = _animate(lab_client, monkeypatch, packer)
    assert job["state"] == "done"
    assert job["url"] and job["error"] is None
    assert job["packed_url"] is None
    assert "cutout session died" in job["pack_error"]
    assert "RuntimeError" in job["pack_error"]


def test_animate_packs_by_default_and_pack_false_skips_it(lab_client, monkeypatch):
    """§12.6 test 5 — the default is ON (production packs, so the Lab packs) and the
    bisection lever works. A default that silently flips is the one way this lies."""
    default = _FakePacker()
    assert _animate(lab_client, monkeypatch, default)["packed_url"], "packing is the default"

    off = _FakePacker()
    job = _animate(lab_client, monkeypatch, off, pack=False)
    assert off.calls == [], "pack: false runs no stage at all"
    assert job["state"] == "done" and job["url"], "…and still returns the loop"
    assert job["packed_url"] is None and job["pack_error"] is None


def test_pack_frames_come_from_the_factory_decoder_minus_the_duplicate(lab_client, monkeypatch):
    """§12.6 tests 6 + 7 — no second decoder, and the duplicated final loop frame is
    dropped exactly as make_pet_zip drops it. Keeping it would put an extra cell on the
    sheet and shift every later frame index, so a Lab frame number and a probe frame
    number would refer to different pictures."""
    packer = _FakePacker()
    _animate(lab_client, monkeypatch, packer)
    assert packer.calls[0] == "decode", "frames come from pf._frames_rgba, not a local decoder"
    assert len(packer.packed_frames["fly"]) == 4, "5 decoded frames pack as 4 cells"


def test_the_lab_metrics_and_the_probe_share_one_function(lab_client, monkeypatch):
    """§12.6 test 8 — one knower. The Lab's numbers and the probe's come from
    `factory.matte_fill_damage`; a Lab number that can disagree with a probe number is
    worse than no number (the effective_strength precedent)."""
    import importlib.util
    from pet_factory import factory

    spec = importlib.util.spec_from_file_location(
        "probe_matte_fill", Path(__file__).resolve().parents[2] / "scripts" / "probe_matte_fill.py")
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    assert probe.factory.matte_fill_damage is factory.matte_fill_damage

    # …and the Lab reports what that function returns, on the sheet it actually packed.
    packer = _FakePacker(sheet_alpha=255)          # an all-opaque BLACK sheet: maximal damage
    job = _animate(lab_client, monkeypatch, packer)
    assert "measure" in packer.calls
    assert job["metrics"]["hard_zero_px"] == 64 * 64
    assert "hard-zero" in job["metrics"]["line"]


def test_the_lab_serves_its_bundle_so_the_probe_can_read_it(lab_client, monkeypatch):
    """§12.2 — the .zip is written and `/asset` serves it, so
    `scripts/probe_matte_fill.py` runs on the Lab's own output unchanged. The asset
    allowlist was ("png", "webp"), which would 404 the artifact the probe reads."""
    job = _animate(lab_client, monkeypatch, _FakePacker())
    r = lab_client.get(job["packed_zip_url"])
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    import io as _io
    import zipfile as _zip
    with _zip.ZipFile(_io.BytesIO(r.content)) as z:
        assert any(n.endswith("_sprite.png") for n in z.namelist())
        assert "manifest.json" in z.namelist()


def test_motion_lab_never_imports_the_ml_factory_at_module_top(monkeypatch):
    """The GPU-less posture (§3.4), mirroring test_pool_mode_never_imports_the_ml_factory.
    The Lab is local-backend-only, but it is IMPORTED wherever app.py is read, and the
    prod deploy gate is literally "`import numpy` must fail". The `_pf()` lazy accessor
    stays the only route to the factory — including from the design compose path, which
    reaches app.py and design_calibration but never the engine."""
    import importlib
    import sys
    monkeypatch.delitem(sys.modules, "pet_factory.factory", raising=False)

    class _Poison:
        def find_spec(self, name, path=None, target=None):
            if name == "pet_factory.factory":
                raise AssertionError("motion_lab imported the ML factory at module top")

    monkeypatch.setattr(sys, "meta_path", [_Poison()] + sys.meta_path)
    import motion_lab
    importlib.reload(motion_lab)
    assert "pet_factory.factory" not in sys.modules
