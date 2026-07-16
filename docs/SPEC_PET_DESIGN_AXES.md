# SPEC — Design Axes: pattern, coat, and expression (animal-aware, and the registry that makes the next one free)

**Status:** rev.3 (2026-07-16)
**Extends:** `SPEC_PET_DESIGNER_FLOW` §4 (the design step) and §7.2 (body shape as content).
**Adds:** three "make it mine" controls to step 2 — **markings/pattern**, **coat type**, and
**expression/mood** — the small registry that lets a *fourth* one (Tier 2: material, aura, …)
ship as data, and the **animal-awareness** that makes the surface control accurate:
a bird is offered feathers, never fur.

**Rev.3 changelog — the variability contract, and closing rev.2's review gaps:**
1. **§12 (new) + §0.9: the variability contract.** A three-tier error taxonomy: variance
   within the request is the product; a modifier the model's prior resists (a purple panda
   rendering grey) is an *acceptable error* with user-held levers; a violated contract —
   including **subject substitution**: a green dragon rendered as a green iguana is an error,
   however coherent the iguana — is a bug. Phase 3's gate now tests the Tier C bar only, and
   the site verbiage is specified (§12.3).
2. **`/api/preview` takes ONE `axis_picks` object, not per-axis `Form` fields** (§4) — rev.2's
   fixed fields meant every new axis was an endpoint edit, contradicting §9's "a new axis is a
   JSON edit". Now §9 is true.
3. **Catalog `surface` is authored at the most specific level with breed inheritance** (§1),
   the way `motion_profile` actually is; the resolver and guards operate on the *resolved*
   surface.
4. **Hardening from review:** the golden test asserts `min_strength` too (§10); the surface
   keyword map is seeded per-word from the motion registry's keyword lists (§3.2);
   `max_concurrent_strong` is a registry field from Phase 0 (§11.6 resolved); the display-name
   honesty quirk is recorded as a decision (§11.7).

**Rev.2 changelog — what animal-awareness changed:**
1. The axes split into **universal** (pattern, expression — every animal) and **surface**
   (fur/feathers/scales — one per animal), where rev.1 made all three flat and agnostic (§0.3).
2. The animal's **surface** is a `animal_catalog` attribute, **not** a motion-profile field,
   and **not** a hard-coded branch. It is resolved at fill time exactly like `motion_profile`
   already is, and carried on the reference record (§3).
3. The **uncatalogued / long-tail** rule is specified: universal axes always; the surface axis
   only when surface is confidently resolved; otherwise omitted, with free text as the escape
   hatch (§3.3). This is the answer to "what if the animal isn't in the catalog."

---

## 0. The core decisions (read this first)

1. **These are step-2 DESIGN modifiers, never step-1 inputs.** Same rule as body shape
   (`SPEC_PET_DESIGNER_FLOW` §0.1): step 1 takes exactly one input — the animal — so a curated
   `base.png` can never be invalidated by a design choice. "Spotted", "fluffy", "grumpy"
   compose into the DESIGN string in `compose_design`, never into the archetype prompt.

2. **They are the same shape as `body_shape` — a design AXIS — so this generalizes
   `body_shapes` into a registry rather than cloning it three times.** Each axis is a curated
   vocabulary of `{key, label, prompt_fragment}` where the default means "change nothing"
   (`prompt_fragment == ""`) and the fragment is server-side content the browser never sees.
   With four axes (body + pattern + coat + expression) and a Tier 2/3 roadmap, this is the
   moment the abstraction is earned, not premature (CLAUDE.md "three instances"). The four test
   questions (§9) fail for a clone-three-modules approach and pass for the registry.

3. **NEW (rev.2): axes are universal or surface-gated. This is the animal-awareness.**
   - **Universal** — pattern (markings) and expression (mood). Every animal has a face and can
     bear markings; shown for all animals, catalogued or not.
   - **Surface** — coat (fur), plumage (feathers), scales (reptiles): mutually exclusive, and
     **exactly one shows**, chosen by the animal's surface. A cat sees coat; a bird sees
     plumage; neither sees the other's. A whole different vocabulary per surface reads truer
     than one "coat" axis with the fur options greyed out on a bird.

