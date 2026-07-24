# SPEC — The Motion Lab (an admin visual workbench for authoring per-pose motion anchors)

**Status:** **IMPLEMENTED** — Phase 1 + Phase 2, 2026-07-24. **Rev.3.** Backend `webui/motion_lab.py`
(still / animate / asset endpoints, local-backend only, tested + live-smoke-verified) + frontend
`web/src/app/admin/motions/lab/page.tsx`, now the **multi-pose** view (§12): a column per selected
pose, all drawn from one shared base + seed, per-pose and "all" Draw/Animate/Save. Backend was
unchanged for Phase 2 (frontend orchestration of the same per-pose endpoints). The optional AI
"suggest-clause" helper (§2) is still not built. See `RESEARCH_POSE_MOTION.md` for the design narrative.

**What this is.** A new **admin web surface** that lets an admin *watch the pose-anchor pipeline
run, step by step*, on a chosen animal + pose — see each intermediate result, edit the **pose
clause**, **re-run any step in seconds**, and **save the working clause back into the motion
profile**. It is the authoring UI for the `pose_prompt` mechanism validated in `SPEC_POSE_ANCHORS`
§7.1.

**Why it's needed (the justifying problem).** Making each species actually *move* in each pose is
**many iterations** — the pose clause has to be tuned per body type, and often per awkward species (a
penguin is not a songbird). Doing that today means editing profile JSON, rebuilding a **whole
~3-minute pet**, and eyeballing a zip — a blind loop that can't even tell you *which* step failed
(was it the anchor still, or the animation off it?). The Lab makes the loop **visual, isolated, and
instant**: each step's output is on screen, and changing the clause re-runs just the affected steps.
Without it, the pose-anchor grind is impractical at the scale the registry is *meant* to grow to
(`SPEC_MOTION_PROFILES` §3.8, "hundreds of entries").

**Where it sits.** Directly **on top of the motion profiles admin** (`SPEC_MOTION_PROFILE_ADMIN`).
Its saves **are** motion-profile writes, through the **same** `motion_admin` validator and write
path — so nothing the Lab saves can break the build (the guard-test-shared validation, the same
discipline the existing editor uses). It is a **richer editor for the same content**, not a parallel
store.

**Relationship to the other specs.**
- **`SPEC_POSE_ANCHORS` §7.1** defines *what* the Lab authors — the per-pose `pose_prompt` anchor
  (a text clause driving a fresh txt2img anchor), and the experiment that validated it. **The Lab is
  the productized version of that experiment**: the MVP Lab loop *is* §7 made repeatable (see §8,
  sequencing). (`SPEC_POSE_ANCHOR_HYBRID` is the superseded sprite-redraw draft — history only.)
- **`SPEC_MOTION_PROFILES` §3.9.1** owns the `pose_prompt` field the Lab writes.
- **`SPEC_MOTION_PROFILE_ADMIN`** is the host admin surface it extends; **`SPEC_MOTION_PROFILES`** is
  the content it reads and writes.

**Repos touched (proposed):** `datsme-pet-factory_wu` — a new `webui/motion_lab.py` admin router,
a new `web/src/app/admin/motions/lab/` page, and exposing `factory.py`'s existing step functions
(`render_design_still` / `_static_image_wf` / `_loop_wf`) as individually-callable admin actions. Saves reuse
`webui/motion_admin.py`. **GPU-dev-box / `PET_GEN_BACKEND=local` only** (§5) — no prod, no new pool
contract.

---

## 0. The workflow it makes visual

The example, verbatim from the request: *an admin wants a **cardinal** that **walks** and **flies**.*

1. The pose's **clause** shows (`"wings spread wide open, mid-flight"` for `fly`) — the shared
   body-type knob; the Lab can draft one from the pose name (AI helper) or the admin writes it.
2. Run **Fresh anchor** → a txt2img **cardinal in that pose, in the house style** appears (the base
   still sits beside it for identity/style comparison).
