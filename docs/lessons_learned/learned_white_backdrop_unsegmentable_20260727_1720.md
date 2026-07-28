# Lessons Learned — a white pet on a white backdrop is not a hard segmentation problem, it is an impossible one

**Date:** 2026-07-27 · **Area:** `pet_factory/prompt_templates.py`, `pet_factory/factory.py`
(`_prep_reference_image`), the whole still → loop → cutout chain · **Severity:** high (any pet
whose colour matched the backdrop shipped with a bite taken out of it) · **Fix commits:**
`73cd6ee` (the backdrop change), `eea7f0f` (one owner + guard test) · **Time cost:** a session,
most of it spent on evidence rather than code — correctly.

**One-line summary:** every still was drawn on `"white background"`, so a white pet had **no
edge to find**. birefnet returned a line drawing (outline opaque, interior transparent), and no
amount of matte repair can invent an edge that was never rendered. The fix is upstream of the
matte entirely: draw on a colour **no animal is** — a flat vivid cyan — chosen by testing, not by
argument.

---

## 1. Symptoms

| # | Observation | First (wrong) impression |
|---|---|---|
| 1 | `white snow leopard` shipped with a **transparent bite** out of its flank | "the black-blob fix broke something new" |
| 2 | The same build's matte was **45.8% interior fill** — nearly half the subject was hole | "birefnet is having a bad day" |
| 3 | A **penguin's white belly** dropped; the black back was perfect | "high-contrast animals are fine, so it's contrast-dependent" |
| 4 | Dark and mid-tone pets (otter, corgi, red panda) were flawless on the same code | "it's rare, maybe ship it" |

Row 1 is the important one: **fixing the black blob did not create this — it revealed it.** The
hole was always there. The old (mis-ordered) repair had been painting it opaque black, so the
symptom changed from "black patch" to "missing patch" the moment the repair started working
correctly. Two defects, stacked, one masking the other.

---

## 2. The investigation — including the wrong turns

### Wrong turn #1 — "make the repair smarter"

The first instinct after seeing the transparent bite was to close it: inpaint it, or fill it from
neighbouring pixels. A nearest-neighbour colour fill was actually **written and then deleted**,
on the user's call:

> "the fix is ugly. we have an application to generate an image, can't we just use our own tool"

That is the correct instinct and it generalises. The hole is missing *information*, not a
mis-set flag. Any downstream repair is inventing pixels, and inventing pixels is how you get a
smear that looks worse than the hole.

**Lesson: when the data is genuinely absent, fix the step that produced it, not the step that
consumes it.** A repair that fabricates plausible data is a cosmetic patch pretending to be a fix.

### Wrong turn #2 — arguing about the colour instead of testing it

The first proposal was grey. It is a defensible argument (mid-tone, neutral, splits the
histogram) and it is **wrong**, as the user immediately spotted:

> "is grey a good color, for animals, there are many animals with grey color... i want to make
> sure that the grey may fix the white leopard, but what happens to an African Grey Parrot"

Then green — the chroma-key intuition from film. Also plausible; also has counter-examples
(parrots, iguanas, tree frogs).

**What actually settled it was 14 real pets rendered against four backdrops.** Cyan won because
saturated cyan (100, 230, 215) is a colour **no natural animal is**: fur and feather pigments
(eumelanin, pheomelanin, carotenoids) cannot produce it, and structural blue — the closest natural
approach, in a blue jay or a macaw — sits far enough away in hue that the matte still separates.
Even the deliberately adversarial cases held: a **cyan parakeet**, a **green parrot**, a
**peacock**, a **blue jay**.

**Lesson: for a choice with a big blast radius and a cheap test, test it.** Four backdrops × 14
pets was under an hour on two GPUs. The user's framing was exactly right —

> "these tests are cheap compared to what will happen if we implement and find out later that it
> doesn't work"

### Wrong turn #3 — trusting proxy metrics over the image

Several measurement shortcuts produced confident, wrong answers on this bug. They are cataloged
in `learned_matte_measurement_traps_*`; the one-line version is that **spill ratio is meaningless
when the pet's colour is near the backdrop's**, which is precisely the case under investigation.

### Wrong turn #4 — assuming one place owned the colour

`"white background"` was changed in the still template and the fix was declared done. The user
pushed back on principle rather than on evidence —

> "there might be hard coded white background in the code base... this is why i hate hard coded
> items"

— and the sweep found it in **five** places, including `_prep_reference_image`, which pads
uploaded reference photos onto a canvas. That one had *nothing* to do with the prompt and would
have quietly re-created the whole defect for every uploaded-photo pet.

**Lesson: a value that appears once in the file you're editing has appeared four more times
somewhere else.** Sweep on the literal, not on the concept.

---

## 3. Root cause

