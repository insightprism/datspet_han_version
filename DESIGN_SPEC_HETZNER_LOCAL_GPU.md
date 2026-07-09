# Design Spec — Hosting pet_factory: Hetzner front door + local GPU workers

**Status:** design (no code in this repo changes to satisfy it; it specifies how to
*deploy* what already exists, plus a small, named hardening of the example queue).
**Audience:** whoever stands up the servers.
**Scope:** how to run the "type an animal → get a pet" feature online when the
public server has **no GPU** (Hetzner) and the GPU lives on **local machines that
are not always on**.
**Target for this deployment:** a **new, self-owned Hetzner VPS** (not a shared
box), with **two** local RTX 3090 machines as workers.

> **This is not hypothetical — it is verified against the live system.** An existing
> deployment of this exact system runs at `hanzchau.com/petmaker`: a GPU-less Hetzner
> VPS holding the web page + job queue, with the actual generation on a home RTX 3090
> that polls and returns results. **§0 below documents what the live server's code
> actually does** (read directly from `/opt/apps/petmaker/petmaker_server.py` on the
> box). This spec adopts that deployment's proven conventions (nginx, `/opt/apps/`,
> gunicorn + systemd, key-only SSH — see §9.1) and adds what the reference lacks:
> **two workers with not-always-on resilience** (§7.1). The reference runs a single
> home PC, which is exactly why its own docs say "if the pet maker is offline, the
> fix is almost always on the HOME PC" — the fragility the two-worker design removes.

---

## 0. The live reference, as actually deployed (verified 2026-07-09)

Read directly off the running VPS (`hanzchau.com` / `5.161.189.215`) from
`/opt/apps/petmaker/petmaker_server.py` and its systemd unit. This is ground truth,
not a proposal — everything below in this section is *what exists today*.

**How it runs.** A single Flask app, `petmaker_server.py` (~175 lines), served by
**gunicorn** under **systemd**:

```ini
# /etc/systemd/system/petmaker.service
Description=Pet Maker queue + page (DatsMe pet generator)
WorkingDirectory=/opt/apps/petmaker
Environment="WORKER_TOKEN=<secret>"          # shared secret; guards worker endpoints
Environment="PETMAKER_MAX_QUEUED=15"
ExecStart=/opt/apps/petmaker/venv/bin/gunicorn --workers 1 --bind 127.0.0.1:5016 --timeout 180 petmaker_server:app
Restart=always
RestartSec=5
```

Its venv contains **only Flask + gunicorn** — no `torch`, `diffusers`, `rembg`, or
any ML library. Confirmed by `pip list`. This is the proof the queue tier is genuinely
light and GPU-free.

**How it "gets the GPU from the Omen": it does NOT reach out at all.** A grep of the
server for `torch|cuda|comfy|ssh|paramiko|omen|192.168|make_pet|subprocess|gpu`
returns **nothing**. The server has zero knowledge of where the GPU box is and never
connects to it. The server's own docstring states it: *"hands jobs to the local
worker (which has the 3090) and stores the .zip. No GPU here."* The GPU is obtained
by **inversion** — the Omen worker dials *out* to the VPS and pulls work:

```
   OMEN (home, RTX 3090)                   HANCHAU VPS (no GPU, gunicorn :5016)
   ─────────────────────                   ───────────────────────────────────
   worker loop, every ~3s ──────POST────▶  /api/worker/claim  (header X-Worker-Token)
                            ◀──────────────  {job_id, animal}  or  {}
   make_pet_zip() on the 3090
   ─────────────────────────────POST────▶  /api/worker/progress  {job_id, pct, msg}
   ─────────────────────────────POST────▶  /api/worker/complete  (multipart: zip)  → results/<jid>.zip
```

**The exact endpoints (verbatim from the live file):**

| Endpoint | Guard | Behavior in the live code |
|---|---|---|
| `GET /` | — | serves the one-input page (templates/) |
| `GET /api/health` | — | `{"worker_online": <seen within 90s>, "busy": <count queued+processing>}` |
| `POST /api/submit` | — | inserts a `queued` job; rejects if queued+processing ≥ `MAX_QUEUED` (15) |
| `GET /api/status/<job_id>` | — | status/pct/msg, plus a download URL when done |
| `GET /api/result/<job_id>` | — | serves `results/<job_id>.zip` |
| `POST /api/worker/claim` | `X-Worker-Token` | atomically takes oldest `queued` → `processing`, stamps `claimed_at` |
| `POST /api/worker/progress` | `X-Worker-Token` | updates `pct`, `msg` |
| `POST /api/worker/complete` | `X-Worker-Token` | saves uploaded zip to `results/`, marks `done`, stamps `done_at` |
| `POST /api/worker/fail` | `X-Worker-Token` | marks `error` with the message |

