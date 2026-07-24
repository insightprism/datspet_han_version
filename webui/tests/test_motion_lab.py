"""API tests for the Motion Lab (SPEC_MOTION_LAB), async job model.

No GPU/ComfyUI: `_pf` is faked and `_submit_and_wait` writes a placeholder output,
so a job completes near-instantly and the start → poll(/job) → /asset chain runs.
The admin gate is overridden.
"""
import time

import pytest


class _FakePF:
    def __init__(self, outdir):
        self.COMFY_OUTPUT_DIR = outdir

    def _base_prompt(self, animal, pose="standing"):
        return f"cute cartoon {animal}, {pose}"

    def _static_image_wf(self, prompt, seed):
        return {"kind": "still", "prompt": prompt, "seed": seed}

    def _loop_wf(self, prompt, path, seed):
        return {"kind": "loop", "prompt": prompt, "src": path, "seed": seed}


@pytest.fixture()
def lab_client(tmp_path, monkeypatch):
    import importlib

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import motion_lab

    importlib.reload(motion_lab)   # match the router's Depends to our override (datsme_integration may be reloaded)
    fake = _FakePF(tmp_path)
    monkeypatch.setattr(motion_lab, "_pf", lambda: fake)

    def fake_submit(pf, wf, jid, timeout=300):
        (pf.COMFY_OUTPUT_DIR / "raw_output").write_bytes(b"\x89PNG\r\n\x1a\n fake")
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
    # cancel is idempotent / safe on any id (sets a flag the poll loop honors)
    assert lab_client.post("/api/admin/motion-lab/cancel/nope").json() == {"canceling": True}
    jid = lab_client.post("/api/admin/motion-lab/still", json={"animal": "robin"}).json()["job_id"]
    j = _wait_done(lab_client, jid)
    assert "elapsed" in j


def test_asset_rejects_bad_ext_and_unknown_id(lab_client):
    assert lab_client.get("/api/admin/motion-lab/asset/abc123.gif").status_code == 404
    assert lab_client.get("/api/admin/motion-lab/asset/nonexistent99.png").status_code == 404
