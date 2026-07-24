# RESEARCH — Pet motion animation (how we made the pets actually move)

**Status:** living reference, last updated 2026-07-24.

**Why this document exists.** The pose-motion work spanned many experiments, dead ends, and design
pivots that are *not* recoverable from the code or the specs alone — the specs record the *decisions*,
but not the *evidence and reasoning that produced them*. This doc is the connective tissue: it explains
**how** we got here so a future session (human or AI) can pick up with the full context instead of
re-deriving it from scratch, or worse, re-litigating a settled question. Read this first; then read the
specs it maps for the authoritative detail.

If you change the motion design, **update this doc** — it is the one place the *reasoning* lives.

---

## 1. The problem, in one paragraph

A DatsMe pet's whole point is that it **moves**. But step 3 (animation) was inconsistent: type a bird,
pick "fly", and some birds flapped while others just sat there with a tiny wing-twitch. Two different
failures were tangled together, and separating them was the first real insight.

---

## 2. The two-layer diagnosis (the key framing)

"Some birds fly, others don't" turned out to be **two independent gates**, and every later decision
depends on keeping them apart:

- **Layer 1 — resolution (does the pet even get `fly` offered?).** An animal is classified to a
  *motion profile* (body type: `avian`, `quadruped`, …). `fly` is only enabled in `avian`/`winged_flyer`.
  "blue jay" and "cardinal" were **not in `avian`'s keyword list**, so they resolved to the default
  `quadruped`, where `fly` is disabled — they never got the pose at all. (My earlier experiments used
  "blue jay **bird**"/"red cardinal **bird**", which matched the `bird` keyword and masked this.)
- **Layer 2 — motion range (the pose is generated, but barely moves).** Even when `fly` *was* offered,
  the animation only twitched. This is a generation-quality problem, not availability.

Both must be fixed for a user typing "blue jay" to get a flapping blue jay. They were solved by two
different mechanisms (§5, §6).

---

## 3. Layer 2 — the motion-range investigation (the heart of it)

### 3.1 The finding that started everything: the single-anchor ceiling

The pipeline animates every pose as a **Wan 2.2 I2V loop whose first and last frame are the *same*
base still** (`factory.py`, `WanFirstLastFrameToVideo` with `start_image == end_image`). The only thing
that varies per pose is the text prompt. **So the anchor pose is a hard ceiling on the motion:** a `fly`
loop whose anchor is a *perched, wings-folded* bird can only crack the wings and settle back — it
cannot complete a wingbeat, because the loop must return to the folded anchor. The prompt asks for
flight; the anchor forbids it.

**The fix hypothesis:** give a pose its own anchor still, in a pose that *can* move (wings spread).

### 3.2 The experiment that proved it (and redirected the mechanism)

Run on a red cardinal, 2×RTX 3090, ComfyUI (`SPEC_POSE_ANCHORS` §7.1). Two things came out:

**The thesis is CONFIRMED.** Same fly loop, same cardinal, only the anchor differs:
- standing/folded anchor → a twitch, settles back (the ceiling);
- wings-spread anchor → a **full wingbeat cycle**.

**The mechanism was redirected — this is the important part.** We tested *three* ways to build a
spread anchor, and each stills-only img2img approach failed on a *different* axis:

| Approach | Pose | Identity | Style | Verdict |
|---|---|---|---|---|
| **A** — prompt img2img on the standing base ("wings spread") | ❌ stayed folded | ✅ | ✅ | text can't impose the pose from a folded base |
| **B (sprite)** — img2img the pet onto a shared "flying bird" sprite, low denoise | ✅ | ❌ generic grey | ❌ | pose copied, identity never repainted |
| **B (sprite)**, high denoise | ❌ pose collapses | ✅ | ✅ | identity comes in only as the pose is lost |
| **C — fresh txt2img** (pose clause + the house-style prompt) | ✅ | ✅ | ✅ | **the winner** |

The lesson: **no img2img strength separates pose from identity**, because the source image fixes pose
*and* identity *and* style together. Only **generating the anchor fresh from text** — the same
`_base_prompt` that draws the standing base, with a pose *clause* swapped in for "standing" — gave all
three at once. This **falsified the shared-sprite idea** we had speced (`SPEC_POSE_ANCHOR_HYBRID`, now
marked SUPERSEDED), and became the `pose_prompt` mechanism (§5).

One refinement mattered: the first fresh anchor drifted to a semi-3D render because the prompt omitted
the house-style clause (`simple flat shading, storybook style`). Pinning that produced a flat-cartoon
flying cardinal that matched the base pet — motion + identity + style, in one txt2img call.

### 3.3 Breadth: does one clause generalize? (yes)

`SPEC_POSE_ANCHORS` §7.2 — the same recipe, a *fixed* clause, only the animal varies:
- **One fly clause** flew robin, sparrow, blue jay (full flap, right identity, right style), **seed-robust**.
- **One run clause** ran a cat and a corgi (real gait). So the clause is a **body-type-level asset**,
  exactly the registry model — authored once per profile, reused across every species in it.
