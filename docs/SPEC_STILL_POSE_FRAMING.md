# SPEC — Still Pose & Framing (deliver the pose the profiles already know, and stop assuming feet)

**Status:** proposed, rev.1 (2026-07-30)
**Grounds:** the 2026-07-30 "prod dragonfly is ugly, staging is good" investigation (§0.1 —
recorded so nobody re-derives it).
**Builds on:** `docs/archive/SPEC_MOTION_PROFILES.md` (the profile registry that owns
`base_pose`), `SPEC_BUNDLE_MOTION_CONTRACT` §3.1 (what `base_pose` means),
`docs/archive/SPEC_MATTE_BACKDROP.md` (the backdrop clause this spec must not disturb),
`SPEC_PET_DESIGNER_FLOW` §5.1/§7.1 (the preview↔build parity contract this spec repairs on
the pool path).
**Counterpart precedent:** the `upload_isolate` v3 roll (SPEC_UPLOAD_LIKENESS §2.2 + the
2026-07-23 fleet incident baked into `scripts/roll_pet_fleet.sh`) — this spec ships the same
shape of change: an optional pool param, a handler version bump, a fleet gate.

> **Why this is a spec and not a patch.** The delivery half (§3) is mechanical. The prompt
> half (§2) is **empirical**: every wording decision here changes what a diffusion model
> draws, and this pipeline's history says intuition loses to renders — the dilution bug
> ("standing side profile" → a sitting cat, three seeds of three,
> `prompt_templates.py:103-113`), the backdrop saga (white → line-drawing mattes,
> SPEC_MATTE_BACKDROP), and the proxy-metrics lesson (brightness/spill metrics all gave
> wrong answers; only looking at the image worked). So §2's wording ships **only through
> §4's contact sheet**, and this spec expects **rev bumps as renders overturn choices**.
> Each overturned choice gets a changelog entry with the seed and sheet that killed it.

---

## §0 — The two defects

### §0.1 The diagnosis this spec descends from (recorded, do not re-derive)

Prod and staging drew visibly different dragonflies. Traced 2026-07-30: **both tiers were
byte-identical** (commit `b80df7f4`, same `PET_GEN_BACKEND=pool`, same `POOL_URL`, same app
key), both jobs carried the identical params `{"description": "dragonfly"}`, and the pool DB
(`/var/www/pool/pool.db`, `jobs.node_id`) shows **every dragonfly job from both
environments ran on the same node, `dual-nvidia-pet`, minutes apart**. The only free
variable was the seed (`factory.py:990` — `random.randint(1, 2**31)` when none is passed,
and the preview handler passes none). Prod drew ~8 samples, staging 2; staging got lucky.
**There was no prod defect.** The systematic ugliness (fat upright body, planted legs,
ground shadow) traced instead to the prompt both environments send — defect §0.2.

### §0.2 Defect A — the pool never receives the pose (delivery)

`motion_profiles/` already owns a correct, per-body-type `base_pose`:

| profile | declared `base_pose` |
|---|---|
| `aquatic` | swimming, body horizontal and level in the water, tail trailing behind, fins out to the sides, **no legs** |
| `avian` | standing upright on two legs, wings folded |
| `humanoid` | standing upright on two legs, arms relaxed at the sides |
| `primate` | standing on all fours in a knuckle-walk stance, torso semi-upright, long arms reaching down to the ground |
| `quadruped` | standing on all fours, alert |
| `serpentine` | coiled at rest with head and upper body raised, tongue flicking, **no legs** |
| `winged_flyer` | standing with wings folded against its back |

But on the pool path — **which is prod AND staging** — none of it is delivered:

- `make_pet_zip` resolves the profile itself on the worker and passes
  `base_pose=profile.base_pose` (`factory.py:1126`). Correct.
- `render_design_still` expects to be *told* (`base_pose="standing"` parameter default,
  `factory.py:1012`); the `pet_preview` handler calls it bare, and the web tier **cannot**
  send the pose: the handler schema is `additionalProperties: false` with no `base_pose`
  property (the documented gap, `webui/app.py:887`).

