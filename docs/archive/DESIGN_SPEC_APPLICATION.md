> **ARCHIVED 2026-07-16 — point-in-time snapshot, no longer current.** Descriptive spec of the
> v1.0.0 library; the code has evolved past it (three-function public API, `pose_frames`
> generalization, `motion_profiles/`/`animal_catalog/`/`design_axes/`/`tiers/` registries, the
> design-axes designer). Current authority: `docs/SPEC_MOTION_PROFILES.md`,
> `docs/SPEC_PET_DESIGNER_FLOW.md`, `docs/SPEC_PET_DESIGN_AXES.md`, and the CLAUDE.md
> architecture section. Kept for historical reference.

# Design Spec — the pet_factory application

**Status:** descriptive spec of the application as it exists today (v1.0.0). Written
from the code, not from intent — every claim below is verifiable in the source.
**Audience:** anyone modifying, extending, or reviewing the `pet_factory` package or
its example programs.
**Scope:** the *application* — the library's architecture, the pipeline stages and
their data contracts, the ComfyUI integration layer, the image post-processing, the
output bundle format, error handling, and the extension points. Deployment and
infrastructure are **out of scope** here (see the doc map below).

### Where this spec sits among the repo's documents

| Document | Question it answers |
|---|---|
| `README.md` | How do I install, configure, and call it? |
| `HOW_IT_WORKS.txt` | What does it do, in plain English, and why those choices? |
| **`DESIGN_SPEC_APPLICATION.md`** (this file) | **How is the application built — modules, stages, contracts, failure behavior, extension points?** |
| `DATSME_INTEGRATION.md` | How does DatsMe (the consuming app) wire this in safely? |
| `DESIGN_SPEC_HETZNER_LOCAL_GPU.md` | How is it hosted (VPS + home GPU workers)? |
| `DESIGN_SPEC_COMPUTE_POOL.md` | How does the queue pattern generalize beyond pets? |

---

## 1. One-sentence description

`pet_factory` is a **GPU pipeline orchestrator**: given an animal name, it drives a
local ComfyUI server through three generation jobs (one still image, two looping
videos), post-processes the resulting frames on its own (background cutout, hole
filling, resizing), and packs them into a DatsMe breed bundle (`.zip`) — returned
as bytes from a single synchronous function call.

## 2. Architecture overview

### 2.1 The components

```
             ┌──────────────────────────── GPU box ────────────────────────────┐
             │                                                                 │
 caller ───▶ │  pet_factory (this package)              ComfyUI (separate app) │
 (CLI /      │  ┌─────────────────────────┐   HTTP      ┌───────────────────┐  │
  worker /   │  │ make_pet_zip()          │──/prompt───▶│ Z-Image, Wan 2.2  │  │
  backend    │  │  · builds workflow JSON │◀─/history───│ (the actual       │  │
  task)      │  │  · polls for completion │             │  models live here)│  │
             │  │  · reads output files ◀─┼─────────────┤ writes to output/ │  │
             │  │  · birefnet cutout      │  shared FS  └───────────────────┘  │
             │  │  · packs the .zip       │                                    │
             │  └─────────────────────────┘                                    │
             └─────────────────────────────────────────────────────────────────┘
```

Three parties, two boundaries:

1. **The caller ↔ pet_factory boundary** is a plain Python function call:
   `make_pet_zip(animal, on_progress, breed_id) -> (breed_id, zip_bytes)`. No
   state survives the call; nothing is written outside temp dirs. The caller
   decides what the bytes become (a file, an HTTP upload, a DB blob).
2. **The pet_factory ↔ ComfyUI boundary** is HTTP *plus a shared filesystem*.
   Workflows are submitted as JSON node-graphs over HTTP; completion is detected
   by polling; but the actual output files are read **directly from ComfyUI's
   output directory on disk** (`PET_FACTORY_COMFY_OUTPUT`). This is why the
   library must run on the same machine as ComfyUI — a deliberate constraint
   (§8.3) that keeps multi-hundred-MB video handling off the HTTP path.

