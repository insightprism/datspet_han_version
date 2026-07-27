# SPEC — Stop drawing pets on white: the backdrop is what breaks the matte

**Status:** proposed, 2026-07-27. **Discharges `SPEC_MATTE_REPAIR_ORDER` §3.2** ("the matte
quality itself"), which that spec deliberately deferred while it fixed a different bug.

**The one-line diagnosis:** `BASE_STILL_TEMPLATE` and `REMIX_STILL_TEMPLATE` both end in
`white background`, and a pale animal on a white field is the one input birefnet cannot
segment. On a white backdrop the matte of a white snow leopard comes back as a **line
drawing** — the outline and nothing else — and the interior of the pet is reconstructed
entirely by `_repair_matte_holes`. Change the backdrop and the same pet mattes whole.

**Amends:** nothing. **Depends on:** `SPEC_MATTE_REPAIR_ORDER` F1 (shipped) — the repair
must already be correct, or this change's effect cannot be separated from that one's.

**Repos touched:** `datsme-pet-factory_wu` only — `pet_factory/prompt_templates.py` (the
backdrop phrase), its tests, and **content regeneration** (§6), which is the real cost.

**Code is cited by symbol, never by line number.**

---

## 0. Why this is not the bug the previous spec fixed

`SPEC_MATTE_REPAIR_ORDER` fixed **where the repair ran** — it was closing holes after the
resample had already destroyed the colour underneath, painting the animal black. That was
real, it is fixed, and it is not this.

This is about **why there were holes to close at all**. The two are easy to conflate
because F1's fix made this one visible: while the fill was painting the body black, a
missing region and a filled region looked identical. They are separate defects with
separate causes, and the operator sees the same symptom — a hole in the pet — either way.
From the product's side that distinction is worth nothing: **a transparent blob and a
black blob are the same bug.** This spec closes the second one.

---

## 1. The measurement

Same pet, same seed, same clause, same pose, four backdrops, all the way through Wan I2V
to the matte. `fill+` is how many pixels `_repair_matte_holes` had to close — **0 means
the matte needed no repair at all**, which is the number that matters.

| pet | backdrop | matte px | **fill+** | backdrop flatness |
|---|---|---|---|---|
| white snow leopard | **white** | 97,008 | **103,403** | 10.8 |
| white snow leopard | grey | 160,939 | **0** | 4.0 |
| white snow leopard | green | 160,329 | **0** | 38.3 |
| white snow leopard | magenta | 172,984 | **0** | 60.1 |
| african grey parrot | white | 157,877 | 665 | 1.2 |
| african grey parrot | grey | 108,013 | **0** | 2.8 |
| african grey parrot | green | 109,272 | **0** | 40.6 |
| african grey parrot | magenta | 128,208 | 306 | 60.4 |
| brown bear | white | 218,371 | **0** | 1.6 |
| brown bear | **grey** | 189,274 | **0** | 3.3 |
| designer brown corgi¹ | white | 213,159 | **0** | 2.9 |
| designer brown corgi¹ | **grey** | 170,129 | **0** | 3.2 |

¹ `vivid brown corgi, recolored entirely brown` — the DESIGNER path, which flattens a coat
to one colour and so removes the tonal variation that otherwise separates a pet from a
similar backdrop. The hardest form of the brown/grey collision, and it still mattes whole.

**Read the first row.** On white, birefnet keeps 97k px of a pet whose body is ~160k, and
the fill adds 103k — *more than the matte returned*. The matte is a line drawing and the
repair is drawing the animal. Every other row needs no repair whatsoever.

**Read the second and sixth rows together.** The failure is not "white pets are hard"; it
is **pet colour ≈ backdrop colour**. The grey parrot mattes fine on white (`fill+ 665`)
and the white leopard does not. Contrast is the variable.

**And the collision threshold is far looser than raw colour distance suggests.** Grey sits
61 RGB units from the designer's `brown` — by distance alone the worst collision of any
candidate — and a brown bear, a brown corgi and an *entirely recoloured* brown corgi all
matte whole on grey (`fill+ 0`). A grey parrot on grey does too. The model's own dark
outlines and internal shading carry separation that a colour-distance argument misses.
Only a near-exact match (white pet, white field) actually breaks it.

---

## 2. The fix

One phrase, in one file:

```python
# prompt_templates.py
BASE_STILL_TEMPLATE  = "... simple flat shading, {backdrop}, storybook style"
REMIX_STILL_TEMPLATE = "... simple flat shading, {backdrop}, storybook style"
```

with the backdrop a **named constant**, not a literal, beside the templates it feeds.

### 2.1 Which colour — and why not a chroma key

The sprite-generation literature says to generate on `#FF00FF` or `#00FF00` and key it out.
**That advice does not transfer here, and the measurement says why:** it assumes a
generator that honours a flat backdrop. Ours does not. The `flatness` column above is the
standard deviation of the backdrop the model actually drew:

```
grey      4.0 / 2.8     flat
green    38.3 / 40.6    vignetted
magenta  60.1 / 60.4    heavily vignetted
```

Z-Image draws a *scene* with a coloured background, not a key. So colour keying cannot
replace segmentation here, and the ~134 lines of cutout apparatus in `factory.py` stay.
We are choosing a backdrop that helps birefnet, not one that replaces it.

Given that, the ranking inverts from what the chroma-key literature would suggest:

| candidate | for | against |
|---|---|---|
| **grey** ✅ | flattest the model draws (4.0); `fill+ 0` on both test pets; neutral, so least spill risk | 61 RGB units from the designer's `brown` — the closest collision of any candidate |
| green | `fill+ 0` on both; far from most pet colours | vignettes badly (38+); users can pick green pets; green parrots and iguanas exist |
| magenta | `fill+ 0` on the leopard | worst vignetting (60); **~5× the edge spill of green on pale fur** (34.3% vs 6.2%), the documented blonde-hair failure; users can pick pink and purple |
| white ❌ | — | the defect |

**Grey, pending §5's open question.** It is the only candidate the model renders flat, and
flatness is what a segmentation model benefits from too — a busy backdrop gives birefnet
more to be wrong about.

### 2.2 What this does NOT do

- **It does not touch the repair.** `_repair_matte_holes` stays exactly as F1 left it. On a
  good backdrop it becomes a no-op, which is the correct end state for a repair: present,
  correct, and rarely needed. F3's warning stays too — it is the thing that will tell us
  whether this fix is holding in production.
- **It does not remove birefnet** (§2.1).
- **It does not change the sprite.** The backdrop is removed by the cutout; the shipped
  bundle is transparent either way. What changes is how much of the animal survives.

---

## 3. The cost, which is the real decision

**The still is user-visible.** It is the designer's step-1 archetype and step-2 preview —
the picture someone looks at before pressing Generate. Today it sits on white. It would
sit on grey.

**Every curated `base.png` in `animal_catalog/` was drawn on white**, and this is a
CORRECTNESS problem rather than a cosmetic one. A curated base is fed to Wan directly — it
*is* the base sprite on the adopt path — so until those files are re-curated, a curated pet
keeps a white backdrop and keeps this defect while every typed pet is fixed. They are
human-approved best-of-N selections and do not silently regenerate. Either they are
re-curated, or the catalog silently diverges from the rest of the app.

**The drawing itself changes.** Measured, not assumed: swapping the backdrop phrase changed
the leopard's composition — smaller in frame, differently posed. The template is part of
the prompt, so every pet drawn after this change differs from the same pet drawn before it.
That is why this is a content decision with catalog-wide reach, not a bug fix.

---

## 4. What we tried, and why each was rejected

*Recorded so that if this fix fails or breaks something downstream, the alternatives and
their evidence are here rather than in someone's memory.*

| # | attempt | measured result | verdict |
|---|---|---|---|
| C1 | Leave it to the hole fill | On white the fill reconstructs the entire body (`fill+ 103,403`), and any region OPEN to the background is unfixable in principle — `binary_fill_holes` closes enclosed pockets only | rejected: the fill cannot close what is not enclosed. This is what the operator saw as a transparent bite |
| C2 | Morphological closing before the fill, to bridge a broken outline | Recovered +576 px at radius 8 — nothing. The opening is wide, not a hairline break | rejected: wrong model of the defect |
| C3 | Enhance the frame for matting only (contrast/autocontrast/unsharp), keep original pixels for colour | Closed the bite convincingly on one frame; **across 6 loops the result was inconsistent** and my concavity metric proved unreliable (returned negative values) | not disproven, but unvalidated — and it treats the symptom while the input stays ambiguous |
| C4 | Cut out the still (which mattes perfectly) and composite it onto a backdrop before the I2V step | **Works**: `fill+ 758 → 0`, pet drawn identically | rejected on cost/elegance: one extra cutout per build, ~+35 s of model movement, and a pipeline stage that exists to compensate for a prompt we control |
| C5 | Chroma key: generate on `#FF00FF`/`#00FF00` and key by colour, dropping birefnet | The model will not draw a flat key (flatness 38–60 vs grey's 4). Magenta also spills ~5× more than green into pale fur | rejected: the literature's premise does not hold for this generator |
| C6 | **Change the backdrop phrase to grey** | `fill+ 0` on every pet tested, flattest backdrop the model draws, no pipeline change | **proposed** |

### 4.1 Measurement mistakes made along the way — do not repeat them

Three proxy metrics gave confident wrong answers before the visual check caught them.
Recorded because the next person will reach for the same shortcuts:

- **Brightness flood-fill as a ground truth for "where is the animal".** It fails for
  exactly the reason birefnet fails — white fur and white background are the same
  brightness. It leaked *into* the pet at 704² and swallowed the hollow of a curled pose at
  256², producing a confident "30% of the pet was dropped" that was wrong.
- **Repainting a frame's background to test a backdrop.** Changes birefnet's output
  *independently of the colour*: 193k px kept on the untouched frame vs 68k on the same
  frame repainted flat white. Only a real re-render answers a backdrop question.
- **`spill%` where the pet's colour is near the backdrop's.** It divides by the
  interior-to-backdrop distance, which collapses — hence 281% for a grey parrot on grey and
  −470% on white. Trust it only when pet and backdrop are far apart.

**The reliable instrument throughout was the eye**, via the Motion Lab's packed tile and
contact sheets. That is worth remembering when the next matte question arrives.

---

## 5. Open questions

1. ~~**Does a BROWN pet survive a grey backdrop?**~~ **ANSWERED — yes, in all three forms
   tested** (§1): a brown bear, a brown corgi, and the designer's `recolored entirely
   brown`, all `fill+ 0`. The 61-unit collision does not materialise in practice.
2. **A pet recoloured to the backdrop's OWN colour is the untested case.** The white
   leopard broke on white; by symmetry a flat grey pet should break on grey. Two things
   make it a smaller risk than it sounds, and neither makes it zero:
   - **`grey` is not in the designer's palette.** The ten colours are red, orange, yellow,
     green, blue, purple, pink, brown, white, black — a user cannot pick grey. Every
     palette colour is now either tested clean on grey (brown, white) or far from it.
   - **A natural grey animal is fine**: the african grey parrot mattes whole on grey.
   The route that remains open is free text — "anything else?" → *grey* — and typed
   animals whose name implies flat grey. Worth two renders before shipping; it is the one
   place the argument still rests on symmetry rather than measurement.
3. **Does the backdrop want to be per-pet?** Only if (2) fails. The backdrop would become
   content resolved at fill time from the pet's colour — the same shape as `base_pose` and
   `motion_profile`, which are already resolved that way. Do not build it until the
   measurement demands it: a constant is a one-line change and a resolver is a subsystem.
4. **What happens to the curated catalog?** §3. Re-curate, or fork the template for curated
   animals. This spec prefers re-curation and does not decide it.
5. **Does F3 go quiet?** `_MATTE_HARD_HOLE_WARN_FRACTION` fires when a frame has >10% hard
   interior holes. If the backdrop change is working, that warning should stop appearing in
   ordinary builds. It is the cheapest possible production signal that this held.

---

## 6. Build order

1. **Answer §5.1** (brown on grey). It is two renders and it decides between a constant and
   a resolver.
2. The constant + template change, with a guard test that the backdrop is a named constant
   and that both templates carry it.
3. **Re-render the §7 baselines and probe them**: `white snow leopard`, the pale case that
   started this, plus one brown pet — `fill+ 0` and `hard-zero 0` on both.
4. **Content regeneration** (§3): the curated `base.png` files and
   `animal_catalog/**/*.zip` samples. This is the bulk of the work and it is not code.
5. Roll the pool fleet — worker nodes carry `prompt_templates.py` too, so an unrolled node
   keeps drawing on white.

---

## 7. Acceptance gate

1. `pytest pet_factory/tests webui/tests` green.
2. A real `./make_pet.sh "white snow leopard"` with the UI idle → `scripts/probe_matte_fill.py`
   reports **0 hard-zero** and the per-pose `fill+` is 0 or near it.
3. **By eye in the Motion Lab**, on the pose that started this: `sleep` on a pale pet, packed
   tile complete — no bite, no blob. The Lab is the instrument; use it.
4. The curated samples still read as their breed after re-curation (§3) — a human check, not
   a number.

---

## 8. Rollback

One constant. Revert it and every subsequently drawn pet returns to a white backdrop; pets
already built are unaffected either way, since the backdrop never reaches the bundle.
The risk that does not roll back is §3: content re-curated against a grey template would
have to be re-curated again.
