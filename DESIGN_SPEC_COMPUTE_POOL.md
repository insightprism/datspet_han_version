# Design Spec — Compute Pool: an app-callable GPU/CPU pool over your own machines

**Status:** design. Generalizes the proven pet_factory queue+worker pattern into a
standalone, reusable **compute pool** that *any* application can call, backed by
whichever of your networked machines are currently up.
**Relationship to pet_factory:** pet_factory stops being a bespoke queue and becomes
**the first client + the first registered task** of this pool. Nothing about its
pipeline changes; only *where the job comes from* changes.
**Target fleet today:** dual-gpu (2× RTX 3090), Omen (1× RTX 3090, mostly-on),
Alienware (laptop) — and any machine added later, GPU or CPU.

> **Why this is an extraction, not a rewrite.** The live `hanzchau.com/petmaker`
> system already proves every core mechanism: an always-on VPS holding a queue,
> home machines that *poll out* and run work on their own GPU, liveness by "who
> polled recently," and results uploaded back. This spec keeps all of that and
> generalizes three things: (1) jobs become **typed tasks** instead of "an animal
> string", (2) workers **advertise capabilities + resources** instead of being
> hardwired to one pipeline, (3) the scheduler **matches** jobs to capable, free
> workers. See the pet_factory deployment spec (`DESIGN_SPEC_HETZNER_LOCAL_GPU.md`)
> for the ground-truth mechanics this builds on.

---

## 1. Goal & shape

**One sentence:** an application submits `{task, params}` to a central dispatcher and
gets a result back, and the work runs on whichever networked machine is up, advertises
that task, and has the resources for it — with no app knowing which machine ran it.

```
   App A ─┐                          ┌── worker: dual-gpu  (gpu×2, 24GB each)
   App B ─┤   POST /jobs {task,      │
   App C ─┴──▶  params, needs} ─────▶│   DISPATCHER  ◀──poll── worker: omen   (gpu×1, mostly-on)
              GET /jobs/<id> ◀───────│  (Hetzner VPS, always-on)
              GET /jobs/<id>/result  │        ▲       ◀──poll── worker: alienware (cpu, laptop)
                                     └────────┘       ◀──poll── worker: <future box>
   Apps submit + poll (HTTPS)          Workers dial OUT and pull matching jobs
```

**The four locked design decisions:**
- **Named tasks.** Workers register capabilities (`pet_factory`, `whisper`, `sdxl`, …).
  No arbitrary code execution — a job names a task the worker already has installed.
- **Hetzner VPS dispatcher.** Always-on, CPU-only. Survives any home machine being off.
- **Workers poll (dial out).** No inbound access, no port-forwarding, works behind NAT.
  Liveness = who polled recently.
- **Capability + free-first scheduling**, **poll-for-result**, **GPU+CPU resource model
  from day one**.

---

## 2. Core concepts

### 2.1 Task
A named unit of work a worker knows how to run, e.g. `pet_factory`. Identified by
`task` name + optional `version`. A task declares:
- its **required resources** (see 2.3) — e.g. `{gpu: 1, vram_gb: 20}` for pet_factory,
  or `{cpu: 4}` for a CPU task;
- its **params schema** (what the app must pass);
- its **result kind** (bytes/file, JSON, or a URL).

Tasks are **content**, added as self-contained handlers (see §6 plugin model). Adding a
task must not modify the dispatcher or other tasks.

### 2.2 Worker
A process on a machine that:
- **advertises** `{worker_id, tasks: [...], resources: {...}, labels: {...}}` on every poll;
- **polls** the dispatcher for a job matching its advertised tasks/resources;
- **runs** the task locally, streaming progress;
- **uploads** the result.

Workers are **interchangeable** for a given task — that's what makes "use whoever's up"
work. A machine can run multiple workers (e.g. one per GPU: `CUDA_VISIBLE_DEVICES=0/1`).