The models themselves (Z-Image, Wan 2.2, their VAEs/text-encoders/LoRAs) are
**not part of this application**. pet_factory holds only the *recipes* — the
workflow graphs naming which models to load and how to run them (§5). ComfyUI is
the execution engine. The one model pet_factory runs in-process is **birefnet**
(background removal via `rembg`/onnxruntime), because ComfyUI's job ends at
"frames with a white background."

### 2.2 Module layout

The application is deliberately a **single module + thin entry points**:

```
pet_factory/
  __init__.py       re-exports the 2-function public API; holds __version__
  factory.py        everything: config, workflow builders, ComfyUI client,
                    frame decoding, cutout post-processing, bundle packing,
                    and the make_pet_zip() orchestrator  (~365 lines)
examples/
  cli.py            argparse wrapper: one animal -> one .zip on disk
  queue_server.py   reference no-GPU job queue (Flask + sqlite)  — see §9
  worker.py         reference GPU-side poll-claim-run-upload loop — see §9
```

Everything in `factory.py` except the two public functions is underscore-private.
There is no class hierarchy, no plugin registry, no config object — the pipeline
is a fixed sequence of function calls with module-level constants. This is a
choice, not an accident: the application has exactly one product (a DatsMe
bundle with a walk and an idle), and a linear pipeline in one file is the
simplest structure that produces it. §11 spells out what to generalize *when* a
second product variant actually appears (per the "three instances" rule — don't
build the registry before the variants exist).

### 2.3 Design principles the code follows

- **Orchestrate, don't compute.** All heavy generation runs in ComfyUI; the
  library builds graphs, waits, and reads files. The only in-process ML is the
  cutout, which ComfyUI cannot do for us on these outputs.
- **Reliability over cleverness.** Every frame goes through birefnet; a
  faster flood-fill shortcut for "easy" frames was built and *removed* because
  its failure modes were hard to detect automatically. Where the code can
  degrade gracefully instead of failing, it does (GPU→CPU cutout fallback,
  opaque-alpha fallback per frame, `/free` best-effort) — §7.
- **One character, one seed.** Both animations are generated *from the same base
  still* and with the *same seed*, so walk and idle depict the identical pet.
- **The output contract is DatsMe's, not ours.** The bundle format (§6) exists
  to pass DatsMe's `validate_uploaded_bundle()` unchanged. Changes to the
  manifest schema are breaking changes to an external consumer.

## 3. Public API

```python
make_pet_zip(animal: str, on_progress=None, breed_id: str|None = None)
    -> tuple[str, bytes]          # (breed_id, zip_bytes)

pack_datsme_bundle(walk_frames, idle_frames, breed_id, display_name,
                   frame_size=256, columns=8, fps=12,
                   movement_class="mammalian_quadruped") -> bytes
```

- `make_pet_zip` is the whole pipeline (§4). Synchronous, blocking, ~3 min on an
  RTX 3090. Input is sanitized: stripped, truncated to 60 chars, empty → `"pet"`.
  The returned `breed_id` is a filesystem/URL-safe slug derived from the animal
  name (lowercase, spaces→`_`, only `[a-z0-9_-]`, max 40 chars) unless overridden.
- `pack_datsme_bundle` is stage 5 alone, exposed publicly so a caller with frames
  from *any* source (a different generator, hand-drawn art) can produce a valid
  bundle. It accepts lists of PIL images (RGB or RGBA) and performs the cutout +
  packing itself.
- `on_progress(message: str, fraction: float)` is an optional callback fired at
  each stage boundary with a human-readable message and overall fraction
  (0.10 → 0.35 → 0.60 → 0.85 → 1.0). It exists so *any* front-end (CLI printout,
  queue progress row, web UI) can show progress without the library knowing
  which one is attached. Exceptions in the callback are not caught — callers
  own their callback's safety (the reference worker's callback swallows its own
  network errors for exactly this reason).

Errors are raised, not returned: `RuntimeError` (ComfyUI rejected a workflow),
`TimeoutError` (generation exceeded the per-job timeout), `requests` exceptions
(ComfyUI unreachable), or a decode error after retries (§7). There is no partial
result — the caller either gets a complete bundle or an exception.

## 4. The pipeline — stages and data contracts

`make_pet_zip` is a linear five-stage pipeline. Each stage's *output contract* is
what the next stage consumes; those contracts are listed here because they are
the real interfaces of this application.

