# SPEC — The Motion Lab (an admin visual workbench for authoring per-pose motion anchors)

**Status:** proposed / **DRAFT for review**, 2026-07-24. **Rev.1.** Design-in-progress; NOT
implementation-ready. No code is written.

**What this is.** A new **admin web surface** that lets an admin *watch the pose-anchor pipeline
run, step by step*, on a chosen animal + pose — see each intermediate result, edit the redraw
prompt and strength, **re-run any step in seconds**, and **save the working recipe back into the
motion profile**. It is the authoring UI for the technique in `SPEC_POSE_ANCHOR_HYBRID`.

**Why it's needed (the justifying problem).** Making each species actually *move* in each pose is
**many iterations** — the redraw prompt, the strength, and the shared pose sprite all have to be
tuned per body type, and often per awkward species (a penguin is not a songbird). Doing that today
means editing profile JSON, rebuilding a **whole ~3-minute pet**, and eyeballing a zip — a blind
loop that can't even tell you *which* step failed (was it the anchor still, or the animation off
it?). The Lab makes the loop **visual, isolated, and instant**: each step's output is on screen, and
changing the prompt re-runs just the affected steps. Without it, the pose-anchor grind is
impractical at the scale the registry is *meant* to grow to (`SPEC_MOTION_PROFILES` §3.8, "hundreds
of entries").

**Where it sits.** Directly **on top of the motion profiles admin** (`SPEC_MOTION_PROFILE_ADMIN`).
Its saves **are** motion-profile writes, through the **same** `motion_admin` validator and write
path — so nothing the Lab saves can break the build (the guard-test-shared validation, the same
discipline the existing editor uses). It is a **richer editor for the same content**, not a parallel
store.

**Relationship to the other specs.**
- **`SPEC_POSE_ANCHOR_HYBRID`** defines *what* the Lab authors — the per-pose anchor recipe (shared
  sprite + redraw prompt template + strength) and the redraw/caption mechanisms. The Lab is the tool
  that makes that recipe by hand, fast.
- **`SPEC_POSE_ANCHORS` §7** describes the *single-anchor experiment* — pick a bird, make a
  wings-spread anchor, animate, judge. **The Lab is the productized version of that experiment**: the
  MVP Lab loop *is* §7 made repeatable (see §8, sequencing).
- **`SPEC_MOTION_PROFILE_ADMIN`** is the host admin surface it extends; **`SPEC_MOTION_PROFILES`** is
  the content it reads and writes.

**Repos touched (proposed):** `datsme-pet-factory_wu` — a new `webui/motion_lab.py` admin router,
a new `web/src/app/admin/motions/lab/` page, and exposing `factory.py`'s existing step functions
(`_base_sprite` / `_img2img_wf` / `_loop_wf`) as individually-callable admin actions. Saves reuse
`webui/motion_admin.py`. **GPU-dev-box / `PET_GEN_BACKEND=local` only** (§5) — no prod, no new pool
contract.

---

## 0. The workflow it makes visual

The example, verbatim from the request: *an admin wants a **cardinal** that **walks** and **flies**.*

1. The generic **avian walk** pose sprite shows (the shared body-type anchor).
2. The Lab drafts (or the admin writes) a **redraw prompt** that stamps a cardinal into that walking
   pose; the admin can edit it.
3. Run the redraw → the **cardinal-in-the-walk-pose anchor still** appears.
4. Run the animation → the **walking cardinal sprite** plays.
5. Not flapping right? Edit the prompt or strength, **re-run steps 3–4** — seconds, not a 3-min
   rebuild. Repeat until it moves and still looks like a cardinal.
6. **Save** the working recipe onto `avian.walk` — now every bird inherits it — or onto a specific
   `cardinal.json`/`penguin.json` pose if this species needs its own (`SPEC_MOTION_PROFILES` §3.7).

The same loop runs for `fly`. The point is that all four intermediate artifacts (base, sprite,
anchor still, animation) are **on screen at once**, each re-runnable in isolation.

---

## 1. The steps the Lab exposes (mapped to code that already exists)

The decomposition is **not a refactor** — `factory.py` already has these as separate functions; the
Lab calls them individually instead of only inside `make_pet_zip`.

| # | Step | Output shown | Backing function (today) | Editable inputs |
|---|---|---|---|---|
| 1 | **Base still** | the designed animal, standing | `_base_sprite` / `render_design_still` | animal name, (optional) design axes |
| 2 | **Shared pose sprite** | the body-type pose anchor (e.g. `avian/fly.pose.png`) | static content read from the profile dir | — (or "author sprite", §2) |
| 3 | **Redraw → anchor still** | *this* animal in the pose | `_img2img_wf(prompt, source, seed, denoise)` | **redraw prompt**, **strength (denoise)**, source = sprite or base |
| 4 | **Animate → moving sprite** | the animated loop | `_loop_wf(prompt, anchor_still, seed)` | motion prompt (the pose's `action`/`suffix`), length/fps |

Editing step 3's prompt/strength and re-running 3→4 is the **inner loop**. Step 1 rarely changes;
step 2 is authored once per body-type pose.

---

## 2. Two authoring modes

**(a) Author the shared pose sprite** — once per body-type pose. Generate a clean generic
"flying bird" / "running quadruped" (via `_base_sprite`/`_static_image_wf` with a generic prompt),
cut it out with the pipeline's birefnet, preview it, and **save it as the profile's pose sprite**
(`avian/fly.pose.png`, stored like `animal_catalog`'s `base.png`). Upstream, infrequent.

**(b) Author the redraw recipe** — the iterative grind. Tune the **redraw prompt template** and the
**strength** that stamp a concrete animal onto the shared sprite (`SPEC_POSE_ANCHOR_HYBRID` §2.1),
tested live on a real animal, until it moves and holds identity. This is what the Lab exists for.

**AI assist (optional).** A "suggest prompt" action drafts the redraw prompt from the sprite +
animal using the AI engine (`SPEC_DATSPET_AI_ENGINE` — a `pose_caption`/redraw-prompt purpose,
`SPEC_POSE_ANCHOR_HYBRID` §2.2). The admin edits the draft and re-runs. The engine is already built;
this is one `ai_purposes/` entry, not new plumbing.

---

## 3. What "Save" writes — a template, not a literal prompt (load-bearing)

The prompt the admin tunes is **animal-specific** ("cute cartoon **red cardinal**, wings spread…").
But `avian.fly` is **per body type** — shared by every bird. So the Lab must save a **template with
the animal spliced in**, never the literal "cardinal" string — exactly how `compose_pose_prompt`
already splices `{animal}` into `action`/`suffix`.

- The saved anchor recipe on a pose = `{ sprite: ref, prompt_template: "…{animal}…", strength: float }`
  (the field shape is `SPEC_POSE_ANCHOR_HYBRID` §8's open `anchor`-vs-§3.9-`control` decision — the
  Lab writes whatever that resolves to).
- The Lab **displays the resolved prompt** for the test animal (cardinal) but **persists the
  template**. A guard in the save path rejects a template that hard-codes a species where `{animal}`
  belongs (the same class of check `motion_admin` already runs).
- **Save target** is a pose in a profile: `avian.fly` for the shared/body-type recipe, or a
  specific `penguin.fly` via the specificity mechanism when a body genuinely diverges. The Lab lets
  the admin **test the template against several concrete animals** (cardinal, robin, blue jay)
  before saving — authoring the *reusable* recipe, validated on real cases.

All writes go through `motion_admin`'s validator + `motion_profiles.reload()`, so a saved recipe is
immediately live and can never be one the build rejects.

---

## 4. Backend surface (new — `webui/motion_lab.py`)

An admin router mounted like the others, gated by `admin_common`'s adm-claim (identical to
`motion_admin`/`ai_admin`). Each generation action returns a **URL to the produced image/animation**
(served from a scratch location the way preview PNGs and `/api/reference/{id}.png` already are), plus
timing:

- `POST /api/admin/motion-lab/base` → render the base still for an animal (reuses
  `render_design_still`). Returns a still URL.
- `POST /api/admin/motion-lab/sprite` → read/preview a profile's pose sprite; `PUT` to save a
  generated one (mode 2a).
- `POST /api/admin/motion-lab/redraw` → `_img2img_wf(prompt, source_url, seed, denoise=strength)` →
  anchor still URL. **The inner-loop endpoint.**
- `POST /api/admin/motion-lab/animate` → `_loop_wf(prompt, anchor_still_url, seed)` → loop
  (webp/gif) URL.
- `POST /api/admin/motion-lab/suggest-prompt` → AI draft (optional, §2).
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

1. **Prove the technique once, by hand** (`SPEC_POSE_ANCHOR_HYBRID` §7): one bird, does a
   wings-spread anchor flap *and* stay the same bird? Cheapest possible de-risk — don't build a UI to
   discover the redraw doesn't move.
2. **Build the Lab MVP** = §1 steps 3–4 on a fixed animal/pose, re-runnable. This *is* the §7 loop
   made repeatable, so steps 1 and 2 can converge if you'd rather prove-in-the-tool.
3. **Grind the registry** with the Lab: per body type first (the shared recipe on `avian`,
   `quadruped`), then specific profiles for the animals that don't port — the exact "many iterations
   per species" this spec is justified by. Each save is immediately live (§3).

So the Lab is **Phase-2 leverage** whose value is the per-species grind (step 3), justified only once
the technique is proven (step 1) — but its MVP is small because the steps already exist as functions.

---

## 9. Open questions (live — this is a draft)

- **Field shape it writes.** Blocked on `SPEC_POSE_ANCHOR_HYBRID` §8 (`anchor` field vs reserved
  §3.9 `control`). The Lab writes whatever that resolves to; the two specs must agree on one field.
- **Where generated Lab assets live and how long.** Anchor stills and animations are scratch; reuse
  the preview/reference serving + the 24 h janitor, or a dedicated ephemeral admin bucket? Saved
  sprites (mode 2a) are permanent profile content and go in the profile dir.
- **Test-animal set for template validation (§3).** Does the admin type each test animal, or does the
  Lab suggest a few representative species per profile (from the profile's keywords) to spot-check
  the template against before saving?
- **Sprite authoring quality bar (mode 2a).** How clean must the generic pose sprite be, and does the
  Lab enforce the birefnet cutout + side-profile framing, or leave it to the admin's eye?
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
| 2 | Does the pipeline need refactoring to expose steps? | **No — `_base_sprite`/`_img2img_wf`/`_loop_wf` are already separate** | The Lab calls them individually instead of via `make_pet_zip`; only new admin endpoints wrap them (§1/§4) |
| 3 | Prod feature or dev tool? | **Local-backend GPU-dev-box tool; inert in GPU-less prod** | It drives `factory.py`/ComfyUI; keeps the deploy gate ("`import numpy` must fail") intact (§5) |
| 4 | What does Save persist? | **A prompt *template* (`{animal}` spliced) + strength + sprite ref — never a literal species** | `avian.fly` is shared across birds; matches how `compose_pose_prompt` splices `{animal}` (§3) |
| 5 | Save target granularity | **A pose in a profile — `avian.fly` (shared) or a specific `penguin.fly` (§3.7)** | Authors the reusable recipe by default; specificity is the escape hatch (§3) |
| 6 | New pool contract? | **No (v1) — local only; pool step-execution deferred** | Authoring is a dev-box act; the fixed pool handlers don't expose arbitrary steps (§5/§7) |
| 7 | Build before or after proving the technique? | **After a one-bird hand-proof (§7); the Lab MVP then IS that loop repeatable** | Don't build a UI to find out the redraw won't flap; but the MVP is small (§8) |
| 8 | Field shape written | **OPEN — follows `SPEC_POSE_ANCHOR_HYBRID` §8** | The two specs must converge on one anchor field (§9) |

---

## 11. Where it would touch the code

- `webui/motion_lab.py` (new) — the admin router: `base` / `sprite` / `redraw` / `animate` /
  `suggest-prompt` actions wrapping `factory.py`'s existing step functions; gated by `admin_common`;
  mounted only under the local backend (§5). Save delegates to `motion_admin`.
- `webui/motion_admin.py` — extend the profile-write validator to accept the anchor recipe fields
  (sprite ref, prompt template, strength) and to reject a template that hard-codes a species (§3).
- `web/src/app/admin/motions/lab/page.tsx` (new) — the stepper UI: animal + pose pickers, a vertical
  stack of step cards each showing its output with a re-run control, prompt/strength editors, "save
  to profile". Mirrors the existing `admin/motions/page.tsx` pattern and the design page's
  seq-stamped async discipline (`useDesignFlow` — drop stale results) so a slow re-run can't
  overwrite a newer one.
- `web/src/lib/api.ts` — the Lab's admin endpoints (the one adapter that knows their URLs, per
  repo convention).
- `pet_factory/ai_purposes/pose_caption.json` (optional, §2) — one purpose for the "suggest prompt"
  action; no engine change.
- `pet_factory/motion_profiles/` — the pose sprites authored via mode 2a live here as content.
- **Tests** — the template-safety save guard (rejects a hard-coded species), the local-only mounting
  (routes absent under the pool backend), and that a Lab save round-trips through `motion_admin`'s
  validator identically to a hand-edited profile.