### 2.3 Resource model (GPU + CPU, and GPU *backend*, from day one)
Both workers and jobs speak the same resource vocabulary, so CPU jobs — and
non-CUDA GPUs — slot in with no redesign:

```
resources (what a worker HAS):          needs (what a job REQUIRES):
  gpu_count: 2                            gpu: 1                 # 0 = CPU-only job
  gpu_vram_gb: 24        # per card       vram_gb: 20            # per card (T1) / combined (T2/T3)
  local_gpus: 2          # cards on THIS  gpus_same_host: 2      # T2: N cards on one machine
  local_vram_total_gb: 48   #  machine    gpus_multi_host: 2     # T3: N cards across machines (future)
  nvlink: true|false                      gpu_backend: "cuda"    # cuda | metal | rocm | none
  gpu_backend: "cuda"                     cpu: 4
  cpu_cores: 24                           ram_gb: 8
  ram_gb: 62                              labels_any: {...}      # optional extra constraints
  labels: {cuda:"12", vendor:"nvidia"}
```

A job is **eligible** for a worker iff the worker advertises the task AND
`worker.resources ⊇ job.needs`. Two dimensions are decided here:

- **GPU vs CPU** — a job with `gpu: 0` runs anywhere with the CPU/RAM; `gpu: 1` needs a
  GPU worker.
- **GPU *backend* (critical for a heterogeneous fleet)** — `gpu_backend` distinguishes
  **NVIDIA/CUDA** from **Apple/Metal** from **AMD/ROCm**. A CUDA-only task (like
  `pet_factory`, whose ComfyUI models are `fp8` CUDA builds and whose birefnet cutout
  uses `CUDAExecutionProvider`) declares `gpu_backend: "cuda"` and will **never** be
  routed to a Metal or CPU worker. An Apple-native task (a Metal/MPS Whisper, a CoreML
  model) declares `gpu_backend: "metal"`. This is what lets the pool safely include an
  M-series Mac *without ever mis-handing it a CUDA job it can't run* (see §2.5).

### 2.4 Job
`{id, task, params, needs, status, progress, result_ref, worker_id, timestamps}`.
Lifecycle: `queued → assigned → running → done | error | reclaimed`.

### 2.5 The actual fleet (verified 2026-07-09) and what each can serve

The `gpu_backend` label matters because this fleet is genuinely heterogeneous:

| Machine | GPU | VRAM | Backend | pet_factory? | Role in the pool |
|---|---|---|---|---|---|
| **dual-gpu** (this box) | 2× RTX 3090 | 24 GB ea | cuda | ✅ (2 workers, one per card) | primary CUDA workers |
| **Omen** (mostly-on) | 1× RTX 3090 | 24 GB | cuda | ✅ (already live) | primary CUDA worker |
| **Alienware** (laptop) | 1× RTX 3060 Mobile | **~6 GB** | cuda | ⚠️ **too little VRAM** for the 14B Wan models (needs ~20 GB); good for *lighter* CUDA tasks | small CUDA worker (driver fixed 2026-07-10) |
| **OakHost Mac** (`oakmac`, M-series) | Apple integrated | unified | **metal** | ❌ (no CUDA; would need a full Metal port) | Metal / CPU-class worker only |

Two things this table encodes:

- **Alienware has a real, usable NVIDIA GPU — just a *small* one.** It's an RTX 3060
  Mobile (~6 GB), CUDA-capable. It is **not** CPU-only. But 6 GB can't hold the pet_factory
  14B Wan experts (~13 GB each), so it advertises `gpu_vram_gb: 6` and pet_factory's
  `needs.vram_gb: 20` **excludes it automatically** — no special-casing, the resource
  match does it. It *can* serve lighter CUDA tasks (SD 1.5, small models, CPU work).
  - **Status (2026-07-10): driver FIXED — now a working CUDA worker.** `nvidia-smi` reports
    the RTX 3060 Laptop GPU on driver 580, module loaded. (The fix was purging the stale 550
    driver so only 580 remained; it briefly wedged the GNOME session, cleared by
    `systemctl restart gdm` over SSH.) It now advertises its ~6 GB and matches lighter CUDA
    jobs; pet_factory's `vram_gb: 20` still excludes it automatically. If the GPU ever drops
    again, the worker's resource auto-detection degrades it to `gpu_count: 0` gracefully.