So every pooled archetype, step-2 preview redraw, and upload redraw is drawn `standing` —
a snake included. And because the designer hands the preview PNG to `make_pet_zip` as
`reference_image` **without** `remix_strength` (the as-is branch, `factory.py:1001`), the
standing snake is **not** corrected at build time; it propagates into the finished pet.
The §5.1 parity comment ("the previewed still IS the build's base sprite") holds as bytes
but the bytes themselves were drawn from the wrong prompt.

### §0.3 Defect B — the fallback asserts feet, and framing lives in the wrong sentence

`DEFAULT_POSE = "standing"` (`prompt_templates.py:25`) assumes legs — wrong for the very
animals whose profiles shout "no legs". Meanwhile the framing instruction "full body,
centered" lives only in `CURATION_STILL_TEMPLATE` (`prompt_templates.py:115`), so ordinary
typed-animal renders never get it — yet framing is a **house-style** property (true of
every render), not a posture (varies per body plan). The slots are miswired: the universal
thing is per-path, the per-body thing is universally defaulted.

---

## §1 — Decisions (with the alternatives that were rejected, and why)

**D1 — Deliver the resolved `base_pose` STRING to the pool, not the profile key.**
The web tier already resolves it on pure data (`_base_pose_for`, `webui/app.py:839` —
motion_profiles is GPU-less-safe by the PEP 562 posture). Sending the string keeps the
handler dumb and makes the **web tier authoritative**: a node whose profile JSONs lag a
content edit cannot silently draw the stale pose. Sending the key would re-resolve on the
node and reintroduce exactly that skew.
*Rejected:* sending the key (skew), re-resolving from `description` on the node (the
description is a composed design string by step 2 — "slender vivid blue dragonfly…" — not
a clean animal noun; keyword resolution against it is a coin flip).

**D2 — Framing ("full body, centered") moves INTO both still templates; posture stays in
the profiles.** The split follows the file's own engine-vs-content line
(`prompt_templates.py:1-19`): style identical for every animal → template; posture per
body type → profile JSON. This also preserves the load-bearing clauses — "facing right"
(DatsMe mirrors for leftward movement) and the cyan backdrop (SPEC_MATTE_BACKDROP) — in
exactly one place each.
*Rejected:* per-body-type prompt templates. Three reasons, argued 2026-07-30: (a) the
house style genuinely doesn't vary by body plan, and two of its clauses are load-bearing;
(b) seven templates = seven copies of the backdrop phrase — the exact three-copies bug
`CURATION_STILL_TEMPLATE`'s comment records this file was created to kill; (c) the lever a
per-type template would add next — a per-type negative — is **measured dead** at CFG 1.0
(`factory.py:76-85`: three different negatives, byte-identical pixels;
`test_samplers_run_at_cfg_one` pins it). Revisit only if ≥3 body types need something a
pose clause structurally cannot say (e.g. different *composition*, not different posture)
— the three-instances rule.

**D3 — `DEFAULT_POSE` becomes the EMPTY clause, and the sentence renderer must join
cleanly around it.** "Standing" assumes feet; no generic posture word exists that doesn't
assume a body plan. With framing moved into the template (D2), the default's only
remaining job is "what to say when the body plan is unknown", and the honest answer is
nothing. Mechanically: the render helpers (`base_still_prompt` / `remix_still_prompt`)
must omit the clause and its comma when `pose` is falsy — never emit `", ,"`. Templates
stay pure data; the join logic lives in the two helpers, which are already the single
definition of each sentence.
*Note:* an empty default is nearly unreachable once D1 ships — resolution falls back to
`registry.default` (`quadruped`), so a truly unknown animal still gets "standing on all
fours, alert" from the profile layer. The empty default protects the residual paths
(`_base_pose_for`'s no-animal fallback `webui/app.py:849`, direct library callers, v3
nodes during the transition window) and removes the false assertion from the signature
defaults (`factory.py:959`, `factory.py:1012`). **Sweep all four "standing" literals in
the same change** (the repeated-bug rule): `prompt_templates.py:25`, `factory.py:959`,
`factory.py:1012`, `webui/app.py:849`.

