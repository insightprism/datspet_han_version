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
| designer grey corgi¹ | white | 220,667 | **0** | 1.2 |
| designer grey corgi¹ | **grey** | 125,308 | **47,407** ❌ | 3.9 |
| elephant | white | 290,110 | 4,202 | 1.3 |
| elephant | **grey** | 129,119 | **30,190** ❌ | 10.9 |
| white snow leopard | **cyan** | 161,848 | **0** ✅ | 57.9 |
| elephant | **cyan** | 197,314 | **0** ✅ | 63.0 |
| brown bear | **cyan** | 196,928 | **0** ✅ | 59.0 |
| designer blue corgi¹ | **cyan** | 158,729 | 7,151 | 65.0 |
| designer blue corgi¹ | white | 140,321 | 10,033 | 5.1 |
| designer teal corgi¹ | **cyan** | 82,142 | **73,591** ❌ | 71.4 |

¹ `vivid brown corgi, recolored entirely brown` — the DESIGNER path, which flattens a coat
to one colour and so removes the tonal variation that otherwise separates a pet from a
similar backdrop. The hardest form of the brown/grey collision, and it still mattes whole.

### 1.1 What `fill+` actually means — read this before drawing conclusions from the table

`fill+` is **how much the sprite depends on the repair**, not whether it is broken. The
distinction cost a wrong reading during this investigation and is easy to repeat:

- **`fill+ 0`** — the matte is complete unaided. Nothing can go wrong downstream.
- **`fill+` high** — the matte came back a partial or line drawing and
  `_repair_matte_holes` reconstructs the body. That WORKS while every dropped region is
  **enclosed**, and produces a visible bite the moment one is **open** to the background,
  because `binary_fill_holes` closes pockets only. Verified: the teal corgi's 73,591 px were
  all enclosed and its final sprite is complete — while the white leopard's SLEEP pose, at
  comparable reliance, had one region open through the curl and shipped a hole.

So high `fill+` is a loaded gun rather than a corpse. It is the right thing to design
against — a matte that needs no repair cannot be defeated by an unlucky pose — but a single
high-`fill+` frame is not itself proof of a broken pet.

**Read the first row with that in mind.** On white, birefnet keeps 97k px of a pet whose
body is ~160k and the fill adds 103k — *more than the matte returned*. The repair is drawing
the animal. That is maximal fragility, and the sleep pose is where it cashed out.

**Read the second and sixth rows together.** The failure is not "white pets are hard"; it
is **pet colour ≈ backdrop colour**. The grey parrot mattes fine on white (`fill+ 665`)
and the white leopard does not. Contrast is the variable.

**A pet on a field of its OWN colour is unsegmentable — that is the whole rule.** A flat
grey corgi and an elephant both matte cleanly on white and both collapse on grey
(`fill+ 47,407` and `30,190`), exactly as the white leopard collapses on white. The defect
is symmetric and it is about the PAIR, never about the backdrop alone.

**And short of that near-match, the threshold is far looser than raw colour distance suggests.** Grey sits
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

with the backdrop a **named constant**, not a literal, beside the templates it feeds — the
tested phrase is `flat vivid cyan background` (§2.1).

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

**No fixed colour survives §1's symmetry.** An earlier draft of this spec proposed grey on
the strength of the parrot and brown results; the grey-corgi and elephant rows killed it.
Whatever constant is chosen, a pet of that colour defeats it — and the designer hands users
a colour picker, so they can aim at it deliberately. The candidates, with what each is
actually worth:

| candidate | clean on | breaks on |
|---|---|---|
| white (today) | grey, brown, dark pets | **pale pets** — the live defect |
| grey | white, brown pets | **grey pets** — `fill+ 47,407` |
| green | leopard, parrot | untested against a green pet; vignettes (38+) |
| magenta | leopard | parrot `fill+ 306`; worst vignetting (60); ~5× green's spill on pale fur |

Two designs were candidates; **(a) is now measured and is the proposal:**

**(a) A colour no pet can be — SATURATED CYAN. ✅ MEASURED.** Every pet that has defeated
another backdrop comes back with a **complete matte, `fill+ 0`**: the white leopard that
broke white, the elephant that broke grey, and the brown bear. The palette-reachable
near-collision — a `recolored entirely blue` corgi — is *better* on cyan (7,151) than on
today's white (10,033), so blue is comfortably far enough, and those holes are the corgi's
own white chest blaze rather than the backdrop.

The one failure is the exact match: a `recolored entirely teal` corgi returns a line drawing
on cyan (`fill+ 73,591`), the same shape as a white pet on white. **No fixed backdrop can
escape its own colour** (§1), so the question is only how reachable that colour is — and
cyan is not in the designer's ten-colour palette. It takes someone typing "teal" into the
free-text box, and F3's warning is what would surface it.

Note the flatness column is irrelevant here and the reason is worth keeping: cyan vignettes
hard (58–65) and still returns perfect mattes, because **birefnet is a segmentation model,
not a chroma keyer.** It reads shape and semantics; an uneven field costs it nothing. This
is also why the film industry's reason for choosing green — twice as many green photosites
on a Bayer sensor, and distance from skin tones — does not transfer: there is no sensor and
no skin here.

