# SPEC — Stop drawing pets on white: the backdrop is what breaks the matte

> **CLOSED & ARCHIVED — 2026-07-28. Shipped and fleet-rolled.**
> `STILL_BACKDROP = "flat vivid cyan background"` and `STILL_BACKDROP_RGB = (100, 230, 215)`
> live in `pet_factory/prompt_templates.py` (the one owner; `factory` re-exports rather than
> redefining), and both pet nodes run it at `c603356`.
>
> **Measured payoff:** a full 3-pose `white snow leopard` build reports `hard-zero 0` on every
> pose with **zero F3 warnings**, and `filled` fell **45.8% → 5.3%** — i.e. the matte stopped
> leaning on the repair at all. That is the difference between fixing the *cause* and fixing
> the *symptom*: `SPEC_MATTE_REPAIR_ORDER` F1 made the repair safe, this made it unnecessary.
>
> **⚠️ ONE OPEN QUESTION THIS SPEC CREATED, and it is why the investigation below exists:**
> a cyan backdrop turns `SPEC_MATTE_REPAIR_ORDER` §3.3's accepted trade-off ("enclosed
> background fills with background colour, which is far less jarring than black") into a
> *saturated teal patch* on the pet — measured at 2,168 px, 0.10% of subject, worst in `eat`.
> The damage metrics **cannot see it** (cyan luma 230 is neither hard-zero nor glaring), so
> `probe_matte_fill.py` calls those bundles clean. **PARKED, not accepted:**
> `docs/INVESTIGATE_CYAN_BACKDROP_ARTIFACT.md` — its first step is perceptual and is allowed
> to close the question. Archiving this spec does not close that.

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
| hyacinth macaw² | **cyan** | 94,218 | **0** ✅ | — |
| hyacinth macaw² | white | 125,319 | 65 | — |
| blue jay² | **cyan** | 122,206 | 2,739 ³ | — |
| blue jay² | white | 153,922 | **0** | — |
| peacock² | **cyan** | 90,725 | 3,228 ³ | — |
| peacock² | white | 122,099 | 5,838 | — |
| green parrot² | **cyan** | 142,963 | 422 ³ | — |
| green parrot² | white | 182,932 | 1,545 | — |
| cyan parakeet² | **cyan** | 112,800 | 346 ³ | — |
| cyan parakeet² | white | 167,832 | 768 | — |

² Natural blues, because blue is the plausible collision for a cyan field. Worth noting how
thin that risk actually is: blue in animals is almost always **structural** — Tyndall
scattering and photonic nanostructures — rather than pigment, so genuinely blue animals are
rare. A cartoon render draws them blue anyway, which is why they are tested. The hyacinth
macaw is the most saturated blue bird there is and returns a perfect matte on cyan.

³ **Not a matte failure — see §2.2.** The 2,739 px the fill closed have a mean colour of
RGB(104, 236, 222): it swallowed real *background* trapped between the bird's legs.

¹ `vivid brown corgi, recolored entirely brown` — the DESIGNER path, which flattens a coat
to one colour and so removes the tonal variation that otherwise separates a pet from a
similar backdrop. The hardest form of the brown/grey collision, and it still mattes whole.

### 1.0 Three things the natural-bird rows settle

**The natural collision does not exist.** A *cyan parakeet on a cyan field* needs 346 px of
repair — **half** what the same bird needs on white. Real animals carry dark barring, eyes,
beaks and shading that birefnet locks onto; the peacock (iridescent blue-green, the closest
natural colour to the backdrop) and a green parrot behave the same way. What broke cyan was
the `recolored entirely teal` corgi, whose coat is *flat and artificial*. So the hole is not
"cyan animals" — it is **flat artificial recolours aimed at the backdrop**, reachable only
through free text, and far narrower than the teal row alone suggests.

**Cyan needs less repair than white on every pet tested**, including birds with nothing in
common with either colour: 3,228 vs 5,838, 422 vs 1,545, 346 vs 768. White is not a neutral
default that happens to fail pale pets; it is the worse backdrop generally.