**Auth & liveness, exactly as implemented:**
- `_require_worker()` does two things on every worker call: rejects with `401` if
  `X-Worker-Token` ≠ `WORKER_TOKEN`, **and** sets `_STATE["worker_seen"] = now`. So the
  token check *is* the heartbeat.
- `/api/health` computes `online = (now - worker_seen) < 90s` (`WORKER_STALE_S = 90`).
  In-memory only (a module global), so it resets on restart — fine, because the worker
  re-polls within seconds.

**The live SQLite schema (`jobs` table):**
```sql
CREATE TABLE jobs (
  id TEXT PRIMARY KEY, animal TEXT, status TEXT,
  breed_id TEXT, error TEXT, pct REAL, msg TEXT,
  created_at REAL, claimed_at REAL, done_at REAL)
```
> Note `claimed_at` and `done_at` already exist. The live code **writes** `claimed_at`
> on claim but does **not** yet read it to reclaim stale jobs — so the schema is
> already one step from the §7.1 resilience this spec requires; only the reclaim logic
> is missing.

**Evidence it works:** at inspection time `/api/health` returned
`{"worker_online": true, "busy": 0}` (the Omen was actively polling), and
`results/` held **21 finished `.zip`s** (0.45–1.4 MB each) — real pets the Omen
generated and uploaded back over weeks.

**Deltas between the live reference and this spec's target (all intentional):**

| Aspect | Live reference | This spec's target |
|---|---|---|
| Workers | 1 (the Omen) | 2 local 3090s (interchangeable) |
| Stale-job reclaim | schema has `claimed_at`, but no reclaim logic | **required** (§7.1) — a dead worker's job returns to the queue |
| Host | Jeff's shared box (16 apps on 2 GB, swap-pressured) | markly's **own** VPS, right-sized (§ sizing note) |
| Worker auth | plaintext shared `WORKER_TOKEN` | same for Profile A; hashed service key / HMAC for Profile B |
| DB | SQLite, single gunicorn worker (`--workers 1`) | same for Profile A; Postgres for Profile B |

---

## 1. Goal & constraints

Run pet generation as an online feature under these real constraints:

- **Public host = Hetzner, CPU-only.** Renting a GPU at Hetzner is expensive and
  defeats the point of using Hetzner. The public server must never need a GPU.
- **GPU is local.** Two local machines each have a 24 GB RTX 3090 — the exact
  reference hardware `pet_factory` targets (README: "~24 GB VRAM (RTX 3090/4090)",
  "~3 minutes on an RTX 3090").
- **Local machines are not always on**, but *at least one is expected to be up at
  any given time*. The system must keep working whenever ≥1 worker is up, and
  degrade cleanly (jobs wait, site stays up) when none are.
- **No inbound access to the local machines.** They sit on a home/office network
  with no public IP and no port-forwarding. Nothing may require reaching *into*
  them.

### Non-goals

- No remote-GPU / GPU-sharing protocol. The GPU is used **only** by the machine it
  physically lives in. (See §4.)
- No autoscaling, no cloud GPU. Adding cloud GPU later is possible but out of scope.
- This spec does not re-specify the ML pipeline; that is `pet_factory/factory.py`
  and the README. It specifies the **deployment topology and the queue contract**.

---

## 2. The core idea in one paragraph

There is **one always-on bookkeeping server** (Hetzner) that holds a queue of jobs
and stores finished results, and **N interchangeable GPU workers** (the local
machines) that **poll the server, claim a job, generate locally on their own GPU,
and upload a small `.zip` back**. Workers reach *out* to Hetzner over HTTPS;
Hetzner never reaches *in*. "Use whichever machine is alive" is not a feature we
build — it is the emergent behavior of workers polling: whoever is polling gets
work; if two poll, two pets run in parallel; if none poll, jobs wait.

---

## 3. Topology