**D4 — `CURATION_STILL_TEMPLATE` loses "full body, centered" in the SAME commit that the
base template gains it.** The curation string is passed as the `{animal}` of a real build,
so the base/remix template wraps it; leaving the clause in both places says it twice, and
twice is how "standing side profile" once drew a sitting cat (`prompt_templates.py:103-113`
— every instruction appears ONCE, that is what makes it land). The two edits are one
atomic change, pinned by a guard test asserting the composed curation-through-base sentence
contains each framing token exactly once.

**D5 — No runtime flag for the send; DEPLOY ORDER is the gate.** Mirror of the
`upload_isolate` fleet gate but simpler: `pet_preview` bumps `"3"` → `"4"` with
`base_pose` **optional** (v4 ⊇ v3, rollback-safe); the web tier change that sends it
deploys only after `roll_pet_fleet.sh` reports every node at 4. Pre-launch, with two nodes
and one operator, a flag would be cleanup debt with no scenario it protects.
*Rejected:* an admin switch à la `settings_admin` (that pattern exists for flags that must
flip without a deploy; this is a one-way migration, not a lever).

**D6 — Wording ships only through renders; per-profile clause quality is CONTENT work.**
The existing `base_pose` strings were authored for the local path and have never been
exercised through prod's renderer at scale. At least one is suspect on its face:
`winged_flyer`'s "wings folded against its back" — dragonflies *cannot* fold their wings
(damselflies can), so the clause may fight what Z-Image knows about the animal. Clause
edits are profile-JSON content changes (motion admin territory, no code), iterated via
§4's sheet. This spec's code phases must not block on them.

---

## §2 — The prompt change (Defect B)

Target sentences (exact wording subject to §4 — these are the rev.1 candidates):

```
BASE:  a cute cartoon {animal}, full body, centered, side profile view, facing right,
       {pose,} soft pastel colors, muted palette, simple flat shading,
       flat vivid cyan background, storybook style

REMIX: a cute cartoon {animal}, exactly {animal}, full body, centered, side profile view,
       facing right, {pose,} rich saturated colors, simple flat shading,
       flat vivid cyan background, storybook style

CURATION: {species}          ← loses "full body, centered" (D4)
```

`{pose,}` denotes the optional clause: present with its trailing comma when `pose` is
non-empty, absent entirely when it is not (D3).

**Invariants that survive any §4 iteration:**
- "facing right" stays — DatsMe authors rightward and mirrors (`prompt_templates.py:66`).
- `STILL_BACKDROP` / `STILL_BACKDROP_RGB` untouched — changing the backdrop is a separate
  content decision with its own spec (SPEC_MATTE_BACKDROP) and re-draws every pet.
- One definition per sentence; the helpers in `prompt_templates.py` stay the only
  renderers; `factory._base_prompt` / `_remix_prompt` keep delegating.
