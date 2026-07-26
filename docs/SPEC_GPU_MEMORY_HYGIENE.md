# SPEC — GPU memory hygiene: bound the allocators, make the failures loud

**Status:** **Rev.5** (2026-07-26) — **COMPLETE. All five fixes are implemented and measured.**
Five small, independent fixes to the build's GPU memory handling and to the *visibility* of its
failures. Grounded against the working tree (`pet_factory/factory.py`, `pet_env.sh`,
`webui/app.py`).

**Where this stands.** F1 (bounded arena), F2 (loud cutout failure), F3 (armed GPU fail-fast),
F4 (verified eviction) and F5 (visible logging) are all in the tree, with 20 guard tests in
`pet_factory/tests/test_cutout_hygiene.py` and 3 in `webui/tests/test_logging_visibility.py`; the
gate is **478 green**. Every headline claim is a measurement, not an estimate:

| | measured |
|---|---|
| cutout VRAM | **14618 → 6426 MiB** (8 GiB reclaimed), via the shipped `factory._rembg()` path |
| ComfyUI eviction | **~18 GB reclaimed in 0.5 s** — a number nobody had before F4 |
| a real 8-pose build | **128/128 frames matted**, 0 opaque fallbacks, 0 ERROR lines |
| cutout speed | **unchanged** — 0.27–0.28 s/frame capped and uncapped alike |

**[Rev.5] The gate is 484 green, and §10 now carries three MEASURED dead ends** so nobody spends
a day rediscovering them. Where a build's time actually goes was measured for the first time
(loops are ~69% of it, and ~82% of a loop is model *movement*, not compute), and the three
optimizations that look obvious from that number were tested: ComfyUI's **`--highvram` OOMs** —
the staging it removes is the only reason a ~34 GB model stack fits on a 24 GB card; **resolution
scales the 7 s of sampling, not the 33 s of movement**; and **`_fill_holes_alpha` is inside the
noise**. §10 also records that the 2-GPU fan-out's long-cited blocker does not exist — a whole
build already runs on GPU 1 with **no code change**, env only.

**[Rev.4] F1 shipped, reversing Rev.3's deferral.** Rev.3 deferred it on three objections (§2.7,
kept verbatim). Measuring four more caps retired two of them: peak-vs-cap is a **cliff, not a
slope**, so the full saving is available anywhere in a 4 GiB-wide band and the cap does not have
to run near the failure floor. §2.8 records how each objection resolved. The same measurement
exposed a *new* and nastier risk — above ~10 GiB the cap silently buys nothing, with no error and
no symptom — which is now the assertion the guard test exists for.

**What is left is measurement, not code** (§11): B2's timing bands and B3's peak still need one
build run through `start_all.sh` rather than a hand-started backend, and the pool nodes need
their own logging config before any of this is visible there.

**[Rev.3] F5 is new, and F4 did not work without it.** Post-implementation review found the app
configured logging *nowhere*, so the root logger had no handler and Python's `logging.lastResort`
applied: WARNING and above reached stderr, **INFO was silently discarded**. F4 reports success at
INFO and failure at WARNING — so a working eviction produced no record while a broken one did, and
"it worked" was indistinguishable from "it never ran". The same review found two implementation
defects, both fixed and both now red-green verified: a poll deadline that could be fully consumed
before the loop began (§5.2) and a fallback budget that was per-pose rather than per-build (§3.2).

**What changed in Rev.2.** Rev.1's F1 was reviewed by running it. Every one of its *mechanism*
claims held; two of its *value* claims did not, and the config it specified fails 100% of frames.
§2.6 is the new measurement table and it is now the spec's evidence base, replacing Rev.1's
"start generous and tighten" loop. Rev.1's §0.2 premise ("the footprint is an allocator artifact")
is corrected to half-true in §0.2. Rev.1's `_FREE_TARGET_VRAM_BYTES` derivation was circular and is
replaced in §5.2. Smaller corrections are marked **[Rev.2]** inline. Rev.1 also cited code by line
number and every citation had drifted ~5 lines; Rev.2 cites symbols.

**None of these four is a performance fix.** They exist so that performance work — the 2-GPU
build fan-out, the cutout pipeline, the `_fill_holes_alpha` vectorization — can be *measured*
rather than guessed at. Today a build that silently ran the cutout on CPU at 1/12 speed, or that
silently shipped an opaque sprite, reports the same `done` at progress 1.0 as a perfect build.
Every timing number taken against that baseline is unfalsifiable. F2 and F3 fix that; F1 and F4
fix the two unbounded/unverified allocator behaviors they reveal.

**Repos touched:** `datsme-pet-factory_wu` only. No bundle-contract change, no host change, no
frontend change. The GPU-less prod web tier never reaches this code (`PET_GEN_BACKEND=pool`), so
prod behavior is unchanged by construction — see §10.

**Dependency:** none. F2 and F3 must land before F1 (§8 explains why).

---

## 0. The core decisions (read this first)

1. **A build that could not matte is a FAILED build, not a degraded one.** The product is a
   *transparent* sprite; an opaque one is unusable in DatsMe. Today the `prep()` closure inside
   `pack_datsme_bundle` converts any cutout exception into a fully-opaque alpha and ships it as
   success. That is the single worst behavior in the *build* pipeline, because it makes every
   other measurement untrustworthy. F2 makes it fatal. Tolerated fallback frames: **zero** — one
   opaque frame in a walk cycle is a visible white flash, so there is no threshold worth tuning.

   **[Rev.2] There is a second, deliberate swallow of the same exception**, and it stays.
   `_prep_reference_image(isolate=True)` catches `_remove_bg` raising and degrades to the raw
   photo; `test_subject_isolation.py::test_cutout_raise_degrades_to_the_raw_photo` pins that on
   purpose (`SPEC_UPLOAD_LIKENESS` §2.2). It is correct there and wrong in `prep()` for one
   reason: a reference photo is an *input* to an img2img redraw, so a failed isolation costs
   likeness; a sprite frame is the *shipped artifact*, so a failed matte costs the product. F2
   touches only `prep()`. Named here because the repo's sweep rule (`CLAUDE.md`) says a repeated
   pattern gets swept, and this is the sweep: two sites, one changes, and the asymmetry is the
   reason.

2. **[Rev.2 — CORRECTED] Roughly half the footprint is an allocator artifact; the other half is
   a real requirement.** Rev.1 argued from `birefnet-general-lite.onnx` being **214 MB** on disk
   that the whole 6–15 GB was arena slack. That argument is a non-sequitur — weight size does not
   bound activation memory — and measurement (§2.6) shows it is wrong. The truth:

   - Uncapped, the arena reaches **14618 MiB** — confirming the code's own "~6–15 GB depending on
     how much was free when the arena grew" comment, and showing Rev.1's cited 6.4 GB was just
     the *first* frame's high-water (frame 0 = 6426 MiB, frame 1 = 14618 MiB, then flat).
   - Capped, the same work completes in **6426 MiB**, and the floor is between 4 and 6 GiB. Below
     it ORT raises on a single **822 MB activation tensor** in
     `/decoder/decoder_block1/dec_att/aspp_deforms.2/atrous_conv` — an activation, not arena slack
     and not a conv workspace.

   So the achievable win is **14618 MiB → 6426 MiB, ~2.3× (8 GiB reclaimed)**, not the order of
   magnitude the 214 MB figure implied. Bounding the arena is still a config change and still
   worth doing; it just buys less than Rev.1 claimed, and it cannot be tuned below ~6 GiB at any
   strategy (4096 MiB fails under both).

3. **The working set is input-size-independent.** rembg normalizes every input to birefnet's
   1024² graph, so a 256px and a 704px frame produce identical peaks (§2.6). One calibrated cap
   holds for every pet, every pose, every frame size the pipeline might later use. This is what
   makes a single named constant the right shape for F1 rather than a per-build computation.

4. **Eviction is already implemented; it is just not verified.** `make_pet_zip` already POSTs
   `/free {unload_models, free_memory}` before the cutout. The defect is that it is
   fire-and-forget inside `except Exception: pass`, followed by a fixed `time.sleep(1.5)` and no
   read-back. **[Rev.2] The premise is stronger than Rev.1 stated**: ComfyUI's `/free`
   (`../ComfyUI/server.py`, `post_free`) only calls `prompt_queue.set_flag(...)` and returns
   **200 unconditionally**; the actual `unload_all_models()` runs later, in the prompt worker
   (`../ComfyUI/main.py`, after `q.get_flags()`). So it is not merely that an error and a success
   look alike — **a successful 200 proves nothing at all.** F4 does not add eviction; it makes the
   existing eviction observable.

5. **F1 and F4 are coupled, in this direction only.** Once the arena is bounded (F1), the cutout
   no longer *depends* on the eviction landing in order to fit. So F4's failure mode is a logged
   WARNING and proceed, not an abort. Before F1, a missed eviction is what produces the OOM; after
   F1, it is merely suboptimal. Do not invert this: F4 must not gate the build.

   **[Rev.3] Free VRAM is not ours to reason about, which settles the posture.** Rev.2 said the
   cutout "fits without eviction by 212 MiB", from a single idle reading (6638 MiB free vs a
   6426 MiB peak). That number was a snapshot, not a property. Across 2026-07-26 the same
   `cuda:0` read **6638, 5535, and 1958 MiB** free, and at one point a process belonging to
   another project held **23.4 GB** of it while ComfyUI held 256 MiB. So:

   - There is no standing margin to defend. Sometimes the cutout fits unevicted; sometimes
     nothing would make it fit, because `/free` cannot reclaim what ComfyUI never held.
   - That is an argument *for* WARNING-and-proceed, not against it. Missing the target does not
     predict a failed cutout, so aborting on it would fail builds that would have succeeded —
     while F2 already raises a real, specific error if the cutout genuinely dies.
   - It also means B4 is a *sample*, never a constant. Record it with a timestamp and what else
     was on the card, or it is not interpretable.

6. **Every value is a named constant.** No inline literals — arena cap, device id, poll timeout,
   poll interval, fallback tolerance, and **[Rev.2]** the peak-VRAM acceptance tolerance, which
   Rev.1 left as an unnamed word in §2.5. §6 is the table; each name is defined once in
   `factory.py`'s constants band alongside `_ANCHOR_SEED`.

7. **Zero-GPU testability is preserved.** The repo's gate is `pytest pet_factory/tests
   webui/tests` with no GPU (155 pet_factory tests green as of 2026-07-26). Every guard test in §7
   stubs the session or `_remove_bg`, exactly as `test_gpu_fail_fast_and_progress.py` and
   `test_pack_bundle_layout.py` already do.

---

## 1. Baseline — capture this BEFORE touching any code

This is the zero point of the paper trail. Without it, "it worked" is not checkable. Run **one
full 8-pose build** through the local stack and record every row of §9's Table A.

```bash
source pet_env.sh && ./start_all.sh
# submit one 8-pose build, then collect:

# B1 — which provider is the cutout actually using? (printed once per session, by
#      _CutoutSession._new_session)
grep "rembg providers" logs/backend*.log

# B2 — per-stage wall time, from the progress band boundaries in the job log
#      base ≈ 0.10 | anchors 0.10→0.22 | loops 0.22→0.85 | cutout+pack 0.85→1.0

# B3 — peak VRAM attributable to the BACKEND PROCESS during the cutout band.
#      [Rev.2] NOT --query-gpu=memory.used: on this box ComfyUI holds ~17.8 GB of cuda:0,
#      so device-total used says nothing about the cutout. Query per-process and match the
#      backend's pid, or the number is unreadable. (The [u] bracket keeps pgrep from
#      matching its own shell — several other uvicorns run on this box.)
BACKEND_PID=$(pgrep -f "[u]vicorn app:app --host 127.0.0.1 --port 19954")
nvidia-smi --query-compute-apps=pid,used_memory --format=csv -l 1 | grep "^$BACKEND_PID"

# B4 — VRAM free on cuda:0 immediately before the cutout, i.e. did /free land?
curl -s localhost:19953/system_stats | python3 -c \
  "import json,sys;print([d['vram_free'] for d in json.load(sys.stdin)['devices'] if d['index']==0])"

