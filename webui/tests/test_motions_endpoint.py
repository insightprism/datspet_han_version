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


def test_start_job_parses_valid_poses_json(app_mod, monkeypatch):
    client, captured = _client_capturing_run(app_mod, monkeypatch)
    r = client.post("/api/generate", data={
        "text": "a red fox",
        "poses": '{"walk": true, "idle": true, "run": true}',
        "motion_profile": "corgi",
    })
    assert r.status_code == 200, r.text
    assert captured["poses"] == {"walk": True, "idle": True, "run": True}
    assert captured["motion_profile"] == "corgi"


def test_start_job_malformed_poses_becomes_none(app_mod, monkeypatch):
    client, captured = _client_capturing_run(app_mod, monkeypatch)
    r = client.post("/api/generate", data={"text": "a red fox", "poses": "not json{{"})
    assert r.status_code == 200, r.text
    assert captured["poses"] is None                    # safe default (walk+idle)
    assert captured["motion_profile"] is None
