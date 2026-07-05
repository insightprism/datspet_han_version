"""worker — runs on the GPU box; polls the queue, generates pets, uploads them.

    QUEUE_URL=https://your-backend/petmaker WORKER_TOKEN=<secret> \
        python examples/worker.py

Needs ComfyUI running locally with the models from the README. For GPU cutout,
make sure onnxruntime-gpu can find CUDA libs (see README "GPU cutout").
Polling the queue also serves as the "worker online" heartbeat.
"""
import io
import os
import time
import traceback

import requests

from pet_factory import make_pet_zip

BASE = os.environ.get("QUEUE_URL", "http://127.0.0.1:5017").rstrip("/")
TOKEN = os.environ.get("WORKER_TOKEN", "change-me")
H = {"X-Worker-Token": TOKEN}


def _progress(jid):
    def cb(msg, pct):
        try:
            requests.post(f"{BASE}/api/worker/progress", headers=H,
                          json={"job_id": jid, "pct": pct, "msg": msg}, timeout=10)
        except Exception:
            pass
    return cb


def main():
    print(f"[worker] polling {BASE}", flush=True)
    while True:
        try:
            r = requests.post(f"{BASE}/api/worker/claim", headers=H, timeout=20)
            job = r.json() if r.status_code == 200 else {}
        except Exception as e:
            print("[worker] claim error:", e, flush=True); time.sleep(5); continue
        if not job:
            time.sleep(3); continue

        jid, animal = job["job_id"], job["animal"]
        print(f"[worker] job {jid}: {animal!r}", flush=True)
        try:
            breed_id, zip_bytes = make_pet_zip(animal, _progress(jid))
            requests.post(f"{BASE}/api/worker/complete", headers=H,
                          data={"job_id": jid, "breed_id": breed_id},
                          files={"zip": (f"{breed_id}.zip", io.BytesIO(zip_bytes), "application/zip")},
                          timeout=120)
            print(f"[worker] done {jid} ({breed_id})", flush=True)
        except Exception as e:
            traceback.print_exc()
            try:
                requests.post(f"{BASE}/api/worker/fail", headers=H,
                              json={"job_id": jid, "error": str(e)}, timeout=20)
            except Exception:
                pass


if __name__ == "__main__":
    main()
