# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

**DatsPet / pet_factory** — type an animal name, get a ready-to-use DatsMe pet. Two layers:

1. **`pet_factory/`** — a pip-installable engine: `make_pet_zip("red panda")` → a DatsMe breed bundle `.zip` (sprite sheet + manifest.json + package.json). The pipeline drives a local ComfyUI over HTTP (Z-Image base sprite → Wan 2.2 I2V walk/idle loops → birefnet cutout) and reads generated files from ComfyUI's output dir (shared filesystem required). ~3 min on an RTX 3090.
2. **The Pet Maker web app** — `webui/` (FastAPI backend) + `web/` (Next.js frontend), with a DatsMe partner (DPP) integration and a `shared_gpu_cpu` compute-pool backend so the same app runs on a GPU-less box in production.

Sibling repos this one talks to (peers under `claude_code/`): `../ComfyUI` (the render engine), `../datsme_me` (the DatsMe host; provides `datsme_partner_sdk` installed editable from `../datsme_me/api/sdk`), `../shared_gpu_cpu` (the compute pool).

`docs/SPEC_*.md` are the authoritative design specs; code comments cite them by section (e.g. `SPEC_MOTION_PROFILES §3.7`). Read the cited spec section before changing code that references one.

## Commands

```bash
# Tests (no GPU needed; each test gets an isolated temp SQLite DB)
.venv/bin/python -m pytest pet_factory/tests webui/tests
.venv/bin/python -m pytest webui/tests/test_scoping.py -k adopt   # single test

# Frontend (from web/)
npm run dev                 # dev server on :19955
npx tsc --noEmit            # typecheck — use this, NOT `next build`, while dev runs
npm run lint

# Full local stack: ComfyUI :19953 → backend :19954 → frontend :19955
./start_all.sh              # idempotent; logs to logs/<name>.log; Ctrl+C stops what it started
./start_comfyui_only.sh / ./start_petmaker_backend_only.sh / ./start_petmaker_frontend_only.sh

# One pet from the CLI (needs ComfyUI up)
./make_pet.sh "red panda" -o out.zip

# Full DPP round-trip E2E (real GPU generation + local datsme_me host; verifies the
# result in the host's SQLite + credit ledger)
./scripts/e2e_design_a_pet.sh
```

**Never run `next build` while the dev server is live** — they share `.next/` and the build poisons the dev server's cache (blank screens, `ENOENT …pack.gz_` errors). `web/scripts/guard-build-vs-dev.js` blocks this at build time; don't override it, typecheck with `tsc --noEmit` instead.

**Environment**: every backend/factory entry point needs `source pet_env.sh` first (the `start_*.sh` scripts do this). It sets `PET_FACTORY_COMFY_URL` (:19953, not the upstream :8188 default), the absolute ComfyUI output dir, `LD_LIBRARY_PATH` for GPU cutout, and sources the gitignored `pet_env.local.sh` (secrets, e.g. `DATSME_HMAC_SECRET`). A backend started without it fails confusingly on the first generation.

