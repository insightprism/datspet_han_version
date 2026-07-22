# SPEC — Pool job-lifecycle support (DatsPet side)

> **Status: DRAFT / FOR REVIEW — 2026-07-21.** App-side companion to the pool-side spec
> `../shared_gpu_cpu/docs/pet_factory_watchdog_failure_fix_spec.md` (read it first; section refs
> below like *pool §9.1* point there). That spec hardens the **pool**; this one lists what
> **DatsPet** (`pet_factory/` engine, `pool_handler/`, `webui/` app-server, `web/` frontend) must
> do so the pool's new self-heal, cancel, and abandonment features actually work end-to-end.
> Nothing here ships without approval.

## 0. Why DatsPet is involved at all

The pool is application-independent — it owns timers, cancellation transport, and terminal states,
but it **cannot** see inside a `pet_factory` run, cannot know a DatsPet user, and cannot emit
progress a handler never produces. Four things therefore have to happen on this side. Two are
defects the pool investigation surfaced in **our** code (A, B); two are the app half of new pool
features (C, D).

| Item | What | Where | Depends on pool |
|---|---|---|---|
| **A** | birefnet GPU fail-fast (stop silent CPU fallback) | `pet_factory/factory.py` | no |
| **B** | per-frame progress during cutout/pack | `pet_factory/factory.py`, `pool_handler/pet_factory_handler.py` | enables *pool §9.1* |
| **C** | consumer heartbeat / abandonment | `webui/` (+ `web/` client) | *pool §10.6* endpoints |
| **D** | user **Stop** button | `webui/`, `web/` | *pool §9.4/§11* cancel |

---

## A. birefnet must fail fast on a GPU node, not silently run on CPU

**Root cause of the 2026-07-21 incident (pool §3):** `_rembg()` (`factory.py:80`) requests
`["CUDAExecutionProvider","CPUExecutionProvider"]`; when the CUDA provider can't load, onnxruntime
does **not** raise — it silently returns a CPU session. birefnet then runs ~10× slower and blows
the pool's 900 s watchdog. The current code's `except` branch never fires (no exception is thrown),
so the "using CPU" path is dead code in this failure mode.

**Change:**
0. **Load the CUDA libs (the enabling half of pool §4.A).** Before creating the session, call
   `onnxruntime.preload_dlls()`. onnxruntime 1.22+ ships CUDA/cuDNN as separate `nvidia-*-cu12`
   wheels but does NOT add them to the loader path on import — without this preload the CUDA
   provider `.so` cannot `dlopen` `libcublasLt.so.12` and silently falls back to CPU, **even with
   the wheels installed**. Wrap it in try/except (no-op / harmless on a CPU-only node). *Verified
   live 2026-07-21: this is the step that actually flipped birefnet to GPU.*
1. Add a `require_gpu` intent (read from env, e.g. `PET_FACTORY_REQUIRE_GPU=1`, which the pet
   worker units set on GPU nodes). Thread it from `pool_handler/pet_factory_handler.run()` →
   `make_pet_zip(..., require_gpu=…)` → `_rembg()`.
2. In `_rembg()`, after creating the session, inspect `inner_session.get_providers()`. If
   `require_gpu` and the providers are CPU-only, **raise** a clear error
   (`"birefnet CUDA provider failed to load — GPU cutout unavailable; check onnxruntime CUDA libs"`).
   Keep the CPU path for genuinely CPU-only nodes (`require_gpu` false).
3. **Watch the masking trap:** `pack_datsme_bundle.prep()` wraps `_remove_bg` in
   `try/except → full-opaque alpha` (`factory.py:331-335`). A raise from *inside* the per-frame
   loop would be swallowed there and silently yield un-cut (opaque) pets. So the assertion must run
   **once at session init** (in `_rembg`, before any frame loop) and propagate out of the handler —
   not per frame. Verify the raise is not caught by `prep`'s except.

**Effect:** a healthy GPU node runs the cutout on GPU (verified live: **14 s** vs. 10+ min on CPU);
a mis-provisioned one fails in ~2 s with a legible reason instead of a 15-min watchdog death. (The
CUDA-lib install into the node's `.pool` venv is *pool §4.A Part 1*, an ops action; the preload +
fail-fast here are *Part 2*, code.)

