# SPEC — "Draw me, not a dog": person subjects survive the redraw

**Status:** proposed, 2026-07-24. **Rev.1.** Written after a live prod finding: a user uploaded a
selfie, the AI captioner correctly read it as a **`man`** (`ai_usage` all `ok=1`; the reference
record carried `description='man', suggested_subject='man'`), and the pipeline **drew a dog**. The
AI is not the fault — the redraw prompt is. This spec makes the redraw honour a subject the
captioner already supports: a **person**.

**The one-line problem.** `pet_factory/factory.py`'s redraw negative prompt hardcodes
`…deformed, human, person, hands, text`, while the positive prompt says `a cute cartoon man,
exactly man…`. Positive "man" vs negative "no human/person/hands" is a contradiction the model
resolves by drawing a non-human cartoon — an animal. The captioner supports people (by design,
`ai_purposes/pet_likeness.json` returns nouns like `man`/`woman`); the *renderer* never got the memo.

**The one-line fix.** Make the redraw **subject-kind-aware**. The captioner already distinguishes a
person from an animal; carry that `kind` on the reference the way `surface` and `motion_profile`
are carried, and let the renderer pick its prompt from it. **Animals are untouched;** only
person subjects change.

**Amends:** `SPEC_UPLOAD_LIKENESS` §2.1 (the noun → redraw), `SPEC_PET_DESIGNER_FLOW` §7.1
(`_base_sprite`, the one base-sprite selector). **Depends on:** `SPEC_DATSPET_AI_ENGINE` (the
captioner emits the kind), `SPEC_UPLOAD_LIKENESS` §2.5 (the captioner exists).
**Repos touched:** `datsme-pet-factory_wu` only — `pet_factory/` (`ai_purposes/pet_likeness.json`
+ `factory.py`), `webui/` (`app.py`), one pool handler (`pet_preview_handler.py`, v3 → **v4 → a
fleet roll**).

---

## 0. Two facts that decide the whole design

### 0.1 The AI already reads people correctly — the renderer throws it away

The captioner is two purposes (`SPEC_UPLOAD_LIKENESS` §2.5): `image_triage` gates
("a single, clearly-depicted **animal or person**"), then `pet_likeness` names the subject with a
generic drawable noun ("`man`", "`woman`", "`parakeet`"). Both `_doc` blocks already say, in
these words, that "the subject may be an ANIMAL or a PERSON; users animate pets, themselves, and
other people." The classification exists. It reaches the reference record as `description`. Then
`_remix_prompt` wraps it as `a cute cartoon {subject}` and `_img2img_wf` runs it against a
negative prompt that forbids `human, person, hands`. The person is *known* and then *negated*.

### 0.2 `kind` is content, resolved once — never a runtime branch on provenance

This spec introduces exactly one new datum: `kind ∈ {animal, person}`. It obeys the repo's
engine-vs-content rule (global CLAUDE.md; `SPEC_PET_DESIGN_AXES` §3.1 for the precedent):

- **Resolved once, at reference-fill time**, from the captioner — exactly where `surface` and
  `motion_profile` are resolved — and **carried on the reference record**. The renderer *reads*
  `kind`; it never asks "was this an upload? was it captioned?" A build, a preview, and a re-roll
  all read the same field.
- **The engine names no person and no animal.** `factory.py` gains a `kind` parameter and two
  prompt variants; it does not classify, does not special-case "man", does not import the
  captioner. The classification is a *content* contribution from the AI purpose, the way an
  animal's `base.png` is content from `animal_catalog`.
- **Absence means `animal`.** Every door that does not run the captioner (catalog, txt2img, a
  degraded/keyless upload, a typed noun) yields `kind='animal'` — today's exact behaviour. The
  new path is strictly additive; nothing that works today changes.

---

## 1. The finding this spec turns on

`git log -S "human, person"` puts the negative term in the **first commit** (`7b5eeb1`,
2026-07-05, "animal name → pet bundle") — the pure-txt2img era, **before uploads existed**. It
was never about cropping people out of photos. Its job is to stop the *generator* from drawing
**anthropomorphic** animals: "a cute cartoon monkey standing" invites a humanoid mascot with
hands, and the negative suppresses that. Three consequences:

1. **It cannot simply be deleted.** The upload redraw runs at **denoise 0.85** (`_img2img_wf`,
   `UPLOAD_REDRAW_STRENGTH`) — heavy enough that the source barely constrains the output, so a
   monkey/ape upload could return humanoid without the guard. Deleting the term risks the *core
   animal product*. It must be **gated**, not removed.
2. **Cropping does not rescue it.** Isolation (`upload_isolate`) is OFF on prod, and even ON it
   cuts the *output frames* — after the redraw. The order is redraw-then-crop; a "man" already
   turned into a dog cannot be un-dogged by a cutout.
3. **The term is only wrong for one kind of subject: a person.** Which is precisely the datum
   §0.2 adds.

