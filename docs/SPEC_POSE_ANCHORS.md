# SPEC — Per-pose motion anchors (making the animation actually move)

**Status:** proposed / **DRAFT for review**, 2026-07-24. **Rev.2.** A design-in-progress doc,
NOT implementation-ready — written to be reviewed and updated as the design settles. No code
is written; the first committed step is a **single-anchor experiment** (§7), not a build. The
Decisions (§9) and Open questions (§8) are the parts we keep refining.

**Rev.2 adds the branch that matters:** two ways to build the anchor (§2) — a per-pet *prompt*
anchor (A) versus a **reusable pose control / silhouette shared across species** (B) — and names
the model-feasibility gate that decides whether the better one (B) is even buildable on the
current base model. Rev.2 also elevates the real motivation: **consistency** (§0.1).

**Rev.3 — the registry already reserved this; §3.9 is the authoritative home.** Verified against
`SPEC_MOTION_PROFILES` §3.9 and the code: the concept is **not new**. The `Pose` schema already
carries an optional `control` field (*"skeleton/depth placeholder — None at launch"*), §3.9 is a
dedicated *"Control-signal tier"* section that reserved exactly this *"for the day prompts hit their
ceiling"* (that day is now), and it names the mechanism — **Wan 2.2 I2V's own control path (Wan
Animate / VACE, driven by a pose skeleton or depth), NOT a Z-Image ControlNet.** That **resolves
decision 11** (the feasibility gate was the wrong layer) and reframes the spec: **Approach B-proper
*is* §3.9's control tier** — already scoped as "pure content + one control path," backward-compatible
by construction. This doc now refines §3.9's *how*; §3.9 owns the schema and the resolution rule.

**Extends:** `SPEC_MOTION_PROFILES` (the pose taxonomy this adds a field to).
**Deliberately revisits:** `SPEC_UPLOAD_LIKENESS` §0.1 — whose *"likeness is decided entirely by
one still"* invariant is exactly the property this design trades against (§4).
**Repos touched (proposed):** `datsme-pet-factory_wu` — `pet_factory/factory.py`,
`pet_factory/motion_profiles/`. No `web/` change (the pose menu is unaffected). The pool handler
is deferred (§8).

A user makes a bird, selects **fly**, and it barely moves — a red cardinal that sits there with
a tiny wing-crack instead of flapping. This is what it would take to make the wings actually beat.

---

## 0. The problem, stated precisely

The bird is **not** missing the fly pose — that is a different, solved layer (pose *availability*
is the motion-profile keyword gate, `SPEC_MOTION_PROFILES`; a bird whose name resolves to `avian`
already gets `fly` in its menu, and the generated bundle already contains a `fly` loop).

The problem is **motion range**: the `fly` loop is generated, but the bird inside it barely moves.
Selecting the pose works; the *animation* does not read as flight.

### 0.1 The real stakes: movement is the product, and it is inconsistent

**The whole premise of a DatsMe pet is that it moves.** A pet that sits still is a sticker. So
"the fly loop doesn't flap" is not a cosmetic nit — it is the product failing at the one thing it
exists to do.

And the failure is **inconsistent**, which is worse than uniformly bad: two birds, same pipeline,
one flaps and one doesn't — purely because of the pose their base still happened to land in (open
wings vs. folded, standing vs. crouched). The user cannot see the cause and cannot fix it. **A
product whose core feature works by luck is the thing this spec is trying to remove.** The design
goal is therefore not just "more motion" but *consistent* motion — every animal of a body type
moving the same, reliable way. That goal is what separates the two approaches in §2.

---

## 1. The finding this turns on — one anchor, reused for every pose

```python
# factory.py — the pose loop:
base = _base_sprite(animal, reference_image=…, remix_strength=…, seed=seed)   # ONE still, made once
for name in pose_names:
    pose_files[name] = _run(_loop_wf(mp.compose_pose_prompt(animal, pose), str(base), seed))
#                                     ^ per-pose PROMPT (varies)              ^ the SAME base (every pose)

# inside _loop_wf, the Wan node (factory.py:214-217):
"WanFirstLastFrameToVideo": { "start_image": ["9",0], "end_image": ["9",0] }   # node 9 = that one still
```

