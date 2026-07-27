# Lessons Learned — the hole fill painted the animal black, because it ran one line too late

**Date:** 2026-07-27 · **Area:** `pet_factory/factory.py` (`pack_datsme_bundle`, `_fit_square`,
`_fill_holes_alpha`) · **Severity:** high (every pale pet ever built shipped with its body
partly black; the worst measured bundle lost 41% of its subject) · **Fix commits:** `3155d79`
(F1+F2+F3), `810e3a7` (the instrument that made it findable) · **Time cost:** most of a session,
of which the fix itself was three lines.

**One-line summary:** `_fill_holes_alpha` is a **matte-repair** step that was running inside the
**geometry** step — one line *after* the resample that had already destroyed the colour it was
meant to protect. It made holes opaque whose RGB was already zero, so it repainted the animal's
own body pure black at full opacity. The fix is to repair the matte *before* any resample.

---

## 1. Symptoms

| # | Observation | First (wrong) impression |
|---|---|---|
| 1 | A `white snow leopard` shipped with its **hindquarters, tail and back leg solid black** | "the model drew a dark pet" |
| 2 | A penguin bundle: **entire face and belly black**, only the back and wing survived | "black-and-white bird, looks stylised" |
| 3 | A curated `friendlypup` sample: black chest blaze and rear leg | "curation picked a bad candidate" |
| 4 | An otter bundle with **23% of its subject hole-filled** and *nothing* visibly wrong | contradicted every theory above |

Row 4 is what made the defect diagnosable: heavy hole-filling was demonstrably harmless on one
pet and catastrophic on another, so "the fill is bad" could not be the whole story.

**Why it hid for months:** the damage is camouflaged in proportion to how dark the animal is. A
blacked-out belly on a penguin reads as a design choice. `test_cutout_hygiene.py` had 21 guard
tests covering session setup, GPU fail-fast and failure semantics — and **not one assertion about
a resulting pixel**, so the suite stayed green throughout.

---

## 2. The investigation — including the wrong turns

### Wrong turn #1 — "the matting model is punching holes in the pet"

The intuitive story: birefnet drops interior regions, the fill closes them, some closures are
wrong. That predicts the *fill* is at fault and should be made more conservative.

It does not survive the otter. 23% filled, zero visible damage. Whatever distinguishes a harmless
fill from a destructive one is not the fill's aggressiveness.

**Lesson: when one instance of a mechanism is harmless and another is catastrophic, the mechanism
is not the bug — the difference between the two instances is.** Here it was the *pre-fill alpha*:
a soft hole (alpha ≥ 120) only dims its pixel slightly, while a hard hole (alpha ≈ 0) has already
lost its colour entirely.

### Wrong turn #2 — reasoning about the pipeline instead of reading it

Several hypotheses were argued from the pipeline's *shape* — the cutout, the sheet packer, the
resample — without opening the function. The bug was visible in four consecutive lines:

```python
result.putalpha(a)                                   # original colours + matte
cell = _fit_square(result, frame_size)               # LANCZOS — premultiplies
cell.putalpha(_fill_holes_alpha(cell.split()[3]))    # ← the fill, on a corpse
```

**Lesson: read the four lines around the symptom before theorising about the system.** The
ordering bug is obvious *in situ* and invisible from a description of the pipeline.

### Wrong turn #3 — believing a plausible cost estimate

The spec estimated that moving the fill to matte resolution would cost 303.9 ms/frame. Measured on
real mattes it was **444.8 ms/frame** — so F1 alone would have been a **57-second** regression on
a 128-frame build, not the 39 s predicted. Had the vectorisation (F2) been treated as optional
follow-up work, the fix would have shipped as a visible slowdown.

**Lesson: re-measure a performance claim on real data before deciding it is tolerable.** The
estimate was in the right order of magnitude and still wrong by 46%.

---

## 3. Root cause

`_fit_square` resizes RGBA with LANCZOS. Resampling premultiplies: a pixel with alpha ≈ 0
contributes its RGB scaled toward zero, so **after the resize, a fully-transparent pixel's colour
is black** — irrecoverably.

`_fill_holes_alpha` then ran on the *resized cell's* alpha and set interior holes to 255. Making a
pixel opaque does not restore its colour; it reveals whatever is there, which is now black.

So the pipeline's own repair step was the thing doing the damage, and it was doing it *because of
where it sat*, not because of what it did. The same function, moved three lines earlier, is
correct.

**The severity is set by the pre-fill alpha, which is why the otter was fine:**

- soft hole (alpha ≥ 120) → colour survives the premultiply mostly intact → dimmed slightly
- hard hole (alpha ≈ 0) → colour annihilated → **opaque black**

---

## 4. The fix

