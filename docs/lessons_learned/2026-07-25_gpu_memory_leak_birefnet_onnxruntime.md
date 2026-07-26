# Lessons Learned — the birefnet / onnxruntime GPU memory leak

**Date:** 2026-07-25 · **Area:** `pet_factory` generation pipeline (GPU) · **Severity:** high
(every build slow; some builds failed) · **Fix commit:** `abb054b` · **Time cost:** most of a
session, inflated by two wrong diagnoses.

**One-line summary:** A persistent onnxruntime CUDA session (birefnet cutout) never returned its
GPU memory, permanently holding ~6–15 GB on the 24 GB card and starving the next build's Wan
generation — which *looked* like a "slow build" and a "the engine isn't using the GPU" problem,
three layers away from the actual cause.

---

## 1. Symptoms (what was observed)

- A dragon design build ran **17+ minutes and still wasn't done** (a normal build is ~3 min).
- The GPU "**wasn't being used**" — utilization looked low while the build crawled.
- **Resting/idle GPU memory was high**: something held **~14.6 GB even when no build was running.**
- During generation, Wan appeared to **reload its models on every pose loop** (thrashing) instead
  of keeping them resident.
- Later, a **downstream casualty**: a build that had been starved hard enough saw its birefnet
  cutout **OOM** (`Failed to allocate memory for requested buffer of size 822083584`), so it
  produced no valid bundle → the result card rendered a **blank portrait and no animation grid**.
  (That blank was initially mis-attributed to a frontend / `loop:false` bug — see the separate note
  `blank-result-card-is-a-failed-build`. It was this leak all along.)

The unifying tell, which was there from the start and initially under-weighted: **memory held at
rest.** A slow *compute* problem does not leave 14.6 GB pinned on an idle GPU.

---

## 2. The investigation — including the wrong turns

The value of this entry is the dead ends. They were caused by two biases: *recency* (blame the
last change I made) and *assumption* (guess the environment instead of checking it).

### Wrong turn #1 — "it's the pose ordering change I just made"

Just before the slow build, generation had been reordered into two phases (all anchors, then all
loops — commit `7da9b48`). Natural suspect: my own recent change.

- **Claim:** the two-phase reorder introduced the slowdown.
- **Corrected by:** the user — *"I think it is not because of the order that caused it. your change
  introduced a new error. look at the resting GPU usage."* The reorder was in fact a valid
  optimization; it was not the cause. **Lesson: the most-recently-changed code is a suspect, not a
  verdict.**

### Wrong turn #2 — "we're competing with staging / the pool for the GPU"

- **Claim:** the build was contending with a shared/staging/pool process on the same GPU.
- **Corrected by:** the user — *"it is not running anywhere else. it is in development… 24 G VRAM
  should be sufficient. we didn't have problems before."* **Lesson: verify the environment; do not
  extrapolate one topology onto another** (`dev-prod-parity-seams`). The contention was real, but it
  was *self*-contention: our own leaked session vs. our own next build.

### Turning toward the evidence

The user redirected to the actual signal — *"something is sucking up the GPU when it is idle"* — and
then named the culprit precisely: *"birefnet cutout: onnxruntime's CUDA session grabs ~14.6 GB, why
isn't it being released."* That reframed the problem from **"why is compute slow"** to **"why is
memory never freed"** — the correct question.

### Wrong turn #3 — "pin birefnet to the other GPU"

My first fix instinct was to move birefnet to GPU 1 so it wouldn't fight Wan on GPU 0.

- **Rejected by the user, and rightly:** *"you can't just go get more memory… if it goes to GPU 1,
  it will just suck up that GPU. this is a huge memory leak. the fix is not to get more memory. the
  fix is to stop the leak."* **Lesson: relocating a leak is not fixing it.** More headroom hides the
  symptom on one axis and reintroduces it the moment that axis fills too.

### The requirements that shaped the real fix

The user then specified the robustness bar directly: *"it should die when the session ends, and
there can only be 1 loaded item, period. if there is one existing one, you need to kill it or wait
until it is done. and if it idle for more than 5 minutes, kill it. I want a robust and good
solution, not just fix one thing and then another hole appears."* Those three clauses map one-to-one
onto the fix below.

---

## 3. Root cause

**onnxruntime's CUDA memory arena never returns memory to the GPU while the session is alive.** It
uses a best-fit arena that *caches* allocations for reuse and grows to a high-water mark — a
fraction of whatever was free when it first ran — then holds that footprint for the session's whole
life.

The old code created **one global birefnet session (`_REMBG`) and kept it forever.** So after the
first cutout, that session sat pinning ~6–15 GB (≈14.6 GB in the incident; the exact figure depends
on how much was free when the arena grew) **for the entire life of the backend process** — across
every subsequent build, whether or not a cutout was running.

The damage then cascaded **outward, several layers from the cause**:

```
onnxruntime CUDA arena never shrinks
   → persistent _REMBG session pins ~14.6 GB on the 24 GB card, permanently
      → the next build's Wan generation can't fit its ~20 GB working set
         → Wan evicts/reloads models every pose loop (thrash)  → 17-min build
         → or, under enough pressure, the cutout itself OOMs   → failed build → blank result card
```

