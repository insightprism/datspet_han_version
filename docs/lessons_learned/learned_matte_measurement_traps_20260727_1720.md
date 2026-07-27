# Lessons Learned — four proxy metrics that each gave a confident wrong answer about the same image

**Date:** 2026-07-27 · **Area:** matte diagnostics — `scripts/probe_matte_fill.py`,
`factory.matte_fill_damage`, and the throwaway scripts written during the black-blob /
backdrop investigation · **Severity:** medium (no shipped defect; cost was wasted cycles and
one nearly-shipped wrong conclusion) · **Time cost:** roughly a third of two sessions.

**One-line summary:** during an image-pipeline investigation I reached for a cheap numeric proxy
four separate times instead of looking at the picture, and **every one of them was wrong** — each
in a way that read as a clean, decisive result. In an image pipeline the image is the ground
truth; a metric is a hypothesis about the image, and it needs its own verification before it is
allowed to settle anything.

---

## 1. Symptoms

There was no user-facing bug here. The symptom was **my own confident wrong answers**, four
times, on the same investigation:

| # | The proxy | What it reported | What was actually true |
|---|---|---|---|
| 1 | Brightness flood-fill as "is this pixel background?" | "the pet has been separated cleanly" | The pet was a line drawing — outline opaque, interior transparent |
| 2 | Repainting an existing frame's background to test a new backdrop | "cyan behaves the same as white" | Meaningless — the *matte* had already been computed from the white render |
| 3 | Cyan-spill ratio inside the subject | "no spill, backdrop is clean" | The pet under test was cyan-adjacent, so pet and spill were indistinguishable |
| 4 | Concavity via `binary_closing` | returned **negative** area — impossible | The structuring element was larger than the features being measured |

Trap #4 is the useful one, because it was *self-evidently* broken: a negative area cannot exist,
so it announced itself. Traps #1–#3 all returned numbers that were plausible, in-range, and
wrong — those are the dangerous kind.

Each of the four was caught the same way: by opening the image.

---

## 2. The investigation — including the wrong turns

### Trap #1 — a proxy for the thing, used as the thing (twice)

Needing "how much of the subject did the matte drop", I flood-filled from the frame border using
a brightness threshold and called everything reached "background". On a white backdrop that is
almost a definition of the subject — *almost*. The pet's white belly is above the threshold, so
the flood ran straight through it and counted the pet as background. The metric said the matte was
clean on the exact frames where the matte had failed hardest.

I then made the same mistake a second time, on a different frame set, before recognising the shape
of it.

**Lesson: a proxy inherits the assumption it was built on, and the assumption fails first in
exactly the case you are investigating.** Brightness-as-background assumes the subject is darker
than the field, which is precisely what a white-pet-on-white bug violates.

### Trap #2 — testing the input by editing the output

To ask "would cyan segment better?", I took an existing rendered frame and repainted its white
background cyan, then re-ran the matte.

This tests nothing. The frame's pixels — its edges, its contrast, its lighting — were all produced
by a model that was *told* to draw on white. Repainting the field afterwards changes the field's
colour and nothing about the boundary. The only honest test is a **re-render** with the new
backdrop in the prompt, which is what the eventual 14-pet matrix did.

**Lesson: to test an upstream change, re-run from upstream.** Simulating it downstream tests your
simulation.

### Trap #3 — a metric whose denominator collapses in the case under test

"Cyan spill" — the fraction of subject pixels that are cyan-ish — is a reasonable backdrop-bleed
metric for a brown dog. Applied to a **cyan parakeet**, which was in the test set *specifically*
because it is the adversarial case, it cannot distinguish spill from plumage. It returned a clean
number that meant nothing.

**Lesson: check that a metric is still well-defined on the adversarial input.** The cases you
added to the suite because they are hard are the cases most likely to break the measurement, not
just the code.

### Trap #4 — a measurement with an unvalidated parameter

`binary_closing` with a structuring element bigger than the features being closed produced a
negative "concavity area". The impossible value is what exposed it; had the element been slightly
smaller the number would have been merely wrong.

**Lesson: sanity-bound every derived metric — areas ≥ 0, fractions in [0,1], counts ≤ total — and
make a violation loud.** #4 caught itself only because the violation was arithmetically obvious.

### The fifth trap, and the biggest — a measured difference is not a product problem

Late in the work, framing analysis showed the new backdrop produced base stills whose subject
occupied **~40% less area** than before. Real, reproducible, and I escalated it into a spec item
(§8.1) with options for the user to choose between.

The user's response was the correction:

> "it doesn't make any sense why it would be drawing smaller. you do not know the root cause and
> asking me to make a decision"

and then, cutting deeper:

> "does this base even hit the design pet application. it has never hit once, so we are trying to
> fix something that is never used"

That was right. Chasing it down: the base still is a **reference** for the design page, it never
becomes a sprite, every render is a *downscale* from a 256px cell (so no quality is lost), and
pets render mobile-first at ≤64px. The user then closed it with actual evidence — a real
snow-leopard bundle on a live DatsMe profile at 128px and 256px:

> "it looked really good. i don't see any issues"

A measured 40% is not a defect until it changes something a user sees. I had a number and turned
it into a decision request without first establishing that the number mattered.

**Lesson: before escalating a measurement, trace it to a user-visible consequence. If you can't,
you have a fact, not a finding.** And a corollary the user stated directly: presenting options
*is* asking someone to decide without a root cause. Find the mechanism first; then there is
usually only one option.

---

## 3. Root cause

Every one of these came from the same trade: rendering an image and looking at it costs ~60
seconds, computing a number costs ~1 second, so I reached for the number. That trade is fine when
the metric is validated. It is a trap when the metric is *invented for this investigation* — which
all four were — because then the metric is an untested hypothesis about an image, being used to
avoid looking at the image.

Compounding it: this pipeline had **two stacked defects** (mis-ordered matte repair, and an
unsegmentable backdrop). Ambiguous evidence is exactly the condition under which a plausible
metric is most persuasive and least reliable.

---

## 4. The fix

**A real damage metric, owned by the engine, not by a script.** `factory.matte_fill_damage()` +
`MatteDamage` — it measures the actual quantity of interest (how many subject pixels were
*hard* holes, alpha ≈ 0, before repair) rather than a proxy for it, and it is the same code the
production warning path (F3) uses. `scripts/probe_matte_fill.py` reads it and prints a per-pose
table with a per-frame verdict column, so the number always arrives attached to *which frame*.

**Contact sheets as the default output of any visual question.** When the user asked

> "these are numbers. how can i visually see them. so i can give you what i recommend"

that was the turning point of the whole session. Every subsequent comparison — backdrop matrix,
tabby candidates, design-axis A/B — produced a labelled contact sheet, and the wrong turns
stopped.

**A verdict column, not just a value.** A raw fill percentage means nothing without knowing
whether 23% is fine (it was, for the otter) or catastrophic. The probe prints the threshold
judgement next to the number.

---

## 5. Verification (proven, not asserted)

- **The metric that replaced the proxies was itself checked against ground truth**: the vectorised
  repair is **byte-identical to the BFS oracle on 16/16 real alpha channels**, so the number the
  probe reports is the number the shipped code produces.
- **The proxies were each falsified by the image, not by argument.** #1 and #3 by opening the
  frame; #2 by re-rendering properly and getting a different answer; #4 by an impossible value.
- **The §8.1 escalation was closed by the user's own live render at 128px and 256px** — the
  strongest available evidence, and stronger than any measurement I had produced about it.

---

## 6. Lessons (generalizable)

1. **In an image pipeline, the image is ground truth.** Any metric is a hypothesis about the
   image and needs verifying before it settles a question.
2. **A new metric gets one validation against a known case before it is trusted.** Run it on an
   input whose answer you already know. All four traps would have died in seconds.
3. **Proxies break first on the case you are investigating.** The assumption behind the shortcut
   and the assumption the bug violates are usually the same assumption.
4. **Sanity-bound derived values and make violations loud.** The only trap that caught itself is
   the one that produced an arithmetically impossible number.
5. **Test upstream changes upstream.** Editing the output to simulate a different input tests the
   simulation.
6. **A measured difference is not a defect until it reaches a user.** Trace the consequence before
   escalating, and never convert an unexplained number into a menu of options for someone else to
   pick from.
7. **When someone asks to see it, that is not a detour — it is the faster path.** The switch to
   contact sheets ended the wrong turns.

---

## 7. Pointers

- `scripts/probe_matte_fill.py` — the damage probe with the per-frame verdict column
- `pet_factory/factory.py` — `matte_fill_damage()` / `MatteDamage`, the metric's one owner
- `docs/SPEC_MATTE_BACKDROP.md` §5 (the 14-pet matrix), §8.1 (the framing side-effect, assessed
  and accepted)
- `learned_matte_repair_after_resample_20260727_1720.md` and
  `learned_white_backdrop_unsegmentable_20260727_1720.md` — the two defects being investigated
  while these traps fired