**Ports** follow the 1995x group: frontend ends in 5, backend in 4, ComfyUI in 3 (mirrors datsme_me's 19995/19994).

**Deploy**: **`deploy/CHECKLIST.md` is the procedure — follow it top to bottom.** Every item on it exists because something broke; §E logs the incident behind each one and is where new ones get added. `deploy/README.md` is the reference (topology, one-off setup). Git bundle → Hetzner box; prod `pet.datsme.me` on :29954, staging twin `pet-staging.datsme.me` on :29964. Deploy only on explicit request.

Two things about this app's deploys that cost a day on 2026-07-15 and are not guessable: **the repo's `deploy/nginx-default.conf` is PRODUCTION's** (hardcoded `:29954`) — `cp`ing it onto staging silently points staging at the prod backend; and **every deploy failure so far has been a false green**, so `scripts/verify_deployment.sh <url>` (which submits real jobs to the real pool) is the gate that counts, not a status code.

## Architecture

### The GPU-less posture (load-bearing — do not break)

Production runs the web tier on a box with **no GPU and no ML packages** (`PET_GEN_BACKEND=pool`). This works because:

- `pet_factory/__init__.py` is **lazy (PEP 562)**: `from pet_factory import motion_profiles` (or `animal_catalog`, `tiers`) imports pure data only. `make_pet_zip` / `render_design_still` drag in the ML stack **at attribute access time**, never at app import.
- `webui/app.py` imports `pet_factory`'s heavy functions only inside the `PET_GEN_BACKEND=local` branch, lazily.
- In prod, `pet_factory` is installed **`pip install --no-deps -e`** so its data subpackages are importable while numpy/rembg/onnxruntime stay absent. The deploy gate is literally "`import numpy` must fail."

Consequence: **never add a module-top import of ML deps (numpy, PIL-beyond-webui's-own-pin, rembg, torch) to `webui/` or to `pet_factory`'s data subpackages.** New pure-data content belongs in a data subpackage; new ML code belongs behind the lazy factory boundary.

### Engine vs. content (the repo-wide pattern)

Runtime code never branches on species/variant; variants are data files + registries with guard tests that fail the build on a half-formed entry:

- `pet_factory/motion_profiles/` — one JSON per body type + `registry.json`. Every profile declares the **full canonical pose key set** (disabled poses are `{"enabled": false}`); there is **no inheritance**. Resolution never raises — unknown animals/keys fall back to `registry.default` (`quadruped`). Two entry points: `resolve_motion_profile(animal)` (keyword) and `load_motion_profile(key)` (pinned).
- `pet_factory/animal_catalog/` — `catalog.json` + one `base.png` per breed. Returns motion-profile *key strings*; cross-layer validity is enforced by guard tests, not runtime imports.
- `pet_factory/tiers/` — entitlement table (pose caps, extra-pose price). Capability→tier mapping is data (`capability_tiers`); `default_tier` is the one-line launch lever. The browser only ever sees its own resolved entitlement.
- `pet_factory/design_axes/` — the step-2 design vocabulary as content (`SPEC_PET_DESIGN_AXES`; absorbed the old `body_shapes/` in the Phase 0 migration). One JSON per axis + `registry.json`: **universal** axes (body/pattern/expression — every animal) and **surface** axes (coat/plumage/scales — exactly one shows, gated by the animal's `surface` tag on the catalog, resolved at fill time like `motion_profile`; unknown animals get universal axes only). A body **shape** is a step-2 *design* modifier — never confuse it with **body type**, taken repo-wide for the motion taxonomy. `prompt_fragment` feeds `compose_design` and never reaches the browser (tier-table posture); each axis default's fragment is `""` and guard tests pin it, plus a computed worst-case-length guard against the pool handler's 600-char param cap. Adding an option or a whole axis is one JSON edit.
- `web/src/pet/behaviorRegistry.ts` and `web/src/pet/locomotion/registry.ts` — the same plugin-registry pattern in the frontend pet runtime.

### Backend (`webui/`, FastAPI on :19954)

- `app.py` — generate/job/pets API. One generation job at a time in a worker thread (the pipeline owns the whole GPU). `PET_GEN_BACKEND` selects `local` (in-process `make_pet_zip` → ComfyUI) or `pool` (route to shared_gpu_cpu); only the generation *source* changes.
- `db.py` — the single SQLite store (`datspet.db`); pet bytes live in-row as blobs. Identity scoping is a nullable `external_user_id` (NULL = standalone, set = DatsMe-launched) applied as a **WHERE clause, never an engine fork**. Timestamps here are unix epoch floats (`time.time()`), not ISO strings.
- `datsme_integration.py` — the DPP partner adapter (`/partner/*`, `/api/datsme/*`). Standalone-first: with `DATSME_HMAC_SECRET` unset the manifest 503s and the whole surface is inert. Writebacks carry a *pointer* (bundle_url + sha256 + one-time token); the host fetches the bundle server-to-server. One DatsPet instance serves exactly ONE DatsMe host.
- `pool_client.py` — the **one adapter** that knows pool endpoint URLs. It translates pool status `dead` → web `error` and pool `pct` (0..100) → fraction (0..1) to match the local path's callback exactly.
- `motion_admin.py` — admin CRUD for motion profiles, gated by the adm-claim cookie; validation is shared with the guard tests so the admin can't write a profile the build would reject.
- `requirements.txt` **pins fastapi==0.115.6 / starlette==0.41.3** — on a mismatched pair, `include_router` silently mounted zero routes. Re-pin only after proving `include_router` works on the new pair (the test suite exercises it).

### Frontend (`web/`, Next.js 14 on :19955)

- `src/lib/api.ts` is the one adapter to the backend — every endpoint URL lives there. Use `localhost`, never `127.0.0.1`: the DPP launch cookie is host-scoped, and a hostname mismatch silently drops it (Accept button disappears). In dev, an empty `NEXT_PUBLIC_API_URL` means same-origin calls proxied by next.config; prod is a static export (`DATSPET_STATIC_EXPORT=1 NEXT_PUBLIC_API_URL=https://pet.datsme.me npm run build`).
- `src/pet/` is the client-side pet runtime (canvas engine, behavior/locomotion registries, personality). Pages under `src/app/design/*` are the themed designer surfaces.
- **There is exactly ONE designer: `src/app/design/general/`** — the three-step flow of `SPEC_PET_DESIGNER_FLOW` (archetype → design → animation), built on the `reference_id` contract. This is where the DPP launch lands (`/design` 307s to it; the deep-link target must never 404). Every step is *work → look → 🔒 lock*, and the lock is a gate: the next step's controls are not mounted until it is pressed. `designFlow.ts` is the pure state machine — the invalidation rules are the product, so they live in one reducer rather than across a dozen `useState`s.
- **The themed pages, `/make`, and `components/PetDesigner.tsx` are DELETED** (`SPEC_PET_DESIGNER_FLOW` §11), and with them the whole legacy `/api/generate` contract. `SPEC_PET_DESIGNER_PLATFORM` §3 still describes the themed pages and is **substantially out of date** — do not treat it as current until it is revised (§11.3). Adopt-a-sample's backend endpoint is still live but has no UI.

### Pool handlers (`pool_handler/`)

Task handlers *installed onto* shared_gpu_cpu worker nodes (`pool-install-handler`); the pool never imports app code — it only defines the `METADATA` + `run(params, ctx)` interface. `pet_factory_handler.py` (full ~3 min build) and `pet_preview_handler.py` (~10 s design-page preview PNG) are deliberately separate tasks with different params/results/timeouts.

### Everything else

- `examples/` — CLI plus the queue-server + worker pattern for GPU-less backends.
- `created_pets/` — scratch pets generated through the live pool (`python3 make_pet.py "penguin"` from that dir); contents gitignored.
- `pet_factory/animal_catalog/**/*.zip` is deliberately un-gitignored — curated sample bundles are content that ships with the catalog.