# B5 — THE OUTPUT CHECK: does the produced sprite actually have transparency?
#      [Rev.3] MUST be PER FRAME, not per sheet. Rev.1/Rev.2 read the whole sheet's alpha
#      extrema, which is too coarse to detect the exact defect F2 exists for: the fallback is
#      PER FRAME, so a sheet with 127 matted frames and one white rectangle still reads
#      (0, 255) and passes. Walk the manifest's cells and count the fully-opaque ones.
python3 - out.zip <<'PY'
import io, json, sys, zipfile
from PIL import Image
z = zipfile.ZipFile(sys.argv[1]); m = json.loads(z.read("manifest.json"))
sheet = Image.open(io.BytesIO(z.read([n for n in z.namelist() if n.endswith("_sprite.png")][0])))
fs = m["frame_width"]; cols = m["columns"]
def cell(i):
    r, c = divmod(i, cols); return sheet.crop((c*fs, r*fs, (c+1)*fs, (r+1)*fs))
bad = {name: [i for i in a["frames"] if cell(i).getchannel("A").getextrema()[0] == 255]
       for name, a in m["animations"].items()}
total = sum(len(a["frames"]) for a in m["animations"].values())
n_bad = sum(len(v) for v in bad.values())
print(f"frames={total} opaque-fallback={n_bad}",
      "PASS" if n_bad == 0 else f"FAIL {[k for k,v in bad.items() if v]}")
PY
```

**B5 is the acceptance test for this whole spec.** It is the one check that distinguishes a real
success from today's false green, and it is the only row of Table A that must be re-run after
every one of the four fixes.

**[Rev.2] B1's answer is already known for this box, and it is the boring one.** Rev.1 said "we do
not know which today — that is the point." A direct probe (2026-07-26) built the real session in
this venv and got `['CUDAExecutionProvider', 'CPUExecutionProvider']` at **0.27 s/frame** — and got
it **even with `LD_LIBRARY_PATH` unset**, because `_new_session`'s `ort.preload_dlls()` already
covers what `pet_env.sh` §2 was added for. So on this box the ~12× is *not* sitting on the table
and F3 will change nothing observable. Still record B1 from a real build (the probe is not the
backend), but expect the null result and see §4.3.

---

## 2. F1 — Bound the birefnet CUDA arena

### 2.1 The defect
`_CutoutSession._new_session` creates the session with a bare provider list and no options:

```python
session = new_session("birefnet-general-lite",
                      providers=["CUDAExecutionProvider", "CPUExecutionProvider"])
```

ORT defaults apply. Read back live from `inner_session.get_provider_options()` (2026-07-26):

```
device_id=0  gpu_mem_limit=18446744073709551615  arena_extend_strategy=kNextPowerOfTwo
cudnn_conv_algo_search=EXHAUSTIVE  cudnn_conv_use_max_workspace=1
```

The arena grows opportunistically against free VRAM and holds its high-water mark for the life of
the session: **14618 MiB** measured.

### 2.2 The change
Pass provider options. Verified against the installed versions (**rembg 2.0.69 / onnxruntime
1.23.2**) *by construction, not by reading*: `BaseSession.__init__` pops `providers` when
`isinstance(providers, list)` and hands it straight to `ort.InferenceSession`. A list containing a
`(name, options_dict)` tuple **is** a list, so this needs no rembg patch and no vendoring — a
session built this way returns the requested options from `get_provider_options()`.

```python
providers=[(_CUTOUT_PROVIDER, {
               "device_id": _CUTOUT_DEVICE_ID,
               "gpu_mem_limit": _CUTOUT_GPU_MEM_LIMIT_BYTES,
               "arena_extend_strategy": _CUTOUT_ARENA_STRATEGY,
           }),
           "CPUExecutionProvider"]
```

### 2.3 Invariants to preserve
- **The GPU fail-fast in `_new_session` must keep working.** `inner_session.get_providers()`
  returns bare provider *name* strings whether or not options were passed — verified on a real
  options-carrying session, which returned exactly
  `['CUDAExecutionProvider', 'CPUExecutionProvider']`. So the `"CUDAExecutionProvider" in
  providers` check is unaffected. Pin this in a guard test (§7.1) — it is the non-obvious part.
- **[Rev.2 — CORRECTED] `kNextPowerOfTwo` is the right strategy; Rev.1 had this backwards.**
  Rev.1 claimed `kSameAsRequested` was "mandatory alongside a tight cap" because
  `kNextPowerOfTwo` would "raise inside the arena". Measurement says the opposite on both axes
  (§2.6): `kNextPowerOfTwo` tolerates a **tighter** cap (6 GiB works, where `kSameAsRequested`
  fails) and settles **lower** (6426 vs 7000 MiB). Keep the ORT default and let the cap do the
  work.
- **The cap is the only control that matters.** `kSameAsRequested` *without* a cap still reaches
  11408 MiB. Strategy alone does not bound anything.
- **CPU-only nodes keep the graceful fallback.** `CPUExecutionProvider` stays in the list,
  unparameterized. Note this is *load-time* fallback only — ORT does not fall back to CPU when an
  allocation fails at runtime, so an over-tight cap is a hard error, never a slow success.
- **[Rev.2] The cuDNN workspace knobs were considered and rejected on measurement.**
  `cudnn_conv_algo_search=HEURISTIC` + `cudnn_conv_use_max_workspace=0` does **not** buy headroom
  (§2.6, row 13): the blocking allocation is an 822 MB activation, not a conv workspace. Do not
  add them; they change nothing and cost algo quality.

### 2.4 Calibration — [Rev.2] already measured, do not re-derive
Rev.1 said "start at 4 GiB (generous), run a full build, tighten toward the measured peak."
**4 GiB is not generous — it is below the floor, and every frame raises.** That loop never gets a
first data point, and post-F2 it fails every build on the first pet. The sweep is done; §2.6 is
the result. Ship the calibrated values:

- `_CUTOUT_GPU_MEM_LIMIT_BYTES = _CUTOUT_WORKING_SET_BYTES` = 7 GiB. The measured floor is
  between 4 GiB (fails) and 6 GiB (passes at 6426 MiB); 7 GiB is the floor-passing value plus one
  GiB of headroom for driver/cuDNN variation, and it costs nothing, since peak at 7 GiB and at
  10 GiB are both 6426 MiB. **[Rev.3]** The number is already in the tree under the
  `_CUTOUT_WORKING_SET_BYTES` name (§6) — F1 passes it to ORT, it does not introduce it.
- `_CUTOUT_ARENA_STRATEGY = "kNextPowerOfTwo"` — the ORT default, and the better one here.

Because the working set is input-size-independent (§0.3), these do not need re-calibrating per
pet. They *would* need re-calibrating if the model changes — which is what §7.6's guard test is
for.

### 2.5 Acceptance
- **[Rev.2]** Peak VRAM attributable to the backend process during the cutout band (B3, measured
  per-process per §1) ≤ `_CUTOUT_GPU_MEM_LIMIT_BYTES + _CUTOUT_PEAK_TOLERANCE_BYTES`. The
  tolerance is a named constant (§6) because the CUDA context lives **outside** the arena and the
  cap therefore cannot bound the process total. Measured before any inference runs: **264 MiB**
  with only the context live (after `del session; gc.collect()`), **526–554 MiB** with the context
  plus the loaded session.
  Rev.1's unnamed "+ tolerance" both violated §0.6 and made the acceptance unfalsifiable.
- B5 still reports `(0, 255)` — the cap did not silently break matting.
- Total build wall time within noise of baseline. Per-frame inference was 0.27–0.36 s capped and
  uncapped alike in the probe, so no slowdown is expected. **A slowdown here is a finding, not a
  pass** — it would mean allocator churn is material and the cap needs raising.

#### [Rev.4] Independent end-to-end verification — ACCEPTANCE MET

F1 was verified by an independent reviewer against a **like-for-like real build**: same animal
(`black bat`), same 8 poses, same instrumented runner, run before and after F1. Not a probe — the
whole pipeline.

| | no F1 (11:35) | **with F1 (12:13)** |
|---|---|---|
| **peak VRAM, this process** | 14618 MiB | **6426 MiB — 8 GiB reclaimed** |
| B5 per-frame alpha | 128 frames, 0 opaque | **128 frames, 0 opaque** |
| B1 providers | CUDA | CUDA |
| B4 eviction | 5631 → 23875 MiB, 0.7 s | 5535 → 23457 MiB, 0.5 s |
| total wall time | 470.9 s | **456.0 s** |

**6426 MiB, to the MiB, matching both §2.6 row 17 and the projection in §9.** The probe's number
transfers to the real pipeline exactly. Also confirmed on the shipped session:
`get_provider_options()` reads back `gpu_mem_limit=8589934592`, `kNextPowerOfTwo`, `device_id=0`,
while `get_providers()` still returns **bare names** — so §2.3's fail-fast invariant holds on the
real object, not just on a stub. And `release()` still returns the arena: **6426 → 264 MiB**.

**One honest finding, per the "a slowdown is a finding" rule above.** The cutout band moved
**46.7 s → 53.9 s** (+15%, 0.365 → 0.421 s/frame at the band level). Three reasons not to act on
it yet, and one reason not to dismiss it: the loops band moved −25.2 s between the same two runs,
so band-level run-to-run variance is already ±25 s; the total build got *faster* (−14.9 s); and
§2.6's controlled probe measures the inference itself at 0.27–0.28 s/frame capped and uncapped
alike, which is the number the cap could plausibly affect. The band also contains eviction, webp
decode, `_fill_holes_alpha` and PNG packing — none of which the cap touches. **But it is one
sample.** Re-run the pair before treating +7 s as noise; it is 1.6% of total, so nothing is
blocked on the answer.

**A false alarm worth recording, because §2.8 predicted it.** The reviewer's first `release()`
check read 6426 → 6426 MiB and looked like a regression. Cause: the *test* held a local reference
to the session (`sess = factory._rembg()`), so `release()`'s `self._session = None` could not drop
the last reference. Re-run without holding one: 6426 → 264 MiB. §2.8 called this exact trap in
advance — which is the value of having written it down.

### 2.6 [Rev.2] The measurement
Probe: real `rembg.new_session("birefnet-general-lite")` in this repo's `.venv`, 3–4 consecutive
`remove()` calls on a 704×704 RGB frame (the Wan loop output size, `_loop_wf`'s `width/height`),
run under `CUDA_VISIBLE_DEVICES=1` — i.e. on the idle second 3090 — so ComfyUI's 17.8 GB on
physical `cuda:0` was undisturbed. (Under that mask the provider's `device_id: 0` *is* physical
GPU 1; in production `_CUTOUT_DEVICE_ID = 0` means physical `cuda:0`. Both cards are 3090s, so the
numbers transfer.) Peak is **per-process** (`nvidia-smi --query-compute-apps`), so it includes the
CUDA context and is directly comparable to B3.

| # | strategy | `gpu_mem_limit` | result | peak (own process) |
|---|---|---|---|---|
| 1 | kNextPowerOfTwo *(today's default)* | none | ok | **14618 MiB** |
| 2 | kSameAsRequested | none | ok | 11408 MiB |
| 3 | kSameAsRequested | 12288 MiB | ok | 11408 MiB |
| 4 | kSameAsRequested | 8192 MiB | ok | 7000 MiB |
| 5 | kSameAsRequested | 7168 MiB | ok | 7000 MiB |
| 6 | kSameAsRequested | 6144 MiB | **FAILS** | — |
| 7 | kSameAsRequested | **4096 MiB** ← *Rev.1's value* | **FAILS** | — |
| 8 | kNextPowerOfTwo | 10240 MiB | ok | 6430 MiB |
| 9 | kNextPowerOfTwo | 8192 MiB | ok | 6426 MiB |
| 10 | kNextPowerOfTwo | **7168 MiB** ← *Rev.2 ships this* | ok | **6426 MiB** |
| 11 | kNextPowerOfTwo | 6144 MiB | ok | 6426 MiB |
| 12 | kNextPowerOfTwo | 4096 MiB | FAILS | — |
| 13 | kSameAsRequested + HEURISTIC + `max_workspace=0` | 4096 MiB | FAILS | — |
| 14 | kNextPowerOfTwo | **12288 MiB** | ok | **12570 MiB** ← benefit gone |
| 15 | kNextPowerOfTwo | 14336 MiB | ok | 14616 MiB |
| 16 | kNextPowerOfTwo | 16384 MiB | ok | 14626 MiB |
| 17 | **shipped code path** — `factory._rembg()` @ 8192 MiB | 8192 MiB | ok | **6426 MiB** |

**[Rev.4] Rows 14–17 are why F1 shipped, and rows 14–16 nearly stopped it.** Rev.3's §2.7
deferred F1 partly on "a tighter cap means more benefit and more risk". Rows 8–16 falsify the
premise: peak-vs-cap is a **cliff, not a slope**.

```
   cap  4096            FAILS
   cap  6144 .. 10240   6424-6426 MiB   ← the entire benefit, FLAT across the band
   cap 12288            12570 MiB       ← benefit essentially gone
   cap 14336+ / none    ~14620 MiB      ← benefit entirely gone
