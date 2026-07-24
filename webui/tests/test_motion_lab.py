"""API tests for the Motion Lab (SPEC_MOTION_LAB).

Exercises webui/motion_lab.py with a FAKE factory (no GPU/ComfyUI): the generation
steps write tiny placeholder files, so the still→animate→asset chain and the input
validation are covered without real generation. The admin gate is overridden.
"""
import pytest


class _FakePF:
    """Stands in for pet_factory.factory: _run writes a placeholder file into
    COMFY_OUTPUT_DIR and returns its name, so the endpoints' copy/serve path runs."""
    def __init__(self, outdir):
        self.COMFY_OUTPUT_DIR = outdir
        self._n = 0

    def _base_prompt(self, animal, pose="standing"):
        return f"cute cartoon {animal}, {pose}"

    def _static_image_wf(self, prompt, seed):
        return {"kind": "still", "prompt": prompt, "seed": seed}

    def _loop_wf(self, prompt, path, seed):
        return {"kind": "loop", "prompt": prompt, "src": path, "seed": seed}

    def _run(self, wf, timeout=360):
        self._n += 1
        ext = "webp" if wf.get("kind") == "loop" else "png"
        name = f"fake_{self._n}.{ext}"
        (self.COMFY_OUTPUT_DIR / name).write_bytes(b"\x89PNG\r\n\x1a\n fake")
        return name


@pytest.fixture()
def lab_client(tmp_path, monkeypatch):
    import importlib

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import motion_lab

    # Reload so the router's captured Depends and our override reference the SAME
    # require_admin_launch — another test may have reloaded datsme_integration
    # (the ai_admin fixture does the same for this reason).
    importlib.reload(motion_lab)
    monkeypatch.setattr(motion_lab, "_pf", lambda: _FakePF(tmp_path))

    app = FastAPI()
    app.include_router(motion_lab.router)
    app.dependency_overrides[motion_lab.datsme_integration.require_admin_launch] = lambda: None
    return TestClient(app)


def test_still_base_and_anchor_are_served(lab_client):
    base = lab_client.post("/api/admin/motion-lab/still", json={"animal": "robin"}).json()
    assert base["kind"] == "base" and base["url"].endswith(".png")
    anchor = lab_client.post("/api/admin/motion-lab/still",
                             json={"animal": "robin", "clause": "wings spread wide open"}).json()
    assert anchor["kind"] == "anchor"
    for a in (base, anchor):
        r = lab_client.get(a["url"])
        assert r.status_code == 200 and r.headers["content-type"] == "image/png"


def test_still_requires_an_animal(lab_client):
    assert lab_client.post("/api/admin/motion-lab/still", json={"animal": "  "}).status_code == 400


def test_animate_from_a_still(lab_client):
    anchor = lab_client.post("/api/admin/motion-lab/still",
                             json={"animal": "robin", "clause": "flying"}).json()
    loop = lab_client.post("/api/admin/motion-lab/animate", json={
        "asset_id": anchor["asset_id"], "animal": "robin",
        "profile_key": "avian", "pose_name": "fly"}).json()
    assert loop["url"].endswith(".webp")
    assert lab_client.get(loop["url"]).status_code == 200


def test_animate_rejects_missing_still_and_disabled_pose(lab_client):
    # a still that was never generated
    r = lab_client.post("/api/admin/motion-lab/animate", json={
        "asset_id": "deadbeefdeadbeef", "animal": "robin",
        "profile_key": "avian", "pose_name": "fly"})
    assert r.status_code == 404
    # a real still but a disabled pose (avian.swim is disabled)
    anchor = lab_client.post("/api/admin/motion-lab/still",
                             json={"animal": "robin", "clause": "swimming"}).json()
    r = lab_client.post("/api/admin/motion-lab/animate", json={
        "asset_id": anchor["asset_id"], "animal": "robin",
        "profile_key": "avian", "pose_name": "swim"})
    assert r.status_code == 400


def test_asset_rejects_bad_ext_and_unknown_id(lab_client):
    assert lab_client.get("/api/admin/motion-lab/asset/abc123.gif").status_code == 404
    assert lab_client.get("/api/admin/motion-lab/asset/nonexistent99.png").status_code == 404