**And the residual on cyan is never the animal.** Every cyan row's closed pixels come back
backdrop-coloured — RGB(101,233,212), (88,208,183), (95,221,212) — i.e. §3.3 pockets, not
fur. Every white row's come back white, RGB(~248,248,246), which is **unreadable**: on a
white field a swallowed background pocket and a repaired fur hole are both white. That is
not a measurement weakness, it is the ambiguity itself, and it is exactly why §3.3 has been
unfixable. **The discriminator §5.8 proposes is now validated 6/6** on these rows: on a
distinctive backdrop, "is this pocket the backdrop?" is a question with an answer.

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

### 2.2 It makes an existing latent defect VISIBLE — and, for the first time, fixable

`SPEC_MATTE_REPAIR_ORDER` §3.3 records "enclosed-background false positives" as a known
defect it deliberately does not fix: when the animal's own geometry traps a pocket of real
background — between the legs, inside a curled tail — `binary_fill_holes` closes it, because
a hole and a trapped pocket are topologically identical.

**This has always happened.** On a white backdrop the result is a white blob on a pale pet
and nobody notices. On cyan it is a turquoise patch, and the blue jay row above is one:
2,739 px at RGB(104, 236, 222) between the legs. Adopting a saturated backdrop therefore
*surfaces* a defect rather than causing one — the same way F1 surfaced this spec's defect by
removing the black paint that hid it.

**And the same change makes it solvable.** The reason §3.3 was left alone is that with a
white backdrop a white pocket and a white fur hole are indistinguishable — the exact
ambiguity §1 is about. With a known, distinctive backdrop the repair gains a test it never
had: *do not close a pocket whose pixels look like the backdrop.* On the blue jay the pocket
is RGB(104, 236, 222) and the bird is RGB(100, 134, 179) — trivially separable. That is a
follow-up, scoped in §5.8, not part of this change; but it is the reason a saturated
backdrop is strictly better than a neutral one even though both matte equally well.

### 2.3 What this does NOT do

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