**Every pose loop begins and ends at the identical still.** Wan 2.2 I2V interpolates the ~15
frames between the two endpoints, and the *only* thing that differs per pose is the text prompt
(`compose_pose_prompt` = `cute cartoon {animal} {action}, side profile, facing right{suffix}`).

> **The anchor pose is a hard ceiling on the motion.** A `fly` loop whose first *and* last frame
> is a **perched bird with folded wings** can only crack the wings slightly open and close them
> back — it cannot complete a wingbeat, because the loop is required to return to the folded
> anchor. The prompt asks for flight; the anchor forbids it.

This is not a bug — it is `SPEC_UPLOAD_LIKENESS` §0.1 working as designed (*"make one picture look
like my dog, and step 3 is innocent"*). The single anchor is what guarantees the pet is the **same
animal** in every pose. But that same property is the ceiling on how much any pose can move.

---

## 2. Two ways to build a per-pose anchor

Both approaches make the same move — give a pose the still it animates *from*, shaped for that
motion — and both fit the repo's grain (the `Pose` schema already carries `action`/`suffix` as
*motion* content; this adds an *anchor*). They differ in **how the pose is imposed**, and that
difference decides the thing §0.1 says matters most: **consistency.**

**Schema — the `control` block, kind `pose_prompt` (VALIDATED 2026-07-24; see §7.1).** `Pose`
reserves an optional `control` block (§3.9). The **validated** anchor kind is a fresh-text pose
prompt; the sprite/img2img kind the earlier draft proposed was **falsified** by the experiment:

| Kind | Fields | Status |
|---|---|---|
| `pose_prompt` | `pose` = a static pose clause (`"wings spread wide open, mid-flight"`) | **VALIDATED — ships first.** Fresh txt2img anchor (`_base_prompt` with `pose` swapped for `standing`), then the standard loop (§3.9.1, §7.1) |
| `depth` / `pose_skeleton` | `ref` = depth/skeleton asset; `strength` = control weight | **RESERVED / deferred** — control-driven loop that holds a *custom* pet's identity (the datsPet path); the answer for uploaded/designed pets that fresh-gen can't serve |
| ~~`sprite`~~ | ~~`ref` = shared pose image; `strength` = denoise~~ | **REJECTED** — no denoise held pose + identity together (§7.1) |

Precedence `pose_skeleton → depth → pose_prompt → loop-only`; absent ⇒ animate from the shared base
still (today, byte-identical, §6). **The prose of §2.A/§2.B below is pre-experiment design history;
§7.1 is the result that supersedes its recommendation.**

**Pipeline (common).** In `factory.py`'s pose loop, per pose: if the pose declares an anchor,
produce `pose_base` (an img2img over the base — §2.A or §2.B); else `pose_base = base` (today's
behaviour). Then `_loop_wf(compose_pose_prompt(...), pose_base, seed)`. The choice is per-pose,
per-profile — data, not code.

> **This is not a new concept — it is the reserved `SPEC_MOTION_PROFILES` §3.9 control tier.** §3.9
> ("Control-signal tier — a forward-compatible placeholder for skeleton-driven motion") already
> defines the field and the rule: the canonical `Pose` carries an optional **`control`** block
> (in the code today: `Pose.control`, loaded, `None` at launch), the resolution precedence is
> **skeleton → depth → prompt**, and with no control present generation is **byte-identical** to
> today (§6). §3.9 names the mechanism: the control drives **Wan 2.2 I2V's own motion path (Wan
> Animate / VACE from a pose skeleton or depth)** — so it constrains the *whole animation*, not
> merely the anchor still, and it does **not** depend on a Z-Image ControlNet. §3.9 warns the
> sibling `datsPet`'s AP-10K skeleton *data model* ports cleanly but its **SD-1.5 ControlNet wiring
> does not** — Wan 2.2 I2V needs its own control path (the real build). **Approaches A and B-crude
> below are stills-only *fallbacks* that need no control path; the target — B-proper — IS §3.9's
> control tier, and the registry was built for it** (`Pose.control`, per-pose × per-body-type).

### 2.A — Prompt-driven anchor (per-pet; feasible on today's model)

`anchor` is a **text** redraw prompt: `fly` → `"wings spread wide, mid-flight"`. `factory.py`
img2img-redraws the base into that pose (`_img2img_wf`, which already exists), then animates.