- **The M-series Mac has a GPU, but the wrong kind for CUDA.** Apple Silicon exposes its
  GPU via **Metal/MPS**, not CUDA. pet_factory's CUDA-built models and `CUDAExecutionProvider`
  cutout can't run on it without a Metal port (a research effort, not a config change). In
  the pool it advertises `gpu_backend: "metal"` and is eligible only for Metal/CPU tasks —
  correctly excluded from every `gpu_backend:"cuda"` job. This is the payoff of the backend
  label: the Mac contributes what it *can* (Apple-native ML, CPU work) and is never handed
  work it can't do.

---

## 3. The dispatcher (Hetzner VPS, always-on, CPU-only)

Mirrors petmaker's role but generalized. Holds the job store, matches jobs to workers,
stores results, tracks liveness. **No task code runs here** — it never needs a GPU and
never imports a task's dependencies. (Same discipline as pet_factory: the VPS must stay
light. See the sizing lesson in `DESIGN_SPEC_HETZNER_LOCAL_GPU.md` §10.5.)

### 3.1 App-facing API (public)
| Method + path | Purpose | Returns |
|---|---|---|
| `POST /api/jobs` `{task, params, needs?}` | submit a job | `{job_id}` (or `429` if pool saturated) |
| `GET /api/jobs/<id>` | poll status/progress | `{status, progress, msg, error, result_url?}` |
| `GET /api/jobs/<id>/result` | download the result | bytes/JSON (or `404` until done) |
| `GET /api/pool` | fleet visibility | `{workers:[{id, tasks, resources, online, busy}], queue_depth}` |
| `GET /api/tasks` | discoverability | list of registered tasks + their needs/params schema |

`needs` is optional — if omitted, the dispatcher fills it from the task's declared
defaults (§2.1). Auth: an **API key per client app** (`X-App-Key`), so you can see/limit
who submits what.

### 3.2 Worker-facing API (token-guarded, `X-Worker-Token`)
| Method + path | Purpose |
|---|---|
| `POST /api/worker/poll` `{worker_id, tasks, resources, labels}` | heartbeat + claim: advertise self, get one matching job `{job_id, task, params}` or `{}` |
| `POST /api/worker/progress` `{job_id, pct, msg}` | progress updates |
| `POST /api/worker/complete` (multipart/JSON: `job_id`, result) | upload result → `done` |
| `POST /api/worker/fail` `{job_id, error}` | mark `error` |

> **`/poll` is claim + heartbeat + registration in one call** — the generalization of
> petmaker's `/api/worker/claim`. The worker sends its full capability profile every
> poll, so the dispatcher always has a fresh view of the fleet with zero extra plumbing,
> and registration is automatic: a new machine appears in the pool the instant it first
> polls. This is what makes "add more computers later" require no central change.

### 3.3 Scheduling (capability + free-first)
On each `/api/worker/poll`, the dispatcher:
1. records `worker_seen[worker_id] = now` and the advertised profile;
2. selects the **oldest `queued` job** whose `task` the worker advertises **and** whose
   `needs ⊆ worker.resources`;
3. atomically marks it `assigned`/`running`, stamps `claimed_at` + `worker_id`, returns it;
4. if none match, returns `{}` (worker sleeps ~3 s, polls again).

"Free-first" falls out naturally: a busy worker isn't polling for new work (it's running
a job), so only free workers pull. No load-balancer needed. If two workers can serve a
job, whichever polls first gets it.

### 3.4 Liveness & the fleet view
- `worker_online(id) = (now - worker_seen[id]) < STALE_S` (e.g. 90 s), **per worker_id** —
  a genuine improvement over petmaker's single global flag. `GET /api/pool` lists each
  machine as up/down/busy, so an app (or a dashboard) can show "3 GPUs online, 1 busy."