**F1 — move the repair onto the matte, before any resample** (the actual fix, 3 lines):

```python
repair = _repair_matte_holes(a)        # matte repair, colour still intact
result = orig.convert("RGBA"); result.putalpha(repair.alpha)
cell = _fit_square(result, frame_size) # geometry only — nothing touches alpha after this
```

The post-`_fit_square` `putalpha` is **deleted**, not branched around. No dual path.

**F2 — vectorise, and ship it in the same change.** The repair now runs at ~704² instead of 256²
— 7.6× the pixels. `scipy.ndimage.binary_fill_holes` replaces the interpreted BFS: 10.0 ms/frame
against 444.8, verified **byte-identical on 16/16 real alpha channels**. F1+F2 together are
cheaper than the original order. scipy arrives with rembg; no new dependency, and it stays behind
the lazy `pet_factory.__init__` boundary so the GPU-less web tier is untouched.

**F3 — make a large matte miss loud.** F1 makes the damage *invisible* — a matte that drops a
third of a frame is now cosmetically perfect. One WARNING per pose (not per frame; 128 lines
buries the signal), naming the worst frame and its hard-hole fraction. It fired on its first real
matte: `idle frame 3 had 56% of its subject as HARD interior holes`.

**`_fill_holes_alpha` keeps its name, signature and body** as the test oracle F2 is compared
against, and because two other specs cite it.

---

## 5. Verification (proven, not asserted)

**The decisive A/B ran on the exact frames that produced the defect** — the Motion Lab's own idle
`.webp`, repacked with the new code. Same frames in, so nothing but the repair can account for the
difference:

```
before   hard-zero 157,296 px (9,831/frame)   glaring 43.7%
after    hard-zero      53 px (    3.3/frame) glaring  2.7%
```

The residual 53 are the sprite's own eye and nose ink, not damage: **the raw ComfyUI frame
contains 32 near-black pixels of its own**, so the repaired sheet is blacker nowhere than the
drawing it came from.

**Guard tests, each verified red against the shipped order before the move** — 8 in
`test_cutout_hygiene.py`, with fixtures generated from a seeded RNG rather than committed. The
obvious real-data fixture was the catalog's staged sample bundle, and declining it proved
correct within the day: `dog/friendlypup` (38,933 hard-zero px, built pre-fix) was retired for
`cat/snowleopard` on 2026-07-27. A test keyed to curated content breaks on a curation decision.

**Two mutation tests** confirmed the new guards actually guard: retyping an input cap fails the
parity test; removing the clamp floor fails the strength test.

**Finally, in the product:** a full 8-pose build uploaded to DatsMe and rendered on a live profile
at 128px and 256px — clean, sharp, correct. `hard-zero 161` across eight poses, against 157,296.

---

## 6. Lessons (generalizable)

### On the bug itself

- **A repair step that runs in the wrong stage is worse than no repair.** It converts a subtle
  defect (a hole) into a loud one (a black blob) while looking like mitigation. Ask of any
  repair: *what has already happened to the data by the time this runs?*
- **Resampling RGBA destroys colour under low alpha.** Every filter except NEAREST premultiplies,
  and Pillow never un-premultiplies. Anything that depends on the colour beneath transparent
  pixels must happen **before** a resize.
- **When you fix a defect, expect to reveal the one it was hiding.** F1 removed the black paint
  and exposed a *transparent* bite that had been there all along — a separate defect
  (see `learned_white_backdrop_unsegmentable_*`). Budget for the second one.

### On the test suite

- **21 green guard tests and not one pixel assertion.** The suite tested that the cutout *ran*,
  that it *failed loudly*, and that its session was configured — never what it *produced*. A
  pipeline whose output is an image needs at least one assertion about a pixel.

### The instrument was worth more than the fix

The defect lived in a stage the Motion Lab did not run — the Lab covered still → loop and stopped
one step short of the packer. Extending it to pack what it animates (F4) turned a 3-minute blind
build into a **60-second visible experiment**, and every subsequent finding came out of it. The
fix is three lines; finding it needed an instrument.

**Corollary worth remembering: build the instrument before the fix, and prove the instrument by
reproducing the defect with it while the defect is still there.** A workbench that cannot show you
the bug is not yet evidence about anything.

---

## 7. Pointers

- `docs/SPEC_MATTE_REPAIR_ORDER.md` — the spec, §0 (the three facts), §2 (F1/F2/F3), §10 (attempt
  log), §12 (F4, the instrument)
- `docs/SPEC_MATTE_BACKDROP.md` — the *cause* of the holes F1 was repairing
- `scripts/probe_matte_fill.py` — the damage metric, and `factory.matte_fill_damage` which owns it
- `pet_factory/tests/test_cutout_hygiene.py` — the 8 guard tests