```
 animal:str
   │  sanitize; pick one random seed (reused by all three generations)
   ▼
 [1] BASE STILL      _static_image_wf → _run → path to a 1024×1024 PNG   (~10s)
   ▼                 contract: one still of the animal, side profile, FACING
   │                 RIGHT, white background  (path into ComfyUI's output dir)
   ▼
 [2] WALK LOOP       _loop_wf(walk prompt, base) → _run → animated WebP  (~70s)
   ▼                 contract: 17 frames @704², first frame == last frame,
   │                 in-place walk cycle, white background
   ▼
 [3] IDLE LOOP       _loop_wf(idle prompt, base) → _run → animated WebP  (~70s)
   ▼                 contract: same, but breathing/sway instead of walking
   │
   │  POST /free to ComfyUI — unload Wan so birefnet fits in VRAM (best-effort)
   ▼
 [4] DECODE          _frames_rgba ×2 → two list[PIL RGBA]; drop each list's
   ▼                 final frame (it duplicates frame 0)  → 16+16 frames
   ▼
 [5] CUTOUT + PACK   pack_datsme_bundle → cutout, hole-fill, fit 256², grid,
                     manifest, zip                                       (~13s GPU)
   ▼
 (breed_id, zip_bytes)
```

### 4.1 Stage 1 — base still (the character sheet)

One text-to-image generation produces the *single* image both animations start
from. The prompt template (`_base_prompt`) hard-codes the traits the rest of the
system depends on:

- **"side profile view, facing right"** — DatsMe stores pets facing right and
  mirrors them for leftward movement (`native_facing`/`mirroring_policy` in the
  manifest, §6). Art facing left would moonwalk in the app.
- **"standing"** — a neutral pose that both a walk and an idle can plausibly
  start from (the video model animates *from this exact frame*, so the pose must
  work as frame 0 of both loops).
- **"white background"** — gives the cutout model a trivially separable
  background; the actual transparency is produced later by birefnet, not by
  keying out white (§4.4 explains why).
- Style words ("soft pastel", "storybook", "simple flat shading") plus a strong
  negative prompt (`NEG`) that bans photorealism, text, humans, and multiple
  subjects.

### 4.2 Stages 2–3 — the two animation loops

Both loops run the **same** image-to-video workflow (`_loop_wf`) differing only
in prompt. The seamless loop is achieved structurally, not by luck: the
`WanFirstLastFrameToVideo` node receives the base still as **both** `start_image`
and `end_image`, so the model is constrained to return to its starting frame —
first frame == last frame == the base still. Stage 4 then drops the duplicated
final frame, leaving a clean 16-frame cycle.

The motion prompts are a load-bearing design surface (§5.3): shared suffixes
(`WALK_SUFFIX` / `IDLE_SUFFIX`) pin everything that must *not* move (mouth, eyes,
camera, horizontal position — the game engine moves the pet; the sprite must
animate in place) while describing the wanted cycle (stride + body bob, or
breathing + sway).

The two loops run **sequentially, not concurrently** — ComfyUI executes one
job at a time on one GPU, and both jobs need the same ~24 GB of Wan weights, so
there is nothing to gain from submitting them together.

### 4.3 Stage 4 — decode to frames

`_frames_rgba` turns whatever ComfyUI saved into `list[PIL RGBA]`:

- Animated WebP/GIF → decoded in-process via `PIL.ImageSequence`.
- Video containers (`.mp4/.webm/.mov/.mkv/.avi`) → extracted to PNGs by
  **ffmpeg** in a temp dir, then loaded. This path exists so the workflow's save
  node can be swapped for a video save without touching the decode code.

Two guards make this stage robust against its real-world failure mode — reading
a file ComfyUI (or a re-encoder) is still writing:

- `_wait_stable` polls the file size until it is non-zero and unchanged between
  polls (0.4 s interval, up to 30 tries) before any read.
- The decode itself retries up to 6 times (0.6 s apart) before re-raising the
  last error.

### 4.4 Stage 5a — cutout and alpha post-processing (inside `pack_datsme_bundle`)

Every frame, from both animations, goes through the same `prep()` sequence:

1. **birefnet matte.** `rembg` with the `birefnet-general-lite` model produces
   an alpha matte; the matte is applied to the *original* RGB frame (so colors
   are untouched — only transparency is added). birefnet was chosen over
   simpler approaches (near-white keying, u2net/isnet) because those hollowed
   out or made translucent any white/light animal (polar bear, swan) standing
   on the white background. The session is created lazily once per process
   (`_rembg`), preferring CUDA (~0.4 s/frame) and falling back to CPU
   (~4.6 s/frame) automatically if the CUDA libraries aren't present — slower,
   never fatal.
2. **Per-frame fallback.** If the cutout throws for a frame, that frame gets a
   fully-opaque alpha instead — one frame with a white box beats a failed
   3-minute job. (Graceful degradation, consistent with §2.3.)
3. **Fit to cell.** `_fit_square` scales the frame (LANCZOS) to fit a
   transparent 256×256 cell, centered, aspect ratio preserved.
4. **Hole filling.** `_fill_holes_alpha` closes any interior transparency the
   matting model punched *inside* the animal (a classic matting artifact on
   flat-shaded art): it flood-fills the transparent region (alpha < 160)
   inward from the image border (BFS, 4-connectivity); transparent pixels
   *not* reachable from the border are interior holes and are forced fully
   opaque. Real background — always connected to the border — stays
   transparent. Note the order: hole-filling runs on the final 256² cell, after
   scaling, so resampled edge alpha is also cleaned up.

### 4.5 Stage 5b — sprite sheet + manifest + zip

Frames are laid onto one transparent PNG grid, `columns=8` wide, cell 256×256:

- Walk frames take indices `0 .. len(walk)-1`.
- **Idle starts on a fresh grid row** — its first index is `len(walk)` rounded
  up to the next multiple of `columns`. With the standard 16+16 frames this
  yields walk on rows 0–1 (indices 0–15), idle on rows 2–3 (indices 16–31),
  a 2048×1024 sheet. The row alignment keeps the sheet human-inspectable
  (each animation is a visually contiguous band) at the cost of at most one
  row of empty cells.
- Frame index → cell position is `col = i % columns`, `row = i // columns` —
  the same rule DatsMe's runtime uses to read it back.

The manifest (`pet_manifest.v1`) records the grid geometry, each animation's
frame index list / fps / loop flag / `runtime_role` (`"active"` = plays while
moving, `"rest"` = idle), plus the facing metadata (`view_kind: "side"`,
`native_facing: "right"`, `mirroring_policy: "flip"`) and a `movement_class`.
`package.json` carries identity: `breed_id`, `display_name` (the title-cased
animal name), `movement_class`. All three files are zipped (deflate) in memory;
nothing touches disk.

**Playback speed is decided here, not at generation time.** The loops are
*generated* at 16 fps (17 frames ≈ a 1-second cycle — the `fps` in the WebP save
node only sets preview timing) but *played* at the manifest's `fps: 12`, i.e.
~25 % slower than generated. This is an intentional single knob: change the
manifest fps to retime pets without regenerating anything.

## 5. The ComfyUI integration layer

### 5.1 Workflow graphs as code

The two workflow builders return plain dicts in ComfyUI's API format — node id →
`{class_type, inputs}`, with cross-references as `["node_id", output_index]`.
They are constructed in code (not loaded from exported JSON files) so that the
variable parts — prompt, seed, start-image path, dimensions, length — are
ordinary function parameters, and the model filename constants at the top of
`factory.py` are the single place the required checkpoint names live (they're
also what the README's model table is generated from, and what an operator must
match on the GPU box).

**`_static_image_wf`** (stage 1): Z-Image-Turbo text-to-image. UNet + VAE +
text-encoder (`lumina2` CLIP type) → AuraFlow model-sampling shift 3.0 →
positive/negative CLIP encode → empty 1024×1024 SD3 latent → `KSampler` with
turbo-appropriate settings (**8 steps, CFG 1.0**, euler/simple) → VAE-decode →
`SaveImage` (prefix `petfactory_still`).