- **Detecting which computer is up = who polled recently.** No health-checking into the
  machines (they're behind NAT); they announce themselves by polling. Exactly your
  requirement, done the robust way.

### 3.5 Stale-job reclaim (required — the not-always-on guarantee)
If a worker claims a job then goes offline mid-run, the job must not be stranded. On each
poll, before matching, the dispatcher re-queues any job that is `running` but whose last
progress/`claimed_at` is older than `max(task_timeout, N min)`. Another eligible worker
then picks it up. (This is the §7.1 hardening from the pet_factory spec, now a
first-class dispatcher feature — essential because your fleet is deliberately
intermittent.) A `dedupe`/idempotency key on `complete` prevents a double result if the
original worker was merely slow, not dead.

### 3.6 Allocation model — how much GPU a job can get (single-GPU → multi-GPU → multi-machine)

A common expectation is *"if a job needs 40 GB and no single card has it, the pool will
combine two machines' GPUs."* **It will not — and neither does almost any simple system,
because summing VRAM across machines is a distributed-computing problem, not an allocation
policy.** Be clear-eyed about what "needs 40 GB" means and which tier applies.

**First, the crucial distinction — two very different "needs 40 GB" cases:**
- **Throughput ("I have many jobs")** — you want all GPUs busy at once. The pool does this
  natively: N jobs → N workers → all run in parallel. This is *parallelism across jobs*, and
  it needs nothing beyond §3.3. **This is what "use both machines in parallel" almost always
  actually means.**
- **One big job ("this single model needs 40 GB")** — a model too large for any one 24 GB
  card, that must run as one computation spanning multiple GPUs. This is the hard case, and
  it does **not** come for free. See the tiers below.

**The pool matches whole workers/GPUs to jobs; it does not silently pool VRAM.** A job
declares its allocation tier explicitly:

| Tier | `needs` example | What the scheduler does | Feasible on this fleet? |
|---|---|---|---|
| **T1 — single-GPU** (default) | `{gpu: 1, vram_gb: 20}` | assign to one worker/one card whose VRAM ≥ need | ✅ the core case; pet_factory is here |
| **T2 — multi-GPU, same host** | `{gpus_same_host: 2, vram_gb: 40}` | assign the **machine**, reserve N cards on it; the task runs tensor/pipeline-parallel across the local cards | ✅ **the realistic path to ~40 GB**: `dual-gpu`'s 2× 24 GB = 48 GB, one model, NVLink/PCIe-local |
| **T3 — multi-machine, distributed** | `{gpus_multi_host: 2, vram_gb: 40}` | co-reserve 2 workers on 2 machines, hand both a rendezvous (master addr/port + rank); the task must be a true multi-node launcher | ⚠️ possible but **slow + complex**; scoped as future (see below) |

**T1 (single-GPU)** — already fully specified (§3.3). Nothing new. A `vram_gb: 40` job at
T1 matches no card here and simply queues (never silently split). The right fix for such a
job is to submit it as T2, not to expect T1 to aggregate.

**T2 (multi-GPU, same host)** — the practical way to reach ~40 GB with your hardware, and a
**modest** extension:
- A worker advertises its *local* GPU set, not just a count:
  `resources.local_gpus: 2`, `resources.local_vram_total_gb: 48`, `resources.nvlink: true|false`.
- A T2 job requests `gpus_same_host: N`. The scheduler matches it to a machine with ≥ N free
  local cards and enough combined VRAM, and hands the worker a job that pins those cards
  (`CUDA_VISIBLE_DEVICES=0,1`).
- **The task itself must be multi-GPU-aware** — the pool provides the GPUs and the pinning;
  the *handler* (e.g. a vLLM/`device_map="auto"`/DeepSpeed launcher) does the actual layer
  splitting. The pool cannot shard an arbitrary single-GPU task.
- On `dual-gpu`, this needs the run one worker that owns *both* cards for T2 jobs (rather
  than two independent one-card workers). Design note: a machine can register **either** as
  two T1 workers (max throughput, one job per card) **or** as one T2-capable worker (one big
  job across both cards) — not both at once for the same cards. Choose per machine, or run a
  small local arbiter. Simplest start: `dual-gpu` = one T2-capable worker advertising both
  cards; it still accepts T1 jobs using one card when no T2 job is queued.

**T3 (multi-machine, distributed)** — **out of scope for the initial build; documented so the
boundary is explicit.** To run one model across `dual-gpu` + `omen` over the LAN, the pool
would have to: co-schedule (atomically reserve a worker on *each* machine, or the job
deadlocks waiting), establish a rendezvous (`torchrun --nnodes=2 --master_addr ...`), and the
task must be a genuine multi-node program. The killer caveat is **interconnect**: cross-machine
GPUs exchange activations over 1–10 GbE, ~100× slower than the NVLink/PCIe that memory-splitting
assumes — so a model that *barely* fits across two machines often runs unacceptably slowly.
Add T3 only for a concrete model that truly cannot fit in `dual-gpu`'s 48 GB (T2), and expect
real engineering (co-scheduling, rendezvous, partial-failure handling when one node drops
mid-job).

**Rule of thumb for sizing on this fleet:** ≤24 GB → T1 (any card). 24–48 GB → **T2 on
`dual-gpu`** (two local cards). >48 GB → either quantize/shard the model to fit T2, or accept
the cost of T3. "Two separate machines summed into one 48 GB pool" is T3, not T2 — the 48 GB
figure only holds *within* `dual-gpu`.

---

## 4. The worker (one install, runs on any machine — GPU or CPU)

A single generic worker program. It is **task-agnostic**: it discovers which tasks it can
run from the task handlers installed on that machine (§6), probes its own resources, and
polls. Adding a machine to the pool = install the worker + whatever task handlers you want
it to serve + point it at the dispatcher.

**Config (env):**
- `POOL_URL=https://<dispatcher-domain>` — where to poll.
- `WORKER_TOKEN=<secret>` — shared worker secret.
- `WORKER_ID=<stable-id>` — e.g. `omen-gpu0` (defaults to hostname+GPU index).
- `WORKER_TASKS=pet_factory,whisper` — which installed tasks to advertise (or `auto`).
- `CUDA_VISIBLE_DEVICES=0` — pin to one card; run a second worker with `=1` for the 2nd.

**Resource auto-detection at startup:** query `nvidia-smi` for GPU count + VRAM +
`gpu_backend: "cuda"` (or detect Apple/Metal via `system_profiler`/`torch.backends.mps`,
AMD/ROCm via `rocminfo`), `nproc` for cores, `/proc/meminfo` for RAM; advertise them.
A machine with no working GPU (e.g. the Alienware while its NVIDIA driver is broken, or
a pure CPU box) detects `gpu_count: 0` and only matches CPU jobs — no special-casing. The
same auto-detection means a machine "self-describes" correctly the moment its GPU comes
back (driver fixed), with no config edit.

**Ops recipe:** reuse the **exact** proven pattern from the live Omen worker
(`DESIGN_SPEC_HETZNER_LOCAL_GPU.md` §5.3): systemd service, `Restart=always`,
`run_worker.sh` wrapper setting `LD_LIBRARY_PATH`/env, token in a file. For tasks that
need ComfyUI (like pet_factory), keep the `comfyui.service` → `worker.service` ordering.
Don't reinvent it — it already survives dispatcher downtime by design.

**The worker loop (generalized from the live worker.py):**
```
loop forever:
    job = POST /api/worker/poll {worker_id, tasks, resources, labels}
    if not job: sleep 3; continue
    handler = registry[job.task]                    # local task handler (§6)
    try:
        result = handler.run(job.params, progress_cb)   # runs on THIS machine's GPU/CPU
        POST /api/worker/complete {job_id, result}
    except e:
        POST /api/worker/fail {job_id, error=e}
```

---

## 5. How an application calls the pool

Any app (a website backend, a script, DatsMe, a future service) is a thin client:

```python
job = POST(f"{POOL_URL}/api/jobs", headers={"X-App-Key": KEY},
           json={"task": "pet_factory", "params": {"animal": "red panda"}})
jid = job["job_id"]
while True:
    s = GET(f"{POOL_URL}/api/jobs/{jid}")
    if s["status"] in ("done", "error"): break
    show(s["progress"], s["msg"]); sleep(2)
result = GET(f"{POOL_URL}/api/jobs/{jid}/result")   # the .zip bytes
```

The app never knows or cares that dual-gpu, the Omen, or a future box ran it. **pet_factory
becomes exactly this** — the petmaker web page's "submit animal → poll → download zip"
flow is unchanged; only its backend now points at the general pool with `task:"pet_factory"`.

### 5.1 Migration: pet_factory → first task on the pool
- Wrap the existing `make_pet_zip(animal, on_progress, breed_id)` as a task handler
  `tasks/pet_factory.py` advertising `needs={gpu:1, vram_gb:20}` and params `{animal, breed_id?}`.
- Point the petmaker web page's submit/status/result at the pool's `/api/jobs*`.
- Retire the bespoke `petmaker_server.py` queue — its job is now the generic dispatcher.
- Net effect: same UX, but now the *same pool* can also run other tasks and other apps.

---

## 6. Plugin model — how tasks and workers grow (the engine/content boundary)

The whole point is that **adding a task or a machine never touches the engine.**

- **A task = one self-contained handler file + one registry entry.**
  `tasks/<name>.py` exports `run(params, progress_cb) -> result`, plus metadata
  (`needs`, `params_schema`, `result_kind`). A registry maps `name -> handler`.
  The dispatcher only ever reads the metadata (to validate `needs`/params); it never
  imports the handler's heavy deps. The worker imports only the handlers installed on
  its machine.
- **Adding a task** (`whisper`, `sdxl`, a CPU `ffmpeg-transcode`): drop in
  `tasks/whisper.py` + registry entry, install its deps on whichever workers should serve
  it, add `whisper` to those workers' `WORKER_TASKS`. **No dispatcher change, no other
  task touched.**
- **Adding a machine:** install the worker + the task handlers you want it to run, set
  `POOL_URL`/`WORKER_TOKEN`/`WORKER_ID`, start it. It self-registers on first poll and
  starts pulling matching jobs. **No central reconfiguration.**
- **Enforcement:** a registry guard test fails the build on a half-formed task entry
  (missing `needs`/`run`/schema), so the pool can't ship a broken task.

This directly satisfies the four test questions: a new task/worker/app requires **no**
engine change; a bug in one task is isolated to that handler and the worker running it.

---

## 7. Security & trust

- **No arbitrary code** — apps name a pre-installed task; they cannot ship code to run.
  This is the core safety property of the "named tasks" choice.
- **Two token classes:** per-app `X-App-Key` (who may submit, rate-limit, revoke) and a
  worker `X-Worker-Token` (who may claim/complete). Store hashes, never plaintext; keep
  tokens in files/systemd env, never in the repo or a transcript.
- **HTTPS everywhere** — apps and workers both send secrets and payloads.
- **Result/param size caps** on the dispatcher (like petmaker's 64 MB `MAX_CONTENT_LENGTH`).
- **Private fleet assumption:** these are your own trusted machines. If the pool ever
  accepts third-party workers, revisit isolation (containers/§ future).

---

## 8. What this buys you (vs. the pet-specific queue today)

| Capability | Today (petmaker) | Compute pool |
|---|---|---|
| Run pet generation on a home GPU | ✅ | ✅ (as task `pet_factory`) |
| Run *other* GPU tasks | ❌ rewrite | ✅ add a handler |
| Multiple apps sharing the GPUs | ❌ | ✅ per-app keys |
| Multiple GPU machines, auto-balanced | ⚠️ possible, untested | ✅ first-class |
| Add a machine with zero central config | ❌ | ✅ self-registers on poll |
| Per-machine "who's up" visibility | ❌ single global flag | ✅ `/api/pool` |
| CPU-only jobs / CPU-only boxes | ❌ | ✅ resource model |
| Survives any machine (or the app) being off | ✅ for petmaker | ✅ generalized |

---

## 9. Build order

1. **Extract the dispatcher** from `petmaker_server.py`: generalize `submit`→`/api/jobs`,
   `claim`→`/api/worker/poll` (with capability/resource matching + per-worker liveness),
   add the reclaim loop (§3.5) and `/api/pool`. Deploy on the VPS exactly like petmaker
   (nginx + gunicorn `--workers 1` + systemd; `DESIGN_SPEC_HETZNER_LOCAL_GPU.md` §9.1).
2. **Write the generic worker** + the task-registry plugin model (§6), with resource
   auto-detection. Reuse the Omen's systemd/`run_worker.sh` ops recipe verbatim.
3. **Port pet_factory to a task handler** (§5.1) and cut the petmaker page over to
   `/api/jobs`. Prove parity with the current system on one machine.
4. **Bring up the fleet (T1 first):** run the worker on dual-gpu as **two T1 workers, one
   per 3090** (max throughput to start), keep the Omen worker, add Alienware as a small-CUDA
   worker once its driver is fixed (CPU-only until then). Verify `/api/pool` shows all of them,
   jobs route to free/eligible workers, and killing a worker mid-job triggers reclaim.
5. **(Later) add T2** (§3.6) when a job actually needs >24 GB: reconfigure dual-gpu as one
   T2-capable worker owning both cards, and give a task a multi-GPU handler. Also add a second
   task (e.g. `whisper` or a CPU transcode) to prove the plugin model, and a small dashboard
   over `/api/pool`.

---

## 10. Open decisions

- **Job priorities / fairness** across apps (FIFO now; add priority lanes later?).
- **Result retention & storage** (VPS disk vs. object storage for large outputs).
- **Container tasks** as a future task *kind* (for tasks whose deps are painful to install
  per-worker) — deferred; named handlers cover the near term.
- **Webhook results** as an optional addition to polling (for very long jobs).
- **GPU sharing within a machine** (two small jobs on one 24 GB card) — start with
  one-job-per-GPU (via `CUDA_VISIBLE_DEVICES` per worker); revisit if utilization warrants.
- **`dual-gpu` registration mode (§3.6):** two T1 workers (max throughput, one job per card)
  vs. one T2-capable worker owning both cards (one big ~40 GB job). Decide per real workload;
  a small local arbiter that switches modes based on the queue is a possible later refinement.
- **T3 multi-machine distributed jobs (§3.6):** deferred. Only worth building for a concrete
  model that cannot fit in `dual-gpu`'s 48 GB via T2, given the cross-machine interconnect cost.

---

### Appendix — grounding

Built directly on the verified live system and the fleet mapped 2026-07-09:
- The queue+worker+poll+liveness+reclaim mechanics: `DESIGN_SPEC_HETZNER_LOCAL_GPU.md`
  (§0 live reference, §5.3 worker ops recipe, §7 liveness, §7.1 reclaim, §9.1 host conventions).
- The proven worker ops (systemd ordering, `run_worker.sh` CUDA-lib borrowing,
  `Restart=always`, token-in-file): the live Omen worker.
- The fleet (dual-gpu 2×3090, Omen 1×3090 mostly-on, Alienware RTX 3060 Mobile ~6 GB
  [driver currently broken], OakHost M-series Mac = Metal-only) and their
  interconnect: the SSH access set up this session.
- pet_factory's callable surface (`make_pet_zip(animal, on_progress, breed_id)`) becoming
  the first task handler: `pet_factory/factory.py`.