- **Feasible now** — Z-Image-Turbo img2img *is* `_img2img_wf`; no new capability.
- **But the pose is imposed by TEXT**, which the model may or may not honour — loose control. And
  each pet's fly pose is generated *independently*, so it varies bird to bird. **It does not solve
  §0.1's consistency problem** — it only raises the odds a given bird flaps.

### 2.B — Reusable pose control / silhouette (the consistency fix)

Author **one canonical pose per movement per BODY TYPE** — a "flying bird" pose, a "walking
quadruped" pose — and reuse it across every species in that profile; the model fills in the
animal's identity (colour, coat, markings). The pose is **content authored once** (like a motion
profile), not generated per pet.

This is the structurally-correct answer and the **direct fix for §0.1**: every bird flies the
*same* canonical way, so movement stops depending on the luck of the base pose. It also matches
`SPEC_MOTION_PROFILES`' taxonomy — the pose asset belongs to the *profile* (avian, quadruped, …),
authored at the body-type level and inherited by every animal that resolves to it.

The proper mechanism is **pose/structure conditioning — ControlNet** (pose / depth / edge). The gate:

> **Feasibility gate (decision 11). The base model is Z-Image-Turbo
> (`zImageTurbo_turbo.safetensors`), and the pipeline uses NO ControlNet today.** Z-Image-Turbo is
> a niche, distilled turbo model — it likely does not have the mature ControlNet ecosystem SDXL /
> Flux do, so a pose ControlNet may simply **not exist** for it. Proper pose conditioning probably
> requires either finding a Z-Image ControlNet (verify) or **adding/switching a base model** that
> has one — a far bigger change than a prompt field, with its own blast radius (§8).

**B without a ControlNet — the feasible middle ("B-crude").** Author the canonical pose as a
**reference sprite** (a generic flying bird, a generic walking quadruped) and use it as the
**img2img *source*** — redraw the specific animal onto it. The pose comes from the source *image*
(much stronger than a text prompt); the identity from the prompt + `anchor_strength`. Cruder than
ControlNet — it conditions on *pixels*, not structure, so a low denoise keeps the generic sprite's
look and a high one loses the pose — but it is **reusable across species** (the whole idea) and
runs on the **current** img2img. `anchor_strength` is the identity↔pose knob §7 must calibrate.

> **→ B-hybrid closes B-crude's identity leak — see `SPEC_POSE_ANCHOR_HYBRID`.** The refinement:
> let the shared sprite supply **only the pose** and a prompt that **names the target animal**
> supply the identity, so the anchor is *"this cardinal, flying"* rather than a generic bird. That
> is the recommended-first, stills-only build; it fits this registry with no redesign and keeps
> B-proper (§3.9 Wan control) as the ceiling. This doc keeps the design-space overview; the hybrid
> spec is the implementation-oriented child.

### The choice, in one table

| | Consistency (§0.1) | Identity control | Feasible on today's Z-Image? | Cost |
|---|---|---|---|---|
| **A** — prompt anchor | low — varies per pet | loose (text-driven pose) | ✅ yes (`_img2img_wf`) | +1 redraw / anchored pose |
| **B-crude** — shared pose *sprite* as img2img source | **high** — one pose per body type | medium (`anchor_strength` knob) | ✅ yes (`_img2img_wf`) | +1 redraw / anchored pose, + author the sprites once |
| **B-proper** — ControlNet | **high** | high (structure held, identity free) | ❓ needs a Z-Image ControlNet (likely absent) or a model swap | model change |

**Working recommendation — RESOLVED by the §7.1 experiment (2026-07-24):** neither A nor the sprite
B-crude. The experiment falsified the sprite/img2img redraw (no denoise holds pose + identity), and
the **fresh-text `pose_prompt` anchor** (a pose clause + the house style, txt2img, then the standard
loop) delivered pose + identity + style on a cardinal (`L7`). Ships as `SPEC_MOTION_PROFILES` §3.9.1's
`pose_prompt` kind; the `depth` control (was "B-proper") is deferred for custom/uploaded pets. The
§2.A/§2.B prose below is retained as pre-experiment design history.

---

## 3. What the single anchor silently buys (the tradeoffs to weigh)