- ~~**Curated `base.png` files must be re-curated**~~ **— WRONG, corrected 2026-07-27.**
  This spec claimed the catalog was a correctness blocker. It is not, and the reason is
  worth recording because the mistake was an assumption that went unchecked for several
  revisions: **every curated `base.png` is a transparent CUTOUT** (RGBA, 60–71% transparent,
  corner `(0,0,0,0)`), not a white-backed image. No white is baked into them. The white only
  ever entered at `_prep_reference_image`'s flatten — the I3 path — which this change already
  fixes. Verified end-to-end: all four bases now composite onto `(100,230,215)`.

  What the audit DID find is unrelated to the backdrop: `cat/tabby` carries **795 hard-zero
  px** of F1-era damage baked into the file — visible dark blotches on its hind legs. The
  other three are clean (0, 0, 32 — the 32 being a corgi's own nose and eyes). So the work is
  **one breed, optional**, and it is F1 debt rather than backdrop debt.

  Note for whoever does it: `generate_candidates.py` runs through the POOL, so it would need
  the fleet rolled to produce cyan-era candidates — a circular dependency with §6.1's gating.
  It dissolves because the bases do not need the roll to be correct; and candidates can be
  generated on a local GPU box instead if that ordering is ever inconvenient.
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
8. **Fix §3.3 using the known backdrop — the discriminator is VALIDATED, 6/6** (§1.0). The
   repair refuses to close an enclosed pocket whose mean colour matches the backdrop within a
   tolerance. Every cyan row above separates cleanly; every white row is unreadable, which is
   the point. Still needs a threshold chosen against real pockets and a guard for a pet that
   genuinely IS backdrop-coloured in that region. Ships after this spec, not with it —
   but it is what turns the blue jay's turquoise patch from a known wart into a fixed bug.
9. **Does F3 go quiet?** `_MATTE_HARD_HOLE_WARN_FRACTION` fires when a frame has >10% hard
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
4. **Nothing required in the catalog** (§3, corrected): the curated bases are transparent
   cutouts and composite onto the new backdrop unchanged. Optional and unrelated to this
   spec: `cat/tabby`, which carried 795 hard-zero px of F1-era damage, and the staged
   `friendlypup.zip` sample. Both were pre-existing debt, neither blocked — and both are now
   cleared: tabby regenerated (`589de78`), friendlypup replaced by `cat/snowleopard`.
5. ~~Roll the pool fleet~~ — **DONE 2026-07-27, `0c5a5f9`, GREEN 7/7.** Worker nodes carry
   `prompt_templates.py` too, so an unrolled node would keep drawing on white. Confirmed by
   importing the constant in each worker's own engine: both `omen-pet` and `dual-nvidia-pet`
   report `STILL_BACKDROP = 'flat vivid cyan background'` / `(100, 230, 215)`.

---

## 6.1 Peripheral impact — the checklist the fleet roll is gated on

"Confirmed fixed" is not enough on its own; the backdrop is an input to more than the matte.
Each of these is a *look* or *calibration* question rather than a correctness one, which is
why they need eyes on them before the pool nodes are rolled:

- **The designer's preview changes.** Step 1's archetype and step 2's preview are the stills
  a user looks at before pressing Generate, and they would sit on cyan. The most visible
  non-pet effect of this change, and a deliberate design call.
- **`compose_design`'s calibration — MEASURED, 2026-07-27: it holds, with a small shift.**
  Two designs (`purple` + `body:fat`, `white` + `coat:fluffy`) rendered through the real
  designer path on both backdrops, same seed:

  | design | on cyan | on white | fur shifted toward cyan by |
  |---|---|---|---|
  | purple + chubby | RGB(175,129,235) | RGB(146, 88,206) | +5.5 |
  | white + fluffy | RGB(245,245,241) | RGB(234,229,222) | +6.4 |

  **The recolour still wins** — visually unambiguous in all four, and the `min_strength`
  clamp fired identically (0.90) on both backdrops, so the strength calibration is
  untouched. What changes is a small lightening/cooling of about 5–6 units.

  The white row is the one worth understanding: on cyan the pet renders RGB(245,245,241),
  near-perfect white; on white it renders (234,229,222), noticeably warm. **The model was
  shading white pets AWAY from a white field to keep them visible** — the same pressure that
  broke the matte, showing up in the colours. On cyan it is free to draw true white, so for
  pale pets this is an improvement rather than a regression.

  **Consequence for the pending work:** `SPEC_PET_DESIGN_AXES` §8 Phase 3 (the axis
  calibration that is "reasoned, not measured") must be done on the CYAN substrate. Doing it
  before this change would have measured the wrong thing. The freshness predicate itself is
  unaffected — `design_calibration.check()` reports 76/76 cells current, because it compares
  (description, strength) and not pixels; only the rendered contact sheets look stale.
- **Curated `base.png` keeps the defect until re-curated** (§3) — a curated base IS the base
  sprite.
- **`animal_catalog/**/*.zip` samples** would visibly differ from freshly built pets.

## 7. Acceptance gate

1. `pytest pet_factory/tests webui/tests` green.
2. A real `./make_pet.sh "white snow leopard"` with the UI idle → `scripts/probe_matte_fill.py`
   reports **0 hard-zero** and the per-pose `fill+` is 0 or near it.
3. **By eye in the Motion Lab**, on the pose that started this: `sleep` on a pale pet, packed
   tile complete — no bite, no blob. The Lab is the instrument; use it.
4. The curated samples still read as their breed after re-curation (§3) — a human check, not
   a number.

---

## 8.1 KNOWN COST — the backdrop shrinks the pet by ~40% of its area

**Measured after implementation, 2026-07-27.** Same species, same clause, **same seed**, only
the backdrop phrase differing. The animal's share is read off the DRAWING (flood the field in
from the border, count what it cannot reach), so the matte's own quality cannot contaminate it:

| pet | white | cyan | area lost |
|---|---|---|---|
| tabby cat | 31.1% | 18.3% | **−41%** |
| corgi dog | 24.1% | 14.6% | **−39%** |

This is not seed variance — both baselines reproduced exactly on a re-run. Z-Image appears to
treat a coloured field as a *scene* and leaves environmental space around the subject, where a
white field reads as "sprite on blank" and it fills.