---

## B. Emit progress during the cutout/pack stage

**Problem:** `make_pet_zip` calls `prog("Cutting out backgrounds & packing…", 0.85)` once, then
hands off to `pack_datsme_bundle` (`factory.py:571`), which runs the **entire** birefnet loop
(`prep()` over every frame of every pose) **silently**. Consequences:
- the UI bar freezes at 85 % for the whole cutout;
- the pool worker sees no progress beat for that span, so the planned **inactivity/stall watchdog
  (pool §9.1)** cannot tell "wedged" from "slowly working" — this stage would either false-kill or
  force a loose stall timeout.

**Change:** thread an optional progress callback into `pack_datsme_bundle` (default `None`, so the
CLI and non-pool callers are unaffected) and call it per frame (or per pose). `make_pet_zip` maps
that sub-progress into the `0.85→~0.99` band and forwards it to `on_progress`; the handler already
relays `on_progress → ctx.progress` (`pet_factory_handler.py:90-92`). Net: the bar advances during
cutout, and the pool gets a beat often enough to run a **tight** `stall_timeout_s`.

**Contract note (opt-in, pool §14.6):** until this ships, `pet_factory` leaves
`TaskMeta.stall_timeout_s = None` → the pool's stall watchdog/reclaim stay **off** for it (only the
wall-clock `timeout_s` applies; zero regression). *After* B ships, declare a value ≥ its slowest
inter-beat gap (~180 s starting point) to engage the tighter timers.

---

## C. Consumer heartbeat / abandonment (app half of pool §10.6)

The pool will auto-cancel a job whose consumer stops renewing a lease (pool §10.6). DatsPet is that
consumer. The elegant part: **the liveness signal already exists** — the frontend polls
`GET /api/job/{job_id}` throughout a build (`webui/app.py:1278`). That poll *is* the device
heartbeat; no new iOS mechanism is needed for the common case.

**Change (app-server, `webui/`):**
1. In the `GET /api/job/{job_id}` handler, stamp `Job.last_client_poll_at = now` (under
   `JOBS_LOCK`).
2. The build runs on a background thread already driving `pool_client.drive_to_result` (a 4 s poll
   loop). Give that loop a per-tick hook (e.g. `drive_to_result(..., on_tick=…)`; keep the
   liveness logic in `webui/`, not in `pool_client`). On each tick the hook:
   - if `now - Job.last_client_poll_at < client_idle_ttl` → send `pool_client.keepalive(pool_job_id)`;
   - else (client has gone quiet — app closed / backgrounded / logged out) → **stop** keepalives and
     `pool_client.cancel(pool_job_id)` (fast path); the pool lease lapses either way.
3. Resolved values (§H; pool §12): keepalive every `hb_interval_s`=10 s, `client_idle_ttl` ≈ 20 s,
   pool `hb_ttl_s`=30 s (≥ `client_idle_ttl`, so the lease is the backstop, not the primary signal).

**The unbroken-chain rule (pool §10.6):** `device → app-server` liveness = the client's ongoing
poll; `app-server → pool` = the keepalive above. If the frontend keeps polling in the background
after the user leaves, that precision is lost — so the `web/` client should **stop polling (or send
an explicit leave) when the build screen is backgrounded/closed**. That client change is the only
`web/` (Next.js) work item in C.

---

## D. User **Stop** button (app half of pool §11)

New capability: let a user stop a build mid-flight (e.g. 3 min into animation). Reuses the pool's
one generic cancel — no new pool mechanism.

**Change:**
1. **`web/` (frontend):** a Stop control while `status == running`; tap → `POST /api/job/{id}/stop`.
   Optional confirm dialog (O-12, pool spec).
2. **`webui/app.py`:** new `POST /api/job/{job_id}/stop` — **ownership-checked** (only the job's
   `external_user_id` / session may stop it); resolve `pool_job_id`; call
   `pool_client.cancel(pool_job_id)`; set `Job.status = "canceled"` under `JOBS_LOCK`;
   `db.delete_pool_job(job_id)`.