The shared anchor is not laziness; it pays for three properties this design puts at risk. Naming
them is the point of writing this down before building.

1. **Identity consistency.** Today every pose is *literally the same image*, so the cardinal is
   identically red and shaped in walk, idle, and fly. A separately-produced fly anchor is a *new*
   image — potentially a subtly different bird (redder, different beak, different proportions).
   The pet could **shimmer identity as it cycles poses.**
   → *Mitigation (§4):* redraw each anchor from the base via **img2img**, never txt2img, so it
   stays the same bird. But that reintroduces the strength↔fidelity tension (the sitting-dog
   problem, one level up).

2. **Transition seams.** The DatsMe runtime plays each pose as its own loop and switches between
   them. Today every loop rests on the *same* still, so idle→walk→fly is seamless. With per-pose
   anchors, each loop rests at a *different* silhouette (folded vs. spread), so switching poses
   would **visibly jump.**
   → *Mitigation: OPEN (§8).* A shared rest frame, a bridge pose, or an accepted jump.

3. **Cost.** `1 still → N loops` becomes `N stills → N loops` — an extra img2img per anchored pose.
   → *Mitigation:* anchors only on the poses whose silhouette must change (§5), not all N.

---

## 4. The identity question, head-on

`SPEC_UPLOAD_LIKENESS` §0.1 rests its whole argument on *one still decides the likeness.* This
design breaks that literally: N stills, N chances to drift. That is the load-bearing objection and
must not be hand-waved.

The case that it can still hold: the anchor is produced by **img2img from the base at moderate
strength**, so it is the *same bird changing pose*, not a bird redrawn from scratch — the same
machinery step 1's upload redraw and step 2's design redraw already use. Identity is anchored on
the base image; only the pose is asked to change.

But: **this is asserted, not measured** — the recurring rule of this whole area. §7's experiment
must judge **identity across the anchors**, not only whether the wings moved. If the wings-spread
cardinal is visibly a different bird, the design fails its own §0.1 objection and needs either a
lower `anchor_strength` (less pose change, safer identity) or a different mechanism (§8's
two-keyframe variant).

---

## 5. Scope — which poses get an anchor

Only poses whose **silhouette must differ from the standing/perched base**:

| Pose | Anchor? | Why |
|---|---|---|
| `fly` | **yes** | wings must be open to beat |
| `run`, `jump` | **probably** | legs extended / body airborne — the base is standing still |
| `walk`, `idle`, `sit`, `sleep`, `eat`, `play` | **no** | small motion around the standing/resting base is fine from the shared still |

This is content, per profile — `avian.fly` gets an anchor, `quadruped.walk` does not. It bounds
both the cost (§3.3) and the identity-drift surface (§4) to the few poses that actually need it.

---

## 6. Backward compatibility (a hard requirement)

A pose with **no `anchor`** must behave **byte-identically** to today: `pose_base = base`, same
`_loop_wf` call, same output. Every existing profile ships without anchors, so **today's pets are
bit-identical after this change** — the field is purely additive. A guard test pins this (a pose
without `anchor` produces the exact current workflow), the same way `compose_pose_prompt` is pinned
byte-for-byte against the old hardcoded form.

---

## 7. Validate before building — the single-anchor experiment

**Do not build the schema or the pipeline first.** The whole design hinges on one unmeasured
assumption: *does Wan actually flap the wings when the anchor is wings-spread?* Answer that with a
throwaway before writing any code:

1. On the dev box (GPU), produce a wings-spread cardinal anchor **two ways**, from the same base:
   - **Arm A (prompt):** img2img the base with `"wings spread, mid-flight"` at a few strengths.
   - **Arm B-crude (pose sprite):** find or make **one** generic "flying bird" sprite (wings open)
     and img2img the cardinal *onto* it at a few strengths — pose from the source image, bird from
     the prompt.
2. Animate **only** the `fly` loop from each anchor.
3. Judge **four** things, not one:
   - **(a) Motion** — does it actually beat the wings now?
   - **(b) Identity (§4)** — is the flying cardinal still the same bird as the base?
   - **(c) Consistency (§0.1) — the deciding one for A vs B.** Run a *second* bird (e.g. a robin)
     through **Arm B-crude with the SAME sprite.** Do the two birds fly the *same* way? That is the
     entire case for B over A; A can't be tested for this (each pet is independent by construction).
   - **(d) Transition (§3.2)** — how jarring is folded-idle → spread-fly?