**`_loop_wf`** (stages 2–3): Wan 2.2-I2V-14B, which is a **two-expert MoE** —
separate high-noise and low-noise UNets that split the denoising trajectory.
The graph therefore loads *two* UNets, each with its matching **LightX2V 4-step
distillation LoRA**, each wrapped in SD3 model-sampling (shift 8.0). Sampling is
two chained `KSamplerAdvanced` nodes over one 4-step schedule: the high-noise
expert runs steps 0→2 and hands over its *still-noisy* latent
(`return_with_leftover_noise`), the low-noise expert finishes steps 2→4. The
conditioning comes from `WanFirstLastFrameToVideo` fed the base still as both
endpoints (the loop trick, §4.2); the input image is loaded by
`VHS_LoadImagePath` (the one custom-node dependency) from an absolute path —
possible only because of the shared filesystem. Output: 17 frames @ 704×704,
saved as animated WebP (quality 90, prefix `petfactory_loop`).

The negative prompt differs deliberately between the two graphs: the still uses
the strong style blacklist `NEG`; the video graphs use an **empty** negative,
because at CFG 1.0 the distilled Wan ignores it anyway and the motion
constraints belong in the positive suffixes.

### 5.2 Submit-and-poll client (`_run`)

`_run` is the entire ComfyUI client: `POST /prompt` with the graph and a
per-process `client_id` (a module-level UUID); non-200 → `RuntimeError` with the
response body. Then poll `GET /history/<prompt_id>` every 1.5 s until any output
node reports a saved artifact — the first entry of `gifs` + `images` (ComfyUI
files animated outputs under `gifs`) — and return **just its filename**, which
the caller joins onto `COMFY_OUTPUT_DIR`. A job exceeding the timeout (default
360 s) raises `TimeoutError`. No websocket, no server-sent events: polling is
simpler, and at 1.5 s granularity costs nothing against 70-second jobs.

### 5.3 Prompts are interface, not decoration

Every behavioral guarantee the pipeline makes downstream — right-facing art,
in-place motion, still camera, loopability, white background — is enforced in
exactly one of three prompt constants (`_base_prompt`, `WALK_SUFFIX`,
`IDLE_SUFFIX`) or structurally (first=last frame). When output quality
regresses, these constants are the tuning surface; when a downstream invariant
changes (e.g. DatsMe ever accepts left-facing art), the prompt is where the
change lands. Treat them with the same review care as code.

### 5.4 VRAM handoff

A 24 GB card cannot hold the Wan 14B weights *and* run birefnet. Between stage 3
and stage 4, the pipeline calls `POST /free` on ComfyUI
(`{unload_models, free_memory}`) and sleeps 1.5 s so the cutout has the GPU to
itself. The call is **best-effort** (wrapped in try/except): if the endpoint is
missing or ComfyUI is old, the cutout simply falls back to CPU via the provider
fallback (§4.4) rather than crashing. The *next* pet's stage 1/2 reloads the
models — that reload cost is accepted as the price of fitting on one consumer
GPU.

## 6. Output contract — the DatsMe breed bundle

The `.zip` contains exactly three entries (no directories):

| Entry | Content |
|---|---|
| `<breed_id>_sprite.png` | one transparent RGBA sprite sheet, all frames in a grid |
| `manifest.json` | playback contract: grid geometry, animations, facing metadata |
| `package.json` | identity: `breed_id`, `display_name`, `movement_class` |

With default parameters, the manifest is:

```json
{
  "schema_version": "pet_manifest.v1",
  "columns": 8, "rows": 4, "frame_width": 256, "frame_height": 256,
  "animations": {
    "walk": {"frames": [0, "…", 15], "fps": 12, "loop": true, "runtime_role": "active"},
    "idle": {"frames": [16, "…", 31], "fps": 12, "loop": true, "runtime_role": "rest"}
  },
  "view_kind": "side", "native_facing": "right",
  "mirroring_policy": "flip", "movement_class": "mammalian_quadruped"
}
```

This format is owned by **DatsMe** (`validate_uploaded_bundle()` /
`POST /api/pets/me/upload`); pet_factory conforms to it. Any change to entry
names, the manifest schema, or the index→cell rule must be validated against
DatsMe, not just against this repo. `runtime_role` is the semantic hook DatsMe
keys on ("active" plays while the pet moves, "rest" while it stands) — animation
*names* are labels, roles are the contract.

**Known limitation:** `make_pet_zip` always emits the default
`movement_class="mammalian_quadruped"`, even for birds or fish — the parameter
exists on `pack_datsme_bundle` but is not plumbed through (nor inferred from the
animal name). See §11.