- Each instruction appears exactly once in any fully-composed sentence, including the
  curation-wrapped one (D4's guard test).

**Consumers to update in the same change:** `test_prompt_templates.py` (pins the
sentences), `motion_admin.py:163` (surfaces `default_pose` to the Lab's prompt preview —
an empty default is correct data; check the Lab copy doesn't render `""` awkwardly) and
its pin `test_motion_admin_api.py:153`.

**Cost note:** every wording change re-draws every future pet differently. Pre-launch this
is free (pre-launch-no-back-compat); the curated `base.png`s in `animal_catalog/` were
human-vetted under the OLD curation sentence and stay valid — they are copied, not
re-rendered (`webui/app.py` catalog door), so D4 does not invalidate the catalog.

---

## §3 — The delivery change (Defect A)

### §3.1 `pet_preview` v4

- `METADATA["version"]: "3" → "4"`.
- `params_schema.properties.base_pose`: `{"type": "string", "maxLength": 200}` — optional,
  additive. (Longest current clause is ~104 chars; 200 leaves authoring room and stays far
  under the pool's 600-char param norm.) `additionalProperties: false` stays.
- `run()` threads it into **both** branches: `render_design_still(description,
  base_pose=…)` and `render_design_still(description, ref, strength, isolate=…,
  base_pose=…)`, defaulting to the D3 empty clause when absent — a v3-era submit renders
  exactly as today minus nothing.

### §3.2 Web tier

In `_render_still`'s pool branch (`webui/app.py`): delete the `NOTE (base_pose parity)`
block (`:887-891`) and send `params["base_pose"] = base_pose`. Callers already compute it
for every door (`:1089` txt2img, `:1157` upload, `:1329` build-from-reference) — the local
branch has honoured it all along; this makes the two branches take the same argument, which
is the §5.1 parity claim becoming true structurally again.

### §3.3 Order of operations (the fleet gate, D5)

1. Land §3.1 + §3.2 in one commit (the web change is inert until deployed).
2. `scripts/roll_pet_fleet.sh` — both nodes to v4; exit 0 or stop. The script already
   reads the target version from this checkout and refuses to finish version-mixed.
3. Deploy **staging** web; `scripts/verify_deployment.sh https://pet-staging.datsme.me`
   (it submits real preview jobs — the false-green rule).
4. Draw the acceptance animals on staging (§5 gate G3).
5. Deploy **prod** web; verify the same way. Staging-before-prod is standing policy;
   deploys only on explicit request.

**Failure mode if the order is violated:** a web tier sending `base_pose` to a v3 node
gets a schema 422, surfaced to the user as the 423 "couldn't draw that just now" — exactly
the intermittent coin-flip the 2026-07-23 incident taught us to pre-empt. The roll script
is the guard; do not hand-install.

---

## §4 — The contact sheet (where the iterations live)

A small render harness, run locally on this box (ComfyUI GPU-testable here), that makes
prompt decisions **visible** before they ship. Modeled on the design-axes calibration
matrix but deliberately lighter: no manifest, no freshness predicate — this is a
decision-making tool, not a permanent gate. `scripts/pose_framing_sheet.py`, outputs
gitignored, montage per row.

**Matrix:** one representative animal per profile × prompt variants × **3 fixed seeds**
(fixed so re-runs are comparable; distinct so one lucky draw can't sell a bad wording).

| profile | animal | note |
|---|---|---|
| serpentine | snake | the "no legs" acid test |
| aquatic | goldfish | the other "no legs" |
| avian | parrot | |
| winged_flyer | dragonfly | the originating complaint; D6's suspect clause |
| quadruped | dog | the control — must not regress |
| primate | monkey | |
| humanoid | gnome | |
| *(fallback)* | *empty pose* | what an unknown animal draws under D3 |

**Prompt columns per cell:** (a) today's sentence (`standing`, no framing) — the baseline;
(b) §2 candidate with the profile's `base_pose`; (c) §2 candidate with empty pose. Plus an
img2img row (one reference, remix template old vs new) for Q5.

**Cache note:** ComfyUI caches on graph+seed. For prompt A/B the graphs differ, so no cell
can fake another; re-rendering an *identical* cell returns the cached image, which is
fine (deterministic) — but never time these runs for speed conclusions.

**The gate is eyeballs.** No proxy metric — brightness, spill, repaint ratios have all
lied here before. A wording wins when a human says the 3-seed row looks like the animal in
the profile's intended posture, framed whole, matting cleanly on cyan.

**Questions the sheet must answer before §2 ships** (each answer → a rev bump):

- **Q1** Does "full body, centered" fight "side profile view, facing right" for
  composition, or drift subjects toward frontal poses?
- **Q2** Dilution: does adding the framing clause weaken the pose clause's grip? (The
  sitting-cat precedent says clause count is not free.)
- **Q3** Empty-pose distribution: with no posture word at all, does the model draw more
  degenerate poses than today's "standing", or fewer? (Today's staging/prod output IS
  approximately column (c) plus the word "standing" — the baseline column shows the delta.)
- **Q4** Per-profile clause quality (D6): does each declared `base_pose` actually render
  as intended — dragonfly wings, "tongue flicking" at sprite scale, the primate
  knuckle-walk?
- **Q5** Remix framing: on img2img, does "centered" shift the subject relative to its
  reference and so break the visual continuity between step-1 archetype and step-2
  preview?
- **Q6** Preview↔animation coherence: a preview drawn in the profile's `base_pose`
  becomes the build's base sprite as-is; do the walk/idle Wan loops start acceptably from
  that posture for the non-quadruped profiles? (Pose anchors §3.9.1 cover poses *with*
  clauses; the base still is the fallback start.)

---

## §5 — Phases and gates

**Phase 0 — sheet harness + baseline.** Build §4's script, render the baseline column.
No product change. *Gate G0:* the baseline reproduces the complaint (standing snake,
chunky dragonfly) — proof the harness measures the real thing.

**Phase 1 — prompt rework (Defect B).** §2 wording per the sheet's verdicts; D3's
four-literal sweep; D4's atomic curation edit; tests updated (`test_prompt_templates`,
`test_motion_admin_api`, the D4 once-only guard). *Gate G1:* pytest green AND the sheet's
(b)/(c) columns beat (a) to a human eye, dog-control not regressed.

**Phase 2 — delivery (Defect A).** §3.1 handler v4, §3.2 web send, §3.3 ordering.
*Gate G2:* `roll_pet_fleet.sh` exit 0, both nodes report 4; `verify_deployment.sh` green
on staging before prod sees the web change.

**Phase 3 — clause calibration (content, D6).** Iterate individual `base_pose` strings
via the motion admin against the sheet — expected to be the long tail, and deliberately
decoupled: profile JSON edits, no code, no fleet roll (the web tier resolves and sends
the string per D1, so a content edit is live on the next preview).
*Gate G3 (acceptance):* on **staging** then prod — dragonfly, snake, goldfish, dog typed
fresh, 4 draws each; every draw shows the profile's posture (coiled, swimming-horizontal,
wings per the calibrated clause, all-fours) with the whole animal in frame; no matte
regressions on the result cards.

