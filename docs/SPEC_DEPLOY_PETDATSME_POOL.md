# SPEC — Deploy DatsPet to `pet.datsme.me` (GPU via the pool)

**Status:** Design — **Rev.5** (2026-07-12), revised against an independent review (Rev.2), a
second verification pass that traced the pool dispatcher/worker internals (Rev.3), a third
pass (Rev.4) that re-verified 23 load-bearing claims against the working tree + the live pool and
hardened the online (staging/prod) cutover after a same-origin/cookie regression was hit and fixed
in dev, and an independent implementation-impact review (Rev.5) that validated Rev.4's claims
against the working tree (all confirmed) and corrected four precision defects — the §A.2 progress
scale, the R4-1 cookie-host mechanics, the §C.5 gate rationale, and the §9 header — plus unit-test
pins for the Finding-1 regression class and an inventory of the Rev.4 session's code edits.
**Implementation-ready:** all §8 decisions are resolved except §8.6, a product call that does not
gate code. No code changes are made by this document.
**Author's intent (verbatim goal):** "A DatsMe user goes to *My Pet → Design a pet*,
designs a pet, and it appears on their profile — the same thing that works in dev today —
but with DatsMe running remotely on `staging.datsme.me` then `datsme.me`, talking to a
remote `pet.datsme.me`. `pet.datsme.me` has no GPU, so generation must borrow the GPU from
this machine or the Omen via the pool."
**Repos touched:** `datsme-pet-factory_wu` (partner web tier + the pool client + the pool
handler(s)), plus deploy-only config on the Hetzner box and a handler (re)install on the GPU
nodes. `shared_gpu_cpu` and `datsme_me` are **not** modified.

---

## Rev.2 — review findings & verdicts (each independently verified against code before acting)

| # | Finding | Verdict | Evidence |
|---|---|---|---|
| **1** (MAJOR) | Part A dropped `reference_image`/`remix_strength`/`display_name` → preview/upload/redesign silently generate a *text-only* pet. | **CONFIRMED** | design page posts `base_pet_id`+`preview_id` (`web/src/app/design/page.tsx:82,130`); `start_job` builds a **local-path** `reference_image` + `remix_strength` + `display_name` → `make_pet_zip` (`webui/app.py:355-388`, `run_pet_job:200` passes `str(reference_image)`); handler `params_schema` allows only `{animal,breed_id}` `additionalProperties:False` (`pool_handler/pet_factory_handler.py:31-39`); `make_pet_zip(animal,on_progress,breed_id,reference_image,remix_strength,display_name)` (`pet_factory/factory.py:384`). Fix legal: `JobSubmit.params: dict[str,Any]` (`shared_gpu_cpu/pool_contracts/messages.py:81`); `MAX_CONTENT_LENGTH` 64 MB→raised to 200 MB in prod (`v1_implementation_contract.md:558`); boundary permits handler knowing `make_pet_zip` (`application_independence_boundary.md:59`); `_prep_reference_image` re-normalizes worker-side (`factory.py:278`). **→ Part A rewritten.** |
| **2** | §A.3 should recommend A3-a (separate `pet_preview` task), reversing A3-b. | **CONFIRMED** | preview fast-fails **423** after a 1.5 s `GPU_LOCK` timeout today (`webui/app.py:276-278`); CP-2 admission control is **per-app**, not per-task (`control_plane_spec.md:28,289`) — can't prioritize preview over build in-app. **→ recommendation reversed to A3-a + a busy-state 423 mitigation.** |
| **3** | `pet_factory` imported at module top → Hetzner venv still needs ML deps. | **CONFIRMED** (evidence corrected, R3-2) | `from pet_factory import …` at `webui/app.py:38`; `pet_factory/__init__.py:6` pulls `.factory` — module-top deps numpy/requests/PIL, with rembg→onnxruntime imported lazily at generation time (`factory.py:86,99`); torch is **not** a direct dep. **→ Part A: move import into the `local` branch.** |
| **4** | `webui/requirements.txt` lacks Pillow but `extract_base_frame` uses PIL. | **CONFIRMED** | no Pillow in `requirements.txt`; `Image.open(...)` at `webui/app.py:165`. **→ Part C: declare Pillow.** |
| **5** | SDK is a path dep; Part C must say how it lands on Hetzner. | **CONFIRMED** | `# pip install -e ../../datsme_me/api/sdk/` (`webui/requirements.txt:18`). **→ Part C addition.** |
| **6** | `JOBS`/`JOBS_LOCK`/SQLite → pin one uvicorn worker. | **CONFIRMED** | `JOBS: dict` + `JOBS_LOCK = threading.Lock()` (`webui/app.py:110-111`); single sqlite conn (`webui/db.py`). **→ Part C: `--workers 1`.** |
| **7** | pool `dead` must map to web `error`. | **CONFIRMED** | pool `JobStatus = Literal[…,"dead"]` (`messages.py:18`); web `JobStatus` has no `dead`. **→ A.1 adapter maps `dead→error`.** |
| **8** | Two dual-nvidia pet workers would collide on one ComfyUI. | **CONFIRMED** | factory targets a single `PET_FACTORY_COMFY_URL` (`factory.py:39`); this box runs one ComfyUI (:19953), shared with dev. **→ Part B: scope to Omen + one local card, or spec per-GPU ComfyUI.** |
| **9** | §9 "workshop offline" would leak the pool key to the browser. | **CONFIRMED** | frontend has no pool access today (grep `web/src` clean). **→ §9/§C: backend proxy over `/api/pool`; key stays server-side.** |
| Opt-1 | Durable job reattach (in-memory `JOBS` orphans a pool job on restart). | **ADOPTED** | `JOBS` in-memory (F6). **→ §7 step 9 + optional A.6.** |
| Opt-2 | "no A-record (000)" wording is wrong. | **CORRECTED** | `dig pet.datsme.me` → `5.161.70.13` (A-record exists; vhost/TLS missing). **→ §0 wording fixed.** |

---

## Rev.3 — second verification pass (dispatcher/worker internals traced before build)

Rev.2's §B.1 premise and two smaller items were re-verified against the pool's actual code.
Three corrections — none structural; the plan and its ordering stand:

| # | Correction | Evidence |
|---|---|---|
| **R3-1** (important) | §B.1 claimed a v1 node would *reject* v2 params. **Wrong mechanism — the real failure is silent.** Submits carry **no version** (`JobSubmit` = task + params, `messages.py:79-83`); the dispatcher validates params against whichever version `resolve_task` resolves — preferring versions advertised by *online* nodes, tie-broken by most-recent advertisement (`catalog.py:67-84`) — so a mixed fleet **flaps** between schemas (intermittent 422s). Worse: the scheduler matches jobs to nodes **by task name only** (`scheduler.py:41`) and workers never re-validate params per job, so a v2-validated job **can be claimed by a v1 node, which silently ignores `reference_image_b64`** and generates a text-only pet — Finding 1's failure recurring at fleet level. There is **no fail-loud net**. | `pool_dispatcher/app.py:86-95`, `catalog.py:67-84`, `scheduler.py:41`, `messages.py:79-83`. **→ §B.1 rewritten: same ordering, corrected mechanism, executable gate, Omen-first rule.** |
| **R3-2** | Finding 3's evidence overstated the import weight ("torch/ComfyUI/rembg" at module top). Actually: module-top pulls numpy/requests/PIL; **rembg → onnxruntime-CUDA is imported lazily at generation time** (`factory.py:86,99`); torch is not a direct dependency at all. The conclusion (lazy import, §A.4) is unchanged, but a "no torch" acceptance gate would pass vacuously. | `pet_factory/factory.py:86,99`. **→ F3 evidence, §A.4, §C.1 gate, §7 gates corrected to check rembg/onnxruntime/pet_factory absence.** |
| **R3-3** | `pet_preview`'s `timeout_s: 60` is too tight on a **cold** ComfyUI (first job loads the Z-Image model and can exceed 60 s); the watchdog bound is authoritative from the claiming node's advertised meta (`scheduler.py:63-64`). Its `needs` were also unstated — the CPU worker must never claim a preview. | `scheduler.py:63-64`. **→ §A.3: `timeout_s: 180` + explicit `needs` block.** |

Rev.3 also **resolves the §8 decisions** (all but the product-call §8.6) and re-sequences §7:
upgrade **Omen first** (the fleet is never version-mixed), run the dev gate against one
known-good node, then add the second generator.

---

## Rev.4 — third verification pass + online-deploy hardening (2026-07-12)

Rev.4 re-verified 23 of the spec's load-bearing claims against the working tree and the live pool
(two independent code-reading passes + direct HTTP probes). **Result: the spec is accurate.** Line
numbers drift ~4 lines throughout (harmless); every substantive claim held, including the highest-
risk one (R3-1, the silent mixed-fleet failure — confirmed link-by-link). The only inaccuracy was
R3-2, which the spec had *already self-corrected*. No finding, ordering, or gate moved.