## 7. Error handling & reliability model

The pipeline distinguishes three classes of failure and treats them differently:

**Fail fast (raise, abort the job):**
- ComfyUI unreachable → `requests` exception from the first `POST /prompt`.
- Workflow rejected (bad node, missing model file) → `RuntimeError` carrying the
  first 200 chars of ComfyUI's response.
- Generation hung/too slow → `TimeoutError` after 360 s of polling.
- Frames undecodable after 6 retries → the underlying decode error.

These abort because the job cannot produce a correct bundle; retrying whole jobs
is deliberately the *caller's* policy (the queue reference marks the job
`error`; a human resubmits), not the library's.

**Degrade gracefully (log/continue, never abort):**
- CUDA unavailable for the cutout → CPU provider, ~12× slower, same output.
- birefnet fails on an individual frame → that frame ships fully opaque.
- `POST /free` unsupported → skipped; cutout may run on CPU that round.

**Guard against races (wait, then proceed):**
- `_wait_stable` + decode retries cover the file-still-being-written window
  between ComfyUI reporting an output and the bytes being fully on disk.

**Concurrency contract:** one `make_pet_zip` at a time per ComfyUI instance.
The library is not internally thread-safe around this (module-level rembg
session; the `/free` call from one job would unload models mid-generation of a
concurrent job), and ComfyUI serializes GPU work anyway. The queue/worker
pattern (§9) enforces this naturally — one worker process, one job claimed at a
time. Determinism: each call draws one random seed; there is no way to pass a
seed in, so identical inputs produce different pets by design (each generation
is "a new individual").

## 8. Configuration surface

### 8.1 Environment variables (runtime, per deployment)

| var | default | meaning |
|---|---|---|
| `PET_FACTORY_COMFY_URL` | `http://127.0.0.1:8188` | ComfyUI base URL |
| `PET_FACTORY_COMFY_OUTPUT` | `~/ComfyUI/output` | ComfyUI's output dir (must be locally readable) |

### 8.2 Module constants (edit `factory.py`; change = new pipeline version)

- Model filenames (`ZIMAGE_*`, `WAN_*`) — must match the files installed in
  ComfyUI's `models/` folders.
- Prompt constants (`NEG`, `WALK_SUFFIX`, `IDLE_SUFFIX`, `_base_prompt`) — §5.3.
- Generation geometry: still 1024², loops 17×704², WebP fps 16.
- Bundle defaults (parameters of `pack_datsme_bundle`): `frame_size=256`,
  `columns=8`, playback `fps=12`, `movement_class="mammalian_quadruped"`.

### 8.3 Fixed constraints (not configurable)

- Same machine as ComfyUI (shared filesystem — both `VHS_LoadImagePath` input
  and output reading depend on it).
- NVIDIA GPU with ~24 GB VRAM for the models listed; `ffmpeg` on PATH (only
  exercised for video-container outputs); Python 3.10+.

## 9. The reference programs (`examples/`)