**Why it matters beyond looks:** the pet occupies ~40% less of the 704² frame, so ~40% fewer
real pixels of animal survive the downscale into a 256² cell. It is a resolution cost, not
only a scale one.

**A prompt phrase recovers about half, and no more:**

| variant | share |
|---|---|
| white, today's words | 31.1% |
| cyan, today's words | 18.3% |
| cyan + `the animal fills the frame` | 17.0% (worse) |
| cyan + `large in frame, close-up` | 23.7% |
| cyan + `tightly cropped, the animal fills most of the image` | **25.6%** |

"Fills the frame" making it *worse* suggests the model reads these as composition hints rather
than scale instructions. So the prompt route is a partial mitigation, not a fix.

**Three options, none of them free** — this is an open decision, not a settled one:

1. **Accept.** Sprites are complete, just smaller in their cell. Cheapest, and pre-launch the
   inconsistency with existing pets does not matter.
2. **Take the partial recovery** — one clause, ~half the loss back, no new failure modes.
3. **Crop to the subject at pack time.** Fully fixes framing AND the pre-existing variance —
   even on white, framing ranged 24.1% (corgi) to 41% (snow leopard), so sprite scale has
   never been consistent. Two caveats: a PER-FRAME crop makes the animal *breathe* through a
   walk cycle, so it needs one shared box computed from the union of every frame's subject;
   and it flattens genuine species scale, which is a product question rather than a technical
   one.

### 8.1.1 DECIDED — accept it. CONFIRMED against a real DatsMe render.

**The confirming evidence came from the product, not from this repo** (2026-07-27): a full
8-pose `white snow leopard` built after every fix, uploaded to DatsMe and rendered on a live
profile at both 128px and 256px. It looks right — clean silhouette, correct colour, sharp,
and well-proportioned on the page. No visible issue at either size, and normal usage is
smaller still.

That bundle also closes the loop on the original defect:

```
BUNDLE   filled 5.9%   hard-zero 161 px across 8 poses (1.3 per frame)
```

against **157,296** on the same pet before F1 — and the 161 are its eyes and nose, drawn
black rather than filled.

**A note on how this section got written.** The framing measurement below is sound and
reproducible, but its significance was over-estimated here for several revisions: it was
escalated to a three-option decision on the strength of pixel coverage inside a 256px cell,
which is not where anyone looks at a pet. The questions that actually resolved it were about
the product — does a curated base ever become a sprite (no), what size are pets rendered at
(64 and below, mobile-first), and does the real thing look wrong (it does not). Worth
remembering the next time a measured difference starts looking like a decision.


**Two questions from the operator deflated this, and both were right.**

**Does the framing even reach a sprite?** Yes, but only through the anchors. A curated
`base.png` never becomes a sprite frame — every enabled pose in all seven profiles has a
`pose_prompt` anchor, so `pose_starts[name] = base` never fires for a prompt-derived pet.
The base is a picker image and a design substrate, so ITS framing is irrelevant, and the
tabby was promoted at 24% of cell without waiting for this decision.

**Does it show at the size pets are displayed?** Rarely, and that is the operative word.
`PetThumbnail` draws the whole cell and `PetCanvas` scales it via `--pet-display-size`
(default 96px); DatsMe's pet-size control offers 32/48/64/96/128/192/256 and sits at **64**.

The product is **mobile-first**, so the small end of that range is where pets actually live —
a phone has no room for more, and even on a desktop a 128px+ pet costs more screen than a
profile ornament is worth. At 32–64px the same sprite at 41% and at 30% of cell are hard to
tell apart, and no detail is lost either way: even the 30% version carries ~77 source pixels
of animal into a ~35px render, still a downscale.

**Quality is never the issue at any supported size — only apparent size is.** The sheet cell
IS 256px and `--pet-display-size` caps at 256, so every render is a downscale or 1:1. Nothing
upscales, so nothing softens. Measured on the same idle frame either side of the change
(bounding box 185×188 on cyan vs 212×217 on white — about 13% smaller linearly):