```
        ┌────────────────────────────────────────────────────────┐
        │  HETZNER  —  always on, CPU only, public HTTPS           │
        │                                                          │
 Browser│   ┌──────────────┐        ┌───────────────────────────┐ │
 ──────▶│   │  web / app   │        │  queue service            │ │
 "make a│   │  (or DatsMe  │◀──────▶│  · jobs table             │ │
  fox"  │   │   FastAPI)   │        │  · result .zip storage    │ │
        │   └──────────────┘        │  · worker liveness        │ │
        │                           └───────────▲───────────────┘ │
        └───────────────────────────────────────┼─────────────────┘
                                                 │
                    outbound HTTPS only (workers dial out;         
                    Hetzner never connects to a worker)            
                                                 │
              ┌──────────────────────────────────┴──────────────────┐
              │                                                      │
     ┌────────┴─────────┐                              ┌─────────────┴────────┐
     │  WORKER A         │                              │  WORKER B            │
     │  local, RTX 3090  │                              │  local, RTX 3090     │
     │  ComfyUI :8188    │                              │  ComfyUI :8188       │
     │  pet_factory      │                              │  pet_factory         │
     │  worker.py        │                              │  worker.py           │
     └───────────────────┘                              └──────────────────────┘
       may be OFF sometimes                               may be OFF sometimes
       (≥1 of the two expected up at any time)
```

Three roles, but only **two kinds of machine to build**: the Hetzner box, and a
worker (cloned onto each local machine).

---

## 4. Where the GPU is used (and where it is NOT)

This is the single most misunderstood point, so it is stated explicitly.

- **All GPU computation happens on the worker machine, on its own local GPU.**
  ComfyUI, Z-Image (base sprite), Wan 2.2 I2V (walk + idle), and birefnet
  background removal all run inside the worker machine. `pet_factory` reads
  ComfyUI's output files off the *local* filesystem (`factory.py`: `COMFY_OUTPUT_DIR`,
  "must run on the same machine as ComfyUI (shared filesystem)").
