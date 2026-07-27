# SPEC — Design parity in the Motion Lab: author the pet a real build would animate — CLOSED / IMPLEMENTED

> **Status: CLOSED / IMPLEMENTED — 2026-07-27, Rev.7.** All of D1–D6 shipped, plus D5, which
> was held behind `SPEC_MATTE_REPAIR_ORDER` F4 and unblocked when F4 landed the same day.
> Guard tests 1–8 (backend) and 9–11 (frontend) are present and green; §7's gates 1–6 pass.
> The last deferral — §5 item 11, `PoseGallery`'s `petId` path after the `PosePlayer`
> widening — is discharged: `web/src/components/posePlayerSource.ts` holds the resolver and
> `posePlayerSource.test.ts` pins it against the api adapter itself.
>
> **Deferred by design, not unfinished** (§10): a persisted design preset, and a matrix mode
> for the Lab (`scripts/calibrate_design_axes.py` still owns sweeps).
> **Archived; the code is the source of truth from here.**
>
> **What it bought, in the end.** The Lab was built to author pose clauses; this made it
> faithful enough to be *evidence*. Within hours of shipping it caught three things that a
> 3-minute blind build had been hiding for months: the pale-anchor template bug (D6), the
> opaque-black hole fill (`SPEC_MATTE_REPAIR_ORDER` F1), and the white backdrop that caused
> the holes in the first place (`SPEC_MATTE_BACKDROP`). The instrument found more than the
> feature did.
>
> **One correction worth carrying forward** (Rev.7): §0.3's table said the anchors draw "the
> short **typed** phrase". They draw `ref["description"]`, which a design REPLACES with
> `display_name.lower()` — so a designed white snow leopard draws *white* anchors. The two
> are the same string only until step 2 runs, and the implementation followed the wrong word
> until a live run caught it.


**Rev.7 — THE SUBJECT CHANGES WHEN A DESIGN IS APPLIED (§0.3).** Found by the operator in live
testing, on the first designed run: the Lab drew a white snow leopard base and then drew **tan**
pose anchors. A build does not do that. `/api/preview` saves its redraw as
`description = display_name.lower()`, `/api/generate` reads that field, so a designed pet's anchors
and loops draw `"white snow leopard"`. Rev.1–6 all wrote "the short **typed** phrase" in §0.3's
table, which is true only until step 2 runs — and the implementation followed the word `typed`.
The `/still` response now hands back a **`subject`** beside the composed `description`, and the
caller carries it into every later anchor and loop, exactly as a build carries the record step 2
wrote. Guarded by `test_a_design_hands_back_the_subject_a_build_would_carry`,
`test_the_designed_subject_matches_what_the_designer_saves`, and `poseSubject` in `labDraw.test.ts`.
**The lesson is §0's own:** this document warned that a naive wiring makes the Lab *more* designed
than a build; the failure that actually shipped made it *less*. Both are the same mistake — not
reading which string the engine gets — and only a real designed draw exposed it.