Matting is edge-finding. birefnet answers "where does the subject stop", and it answers it from
luminance and chroma discontinuity. Where a white pet meets a white field there **is no
discontinuity** — not a weak one, not a hard one, *none*. The model does the only thing available
and returns the drawn outline: contour opaque, interior transparent. A line drawing.

The matte was never wrong. The **render** was under-determined, and the matte reported that
faithfully.

This also explains the confusing pattern in the symptoms: the penguin's black back segmented
perfectly while its white belly dropped, in the same frame, from the same model. The variable is
the pet's colour distance from the backdrop, nothing else.

---

## 4. The fix

**One constant, one owner** — `pet_factory/prompt_templates.py`, chosen because it is pure data
and stays importable on the GPU-less web tier:

```python
STILL_BACKDROP = "flat vivid cyan background"     # what the model is told to draw
STILL_BACKDROP_RGB = (100, 230, 215)              # what we paint when WE make the canvas
```

Both are needed and they are not redundant: the prompt drives the generator, the RGB tuple drives
`_prep_reference_image`'s own padding. Two representations of one decision, in one file, next to
each other.

**All five sites now read the constant** — the base still template, the remix still template, the
curation prompt, `_prep_reference_image`'s canvas, and `factory`'s re-export.

**A guard test pins it**, and — the part that matters — **the guard was verified to fire**: a
re-introduced hardcoded `"white background"` makes `test_prompt_templates.py` fail. An unverified
guard test is a comment with a green checkmark.

**Ship discipline the user set and I should not have needed to be told:** the change is inert
until the fleet is rolled, and the fleet roll waits on the user's own manual runs. Confirmed
fixed, not fleet-rolled, is a legitimate and honest end state for a session.

---

## 5. Verification (proven, not asserted)

**The backdrop matrix — the evidence that chose cyan.** Four backdrops (white / grey / green /
cyan) against a deliberately hostile pet set: white snow leopard, African grey parrot, elephant,
brown bear, penguin, blue jay, macaw, peacock, green parrot, cyan parakeet, otter, corgi, red
panda, tabby. Cyan was the only backdrop with **no failure** across the set. Grey failed the grey
parrot and the elephant; green failed the parrot and the peacock; white failed everything pale.

**End-to-end on a real build, same species that produced symptom #1:**

```
before   filled 45.8% of subject   hard-zero 608 px/frame
after    filled  5.3%              hard-zero   0
```

**Design-axis regression** — the step-2 recolour calibration was tuned against white renders, so
a cyan substrate could plausibly have broken it. Ran the real designer path (`render_design_still`
→ composed design img2img at the clamped strength), same seed, cyan vs white: **recolour still
wins** (a purple corgi is purple) and **cyan does not bleed** into the pet. The calibration holds.

**In the product, by the user, on the real host:** an 8-pose snow leopard built after both fixes,
uploaded to DatsMe, rendered on a live profile at 128px and 256px —

> "it looked really good. i don't see any issues"

That is the verification that counts. Everything above is instrumentation agreeing with it.

---

## 6. Lessons (generalizable)

### On the bug

- **Some defects are under-determination, not error.** The model got an ambiguous input and
  returned an honest answer. Before hardening a consumer, check whether its input actually
  contained the answer.
- **Pick constants against the adversarial case, not the average one.** "Neutral" is the wrong
  goal for a backdrop; "outside the subject's possible gamut" is the right one. Grey is neutral
  and grey animals exist — that is the whole argument.
- **Fixing one defect can unmask another.** Plan for the second symptom and don't read it as a
  regression. The black blob and the transparent bite were the same hole, differently painted.

### On method

- **Cheap experiments beat expensive arguments, and this project can afford them.** Two GPUs,
  ~60 s per pet through the Lab. Any question phrased as "would X work?" should have become a
  render.
- **A magic value gets a name and one owner the first time it is touched** — with a guard test
  you have *seen fail*. Five copies of `"white background"` is what "I'll centralise it later"
  looks like in production.
- **The user's domain intuition caught two of the three wrong turns.** "What about an African
  grey parrot" and "there might be hardcoded white elsewhere" were both correct, both cheap to
  check, and both would have shipped broken otherwise. When someone names a specific
  counter-example, render it before defending the design.

---

## 7. Pointers

- `docs/archive/SPEC_MATTE_BACKDROP.md` — the spec: §3 the constant, §5 the backdrop matrix and the
  14-pet result table, §6.1 the design-axis regression, §8.1 the framing side-effect (assessed
  and accepted)
- `pet_factory/prompt_templates.py` — the single owner
- `pet_factory/tests/test_prompt_templates.py` — the one-owner guard, verified red
- `learned_matte_repair_after_resample_20260727_1720.md` — the defect this one was hiding behind
- `learned_matte_measurement_traps_20260727_1720.md` — the proxy metrics that lied during this
  investigation