- **Hetzner performs no ML computation and needs no GPU.** It stores jobs and the
  finished `.zip`. It never imports `pet_factory` (confirmed by the repo:
  `DATSME_INTEGRATION.md` — "`pet_factory` is never imported by DatsMe — only by
  the GPU worker").
- **What crosses the network** is tiny and text/asset-sized, never GPU work:
  - **Down** to the worker: a claimed job — essentially `{job_id, animal}`.
  - **Up** to Hetzner: the finished bundle — a `.zip` of one PNG sprite sheet +
    `manifest.json` + `package.json` (see `factory.py: pack_datsme_bundle`).

| Misconception | Reality |
|---|---|
| Hetzner "pulls GPU" from a local machine | The local machine uses **its own** GPU, locally |
| GPU compute is streamed to Hetzner | Only a finished **`.zip`** is uploaded to Hetzner |
| Hetzner reaches into the local network | The worker dials **out**; Hetzner accepts inbound only |

---

## 5. Component responsibilities

### 5.1 Hetzner box — the always-on front door (CPU only)

The only piece that must stay up 24/7. Deliberately light.

**Runs:**
- The **queue service** — either the standalone `examples/queue_server.py` (Flask +
  SQLite, explicitly "intentionally minimal — adapt it to your framework") **or**,
  for the real product, the DatsMe-integrated routes described in
  `DATSME_INTEGRATION.md` (FastAPI + Postgres). This spec supports both; see §9.
- Result storage: finished `.zip`s on local disk (example) or wherever
  `write_assets` puts them (DatsMe integration).
- A reverse proxy terminating **HTTPS** (Caddy or nginx) in front of the queue.

**Must have:** Python 3, the web framework, a database, disk for results, a domain
+ TLS cert, and the shared **worker secret** (`WORKER_TOKEN` in the example;
a hashed service-account key or HMAC secret in the DatsMe integration).

**Must NOT have:** CUDA, ComfyUI, model weights, `pet_factory`, ffmpeg-for-GPU.
None of it. If any of those end up on the Hetzner box, the design has leaked.

### 5.2 Worker machines — the GPU tier (identical on every local box)

Clones of one another; that is what makes them interchangeable.

**Runs (per machine):**
- **ComfyUI** on `127.0.0.1:8188` with the models & custom node from the README:
  Z-Image (`zImageTurbo_turbo`, `zimage_ae`, `qwen_3_4b_fp8`), Wan 2.2 I2V
  (`wan2.2_i2v_high/low_noise_14B_fp8_scaled`, `wan_2.1_vae`, `umt5_xxl_fp8`),
  the LightX2V 4-step LoRAs, and **VideoHelperSuite** (provides `VHS_LoadImagePath`).
  ~40–50 GB of weights total. **ffmpeg** (`factory.py` shells out to it).
- **`pet_factory`** (this repo, `pip install -e .`) + **`examples/worker.py`**.

**Config (env vars):**
- `QUEUE_URL=https://<hetzner-domain>` — where to poll (`worker.py`).
- `WORKER_TOKEN=<secret>` — sent as `X-Worker-Token` (`worker.py` / `queue_server.py`).
- `PET_FACTORY_COMFY_URL` (default `http://127.0.0.1:8188`) and
  `PET_FACTORY_COMFY_OUTPUT` (default `~/ComfyUI/output`) if ComfyUI isn't at the
  defaults (`factory.py`).

**Requires no inbound connectivity.** Only outbound HTTPS to Hetzner. No public IP,
no port-forward, no firewall change on the local network.

**On the two 3090s (per earlier decision — one worker for now):** start with a
single ComfyUI + one `worker.py` using one card. To use both cards later, run a
second ComfyUI on another port pinned with `CUDA_VISIBLE_DEVICES=1` and a second
`worker.py` pointed at it — the queue already supports multiple workers claiming
independently, no server change.

### 5.3 Worker ops recipe — imitate the live Omen (verified 2026-07-09)

There is already a **fully working GPU worker** running: Jeff's Omen desktop
(1× RTX 3090, i9-12900K, 62 GB RAM, Ubuntu 24.04) powers `hanzchau.com/petmaker`
today. Its **operational setup is the wheel to copy** — do not reinvent it. (Its
*pipeline code* is a different story — see the warning at the end.)

**Two ordered systemd services** — ComfyUI first, then the worker:

```ini
# /etc/systemd/system/comfyui.service
[Unit]
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
User=<you>
WorkingDirectory=/home/<you>/ComfyUI
ExecStart=/home/<you>/ComfyUI/venv/bin/python main.py --preview-method latent2rgb
Restart=always
RestartSec=5
TimeoutStartSec=0        # ComfyUI takes ~20–40s to load; don't let systemd time it out
[Install]
WantedBy=multi-user.target
```

```ini
# /etc/systemd/system/petmaker-worker.service
[Unit]
After=comfyui.service network-online.target    # worker starts only after ComfyUI
Wants=network-online.target
[Service]
Type=simple
User=<you>
WorkingDirectory=/home/<you>/pet_factory
ExecStart=/bin/bash /home/<you>/pet_factory/run_worker.sh
Restart=always                                  # survives VPS downtime; just keeps retrying
RestartSec=5
[Install]
WantedBy=multi-user.target
```

**The `run_worker.sh` wrapper** — this is the non-obvious part that makes GPU cutout
work. It sets three things *before* python starts, then execs the worker:

```bash
#!/bin/bash
cd /home/<you>/pet_factory
# Borrow ComfyUI's bundled CUDA 12 + cuDNN 9 libs so onnxruntime-gpu can run
# birefnet on the GPU (~12x faster). Must be set BEFORE python starts (dlopen
# reads LD_LIBRARY_PATH at process start). Falls back to CPU if not found.
NV=/home/<you>/ComfyUI/venv/lib/python3.12/site-packages/nvidia
export LD_LIBRARY_PATH="$NV/cublas/lib:$NV/cudnn/lib:$NV/cuda_runtime/lib:$NV/cufft/lib:$NV/curand/lib:$NV/cusparse/lib:$NV/cusolver/lib:$NV/cuda_nvrtc/lib:$NV/nvjitlink/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export PETMAKER_URL="https://<your-queue-domain>/petmaker"
export WORKER_TOKEN="$(cat /home/<you>/pet_factory/.worker_token)"   # token in a file, not inline
exec /path/to/venv/bin/python worker.py
```

Key ops facts learned from the live worker:
- **`Restart=always` is the resilience.** When the VPS was down earlier today the
  worker logged `Connection refused` every few seconds and just kept retrying — no
  crash, no intervention. It resumed the moment the VPS came back.
- **Silence in the logs = healthy.** The worker only logs errors and job activity;
  routine empty polls print nothing. "No logs for hours" + `worker_online:true` on
  the VPS means it's polling fine.
- **Token lives in a file** (`.worker_token`, `chmod 600`), read by the wrapper —
  keeps it out of the unit file and out of `ps`.
- **The heartbeat is the poll** (§7): the worker's `claim` calls are what set
  `worker_online` on the VPS. Nothing extra to run.

**Models:** the Omen already has all ~46 GB of the correct weights under
`/home/<omen>/ComfyUI/models/`. **rsync them to your box over the SSH link** rather
than re-downloading:
`rsync -av --progress <omen>:/home/flipper/ComfyUI/models/ ~/ComfyUI/models/`.

> ⚠️ **Copy the Omen's OPS, not its `factory.py`.** The Omen's running `factory.py`
> is an **older ancestor** of this repo's `pet_factory/factory.py`: it hardcodes
> paths (`COMFY_HTTP`, `/home/flipper/...`), lacks the `breed_id` override and
> `schema_version` the integration needs, and still carries the abandoned
> `_flood_alpha`/`_needs_birefnet` flood-fill shortcut (its own comment says it was
> reverted as unreliable — the repo already deleted it). **Use this repo's code**
> (`pip install -e .` + `examples/worker.py`, which is env-configurable and
> integration-ready) and wrap it with the Omen's proven systemd + `run_worker.sh`
> recipe. Best of both: current code, battle-tested ops.
>
> Historical note the Omen's comments preserve: pet_factory was carved out of a
> larger `sheet_music_app`/`anim_studio` project specifically so the worker would
> **not** import anim_studio's background "stabilizer" thread (two stabilizers
> re-encoding the same loop `.webp` at once corrupts it). That's why `factory.py`
> is deliberately self-contained and why `_wait_stable()` guards every file read.