**Status: D6, D1–D4 AND D5 IMPLEMENTED — 2026-07-27 (Rev.7).** D5 is no longer held: F4
(`SPEC_MATTE_REPAIR_ORDER` §12) was built alongside it, so the packed tile has something to
render. `PosePlayer` now takes either a `petId` or an explicit `{sheetUrl, manifestUrl}`,
and the Lab's packed tile is that same component over a checkerboard with the damage line
under it. **Gate 8 (§7) is GREEN on real GPU**: `white snow leopard` → `idle` → one press →
the raw tile clean, the packed tile's body blacked out, `hard-zero 157,296 px · filled
45.8% · glaring 43.7%`.

**Status of the earlier items: D6 + D1–D4 IMPLEMENTED, 2026-07-27 (Rev.7).** Gates 1, 2 and 4–6
are green: `pytest webui/tests` 326 passed with tests 1–8 present, `tsc --noEmit` clean, vitest 19
passed with tests 9–10 in `labDraw.test.ts`. The by-eye gates were run against the **real**
`prompt_templates` and `compose_design` in-process (the unit tests use a fake `_pf`), confirming an
anchor with no reference now carries `exactly {animal}, … rich saturated colors` while a
from-scratch base still carries `soft pastel colors, muted palette` — the asymmetry D6 exists to
create — and that only a base-with-reference draw is img2img. **Not verified:** the mounted
`<DesignStep>` in a browser (the Lab is adm-cookie gated) and any real GPU draw. Gates 7–9 belong
to D5/F4.

**Rev.6 — four gaps closed against the shipped code (I10–I13);
§1.1's fidelity claim corrected; D5 held behind F4.** A pre-implementation review ran every claim
in Rev.5 against the code and found four places where the spec could not be built as written:

- **The frontend tests it asks for cannot exist here.** `web/vitest.config.ts` is
  `include: ["src/**/*.test.ts"]` with **no jsdom and no React testing**, and its docstring argues
  deliberately against adding one. Tests 9–11 were component tests. **I10** decides the answer:
  the request shaping moves into a pure module (`labDraw.ts`) and test 11 tests *that*; the
  rendering assertions become by-eye gates. No browser harness is introduced.
- **I4 silently dropped a clamp.** `/api/preview` and the Lab both do `min(0.9, max(0.3, s))`;
  `effective_strength` has **no lower bound**. Adopting it as written let `strength=0.05` through
  on both surfaces. **I11** moves the floor *into* `effective_strength`, where "the one knower"
  requires it to be.
- **I6 gave one state slot two producers.** **I12** replaces the overloaded `reference` with a
  named `LabSource` discriminated union (`upload` | `design`).
- **Nothing enforced §0.3's failure mode on the wire.** **I13** makes design fields a **400**
  anywhere except a base img2img draw, so §0.3 is structural rather than a convention the caller
  is trusted to keep.

**§1.1 was overstated and is corrected below.** A build's pose anchors are drawn from the short
phrase by construction (`anchor_prompt(animal, clause)`), and `remix_strength=None` puts
`_base_sprite` on its **as-is** branch — the designed reference *is* the base sprite, never
redrawn at build time. So after D6 the Lab's anchors already match a build's byte for byte,
designed or not. D1–D4 buy the **base still** (and therefore clause-less poses) plus interactive
**axis calibration** — a narrower and still worthwhile claim, now stated as the real one. See B8.

**D5 is held.** It requires F4 (`SPEC_MATTE_REPAIR_ORDER` §12), which is not built. Building D5's
half alone would ship a widened `PosePlayer` with no consumer. §6 sequences it after F4 and it is
explicitly **not** in this document's delivery.

**Rev.5 — D5 collapses to a display concern (§2.5).**
`SPEC_MATTE_REPAIR_ORDER` Rev.3 made packing the last **stage of the Lab's animate job** instead of
a separate `Pack` action, so this spec no longer places a rung, a busy state or a `Pack all` batch
row — pressing `Animate` produces both tiles. §2.5 keeps only what it always really owned: the two
tiles, the checkerboard, the damage line, and `PosePlayer` reuse. Guard test 10 (the disabled-until-
animated gate) is **deleted**: the condition it defended is now structurally impossible.

**Rev.4 — implementation-ready.** A readiness review found nine
decisions the spec left to whoever typed the code; §11 closes all nine and each D now carries its
own resolutions inline (`I1`…`I9`). Nothing here changes the design — it removes the places two
reasonable implementers would have diverged. The largest was scope: `web/src/lib/api.ts`, the app's
one endpoint adapter, has to change for D1, D2 and D3 and was not in "Repos touched".

**Rev.3 — D6 is new: the anchor template (§2.6).** A review of
Rev.2 found the Lab drawing its pose anchors from a sentence **no app build has ever used**:
`anchor_prompt` in `make_pet_zip` is `_remix_prompt` on every web build (the web tier cannot produce
a `reference_image` of `None`), while the Lab falls back to `_base_prompt` whenever no reference is
loaded. It is one line, it depends on none of D1–D5, and it is the largest parity gain in this
document — §6 sequences it first. Rev.3 also corrects §0.3 and §2.3, which called the anchor path
"unchanged from today" and meant it as a statement of parity.

**Rev.2 — D5: the packed pose, shown under the raw one (§2.5).** *(Rev.2 placed this as a `Pack`
rung; Rev.5 dropped the rung when F4 became a stage. The reason it exists is unchanged:)* the Lab's
cards end at `Animate`, one stage short of the bundle, so a packer defect has nowhere to appear. D5
plays the *same* pose packed, in the pet house's own player, directly under the raw loop — the
difference between the two tiles is what the packer did. What the pack *does* stays in
`SPEC_MATTE_REPAIR_ORDER` §12; §2.5 owns only how it is shown, and §4 states the split.

**Rev.1.** The Motion Lab can author *poses* but not the *pet*:
it has no colour, body, accessory or free-text controls, so its stills are drawn from a bare typed
noun while a real designed build animates a still that step 2 redrew. This closes that gap by
reusing the designer's own step-2 component and the one composer, so the Lab draws what a build
draws — and can therefore be trusted as evidence about a build.

**§0 is the whole spec.** The parity contract was read out of the shipped code, and it is **not**
what it looks like from the outside: the composed design string is used exactly **once**, and a
naive wiring makes the Lab *more designed than a real build at every anchor and loop*. Read §0.1
and §0.3 before writing anything.

**Amends:** `SPEC_MOTION_LAB` (the Lab's surface). **Depends on:** nothing new — no model, no key,
no migration. **Reads from:** `SPEC_PET_DESIGN_AXES` §2/§3/§4 (the vocabulary and the surface
gate), `SPEC_PET_DESIGNER_FLOW` §4 (step 2).

**Repos touched:** `datsme-pet-factory_wu` only — `webui/app.py` (one query param; one shared
normalizer, I2; `effective_strength` adopted, I4), `webui/design_calibration.py` (the 0.3 floor
moves in, I11), `webui/motion_lab.py` (compose + the design body fields + the I13 gate, plus the
anchor template §2.6), **`web/src/lib/api.ts`** (`fetchDesignAxes` and `motionLab.startStill`
signatures + the `/still` response type — I5, I8; this is the app's ONE endpoint adapter and
omitting it understated the blast radius through Rev.3),
`web/src/app/admin/motions/lab/page.tsx` (mount the existing components; always send `base`, §2.6),
**`web/src/app/admin/motions/lab/labDraw.ts`** (new, pure — the request shaping the page used to
inline, I10) and its `labDraw.test.ts`,
`web/src/components/DesignStep.tsx` (**moved** from `app/design/general/`, I7),
`web/src/app/design/general/useDesignFlow.ts` (the `fetchDesignAxes` call site, I8),
`web/src/app/design/general/Designer.tsx` (the moved component's import, I7), tests.
**Held with D5, not touched here:** `web/src/components/PosePlayer.tsx` (§2.5).
**No engine change. No `pet_factory` change. No content change.** The GPU-less prod posture
is untouched (§3.4).

**Related but separate:** `SPEC_MATTE_REPAIR_ORDER` §12 (F4, the pack toggle). The two are
complementary and the difference matters — see §4.

**Code is cited by symbol, never by line number.**

---

## 0. The parity contract, as the code actually implements it

### 0.1 A designed build sends the SHORT phrase, not the composed design string

The generate endpoint:

```python
description = ref.get("description") or "pet"        # the reference's description
kwargs={"description": description, "reference_image": reference_image,
        "remix_strength": None, ...}                 # ALWAYS None — "generate is always as-is"