What Rev.4 *adds* is not a correction of the pool work but a hardening of the **online cutover**,
prompted by a real regression hit and fixed in dev this session. The dev box's repo had been copied
to a new directory (`…/datsme-pet-factory` → `…/datsme-pet-factory_wu`), and a chain of stale
absolute-path artifacts (a baked Next.js build, an editable-install finder pointing at the old dir,
venv script shebangs) masked the real issues. While chasing them, the frontend's API base was
briefly split (`localhost` page origin vs a `127.0.0.1` API origin) — which **silently dropped the
DPP launch cookie and made the "Accept — send to my DatsMe" button never appear.** The pet built
fine; it just couldn't be sent home. That failure mode is *exactly* what §C.2/§C.3 must prevent in
prod, so Rev.4 promotes those from "preferred" to **enforced, gated requirements** and adds §C.5.

| # | Finding (verified this session) | Verdict | Consequence |
|---|---|---|---|
| **R4-1** (deploy-critical) | The DPP launch cookie is bound to **one origin** — the host in `DATSPET_FRONTEND_URL`, where `/launch` sets it (`datsme_integration.py:235-243`). The browser sends it on `fetch` only to that **same host**. If the page origin and the `NEXT_PUBLIC_API_URL` origin differ *in any way* — `localhost` vs `127.0.0.1`, apex vs `www`, http vs https, or two different subdomains — the cookie is not sent, `getDatsmeSession()` returns `launched:false`, and **the Accept button silently disappears**. There is no error; generation still works, so it reads as "DPP is broken/unconnected." | **CONFIRMED (live)** (mechanics refined, R5-2) | **→ §C.2 makes same-origin a hard requirement; §C.5 states the single-hostname invariant; §7 adds an explicit "Accept button renders after a real launch" gate.** |
| **R4-2** | The cookie is `SameSite=None; Secure` in dev (`datsme_integration.py:81-82`, default `DATSPET_COOKIE_SAMESITE=none`). `Secure` cookies are sent only over HTTPS **or to `localhost`** (browsers treat `http://localhost` as a secure context — `127.0.0.1` also qualifies, but as a *different host*). On a plain-HTTP staging box that is **not** `localhost`, a `Secure` cookie is dropped entirely → no session, no Accept. Prod is HTTPS so `Secure` is fine there; the trap is any **non-TLS, non-localhost** intermediate box. | **CONFIRMED** | **→ §C.5: staging must be real HTTPS (same as prod), never plain-HTTP; with same-origin behind the proxy, switch to `SameSite=lax` and drop the `Secure` dependence.** |
| **R4-3** | "dev→prod is env values, not code" (§0) held up under scrutiny — none of the session's breakage was in the code the spec changes; it was all **environment artifacts of the directory copy** (stale build cache, editable-install path, venv shebangs). This *validates* the spec's core premise, but is a caution: a copied/rsynced deploy tree can carry the same stale absolute paths. | **CONFIRMED** | **→ §C.5 deploy hygiene: build on the target (or clean the build cache), reinstall editables against the deploy path, never rsync a `.next`/venv from another path.** |
| **R4-4** | `NEXT_PUBLIC_API_URL` is inlined into the JS **at build/dev-boot time**, not read at runtime (`web/src/lib/api.ts:9`). Flipping the env after a build has no effect until a rebuild/restart. | **CONFIRMED** | **→ §C.3 note + §C.5: set the prod value *before* `next build`; a stale bundle points the browser at the wrong origin (the dev symptom, at prod scale).** |

---

## Rev.5 — independent implementation-impact review (2026-07-12)

Rev.5 is an outside review of Rev.4. Every R4 claim was re-verified against the working tree
(`datsme_integration.py:81-82,235-243`, `web/src/lib/api.ts`, the e2e session assertion at
`scripts/e2e_design_a_pet.sh:102-104`, the re-anchored `app.py` line numbers) — **all confirmed**,
including that the ~4-line drift Rev.4 measured was caused by the Rev.4 session's own CORS edit to
`app.py`, not a stale tree. The plan, ordering, decisions, and gates all stand. What Rev.5 changes
is precision: one implementation-critical detail was stated backwards (the progress scale), two
mechanics statements were overbroad or misattributed, one gate rationale was overstated, and one
section header contradicted its own table. All are corrected inline with R5 tags; none move a
decision.

| # | Finding | Verdict | Consequence |
|---|---|---|---|
| **R5-1** (implementation-critical) | §A.2 said `on_progress` fractions "map 1:1" through the pool. **Backwards:** locally, `run_pet_job` stores `make_pet_zip`'s **fraction 0..1** straight into `Job.progress` (`webui/app.py:97,198-201`), but the handler bridges that fraction to the pool's **pct 0..100** (`pet_factory_handler.py:53`) and `GET /api/jobs/{id}` returns pct. Wired as written, the UI progress bar pins at 100× instantly. | **CONFIRMED** | **→ §A.1/§A.2: the adapter divides pct by 100 (pool branch only — the local path stays fraction-native); §7 step 1 pins it with a unit test.** |
| **R5-2** | R4-1's mechanics were imprecise on two axes. (a) Cookies are **host-scoped, not origin-scoped** — a port-only split does *not* drop them; dev's own working posture (page `:19955` → API `:19954`, SameSite=None) is the in-spec counterexample to "differ in any way". (b) The cookie is bound to the host that **serves `/launch`** — the `DATSPET_PUBLIC_URL` origin (the Set-Cookie rides the `/launch` response, `datsme_integration.py:235-243`) — not to `DATSPET_FRONTEND_URL`; dev masks the distinction because both hosts are `localhost`. The **byte-for-byte invariant is unchanged**: it is a deliberately stricter *sufficient* condition, kept because it is mechanically checkable. | **CONFIRMED** | **→ §C.2 / §C.5 item 1 restated with the precise mechanics; the enforced rule is untouched.** |
| **R5-3** | §C.5's gate rationale overstated: "the existing generation/adoption gates do not" catch an origin/cookie mismatch. Step 6's pre-existing gate (… → Accept → pet in My Pets, credits charged) **does fail** when the Accept button never renders — but it fails *ambiguously*, reading as "DPP broken". The new gate's real value is **isolation + scriptability**, not unique detection. | **CONFIRMED** | **→ §C.5 closing + §9 row reworded.** |
| **R5-4** | §9's header ("all degrade to 'the feature waits'") contradicted its own R4-1/2 row ("NOT a degrade-to-wait failure"). The row is right. | **CONFIRMED** | **→ §9 header amended to name the one exception.** |
| **R5-5** | §A.3's 423 busy-state mitigation is **best-effort, not a contract**: the busy check and the submit are two steps, so two callers can both observe "free" and one preview then queues silently behind the other's build (TOCTOU). Rare at launch volume; a hard guarantee would need per-task admission control in the pool (out of scope, §2). | **CONFIRMED** | **→ §A.3 + §9 row say "best-effort" explicitly.** |
| **R5-6** | §7 step 1's "unit tests green" named no tests for the exact regression class the spec revolves around (Finding 1: params silently dropped between web tier and handler). The step-3 live E2E proves the wiring **once**; only unit tests keep it proven after launch. | **ADOPTED** | **→ §7 step 1 names the mocked-pool param-passthrough pins.** |
| **R5-7** | The Rev.4 session left four working-tree edits uncommitted and uninventoried: `webui/app.py` (**functional** — `http://[::1]:{PORT}` added to CORS `allow_origins`; this is also the +4-line drift Rev.4 measured), comment-only edits to `web/src/lib/api.ts` and `start_petmaker_backend_only.sh`, and a path fix in `created_pets/README.md`. The app.py comment justifying the `[::1]` entry **misstated Origin mechanics**: the `Origin` header reflects the document URL's hostname *as typed*, never the resolved IP — a page at `http://localhost:PORT` always sends `Origin: http://localhost:PORT`; only a tab explicitly opened at `http://[::1]:PORT` sends a `[::1]` Origin. The entry itself is harmless and kept. | **CONFIRMED** | **→ the app.py + api.ts comments corrected in-tree (Rev.5 session); land all four edits with the Part A commit. Appendix `getaddrinfo` note reconciled.** |
| **R5-8** (nit) | Every revision/verification stamp was dated 2026-07-12 — a day in the future at writing time. | **CORRECTED** | **→ all stamps set to 2026-07-12.** |

Rev.5 also adds one non-gating hardening note to §B.1: a *breaking* handler-schema change can ship
as a **new task name** instead of a same-name version bump — the scheduler's name-only matching
then becomes the fail-loud net R3-1 proves does not exist for same-name versions. Deferred while
the fleet is 1–2 owned nodes.

---

## Rev.6 — motion-profiles impact: the "no-ML" gate is now "no-ML-STACK" (2026-07-13)