---

## 6. The queue contract (worker ⇄ Hetzner)

Exactly the protocol already implemented in `examples/queue_server.py` and
`examples/worker.py`. Endpoints:

**Public (browser / app):**
| Method + path | Purpose | Returns |
|---|---|---|
| `POST /api/submit` `{animal}` | enqueue a job | `{job_id}` (or `429` if queue full) |
| `GET /api/status/<job_id>` | poll progress | `{status, pct, msg, error, download_url?, breed_id?}` |
| `GET /api/result/<job_id>` | download the finished `.zip` | the file (or `404` if not ready) |
| `GET /api/health` | is a worker online? | `{worker_online: bool}` |

**Worker-only (header `X-Worker-Token: <secret>`):**
| Method + path | Purpose |
|---|---|
| `POST /api/worker/claim` | atomically take the oldest `queued` job → `{job_id, animal}` or `{}` |
| `POST /api/worker/progress` `{job_id, pct, msg}` | update the progress bar |
| `POST /api/worker/complete` (multipart: `job_id`, `breed_id`, `zip`) | upload the finished bundle |
| `POST /api/worker/fail` `{job_id, error}` | mark the job failed |

**Job lifecycle:** `queued → processing → done | error`.

**The worker loop** (`worker.py`, verbatim behavior): loop forever → `POST /claim`
→ if `{}` sleep 3s and retry → else `make_pet_zip(animal, progress_cb)` → on
success `POST /complete` with the zip → on exception `POST /fail`. The claim poll
**is also the heartbeat** — see §7.

---

## 7. "Which machine is alive?" — liveness by polling (the key behavior you asked for)

You asked for the server to poll which machines are alive and use whoever is up.
The design delivers that, but **inverts who polls whom**, which is what makes it
work without inbound access:

- Workers **announce themselves by polling.** Every `POST /api/worker/claim` (which
  a worker sends continuously — every ~3 s when idle) updates a server-side
  "last worker seen" timestamp (`queue_server.py`: `_STATE["worker_seen"] = time.time()`
  inside `_need_worker()`).
- `GET /api/health` reports `worker_online = (now - worker_seen) < WORKER_STALE_S`
  (90 s in the example). The frontend uses this to show/hide the "Make your own
  pet" control — an offline GPU tier just means the button isn't there, and the
  rest of the site is unaffected.
- **Why not have Hetzner health-check the machines directly?** That would require
  Hetzner to reach *into* the local network (needs their IPs, open ports, breaks on
  IP change, breaks behind NAT). Polling-outward needs none of that. This is a
  deliberate design choice, not a limitation.

### 7.1 Required hardening for "machines aren't always on"

The example's liveness is a **single global timestamp** ("is *any* worker online?").
For your not-always-on machines, that is not enough on its own. **This spec requires
one addition to the queue service before production:**

