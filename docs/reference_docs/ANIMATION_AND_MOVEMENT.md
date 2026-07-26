# Reference — How DatsPet animation & movement works

**Type:** Reference guide (not a spec — nothing here is a proposal; it describes the system as
built). Grounded against the working tree, 2026-07-26.

**Read this if** you are authoring a motion profile, debugging why a pet moves wrong, adding a
body type, or trying to understand what the walk/run *prompt* actually controls versus what the
runtime figures out on its own.

**Related specs** (the "why" and the change history behind each layer):
`docs/RESEARCH_POSE_MOTION.md` (the derivation), `docs/archive/SPEC_MOTION_PROFILES.md` (the
profile registry), `docs/SPEC_BUNDLE_MOTION_CONTRACT.md` (the bundle wire format),
`docs/SPEC_MOTION_BODY_PROFILE.md` (the future composed-prompt model),
`docs/SPEC_MOTION_PROFILE_ADMIN.md` (the Motion Lab authoring tool).

---

## 0. The one thing to understand first

**DatsPet animates with pre-rendered sprite frames, not a rig.** There is no skeleton, no bones,
no procedural in-betweening. Every frame of every animation is a little image the AI *painted* at
build time. Nothing at display time can change what a limb does — the pixels are already baked.

This is the fork that surprises people. Most game/pet engines are **rigged**: you give the engine
a pose and a gait parameter and it *computes* a walk cycle from bones. If DatsPet worked that way,
"just give it a pose and the engine figures out the rest" would be true. It doesn't. DatsPet paints
frames, which means:

> The text **prompt** is the only place that decides how the limbs move. Silence about a limb in
> the prompt is silence in the pixels, and no downstream engine can add it back.

The upside of the choice: you can type "axolotl" or "gargoyle" — a body nobody rigged — and get
animation. The cost: the prompt is load-bearing, and that is why a wrong walk prompt (the
`winged_flyer` "hovering" bug, worked through in §4) produced a dragon that skated on its belly.

---

## 1. There are two engines, not one

| | **Generation engine** | **Playback engine** |
|---|---|---|
| **When** | Build time (~3 min) | Display time (every frame, 60 Hz) |
| **Where** | ComfyUI on the GPU (`pet_factory`) | The browser — Pet Maker's own runtime *and* the DatsMe host both consume the same bundle |
| **What it is** | Z-Image (txt2img) + **Wan 2.2 I2V** (image-to-video) + birefnet (cutout) | A **flipbook player** + a state machine + a locomotion strategy |
| **What it does** | *Paints* the frames from the anchor still + the motion prompt | *Flips through* the painted frames and *moves the sprite around the page* |
| **Controlled by** | The motion profile's prompts (anchor + action/suffix) | The manifest's per-animation metadata (`loop`, `runtime_role`, `view`) + `movement_class` |
| **Can do** | Invent limb motion, expression, wing beats — anything describable | Choose which clip plays, where the pet walks, how fast, which way it faces |
| **Cannot do** | Nothing after the build — the frames are then immutable | Change a single pixel of a limb; it only plays what was painted |

The walk/run **prompt talks to the generation engine.** The playback engine never sees it — by the
time playback runs, the prompt has already been "spent" as pixels on the sprite sheet.

---

## 2. The layers, end to end