3. Run **Animate** → the **flying cardinal loop** plays.
4. Not flapping right, or the pose off? Edit the **clause**, **re-run** — seconds, not a 3-min
   rebuild. Repeat until it moves and still reads as a cardinal in the right style.
5. **Save** the clause onto `avian.fly` — now every bird inherits it — or onto a specific
   `penguin.json` pose if that body needs its own (`SPEC_MOTION_PROFILES` §3.7).

The point is that the base still, the anchor still, and the animation are **on screen at once**, each
re-runnable in isolation.

---

## 1. The steps the Lab exposes (mapped to code that already exists)

The decomposition is **not a refactor** — `factory.py` already has these as separate functions; the
Lab calls them individually instead of only inside `make_pet_zip`.

| # | Step | Output shown | Backing function (today) | Editable inputs |
|---|---|---|---|---|
| 1 | **Base still** (reference) | the designed animal, standing | `_base_sprite` / `render_design_still` | animal name, (optional) design axes |
| 2 | **Pose clause** | the text clause for this pose (`"wings spread wide open, mid-flight"`) | content on the pose (`control.pose`) | **the pose clause** — the core knob |
| 3 | **Fresh anchor still** | *this* animal in the pose | `_static_image_wf(_base_prompt(animal)` with the clause swapped for `standing`) | the pose clause, seed |
| 4 | **Animate → moving sprite** | the animated loop | `_loop_wf(action/suffix, anchor_still, seed)` | motion prompt (the pose's `action`/`suffix`), length/fps |

Editing step 2's clause and re-running 3→4 is the **inner loop**. Step 1 is the standing reference
(for identity/style comparison only); the fresh anchor (step 3) is **txt2img, not img2img**, so there
is no sprite asset and no strength knob (the sprite/redraw path was rejected, §7.1 of `SPEC_POSE_ANCHORS`).

---

## 2. The authoring loop

**Tune the pose clause** — the iterative grind, and the whole reason the Lab exists. For an anchored
pose the admin edits the **pose clause** (`control.pose`), runs the fresh anchor + loop, and iterates
until the animal moves *and* still reads as itself in the house style — tested live on one or more
concrete species. The clause is per-body-type content, reused across every species in the profile
(§3), with a specific profile as the escape hatch for a divergent body.

**AI assist (optional).** A "suggest clause" action drafts a pose clause from the pose name + animal
using the AI engine (`SPEC_DATSPET_AI_ENGINE` — one `ai_purposes/` entry). The admin edits and
re-runs. The engine is already built; this is content, not new plumbing.

*(There is no sprite-authoring mode — the sprite/img2img approach was rejected by the §7.1 experiment.
The deferred `depth` kind for custom pets, if built, would add its own asset-authoring flow then.)*

---

## 3. What "Save" writes — `control.kind == "pose_prompt"` (VALIDATED 2026-07-24)

The §7.1 experiment settled both the field and the mechanism (`SPEC_MOTION_PROFILES` §3.9.1): the
anchor is a **`control` block**, `{ kind: "pose_prompt", pose: "<static pose clause>" }`. So the Lab's
core knob is a **text pose clause** (`"wings spread wide open, mid-flight"`) that drives a *fresh
txt2img* anchor (`_base_prompt` with the clause swapped for `standing`, so the house style and the
species ride along), then the standard loop.

- **The Lab's save is `{kind: "pose_prompt", pose}`** — through `motion_admin`'s validator +
  `motion_profiles.reload()`, so a saved block is immediately live and can never be one the build
  rejects. **No `ref`, no `strength`, no sprite asset** (the sprite/img2img redraw was rejected, §7.1).
- **The pose clause is per-body-type content, reused across species** — `avian.fly.control.pose`
  serves every bird; a divergent body (penguin) gets its own via specificity (`SPEC_MOTION_PROFILES`
  §3.7). The Lab lets the admin **spot-check the clause on several concrete animals** (cardinal,
  robin, blue jay) before saving.
- **Custom/uploaded pets are out of scope for this kind** — a fresh txt2img matches a *species*, not a
  user's specific pet (§7.1); those await the deferred `depth` kind, which the Lab need not author in v1.

Because the clause is a generic pose description carrying no per-species string, there is **no
literal-species hazard** — the earlier "never save a literal 'cardinal'" concern is moot.

---

## 4. Backend surface (new — `webui/motion_lab.py`)

An admin router mounted like the others, gated by `admin_common`'s adm-claim (identical to
`motion_admin`/`ai_admin`). Each generation action returns a **URL to the produced image/animation**
(served from a scratch location the way preview PNGs and `/api/reference/{id}.png` already are), plus
timing:

- `POST /api/admin/motion-lab/base` → render the base still for an animal (reuses
  `render_design_still`). Returns a still URL (the standing reference).
- `POST /api/admin/motion-lab/anchor` → `_static_image_wf(_base_prompt(animal)` with the `pose`
  clause swapped for `standing`) → fresh anchor still URL. **The inner-loop endpoint.**
- `POST /api/admin/motion-lab/animate` → `_loop_wf(action/suffix, anchor_still_url, seed)` → loop
  (webp/gif) URL.
- `POST /api/admin/motion-lab/suggest-clause` → AI draft of the pose clause (optional, §2).
- **Save** reuses `motion_admin`'s existing profile-write endpoint — the Lab does not get its own
  store or write path.

**Single-GPU reality.** Generation is one-at-a-time (the pipeline owns the GPU — `app.py`'s worker
thread). Lab runs queue behind that same constraint and behind any real generation in flight. On the
GPU dev box where authoring happens, that is fine; the Lab surfaces "waiting for GPU" honestly rather
than pretending to parallelize.

---

## 5. GPU / backend posture (keeps the load-bearing GPU-less prod intact)

The Lab drives **local ComfyUI through `factory.py`** — it needs the ML pipeline. Therefore:

- It is a **`PET_GEN_BACKEND=local`, GPU-dev-box tool**, not a production feature. In GPU-less prod
  `factory.py` is not even importable (the lazy-import posture, CLAUDE.md "GPU-less posture"), so the
  Lab's routes are **inert/absent there** — mounted only when the local backend is active, the same
  way the local generation path is. This does **not** weaken the deploy gate ("`import numpy` must
  fail" stays true for the web tier).
- It needs **no new pool contract** for v1. The pool handlers (`pet_preview_handler`,
  `pet_factory_handler`) are fixed tasks; exposing arbitrary intermediate steps through them is a
  separate, deferred effort (§7). Authoring is a dev-box act; that is where the GPU and the iteration
  are.

---

## 6. Engine vs. content (the boundary this must respect)

The Lab is **tooling/engine**; the anchors it produces are **content** in the profiles. It never
hardcodes a species — it operates on whatever `(animal, pose, profile)` the admin selects, reads the
profile, and writes back through the shared validator. Adding a body type or a specific override is
a content edit made *in the Lab*, not a code change. This is the same engine-vs-content line the
motion registry already draws; the Lab is just a better pen for the content side.

---

## 7. Scope & non-goals

**In scope (v1):** the four-step visual loop (§1), both authoring modes (§2), template-safe save-back
through `motion_admin` (§3), local-backend only (§5), optional AI prompt suggestion (§2).

**Non-goals / deferred:**
- **Not a prod feature**; no GPU-less operation.
- **Not a new store** — writes go through `motion_admin`.
- **No pool path** in v1 (running steps on a pool GPU node = new handler tasks; deferred).
- **Not a replacement for the §7 proof** — it *is* that experiment productized (§8), but the first
  proof that the technique flaps at all can be a throwaway hand-run before the UI is built.
- **No batch/grid authoring** (author-many-animals-at-once) in v1 — one animal/pose at a time; the
  "test the template on cardinal + robin + blue jay" case (§3) is sequential.

---

## 8. Sequencing — how this relates to actually building the anchors

1. **Prove the technique once, by hand** — **DONE** (`SPEC_POSE_ANCHORS` §7.1): a `pose_prompt` anchor
   flew a cardinal that both flaps *and* stays a cardinal in the house style. The de-risk is spent.
2. **Build the Lab MVP** = §1 steps 2–4 on a fixed animal/pose, re-runnable. This *is* the §7.1 loop
   made repeatable.
3. **Grind the registry** with the Lab: per body type first (the shared recipe on `avian`,
   `quadruped`), then specific profiles for the animals that don't port — the exact "many iterations
   per species" this spec is justified by. Each save is immediately live (§3).

So the Lab is **Phase-2 leverage** whose value is the per-species grind (step 3), justified only once
the technique is proven (step 1) — but its MVP is small because the steps already exist as functions.

---

## 9. Open questions (live — this is a draft)

- ~~Field shape it writes.~~ **RESOLVED (§3): `control.kind == "pose_prompt"`** (`{kind, pose}`) — a
  text clause, no sprite/`ref`/`strength`.
- **Where generated Lab assets live and how long.** Anchor stills and animations are scratch; reuse
  the preview/reference serving + the 24 h janitor, or a dedicated ephemeral admin bucket? (Nothing
  permanent is authored — the `pose_prompt` kind saves only a JSON clause.)
- **Test-animal set for clause validation (§3).** Does the admin type each test animal, or does the
  Lab suggest a few representative species per profile (from the profile's keywords) to spot-check
  the clause against before saving?
- **Does one clause generalize across a profile's species?** The clause is authored on `avian.fly`
  and reused by every bird — the Lab should make it easy to confirm a clause tuned on a cardinal also
  flies a robin/sparrow before it ships (the breadth pass §7.1 still owes).
- **Two-keyframe animate.** `_loop_wf` today uses `start==end`; `SPEC_POSE_ANCHORS` §8's two-keyframe
  variant (wings-up start, wings-down end) would need the Lab's animate step to accept two stills.
  Worth exposing as an option once the single-anchor path is proven.
- **Concurrency UX.** With one GPU, how does the Lab present "a real pet generation is running, your
  re-run is queued"? A simple honest banner, or a soft lock while a build holds the GPU?
- **Pool path (deferred).** If authoring ever needs to run on a pool GPU node (no local GPU box), the
  step endpoints would need pool handler tasks — a separate spec, explicitly out of v1 (§5).

---

## 10. Decisions (running log)

| # | Question | Answer | Why |
|---|---|---|---|
| 1 | Does this need its own store? | **No — saves go through `motion_admin`** | The Lab edits motion-profile content; reusing the validator means nothing saved can break the build (§3) |
| 2 | Does the pipeline need refactoring to expose steps? | **No — `render_design_still`/`_static_image_wf`/`_loop_wf` are already separate** | The Lab calls them individually instead of via `make_pet_zip`; only new admin endpoints wrap them (§1/§4) |
| 3 | Prod feature or dev tool? | **Local-backend GPU-dev-box tool; inert in GPU-less prod** | It drives `factory.py`/ComfyUI; keeps the deploy gate ("`import numpy` must fail") intact (§5) |
| 4 | What does Save persist? | **`control: {kind:"pose_prompt", pose:"<clause>"}` — a per-body-type pose clause, NO per-species string** | Validated by §7.1: a fresh txt2img from the clause + house style. No `ref`/`strength`/sprite (that path was rejected) (§3, §3.9.1) |
| 5 | Save target granularity | **A pose in a profile — `avian.fly` (shared) or a specific `penguin.fly` (§3.7)** | Authors the reusable recipe by default; specificity is the escape hatch (§3) |
| 6 | New pool contract? | **No (v1) — local only; pool step-execution deferred** | Authoring is a dev-box act; the fixed pool handlers don't expose arbitrary steps (§5/§7) |
| 7 | Build before or after proving the technique? | **After the §7.1 hand-proof (done — `pose_prompt` validated on a cardinal); the Lab MVP IS that loop repeatable** | The technique is proven; the Lab now scales the per-species grind. The MVP is small (§8) |
| 8 | Field shape written | **RESOLVED — `control.kind == "pose_prompt"` (`{kind, pose}`)** | The §7.1-validated kind; sprite/img2img was tested and rejected (§3, `SPEC_MOTION_PROFILES` §3.9.1) |

---

## 11. Where it would touch the code

- `webui/motion_lab.py` (new) — the admin router: `base` / `anchor` / `animate` / `suggest-clause`
  actions wrapping `factory.py`'s existing step functions (`render_design_still`, `_static_image_wf`,
  `_loop_wf`); gated by `admin_common`; mounted only under the local backend (§5). Save delegates to
  `motion_admin`.
- `webui/motion_admin.py` — extend the profile-write validator to accept a populated `control` block:
  `kind` in the allowed set (incl. `pose_prompt`), and for `pose_prompt` a non-empty `pose` clause
  (for the deferred `depth`/`pose_skeleton` kinds, a `ref` that resolves + a `strength` in range) —
  the §3.9 guard-test additions, shared with the Lab.
- `web/src/app/admin/motions/lab/page.tsx` (new) — the stepper UI: animal + pose pickers, a vertical
  stack of step cards each showing its output with a re-run control, the **pose-clause editor**, "save
  to profile". Mirrors the existing `admin/motions/page.tsx` pattern and the design page's
  seq-stamped async discipline (`useDesignFlow` — drop stale results) so a slow re-run can't
  overwrite a newer one.
- `web/src/lib/api.ts` — the Lab's admin endpoints (the one adapter that knows their URLs, per
  repo convention).