- **Stale-job reclaim.** If a worker claims a job (`status='processing'`) and then
  goes offline mid-generation (power off, network drop, crash), that job must not
  be stranded in `processing` forever. The queue must return a job to `queued` if
  it has been `processing` longer than a timeout **without a `progress` update**,
  so the *other* machine picks it up.
  - **The live reference already stores what's needed but does not act on it.** Its
    `jobs` table has `claimed_at` (stamped on claim — see §0), yet `worker_claim()`
    only ever pulls `status='queued'` rows; a `processing` job whose worker died is
    never revisited. The addition is: inside `claim`, *before* selecting the next
    queued job, run one `UPDATE jobs SET status='queued' WHERE status='processing'
    AND <staleness condition>`. So on the live schema this is genuinely a few lines,
    not a migration.
  - **Staleness signal.** The pipeline is ~3 min and posts progress at 10/35/60/85/100 %
    (`factory.py`), so "still `processing` but `claimed_at`/last-progress older than
    e.g. `max(pipeline_timeout, 10 min)`" is a reliable death signal. (Add a
    `progress_at` timestamp updated by `/api/worker/progress` if you want to
    distinguish "slow but alive" from "dead" more tightly than `claimed_at` alone.)
  - **Avoid duplicate pets on false reclaim.** If a worker was merely slow (not dead)
    and both it and the reclaiming worker finish, you get two pets. The
    `DATSME_INTEGRATION.md` schema guards this with a `dedupe_key`; the standalone
    reference has no such guard, so for Profile A either accept the rare double or
    add a `dedupe_key` / "first-completer-wins" check in `/api/worker/complete`.

This is a small, self-contained change to the queue service (a few lines in
`claim`), not a structural one. It is the one place the "intentionally minimal"
example must be hardened for this deployment. **It is in scope for this spec.**

### 7.2 Optional: per-worker visibility

If you later want "Machine A up / Machine B up" instead of just "≥1 worker up",
have each worker send a stable `worker_id` on `claim`, and track `last_seen` per
id. Not required for the "one of two is always up" goal; listed for completeness.

---

## 8. Failure modes — everything degrades to "the feature just waits or isn't there"

Mirrors and extends the table in `DATSME_INTEGRATION.md`.

| What happens | Effect | Site core affected? |
|---|---|---|
| **Both workers off** | jobs sit in `queued`; `health.worker_online=false`; button hidden or shows "workshop offline" | **No** — site fully up |
| **One worker off** | other worker drains the queue; throughput halves | **No** |
| **Worker dies mid-job** | stale-reclaim (§7.1) returns the job to `queued`; other worker retries; `dedupe_key` prevents a double pet | **No** |
| **Generation fails** (bad ComfyUI, OOM) | worker `POST /fail`; job → `error`; nothing written | **No** |
| **Invalid bundle at complete** | rejected by `validate_uploaded_bundle` before any pet is written (DatsMe integration) | **No** |
| **Queue full** | `POST /submit` → `429 busy`; user retries later | **No** |
| **Hetzner down** | the whole feature is down *and so is the site* — this is the one always-on dependency; standard uptime practices apply | site down (expected) |

The only single point of failure is Hetzner itself — which is correct, because it
*is* the always-on tier. The GPU tier is designed to be flaky.

---

## 9. Two deployment profiles (pick one)

Both share the exact same worker side (§5.2). They differ only in what runs on
Hetzner.

### Profile A — Standalone (fastest to validate)
- Hetzner runs `examples/queue_server.py` behind **nginx** HTTPS, as a **gunicorn +
  systemd** service, with the stale-reclaim hardening from §7.1.
- Results are `.zip`s on disk under `RESULTS/`.
- Good for: proving the end-to-end pipeline, a standalone "pet maker" site.
- Limitation: the example is single-process Flask + SQLite. Fine for low volume;
  not the path for high concurrency. **Run gunicorn with a single worker process**
  (`--workers 1`) so the in-process `_LOCK` and SQLite stay coherent — the example
  is not written for multi-process concurrency. Scale later via Profile B, not by
  adding gunicorn workers.

#### 9.1 Concrete layout (mirrors the live `hanzchau.com/petmaker` reference)

The running reference established these conventions; replicate them on your own box.

