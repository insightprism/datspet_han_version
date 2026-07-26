"""API tests for the Motion Lab (SPEC_MOTION_LAB), async job model + endpoint dispatch.

No GPU/ComfyUI: one fake endpoint, `_healthy` forced True, and `_submit_and_wait`
writes a placeholder output, so a job completes near-instantly and the
start → poll(/job) → /asset chain runs. The admin gate is overridden.
"""
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
    """Mirrors factory.py:733 exactly. A reference swaps _base_prompt for _remix_prompt on
    EVERY draw, but only the shared base is redrawn img2img — a build never img2img's a pose
    anchor, so drawing one that way here would flatter the Lab and lie about the build."""
    ref = _upload_reference(lab_client, monkeypatch,
                            caption={"subject": "lion", "features": "", "description": ""})
    rid = ref["reference_id"]
    sent = []
    import motion_lab
    real_start = motion_lab._start
    monkeypatch.setattr(motion_lab, "_start", lambda wf, ext: (sent.append(wf), real_start(wf, ext))[1])

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
    """The typed-pet path is unchanged: no reference → the base template, txt2img."""
    sent = []
    import motion_lab
    real_start = motion_lab._start
    monkeypatch.setattr(motion_lab, "_start", lambda wf, ext: (sent.append(wf), real_start(wf, ext))[1])
    r = lab_client.post("/api/admin/motion-lab/still", json={"animal": "lion", "clause": "", "seed": 42})
    assert r.status_code == 200
    assert sent[-1]["kind"] == "still" and "exactly" not in sent[-1]["prompt"]


def test_an_unknown_reference_id_is_a_clean_404(lab_client):
    r = lab_client.post("/api/admin/motion-lab/still", json={
        "animal": "lion", "clause": "", "seed": 42, "reference_id": "deadbeef1234", "base": True})
    assert r.status_code == 404