These are *reference implementations*, explicitly meant to be adapted, not
imported — `queue_server.py` says so in its docstring ("fold these into DatsMe's
FastAPI app"). They demonstrate the two integration modes named in the README.

**`cli.py`** — the direct mode: parse args, call `make_pet_zip` with a printing
progress callback, write bytes to disk. Also the minimal smoke test of a GPU box.

**`queue_server.py` + `worker.py`** — the split mode for GPU-less backends. The
design is *worker-pull* (the GPU box dials out; the server never connects to the
worker — no inbound port, works behind NAT):

- **Job state machine:** `queued → processing → done | error`, persisted in a
  single sqlite table (`jobs`), one row per job, `id` = 12-hex-char uuid slice.
- **Public API:** `POST /api/submit {animal}` (validates non-empty, truncates to
  60 chars, rejects with 429 when queued+processing ≥ `MAX_QUEUED`, default 15)
  → `{job_id}`; `GET /api/status/<id>` → status/pct/msg (+ download URL and
  breed_id when done); `GET /api/result/<id>` → the `.zip` from a results dir.
- **Worker API** (all guarded by a shared-secret header `X-Worker-Token`):
  `claim` (atomically takes the oldest queued job under a process-wide lock and
  flips it to `processing`), `progress` (writes pct/msg — fed directly by
  `make_pet_zip`'s `on_progress`), `complete` (multipart upload of the zip;
  flips to `done`), `fail` (records the error string; flips to `error`).
- **Liveness by side-effect:** every authenticated worker call stamps
  `worker_seen`; `GET /api/health` reports `worker_online` = stamped within the
  last 90 s. Because the worker polls `claim` every ~3 s even when idle, polling
  *is* the heartbeat — no separate ping protocol.
- **The worker loop:** poll `claim` → if a job, run `make_pet_zip` with a
  progress callback that POSTs progress (and swallows its own network errors so
  a flaky link can't kill a 3-minute job) → upload via `complete`, or report
  via `fail` on any exception, then keep looping. Claim errors back off 5 s.

Known reference-grade gaps (documented, intentionally unfixed here): a job
claimed by a worker that then dies stays `processing` forever (no lease/timeout
— the deployment spec's §7.1 hardens exactly this for two workers), results are
kept indefinitely, and there is no per-user rate limiting. Production hardening
belongs to the deployment layer (`DESIGN_SPEC_HETZNER_LOCAL_GPU.md`), not the
library.

## 10. Performance profile (RTX 3090, measured)

| stage | time |
|---|---|
| base still (Z-Image turbo, 8 steps) | ~10 s |
| walk loop (Wan 2.2, 4 steps, 17f @704²) | ~70 s |
| idle loop (same) | ~70 s |
| cutout ×32 frames (birefnet, CUDA) | ~13 s (~0.4 s/frame; CPU: ~4.6 s/frame → ~+2 min) |
| packing + zip | <1 s |
| **total** | **~3 min** (≈5 min with CPU cutout) |

The dominant cost is the two video generations; they are inherently sequential
on one GPU (§4.2). The 4-step LightX2V distillation LoRAs are what keep each
loop at ~70 s instead of several minutes.

## 11. Extension points — and what each change touches

Ordered from designed-for to needs-a-refactor:

- **Tune style/motion quality** → edit the prompt constants (§5.3). Touches
  nothing else.
- **Swap or upgrade a model** (e.g. a new base T2I) → edit the filename
  constants and, if the architecture differs, the corresponding workflow
  builder. The rest of the pipeline sees only "a filename in the output dir."
- **Retime animations** → manifest `fps` (a `pack_datsme_bundle` parameter).
- **Correct movement classes** (bird/fish/reptile) → plumb `movement_class`
  through `make_pet_zip` (or infer it), passing it to `pack_datsme_bundle`,
  which already accepts it. This is the smallest real gap in the current API
  (§6).
- **A third animation** (e.g. "sleep") → today requires: a new suffix constant,
  a third `_loop_wf` call, and **generalizing `pack_datsme_bundle`'s signature**
  from `(walk_frames, idle_frames)` to an ordered mapping of
  `name → (frames, runtime_role)`. That signature change is the known refactor
  cost of the current two-animation hard-coding — deliberately deferred until a
  third animation actually exists, and the packing loop already handles
  arbitrary frame counts and row-aligned segments, so the change is contained
  in one function plus its two callers.
- **A non-DatsMe output format** → a sibling of `pack_datsme_bundle` (a second
  packer), *not* flags inside it — the bundle format is an external contract
  (§6) and shouldn't grow variant branches.

Changes that should *not* be made unilaterally: anything in §6 (DatsMe owns that
contract), and re-introducing per-frame cutout shortcuts (tried, removed —
reliability regression, §2.3).

## 12. Non-goals

- **No job persistence, retries, auth, or multi-tenancy in the library** — the
  library is a pure function; those concerns belong to the caller (see §9 and
  the deployment spec).
- **No user-controllable style, pose, or seed** — one house style, one new
  individual per call. Style consistency across all users' pets is a feature.
- **No remote-ComfyUI mode** — the shared-filesystem constraint (§8.3) is
  accepted; distributing across machines is solved one level up by the
  queue/worker split, not by teaching the library HTTP file transfer.
- **No model management** — installing/updating checkpoint files in ComfyUI is
  an operator task (README "Requirements"), not application logic.