---

## 2. The design

### 2.1 `pet_likeness` returns `kind`

One field on `ai_purposes/pet_likeness.json`'s `output_schema`:

```json
"kind": { "type": "string", "enum": ["animal", "person"] }
```

added to `required`, with a system-prompt sentence: *"`kind`: `person` if the subject is a human
being, otherwise `animal`."* The model already decides this implicitly (it returns "man" vs
"parakeet"); we are only asking it to say so explicitly. `image_triage` is **unchanged** — it
already admits people; the naming purpose is the right owner of the person/animal call. Cost is
unchanged (one extra enum token). A guard test pins `kind` in the schema and `required`.

### 2.2 The reference record carries `kind`

`webui/app.py` `_save_reference(...)` gains `kind: str = "animal"`, stored in the meta JSON beside
`surface`/`motion_profile`/`suggested_subject`. `create_reference`'s upload branch sets it from
the captioner: `kind = (caption or {}).get("kind") or "animal"`. Every other door passes the
default. `_reference_record` need not expose it to the browser (it is a render input, not a UI
choice — the tier-table posture of never shipping engine internals, `SPEC_PET_DESIGN_AXES` §4).

### 2.3 The renderer is kind-gated — the only behavioural change

`pet_factory/factory.py`:

- Split the monolithic `NEG` into a shared base plus a per-kind tail:
  - `NEG_BASE` = everything except the subject-exclusion terms.
  - **animal tail** = `, human, person, hands` — today's exact string, so **animal output is
    byte-identical**.
  - **person tail** = `, animal, fur, snout, tail, paws, muzzle` — the symmetric guard that keeps
    a person from drifting into an animal.