```

Two consequences, and they point in opposite directions:

- **The risk was over-priced.** You do not have to run close to the floor to get the saving. The
  proven-good band is 4 GiB wide, so the shipped cap sits 2 GiB clear of the highest cap that
  still fails *and* 2 GiB clear of the lowest that stops working. Rev.3's headline objection was
  built on a slope that does not exist.
- **A new, worse risk appeared.** Above ~10 GiB the fix silently stops working: no error, no
  failed test, no symptom, same build, same speed. And "the cap looks tight, raise it" is exactly
  what anyone does after a memory scare. That is now the most likely way F1 regresses, and it is
  why `test_the_arena_cap_stays_inside_the_band_where_it_actually_does_something` asserts an
  **upper** bound — the assertion that earns its keep — with a failure message that explains the
  cliff rather than just printing two numbers.

Row 17 is the acceptance measurement: not a hand-built probe session but `factory._rembg()`
itself, the shipped path, with ORT reading back `gpu_mem_limit=8589934592`.

Supporting observations from the same probe:

- **Input size is irrelevant.** 256×256 and 704×704 both peak at 11408 MiB under row 2 — rembg
  normalizes to birefnet's 1024² graph. Hence §0.3.
- **The failure is an activation, not slack.** Row 7's raise:
  `bfc_arena.cc:359 … Available memory of 603602432 is smaller than requested bytes of 822083584`
  at node `/decoder/decoder_block1/dec_att/aspp_deforms.2/atrous_conv/Mul_8`. Row 6 raises on the
  neighbouring `Conv` for the same 825 MB. This is the evidence behind §0.2's correction.
- **The high-water is reached on the SECOND inference, not the first.** Row 1, 0-indexed: frame 0
  = 6426 MiB, frame 1 = 14618 MiB, frames 2+ flat. A one-frame probe would have measured 6.4 GB
  and concluded there was nothing to fix — which is, on the evidence, exactly what produced the
  code comment's "6.4 GB" figure. Any future re-measurement must run ≥ 3 frames.
- **The release path works.** After `del session; gc.collect()`, the process drops to 264 MiB —
  confirming the existing `_CutoutSession.release()` design (§3.2) empirically, and matching the
  code comment's "6.4 GB → 0.26 GB after gc".

### 2.7 [Rev.3 — SUPERSEDED by §2.8, kept verbatim] Why F1 was deferred

§2.6 settled the mechanism and the number. It did not settle whether to ship, and three things
have to be answered first. **The first is the serious one.**

1. **F1 currently buys nothing measurable, and that changes the risk calculus.** The cutout is
   the build's *last* GPU step: Wan is already evicted (§5), and `_CUTOUT.release()` hands the
   arena back the instant packing finishes. So during the cutout nothing else on this pipeline
   wants the card, and afterwards the memory is returned either way. Uncapped 14618 MiB and
   capped 6426 MiB produce the *same* build in the *same* wall time. The 8 GiB is real but
   currently spent on nothing — its payoff is prospective (the 2-GPU fan-out, concurrent builds),
   plus one live case: on a **shared** box the uncapped arena grabs 8 GiB it does not need and
   starves a neighbour, which is exactly what was observed on 2026-07-26 (§0.5). So the question
   for the reviewer is not "is 7 GiB the right cap" but **"what is the cap for, today?"** If the
   answer is "the fan-out", F1 belongs in that spec, next to the `device_id` threading it
   already depends on (§10).
2. **The floor is bracketed, not bisected, and the consequence of being wrong is asymmetric.**
   4096 MiB fails, 6144 MiB passes; the true floor is somewhere between. 7 GiB carries ~1 GiB of
   headroom over a number known only to ±1 GiB. Uncapped, a heavier future frame or model just
   uses more VRAM; capped, it becomes `CutoutFailed` — and per §3.3 the pool then burns three
   full builds discovering that. Bisect the floor before trading a graceful degradation for a
   hard edge.
3. **Every §2.6 row was measured on an idle card by a standalone process.** The real backend
   creates its session alongside a live ComfyUI, sometimes with very little free VRAM at session
   creation (1958 MiB was observed). The arena grows lazily so it *should* behave identically,
   but "should" is what this spec exists to stop accepting. Re-run §2.6 rows 1 and 10 from inside
   the backend, during a real build, before the cap goes in front of users.

Nothing here contradicts §2.6 — the calibration stands and `_CUTOUT_WORKING_SET_BYTES` already
carries it. F1 is a ~10-line change once these are closed.

### 2.8 [Rev.4] How each of §2.7's objections resolved — F1 SHIPPED

Kept above verbatim rather than rewritten, because two of the three were wrong for reasons worth
being able to re-read.

1. **"Buys nothing measurable today" — half stands, and stopped being the deciding question.**
   Still true that a single serialized build is unaffected: the cutout is the last GPU step, the
   arena is released immediately after, and per-frame inference is 0.27–0.28 s capped exactly as
   uncapped. What the objection under-weighted is `device_id`. It arrives in the *same* provider
   options tuple as `gpu_mem_limit`, and ORT's default is `device_id: 0` — measured. So without
   F1 two concurrent self-contained builds both put their cutout on cuda:0, each growing toward
   14.6 GB of a 24 GB card. F1 is therefore not an optimization the fan-out would *like*; it is
   the mechanism the fan-out cannot exist without. Plus the live case: on this shared box the
   uncapped arena holds ~8 GiB it will never use for the whole cutout band.
2. **"The floor is bracketed, so the margin is thin" — falsified.** It rested on tighter = better
   = riskier. Rows 8–16 show the benefit is flat across [6144, 10240], so the cap can sit in the
   middle of a 4 GiB band and lose nothing. The floor never needed bisecting; the objection was
   an artifact of assuming a slope. What it correctly identified — that a too-tight cap is a hard
   `CutoutFailed`, not a graceful degradation — remains true and is why the band's lower edge is
   asserted too.
3. **"Everything was measured standalone on an idle card" — closed for the code path, still open
   for the concurrent case.** Row 17 re-measures through `factory._rembg()` — the real managed
   session, real fail-fast, real `_remove_bg` — and gets 6426 MiB with ORT reading the cap back.
   What is *not* yet proven is the cap under a genuinely contended card. It is the same lazy
   arena and the failure would be loud, so this is a residual, not a blocker; §11 tracks it, and
   B3 on the next real build settles it.

**One thing F1 nearly broke, caught during verification.** Measuring through the shipped path
first showed `release()` freeing nothing — 6426 MiB still held. That was the *measurement*
holding a reference to the session, not a defect: re-run without binding it (as
`pack_datsme_bundle` never does) and it drops **6426 → 264 MiB**. Recorded because "the managed
session stopped releasing" is exactly the kind of regression a cap could plausibly cause, and the
first reading looked like it.

---

## 3. F2 — Make a failed cutout fail the build

### 3.1 The defect
The `prep()` closure inside `pack_datsme_bundle`:

```python
try:
    a = _remove_bg(orig).convert("RGBA").split()[3]
except Exception:
    a = Image.new("L", orig.size, 255)     # fully opaque
