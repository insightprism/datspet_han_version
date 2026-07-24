# SPEC — Hybrid pose anchor (pose from a shared sprite, identity from the prompt)

**Status:** **SUPERSEDED / retained for design history**, 2026-07-24. **Rev.2.**

> **⚠️ Rev.2 — the central mechanism of this spec was FALSIFIED by the §7 experiment (2026-07-24).**
> This spec's premise — take a shared pose *sprite* and **img2img-redraw** the target animal onto it
> (pose from the sprite, identity from the prompt) — **does not work**: no denoise value holds pose
> *and* identity at once (low → the pet stays the generic sprite; high → the flight pose collapses).
> See `SPEC_POSE_ANCHORS` §7.1 for the full result. **The validated mechanism is a *fresh txt2img*
> anchor from a pose clause + the house style** (`SPEC_MOTION_PROFILES` §3.9.1, the `pose_prompt`
> kind) — simpler than this spec (no sprite asset, no redraw step). For *custom/uploaded* pets, whose
> specific identity a fresh txt2img can't hold, the reserved answer is the **`depth` control kind**
> (B-proper, deferred). **Read this doc only for the design history of why the sprite approach was
> tried and rejected; the live design is §3.9.1 + `SPEC_POSE_ANCHORS` §7.1.** The sections below are
> left as written (pre-experiment).

**What this is.** The concrete, stills-only technique to make a pet actually *move* in a pose
(a bird that flaps, a dog that runs) **without** losing the animal's identity and **without** a
ControlNet or a base-model swap. It is the refinement of `SPEC_POSE_ANCHORS` §2.B-crude that
closes B-crude's one hole — the anchor coming out as the *generic* animal instead of *this* pet.