- `_remix_prompt(subject, kind)` and `_base_prompt` gain the kind:
  - **animal** → today's wording verbatim.
  - **person** → a person framing ("a cute cartoon character of a {subject}, a person, side
    profile, full figure, flat shading, white background, storybook style"). Exact wording is a
    **tuning task**, validated on staging against a real selfie before it ships (§5, gate P1).
- `_img2img_wf(prompt, image_path, seed, denoise, neg=NEG_ANIMAL)` takes the negative as a
  parameter; `_base_sprite(…, kind="animal")` and `render_design_still(…, kind="animal")` thread
  it through the *one* base-sprite selector (`SPEC_PET_DESIGNER_FLOW` §7.1), so preview and build
  share it by construction. Defaulting the parameter to `"animal"` keeps every existing caller
  correct without edit.

### 2.4 The pool handler param + the fleet gate

`pool_handler/pet_preview_handler.py`: add `"kind": {"type": "string", "enum": ["animal",
"person"]}` to `params_schema`, pass it to `render_design_still`, bump `version` **3 → 4**. Because
the schema is `additionalProperties:false`, a request carrying `kind` **422s on a v3 node** — the
same fleet gate `isolate_subject` uses. So the web tier sends `kind` only when it is `person`
(an animal is the schema default and need not be sent), and the roll order is the established one:
**both nodes to v4 first (`scripts/roll_pet_fleet.sh`), then the web tier.** `pet_factory_handler`
(the build) also gains `kind`, since a person reference must animate as the person it was drawn as.

### 2.5 Every other door is `animal`, explicitly

Catalog (curated animals), txt2img (door 2 is "type an animal"), a typed upload noun, and any
degraded/keyless upload all resolve `kind='animal'`. This is not a fallback that *loses*
information — those doors carry no person signal — it is the correct value. A person who uploads
with the captioner OFF still becomes an animal, exactly as today; turning the captioner on is what
unlocks person rendering (the same on/off story `SPEC_UPLOAD_LIKENESS` §2.5 already tells).

---

## 3. What this deliberately does NOT fix — and why that is safe

A person subject that draws correctly is **half** of "animate me." The other half is motion, and
it is genuinely separable — the redraw fix ships value on its own (a recognisable person sprite,
and step 2's design changes applied to it) without any of the below.

- **3.1 Person animation (the big one).** There is **no biped/person motion profile** —
  `motion_profiles/` has quadruped (default), avian, aquatic, serpentine, winged_flyer. A "man"
  keyword-resolves to `quadruped`, so a person would **walk on all fours**. Fixing that is a new
  motion profile (`biped.json` + a registry entry + the person keywords), which is a *content*
  add under `SPEC_MOTION_PROFILES` — no engine change — but it is its own review. **Phase 2.**
  Until then, a person animates with quadruped motion: acceptable for a first cut (the sprite is
  right, the gait is wrong), and the honest thing to say in the UI.
- **3.2 Typed-noun person detection.** If the user types "man" into the upload noun field (the
  manual path that *skips* the captioner), `kind` stays `animal`. Classifying a free-typed noun is
  a separate, avoidable can of worms; the auto-caption path is the supported way to get a person.
  Noted, not solved.
- **3.3 Design axes for people.** Step 2's surface axes (coat/plumage/scales) are animal surfaces
  (`SPEC_PET_DESIGN_AXES`). They will simply not apply to a person (the universal axes —
  expression, palette — still do). Person-specific axes (hair, outfit) are future content, out of
  scope here.

---

## 4. Decisions

1. **`kind` lives on `pet_likeness`, not `image_triage`.** Triage is a gate; naming is where the
   subject is classified. One purpose owns the person/animal call.
2. **Two values, no `unknown`.** Absence resolves to `animal` at the record boundary, so the
   engine only ever sees `animal|person`. An `unknown` would just be `animal` with extra branches.
3. **The negative is a base + per-kind tail, not two unrelated strings.** Shared terms stay shared
   (one place to tune "no watermark"); only the subject-exclusion differs. The animal tail is the
   *exact* current string, so a guard test can prove animal output is unchanged.
4. **`kind` is a render input, not a browser control.** The user does not pick "I am a person"; the
   photo says so. Nothing about `kind` reaches the client (tier-table posture).
5. **The fleet rolls before the web tier**, `kind` sent only when `person` — identical to the
   `isolate_subject` gate, so the roll playbook and `roll_pet_fleet.sh` already cover it.
6. **Motion is Phase 2.** The redraw fix is shippable and valuable alone; a person walking like a
   dog is a known, stated limitation, not a blocker.

---

## 5. Build order

**Phase 1 — the redraw (this spec's core).** Animals provably unchanged; people draw as people.
1. `pet_likeness.json`: add `kind` to schema + `required` + system prompt; guard test.
2. `factory.py`: `NEG_BASE` + tails; `_remix_prompt`/`_base_prompt`/`_img2img_wf`/`_base_sprite`/
   `render_design_still` take `kind` (default `animal`); guard test pins the animal path
   byte-for-byte.
3. `webui/app.py`: `_save_reference` stores `kind`; `create_reference` sets it from the caption;
   `_render_still` forwards it; `/api/preview` reuses the reference's `kind`.
4. `pet_preview_handler.py` + `pet_factory_handler.py`: `kind` param, `pet_preview` v3 → v4.
5. **Roll the fleet** (`scripts/roll_pet_fleet.sh`) to v4 — both nodes — **before** the web tier.
6. **Gate P1 (the real test):** on staging, upload a real selfie → the reference draws a
   recognisable **cartoon person**, not an animal; and an animal upload draws **identically** to a
   pre-change baseline (same seed). Tune the person positive-prompt here, on real output, before
   prod.

**Phase 2 — person motion (separate review).** `motion_profiles/biped.json` + registry entry +
person keywords, so a person walks upright. Pure content under `SPEC_MOTION_PROFILES`; no engine
or handler change; no fleet roll.

---

## 6. Guard tests

- **`kind` is in `pet_likeness`'s schema and `required`** — the captioner cannot silently drop it
  (mirrors the existing purpose guard tests).
- **The animal path is unchanged** — `_remix_prompt(x, "animal")` and the composed animal negative
  equal the pre-change constants **byte-for-byte**. This is the test that lets the change ship
  without re-validating every existing animal.
- **`kind` round-trips the record** — a reference saved `person` loads `person`; a reference with
  no `kind` in its meta loads `animal` (back-compat for records minted before this spec).
- **The pool param cap still holds** — `kind` is a bounded enum; the composed prompt's worst-case
  length stays under the handler's 600-char param cap (the `SPEC_PET_DESIGN_AXES` computed guard).
- **Fleet-gate honesty** — a `kind='person'` preview submitted to a v3 node 422s (proves the gate
  is real, not schema-green while jobs die — the 2026-07-15 lesson).

---

## 7. Risks & what to check in review

- **Blast radius is the shared engine.** `factory.py` and both handlers change, so this is a fleet
  roll and a prod deploy, not a config flip. The mitigation is decision 3 + the byte-for-byte
  animal guard: if the animal path is provably identical, the only thing that can regress is the
  new person path, which is inert until a person is actually uploaded.
- **Person-sprite quality is a tuning unknown.** We do not yet know how good a side-profile cartoon
  *person* looks out of Z-Image at 0.85 denoise. Gate P1 exists to answer that on staging before
  prod; if it looks bad, that is a wording/denoise tune, not a redesign.
- **The gait limitation is real and visible.** Shipping Phase 1 alone means a person walks like a
  quadruped. Decide in review: ship Phase 1 with an honest note and fast-follow Phase 2, or hold
  Phase 1 until `biped.json` lands so "animate me" is whole on first contact.
- **Scope creep toward "make me a pet."** A person-that-animates invites hair/outfit axes, name
  overlays, etc. (§3.3). This spec deliberately stops at "the subject you uploaded is the subject
  we draw and animate." Everything past that is a new spec.
- **AI spend.** No new calls — `kind` rides the existing `pet_likeness` response. Zero cost delta.
```