```

and the design step, when it saves the redrawn reference:

```python
_save_reference(png, owner=owner, description=display_name.lower(), ...)
```

So a designed pet's stored `description` is the **short phrase** (`"white snow leopard"`), and the
in-tree comment is explicit about why: *"The new record carries the SHORT species phrase ('purple
corgi'), NOT the ~240-char composed design string (§7.3) … The long prompt did its job here, in the
redraw."*

`make_pet_zip(description, …)` receives that short phrase, and the pool path sends
`params = {"animal": description}`. **The Lab's existing `animal` field is already the same slot a
build fills.** That is why no engine change is needed.

### 0.2 The composed string is used exactly once — in the redraw

`compose_design(species, color, accessories, picks, extra) -> (description, display_name,
min_strength)` feeds `_render_still(description, …)`, which redraws the still **img2img from the
prior reference** at the clamped strength. That new PNG *is* the design. Step 3 then animates it
**as-is** (`remix_strength=None`), guarded by **`test_generate_animates_the_reference_as_is`** in
`webui/tests/test_reference_flow.py`.

> Aside, since it will waste someone's afternoon: the comment at that call site names the guard
> `test_generate_is_always_as_is`, which **does not exist**. The real test is the name above. The
> comment's name drifted; the guard is real.

### 0.3 Therefore the Lab needs TWO values, not one — the crux

| value | used for | in a build |
|---|---|---|
| **the SUBJECT** | pose anchors, loop prompts, motion-profile keyword resolution, the breed slug | `ref["description"]` |
| **composed design string** | the **base still redraw only**, once | `compose_design(...)` → `_render_still` |

**And the subject CHANGES when a design is applied — Rev.7, and it is the one thing every
earlier revision got wrong.** Rev.1–6 called the first row "the short **typed** phrase", which is
true only until step 2 runs. `/api/preview` saves its redraw with
`description = display_name.lower()`, and `display_name` is `f"{color} {species}".title()` — so a
designed pet's record says **`"white snow leopard"`**, and `/api/generate` reads exactly that
field. Every anchor and every loop of a designed build therefore draws a **white** snow leopard.

What rides into the subject is the **colour and the species, nothing else**. The body shape, the
accessories, the free text and the `recolored entirely` clause live in the ~240-char composed
string, are spent on the redraw, and a build never sees them again. Imitating *that* asymmetry is
the parity:

| a designed `white snow leopard`, chubby, wearing a crown | draws |
|---|---|
| base still (step 2's redraw) | `chubby and round vivid white snow leopard, … wearing a crown, recolored entirely white` |
| every pose anchor, every loop | `white snow leopard` |

The *value* an anchor carries is only half of its parity; the *template* that value lands in is the
other half, and that is the half the Lab gets wrong today — **§2.6**. Rev.1 and Rev.2 read this
table as "anchors are already faithful, leave them alone". They are faithful in their **value** and
not in their **sentence**.

**The failure mode this section exists to prevent:** wiring the composed description into the Lab's
`animal` field. Every anchor and every loop would then carry the ~240-char design string, which a
real build never does — the Lab would draw different stills, get different mattes, and lie in
exactly the investigation it was built to serve. **A more-designed Lab is not a safer Lab.**

### 0.4 The Lab already has every mechanism but one

Verified against the shipped code — this is why the change is small:

| need | already there |
|---|---|
| a base still drawn **img2img from a prior reference at a strength** | `POST /still` with `reference_id` + `base: true` + `strength` → `_img2img_wf(_remix_prompt(...), reference, seed, strength)` — *"mirror `make_pet_zip` exactly"* |
| a prior reference to redraw **from** | a Lab still's `asset_id` **is** a usable `reference_id`: `_lab_reference` only checks `_lab_dir()/{id}.png`, and `_run_job` writes stills there under exactly that name. **No new plumbing.** |
| the step-2 UI | `web/src/app/design/general/DesignStep.tsx` — a **pure presentational component**: 7 values + 5 `onX` callbacks, no fetching, no reducer coupling, and *"holds NO animal logic"* |
| the vocabulary, fragment-free | `fetchDesignAxes()` → `/api/design-axes` → `{axis, label, kind, default, options}`; `prompt_fragment` never crosses |
| surface resolution from **typed text** | `_resolve_typed_surface(animal)` → `design_axes_mod.resolve_surface`, with the miss log |
| the strength clamp | `design_calibration.effective_strength(picks, color, species, base_strength)` — the one knower |

The one missing piece is the wiring, plus an `animal` query param on the axes menu (§2.1).

---

## 1. Why build it

1. **Fidelity of the BASE still — and only it (corrected in Rev.6).** Rev.1–5 claimed here that
   "pose wording tuned in the Lab is tuned against an image the build will not produce." That is
   **not true of a pose with a clause**, which is every pose the Lab exists to author: a build
   draws its anchor `_static_image_wf(anchor_prompt(animal, clause), _ANCHOR_SEED)` — txt2img, from
   the **short phrase**, with the design nowhere in it (§0.3, B8). After **D6** the Lab's anchors
   are byte-identical to a build's whether the pet was designed or not.
   What D1–D4 actually buy is the other half of a build: the **base still** — which for a designed
   pet *is* the design (`remix_strength=None` → `_base_sprite`'s **as-is** branch) — and therefore
   every **clause-less** pose, which animates that base. That is a real gap and it is where the
   matte/pack behaviour of a pale designed pet lives; it is just not the anchor path.
2. **A calibration this repo already owes itself.** `compose_design` carries: *"NOT YET CALIBRATED
   (`SPEC_PET_DESIGN_AXES` §8 Phase 3): the axis slots and free-text positions are reasoned, not
   measured … the rest deserve the same GPU session before the axis controls go user-visible."*
   The Lab is that GPU session. `scripts/calibrate_design_axes.py` already renders axis matrices
   into contact sheets from the CLI; this makes the same thing interactive, which is what an
   *ordering* question (does the accessory survive the recolour clause?) actually needs.
3. **Reproducing a specific reported pet.** A user's pet is a species *plus* its design. Without
   step 2's controls the Lab cannot re-draw the still someone is complaining about.

---

## 2. The design

### 2.1 D1 — the axes menu for a typed animal

`GET /api/design-axes` resolves `surface` from a `reference_id`. The Lab has free text and no
reference, so add an **optional `animal` query param**:

- `animal` present and no `reference_id` → `surface = _resolve_typed_surface(animal)`,
  `restriction = None` (the per-breed `resolved_surface_options` restriction applies to *curated*
  animals, which a typed name is not).
- `reference_id` wins when both are given — do not merge two sources of surface.
- Unresolved → `None` → universal axes only, which is the existing §3.3 unknown-animal posture.
  **Not an error**, exactly as today: a menu endpoint must never dead-end the step.

Reuse `_resolve_typed_surface`; do not re-derive. Its miss log is the growth list for
`surface_keywords.json` and the Lab is a good place to feed it.

> **I8 — `fetchDesignAxes` takes an options object, `{referenceId?, animal?}`.** It is
> `fetchDesignAxes(referenceId?)` today: one optional positional string. Adding a second means
> `fetchDesignAxes(animal)` type-checks, is read as a reference id, fails `_load_reference`, and
> degrades to universal axes — silently, since that degradation is the endpoint's designed-in
> success path. The call that looks most obviously right is the one that breaks, which is exactly
> the failure D1 exists to prevent.

### 2.2 D2 — compose server-side, on the Lab's own endpoints

Extend `StillBody` with the structured design fields (`color`, `accessories`, `axis_picks`,
`extra`) and compose **in the handler**:

```python
picks = design_axes_mod.filter_picks(picks, _resolve_typed_surface(animal))   # same filter as step 2
description, display_name, min_strength = compose_design(animal, color, accessories, picks, extra)
strength = design_calibration.effective_strength(picks, color, animal, base_strength)
```

Three non-negotiables:

- **`filter_picks` before composing.** Step 2 filters picks by the resolved surface first; skipping
  it composes a fur fragment onto a bird and the Lab stops matching the designer.
- **`effective_strength`, not a re-implemented clamp.** An earlier duplicate of that folding existed
  and was deliberately removed (Finding 4e); do not reintroduce it.
- **Lazy imports.** `app.py` imports `motion_lab.py`, so `from app import compose_design` at module
  top is circular. `design_calibration.py` documents this exact trap. Import inside the handler.

> **I1 — one strength field, the existing `StillBody.strength`.** No `design_strength`. That field
> already means "the base img2img denoise", which is what a design strength *is*; a second one only
> creates a which-wins question at every call site. It is the `base_strength` argument in the snippet
> above.
>
> **I2 — the input caps move to a shared normalizer, and the Lab calls it.** `/api/preview` slices
> species `[:60]`, colour `[:20]`, accessories `[:30]`×3 capped at 3, extra `[:120]`. Those widths
> are **part of the composition contract**, not request hygiene: retyped in `motion_lab.py` they
> drift, and the two surfaces compose different strings for the same picks. One function in `app.py`
> beside `compose_design`, imported lazily by the Lab exactly as `compose_design` is. Note I3 —
> a function-level test cannot see this drift.
>
> **I3 — test 1 asserts at the HANDLER, not at `compose_design`.** Monkeypatch `_render_still` on
> both paths and compare the `description` each handler actually passed it. Calling `compose_design`
> directly from both sides proves only that one function is deterministic — it would pass today,
> before any of this is built, and it would sail straight past I2's drift. `test_reference_flow.py`
> already uses this seam; follow it.
>
> **I4 — `/api/preview` adopts `effective_strength` as part of this work.** Today it folds
> `min_strength` inline *after* its own 0.9 clamp while `effective_strength` clamps to 0.9 **last**;
> `test_no_axis_exceeds_the_strength_cap` exists solely to keep an axis from being authored into the
> gap between them. Leaving the Lab on one and the designer on the other makes "the one knower" an
> aspiration and keeps a guard test alive to defend a divergence nobody wants. Two surfaces, one
> function — then that test guards a bound instead of a discrepancy.
>
> **I11 — the 0.3 FLOOR moves into `effective_strength` before anyone adopts it.** Rev.4 missed
> that the two clamps are not the same clamp. `/api/preview` and `motion_lab.start_still` both do
> `min(0.9, max(0.3, s))`; `effective_strength` ends at `min(0.9, strength)` with **no lower
> bound**, because its only callers so far pass the calibration substrate (0.85) and never a user
> number. Adopting it as Rev.4 wrote it would let `strength=0.05` reach ComfyUI from **both**
> surfaces — a clamp deleted by a refactor whose stated purpose was to have one. The floor is part
> of the formula, so it lives with the formula: `min(0.9, max(0.3, strength))` in
> `design_calibration.effective_strength`, named as constants, with the existing calibration
> unaffected (`matrix.json` substrate is 0.85). **Every Lab base draw goes through it too** —
> including the undesigned photo redraw, where it degenerates to exactly today's clamp — so the
> Lab has no local copy of the arithmetic at all.
>
> **I13 — design fields are a 400 anywhere except a base img2img draw.** §0.3 names the failure
> mode (the composed string reaching an anchor) and test 2 asserts it, but nothing *prevented* it:
> a caller that attached design fields to an anchor would have had them silently composed or
> silently dropped, and both are worse than a refusal. The rule on the wire: `color`,
> `accessories`, `axis_picks` or `extra` are accepted **only** when `base` **and** `reference_id`
> are both set; otherwise `400 "a design is a redraw of a base still — draw the base first"`.
> This is not §3.1's gate in disguise: designing **nothing** on a base redraw stays legal and
> composes to the bare species phrase (that is §3.1, and it falls out of `compose_design` for
> free). What is refused is a design with nowhere legitimate to land.

### 2.3 D3 — spend the composed string only on the base

Per §0.3, in the Lab exactly as in a build:

- `base: true` + a `reference_id` → prompt from the **composed description**, img2img, clamped
  strength. This is the design.
- every **anchor** (`clause` set) and every **`/animate`** → the **subject**, which is the typed
  phrase before a design and `display_name.lower()` after one (§0.3). `compose_pose_prompt(subject,
  pose)` and the profile keyword match keep working either way — "white snow leopard" resolves the
  same profile "snow leopard" does. The `/still` response hands the subject back (I5) and the
  caller carries it into its next anchor, which is precisely what a build does by re-reading the
  reference record step 2 wrote. The *template* that phrase lands in is
  **not** unchanged — see §2.6, which is the one behavioural correction in this document.
  **After D6 an anchor draw stops sending `reference_id` at all** (Rev.6): the field's only
  remaining job on that path was to pick the template, and §2.6 takes that job away. A build's
  anchor knows nothing about the reference; neither should the request that mirrors it.
- The Lab **displays** the composed description read-only next to the base still, so the operator
  can see the exact string that was spent (§3.3 permits it).

The natural flow is therefore two draws — *Redraw* (txt2img, the un-designed base) then *Apply
design* (img2img from it) — which mirrors step 1 → step 2 with no new state machine.

> **I5 — the composed description rides back on the `/still` RESPONSE**, not on the job record:
> `{job_id, description, min_strength}`. It is known at request time, so it does not need to survive
> the ~15–50 s job, and `LabJob` stays what it is — a job-status shape. `_start()` returns
> `{"job_id"}` today, so this is two fields on that dict and two on the client's return type.
> **`min_strength` joins it in Rev.6**: `<DesignStep>` takes a `minStrength` prop and says "clamped
> to 0.90" with it. Without the field the Lab would have to pass `null` forever — mounting the
> shared component with one of its controls permanently lying, which is the drift D4 exists to
> avoid. Same value, same call, same request; it costs one dict key.
>
> **I6 — "Apply design" REPLACES `base` and becomes the reference.** Not a second slot. One `base`
> keeps `animateOne`'s clause-less fallback correct — a pose with no clause animates the designed
> still, which is what `pose_starts[name] = base` does in a build. Promoting it to the reference is
> what makes the *next* base draw an img2img from the design, mirroring step 2 → step 2 restacking.
>
> **This is safe only after D6, and that ordering is the reason §6 sequences D6 first.** Until §2.6
> lands, the reference also selects the prompt *template*, so promoting the designed still would
> silently flip every subsequent anchor from `_base_prompt` to `_remix_prompt` — the right sentence,
> arrived at by accident, and only while a design happens to be applied. After D6 the template no
> longer hangs off that field and I6 is inert with respect to anchors.
>
> **I12 — the slot it replaces is a NAMED union, not today's `reference` state.** The page's
> `reference: LabReference | null` means *an uploaded photo*, and the upload card renders its
> triage verdict straight off it. Letting "Apply design" write the same slot gives one piece of
> state two producers with different shapes, in an 820-line page with no reducer — the exact
> condition `designFlow.ts` exists to avoid on the designer side. So the slot becomes:
>
> ```ts
> export type LabSource =
>   | { kind: "upload"; reference_id: string; url: string; upload: LabReference }
>   | { kind: "design"; reference_id: string; url: string; description: string };
> ```
>
> One `source`, two kinds, each carrying only what its own card renders. The upload card keys off
> `source?.kind === "upload"`, the composed-string readout off `"design"`, and `clearRenders()`
> drops a **design** source while keeping an **upload** one — a design is a redraw of a base still,
> so when the animal or seed changes and the base goes, the design that was drawn from it goes
> too, while the photo on the desk stays on the desk.

### 2.4 D4 — mount the existing component

`<DesignStep>` takes `{color, accessories, axisPicks, extra, strength, axes, minStrength}` plus
`onColor / onAccessory / onAxisPick / onExtra / onStrength`. The Lab holds those five values in its
own state and passes callbacks. Cap accessories with the shared `MAX_ACCESSORIES` from
`designFlow.ts` — import it, do not retype the number.

**Do not fork the component.** If the Lab needs a variant, that is a prop on the shared component,
because two step-2 UIs drifting apart reintroduces the fidelity gap this spec closes.

**Its own CARD, in its own tint** *(added on first use, 2026-07-27)*. The first build mounted the
step-2 block as one more `border-t` row inside the Lab's setup card, and it failed on contact: it
**split that card's three rows in half** (animal/seed/base · photo · motion profile), and sharing a
surface made "what does the pet look like" read as one more piece of "which animal, which profile"
— which is precisely the distinction §0.1 of `SPEC_PET_DESIGN_AXES` exists to hold. The fix is
structural, not cosmetic: step 2 is its own card, placed directly under the setup it follows, and
carrying a **`.card-design`** modifier (a purple tint + the two-colour accent strip) added beside
`.card` in `globals.css`. A modifier rather than an inline style block, because what it marks is a
CATEGORY — a panel that holds a design — and the designer's own step 2 can adopt it. One card, one
question, which is the rule the three-step designer is already built on.

> **I7 — move `DesignStep` to `web/src/components/`.** It sits in `app/design/general/` today, so
> mounting it from `app/admin/motions/lab/` is one route folder reaching into another's internals.
> The repo already has the answer: `PosePlayer`, `PoseGallery` and `PetThumbnail` are shared
> components and live in `components/`. A move, not a rewrite — the import of `MAX_ACCESSORIES` from
> `designFlow.ts` follows it as a path change, and `designFlow.ts` correctly stays put, because the
> reducer is the general designer's state machine and the Lab does not have one. Doing this at mount
> time costs a rename; doing it later costs it plus a second consumer's imports.

### 2.5 D5 — the packed tile, under the animation it came from

*What the pack **does** is `SPEC_MATTE_REPAIR_ORDER` §12 (F4). This section owns only **how it is
shown** — the split is deliberate: the card's layout changes with the Lab, the packer's invocation
rules change with the packer.*

**Rev.5 rewrote this section.** D5 was a `Pack` rung with its own button, busy state and `Pack all`
batch row. F4 Rev.3 made packing the **last stage of the animate job** (§12.2), so there is nothing
to press and nothing to gate — pressing `Animate` produces both tiles. What is left here is display:

```
  ▸ animation        [ raw webp — white background, as ComfyUI made it ]
  ▸ packed           [ the SAME pose, animating, cut out and packed ]
                       hard-zero 0.0% · filled 12.4% · glaring 0.0%
  [ Animate ]
  [ Save clause ]
