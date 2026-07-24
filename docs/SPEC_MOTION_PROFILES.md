# SPEC — Species-aware motion profiles (per-body-type pose registry)

**Status:** Design — **Rev.3** (2026-07-13). Grounded against the working tree and the live
DatsMe pet runtime; every runtime claim below was read from code, not assumed.
**Implementation-ready:** all §9 decisions are resolved except §9.6 (which optional pose
descriptions to author at launch — a product call that does not gate code); every §10 gate is
executable, including the v3 two-field probes and the §5.2 profile-skew fallback; §3.6 names **both**
loader entry points (keyword `resolve_motion_profile` + pinned `load_motion_profile`) so the API
surface matches §5.2; and the §3.9 datsPet reference claims were independently verified against the
sibling repo. No code changes are made by this document. **Rev.3** adds
**specificity levels** (§3.7): every profile declares a `level` — **1 breed → 2 species → 3 animal
type → 4 generic** — and resolution selects the *most-specific-level* keyword match and uses **that
file whole (no inheritance)**. This answers a real fidelity gap — a mouse and a horse are both
quadrupeds but move very differently (a mouse scurries with quick tiny steps; a horse has a heavy
four-beat gait, mane and tail flowing) — without breaking the engine-vs-content boundary: the
*engine* reads one resolved file and never names a species; the species/breed naming lives entirely
in *content* (a `corgi.json` at `level:1`). A matched file's available poses are **exactly what it
lists** — a corgi with no `jump` has no jump option, even though the quadruped type enables it;
nothing is borrowed from a more general level. §3.8 frames the strategic upside: the registry is
*meant* to grow to hundreds of entries, each an isolated, guaranteed-correct motion description that
compounds — a fidelity asset and a competitive moat (the hand-tuned per-body-type knowledge is not
derivable from the generated output and cannot be shortcut by a clone). §3.9 adds a **forward-compatible
placeholder** for the day prompts hit their ceiling: an optional per-pose `control` field (a skeleton
or depth reference) with precedence **skeleton → depth → prompt**, so a future control signal is one
JSON field, not an engine change — authored empty at launch, default-inert, prompt-only for now.
The shipped sibling app `datsPet` is the **reference implementation** to imitate when that day comes
(its AP-10K skeleton data model + specificity registry port cleanly; its SD 1.5 ControlNet wiring does
not — this repo's newer Wan 2.2 I2V engine needs its own control path, §3.9).
**Rev.2** reconciled this spec with
`SPEC_PET_DESIGNER_PLATFORM` after a cross-spec consistency audit: the canonical pose set grew to
**10** and `MAX_POSES` to **10** (was 4 — it contradicted the platform's paid tier), the watchdog
implication of large builds is stated honestly (§8), and the front end is framed as the user
**freely choosing** which poses (up to a tier cap).
**Author's intent (verbatim goal):** "A bird and a dog describe *walking* differently. Make the
motion prompt species-appropriate so the animation is accurate and consistent. Each body type is a
key with its own JSON file describing the movements/poses available. Whether a pose is on is a
true/false flag; if true, read its description. The front end sends the package of which poses to
generate. Modular and configuration-driven."
**Repos touched:** `datsme-pet-factory_wu` (the `pet_factory` generator, its pool handler, the web
tier, and the design-page frontend). `shared_gpu_cpu` and `datsme_me` are **not** modified — the
DatsMe runtime already supports the roles this produces (§2).

---

## 1. The problem this solves

Today `make_pet_zip` animates every pet with **two hardcoded prompt templates** that differ only by
the `{animal}` string spliced in (`pet_factory/factory.py:431,435`):

```
walk:  "cute cartoon {animal} walking, side profile, facing right" + WALK_SUFFIX
idle:  "cute cartoon {animal} sitting calmly, side profile, facing right" + IDLE_SUFFIX
```

`WALK_SUFFIX`/`IDLE_SUFFIX` are two module-level constants (`factory.py:68,73`) appended verbatim to
every animal. Consequences, all confirmed in code:

1. **The motion wording is mammal-centric for every species — and even "species" is too coarse.** A
   snake gets "walking… complete stride"; a bird gets "sitting calmly". The Wan 2.2 I2V model is left
   to improvise motion against an instruction that doesn't match the creature — the source of the
   accuracy/consistency gap the goal names. And the coarseness runs *deeper than species*: "dog"
   alone spans a Great Dane's slow lope, a poodle's bouncy prance, and a corgi's low waddle — one
   description cannot be right for all three. A single generic prompt is right for the common body and
   **silently wrong for the divergent long tail**; on a product whose deliverable *is* the animation,
   that ~10–20% failure rate is unacceptable. This is what motivates resolving motion at the most
   specific level available — breed before species before body type (§3.7).
2. **`movement_class` is a lie for every non-quadruped pet.** `pack_datsme_bundle` hardcodes
   `movement_class="mammalian_quadruped"` (`factory.py:315`) and it is never overridden — so every
   bird, fish, and snake ships mislabeled. This field is **consumed** downstream: the DatsMe admin
   catalog reads it (`datsme_me/api/routes/admin.py:1164-1197`) and it is the natural key for
   per-body-type mirroring policy.
3. **The set of animations is frozen at two.** Adding "run" means editing engine code, not data —
   it fails the "new variant without an engine change" test.

The fix: make the motion vocabulary **content**, not code. A body type is one self-contained JSON
file; the engine reads whichever poses the file enables and never names a species.

---

## 2. What is already TRUE in the DatsMe runtime (verified 2026-07-13, not assumed)

This is the load-bearing discovery that makes the feature worth building: **the pet runtime already
plays more than walk+idle.** Extra poses are not dead weight waiting on an engine change.

| Fact | Evidence |
|---|---|
| The runtime models **four** animation roles, not two: `"rest" \| "active" \| "timed" \| "triggered"`. | `datsme_me/web/src/pet/types.ts:10` (`RuntimeRole`). |
| The auto state machine dispatches **by `runtime_role`, animation-name-free** — it does not hardcode "walk"/"idle". | `pet/behaviors/useAutoStateMachine.ts:6,181,219,228`. |
| **`active`** = locomotion; armed with an arrival check and `pick_weight` for wander selection. Multiple active anims are picked among by weight. | `useAutoStateMachine.ts:181-199`; `pick_weight` in `types.ts:74`. |
| **`rest`** = the dwell state (idle); `rest_dwell_ms` sets how long before exiting, `rest_exit_weight`/`run_arrival_weight` route transitions. | `useAutoStateMachine.ts:203-217`; `types.ts:77-81`. |
| **`timed`** = plays once (or for a buffer) then returns to rest — the natural home for **sleep**, a stretch, a one-shot. | `useAutoStateMachine.ts:219-224`; `timed_buffer_ms` in `types.ts:85`. |
| **`triggered`** = never auto-driven; fired by an interaction behavior (e.g. click-to-excite). The home for a **jump**/reaction pose. | `useAutoStateMachine.ts:228`; `pet/behaviors/useClickPetExcited.ts`. |
| Animations **without** a `runtime_role` are kept but never auto-played (safe: an unknown pose can't break the machine). | `types.ts:70-72`; `manifest.ts:57`. |

**Implication for this spec.** The manifest's `animations` map already carries per-animation
`runtime_role` + role-specific knobs, and the runtime already honors them. So a motion profile that
declares `sleep` as `runtime_role: "timed"` or `jump` as `runtime_role: "triggered"` produces a pose
the engine **actually plays** — no `datsme_me` change required. The one caveat: a `triggered` pose
only fires if some interaction behavior references it; today `useClickPetExcited` is the trigger
path. A `triggered` pose with no wired trigger is generated and packed but idle until a trigger
points at it. The spec surfaces this honestly in §7 rather than promising motion it can't drive.

---

## 3. Design — the motion-profile registry

### 3.1 Layout (one file per body type + a master registry)

```
pet_factory/motion_profiles/
├── registry.json          # master index: default key + every body type → its file
├── quadruped.json         # the current behavior, made explicit (the default)
├── avian.json
├── serpentine.json
├── aquatic.json
└── winged_flyer.json
```

Each body-type file is **self-contained** — it owns its `movement_class`, its species keywords, and
the full canonical pose set. Adding a body type is: drop one JSON file + add one registry line.
Nothing in `factory.py` changes. This is the engine-vs-content boundary the global rules require:
runtime code reads a record and acts; it never branches on *which* body type produced it.

### 3.2 A body-type file (`serpentine.json`)

```json
{
  "key": "serpentine", "level": 3,
  "movement_class": "limbless_serpentine",
  "keywords": ["snake", "serpent", "python", "cobra", "viper", "boa"],
  "poses": {
    "walk":  { "enabled": true,  "runtime_role": "active", "action": "slithering forward in a smooth S-curve", "suffix": ", body undulating side to side, no legs, no camera movement, no panning" },
    "idle":  { "enabled": true,  "runtime_role": "rest",   "action": "coiled at rest, slow tongue flicks",       "suffix": ", gentle breathing, small head movements, no camera movement" },
    "run":   { "enabled": true,  "runtime_role": "active", "action": "rapid slithering, body in fast S-waves",   "suffix": ", quick undulation, no legs, no camera movement" },
    "sleep": { "enabled": true,  "runtime_role": "timed",  "action": "coiled tightly, head resting, still",       "suffix": ", motionless, slow breathing, no camera movement" },
    "sit":   { "enabled": false },
    "eat":   { "enabled": true,  "runtime_role": "timed",  "action": "slowly swallowing a small meal, gentle gulps", "suffix": ", deliberate slow movement, no camera movement" },
    "jump":  { "enabled": false }, "play": { "enabled": false },
    "swim":  { "enabled": true,  "runtime_role": "active", "action": "undulating through water",                  "suffix": ", smooth swimming motion, no camera movement" },
    "fly":   { "enabled": false }
  }
}
```

**The `enabled` flag is the heart of the design (per the goal).** Every body-type file declares the
**same canonical pose keys** (§3.4). A pose the creature cannot do sets `enabled: false` and may omit
everything else — a snake's `jump` is `{ "enabled": false }`, nothing more. This is deliberate over
*omitting* the key:

- **Uniform schema** — every file has the identical key set, so the guard test is a simple shape
  check and two body types diff by flags/descriptions, not by reconciling different key sets.
- **The `false` is a recorded decision.** `jump: enabled=false` documents *"snakes don't jump"* and
  is reviewable; a missing key is silent. (Consistency-is-the-default: whether a pose *exists as a
  field* is the contract; whether it is *enabled* is the per-body-type value. We do not fork the
  schema because a snake can't jump — we set a flag.)
- **The front end reads flags directly** (§4) — the pose menu for an animal is a pure projection of
  its resolved profile.

### 3.3 The master registry (`registry.json`)

```json
{
  "default": "quadruped",
  "body_types": [
    { "key": "quadruped",    "file": "quadruped.json",    "label": "Four-legged mammal" },
    { "key": "avian",        "file": "avian.json",        "label": "Bird" },
    { "key": "serpentine",   "file": "serpentine.json",   "label": "Legless / snake" },
    { "key": "aquatic",      "file": "aquatic.json",      "label": "Fish / aquatic" },
    { "key": "winged_flyer", "file": "winged_flyer.json", "label": "Winged flyer (dragon, insect)" }
  ]
}
```

`default` names the profile used when no keyword matches. It **must** be `quadruped`, whose poses
reproduce today's exact `walk`/`idle` wording — so an unclassified animal generates byte-identical
output to today. That is the backward-compatibility guarantee (§6).

**Rev.3:** the registry lists profiles at **every level**, not just body types, and each entry
carries its `level` (1 breed / 2 species / 3 animal type / 4 generic) — e.g.
`{ "key": "corgi", "file": "corgi.json", "label": "Corgi", "level": 1 }` and
`{ "key": "quadruped", "file": "quadruped.json", "label": "Four-legged mammal", "level": 3 }`. The
registry stays a flat list; the `level` field is what orders resolution (most-specific-level-wins,
whole file — no inheritance, §3.7). Adding a breed is one line + one complete file.

### 3.4 The canonical pose set

The set of pose *keys* is fixed platform-wide (every file declares all of them; `enabled` varies):

| pose | default `runtime_role` | engine behavior (§2) | required? |
|---|---|---|---|
| `walk`   | `active`    | locomotion, wander | **required** (every profile: `enabled:true`) |
| `idle`   | `rest`      | dwell state | **required** (every profile: `enabled:true`) |
| `run`    | `active`    | faster locomotion, weighted against walk | optional |
| `sleep`  | `timed`     | plays then returns to rest | optional |
| `sit`    | `timed`     | sits, then returns to rest | optional |
| `eat`    | `timed`     | a one-shot eating/nibbling loop | optional |
| `jump`   | `triggered` | fired by an interaction behavior | optional (see §7 caveat) |
| `play`   | `triggered` | a playful reaction (interaction-fired) | optional (see §7 caveat) |
| `swim`   | `active`    | locomotion (aquatic bodies) | optional |
| `fly`    | `active`    | locomotion (winged bodies) | optional |

`walk`+`idle` are **required** because the auto state machine needs at least one `active` and one
`rest` animation to function (`useAutoStateMachine.ts` routes rest↔active). The loader enforces this
(§3.6). The canonical set is **10 poses** — chosen so the platform's per-user pose caps (up to 5,
SPEC_PET_DESIGNER_PLATFORM §5) always have a real menu to pick from, and the hard `MAX_POSES=10`
ceiling (§8) equals the full set. Adding a new pose key platform-wide is a one-line change to this
table + the guard test; adding it to a *body type* is one JSON edit. A body type that can't do a
pose sets `enabled:false` (e.g. a snake's `jump`/`fly`; a non-aquatic animal's `swim`).

### 3.5 Classification (`animal` → most-specific profile)

No LLM exists in the pet pipeline (verified: no `anthropic` import anywhere in `pet_factory/` or
`webui/`), and none is added. Classification is **keyword match** over the `animal` string, which the
design page already produces as a clean species field:

- **Most-specific-level-wins, longest-keyword within a level** (Rev.3, §3.7). A level-1 (breed)
  match beats a level-2 (species) match beats a level-3 (animal-type) match; within one level, longest
  keyword wins (so "sea snake" → `serpentine`, not a stray "sea" → aquatic). Case-insensitive,
  word-boundary aware. (In the flat Rev.2 model there was only the animal-type level; Rev.3 adds the
  breed/species levels and the fallback order.)
- No match at any level → `registry.default` generic (level 4).

The classifier is a pure function behind one seam — `resolve_motion_profile(animal)` — which returns
the **winning file, loaded whole** (§3.7 — no inheritance/merge). If keyword coverage ever becomes a
maintenance burden, an LLM classifier swaps in **behind that same seam** with zero change to callers
(it would return a profile key; loading is unchanged). Explicitly out of scope for Rev.1.

### 3.6 The loader + guard test

`pet_factory/motion_profiles/__init__.py` exposes **two loaders** — the keyword path and the pinned
path — plus the dataclass:

- `resolve_motion_profile(animal: str) -> MotionProfile` — **keyword path** (§3.5/§3.7): classify to
  the most-specific matching profile **by level**, load that file whole (cached), return it. No merging
  across levels. Used by the General free-text page and by `load_motion_profile`'s fallback. Never
  raises — an unmatched animal lands on `registry.default` (`quadruped`), which always exists.
- `load_motion_profile(key: str, *, fallback_animal: str | None = None) -> MotionProfile` — **pinned
  path** (§5.2): load the profile whose registry `key` equals `key` (cached), return it. If `key` is
  not in the registry (profile-set skew, §5.2): fall back to `resolve_motion_profile(fallback_animal)`
  and **log a skew warning** (`WARNING: pinned motion_profile '<key>' not found, falling back to
  keyword resolution of '<fallback_animal>'`); if `fallback_animal` is also `None`, fall back to
  `registry.default`. So this loader, like the keyword one, **never raises on a miss** — a skewed
  fleet degrades to coarser-but-correct motion, never a failure. (The `/api/motions?profile=` *menu*
  path 404s on an unknown key instead — the catalog guard test prevents that shipping — but the
  *generate* path always degrades gracefully; §5.2.)
- `MotionProfile` — a frozen dataclass: `key`, `level`, `movement_class`, `poses: dict[str, Pose]`
  (the file's own full canonical key set), and `enabled_poses()` / `pose(name)` helpers. `Pose` =
  `enabled`, `runtime_role`, `action`, `suffix`, and an **optional `control`** (the §3.9 skeleton/
  depth placeholder — `None` everywhere at launch, so prompt-only is the default path).

Both loaders return the identical `MotionProfile` shape, so every caller (the engine, `/api/motions`,
`make_pet_zip`) is agnostic to *how* the profile was resolved — keyword vs pinned is a caller's choice
of entry point, not a difference in the record.

**Enforcement test** (`tests/test_motion_profiles.py`) — fails the build on a half-formed profile:

- `registry.json` parses; `default` key exists and resolves.
- Every listed file parses and its `key` matches the registry entry.
- **Every profile — at every level — independently declares the full canonical pose key set (§3.4).**
  There is no inheritance (§3.7), so no file may lean on another to supply a key; a breed file lists
  all canonical poses and sets `enabled:false` for the ones it can't do.
- **Every profile declares a valid `level` (1–4)**, and it matches the registry entry's `level` (§3.7).
- `walk` and `idle` are `enabled:true` in **every** profile (each file must be independently
  runnable — the auto state machine needs one `active` + one `rest`).
- Every `enabled:true` pose has a non-empty `action` and a `runtime_role` in the allowed set.
- `keywords` are non-empty and unique across ALL profiles at all levels (no two profiles claim the
  same token — §3.7).
- The `quadruped` animal-type profile's `walk`/`idle` `action`+`suffix` reproduce today's constants
  **verbatim** (the backward-compat pin, §6).

### 3.7 Specificity levels — most-specific-level-wins, whole-file, no inheritance (Rev.3)

**The problem Rev.2 left open — and why it is a correctness problem, not a polish one.** A category is
a coarse bucket, and the coarseness bites *within* a category, not just across categories. "Quadruped"
spans a mouse and a horse; worse, a single **species** is not motion-uniform either. **"Dog" spans a
Great Dane and a poodle and a corgi and a greyhound** — a tall slow lope, a light bouncy prance, a
low stubby waddle, a long-stride sprint. Same species, radically different bodies, radically different
motion. A generic description gets the *common* case and quietly mis-animates the long tail: it might
be right **80% of the time and wrong 10–20%** — and for this product the animation *is* the deliverable,
so a 10–20% "walks wrong" rate is **not acceptable**. Body type is the right *floor*, never the *ceiling*;
even species is often too coarse. The intricacies that must be right — a Great Dane's slow lope vs a
poodle's prance, a kangaroo's hop, a crab's sideways scuttle, a hummingbird's hover — only a
breed/species-level description captures.

**The design: an explicit level + whole-file fallback. NO inheritance — and the no-inheritance is the
whole point.** Every profile declares a `level`; resolution picks the **most-specific profile whose
keywords match**, and uses **that file, whole**. A matched file is complete and self-contained —
nothing merges in from a more general level. Four levels:

```
level 1  breed        → corgi.json      (shortest legs, low waddle)
level 2  species      → dog.json        (panting, tail wag)
level 3  animal type  → quadruped.json  (the body type; today's default)
level 4  generic      → registry.default (the floor — always present)
```

**Fallback order (most specific first, whole-file wins):** classify an animal → is there a **level-1
(breed)** match? Use that file, done. No breed → **level-2 (species)** match? Use that file, done. No
species → **level-3 (animal type)**? Use it. Nothing → **level-4 generic**. The first level that
matches wins outright; more general levels are never consulted once a match is found.

**A matched file's poses are exactly what it lists — no borrowing.** This is the core rule and the
one you named directly: if `corgi.json` matches, the pet's available poses are **precisely** the
enabled poses in `corgi.json`. If corgi has no `jump` (it sets `"jump": {"enabled": false}`), then
**jump is not an option** for a corgi — *even though `quadruped` enables jump*. There is no reaching
up a level to pull jump in. What the winning file declares is the whole story.

```json
// corgi.json — a complete, standalone level-1 file (declares ALL canonical keys)
{
  "key": "corgi", "level": 1,
  "movement_class": "mammalian_quadruped",
  "keywords": ["corgi", "pembroke", "cardigan corgi"],
  "poses": {
    "walk":  { "enabled": true,  "runtime_role": "active", "action": "trotting with short quick legs, low to the ground", "suffix": ", stubby-legged waddle, no camera movement" },
    "idle":  { "enabled": true,  "runtime_role": "rest",   "action": "standing alert, tail wagging",                     "suffix": ", gentle breathing, ears perked, no camera movement" },
    "run":   { "enabled": true,  "runtime_role": "active", "action": "galloping fast despite short legs",                 "suffix": ", energetic, no camera movement" },
    "sleep": { "enabled": true,  "runtime_role": "timed",  "action": "curled up, belly to the floor",                     "suffix": ", still, slow breathing, no camera movement" },
    "sit":   { "enabled": true,  "runtime_role": "timed",  "action": "sitting, ears up",                                  "suffix": ", small head movements, no camera movement" },
    "eat":   { "enabled": false }, "jump": { "enabled": false }, "play": { "enabled": false },
    "swim":  { "enabled": false }, "fly":  { "enabled": false }
  }
}
```

Because there's no inheritance, **each file declares the full canonical pose key set** (§3.4) and
sets `enabled` per pose — a corgi's un-doable poses are `{"enabled": false}` (the §3.2 rule:
whether a pose *exists as a key* is the uniform contract; whether it's *enabled* is this file's
decision). "Corgi can't jump" is therefore a **recorded, reviewable fact in `corgi.json`**, not a
silent omission and not something to reason about across levels.

**No-inheritance is a forcing function for correctness (the real reason — decision §9.4).** The point
is not merely that whole-file resolution is simpler to reason about; it is that **inheritance would
re-introduce the exact failure this feature exists to kill.** An inheriting model invites the 80%
path: "a Great Dane is mostly a dog, just override a little." Whatever the author *doesn't* override
is silently inherited — and for the breeds whose bodies diverge from the species norm, the inherited
`walk` is *wrong*, yet the file looks complete and reviews clean. That is precisely the 10–20% silent
mis-animation, now baked into the data model. No-inheritance removes the option to be lazy: because a
matched file is used whole and lists every pose itself, **authoring `great_dane.json` forces a
conscious decision about how a Great Dane actually moves** — you cannot accidentally inherit a
description that doesn't fit, because there is nothing to inherit. Completeness is mandatory, so
correctness is deliberate.

**The accepted cost is duplication.** A breed file repeats the shared wording for the poses it doesn't
change (a corgi's `sleep` may read much like a generic quadruped's). We pay that willingly: duplication
is a *maintenance* cost (a shared-wording tweak is redone per file), whereas silent inheritance is a
*correctness* cost (a wrong animation ships). We trade the cheaper problem for the elimination of the
expensive one. If the maintenance cost ever bites, an author-time helper can pre-fill a new breed file
from its animal-type template so a human edits only the differences — but that is a *scaffolding*
convenience that still produces a complete standalone file; the runtime stays inheritance-free and the
forcing function intact (§9.4).

**Classification = most-specific-level-match (replaces §3.5's flat rule).** Keyword matching runs
across *all* profiles at *all* levels; the winner is the match at the **lowest level number** (1
beats 2 beats 3), longest-keyword tie-broken within a level. So "corgi" → `corgi` (level 1); "dog"
(no breed word) → `dog` (level 2); "wolf" (only an animal-type keyword, or none) → `quadruped` (level
3); an unmatched animal → `registry.default` generic (level 4). The level-3/4 path reproduces today's
behavior exactly, so the backward-compat guarantee (§6) is untouched.

**Why this is still engine-vs-content (the boundary holds).** The engine calls
`resolve_motion_profile(animal)` and gets back **one** `MotionProfile` — the winning file, loaded.
It has no idea what level that file was, or that other levels exist. `make_pet_zip` loops over
`profile.enabled_poses()` and never names a species. The *naming* — "corgi", "the corgi's stubby
waddle" — lives 100% in the content file. Adding `arabian_horse.json` at level 1 is one file + one
registry line; no engine change, no change to any other profile. This *strengthens* the "new variant
without an engine change" property: a variant can be as fine-grained as a single breed, and each
variant file is independently readable.

**Guard-test additions (§3.6):** every profile declares a valid `level` (1–4); `level` in the file
matches the registry entry; `keywords` are unique across all profiles at all levels; **every profile
independently declares the full canonical pose key set with `walk`+`idle` enabled** (no inheritance,
so no file may lean on another to supply them); the `quadruped` animal-type file still reproduces
today's wording verbatim (unchanged pin). There is no `parent` link and therefore no cycle/depth
concern — the level number alone orders resolution.

**Scope note.** Rev.3 specifies the *mechanism* and ships the level-3 animal-type roots plus the
level-4 generic default, exactly as Rev.2's coverage. Authoring specific species/breed files (levels
1–2) is incremental **content** work — highest-traffic animals first (dog, cat, horse, corgi, mouse,
rabbit, popular bird species) — each a complete standalone file behind the guard test, needing no
code or engine change. The levels exist so authoring can get as specific as fidelity demands,
whenever it demands it, without ever reopening the engine.

### 3.8 The registry as a growing fidelity asset (and a defensibility moat)

The registry is **designed to grow** — to hundreds of entries over time — and that growth is the
point, not a cost to be minimized. Each framing below is a deliberate strategic property of the
no-inheritance, most-specific-wins design (§3.7).

**Body type drives animation — this is the load-bearing craft insight.** From hands-on animation
experience: *how a creature is shaped is one of the biggest determinants of how it moves.* Weight
distribution, limb length, mass, center of gravity — these dictate gait, timing, and secondary motion
far more than the species label does. A description that ignores body shape produces motion that reads
as "generically animal" rather than "*this* animal," and viewers feel the wrongness even when they
can't name it. The whole point of the level system is to let the motion description track the thing
that actually governs motion — the body — as finely as needed.

**Fidelity has no fixed floor.** The four named levels (breed → species → animal type → generic) are
where authoring *usually* lands, but "most-specific-keyword-wins" imposes no ceiling on specificity.
When a case surfaces that even a breed can't capture, the answer is the same one-file move at a still
more specific match — **a fat corgi and a skinny corgi may genuinely need different descriptions**
because their body types diverge enough to animate differently (a low-slung heavy waddle vs a lighter
trot). The design already accommodates this: it is just another, even-more-specific entry (a
body-variant keyword like "chubby corgi", or a sub-breed file). The architecture never has to *predict*
how fine-grained fidelity will need to go — it only has to let authoring go there the moment reality
demands it, which it does, at the cost of exactly one more isolated file.

**Growth is monotonic and compounding.** Because every file is standalone and isolated (§3.7), each
new entry is guaranteed-correct motion for one more creature that *cannot regress or break any other
entry*. The library's accuracy is a monotonic function of authoring effort: quality only ever goes up,
one file at a time. Exceptions discovered in production are absorbed the same way — spot a creature
that animates wrong, add one more specific file, done. The system is built to *accumulate* fidelity,
not to be finished.

**The accumulated registry is a moat competitors cannot easily copy.** The engine is commodity — a
handful of ComfyUI workflows anyone can reproduce. The *value* is the hundreds of hand-tuned,
body-type-aware motion descriptions that encode real animation expertise, each earned by observing
what actually reads right for that creature. That knowledge lives in the `motion_profiles/` JSON and
nowhere else; it is not derivable from the generated output (a competitor sees the animation, not the
prompt that made it), and it is not something a clone can shortcut. A rival can copy the mechanism in
a weekend; reproducing the *catalog* means redoing the same long-tail craft work, per creature, from
scratch. **The registry is therefore both the product's consistency guarantee and its durable
competitive asset** — the longer it runs and the more exceptions it absorbs, the harder it is to
imitate. This is a direct argument for investing in the content over time, not treating profile
authoring as a chore.

> **Rev.3 alignment pass (same day):** cross-spec audit fixes applied — §3.2's example now satisfies
> §3.6's own guard (declares `level` + the full 10-key canonical set); §4.1 gained the pinned-profile
> lookup (`?profile=<key>`) and returns the resolved `profile`+`level`; §5.2/§5.3 carry the pinned
> `motion_profile` through generation so a catalog pin governs the *build*, not just the menu.
> Counterpart edits in SPEC_PET_DESIGNER_PLATFORM Rev.3 (§4.2 catalog `motion_profile` pinning —
> without it, a catalog Corgi would have resolved coarser than free-text "corgi").
> **Readiness pass (same day):** §10 step-3 gate now probes BOTH v3 fields (incl. an
> unknown-`motion_profile` probe proving the skew fallback); step-4 gate covers the pinned
> `?profile=` path end to end; §5.2 gained the profile-set skew rule (unknown pinned key on the
> worker → keyword fallback + warning, never an error; profile additions install node-first, the
> §B.1 habit applied to content).

### 3.9 Control-signal tier — a forward-compatible placeholder for skeleton-driven motion (Rev.3; Rev.4 adds the `sprite` kind, §3.9.1)

**Why this belongs in the design now, even though it ships empty.** A text prompt asks the model to
*improvise* the motion; a **control signal** — a pose skeleton, or a depth-map reference — *constrains*
it so the model copies the motion instead of inventing it. Prompt-only therefore has a ceiling (the
long-tail cases §1/§3.7 describe), and the industry-standard way through that ceiling is a control
signal (ComfyUI/Wan "Animate"/VACE drive motion from a DWPose/animal-pose skeleton or a depth video;
see `docs/` research notes). **A skeleton is strictly more specific and more reliable than any prompt**
— it is the most specific description of a motion there is. This is the same "most-specific-wins"
instinct as the level system (§3.7), applied one axis over: not a more-specific *profile*, but a
more-specific *control method within a pose*.

**Decision — design the seam now, author nothing yet.** We are deliberately staying **prompt-only at
launch** to see how far prompts go (per author intent). But because retrofitting a control tier later
would be an engine change if the shape isn't reserved, §3.9 defines the field and the resolution rule
*now* so that adding a skeleton later is **pure content** — one field on one pose, no `factory.py`
change. The field is optional and unset everywhere today, so the design is **default-inert**: with no
control signal present, generation is byte-identical to the prompt-only pipeline (§6 backward-compat
is untouched).

**The shape — one optional block per pose.** The canonical `Pose` (§3.6) gains an optional `control`
object; a pose with no `control` is prompt-driven exactly as today:

```json
"walk": {
  "enabled": true, "runtime_role": "active",
  "action": "trotting with short quick legs, low to the ground",
  "suffix": ", stubby-legged waddle, no camera movement",
  "control": {                          // OPTIONAL — absent today; the placeholder
    "kind": "pose_skeleton",            // "pose_skeleton" | "depth" | "sprite" (§3.9.1)
    "ref": "corgi/walk.skeleton.mp4",   // path within the profile dir, shipped with the handler
    "strength": 1.0                     // how hard the signal constrains (0..1)
  }
}
```

**Resolution rule — control beats prompt, per pose (extends §3.7's spirit).** When `make_pet_zip`
builds a pose, it checks for `control`:

- **`control` present and its `kind` is supported by the running engine** → drive that pose from the
  control signal (the prompt `action`/`suffix` become a *secondary* style hint the control workflow
  still accepts). This is the strongest, most reliable tier.
- **`control` absent, OR its `kind` isn't supported by this engine build** → fall back to the
  prompt-only path (today's `_loop_wf`). The fallback is what keeps the field safe to add before the
  control workflow exists: an older/handler-only-prompt node simply ignores `control` and generates
  from the prompt, never erroring.

So the precedence within a pose is **skeleton → depth → sprite → prompt**, mirroring the profile-level
"most-specific-wins": use the most specific control available, fall back to the most general (the
prompt) when it isn't. Per pose, per profile — a `corgi.json` could skeleton-drive only its `walk`
(where gait fidelity matters most) and leave every other pose prompt-driven.

**§3.9.1 The `sprite` kind — the stills-layer control that ships first (Rev.4).** Between prompt-only
and a true skeleton/depth signal sits a third, cruder kind that needs **no new engine capability**: a
**pose *sprite*** used as an img2img *source*. `ref` points at a shared per-body-type pose image (a
generic wings-spread bird, `avian/fly.pose.png`); the engine img2img-redraws the pose's own base
still onto it at `strength`, producing a *"this animal, in that pose"* anchor still, then runs the
**standard prompt-driven `_loop_wf`** from that still. It differs from `pose_skeleton`/`depth` in
*which pipeline stage* it acts on — the sprite reshapes the **anchor still**, then the normal loop
runs; skeleton/depth constrain the **video motion** itself — which is why its precedence sits *below*
them and *above* prompt. Crucially the sprite kind **reuses the pose's existing `action`/`suffix`** as
its redraw prompt (spliced with `{animal}` by `compose_pose_prompt`, already templated), so it needs
**no new field and stores no per-species string**: the block stays `{kind, ref, strength}`. This is
the mechanism `SPEC_POSE_ANCHOR_HYBRID` specifies and the **first `control` kind slated to ship** —
feasible on today's `_img2img_wf`, gated only on the §7 validation experiment. It is also the
**resolution of the "pose anchor vs. control field" question** raised across the sibling specs: the
"pose anchor" is *realized as* this `control` block, sprite kind — one field, not two. Engine dispatch
is per-kind (the plugin pattern this block was built for): `sprite` → redraw-then-standard-loop;
`pose_skeleton`/`depth` → control-driven loop.

**What this does NOT commit us to now (scope guard).** §3.9 reserves the *shape and the fallback
rule* only. It does **not** add a control-capable ComfyUI workflow, does **not** ship any `.skeleton`
assets, and does **not** touch `_loop_wf` at launch — the resolver simply never sees a `control` block
because none is authored. Building the actual skeleton/depth workflow (an animal-pose model — DWPose
is human-only; a quadruped-keypoint ControlNet or species-agnostic depth is the animal path) is a
**later, separate spec**, gated like any generation change (a handler version bump + the
`SPEC_DEPLOY_PETDATSME_POOL.md` §B.1 fleet discipline, since it changes what a node must run). The
value captured today is only this: **when that day comes, turning it on for an animal is editing a
JSON file, not the engine.**

**Guard-test additions (when the field is first used, not before):** if a pose declares `control`,
its `kind` is in the allowed set and its `ref` resolves to a file shipped in the profile dir; a
`control` block never removes the requirement that the pose still have a valid prompt `action`/`suffix`
(the fallback must always exist). Until any profile authors a `control` block, these assertions are
vacuously true — the placeholder costs nothing.

**Reference implementation — imitate `datsPet` when the skeleton day comes.** The skeleton path is
not hypothetical: a **shipped, validated** version exists in the sibling `datsPet` application
(`/home/markly2/claude_code/datsPet`), and the future control workflow should imitate its **data model
and registry**, which map almost one-to-one onto this spec. Concretely, from that codebase:

- **The skeleton representation to copy.** A pose = a `(17, 2)` array of AP-10K animal keypoints
  (eyes, nose, neck, tail-root, per-leg shoulder/elbow/paw + hip/knee/paw); a motion = a
  `(num_frames, 17, 2)` array. It is stored as *code that computes coordinates*, not an image — one
  self-contained module per animation exporting `build_keypoints(n) -> array`
  (`datsPet/generation/dog_pose/sequences/pose_dog_walk.py`), with a fixed topology + locked
  ControlNet-matched colors in `ap10k_skeleton.py`. Non-skeleton bodies (birds, butterflies) use the
  same slot but emit grayscale silhouettes for a depth ControlNet — the topology-agnostic fallback.
- **The registry to copy — it already IS this spec's hierarchy.** datsPet keys conditioning on
  `(movement_class, animation) -> build_keypoints`, with **species packages** (`dog_pose`, `cat_pose`)
  sitting *more specific than* the **animal-type package** (`quadruped_pose`) over a **generic**
  (`default_pose`). That is exactly §3.7's corgi→dog→quadruped ladder, in production — a direct
  validation that the level design is right. When we add `control`, the skeleton asset is simply the
  payload behind a pose's `control` field, keyed the same way our prose already is.
- **Two authoring paths to reuse.** Hand-authored parametric motion (sin/cos joint curves with a
  GPU-free preview loop) for speed, and a **video→skeleton** extractor (MMPose AP-10K, run in an
  *isolated* env via subprocess + JSON — `datsPet/docs/GUIDE_VIDEO_TO_SKELETON.md`,
  `SPEC_SKELETON_LAB*.md`) for real biological motion. The isolation discipline (the ML tool is
  invoked, never imported) is itself worth copying.
- **Hard-won constants to start from.** datsPet's validated operating point is `cn_scale≈0.7 /
  ip_scale≈0.3` (follow the precise pose strongly; anchor supplies identity only) — a starting point,
  not a re-derivation.

**The one caveat that keeps this a *later* spec, not a copy-paste (engine mismatch).** datsPet runs
**SD 1.5 + AnimateDiff + a ControlNet** (a motion adapter grafted onto a still-image model — 2023-era,
and datsPet's own docs name "a stronger video model" as its upgrade path). This pipeline runs a
**newer engine**: **Z-Image-Turbo + Wan 2.2 I2V** — a purpose-built image-to-video model, i.e. the very
class of engine datsPet was looking toward. So the current stack is *ahead on the engine* but *behind
on motion control* (prompt-only today vs datsPet's skeleton control). The consequence: the **skeleton
data model and the registry port cleanly; the ControlNet wiring does not** — Wan 2.2's control path is
its own (VACE / Wan-Animate-style adapters), not SD 1.5's ControlNet. This is precisely why §3.9
reserves only the *shape* here and defers the control *workflow* to a separate spec: that spec's real
work is porting datsPet's proven skeleton concept onto this repo's more modern Wan engine.

---

## 4. Front-end integration — the pose-selection package

The design page lets the user choose **which enabled poses to generate this run** — the GPU-cost
control (each pose is a separate ~75 s Wan I2V generation; §8).

### 4.1 New read-only endpoint — the menu
Two lookup modes, one response shape:
- `GET /api/motions?animal=<species>` — **keyword path** (the General free-text page): resolves via
  §3.5/§3.7 most-specific-level matching.
- `GET /api/motions?profile=<key>` — **pinned path** (a curated base's reference carries its
  authored key; the "themed pages" this once named are deleted — SPEC_PET_DESIGNER_FLOW §11 —
  but the pinned path is unchanged and is what the designer uses. It passes the authored
  `motion_profile` key, SPEC_PET_DESIGNER_PLATFORM §4.2): loads that profile directly, no keyword
  matching. An unknown key → 404 (a catalog guard test prevents this shipping).

The response carries the **resolved profile identity** — key + level — so the UI (and any debugging)
can see exactly which file won resolution:
```json
{
  "profile": "corgi",
  "level": 1,
  "movement_class": "mammalian_quadruped",
  "poses": [
    { "name": "walk",  "required": true,  "enabled": true },
    { "name": "idle",  "required": true,  "enabled": true },
    { "name": "run",   "required": false, "enabled": true },
    { "name": "sleep", "required": false, "enabled": true },
    { "name": "sit",   "required": false, "enabled": true }
  ]
}
```
Only `enabled:true` poses are returned (a corgi's disabled `jump`/`swim`/`fly` never appear). The
server never exposes the raw prompt text to the browser (it's authored content, and irrelevant to
the UI).

### 4.2 The control (`web/src/app/design/page.tsx`)
A "Poses to generate" section: one checkbox per returned pose — **the user freely picks which poses
their pet gets**, up to their tier cap (base 2, plus up to 5 — SPEC_PET_DESIGNER_PLATFORM §5).
`required` poses (walk+idle) render checked-and-disabled; the rest are the user's choice. Once the
cap is reached, remaining unchecked poses disable with an upsell tag ("upgrade for more poses"). A
live cost hint reads off the checked count ("3 poses ≈ 4½ min"). On species/base-pet change the menu
refetches, so a snake and a bird show different options — the UI is a projection of the resolved
profile, no client-side species logic.

### 4.3 The request
`POST /api/generate` gains one field: `poses` — the selected package, e.g.
`{"walk":true,"idle":true,"run":true,"jump":false}` (JSON string in the form body, mirroring how the
design fields already ride). Absent → walk+idle only (today's behavior; safe default).

---

## 5. Back-end + transport integration

### 5.1 Web tier (`webui/app.py`)
- `start_job` reads `poses`, resolves the profile, intersects the request with the profile's enabled
  poses, and **always unions in `required_motions`** (walk+idle) — a malformed request can never
  produce a pet the runtime can't drive. The validated pose list flows to generation.
- One new endpoint (§4.1). Both are thin; no DB or DPP change.

### 5.2 The pool transport — handler **v3**
The selected poses ride in the existing params dict: `params["poses"] = {...}`, and the catalog's
pinned profile key rides alongside as optional `params["motion_profile"]` — so a catalog-pinned
resolution governs the *build*, not just the menu (without it, generation would keyword-re-resolve
from the composed description and could diverge from what the menu showed). When `motion_profile`
is present, `make_pet_zip` loads that profile directly; absent → keyword resolution (§3.5/§3.7), as
for General free text. This is a **v3 `pet_factory` handler** schema bump (two new optional fields:
the `poses` object and the `motion_profile` string). Both fields are optional, so v2
submits still validate — but §B.1 of `SPEC_DEPLOY_PETDATSME_POOL.md` **binds fully**: install v3 on
**Omen first** (single-version fleet), run the executable gate (probe submits carrying `poses` AND
probe submits carrying `motion_profile` both validate; a bare submit still works), then the
dual-nvidia card. The same silent-mixed-fleet hazard (a v2 node ignoring `poses` → generating only
walk+idle) applies; the ordering discipline is the mitigation. `pet_preview` is unaffected (preview
is the still, not motion).

**Profile-set skew — the pinned key may not exist on the worker (must handle, will happen).** The
`motion_profiles/` content ships *with the handler* to each GPU node, and the web tier carries its
own copy — so the two sets can diverge between rollouts: add `corgi.json`, redeploy the web tier
first, and the web pins `motion_profile: "corgi"` while the node's copy doesn't have it yet. The
rule: **an unknown pinned key on the worker falls back to keyword resolution (§3.5/§3.7) and logs a
warning — never an error.** The degradation is exactly the pre-`corgi.json` behavior (the keyword
path lands `dog`/`quadruped`), so a skewed fleet generates slightly-coarser motion, not failures.
The same applies web-tier-side (`/api/motions?profile=` 404s only on the *menu*, where the catalog
guard test prevents it shipping; the generate path degrades). Operationally, profile *additions*
follow the same ordering discipline as handler versions: **install on the GPU nodes before the web
tier/catalog references the new key** — the §B.1 habit, applied to content.

### 5.3 `pet_factory` (`make_pet_zip` + `pack_datsme_bundle`)
- `make_pet_zip` gains `poses: dict[str,bool] | None` and `motion_profile: str | None` (the pinned
  key, §5.2; absent → keyword resolution). It resolves the profile once — **`motion_profile` present →
  `load_motion_profile(motion_profile, fallback_animal=animal)`; absent →
  `resolve_motion_profile(animal)`** (§3.6) — computes the effective pose list (enabled ∩ requested ∪
  required), then **loops** those poses — each a `_loop_wf` generation using that pose's
  `action`+`suffix` — collecting `{pose: frames}`. The two hardcoded walk/idle calls
  (`factory.py:430-436`) become this loop. Progress ticks are distributed across the N poses instead of
  the fixed 0.35/0.60.
- `pack_datsme_bundle` takes the `{pose: frames}` dict (replacing `walk_frames, idle_frames`) plus
  `movement_class=profile.movement_class`. It writes each pose into the manifest `animations` map
  with its declared `runtime_role` (+ role knobs where the profile sets them). **This finally stamps
  the real `movement_class`** — fixing the mislabel bug (§1.2) as a side effect.
- Sheet layout generalizes from "walk row + idle row" to "one row band per pose"; `columns` and
  frame indices are computed per pose (the packer already lays walk on row 0 and idle on a fresh
  row — this extends that to N).

### 5.4 What deliberately does NOT change
- **No ComfyUI/workflow change** — `_loop_wf` is untouched; only the prompt strings fed to it, and
  how many times it's called, differ.
- **No `datsme_me` change** — the runtime already plays these roles (§2). Manifest shape is
  unchanged; we populate more of it.
- **No DPP / bundle-format / preview change.** `make_pet_zip`'s new arg is optional; every existing
  caller (the local path, the v2/older submit) behaves exactly as today when `poses` is absent.

---

## 6. Backward compatibility (the safety property)

The whole change is **additive and default-inert**:

- `poses` absent (any old caller, a v2 submit, a standalone text generation) → the effective set is
  the profile's required poses = `walk`+`idle`, with the `quadruped` profile's wording pinned
  verbatim to today's constants (§3.6 test). **Output is byte-identical to current behavior** for an
  unclassified animal.
- A classified animal with no pose selection still generates only walk+idle — but now with
  *species-correct* wording and the *correct* `movement_class`. That is strictly a fidelity
  improvement over today, at the same 2-pose GPU cost.
- Extra poses cost GPU only when a user opts in (§8).

---

## 7. The `triggered`/`timed` honesty note (jump & sleep)

§2 established the runtime plays all four roles, but with one asymmetry worth stating plainly so the
UI doesn't over-promise:

- `active` (walk/run/swim) and `rest` (idle) are **auto-driven** — generate them and the pet uses
  them immediately.
- `timed` (sleep) is **auto-reachable** from rest — generate it and the pet will play it on its own.
- `triggered` (jump) is **only** fired by an interaction behavior. Today the sole trigger path is
  `useClickPetExcited` (`pet/behaviors/`). A `triggered` pose with no behavior pointing at it is
  generated and packed but never plays. So `jump` is real *if* a trigger references it; wiring a new
  trigger (e.g. "jump on double-click") is a small **`datsme_me`** task, out of scope here.

**Decision (§9.1):** at launch the pose menu offers only auto-driven roles — the `active`/`rest`/
`timed` poses (`walk`, `idle`, `run`, `swim`, `fly`, `sleep`, `sit`, `eat`). The `triggered` poses
(`jump`, `play`) are authored in the profiles (so the data model is complete and proven) but
**hidden from the selector** until a DatsMe-side trigger is wired, so no user pays GPU for a pose
that won't move. Flipping them on later is a one-line UI change, no regeneration of the data model.
The user **freely picks which** of the offered poses to build, up to their tier cap (§4, §8) —
walk+idle are always included (required), and the remaining slots are the user's choice.

---

## 8. GPU cost & guards

- Each enabled+selected pose = one Wan I2V generation ≈ 75 s on a 3090. walk+idle = ~3 min (today);
  5 poses ≈ ~7 min; the sheet grows one row-band per pose.
- **`MAX_POSES = 10`** — the absolute platform ceiling, enforced in the loader/validator so a profile
  or a request can never balloon a build unbounded. It equals the full canonical pose set (§3.4).
  This is the *hard* ceiling; the **per-user cap is set lower by the tier layer** (base 2, plus up to
  5 — SPEC_PET_DESIGNER_PLATFORM §5.1), so in practice a build is 2–5 poses. A selection over the cap
  is clipped with a log line (no silent truncation).
- **Handler `timeout_s` must rise for the 10-pose worst case (R1-fix).** 10 poses × ~75 s + the still
  + cutout ≈ ~14 min — dangerously close to the current 900 s (15 min) watchdog kill. Two options,
  both fine: (a) raise `pet_factory` v3's `timeout_s` to **1500 s** (25 min) to cover the ceiling with
  headroom; or (b) leave 900 s and cap the *effective* build at the tier maximum (≤5 poses ≈ ~7 min,
  comfortably under 900 s) — never letting a single build approach 10. **Recommended: (b) at launch**
  (tiers cap builds well under the watchdog) with (a) as the change if the ceiling is ever raised to
  real 10-pose builds. Either way, `MAX_POSES=10` is the data ceiling; the *realized* build size is
  tier-bounded, so the watchdog is safe without a v3 timeout change at launch.
- The front-end cost hint makes the tradeoff visible **before** the user commits (§4.2).

---

## 9. Decisions

1. **`jump`/`triggered` at launch — RESOLVED: author it, hide it from the selector** until a
   DatsMe trigger is wired (§7). The data model is complete; the UI is conservative.
2. **Config format — RESOLVED: JSON files, one per body type + a registry.** Matches the goal
   verbatim and the engine-vs-content boundary. (A Python registry was considered and rejected: the
   goal is explicitly configuration-driven, and JSON keeps the vocabulary editable without touching
   generation code — the whole `motion_profiles/` dir ships with the handler to the GPU nodes.)
3. **Classification — RESOLVED: keyword match, LLM deferred** behind the `resolve_motion_profile`
   seam (§3.5).
4. **Specificity levels — RESOLVED (Rev.3): explicit `level` (1 breed / 2 species / 3 animal type /
   4 generic), most-specific-level-wins, whole-file, NO inheritance (§3.7).** The driver is
   *correctness*, not taxonomy neatness: a single species is not motion-uniform — "dog" spans a Great
   Dane, a poodle, a corgi, a greyhound — so a general description is right ~80% and silently wrong for
   the divergent long tail (10–20%), which is unacceptable when the animation *is* the product. A
   profile declares its level; resolution uses the lowest-level keyword match's file *as-is*.
   **No merging across levels:** a matched file's poses are exactly what it lists (a corgi with no
   `jump` simply has no jump option, regardless of what `quadruped` enables). Chosen over an inheriting
   `parent` chain (deep-merge child-over-parent), which was **rejected specifically because inheritance
   re-introduces the failure**: it lets a breed silently inherit a species `walk` that doesn't fit its
   body, and the file still reviews clean. No-inheritance is a **forcing function** — authoring
   `great_dane.json` compels a conscious description of how a Great Dane moves; nothing can be
   inherited wrong. The accepted cost is duplication (a breed file repeats shared wording for poses it
   doesn't change) — a *maintenance* cost traded for eliminating a *correctness* cost; an optional
   author-time template helper can pre-fill new breed files, but the runtime stays inheritance-free.
   The engine-vs-content boundary holds: the
   engine reads one resolved file and never names a species. Authoring specific files is incremental,
   non-gating content work; the animal-type (level 3) roots + generic default ship first, per Rev.2.
5. **Control-signal tier — RESOLVED (Rev.3): design the seam now, author nothing yet (§3.9).** A
   prompt improvises motion (ceiling on the long tail); a skeleton/depth control signal constrains it
   and is strictly more specific and more reliable — the most specific motion description there is. We
   stay **prompt-only at launch** (author intent: see how far prompts go), but reserve an optional
   per-pose `control` field and the precedence rule **skeleton → depth → prompt** now, so adding a
   control signal later is pure content (one JSON field) rather than an engine change. Default-inert:
   with no `control` authored, generation is byte-identical to the prompt-only pipeline. Building the
   actual control workflow is a **later separate spec**, gated by the deploy §B.1 fleet discipline, and
   it should **imitate the shipped `datsPet` skeleton system** (§3.9 reference) — copy its AP-10K
   `(N,17,2)` data model + specificity registry, but re-do the engine wiring for this repo's Wan 2.2
   I2V (datsPet's ControlNet is SD 1.5-specific; our engine is newer). This decision captures only the
   forward-compatible shape.
6. **Launch pose set — OPEN (product call, does not gate the build):** which optional poses to
   author descriptions for at launch (run? sleep? swim only for aquatic?). The machinery is
   pose-agnostic; this is just how many description strings to write on day one. Recommendation:
   `walk`+`idle`+`run` everywhere, `swim` for aquatic/serpentine, `sleep` where it reads well.

---

## 10. Implementation & cutover order

1. **`pet_factory/motion_profiles/`** — registry (with `level` per entry) + animal-type (level-3)
   JSONs + **both loaders** (§3.6: keyword `resolve_motion_profile` + pinned `load_motion_profile`
   with skew fallback) + guard test. Unit-testable with zero GPU (resolution order, validation,
   backward-compat pin). *Gate: guard test green; `quadruped` resolves to today's verbatim wording; a
   test `corgi.json` at `level:1` wins over `quadruped` for "corgi" and its enabled-pose set is exactly
   corgi's (e.g. jump absent because corgi disables it); every file independently declares the full
   pose key set; `load_motion_profile("corgi")` returns corgi, and `load_motion_profile("nonesuch",
   fallback_animal="dog")` falls back to keyword resolution (returns quadruped) with a logged warning
   and does NOT raise.* (Species/breed files are later content adds; the mechanism + one fixture prove
   the level fallback here.)
2. **`make_pet_zip` + `pack_datsme_bundle`** — the pose loop + per-pose manifest packing +
   `movement_class` from the profile. *Gate: a local `poses=None` build is byte-identical to today; a
   `poses={walk,idle,run}` build produces a 3-animation bundle whose manifest carries correct roles.*
3. **Handler v3** — add optional `poses` AND `motion_profile` to the schema (§5.2); bump METADATA
   version "2"→"3". *Gate: the §B.1 executable checks (Omen-first; probe submits carrying `poses`
   validate; probe submits carrying `motion_profile` validate; a bare v2-shaped submit still works;
   a probe with an UNKNOWN `motion_profile` key still generates — keyword fallback, §5.2 skew rule —
   and the worker log shows the fallback warning).*
4. **Web tier** — `/api/motions` (both lookup modes) + `start_job` pose/pin handling. *Gate: curl
   the menu for "cobra" vs "sparrow" → different offers (keyword path); curl `?profile=corgi` →
   the corgi menu with `profile`+`level` in the response, unknown key → 404 (pinned path); a
   generate with a pose package produces the selected animations; a generate carrying
   `motion_profile` builds from the pinned profile (assert via the manifest's `movement_class` +
   animation set).*
5. **Front end** — the pose selector + cost hint. *Gate: menu reflects the resolved profile;
   required poses locked; cost hint tracks the count; a full designed flow end to end.*
6. **Fleet rollout** — install v3 per `SPEC_DEPLOY_PETDATSME_POOL.md` §B.1 (Omen first, then the
   dual-nvidia card), same discipline as the v2 cutover.

---

## 11. Consistency checks (global engineering rules)

- **New variant without an engine change?** ✓ **and now at any granularity (Rev.3).** An animal type,
  a species, or a single breed is one JSON file + one registry line (with its `level`); `make_pet_zip`
  never names a species — it loops whatever the resolved profile enables. The levels *strengthen* this
  test: fidelity can go as fine as a corgi without ever touching generation code.
- **New feature without touching unrelated files?** ✓ Generation: the two hardcoded calls become a
  loop over a new package; the loader returns one resolved file (§3.7), so `make_pet_zip` is unaware
  that levels exist. Transport: one optional param + a version bump. Web/front: one endpoint + one
  control. DB, DPP, preview, bundle format, `datsme_me`: untouched.
- **Third-party/engine integration without modifying owned paths?** ✓ `datsme_me` is unchanged — the
  runtime already consumes the roles this produces (§2); we populate manifest fields it already
  reads.
- **Bug in one profile can't touch another?** ✓ **Fully isolated (Rev.3).** With no inheritance,
  every profile file is completely independent — a bad `corgi` description cannot affect `dog`,
  `quadruped`, or any other profile; there is no shared/parent state for a bug to propagate through.
  Each file is used whole or not at all. The guard test fails the build before a half-formed profile
  ships.
- **Fixes a standing inconsistency:** every non-quadruped pet is currently mislabeled
  `mammalian_quadruped`; §5.3 stamps the real `movement_class` as a side effect.

---

### Appendix — grounding (every claim traces to code, verified 2026-07-13)
- Hardcoded motion prompts + suffixes: `pet_factory/factory.py:68,73,430-436`.
- `movement_class` hardcoded + consumed: `factory.py:315,357,359`; `datsme_me/api/routes/admin.py:1164-1197`.
- Runtime role model (4 roles) + role knobs: `datsme_me/web/src/pet/types.ts:10,63-92`.
- Role dispatch (name-free, by `runtime_role`): `pet/behaviors/useAutoStateMachine.ts:181,203,219,228`.
- Rest-anim resolution by role: `pet/petStore.ts:334-341`; `pet/personality.ts:109,180`.
- Absent-role safety (kept, not auto-played): `types.ts:70-72`; `manifest.ts:57,70`.
- Trigger path for `triggered`: `pet/behaviors/useClickPetExcited.ts`.
- No LLM in the pet pipeline: no `anthropic` import in `pet_factory/` or `webui/` (grep-clean).
- Fleet-cutover discipline reused: `docs/SPEC_DEPLOY_PETDATSME_POOL.md` §B.1.