3. **`Job` model:** add a `canceled` status, **distinct from `error`**, so the UI reads **"Stopped"**
   not "Failed" (`Job.status` is currently `queued|running|done|error`, `app.py:172`).
4. **`webui/pool_client.py`:**
   - `poll()` currently folds pool `dead → error` (`pool_client.py:92`); also fold pool
     `canceled → canceled`.
   - `drive_to_result` must treat `canceled` as a clean stop (break, no exception) and also honor a
     local cancel (via the `on_tick` hook from C, or by observing `Job.status == "canceled"`), so
     the background thread exits promptly instead of polling a dead job.
5. **No partial pet:** `pet_factory` packs the bundle only at the end, so a canceled build yields no
   result — correct for "I don't want it." "Keep what's rendered" = partial bundles = out of scope.

---

## E. New `pool_client` surface (thin wrappers over pool endpoints)

Both C and D need two calls the client doesn't have yet; they wrap pool endpoints defined in the
pool spec (§9.4/§10/§11). Add to `webui/pool_client.py`:

```python
def cancel(pool_job_id: str) -> None:        # POST /api/jobs/{id}/cancel   (app-key scoped)
def keepalive(pool_job_id: str) -> None:     # POST /api/jobs/{id}/keepalive (app-key scoped)
```

Both are best-effort and idempotent: a job that is already terminal returns terminal; the client
tolerates that (a race between finish and cancel is normal — pool §11.4).

---

## F. Boundary & dependency notes

- **Boundary:** DatsPet never asks the pool to understand "Stop buttons," sessions, or
  `external_user_id`. The pool exposes generic verbs (`cancel`, `keepalive`, terminal `canceled`);
  DatsPet supplies the intent and the UX. This mirrors *pool §10.5 / §11.5*.
- **Order of dependencies** (master sequence is the pool spec §7 phase table):
  - **A, B = Phase 1** — pure DatsPet changes, shippable right after the ops lib fix (pool §4.A,
    Phase 0); independent of all other pool work. **B is a prerequisite** for the pool's *tight*
    stall watchdog (pool §9.1, Phase 2), so B should land before that.
  - **C, D = Phase 4** — must **not** start until the pool's **Phase 3** endpoints
    (`cancel`, `keepalive`, `canceled` status) are live; C/D call them. So: pool Phase 3, *then*
    C/D here.
  - Net: DatsPet is **first and last** — A/B lead, C/D follow the pool's cancel transport.
- **Do NOT** reintroduce pool concerns on this side: no client-side watchdog on the *pool's* behalf,
  no re-implementing retries — the pool owns those (pool §9).

## G. Verification

- **A:** on a node with CUDA libs hidden, a `pet_factory` job fails in seconds with the birefnet-CUDA
  message; `prep()` does not mask it. With libs present, the job runs on GPU (~2–3 min).
- **B:** the `/api/job/{id}` progress advances between 0.85 and 1.0 during cutout; pool worker
  receives beats through the cutout stage.
- **C:** kill the frontend poll (close the build screen) mid-build → keepalives stop → the pool job
  reaches `canceled` within ~`hb_ttl_s`; GPU frees.
- **D:** tapping Stop mid-animation moves the web job to `canceled` (UI shows "Stopped"), the pool
  child dies within ~`control_poll_s`, and no bundle is produced.

## H. Decisions (resolved 2026-07-21)

- **D-1 → `on_tick` hook** in the existing `drive_to_result` thread; no separate reaper. Reuse the
  thread that already drives the job — no parallel path.
- **D-2 → do both.** The `web/` client stops polling on background/close (the precise device-liveness
  signal) **and** the server keeps `client_idle_ttl` as a backstop. The precise version is the
  lasting one, not an MVP shortcut; the backstop covers a client that dies without a clean close.
- **D-3 → reuse the existing `external_user_id` scoping** (`db._scope_clause`, already used for
  pets). A standalone (NULL-user) job is stoppable by its creating session. Consistency with how
  pets are already owned — no new ownership model.

Config, resolved (matches pool §12): `client_idle_ttl` ≈ 20 s (≤ pool `hb_ttl_s`=30), pool
`hb_interval_s`=10. Tune from telemetry.