- The **penguin** (flightless, divergent body) got a *graceful* grounded flipper-flap from the shared
  "flying" clause — not garbage, and improvable with its own clause via the §3.7 specificity ladder.
  This is the escape hatch demonstrated, not asserted.

### 3.4 Designer pets: does the anchor match a *designed* pet? (yes, with a caveat)

`SPEC_POSE_ANCHORS` §7.3 — a designed bird (a plain species remixed toward "a turquoise blue songbird
with a yellow belly"). The fresh anchor generated from the *description* reproduced the design (blue +
yellow belly) and flapped. **Identity lives in the description**, which the anchor regenerates — so the
extension works for any pet whose look is prompt-describable (typed + designer). The one caveat: the
fresh anchor is slightly more *saturated* than the softer remixed base (we mirror the base's palette by
using `_remix_prompt` for reference-based pets, which narrows but doesn't erase the gap). The design
identity holds; only the palette is a touch off.

**The line this draws:** anchor-from-description works when the description carries the identity. It does
**not** work for a **photo upload**, whose stored description is a bare noun ("dog") — a fresh still
can't match the specific uploaded dog. Uploads therefore **opt out** of the anchor (they keep the shared
base) until the `depth` control kind ships (§7).

### 3.5 End-to-end confirmation

`make_pet_zip("robin", poses={fly})` through the *real* pipeline packs a fly loop that sweeps a full
wingbeat in the actual bundle sprite sheet, and the walk pose (from the base) and fly pose (from the
anchor) are the **same robin in the same style** — because both derive from `_base_prompt("robin")` with
only the pose word changed. Cutout (birefnet) works on the anchor-derived frames.

---

## 4. Layer 1 — resolution (the keyword problem, and the AI answer)

Classifying an animal to its body type was done by **exhaustive per-profile keyword lists** with
word-boundary substring matching. This is crude: no list ever enumerates every species, substring
matching false-positives (a **komodo dragon** matched "dragon" → `winged_flyer`, badly wrong), and every
new animal is a manual edit. We first patched it by adding ~40 birds to `avian`, then replaced the whole
approach:

**An AI classifier** (`motion_classify`, a `fast`/Haiku purpose in the existing AI engine) maps any
animal → its body-type key. Live-validated 2026-07-24:
- **quetzal → avian**, **axolotl → aquatic** (keywords missed both → default quadruped);
- **komodo dragon → quadruped** (keyword *false-positived* on "dragon" → winged_flyer; the AI fixed it);
- agrees with keywords where they were already right.

The keyword lists **stay as the offline fallback** (standalone / no-API-key mode), but stop being
something to maintain exhaustively. See §6 for the architecture that keeps this safe.

---

## 5. Design decisions, and *why* (the durable output)

1. **The motion anchor is a `pose_prompt` control kind, not a shared sprite.** Falsified the sprite/
   img2img redraw (no denoise holds pose + identity, §3.2); a fresh txt2img from a pose *clause* holds
   all three axes. Field: `control: { kind: "pose_prompt", pose: "<clause>" }` on the pose — the
   pre-reserved §3.9 `control` block, extended with one kind. Precedence
   `pose_skeleton → depth → pose_prompt → loop-only`. No control ⇒ byte-identical to today.
2. **The clause is per-body-type content, reused across species** (§3.3). Divergent bodies (penguin)
   get their own clause via the §3.7 specificity ladder — the same engine-vs-content split the rest of
   the registry uses.
3. **Scope: fire for prompt-derived pets (typed / designer / catalog); uploads opt out.** Identity must
   be in the description for a fresh anchor to match (§3.4). Uploads (bare-noun description) keep the
   shared base until the deferred **`depth`** control kind, which conditions on the base image and *can*
   hold a custom pet's pixel identity (the datsPet-validated depth-silhouette path).
4. **Resolution is an AI classifier with a keyword fallback, not exhaustive keywords** (§4). Engine vs.
   content: the classifier is *engine* (in the web tier, where the AI lives), the profiles are *content*.
5. **Everything degrades safely.** No API key → the classifier falls back to keywords; no control on a
   pose → the loop-only path. Standalone mode is never worse than before.

---

## 6. What is implemented (2026-07-24) and where

**`pose_prompt` motion anchor** (commits `d9af7aa`, `3a52b53`, plus the designer extension):
- `pet_factory/motion_profiles/__init__.py` — `ALLOWED_CONTROL_KINDS`, `anchor_clause(pose)` (the one
  reader of a pose_prompt control), `list_profiles()`.
- `pet_factory/motion_profiles/admin.py` — validates the `control` block shape (shared by the guard test
  and the admin editor).
