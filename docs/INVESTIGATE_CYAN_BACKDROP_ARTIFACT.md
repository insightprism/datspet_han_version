# INVESTIGATION — is the cyan backdrop artifact worth fixing?

**Status: PARKED, 2026-07-27.** Raised during the post-implementation review of
`SPEC_MATTE_REPAIR_ORDER` (F1–F4) and `SPEC_MATTE_BACKDROP`. Deferred deliberately: the
product owner looked at the live pet on the DatsMe profile page and could not see the
artifact, so this waits until there is time to look properly at real output. Pick it up when
things settle.

**This is an investigation brief, not a spec.** It asks a question and can answer "no". If it
answers "no", the deliverable is a paragraph in `SPEC_MATTE_REPAIR_ORDER` §3.3 — not code.

**Code is cited by symbol, never by line number.**

---

## 1. Context

The backdrop moved from white to cyan (`SPEC_MATTE_BACKDROP`;
`prompt_templates.STILL_BACKDROP` / `STILL_BACKDROP_RGB = (100, 230, 215)`), and the matte
repair moved before the geometry (`SPEC_MATTE_REPAIR_ORDER` F1). **Both work** — a fresh
`white snow leopard` bundle probes at **1.3 hard-zero px/frame** against the 9,831/frame
defect that started that spec.

An *interaction between them* produces a new artifact. `_repair_matte_holes` fills any
border-unreachable transparent region, including a genuinely enclosed piece of background
(the gap between a tail and a thigh). `SPEC_MATTE_REPAIR_ORDER` §3.3 accepts this explicitly,
reasoning that post-F1 such a region "fills with background colour instead of black" and that
"background-coloured is far less jarring than black."

**That reasoning was written when the background was white.** It is now vivid cyan, so those
regions come out as saturated teal patches on the pet. Neither spec is wrong on its own;
nobody re-read §3.3 after the backdrop landed.

## 2. What was measured (2026-07-27)

On a real shipped bundle — `white_snow_leopard_datsme.zip`, 8 poses × 16 frames, the one
running live on the profile page — counting opaque subject pixels where
`g - r > 40 and b - r > 30`:

| | cyan px |
|---|---|
| **whole bundle** | **2,168** of 2,156,490 subject px (**0.10%**) |
| eat | 869 — worst single frame **640**: the model drew a teal puddle and the matte kept it whole |
| run / play / walk | 410 / 297 / 262 |
| jump / sleep / idle / sit | 200 / 125 / 5 / 0 |

**`scripts/probe_matte_fill.py` calls this bundle `clean`.** Cyan luma is 230, and the
metrics only measure darkness — `hard_zero` needs ≤ `MATTE_ANNIHILATED_LUMA` (8), `glaring`
needs < `MATTE_GLARING_FRACTION` × the pet's median. A bright artifact is invisible to all
three numbers. That blind spot is new and arrived with the backdrop.

**Counter-evidence, and it is the strongest evidence here:** the walk and idle poses were
viewed live on the DatsMe profile page and nothing looked wrong. The haunch patch was found
only by zooming 4× and running a pixel query.

## 3. The question

Two gates, **in order**. Stop at the first that fails. "Not worth doing" is the expected
answer and a successful outcome — do not proceed to code because the earlier steps were
interesting.

1. **Is it visible to a person at real display size?**
2. **If so, can it be fixed reliably without breaking the repair that already works?**

## 4. Step 1 — perceptual (the kill shot, ~30 min)

Measure the pet's **actual rendered size** on the DatsMe profile page from the DOM. Do not
assume — the canvas is scaled, and every number below is meaningless at the wrong size.

- Render the worst `eat` frame (640 cyan px) and a `walk` frame (~56 px) at **exactly** that
  size, no zoom.
- Put each beside the same frame with the cyan pixels made transparent, as a reference for
  what "fixed" would even look like.
- `eat`, `sleep` and `sit` are `runtime_role: timed`; check how often and how long they
  actually play in the DatsMe runtime. An artifact in a pose that shows for two seconds every
  few minutes is not the same finding as one in `walk`.

