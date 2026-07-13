# SPEC — v3 `pet_factory` handler fleet rollout (the motion-profiles cutover)

**Status:** Design — **Rev.1** (2026-07-13), **execution-ready**. Grounded against the live fleet.
This is the standalone runbook for the prerequisite named in `SPEC_PET_DESIGNER_PLATFORM.md` §8 step 0
and `SPEC_DEPLOY_PETDATSME_POOL.md` §B.1: getting the **v3 `pet_factory` handler onto every pet-capable
GPU node before any web tier submits v3 params.** The v3 handler (with `poses` + `motion_profile`) is
already in the repo (`pool_handler/pet_factory_handler.py`, `"version": "3"`); this doc is only the
*deploy* of it to the fleet.

**Why this is a prerequisite, not a step.** The shipped design page appends `poses` to the generate
request (`web/src/app/design/page.tsx:207`), and the pool fleet serves only **v2** today
(`GET /api/tasks` → `pet_factory` v1+v2, no v3 — verified). A v2 dispatcher validates `poses` against
the v2 schema, whose `additionalProperties:False` **422-rejects it**. So the moment a user picks one
optional pose against a pool backend, generate fails. No web tier running the current selector may
deploy against the pool until this rollout completes.

**Scope guard.** Handler install + worker restart on the two owned GPU nodes, plus the §B.1 gate. This
doc changes **no code**, touches **no web tier**, and modifies **neither `shared_gpu_cpu` nor
`datsme_me`**. Rollback is one file copy + one restart per node.

---

## 0. What is already TRUE (verified 2026-07-13, on the live fleet)

| Fact | Evidence |
|---|---|
| **The fleet is TWO pet nodes, both online**: `omen-pet` and `dual-nvidia-pet`, each advertising `pet_factory` + `pet_preview`. | `GET /api/pool`. |
| **Both serve v2 today.** The installed `pet_factory_handler.py` on each is `"version": "2"`; the catalog shows v1 (stale orphan) + v2. | node handler files + `GET /api/tasks`. |
| **The v3 handler is in the repo**, validated (`TaskMeta` OK, v2/v1 submits still validate). `poses`/`motion_profile` are **optional** — a v2-shaped `{animal}` submit still passes v3's schema. | `pool_handler/pet_factory_handler.py`; the review-fix commit `6e13aba`; 60 tests green. |
| **Both nodes are reachable and their layout is known.** `omen-pet` = `ssh flipper@192.168.0.22`, handlers dir `/home/flipper/.pool/pet_handlers`, worker unit `pool-worker-pet.service`, dedicated ComfyUI. `dual-nvidia-pet` = THIS box, handlers dir `/home/markly2/.pool/handlers_pet`, worker unit `pool-worker-pet.service`, dedicated ComfyUI on GPU 1 (`comfyui-pool.service`, :19956). | SSH + `systemctl show`. |
| **The install CLI exists.** `pool-install-handler` at `shared_gpu_cpu/pool_cli/install_handler.py` validates a handler against the same guard the build uses, copies it into `POOL_HANDLERS_DIR`, and restarts the named unit. It installs on **THIS node** (invariant 1: the pool never pushes to a worker), so it runs per-node. | Earlier Part B work; `install_handler.py`. |
| **The pet pipeline on both nodes already runs the design-capable `pet_factory`** (walk/idle/run + `render_design_still`), from the Part B cutover. So v3's pose loop has real code to call — no pipeline change needed. | Part B validated `omen-pet` end-to-end; this box built multi-pose pets locally. |

### The one structural difference from the v2 rollout (why this needs care)

The v2 rollout began with **one** pet node (Omen), so "upgrade Omen first" meant the fleet was *never*
version-mixed. **v3 starts with two pet nodes**, so there is an unavoidable window where one node is v3
and the other is v2. This doc's ordering minimizes and gates that window — it does not eliminate it,
because you cannot atomically restart two machines. §3 explains why the window is nonetheless **safe**
for v3 specifically (v3's new fields are optional, so a v2 node claiming a v3 job degrades to
walk+idle, not an error — the same non-fatal degradation the platform already tolerates pre-rollout).

---

## 1. The hazard, stated exactly (from deploy §B.1 / R3-1)

