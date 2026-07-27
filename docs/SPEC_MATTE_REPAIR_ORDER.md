# SPEC — Repair the matte before the geometry: the opaque-black hole fill

**F1 + F2 + F3 ARE BUILT AND THE FIX HOLDS — 2026-07-27, measured on the real defect.**
The decisive A/B was run on the EXACT loop that produced the blob (the Lab's own idle
`.webp`, repacked with the new code — same frames in, so nothing but the repair can account
for the difference):

| | hard-zero | per frame | glaring |
|---|---|---|---|
| before F1 | 157,296 px | 9,831 | 43.7% |
| **after F1** | **53 px** | **3.3** | **2.7%** |

**The 53 are the pet's own ink, not residual damage.** The raw ComfyUI frame contains 32
near-black px of its own (eye pupil, nose), and the repaired sheet carries 3.3 px/frame —
*fewer black pixels than the drawing it came from*. This is §7's warning arriving in
practice: `alpha == 255` identified the fill only because the buggy path left the fill as
the one thing writing an exact 255, and moving the repair onto the matte dissolves that
signature. So the gate cannot be a raw count. `MATTE_DAMAGE_PX_PER_FRAME = 100` sits in
the three-order-of-magnitude gap between the defect (9,831/frame) and a sprite's own ink
(3.3/frame) and needs no tuning; the probe reads the per-frame column and still calls
penguin (7,411), friendlypup (608) and the before-bundle (9,831) damaged while passing the
fixed one and the otter (0).

**F2 was underestimated, in the direction that matters.** On real mattes at 704² the
interpreted BFS costs **444.8 ms/frame**, not the 303.9 estimated in §2.2 — so F1 without
F2 would have been a **57 s** regression on a 128-frame build, not 39 s. `scipy` measures
10.0 ms (est. 8.6) and is **byte-identical on 16/16 real alpha channels**. F1+F2 together
remain cheaper than the shipped order.

**F3 fired on its first real matte**, which is the point of it:
`weak matte on pose 'idle': frame 3 had 56% of its subject as HARD interior holes
(alpha < 20). The repair closed them, so the sprite looks right — the MATTE is what is
weak here.` That frame's matte is genuinely broken; before F3 the repair would have hidden
it perfectly, which is exactly how this defect shipped for months.

**Gate 2 is now GREEN too** (2026-07-27, after the backdrop change): a full 3-pose build of
`white snow leopard` reports `hard-zero 0` on every pose, zero F3 warnings, and `filled`
down from 45.8% to 5.3% — the matte no longer leans on the repair at all. See
`SPEC_MATTE_BACKDROP`, which fixes the *cause* this spec's F1 was compensating for.

**Still open on this spec:** §8 (regenerate the baked bundles + roll the pool fleet), and
§7 gate 4's real-matte equivalence at full scale — the scipy/BFS agreement was verified on
**16/16** real alpha channels from a Lab bundle, not the 128 a full build offers.