---

## §6 — Files touched

| file | change |
|---|---|
| `pet_factory/prompt_templates.py` | §2 sentences, D3 empty default + join, D4 curation edit |
| `pet_factory/factory.py` | D3 sweep (`:959`, `:1012` defaults) |
| `webui/app.py` | D3 sweep (`:849`), §3.2 send + NOTE deletion |
| `pool_handler/pet_preview_handler.py` | §3.1 v4 |
| `pet_factory/tests/test_prompt_templates.py` | re-pin sentences; D4 once-only guard |
| `webui/tests/test_motion_admin_api.py` | `default_pose` pin follows D3 |
| `webui/tests/test_pool_backend.py` | assert the pool submit carries `base_pose` |
| `scripts/pose_framing_sheet.py` | new, §4 |
| profile JSONs (`motion_profiles/*.json`) | Phase 3 content only |

Out of scope: `registry.default` (quadruped fallback is *correct* for animation and
therefore for the still, once delivered), the backdrop, pose anchors (§3.9.1 already
per-pose), `verify_deployment.sh` (already exercises `pet_preview`).

## §7 — Known traps carried in from history

- **Dilution** — one instruction once (`prompt_templates.py:103-113`). Every clause §2
  adds must earn its seat on the sheet.
- **False-green deploys** — every deploy failure so far looked green; only
  `verify_deployment.sh` counts.
- **Version-mixed fleet** — the 2026-07-23 coin-flip; `roll_pet_fleet.sh` or nothing.
- **Graph+seed cache** — never reuse a seed when judging *variety*; never time a cached
  A/B.
- **Proxy metrics lie** — the sheet's gate is a human looking at the image, full stop.
- **Backend has no `--reload`** — restart after edits or chase phantom AttributeErrors.
