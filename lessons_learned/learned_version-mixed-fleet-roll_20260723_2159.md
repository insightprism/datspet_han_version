# Lessons Learned — a fleet roll nearly left the pool version-mixed

- **Date:** 2026-07-23 21:59
- **Task:** Roll the DatsPet pool to `a89cc3a` / `pet_preview` **v3** across the GPU fleet, to
  turn on upload subject-isolation (`upload_isolate`, SPEC_UPLOAD_LIKENESS Phase 3).
- **Outcome:** Delivered and verified — both pet nodes on v3, isolation working, prod unaffected.
  But it nearly shipped a **version-mixed fleet** (intermittent 422s) because the docs said the
  fleet had one pet node and it had two.

---

## The problem

The roll had to advance every pet node in lockstep: `pet_preview` v3 adds an optional
`isolate_subject` param, and the handler schema is `additionalProperties: false`, so a **v2 node
422s any request carrying `isolate_subject`**. That schema mismatch is the deliberate *fleet gate*
— but it only protects you if **every** node is v3. One stale node still online means isolate jobs
that happen to route there fail, intermittently, with a schema error the user sees as "workshop
couldn't draw."

Every handoff doc and memory said the pet fleet was a **single node** (`omen-pet`). It was **two**:
`omen-pet` **and** `dual-nvidia-pet` — and the second was still on the old **v2** handler, actively
polling and eligible for routing. Trusting the docs and stopping after `omen-pet` would have left a
coin-flip failure in production that is miserable to diagnose (works on retry when it happens to
route to the good node).

Five more snags surfaced during the roll, below.

---

## How it was fixed

### The roll itself
1. **Enumerated the real fleet from the dispatcher**, not the docs: `GET https://pool.datsme.me/api/pool`
   (dispatcher on the Hetzner box, :29996) with header `X-App-Key`. It reported exactly two online
   pet nodes: `omen-pet` and `dual-nvidia-pet`.
2. **`omen-pet`** (`flipper@192.168.0.22`, checkout `/home/flipper/datsme-pet-factory_wu`, handler
   dir `~/.pool/pet_handlers`): its checkout carried an **uncommitted stale worktree** (old
   `_rembg`, v2 handler) that blocked `git pull --ff-only`. Backed the files up, **stashed** (not
   discarded — a node *might* carry a real hotfix) as `omen-stale-worktree-pre-a89cc3a`, then
   fast-forwarded `464095a → a89cc3a`. Copied the v3 handler into the handler dir, cleared
   `__pycache__`, restarted `pool-worker-pet`.
3. **`dual-nvidia-pet`** (this dev box, GPU 1, imports `pet_factory` **live** from
   `/home/markly2/claude_code/datsme-pet-factory_wu`, handler dir `~/.pool/handlers_pet`): engine
   was already `a89cc3a` (it tracks the operator repo), so only the **installed handler copy**
   needed the v2→v3 bump + a restart.
4. **Pre-checked the risky bit before mutating:** `PET_FACTORY_REQUIRE_GPU` is unset on both
   workers, so the new `_rembg` (which fail-fasts when that is set) safely falls back to CPU — the
   advance could not break prod *builds*.

### Verification (real jobs, not status codes)
- **4/4** isolate uploads to staging → **HTTP 200** (the exact path that 422'd before).
- A **full corgi build** through the pool → a valid **833 KB** bundle (`corgi_sprite.png` +
  `manifest.json` + `package.json`, 2048×1024 sheet) — gates the engine change on the node that
  serves prod builds.
- **Prod** txt2img smoke → 200. Prod is safe because its web tier predates `settings_admin`, so it
  *cannot* send `isolate_subject` — it hits the v3 nodes as backward-compatible v2-shaped traffic.

### Durable fixes shipped
- **`scripts/roll_pet_fleet.sh`** — rolls the whole pet fleet by **discovering nodes from the
  dispatcher**, HARD-STOPS if a discovered pet node isn't in its reach-map (the guardrail that
  would have caught node #2), refuses to finish **version-mixed**, and verifies the *runtime*
  (installed handler version grep + optional real upload job), never the installer's output.
- **Corrected the stale "only `omen-pet` serves pets" claims** in the shared_gpu_cpu docs:
  `HANDOFF_BRIEFING.md`, `user_guide.md` (two spots), `v1_implementation_contract.md` — each now
  names both pet nodes and points to `GET /api/pool` as the authority.
- **Recorded the new fleet state** in project memory (`datspet-pool-deploy-state`).

---

## Lessons learned

1. **The dispatcher is the ONLY source of truth for fleet membership.** `GET /api/pool` before
   *and* after every roll. Never trust a doc, a memory, or a handoff note for "how many nodes" or
   "which node serves task X" — those go stale silently; the running fleet does not. A roll tool
   should *discover* the node set and hard-stop on any node it can't reach, rather than replay a
   hardcoded list.

2. **A node checkout can carry uncommitted local edits.** Step 0 of any roll is `git status`
   (scoped to the files you're rolling — here `pet_factory/` + `pool_handler/`) on each node.
   Keep node checkouts clean so a roll is a pure fast-forward. If dirty, **stash, don't discard** —
   a node may carry a genuine local hotfix (diff it against the target before assuming it's stale).

3. **Don't assume node symmetry.** These two nodes differ on handler dir, engine source (one runs
   from its own git checkout, one imports the package live from the operator repo), GPU id, and
   ComfyUI URL. Capture per-node facts explicitly. And remember the **installed handler is a COPY**
   — advancing git does not touch it; you must copy the file + clear `__pycache__` + restart, then
   grep the installed version to confirm.

4. **Reproduce a worker's behavior with its FULL environment, not part of it.** A birefnet cutout
   repro run *without* `CUDA_VISIBLE_DEVICES=1` landed on the full GPU 0 and OOM'd — I briefly
   concluded the feature was broken and nearly started a needless CPU-fallback rewrite. The worker
   actually uses the near-empty GPU 1. A partial-env repro tests a different thing than the worker
   does. (Same reflex as "a CORS error is often a backend 500" — verify against the *actual*
   conditions, not a lookalike.)

5. **Verify the runtime, gate on real jobs.** `pool-install-handler --restart` has printed
   "restarted" while the restart failed; installers lie. Check the unit is actually up, grep the
   installed handler version, and submit a **real job** (an isolate upload + a full build that
   produces a valid bundle). This repo's deploy history is "every failure was a false green" — a
   status code is a proxy for the thing, not the thing.

6. **Derive service state from the service's own env.** Flipping `upload_isolate` writes a SQLite
   row; getting `PETMAKER_OUTPUT_DIR` from the service's actual `.env` (not a default) is what
   makes you edit the *right* db. Assume-the-default → "no such table" on the wrong file.

---

## References

- Roll tool: `scripts/roll_pet_fleet.sh` (dry-run: `scripts/roll_pet_fleet.sh --dry-run`)
- Deploy gate: `scripts/verify_deployment.sh <url>` (real jobs, not status codes)
- Fleet state / topology: memory `datspet-pool-deploy-state`; dispatcher `GET :29996/api/pool` + `X-App-Key`
- Spec: `docs/SPEC_UPLOAD_LIKENESS.md` (Phase 3 = the `upload_isolate` runtime toggle)
- Nodes: `omen-pet` = `flipper@192.168.0.22`; `dual-nvidia-pet` = this dev box, GPU 1, `comfyui-pool` :19956
- Rollback breadcrumb: omen stash `omen-stale-worktree-pre-a89cc3a`; both nodes' prior handler was v2