- `pet_factory/ai_purposes/pose_clause.json` (optional, §2) — one purpose for the "suggest clause"
  action; no engine change.
- `pet_factory/motion_profiles/` — the per-pose `control.pose` clauses live here as JSON content (no
  binary assets for the `pose_prompt` kind).
- **Tests** — the `control`-block validator (`kind` allowed incl. `pose_prompt`, `pose` non-empty —
  the §3.9 guard-test additions), the local-only mounting (routes absent under the pool backend), and
  that a Lab save round-trips through `motion_admin`'s validator identically to a hand-edited profile.

---

## 12. Phase 2 — Multi-pose authoring (IMPLEMENTED 2026-07-24)

**Why.** Phase 1 tunes one clause in isolation, but the real build (`make_pet_zip`) draws **every**
pose from **one base + one seed**, and the failure Phase 1 hides is **cross-pose drift** — a `fly`
anchor coming out a different red or style than the `walk`. Phase 2 draws all the selected poses from
the shared base/seed and shows them **side by side**, so the admin catches drift *before* saving —
the pre-save version of the real app's "Generated poses" strip (which today you only see *after* a
~3-minute build).

**Shape (agreed decisions).**
- **Controls:** animal + profile + a **multi-select of poses** + **one shared seed**. The shared seed
  is load-bearing: `factory.py`'s real pose loop uses the build seed for the base *and* every anchor,
  so the Lab must too — otherwise the columns aren't the same animal and the comparison is meaningless.
