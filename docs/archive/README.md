# docs/archive — retired specs and reference material

Documents here are **historical**: superseded, never built, or one-shot plans that were
executed to completion. Each archived spec carries an `ARCHIVED <date>` banner at the top
naming the reason and the living successor. Do not implement from these documents; the
authoritative specs live one level up in `docs/`.

| Document | Why archived (2026-07-16) | Living successor |
|---|---|---|
| `DATSME_INTEGRATION.md` | Never built — plan to embed pet generation inside the DatsMe host; the shipped architecture inverted it (DatsPet as standalone DPP partner). | `docs/SPEC_DATSPET_DPP_INTEGRATION.md`, `docs/SPEC_DATSPET_HOUSE_ADOPT.md` |
| `DESIGN_SPEC_APPLICATION.md` | Point-in-time snapshot of the v1.0.0 `pet_factory` library; the code evolved past it (registries, `pose_frames`, design axes). | `docs/SPEC_MOTION_PROFILES.md`, `docs/SPEC_PET_DESIGNER_FLOW.md`, `docs/SPEC_PET_DESIGN_AXES.md`, `CLAUDE.md` |
| `DESIGN_SPEC_COMPUTE_POOL.md` | Origin design study for the compute pool, since built as the sibling `../shared_gpu_cpu` project whose own docs are the authority. | `../shared_gpu_cpu/docs/`, `webui/pool_client.py`, `docs/SPEC_DEPLOY_PETDATSME_POOL.md` |
| `DESIGN_SPEC_HETZNER_LOCAL_GPU.md` | Superseded bespoke-queue deployment — `SPEC_DEPLOY_PETDATSME_POOL.md` §2 says "do not build". | `docs/SPEC_DEPLOY_PETDATSME_POOL.md`, `deploy/CHECKLIST.md` |
| `SPEC_V3_FLEET_ROLLOUT.md` | One-shot v3 handler fleet cutover, executed to completion 2026-07-13. | `deploy/CHECKLIST.md` item A6, `docs/SPEC_DEPLOY_PETDATSME_POOL.md` §B.1 |
| `SPEC_GPU_MEMORY_HYGIENE.md` | Five GPU-memory/observability fixes (F1–F5), executed to completion 2026-07-26 and verified against real builds. **Exception to "do not read": its §10 is live reference — the MEASURED dead ends for generation speed (`--highvram` OOMs, resolution is not a lever, single-expert fringes, `_fill_holes_alpha` is noise) plus the ComfyUI graph+seed caching trap. Read §10 before any generation-speed work.** | the shipped code: `pet_factory/factory.py` constants band + `_CutoutSession`, `webui/app.py` logging, `pool_handler/*.py`; guarded by `pet_factory/tests/test_cutout_hygiene.py` and `webui/tests/test_logging_visibility.py`; re-runnable evidence in `scripts/probe_cutout_arena.py` |
| `*.html` + `*_files/` (untracked) | Browser-saved research pages whose conclusions were absorbed into specs: the two motion studies fed `SPEC_MOTION_PROFILES.md` §3.9; the Phase 3 contact sheet's durable record is `pet_factory/design_axes/calibration/`. | the specs named per row |