- `pet_factory/factory.py` — `_base_prompt(animal, pose="standing")` and `_remix_prompt(animal,
  pose="standing")`; the pose loop draws a fresh anchor (mirroring the base's prompt: remix for
  reference pets, base for typed) when the pose has a clause and `pose_anchor` is on.
- `pet_factory/motion_profiles/avian.json` `fly` + `quadruped.json` `run` — the two validated clauses;
  broadened `avian` keywords (Layer-1 fallback).
- `make_pet_zip(..., pose_anchor=True)`; web tier passes `pose_anchor = (source != "upload")`; threaded
  through `run_pet_job` → `_generate_via_pool` → the pool handler (schema v4, additive; **deploy the
  handler before the web tier** — the web tier sends the param only when `False`, so an older fleet
  handler is untouched for the common case).

**AI motion classifier:**
- `pet_factory/ai_purposes/motion_classify.json` (+ registry entry) — the `fast`/Haiku purpose,
  registry-agnostic (valid keys passed in, validated caller-side; no `enum`).
- `webui/motion_resolver.py` — `resolve_motion_key(animal)`: AI → keyword fallback → default; caches
  confirmed AI results only.
- `webui/app.py` — the txt2img and upload reference doors now pin the classified key at fill time
  (previously left `None` to keyword-resolve at build).

**Tests:** the full backend suite passes (`.venv/bin/python -m pytest pet_factory/tests webui/tests`);
one pre-existing, unrelated cookie test fails on a clean tree too. New coverage: control-block validator
negatives, `anchor_clause`, and the updated purpose/resolution assertions.

---

## 7. Open threads (what a future session should pick up)

- **The Motion Lab** (`SPEC_MOTION_LAB`) — the admin visual workbench to tune a pose clause and watch
  the anchor + loop, so the per-species grind is fast. Next planned build.
- **The `depth` control kind** — the deferred robust answer for **photo uploads** (custom pixel
  identity), conditioning on the base image; imitate the sibling **datsPet**'s depth-silhouette
  ControlNet path (`/home/markly2/claude_code/datsPet`; birds use depth silhouettes, not skeletons —
  AP-10K is quadruped-only). Until then, uploads keep the shared base (no anchor).
- **Palette match for designer pets** — the fresh anchor is slightly more saturated than the remixed
  base (§3.4); tune if it reads as inconsistent.
- **Flightless avians** (penguin, ostrich) resolve to `avian` and get a graceful grounded flap; give
  them their own clause via a specific profile if desired.
- **Pool/prod deploy** — the handler carries `pose_anchor` (v4); prod must deploy the handler before the
  web tier (fleet discipline). Verify with `scripts/verify_deployment.sh`.

---

## 8. The related specs (the map the user asked for)

The design is spread across specs by concern; this doc is the narrative that ties them together.

| Spec | Role | State |
|---|---|---|
| **`SPEC_POSE_ANCHORS`** | The parent design-space doc + the **experiment record** (§7.1 the three-arm result, §7.2 breadth, §7.3 designer). The "why pose_prompt" evidence lives here. | Active |
| **`SPEC_MOTION_PROFILES`** §3.9 / §3.9.1 | Owns the `Pose` schema and the **`control` block** — the field the anchor writes (`pose_prompt` kind, precedence, backward-compat). The authoritative schema. | Active (pre-existing spec, extended) |
| **`SPEC_MOTION_LAB`** | The admin **authoring tool** to tune pose clauses visually and save them to a profile. | Draft (not yet built) |
| **`SPEC_POSE_ANCHOR_HYBRID`** | The **superseded** sprite-redraw draft — kept for design history (why the sprite approach was tried and rejected). | Superseded |
| **`SPEC_DATSPET_AI_ENGINE`** | The AI engine (purpose registry, tiers, usage ledger) that powers the **`motion_classify`** classifier and the upload captioner. | Active (implemented) |

Related but not motion-specific: `SPEC_UPLOAD_LIKENESS` (the upload/captioner flow, and the §0.1
"one still decides likeness" invariant this design trades against), `SPEC_PET_DESIGNER_FLOW` (the
three-step designer the pets come from).

---

## 9. Reproducing the experiments

All on the GPU dev box (`source pet_env.sh` first — sets `PET_FACTORY_COMFY_URL` :19953, the ComfyUI
output dir, GPU libs). ComfyUI must be up. The pipeline building blocks are `factory.py`'s
`_static_image_wf` / `_img2img_wf` / `_loop_wf` + `_run` (drive ComfyUI over HTTP; outputs land in
`COMFY_OUTPUT_DIR` and can be chained). The experiment harnesses used this session lived in the session
scratchpad (`pose_anchor_exp*.py`, `pose_anchor_breadth.py`, `designer_validate.py`, `pose_anchor_e2e.py`)
— they are throwaway scripts, not committed; re-derive from the recipe in §3 if needed. The classifier is
testable with `resolve_motion_key(animal)` from `webui/motion_resolver.py`.