```
  animal name / design
        │
  ┌─────▼─────────────────────────────────────────────┐
  │ L0  CONTENT   motion_profiles/*.json               │  per body type, per pose:
  │               (one JSON per body type + registry)  │  anchor clause · motion prompt ·
  │                                                    │  runtime_role · loop · timed_buffer · view
  └─────┬─────────────────────────────────────────────┘
        │  resolve_motion_profile(animal)  /  motion_resolver.resolve_motion_key()
  ┌─────▼─────────────────────────────────────────────┐
  │ L1  RESOLUTION   animal → profile key              │  AI classifier → keyword → default(quadruped)
  └─────┬─────────────────────────────────────────────┘
        │  make_pet_zip(...)   (pet_factory/factory.py)
  ┌─────▼─────────────────────────────────────────────┐
  │ L2  GENERATION (GPU, ~3 min)                       │
  │   base sprite ─► per-pose ANCHOR still (Z-Image)   │  _static_image_wf, _ANCHOR_SEED
  │              ─► Wan I2V LOOP per pose              │  _loop_wf  (first==last frame → seamless)
  │              ─► birefnet cutout (transparent)      │  _CutoutSession
  │              ─► pack sheet + manifest              │  pack_datsme_bundle
  └─────┬─────────────────────────────────────────────┘
        │  the .zip  (immutable artifact)
  ┌─────▼─────────────────────────────────────────────┐
  │ L3  THE BUNDLE (the wire)                          │  sprite PNG + manifest.json + package.json
  │     sheet grid · animations{frames,fps,loop,       │  schema pet_manifest.v1
  │     runtime_role,timed_buffer_ms,view} ·           │
  │     movement_class · view_kind/native_facing/…     │
  └─────┬─────────────────────────────────────────────┘
        │  fetched once, stored verbatim, animated forever
  ┌─────▼─────────────────────────────────────────────┐
  │ L4  PLAYBACK (browser, 60 Hz)                      │
  │   animsFromManifest ─► petStore                    │  web/src/pet/manifest.ts
  │   flipbook loop (frameIdx = (i+1) % n)             │  useAnimationLoop.ts
  │   auto state machine over runtime_role             │  behaviors/useAutoStateMachine.ts
  │   movement_class → locomotion strategy             │  locomotion/registry.ts  (moves sprite on page)
  └───────────────────────────────────────────────────┘
```

Two boundaries carry the whole design:

- **L2 → L3 is a one-way, permanent write.** The host stores the manifest *verbatim* and animates
  from it forever. A field written wrong is baked into every pet until someone pays the GPU to
  regenerate. This is why the bundle contract (`SPEC_BUNDLE_MOTION_CONTRACT`) treats every field as
  additive and immutable.
- **L4 never branches on species.** The playback engine dispatches through `movement_class` →
  strategy and through `runtime_role`; it never contains `if animal == "dragon"`. That is the
  repo-wide engine-vs-content rule (see §8).

---

## 3. Layer 0 — the motion profile (the content you author)

One JSON per body type in `pet_factory/motion_profiles/` (`quadruped`, `avian`, `aquatic`,
`serpentine`, `winged_flyer`) + `registry.json`. Every profile declares the **full canonical pose
set** — there is no inheritance; a disabled pose is `{"enabled": false}`. Resolution never raises:
an unknown animal or key falls back to `registry.default` (`quadruped`).

The canonical poses (`motion_profiles/__init__.py`, `CANONICAL_POSES`):

```
walk · idle · run · sleep · sit · eat · jump · play · swim · fly
```

`walk` + `idle` are `REQUIRED_POSES` (always built). Each pose entry:

```json
"walk": {
  "enabled": true,
  "runtime_role": "active",                       // rest | active | timed | triggered
  "action": "walking on its legs",                // ── MOTION prompt (what Wan paints) ──┐
  "suffix": ", full walk cycle in place: legs …",  //                                       │
  "loop": true,                                    // playback hint                         │
  "timed_buffer_ms": 6000,                         // optional dwell (timed poses)          │
  "control": {                                    //                                       │
    "kind": "pose_prompt",                        // ── ANCHOR clause (the still) ──────────┘
    "pose": "front legs mid-stride, one forward and one back, torso leaning forward"
  }
}
```

Plus profile-level fields: `movement_class` (the host locomotion key), `base_pose` (the resting
description, e.g. aquatic = `"swimming, body horizontal…"`), `view` (`side`/`right`/`flip`), and
`keywords` (offline resolution fallback).

The two fields that do the animation work are `control.pose` and `action`+`suffix`. They feed two
different generation calls — the next section is the crux of the whole guide.

---

## 4. Anatomy of a pose — the two prompts

Each pose is generated by **two** calls in `factory.py`, and they answer two different questions:

| | field | composed by | question it answers |
|---|---|---|---|
| **The still** | `control.pose` (anchor clause) | `anchor_clause()` → `_static_image_wf` (Z-Image txt2img) | *What does the pet look like, frozen, in this pose?* |
| **The motion** | `action` + `suffix` | `compose_pose_prompt()` → `_loop_wf` (Wan 2.2 I2V) | *How does it move across the ~16-frame loop?* |

**How Wan turns one still into motion.** `_loop_wf` hands Wan the anchor as **both the first and
last frame** and lets it invent the frames in between — a seamless loop. The **text prompt is the
only guidance** for what those in-between frames contain. So:

- The anchor decides the *starting/ending pose* (legs mid-stride, or wings spread).
- The motion prompt decides *what changes between the frames* (legs cycling, or wings beating).

**Why every movement needs its OWN pose (anchor).** This is the heart of the design (validated
live — see `RESEARCH_POSE_MOTION.md`). If every pose started from the same shared base still (a
bird standing with wings folded), Wan could only *twitch* it — the first and last frame are already
"standing," so there is nowhere for the motion to go. Giving each pose a **distinct anchor in its
own pose** — a bird with wings *spread* for `fly`, a dog with legs *mid-stride* for `run` — is what
lets Wan produce real, different motion per pose. A pose per movement is not bookkeeping; it is the
mechanism that makes the movement possible.

**The load-bearing rule (learned the hard way).** The anchor posing a limb is **not enough** — the
*motion* prompt must explicitly say that limb cycles. The `winged_flyer` `walk` bug:

```
anchor : "front legs mid-stride, one forward and one back"   ← legs ARE posed
motion : "hovering forward with steady wing beats"           ← but Wan is told to flap, not step
result : wings flap over a static-legged still — a dragon skating on its belly
```