```

Four compounding problems: the `except` is blanket (a CUDA OOM, a provider failure and a corrupt
frame are handled identically); it is **per frame**, so it does not even abort the pose (frames 1–6
matte, frame 7 does not, and the sheet mixes them); nothing is logged; and the build still returns
valid zip bytes and reports `done` at 1.0. Since the still prompt asks for `"white background"`
(`prompt_templates.py`, `base_still_prompt` / `remix_still_prompt`), the visible result is a pet
with an opaque white rectangle behind it.

Note the team already fixed *half* of this: session creation and the GPU fail-fast were hoisted
out of the loop specifically "so it is never swallowed inside prep()'s per-frame try/except"
(the `_CUTOUT.get()` call at the top of `pack_datsme_bundle`). What remains swallowed is per-frame
**inference** failure — which is exactly where a runtime OOM lands, and exactly where an over-tight
F1 cap lands (§2.6 rows 6, 7, 12, 13).

### 3.2 The change — **[Rev.3] IMPLEMENTED**
Fail fast on the first fallback frame. A per-frame raise from a PIL RGB input means the session is
broken, not that one frame is odd — there is no realistic transient, and spending GPU time on 127
more frames after the session dies is waste.

**[Rev.3] One shape detail the spec did not anticipate:** `prep()` was a closure over `frames`
only, so it had no idea which pose it was matting and the exception could not name one. It now
takes `prep(pose_name, frames)` and enumerates, which is the whole reason `CutoutFailed` can carry
`pose_name` / `frame_index`. A one-argument version would have produced "the cutout failed"
and sent the reader back to the GPU log — the exact failure mode F2 exists to end.

- Raise a named exception (`CutoutFailed`) carrying the pose name, frame index, and the original
  exception's class + message.
- Log at ERROR before raising.
- `_CUTOUT_MAX_FALLBACK_FRAMES = 0` — the tolerance is a named constant so the decision is
  visible and revisitable, not because a nonzero value is expected.
- **[Rev.3 — DEFECT FOUND AND FIXED] The budget is BUILD-wide, and the first implementation made
  it per-pose.** `fallbacks` was initialised inside `prep()`, which runs once **per pose** — so a
  tolerance of N silently meant N *per pose*, i.e. up to 8N opaque frames in an 8-pose build,
  which is not what the constant says. Verified by setting the constant to 1 and shipping a bundle
  with **two** white-flash frames. Invisible at the shipped value of 0, which is exactly what made
  it dangerous: the constant advertises itself as revisitable, so the trap springs on whoever
  revisits it. `fallbacks` now lives in `pack_datsme_bundle`'s scope alongside `done_frames`, and
  `test_fallback_budget_is_build_wide_not_per_pose` (§7 item 14) fails if it moves back.
- `make_pet_zip` lets it propagate; `webui/app.py`'s `run_pet_job` already turns any exception into
  job `status="error"` with a message (its `except Exception as e` sets `job.status = "error"`,
  `job.error = str(e)`), so the user sees a failed build instead of a white pet.
- **[Rev.2] The GPU-release claim, confirmed rather than assumed.** `_CUTOUT.release()` sits in a
  `finally` wrapping `make_pet_zip`'s call to `pack_datsme_bundle`, so it **is** reached when
  `CutoutFailed` propagates. But that `finally` belongs to `make_pet_zip`, not to
  `pack_datsme_bundle` — a caller using the public `pack_datsme_bundle` directly still depends on
  `_CutoutSession`'s idle watchdog (`IDLE_TIMEOUT_S`) to reclaim the arena. That is pre-existing
  and acceptable; it is stated so nobody reads the `finally` as covering both entry points.

### 3.3 Blast radius — checked
`pack_datsme_bundle` is public API (`pet_factory/__init__.py`) and three tests call it directly.
**All of them stub `_remove_bg` to a lambda that succeeds** (`test_pack_bundle_layout.py`,
`test_gpu_fail_fast_and_progress.py`), so none exercises the fallback and none breaks.

**[Rev.2] `test_subject_isolation.py::test_cutout_raise_degrades_to_the_raw_photo` also stubs
`_remove_bg` to raise, and must keep passing.** It exercises `_prep_reference_image`, not
`pack_datsme_bundle` — a different swallow site that F2 deliberately does not touch (§0.1). Rev.1's
"all of them stub to a lambda that succeeds" was true of the `pack_datsme_bundle` callers and
missed this one. Run the full `pet_factory/tests` (155 green today), not just the three.

**[Rev.2] The pool inherits a retry cost, and it is bounded but not free.** The pool handler calls
`make_pet_zip`, so it inherits the new failure as a task error — correct behavior (a failed task is
reported; a white-background success is not). But shared_gpu_cpu *retries* failed jobs:
`storage.fail_attempt` re-queues until `attempts >= MAX_ATTEMPTS` (`config.py` default **3**) and
only then dead-letters, and `scheduler._recently_failed_here` steers each retry to a *different*
node. A **deterministic** `CutoutFailed` — precisely what a mis-set cap produces — therefore burns
up to **3 full ~3-min builds, on 3 different nodes**, before the job goes `dead`. Bounded, and
still ~9 GPU-minutes per submitted pet across the fleet while a bad cap is live. Two consequences
for the handler rollout (§10): validate the F1 cap on one node before rolling, and decide whether
a `CutoutFailed` should dead-letter immediately rather than consume all three attempts, since a
capped-arena failure is deterministic and no node will succeed. Neither blocks F2 in-repo.

### 3.4 Acceptance
- New guard test: stub `_remove_bg` to raise → `pack_datsme_bundle` raises `CutoutFailed`, does
  **not** return bytes (§7.2).
- A real build's log contains **zero** cutout ERROR lines, and B5 reports `(0, 255)`.
- **Expect new failures.** If some fraction of recent builds were silently degrading, they will
  now fail. That is the fix working, not a regression. Record how many, in Table B — it is the
  measurement of how bad the old behavior was.

---

## 4. F3 — Arm the GPU fail-fast on this box

### 4.1 The defect
The fail-fast in `_CutoutSession._new_session` only arms when `PET_FACTORY_REQUIRE_GPU` is set. It
is set **nowhere** — not in `pet_env.sh`, not in `pet_env.local.sh`, not in any `start_*.sh`
(verified 2026-07-26; the only non-doc hits are the flag's own read and three tests). So on this
GPU box the "graceful fallback" branch is live, and per the code's own comment onnxruntime "drops a
provider it can't load without raising" while CUDA is **~12× faster**. A CUDA provider that fails
to load yields correct output at 1/12 speed, indefinitely, with no signal.

### 4.2 The change — **[Rev.3] IMPLEMENTED**
Export `PET_FACTORY_REQUIRE_GPU=1` in `pet_env.sh`. This box is a declared GPU node; a silent CPU
cutout here is a misconfiguration, exactly as it is on a pool GPU node.

- Do **not** set it in any CPU/pool deploy path. The prod web tier has no ML stack and never
  reaches this code, but keep the env explicit rather than relying on that.
- Add a one-line comment in `pet_env.sh` citing this spec section, per repo convention.
- **[Rev.3] Placed beside the `LD_LIBRARY_PATH` export, not in a new numbered section.** The two
  are one thought — point onnxruntime at the CUDA-12 wheels, then refuse to run if that did not
  take — and co-locating them means the guard is read by anyone touching the thing it guards.
  Verified: `source pet_env.sh` sets the flag, and the real session still builds
  `['CUDAExecutionProvider', 'CPUExecutionProvider']`.

### 4.3 This is a detector, not an optimization — and here it will detect nothing
Setting the flag makes nothing faster. It converts a silent CPU fallback into a loud startup
error, so the CUDA libs get fixed and *then* the cutout band gets ~12×.

**[Rev.2] On this box, expect exactly that null result.** The §1 probe already answered B1: CUDA
loads, at 0.27 s/frame, and it loads even without `pet_env.sh`'s `LD_LIBRARY_PATH` because
`_new_session` calls `ort.preload_dlls()` first. Rev.1 framed the CPU-fallback branch as a live
possibility worth ~12×; on the current venv it is not. F3 remains worth shipping — it is the same
misconfiguration guard the pool nodes need, and an env that drifts (a venv rebuild, a CUDA-13
torch leaking into the path) is exactly what it catches — but nobody should book a speedup against
it. Ship it as insurance and record the null in Table B.

**[Rev.3 — F3 is a PREREQUISITE for F1, not merely insurance.** Rev.2 framed F3 as standalone
cover for env drift. Measured (2026-07-26, onnxruntime 1.23.2): an **invalid `device_id` does not
raise**. Requesting a device that does not exist prints an EP Error to *stderr* and silently
returns a CPU-only session:

```
EP Error ... Invalid device ID: 7, must be between 0 (inclusive) and 2 (exclusive).
Falling back to ['CPUExecutionProvider'] and retrying.
device_id=7: created, providers=['CPUExecutionProvider']
```

F1 introduces `_CUTOUT_DEVICE_ID` — so F1 *creates* a new way to land in a silent 1/12-speed
cutout, and F3's fail-fast is what catches it, since `CUDAExecutionProvider` is absent from the
post-fallback provider list. §8's ordering (F3 before F1) was already right; it is now
load-bearing rather than incidental. Note also that the EP Error goes to stderr **outside the
logger**, so the durable record is still the provider line of §11.2.**

### 4.4 Acceptance
- `grep "rembg providers" logs/backend*.log` → `['CUDAExecutionProvider', 'CPUExecutionProvider']`.
  Paste the literal line into Table A.
- Existing tests still pass unchanged. They are env-independent by construction:
  `test_fail_fast_when_gpu_required_but_cpu_only` sets the var,
  `test_cpu_fallback_allowed_when_not_required` `delenv`s it.
- If the flag now raises at startup: that is the ~12× discovery (unexpected per §4.3, and all the
  more worth recording). Fix the CUDA libs — `_new_session`'s comment names the
  `ort.preload_dlls()` / `libcublasLt.so.12` failure mode — then re-record B2's cutout band.

---

## 5. F4 — Verify the ComfyUI eviction actually landed

### 5.1 The defect
In `make_pet_zip`: a POST to `{COMFY_URL}/free` inside `except Exception: pass`, then
`time.sleep(1.5)`. No read-back, no log. **[Rev.2]** And per §0.4, ComfyUI's `/free` only sets a
queue flag and returns 200 unconditionally — the unload happens later on the prompt worker — so
1.5 s is a guess *and* the 200 carries no information. An unreachable endpoint, a 200 that
unloaded nothing, and a real eviction are all indistinguishable from the log.

### 5.2 The change — **[Rev.3] IMPLEMENTED** (`_evict_comfy_models_for_cutout`, `_comfy_vram_free`)
Replace the fixed sleep with a bounded poll of ComfyUI's `/system_stats`, which `start_all.sh`
already uses for readiness, so the endpoint is known-good. Field names confirmed against the live
instance 2026-07-26:

```json
{"devices": [{"name": "cuda:0 …", "type": "cuda", "index": 0,
              "vram_total": 25556615168, "vram_free": 6960944720}, …]}
