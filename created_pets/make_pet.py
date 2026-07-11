#!/usr/bin/env python3
"""make_pet.py — generate a pet through the shared GPU pool and save it here.

Submits {task: pet_factory, params: {animal: ...}} to pool.datsme.me as the datspet app,
watches progress, downloads the bundle, and unpacks it into
created_pets/<slug>/ so every test pet lands in one place.

Usage:
    python3 make_pet.py "cardinal bird"
    python3 make_pet.py "red panda"

The app key is read from ~/.pool/datspet_key if present, else pass it:
    POOL_APP_KEY=<key> python3 make_pet.py "penguin"
(get the key from the server: ssh root@5.161.70.13 cat /var/www/pool/app_key_datspet)
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

POOL = os.environ.get("POOL_URL", "https://pool.datsme.me").rstrip("/")
HERE = Path(__file__).resolve().parent


def _app_key() -> str:
    key = os.environ.get("POOL_APP_KEY")
    if key:
        return key.strip()
    keyfile = Path.home() / ".pool" / "datspet_key"
    if keyfile.is_file():
        return keyfile.read_text().strip()
    sys.exit("no app key — set POOL_APP_KEY, or save it to ~/.pool/datspet_key "
             "(ssh root@5.161.70.13 cat /var/www/pool/app_key_datspet)")


def _req(method, path, key, body=None):
    data = json.dumps(body).encode() if body else None
    r = urllib.request.Request(POOL + path, data=data, method=method,
                               headers={"X-App-Key": key, "Content-Type": "application/json"})
    return urllib.request.urlopen(r, timeout=60)


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "pet"


def main():
    if len(sys.argv) < 2:
        sys.exit('usage: python3 make_pet.py "<animal>"   e.g. "cardinal bird"')
    animal = " ".join(sys.argv[1:])
    key = _app_key()

    print(f"submitting '{animal}' to {POOL} ...", flush=True)
    try:
        jid = json.load(_req("POST", "/api/jobs", key,
                             {"task": "pet_factory", "params": {"animal": animal}}))["job_id"]
    except urllib.error.HTTPError as e:
        sys.exit(f"submit failed {e.code}: {e.read().decode()[:300]}")
    print(f"job: {jid}", flush=True)

    last = ""
    start = time.time()
    while True:
        s = json.load(_req("GET", f"/api/jobs/{jid}", key))
        line = f"[{int(time.time()-start):3d}s] {s['status']:8} {s['pct']:5.1f}%  {s.get('msg','')}"
        if line != last:
            print(line, flush=True)
            last = line
        if s["status"] in ("done", "dead", "error"):
            break
        time.sleep(4)

    if s["status"] != "done":
        sys.exit(f"generation {s['status']}: {(s.get('error') or '')[-400:]}")

    out_dir = HERE / _slug(animal)
    out_dir.mkdir(exist_ok=True)
    zip_path = out_dir / f"{_slug(animal)}.zip"
    zip_path.write_bytes(_req("GET", f"/api/jobs/{jid}/result", key).read())
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(out_dir)
    print(f"\n✓ saved to {out_dir}/")
    for f in sorted(out_dir.iterdir()):
        print(f"    {f.name}")


if __name__ == "__main__":
    main()