4. **The animal's surface lives on the `animal_catalog`, NOT the motion profile.** The instinct
   to key design off "animal type" is right; the motion profile is the wrong home for two
   reasons. (a) *Different reasons to change* (CLAUDE.md's boundary rule): motion owns how an
   animal MOVES (walk/idle, movement class); design owns what it LOOKS like. Tuning a bird's
   flap has nothing to do with its feather options, and they have different owners. Co-locating
   would drag design vocabulary under the motion admin + motion guard tests, so a bad feather
   fragment could break a motion profile's validation. (b) *Too coarse:* motion profiles are
   keyed by **movement class** (quadruped/avian/serpentine), so a Persian and a Siamese share
   one profile — you could never express "Persian defaults to long-haired." The catalog is
   per-**breed**, already the source of truth for animal→type, and already carries the
   `motion_profile` key; `surface` (and optional per-breed design defaults) belong right beside
   it. The catalog is the JOIN; motion and design each stay their own registry, both resolving
   from the catalog's classification. Parallel structure: motion keyed by movement-class,
   design surface keyed by surface, catalog joins both per breed.

5. **Uncatalogued animals fall back to the universal axes, never to a wrong surface.** Surface
   resolves at fill time in three tiers (catalog tag → keyword → unknown), exactly mirroring
   how motion already resolves the long tail. Unknown ⇒ show only pattern + expression; free
   text still covers "with fluffy fur" by hand. Details in §3.3 — this is the case the user
   asked about, and the answer is "two of the three Tier 1 controls stay; only the
   surface-specific one is conditional."

6. **Generation-time cost is zero; the real cost is a calibration pass.** All axis fragments
   ride inside the same 8-step img2img still (`factory.py:139`); the animation and cutout
   stages never see the design prompt, so a 6-modifier design builds in the same ~3 min as a
   3-modifier one. The cost is prompt-attention (more adjectives competing in one still) plus a
   one-time GPU calibration pass (§8 Phase 3) — not more time.

7. **The page-size discipline is a hard constraint.** §4.6 of the flow spec cut the palette
   16→10 for legibility. The new controls sit behind a collapsed "✨ more ways to make it
   yours" disclosure, each a compact `<select>` — lean first paint preserved, depth opt-in
   (§7).

8. **Colour, accessories, free text, strength stay bespoke — they are not axes.** An axis is
   precisely "a curated adjective fragment". Colour has a dual clause + species-conflict
   `min_strength`; accessories have worn-item grammar; free text is unbounded; strength is the
   denoise. Forcing them into the axis shape would fork the schema to fit genuinely different
   cases (CLAUDE.md: diverge only for a real semantic difference).

9. **NEW (rev.3): variability is product; the error bar is the CONTRACT, not the render.**
   Generation is stochastic and the same picks render differently — that is largely the
   product ("you almost get a unique animal"), not a defect, and the flow's economics make it
   honest: a redesign is a ~10 s preview, and the 3-minute paid build happens only after the
   user locks real pixels they have seen. But acceptable-variance must never dilute what the
   user asked for. Three tiers (§12): variance *within* the request is welcome; a modifier the
   model's prior resists (a purple panda rendering grey) is an **acceptable error** — still an
   error, but visible at the cheap step, gracefully degraded, and recoverable with levers the
   user holds; a violated contract — a dead control, an erased pick, a flipped breed, or a
   **substituted subject** (a green dragon rendered as a green iguana) — is a bug. Step 1's
   animal is contract; step 2's modifiers are best-effort with recourse. Phase 3 gates on
   Tier C only.

---

## 1. The architecture — one design-axis registry, joined through the catalog

A pure-data subpackage `pet_factory/design_axes/`, structured like `motion_profiles/` (one JSON
per axis + a `registry.json`), replacing single-purpose `body_shapes/`:

```
pet_factory/design_axes/
  registry.json          # the axes, their order, kind (universal|surface), and composition metadata
  body.json              # migrated from body_shapes — thin/normal/chubby (universal)
  pattern.json           # NEW — markings (universal)
  expression.json        # NEW — mood (universal)
  coat.json              # NEW — fur (surface: "fur")
  plumage.json           # NEW — feathers (surface: "feathers")
  scales.json            # NEW — reptile scales (surface: "scales")
  __init__.py            # resolver (pure stdlib; NO ml imports)
```

**One axis file** (surface axis shown):
```json
{
  "axis": "plumage",
  "label": "feathers",
  "kind": "surface",            // "universal" | "surface"
  "applies_to": "feathers",     // surface axes only: the catalog `surface` value this serves
  "default": "natural",
  "clause_slot": 30,            // composition order (§2); lower = nearer the species noun
  "position": "prefix",         // prefix adjective (default) | suffix phrase
  "min_strength": null,
  "options": [
    { "key": "natural",     "label": "natural",     "prompt_fragment": "" },
    { "key": "iridescent",  "label": "iridescent",  "prompt_fragment": "with iridescent plumage" },
    { "key": "ruffled",     "label": "ruffled",     "prompt_fragment": "with ruffled feathers" },
    { "key": "downy",       "label": "downy",       "prompt_fragment": "with soft downy feathers" }
  ]
}
```

**The catalog gains one attribute** — `surface`, beside the `motion_profile` key, and authored
the way `motion_profile` actually is: **at the most specific level, with breed inheritance**
(rev.3 — rev.2's example implied per-breed authoring everywhere). An animal row sets the
default all its breeds inherit; a breed row may override (a Sphynx diverging from `cat`). The
resolver and every guard operate on the **resolved** surface, mirroring
`resolved_motion_profile`:
```json
{ "key": "cat", "label": "Cat", "motion_profile": "quadruped", "surface": "fur",
  "breeds": [ { "key": "tabby", "label": "Tabby" }, { "key": "siamese", "label": "Siamese" } ] }
```
A guard test (like the one that asserts every `motion_profile` resolves) asserts every catalog
entry's *resolved* `surface` matches a `surface` axis's `applies_to`, so a typo can't ship a
breed whose surface axis silently never appears.

**The resolver** (`design_axes/__init__.py`) generalizes `body_shapes`'s function set —
`list_options(axis)`, `default_key(axis)`, `prompt_fragment(axis, key)`, `is_default(axis, key)`,
`list_axes()` — same never-raises, pure-stdlib, fragment-withheld-from-browser posture. Plus:
`axes_for_surface(surface) → [universal axes…] + [the one surface axis matching surface]`,
or just the universal axes when `surface` is None/unknown.

---

## 2. The axes (content — placeholders; the look owner sets the words, Phase 3 calibrates)

**Universal (all animals):**
- **pattern** (markings): natural · spotted · striped · tuxedo · patches · ombre. Generic words
  read across surfaces (a spotted bird, a striped snake); surface-specific pattern wording
  (e.g. "barred plumage") is a Phase-3-or-later refinement, not now (§10 Q4).
- **expression** (mood): neutral · happy · grumpy · sleepy · mischievous · wide-eyed. Likely a
  **suffix** ("…, with a grumpy expression") — `position` supports it, Phase 3 measures it.

**Surface (exactly one, by the animal's `surface`):**
- **coat** (`applies_to: fur`): natural · fluffy · sleek · long-haired · shaggy · curly.
- **plumage** (`applies_to: feathers`): natural · iridescent · ruffled · downy · glossy.
- **scales** (`applies_to: scales`): natural · glossy · matte · patterned.

Every axis ships a `natural`/`neutral` default with fragment `""`, so an un-modified pet
composes exactly as today. `compose_design` clause order (§ below) is calibrated per axis via
`clause_slot`.

`compose_design` becomes **slot-ordered** (rev.1's design, unchanged): colour's inline
`vivid {color}` lead, then selected axis prefix-fragments in ascending `clause_slot`, then
accessories (`wearing …`), free text, and colour's terminal `recolored entirely {color}` LAST
— the calibrated tail. Suffix-position axes append after the species phrase. `min_strength` is
the max of colour's rule and every selected axis's declared `min_strength`. Body's current
prepend + 0.9 silhouette rule becomes data on `body.json`, so existing output is byte-identical
(golden test, §8 Phase 0). `registry.json` also carries `max_concurrent_strong` from Phase 0 —
the §11.6 soft-cap on concurrent strong modifiers, shipped unset until Phase 3 measures the
real ceiling (a data edit, not a schema change, when it does).

---

## 3. Surface resolution — at fill time, like motion, carried on the reference

The animal's surface is resolved ONCE, at step 1 (`/api/reference`), and stored on the
reference record — exactly where and how `motion_profile` is resolved today
(`webui/app.py:663-712`: catalog door pins it from the catalog, txt2img/upload leave it for
keyword resolution). This keeps step 2 from re-deriving it and keeps one resolution path.

### 3.1 Catalog door (curated animal) — confident
`surface` = the catalog breed's `surface` tag. A Persian entry says `fur`; a parrot says
`feathers`. Breed-accurate by construction.

### 3.2 Typed animal (the long tail) — keyword-resolved
No catalog entry, so resolve from the name, the same philosophy motion already uses. A small
`surface` keyword map (bird/jay/parrot/eagle → feathers; snake/python/lizard/gecko → scales;
otherwise the mammal-defaulting fur signal). Confident matches get their surface axis; the map
is content, extendable without code.

**Seed the map from the motion registry's keyword lists** — `avian.json` and `serpentine.json`
already enumerate ~35 bird/snake words — but assign surfaces **per word, never per movement
class**: `winged_flyer` (dragon=scales, bat=fur, butterfly=neither) and `aquatic` (fish=scales,
dolphin=skin) are mixed-surface classes, which is exactly why surface is not a motion field
(§0.4). Borrow the vocabulary, not the classification. Typed animals that resolve to null are
**logged**; that log is the map's growth list, turning each miss into a one-line content edit.

### 3.3 Unknown — universal axes only (the answer to "not in the catalog")
When neither the catalog nor the keyword map is confident ("a clockwork octopus", "a griffin",
or a bare photo upload), `surface` is **null**. The design step then shows **only the universal
axes** — pattern and expression — and **no surface axis at all**. It never guesses fur onto an
unknown creature. Free text is the escape hatch: "with fluffy fur" typed by hand still works,
exactly as it does today.

So an uncatalogued animal keeps two of the three Tier 1 controls (pattern, expression) and
loses only the surface-specific one — never the whole feature, and never a wrong option.

### 3.4 Upload door
Same as unknown (§3.3): a photo carries no reliable surface signal → universal axes only. If
the user also typed an animal name, §3.2's keyword map may promote it.

---

## 4. The web tier

- **`GET /api/design-axes?reference_id=…`** replaces `GET /api/body-shapes`. The **server**
  reads the reference's resolved `surface` and returns only the applicable axes — the universal
  ones plus the single matching surface axis (or none) — as `{axis, label, kind, default,
  options: [{key, label, is_default}]}`, fragments withheld (tier-table posture). The browser
  renders what it is handed; surface gating is server-owned, consistent with how the server
  owns motion resolution. A new axis or a new surface appears with no endpoint change.
  `/api/body-shapes` stays a thin alias for one deprecation cycle.
- **`POST /api/preview`** (`webui/app.py:787`) gains **one** field: `axis_picks`, a
  JSON-encoded object `{axis_key: option_key}` (rev.3 — rev.2's fixed per-axis `Form` fields
  made every new axis an endpoint edit, contradicting §9). Validation is registry-driven:
  unknown axis keys and unknown option keys are ignored (the body_shapes never-raises
  posture), and a surface-axis pick that doesn't match the reference's resolved surface is
  ignored (defense in depth — the menu already hid it). The existing `body_shape` field stays
  a server-side alias for `axis_picks["body"]` for one deprecation cycle, mirroring the
  `/api/body-shapes` alias. The "designing nothing is adopting" guard (`:820`) widens to count
  a non-default pick on any axis.
- The reference record gains `surface` (resolved at fill, §3); picks ride the existing design
  record contract (§7.3). No new store, no new handle type.

---

## 5. The frontend

`DesignStep.tsx` already renders body shape by mapping `/api/body-shapes` with zero hardcoded
keys. Extend that: fetch `/api/design-axes?reference_id=…` once and render the returned axes.
Body stays the inline chip row; pattern/expression/(the one surface axis) render as compact
`<select>`s inside the disclosure (§7). Because the **server** already filtered by surface, the
frontend has no animal logic — an uncatalogued animal simply receives fewer axes and renders
fewer controls. `designFlow.ts` carries the picks; `api.ts` gains the `axis_picks` field and the
`DesignAxis[]` type. No engine, no other page.

---

## 6. Strength interaction

Unchanged mechanism (`SPEC_PET_DESIGNER_FLOW` §4.5): an axis whose change fights the source
declares `min_strength: 0.9` in its JSON. The existing "using strong — required for this
change" notice covers it. **Measured (Phase 3, 2026-07-16):** coat, plumage, and scales all
carry 0.9 — texture asks fight the authored surface and lose at 0.85; expression and pattern
carry none (expression's weakness on realistic styles is semantic, and pattern's failures on
strongly-marked animals are Tier B by choice — see §8's results).

---

## 7. UX / the page budget

Per §0.7: the new controls sit behind a collapsed **"✨ more ways to make it yours"**
disclosure under the existing controls. First paint of step 2 is unchanged. Opened, it adds at
most three compact `<select>`s (pattern, expression, and the one surface axis) — within the
measured budget, and fewer for an uncatalogued animal (no surface axis).

---

## 8. Phasing / build order

| Phase | Scope | Gate |
|---|---|---|
| **0** | `design_axes` registry + slot-ordered `compose_design`; migrate `body_shapes` → `body.json`; `/api/design-axes` (alias `/api/body-shapes`). No new axis, no behavior change. | Golden test: every existing colour/shape/accessory/text design composes byte-identically; suite green; `import numpy` still fails in the web tier. |
| **1** | Surface plumbing: `surface` tag on the catalog + guard test; fill-time surface resolution (catalog → keyword → null) stored on the reference; the axes-for-surface filter in `/api/design-axes`. | A catalog cat resolves `fur`; "a blue jay" resolves `feathers`; "a clockwork octopus" resolves null → universal axes only; upload → universal only. |
| **2** | The axes as data: `pattern.json`, `expression.json`, `coat.json`, `plumage.json`, `scales.json` (placeholder fragments); the `Form` fields; the disclosure UI. | A pattern-only / surface-only / expression-only preview renders; each default a true no-op; the right surface axis shows per animal, none for unknown. |
| **3** | **GPU calibration pass** — tune fragments, `clause_slot`, `position` (esp. expression), per-axis `min_strength`, and `max_concurrent_strong` on real 160 px renders across surfaces. Scripted, not eyeballed: the matrix renders via the ~10 s preview path into a contact sheet (GPU cost ~20–40 min; human review is the real cost). | **The Tier C bar (§12.4):** on a fixed matrix (a cat, a bird, a snake, an unknown), every selectable option is **live** (visibly changes the still), **non-destructive** (doesn't erase colour/accessories/another axis), and **subject-preserving** (the corgi is still a corgi; the dragon never becomes an iguana); the bird never shows fur. Unexpected-but-alive renders PASS — Tier A/B deviation is not a gate failure. |

Phase 0 is a pure test-guarded refactor and ships alone. Phase 1 is invisible (no new UI, just
resolution + a filtered endpoint). Phases 2 and 3 ship together behind the disclosure — an
un-calibrated axis is worse than none.

**Phase 3 RAN 2026-07-16 — PASSED the Tier C bar,** on a 76-cell fixed-seed matrix (curated
tabby / txt2img blue jay / txt2img python / "a clockwork octopus") plus a 14-cell follow-up at
0.9. Results, now carried as data in the axis files' `_doc`s:

- **Expression is the strongest axis** (inverting this spec's own risk call): all five options
  live at 0.85 on every cartoon-styled animal; suffix position confirmed (§11.3). On the
  realistic-styled jay only grumpy+sleepy read — semantics (a beak can't smile), not strength.
- **coat / plumage / scales got `min_strength: 0.9`, measured** — at 0.85 the authored surface
  won (coat 2/5 live, plumage 0/4, scales 1/3); at 0.9 everything took with identity intact.
  §6's prediction confirmed. Plumage's options read similar to each other at 0.9 — live, but
  the vocabulary wants sharper words (§11.2).
- **pattern stays unclamped, deliberately**: live at 0.85 on plainly-marked animals (patches
  renders as a charming patchwork on the octopus — Tier A) and prior-locked on tabby stripes /
  jay wings — Tier B, the strength slider's territory. Forcing 0.9 would cost distinctive base
  details exactly where 0.85 already works (see next bullet).
- **0.9 wins fights but erodes fine base detail**: the clockwork octopus lost its clock in the
  0.9 stack; the python's palette drifted at body-thin's forced 0.9. The §12.3 pre-build
  verbiage and the strength control's honesty matter for exactly this reason.
- **`max_concurrent_strong` measured null**: the stacks (colour + accessory + pattern + surface
  + expression, ± body at 0.9) showed no destructive interference on any matrix animal; clause
  ordering held everywhere (no erased picks). No subject substitution in any step-2 cell.
- **Step-1 observation, out of this spec's scope but recorded**: the txt2img "python"
  *archetype* drew a legged cute reptile — subject drift at the fill step, disclosed by the
  work→look→lock flow (the user sees the base before locking), but relevant to any future
  front-door quality work.

---

## 9. The four test questions

- **New variant → engine change?** No. A new option, a new axis, or a new surface (a "shell"
  axis for turtles) is a JSON edit + a catalog tag. `compose_design` and `DesignStep` are
  axis-count- and surface-agnostic, and (rev.3) so is `/api/preview` — `axis_picks` is one
  registry-validated object, so a new axis adds no `Form` field (§4).
- **New feature → touch unrelated files?** No. An axis is one file + a `registry.json` line; a
  surface is one catalog field. Motion is untouched.
- **Third-party integration → modify owned paths?** N/A.
- **Bug in one variant → debug shared code?** Isolated. `plumage.json` can't affect `coat.json`
  or any motion profile — the design and motion registries are separate, joined only by the
  catalog's classification.

---

## 10. Guard tests

- **Golden composition (Phase 0, load-bearing):** existing inputs → identical `compose_design`
  output — the **full returned tuple, `min_strength` included**, not just the composed string.
  The 0.9 silhouette rule moves from code to `body.json` data in this migration; a migration
  that composed identical strings while dropping the 0.9 would silently weaken every
  body-shape render. The migration changes no pixels.
- **Per-axis default is a no-op;** **every selectable option changes something** (empty
  fragment on a non-default option fails the build) — generalized from `test_body_shapes.py`.
- **Catalog surface integrity:** every catalog `surface` resolves to a surface axis's
  `applies_to`; every surface axis's `applies_to` is a real surface value. A half-formed pair
  fails the build (the registry rule).
- **Surface resolution:** catalog animal → its tag; a keyword-mapped name → its surface; an
  unmatched name and an upload → null → universal axes only, never a surface axis.
- **Endpoint gating:** `/api/design-axes` for a bird returns plumage and NOT coat; for an
  unknown animal returns only universal axes; never serializes a `prompt_fragment`.
- **`axis_picks` robustness:** unknown axis keys, unknown option keys, and a surface pick that
  doesn't match the reference's resolved surface are ignored, never 500 (the body_shapes
  never-raises posture, §4).
- **GPU-less posture:** `design_axes` imports pure stdlib only (extends the existing guard).

---

## 11. Open questions

1. **Per-breed design defaults / availability.** The catalog is per-breed, so it CAN carry
   "Persian defaults to long-haired" or "Sphynx offers only hairless" — the accuracy that
   motion-profile granularity could never reach (§0.4). Worth doing? It is additive: an
   optional `surface_default` / `surface_options` override on the catalog entry (the field
   names `SPEC_PET_DESIGN_AXES_ADMIN` §1.2 uses), read by
   `/api/design-axes`. Deferred until the base feature lands, but the structure is chosen so it
   slots in as data.
2. **Vocabularies are content — who owns the words?** §2 is engineering placeholders; the look
   owner sets options + copy; Phase 3 calibrates against renders.
3. **Expression prefix or suffix? — RESOLVED (Phase 3, 2026-07-16):** suffix, confirmed on
   renders; the axis is the strongest of the set at 0.85 on sprite-styled animals.
4. **Surface-specific pattern vocabulary.** Pattern is universal with generic words now; "barred
   plumage" vs "tabby stripes" could later make pattern itself surface-aware (its `options`
   filtered by surface, reusing the same `applies_to` mechanism). Deferred — generic works.
5. **Premium axes.** Material (Tier 2) is the monetization candidate; the registry is agnostic,
   so pricing attaches later via the tier table without touching axes.
6. **Combination ceiling — RESOLVED (rev.3): the cap is a registry field from Phase 0.**
   Colour + up-to-3 axes + accessories + free text is a long adjective pile an 8-step still may
   not resolve cleanly. `registry.json` carries `max_concurrent_strong` from Phase 0 (shipped
   unset), so the ceiling Phase 3 measures is a one-line data edit, not a schema change. Note
   that §12's variability posture loosens the pressure here: an adjective pile-up that renders
   *unexpectedly* is Tier A; only one that goes destructive or incoherent needs capping.
7. **Display-name honesty (rev.3 — recorded as a decision, not an accident).** `compose_design`
   names the pet from the picks ("Purple Panda") even when the model's prior resisted the
   recolor (§12 Tier B) — the label can claim what the render refused. Accepted for now: the
   `name` field lets the user rename, and "a grey panda named Purple" is arguably charming.
   Revisit if users read it as a bug; the fix would be deriving the display name from what the
   user typed rather than from the picks.

---

## 12. The variability contract (rev.3) — which misses are errors, and what we promise

Generation is stochastic: the same picks render differently run to run, and modifiers can land
in unexpected ways. Most of that is not a defect — it is the product ("you almost get a unique
animal"), and the flow's economics make it honest: a redesign is a ~10 s preview render, and
the 3-minute paid build happens only after the user **locks real pixels they have seen**
(`SPEC_PET_DESIGNER_FLOW`'s lock gate). Variance is front-loaded into the cheap loop.

But "variance is fun" must never dilute what the user actually asked for. Not getting your
request is still not getting your request — some misses are simply more acceptable than
others, and the tiers below draw the line that the calibration gate (§8 Phase 3) and the site
copy (§12.3) both use.

### 12.1 The three tiers

- **Tier A — variance within the request (the product).** The spots landed differently than
  imagined, the fluff is wilder, the colour has an odd sheen. The subject is right, every pick
  is visibly honored, the rendering is the model's take. Welcome, never gated, and what the
  site copy celebrates.

- **Tier B — prior-resistance (an acceptable error — but still an error).** The model's prior
  fights a modifier and wins at the chosen strength: a **purple panda renders grey**, because a
  panda "is" black-and-white the way a blue jay "is" blue — and the codebase has already met
  this class (the emerald blue jay held blue at 0.85 and flipped at 0.9; `webui/app.py:200`).
  Acceptable because it fails *well*: visible at the cheap preview (never after payment),
  degraded *gracefully* (toward a coherent real animal, never a smear — the prior doubles as a
  coherence floor), and recoverable with levers the user holds (the strength slider, redesign,
  free text). The blue-jay evidence shows the fight is usually winnable at 0.9, so the site
  copy points at the lever (§12.3) instead of apologizing. Acceptable ≠ ignored: calibration
  still reduces Tier B where a `min_strength` declaration can (§6); we just don't block launch
  on eliminating what generation can't guarantee.

- **Tier C — contract violations (bugs; the calibration and guard bar).** Four, and only four:
  1. **Dead control** — a pick changes nothing. The guard "every selectable option changes
     something" (§10) is the build-time face of this; calibration is the render-time face.
  2. **Erased pick** — a new modifier silently deletes an earlier one the user already saw
     working. The `clause_slot` ordering work (§2) exists for this.
  3. **Identity flip** — a curated breed stops being that breed at forced strength. The vetted
     corgi is the one thing in the flow we guaranteed.
  4. **Subject substitution** — the render migrates to a *different animal* than the user
     named: **a green dragon rendered as a green iguana is Tier C**, however coherent the
     iguana and however much someone might squint it into a dragon. The green may lose
     (Tier B); the dragon may not.

### 12.2 The rule that makes the fuzzy cases decidable

**Step 1's animal is CONTRACT; step 2's modifiers are BEST-EFFORT with recourse.** This is
§0.1's boundary restated for errors: the subject noun must survive every design choice and
every strength, while the adjectives are negotiated with the model, with the user holding the
dial. When a case still feels fuzzy, classify by the user's plausible reading: "a fun take on
what I asked for" is Tier A/B; "that is not what I asked for" is Tier C.

### 12.3 The site copy (a promise, not a disclaimer)

Two placements, written to sell the same fact a disclaimer would apologize for:

- **Step 2, near the preview:** "every pet comes out one-of-a-kind — don't like this one?
  redesign in seconds." Plus the Tier B lever, shown where the miss is experienced: "colour
  didn't take? some animals hold on to their natural look — push the strength up and try
  again."
- **Before the paid build:** the animation stage (Wan I2V) generates motion *from* the locked
  still and adds its own variance on top — the one place "you saw what you locked" is not the
  complete story. One line of expectation-setting belongs at the build button, not only at
  step 2.

### 12.4 What this changes in Phase 3

The gate tests **Tier C only**: every option live, non-destructive, subject-preserving (§8).
An option that renders unexpectedly-but-alive passes — so fewer options get cut and the
vocabulary ships richer than a "renders exactly as named" bar would allow. Tier B is measured
and mitigated (per-axis `min_strength`), not eliminated.

---

### Appendix — grounding (verified 2026-07-16)

| Claim | Evidence |
|---|---|
| Body shape is already a step-2 design axis with a server-side fragment | `pet_factory/body_shapes/__init__.py` |
| `compose_design` is the one composition point; order is calibrated | `webui/app.py:208-266` |
| Design picks enter at `/api/preview`, redraw the still, return a reference | `webui/app.py:787-848` |
| Step 1 (`/api/reference`) resolves `motion_profile` at fill; carries no design | `webui/app.py:663-712` (catalog pins motion_profile; txt2img/upload leave it None) |
| Catalog carries a `motion_profile` key per breed; a guard asserts it resolves | CLAUDE.md (animal_catalog) + `pet_factory/tests/test_animal_catalog.py` |
| Motion is keyed by movement class (quadruped/avian/serpentine), coarser than breed | CLAUDE.md (motion_profiles); `tiers.json` `_doc` |
| Fragments are withheld from the browser (tier-table posture) | `body_shapes/__init__.py:59-72` |
| `body_shapes` is pure-stdlib for the GPU-less tier | `body_shapes/__init__.py:28-29` |
| Default fragment `""` and "selectable ⇒ non-empty" are guard-tested | `pet_factory/tests/test_body_shapes.py:21,59` |
| Modifiers ride the 8-step img2img still; animation is downstream | `pet_factory/factory.py:139`; CLAUDE.md pipeline note |
| The page was deliberately trimmed for legibility (16→10 palette) | `web/src/app/design/general/DesignStep.tsx:11-27` |
| Tier B "prior-resistance" is already documented empirically (blue jay held blue at 0.85, flipped at 0.9) | `webui/app.py:196-205` (`_COLOR_WORDS` note) |