```

- **Select the device by `index`, not `devices[0]`.** A 2-GPU box reports *both* devices even
  though this ComfyUI is pinned to one — confirmed live. **[Rev.2] The reason is not the one Rev.1
  gave.** This ComfyUI deliberately sorts the primary device first (`server.py`: "with the primary
  device first so existing clients that read `devices[0]` keep working"), so `devices[0]` is in
  fact ComfyUI's device. Index-matching is still correct, for a different reason: the device we
  care about is the one *the cutout* will run on, and `_CUTOUT_DEVICE_ID` need not equal ComfyUI's
  primary — that decoupling is exactly what the 2-GPU fan-out (§10) will exploit. Match on
  `_CUTOUT_DEVICE_ID`.
- Poll until `vram_free` ≥ `_FREE_TARGET_VRAM_BYTES`, or `_FREE_POLL_TIMEOUT_S` elapses, at
  `_FREE_POLL_INTERVAL_S` intervals.
- Log one INFO line either way: `vram_free` before, after, and the wait actually taken. **[Rev.3]
  That line is only visible because of F5 (§5.5); before it, this INFO went nowhere.**
- On timeout or unreachable endpoint: log WARNING and **proceed** (§0.5). Keep the POST's
  exception guard, but log instead of `pass`.
- **[Rev.3 — DEFECT FOUND AND FIXED] Anchor the poll deadline AFTER the POST, not before the
  first read.** The first implementation computed `deadline = started + _FREE_POLL_TIMEOUT_S`
  where `started` preceded two HTTP hops — the `before` read and the `/free` POST — each able to
  burn a full `_COMFY_HTTP_TIMEOUT_S` (10 s) against a 20 s budget. Verified: with the two hops
  made to cost 0.30 s against a 0.25 s budget, the `while` loop iterated **zero** times and the
  read-back never happened. The failure mode is precisely inverted from what you want — the poll
  gives up exactly when a sluggish ComfyUI makes verifying the eviction most valuable. `started`
  is retained for the elapsed figure in the report; the deadline is now `time.time() +
  _FREE_POLL_TIMEOUT_S` after the POST, pinned by §7 item 15.

**[Rev.2 — CORRECTED] Derive `_FREE_TARGET_VRAM_BYTES` from the requirement, not from B4.**
Rev.1 said to set it "from baseline B4" and deferred F4 to last for that reason (§11.1). That is
circular: B4 is an observation of *current* behavior, so if eviction is broken B4 is low, the
watermark is set to the broken value, and the poll passes trivially forever — the check would
certify whatever it found. The watermark is a requirement, and F1 has now measured it:

```
_FREE_TARGET_VRAM_BYTES = _CUTOUT_WORKING_SET_BYTES + _CUTOUT_PEAK_TOLERANCE_BYTES
```

i.e. "enough free VRAM for the cutout plus its out-of-arena context to fit" — 7 GiB + 1 GiB =
**8192 MiB** with §6's values. **[Rev.3]** This is why F4 could ship ahead of F1 (§8): the
watermark needs the cutout's *budget*, which §2.6 measured, not the arena *cap*, which F1 will
later set to the same number. B4 stays in Table A as the observation this is compared against,
and per §0.5 it is a sample, not a constant.

**[Rev.3] Rev.2 predicted this would time out on current behavior. It does not — it lands.**
Rev.2 reasoned from the one idle B4 (6638 MiB, below the 8192 MiB target) that the first result
would be a warning, and called that "the first evidence that `/free` does not reclaim what the
cutout needs". Measured against the live instance instead of inferred: **5535 MiB → 23874 MiB in
0.5 s, ~18 GB reclaimed, target met.** The prediction was wrong because it compared the target
against free VRAM *before* the eviction, which is the one number the eviction exists to change.
`/free` works; what was missing was any way to know that.

### 5.3 Note the reload cost this is buying
`free_memory: True` is more aggressive than `unload_models` alone, and the Wan stack is **34 GB**
on disk (14 + 14 GB experts, 6.3 GB umt5 TE, 243 MB VAE — verified). This box has 62.5 GiB RAM with
~46 GB free/cached, so the weights *can* mostly stay cached — but that is close enough to the
ceiling that a second ComfyUI evicts them. **The reload cost lands on the next build, not the one
being timed**, so it is invisible in a single-build measurement and shows up as a mysteriously slow
first phase on back-to-back runs. Record B2 for two consecutive builds, not one (Table A note).

### 5.4 Acceptance — **[Rev.3] MET**
- ✅ Log shows the before/after `vram_free` and the measured wait:
  `ComfyUI eviction landed: vram_free 5535 MiB → 23874 MiB (target 8192 MiB) after 0.5s`
- ✅ **The reclaimed amount is now known for the first time: ~18 GB (5535 → 23874 MiB), in 0.5 s
  — one poll interval.** The `sleep(1.5)` it replaces was 3× longer than the eviction actually
  takes *and* told the reader nothing. A warm re-run (already evicted) returns in 0.2 s having
  slept zero times, which is what `test_free_poll_stops_as_soon_as_the_target_is_met` pins.
- ✅ A stopped/unreachable ComfyUI produces a WARNING and the build still proceeds — covered by
  `test_free_poll_timeout_warns_and_proceeds` (§0.5). Not yet exercised against a genuinely
  stopped instance in a real build; the stubbed path is exact, but say so rather than imply it.
- **[Rev.2]** A timeout against a *running* ComfyUI that did not reclaim to the target is also a
  WARNING-and-proceed, and is a **finding to record**, not a threshold to lower. **[Rev.3]** Rev.2
  expected this to be the *first* result and it was not — see §5.2. The eviction lands.

### 5.5 [Rev.3] F5 — the reports have to be visible (`webui/app.py`) — **IMPLEMENTED**

**The defect.** Nothing in the app configured logging: no `basicConfig`, no `dictConfig`, no
`setLevel`, anywhere in `webui/`. So the root logger had no handler and Python's
`logging.lastResort` applied — **WARNING and above reached stderr, INFO was discarded.**

uvicorn does not cover this. Verified by configuring uvicorn's `LOGGING_CONFIG` and inspecting
root: `handlers == []`. Its dictConfig defines only `uvicorn*` loggers, and those do not
propagate.

**Why it is part of this spec and not a housekeeping aside.** F4 reports its *success* at INFO
and its *failures* at WARNING. With INFO discarded, a landed eviction wrote nothing to the log and
a failed one wrote a warning — so the observability fix had the same defect it was built to
remove: **"it worked" and "it never ran" produced identical evidence.** Measured before the fix:
calling `_evict_comfy_models_for_cutout()` with the target already met printed nothing at all.

**The change.** `logging.basicConfig` at module scope in `webui/app.py`, level from
`DATSPET_LOG_LEVEL` (default `INFO`), resolved with `getattr(logging, name, logging.INFO)` so an
operator typo degrades to the default instead of raising at import and taking the backend down.

Three properties worth stating because each was checked, not assumed:

- **It does not fight uvicorn.** Root is untouched by uvicorn's config (measured above), and
  uvicorn's own loggers do not propagate, so there is no double-printing.
- **It yields to an embedding host.** `basicConfig` is a documented no-op when root already has
  handlers, so a host that configures logging itself keeps its configuration.
- **It does not break the GPU-less posture.** `logging` is stdlib; no ML import is added.

**Acceptance — MET.** The eviction's success line now appears:

```
2026-07-26 10:51:20,464 INFO    pet_factory.factory: ComfyUI eviction landed: vram_free 8192 MiB → 8192 MiB (target 8192 MiB) after 0.0s
```

**This reverses §11.2.** That open item proposed promoting the `rembg providers` bare `print` to
`log.info`. Before F5 that would have made the line **disappear** — the un-migrated `print` was
strictly more visible than the logger. After F5 the promotion is safe. Sequencing matters, so the
item is now closed with that dependency recorded rather than left as free-standing advice.

---

## 6. Named constants

All in `factory.py`'s constants band next to `_ANCHOR_SEED`, each with a comment citing its
section here. **[Rev.4] All of them are now in the tree — F1 shipped, so there is no ⬜ left.**

| | constant | value | § | rationale |
|---|---|---|---|---|
| ✅ | `_CUTOUT_DEVICE_ID` | `0` | 2.2, 5.2 | the CUDA device the cutout runs on; also the `/system_stats` device selector. Shipped early because F4 needs the selector |
| ✅ | `_CUTOUT_WORKING_SET_BYTES` | `7 * 1024**3` | 2.4, 2.6 | birefnet's measured REQUIREMENT — the capped session settles at 6426 MiB, and this is that plus rounding. Rev.1's 4 GiB fails every frame. **[Rev.3] Renamed** from `_CUTOUT_GPU_MEM_LIMIT_BYTES` because F4's watermark derives from it and it shipped first. **[Rev.4]** That rename turned out to be load-bearing rather than cosmetic: F1 needed a *different* number for the cap, and had the two still shared a name they would have been silently merged |
| ✅ | `_CUTOUT_PEAK_TOLERANCE_BYTES` | `1 * 1024**3` | 2.5, 5.2 | **[Rev.2] new.** The CUDA context lives outside the arena (264 MiB bare, 526–554 MiB with the session loaded), so process peak can legitimately exceed the budget. Names what Rev.1 §2.5 left as the unnamed word "tolerance" |
| ✅ | `_CUTOUT_MAX_FALLBACK_FRAMES` | `0` | 3.2 | one opaque frame is a visible white flash; the name makes the decision revisitable |
| ✅ | `_FREE_TARGET_VRAM_BYTES` | `_CUTOUT_WORKING_SET_BYTES + _CUTOUT_PEAK_TOLERANCE_BYTES` | 5.2 | derived from the requirement (the cutout must fit), not from observed B4 — Rev.1's derivation was circular |
| ✅ | `_FREE_POLL_TIMEOUT_S` | `20` | 5.2 | bounded wait, replaces the blind `sleep(1.5)`. Measured: the eviction lands in 0.5 s, so this is a ceiling that is never approached in the healthy case |
| ✅ | `_FREE_POLL_INTERVAL_S` | `0.5` | 5.2 | poll cadence |
| ✅ | `_COMFY_HTTP_TIMEOUT_S` | `10` | 5.2 | **[Rev.3] new**, not in Rev.2's table: the per-request timeout for the eviction POST and each stats read. Rev.2 would have had these as inline literals. Only the new call sites use it; the pre-existing inline `timeout=` values in `_run` are left alone as out of scope |
| ✅ | `BACKEND_LOG_LEVEL` | `os.environ["DATSPET_LOG_LEVEL"]` or `"INFO"` | 5.5 | **[Rev.3] new**, and in `webui/app.py` rather than `factory.py` — the only constant here that is not a factory value, because the defect it fixes is the app's. Operator-overridable so a pool node drowning in INFO has a lever that is not a code change; an unparseable value falls back rather than raising at import |
| ✅ | `_CUTOUT_PROVIDER` | `"CUDAExecutionProvider"` | 2.2 | the parameterized provider name, used by both the options tuple and the fail-fast check |
| ✅ | `_CUTOUT_ARENA_STRATEGY` | `"kNextPowerOfTwo"` | 2.3, 2.6 | **[Rev.2]** the ORT default, and measurably better than `kSameAsRequested` on both axes — tolerates a tighter cap and settles ~574 MiB lower. Rev.1 specified `kSameAsRequested` and called it mandatory; that is falsified by §2.6 rows 6 vs 11. Pinned by name in a guard test, because ORT's *generic* docs recommend the opposite and this looks like a bug to a reader who has not seen the measurement |
| ✅ | `_CUTOUT_GPU_MEM_LIMIT_BYTES` | `8 * 1024**3` | 2.2, 2.6, 2.8 | **[Rev.4] NOT an alias of `_CUTOUT_WORKING_SET_BYTES`, and Rev.3's table was wrong to say it would be.** They answer different questions: this is the CEILING (what ORT may hoard), that is the REQUIREMENT (what the cutout needs, hence what F4's watermark is built from). Merging them either caps at 7 GiB with ~1 GiB over the floor, or drags F4's watermark to 11 GiB so the poll warns when 8 GiB free was fine — `test_the_cap_and_the_requirement_are_separate_numbers` pins the split. 8 GiB is the midpoint of the proven-good band [6144, 10240] (§2.6): 2 GiB clear of the highest failing cap, 2 GiB clear of the lowest that stops bounding anything |

---

## 7. Guard tests

`pet_factory/tests/test_cutout_hygiene.py` — **[Rev.4] 20 tests, green.** Zero-GPU, zero network,
stubbed sessions, following `test_gpu_fail_fast_and_progress.py`'s existing patterns. Items 7+
are additions the implementation showed were worth pinning.

**[Rev.4] Each new F1 assertion was red-green verified** — mutated to the wrong value and watched
to fail, then restored. An assertion nobody has seen fail is a guess about what it covers. The
five mutations checked: cap raised to 12 GiB (the silent dead band), cap raised to 16 GiB, cap
lowered to 4 GiB, strategy switched to `kSameAsRequested`, and the cap aliased to
`_CUTOUT_WORKING_SET_BYTES` — which is what Rev.3's own §6 told an implementer to do. All five
caught. Two of them originally failed with a bare `AssertionError` and no message; both now
explain the cliff, because this is the assertion someone meets *after* deciding to raise the cap
and a naked traceback would just look like an obstacle.

1. **`test_the_arena_options_are_actually_passed_to_the_cuda_provider`** and
   **`test_passing_provider_options_does_not_disarm_the_gpu_fail_fast`** — **[Rev.4] written**,
   split in two because they pin different contracts. **[Rev.2] Rev.1's single version was
   tautological**: it stubbed `rembg.new_session` wholesale, so ORT never saw the options and the
   test could not tell an options tuple from the bare list that preceded F1. The stub now
   **captures** its `providers` kwarg. (a) asserts the CUDA provider arrives as a `(name, dict)`
   tuple carrying all three knobs with CPU left bare — our half of the rembg contract; (b)
   asserts a `get_providers()` returning bare names still satisfies the CUDA check — §2.3's
   invariant, and the one that fails in the *dangerous* direction, since a fail-fast that stops
   matching silently re-arms the 1/12-speed CPU fallback F3 exists to catch.
2. **`test_cutout_failure_raises_instead_of_shipping_opaque_alpha`** — `_remove_bg` raises →
   `pack_datsme_bundle` raises `CutoutFailed`; assert no bytes returned. Pins §3.2.
3. **`test_cutout_failure_still_releases_the_session`** — the `finally` release survives the new
   raise path. Pins §3.2's GPU-hygiene claim. **[Rev.2]** Drive it through `make_pet_zip`'s
   `finally`, not `pack_datsme_bundle`'s — the latter has none (§3.2).
4. **`test_free_poll_selects_device_by_index`** — a fake `/system_stats` with `index: 1` first
   must still read `index: 0`'s `vram_free`. Pins the §5.2 two-GPU trap.
5. **`test_free_poll_timeout_warns_and_proceeds`** — an unreachable/never-reclaiming endpoint does
   not abort the build. Pins §0.5.
6. **`test_cutout_budget_constants_are_named_and_above_the_measured_floor`** — the constants
   exist and the budget is **above the measured 6 GiB floor**, not merely "> the model size" as
   Rev.1 had it. Rev.1's bound would have passed the broken 4 GiB value: the 214 MB model size is
   not the relevant floor (§0.2), the measured working set is. This is the test that catches a
   future model swap invalidating §2.6. **[Rev.3]** The `kNextPowerOfTwo` assertion moves here
   with F1; the budget assertion did not wait, because F4 already depends on the number.

   **[Rev.4] F1 split this into two more tests, and one of them is the most important assertion
   in the file:**

   - **`test_the_arena_cap_stays_inside_the_band_where_it_actually_does_something`** — pins
     **both** edges of [6144, 10240] MiB. The lower edge is a convenience: below it the cutout
     raises on the first frame, loudly and immediately. The **upper** edge is the one that earns
     its keep, because it guards the only way F1 can fail *silently* — past ~10 GiB the arena
     resumes growing, the build is identical, the speed is identical, no test fails, and the fix
     is simply gone. "The cap looks tight, let's raise it" is the natural move after any memory
     scare and it lands exactly in that dead band, so the failure message explains the cliff
     rather than printing two numbers.
   - **`test_the_cap_and_the_requirement_are_separate_numbers`** — asserts the ceiling sits above
     the requirement and that F4's watermark is still built from the requirement. This exists
     because Rev.3's §6 explicitly instructed an implementer to alias them (§2.8), and either
     resulting value is wrong in a different, quiet way.

**[Rev.3] Added during implementation** — each pins something the code review of the diff would
otherwise have to re-derive:

7. **`test_cutout_failure_aborts_the_pose_instead_of_mixing_matted_and_opaque_frames`** — fails
   on frame 3 of 8 and asserts the remaining 5 are never matted. Zero tolerance is only
   meaningful if it aborts *mid-pose*; the old bug's signature was a sheet mixing matted and
   opaque frames, and that is what must not come back.
8. **`test_a_successful_cutout_still_returns_bytes`** — the happy path. F2 is a change to error
   handling, and the cheapest way to get it wrong is to make a working build raise.
9. **`test_zero_fallback_tolerance_is_the_shipped_decision`** — asserts
   `_CUTOUT_MAX_FALLBACK_FRAMES == 0`, so raising it fails here first, next to the comment
   explaining why it is zero, rather than silently invalidating tests 2 and 7.
10. **`test_free_poll_stops_as_soon_as_the_target_is_met`** — asserts *zero* sleeps when the
    eviction has already landed. The whole point of F4 is replacing a blind wait; a poll that
    always paid one interval would have quietly kept the defect.
11. **`test_free_poll_returns_none_for_a_device_that_is_not_reported`** and
    **`test_free_poll_reports_unknown_rather_than_zero_when_stats_are_unreadable`** — an
    unreadable device must be `None`/`"unknown"`, never `0`. A log line reading `0 MiB free`
    inverts the meaning of the reading and sends the reader hunting a leak that isn't there.
12. **`test_free_target_is_derived_from_the_requirement_not_from_observed_free_vram`** — pins
    §5.2's correction structurally, so the circular B4-derived watermark cannot come back.
13. **`test_poll_budget_is_bounded_and_actually_polls`** — interval < timeout ≤ 60 s. A timeout
    below one interval never re-reads; an unbounded one hangs a build behind a wedged ComfyUI.

**[Rev.3] Added by post-implementation review** — each was written *after* finding the defect it
covers, and each was confirmed **red-green**: reverted against the unfixed code, exactly these
fail and nothing else does. A guard test that passes either way is worthless, so this was checked
rather than assumed.

14. **`test_fallback_budget_is_build_wide_not_per_pose`** — sets the tolerance to 1, fails one
    frame in each of two poses, and requires the *second* pose's failure to raise. Against the
    per-pose implementation the build succeeded with two opaque frames. Pins §3.2.
15. **`test_poll_budget_starts_after_the_post_not_before_the_first_read`** — makes the two
    pre-loop HTTP hops (0.30 s) exceed the whole poll budget (0.25 s) and asserts the loop still
    re-reads at least once. Against the `started`-anchored deadline it re-read zero times.
    Pins §5.2.

`webui/tests/test_logging_visibility.py` — **[Rev.3] 3 tests, green.** Covers F5 (§5.5):
root logging is configured at a level that keeps INFO; a bogus `DATSPET_LOG_LEVEL` falls back
instead of killing the boot; the level is operator-overridable.

These patch `logging.basicConfig` and reload the app rather than asserting on root's handlers —
**deliberately**, because pytest's own logging plugin attaches handlers to root, so an assertion
about root would pass whether or not the app configured anything. That is the same tautology §7.1
calls out in Rev.1's provider-options test, and repeating it in the fix for an observability bug
would have been the sharpest possible own goal.

---

## 8. Implementation order (not negotiable)

1. ✅ **F2** — loud cutout failure. First, because it is the instrument every later step is read
   with. A too-tight arena cap from F1 manifests *through* F2's path; without F2 it manifests as a
   white pet reported as success. **[Rev.3] Landed.** `CutoutFailed` + `_CUTOUT_MAX_FALLBACK_FRAMES`
   in `factory.py`; `prep()` now takes the pose name so the exception can say which frame died.
2. ✅ **F3** — arm the fail-fast. Second, because it closes the "is the cutout even on CUDA?"
   question at the source rather than by inference. **[Rev.2]** Rev.1 placed it here because that
   question was open and worth ~12×; §4.3 has since answered it (CUDA, already). The position
   still holds — it is one line, and it makes the answer permanent rather than a one-off probe —
   but it is no longer load-bearing for the timing work. **[Rev.3] Landed** in `pet_env.sh`,
   beside the `LD_LIBRARY_PATH` block it guards. Verified: the flag is set and the real session
   still builds on CUDA.
3. ⬜ **Re-run the §1 baseline.** With F2 + F3 in, the numbers are trustworthy for the first time.
   Record as Table A "after F2+F3". This is the real baseline; §1's is the archaeology.
   **[Rev.3] Still outstanding** — no full 8-pose build has been run since F2/F3 landed, so B2
   and B5 are still empty.
4. ✅ **F4** — eviction verification. **[Rev.2]** No longer gated on baseline B4: §5.2 derives
   `_FREE_TARGET_VRAM_BYTES` from the cutout's measured budget. **[Rev.3] Landed and moved ahead
   of F1**, which is what its independence bought: `_evict_comfy_models_for_cutout()` +
   `_comfy_vram_free()` replace the blind `sleep(1.5)`. Verified against the live instance, both
   paths (§5.4).
5. ✅ **F1** — arena cap. **[Rev.4] Landed last, exactly as the ordering intended.** Rev.2 called
   it "a verification, not a search"; Rev.3 deferred it on §2.7. Both were right in sequence: the
   deferral bought four more measurements (§2.6 rows 14–17) which found the cliff, retired two of
   the three objections (§2.8), and changed the shipped cap from Rev.3's proposed 7 GiB to 8 GiB
   for reasons that did not exist when Rev.3 was written. Shipping it first would have shipped a
   worse number with a weaker guard test.

   Landing it last also meant F2 was already in place to catch a too-tight cap loudly, which is
   what §8's whole "not negotiable" ordering was for — and it stayed theoretical, because the cap
   was calibrated before it ever ran in a build.

6. ✅ **[Rev.3] F5** — visible logging (§5.5). Not in Rev.2's plan at all; found by reviewing the
   implementation and required before F4's report means anything. Landed with F4's two defect
   fixes (§3.2, §5.2).

F2 and F3 were ~20 lines between them; F4 was ~55 with its two helpers; F5 was ~8 plus its
comment. F1 remains ~10.

**[Rev.3] A note for whoever re-runs the gate.** The documented invocation
(`.venv/bin/python -m pytest pet_factory/tests webui/tests`, **without** sourcing `pet_env.sh`) is
470 green. Two environment traps cost time during this review and are worth knowing:
sourcing `pet_env.sh` first makes `test_accept_fixes.py::test_launch_cookie_is_samesite_none_secure`
fail, because the gitignored `pet_env.local.sh` sets `DATSPET_COOKIE_SAMESITE=lax` — pre-existing
and unrelated to this spec. And three stale `.pyc` files under `webui/tests/__pycache__/` carried
a `co_filename` from before this tree was renamed, so tracebacks pointed at a long-empty
`claude_code/datsme-pet-factory/` directory. Pytest validates its rewritten-assertion cache on
source **mtime + size only**, so they were being reused. Cleared; `find . -name __pycache__ -prune
-exec rm -rf {} +` after any future repo move.

---

## 9. Completion record — fill this in

### Table A — measurements

**[Rev.3] MEASURED** — `black bat`, 8 poses (`winged_flyer`), 2026-07-26 11:35, F2–F5 in the tree,
F1 not. Instrumented runner calling `make_pet_zip` directly — the same call `webui/app.py`'s local
branch makes under `GPU_LOCK`; only the HTTP/job wrapper differs. It replicates F5's `basicConfig`,
which is the only reason B1 and B4 exist as records at all (§11.9).

| # | measurement | **measured (F2–F5, no F1)** | with F1, projected |
|---|---|---|---|
| B1 | `rembg providers` | `['CUDAExecutionProvider', 'CPUExecutionProvider']` — CUDA, as §4.3 predicted | unchanged |
| B2a | base + anchors band | **97.5 s** (20.7%) | unchanged |
| B2b | loops band | **326.7 s** (69.4%) | unchanged |
| B2c | cutout + pack band | **46.7 s** (9.9%) — 128 frames ⇒ **0.365 s/frame** | unchanged |
| B2d | total wall time | **470.9 s** (7.9 min) | unchanged |
| B2e | total, 2nd consecutive build — §5.3 | not run | — |
| B3 | peak VRAM, **this process** | **14618 MiB** | ~6426 MiB (§2.6 row 10) |
| B4 | eviction, before → after | **5631 → 23875 MiB, ~18 GB, in 0.7 s** — target met | unchanged |
| B5 | **per-frame alpha (§1)** | **128 frames, 0 opaque fallbacks — PASS** | unchanged |

**B3 = 14618 MiB is the finding, and it closes the biggest open question in this spec.** That is
§2.6 row 1's uncapped arena figure **to the MiB**, reproduced inside a real 8-pose build rather
than a standalone probe. Three things follow:

1. **The §2.6 sweep transfers.** A scratch probe on an idle card and a real build agree exactly, so
   the calibration in §6 can be trusted for F1.
2. **F1's payoff in the real pipeline is now proven, not projected: ~14618 → ~6426 MiB, ~8 GB.**
   Review had argued the 2.3× might be an artifact of measuring on an idle card — that on the real
   `cuda:0`, with ComfyUI resident and only ~6.6 GB free, the arena could never reach 14.6 GB and
   F1 would reclaim nothing. **The build settles it, and the mechanism is the coupling that
   objection missed:** F4's eviction frees ~18 GB *immediately before* the cutout, so by the time
   birefnet allocates, the card is nearly empty and the unbounded arena grows to fill it. The
   `black bat` build spent 14.6 GB on a 214 MB model because there was 23.8 GB free to take.
3. **So F4 working is exactly what makes F1 worth doing.** §0.5 has these coupled in one direction
   (F1 frees F4 from gating the build); this is the other direction, and it is the stronger one.

Two smaller results:

- **`_fill_holes_alpha` does not need vectorizing** (§10 non-goal, previously "measure it").
  Cutout + pack is 0.365 s/frame end-to-end, against 0.27–0.36 s/frame for birefnet inference alone
  in the §2.6 probe. Inference dominates; the interpreted flood fill is inside the noise. Closed on
  data rather than left open.
- **The assumed band proportions were off.** §1 documents 10/12/63/15; measured is 20.7 / 69.4 /
  9.9. Anchors cost about twice the assumed share and the cutout tail about a third less — worth
  correcting before anyone sizes the fan-out work against the old split.

**A prediction that was wrong, recorded because the reasoning error is reusable.** Before the run
this was expected to take F4's *fast* path — `cuda:0` read 23978 MiB free beforehand, far above the
8192 MiB target, so the poll should have found the target already met and slept zero times. It
did not: it started at **5631 MiB**. The pre-build reading was irrelevant because *the build itself*
loads the Wan stack into that space. B4 must be read immediately before the cutout, which is
precisely where F4 reads it — and precisely why a watermark derived from an observation (§5.2's
corrected circularity) would have been meaningless.

**[Rev.3] Two real builds have now been run.** The table above is the **second** (11:35,
instrumented, F2–F5 live). The **first** was through the UI — `black_bat`, 8 poses, 11:07,
`winged_flyer` — and is what closed §3.4's real-build half; its numbers were limited to B5 because
its backend logged to a tty (§11.9). Both agree where they overlap: **128 frames, 0 opaque
fallbacks, 0 ERROR lines.**

**First, the check that makes the rest of this row mean anything: did the build actually run the
new code?** This repo's backend has no `--reload`, so a build submitted to a backend started
before the edits would exercise a stale snapshot and "prove" nothing. Verified, not assumed:
`factory.py` last written **10:51:04**, backend process 2028540 started **10:56:45**, bundle
written **11:07:39** — the process postdates the edit. And `/proc/2028540/environ` carries
`PET_FACTORY_REQUIRE_GPU=1`, so F3 was armed *in the process that did the build*; since the build
succeeded, the fail-fast necessarily saw CUDA. Record this ordering for every future Table A row —
without it, a green build is not evidence.

**B5 passes outright and is the strongest evidence in this spec:**

| | result |
|---|---|
| sheet alpha extrema | `(0, 255)` — PASS |
| **per-frame** (the check that matters, §1) | **128 frames, 0 opaque fallbacks, 0 empty** |
| per-frame transparent-pixel fraction | **0.600–0.796**, and tight *within* each pose (walk 0.644–0.662, sleep 0.621–0.622, fly 0.698–0.796). Stronger than "not opaque": a near-degenerate matte — a frame the model barely cut — would show up as an outlier low fraction, and none does. The spread across poses tracks silhouette size, which is what it should track |
| poses emitted | walk, idle, run, sleep, sit, eat, jump, fly — 16 frames each, 8×16 grid |
| bundle metadata | `movement_class=winged_flyer`; `jump` `loop:false`; `sleep` `timed_buffer_ms:6000`; view `side/right/flip` — the content→bundle contract round-trips |
| F2 ERROR lines | none |

So the cutout is genuinely matting every frame, and F2's zero-tolerance did not turn a working
build into a failure. **B1–B4 are still empty, and for a reason worth fixing** (§11.9): this
backend was started as a bare `uvicorn app:app`, whose stdout is a **tty** (`/dev/pts/12`), not
`logs/backend.log`. The provider line and the eviction report were both printed and both lost.
`start_all.sh` redirects to `logs/<name>.log`; a hand-started backend does not.

### Table B — sign-off

| fix | landed | guard tests | acceptance (§) | notes / surprises |
|---|---|---|---|---|
| ✅ F2 loud cutout failure | `factory.py` — `CutoutFailed`, `prep(pose_name, frames)` | 6 in `test_cutout_hygiene.py` | §3.4 — **met** | **[Rev.3] Real build verified:** `black_bat`, 8 poses, **128/128 frames matted, 0 opaque fallbacks, 0 ERROR lines**. Zero tolerance did not break a working build — the risk §3.4 flagged. Builds that now fail but previously "succeeded": **0 of 1 so far**; needs more builds before the old defect's rate is known |
| ✅ F3 arm GPU fail-fast | `pet_env.sh`, beside `LD_LIBRARY_PATH` | existing 3, unchanged | §4.4 — met | CPU fallback found? **N**, as §4.3 predicted. Flag set, real session still builds `['CUDAExecutionProvider', 'CPUExecutionProvider']`. No speedup, none expected |
| ✅ F1 arena cap | `factory.py` — `_CUTOUT_GPU_MEM_LIMIT_BYTES` (8 GiB), `_CUTOUT_ARENA_STRATEGY`, `_CUTOUT_PROVIDER` + the options tuple in `_new_session` | 4 in `test_cutout_hygiene.py`, all red-green verified | §2.5 — **met** | **Peak 14618 → 6426 MiB (8 GiB reclaimed)**, measured through the shipped `factory._rembg()` path with ORT reading `gpu_mem_limit=8589934592` back. Alpha `(0, 255)` every frame; 0.27–0.28 s/frame, unchanged. `release()` still returns the arena (6426 → 264 MiB). **Surprises: (1)** peak-vs-cap is a cliff — ≥12 GiB silently buys nothing — which inverted the risk model and is now the upper-bound guard; **(2)** the cap and the requirement had to become separate constants, against Rev.3's §6 instruction; **(3)** the first `release()` reading looked broken and was the measurement holding a reference (§2.8) |
| ✅ F4 verify eviction | `factory.py` — `_evict_comfy_models_for_cutout`, `_comfy_vram_free` | 7 in `test_cutout_hygiene.py` | §5.4 — met | **VRAM reclaimed: 5535 → 23874 MiB = ~18 GB, in 0.5 s.** Hit the 8192 MiB target: **Y**. Warm re-run: already free, 0.2 s, zero waits. The `sleep(1.5)` was 3× longer than needed *and* proved nothing. **[Rev.3] Review found the poll deadline could be fully consumed before the loop began — fixed (§5.2)** |
| ✅ **F5 visible logging** | `webui/app.py` — `BACKEND_LOG_LEVEL` + `basicConfig` | 3 in `test_logging_visibility.py` | §5.5 — met | **[Rev.3] New in Rev.3, and F4 was inert without it:** INFO was being discarded process-wide, so a landed eviction logged *nothing* while a failed one warned. Root handlers after uvicorn configures itself: `[]`. Success line now appears |

### The one-line verdict
**[Rev.4] Fillable at last.** **B5 is `(0, 255)` per-frame on 128/128 frames of a real 8-pose
build, with no ERROR lines in the cutout band; peak cutout VRAM is bounded at 6426 MiB (from
14618); and eviction is confirmed reclaiming ~18 GB in 0.5 s.** All five fixes are in the tree,
478 tests green, and every number above was measured rather than estimated.

Still open, and none of it is cosmetic. **B5 on three consecutive builds, not one** — a single
clean build is evidence, not a rate. **B2's timing bands and B3 from a real build**, which need a
backend started through `start_all.sh` so stdout reaches `logs/` (§11.9); B3 is currently proven
only through the shipped code path in isolation, not against a contended card. **How many builds
the old silent fallback was actually degrading** — the number that would say what F2 was worth,
and which no amount of testing can supply. And **the pool nodes see none of this yet** (§11.8):
the handler runs in its own subprocess with no logging configured, so on a pool node F1's and
F4's reports are still discarded.

The spec's own thesis is the thing to hold onto: none of these five was a performance fix. They
exist so that the next round of work — the fan-out, the cutout pipeline, `_fill_holes_alpha` —
can be measured instead of guessed at. That is now true, and it was not true this morning.

---

## 10. Non-goals — deliberately out of scope

Named here so this spec stays reviewable and so nobody reads a robustness change as a
performance promise.

- **The 2-GPU self-contained build fan-out** (one whole build per card, ~2× throughput). This is
  the next spec, and it is the real performance work. It depends on F1 (`device_id` pinning) and
  on threading each endpoint's URL + output dir through `_run`/`make_pet_zip` — `COMFY_OUTPUT_DIR`
  and `COMFY_URL` are module globals in `factory.py`, which is the one genuine obstacle. Note the
  honest ceiling: a single 24 GB card cannot hold 14 + 14 GB of Wan experts plus a 6.3 GB TE, so
  each self-contained build pays an expert swap per pose — 2× *throughput*, not a 2× faster single
  pet. **[Rev.2]** F1 helps more than Rev.1 assumed here: 8 GiB of reclaimed arena is a third of a
  card, and §2.6 row 11 shows the cap can be pulled to 6144 MiB at no cost in peak if a fan-out
  build needs the room. **[Rev.4] With F1 shipped, this dependency is now satisfied, and it was
  the strongest argument for shipping F1 at all** (§2.8): `device_id` rides in the same provider
  options tuple as `gpu_mem_limit`, and ORT's default is `device_id: 0` — measured. Without it
  two concurrent self-contained builds would both put their cutout on cuda:0. The fan-out spec
  therefore starts from a cutout that is already per-device pinned and bounded at a known
  6426 MiB, rather than having to introduce device pinning, a memory bound, and concurrency in
  one change.

  **[Rev.5 — the "remaining obstacle" was never an obstacle. Measured: a whole build already runs
  on GPU 1 with NO code change.**](#) Every earlier revision called
  `COMFY_URL` / `COMFY_OUTPUT_DIR` being module globals the blocker. They are globals *read from
  the environment at import*, so a per-card build needs only env:

  ```bash
  CUDA_VISIBLE_DEVICES=1 \                                   # the in-process birefnet cutout
  PET_FACTORY_COMFY_URL=http://127.0.0.1:19963 \             # start_comfyui_gpu1.sh, --cuda-device 1
  PET_FACTORY_COMFY_OUTPUT=<ComfyUI>/output_gpu1 \
      python -c "from pet_factory import make_pet_zip; ..."
  ```

  A complete 3-pose build ran this way on 2026-07-26 in **176.9 s**, fully isolated, while GPU 0
  stayed free. Threading the endpoint through `_run`/`make_pet_zip` is required only to split **one**
  build across two cards — not for the self-contained-per-card design, which is the one actually
  wanted. Two further confirmations from the same run: `:19963` reports its device as `cuda:0`
  (that is `--cuda-device 1` remapping), so F4's index lookup reads the right card without
  changes; and `_CUTOUT_DEVICE_ID = 0` under `CUDA_VISIBLE_DEVICES=1` correctly lands the cutout
  on physical GPU 1. **The fan-out's cost estimate should be revised down accordingly** — the
  remaining work is orchestration (who dispatches to which card, and cross-process
  serialization), not plumbing.

  **[Rev.5] Related, and load-bearing for that orchestration: `GPU_LOCK` is process-local.** It is
  a `threading.Lock` in `webui/app.py`, so it serializes only builds *that backend process*
  starts. A CLI build, a script, or the Motion Lab bypasses it entirely. Observed twice on
  2026-07-26: an out-of-process build saturated ComfyUI while a user was in the designer, and the
  UI surfaced *"The GPU is busy generating a pet"* — which is the preview path's
  `GPU_LOCK.acquire(timeout=1.5)` fast-fail, pointing at the lock while the real cause was
  saturation from outside the process. A second occurrence corrupted a measurement run. Any
  fan-out multiplies the number of things driving ComfyUI, so cross-process serialization is a
  prerequisite, not a nicety.

- **[Rev.5] ComfyUI's `--highvram` — TRIED, MEASURED, DO NOT RETRY.** The loop band is ~69% of a
  build, so it is the only part worth optimizing, and per-loop time is dominated by *model
  movement*, not compute. Warm 704² loop, 3-pose A/B on 2026-07-26:

  | | per loop |
  |---|---|
  | two Wan expert stagings (13.6 GB each) | ~15 s |
  | `WanTEModel` re-staged (6419 MB) + VAE + encode/decode | ~18 s |
  | **actual sampling, 4 steps** | **~7 s** |
  | total | ~40 s (measured 42.0 / 40.3 / 36.9) |

  **~82% is model movement.** That makes `--highvram` look obvious — ComfyUI's own help says it
  "keeps them in GPU memory" instead of unloading, and `enables_dynamic_vram()`
  (`comfy/cli_args.py:284`) shows the flag switches the staging path off. **It does not work: it
  OOMs.** Both runs died with `Requested to load WAN21` → `OutOfMemory`, then `_run` polled a
  file that never appeared until its 360 s ceiling. Zero `"prepared for dynamic VRAM loading"`
  lines confirm the flag took effect — that *is* the failure. Resident-loading a 13.6 GB expert
  plus a 6.4 GB TE plus VAE plus context does not fit in 24 GB.

  **The conclusion that matters: the staging cost is not waste ComfyUI could avoid — it is the
  only reason a ~34 GB model stack runs on a 24 GB card at all.** So the levers are fewer/smaller
  models, more VRAM per card, or parallelism across cards. Not a flag.

  Two corollaries, both correcting earlier guesses in this spec's own review thread:

  - **Resolution is not a lever.** 704² → 512² scales the ~7 s of sampling, not the ~33 s of
    movement — worth ~2 s per loop. Same for frame count and step count.
  - **The "two-pass expert split" (all poses' high-noise steps, then all low-noise) is a much
    weaker idea than it first appeared.** It was estimated at ~37% on the assumption that
    consecutive same-expert prompts would stage once. Leg A falsifies the premise: ComfyUI
    **re-staged on every prompt even when the model did not change** (init waits `15,15` on the
    cold loop, then `7,7 / 8,8 / 7,7`). There is a warm-cache effect that roughly halves it, but
    it is per-prompt regardless of model identity. Any revival of this idea must first measure
    whether consecutive same-expert prompts stage faster — the 37% figure was extrapolation and
    should not be quoted.
- **Vectorizing `_fill_holes_alpha` — MEASURED, NOT WORTH IT.** An interpreted BFS over a 256²
  alpha, run once per frame, 128 times in an 8-pose build; it looked like a plausible hidden CPU
  cost. It is not: the whole cutout + pack band runs at **0.365 s/frame** end-to-end against
  **0.27–0.36 s/frame** for birefnet inference alone (§2.6). Inference dominates; the flood fill
  is inside the noise. Closed on data, not deferred.
- **Pipelining the cutout behind the loops** — ~15% tail, and mutually exclusive with the fan-out
  since both want the second card.
- **Prod/pool behavior.** The web tier runs `PET_GEN_BACKEND=pool` with no ML stack and never
  executes this code. The pool *handler* nodes do, and inherit F1/F2/F4 when the handler is
  rebuilt — a separate rollout (`pool-install-handler`), not part of this spec. **[Rev.2]** That
  rollout carries the retry cost in §3.3: validate the cap on one node first, because a
  deterministic `CutoutFailed` costs a full build per retry per node.

---

## 11. Open items

1. **[Rev.2 — CLOSED] `_FREE_TARGET_VRAM_BYTES` no longer waits on baseline B4.** §5.2 derives it
   from the cutout's measured budget instead; Rev.1's B4-derived version was circular. **[Rev.3]**
   This is what let F4 ship *before* F1 rather than after it.
2. **[Rev.4 — DONE] The provider `print` in `_new_session` is now `log.info`.** Shipped together
   with item 8, and **only correct in that order** — this is the third time this item has changed
   direction, and each turn was a different reason the "cheap one-liner" was not one:

   - Rev.2 proposed the promotion outright.
   - Rev.3 found it would have made the line **disappear**: INFO was discarded process-wide
     (§5.5), so the bare `print` was strictly *more* visible than the logger.
   - Rev.4 found F5 alone was still not enough. On a **pool** node the promotion would have been a
     regression even after F5, because the handler runs in a subprocess F5 never reaches (item 8).
     Today's `print` at least surfaces there — as the worker's *"non-JSON handler stdout dropped"*
     warning, since stdout is `run_handler`'s JSON-lines protocol. A bare `log.info` into a
     handler-less root would have gone nowhere at all.

   So the promotion shipped **with** the handler logging blocks, never before them. Verified
   end-to-end: the line appears on **stderr** (`… INFO pet_factory.factory: rembg providers:
   ['CUDAExecutionProvider', 'CPUExecutionProvider']`) and **zero** occurrences on stdout, so the
   pool's result channel stays clean and the worker picks the line up in its heartbeat
   `stderr_tail`. §1's B1 grep is unchanged and still matches. Pinned by
   `test_the_provider_line_goes_through_the_logger_not_stdout`, red-green verified.

   **The lesson is the sequencing, not the line.** "Improve the logging" is a regression whenever
   nothing has checked that the logging works — and the check has to cover *every process the code
   runs in*, not just the one in front of you.

   **[Rev.3 — REOPENED, and now the promotion is required, not optional.]** On a pool node the
   handler's **stdout is a strict JSON-lines protocol** (`pool_worker/run_handler.py`: progress
   beats then exactly one result; the worker drops non-JSON stdout and logs
   `non-JSON handler stdout dropped`). So this `print` is not merely "easy to lose" there — it
   writes a junk line into a protocol channel on **every pool build**, today. It is non-fatal
   because the worker is tolerant, but it is the wrong stream by design. `logging` writes to
   **stderr**, which is exactly what the worker captures as its stall-visibility tail. So the
   promotion to `log.info` is the correct fix for a reason Rev.2 never had, and it must not be
   reverted to `print` for pool visibility — that would be backwards. This also retires the idea,
   briefly held during F4's implementation, that `print` is the robust channel for this module:
   it is the robust channel in a *terminal*, and the wrong one everywhere that matters.

   **There are two of these, not one** — `_new_session`'s provider line and
   `_prep_reference_image`'s "subject isolation failed, using the raw photo". Both write to
   stdout; both are on the pool path. Per the repo's sweep rule, promote them in the same change
   rather than fixing the one this spec happened to notice.
3. **Expert-swap cost during Phase B is unmeasured.** The ComfyUI log records
   `Requested to load WAN21` twice per generation and an `N models unloaded` count; on
   `comfyui_32g.log` that count is `0` throughout, but that is a VRAM-experiment config and may
   not reflect real 24 GB behavior. Quantify before the fan-out spec, since it sets that spec's
   realistic ceiling.
4. **[Rev.4 — CLOSED, WON'T FIX] The pool's retry cost on a deterministic `CutoutFailed`.**
   Rev.2 framed this as "dead-letter immediately, the other two attempts are pure waste". Both
   candidate fixes were investigated and **both are rejected on evidence.** The item is closed
   rather than reworded, because the conclusion is that there is nothing to build here.

   **Rejected: signal "permanent" to the dispatcher.** `pool_dispatcher/storage.py:_fail_locked`
   branches on `attempts >= max_attempts` and nothing else, and the contract has **no
   permanent/retryable concept** (`pool_contracts/messages.py` has only `JOB_TERMINAL_STATUSES`,
   which is the resulting state, not a handler signal). Implementing it means an engine change
   across four files in `shared_gpu_cpu` — defensible in principle, since "a handler may declare a
   failure permanent" is generic rather than app-specific. But setting the flag correctly requires
   distinguishing an **arena-limit** failure (deterministic, retry is waste) from a **device OOM**
   caused by a co-tenant (transient — retry on another node is exactly right, and
   `scheduler._recently_failed_here` exists to steer it). That is an error classifier built on
   zero observed instances. Deferred under the repo's three-instances rule.

   **Rejected on measurement: pre-flight the cutout before generating.** The idea was to keep the
   3 attempts but make each cheap — one tiny inference at handler start, failing in seconds rather
   than at the 0.85 mark, ~6.7 min in. It was *built and then reverted*, because **the pipeline
   itself creates the memory conditions the cutout needs, so the cutout cannot be validated out of
   sequence:**

   - the real cutout runs at **minimum** memory pressure — immediately after
     `_evict_comfy_models_for_cutout()` frees ~18 GB;
   - a pre-flight necessarily runs at **maximum** pressure, while ComfyUI still holds Wan.

   Measured directly: with Wan resident, `cuda:0` free was **2537 MiB** against the cutout's
   ~6426 MiB working set, and the pre-flight raised the arena error on a build whose real cutout
   would have succeeded minutes later. On a warm pool node that is not a marginal regression, it
   is total: **every** build fails pre-flight and burns all three attempts instantly — strictly
   worse than the problem. A guarded variant (probe only when free VRAM already exceeds the
   working set) would work, but it adds a second mechanism to rescue the first and silently
   does nothing on exactly the warm nodes it was meant to protect.

   **What stands instead** is what already exists: `test_the_arena_cap_stays_inside_the_band_where_it_actually_does_something`
   makes a bad cap fail the build gate rather than the fleet, and §3.3's staged rollout catches it
   at one node's cost. A configuration error should be caught by a test, not paid for at runtime.

   **The transferable lesson**, and the reason this is written up rather than deleted: *a resource
   check is only meaningful under the conditions the real work runs in.* The eviction is not
   incidental setup — it is what makes the cutout fit, so anything validating the cutout must run
   after it, which is precisely where the failure already surfaces.
5. **[Rev.2 — NEW; Rev.4 — still open, now with F1 shipped] Is 6426 MiB still too much to hold
   across the whole cutout band?** F1 bounds the arena but does not change *when* it is
   allocated: the session lives for the entire cutout + pack phase. With the loops finished and
   Wan evicted that is fine today, but the fan-out spec puts a second build's Wan load in exactly
   that window. Nothing to do now; flagged so the fan-out spec does not assume the cutout's
   6426 MiB is free real estate. **[Rev.4]** §2.6 row 11 is the lever if it ever is: the cap can
   drop to 6144 MiB at no cost in peak — but that spends the entire lower margin, so it is a
   deliberate trade for the fan-out to make with numbers, not a default.
6. **[Rev.4 — CLOSED] The §2.6 probe is now in the repo** as `scripts/probe_cutout_arena.py`,
   with two modes: `--sweep` re-runs the full cap/strategy table, `--shipped` measures today's
   constants through the real `factory._rembg()` path (that mode *is* row 17, and it reproduces
   6426 MiB and the 264 MiB release). Raised in Rev.3 as "needed before F1 lands" and honoured
   rather than waived, because §2.6 is the entire justification for two shipped constants and a
   table nobody can re-run is the unfalsifiable claim this spec exists to refuse. The two probe
   mistakes that cost real time — one frame instead of three, device-level instead of
   per-process VRAM — are documented in its module docstring so a re-run cannot repeat them.
7. **[Rev.3 — PARTLY CLOSED] F2's real-build half.** The `black_bat` build (§9) closed the half
   that mattered most: **128/128 frames matted, 0 fallbacks, 0 ERROR lines** — zero tolerance did
   not break a working build. What one build cannot give is the other number §3.4 asks for: how
   many builds the *old* silent fallback was degrading. That is a rate, so it needs a run of
   builds, and it can only ever be estimated now that the fallback is gone.
8. **[Rev.4 — DONE] F5 now reaches the pool nodes.** Both `pool_handler/pet_factory_handler.py`
   and `pool_handler/pet_preview_handler.py` configure logging at module scope —
   `DATSPET_LOG_LEVEL` (default INFO), typo-tolerant, and **explicitly `stream=sys.stderr`**
   because stdout is `run_handler`'s JSON-lines result protocol and logging there would inject
   non-JSON lines into the result channel. The handler is the app's own code running in that
   subprocess, so this needs no change to `shared_gpu_cpu`. Duplicated across the two handlers
   deliberately: they are independently installed (`pool-install-handler`) and must not grow a
   shared import. Four guard tests, red-green verified, including one that specifically pins
   `stream is sys.stderr` — the assertion that protects the result channel.

   Consequence: F4's verified-eviction **success** line is now recorded on pool nodes, not only
   its failures. The original diagnosis below is kept because the mechanism took two tries to get
   right:

   **[Rev.3] Conclusion confirmed; the mechanism is
   more specific than first written, and it changes the fix. It is **not** that the worker
   forgets to configure logging — `pool_worker/loop.py`'s `main()` *does* call
   `basicConfig(level=INFO)`. It is that the handler does not run in the worker process at all:
   the worker **spawns a subprocess**, `python -m pool_worker.run_handler <handler_file>`
   (`pool_worker/spawn.py`, contract §4.3, so a runaway handler can be process-group killed).
   Logging config is per-process, so the worker's `basicConfig` cannot reach it, and
   `run_handler.py` sets up none of its own (verified: zero `basicConfig`). Hence INFO is
   discarded there exactly as it was everywhere before F5.

   **[Rev.4] Independently re-verified**, because the item's first draft (mine) asserted the
   conclusion from the wrong mechanism — "the pool worker configures no logging", which is false:
   `loop.py`'s `main()` does call `basicConfig(level=INFO)`. Confirmed the corrected version at
   source: `spawn.py:23-25` runs `subprocess.Popen([sys.executable, "-m",
   "pool_worker.run_handler", handler_path], …)`, and `run_handler.py` contains **zero**
   `basicConfig` calls. Right conclusion, wrong reason, and the wrong reason would have sent the
   fix to the wrong file — worth noting that a correct conclusion is not evidence of a correct
   model.

   The fix must therefore be `logging.basicConfig(level=INFO, stream=sys.stderr)` **in
   `pool_handler/pet_factory_handler.py`** — ours, and the first of our code to run in that
   process. Two constraints make the stream explicit rather than incidental: the handler's
   **stdout is the JSON result protocol** and must carry nothing else, while its **stderr is
   captured by the worker** as the stall/error tail. `basicConfig` already defaults to stderr,
   but on a channel this load-bearing the default should be written down, not relied on.
   Belongs to the handler rollout (§10), and should land together with §11.2 — both are about
   what a pool node can actually see, and §11.2's `print` is currently polluting the very
   stdout this item has to keep clean.
9. **[Rev.3 — NEW] A hand-started backend throws its logs away, which is why B1–B4 are still
    empty after a real build ran.** The `black_bat` build went through a backend launched as a
    bare `uvicorn app:app`, whose stdout/stderr are a **tty** (`/dev/pts/12` — confirmed via
    `/proc/<pid>/fd/1`). `start_all.sh` redirects each service to `logs/<name>.log`; starting
    uvicorn by hand does not, so the `rembg providers` line (B1) and F4's eviction report (B4)
    were both emitted and both lost. F5 made those lines *exist*; this is the separate problem of
    where they *go*. Worth a line in `start_petmaker_backend_only.sh`, or a note in `CLAUDE.md`
    that a build whose evidence matters must be run via `start_all.sh`. Until then the paper
    trail has a hole that no amount of logging code will close.
10. **[Rev.3 — NEW] F5's format is not structured.** `basicConfig` with a text format is right for
   a dev box read by a human. If the pool ever ships these logs somewhere that parses them, it
   becomes the wrong choice and should move to JSON. Noted so the decision stays visible rather
   than inherited by default.