Every visible symptom — slow build, "GPU not used," model thrash, blank card — was a downstream
shadow of one upstream fact: **a session that should have been transient was permanent.**

---

## 4. The fix

Not "more memory" — a **managed, single-instance cutout session with a GPU-bounded lifetime**
(`pet_factory/factory.py`, `class _CutoutSession`, commit `abb054b`). It implements the user's three
requirements exactly:

| Requirement | Mechanism |
|---|---|
| **Only ever one** loaded | One module-level `_CUTOUT = _CutoutSession()`; an `RLock` serialises `get`/`release`/watchdog so a second is never created |
| **Dies when the work ends** | `make_pet_zip` wraps the cutout+pack in `try: … finally: _CUTOUT.release()` — the session is destroyed the instant the build's cutout finishes |
| **Killed if idle > 5 min** | A daemon watchdog thread (`_watch`, `IDLE_TIMEOUT_S = 300`, poll `30 s`) reclaims the session if a `release()` was ever missed (a crash, or a caller using `pack_datsme_bundle` directly) |

The reclaim itself is the crux: **onnxruntime frees the CUDA arena when the session object is
garbage-collected**, so `release()` is simply:

```python
def release(self):
    with self._lock:
        if self._session is not None:
            self._session = None
            gc.collect()          # onnxruntime hands the CUDA arena back on GC
```

`get()` creates the session lazily (with the existing GPU-node fail-fast) and **bumps a
`_last_used` clock on every frame**, so the watchdog can never reclaim a session mid-cutout. `_rembg`
/ `_remove_bg` became thin accessors over `_CUTOUT.get()`, preserving the old fail-fast contract and
its tests.

Why this is the *permanent* fix and not another patch: the leak is closed on **all** its exits at
once — normal completion (`finally`), abnormal exit (idle watchdog), and duplication (lock +
single instance). That is what "not just fix one thing and then another hole appears" required.

---

## 5. Verification (proven, not asserted)

A leak fix that's only reasoned about is a hypothesis. Two proofs:

- **Synthetic before/during/after** (a harness that measures GPU memory around one cutout):
  `before 0 MiB → during cutout 14618 MiB held → after build release() 264 MiB` → **`LEAK_FIXED`**.
  The arena was genuinely handed back, not just dereferenced.
- **A real build:** the fresh all-motion dragon completed in **358 s (~6 min, down from 17+)**, and
  after it the GPU dropped to **784 MiB** with the backend process at **264 MiB** (not 14.6 GB). It
  was faster *and* correct because generation was no longer fighting the leak.
- **Guard tests** pin both guarantees: `test_cutout_session_is_single_instance_and_release_frees_it`
  and `test_cutout_session_idle_watchdog_reclaims_a_missed_release` (full suite green).

---

## 6. Lessons (generalizable)

1. **A performance symptom can be a memory symptom in disguise. Measure the resting state.** 14.6 GB
   pinned on an *idle* GPU was the whole diagnosis, visible from minute one. "Why is it slow" was the
   wrong question; "why is memory never freed" was the right one.
2. **onnxruntime CUDA sessions are a known leak shape.** The arena caches and never shrinks while the
   session lives; a long-lived session sharing a GPU with another large consumer *will* starve it.
   The only reclaim is to **destroy the session (`del` + `gc.collect()`)**. Treat any persistent
   onnxruntime/CUDA session as a resource with an explicit lifetime, never a fire-and-forget global.
3. **Relocating a leak is not fixing it.** "Put it on the other GPU / give it more headroom" hides
   the leak until that resource fills too. Stop the leak at its source.
4. **The most-recently-changed code is a suspect, not the verdict.** Recency bias cost wrong turn #1.
   When evidence contradicts the hypothesis, ask *what must be true for my hypothesis to hold* and
   check *that* — the resting-memory number falsified the ordering theory immediately.
5. **Verify the environment; don't assume it.** Wrong turn #2 invented a staging/pool contention that
   didn't exist. Check the actual box before theorizing about topology.
6. **A leak's damage surfaces layers from its cause.** Arena → starvation → thrash → slow build → OOM
   → failed build → blank UI. When a symptom is far downstream (a blank result card), trace upstream
   before "fixing" the layer you first see it on.
7. **Design the fix to close every hole at once.** Single-instance + release-on-completion + idle
   watchdog wasn't three separate patches; it was the shape that leaves no exit un-plugged. That is
   the difference between a fix and a whack-a-mole.

## 7. Pointers

- Code: `pet_factory/factory.py` — `class _CutoutSession`, `make_pet_zip`'s `finally: _CUTOUT.release()`.
- Tests: `pet_factory/tests/test_gpu_fail_fast_and_progress.py`.
- Related memory notes: `local-petmaker-build-gotchas`, `blank-result-card-is-a-failed-build`.
- The blank-card downstream symptom is written up separately (it was the same root cause seen from
  the UI).