Submits carry **no version**. The dispatcher validates a submit against whichever `pet_factory`
version `resolve_task` resolves — it prefers a version advertised by an **online** node, tie-broken by
most-recent advertisement (`catalog.py:67-84`). The scheduler then matches jobs to nodes **by task
name only** (`scheduler.py:41`), and **workers never re-validate params per job**. Consequences on a
mixed v2/v3 fleet:

- **Validation flap (transient 422s).** With a v2 node and a v3 node both online, a submit carrying
  `poses` is validated against whichever version wins the tie-break. When v2's schema wins, `poses`
  hits `additionalProperties:False` → **422**. So during the mixed window, pose-carrying submits are
  *intermittently* rejected.
- **Silent degrade (v2 node claims a v3 job).** When a `poses` submit *does* validate (v3 won the
  tie-break), the scheduler may still hand it to the **v2 node**, which ignores `poses` and builds
  **walk+idle only**. No error — the user silently gets fewer poses than they picked.

**Neither is catastrophic for v3** (unlike v2's reference-image drop, which produced a *wrong* pet):
the worst case is "fewer poses than requested," and it only occurs during the mixed window, only for
submits that actually carry `poses`, and only against the pool backend. But both are user-visible, so
the window must be **short and gated**, and **nothing should submit `poses` to the pool until the
window closes.**

---

## 2. Rollout order (both nodes → single-version v3 fleet)

The safe order is: **upgrade both pet nodes to v3 back-to-back with no `poses` traffic in between,
then open the gate.** Because v3 is a strict superset of v2 (v2 submits still validate on v3), a
v3 node serves *existing* v2 traffic identically — so upgrading a node "early" never breaks the
current (v2) production path. That is what makes back-to-back upgrades safe.

**Precondition (do first): freeze `poses` traffic to the pool.** Until both nodes are v3, no web tier
pointed at the pool may submit `poses`. Today this is already true (dev is `PET_GEN_BACKEND=local`;
prod runs older code without the selector) — but **confirm it**, and do NOT deploy the current
selector-carrying web tier to any pool-backed environment until §4 passes. This is the real gate: the
handler rollout is safe at any pace *as long as no `poses` submit races it.*

**Step 1 — Back up both nodes' current v2 handler** (one-step rollback insurance).
On each node, copy the installed handler + note the worker unit:
```
# omen-pet:
ssh flipper@192.168.0.22 'cp /home/flipper/.pool/pet_handlers/pet_factory_handler.py \
    /home/flipper/.pool/backup_v2_$(date +%Y%m%d_%H%M%S)_pet_factory_handler.py'
# dual-nvidia-pet (this box):
cp /home/markly2/.pool/handlers_pet/pet_factory_handler.py \
    /home/markly2/.pool/backup_v2_$(date +%Y%m%d_%H%M%S)_pet_factory_handler.py
```

**Step 2 — Get the v3 handler file onto each node.** The v3 handler is
`pool_handler/pet_factory_handler.py` in this repo (already on `dual-nvidia-pet` = this box). For
`omen-pet`, the node has the `_wu` repo clone from Part B — update it, or scp the single file:
```
# omen-pet already has /home/flipper/datsme-pet-factory_wu (Part B). Pull the v3 handler:
ssh flipper@192.168.0.22 'cd /home/flipper/datsme-pet-factory_wu && git fetch origin && git checkout origin/main -- pool_handler/pet_factory_handler.py && grep \"\\\"version\\\"\" pool_handler/pet_factory_handler.py | head -1'
# expect: "version": "3"
```
(If Omen's clone can't reach the remote, `scp pool_handler/pet_factory_handler.py flipper@192.168.0.22:/tmp/` and install from there.)

**Step 3 — Install v3 + restart the worker, ONE node, then the other.** Use `pool-install-handler`
(validates before copying, then restarts the unit so it re-advertises). Do `dual-nvidia-pet` and
`omen-pet` back-to-back — the goal is the mixed window measured in **seconds/minutes**, not hours.
```
# dual-nvidia-pet (this box):
POOL_HANDLERS_DIR=/home/markly2/.pool/handlers_pet \
  /home/markly2/claude_code/shared_gpu_cpu/.venv/bin/python -m pool_cli.install_handler \
  pool_handler/pet_factory_handler.py --restart pool-worker-pet

# omen-pet (worker venv verified: /home/flipper/sheet_music_app/anim_studio/venv/bin/python):
ssh flipper@192.168.0.22 'cd /home/flipper/datsme-pet-factory_wu && \
  POOL_HANDLERS_DIR=/home/flipper/.pool/pet_handlers \
  PYTHONPATH=/home/markly2/claude_code/shared_gpu_cpu \
  /home/flipper/sheet_music_app/anim_studio/venv/bin/python -m pool_cli.install_handler \
  pool_handler/pet_factory_handler.py --restart pool-worker-pet'
```
(That venv is the one Omen's pet worker runs from — verified via `systemctl show`. It must have
`pool_cli` importable, i.e. the `shared_gpu_cpu` tree on `PYTHONPATH` or installed; adjust the path if
Omen's copy lives elsewhere. `--restart` re-advertises within one poll.)

**Step 4 — Run the §4 gate.** Only after it passes may a `poses`-carrying web tier deploy to the pool.

**`pet_preview` is untouched.** It is a separate task, unaffected by the `pet_factory` version bump —
do not reinstall it.

---

## 3. Why the mixed window is safe for v3 (and was NOT fully safe for v1→v2)

| | v1 → v2 (reference image) | v2 → v3 (poses) |
|---|---|---|
| New fields | `reference_image_b64`, `remix_strength`, `display_name` | `poses`, `motion_profile` |
| Old node claims new job → | **wrong pet** (text-only, ignoring the reference image — a silent *correctness* failure) | **fewer poses** (walk+idle, ignoring `poses` — a silent *degradation*, not a wrong pet) |
| Mixed-window blast radius | high — a paid design comes out wrong | low — the pet is correct, just missing optional poses |
| Mitigation | strict single-version ordering (Omen was the only node) | back-to-back upgrade + freeze `poses` traffic until both are v3 |

The takeaway: **v3's optional-field design means the fleet never produces a *wrong* pet during the
window** — the failure mode is bounded to "missing optional poses," and the `poses`-traffic freeze
removes even that. This is exactly the Rev.5 "optional fields are cutover-safe" property the deploy
spec §B.1 documented.

---

## 4. The gate — executable, run after both nodes are restarted (deploy §B.1 (a)-(d) for v3)

Version is not in `/api/pool` (`NodeView.tasks` is names only) and `/api/tasks` includes stale
entries, so verify with **both an ops check and live probes**:

**(a) Ops check — both nodes serve v3, both restarted.**
```
ssh flipper@192.168.0.22 'grep "\"version\"" /home/flipper/.pool/pet_handlers/pet_factory_handler.py'   # "version": "3"
grep '"version"' /home/markly2/.pool/handlers_pet/pet_factory_handler.py                                  # "version": "3"
# both workers restarted (check `systemctl show -p ActiveEnterTimestamp pool-worker-pet` is recent on each)
```

**(b) Catalog shows v3.** `GET /api/tasks` lists a `pet_factory` v3 entry whose params include `poses`
and `motion_profile`:
```
curl -s -H "X-App-Key: $KEY" https://pool.datsme.me/api/tasks | \
  python3 -c "import sys,json; [print(t['version'], sorted(t['params_schema']['properties'])) \
  for t in json.load(sys.stdin) if t.get('task')=='pet_factory']"
# expect a row: 3 [..., 'motion_profile', 'poses', ...]
```

**(c) Probe: a `poses`-carrying submit validates REPEATEDLY (no 422).** Since `resolve_task` only
resolves online-advertised versions, consistent acceptance across several submits means **no online
node is still advertising v2** for `pet_factory`. Submit 3–5 times:
```
for i in 1 2 3 4 5; do
  curl -s -o /dev/null -w "%{http_code}\n" -X POST https://pool.datsme.me/api/jobs \
    -H "X-App-Key: $KEY" -H "Content-Type: application/json" \
    -d '{"task":"pet_factory","params":{"animal":"probe dog","poses":{"walk":true,"run":true},"motion_profile":"quadruped"}}'
done
# expect: 201 every time (never 422). A single 422 = a v2 node is still online → a worker didn't restart.
```

**(d) A v2-shaped submit still works** (backward-compat — the new fields are optional):
```
curl -s -o /dev/null -w "%{http_code}\n" -X POST https://pool.datsme.me/api/jobs \
  -H "X-App-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"task":"pet_factory","params":{"animal":"probe cat"}}'
# expect: 201 (a plain {animal} submit validates on v3).
```

**(e) End-to-end (optional but recommended): let one probe finish and assert the pose loop.** Poll a
`poses:{walk,run}` job to `done`, fetch the result, assert the manifest `animations` map has `walk` +
`run` (not just walk+idle) and the `motion_profile` pin governed the build (manifest `movement_class`
matches). This is the true confirmation v3 *does* the new thing, not just validates it.

**Gate passes when (a)–(d) all hold** (and ideally (e)). Cancel/ignore probe jobs — they run on the
GPUs (~3 min each); keep the probe count small, or point them at a throwaway animal.

---

## 5. Rollback (if the gate fails or a v3 build misbehaves)

Per node, restore the v2 handler and restart — one file copy + one restart:
```
# dual-nvidia-pet:
cp /home/markly2/.pool/backup_v2_<stamp>_pet_factory_handler.py /home/markly2/.pool/handlers_pet/pet_factory_handler.py
systemctl restart pool-worker-pet   # (sudo if needed)
# omen-pet: same with its backup path + ssh
```
Because v3 is a superset of v2, rolling *back* is also safe for existing traffic — a v2 fleet serves
every current (non-`poses`) submit identically. The only thing lost on rollback is the pose feature,
which stays frozen (no `poses` traffic) until the next attempt.

---

## 6. Ordering relative to the platform + prod deploy

This rollout is **step 0 of the platform** and also the gate for **any prod/staging web-tier deploy of
the current `main`** (which carries the pose selector). The clean sequence:

1. **This rollout** (both pet nodes → v3, §4 gate green). Fleet is now v3, `poses`-ready.
2. **Then** the web-tier deploy can proceed — including the `--no-deps -e` `pet_factory` install
   (deploy spec Rev.6) and the §C.5 origin/cookie checks. Prod/staging may now run the selector.
3. **Then** the platform steps (SPEC_PET_DESIGNER_PLATFORM §8 steps 1–6) build on top.

Until step 1's gate is green, **do not deploy any selector-carrying web tier to a pool-backed
environment.** That single rule is the whole point of this spec.

---

## 7. Consistency checks (global engineering rules)

- **New variant without an engine change?** ✓ v3 is a handler-file + restart per node; `shared_gpu_cpu`
  is untouched (the handler is a plugin the pool runs, never imports).
- **No host change?** ✓ `datsme_me` is not touched — this is pool-fleet only.
- **Bug isolation / reversibility?** ✓ Each node is independent; rollback is one file + one restart;
  v3⊇v2 means neither the roll-forward nor the roll-back breaks existing traffic.
- **Fail-loud where it matters?** The gate's probe-repeatedly check (c) is the fail-loud net: a single
  422 across repeated `poses` submits proves a node didn't restart, caught before real traffic.

### Appendix — grounding (verified 2026-07-13)
- v3 handler (optional `poses`/`motion_profile`): `pool_handler/pet_factory_handler.py` (`"version":"3"`).
- Frontend sends `poses`: `web/src/app/design/page.tsx:207`.
- Fleet is v2, two pet nodes: `GET /api/pool`, `GET /api/tasks` (live).
- Node layout: `omen-pet` (ssh flipper@192.168.0.22, `/home/flipper/.pool/pet_handlers`,
  `pool-worker-pet.service`), `dual-nvidia-pet` (this box, `/home/markly2/.pool/handlers_pet`,
  `pool-worker-pet.service`, `comfyui-pool.service` :19956).
- Install mechanism: `shared_gpu_cpu/pool_cli/install_handler.py` (validate → copy → restart, per-node).
- The §B.1 hazard + gate this mirrors: `docs/SPEC_DEPLOY_PETDATSME_POOL.md` §B.1 (R3-1).