**Relationship to the other specs.**
- **`SPEC_POSE_ANCHORS`** is the parent design-space doc: it states the problem (the shared anchor
  is a hard ceiling on motion, §1 there), the stakes (consistent movement *is* the product, §0.1
  there), and the three candidates — A (prompt anchor), B-crude (shared sprite), B-proper
  (`SPEC_MOTION_PROFILES` §3.9's Wan control tier). **This doc is the "B-hybrid" it names** — the
  one we recommend building/testing first.
- **`SPEC_MOTION_PROFILES` §3.9** owns the schema and the resolution rule (the reserved per-pose
  `control` field, `skeleton → depth → prompt`). B-proper is that tier and remains the **ceiling**;
  this hybrid is the pragmatic path that runs on **today's** pipeline and needs no control path.

**Extends:** `SPEC_POSE_ANCHORS` §2 (adds the per-pose anchor field), `SPEC_MOTION_PROFILES` (the
profile the anchor lives in).
**Deliberately revisits:** `SPEC_UPLOAD_LIKENESS` §0.1 — *"likeness is decided by one still"* — the
invariant this trades against; §2 below is the argument for why the hybrid can still honour it.
**Repos touched (proposed):** `datsme-pet-factory_wu` — `pet_factory/factory.py`,
`pet_factory/motion_profiles/`. For the caption variant only (§2.2): `webui/ai_engine.py` +
one `pet_factory/ai_purposes/` entry. **No `web/` change** (the pose menu is unaffected). The pool
path is content-only, likely no handler contract change (§8).

---

## 0. The hole this closes

B-crude (`SPEC_POSE_ANCHORS` §2.B) authors **one canonical pose sprite per body type** — a generic
flying bird, a generic running quadruped — and uses it as the img2img *source* so the pose comes
from a real image, not a hopeful text prompt. That fixes **motion** and **consistency** (every bird
flies the same, authored way). But it leaves one thing wrong: if the anchor *is* the generic
sprite, the pet's **identity** drifts toward "some bird" — a low denoise keeps the generic look, a
high one loses the pose. That is the identity↔pose whack-a-mole, and it is exactly the tuning this
repo refuses to do blind.

**The fix (the insight this spec turns on):** the generic sprite should supply **only the pose**.
The **identity** comes from a **prompt that names the target animal**. Produce an anchor that is
*"this cardinal, in the flying pose"* — right pose **and** right animal — and only *then* animate.
The two axes are separated: **pose from the shared sprite, identity from the prompt.**

---

## 1. The technique in one line

```
anchor = redraw( pose := shared_body_type_sprite,  identity := "cute cartoon <this animal>" )
pose_base = anchor          # instead of the standing/perched base
fly_loop  = Wan_I2V(prompt, start=pose_base, end=pose_base)
```

The shared sprite is authored **once per body type** and reused across every species in that
profile; the redraw that stamps *this* animal onto it runs **per pet, per anchored pose** at build
time. The result is a per-pet anchor with the body-type-consistent pose and the pet's own identity.

---

## 2. Two ways to realize "target animal in the shared pose"

Both take the shared pose sprite and produce *this animal* in that pose. They differ in which axis
is hard-held and which leans on prompt-following — a real tradeoff, not a wash.

### 2.1 Redraw — img2img from the sprite, prompt names the target (PRIMARY)

`init` = the shared pose sprite (wings-spread bird); `prompt` = the target animal (`"cute cartoon
red cardinal, wings spread mid-flap, side profile, facing right"`); a **moderate denoise**. The
init image carries the pose; the prompt repaints the identity. Reuses `_img2img_wf`, which already
exists — **no new capability.**

**Why identity holds here** (the point that makes this better than plain B-crude): within a body
type the sprite and the target **share a silhouette**, so the img2img is not inventing structure —
it is mostly a **recolour** over a pose that is *already correct* for the target. Repainting a
generic songbird to a cardinal while keeping the wing-spread shape is a short img2img hop (colour +
markings), because a cardinal's flying pose ≈ a generic bird's flying pose. **Pose is copied
(reliable); identity is repainted (reliable within a body type).**

- **Held hard:** the pose (copied from the init pixels).
- **Leans on prompt:** the identity (but only a recolour, within a body type).
- **Knob:** one `anchor_strength` **per body type**, calibrated **once** (§7) — bounded, not
  per-pet, and likely to generalise across similar cartoon animals. This is the crucial difference
  from the per-photo upload-redraw strength, which can never be one value.

### 2.2 Caption + fresh generate — vision → pose prompt → txt2img (ALTERNATIVE / identity-safe)

Use **Claude** (the AI engine already built — `SPEC_DATSPET_AI_ENGINE`) to *look at* the shared
sprite and write a **precise pose description** (`"wings fully extended upward, primaries spread,
body pitched forward, tail fanned, head level"`). Then **txt2img the target from scratch** with
that description as the pose prompt. No init image, so **zero generic-sprite residue.**

- **Held hard:** the identity (fresh generation of the actual animal).
- **Leans on prompt:** the pose (prose-driven — more reliable than `"flying"` because it is
  detailed and vision-authored, but still not *copied* like 2.1).
- **No `anchor_strength`** (it is txt2img), at the cost of **+1 vision call** per body-type sprite
  (the caption is authored **once per sprite**, not per pet — cache it in the profile).
- **Synergy:** this is one more `ai_purposes/` entry (`pose_caption`, `fast` tier, image input) in
  the exact registry the upload captioner already uses — the engine is done, this is content.

### The choice, in one table

| | Pose fidelity | Identity fidelity | New capability | Cost | Best when |
|---|---|---|---|---|---|
| **2.1 Redraw** (primary) | **high** — copied from the sprite pixels | high *within a body type* (a recolour) | none (`_img2img_wf` exists) | +1 img2img / anchored pose / build | source & target share a silhouette (songbirds, quads) |
| **2.2 Caption+t2i** | medium — prose-driven | **perfect** — fresh gen | one `ai_purposes` entry + a vision call (once/sprite) | +1 txt2img / anchored pose / build | identity bleed from 2.1 is unacceptable, or the target silhouette differs from the sprite |

**No free lunch.** Each hard-holds *one* axis and trusts prompt-following for the other. Holding
**both** at once — pose *and* identity structurally constrained — is precisely what B-proper
(`SPEC_MOTION_PROFILES` §3.9, Wan skeleton/depth control) buys, and why it stays the ceiling. But
for **cartoon animals within a shared body type**, the hybrid is very likely good enough, and it is
dramatically cheaper — so it is the correct thing to build first.

**Working recommendation (decision 2):** ship **2.1 (redraw)** as the primary; keep **2.2** as the
identity-safe fallback for bodies where the shared sprite bleeds the wrong shape. §7 measures both
on the same bird before committing.

---

## 3. How it fits the registry — no redesign

This rides the existing engine-vs-content boundary; nothing here makes the engine branch on species.

- **The shared pose sprite is per-body-type content.** `avian/fly.pose.png`,
  `quadruped/run.pose.png` — one asset per movement per profile, stored in the profile directory
  **the way `animal_catalog` stores `base.png` per breed** (the binary-asset pattern already
  exists, and `animal_catalog/**/*.zip` is already deliberately un-gitignored as shipped content).
- **Reused across every species that resolves to the profile.** A cardinal, blue jay, robin, and
  sparrow all resolve to `avian` and share `avian/fly.pose.png` — that *is* the reuse. Authoring is
  once per body type, not per animal.
- **The per-pose field is `SPEC_MOTION_PROFILES` §3.9's `control` block — RESOLVED.** No new field.
  The redraw sprite is a new **`kind`** on the existing `{kind, ref, strength}` block
  (`§3.9.1`): `control: { kind: "sprite", ref: "avian/fly.pose.png", strength: 0.5 }`. Precedence
  is `pose_skeleton → depth → sprite → prompt`. The sprite kind **reuses the pose's `action`/`suffix`**
  as its redraw prompt (already `{animal}`-spliced by `compose_pose_prompt`), so it stores **no
  per-species string** and needs no `prompt_template` field. This is the least-divergent answer — it
  reuses the seam §3.9 already built for "future kinds," and the engine dispatches per-kind (sprite →
  redraw-then-standard-loop). The "pose anchor" of this spec *is* `control.kind == "sprite"`.
- **Silhouette-match caveat + the specificity escape hatch.** The shared sprite must roughly match
  the target's silhouette. Songbirds share one; a **penguin** or **flamingo** does not — a shared
  songbird sprite would bleed the wrong body. Those birds get their **own** sprite via the
  specificity mechanism (`SPEC_MOTION_PROFILES` §3.7: a `penguin.json` at level 2 wins over `avian`
  at level 3, used whole). The registry already routes each animal to the right profile, so "which
  birds need their own pose sprite" is answered by the same resolution that picks the profile — no
  new machinery. Same for quads: one running-quadruped sprite for cat/dog, a specific one only
  where a body genuinely differs.
- **The engine still reads content and never names a species.** `factory.py` applies "if this pose
  has an anchor, redraw the base into it" uniformly; the *which pose, which sprite, which strength*
  is all data in the profile. Adding a body type or a specific override is a content edit.

---

## 4. The pipeline

In `factory.py`'s pose loop, per pose:

```python
if pose.anchor:                       # content: this pose declares a shared pose sprite
    pose_base = redraw(base, pose.anchor, strength=pose.anchor_strength)   # §2.1  (or caption+gen, §2.2)
else:
    pose_base = base                  # today's behaviour — byte-identical (§6)
pose_files[name] = _run(_loop_wf(compose_pose_prompt(animal, pose), str(pose_base), seed))
```

- **The anchor redraws from the DESIGNED base, not the plain base** (resolves `SPEC_POSE_ANCHORS`
  §8's open ordering question): a *red* cardinal's fly anchor must be red, so the redraw runs
  **after** step 2's design is applied, on the final base the loops already animate from. Identity
  is therefore anchored on the same designed still `SPEC_UPLOAD_LIKENESS` §0.1 relies on — the
  redraw only asks the pose to change.
- **Cost:** the generic sprite is authored **once per body type** (offline); the per-pet anchor is
  `+1 generation per anchored pose per build`. Only `fly`/`run`/`jump` carry anchors (§5), so a
  5-pose bird with one anchored pose is one extra redraw (~10 s) on a ~3-min build.

---

## 5. Scope — which poses get an anchor

Unchanged from `SPEC_POSE_ANCHORS` §5: **only silhouette-changing poses** — `fly` (wings must open),
`run`/`jump` (legs extended / airborne). `walk`, `idle`, `sit`, `sleep`, `eat`, `play` animate fine
from the shared standing/resting base and get **no** anchor. This bounds both the per-build cost and
the identity-drift surface to the few poses that need it. It is content, per profile — `avian.fly`
gets a sprite, `avian.idle` does not.

---

## 6. Backward compatibility (hard requirement)

A pose with **no anchor** behaves **byte-identically** to today: `pose_base = base`, same `_loop_wf`
call, same bytes. Every existing profile ships without anchors, so today's pets are bit-identical
after this change — the field is purely additive. A guard test pins it (a pose without an anchor
produces the exact current workflow), the same way `compose_pose_prompt` is pinned against the old
hardcoded form.

---

## 7. Validate before building — the experiment

Refines `SPEC_POSE_ANCHORS` §7 with the hybrid as the **primary arm**. All on the dev-box GPU, no
schema and no plumbing first.

> **`SPEC_MOTION_LAB` productizes this loop.** A first hand-run proves the technique flaps at all;
> the Motion Lab then turns "pick animal + pose → see the sprite → edit the redraw prompt → run →
> watch it animate → save to the profile" into a repeatable admin UI, which is what makes the
> per-species grind (steps 2.1 across many birds/quads) practical. Prove once by hand, then author
> in the Lab.

1. Author **one** generic `avian/fly` pose sprite (wings open, side profile) — generate it with the
   existing Z-Image generator and cut it out with the pipeline's birefnet, then hand-pick a clean one.
2. Produce a **flying-cardinal anchor three ways** from the same *designed* cardinal base:
   - **Arm A** (baseline, `SPEC_POSE_ANCHORS` §2.A): img2img the base with `"wings spread, flying"`
     — no sprite. The floor to beat.
   - **Arm 2.1 (redraw — the candidate):** img2img the cardinal *onto* the shared sprite at a few
     strengths.
   - **Arm 2.2 (caption+t2i):** caption the sprite's pose with Claude, txt2img the cardinal fresh.
3. Animate **only** the `fly` loop from each anchor.
4. Judge **four** things:
   - **(a) Motion** — do the wings actually beat now?
   - **(b) Identity** — is the flying cardinal still *this* cardinal? (the §0.1 test)
   - **(c) Consistency** — run a **second** bird (robin) and a **third** (blue jay) through **Arm
     2.1 with the SAME sprite.** Do they fly the same way *and* stay themselves? This is the whole
     case for a shared sprite over per-pet prompting.
   - **(d) Silhouette limit** — run a **penguin** through the songbird sprite. Does it bleed the
     wrong body? A "yes" is not a failure — it *locates* where a specific `penguin.json` pose sprite
     is needed (§3's escape hatch), which is a design output, not a bug.

**Reading it:**
- **2.1 wins (a)+(b)+(c)** → build §2.1, scoped to §5's poses, with the calibrated per-body-type
  strength. Target outcome.
- **2.1 bleeds identity but 2.2 holds it** → ship 2.2 for that body type (accept the vision call).
- **Neither opens the wings even from a spread anchor** → the stills path is a dead end for `fly`;
  escalate to B-proper (§3.9 Wan control) or accept the ceiling. (This would also condemn plain
  B-crude, so it is worth knowing early.)

---

## 8. Open questions (live — this is a draft)

- ~~Field shape: reuse §3.9 `control`, or a new `anchor` block?~~ **RESOLVED (§3): `control.kind ==
  "sprite"`** on §3.9's `{kind, ref, strength}` block — one field, precedence
  `pose_skeleton → depth → sprite → prompt`, redraw prompt reuses `action`/`suffix`. See
  `SPEC_MOTION_PROFILES` §3.9.1.
- **`anchor_strength` calibration (2.1).** One value per body type is the hypothesis (§2.1); §7
  must confirm it generalises across the profile's species. This is a bounded sweep, not a guess —
  the calibration-harness discipline (`SPEC_PET_DESIGN_AXES` §8).
- **Caption fidelity (2.2).** Does a detailed prose pose actually hold in txt2img for this cartoon
  style, or does the model still drift to a neutral pose? Measured in §7 Arm 2.2.
- **Redraw vs caption as the shipped default.** §2's recommendation is 2.1-primary / 2.2-fallback;
  §7 decides per body type. It may be mechanism-per-profile (redraw for birds, caption for a body
  whose sprite bleeds), which the registry can carry as content.
- **Authoring standard for the shared sprites.** One clean, neutral, side-profile pose sprite per
  movement per body type that redraws well across species — one-time content work (like authoring a
  motion profile), but it needs a small quality bar.
- **The `pose_caption` purpose (2.2 only).** A new `pet_factory/ai_purposes/pose_caption.json`
  (`fast` tier, image input, output a short pose phrase). Author it now, or only if §7 picks 2.2?
  Deferred until §7.
- **Transition seams.** Inherited from `SPEC_POSE_ANCHORS` §3.2 — different-silhouette loops rest at
  different frames, so idle→fly may jump. Depends on the host runtime's pose-switch behaviour; a
  shared rest frame / bridge pose / accepted jump. Unchanged by the hybrid.
- **Pool path.** The extra per-pose redraw runs on the worker as content (the sprite is in the
  profile the worker already loads), so this likely needs **no** handler param change — unlike
  `isolate_subject`. Confirm against `pet_factory_handler`'s schema before assuming. Deferred.

---

## 9. Decisions (running log)

| # | Question | Answer | Why |
|---|---|---|---|
| 1 | How to keep identity when the anchor comes from a shared sprite? | **Separate the axes — pose from the sprite, identity from a prompt that names the target** | The sprite supplies only the pose; the pet's identity is repainted/generated from its own name (§0/§2) |
| 2 | Which mechanism ships? | **2.1 redraw (img2img from the sprite) primary; 2.2 caption+t2i as the identity-safe fallback** | Redraw copies the pose (reliable) and, within a body type, only recolours identity; caption+t2i holds identity perfectly when the sprite bleeds (§2) |
| 3 | Where does the shared sprite live? | **Per-body-type content in the profile dir, like `animal_catalog`'s `base.png`; reused across species** | The reuse win and the existing binary-asset pattern; adding one is a content edit (§3) |
| 4 | Divergent silhouettes (penguin vs songbird)? | **A specific profile's own sprite via `SPEC_MOTION_PROFILES` §3.7 specificity** | The resolution that picks the profile already routes the exception; no new machinery (§3) |
| 5 | Redraw from the plain or the designed base? | **The designed base (post step-2)** | A red cardinal's fly anchor must be red; identity stays anchored on the same still §0.1 relies on (§4) |
| 6 | Which poses get an anchor? | **Only silhouette-changing ones (fly/run/jump)** | Bounds cost and identity-drift to where it is needed (§5) |
| 7 | Backward compatibility? | **A pose with no anchor is byte-identical to today** | Purely additive, guard-test pinned (§6) |
| 8 | Build first or validate first? | **Validate — the three-arm experiment before any code** | The design hinges on unmeasured "does it flap, and does identity hold?" (§7) |
| 9 | Field shape (`anchor` vs §3.9 `control`) | **RESOLVED — `control.kind == "sprite"` on §3.9's `{kind, ref, strength}` block** | Reuses the seam §3.9 built for "future kinds"; precedence `pose_skeleton → depth → sprite → prompt`; redraw prompt reuses `action`/`suffix`, so no per-species string is stored (`SPEC_MOTION_PROFILES` §3.9.1) |
| 10 | `anchor_strength` value(s) | **OPEN — one per body type, confirm it generalises (§7)** | Bounded calibration, not the per-photo whack-a-mole (§8) |

---

## 10. Where it would touch the code

- `pet_factory/factory.py` — the pose loop gains the per-pose redraw step (§4): when a pose declares
  an anchor, build `pose_base` via `_img2img_wf` from the shared sprite (2.1) or caption+txt2img
  (2.2); else `pose_base = base`. Gated on the field, **never branching on species.**
- `pet_factory/motion_profiles/` — the per-pose anchor field (§8 decides `anchor` vs §3.9 `control`)
  + the shared pose-sprite assets (`avian/fly.pose.png`, …) stored like `animal_catalog`'s `base.png`.
- `pet_factory/tests/` — backward-compat pin (no anchor ⇒ today's workflow, byte-identical) and the
  anchor-field validator (shared with `motion_admin.validate_profile`, so the admin can't author an
  anchor the build would reject).
- `webui/ai_engine.py` + `pet_factory/ai_purposes/pose_caption.json` — **only if §7 picks 2.2** —
  one new purpose in the existing registry; no engine change (the captioner path is done).
- **No `web/` change** — the pose menu, reference flow, and candidate strip are all upstream; the
  anchor is a generation-time detail invisible to the browser.

---

## 11. Why this is the one to build first

- It is the **cheapest path to consistent motion**: no ControlNet, no base-model swap, runs on
  today's `_img2img_wf`, and the only tuning is a **bounded, once-per-body-type** strength (§2.1) —
  not the per-photo calibration this repo refuses to do.
- It **fixes the identity leak** that was the one objection to plain B-crude, by construction (§0).
- It **fits the registry with no redesign** — per-body-type content, reused across species, engine
  unchanged, specificity as the escape hatch (§3).
- **B-proper (`SPEC_MOTION_PROFILES` §3.9 Wan control) stays the ceiling** — the structurally-exact
  end state. This hybrid is the pragmatic first build that either satisfies the need outright or, via
  §7, tells us precisely where only a real control signal will do.