The species-aware motion-profiles feature (`SPEC_MOTION_PROFILES`) made the GPU-less web tier import
`pet_factory.motion_profiles` at module top — the pose menu is **pure JSON data** the web tier reads
(`/api/motions`, the pose loop's profile resolution). This changes one deploy property and nothing else:

- **The gate was "no `pet_factory` at all"; it is now "no ML *stack*".** `pet_factory` must be *findable*
  on the GPU-less venv (the repo root is not on the backend's `sys.path` — cwd is `webui/`), so it is
  installed **`pip install --no-deps -e /var/www/datspet`**. `--no-deps` is essential — `pyproject.toml`'s
  deps include numpy/rembg, so a plain install would reintroduce the ML stack. The lazy PEP-562
  `pet_factory/__init__` means importing `motion_profiles` never pulls `.factory`; a factory attribute
  (`make_pet_zip`) raises `ModuleNotFoundError: numpy` only at access time, which the pool backend never
  reaches. **Verified locally in a throwaway venv:** `--no-deps -e .` → `from pet_factory import
  motion_profiles` works, `import numpy` fails, `pip list` shows `pet_factory` but no rembg/onnxruntime/
  numpy/torch.
- **Consequence for the acceptance gate** (§C.1, §7 step 5, and `deploy/README.md`): the grep is now
  `rembg|onnxruntime|numpy|torch` must be EMPTY; `pet_factory` MAY appear (data-only). The positive
  check is `from pet_factory import motion_profiles` imports while `import numpy` fails.
- **First-deploy ordering:** run the `--no-deps -e` install BEFORE restarting the backend, or the
  module-top import hits `ModuleNotFoundError` and `Restart=always` crash-loops. Documented in
  `deploy/README.md` (update procedure + first-deploy note). No fleet/handler change; this is web-tier
  packaging only.

---

## 0. What is already TRUE (verified 2026-07-12, not assumed)

This spec is deliberately small because most of the machinery already exists and was
verified live before writing it:

| Fact | How verified |
|---|---|
| **The compute pool is live** at `pool.datsme.me` (`/docs` → 200). | HTTP probe. |
| **Pet generation works end-to-end on the pool right now.** Submitting `{task:"pet_factory", params:{animal:…}}` with the `datspet` app key was claimed by GPU worker `omen-pet` and generated a pet (observed progressing idle→walk→run). | Live job `1467e39a…` submitted + polled. |
| **The `datspet` app is registered** on the pool; its key is cached locally at `~/.pool/datspet_key` (server copy: `ssh root@5.161.70.13 cat /var/www/pool/app_key_datspet`). | File read + successful authenticated submit. |
| **The pool contract** is `POST /api/jobs` → poll `GET /api/jobs/{id}` (`{status,pct,msg,error}`) → `GET /api/jobs/{id}/result` (the `.zip`), auth via `X-App-Key`. A working reference client is `created_pets/make_pet.py`. | Read + exercised. |
| **The DPP integration (DatsMe ⇄ DatsPet) is built, hardened, and E2E-verified.** Launch → design → Accept → `pet_bundle.v1` writeback → host fetches the bundle → adopts into My Pets, credits charged, consent + host-signature security done. | Prior sessions; `docs/SPEC_DATSPET_DPP_INTEGRATION.md`. |
| **All the relevant config is env-driven**, so dev→prod is env values, not code: `DATSPET_PUBLIC_URL`, `DATSPET_FRONTEND_URL`, `DATSME_BASE_URL`, `DATSME_PUBLIC_URL`, `DATSME_HMAC_SECRET`, `NEXT_PUBLIC_API_URL`. | `webui/datsme_integration.py`, `web/.env.local`. |
| **`pet.datsme.me`, `staging.datsme.me`, `datsme.me`, `pool.datsme.me` all resolve to `5.161.70.13`** — the Hetzner box. `pet.datsme.me`'s **A-record already exists** (→ `5.161.70.13`); what's missing is the served **vhost + TLS cert** (a plain HTTP probe returns 000 because nothing is listening for that host yet). | `dig pet.datsme.me` → `5.161.70.13`. |
| **The GPU nodes dial *out* to the pool** (NAT-friendly); nothing reaches into this box or Omen. | Pool design; `/api/pool` shows `omen-pet`, `dual-nvidia-gpu0/1` online. |

### The ONE gap that blocks pet-generation-from-a-remote-web-tier

**`webui/app.py` still calls the local GPU directly** — `make_pet_zip()` (full build, L199) and
`render_design_still()` (preview, L279), guarded by an in-process `GPU_LOCK` (L84). On a
GPU-less Hetzner box these calls have nothing to run against. This is the only reason the web
tier can't simply be copied to Hetzner as-is. **Closing this gap — routing generation to the
pool instead of the local GPU — is the core engineering work of this spec (Part A).**

### The one deployment fact that makes this cheap

`pet.datsme.me` is a **new vhost on the same Hetzner box** (`5.161.70.13`) that already runs
the pool dispatcher and DatsMe. So "deploy DatsPet to Hetzner" is: add a vhost + two systemd
services behind the box's existing TLS proxy. No new server, no new TLS stack to invent.

---

## 1. Target topology

```
  Browser
    │  (1) DatsMe "Design a pet"  ── DPP launch ──►
    ▼
  ┌───────────────────────── HETZNER  5.161.70.13  (CPU-only, public HTTPS) ─────────────────────────┐
  │                                                                                                   │
  │   datsme.me / staging.datsme.me            pet.datsme.me  (NEW vhost)         pool.datsme.me        │
  │   = DatsMe (FastAPI + Postgres)            = DatsPet web tier (GPU-LESS)      = pool dispatcher     │
  │        │                                        │  frontend (Next.js)         (already live)        │
  │        │  (2) DPP writeback  ◄─────────────────  │  backend (FastAPI)              ▲                 │
  │        │  (3) fetch bundle_url ────────────────► │       │ submit {pet_factory}    │ (workers        │
  │        ▼                                          │       └─────────────────────────┘  dial OUT)     │
  │   adopts into My Pets                             │  poll + download .zip                            │
  └───────────────────────────────────────────────────────────────────────────────────────────────────┘
                                                              ▲ pool routes the job to a GPU worker
                                        ┌─────────────────────┴───────────────────────┐
                                   this box (dual-nvidia)                       Omen (omen-pet)
                                   GPU worker running the                       GPU worker running the
                                   pet_factory handler + ComfyUI                pet_factory handler + ComfyUI
                                   (dials out — no inbound)                     (already live, generating)
```

Three network hops matter and all are already proven individually:
1. **DatsMe → DatsPet (DPP launch/writeback):** built + hardened. Only prod URLs + a prod registration change.
2. **DatsPet → pool (generation):** the pool works today; DatsPet's web tier must *use* it (Part A).
3. **pool → GPU worker:** live (Omen already; this box needs the pet_factory handler installed).

---

## 2. Non-goals / explicit scope guards

- **No new GPU-sharing system.** We use the deployed `shared_gpu_cpu` pool. The older
  `DESIGN_SPEC_HETZNER_LOCAL_GPU.md` (a bespoke queue) is **superseded for this deployment** —
  do not build it. (It remains valid history; this spec chooses the pool per the 2026-07-12
  decision.)
- **No change to `shared_gpu_cpu`.** DatsPet is a *client* of the pool. The independence
  boundary holds: the pool never imports DatsPet; DatsPet only speaks the pool's HTTP contract.
- **No change to the DPP protocol or the `datsme_me` host** beyond a prod partner registration
  (a data change, not code).
- **No secrets in the repo or this doc.** The pool app key, the DPP HMAC secret, and the pool
  worker token live only in server-side env / gitignored files.

---

## 3. Part A — Route generation to the pool (the core code work)

**Where:** `datsme-pet-factory_wu/webui/`. **Principle:** the web tier stops importing
`pet_factory` and stops owning a GPU; it becomes a pool *client*. This is the change that lets
the identical web tier run on a GPU box (dev) OR a GPU-less box (Hetzner) with only a config
flip.

> **Rev.2 — the reference-image problem (Finding 1) is the crux of Part A.** The dev flow is
> not "text → pet". It is: preview a design (img2img redraw of a base pet or an uploaded photo),
> then *build the exact previewed still into a pet*. Concretely `start_job` passes a
> **web-tier-local filesystem path** `reference_image` plus `remix_strength` and `display_name`
> to `make_pet_zip` (`webui/app.py:355-388,200`). A pool worker on another machine cannot see
> that path, and the handler's schema rejects the extra params (`additionalProperties:False`,
> `pet_factory_handler.py:39`). **So generation params — including the reference image bytes —
> must travel to the worker.** Part A below carries them; a text-only submit would silently make
> the wrong pet (Finding 1, confirmed).

### A.1 A single pool-client adapter (`webui/pool_client.py`, NEW)

One file, one job: submit a task to the pool and drive it to a result. Mirrors
`created_pets/make_pet.py` (proven) but as a reusable module with progress callbacks so the
existing job/preview UX is preserved.

Surface (proposed):
- `submit(task: str, params: dict) -> job_id`
- `poll(job_id) -> {status, pct, msg, error}`. **Pool status ∈ queued|running|done|error|dead**
  (`shared_gpu_cpu/pool_contracts/messages.py:18`). The web tier has no `dead` state, so the
  adapter **maps `dead → error`** (Finding 7) before it reaches the existing job machinery.
  **`pct` is 0..100 pool-side while the web tier's `Job.progress` is a fraction 0..1 — the
  adapter converts (÷100) here as well (R5-1).**
- `result_bytes(job_id) -> bytes` (the `.zip` for `pet_factory`; the PNG for the `pet_preview`
  task, §A.3).
- Config from env: `POOL_URL` (default `https://pool.datsme.me`), `POOL_APP_KEY`
  (from env or `~/.pool/datspet_key`). Auth header `X-App-Key`.
- One place that knows the pool endpoint URLs (the "one client adapter per backend" rule).

### A.2 Rewire `run_pet_job` (full build) — carry ALL generation params (Finding 1)

Today (`app.py:199`): `with GPU_LOCK: breed_id, zip_bytes = make_pet_zip(description,
on_progress=…, reference_image=str(<local path>), remix_strength=…, display_name=…)`.

After: submit `{task:"pet_factory", params:{...}}` to the pool with **all** the params the local
call used, then poll and download the result `.zip`. The params dict carries:
- `animal`: the composed description (as today).
- `display_name`: preserved (else the pet name degrades to the composed prompt `.title()`ed —
  Finding 1).
- `remix_strength`: preserved (the redesign/strength control).
- **`reference_image_b64`**: when `run_pet_job` has a `reference_image` path (preview still,
  redesigned base frame, or uploaded photo), the web tier **reads the file, downscales it to
  ≤1024 px (PIL), and base64-encodes it** into this param. This is the transport that replaces
  the meaningless local path. Verified legal: `JobSubmit.params` is `dict[str,Any]`
  (`messages.py:81`); the dispatcher/nginx body cap is 64 MB v1, raised to 200 MB in the live
  prod config (`v1_implementation_contract.md:558`), and a 12 MB upload → ~16 MB b64 fits with
  headroom. The downscale keeps the dispatcher DB small; it is loss-safe because the worker's
  `_prep_reference_image` re-pads/normalizes to a square canvas anyway (`factory.py:278`).

Handler side (this repo — see the boundary note below): extend `pet_factory_handler.py`'s
`params_schema` with optional `reference_image_b64`, `remix_strength`, `display_name`; in
`run()`, if `reference_image_b64` is present, decode it to a temp file **inside the handler's own
process/`result_dir`** and pass that path (plus the other two) through to `make_pet_zip`. The
handler already knows `make_pet_zip` and lives in the app repo, so this is squarely inside the
independence boundary (acid test: `application_independence_boundary.md:59` — "the `pet_factory`
handler … knows `make_pet_zip` … lives with DatsPet / on the node as an installed plugin").
**Bump the handler METADATA `version` "1" → "2"** so the schema change is explicit and the
cutover (§7 / Part B) can order the reinstall before the new web tier submits new params.

The rest of `run_pet_job` (unpack sheet/manifest, `db.insert_pet`, draft flag, DPP scoping
`external_user_id`) is unchanged — it already operates on `zip_bytes`, and the pool returns
exactly that. **Progress does NOT map 1:1 (R5-1):** locally, `run_pet_job` stores `make_pet_zip`'s
**fraction 0..1** straight into `Job.progress` (`app.py:97,198-201`), but the handler bridges that
fraction to the pool's **pct 0..100** (`pet_factory_handler.py:53`) and the poll returns pct — the
pool branch must divide by 100 (in the §A.1 adapter; the local branch stays fraction-native), or
the UI progress bar pins instantly.

- `GPU_LOCK` is deleted from the web tier: concurrency is now the pool's job. (Note the caveat in
  Finding 8 / Part B — the *pool* only parallelizes across *distinct ComfyUI-backed workers*.)

### A.3 The preview path (`render_design_still`, ~10 s) — **A3-a: a separate `pet_preview` task** (Rev.2: recommendation reversed)

Rev.1 recommended reusing `pet_factory` for previews. **Rev.2 reverses this to A3-a — a distinct
`pet_preview` handler** — because reuse was illusory: the preview needs **different params** (the
reference image + strength — same transport as A.2), a **different result shape** (a PNG, not a
`.zip`), and a **different timeout** (~10 s vs the build's 900 s). Since the handler install is
already being touched for Finding 1, adding a second small handler is marginal, and it buys:
- `timeout_s: 180` (Rev.3, was 60 — R3-3) — a hung preview releases the GPU slot in minutes, not
  15. 60 s is fine warm (~10 s redraw) but the **first job on a cold ComfyUI loads the Z-Image
  model** and can exceed it, and the watchdog kill bound is authoritative from the claiming
  node's advertised meta (`scheduler.py:63-64`). 180 s covers a cold start with headroom while
  staying far under the build's 900 s.
- A distinct task name in `/api/pool`, addressable by future admission control.
- A ~1 s poll cadence (the 4 s in `make_pet.py` is tuned for 3-min builds).

`pet_preview` handler (this repo): `params_schema` = `{reference_image_b64 (required),
description, strength}`, `result_kind: "bytes"` returning the redrawn PNG; **`needs` = the same
GPU profile as `pet_factory`** (`{gpu:1, vram_gb:20, gpu_backend:"cuda"}`) so the CPU-only worker
can never claim a preview (R3-3); `timeout_s: 180`; `run()` decodes the b64 and calls
`render_design_still(description, <temp path>, strength)`.

**UX-regression mitigation (Finding 2, confirmed).** Today the preview *fast-fails 423* after a
1.5 s `GPU_LOCK` timeout when the GPU is busy (`webui/app.py:276-278`); through the pool it would
silently queue behind a build for minutes. CP-2 admission control is **per-app, not per-task**
(`control_plane_spec.md:28`), so it cannot deprioritize builds under previews. Mitigation the web
tier implements: before submitting a `pet_preview`, consult `/api/pool` for pet-capable workers'
busy-state (via the backend proxy of §C/§9 — the app key must not reach the browser, Finding 9);
if none are free, return the same **423 "the workshop is busy — try again in a bit"** the local
path returns today. Preserves today's fast-fail behavior — **best-effort, not a contract (R5-5)**:
the busy check and the submit are two steps, so two callers can both observe "free" and one
preview then silently queues behind the other's build (TOCTOU). Acceptable at launch volume; a
hard guarantee would need per-task admission control in the pool (out of scope, §2).

If `pet_preview` isn't ready at cutover, the **preview button is feature-flagged off on prod**
(design → generate-from-text/redesign still works end to end).

### A.4 Move the `pet_factory` import off the module top (Finding 3)

`webui/app.py:38` does `from pet_factory import make_pet_zip, render_design_still` at module load,
and `pet_factory/__init__.py:6` imports `.factory` — whose module-top deps are numpy/requests/PIL,
with the GPU stack (rembg → onnxruntime-CUDA) imported lazily at generation time
(`factory.py:86,99`); torch is not a direct dependency at all (R3-2). With the
`PET_GEN_BACKEND=local|pool` switch (§A.6), this import **must move inside the `local` branch**
(imported lazily only when the local backend is selected). Otherwise the GPU-less Hetzner install
still needs pet_factory + its dependency stack, and Part C's "no ML deps" proof gate fails.

### A.5 Result-size consideration (carry forward, don't solve yet)

`pet_factory_handler.py` uses `result_kind: "bytes"`; the pool design flags switching to
`result_kind: "url"` if volume makes the dispatcher funnel bite. For launch volume, `bytes` is
fine. **Dovetail:** DPP already fetches the pet via a partner-hosted `bundle_url` (fetch-URL
transport), so a later move to pool `url` results should be reconciled with the DPP flow (out of
scope here; noted for the follow-up). Note the *inbound* reference image is bounded by the same
`MAX_CONTENT_LENGTH` gate as results (A.2), which is why the ≤1024 px downscale matters.

### A.6 The `PET_GEN_BACKEND=local|pool` switch + what does NOT change

- **Standalone-local mode is preserved** as a break-glass: `PET_GEN_BACKEND=local` keeps dev using
  the on-box GPU directly (no pool/network dependency for dev); `pool` is prod. Same codebase.
  The `local` branch is the *only* place `pet_factory` is imported (§A.4).
- **Unchanged:** the DB layer (`webui/db.py`), the DPP adapter (`webui/datsme_integration.py`),
  per-user scoping, the bundle format, the frontend job/progress UX. Generation output is still
  `zip_bytes`; only its *source* changes.
- **Optional (Finding Opt-1) — durable pool-job reattach.** `JOBS` is in-memory (`app.py:110`), so
  a web-tier restart orphans an in-flight pool job that still completes on the worker. Optionally
  persist `pool_job_id ↔ web pet_id` in the DB and reattach on startup (cheap now that pool jobs
  are durable server-side objects). At minimum this is a §7-step-9 production item; adopt into A.6
  if we want zero-loss across restarts at launch.

---

## 4. Part B — Install the (updated) `pet_factory` + `pet_preview` handlers on the GPU nodes

Verified state: `omen-pet` advertises `pet_factory` (and is generating). This box's GPU workers
(`dual-nvidia-gpu0/gpu1`) advertise only `echo`/`sleep_test` — the pet handler is not installed
here.

**Work:**
1. Install the **v2** `pet_factory` handler (with the `reference_image_b64`/`remix_strength`/
   `display_name` params, §A.2) **and** the new `pet_preview` handler (§A.3) on the pet-capable
   nodes:
   ```
   POOL_URL=https://pool.datsme.me pool-install-handler pool_handler/pet_factory_handler.py --restart <gpu worker unit>
   POOL_URL=https://pool.datsme.me pool-install-handler pool_handler/pet_preview_handler.py  --restart <gpu worker unit>
   ```
2. Prereq on any node that runs them: the full ComfyUI + models pipeline
   (`needs: {gpu:1, vram_gb:20, gpu_backend:cuda}`). Omen has it; this box's ComfyUI (:19953) has
   the Z-Image + Wan 2.2 models (dev generates locally), but the *pool worker's* interpreter must
   reach the same `pet_factory` install + ComfyUI URL.

### B.1 Handler-version cutover ordering (Finding 1 consequence — MUST get right; mechanism corrected in Rev.3, R3-1)

Because §A.2 changes the submit params, **every pet-capable node must serve the v2 handler
*before* anything submits v2 params.** Rev.3 traced what actually happens on a mixed fleet, and
it is **worse than rejection — it is silent**:

- Submits carry **no version** (`JobSubmit` = task + params only, `messages.py:79-83`). The
  dispatcher validates params against whichever version `resolve_task` resolves — preferring
  versions advertised by *online* nodes, tie-broken by most-recent advertisement
  (`catalog.py:67-84`). With a v1 node and a v2 node both online, validation **flaps per
  submit**: v2 params are intermittently 422-rejected whenever v1's schema
  (`additionalProperties:False`) wins the tie-break.
- When a v2 submit *does* validate, the scheduler matches jobs to nodes **by task name only**
  (`scheduler.py:41`), and workers never re-validate params per job — so **a v1 node can claim
  the v2 job and silently ignore `reference_image_b64`**, generating a text-only pet. That is
  Finding 1's silent failure recurring at fleet level. **Never rely on rejection to catch an
  ordering mistake; there is no fail-loud net.**

The mitigation is pure deploy discipline, and today's fleet makes the risk window ~zero when
ordered right — Omen is currently the **only** pet node, so upgrading it first means the fleet is
never version-mixed for `pet_factory`:
1. Install v2 `pet_factory` + the new `pet_preview` on **Omen first** and restart its worker
   (single-version fleet throughout).
2. **Gate (strengthened, and executable):** version is NOT visible in `/api/pool`
   (`NodeView.tasks` is names only, `messages.py:106`), and `GET /api/tasks` lists the whole
   catalog *including stale entries* — so verify with both an ops check and a probe:
   (a) every pet-capable node's installed handler file is v2 and its worker was restarted;
   (b) `GET /api/tasks` shows the v2 `pet_factory` entry and `pet_preview`;
   (c) **probe submits carrying `reference_image_b64` validate repeatedly (no 422)** — since
   `resolve_task` only resolves online-advertised versions, consistent acceptance means no online
   node is still advertising v1;
   (d) a plain text-only submit (`created_pets/make_pet.py`) still works — v2 accepts v1-shaped
   params because the new fields are optional.
3. Only then may anything submit v2 params (the dev web tier at §7 step 3; Part C later).
4. The dual-nvidia card is added **after** the dev gate (§7 step 4) — it installs v2 directly and
   never serves v1.
The handler `version` bump ("1"→"2", §A.2) makes the state auditable. The same rule binds any
future node: **never attach a node with a stale handler copy while newer-schema submits exist.**

**Future hardening (Rev.5, non-gating):** when a schema change is *breaking* (v2's is not — the new
fields are optional), ship it as a **new task name** rather than a same-name version bump. The
scheduler's name-only matching (`scheduler.py:41`) then guarantees a stale node can never claim the
new-schema job — the fail-loud net this section proves does not exist for same-name versions.
Deferred while the fleet is 1–2 owned nodes; reconsider when it grows or third parties run nodes.

### B.2 One ComfyUI ≠ two pet workers (Finding 8, confirmed)

`pet_factory` drives **one** ComfyUI instance (`PET_FACTORY_COMFY_URL`, default one URL —
`factory.py:39`). This box runs a **single** ComfyUI (:19953), also shared by dev. So even though
both `dual-nvidia-gpu0` and `gpu1` satisfy `needs:{vram_gb:20}`, **installing the pet handler on
both would let the pool schedule two concurrent pet jobs onto one ComfyUI — they collide.** Two
valid postures (resolved in §8.7 — launch scope):
- **Launch scope (recommended): Omen + exactly ONE local card.** Install the pet handler on Omen
  and on *one* of this box's GPU workers (or a dedicated single pet worker pinned to one card).
  Gives the "≥1 of two always up" redundancy without the collision. Simplest, correct.
- **Both local cards:** requires **per-GPU ComfyUI** — a second ComfyUI on a distinct port pinned
  with `CUDA_VISIBLE_DEVICES=1`, and the second pet worker's `PET_FACTORY_COMFY_URL` pointed at it,
  with its own models/output dir. More throughput, more ops. Also note: **dev shares this box's
  ComfyUI (:19953)** — a pool pet job and a dev-local generation would contend on it; scope
  accordingly (e.g. don't run the pool pet handler on the same ComfyUI dev is actively using, or
  give the pool worker its own instance).

**Acceptance:** `/api/pool` shows ≥2 nodes advertising `pet_factory` (+ `pet_preview`), each
backed by its **own** ComfyUI; the §B.1 gate holds (no online node advertising v1 — verified via
the ops check + probe submits, since `/api/pool` does not show versions); killing one mid-job,
the other reclaims (the pool's crash-reclaim, already built).

---

## 5. Part C — Deploy the GPU-less web tier to `pet.datsme.me`

Same Hetzner box, new vhost, behind the box's existing TLS proxy. Two services (mirrors the DatsMe
and pool deploy conventions already on the box).

### C.1 Services
- **DatsPet backend** (FastAPI, `webui/app.py`) under systemd, bound to a local port, GPU-less
  (`PET_GEN_BACKEND=pool`), **pinned to ONE worker process** (`--workers 1` / single uvicorn
  worker). This is required, not optional: `JOBS`/`JOBS_LOCK` are in-memory and the SQLite store
  uses a single module-level connection (`webui/app.py:110-111`, `webui/db.py`) — multiple
  processes would fork the job map and race the DB (Finding 6). Scale later via a shared store,
  not more workers.
- **The GPU-less dependency set (Findings 3,4,5; gate re-pointed in Rev.3, R3-2) — the "no ML
  deps" proof.** With §A.4 the web tier imports `pet_factory` only in the (unused-on-prod)
  `local` branch, so pet_factory's stack — **rembg / onnxruntime(-CUDA) / numpy and the
  ComfyUI-driving code — is absent** from the Hetzner venv. (torch was never a direct dep;
  checking for it would pass vacuously.) But the web tier still directly needs:
  - **Pillow** — `extract_base_frame` uses `PIL.Image` (`webui/app.py:165`); today it arrives
    transitively via the pet_factory env, which is gone on Hetzner. **Declare Pillow explicitly**
    in `webui/requirements.txt` (Finding 4).
  - **The DatsMe partner SDK** — a path dependency (`# pip install -e ../../datsme_me/api/sdk/`,
    `webui/requirements.txt:18`). On Hetzner the `datsme_me` repo is co-located (same box), so
    install it editable from that path; if it is *not* co-located, ship the SDK as a wheel/vendored
    copy and install from there. **State the chosen mechanism in the deploy runbook** (Finding 5).
    Verify at deploy: `python -c "from datsme_partner_sdk.host_signature import verify_host_signature"`.
  - fastapi, uvicorn, python-multipart, httpx (already pinned), + Pillow. Acceptance gate
    (R3-2, **reworded in R6** — see below): `pip list` on the Hetzner venv shows **no rembg, no
    onnxruntime, no numpy, no torch** (the ML stack is absent), and the backend imports cleanly with
    `PET_GEN_BACKEND=pool`. **`pet_factory` MAY be present** — but only as a `pip install --no-deps -e`
    **data-only** install (motion profiles are pure JSON the web tier reads; the lazy PEP-562
    `pet_factory/__init__` never pulls the ML factory unless a factory attribute is accessed, which
    the pool backend never does). Confirm: `from pet_factory import motion_profiles` imports while
    `import numpy` fails. This is the analog of the reference queue's "Flask + gunicorn only, no ML libs".
- **DatsPet frontend** (Next.js, `web/`) — built (`next build`) and served (or statically
  exported + proxied). `NEXT_PUBLIC_API_URL=https://pet.datsme.me` (same-origin API; see C.3).

### C.1a Backend proxy for pool worker-state (Finding 9)
The "workshop offline / busy" UI (§9, §A.3) needs pet-worker liveness, which lives behind
`/api/pool` on the pool — **guarded by the `datspet` app key that must NEVER reach the browser.**
Add a tiny backend endpoint (implemented in Part A as `GET /api/workshop-status` — not under
`/api/datsme/` since worker liveness is not DPP-specific) that the *server* calls
`/api/pool` with the key and returns a reduced `{online: bool, busy: bool}` to the frontend. The
key stays server-side; the browser learns only the boolean it needs.

### C.2 Reverse proxy / TLS — same-origin is REQUIRED, not preferred (R4-1)
Add `pet.datsme.me` to the box's proxy (same pattern as `pool.datsme.me` / `datsme.me`): terminate
HTTPS, route `/` to the frontend and `/api`, `/partner`, `/launch` to the backend — **all under the
one origin `https://pet.datsme.me`.**

**This is a hard requirement, not a preference (Rev.4 promotes it from "preferred"; mechanics
refined R5-2).** The DPP launch cookie is bound to the **host that serves `/launch`** — the
`DATSPET_PUBLIC_URL` origin, since the Set-Cookie rides the `/launch` response
(`datsme_integration.py:235-243`; dev masks the distinction because the frontend and backend hosts
are both `localhost`). The browser attaches it only to `fetch`es targeting **that same host**. If
the API host is spelled differently from the cookie host — `localhost` vs `127.0.0.1`, apex vs
`www`, two subdomains — or a `Secure` cookie meets a plain-http non-localhost origin, the cookie is
not sent, `getDatsmeSession()` returns `launched:false`, and the "Accept — send to my DatsMe"
button **silently vanishes with no error** (R4-1, hit live in dev). (Precision, R5-2: cookies are
host-scoped, not origin-scoped — a port-only split like dev's `:19955` page → `:19954` API does
*not* drop them, which is why dev works at all. The deploy rule below is deliberately stricter than
the mechanics require, because byte-for-byte equality is checkable and leaves nothing to reason
about.) Same-origin also makes the
cookie first-party, which lets us drop the `SameSite=None; Secure` cross-origin workaround the dev
port-split required (DPP doc §5.5) in favor of `SameSite=lax` (§C.3, §C.5). This is the prod posture
that doc's Phase 4 already anticipated.

**The origin-consistency invariant (§C.5 states it in full):** `DATSPET_FRONTEND_URL`,
`DATSPET_PUBLIC_URL`, and the browser-inlined `NEXT_PUBLIC_API_URL` must be the **byte-for-byte same
scheme + host + port**. `https://pet.datsme.me` for all three — never mix apex/`www`, never mix
`localhost`/`127.0.0.1`, never mix http/https.

### C.3 Prod env (the dev→prod flip — all values, no code)
| Var | Dev | Prod (`pet.datsme.me`) |
|---|---|---|
| `DATSPET_PUBLIC_URL` | `http://localhost:19954` | `https://pet.datsme.me` |
| `DATSPET_FRONTEND_URL` | `http://localhost:19955` | `https://pet.datsme.me` |
| `NEXT_PUBLIC_API_URL` | `http://localhost:19954` | `https://pet.datsme.me` |
| `DATSME_BASE_URL` | `http://localhost:19994` | `https://staging.datsme.me` → `https://datsme.me` |
| `DATSME_PUBLIC_URL` | `http://localhost:19995` | `https://staging.datsme.me` → `https://datsme.me` |
| `DATSME_HMAC_SECRET` | dev secret | **prod partner secret** (from prod registration, §6) |
| `POOL_URL` | `https://pool.datsme.me` | same |
| `POOL_APP_KEY` | `~/.pool/datspet_key` | prod app key on the box (`/var/www/pool/app_key_datspet`) |
| `DATSPET_COOKIE_SAMESITE` | `none` | `lax` (same-origin behind one proxy; drops the `Secure`-cookie requirement — R4-2) |

**Origin-consistency invariant (R4-1) — the top three rows MUST match byte-for-byte.**
`DATSPET_PUBLIC_URL`, `DATSPET_FRONTEND_URL`, and `NEXT_PUBLIC_API_URL` must be the identical
scheme+host+port (`https://pet.datsme.me`). A single mismatch (apex vs `www`, `localhost` vs
`127.0.0.1`, http vs https) drops the DPP launch cookie and hides the Accept button with no error.
**`NEXT_PUBLIC_API_URL` is inlined into the frontend JS at `next build` time (R4-4)** — set it before
building; flipping it afterward requires a rebuild. See §C.5 for the full rule and its cutover gate.

### C.4 The bundle-fetch reachability requirement (critical, easy to miss)
DPP Accept posts a `bundle_url` = `{DATSPET_PUBLIC_URL}/api/datsme/bundle/{token}`, and the DatsMe
**host fetches it server-to-server** to get the pet bytes. So `pet.datsme.me/api/datsme/bundle/*`
**must be reachable from the DatsMe host** (same box here — trivially reachable) AND the host's SSRF
allowlist for the `datspet` partner must equal `pet.datsme.me`'s origin. This is set by the prod
partner registration (`launch_base_url` origin, §6). Verify explicitly at cutover.

### C.5 Online cookie/session correctness — the invariant that hides the Accept button (Rev.4, R4-1/2/3/4)
This subsection exists because a same-origin/cookie mistake produces the **most confusing possible
failure**: the whole app looks healthy — pages load, pets generate — but the DatsMe hand-off silently
disappears, so it reads as "DPP is unconnected." It cost real debugging time in dev this session; on
a remote box with no shell handy it costs much more. Get these four right and the online DPP flow
works on the first try.

1. **One origin, spelled one way (R4-1; mechanics refined R5-2) — the single-hostname invariant.**
   The precise mechanics: cookies are **host-scoped, not origin-scoped** (the port is ignored; the
   scheme matters only via `Secure`). The Set-Cookie rides the `/launch` **response**, so the DPP
   launch cookie (`datsme_launch`, HttpOnly) is bound to the host serving `/launch` — the
   `DATSPET_PUBLIC_URL` origin, via the registration's `launch_base_url`. A `credentials:"include"`
   fetch carries it only when (a) the fetch target's **host** equals the cookie's host, (b) the
   SameSite policy admits the page→API relationship, and (c) `Secure` is satisfied (HTTPS or
   localhost). That is why dev's port-split works (`localhost:19955` page → `localhost:19954` API:
   same host, SameSite=None) while a `localhost` page calling a `127.0.0.1` API — the dev
   regression — does not. **The enforced rule is the stricter, checkable sufficient condition:**
   `DATSPET_FRONTEND_URL`, `DATSPET_PUBLIC_URL`, and the browser-inlined `NEXT_PUBLIC_API_URL`
   **byte-for-byte identical** scheme+host+port — `https://pet.datsme.me` for all three. Never mix
   `www.` vs apex, `localhost` vs `127.0.0.1`, `http` vs `https`: any host or scheme variance drops
   the cookie, `getDatsmeSession()` → `launched:false`, and the Accept button never renders.
   **No error is logged; generation still works.**

2. **Staging must be real HTTPS, exactly like prod (R4-2).** The cookie is `SameSite=None; Secure`
   until §C.3 flips `DATSPET_COOKIE_SAMESITE=lax`. A `Secure` cookie is sent only over HTTPS **or to
   `localhost`** — a remote plain-HTTP staging box is neither, so the cookie is silently dropped.
   Do **not** stand up an http-only staging vhost to "test quickly"; it will exhibit the no-Accept-
   button failure for a reason unrelated to the code. Terminate TLS for `staging`/`pet` the same way
   prod does. With same-origin behind the proxy, set `DATSPET_COOKIE_SAMESITE=lax` (drops the `Secure`
   dependence and is the correct first-party posture); keep `none` only if some deployment genuinely
   splits frontend/backend origins (it should not — see item 1).

3. **`NEXT_PUBLIC_API_URL` is baked at build time (R4-4).** Next inlines `NEXT_PUBLIC_*` into the
   client bundle during `next build` (or dev-boot). Set the prod value **before** building the
   frontend; changing the env on a running service does nothing until a rebuild. A bundle built with
   the wrong origin points every browser `fetch` at the wrong host — the dev symptom at prod scale.

4. **Deploy hygiene: no stale absolute paths from the source box (R4-3).** "dev→prod is env values,
   not code" holds only if the deploy tree doesn't drag along build/venv artifacts that hardcode the
   *source* path. If the tree is rsync'd/copied rather than freshly checked out: (a) do **not** copy
   `web/.next` — build it on the target (or delete the cache and rebuild); a baked build serves the
   old paths and 500s. (b) Re-create or repair the Python venv on the target — a copied venv has
   script shebangs and editable-install finders pinned to the source path (both bit us this session).
   (c) Install the SDK editable against the *target's* `datsme_me` path (§C.1), and confirm
   `python -c "import pet_factory"` is **absent** on the GPU-less box, not resolving to some copied
   tree. A clean checkout on the target sidesteps all of this.

**Cutover gate (added to §7 steps 6 & 8):** after the proxy/TLS is up, drive a **real launch** end to
end — mint a launch on the staging/prod DatsMe → follow it into `pet.datsme.me` → generate a pet →
**assert the "Accept — send to my DatsMe" button actually renders**, then Accept and confirm the pet
lands in the user's house. This one check exercises every failure in this subsection **and
isolates the cause** (R5-3: the step-6 adoption gate also *fails* when the Accept button is
missing — a pet that builds but cannot be sent never reaches "pet in My Pets" — but it fails
ambiguously, reading as "DPP broken"; the explicit button/session assertion pins the failure to
cookie/origin config and is scriptable).

---

## 6. Part D — Prod partner registration (DatsMe ⇄ pet.datsme.me)

The dev registration used `--skip-validation` bootstrap and pointed at localhost. Prod needs a
registration against the **staging/prod DatsMe** with `pet.datsme.me` URLs:
```
DATSPET_SKIP_VALIDATION=1 ./scripts/register_datspet.sh   # with DATSPET_PUBLIC_URL=https://pet.datsme.me,
                                                          # against the staging DatsMe DB
```
(Recall the chicken-and-egg: the host verifies the manifest signature against the secret it
*generates*, so first registration bootstraps with skip-validation, then wire the printed secret
into `pet.datsme.me`'s `DATSME_HMAC_SECRET` and restart.) After: reconcile the manifest so
`design_a_pet` + `pets.write`/`profile.read` land in the staging catalog (the "Design a pet" button
resolves the partner from there). Then repeat for prod `datsme.me`.

**Two registrations, staged:** staging.datsme.me first (full E2E rehearsal), then datsme.me.
Each is an independent partner row + secret.

---

## 7. Implementation & cutover order (each step verifiable before the next; re-sequenced in Rev.3)

Rev.3 splits the old step 0: **Omen upgrades first** (the fleet is never version-mixed, §B.1),
the dev gate runs against that single known-good node (correctness first, one variable), and the
second generator is added afterwards (fleet behavior second).

1. **Part A code lands** (all of it, this repo): `pool_client.py`, the `app.py` rewire + lazy
   import + `PET_GEN_BACKEND` switch + workshop-status proxy (§C.1a), the **v2**
   `pet_factory` handler, and the `pet_preview` handler. Unit tests green — **including the
   mocked-pool param-passthrough pins (R5-6)**: (a) with a reference image present, the submitted
   params carry `reference_image_b64` + `remix_strength` + `display_name` (mock the pool client,
   assert the submit body); (b) the v2 handler decodes the b64 to a temp path and passes it plus
   both params through to `make_pet_zip` (mock it); (c) the adapter maps `dead→error` (Finding 7)
   and pct 0..100 → fraction 0..1 (R5-1). The step-3 live E2E proves this wiring once; these
   tests keep it proven after launch.
2. **Install v2 + `pet_preview` on Omen FIRST** and restart its worker (§B.1 — Omen is the only
   live pet node, so the fleet stays single-version). *Gate: the §B.1 executable checks — ops
   check, `GET /api/tasks` shows v2 + `pet_preview`, repeated `reference_image_b64` probe submits
   validate (no 422), and a plain `created_pets/make_pet.py` text submit still generates (v2
   accepts v1-shaped params — the new fields are optional).*
3. **Dev gate against Omen alone** — `PET_GEN_BACKEND=pool` on the dev box (generation goes to
   the pool, not the local GPU). *Gate (Finding 1 — the test that catches the reference-image
   drop): the dev E2E must exercise the **full designed flow** — pick a base pet → **Preview this
   design** → **Create my design (from the preview)** → the generated pet **matches the preview**
   (not a text-only pet) → adopted into a DatsMe user's house. Also cover the photo-upload and
   redesign-a-house-pet paths, and assert `display_name` is preserved.* A text→pet-only gate
   would have missed Finding 1 entirely.
4. **Add the second generator:** install v2 + `pet_preview` on **one** dual-nvidia card (§B.2),
   backed by its **own** ComfyUI instance (§8.7). *Gate: two concurrent jobs run in parallel on
   two machines; kill one worker mid-job → the pool reclaims and the other re-runs it (progress
   restarts from zero — `preemptible: "abort"` is by design, not a bug).*
5. **Part C:** deploy the GPU-less web tier to `pet.datsme.me` (backend `--workers 1` + frontend +
   proxy + TLS). *Gate: `https://pet.datsme.me` serves the designer standalone; **`pip list` shows
   no rembg/onnxruntime/numpy/torch** (the ML stack absent — §C.1, R6); `pet_factory` may appear only
   as the `--no-deps` data-only install and `from pet_factory import motion_profiles` imports while
   `import numpy` fails; the SDK + Pillow import cleanly; a standalone
   design → preview → create-from-preview → download works via the pool. **Origin/cookie preflight
   (§C.5): the top three env URLs are byte-for-byte `https://pet.datsme.me`; the frontend was built
   AFTER `NEXT_PUBLIC_API_URL` was set (R4-4); TLS terminates for the vhost (R4-2); no `web/.next`
   or venv was copied from the source box unrepaired (R4-3).***
6. **Part D (staging):** register the partner against `staging.datsme.me`; wire the secret; reconcile.
   *Gate: from staging.datsme.me My Pet → Design a pet → **preview → create-from-preview** → Accept
   → pet in My Pets, credits charged — observed in the DB, mirroring today's dev behavior. **Cookie/
   session gate (§C.5, R4-1): the "Accept — send to my DatsMe" button MUST actually render after the
   real launch — its presence is what proves the launch cookie survived same-origin/TLS. A pet that
   builds but shows no Accept button is the R4-1 failure, not a pass.***
7. **Verify bundle-fetch + SSRF allowlist** explicitly (§C.4). *Gate: the host actually fetched the
   bundle from `pet.datsme.me` (host log), not a queued/failed writeback.*
8. **Part D (prod):** repeat against `datsme.me`. *Gate: same as step 6 including the §C.5 cookie/
   session gate — re-run the "Accept button renders after a real launch" check against prod origins,
   since a per-environment URL/TLS/cookie mismatch would not have shown up on staging.*
9. **Production posture:** retry-queue drain scheduler, result retention/cleanup on the web tier,
   **durable pool-job reattach across web-tier restarts (Opt-1, §A.6)**, monitoring, rate limits
   (carry from DPP spec Phase 4).

A dedicated end-to-end verification script (the analog of the dev `scripts/e2e_design_a_pet.sh`,
pointed at staging URLs) should gate steps 6–8, and **must drive preview → create-from-preview**,
observing the pet + credits in the DB, not just HTTP. **It must also assert the browser-facing
session (§C.5): after the real launch, `GET /api/datsme/session` with the launch cookie returns
`launched:true` from the *same origin the page is served on* — the machine check behind "the Accept
button renders." The dev `e2e_design_a_pet.sh` already builds the cookie and hits `/api/datsme/session`;
the staging variant must do so against `https://pet.datsme.me` (one origin) to catch an R4-1 split.**

---

## 8. Decisions (Rev.3: RESOLVED for implementation — only #6 remains open, and it does not gate code)

1. **Preview path (§A.3) — RESOLVED: A3-a, built at launch.** A separate `pet_preview` task (own
   `timeout_s: 180`, own result shape, ~1 s poll cadence, busy-state 423 mitigation). Build it
   with Part A rather than feature-flagging it off: the preview is the heart of the designed flow
   the goal statement names, and the b64 transport is shared with the build path anyway. (The
   prod feature flag remains a break-glass if `pet_preview` regresses at cutover.)
2. **Reference-image transport (§A.2) — RESOLVED: `reference_image_b64` in `params`** with the
   web-tier ≤1024 px downscale. Verified against the live 200 MB `MAX_CONTENT_LENGTH`
   (`v1_implementation_contract.md:555-558`). The input-by-URL alternative (one-time URL the
   worker fetches, paralleling the DPP `bundle_url` pattern) stays deferred unless b64 bloat
   bites.
3. **`PET_GEN_BACKEND` — RESOLVED: keep the `local|pool` switch.** Dev keeps a no-network
   break-glass; the `local` branch is the only importer of `pet_factory` (§A.4), which is what
   keeps the Hetzner venv ML-dep-free.
4. **Result transport — RESOLVED: pool `bytes` at launch**; revisit `url` later, reconciled with
   the DPP `bundle_url` (§A.5).
5. **Frontend serving — resolve during Part C (non-blocking): static export preferred** — the
   pages are client-side and it is lighter on the CPU-only box; fall back to the SSR service only
   if a route turns out to need it. **Either way, the §C.5 rules bind identically:** a static export
   still bakes `NEXT_PUBLIC_API_URL` at build time (R4-4) and must be served **under the same origin
   as the API** through the proxy (R4-1). Static-vs-SSR changes how bytes are served, not the
   origin/cookie invariant.
6. **`credit_pet_design_cost` prod value — OPEN (product call, per DPP spec open Q1).** Does not
   gate implementation: staging registration proceeds with the dev default (100) until decided.
7. **Worker capacity (Finding 8) — RESOLVED: Omen + exactly ONE dual-nvidia card** (§B.2), and
   the pool pet worker gets its **own ComfyUI instance** (pinned to its card via
   `CUDA_VISIBLE_DEVICES`, own port) rather than sharing dev's :19953 — dev generation and pool
   jobs must not contend. Both-cards parallelism is a later add.
8. **Durable reattach (Opt-1) — RESOLVED: defer to the §7 step-9 production pass.** In-memory
   behavior matches dev today; the pool job still completes server-side and nothing is lost but
   the UI linkage.

---

## 9. Risk / failure-mode summary (runtime failures degrade to "the feature waits," never data loss — the ONE exception is the §C.5 config defect, per R5-4)

| Failure | Effect | Notes |
|---|---|---|
| All GPU workers off | Pet jobs sit `queued`; the "Design a pet" flow shows "workshop offline"; DatsMe + pet.datsme.me stay up. | The pool holds the queue; nothing is lost. Worker-online is surfaced **via the backend proxy over `/api/pool`** (§C.1a) — the app key never reaches the browser (Finding 9). |
| One GPU worker off | The other drains the queue; throughput halves. | Why Part B (2 generators, each own ComfyUI) matters. |
| GPU busy when previewing | Preview returns **423 "workshop busy"** (the backend checks pet-worker busy-state first), preserving today's fast-fail — not a silent multi-minute queue (Finding 2). | §A.3 mitigation — **best-effort (R5-5)**: the check-then-submit race can let an occasional preview queue behind a concurrent build. |
| Worker dies mid-job | Pool crash-reclaim re-runs it on another node (already built). | DPP idempotency (jti) prevents a double adopt. A web-tier restart mid-job orphans the in-memory job tracker unless Opt-1 reattach is built. |
| Pool dispatcher down | No new pets generate; the rest of both sites stays up. | Pool is the always-on tier (already deployed with systemd). |
| DatsMe host can't fetch `bundle_url` | Accept fails/queues; design preserved as a draft; retry covers it. | §C.4 reachability + SSRF allowlist must be correct. |
| **Origin/cookie mismatch on the web tier (R4-1/2)** | **Pets build fine but the "Accept — send to my DatsMe" button never appears — the DatsMe hand-off silently breaks while everything else looks healthy.** Reads as "DPP is unconnected." | **NOT a degrade-to-wait failure — it is a config defect that ships broken and looks fine. Prevented by the §C.5 single-hostname invariant + real-HTTPS staging, and caught by the §7 step-6/8 "Accept button renders" gate. A generation-only smoke test cannot detect it; the step-6 adoption gate fails on it but ambiguously — the explicit gate isolates the cause (R5-3).** |
| pet.datsme.me down | Design-a-pet unavailable; DatsMe core unaffected (DPP is an adapter). | Standalone-first principle holds. |

---

## 10. Consistency checks (global engineering rules)

- **New variant without engine change?** ✓ DatsPet is a pool *client* and a DPP *partner*; no
  change to the pool **engine** (`shared_gpu_cpu/`) or the DatsMe host engine. Generation source is
  swapped behind a config flag, not a fork.
- **Independence boundary held despite the handler change?** ✓ Rev.2 extends the `pet_factory`
  handler (v2 params) and adds a `pet_preview` handler — but both live **in this app repo /
  installed on the node as plugins**, exactly where the boundary's acid test says pet-meaning
  belongs (`application_independence_boundary.md:59`). Nothing in `shared_gpu_cpu/` is touched; the
  handler protocol (`run(params,ctx)`, `params_schema`, `result_kind`) is consumed, not modified.
- **New feature without touching unrelated files?** ✓ Web tier: one new adapter (`pool_client.py`)
  + the two `app.py` call sites + a lazy-import move + a small proxy endpoint. Handlers: one edit
  (v2) + one new file, both in `pool_handler/`. DB/DPP-adapter/frontend logic untouched;
  `requirements.txt` gains Pillow (Finding 4).
- **Third-party integration without modifying owned paths?** ✓ `shared_gpu_cpu` and `datsme_me`
  are consumed over their HTTP contracts + the SDK, not edited.
- **Bug isolation?** ✓ A pool outage, a GPU-worker crash, and a DatsMe outage each fail
  independently and degrade to "wait," per §9. Standalone-local mode keeps a break-glass path.
- **Config correctness verifiable, not just plausible? (Rev.4)** ✓ The one non-degrading failure
  mode — the origin/cookie mismatch (§C.5, R4-1/2) — is now caught by an explicit cutover gate
  (§7 steps 6 & 8: "the Accept button renders after a real launch") and an E2E `session` assertion,
  rather than left to reviewer vigilance. The single-hostname invariant (§C.2/C.3/C.5) is stated as
  a byte-for-byte equality across three env vars, which is mechanically checkable at deploy.

---

### Appendix — grounding (every claim traces to verified reality; Rev.2 + Rev.3 findings verified 2026-07-12, Rev.4 re-verified + online-hardened 2026-07-12, Rev.5 independently re-checked 2026-07-12)

**Rev.4 verification (23 claims, two independent code-reading passes + live probes):** all
substantive claims CONFIRMED; line numbers drift ~4 lines; the only inaccuracy (R3-2) was already
self-corrected by Rev.3. Spot anchors re-confirmed: `webui/app.py:38` (module-top `pet_factory`
import), `:88` (`GPU_LOCK`), `:114-115` (in-memory `JOBS`/`JOBS_LOCK`), `:164-173` (`extract_base_frame`
uses `PIL.Image`), `:280-281` (preview 423 fast-fail); `webui/requirements.txt` has **no Pillow**
(Finding 4 confirmed real); `webui/db.py:42-53` (single module-level SQLite conn); `pet_factory/
factory.py:370,384` (`render_design_still` / `make_pet_zip` six-arg signatures), `:86,99` (rembg lazy),
`:39` (single `PET_FACTORY_COMFY_URL`); `pool_handler/pet_factory_handler.py:23-43` (v1 METADATA,
schema `additionalProperties:False`). Live pool: `/api/pool` shows `omen-pet` advertising
`pet_factory` (v1) with the dual-nvidia workers on `echo`/`sleep_test` only, `pet_preview` absent —
exactly the §0 starting state; `/docs` → 200; app key present.

**Online cookie/origin (R4-1/2/3/4):** `webui/datsme_integration.py:81-82` (`SameSite=None; Secure`
default), `:119-121` (`_frontend_url`), `:235-243` (`/launch` sets the cookie on the frontend origin +
303 to `/design`), `:262-279` (`resolve_launch_identity` verifies the JWT for scoping);
`web/src/lib/api.ts:9` (`NEXT_PUBLIC_API_URL` inlined, `credentials:"include"` on the session/accept
calls). Local resolution fact behind the dev regression: on this box `getaddrinfo("localhost")` →
`127.0.0.1` only (IPv4), and `localhost`/`127.0.0.1` are distinct cookie **hosts** — a same-host
spelling split is enough to drop the cookie. (R5-7: that is libc resolution; browsers use their own
resolver and may prefer `::1` — but the `Origin` header always reflects the *typed* hostname, never
the resolved IP, so resolution order cannot change the cookie/CORS origin of a `localhost`-typed
page.) These are the mechanics §C.5 codifies for the online tiers.

### Appendix (cont.) — original grounding (Rev.2 + Rev.3)
- Pool contract + live generation: `pool.datsme.me/openapi.json`, live job `1467e39a…` (done),
  `created_pets/make_pet.py`, `pool_handler/pet_factory_handler.py`.
- **Reference-image flow (Finding 1):** `web/src/app/design/page.tsx:82,130` (posts base_pet_id +
  preview_id), `webui/app.py:355-388` (`start_job` builds local-path `reference_image` +
  `remix_strength` + `display_name`), `:200` (`run_pet_job` → `make_pet_zip`),
  `pet_factory/factory.py:384` (signature), `:278` (`_prep_reference_image` re-normalizes),
  `pool_handler/pet_factory_handler.py:31-39` (schema `additionalProperties:False`).
- **Transport legality:** `shared_gpu_cpu/pool_contracts/messages.py:81` (`params: dict[str,Any]`),
  `messages.py:18` (`JobStatus … "dead"`), `v1_implementation_contract.md:558` (200 MB prod cap),
  `application_independence_boundary.md:59` (handler acid test).
- **Mixed-fleet mechanics (R3-1):** `pool_dispatcher/app.py:86-95` (submit validated against the
  *resolved* catalog version), `pool_dispatcher/catalog.py:67-84` (`resolve_task` prefers
  online-advertised versions, most-recent tie-break), `pool_dispatcher/scheduler.py:41` (claim
  matching is by task **name**, version-blind), `scheduler.py:63-64` (the claiming node's
  advertised `timeout_s` is the watchdog bound), `messages.py:79-83` (`JobSubmit` carries no
  version), `messages.py:106` (`NodeView.tasks` is names only — versions not in `/api/pool`);
  workers do not re-validate params per job (`pool_worker/`).
- **Lazy GPU stack (R3-2):** `pet_factory/factory.py:86,99` (rembg imported inside `_rembg()` at
  generation time); module-top imports are numpy/requests/PIL only; torch is not a direct dep.
- **Preview / CP-2 (Finding 2):** `webui/app.py:276-278` (423 fast-fail),
  `control_plane_spec.md:28` (per-app admission).
- **GPU-less deps (Findings 3,4,5,6):** `webui/app.py:38` (top import), `pet_factory/__init__.py:6`,
  `webui/app.py:165` (PIL), `webui/requirements.txt:18` (SDK path dep), `webui/app.py:110-111`
  (in-memory JOBS).
- **Single ComfyUI (Finding 8):** `pet_factory/factory.py:39` (`PET_FACTORY_COMFY_URL`), this box's
  one ComfyUI on :19953.
- Env-driven config: `webui/datsme_integration.py:104-121`, `web/.env.local`.
- DNS (all → `5.161.70.13`, incl. `pet.datsme.me`): `dig`.
- DPP integration (built + hardened): `docs/SPEC_DATSPET_DPP_INTEGRATION.md`,
  `docs/RUNBOOK_DPP_E2E.md`.
- Superseded bespoke-queue design: `docs/DESIGN_SPEC_HETZNER_LOCAL_GPU.md` (do not build).