```

The two tiles are the instrument: **whatever the packer did to the pet is the visible difference
between two tiles of the same animation**, in one run. That is also what makes the card answer
"which step caused it" — the upper tile is the pipeline before the packer, the lower one after, and
they are the same 40 s of GPU.

**Rules:**

- **No new rung, no new busy state, no `Pack all`.** The animate job's existing `cell.busy ===
  "animate"` covers the whole thing; `phase` reads `packing` for the last ~6 s, through the same
  `runLabel(...)` that already renders every phase. This is the deletion F4 Rev.3 bought.
- **The packed tile appears when it appears.** The loop is published first and the packed sheet
  follows (§12.2), so the raw tile renders while the pack is still running. Do not hold both back
  for one atomic update — a visible loop *is* a result, and it is the result you still have when the
  packer is the broken thing.
- **A pack failure shows on the card, not in a toast.** `pack_error` renders under the empty packed
  tile ("packing failed: …"). The row that failed must be the row that says so.
- **Checkerboard substrate**, not white. On white, missing alpha is invisible — and a matte defect
  that only shows against a background is the exact class of bug this tile exists to catch.
- **The damage line under the tile** — hard-zero %, filled %, glaring % for that pose, from §12.4's
  shared metric function. A number beside the picture is what turns "that looks off" into a report.

**Reuse the pet house's own player.** `web/src/components/PosePlayer.tsx` already cycles one named
animation's frames from a real sprite sheet at the manifest's fps, and `PoseGallery` uses it for the
designer's result panel — the "Generated poses (8) — each animation is playing" grid. Mounting the
*same* component in the Lab means the packed tile is rendered by the same code the user's result
card uses, which is the strongest available answer to "does this imitate what really happens".

One small refactor is required and is the right one: `PosePlayer` takes `petId` and derives its URLs
via `petManifestUrl` / `petSheetUrl`, so it cannot currently play an arbitrary sheet. Widen it to
accept **either** a `petId` **or** an explicit `{sheetUrl, manifestUrl}` pair, leaving the `petId`
call path byte-identical for `PoseGallery`. Do **not** copy the component — a second frame-cycling
implementation is how the Lab's preview and the user's preview start disagreeing.

### 2.6 D6 — the anchor template: every app build is a reference build

*The one place the Lab draws a sentence the app never draws. One line of engine-adjacent code, one
line of frontend, and it depends on nothing else in this spec — which is why §6 sequences it first.*

`/api/generate` **requires** a `reference_id` and always resolves it to a PNG path, so
`reference_image` is **never `None` in the web tier**. `make_pet_zip` therefore takes
`anchor_prompt = _remix_prompt` on **every build the app has ever run** — typed, curated, designed
and uploaded alike. `_base_prompt` is not dead code: it is the **CLI's** branch (`examples/cli.py`
and `scripts/_node_build_check.py` call `make_pet_zip(animal)` bare). It is simply not a branch any
user's pet has ever taken.

The Lab picks its template off `body.reference_id` instead, so its default flow — type a noun, draw
an anchor — lands on `_base_prompt`. The two templates are not stylistic variants of each other:

| template | the wording that differs |
|---|---|
| `BASE_STILL_TEMPLATE` | `soft pastel colors, muted palette` |
| `REMIX_STILL_TEMPLATE` | `exactly {animal}` (the noun repeated), `rich saturated colors` |

**The direction of the error is the damaging one.** The Lab's default draws a *paler, less
saturated* animal than production has ever drawn, and pale-on-white is exactly the input condition
that makes birefnet punch interior holes — the defect §2.5 exists to display. Uncorrected, the Lab
overstates that defect, and any severity number read off it is not the app's number. A workbench
whose errors run *toward* the bug it is investigating is worse than no workbench.

**The fix, decided per draw** — the template follows what the *build* does at that stage, never what
the Lab happens to be holding:

- **anchor** (`base: false`) → **`_remix_prompt` unconditionally**, reference or not. This is
  `factory.py`'s `anchor_prompt` for every web build, and the reference's presence has no say in it.
- **base still** (`base: true`) → **unchanged**. `_base_prompt` txt2img with no reference (mirrors
  step 1 and `_base_sprite`'s text branch); `_remix_prompt` img2img with one (mirrors step 2, and
  the "Apply design" draw of §2.3). This branch was always right.

So `reference_id` keeps deciding **img2img vs txt2img** and stops deciding **which sentence**. Those
were one decision by accident; a build makes them separately.

**The frontend half is required, not optional.** `doDrawBase` sends `base: true` **only when a
reference exists** — without one, the base draw arrives with `base` defaulting to `false`. That was
harmless while the flag did nothing on the no-reference path; once the flag selects the template it
is load-bearing, and a base draw that forgets it gets an anchor's sentence. The page must send
`base: true` on **every** base draw. `StillBody`'s existing comment ("the backend cannot infer it")
becomes true on both paths rather than one.

`test_without_a_reference_the_lab_draws_from_text_as_before` draws a base with the flag absent and
asserts the base template. It needs the **flag added**, not its assertion weakened — the assertion
is still exactly right.

**Deliberately not a control.** Authoring against `_base_prompt` means authoring for the CLI, which
ships no pets to anyone. If that need ever appears it becomes an explicit toggle with a label; it
does not survive as an implicit branch off a field that means something else.

---

## 3. Deliberate divergences from the designer *(each one, and why)*

### 3.1 The "you designed nothing" 400 is NOT inherited
`/api/preview` rejects a request with no colour, accessory, non-default pick or free text (§4.1:
*"designing nothing is adopting"*). The Lab **must allow it** — drawing the un-designed baseline to
compare against is the entire point of a workbench. Divergence in a *gate*, not in composition.

### 3.2 JSON bodies, not form fields
`/api/preview` takes `Form(...)` fields (it also carries an upload); the Lab's endpoints are JSON.
Keep the Lab's convention. `axis_picks` arrives as a real object rather than a JSON-encoded string —
a transport difference, and composition is still the one shared function, which is what §5.1 pins.

### 3.3 Fragments MAY be displayed here
`prompt_fragment` is withheld from the browser everywhere else (the tier-table posture), but the
design **admin** already establishes that a gated surface may show calibrated wording — editing it
is that surface's job. The Lab is adm-gated and its whole purpose is to see the prompt. Show the
composed description; do not ship the fragment table to any ungated page.

### 3.4 No tiers, no pool, no posture change
No entitlement caps (admin surface), no pool routing (the Lab is local ComfyUI by construction),
and **no ML import at `motion_lab.py`'s module top** — the existing `_pf()` lazy accessor stays the
only route to the factory, because `webui` runs on the GPU-less prod tier where `import numpy` must
fail.

---

## 4. How this and the pack toggle divide up

The Lab becomes a full-pipeline workbench only with both changes, and they own different halves:

| | owns | gets you |
|---|---|---|
| **this spec** | design parity (§2.1–2.4), **the anchor template** (§2.6) **and how the packed pose is shown** (§2.5) | the **same image** a designed build would animate — same sentence, same pale-on-white still, same matte problem — and two tiles that name the stage between them |
| **`SPEC_MATTE_REPAIR_ORDER` §12** (F4) | what the pack action *does*: the shipped packer, the eviction, `GPU_LOCK`, the metrics, the posture | the **same failure** — it runs the stage that has the bug |

Neither half alone is a faithful repro. Design parity without F4 shows a correct-looking still and
no black blobs, because nothing ran the packer. F4 without design parity reproduces black blobs on
an *undesigned* pet — which is still enough to develop and verify F1 against, and is why F4 is
sequenced first in that spec. This spec is what makes the reproduced defect the **right** one.

**§2.5 is the seam between them.** If you implement one and not the other, implement §12 first: a
`Pack` button with no design controls is useful, and design controls with no `Pack` button cannot
show you a packer bug at all.

---

## 5. Guard tests

In `webui/tests/test_motion_lab.py`, the existing home for Lab behaviour.

1. **`test_lab_and_designer_compose_the_same_description`** — the same picks through the Lab's
   endpoint and through `/api/preview` produce a **byte-identical** description, display name and
   `min_strength`. **This is the test that makes the Lab evidence rather than decoration**; without
   it the Lab can silently drift and every conclusion drawn in it is void.
   **Assert at the handler (I3):** monkeypatch `_render_still` on both paths and compare what each
   one *passed* it. Comparing two direct `compose_design` calls tests one function's determinism,
   passes before a line of this is written, and cannot see the normalization drift I2 exists to
   prevent — include at least one input past every cap (a >60-char species, a 4th accessory) so the
   test would actually fail if the caps were retyped.
2. `test_lab_anchors_and_loops_never_receive_the_composed_string` — §0.3's failure mode, asserted:
   an anchor draw and an `/animate` call carry the short phrase even when design picks are set.
3. `test_the_axes_menu_matches_the_designer_for_the_same_surface` — `?animal=cockatiel` returns the
   same axis set a reference with `surface="feathers"` returns; an unresolved name returns the
   universal axes and does not error.
4. `test_lab_filters_picks_by_surface_before_composing` — no fur fragment on a bird.
5. `test_lab_applies_the_shared_strength_clamp` — via `effective_strength`, not a local copy. With
   I4 this widens to **both** surfaces: `/api/preview` and the Lab return the same strength for the
   same picks, because they call the same function. Keep `test_no_axis_exceeds_the_strength_cap` —
   after I4 it guards a real bound (an axis may not declare >0.9) rather than papering over a
   divergence between two clamps.
6. `test_lab_allows_an_undesigned_draw` — §3.1's divergence, pinned so nobody "fixes" it by copying
   the designer's 400.
7. `test_motion_lab_never_imports_the_ml_factory_at_module_top` — the posture guard, following
   `test_pool_mode_never_imports_the_ml_factory`.
8. **`test_lab_anchors_always_use_the_remix_template`** — §2.6. An anchor drawn with **no**
   reference carries `exactly {animal}`; a base drawn with no reference still carries the base
   template. **The asymmetry is the assertion** — a test that only exercises the reference case
   passes on today's code and proves nothing, which is how this survived Rev.1 and Rev.2.
   `test_a_reference_switches_the_template_and_only_the_base_is_img2img` keeps its name and its
   img2img half; its template half now covers only the base draw.

In `web/` — and **I10 decides where they can live**:

> **I10 — no browser harness is introduced; the logic moves to where the harness already reaches.**
> `web/vitest.config.ts` is `include: ["src/**/*.test.ts"]` with no jsdom, no `@testing-library`,
> and a docstring that makes the exclusion a decision rather than an omission: *"There is no jsdom
> and no React testing here, and that is the point … If a test ever needs a browser, that is a
> signal the logic under it belongs in the reducer instead."* Rev.4's tests 9–11 were all component
> tests, so as written **none of them could be run** — the spec asked for a gate the repo has no
> way to green, which is I9's mistake repeated. Two ways out; take the one the config's own
> docstring names.
>
> The Lab's request shaping moves into **`web/src/app/admin/motions/lab/labDraw.ts`** — pure, no
> React, no fetch, no DOM: the `LabSource` type (I12) and `baseDrawOptions(referenceId, strength,
> design?)`, which is the one function that decides what a base draw puts on the wire. The page
> imports it and does nothing but call it. That is exactly the reducer-shaped extraction the
> config asks for, and it is where D6's un-guardable frontend half becomes guardable.

9. **`baseDrawOptions` always sets `base: true`** — with a reference and without (§2.6, the
   frontend half of D6, replacing Rev.4's test 11), and it attaches `reference_id`/`strength` only
   when a reference exists. This is the whole of what `doDrawBase` was doing wrong, now testable
   without a DOM. In `labDraw.test.ts`, beside `designFlow.test.ts` — the second file in the
   frontend's pure-logic suite.
10. **`baseDrawOptions` carries a design only with a reference** — the client-side mirror of I13,
    so the 400 is a backstop rather than something the UI can trip.
11. ~~**Deferred with D5**~~ **— WRITTEN, 2026-07-27.** D5 is no longer held (F4 shipped), so
    this deferral is discharged rather than pending. Rev.6 said that when D5 landed the rule
    would be "extract the source resolution into a pure function and test *that*" — done:
    `web/src/components/posePlayerSource.ts` owns `posePlayerUrls`, `PosePlayer` delegates
    to it, and `posePlayerSource.test.ts` pins that a saved pet's URLs are still exactly
    `petManifestUrl`/`petSheetUrl` — compared against the adapter itself rather than a
    copied literal, so it follows a URL-shape change instead of going stale.
    **Why it mattered:** `PoseGallery` renders the user's finished pet on the result panel
    and passes `petId`. The widening for the Lab's packed tile had to leave that path
    untouched, and "untouched" was a claim in a comment until this test existed.
    The two-tile RENDERING remains a by-eye gate (§7), as Rev.6 said — that part is a GPU
    check and was never going to be a unit test.

---

## 6. Build order

**D6 (§2.6) first, on its own.** It depends on nothing else here, it is one line each side, and it
is the only item in this document that changes what the Lab *draws* rather than what it *offers*.
Tests 8 and 9. Ship it before D5 too: an unfixed template makes every packed tile paler than the
app's, so the D5 A/B would be run against the wrong image. Then:

1. D1 — the `animal` param on `/api/design-axes`, plus test 3. Smallest, and independently useful.
2. D2 — compose in the Lab's handlers, plus tests 1, 4, 5, 7. **Test 1 before the UI**: parity is a
   backend property and proving it first means the UI cannot be blamed for a drift. Note this step
   touches `webui/app.py` as well as `motion_lab.py` — I2 extracts the normalizer, I4 moves
   `/api/preview` onto `effective_strength` and I11 puts the floor inside it. Land all three
   *before* the Lab calls any of them, so the shared pieces have one caller when they change and
   two when they are asserted equal.
3. D3 — the two-value split, plus tests 2 and 10. Do not merge D2 and D3; test 2 is the one that
   fails silently and expensively.
4. D4 — mount `<DesignStep>`, plus test 6.
5. **D5 — HELD (Rev.6), and not delivered by this document.** It requires F4 from
   `SPEC_MATTE_REPAIR_ORDER` §12, which is not built. Building D5's half alone ships a widened
   `PosePlayer` with no consumer and a card slot with nothing to put in it — dead code awaiting a
   feature, which this repo deletes on sight. D5 lands **with** F4, from that spec's build order,
   and §2.5 stays here as its display contract.

If the goal is reproducing the matte defect rather than design fidelity, the useful order across
both specs is: **D6 (§2.6) → F4 (§12) → D5 → F1+F2 → then D1–D4** when you want the repro to match a
specific reported pet. D6 leads even there, and especially there: it costs a line and it is the
difference between packing the app's frames and packing paler ones.

---

## 7. Acceptance gate

1. `.venv/bin/python -m pytest webui/tests` green, with tests 1–8 present.
2. `npx tsc --noEmit` from `web/` — **not `next build`**, which poisons a live dev server — and
   `npm test` (vitest) green with tests 9–10 present in `labDraw.test.ts`.
3. **Parity is test 1, not a draw** (I9). Rev.1–3 asked here for the same pet designed twice, once
   through `/design/general` and once in the Lab "with the same seed", and for the two base stills to
   match. **That gate was never runnable:** `/api/preview` reaches `render_design_still` without a
   seed, so `_base_sprite` rolls a random one and the designer path has no seam to pin it through.
   Two stills from the same picks differ every time, and a gate that always fails teaches an
   implementer to skip gates. Decision #4 already says parity is a test; test 1 (as sharpened by I3)
   is that test. **By eye, confirm only what an eye can confirm:** the same picks produce the same
   *design* — the colour landed, the accessory survived, the body read — not the same pixels.
4. **The un-designed baseline still draws** (§3.1), and pose anchors still resolve their motion
   profile from the typed keyword (§0.3 regression check, visible in the Lab's own
   "auto-matched from …" line).
5. **D6, by eye and in one draw** (§2.6): with the animal field filled and **no reference loaded**,
   draw a pose anchor and confirm the prompt is the remix sentence — `exactly {animal}`, no
   `muted palette`. This is the gate for the only correction in Rev.3, and it is checkable in ~20 s
   before any of the rest exists.
6. **D2–D4, by eye, in one pass:** type `snow leopard`, `Draw base` (txt2img, the archetype), pick
   `white` + an accessory, `Apply design` — the still is redrawn, the composed string is on screen
   beside it, and the strength control reports the clamp the server applied. Then draw a pose
   anchor and confirm from the readout that it carried the **short phrase**, not that string
   (§0.3 by eye; test 2 is the assertion).
7. **Gates 8–9 belong to D5 and are HELD with it** (Rev.6): the two-tile A/B on a pale pet
   (`white snow leopard` → `idle` → `Animate`, packed tile showing black hindquarters and a
   non-zero hard-zero %) and the `pack: false` bisection lever both require F4. **A Lab that cannot
   show the defect while the defect is still there is not yet an instrument** — that remains the D5
   gate, run *before* F1, in `SPEC_MATTE_REPAIR_ORDER`'s order.

---

## 8. Decisions

1. **Reuse `<DesignStep>`; never fork it.** Two step-2 UIs would drift, and drift is the exact
   defect this spec exists to remove.
2. **Compose server-side.** Not only for the fragment posture — a browser-side composer would be a
   *second* implementation of the ordering rules that `compose_design`'s calibration comments say
   are still under measurement.
3. **The short phrase stays the Lab's `animal`.** The composed string is a per-draw input, not a
   rename of the field. This keeps profile resolution, the "auto-matched" line and every existing
   Lab behaviour working unchanged.
4. **Parity is a test, not an intention** (test 1). Everything else here is wiring; that assertion
   is the deliverable.

The thirteen **implementation** decisions — the ones that decide how, not whether — are §11.

---

## 9. Attempt log — append as this iterates

| # | date | attempt | measured result | verdict |
|---|---|---|---|---|
| B1 | 2026-07-27 | Can the Lab already draw a designed still? | `/still` with `reference_id`+`base`+`strength` is already the img2img redraw, and a Lab still's `asset_id` is a valid `reference_id` (`_lab_reference` only stats `_lab_dir()/{id}.png`) | mechanism exists; only wiring missing (§0.4) |
| B2 | 2026-07-27 | What does a designed build actually send? | `description = ref["description"]` = `display_name.lower()` (short phrase); `remix_strength=None` always | the composed string is spent once, in the redraw (§0.1/§0.2) |
| B3 | 2026-07-27 | Is `<DesignStep>` reusable outside the flow? | pure props component, 7 values + 5 callbacks, "holds NO animal logic" | mount as-is (§2.4) |
| B4 | 2026-07-27 | Does surface resolution work from typed text? | `_resolve_typed_surface` exists, with a miss log | one query param away (§2.1) |
| B5 | 2026-07-27 | Is there a player for a packed sheet, or must one be written? | `PosePlayer` already cycles one pose's frames from a real sheet at the manifest fps, and `PoseGallery` uses it for the **designer's result panel** | reuse it; one additive prop pair to accept a non-`petId` sheet (§2.5) |
| B6 | 2026-07-27 | Rev.2 claimed the Lab's anchors already match a build. Do they? | **No.** `/api/generate` requires a `reference_id`, so `reference_image` is never `None` in the web tier and `anchor_prompt` is `_remix_prompt` on **every** app build; the Lab uses `_base_prompt` whenever no reference is loaded. The templates differ by `muted palette` vs `rich saturated colors` + a repeated noun — and the Lab's side is the *paler* one, toward the very defect §2.5 investigates | the anchor value was right and the anchor **sentence** was wrong; D6 (§2.6), sequenced first |
| B7 | 2026-07-27 | Is a one-pose Lab pack arithmetically the same as that pose inside an 8-pose build? | **Yes.** `pack_datsme_bundle`'s `prep()` is entirely per-frame: `_remove_bg` per frame, `_fit_square` scales from that frame's own size, `_fill_holes_alpha` floods from that cell's own border. The only bundle-wide state is `total_frames` (progress) and `fallbacks` (a failure budget). No cross-pose or cross-frame state anywhere | this is *why* §2.5's tile is evidence and not an approximation — recorded here because §12.2 relies on it without proving it |
| B8 | 2026-07-27 | Rev.1–5 §1.1 says a designed build "animates a redrawn still". Which draws does the design actually reach? | **Only the base.** `/api/generate` sends `remix_strength=None` always, so `_base_sprite` takes its **as-is** branch — the designed reference IS the base sprite, `_prep_reference_image`'d and never redrawn. Every pose WITH a clause draws its own anchor `_static_image_wf(anchor_prompt(animal, clause), _ANCHOR_SEED)` from the short phrase; the design is nowhere in it. Only clause-less poses (`pose_starts[name] = base`) inherit the design | §1.1 overstated: after D6 the Lab's anchors already match a build's exactly. D1–D4 buy the base still, clause-less poses, and axis calibration — §1.1 rewritten to claim that instead |
| B9 | 2026-07-27 | Can Rev.4's frontend tests 9–11 be written? | **No.** `web/vitest.config.ts` is `include: ["src/**/*.test.ts"]` — no jsdom, no `@testing-library`, one existing test file (`designFlow.test.ts`, a pure reducer), and a docstring that makes the exclusion deliberate | I10: extract `labDraw.ts` and test the pure request shaping; do not add a browser harness. The same trap as I9 — a gate with no way to go green |
| B11 | 2026-07-27 | A designed white snow leopard drew TAN pose anchors in the Lab. Is that what a build does? | **No.** `compose_design` returns `display_name` = `f"{color} {species}".title()`; `/api/preview` saves the redraw with `description=display_name.lower()`; `/api/generate` passes `ref["description"]` to `make_pet_zip`. So a designed build's anchors draw `"white snow leopard"`. The colour rides in via display_name; the body shape, accessories, free text and recolor clause do NOT — they were spent on the redraw | §0.3's "short **typed** phrase" was wrong in one word and the code followed it. Rev.7: `/still` returns `subject`, the caller carries it |
| B10 | 2026-07-27 | Does test 1 actually catch the drift it was written for, or does it pass vacuously? | **It catches it.** Two mutations, each reverted after: (a) the Lab retypes the species cap (`animal[:70]` instead of the shared normalizer's 60) → test 1 fails; (b) the 0.3 floor removed from `effective_strength` → test 5 fails. The over-cap fixture is load-bearing: with in-cap inputs, mutation (a) passes | the I3/I11 assertions are real; recorded because "the test passed" is not evidence a guard guards |

---

## 10. Open questions

1. **Should the Lab persist a design preset?** Re-typing five picks per session is the friction that
   makes a workbench go unused. Deferred until the flow is used once in anger — the Lab has no
   settings store today and inventing one before the need is speculative.
2. **Should the pose-anchor draws see the design at all?** §0.3 says no *because that is what a
   build does*, and fidelity outranks preference. But if anchors on a heavily recoloured pet drift
   in colour, that is a finding about the **build**, not about the Lab — and the Lab is now the
   place it would show up. Record it if seen; do not "fix" it in the Lab.
3. **Does the calibration in §1.2 want a matrix mode?** `scripts/calibrate_design_axes.py` already
   does matrices; the Lab does one cell at a time well. Leave the CLI owning sweeps unless
   interactive comparison proves it needs both.

---

## 11. Implementation decisions — closed before code (Rev.4, extended in Rev.6)

Thirteen places where the spec described *what* without deciding *how*, each found by asking what two
implementers would do differently — I1–I9 from Rev.4's readiness review, **I10–I13 from Rev.6's,
which read every claim against the shipped code rather than against the spec**. They are recorded here as a block and inline at the D they
govern; the inline copy is the normative one. **None changes the design** — an item that did would
belong in §8.

| # | the question Rev.3 left open | decision | § |
|---|---|---|---|
| **I1** | `design_strength` as a new field, or the existing `strength`? | the existing **`strength`** — it already means the base img2img denoise | 2.2 |
| **I2** | who owns the `[:60]`/`[:20]`/`[:30]`/`[:120]` input caps? | **one shared normalizer** in `app.py`, lazily imported by the Lab; the widths are part of the composition contract | 2.2 |
| **I3** | test 1 compares two `compose_design` calls, or two handlers? | **two handlers**, via a monkeypatched `_render_still`, with at least one over-cap input | 2.2 / 5 |
| **I4** | Lab uses `effective_strength` while `/api/preview` keeps its inline clamp? | **`/api/preview` adopts `effective_strength`** — otherwise "one knower" is a slogan | 2.2 |
| **I5** | where does the composed description travel back? | the **`/still` response** (`{job_id, description, min_strength}`), not the job record | 2.3 |
| **I6** | does "Apply design" replace `base` or add a slot? | **replaces it, and becomes the reference** — safe only after D6; the slot itself is I12 | 2.3 |
| **I7** | mount `DesignStep` in place, or move it? | **move to `web/src/components/`**, alongside the other shared components | 2.4 |
| **I8** | `fetchDesignAxes(referenceId?, animal?)`? | **an options object** — two optional positional strings is a silent-miswire | 2.1 |
| **I9** | how is base-still parity verified by eye? | **it isn't** — the seed cannot be pinned through `/design/general`; test 1 is the gate | 7 |
| **I10** | where do the frontend guard tests live, given no jsdom? | **`labDraw.ts`, a pure module** — extract the request shaping and test that; no browser harness | 5 |
| **I11** | `effective_strength` has no 0.3 floor — adopt it anyway? | **no** — the floor moves INTO it first, and every Lab base draw goes through it | 2.2 |
| **I12** | does "Apply design" write the existing `reference` state? | **no** — a named `LabSource` union (`upload` \| `design`), one slot, two kinds | 2.3 |
| **I13** | what happens if design fields arrive on an anchor draw? | **400** — they are accepted only on `base` + `reference_id`; §0.3 becomes structural | 2.2 |

**The pattern in all thirteen, worth naming:** every one is a place where the *obvious* implementation
is wrong in a way nothing would have caught — a second strength field nobody reads, retyped caps
that drift, a test that passes before the feature exists, a positional argument silently accepted in
the wrong slot, a gate that can never go green. A spec that stops at "compose in the handler" hands
those to whoever types fastest.

**Scope correction that came with them:** `web/src/lib/api.ts` changes for D1, D2 and D3 and was
absent from "Repos touched" through Rev.3. It is the app's ONE endpoint adapter (project
`CLAUDE.md`), so its absence read as "the frontend just mounts a component."