- **Layout: one grid, a column per selected pose** (decision P2-1). Each column *stacks*: pose name ·
  clause editor · Draw + still · Animate + loop · Save. You scan across columns to compare.
- **Scope: every selected pose, including base-driven ones** (decision P2-2). A pose *with* a clause
  draws a fresh anchor; a pose *without* one shows the **shared base** as its source (labeled "uses
  base") and animates from it — so the whole pet appears the way the real app draws it.

**Per-column controls.**
- **Clause editor** — empty ⇒ this pose uses the shared base; a clause ⇒ it becomes an anchored pose
  (Draw enabled). Editing the clause clears that column's now-stale still + loop.
- **Draw** — the fresh anchor (`_static_image_wf(_base_prompt(animal, clause), seed)`); for an empty
  clause the column simply shows the shared base (nothing to draw).
- **Animate** — the loop from this column's source
  (`_loop_wf(compose_pose_prompt(animal, pose), source, seed)` — the anchor for a clause pose, the
  base for a base pose).
- **Save** — writes this pose's `control` block to the profile.

**Global controls.**
- **Draw all anchors** — draws every clause column's anchor, **sequentially** (the GPU is serial, so
  they queue with per-column progress). Base columns need no draw.
- **Animate all** — ensures each column's source exists (drawing any missing anchors first), then
  loops every column.