| display box | cyan era | white era |
|---|---|---|
| 48px | 35px of animal | 40px |
| 64px | 47px | 54px |
| 128px | 94px | 108px |
| 192px | 141px | 162px |
| 256px | 188px | 217px |

So a cyan-era pet renders correctly at 128 or 192 — it simply sits slightly smaller in its
box with a little more margin. The one scenario that would bite is wanting the ANIMAL itself
to span a full 192px, which needs the cell drawn at ~260px and crosses into upscaling; the
white-era framing had ~15% more headroom before that point. Nothing in the product does this.

**Being precise about the limit of that claim:** the larger sizes exist, and at 192 or 256 a
30%-of-cell pet is visibly smaller in its box than a 41% one. The decision below rests on
those sizes being rare by design rather than absent — if pets ever become a large-format
element, this is worth re-opening, and §8.1.2 says what to do then.

**So: accept.** The pets are correct, complete, and slightly smaller in their box than
white-era ones. Neither alternative earns its cost at the sizes that dominate — the prompt
phrase recovers half of a difference that is hard to see at 64px, and cropping to the subject
would rewrite sprite scale across the whole catalog for a cosmetic delta.

**Also established while investigating, and worth keeping** (§8.1.2): the trade-off is real
and there is no window — every backdrop tint that fixes the matte shrinks the pet, and every
one that preserves framing breaks the matte. But the opposition exists ONLY FOR PALE PETS.
White is fine for most (`fill+ 0` on a brown bear, a brown corgi, a blue jay) and
catastrophic only for pale ones (`103,403` on a white snow leopard). If the framing loss ever
does matter, the answer is not a global backdrop — it is to resolve the backdrop per pet:
white by default, tinted only when the pet is pale. Not built, because nothing needs it.

## 9. Implementation decisions — closed before code

Found by asking what two implementers would do differently. **I3 is the one that matters**:
without it this change silently does nothing for most pets.

| # | the question | decision |
|---|---|---|
| **I1** | where does the phrase live? | `STILL_BACKDROP = "flat vivid cyan background"` in `prompt_templates.py`, baked into both templates at module level so `base_still_prompt(animal, pose)` keeps its exact signature. A third format field would break every caller for no gain. |
| **I2** | both templates, or only the remix one? | **both.** `_base_prompt` is the CLI's branch (§2.6 of SPEC_MOTION_LAB_DESIGN_PARITY) and `_remix_prompt` is every web build's. Fixing one would make the CLI and the app disagree about the one thing this spec is about. |
| **I3** | **`_prep_reference_image` pads and flattens onto `(255,255,255)`.** | **It must use the backdrop too.** This is not optional and it is easy to miss: `_base_sprite`'s **as-is** branch runs it on EVERY web build, and the upload door runs it with `isolate=True`, which cuts the subject out and then drops it on a white field — manufacturing the exact defect this spec removes. A prompt-only change leaves that path broken. |
| **I4** | what RGB, given the phrase only *asks* for cyan? | `STILL_BACKDROP_RGB = (100, 230, 215)`, measured from what the model actually draws (the swallowed-pocket means across six renders were RGB(88–104, 208–236, 183–222)). It only has to be close enough that padding does not seam against the drawn field. |
| **I5** | two representations of one decision — a PHRASE and a PIXEL. | Accepted, and guarded: the phrase lives in `prompt_templates` (pure data, GPU-less-safe) and the pixel in `factory` (needs PIL). A test pins that they agree in name and intent, since nothing else can keep a sentence and a tuple in sync. |
| **I6** | does anything downstream assume white? | The cutout removes the backdrop, so the shipped sprite is unchanged. The one behavioural difference is the **cutout-failure fallback**: `_CUTOUT_MAX_FALLBACK_FRAMES = 0` means a failure raises rather than shipping an opaque frame, so no cyan-backed sprite can escape. Worth knowing that if that constant were ever raised, the failure mode becomes visibly cyan instead of invisibly white — which is an improvement. |

## 8. Rollback

One constant. Revert it and every subsequently drawn pet returns to a white backdrop; pets
already built are unaffected either way, since the backdrop never reaches the bundle.
The risk that does not roll back is §3: content re-curated against a grey template would
have to be re-curated again.