| Concern | Convention (adopt as-is) |
|---|---|
| OS / access | Ubuntu VPS; **SSH public-key only, no password login**. Each person/computer gets its own key appended to `~/.ssh/authorized_keys`; revoke by deleting the line. Prefer a non-root deploy user; if using `root`, treat access carefully. |
| App location | `/opt/apps/petmaker/` — the `pet_factory` repo (for `examples/queue_server.py`) + a venv. Each app is one dir under `/opt/apps/`. |
| Process manager | **gunicorn** bound to a local port (reference uses **5016**; the repo example defaults to 5017 — pick one and be consistent), supervised by **systemd** (`systemctl status petmaker`). |
| Reverse proxy | **nginx**. Config lives at `/etc/nginx/sites-available/default` **and is also copied to** `/etc/nginx/sites-enabled/default` — **edit BOTH**, then `nginx -t && systemctl reload nginx`. Proxy `location /petmaker` → the gunicorn port. |
| TLS | HTTPS on the public vhost (Let's Encrypt/certbot with nginx). |
| Public URL | `https://<your-domain>/petmaker`. |
| Deploy | **rsync** files up to `/opt/apps/petmaker/`, then `systemctl restart petmaker`. |

Illustrative systemd unit (`/etc/systemd/system/petmaker.service`):

```ini
[Unit]
Description=Pet Maker queue (Flask via gunicorn)
After=network.target

[Service]
WorkingDirectory=/opt/apps/petmaker
Environment=WORKER_TOKEN=<generate-a-long-random-secret>
# gunicorn imports the Flask app object `app` from examples/queue_server.py
ExecStart=/opt/apps/petmaker/venv/bin/gunicorn --workers 1 --bind 127.0.0.1:5016 examples.queue_server:app
Restart=always

[Install]
WantedBy=multi-user.target
```

Illustrative nginx location (in the default site, mirrored to sites-enabled):

```nginx
location /petmaker/ {
    proxy_pass http://127.0.0.1:5016/;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    client_max_body_size 64m;   # results/bundles; matches queue_server MAX_CONTENT_LENGTH
}
```

> Note the trailing-slash rewrite: `queue_server.py` serves routes at `/api/...`.
> Either mount it at a subpath consistently (proxy `/petmaker/` → `/`) or give it
> its own subdomain. Keep the worker's `QUEUE_URL` (§5.2) pointing at whatever
> public base the browser/worker actually reach (e.g.
> `https://<your-domain>/petmaker`).

### Profile B — Integrated into DatsMe (the real product)
- Hetzner runs DatsMe's FastAPI app; the queue becomes the routes/tables specified
  in `DATSME_INTEGRATION.md` (`pet_gen_routes.py`, `PetGenJob` in `social_models.py`,
  `pet_gen_enabled` feature flag in `system_config`, worker auth via hashed
  service-account key / HMAC).
- On `complete`, the pet is created with DatsMe's own `create_pet` → `write_assets`
  → ownership calls — the **same** path as the manual upload button, minus the
  credit charge. The stale-reclaim from §7.1 applies to `pet_gen_jobs`.
- Good for: the actual "Make your own pet" button in Settings → Pet.
- This spec's topology, GPU-locality, and liveness rules apply unchanged; only the
  storage/auth substrate differs.

---

## 10. Security

- **Worker auth on every worker endpoint.** Example: `X-Worker-Token` shared
  secret. Production/DatsMe: a **hashed** service-account key or HMAC-signed
  requests (`DATSME_INTEGRATION.md`) — store a hash, never plaintext, never commit
  the secret.
- **HTTPS everywhere.** Workers send the token and upload bundles; both must be
  encrypted in transit.
- **Bundle validation before write.** The `complete` path must run
  `validate_uploaded_bundle` (DatsMe) so a generated pet is never riskier than a
  hand-uploaded one.
- **Input clamp.** `animal` is trimmed/truncated (`[:60]`) at submit
  (`queue_server.py`, `factory.py`) — keep that.
- **Keep the `WORKER_TOKEN` out of the repo and out of transcripts.** It lives only
  in the systemd unit's `Environment=` on the server. (On the live reference it sits
  in `/etc/systemd/system/petmaker.service` in plaintext — acceptable for a shared
  secret that only authorizes queue claims, but rotate it if it ever leaks, and
  prefer the hashed/HMAC scheme for Profile B.)

---

## 10.5 Host sizing (lesson from the live reference)

The live `hanzchau.com` box is a **2 GB Hetzner CPX11 running 16 gunicorn apps**
(`/opt/apps/*`), and at inspection it was already ~800 MB into swap. Its console
history showed a past OOM storm — the kernel repeatedly killing a ~1.6 GB `python3`
process — cleared only by a reboot. `petmaker` itself was **not** the culprit (its
venv is just Flask + gunicorn, ~13 MB resident); the box was simply oversubscribed,
so any heavy transient (an `unattended-upgrade`, a spike in another app) tipped it
over. Takeaways for your own VPS:

- **Right-size the queue tier and give it headroom.** The queue is light (Flask +
  gunicorn + SQLite), but "light" ≠ "runs fine on a box crammed with 15 other apps."
  Don't co-locate the pet queue with a pile of unrelated services on a 2 GB box.
- **Keep swap configured** (the reference has a 4 GB swapfile) as a cushion, but treat
  swap usage as a warning sign, not a solution.
- **Enable persistent journald** (`Storage=persistent` in `journald.conf`). The
  reference does *not*, so every reboot erased the evidence of *which* process
  OOM'd — making the root cause unknowable after the fact. Persistent logs let you
  identify the offender next time.
- **The queue tier stays CPU/RAM-modest regardless of pet volume** — heavy work is
  always on the GPU workers, never here. So a small-but-uncrowded VPS is the right
  call, not a bigger shared one.

---

## 11. What to build, in order

1. **Stand up Hetzner (Profile A first)** on your own new VPS, following §9.1:
   provision Ubuntu → key-only SSH → deploy `pet_factory` to `/opt/apps/petmaker/`
   in a venv → gunicorn+systemd (`--workers 1`, port 5016) with `WORKER_TOKEN` →
   nginx dual-config `location /petmaker/` → certbot HTTPS. Verify
   `GET https://<domain>/petmaker/api/health` returns `{worker_online:false}`
   (no worker yet).
2. **Add stale-job reclaim** (§7.1) to the queue service.
3. **Build one worker** on the local 3090 box: ComfyUI + models + VideoHelperSuite
   (the ~40–50 GB download — note these are **not** currently on the machine; the
   existing ComfyUI there is a different SDXL/LoRA stack) + `pip install -e .` +
   `worker.py` with `QUEUE_URL`/`WORKER_TOKEN`. Verify a pet end-to-end.
4. **Clone the worker** onto the second machine. Confirm: with both up, two jobs
   run in parallel; kill one mid-job, confirm the other reclaims it.
5. **(Later)** Add the second card on each box as a second worker; and/or migrate
   Hetzner to Profile B (DatsMe integration) per `DATSME_INTEGRATION.md`.

---

## 12. Open decisions (not yet made)

- **Profile A vs B** to launch with.
- **Result retention** on Hetzner (how long `.zip`s live before cleanup).
- **`MAX_QUEUED`** depth (example default 15) given only 1–2 workers.
- **Whether to run one or two workers per machine** (one 3090 vs both) at launch.

---

### Appendix — repo grounding

Every claim above traces to code in this repo:
- Worker loop, heartbeat-by-poll, upload-on-complete: `examples/worker.py`.
- Queue endpoints, `worker_seen` liveness, `MAX_QUEUED`, `WORKER_STALE_S`,
  SQLite: `examples/queue_server.py`.
- GPU-locality (reads ComfyUI output off local disk), pipeline stages, progress
  fractions, bundle format: `pet_factory/factory.py`.
- "never imported by DatsMe", integrated routes/tables/flag/auth, same-as-upload
  write path, failure table: `DATSME_INTEGRATION.md`.
- Models, custom node, VRAM, timing: `README.md`.

**What the repo does NOT provide (and this spec adds):** any Hetzner/host-specific
runbook, HTTPS/domain/service-management setup, the multi-worker not-always-on
resilience story, and the stale-job reclaim hardening (§7.1).

**External source for the host conventions (§9.1):** the access/orientation doc for
the live `hanzchau.com/petmaker` deployment (Hetzner Ubuntu VPS; nginx dual
sites-available/enabled config; `/opt/apps/<name>/` apps under gunicorn+systemd;
`petmaker` on port 5016; rsync-then-`systemctl restart` deploy; key-only SSH). That
deployment is the proof-of-concept this spec generalizes to a two-worker,
not-always-on setup on a self-owned box.

**Live-server verification (§0, §7.1 note, §10.5), read 2026-07-09** directly off the
running VPS via SSH: `/opt/apps/petmaker/petmaker_server.py` (endpoints, `_require_worker`
token+heartbeat, `worker_online`/90 s health, `MAX_QUEUED`, the `jobs` schema incl.
`claimed_at`/`done_at`), the `petmaker.service` systemd unit (gunicorn `--workers 1`,
port 5016), the venv's `pip list` (Flask + gunicorn only, no ML libs), `results/`
(21 finished `.zip`s), and the host's memory/OOM state (2 GB, 16 apps, swap pressure).
These sections are ground truth, not inference. Note this reference server is Jeff's
shared box — the spec's *target* is markly's own VPS.