**F4 IS BUILT AND THE INSTRUMENT WORKS — 2026-07-27, verified on real GPU.** §6 step 0
(`factory.matte_fill_damage` + `scripts/probe_matte_fill.py`) and F4 (packing as the last
stage of the Lab's animate job) are shipped, with D5's two tiles from
`SPEC_MOTION_LAB_DESIGN_PARITY` §2.5. **`white snow leopard` → `idle` → one press of
Animate reproduces the defect**: the raw tile is a clean pale leopard, the packed tile has
its whole body blacked out, and the line under it reads
`hard-zero 157,296 px · filled 45.8% · glaring 43.7%` — worse than the penguin baseline
(§1), which is what §0.5 predicts for the palest pet in the table.

**The per-pose asymmetry §1 recorded is reproduced too, on the same pet in the same
session:** `walk` came back `hard-zero 625 px · filled 5.7% · glaring 0.5%` — visibly
clean — while `idle` was catastrophic. §1's staging row said the same thing
("idle #24 is 41% of that frame"); it is now a 6-second experiment instead of a
3-minute build, which is the whole point of F4.

Verified alongside it: the eviction ran (GPU 0 fell ~18 GB → 6.9 GB across the pack), the
bundle carries **16 cells from a 17-frame loop** (the duplicated final frame dropped, as
`make_pet_zip` does), it carries the real `breed_id` / `display_name` / `movement_class` /
`runtime_role` / `view`, and `scripts/probe_matte_fill.py` reads the Lab's own `.zip`
unchanged and prints **the same numbers the tile shows** — one instrument, both surfaces.

**F1 had NOT been built when this paragraph was written**, and that was the point: the
ordering in §12.7 is deliberate — a workbench that cannot show the defect while the defect
is still there is not yet an instrument. F4 proved it could, and F1 shipped immediately
after (see the header). Kept in the past tense rather than deleted, because the sequence is
the argument for building the instrument first.


**Status:** proposed, 2026-07-27. **Rev.3 (2026-07-27) — F4 is now a STAGE of the Lab's animate job,
not a `Pack` button (§12.2).** The Lab stopped one stage short of the bundle; the fix is to stop
stopping. `/animate` runs the loop and then packs it, `pack: bool = True` on the body, default ON —
so the Lab replicates production by default and `pack: false` is the bisection lever. This deletes
the standalone endpoint, `_start_local`, the second busy state, the pose-card rung and `Pack all`,
and is *more* faithful than the button was: a build never asks whether to pack. The price is the
eviction tax per pose on a batch (§12.3), taken deliberately. §12.6 gains three tests: the default
holds, a pack failure keeps the loop, and the failing stage is named.

**Rev.2a (2026-07-27) — two corrections to F4 from a review of
the Lab's actual frames:** §12.2 now says to **drop the duplicated final loop frame** as
`make_pet_zip` does (without it every Lab frame index is one off from the probe's), and §12.1
records that the Lab draws anchors from the *base* still template while every app build uses the
*remix* one — a paler frame, biased toward the very defect F4 measures. That fix is
`SPEC_MOTION_LAB_DESIGN_PARITY` §2.6 and it now precedes F4 in the build order (§12.7).

**Rev.2 — F4 (the Motion Lab pack toggle, §12) is new, and it is
step 1 of the build order.** The Lab was the obvious place to reproduce this and it structurally
cannot: it stops one stage short of the packer, where the whole defect lives (§12.1). Rev.2 also
passed an implementation-readiness review, which added the exact code shape (§2.4), the per-pose
log cap (§2.3), the generated-not-committed fixture decision (§5), a checked-correct note on
`_prep_reference_image` (§3.5), how to read the probe *after* the fix (§7), and §13 rollback.

**Rev.1** — written from a live defect on staging (a `white snow leopard` build under a
DatsMe-launched user, job `d401be570e91`), then measured against six shipped bundles before any
code was designed. Every number below is a measurement taken on this box, not an estimate. §10 is
the **attempt log** — append to it as this iterates; that is the part of this document that earns
its keep if the first fix does not land clean.

**The one-line diagnosis:** `_fill_holes_alpha` is a **matte-repair** step that runs inside the
**geometry** step, one line *after* the resample that has already destroyed the colour it needed
to preserve. It repaints the animal's own body pure black at full opacity.

**Amends:** nothing. **Depends on:** nothing new — no model, no key, no host change, no bundle
contract change. **Reactivates a closed dead end** in `docs/archive/SPEC_GPU_MEMORY_HYGIENE.md`
§10 — see §4.3, which is the one place this spec argues with a previous measurement.

**Repos touched:** `datsme-pet-factory_wu` only — F1–F3 are `pet_factory/factory.py`, its tests and
one probe script; **F4 additionally touches `webui/motion_lab.py` and the Lab page under `web/`**
(admin-gated, §12.5). The GPU-less prod web tier never reaches the packer
(`PET_GEN_BACKEND=pool`), so prod behaviour is unchanged by construction. Pool worker nodes run
this code and must be rolled (§8).

**Code is cited by symbol, never by line number** — the Rev.2 lesson from
`SPEC_GPU_MEMORY_HYGIENE`: every line citation in that spec's Rev.1 had drifted ~5 lines.

---

## 0. Three facts that decide the whole design

All three verified before the fix was designed.

### 0.1 Opaque pure black is arithmetically impossible from a matte

A matte writes **alpha only**. The shipped snow leopard sheet contains 240,889 pixels at
`RGB(0,0,0)` with `alpha=255`. Something painted them; birefnet cannot have.

The sheet carries a clean fingerprint of *what* painted them:

| population | count (frame 24) | meaning |
|---|---|---|
| `alpha == 254` | 13,798 | genuine birefnet foreground (see 0.2 — the self-masked paste squares 255 → 254) |
| `alpha == 255` **exactly** | 10,365 | `_fill_holes_alpha`'s `a[holes] = 255`, and nothing else |
| of those, `max(RGB) < 45` | 9,103 | **the defect** |
| of those, border-unreachable | 9,103 / 9,103 = **100%** | exactly the `holes` set the fill computes |

Semi-transparent pixels independently confirm the mechanism — their colour tracks
`fur × alpha/255`, which is what compositing against a transparent-**black** canvas produces:

| pre-fill alpha | 1–40 | 40–80 | 80–120 | 120–160 | 160–200 | 200–240 |
|---|---|---|---|---|---|---|
| measured mean RGB | 8 | 23 | 69 | 102 | 124 | 156 |
| `245 × alpha/255` | 18 | 54 | 90 | 126 | 162 | 198 |

### 0.2 Every resample filter except NEAREST premultiplies — and Pillow never un-premultiplies

This is the fact that kills the obvious fix. `RGB=200, alpha=0` through `Image.resize`:

| NEAREST | BOX | BILINEAR | HAMMING | BICUBIC | LANCZOS |
|---|---|---|---|---|---|
| `[200,200,200]` | `[0,0,0]` | `[0,0,0]` | `[0,0,0]` | `[0,0,0]` | `[0,0,0]` |

So **colour under a zero matte is unrecoverable after any usable resample** — `_fit_square`'s
LANCZOS annihilates it, and un-premultiplying cannot bring it back (it is a divide by zero).
The same premultiply is why genuine foreground reads 243/254 where the source is 245/255: the
sheet ships *premultiplied* while the host composites it as straight alpha. That second defect
is real but **out of scope** — §3.1.

**Corollary, and the whole design in one sentence:** the repair must happen **before any
resample**, while the colour still exists.

### 0.3 The root cause is placement, not arithmetic

`pack_datsme_bundle.prep()` runs, per frame:

```python
a = _remove_bg(orig)...split()[3]                  # matte stage    — colour intact
result = orig.convert("RGBA"); result.putalpha(a)
cell = _fit_square(result, frame_size)             # geometry stage — colour destroyed here
cell.putalpha(_fill_holes_alpha(cell.split()[3]))  # matte repair, one stage too late
```

`_fill_holes_alpha` is a **matte-repair** operation: its own docstring says it "closes any hole
the matting model punches inside the animal". It belongs beside the matte it repairs, at the
matte's resolution. It was placed in the geometry stage, downstream of the step that eats its
input. *Things that change for the same reason live together* — the fill and the matte change for
the same reason (the matting model), and `_fit_square` changes for a different one (sheet
layout). The bug is that boundary being drawn in the wrong place.

### 0.4 The defect is original — the GPU-memory work is not implicated

Asked directly, because the timing invites it: the cutout was reworked hard on 2026-07-25/26
(`abb054b` managed session, `3f112f5` memory hygiene F1–F5). It did not cause this.

| evidence | finding |
|---|---|
| `git blame` on `_fit_square`, `_fill_holes_alpha`, **and the call-site ordering** | every line is `^7b5eeb1`, **2026-07-05** — the first `pet_factory` commit, never modified since |
| `friendlypup.zip`, committed `b64dc3c` **2026-07-13** | already damaged (40,673 hard-zero px) — **12 days before** the memory work |
| the cutout model across all history | **always** `birefnet-general-lite`; the VRAM reduction did not swap in a lighter matte model |
| what F1–F5 actually changed | ORT arena *bounds*, session *lifetime*, ComfyUI eviction, logging — allocation and lifecycle, none of which touch birefnet's output values |

The memory work's one change to the pixel path went the **opposite** way: F2 made a *raising*
cutout fail the build instead of silently shipping an opaque alpha. That is a different failure
(a white-background pet, not black blobs) and it is now loud. Do not conflate the two.

One honest footnote: `SPEC_GPU_MEMORY_HYGIENE` §10 *measured* `_fill_holes_alpha` and closed it as
"inside the noise" — so this work looked straight at the function and passed over the ordering
defect, because it was asking about speed. That is a near-miss, not a cause.

### 0.5 The trigger is the prompt, not the hardware

`prompt_templates.py` puts **`white background`** in both still templates (`base_still_prompt`,
and the pastel variant). So a white animal is rendered *on white* by construction, and birefnet is
handed a matte problem with almost no contrast — it confidently classifies the pale body as
background. This is why the damage tracks **pale regions** (§1.1), and why `white snow leopard`
is close to the worst case the pipeline can be asked for: white-on-white, requested by name.

---

## 1. The damage, measured across every bundle on the box

`filled` = subject pixels the fill made opaque. `hard-zero` = of those, the ones whose pre-fill
alpha was ≈0, so their colour was fully annihilated. `glaring` = subject fraction that lost >60%
of its true brightness.

| bundle | filled | hard-zero | glaring | what is visibly wrong |
|---|---|---|---|---|
| **penguin** (`created_pets/`) | 43% | 237,343 px | **41%** | **entire face + belly** black; only the back/wing survived |
| **white snow leopard** (staging, 2026-07-27) | 12.4% | 209,079 px | **10.3%** | hindquarters, tail, back leg; idle #24 is **41%** of that frame |
| **friendlypup** (`animal_catalog/_candidates/dog/samples/`) | 8.7% | 40,673 px | **7.5%** | chest blaze, rear leg |
| red panda | 6.0% | 1,679 px | 1.2% | small specks |
| otter | **23.0%** | **0 px** | 0.7% | nothing visible |
| cardinal | 16.1% | 4 px | 0.1% | nothing visible |

### 1.1 It is a pale-**region** bug, not a white-**animal** bug

The otter had *23% of its subject hole-filled* and shipped clean. Hole-filling is routine and
almost always harmless, because most holes are **soft** (pre-fill alpha ≥ 120 — matte edge
softness), and a soft hole only dims its colour slightly. Damage needs a **hard-zero** hole, and
its severity is then the true pixel's brightness. Pale regions are what break, and nearly every
animal has them: the penguin's belly, the corgi's chest blaze, the snow leopard's whole body.
And per §0.5 the pipeline *asks* for white-on-white, so a pale region is a matte problem the
prompt created.

### 1.2 Why it hid for so long

The penguin — the worst-damaged bundle on the box — still reads as *a penguin*, because a
blacked-out belly on a black-and-white bird looks like a stylistic choice. The failure is
**camouflaged in proportion to how dark the animal is**, so the bundles most likely to be noticed
are the ones least likely to be damaged. `pet_factory/tests/test_cutout_hygiene.py` has 21 guard
tests covering session setup, GPU fail-fast and failure semantics, and **not one assertion about
a resulting pixel**, which is why the gate stayed green.

---

## 2. The fix

Four changes. F1 is the defect; F2 keeps F1 from costing 39 s a build; F3 is the loud signal that
should have existed; **F4 (§12) is the instrument that makes iterating on F1 cost 6 s instead of
3 minutes** — it is separate because it is a Lab surface, not a packer change.

### 2.1 F1 — move the repair into the matte stage *(the fix)*

Fill on the birefnet matte, at matte resolution, before `_fit_square`:

```python
a = _fill_holes_alpha(a)                           # matte repair, colour still intact
result = orig.convert("RGBA"); result.putalpha(a)
cell = _fit_square(result, frame_size)             # geometry only — no putalpha after it
```

Measured on the reproduction (704² frame, hard-zero interior hole, pale fur + a tan flank):

| | hole RGB | hole alpha | body RGB | body alpha |
|---|---|---|---|---|
| shipped order | `[0,0,0]` | 255 | 243 | 253 |
| **F1** | **`[245,244,243]`** ✓ | 255 | 243 | 253 |

The true colour comes back, and **non-hole pixels are byte-identical** (243/253 both ways) —
F1 does not touch the resample or the paste, so edges, silhouette, alpha values and sheet layout
are unchanged. The fallback branch (`a = Image.new("L", …, 255)` on a dead cutout session) is
unaffected: an all-opaque matte has no holes, so the fill is a no-op there.

We are explicitly **not** preserving colour under *real* background — `_fit_square` may go on
annihilating that. It is invisible and it keeps the PNG compressible.

### 2.2 F2 — vectorize the fill, because F1 changes the resolution it runs at

`_fill_holes_alpha` is an interpreted BFS. Moving it from 256² to 704² is 7.6× the pixels:

| | per frame | per 128-frame build |
|---|---|---|
| BFS @ 256² (today) | 21.4 ms | 2.74 s |
| BFS @ 704² (F1 without F2) | **303.9 ms** (real mattes, 278–338 range) | **38.9 s** |
| `scipy.ndimage.binary_fill_holes` @ 704² | **8.6 ms** | **1.10 s** |

So F1+F2 together are **cheaper than today** (1.10 s vs 2.74 s), and F1 alone would add ~39 s to
a ~3 min build — the whole cutout+pack band is 46.7 s, 0.365 s/frame end-to-end
(`SPEC_GPU_MEMORY_HYGIENE` §9 B2c, restated in §10), which a 304 ms fill nearly doubles.
**F2 is not optional.**

Equivalence is verified, not assumed: the scipy form produced **byte-identical output on
128/128** real alpha channels from the shipped snow leopard sheet. `scipy` is already a
transitive dependency of `rembg`, which `factory.py` requires — no new dependency, and it stays
inside `factory.py`, behind the lazy `pet_factory.__init__` PEP-562 boundary, so the GPU-less
posture is untouched (`import numpy` must still fail on the web tier).

### 2.3 F3 — make a large matte miss loud

Post-F1 a hard-zero hole is cosmetically repaired, which means a matte that drops 36% of a frame
becomes *invisible*. That is how this shipped in the first place. Log at WARNING, naming the pose
and frame, when the hard-zero fraction of a frame's subject exceeds a threshold. This is a
**quality signal, not a failure** — it must never fail the build.

Thresholds are named constants, never literals, and live beside the existing cutout constants
band in `factory.py`:

| constant | value | why |
|---|---|---|
| `_MATTE_HOLE_ALPHA_THR` | 160 | today's `_fill_holes_alpha(thr=)` default, promoted to the band and referenced as the signature default so there is one value |
| `_MATTE_HARD_HOLE_ALPHA` | 20 | below this, colour was fully premultiplied away — a *confident* matte miss, not edge softness |
| `_MATTE_HARD_HOLE_WARN_FRACTION` | 0.10 | idle #24 is 0.36 and trips; the otter's 23% of soft fill is 0.0 and stays quiet |

**One WARNING per pose, not per frame.** `prep()` already runs once per pose: accumulate the worst
frame over its loop and emit a single line naming the pose, the worst frame index and its fraction.
A fully-broken matte otherwise emits 128 WARNING lines and buries the signal it exists to give.
Poses that do not trip say nothing at all.

### 2.4 The code shape *(so two implementers produce the same thing)*

```python
# factory.py — beside the existing cutout constants band
@dataclass(frozen=True)
class _MatteRepair:
    alpha: Image.Image      # the repaired matte
    subject_px: int         # opaque subject pixels after the repair
    filled_px: int          # holes closed
    hard_px: int            # of those, pre-fill alpha < _MATTE_HARD_HOLE_ALPHA

def _repair_matte_holes(alpha: Image.Image) -> _MatteRepair:      # SHIPPED — scipy (F2)
def _fill_holes_alpha(alpha, thr=_MATTE_HOLE_ALPHA_THR) -> Image: # the ORACLE — today's body, untouched
```

`factory.py` imports neither `dataclass` nor `NamedTuple` today, so `from dataclasses import
dataclass` is a new (stdlib, GPU-less-irrelevant) import at its top.

Two deliberate naming decisions:

- **The new shipped function gets the honest name** (`_repair_matte_holes` — it is matte repair,
  §0.3) and returns the stats F3 and F4 need. Returning a struct rather than an `Image` is safe:
  the call site is the only caller.
- **`_fill_holes_alpha` keeps its name, signature and body**, because
  `SPEC_GPU_MEMORY_HYGIENE` §9 and §10 cite it and those citations should stay resolvable — and it
  is the test oracle (§9.3). It is not an alias and not dead code: test #4 is its consumer.

---

## 3. What this deliberately does not fix

### 3.1 The sheet ships premultiplied *(known, separate, recorded so it is not lost)*
Body pixels read RGB 243 / alpha 253 where the source is 245 / 255 (§0.2), so every edge is
double-darkened by a host that composites straight alpha. The fix is to resize the bands
independently (verified working: body 245/254 and the hole also restored) — but it alters **every
edge pixel of every frame**, which needs its own visual A/B and its own revision. Keeping it out
of F1 is what makes F1's "non-hole pixels are byte-identical" claim true and cheap to verify.

### 3.2 The matte quality itself
birefnet still drops large pale regions; F1 makes the drop *invisible* rather than *black*. F3 is
the compensating signal. The real fix is upstream and is **not** a matte-model swap: stop
generating pale animals on a white background (§0.5). Rendering the still on a contrasting
background would give birefnet the contrast it needs — but it changes the look of every still, the
step-2 design preview, and the `_remix_prompt` path, so it is its own spec with its own A/B.
Recorded here so the cosmetic fix does not close the question.

### 3.3 Enclosed-background false positives
The fill makes **any** border-unreachable transparent region opaque — including a genuinely
enclosed gap (between legs, inside a curled tail). Post-F1 that region fills with background
colour instead of black. Both are wrong; neither is new (the fill already fired there); and
background-coloured is far less jarring than black. Not a regression, and not addressed.

### 3.4 Holes that touch the frame border
Still left transparent, correctly — that is real background. None of the snow leopard's damage
was border-connected (100% interior, §0.1), so this is not the current failure mode.

### 3.5 `_prep_reference_image`'s self-masked paste is correct — leave it
It uses the same `canvas.paste(img, box, img)` shape as `_fit_square`, which makes it look like a
second instance of this bug. It is not: its canvas is **opaque white** (a deliberate flatten for the
Wan I2V stage) and it **pads without resampling**, so nothing is premultiplied away. Checked, so
that a sweep for the pattern does not "fix" a working function. The `sheet.paste(fr, …, fr)` in the
packer is likewise harmless *after F1* — by then the repaired cells carry `alpha=255` over intact
colour, so the sheet composite has nothing left to destroy.

---

## 4. Measured dead ends — do not retry

### 4.1 "Just paste without the self-mask" — **rejected, tested**
`_fit_square`'s `cell.paste(img, box, img)` looks like the culprit. Removing the mask leaves the
hole at **`RGB=[3,3,3]`** — still black. The colour is already gone by then; LANCZOS ate it
(§0.2). This was the author's own first proposal and it is wrong.

### 4.2 "Use a different resample filter" — **rejected, tested**
Every filter premultiplies except NEAREST (§0.2 table), and NEAREST is unusable for a 704→256
sprite downscale.

### 4.3 "`_fill_holes_alpha` does not need vectorizing" — **true then, false now**
`SPEC_GPU_MEMORY_HYGIENE` §10 closed this on data: at 256², inside a 0.365 s/frame cutout+pack,
the interpreted flood fill is noise. That measurement stands and is not being overturned. F1
changes its *input resolution* to 704², where the same code costs 303.9 ms/frame. The dead end
was answered for the shipped call site; F1 creates a different one. **Do not read §10 as blocking
F2** — and if F1 is ever reverted, F2's justification reverts with it.

### 4.4 "Filter out black pixels" — **rejected by inspection**
The cartoon style has genuinely black lineart, eyes and noses; that is the 360 px floor on the
clean `walk` pose. Any rule keyed on pixel darkness eats the artwork.

---

## 5. Guard tests

In `pet_factory/tests/test_cutout_hygiene.py` (the existing home for cutout behaviour). Each must
be **red-green verified** — confirmed failing against the shipped order before F1 lands.

1. `test_a_filled_hole_keeps_the_animals_colour` — synthetic pale frame, hard-zero interior hole;
   assert the filled region is the fur colour, not black. **This is the regression test.**
2. `test_no_opaque_pixel_is_black_that_the_matte_cannot_explain` — no `alpha>200 & max(RGB)<45`
   pixel outside a region the input frame drew dark.
3. `test_the_matte_is_repaired_before_any_resample` — structural: monkeypatch `_fit_square` to
   capture its input and assert that alpha has no border-unreachable transparent region, so the
   ordering cannot silently regress.
4. `test_the_vectorized_fill_matches_the_reference_bfs` — `_repair_matte_holes` vs
   `_fill_holes_alpha` byte-identical, including border-connected transparency staying transparent.

**Fixtures are generated, not committed.** Build the matte set in-test from a seeded
`numpy.random.default_rng` plus a few hand-drawn shapes (hard hole, soft hole, border-connected
bite, donut). Two reasons this is not laziness: committing binaries into `pet_factory/tests` has no
precedent, and the obvious real-data fixture — `friendlypup.zip` — **is scheduled for regeneration
in §8**, so a test keyed to it would change inputs the moment the fix ships. The real-matte
equivalence run (128/128, §2.2) belongs in the §7 gate, against a bundle, where it can be re-run
rather than frozen.
5. `test_non_hole_pixels_are_unchanged_by_the_repair_move` — pins §2.1's byte-identical claim.
6. `test_the_hard_hole_warning_names_the_pose_and_frame` — and that it is WARNING, not an error,
   and never fails the build (`caplog`, per the F5 logging lesson).
7. `test_the_matte_thresholds_are_named_constants` — no literal 160 / 20 / 0.10 at a call site.
8. `test_an_opaque_fallback_matte_is_a_no_op_for_the_repair` — the dead-session branch.

---

## 6. Build order

F2 lands with F1 in one change (F1 alone is a 39 s regression, §2.2). F3 may follow, but before
the acceptance gate — its warning is one of the signals the gate reads.

0. **The damage-metric function in `pet_factory/factory.py`, then `scripts/probe_matte_fill.py` as
   its first caller** — the instrument, before the fix it measures. It must report today's damage on
   the §7 baselines before it is trusted to report zero. **The function, not just the script**: F4
   imports the same function through `_pf()` (§12.4), and metrics written inside `scripts/` are
   unreachable from `webui` — that is test 8 failing after all the code is done.
1. **F4, packing as a stage of the Lab's animate (§12)** — the 6 s iteration loop, before spending
   3 min a try. Skippable only if you are confident F1 lands first time; §10 assumes otherwise.
2. Promote the thresholds to named constants; add `_repair_matte_holes` (§2.4) beside
   `_fill_holes_alpha`, which stays as the oracle.
3. Move the repair into the matte stage; delete the post-`_fit_square` `putalpha`. **Delete, not
   comment out** — no dual path.
4. Tests 1–8, each red first.
5. F3's warning (one per pose, §2.3).

---

## 7. Acceptance gate

A status code is not a pass; three things are.

1. **The suite:** `.venv/bin/python -m pytest pet_factory/tests webui/tests` green, with tests
   1–8 (and §12.6's 1–5 if F4 landed) present and each verified red first.
2. **A real build of the exact failing case** — `./make_pet.sh "white snow leopard"`, not a
   generic snow leopard: §0.5 says white-on-white is the trigger, so the pale case is the test.
   A synthetic matte cannot prove birefnet's real hole shapes are handled, and this is the step
   most likely to surface a second-order problem.
   **Run it with the UI idle.** A CLI build bypasses `GPU_LOCK` (it is process-local), so it can
   collide with a backend cutout and OOM — which post-F2 fails the build and would read as a
   regression in the fix. A stray ComfyUI over-subscribing the card does the same.
3. **`scripts/probe_matte_fill.py <bundle.zip>`** reports **0 hard-zero black fill** and prints the
   §1 per-pose table for the new bundle. It must also still report the *old* bundles as damaged —
   a probe that passes everything is broken. Baselines already measured:
   `white_snow_leopard.zip` (10.3% glaring) and `created_pets/penguin_dualnvidia_test.zip` (41%).
4. **The real-matte equivalence run** (§5, moved out of the unit tests): `_repair_matte_holes` vs
   `_fill_holes_alpha` byte-identical across every alpha channel of a real bundle. It was 128/128
   when this spec was written; re-run it rather than trusting that number.

**Reading the probe after the fix.** Its damage metrics (`filled`, `hard-zero`, `glaring`) stay
valid before and after F1 — but the *inference* behind `alpha == 255 means hole-filled` is a
property of the **buggy** path only (§0.1: the self-masked paste squares genuine foreground to
254). Post-F1 that separation is gone, which is why the gate is stated as **damage = 0**, not as a
fill count. Do not read a post-fix `0` as "the fill stopped running" — F3's per-pose line is what
tells you it still does.

---

## 8. Already-baked bundles

The damage is baked into shipped bytes; no code change repairs an existing `.zip`. Regenerate
after the gate passes:

- `pet_factory/animal_catalog/_candidates/dog/samples/friendlypup.zip` — **ships with the repo**
  as curated catalog content, 7.5% glaring. The highest priority.
- `created_pets/penguin_dualnvidia_test.zip` — worst measured (41%); gitignored, so regenerate or
  delete.
- The staging `white_snow_leopard` pet (job `d401be570e91`) — a user-visible draft.
- **Pool worker nodes carry this code** (`pool-install-handler`): both pet nodes need a roll
  (`scripts/roll_pet_fleet.sh --verify-build`) or every pool-built pet keeps the defect.

---

## 9. Decisions

1. **Repair at matte resolution, not sheet resolution.** The alternative (band-independent
   resize, §3.1) also works and fixes more, but changes every edge pixel. Minimal, provable,
   reversible wins for the defect fix.
2. **F2 ships with F1, not after.** A correct fix that costs 39 s a build gets reverted for
   speed and then nobody re-lands the correctness.
3. **Keep the BFS in the tree as the test oracle.** Two implementations of one function is
   normally a smell; here the interpreted one is the readable definition of intent and the
   equivalence test is what licenses the fast one. Delete it only if it stops being the oracle.
4. **F3 warns, never fails.** A matte miss is a quality signal; failing the build on it would
   turn a cosmetic issue into an outage for the animals that need the repair most.
5. **F4 calls the shipped packer or it is worthless.** An instrument that runs its own copy of the
   stage measures the copy. This is the one non-negotiable constraint on §12.
6. **Build the instrument before the fix** (§6 steps 0–1). Both were written *after* the diagnosis
   here was done by hand, which is exactly the cost they exist to remove next time.

---

## 10. Attempt log — append as this iterates

The point of this section: nobody re-runs a rejected approach, and a half-landed attempt leaves a
record. One row per attempt, newest last. Record the *measurement*, not the intent.

| # | date | attempt | measured result | verdict |
|---|---|---|---|---|
| A1 | 2026-07-27 | F1+F2+F3, A/B'd on the exact loop that produced the blob | hard-zero **157,296 → 53** px (9,831 → 3.3 per frame), glaring 43.7% → 2.7%; the 53 are the sprite's own eye/nose ink, and the raw ComfyUI frame contains 32 near-black px of its own — the repaired sheet is BLACKER NOWHERE than the drawing | the fix holds. The gate had to move from a raw count to px/frame, because §7's "alpha==255 means fill" inference dissolves with the fix — `MATTE_DAMAGE_PX_PER_FRAME = 100`, in the 3-orders gap |
| A3 | 2026-07-27 | §11 Q4: does a contrasting backdrop fix the matte? And which stage actually fails? | The Z-Image **still** mattes perfectly on white. The **Wan loop frame** does not — it drops the tucked paws, open to the background so no fill can close it. Redrawn on `flat slate grey background`: clean silhouette, **fill added 0 px**. Two earlier offline attempts were CONFOUNDED — repainting a frame's background changes birefnet's output independently of colour (193k px kept untouched vs 68k repainted-white), so only a real re-render answers this | the lever is real but it lives in `prompt_templates`, which redraws the whole catalog — §3.2's decision, not this spec's |
| A2 | 2026-07-27 | Is §2.2's 303.9 ms BFS estimate right on real mattes? | **No — 444.8 ms/frame** at 704². F1 alone would have been a 57 s regression, not 39 s. scipy: 10.0 ms, byte-identical on 16/16 real alpha channels | F2 was even less optional than the spec said |
| A1 | 2026-07-27 | Read the sheet: is the damage real and where? | 240,889 px `RGB(0,0,0)/alpha=255`; 100% border-unreachable; `alpha==255` is the fill's fingerprint | defect confirmed, mechanism located |
| A2 | 2026-07-27 | `_fit_square`: paste without the self-mask | hole `RGB=[3,3,3]` — still black | **rejected** → §4.1 |
| A3 | 2026-07-27 | Probe where colour actually dies | `RGB=200/alpha=0` → LANCZOS → `[0,0,0,0]`; NEAREST preserves | root cause: the resample premultiplies (§0.2) |
| A4 | 2026-07-27 | Fill the full-res matte before `_fit_square` | hole `[245,244,243]`; non-hole pixels byte-identical | **adopted** as F1 |
| A5 | 2026-07-27 | Band-independent resize | fixes the hole *and* the premultiply (body 245/254) | deferred → §3.1 |
| A6 | 2026-07-27 | Cost of F1's resolution change | BFS 21.4 ms @256² → 303.9 ms @704² = +38.9 s/build | F2 required → §2.2 |
| A7 | 2026-07-27 | `scipy.ndimage.binary_fill_holes` equivalence + cost | identical on 128/128 real mattes; 8.6 ms/frame (1.10 s/build) | **adopted** as F2 |
| A8 | 2026-07-27 | Survey six shipped bundles | penguin 41% glaring, snow leopard 10.3%, pup 7.5%, otter 0 hard holes | scope: pale *regions*, not pale animals (§1.1) |
| A9 | 2026-07-27 | Did the 2026-07-25/26 GPU-memory work cause it? | blame is `^7b5eeb1` 2026-07-05 on all three lines; `friendlypup.zip` damaged and committed 2026-07-13; model always `birefnet-general-lite` | **not implicated** → §0.4 |
| A10 | 2026-07-27 | Then why do pale animals fail? | both still templates prompt `white background` | trigger is the prompt (§0.5); upstream fix deferred → §3.2 |
| A11 | 2026-07-27 | Reproduce it in the Motion Lab | `motion_lab.py` has **zero** references to `_remove_bg` / `_fit_square` / `_fill_holes_alpha` / `pack_datsme_bundle`; `/still` and `/animate` return raw ComfyUI output | Lab **structurally cannot** repro; the missing design section is not the reason → F4, §12 |

**Iteration rules.** A rejected approach moves to §4 with its measurement. A partial landing gets
a row here *and* a `[Rev.N]` note in the header. If the §7 real-build step contradicts anything in
§0, stop and fix §0 first — the whole design hangs off those three facts.

---

## 11. Open questions

1. **Do birefnet's real hole shapes ever enclose true background at the fill threshold?** §3.3 is
   reasoned, not measured. The §7 real build is the first chance to look; if it happens, the
   answer is probably a size cap on what a single fill may close, not a threshold change.
2. **Is `_MATTE_HOLE_ALPHA_THR = 160` still right at matte resolution?** It was chosen against
   256² cells. A 704² matte has a proportionally thinner edge band, so the same threshold may
   sweep in slightly less. Measure on the real build before touching it.
3. **How often does F3 fire across the catalog?** If a large fraction of ordinary builds trip
   0.10, the threshold is wrong or the matte is worse than anyone thought — either is worth
   knowing, and it is the input to the §3.2 matte-quality spec.
4. **ANSWERED, 2026-07-27 — yes, and the failing stage is not the one this spec assumed.**
   Run after F1, so the two effects stayed separable. Three findings, in order of how much
   they change the picture:

   **(a) The Z-Image STILL mattes perfectly on white.** A clean, complete silhouette, no
   holes. So "white-on-white breaks birefnet" is wrong *at the still stage*, and §0.5's
   reading of the trigger needs qualifying.

   **(b) The WAN FRAME does not.** What gets packed is never the still — it is the I2V loop
   output, which at 4 steps is softer and lower-contrast. On the same pet, same seed, same
   clause: the Wan frame's matte drops the tucked front paws and lower chest, and because
   that region is open to the background no fill can close it (the repair added 758 px and
   the hole survived). This is the "transparent bite" an operator sees post-F1, and it was
   there before F1 too — the opaque black was covering it.

   **(c) A contrasting backdrop removes it entirely.** Same pet, `white background` →
   `flat slate grey background` in the template:

   | Wan frame drawn on | matte | after fill | result |
   |---|---|---|---|
   | white (today) | 257,936 px | 258,694 | bite out of the bottom |
   | slate grey | 151,612 px | 151,612 | clean silhouette, **fill added 0 px** |

   **What this does NOT settle**, and why it is not being changed here: the backdrop is in
   `prompt_templates`, which every pet in the catalog is drawn through, and swapping it
   visibly changed the drawing itself (the leopard came out smaller and differently posed).
   So it is a content decision with catalog-wide reach — curated `base.png` files would no
   longer match their own template — not a bug fix. A single fixed colour also only moves
   the problem: a grey pet on a grey backdrop is the same ambiguity. The principled options
   are a saturated colour no pet uses (green-screen logic, needs a bleed check) or a
   per-pet backdrop resolved like `base_pose` already is. Both belong in the §3.2 matte-
   quality spec, with this measurement as their premise.

---

## 12. F4 — the Motion Lab packs what it animates *(the repro instrument)*

### 12.1 Why it exists

The Lab covers **still → loop** and stops one stage short of the bundle. This defect lives
*entirely* in that missing stage, so **the Lab cannot reproduce it** — verified: `motion_lab.py`
contains no reference to `_remove_bg`, `_fit_square`, `_fill_holes_alpha` or
`pack_datsme_bundle`. `/still` returns a raw PNG (`_static_image_wf` / `_img2img_wf`) and
`/animate` a raw webp (`_loop_wf`), both with the white background still on them. The designer's
`/api/preview` → `render_design_still` has no cutout either.

**Consequence, recorded because it was the first hypothesis and it is wrong:** the Lab's missing
"Design your pet" section is *not* why the defect will not reproduce there. A full build is the
only thing in the app that runs the packer. Adding every design control would change nothing.

**But one Lab-side prompt difference does matter, and it is not a design control.** The Lab draws
pose anchors with `_base_prompt` when no reference is loaded, while every app build draws them with
`_remix_prompt` (`reference_image` is never `None` in the web tier — `/api/generate` requires a
`reference_id`). The base template says `soft pastel colors, muted palette`; the remix template says
`rich saturated colors`. So the Lab's default frames are **paler than production's**, and pale-on-
white is the input condition for the interior holes this spec is about — F4 would overstate the
defect it is built to measure. The fix is `SPEC_MOTION_LAB_DESIGN_PARITY` **§2.6 (D6)**, one line,
and it should land **before** F4 rather than with the rest of that spec.

F4 closes the gap by **removing the stop**: `/animate` runs the loop and then runs the shipped
packer on it, the way `make_pet_zip` runs Phase B and then packs. 16–17 frames × 0.365 s ≈ **6 s per
pose**, against a ~3 min build — that is the iteration loop §10 assumes this work will need.

**Rev.3 note — why this is a stage and not a `Pack` button.** The first shape was a standalone
`POST /pack` with its own runner, its own busy state, its own rung and its own batch row. All of
that was machinery for making the Lab stop and then un-stop by hand. Making the pack the last stage
of the animate job deletes every piece of it and is *more* faithful, not less: a build never asks
whether to pack. What survives the collapse is what was load-bearing all along — the eviction, the
lock, one shared metric function, and the dropped final frame.

### 12.2 Shape — a STAGE of the animate job, not a second action

**Rev.3 replaced the standalone `POST /pack` endpoint with this.** The Lab stopped one stage short
of the bundle; the fix is to *stop stopping*, not to add a second button that finishes the job by
hand. `/animate` runs the loop and then packs it, exactly as `make_pet_zip` runs Phase B and then
packs. Nothing about the Lab's job model changes.

```
AnimateBody: ..., pack: bool = True     # the whole API surface of this feature
```

- **No new endpoint, no `_start_local`, no second busy state, no `Pack all`.** The pack is a stage
  inside the existing `_run_job` thread, after `_submit_and_wait` returns the loop. Everything that
  made the standalone shape big — a sibling runner, a per-pose rung, a batch row, a
  disabled-until-animated gate — is deleted by this, not implemented.
- **Default ON.** The Lab's job is to show what production does, and production packs. `pack: false`
  is the **bisection lever**: rerun the same pose with the pack off and the loop is all you get.
  Since §12.4 shows the raw loop and the packed sheet *together* on every packed run, the toggle is
  not how you attribute a defect to the packer — it is how you skip the eviction tax on a batch
  (§12.3), and how you still get a loop when the packer is the thing that is broken.
- **Two result slots, and the loop is reported FIRST.** The loop costs ~40 s of GPU; a pack failure,
  a busy `GPU_LOCK` or a `CutoutFailed` must never discard it. `_update_job` publishes the loop
  asset and `phase="packing"` as soon as Phase B lands, then adds `packed_asset_id` /
  `packed_url` / `metrics` when the pack finishes. A pack that fails sets `pack_error` and leaves
  `state="done"` — the job produced a loop, which is a real result.
- **Errors name their stage.** `pack_error` is a distinct field from `error` precisely so the answer
  to "which step caused it" is read off the record instead of inferred. That is the whole point of
  the instrument.
- Frames come from **`pf._frames_rgba(path)`** — the factory's existing webp/gif/video decoder.
  Do not write a second decoder.
- **Drop the duplicated final loop frame**, exactly as `make_pet_zip` does
  (`if len(frames) > 1: frames = frames[:-1]`). A Wan loop's last frame repeats its first; the build
  discards it before packing, so keeping it here puts one extra cell on the sheet and shifts **every
  frame index after it**. It does not hide the defect — the duplicate gets the same treatment as any
  other frame — but it makes a Lab frame number and a probe frame number refer to different pictures,
  which is the disagreement §12.4 exists to forbid. Two lines apart in `make_pet_zip`'s caller and
  easy to read past; call it out rather than rediscover it from an off-by-one in the metrics.
- It must call the shipped **`pack_datsme_bundle`**, never a copy. A Lab that re-implements the
  stage stops being evidence about the build. The Lab is a *surface*, not a second engine.
- `pose_frames={pose_name: frames}` is a legal one-pose bundle; the packer needs no change. **This
  is faithful, not an approximation:** `prep()` is entirely per-frame — `_remove_bg` per frame,
  `_fit_square` scaling from that frame's own size, `_fill_holes_alpha` flooding from that cell's own
  border — with no cross-pose or cross-frame state anywhere. A one-pose pack produces **byte-identical
  cells** to the same pose inside an eight-pose build. Only the manifest differs (frame indices, row
  bands), and the defect does not live in the manifest.
- **Pass what `make_pet_zip` passes.** `pack_datsme_bundle` also takes `breed_id`, `display_name`,
  `pose_meta`, `movement_class` and `view`; the packed sheet is rendered through `PosePlayer`, which
  reads fps/frames/columns out of the manifest they produce. Use `pf._slug(animal)`, `animal.title()`,
  and the loaded profile's `movement_class` / `view` / per-pose meta — the same values, from the same
  profile the loop already resolved. §12.5's "not a second pipeline" is decided here or nowhere.
- Write **both** outputs into `_lab_dir()`: `{new_asset_id}.zip` (the real bundle bytes) and
  `{new_asset_id}.png` (its sheet, for display via the existing asset route). **A freshly minted id**,
  as every other Lab job does — not the loop's, which the job still needs to serve alongside it. The
  zip matters because it means **`scripts/probe_matte_fill.py` runs on the Lab's output unchanged** —
  one instrument, both surfaces.
- **`/asset/{id}.{ext}` must accept `zip`.** Its allowlist is `("png", "webp")` today, so the bundle
  would 404. Add it, or the operator cannot pull the artifact the probe reads.

### 12.3 The GPU discipline — the part that will bite

This is the first Lab operation that runs GPU work **in the backend process**; every existing one
goes to ComfyUI's own queue, which serializes itself. Two consequences, both load-bearing:

1. **`_evict_comfy_models_for_cutout()` is called by `make_pet_zip`, NOT by
   `pack_datsme_bundle`.** A direct caller therefore *skips the eviction* and runs birefnet's
   ~7 GiB working set (`_CUTOUT_WORKING_SET_BYTES`) against a GPU still holding ComfyUI's Wan
   stack — the documented OOM, and post-F2 an OOM **fails** rather than degrades. F4 must call
   the eviction itself, exactly as `make_pet_zip` does.
2. **It must take `GPU_LOCK`** (`webui/app.py`) or a Lab pack will collide with a real build or a
   design preview on the same card. Follow the preview's pattern (acquire with a timeout, surface
   busy) rather than blocking a UI thread indefinitely. A busy lock is a `pack_error` on a job that
   still returns its loop (§12.2) — never a lost animation. Note the lock is **process-local**: it
   serializes this backend against itself, while the eviction is what handles a ComfyUI holding
   VRAM in another process. Both halves are needed; neither substitutes for the other.

**Lazy import, both of them.** `app.py` imports `motion_lab.py`, so a module-top
`from app import GPU_LOCK` is circular — import inside the handler. `design_calibration.py`
documents this exact trap for `compose_design`; F4 hits it for `GPU_LOCK`.

**Honest cost, and it is the one real price of the merged shape.** The eviction makes the *next* Wan
loop reload (~33 s of model movement, `SPEC_GPU_MEMORY_HYGIENE` §10). Packing inside every animate
therefore pays that reload **per pose** instead of once per batch:

| 8-pose "Animate all" | Wan loads | rough wall time |
|---|---|---|
| loops only (`pack: false`) | 1 | ~33 s + 8×7 s ≈ **90 s** |
| loops + pack (`pack: true`) | 8 | 8 × (33 + 7 + 6) ≈ **370 s** |

Roughly 4×, from the numbers in `SPEC_GPU_MEMORY_HYGIENE` §10 and §12.1. **We take it, on purpose.**
Investigating one pose — the actual use — pays nothing, because a single animate reloads Wan anyway.
The batch case is a **default**, not an architecture: `pack: false` already exists on the body, so if
8-pose sweeps become the common path, `Animate all` sends `false` and that is a one-line change. Do
not pre-build a batching mode, a deferred-pack queue or a "pack after all animating" scheduler for a
cost nobody has complained about yet.

### 12.4 What it shows

The packed pose **animating** over a checkerboard (so alpha is visible), plus the §1 metrics for
that pose — filled %, hard-zero px, glaring %. Those numbers must come from **the same function the
probe uses**, imported, not re-derived: a Lab number and a probe number that can disagree are worse
than no number. (The `design_calibration.effective_strength` precedent — one knower, many surfaces.)

**Both tiles, every packed run — this is the instrument.** The raw loop above (white background, as
ComfyUI made it), the packed sheet below (checkerboard). Whatever the packer did to the pet **is the
visible difference between two tiles of the same animation**, in one run, with no second press and
no A/B to set up. That is what answers "which step caused it": the loop tile is the pipeline before
the packer, the packed tile is after, and they are the same 40 s of GPU.

**Where the tiles live is `SPEC_MOTION_LAB_DESIGN_PARITY` §2.5** — under the existing `▸ animation`
row of each pose card, with no new rung, because Rev.3 made packing a stage rather than an action.
That spec also settles the player: reuse `web/src/components/PosePlayer.tsx`, the same component
`PoseGallery` uses for the designer's result panel, widened to accept an explicit sheet rather than
only a saved `petId`. This section owns what the stage does; that one owns how it is shown.

**Where that shared function lives, and the posture trap.** It cannot live in `scripts/` (not a
package) and it must not be imported at `motion_lab.py`'s module top: `webui` runs on the
**GPU-less prod tier**, where a module-top import of anything ML-bearing breaks the deploy gate
("`import numpy` must fail"). Put it in `pet_factory/factory.py` beside the repair, and reach it
from the Lab through the **existing `_pf()` lazy accessor** — which is exactly why `_pf()` exists.
The probe script imports it directly. Same function, two callers, posture intact.

### 12.5 Scope and non-goals

- **No design section.** That is **`SPEC_MOTION_LAB_DESIGN_PARITY`** — a separate spec, because it
  changes for a different reason (design-axis calibration and designer fidelity, not the matte).
  The two are complementary: design parity gets the Lab the **same image** a designed build would
  animate; F4 gets it the **same failure**. Neither alone reproduces this defect — F4 alone
  reproduces it on an *undesigned* pet, which is enough to fix F1 against.
- **Admin-gated** like the rest of the Lab (adm cookie). Pool nodes do not get it.
- **Not a second pipeline.** If F4 ever needs a code path the build does not have, that is the
  signal it has gone wrong.

### 12.6 Guard tests

In `webui/tests/test_motion_lab.py`, the existing home for Lab behaviour.

1. `test_animate_calls_the_shipped_packer` — monkeypatch `pack_datsme_bundle`, assert it is the
   function invoked (no copy, no re-implementation).
2. `test_pack_evicts_comfy_before_the_cutout` — ordering, because §12.3's whole point is that a
   direct caller does not get it for free.
3. `test_pack_takes_the_gpu_lock_and_reports_busy` — held lock → the job still returns its **loop**
   with a `pack_error`, never a collided cutout and never a lost animation (§12.2).
4. `test_a_pack_failure_keeps_the_loop` — `pack_datsme_bundle` raising leaves `state="done"`, the
   loop asset served, and the stage named in `pack_error`. The loop cost ~40 s of GPU; a packer bug
   must not eat it, and "which step failed" must be readable off the record.
5. `test_animate_packs_by_default_and_pack_false_skips_it` — the default is ON (§12.2) and the
   bisection lever works. A default that silently flips is the one way this instrument lies.
6. `test_pack_frames_come_from_the_factory_decoder` — no second decoder.
7. `test_pack_drops_the_duplicated_final_frame` — an N-frame loop packs N−1 cells, matching
   `make_pet_zip`. Without it the Lab's frame indices and the probe's silently diverge by one (§12.2).
8. `test_the_lab_metrics_and_the_probe_share_one_function` — imported from one place.
9. `test_the_lab_pack_never_imports_the_ml_factory_at_module_top` — the posture guard, following
   the established `test_pool_mode_never_imports_the_ml_factory` /
   `test_predicate_never_imports_the_ml_factory` pattern. This is the test that would catch someone
   "tidying" the `_pf()` indirection into a top-level import and taking prod down.

### 12.7 Order

**Build F4 first**, before F1. It is what tells you F1 worked on *real birefnet mattes* without
waiting 3 minutes per attempt, and §10's premise is that this will iterate. If F1 does land clean
first time, F4 has still paid for itself as the workbench for §3.1 and §3.3 — both of which are
packer-stage questions with no instrument today.

**Two things go before F4:**

1. **The shared metric function + `scripts/probe_matte_fill.py`** (§6 step 0). The function lives in
   `pet_factory/factory.py` (§12.4) and the probe is its first caller — **not** metrics written
   inside the script, which `motion_lab.py` cannot import and which test 8 would fail on at the very
   end, after the code is written. Write the function first, the script second, F4 third.
2. **D6** (`SPEC_MOTION_LAB_DESIGN_PARITY` §2.6, one line each side). F4 packs whatever frames the
   Lab drew, so an anchor drawn from the wrong template hands the packer a paler animal than
   production ever produces — §12.1. Nothing else from that spec is needed first; D6 is independent
   of its own D1–D5.

Strictly, D6 could follow F4 — the endpoint does not care which sentence drew the frames. But the
first thing anyone does with F4 is read a damage number off it, and a number taken from a paler-than-
production frame is the wrong number. One line, first.

---

## 13. Rollback

One commit, and it reverts clean: F1 is a three-line move, F2 adds a function beside the BFS that
stays in the tree as the oracle (§9.3), F3 is a log line, F4 is additive and admin-gated. Reverting
F1 **must** revert F2's justification with it (§4.3) — a vectorized fill at 256² is re-litigating a
closed dead end. Nothing here changes the bundle contract, so a reverted build produces the same
bytes as today, defect included.