The model was fully capable of moving the legs (the `play` pose, whose prompt said "limbs
bouncing," accidentally walk-cycled them). The `walk` prompt just never asked. The fix mirrored the
proven `quadruped` phrasing — `"full walk cycle in place: legs cycling through one complete
stride… no wing flapping, no hovering"` — and pinned the wings folded. **Authoring rule: name the
limb that moves, in the motion prompt, for every pose.** (`SPEC_MOTION_BODY_PROFILE` exists to make
this omission structurally impossible by *composing* the prompt from the body's limb inventory
rather than hand-writing free text.)

---

## 5. Layer 3 — the manifest (the contract between the two engines)

`pack_datsme_bundle` (`factory.py`) writes the sprite PNG plus `manifest.json`. The manifest is the
**only** channel to the playback engine — anything resolved but not written here is lost. Shape:

```json
{
  "schema_version": "pet_manifest.v1",
  "columns": 8, "rows": 16, "frame_width": 256, "frame_height": 256,
  "animations": {
    "walk": { "frames": [0..15], "fps": 12, "loop": true,  "runtime_role": "active",
              "view": {"view_kind":"side","native_facing":"right","mirroring_policy":"flip"} },
    "jump": { "frames": [96..111], "fps": 12, "loop": false, "runtime_role": "triggered", … }
  },
  "movement_class": "winged_flyer",
  "view_kind": "side", "native_facing": "right", "mirroring_policy": "flip"
}
```

What each field controls at **playback**:

| field | who reads it | effect |
|---|---|---|
| `frames` | flipbook loop | the cells of the sprite sheet this animation cycles through |
| `fps` | flipbook loop | playback speed (note: **12** here is the display rate; Wan generated at 16 — different numbers) |
| `loop` | `useAnimationLoop` | `true` → cycles `0→n→0`; `false` → plays once and **holds the last frame** (`frameIdx = frames.length-1`) |
| `runtime_role` | `useAutoStateMachine` | how the pet reaches the pose on its own — see table below |
| `timed_buffer_ms` | host timed branch | how long a `timed` clip dwells on screen |
| `view` (per-animation) | sprite-tilt / mirroring gate | orientation of *this* clip (a top-down `sleep` can differ from a side `walk`) |
| `movement_class` | locomotion registry | which per-frame **on-page movement** strategy drives the sprite |

**`runtime_role`** — how a pose is reached (`ALLOWED_ROLES` in `motion_profiles/__init__.py`):

| role | meaning | loop | example |
|---|---|---|---|
| `rest` | the default/resting animation the pet returns to | true | `idle` |
| `active` | a travel/locomotion gait, played while moving on the page | true | `walk`, `run`, `fly`, `swim` |
| `timed` | auto-reached from rest, dwells, returns (needs `timed_buffer_ms`) | true | `sleep`, `sit`, `eat` |
| `triggered` | played once on interaction, then returns to rest | **false** | `jump`, `play` |

A `triggered` pose **must** be `loop:false` — "a jump that loops is not a jump." That is why the
playback engine, on `loop:false`, holds the last frame rather than restarting.

---

## 6. How to control movement — the levers, and where each lives

Working outward from "what motion exists" to "how it plays":

| # | Lever | Where | Controls |
|---|---|---|---|
| 1 | **Which poses exist / are enabled** | profile JSON `enabled` + `CANONICAL_POSES` | the menu of possible movements for a body type |
| 2 | **Which poses actually get built** | `REQUIRED_POSES`, tier caps (`_clip_poses_to_cap`, `tiers/`), *(planned `signature_pose`)* | which movements a given build spends GPU on |
| 3 | **The still pose** | `control.pose` (anchor clause) | the frozen shape Wan animates *from* |
| 4 | **The motion** ⭐ | `action` + `suffix` → `compose_pose_prompt` | *what the limbs actually do* — the load-bearing lever |
| 5 | **The resting pose** | profile `base_pose` | the pet's neutral still (aquatic = swimming, not standing) |
| 6 | **Playback behavior** | `loop`, `runtime_role`, `timed_buffer_ms` | how/when the clip is reached and whether it repeats |
| 7 | **Orientation** | `view` / `view_kind` / `native_facing` / `mirroring_policy` | facing and mirroring at playback |
| 8 | **On-page movement** | `movement_class` → `locomotion/registry.ts` (host-owned) | where/how fast the sprite travels the page (not the limbs) |
| 9 | **Authoring & preview** | the **Motion Lab** (`webui/motion_lab.py`, `/admin/motions/lab`) | draw/animate/save any pose's anchor+motion on the GPU box before shipping |

Lever **#4 is the one that makes limbs move**, and the one with no safety net today (free text).
Levers #6–#8 are hints to the playback engine; they can reorder or reposition a clip but can never
change what a limb does inside it.

**What you *cannot* control after the build:** anything about the pixels. The bundle is immutable
(L2→L3). Fixing a wrong walk means editing the profile and **regenerating** the pet.

---

## 7. Worked example — "red dragon", the `walk` pose

1. **L1 resolution:** `"red dragon"` → `winged_flyer` (keyword/AI classifier; unknown would fall to
   `quadruped`).
2. **L0 content:** `winged_flyer.walk` supplies the anchor `"front legs mid-stride…"` and the
   motion `"walking on its legs, full walk cycle in place: legs cycling through one complete
   stride, wings kept folded…"`.
3. **L2 generation:**
   - `_static_image_wf(anchor_prompt, _ANCHOR_SEED)` → a single still of the dragon mid-stride.
   - `_loop_wf(compose_pose_prompt("red dragon", walk), that_still, _ANCHOR_SEED)` → Wan paints ~16
     frames of the legs cycling (still first=last, motion between).
   - birefnet cutout → transparent frames; packed into the sheet at cells `[0..15]`.
4. **L3 bundle:** `animations.walk = {frames:[0..15], fps:12, loop:true, runtime_role:"active",
   view:{side/right/flip}}`, `movement_class:"winged_flyer"`.
5. **L4 playback:** the pet wanders the page using the `winged_flyer` locomotion strategy; while
   travelling it plays the `walk` clip; `useAnimationLoop` flips frames `0→15→0`; mirroring flips
   the sprite when it walks left.

Change the motion prompt at step 2 and *only step 2's pixels* change. Change `movement_class` and
only step 5's *path across the page* changes. They are independent knobs on the two engines.

---

## 8. Design principles

- **Engine vs. content.** No runtime code branches on species/breed/`movement_class`. The packer
  reads whatever the resolved profile carries; the playback engine dispatches through the registry.
  Adding a body type is one JSON + one registry line, never an engine edit.
- **The prompt is load-bearing; silence about a limb is the bug.** Every limb the animal has should
  get a clause in every pose. `SPEC_MOTION_BODY_PROFILE` is the plan to enforce this by composition.
- **A pose per movement is the mechanism, not bookkeeping.** Wan animates *from* the anchor; a
  generic anchor can only twitch. Distinct per-pose anchors are what make distinct motion possible.
- **Bundles are immutable.** The host animates the manifest forever; you cannot patch a shipped
  pet, only regenerate it. Get the fields right before stamping (`SPEC_BUNDLE_MOTION_CONTRACT` §8).
- **GPU-less posture.** `motion_profiles` and the manifest logic are pure data / behind the lazy ML
  boundary; the web tier reads the profile menu without importing numpy/Wan/rembg.

---

## 9. File & function quick-map

| Concern | Location |
|---|---|
| Profiles (content) | `pet_factory/motion_profiles/*.json` + `registry.json` |
| Pose model, `CANONICAL_POSES`, `REQUIRED_POSES`, `ALLOWED_ROLES` | `pet_factory/motion_profiles/__init__.py` |
| Motion prompt composer | `compose_pose_prompt()` (same file) |
| Anchor clause accessor | `anchor_clause()` (same file) |
| Resolution (keyword) | `resolve_motion_profile()` / `load_motion_profile()` (same file) |
| Resolution (AI classifier) | `webui/motion_resolver.py::resolve_motion_key()` |
| Generation pipeline | `pet_factory/factory.py` — `make_pet_zip`, `_base_sprite`, `_static_image_wf`, `_loop_wf`, `_CutoutSession`, `pack_datsme_bundle` |
| Tier caps / which poses build | `webui/app.py::_clip_poses_to_cap`, `pet_factory/tiers/` |
| Bundle wire format | `docs/SPEC_BUNDLE_MOTION_CONTRACT.md` |
| Playback: flipbook | `web/src/pet/useAnimationLoop.ts` |
| Playback: manifest → runtime | `web/src/pet/manifest.ts::animsFromManifest`, `web/src/pet/types.ts` |
| Playback: auto state machine | `web/src/pet/behaviors/useAutoStateMachine.ts` |
| Playback: on-page movement | `web/src/pet/locomotion/registry.ts` (+ `quadruped.ts`) |
| Authoring tool | `webui/motion_lab.py`, `web/src/app/admin/motions/lab/` |

---

## 10. Glossary

- **Anchor / anchor clause** (`control.pose`) — the text that draws the single *still* frame a pose
  is animated from.
- **Motion prompt** (`action` + `suffix`) — the text that tells Wan *what moves* across the loop.
- **Sprite sheet** — one PNG grid holding every frame of every pose; the baked output.
- **Flipbook** — the playback model: cycle pre-painted frames; no procedural motion.
- **`runtime_role`** — `rest`/`active`/`timed`/`triggered`; how the pet reaches a pose on its own.
- **`movement_class`** — the key the playback engine maps to an on-page locomotion strategy (moves
  the *sprite*, not the limbs).
- **`base_pose`** — the profile's neutral resting description.
- **`signature_pose` / `primary_motion`** — the defining motion of a body type (bird→fly), which
  the tier cap must not drop (`SPEC_BUNDLE_MOTION_CONTRACT` §3.4; the two specs converge on one
  field — *not yet implemented*).
- **Rig** — a skeletal animation system (bones + skinning). DatsPet has **none**; this is why the
  prompt, not the engine, decides limb motion.
