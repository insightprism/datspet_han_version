"""Unit pins for the §7 step-9 production posture:

  (a) Opt-1 reattach — a pool job persisted at submit is resumed after a
      restart (fresh app import), completes, lands the pet, clears its row.
  (b) The persistence lifecycle — the row exists exactly while a pool job is
      in flight (present during drive, gone at both terminal states).
  (c) Transient retention — old previews/scratch/expired tokens are swept;
      fresh files and active jobs' scratch survive.
  (d) /api/health — liveness + workshop summary without touching the network.
"""
import importlib
import io
import json
import os
import sys
import time
import zipfile

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WEBUI = os.path.join(REPO, "webui")
for p in (WEBUI, REPO):
    if p not in sys.path:
        sys.path.insert(0, p)


def _fake_bundle(breed_id="a_red_panda", display_name="A Red Panda") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(f"{breed_id}_sprite.png", b"\x89PNG\r\n\x1a\nDATA")
        z.writestr("manifest.json", json.dumps({"animations": {}}))
        z.writestr("package.json", json.dumps(
            {"breed_id": breed_id, "display_name": display_name}))
    return buf.getvalue()


@pytest.fixture()
def pool_app(tmp_path, monkeypatch):
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


def _wait_terminal(app_mod, job_id, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with app_mod.JOBS_LOCK:
            job = app_mod.JOBS.get(job_id)
            if job and job.status in ("done", "error"):
                return job
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} never reached a terminal state")


# (a) reattach: persisted pool job resumes after a restart ----------------------
def test_reattach_resumes_and_completes_orphaned_pool_job(pool_app, monkeypatch):
    import db
    # A restart scenario: the row exists (recorded pre-restart), JOBS is empty.
    db.record_pool_job(job_id="webjob000001", pool_job_id="pool-abc",
                       description="red panda", display_name="A Red Panda",
                       created_at=time.time(), external_user_id="user-77")

    driven = {}
    monkeypatch.setattr(pool_app.pool_client, "drive_to_result",
                        lambda pjid, **kw: (driven.update(pjid=pjid) or _fake_bundle()))

    pool_app._reattach_pool_jobs()
    job = _wait_terminal(pool_app, "webjob000001")

    assert driven["pjid"] == "pool-abc", "did not resume the persisted pool job id"
    assert job.status == "done" and job.name == "A Red Panda"
    row = db.get_pet("webjob000001")
    assert row is not None and row["external_user_id"] == "user-77"
    assert db.list_pool_jobs() == [], "reattach row must clear at terminal state"


def test_reattach_is_inert_in_local_mode(pool_app, monkeypatch):
    import db
    db.record_pool_job(job_id="webjob000002", pool_job_id="pool-x",
                       description="fox", display_name=None,
                       created_at=time.time())
    monkeypatch.setattr(pool_app, "PET_GEN_BACKEND", "local")
    pool_app._reattach_pool_jobs()
    with pool_app.JOBS_LOCK:
        assert "webjob000002" not in pool_app.JOBS


# (b) persistence lifecycle ------------------------------------------------------
def test_pool_row_exists_during_drive_and_clears_on_success(pool_app, tmp_path, monkeypatch):
    import db
    seen = {}

    monkeypatch.setattr(pool_app.pool_client, "submit", lambda task, params, *, labels=None: "pool-live")

    def fake_drive(pjid, **kw):
        rows = db.list_pool_jobs()
        seen["during"] = [(r["id"], r["pool_job_id"]) for r in rows]
        return _fake_bundle()
    monkeypatch.setattr(pool_app.pool_client, "drive_to_result", fake_drive)

    job = pool_app.Job(id="webjob000003", name="x")
    pool_app.run_pet_job(job, description="red panda", reference_image=None)

    assert job.status == "done", job.error
    assert seen["during"] == [("webjob000003", "pool-live")], "row missing mid-flight"
    assert db.list_pool_jobs() == []


def test_pool_row_clears_on_error(pool_app, tmp_path, monkeypatch):
    import db
    import pool_client as pc
    monkeypatch.setattr(pool_app.pool_client, "submit", lambda task, params, *, labels=None: "pool-err")
    def boom(pjid, **kw):
        raise pc.PoolError("worker died and was not reclaimed")
    monkeypatch.setattr(pool_app.pool_client, "drive_to_result", boom)

    job = pool_app.Job(id="webjob000004", name="x")
    pool_app.run_pet_job(job, description="red panda", reference_image=None)

    assert job.status == "error"
    assert db.list_pool_jobs() == [], "error path must clear the reattach row"


# (c) transient retention --------------------------------------------------------
def test_cleanup_transients_sweeps_old_keeps_fresh_and_active(pool_app):
    import db
    old = time.time() - 100_000
    stale_preview = pool_app.PREVIEW_DIR / "stale.png"
    fresh_preview = pool_app.PREVIEW_DIR / "fresh.png"
    stale_preview.write_bytes(b"x"); os.utime(stale_preview, (old, old))
    fresh_preview.write_bytes(b"x")

    stale_dir = pool_app.SCRATCH_DIR / "deadjob00001"
    stale_dir.mkdir(); (stale_dir / "ref.png").write_bytes(b"x")
    os.utime(stale_dir, (old, old))
    active_dir = pool_app.SCRATCH_DIR / "livejob00001"
    active_dir.mkdir(); os.utime(active_dir, (old, old))
    with pool_app.JOBS_LOCK:
        pool_app.JOBS["livejob00001"] = pool_app.Job(
            id="livejob00001", name="live", status="running")

    # bundle_tokens FK-references pets(id) — park the expired token on a real pet
    db.insert_pet(pet_id="tokpet000001", breed_id="b", display_name="T",
                  created_at=time.time(), draft=False, sheet_png=b"x",
                  manifest_json="{}", package_json=None, bundle_zip=b"x")
    db.create_bundle_token("tok-expired", "tokpet000001", time.time() - 90_000)

    removed = pool_app._cleanup_transients(max_age_s=24 * 3600)

    assert not stale_preview.exists() and fresh_preview.exists()
    assert not stale_dir.exists(), "old inactive scratch must be swept"
    assert active_dir.exists(), "an ACTIVE job's scratch must survive any age"
    assert removed >= 3  # stale preview + stale dir + expired token


# (d) health endpoint -------------------------------------------------------------
def test_health_reports_backend_and_workshop(pool_app, monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setattr(pool_app.pool_client, "workshop_status",
                        lambda task="pet_factory": {"online": True, "busy": False})
    client = TestClient(pool_app.app)
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["backend"] == "pool"
    assert body["workshop"] == {"online": True, "busy": False}
    assert isinstance(body["active_jobs"], int)