- **Save all** — sets every edited column's `control` and writes the profile in **one** `motion_admin`
  PUT.

**Invalidation.** Editing a column's clause clears that column's anchor + loop. Changing the **animal**
or **seed** clears the base *and* every column — they must be redrawn from the new base/seed.

**The consistency payoff.** The columns side by side surface exactly the drift Phase 1 can't: the
fresh anchors (`fly`) against the base-derived poses (`walk`/`idle`/`sleep`). This is the pre-save
check that the whole pet will read as one coherent animal.

**Backend impact: NONE.** The Phase-1 endpoints already work one pose at a time — `/still` (called
per clause, plus once for the base with an empty clause), `/animate` (per pose, passing the base's
asset id for base columns), `/asset`, and the `motion_admin` PUT for Save. Phase 2 is **frontend
orchestration + layout**. A batch "draw-all" backend endpoint is explicitly **not** wanted: per-pose
calls give per-column progress and single-column re-runs, and the GPU is serial regardless.

**Phase 1 = N-of-1.** Phase 2 *generalizes* the page — one selected pose reproduces today's
single-column view — it does not fork it.

**Open (minor, settle at build).**
- **Default pose selection** — all enabled poses (full strip, more GPU) vs a subset. Lean: default to
  the clause-bearing poses + `walk`/`idle` as the reference, admin adds more.
- **"Animate all" auto-drawing missing anchors** vs requiring "Draw all anchors" first. Lean: auto
  (smoother), though it collapses the anchor step; confirm at build.
- **GPU-serial progress UX** — a per-column spinner + "queued" state; the Lab already runs one
  generation at a time.

**Decisions (P2 log).**

| # | Question | Answer |
|---|---|---|
| P2-1 | Layout | **One grid, a column per pose** (clause + still + loop stacked) |
| P2-2 | Which poses show panels | **Every selected pose** — base-driven ones show the shared base as their source |
| P2-3 | Backend change? | **None** — the Phase-1 per-pose endpoints + `motion_admin` PUT suffice; the frontend orchestrates |
| P2-4 | Seed | **One shared seed** for the base + all anchors (mirrors the real build) |

---

## 13. Multi-GPU dispatch (IMPLEMENTED 2026-07-24)

ComfyUI is one-GPU-per-instance and serial, so the Lab dispatches each job across a
set of **endpoints** — one ComfyUI per GPU. Endpoint 0 is the primary (`factory`'s
ComfyUI on GPU 0); endpoint 1 is a second ComfyUI on GPU 1 (conventional `:19963` +
`<ComfyUI>/output_gpu1`, overridable via `PET_LAB_COMFY_URL_2` /
`PET_LAB_COMFY_OUTPUT_DIR_2`; started with **`start_comfyui_gpu1.sh`**, `--cuda-device 1`).

- **Dispatch:** each job goes to the **least-busy healthy enabled** endpoint (tracked
  in-flight counts). With both GPUs up, two jobs run at once — **~2× on a batch**
  (live-verified: two stills dispatched to ep0/ep1, both `running` concurrently).
- **One asset store:** every output is copied into `<GPU 0 out>/_lab` (served by
  `/asset`, read by every ComfyUI as an animate input over the shared filesystem), so
  the frontend and the animate step never care which GPU produced a still.
- **The toggle lives in the Lab (per request):** `GET/PUT /api/admin/motion-lab/config`
  reports the endpoints + health + which are enabled, and the page shows a **GPU chip
  toggle** (green dot = the instance is up). Default: **all endpoints active**. A
  down/disabled GPU is simply skipped; at least one must stay active.
- **The production pipeline is untouched** — `make_pet_zip` still uses GPU 0 only. The
  shared pool is deliberately NOT used (§5): the Lab stays local, and the idle local
  GPU is the clean win.