**(b) Resolve the backdrop from the pet, at fill time — NOT NEEDED unless (a)'s hole
matters.** The shape `base_pose`,
`motion_profile` and `surface` already use: content plus a keyword map, resolved where the
animal is known, defaulting to today's white when it is not. Robust by construction — it
picks a backdrop that contrasts with *this* pet — and it costs no extra GPU, because the
choice is made while composing the prompt rather than by looking at pixels. It is a
subsystem rather than a constant, and `surface_keywords.json`'s miss log is the precedent
for how its map grows.

### 2.2 What this does NOT do

- **It does not touch the repair.** `_repair_matte_holes` stays exactly as F1 left it. On a
  good backdrop it becomes a no-op, which is the correct end state for a repair: present,
  correct, and rarely needed. F3's warning stays too — it is the thing that will tell us
  whether this fix is holding in production.
- **It does not remove birefnet** (§2.1).
- **It does not change the sprite.** The backdrop is removed by the cutout; the shipped
  bundle is transparent either way. What changes is how much of the animal survives.

---

## 3. The cost — smaller than it first appears, because the app is pre-launch

**The project is in development. Pets already built do not have to stay compatible**
(decision, 2026-07-27). That removes most of what looked like the expensive half of this
change, and it is worth being explicit about what survives that removal and what does not.

**Gone as a concern:**

- *Existing bundles.* Already-built pets keep whatever they were built with. Nothing
  migrates, nothing is re-issued, and a pet built before this change is not "wrong" — it is
  just older. The backdrop never reaches a bundle anyway; it is removed by the cutout.
- *"The drawing changes."* It does — measured, the backdrop phrase changed the leopard's
  composition, smaller in frame and differently posed. Pre-launch, that is a restyle, not a
  regression. It would be a serious cost against a live catalog users had already adopted
  from; it is not one now.
- *Catalog divergence over time.* Nothing has to be kept consistent with pets that already
  exist.

**Still real, and the only work this change actually carries:**

- **Curated `base.png` files must be re-curated**, and this is CORRECTNESS, not tidiness. A
  curated base is fed to Wan **directly** — it *is* the base sprite on the adopt path — so a
  curated base drawn on white keeps this defect after the fix, while every typed pet is
  cured. That is a live divergence *going forward*, not a legacy one, which is why it
  survives the pre-launch dispensation. They are human-approved best-of-N selections and do
  not silently regenerate.
- **The still is user-visible.** It is the designer's step-1 archetype and step-2 preview —
  what someone looks at before pressing Generate. It would sit on grey. That is a design
  call to make deliberately rather than a cost to absorb: a grey field may read better or
  worse behind a pale pet, and it is worth one look before committing.
- **Pool worker nodes carry `prompt_templates.py`.** An unrolled node keeps drawing on
  white, so the fleet roll is part of shipping this, not a follow-up.

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
2. ~~**A pet recoloured to the backdrop's OWN colour is the untested case.**~~ **ANSWERED —
   it breaks, decisively** (§1): a flat grey corgi `fill+ 47,407` and an elephant
   `fill+ 30,190` on grey, both `fill+ 0`-to-4k on white. No fixed backdrop survives. The
   text below is kept because its reasoning was wrong in an instructive way — the palette
   argument and the live parrot both suggested grey was safe, and neither predicted this.
   ORIGINAL TEXT: The white
   leopard broke on white; by symmetry a flat grey pet should break on grey. Two things
   make it a smaller risk than it sounds, and neither makes it zero:
   - **`grey` is not in the designer's palette.** The ten colours are red, orange, yellow,
     green, blue, purple, pink, brown, white, black — a user cannot pick grey. Every
     palette colour is now either tested clean on grey (brown, white) or far from it.
   - **A natural grey animal is fine**: the african grey parrot mattes whole on grey.
   The route that remains open is free text — "anything else?" → *grey* — and typed
   animals whose name implies flat grey. Worth two renders before shipping; it is the one
   place the argument still rests on symmetry rather than measurement.
3. ~~**Which of §2.1's two designs?**~~ **ANSWERED — (a), a saturated cyan constant** (§2.1).
   The adversarial set all came back `fill+ 0`. The per-pet resolver is not needed and should
   not be built: it is a subsystem where a constant suffices, and §1 shows it would still
   have an exact-match hole of its own if the resolver ever guessed wrong.
4. **Is cyan the right cyan?** The tested phrase is `flat vivid cyan background`. The exact
   value is unpinned — the model interprets it — and a slightly different phrasing may sit
   nearer or further from the palette's `blue`. Worth pinning the phrase in the constant and
   re-running the blue corgi if it is ever reworded.
5. **Does the free-text hole need a guard?** A user typing "teal" or "cyan" into the
   free-text field aims straight at the backdrop. Cheapest mitigation is not a colour
   resolver but a note from F3's warning telling us it happened; the next cheapest is
   refusing those two words in free text. Do neither until it is seen. The backdrop would become
   content resolved at fill time from the pet's colour — the same shape as `base_pose` and
   `motion_profile`, which are already resolved that way. Do not build it until the
   measurement demands it: a constant is a one-line change and a resolver is a subsystem.
6. **What happens to the curated catalog?** §3. Re-curate, or fork the template for curated
   animals. This spec prefers re-curation and does not decide it.
7. **Does F3 go quiet?** `_MATTE_HARD_HOLE_WARN_FRACTION` fires when a frame has >10% hard
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
4. **Re-curate the curated `base.png` files** (§3) — required for correctness, since a
   curated base is the base sprite. The `animal_catalog/**/*.zip` samples are cosmetic by
   comparison and can follow whenever convenient; pre-launch, nothing depends on them
   matching pets that already exist.
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