**If a person cannot pick the artifact out at 1× without being told where to look, report
that and stop.** That is the answer, and §3.3 gets its paragraph.

## 5. Step 2 — incidence (~1 h, only if step 1 shows something)

One pet is not a finding. Cover the range: a pale pet, a dark pet, a bird, and one with a
curled tail or a wide leg gap — that geometry is what creates enclosed regions at all.

The Motion Lab makes each pose ~1 min: type the animal, pick a pose, press **Animate** (it
packs automatically, F4) and read the metrics line under the packed tile.

Report cyan px/frame per pet and per pose. **If this is one bad `eat` render on one pet
rather than a systematic property of the backdrop, say so** — that is a content problem, not
an engine one, and the answer is to redraw a pose, not to change the repair.

## 6. Step 3 — is the signal actually separable? (~1 h, only if 1 and 2 justify it)

**This is the step the reviewer was least confident about, and it must be tested before any
fix is designed.** The proposed fix was: in `_repair_matte_holes`, label the hole regions
(`scipy.ndimage.label` — scipy is already imported for F2) and skip filling any region whose
mean RGB is backdrop-coloured, because such a region is background that happened to be
enclosed.

It rests on an assumption nobody has checked: **that backdrop-coloured and pet-coloured hole
regions separate cleanly.** Test that directly, on real mattes, before writing anything:

- Dump every hole region from ~5 real frames with its mean RGB, its pixel count, and a crop.
- Do the "should skip" and "should fill" populations separate, or overlap?

Three specific risks, each of which can sink the approach on its own:

- **A white animal's shading is often cool blue-grey.** A snow leopard's shadow may sit in
  the same hue band as the backdrop. If so the fix punches real holes in the pet — strictly
  worse than a teal patch, and it would be reintroducing the class of bug F1 just removed.
- **A hole region that is *partly* backdrop and *partly* a real matte miss.** Skipping the
  whole region reintroduces transparency inside the animal. How common is that shape?
- **The backdrop is not a flat key.** Z-Image paints a scene: measured backdrop std-dev
  58–65, cyan ranging RGB(88–104, 208–236, 183–222), and shaded backdrop inside a leg gap is
  darker still. Does any fixed threshold hold across that range?

One point in the fix's favour, worth **confirming rather than assuming**: post-F1 the repair
runs *before* `_fit_square`, so the RGB under a hole is the original ComfyUI colour and has
not been destroyed by the premultiplying resample. The colour signal should be trustworthy at
that point — verify that it is.

**If the populations overlap, report that and stop.** A fix that sometimes eats the pet is
worse than the artifact it removes.

## 7. Step 4 — only if all three pass

Propose the change with a **measurement, not a description**:

- before/after cyan px, per pose;
- before/after `hard_zero` per frame — **it must not regress**, that is the defect F1 fixed;
- the existing suite green (`.venv/bin/python -m pytest pet_factory/tests webui/tests` —
  528 tests as of 2026-07-27).

`_fill_holes_alpha` is the oracle that §5 test 4 compares against byte-for-byte. If the
change makes the two disagree, that is a decision to **surface**, not a test to update.

Note there is also a **detection-only** option, roughly an hour: a `backdrop_px` field on
`MatteDamage` counting opaque subject pixels in the backdrop's hue band, surfaced through
`line()` (which the Lab tile and the probe both already render, so no frontend text change).
It does not remove the artifact — it stops the probe calling those bundles clean. Only worth
it if the answer to §3's gate 1 is "yes, visible" but the answer to gate 2 is "no, not safely
fixable": a defect you have decided to live with is one you should at least be able to see.

## 8. Report back

- **Visible at 1×?** yes/no, with the images.
- **Incidence** across the pets tested.
- **Separable?** yes/no, with the region-population data.
- **Recommendation:** fix / don't fix / fix something else — and why.

If the recommendation is **don't fix**, the deliverable is a paragraph for
`SPEC_MATTE_REPAIR_ORDER` §3.3 recording that the white-era reasoning was re-examined under
the cyan backdrop, what was measured, and that it was accepted again. **That closes the
question**, so nobody reopens it from the same screenshot in three months.
