"""queue_server — a tiny job queue + status API for backends WITHOUT a GPU.

DatsMe's API server has no GPU, so it can't run the pipeline directly. Pattern:
this queue lives next to your no-GPU backend; a `worker.py` on the GPU box polls
it, generates the pet, and uploads the .zip back here.

Run:  WORKER_TOKEN=<secret> python examples/queue_server.py    # serves :5017

Public endpoints:
  POST /api/submit            {animal}          -> {job_id}
  GET  /api/status/<job_id>                     -> {status, pct, msg, download_url?}
  GET  /api/result/<job_id>                     -> the .zip
Worker endpoints (header X-Worker-Token: <secret>):
  POST /api/worker/claim                        -> {job_id, animal} | {}
  POST /api/worker/progress   {job_id,pct,msg}
  POST /api/worker/complete   (multipart: job_id, breed_id, zip)
  POST /api/worker/fail       {job_id, error}

This is intentionally minimal — adapt it to your framework (e.g. fold these into
DatsMe's FastAPI app and store jobs in your DB).
"""
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from flask import (Flask, abort, jsonify, request, send_from_directory)

ROOT = Path(__file__).parent
RESULTS = ROOT / "results"
RESULTS.mkdir(exist_ok=True)
DB = ROOT / "queue.db"
TOKEN = os.environ.get("WORKER_TOKEN", "change-me")
MAX_QUEUED = int(os.environ.get("MAX_QUEUED", "15"))
WORKER_STALE_S = 90

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024
_LOCK = threading.Lock()
_STATE = {"worker_seen": 0.0}


def _db():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    return c


with _db() as c:
    c.execute("""CREATE TABLE IF NOT EXISTS jobs (
        id TEXT PRIMARY KEY, animal TEXT, status TEXT, breed_id TEXT,
        error TEXT, pct REAL, msg TEXT, created_at REAL)""")


def _need_worker():
    if request.headers.get("X-Worker-Token") != TOKEN:
        abort(401)
    _STATE["worker_seen"] = time.time()


@app.route("/api/health")
def health():
    online = (time.time() - _STATE["worker_seen"]) < WORKER_STALE_S
    return jsonify({"worker_online": online})


@app.route("/api/submit", methods=["POST"])
def submit():
    animal = ((request.json or {}).get("animal") if request.is_json else request.form.get("animal")) or ""
    animal = animal.strip()[:60]
    if not animal:
        return jsonify({"error": "animal required"}), 400
    with _LOCK, _db() as c:
        n = c.execute("SELECT COUNT(*) n FROM jobs WHERE status IN ('queued','processing')").fetchone()["n"]
        if n >= MAX_QUEUED:
            return jsonify({"error": "busy, try again later"}), 429
        jid = uuid.uuid4().hex[:12]
        c.execute("INSERT INTO jobs (id,animal,status,pct,msg,created_at) VALUES (?,?,?,?,?,?)",
                  (jid, animal, "queued", 0.0, "Waiting…", time.time()))
    return jsonify({"job_id": jid})


@app.route("/api/status/<jid>")
def status(jid):
    with _db() as c:
        r = c.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
    if not r:
        return jsonify({"error": "unknown job"}), 404
    out = {"status": r["status"], "pct": r["pct"] or 0, "msg": r["msg"] or "", "error": r["error"]}
    if r["status"] == "done":
        out["download_url"] = f"api/result/{jid}"
        out["breed_id"] = r["breed_id"]
    return jsonify(out)


@app.route("/api/result/<jid>")
def result(jid):
    if not (RESULTS / f"{jid}.zip").exists():
        return jsonify({"error": "not ready"}), 404
    return send_from_directory(RESULTS, f"{jid}.zip", as_attachment=True, download_name="pet.zip")


@app.route("/api/worker/claim", methods=["POST"])
def claim():
    _need_worker()
    with _LOCK, _db() as c:
        r = c.execute("SELECT id,animal FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
        if not r:
            return jsonify({})
        c.execute("UPDATE jobs SET status='processing', msg='Starting…' WHERE id=?", (r["id"],))
        return jsonify({"job_id": r["id"], "animal": r["animal"]})


@app.route("/api/worker/progress", methods=["POST"])
def progress():
    _need_worker()
    d = request.json or {}
    with _LOCK, _db() as c:
        c.execute("UPDATE jobs SET pct=?, msg=? WHERE id=?",
                  (float(d.get("pct", 0)), str(d.get("msg", ""))[:120], d.get("job_id")))
    return jsonify({"ok": True})


@app.route("/api/worker/complete", methods=["POST"])
def complete():
    _need_worker()
    jid = request.form.get("job_id"); f = request.files.get("zip")
    if not jid or not f:
        return jsonify({"error": "job_id and zip required"}), 400
    f.save(RESULTS / f"{jid}.zip")
    with _LOCK, _db() as c:
        c.execute("UPDATE jobs SET status='done', breed_id=?, pct=1.0, msg='Done!' WHERE id=?",
                  ((request.form.get("breed_id") or "pet")[:48], jid))
    return jsonify({"ok": True})


@app.route("/api/worker/fail", methods=["POST"])
def fail():
    _need_worker()
    d = request.json or {}
    with _LOCK, _db() as c:
        c.execute("UPDATE jobs SET status='error', error=? WHERE id=?",
                  (str(d.get("error", "failed"))[:300], d.get("job_id")))
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5017)), threaded=True)