**Reading the result:**
- **B-crude wins (a)+(b)+(c)** → build §2.B-crude (the sprite-conditioned anchor), scoped to §5's
  poses. This is the target outcome.
- **Only A works** (the shared sprite muddies identity, but a text prompt opens the wings) → fall
  back to §2.A, accepting per-pet inconsistency.
- **Neither opens the wings** (Wan won't beat even from a spread anchor) → anchors are a dead end;
  the lever is elsewhere (a proper ControlNet / a different model — §8), or the ceiling is accepted.

This is the cheapest decisive test — no schema, no plumbing — and it is entirely a GPU-side
dev-box act.

### 7.1 Results (run 2026-07-24 — 2×RTX 3090, ComfyUI, on a red cardinal)

**The core thesis is CONFIRMED and the mechanism is redirected.**

**Thesis — CONFIRMED.** Same `fly` loop, same cardinal, only the anchor pose differs:
- Standing/folded anchor → the wings crack open and settle back; a twitch, not flight (the ceiling).
- Wings-spread anchor → a **full wingbeat cycle** (wings sweep up → down → up across the loop).

So the shared anchor *is* the motion ceiling (§1), and a per-pose spread anchor unlocks real flapping.

**Mechanism — redirected from sprite/img2img to fresh-text.** Each stills-only img2img arm failed on
a different axis; only a fresh txt2img delivered all three (pose + identity + house style):

| Arm | Pose | Identity | Style |
|---|---|---|---|
| A — prompt img2img on the standing base | ❌ stayed folded | ✅ | ✅ |
| sprite img2img (redraw pet onto a flying sprite), d=0.5–0.6 | ✅ | ❌ generic grey | ❌ |
| sprite img2img, d=0.75–0.85 | ❌ pose collapses | ✅ | ✅ |
| **fresh txt2img — pose clause + house style** | ✅ | ✅ | ✅ (**winner**, `L7`) |

No img2img strength separates the axes (the source image fixes pose *and* identity *and* style
together). The winner — a **fresh txt2img anchor from a pose clause + the house-style prompt**, then
the standard loop — is *simpler* than the sprite plan (no shared sprite asset, no redraw step) and is
realized as `SPEC_MOTION_PROFILES` §3.9.1's **`pose_prompt`** kind. **The sprite-redraw hypothesis
(the old §2.B-crude / `SPEC_POSE_ANCHOR_HYBRID`) is FALSIFIED.**

**Two caveats carried forward.** (1) n=1 species/seed — a breadth pass (more birds, a quad running,
seed variation) is still owed. (2) Fresh-gen matches a *species*, not a *custom/uploaded* pet — those
fly as a generic species and need the `depth` control kind (B-proper, §8), deferred. **Decision
(2026-07-24): ship `pose_prompt` now for typed species; scope `depth` for custom pets later.**

Artifacts: `…/scratchpad/pose_anchor_exp/` — `L1` (standing → twitch), `L3` (spread → flaps),
`L7` (the styled flapping cardinal), `10` (the winning anchor still).

### 7.2 Breadth pass (run 2026-07-24 — resolving §7.1 caveat 1: does one clause generalize?)

Ran the exact `pose_prompt` recipe (fresh txt2img, house style, a **fixed** pose clause, only the
animal varies) across a body type, plus seed variation and the divergent case:

| Animal | Body / pose | Motion | Identity | Style | Notes |
|---|---|---|---|---|---|
| robin | avian / fly | ✅ full flap | ✅ | ✅ | seeds 42 & 7 both clean |
| sparrow | avian / fly | ✅ full flap | ✅ | ✅ | |
| blue jay | avian / fly | ✅ full flap | ✅ | ✅ | the bird that "didn't fly" originally |
| **penguin** | avian / fly | ✅ grounded flipper-flap | ✅ | ✅ | **divergent** — the shared "flying" clause gives a plausible grounded flap, *not* flight |
| tabby cat | quadruped / run | ✅ trotting gait | ✅ | ✅ | one shared run clause |
| corgi | quadruped / run | ✅ running gait | ✅ | ✅ | seeds 42 & 7 both clean |

**Findings.**
1. **One clause per body type works.** The songbird fly clause flew robin/sparrow/blue jay; the
   quadruped run clause ran cat/corgi — the clause is a **body-type-level content asset**, exactly the
   registry model (§3.7). §7.1 caveat 1 (generalization) is **resolved for typed species**.
2. **Seed-robust.** Robin and corgi both held across two seeds — not a lucky draw.
3. **Graceful degradation + specificity confirmed.** The penguin (flightless, divergent body) got
   plausible-but-different motion from the shared clause (a grounded flipper-flap, not flight) — **not
   garbage**, and improvable with a specific `penguin.json` clause. Exactly the purpose of the §3.7
   specificity escape hatch, now demonstrated.
4. **Style has family resemblance, drifts slightly across species** (birds painterly, cat/corgi
   chibi). Within one pet (same animal, all poses) this is a non-issue; the cross-species drift is
   cosmetic. One end-to-end check still owed: the fresh anchor's style vs the *actual base still* of
   the same pet (both are house-style-generated, so they should match).

**Verdict: `pose_prompt` is validated for typed species across body types (avian + quadruped).
Cleared to implement.** The custom/uploaded-pet gap (§7.1 caveat 2) remains the deferred `depth` job.

Artifacts: `…/scratchpad/pose_anchor_breadth/` — `b1–b4` birds, `q1–q2` quads, `_montage.png` each.

---

## 8. Open questions (this is a draft — these are the live ones)

- **Base-model / ControlNet feasibility (decision 11) — the biggest unknown.** B-proper (§2.B)
  needs a pose **ControlNet for Z-Image-Turbo**, which the pipeline doesn't use and which likely
  doesn't exist for this niche turbo model. Verify whether *any* Z-Image ControlNet exists. If not,
  the choices narrow to **B-crude** (no ControlNet) or a **base-model change** (e.g. SDXL / Flux +
  their pose ControlNets) — a decision far larger than this spec, weighed against everything
  Z-Image-Turbo buys (speed, the 8-step turbo cost, the established look). **Do not assume a model
  swap; it is its own spec.**
- **Authoring the pose sprites (B-crude).** Who makes the canonical "flying bird" / "walking
  quadruped" sprites, and to what standard? One per movement per body type. It is one-time content
  work (like authoring a motion profile), but it needs a clean, neutral, side-profile sprite that
  redraws well across species — itself a small calibration.
- **Transition seams (§3.2).** Shared rest frame, an explicit bridge pose, or accept the jump?
  The runtime's pose-switching behaviour (does DatsMe blend, or hard-cut?) decides how bad this is
  — needs a look at the host runtime, not just this repo.
- **`anchor_strength` calibration.** One global value, per-profile, or per-pose? This is the
  identity↔pose-change knob (§4) and is exactly the kind of value that needs a measurement sweep,
  not a guess (the calibration-harness discipline, `SPEC_PET_DESIGN_AXES` §8).
- **Two-keyframe variant.** `WanFirstLastFrameToVideo` accepts a *different* first and last frame
  (today they are the same). Instead of (or with) a spread anchor, give it **wings-up as start and
  wings-down as end** and let it interpolate a real beat. Worth running as a second arm of §7's
  experiment — it may achieve motion with *less* identity risk than a full pose redraw.
- **Does the anchor redraw start from the plain base or the designed base?** Probably the designed
  one — a *red* cardinal's fly anchor should also be red — which means the anchor redraw runs
  after step 2's design is applied, on the final base. Confirm the ordering.
- **Cost ceiling.** Is `N×` still generation acceptable per pet, or cap the number of anchored
  poses? A 5-pose bird with 2 anchors is 2 extra redraws (~20 s) on a ~3-min build — likely fine,
  but state it.
- **Pool path.** The pool handler (`pet_factory_handler`) would run the extra per-pose redraw on
  the worker — no new *param* (the anchor is content in the profile the worker already loads), so
  this may need **no** handler contract change, unlike `isolate_subject`. Confirm against
  `pet_preview_handler`/`pet_factory_handler`'s schema before assuming. Deferred until the design
  settles.

---

## 9. Decisions (running log — mostly OPEN at Rev.1)

| # | Question | Answer | Why |
|---|---|---|---|
| 1 | Is "no movement" a pose-availability problem? | **No** | The pose is generated; it is a motion-*range* problem bounded by the shared anchor (§0/§1) |
| 2 | Where does the per-pose anchor live? | **Content — `SPEC_MOTION_PROFILES` §3.9's `control` block, `kind: "pose_prompt"` (RESOLVED)** | Reuses the reserved kind-block; the validated kind is a `pose` text clause driving a fresh txt2img anchor (`sprite` was rejected by §7.1) (§2, §3.9.1) |
| 3 | Fresh anchor per pose, or img2img from the base? | **img2img from the base** | Identity is anchored on the one still §0.1 relies on; a fresh txt2img would drift the bird (§4) |
| 4 | Which poses get anchors? | **Only silhouette-changing ones (fly/run/jump)** | Bounds cost and identity-drift to where it is needed (§5) |
| 5 | Backward compatibility? | **A pose with no anchor is byte-identical to today** | Purely additive; existing pets unchanged, guard-test pinned (§6) |
| 6 | Build first or validate first? | **Validate — one hand-made fly anchor before any code** | The design hinges on an unmeasured "does Wan flap?" assumption (§7) |
| 7 | Transition seam between different-silhouette loops | **OPEN** | Depends on the host runtime's pose-switch behaviour (§8) |
| 8 | `anchor_strength` value(s) | **OPEN — needs a calibration sweep** | The identity↔pose knob; guessing it is the whack-a-mole this repo avoids (§8) |
| 9 | Spread-anchor vs. two-keyframe (up/down) | **OPEN — both arms of the §7 experiment** | Two-keyframe may get motion with less identity risk (§8) |
| 10 | Prompt anchor (A) or reusable pose control (B)? | **RESOLVED by §7.1 — neither: a fresh-text `pose_prompt` anchor wins** | The experiment falsified the sprite/img2img redraw (B-crude/hybrid) — no denoise holds pose+identity. A fresh txt2img from a pose clause + house style delivers pose+identity+style; ships as the `pose_prompt` kind. `depth` control (was B-proper) is deferred for custom pets (§7.1, §3.9.1) |
| 11 | Can we do proper pose conditioning here? | **YES — via Wan's own control path, NOT a Z-Image ControlNet (`SPEC_MOTION_PROFILES` §3.9)** | §3.9 already reserved the per-pose `control` field (skeleton/depth) + the skeleton→depth→prompt rule, and names the mechanism: Wan 2.2 I2V "Animate"/VACE driven by a pose skeleton or depth video. The still-model-ControlNet worry (Rev.2) was the wrong layer — the control drives the *video motion*, not the anchor still. The build is Wan's control path (the SD-1.5 wiring from `datsPet` does not port; §3.9) + authoring the per-pose skeletons |

---

## 10. Where it would touch the code

**The schema already exists** — `Pose.control` is in `motion_profiles/__init__.py` today, loaded,
`None` at launch, reserved by §3.9. This is NOT a schema reshape. The work, for the target (§3.9
control tier):

- `pet_factory/factory.py` — **the real build: a Wan 2.2 I2V control path** (Wan Animate / VACE)
  that, when `pose.control` is set, drives the video from the pose skeleton/depth instead of the
  prompt-only loop; when it is `None`, **byte-identical to today** (§6). §3.9 is explicit: the
  SD-1.5 ControlNet wiring from the sibling `datsPet` does **not** port — this control path is new.
- `pet_factory/motion_profiles/` — author the per-pose **control assets** (a pose skeleton or depth
  per movement per body type), stored in the profile dir the way `animal_catalog` stores `base.png`
  per breed; the `control` block references them. `motion_admin.validate_profile` accepts a
  *populated* `control` (it validates an empty one today).
- `pet_factory/tests/` — backward-compat pin (no `control` ⇒ today's workflow, byte-identical),
  the `control` block validator, and the skeleton→depth→prompt resolution.
- **The stills-only fallbacks (A / B-crude)** would instead add an img2img redraw step to the pose
  loop with no control path — cheaper to build, weaker result; only worth it if the Wan control
  path proves too costly (which §7 would measure).
- **No `web/` change** — the pose menu, reference flow, and candidate strip are all upstream; this
  is a generation-time detail invisible to the browser.
