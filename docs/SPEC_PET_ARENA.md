# SPEC_PET_ARENA — the Pet Games: a track-and-field meet for pets you built

**Status: Rev.6 (2026-08-02) — DRAFT FOR OWNER REVIEW; NOTHING BUILT.** No code, no
migration, no deploy. §0 records the owner's product direction and the decisions that follow from it;
§16 lists what still needs a call.

> ### Rev.6 — the pre-build review: losing is designed for; the handicap and the bot get definitions
>
> A full review of Rev.5 against the codebase (2026-08-02) confirmed the feasibility claims —
> `PetStage`'s pet list, the seven profiles, `CANONICAL_POSES`/`MAX_POSES`, the `JOBS` pattern and
> the nginx gaps are all where this document says. Four changes came out of it, none of which alters
> a game rule; the companion spec picked up four more (`SPEC_PET_ARENA_ROOMS.md` Rev.2).
>
> **1. Losing is designed for, in v1** (§8.8 new, decision 0.15). Per-event medals, personal-best
> framing and private practice against the bot sat in §16.2 as things that "belong in v1" — inside
> the open-questions section, which is where committed-sounding scope goes to get cut. Now committed
> and phased: the bot ships in Phase 2 (it is also the opponent that makes a solo race a race rather
> than a time trial), the rest with the Phase 3 results screen. Personal bests are device-local
> (`localStorage`), so §15's no-backend posture holds.
>
> **2. The handicap is specified** (§8.3.1 new). §8.3 promised mixed-age races "an explicit, visible
> handicap" and no revision defined one. It is a per-entrant stride multiplier from a closed ladder
> in `pet_factory/athletics/handicaps.json`, chosen at setup, shown wherever the entrant is, and
> recorded in the race header so replays reproduce. Siblings are the launch audience — the mixed-age
> race is the *first* race this game runs, not an edge case.
>
> **3. The bot rate is a ladder, not a number** (§7.3). `pet_factory/athletics/bots.json`, named
> rungs. Practice-vs-bot is plausibly the most-played mode; one seeded rate gives it no progression.
>
> **4. The race recap ships with the results screen** (§7.4, §12 Phase 3). The impulse log already
> *is* the replay; the "watch how you won" screen is nearly free, and it is the thing children show
> each other.

<details><summary>Rev.5 — coordination is an existing pose; the relay swaps pets under a continuous player</summary>

> The owner, on three points:
>
> > "For the coordination pose, you do not need a pose for that. We will use an existing pose to
> > represent it — for example playing, that is coordination, so we can say run + play as condition.
> > And for the relay concept, basically the pet will be changed automatically after the 1st leg, so
> > you may have a chicken, cheetah, dog, cat. After 100 metres the chicken will be switched to
> > cheetah. Cheetah has its own spec, but for the user he keeps typing the same way. So 5 people
> > (configurable 1–5) can play at the same time with their own devices, and you need to make a room
> > that allows for playing that is viewable by everyone. We may even turn that into a URL so
> > visitors can go to the URL and watch in real time."
>
> **1. No new poses. An event assigns meaning to an existing one.** `play` *represents* coordination;
> the pose vocabulary stays fixed content and the **event** decides what a pose stands for. This is
> better than authoring `dance`: it costs no GPU, strands no existing pet, and it means the launch
> catalogue (§6.4) is buildable today. Rev.4's `dance`/`bounce` examples are withdrawn.
>
> **2. The relay swaps the pet, not the player** (§6.5). Four pets run four legs; the player answers
> continuously and never touches a control. Each pet's stats change the exchange rate underneath
> them — the same effort produces different speed per leg. That is a genuinely good mechanic and it
> makes a mediocre pet in the house useful, because a team needs four.
>
> **A hole this exposed, and it is worth catching now:** with four equal legs the *total answers*
> required is `Σ Dᵢ/Sᵢ` — a permutation-invariant sum — so finish time is **order-independent**, and
> the four-pet team is a collection requirement with no strategy in it. **This survived the owner's
> challenge that human fatigue and random question difficulty would break it** (simulated: 0.002 s
> spread across all 24 orderings), and §6.5.1 records the analysis in full so it is not re-litigated.
> The owner's underlying instinct is right and is now **fix #3**: the end of a race *should* be
> harder — it just has to attach to the leg rather than to the player.
>
> **3. Five players, own devices, a shared room, a spectator URL** — this is the tripwire in §11
> firing, exactly as written: *"the moment results are shared, the simulation has to move
> server-side."* It is a different system (transport, sessions, public surfaces, child safety) with a
> different change cadence, so it gets **its own spec: `SPEC_PET_ARENA_ROOMS.md`**. Decision 0.7 and
> §11 now point at it. The game rules in this document are unchanged by it — a room feeds the same
> impulse stream (§7.1).

</details>

<details><summary>Rev.4 — the qualification is configured per event: pose combinations, alternatives, and teams</summary>

The owner, extending Rev.3:

"Currently we may only have 10 poses, but it will definitely increase. And we can do pose
combinations. For example, to do hurdles you may need to have run + (bounce or jump); to do a
relay 400 metres you will need to have 4 pets with run + dance (or another pose that represents
coordination). The point is that we can configure each event for the qualification."

Three things follow, and the first two are the same change:

**1. A requirement is a list of clauses, each clause a list of acceptable poses** (§6.3) —
`[["run"], ["jump", "bounce"]]` reads *"must have run, AND must have jump or bounce."* AND-of-ORs
covers every case the owner named, is pure data with no parser, and stays readable to whoever edits
the JSON. **Deliberately not a boolean expression language** (§6.3.1): no NOT, no nesting, no
precedence rules to get wrong.

**2. An event declares a team size** (§6.5). Relay 4×100 is `teamSize: 4`, every member satisfying
the requirement. This is the first event where an entrant is not one pet, and it is the reason the
entrant model is stated explicitly rather than assumed.

**3. The pose vocabulary is a growing list, and nothing may assume its size.** Rev.3 quoted "10
canonical poses, 5 athletic" as if it were a ceiling. It is **today's snapshot** (§10.2). Events
reference poses by name; the guard test validates those names against the **live**
`CANONICAL_POSES` rather than a copy, so a new pose needs no arena change and an event referencing
a not-yet-authored pose fails the build instead of shipping unenterable.

**The relay quietly answers the children's other request.** Fielding a 4×100 team means owning four
pets that each have `run` + a coordination pose. That is a *collection* mechanic — it is a reason to
want more slots (the original ask) and more poses (§10) at the same time, and it arrived without
anyone designing it that way.

**One naming note:** `bounce` and `dance` do not exist in `CANONICAL_POSES` today. They are examples
of the growth in point 3, not fields to add now — §15 keeps pose authoring out of this spec and
§10.2 records what adding one costs.


</details>

<details><summary>Rev.3 — one rule: the event requires a motion, the pet either has it or it does not</summary>

The owner, replacing Rev.2's medium-eligibility design:

> "Let's make the game easy. Each event will have a motion requirement. If the animal has that
> motion, it can compete in that sport. So that fish example — if that particular fish has a run
> motion, it can still compete in the 100 metre dash even though it is on land. For kids, they will
> think it pretty funny to see the fish compete in running. Also, this makes buying an animal with
> different motions more valuable. Currently we cap at 8 poses, but in the future we may sell
> premium animals with more than 8 poses. These premium animals can compete in more events as they
> have more poses."

**Eligibility is now one line: `event.requiresPose ∈ manifest.animations`.** No affinity gate, no
`null` semantics, no capability table, no derivation. It reads off the bundle the pet already
carries, per pet rather than per species — which is what makes the owner's *"if **that particular
fish** has a run motion"* work.

This is the third eligibility rule in three revisions, and it is the right one because it is the
only one that is also a **business mechanism**: poses are already the thing users pay for
(`tiers.json`, 50 credits per pose beyond walk+idle), so **the pose you buy is the event you
unlock**. §10 is rewritten around that, with the numbers.

What changes: §0.5, §2.2 (affinities become performance-only — a fish may run, it is just terrible
at it, which is the joke), §6.3 (rewritten), §6.4 (every event declares its required motion), §10
(rewritten as the monetization lever), and the guard tests.

**Three findings that fell out of measuring it** (§6.3, §10.2):

- **`walk` is a required pose on every pet ever built** (`motion_profiles/__init__.py:44`), so the
  **racewalk is a universal event** — a real Olympic sport, and the guarantee that no child's pet is
  ever locked out of everything.
- **Only 5 of the 10 canonical poses are athletic** (`walk, run, jump, swim, fly`), and a pet can
  only own poses its *body type's profile* enables. **A dog tops out at 3** (walk/run/jump) no matter
  what is spent — the premium ceiling is the profile, not the tier (§10.3).
- **The cheapest premium content in the codebase is one line of JSON:** `quadruped.json` has
  `swim: off`. Dogs swim. Turning it on opens the entire swimming category to every quadruped and
  costs no GPU and no code (§10.4).

</details>

<details><summary>Rev.2 — the player is the engine (kept; only its eligibility rule was replaced)</summary>

A request from the **parents**: the children play too much and need to study, maths especially. The
owner's answer reframed the game rather than bolting a lesson onto it — *"if they get it right, it
moves the frame by 1… so a very fast person who can solve math problems can still beat another
user's animal who is naturally faster but can't do math."*

**Rev.2's contributions, all still current:** the pet advances one step per challenge solved (§7);
the impulse stream replacing Rev.1's simulate-then-animate, which could not survive live player input
(§7.1); automatic mode as a bot on the same stream (§7.3); determinism as replay-from-impulse-log
(§7.4); and the challenge registry (§8).

**Superseded:** Rev.2's eligibility rule (medium capability, `null` affinity = ineligible), replaced
by Rev.3's motion requirement. Rev.2 had ruled that a fish may never run; Rev.3 says it may, if it
owns the pose, and that this is funny.

</details>

<details><summary>Rev.1 — the meet (superseded in two sections)</summary>

Rev.1 specified the meet, the stat model, the manifest block and the event registry, all of which
stand unchanged. Its simulate-then-animate model was deleted by Rev.2; its "every pet may enter every
event" rule was narrowed by Rev.2 and then re-widened — on a different mechanism — by Rev.3.

</details>

**Where this came from.** The owner's nieces and nephews used the designer, loved it, and asked for
two things: more slots, and *"can they compete with each other."* The owner's shape for it:

> "Track and field or maybe even Olympic style, in which we can [have] different events. We can start
> with the simplest first such as running (100 yards, 200), then we can do high jump, then long
> jump… so different animals with different specs will perform differently. How funny would it be to
> see a dog, cat and bird compete in skiing or pole vault. Or maybe even swimming… Maybe these stats
> can be created at build time and put in the manifest, and certain things can be random to provide
> uniqueness to the animal."

That last sentence is the architecture, and this spec follows it.

**The headline feasibility finding: the multi-pet arena already exists and is in production.**
`PetStage` (`web/src/components/PetStage.tsx`) takes a *list* of pets, mounts one `PetCanvas` each on
a **shared stage**, and drives them all from one set of engine hooks. `/house` renders a page of pets
on it today (`web/src/app/house/page.tsx:550`). What is missing is not the stage — it is stats, rules,
and a driver.

**The second finding: seven body types already exist, with distinct pose sets** (§1.3). A dog, a
bird and a fish are already mechanically different animals in this codebase. The comedy the owner
wants is sitting in data that shipped months ago.

---

## §0 The decisions

| # | Decision | Choice |
|---|---|---|
| 0.1 | Format | **Olympic-style meet: many small events, not one game.** Ship one event, then add events one file at a time (§6). |
| 0.2 | First events | **100 m sprint**, then **200 m**, then **long jump**, then **high jump**. Skiing / pole vault / swimming follow the same registry (§6.4). |
| 0.3 | Where stats come from | **Minted at BUILD TIME and written into `manifest.json`** as an `athletics` block (owner's instruction, §4). |
| 0.4 | Uniqueness | **Two different randomnesses, deliberately separated** (§7.5): a per-pet roll minted once and permanent, and a per-race roll that makes each running of an event different. |
| 0.5 | Who may enter what | **Each event configures its own qualification** (§6.3): a list of clauses, each a list of acceptable poses — `run` AND (`jump` OR `play`). Per pet, read off `manifest.animations`. A fish that owns `run` may enter the 100 m, and being terrible at it is the joke. |
| 0.5a | How many pets is an entrant | **`teamSize`, declared per event** (§6.5). Singles are a team of one, so nothing branches on solo-vs-team. |
| 0.5b | The pose vocabulary | **Expected to grow.** Events name poses as strings and the guard test reads the live list, so a new pose needs no arena change (§6.3.2). |
| 0.6 | Module boundary | **A separate module in every layer.** New content package, new backend module, new frontend directory. The pet runtime is *used*, not modified (§9). |
| 0.7 | Backend surface | **None for solo and hot-seat play.** Multi-device rooms and the spectator URL are a server concern and live in **`SPEC_PET_ARENA_ROOMS.md`** (§11). Records/leaderboards remain deferred (§15). |
| 0.8 | Legacy pets | **Every pet ever built can compete on day one**, via a read-time derivation from facts already in its manifest (§5). |
| 0.9 | **How the pet moves** | **The player moves it.** One solved challenge = one step. Pet stats are the exchange rate, player rate is the tempo, velocity is the product (§7). |
| 0.10 | What counts as a challenge | **A registry, orthogonal to events** — tap, arithmetic, typing, spelling. Any challenge can drive any event (§8). |
| 0.11 | Automatic mode | **Kept, as a bot filling the same impulse stream** (§7.3). The event never learns whether a human or a simulation is playing. |
| 0.12 | Who the customer is | **The parents, as much as the children.** Player skill must visibly dominate pet stats, or the maths is decoration (§8.4). |
| 0.13 | Poses are the product | **The pose you buy is the event you unlock** (§10). Eligibility is deliberately the same mechanism as monetization, not a separate one bolted alongside it. |
| 0.15 | Losing | **Designed for in v1, not patched after the first sulk** (§8.8, Rev.6): per-event medals, personal-best framing, private practice vs the bot, the race recap. (0.14 is the posture section below; the number is skipped, not missing.) |

### 0.14 The posture that must not change

1. **No event logic in the engine.** Adding an event is one file plus one registry entry, and it
   must not modify the simulator, the stat model, or any other event — the repo-wide plugin rule.
2. **No species names in code.** Stats derive from declared data (`movement_class`, the pose set, the
   design block), never from `if species == "cheetah"`. Same rule the motion system already lives
   under.
3. **The pet runtime is a dependency, not a fork** (§9.2). The arena adds a second *driver* over the
   existing primitives; it does not edit `petStore.ts`, `useAnimationLoop.ts` or any strategy file.
4. **The GPU-less posture.** The new content package is pure data; the new `webui/` module is stdlib.

---

## §1 What already exists (the feasibility evidence)

### 1.1 The stage is built and shipping

| Capability | Where | State |
|---|---|---|
| Many pets, one stage | `web/src/components/PetStage.tsx` — takes `pets: StagePet[]`, one `PetCanvas` per pet on a shared `stageRef`, spaced `80 + i * 150` | **in production on `/house`** |
| Per-pet state | `petStore.pets: Map<string, PetState>` (`web/src/pet/petStore.ts:130`) — position, facing, animation, target, per pet | built |
| Per-frame motion | `strategy.tick(pet, dtMs)` integrates position; `applyTransform` composes translate → rotate → scaleX (`petStore.ts:378`) | built |
| Sprite frame advance | `setBgPos(pet, petEl, linearIdx)` (`petStore.ts:351`) | built |
| Animation switching | `setAnim(pet, name)` (`petStore.ts:305`) | built |
| Loading a pet by id | `PetStage` fetches sheet + manifest from `petSheetUrl` / `petManifestUrl` and calls `ensurePet` | built |

**"Import up to 5 or 10 pets into an arena" is a list of pet ids passed to a component that already
does this.**

### 1.2 The driver is already separable from the loop

This is the detail that makes the arena cheap. Ambient life and frame advance are **different hooks**:

- `useAnimationLoop` — the page-level rAF ticker. Advances frames, calls the strategy's motion
  integration, clamps to `pickableArea`.
- `useAutoStateMachine` — the *ambient* driver, and the only thing that decides where a pet goes
  (`inst.targetX = target.x`, `setAnim(pet, next)`).

`PetStage` mounts them explicitly and separately. **A race is a third driver: mount the frame
primitives, do not mount the ambient state machine, and pace the pets from the event's own
simulation.** Nothing about ambient behaviour needs to change or be disabled by a flag.

### 1.3 Seven body types, already mechanically distinct

`pet_factory/motion_profiles/registry.json` declares seven profiles, each with its own
`movement_class` and its own enabled pose set:

| profile | `movement_class` | poses enabled today |
|---|---|---|
| quadruped | `mammalian_quadruped` | walk, idle, run, sleep, sit, eat, jump, play |
| avian | `avian_biped` | …+ **fly** |
| winged_flyer | `winged_flyer` | …+ **fly** |
| humanoid | `humanoid_biped` | …+ **fly** |
| primate | `primate_walker` | walk, idle, run, sleep, sit, eat, jump, play |
| aquatic | `aquatic_swimmer` | walk, idle, run, sleep, eat, play, **swim** — **no jump** |
| serpentine | `limbless_serpentine` | walk, idle, run, sleep, sit, eat, **swim** — **no jump, no play** |

Read that table as an athletics chart and it already is one. A fish cannot jump. A snake cannot
jump. Birds, dragons and superheroes fly. This is not data that needs inventing — it needs reading.

### 1.4 One wrinkle found, and it is not about the arena

`web/src/pet/index.ts` says the engine files are *"copied verbatim from `datsme_me/web/src/pet`"*.
**They are not, any more.** Measured on 2026-08-02:

| file | vs. the host copy |
|---|---|
| `personality.ts` | identical |
| `locomotion/quadruped.ts` | identical in content |
| `petStore.ts` | **331 changed lines** |
| `useAnimationLoop.ts` | **285 changed lines** |

That drift is worth a separate look — it is not this spec's problem to fix, and the direction of the
drift has not been established. It is recorded here because it **strengthens §9.2**: the arena must
not add to it, whichever way it went.

---

## §2 The stat model

Six numbers per pet. Small enough for a child to read on a card, orthogonal enough that events can
weight them differently.

### 2.1 Three attributes

| attribute | means | the event that needs it |
|---|---|---|
| `speed` | top velocity | 100 m |
| `power` | explosive force | long jump, high jump, pole vault |
| `endurance` | how well speed holds up over distance | 200 m and anything longer |

### 2.2 Three medium affinities

| affinity | means |
|---|---|
| `land` | on the ground |
| `water` | in it |
| `air` | above it — flight, and by extension anything airborne like ski jump |

An event declares its medium; the pet's affinity for that medium **multiplies its performance and
never gates entry** (§6.3). A fish that owns the `run` pose enters the 100 m with a fine `speed` and
a terrible `land` affinity, and flops down the track behind everyone — which is the entire point.

**Rev.3 removed the `null` = ineligible semantics.** Every cell is now a plain number in `0.0–1.0`,
because eligibility moved to the motion requirement. That is one less rule, one less special value,
and one less guard test.

### 2.3 From six numbers to one stride — the formula

**This was missing from Rev.1–5 and is the one thing nothing else can be built without**: §7.1 uses
`stride(pet, event)` as the exchange rate and no revision ever defined it. Written out here.

```
score   = Σ (event.weights[a] × pet[a])        for a in {speed, power, endurance}   → 0..1
score  ×= pet.affinity[event.medium]                                                → 0..1
stride  = STRIDE_BASE_M × ATHLETIC_STRIDE_SPREAD ^ (2 × score − 1)
```

**Why the exponential rather than a linear interpolation.** `ATHLETIC_STRIDE_SPREAD` is defined in
§8.4 as *a ratio* — best pet ÷ worst pet. The exponent maps `score = 0 → spread^-1`,
`score = 0.5 → 1.0`, `score = 1 → spread^+1`, so the best pet is exactly `spread²`… which is not what
§8.4 says. **Use `spread ^ (score − 0.5)`** instead, giving best ÷ worst = `spread` exactly, a
mid-pet of 1.0, and a knob whose name matches its behaviour. That correction is the kind of thing
that would otherwise be discovered by a confused implementer:

```
stride = STRIDE_BASE_M × ATHLETIC_STRIDE_SPREAD ^ (score − 0.5)
```

At the recommended `spread = 1.6`, the best pet covers 1.6× the ground per answer that the worst
does — so a child answering 1.6× faster exactly cancels the worst possible pet matchup, which is
§8.4's whole intent stated as an equation.

`STRIDE_BASE_M` is the tuning constant that sets how long a race *feels*: metres per correct answer
for an average pet. At `STRIDE_BASE_M = 2.0`, a 100 m sprint is ~50 answers for a mid pet — call it
40 seconds of brisk arithmetic. **That number, not the spread, is what makes a race the right
length**, and it is the first thing to tune on the sofa.

### 2.4 Endurance, and what makes 200 m different from two 100 m races

`endurance` is inert unless something decays. The decay is declared per event, so a sprint can ignore
it entirely:

```
effective_stride(x) = stride × (1 − event.decay × (x / event.distance) × (1 − pet.endurance))
```

At `decay = 0` (the 100 m) endurance does nothing. At `decay = 0.35` (the 200 m) a pet with
`endurance = 0` finishes at 65% stride while a pet with `endurance = 1` never slows. **This is what
makes the 200 m a different event rather than a longer one**, and it is why §6.4 orders it second.

Note it decays with **distance covered**, not elapsed time — otherwise a slow player would fatigue
the *pet*, which is the player's job, not the pet's (§6.5.1).

### 2.5 Why six and not more

`agility` is the obvious fourth attribute and it is **deliberately not in v1**: none of the four
launch events (§0.2) reads it, and CLAUDE.md's rule is not to build an abstraction before three
concrete instances vary. **Tripwire:** the first event whose ranking cannot be expressed as a
weighting of `speed`/`power`/`endurance` — hurdles and slalom are the likely first — is when
`agility` is added. Adding an attribute is one entry in the vocabulary file plus a re-mint (§5.3),
not a schema change.

Values are `0.0–1.0`, normalized. A displayed "stat bar" is a read-time presentation concern.

---

## §3 Where the numbers come from

Four inputs, applied in order. Every one is **declared data the pet already carries** — no new user
input, no new step in the designer.

### 3.1 Base — the `movement_class`

`pet_factory/athletics/movement_classes.json` maps each of the seven declared classes to a base
six-tuple. This is the single biggest determinant and it is one flat table an admin can tune:

```json
"aquatic_swimmer": {
  "speed": 0.55, "power": 0.30, "endurance": 0.70,
  "land":  0.15, "water": 1.00, "air": 0.05,
  "_note": "Dominant in the pool, comic on the track. The comedy is the design (§0.5)."
}
```

An unknown class falls back to the registry default (`quadruped`) — the never-raises posture
`resolve_motion_profile` already uses.

### 3.2 Modifiers — the design axes

The `design` block from SPEC_PET_DESIGN_PROVENANCE carries the axis picks. `athletics/modifiers.json`
maps `{axis, option}` → attribute deltas:

```json
"body": { "fat": { "speed": -0.15, "power": +0.15 },
          "lean": { "speed": +0.15, "power": -0.10 } }
```

**This is the part that answers what the kids actually asked for.** Their words were *"put the pet
together and see how they perform"* — they want the design to *mean* something. A chubby corgi being
slower and stronger than a lean one is that, and it costs one JSON file because the provenance work
put the picks where this can read them.

An axis with no entry contributes nothing, so adding a design axis never breaks athletics, and
adding an athletic modifier for an existing axis is a one-line edit.

### 3.3 Capability — the pose set

`manifest["animations"]` names the poses the pet actually has, and in Rev.3 it does **two different
jobs that must not be confused**:

- **Eligibility** (§6.3) — the event's required pose is present, or the pet cannot enter. A hard
  yes/no, read per pet.
- **Performance** (here) — among the poses it *does* own, owning the *right* one matters. A pet
  entering the 100 m on `run` is driven at its full `speed`; the affinity for the event's medium
  multiplies on top, which is why a fish that owns `run` may enter and still flops.

The first is a gate and lives in the event registry. The second is a multiplier and lives in the stat
table. Putting eligibility in the stat table is what Rev.2 did, and it made a simple question
(*"does it have a run animation?"*) into a derivation.

`animations` also names the sprite the arena plays back (§7.6) — the same field, a third use, and
the reason it is the one input this design leans on hardest.

### 3.4 The per-pet roll — uniqueness

A bounded random modifier, **minted once at build and never re-rolled** (§7.5). Its range lives in
`athletics/roll.json` as a named constant (default `±0.08`) — wide enough that two identical designs
are distinguishable, narrow enough that design still dominates. This is the owner's *"certain things
can be random to provide uniqueness to the animal."*

---

## §4 The manifest block, and where it is written

### 4.1 The block

```json
"athletics": {
  "schema_version": "pet_athletics.v1",
  "table_version": "athletics.v1",
  "speed": 0.71, "power": 0.42, "endurance": 0.63,
  "land": 0.95, "water": 0.30, "air": 0.05,
  "roll": 0.031,
  "poses": ["walk", "idle", "run", "jump"],
  "minted_at": "2026-08-02T11:04:19Z"
}
```

`roll` is stored **as its own field as well as being folded into the attributes**, so a re-mint under
a new balance table (§5.3) can reproduce the pet's identity instead of re-rolling it. Losing that
would mean every balance patch silently gives every pet a new personality.

`table_version` is what makes a re-mint detectable and a mixed field diagnosable.

### 4.2 Where it is written — the provenance mechanism, reused exactly

`_finalize_pet_from_zip` (`webui/app.py:605`) already patches `manifest.json` twice
(`webui/app.py:623-628`), and SPEC_PET_DESIGN_PROVENANCE §3.4 adds a third. **The athletics block is
a fourth patch at the same seam**, using the same `patch_bundle_manifest` helper that spec extracts,
and for the same reasons:

- upstream of `insert_pet`, so the derived `bundle_sha256` covers the stamped bytes;
- both backends and the pool-reattach path converge there;
- **the packer is untouched**, so `pack_datsme_bundle` stays free of game rules and
  `pet_factory/tests/test_pack_bundle_layout.py` needs no change.

**Not in the packer**, for the same ruling SPEC_PET_OWNER_FIELD §2.4 made and
SPEC_PET_DESIGN_PROVENANCE §7 restated: the packer runs on pool GPU nodes, cannot see the design
inputs, and game balance must not require a fleet roll to change.

**Dependency, stated plainly:** the design-modifier input (§3.2) needs the `design` block, so
athletics-with-modifiers ships **after** SPEC_PET_DESIGN_PROVENANCE Phase 2. Without it, §3.1, §3.3
and §3.4 still work and modifiers are simply inert — so the arena is not blocked, it is just less
interesting. §12 sequences this.

---

## §5 Legacy pets — the arena works on day one

Unlike design provenance, **athletics is fully derivable after the fact.** Every manifest ever
written by this repo already carries `movement_class` and `animations`
(`pet_factory/factory.py:940`), which are §3.1 and §3.3 — the two largest inputs.

### 5.1 The resolver

One function, in the shared content package, with a strict precedence:

1. `manifest["athletics"]` present and `schema_version` known → **use it verbatim.**
2. Absent → **derive** from `movement_class` + `animations`, with modifiers skipped (no design block)
   and the roll derived per §5.2.

The arena calls only the resolver. **Nothing in the game ever branches on whether a pet was minted
with a block** — that would be a provenance branch, which §0.14 forbids.

### 5.2 A stable roll for a pet that never got one

The roll must be *stable* (the same pet is the same athlete every time) without being *stored*.
Derive it from a hash of the pet's own sprite sheet bytes, which the arena has already fetched to
render it, folded into the roll range. Same pet → same bytes → same roll, forever, with nothing
persisted.

Two properties worth stating: it is stable across devices and reloads, and it is **not** stable
across a rebuild of the same design — which is correct, because that is a different pet.

### 5.3 Re-minting when the balance table changes

Balance will be wrong at first. A `table_version` bump means stored blocks are stale, and the rule
is: **the resolver recomputes from `table_version` mismatch rather than trusting a stale block**,
reusing the stored `roll` so identity survives (§4.1). No migration, no GPU, no re-download — the
inputs are all still in the manifest.

This is why §4.1 stores the raw inputs and the roll rather than only the final six numbers.

---

## §6 Events

### 6.1 One event = one file + one registry entry

`web/src/arena/events/`, mirroring `web/src/pet/locomotion/registry.ts` and
`pet_factory/motion_profiles/` — the pattern this repo uses everywhere a variant list grows:

```ts
export const sprint100: ArenaEvent = {
  key: "sprint_100",
  label: "100 m Sprint",
  medium: "land",
  weights: { speed: 0.80, power: 0.15, endurance: 0.05 },
  preferredPoses: ["run", "walk"],   // best one the pet owns
  simulate(entrants, rng) { /* → ordered results + per-entrant timeline */ },
};
```

The registry is `{ [key]: ArenaEvent }` with a guard test that fails the build on a half-formed
entry — the enforcement rule every registry in this repo carries.

**Seven concrete events are already named by the owner** (§0.2 plus skiing, pole vault, swimming), so
the registry is earned rather than speculative — CLAUDE.md's three-instances bar, cleared twice over.

### 6.1a The split that makes a room possible — declaration is DATA, procedure is code

**Found in the Rev.5 readiness review, and it is the one gap that would have surfaced on day three of
building rooms.** Rev.1–5 put events in `web/src/arena/events/` as TypeScript objects with a
`simulate()` method. But `SPEC_PET_ARENA_ROOMS.md` §3.4 makes **the server** authoritative for the
result — and the server is Python. As written, the room server cannot score a race without a second
implementation of every event.

The fix is the pattern this repo already uses for `motion_profiles`, `design_axes` and `tiers`:
**split the declaration from the procedure.**

| | lives in | language | who reads it |
|---|---|---|---|
| **declaration** — `requires`, `weights`, `medium`, `distance`, `legs`, `teamSize`, `decay`, `handover`, `preferredPoses` | `pet_factory/athletics/events/*.json` + `registry.json` | **data** | Python (server, build-time, tests) **and** TypeScript (client) |
| **procedure** — how a result is produced from an impulse log | one integrator per side | code | each side, once |

**Most events need no procedure at all.** Racewalk, 100 m, 200 m, relay, freestyle and downhill are
all *"integrate stride until the distance is covered"* — one generic integrator, parameterised by the
declaration. Those are **Tier 1**, and a Tier-1 event is a JSON file and nothing else.

**Jumps are genuinely procedural** — best-of-three attempts, elimination at rising heights — and stay
**Tier 2**: a declaration plus a small code module, written twice if a room ever hosts one.

Three consequences, all good:

- **Adding a Tier-1 event stays a one-file change** and now works in rooms for free.
- **Rooms launch Tier 1 only** (`SPEC_PET_ARENA_ROOMS.md` §11 R2), where the server can be
  authoritative with one integrator. Jumps stay solo/hot-seat until someone wants them networked.
- **The two integrators are kept honest by a shared fixture**, the SPEC_PET_OWNER_FIELD §2.3a
  pattern: DatsPet owns `pet_factory/athletics/tests/fixtures/race_vectors.json` — impulse log in,
  result out — and both sides run it. Two implementations that drift are otherwise indistinguishable
  from a cheating child.

**Tripwire:** the first Tier-1 event that wants "just a little" custom logic. That is how a data
format becomes a scripting language. Add the parameter to the declaration, or promote the event to
Tier 2 honestly.

### 6.2 What an event owns, and what it must not

| an event declares | an event must never |
|---|---|
| its medium and attribute weights | name a species or a `movement_class` |
| which poses it prefers to animate | read another event's state |
| its own simulation and result shape | modify the pet runtime |
| its own scoring unit (seconds, metres) | require a change to the stat vocabulary |

The last one is the real constraint: **if a new event cannot be expressed in the existing
vocabulary, that is the signal to extend the vocabulary deliberately (§2.3), not to special-case the
event.**

### 6.3 Qualification — configured per event, as data

Every event declares a `requires`: **a list of clauses, each clause a list of acceptable poses.**
All clauses must be satisfied; any one pose within a clause satisfies it.

```json
"requires": [["run"]]                        // 100 m — has run
"requires": [["run"], ["jump", "play"]]      // hurdles — run AND (jump OR play)
"requires": [["run"], ["play"]]              // relay leg — run AND a coordination pose
"requires": [["walk"]]                       // racewalk — every pet alive
```

```ts
qualifies = event.requires.every(clause => clause.some(pose => pose in manifest.animations))
```

Per **pet**, read off the bundle it already carries — which is what makes the owner's *"if **that
particular fish** has a run motion"* work. Two fish can differ.

| | 100 m — `[["run"]]` | |
|---|---|---|
| a dog that bought `run` | **yes** | the expected case |
| a dog that did not | **no** | the racewalk is waiting |
| a **fish** that bought `run` | **yes** | flops down the track in last place. This is the joke, and children will love it |
| a fish that did not | **no** | its pool events are waiting |

### 6.3.1 AND-of-ORs, and deliberately nothing more

The form is conjunctive normal form and it stops there. **No NOT, no nesting, no precedence.**

Every case the owner named — a single pose, two required poses, a choice between equivalents — is one
clause list. A boolean expression language would need a parser, an evaluation order, and a way to
express something nobody has asked for; and the moment an event's qualification is not readable at a
glance by whoever is balancing the game, the game stops being balanced.

**Tripwire:** the first event whose qualification genuinely needs a NOT ("anything except a flyer") or
a nested group. Reach for a second field before reaching for an expression language — an
`excludes: [...]` list would cover the NOT case and stay data.

### 6.3.2 The pose vocabulary grows; the arena must not care

Poses are referenced **by name, as strings**. When a new pose is authored, an event can require it
with no arena change at all.

The guard test reads the **live** `motion_profiles.CANONICAL_POSES` rather than a copy (§14), so:

- a new pose is usable the moment it exists;
- an event referencing a pose that does **not** exist fails the build, rather than shipping an event
  no pet on earth can enter — which would be invisible until a child asked why the hurdles are always
  greyed out.

**An event assigns meaning to a pose; it does not need one minted for it** (Rev.5). `play` *represents*
coordination in the relay — the pose vocabulary is fixed content and the event decides what a pose
stands for. That is why the entire launch catalogue (§6.4) is buildable from poses that exist today,
and why no event in it blocks on a GPU session. Reach for a new pose only when no existing one can
plausibly stand in.

### 6.3.3 The universal event, and how a locked event is presented

**`walk` is required on every pet ever built** (`pet_factory/motion_profiles/__init__.py:44`), so an
event requiring only `walk` — the **racewalk**, a real Olympic sport — is enterable by every pet in
existence including every legacy one. That is the floor, and it is deliberate: **no child's pet is
ever locked out of everything.**

Three presentation rules, because a gate a child does not understand is just a wall:

1. **Show locked events, never hide them.** A greyed hurdles with *"needs Run, and Jump or Bounce"*
   teaches what poses are for. A hidden one teaches nothing.
2. **Name every unsatisfied clause**, and — since poses are purchasable — link to where they are
   bought. With alternatives, name them all: *"needs Jump **or** Bounce"* is a cheaper-looking ask
   than either alone.
3. **Never show a pet with zero entries.** The racewalk guarantees this structurally; a guard test
   pins it (§14).

### 6.4 The event catalogue, and what each one requires

Many events share one pose, which is what makes a deep catalogue affordable. The `requires` column is
the §6.3 clause form.

| order | event | `requires` | team | why it is next |
|---|---|---|---|---|
| 0 | **racewalk** | `[["walk"]]` | 1 | **the universal event.** Every pet ever built qualifies (§6.3.3). Ships alongside the 100 m so no pet is ever empty-handed. |
| 1 | 100 m sprint | `[["run"]]` | 1 | one attribute dominates, one clause. The whole pipeline proven end to end on the simplest rules. |
| 2 | 200 m | `[["run"]]` | 1 | adds `endurance` and a decay curve. **Costs no new pose** — the catalogue-depth proof. |
| 3 | long jump | `[["jump"]]` | 1 | adds `power` and a best-of-three attempts structure. |
| 4 | high jump | `[["jump"]]` | 1 | elimination at rising heights — a different result shape from a time or a distance, which proves the event interface is general. |
| later | hurdles | `[["run"], ["jump","play"]]` | 1 | **the first multi-clause event**, and the first with alternatives — both from poses that exist today. |
| later | medley relay | `[["run"], ["play"]]` | **4** | **the first team event** (§6.5). Legs `[100,200,100,400]` — unequal on purpose, so pet order is a decision (§6.5.1). |
| later | 100 m freestyle | `[["swim"]]` | 1 | the first event a fish wins, and the first that makes `water` affinity pay. |
| later | pole vault | `[["jump"]]` | 1 | |
| later | air race | `[["fly"]]` | 1 | birds, dragons and flying superheroes only. |
| later | downhill ski | `[["run"]]` | 1 | the ski is a prop; the motion is the same. **A whole category on a pose everyone already owns.** |

**What this table is designed to show.** Events 1 and 2 share `run`; 3 and 4 share `jump`; downhill
reuses `run` again — **the catalogue grows faster than the pose vocabulary**, which is what keeps
content cheap. And the `requires` column is a purchase prompt: a child looking at locked hurdles is
looking at a reason to buy `jump`.

### 6.5 Team events — the pet changes, the player does not

Relay makes an entrant a **team**: an ordered list of pets of length `event.teamSize`. Singles are
`teamSize: 1` — a list of one, not a special case, so nothing branches on solo-vs-team. Every member
qualifies independently (§6.3); a team is not a way to carry a pet that lacks the pose.

**The swap is automatic and invisible to the player.** The owner's shape: *"you may have a chicken,
cheetah, dog, cat. After 100 metres the chicken will be switched to cheetah… but for the user he
keeps typing the same way."* At each leg boundary the active pet changes; the player's challenge
never pauses and no control is touched.

That is the mechanic, and it is a good one: **the exchange rate changes underneath a constant
effort.** The same answering rate produces a crawl behind the chicken and a surge behind the cheetah,
which is visible, legible and funny. It also gives a mediocre pet a job — a team needs four, so the
fourth-best pet in the house is suddenly worth owning.

Implementation is small because §7 already isolates it: a leg is a race, the impulse stream does not
change, and the handover is the event advancing its active-member index. `setAnim` and the sheet swap
are the same primitives the arena already uses for playback (§7.6).

### 6.5.1 Order-independence — the analysis, because it is counter-intuitive

**Recorded in full because the conclusion is surprising, the owner reasonably challenged it, and it
would otherwise be re-litigated every time somebody looks at the relay.**

#### The invariant

With equal legs, whatever order the pets run in, the player must supply **the same total number of
correct answers**:

```
answers for leg i = Dᵢ / Sᵢ          total = Σᵢ Dᵢ / Sᵢ      ← a sum: permutation-invariant
```

Finish time is a monotonic function of *cumulative answers supplied*, so **any player effect that
depends on elapsed time or on answers-given cancels out.** It changes when the total is reached —
identically for every ordering.

#### The owner's objection, and why it does not break it

> *"You forget the human aspect. A user may tire out near the end, so his typing will be slower… also
> the question may be random, so that randomness also makes the user type more or less right
> answers."*

Both premises are **true** — no child answers at a constant rate for several minutes, and random
question difficulty does make the instantaneous rate lumpy. Neither breaks the invariant, because
both are functions of *time* or *luck*, not of *which pet is currently running*. Simulated over all
24 orderings of a chicken (0.6), cheetah (2.4), dog (1.3) and cat (1.0) with an exponential fatigue
curve and ±60% random question difficulty:

| player model | spread across all 24 orderings |
|---|---|
| constant rate | **0.000 s** |
| exponential fatigue | **0.002 s** |
| fatigue + random difficulty | **0.001 s** |

(Milliseconds; that is integration error, not an effect.) Worked by hand: chicken (needs 10 answers)
then cheetah (needs 5) at 1/s falling to 0.5/s finishes at t=20; cheetah then chicken finishes at
t=20. The slow pet costs the same answers wherever it runs — fatigue just decides how long those
answers take, and it charges every ordering the same.

**The one human effect that WOULD break it** is effort responding to *what is on screen* — a child
pushing harder while the cheetah flies, slumping behind the chicken. That is real, and it is
deliberately not a design foundation: it is unmodelable, unreliable, and reverses between children.
A team's strategy must not rest on how a particular child feels about a particular sprite.

#### The fix, and it is the owner's instinct in the right place

The intuition — *"the end of a race is harder"* — is right. It just has to attach to the **leg**
rather than to the **player**, because a player effect applies equally to every ordering while a leg
effect does not. Three asymmetries, all measured against the same simulation:

| | mechanism | measured spread | recommend |
|---|---|---|---|
| **1. Medley — unequal legs** | `legs: [100, 200, 100, 400]`; total becomes `Σ Dᵢ/Sᵢ` with `Dᵢ` paired to `Sᵢ` — the rearrangement inequality | **663 s** | **yes** — the strongest, and the medley relay is a real event |
| **2. Pair-dependent handover** | each exchange costs time, reduced by the outgoing and incoming pets' coordination; depends on *adjacent pairs* | **3.9 s** | **yes** — small, but it is what makes the `play` requirement mean something |
| **3. Per-leg-position modifier** | later legs run at a declining multiplier (`[1.0, 0.95, 0.90, 0.82]`) — "the anchor leg is the hard one" | **48 s** | **yes** — this is the owner's fatigue idea, correctly located |

All three are the same trick: make the total something other than a permutation-invariant sum. With
all three the best order is a real puzzle — put the strongest pet where the distance is longest and
the multiplier is worst, and mind who you hand over to.

**Why #3 is worth having even though #1 is bigger:** it is the one a child can *explain*. "The last
leg is the hardest, so your best runner goes last" is how relay strategy is actually talked about,
and it makes the anchor leg feel like the anchor leg.

### 6.5.2 Consequences worth pricing

- **Stage crowding.** Six teams of four is twenty-four pets. `PetStage` will mount them; a phone will
  not read them. Team events run **one leg at a time**, so the track holds `teamSize`-many runners
  regardless of field size — which is also how a relay looks on television. §16.4 carries it.
- **A collection mechanic that lands on the original request.** Fielding a team means owning four
  pets that each have `run` + `play`. That is a reason to want more slots — what the children asked
  for in the first place — and more poses (§10) at once. Nobody designed that; it fell out.
- **Hot-seat handover is free.** *"Leg two — your turn"* is a built-in reason to pass a device. Whether
  a relay is one child driving four legs or four children driving one each is a **setup choice**, not
  two code paths — the event consumes an impulse stream and never asks who fills it (§7.3).

---

## §7 The race loop — the impulse stream

### 7.1 One contract, three parties that never meet

```
   CHALLENGE  ──impulse──▶  EVENT  ◀──exchange rate──  PET
   "2 × 3 = ?"              100 m                      stats (§2)
```

- A **challenge** emits an `Impulse { at: ms, quality: 0..1 }` each time the player succeeds. It
  knows nothing about pets, events, tracks or distance.

  **`quality` is 1.0 for a correct answer and the impulse is not emitted at all for a wrong one.**
  Stated because Rev.2–5 left it undefined. Two temptations, both declined: scaling `quality` by
  question difficulty would mean a child on the hard ladder outruns one on the easy ladder for the
  same effort, which breaks §8.3's fairness rule the moment two siblings pick different levels; and
  partial credit turns "did you know it" into a judgement call. A challenge that genuinely wants
  graded output — a typing speed test, say — may emit `< 1.0`, which is why the field is a float and
  not a boolean.
- The **pet's stats** are the exchange rate: `distance = quality × stride(pet, event)`.
- The **event** integrates distance over time and decides the result. It knows nothing about
  arithmetic, typing or tapping.

Neither side can name the other. That is what makes "add a new challenge" and "add a new event"
independent one-file changes, and it is the whole reason the two are separate registries rather than
a combined list of game modes (§8.1).

**Velocity is the product of two rates:**

```
velocity = (answers per second)  ×  (distance per answer)
             the player                the pet
```

A child who answers twice as fast doubles their speed. A pet with twice the stride doubles it too.
**Both matter, multiplicatively** — which is exactly the owner's *"a very fast person who can solve
math problems can still beat another user's animal who is naturally faster but can't do math."*

### 7.2 Wrong answers cost time, never distance

A wrong answer produces no impulse and a brief input lockout. **The pet never moves backwards.**

Two reasons, and the second is the one that matters: a runaway-loser dynamic (fall behind → panic →
more mistakes → fall further behind) is miserable at any age and unbearable at eight; and a time cost
is already a sufficient penalty, because every second not answering is a second the opponent is.

### 7.3 Automatic mode is a bot on the same stream

The owner asked to keep the non-interactive mode as an option. It is not a second code path: a
**bot fills the impulse stream** at a seeded rate, and the event cannot tell the difference.

This is the engine-vs-content rule applied to the player: the event never asks *where an impulse came
from*. It also buys three things for free — a practice mode, an opponent when nobody else is around,
and a way to test every event without a human in the loop.

**The bot's rate is a declared ladder, not one number** (Rev.6): `pet_factory/athletics/bots.json`,
named rungs (`gentle` / `steady` / `brisk`, answers-per-second each), chosen at race setup the same
way challenge difficulty is (§8.7). Practice-vs-bot is plausibly the most-played mode (§8.8), and a
single rate gives it no progression — a child who beats the bot needs a next bot to beat. The file
lives beside the other athletics declarations rather than in the browser so a room hosting a bot
lane reads the same data the solo arena does (the §6.1a posture); the guard test pins the rungs as
named, positive and strictly ascending (§14).

### 7.4 Determinism becomes replay, not re-simulation

Rev.1 could reproduce a race from `(stats, seed)`. With a human in the loop that is gone — the input
is the race. What replaces it is stronger for debugging and weaker for nothing that matters:

> **The impulse log IS the race.** Record `[{at, quality, challengeId}]` per entrant and the result
> is reproducible exactly, on any machine, at any speed.

That makes a shareable replay, a "watch how you won" playback, and a reproducible bug report all the
same feature. It also means the arena is frame-rate independent: impulses carry their own
timestamps, so a child on an old tablet is not penalised by a low frame rate.

**The playback has a ship date now** (Rev.6): the race recap arrives with the Phase 3 results screen
(§8.8, §12) — nearly free once the log exists, and the thing children show each other.

### 7.5 The two randomnesses, kept separate

The owner asked for randomness "to provide uniqueness to the animal." There are two, they serve
different purposes, and conflating them is the classic way this kind of game goes wrong:

| | the pet roll | the race roll |
|---|---|---|
| minted | once, at build | per running of an event |
| lifetime | permanent, part of the pet | discarded when the race ends |
| stored | in the manifest (§4.1) | nowhere |
| purpose | **identity** — two identical designs are different athletes | **texture** — a stride varies slightly, so a race is not a metronome |
| range | `±0.08` (named constant) | per-event, declared by the event, and **small** |

**The race roll shrinks in Rev.2, and that is deliberate.** In Rev.1 it carried the entire drama,
because two fixed stat-sets always produced the same winner. Now the player carries the drama, and
random noise on top of a skill contest reads as cheating — a child who answered faster and lost to a
dice roll has learned the wrong lesson. Keep it small enough to feel alive and too small to decide a
race.

### 7.6 Playback

The arena mounts the frame-advance primitives, sets each pet's animation to the best pose it owns for
the event's medium, and advances position from the impulse stream. Facing, mirroring and tilt come
from the existing transform composition for free. Sprite frame rate should track velocity, so a pet
being driven hard visibly runs faster — the feedback loop that makes answering feel like pedalling.

`web/src/pet/index.ts` gains re-exports (`setBgPos`, `applyTransform`, `getPet`) — and that file is
**already one of the two the runtime designates as legitimately host-specific**, so widening it is
the sanctioned seam rather than a fork (§9.2).

---

## §8 The challenge layer

This is the part the parents are actually buying, and it is where the product stops being a toy.

### 8.1 A second registry, orthogonal to events

Challenges and events form a **matrix, not a hierarchy**: any challenge can drive any event. The 100 m
can be run on tap speed or on times tables; the long jump can be won by spelling. Two registries that
compose:

```ts
export const arithmetic: ArenaChallenge = {
  key: "arithmetic",
  label: "Times tables",
  minAge: 6,
  generate(rng, difficulty) { /* → { prompt: "7 × 8", answer: "56" } */ },
  check(given, expected) { /* → boolean */ },
  inputKind: "numeric",
};
```

`web/src/arena/challenges/`, same shape and same guard test as `events/`. **Four concrete challenges
are named by the owner or fall out immediately** — tap, arithmetic, typing, spelling — so the
registry is earned rather than speculative.

### 8.2 Questions are generated, never authored

A challenge is a **seeded generator plus a validator**, both pure functions. Nobody writes a question
bank; `generate(rng, difficulty)` produces an endless supply, and the same seed produces the same
sequence.

That last property is the fairness mechanism (§8.3) and the replay mechanism (§7.4) at once.

### 8.3 Head-to-head fairness — same questions, same order

**Every entrant in a race receives the identical question sequence**, from one seed minted at race
start. Without this, "I got harder questions" is true often enough to poison every result, and a
child's sense of fairness is not negotiable.

Difficulty is chosen **per race**, not per player, for the same reason. A mixed-age race needs an
explicit, visible handicap (a stride bonus for the younger player) rather than silently easier sums —
handicaps are honest and a child can understand one; secretly easier questions are patronising and
they always find out.

### 8.3.1 The handicap, specified — the mixed-age race is the first race

Rev.1–5 promised the handicap above and never defined it, which is how a "later" becomes a
launch-day gap: siblings are the launch audience, so a seven-year-old racing a ten-year-old is the
first race this game ever runs, not an edge case.

**A handicap is a per-entrant stride multiplier from a closed ladder, chosen at race setup, visible
to everyone.** The ladder is content, beside the other declarations (§6.1a) so the room server and
the solo arena read the same file:

```json
"handicap_ladder": { "none": 1.0, "boost": 1.25, "big_boost": 1.5, "rocket": 2.0 }
```

in `pet_factory/athletics/handicaps.json`. Four rules:

- **It multiplies the §2.3 stride after everything else** — `stride × handicap`, one number applied
  in one place. At `rocket`, a younger sibling answering at half the rate holds even, which is the
  whole job.
- **It is chosen per entrant at setup** — by whoever sets the race up locally, or by the host in a
  room's lobby (`SPEC_PET_ARENA_ROOMS.md` §2.2) — and **shown wherever the entrant is**: the lane,
  the results screen, the recap. A hidden handicap is §8.3's "secretly easier questions" failure
  with extra steps.
- **It is recorded in the race header** beside the seed and the difficulty, so a replayed impulse
  log reproduces the finish exactly (§7.4) and a result never lies about how it was achieved.
- **The ladder is closed.** A value off it is refused (§14) — a free slider is how "visible and
  honest" quietly becomes 1.37× and unexplainable. The names are the point: a child who accepts
  "you get the rocket" has agreed to something they understand.

### 8.4 The balance knob — and the recommendation

The single most important number in this design is **how much of the outcome is the child and how
much is the pet.** It has a name and an admin default:

`ATHLETIC_STRIDE_SPREAD` — the ratio of stride between the best and worst pet in an event.

- A **wide** spread (say 4×) means the pet dominates: a child who studies loses to a child with a
  luckier animal, the maths becomes decoration, and the parents' complaint is not answered.
- A **narrow** spread (say 1.6×) means skill dominates: a better pet is a real but surmountable edge,
  and roughly a 1.6× faster answer rate overturns the worst matchup.

**Recommend starting at 1.6× and tuning down, not up.** The parents are the customer here (decision
0.12); the pet is the *reason to play* and the arithmetic is the *game*. If a session ever feels like
the animal won it, the number is too high.

It is one constant in `pet_factory/athletics/`, tunable without a deploy, and §16.1 asks the owner to
confirm the starting value.

### 8.5 Do not reward guessing

**Typed answers for arithmetic, not multiple choice.** Four-way multiple choice hands out 25% of the
progress for free and rewards mashing over knowing — which defeats the entire reason the parents
would allow this. Tap remains the floor for children too young to type (§8.6), and that is the
deliberate exception rather than a slide toward it.

### 8.6 Tap is the floor, and it is not a lesser mode

The owner's *"the most basic is just tapping on a certain key"* is the accessibility baseline: no
reading, no arithmetic, no typing. A four-year-old, a child with dyslexia, and a sibling who just
wants to play all need it, and a game that only rewards the strongest reader in the family will not
be played twice.

It is a full-fledged challenge in the registry, not a fallback: tap rate is a real skill and a fast
tapper beating a slow multiplier is a legitimate outcome.

### 8.7 Difficulty is selectable, not adaptive

A declared ladder per challenge (arithmetic: sums within 10 → within 100 → times tables → two-digit
multiplication). Chosen at race setup.

**Adaptive difficulty is deliberately not in v1**: it is a whole system, it interacts badly with
§8.3's same-questions rule, and getting it wrong makes a child feel punished for improving.
**Tripwire:** the first time a family reports that one ladder rung is a wall and the next is trivial.

### 8.8 Losing is designed for in v1, not patched after the first sulk

Rev.1 asked whether losing feels too bad, and Rev.1–5 left the mitigations in §16's open-questions
section — which is where committed-sounding scope goes to get cut. **Under Rev.2's rules losing
means "you were worse at maths than your cousin, in front of your cousin"**, so the mitigations are
now committed scope (decision 0.15), phased in §12:

- **Per-event medals** (Phase 3, with the results screen). Many small events means different
  children win different things in one sitting — the meet format doing emotional work, not just
  content work.
- **Personal bests as the default framing** (Phase 3). The results screen leads with "you beat your
  own time" and shows placement second. Bests are **device-local** — `localStorage`, keyed by
  event + challenge + difficulty + handicap, no network call — so §15's no-persisted-results posture
  holds and §11's shared-results tripwire stays unfired. Clearing the browser clears the bests;
  accepted.
- **Private practice** (Phase 2, not Phase 6 as Rev.1–5 had it). The bot (§7.3) ships with the first
  playable slice, both because a solo race against nobody is a time trial and because practising
  where nobody watches is the mitigation that matters most. Solo-vs-bot may well be the most-played
  mode, and the bot ladder (§7.3) is what gives it somewhere to go.
- **The race recap** (Phase 3). "Watch how you won" (§7.4) doubles as "see where it slipped away" —
  a loss a child can explain is a puzzle; one they cannot is just a verdict.

What §16.2 still asks is only the observational half: watch the first family session for whether
these are enough.


## §9 Module boundaries

### 9.1 Four places, one concern each

| layer | new | why here |
|---|---|---|
| content | `pet_factory/athletics/` — vocabulary, `movement_classes.json`, `modifiers.json`, `roll.json`, `bots.json` (§7.3), `handicaps.json` (§8.3.1), **`events/*.json` + `registry.json`** (§6.1a), the stat resolver, and the reference integrator | pure data on the GPU-less tier, beside `tiers/` and `design_axes/`; read by the build, the room server, the browser and the tests — **one declaration, four readers** |
| backend | `webui/pet_athletics.py` — compute the block, stamp it at `_finalize_pet_from_zip` | the `pet_ownership.py` precedent: not `db.py` (record view), not `app.py` (HTTP surface) |
| frontend game | `web/src/arena/` — `challenges/`, the race loop, the Tier-2 event procedures, the arena page. **Tier-1 events are JSON in `pet_factory/athletics/events/`, not here** (§6.1a) | **the new module the owner asked for** |
| frontend runtime | `web/src/pet/` — **unchanged except `index.ts` re-exports** | §9.2 |

Events and challenges are **sibling registries, not nested** (§7.1). Nesting challenges under events
would make "add a challenge" an edit to every event, which is the exact failure the plugin rule
exists to prevent. They live in *different repositories of content* for a reason: an event
declaration is shared with the server (§6.1a), a challenge is browser-only — nothing server-side ever
needs to know what 7 × 8 is.

### 9.2 The arena is a second driver, not a second engine

The pet runtime has one driver today: ambient life (`useAutoStateMachine`). The arena is a second
driver over the **same primitives** — same `petStore`, same strategies, same transform composition.

No edits to `petStore.ts`, `useAnimationLoop.ts`, or any locomotion strategy. Two reasons:

1. **Change cadence.** The runtime changes when pets need to *behave* differently; the arena changes
   when the *game* changes. Different reasons, different places.
2. **The drift already measured in §1.4.** Whatever the story is behind 331 changed lines in
   `petStore.ts`, the answer is not to add game rules to it.

The one seam is `index.ts`, which the runtime already designates as host-specific.

---

## §10 Poses are the product — the monetization lever, with the numbers

The owner: *"this makes buying an animal with different motions more valuable… premium animals can
compete in more events as they have more poses."* §6.3's eligibility rule is that sentence expressed
as one line of code, and this section is what it is worth.

### 10.1 What exists today

`tiers.json` ships `default_tier: "plus"` — **8 poses for everyone**, each pose beyond walk+idle
charged at **50 credits** (live: the host counts poses from the fetched bundle manifest, so charging
already works with no capability grant). The file's own note describes flipping back to `base`
(2 poses) once a real premium capability exists.

So the mechanism is **already built and already charging**. The arena does not add a purchase flow;
it adds a *reason*. Today a pose is bought for charm — a sleeping cat is nice. After this, a pose is
bought for entry.

### 10.2 Today's snapshot — NOT a ceiling

The owner has confirmed the pose vocabulary *"will definitely increase."* These are the numbers on
**2026-08-02** and nothing in this design may assume they hold (§6.3.2):

| | |
|---|---|
| canonical poses | **10** (`walk, idle, run, sleep, sit, eat, jump, play, swim, fly`) |
| of which **athletic** | **5** (`walk, run, jump, swim, fly`) — the other five are charm |
| `MAX_POSES` platform ceiling | **10** (`motion_profiles/__init__.py:52`) |
| `plus` tier cap | **8** |
| headroom available with **no code change** | **8 → 10** |

Two purchasable slots exist above today's cap needing nothing but a `tiers.json` edit — that is the
near-term lever.

**Growing the vocabulary itself** — a `climb`, a `dig`, a `bounce` — costs three things together,
and the third is the expensive one:

1. raise `MAX_POSES` (one constant);
2. author the pose in each of the seven profile files that should have it — a clause, a
   `runtime_role`, a `view`, per profile;
3. **regenerate any pet that should own it.** Bundles are immutable: an existing pet can never gain a
   pose without a fresh ~3-minute build. This is the same immutability that ruled out fighting (§15).

So new poses are for **new** pets, and each one is a reason to build another — which is the business
model working rather than a limitation. It does mean the *first* few pets a family owns will age out
of the newest events, and §16 asks whether that is acceptable or wants a rebuild path.

### 10.3 Today the ceiling is the body type, not the tier

A pet can only own poses its **profile** enables. Athletic poses available per body type:

| body type | athletic poses it can ever own | events reachable |
|---|---|---|
| avian, winged_flyer, humanoid | `walk, run, jump, fly` — **4** | most |
| quadruped, primate | `walk, run, jump` — **3** | land only |
| aquatic, serpentine | `walk, run, swim` — **3** | no jumps at all |

**Today a dog owner cannot buy their way past 3 athletic poses**, no matter what is spent — the extra
slots go to `sleep`, `sit`, `eat`, `play`, which are charm. So "premium animals compete in more
events" is true, but right now it is delivered by **which animal you choose** at least as much as by
how many poses you buy. Worth knowing before it is advertised the other way round.

**This is the constraint that new poses relieve most.** A `bounce` authored onto `quadruped` would give
dogs a fourth athletic pose and unlocks hurdles for them; §10.4's `swim` gives a fifth. The vocabulary
growing is not just more events — it is *more purchasable ability per body type*, which is where the
revenue per pet actually is.

It also means the *bird* is the natural premium archetype: four athletic poses, the only body type
that reaches air events. If premium animals are a product, birds and dragons are the obvious stock.

### 10.4 The cheapest premium content in the codebase is one line of JSON

`quadruped.json` ships `swim: off`. **Dogs swim.** Enabling it:

- costs one data edit, no code, no GPU, no deploy of anything but content;
- opens the entire swimming category to every quadruped — the largest body-type population;
- creates a fourth purchasable athletic pose for dogs and cats, lifting §10.3's ceiling from 3 to 4;
- is exactly the "engine vs content" pattern working as designed — a capability change that touches
  no runtime code.

The same question is worth asking of `primate` (chimps swim; apes largely do not) and of `jump` for
`serpentine` (snakes strike — arguably a jump).

**This should be verified with a real generation before it is sold**: a `swim` pose is a Wan I2V loop
against a swimming clause, and whether a corgi doing breaststroke looks charming or broken is a GPU
question, not a design one.

### 10.5 The `default_tier` flip is now a game-balance change

Flipping `default_tier` to `base` gives a free pet 2 poses: `walk` and `idle`. Under §6.3 that pet
can enter **exactly one event** — the racewalk.

That is coherent and it is monetizable, but it is a **product decision that must be made
deliberately**, because the same mechanism can make a free child's experience feel like a locked
door. Three mitigations, all already in this design:

- the **racewalk exists** so a free pet is never empty-handed (§6.3);
- locked events are **shown with their requirement**, so the gate reads as a goal rather than a
  refusal;
- the **affinity numbers are knobs, not zeroes** — a walking pet in a walking race is a real
  competitor.

**Tripwire:** whoever flips `default_tier` must read this section. It stopped being a pricing change
the moment poses became entry tickets.

---

## §11 Fairness — and the tripwire that has now fired

Stats live in `manifest.json`, and anyone who unzips a bundle can edit them. **That is accepted, not
a gap to close** — the same no-DRM posture SPEC_PET_OWNER_FIELD §0.1 took, for the same reason: the
cost of real enforcement exceeds the value being protected.

**Rev.1 wrote the tripwire and Rev.5 fired it**, so it is recorded here rather than quietly edited
away. The original wording:

> *"The moment results are shared — a leaderboard, a record book, a tournament across households —
> client-computed stats stop being adequate and the simulation has to move server-side."*

Five children on five devices racing in one room is exactly that. The response is **not** to bolt
authority onto this document: real-time sessions, a public spectator URL, room-scoped asset access
and child-safety rules are a different system with a different change cadence, and they get their
own spec — **`SPEC_PET_ARENA_ROOMS.md`**.

**What stays true here regardless of where a race is run:**

- The game rules in this document do not change. A room feeds the **same impulse stream** (§7.1), so
  events, challenges, stats and qualification are untouched by it.
- Solo and hot-seat play (§12 Phases 2–3) need **no server at all** and should ship first, because
  they prove the game is fun before anything is spent on transport.
- The no-DRM posture survives for the *pet*; it is the *race* that gains an authority. A child can
  still edit their own bundle's stats — and in a room, the server reading those stats is reading what
  the child's own device sent, which the rooms spec bounds rather than eliminates.

## §12 Rollout

| Phase | Ships | Depends on |
|---|---|---|
| **1** | `pet_factory/athletics/` content package + the resolver + eligibility table + guard tests. Nothing consumes it. | nothing |
| **2** | **The playable slice**: arena page, 100 m, the impulse loop (§7), **two** challenges — `tap` and `arithmetic` — and **the bot** (§7.3), because a solo race against nobody is a time trial and private practice is v1 scope (§8.8). Runs on §5's derived stats: **no manifest change, no backend, no factory change at all.** | Phase 1 |
| **3** | Two-player on one device (hot-seat), shared question seed (§8.3), the handicap (§8.3.1), and the results screen **with per-event medals, personal-best framing and the race recap** (§8.8). **Still no server.** | Phase 2 |
| **4** | `webui/pet_athletics.py` mints the block at build; `table_version` in place. | SPEC_PET_DESIGN_PROVENANCE Phase 2 *(only for §3.2 modifiers; the block ships without them)* |
| **5** | Events 2–4 (200 m, long jump, high jump) + `typing`/`spelling` challenges — one file each, in any order. | Phase 3 |
| **6** | Skiing, pole vault, swimming. *(The bot moved to Phase 2 in Rev.6 — §8.8.)* | Phase 5 |
| **R** | **Rooms** — five players, own devices, spectator URL. Its own spec (`SPEC_PET_ARENA_ROOMS.md`), its own phases, and it can start any time after Phase 2 because it consumes the same impulse stream. | Phase 2 |

**Phase 2 is the whole idea, playable, and it touches nothing that already exists.** No factory
change, no pool change, no bundle change, no backend route — §5's derived stats mean the children's
existing pets compete on day one. That is the fastest possible path from this document to a child
doing times tables to make a corgi run.

**Ship two challenges in Phase 2, not one.** With only `arithmetic` the concept is untestable — you
cannot tell whether a race felt good because the maths was well-tuned or because the pet was. `tap`
is the control: same event, same pets, no arithmetic. It is also the accessibility floor (§8.6), so
it is not throwaway scaffolding.

**Slots.** Separately from all of this: the house cap is `DEFAULT_HOUSE_MAX_PETS = 50`, already a
runtime env knob (`PETMAKER_HOUSE_MAX_PETS`, `webui/house_capacity.py:24-26`). Raising it is one env
var. The cost is storage — bundles are blobs in-row at roughly 3.5 MB each, so 200 pets is ~700 MB
per user. Worth confirming what the children are actually hitting before raising anything; 50 saved
pets is a lot to burn through.

---

## §13 The four test questions

1. **Will adding a new variant require an engine change?** No. A new **event** is one file plus one
   registry line. A new **body type** already lands in `movement_classes.json` as one entry. A new
   **design axis** contributes a modifier or nothing. None touches the simulator.
2. **Will adding a feature require touching unrelated files?** No. Phases 1–2 add three new
   directories and change nothing existing. Phase 3 adds one stamp beside three existing stamps.
   The packer, the pool handlers, the store, the DPP adapter and the designer are untouched
   throughout.
3. **Will a third-party integration require modifying owned code paths?** No. `athletics` is one more
   unknown manifest key; DatsMe's validator tolerates unknown keys
   (`../datsme_me/api/apps/pets/pet_assets_service.py:265-277`) and its ownership writer preserves
   them by documented rule. The host needs no change and gains a pet that races if it ever wants one.
4. **Will a bug in one variant force debugging shared code?** No. A broken event is one file; the
   registry guard stops it shipping half-formed. A wrong stat is one row of a JSON table. Neither can
   reach the pet runtime, because the arena does not modify it (§9.2).

---

## §14 Guard tests

**`pet_factory/tests/test_athletics.py`** — the content package

- Every `movement_class` in `motion_profiles/registry.json` has a row in `movement_classes.json`, and
  no row exists for a class that is not declared. **This is the cross-layer test that stops a new
  body type silently defaulting to average at everything.**
- Every attribute and affinity in a row is in the declared vocabulary and within `0.0–1.0` — **no
  `null`**, since Rev.3 removed the ineligible semantics (§2.2).
- **Every pose named in every event's `requires` exists in the LIVE `motion_profiles.CANONICAL_POSES`**
  — imported, never copied (§6.3.2). A typo'd or not-yet-authored pose makes an event permanently
  unenterable by every pet on earth, silently. This is the cross-layer test that matters most.
- **Every clause is non-empty**, and `requires` itself is non-empty. An empty clause would qualify
  nobody; an empty `requires` would qualify everybody. Both are silent, and both are what a
  half-finished JSON edit produces.
- **Every `requires` clause is satisfiable by at least one shipped profile.** A clause like
  `["fly"]` combined with `["swim"]` names two poses no single profile enables — an event nobody can
  ever enter, which passes every other check. Computed against the profile set, not asserted by hand.
- **At least one event requires only `walk`** — the universal-event guarantee (§6.3.3), pinned where
  the event table lives so deleting the racewalk fails the build rather than quietly stranding
  2-pose pets.
- **`teamSize` is a positive integer** and every event declares one; singles are `1`, never absent
  (§6.5) — an absent value is how a team event silently becomes a solo one.
- Every modifier's `{axis, option}` resolves against `design_axes` — a typo'd option key fails the
  build rather than becoming inert.
- **`handicap_ladder` includes `1.0` and every value is ≥ 1.0** (§8.3.1) — "no handicap" must be
  expressible, and a handicap may only help. The ladder is closed: race setup refuses a value off it.
- **`bots.json` rungs are named, positive and strictly ascending** (§7.3) — a flat ladder means
  beating the bot has no next step.
- The resolver never raises: unknown class, missing `animations`, malformed block, empty manifest all
  return a usable six-tuple.
- **Precedence:** a manifest with a valid block returns it verbatim; a stale `table_version`
  recomputes; an absent block derives — and the derived path reuses no stored state.

**`webui/tests/test_athletics_stamp.py`** — the build seam

- A built pet's manifest carries `athletics`, and the block's inputs match the pet's own
  `movement_class` and pose set.
- The block survives the ownership stamps and the design stamp in any order (patch-never-rebuild).
- Every other manifest key is byte-identical to the packer's output.
- Re-minting under a bumped `table_version` **preserves `roll`** — the identity-survives-rebalance
  rule (§4.1). This is the one that will actually catch a regression.

**`web/src/arena/*.test.ts`** — the game

- **The stride formula is pinned** (§2.3): a table of `(score, spread) → stride` fixtures, including
  `score = 0.5 → STRIDE_BASE_M` exactly, and `best ÷ worst == ATHLETIC_STRIDE_SPREAD` exactly. This
  is the equation the whole game reduces to and it must not drift on a refactor.
- **The shared race-vector fixture** (§6.1a) produces identical results from the Python integrator
  and the TypeScript one. Owned by `pet_factory/athletics/tests/fixtures/race_vectors.json`, run by
  both sides — the SPEC_PET_OWNER_FIELD §2.3a pattern.
- **Tier-1 events carry no code:** every event in `athletics/events/` is pure JSON with no companion
  module, asserted so a "just a little logic" exception fails the build (§6.1a tripwire).
- **Both registries enforced:** every event declares every required field, weights sum to 1.0,
  `medium` is in the vocabulary, `preferredPoses` are canonical pose names; every challenge declares
  `generate`, `check`, `inputKind` and a difficulty ladder.
- **Replay determinism:** the same impulse log replayed produces byte-identical results (§7.4).
  Without this nothing else in the game is debuggable.
- **The flopping-fish test:** an `aquatic_swimmer` **that owns `run`** is admitted to the 100 m and
  finishes last; the same body type **without** `run` is refused. Two pets, one species, opposite
  answers — which is the per-pet nature of §6.3 and the thing a per-species implementation gets wrong.
- **The universal-event test:** every body type, at the **2-pose minimum**, has at least one enterable
  event. This is the structural guarantee that no child ever opens the arena to an empty list (§6.3),
  and it must be asserted rather than assumed, because it holds only while some event requires `walk`.
- **Locked is visible:** an unqualified event is returned to the UI **with every unsatisfied clause
  named, including all its alternatives**, never filtered out of the list (§6.3.3, §10.5).
- **Alternatives are honoured:** a pet with `bounce` but not `jump` qualifies for hurdles; a pet with
  neither does not; a pet with `jump` but not `run` does not. The three cases together are the whole
  clause evaluator (§6.3).
- **Team qualification is per member:** a 4-pet relay team with three qualifying pets and one that
  lacks the coordination pose is **refused as a team**, and the UI names which pet is the problem
  (§6.5). Carrying a member is the obvious bug here and it must fail loudly.
- **The legacy test:** a manifest with **no** `athletics` block still yields a complete entrant, and
  the same sheet bytes yield the same roll across runs (§5.2).
- **The skill-beats-stats test — the headline one:** the worst-stat pet driven at 2× the answer rate
  beats the best-stat pet. If this fails, `ATHLETIC_STRIDE_SPREAD` is too wide and the parents'
  reason for allowing the game is gone (§8.4).
- **Same questions for everyone:** two entrants in one race receive identical prompt sequences in
  identical order (§8.3).
- **The handicap is honest** (§8.3.1): effective stride is exactly `stride × handicap`; the race
  header names every entrant's handicap; replaying a handicapped race reproduces the finish. A
  result payload that omits a non-1.0 handicap is a failing test, because a hidden handicap is the
  "secretly easier questions" failure §8.3 forbids.
- **Personal bests never leave the device** (§8.8): the results screen reads and writes
  `localStorage`, keyed by event + challenge + difficulty + handicap, and makes no network call.
- **No backwards movement:** a run of only wrong answers leaves position at exactly the start line,
  never behind it (§7.2).
- **Guessing does not pay:** an `arithmetic` challenge exposes no answer set to guess from
  (`inputKind: "numeric"`, not a choice list) — §8.5, pinned so a later "make it easier on mobile"
  cannot quietly become multiple choice.
- **The bot is indistinguishable:** an event fed a bot's impulse stream and a recorded human's
  produce results through the identical code path (§7.3).

**`pet_factory/tests/test_pack_bundle_layout.py`** — **unchanged, and that is the assertion.** If it
needs an edit, game rules have reached the packer.

---

## §15 Deliberately not done

- **No fighting.** The canonical pose vocabulary is `walk, idle, run, sleep, sit, eat, jump, play,
  swim, fly` (`pet_factory/motion_profiles/__init__.py:39`) — there is no combat pose, and since
  bundles are immutable **every pet already built would need regenerating at GPU cost to gain one**.
  Track and field ships to the existing population; fighting strands it. That is the whole reason
  this spec is a meet and not a brawl.
- **No leaderboards, records, or cross-household tournaments** — §11's tripwire. Results are
  ephemeral in v1, with one deliberate exception: device-local personal bests in `localStorage`
  (§8.8), which never leave the device and are a mirror, not a record book.
- **No backend for the arena.** No new tables, no new routes, no persisted results.
- **No wagering, ranking, or progression** — no XP, no training, no levelling. A pet's ability is
  what it was built with. Revisit only as its own product decision.
- **No `agility` attribute** until an event needs it (§2.3).
- **No pose authoring in this spec.** New poses are *expected* (§6.3.2) and the arena is built so
  they need no arena change — but authoring `bounce` or `dance` is a motion-profile project with a
  GPU cost (§10.2), owned by whoever owns the profiles. The launch catalogue (§6.4) is deliberately
  built from poses that already exist, so the arena never blocks on one.
- **No boolean expression language for qualification** (§6.3.1) — AND-of-ORs only, no NOT, no
  nesting.
- **No cross-family or online teams.** A relay team is four pets from one house (§6.5).
- **No enabling of `swim` on `quadruped`** as part of this spec, tempting as §10.4 is. It is a
  motion-profile content change that needs a GPU session to verify, and it belongs to whoever owns
  the profiles — not smuggled in with a game.
- **No per-pet speed in the locomotion strategies.** The impulse stream drives position directly
  (§7.1), and §9.2 forbids the edit.
- **No adaptive difficulty** (§8.7), **no multiple choice** (§8.5), and **no answer streak bonuses** —
  a streak multiplier compounds an early lead into an unrecoverable one, which is the same
  runaway-loser failure §7.2 avoids.
- **No progress tracking, parent dashboard, or "what your child practised" report.** This is the
  single most valuable thing that could be built on top — it is what converts a parent's complaint
  into a parent's endorsement — and it is deliberately out of v1 because it needs a backend, a data
  model, and a serious think about storing children's performance data. **Tripwire:** the first
  parent who asks whether it is working.
- **No arena on the DatsMe host.** The game lives on the partner side, where the pets and the house
  already are. The host gains one inert manifest key and no work.
- **No changes to the designer.** The arena adds no step, no field, and no decision to the three-step
  flow. A pet's athletics are a *consequence* of design choices already being made.

---

## §16 Open questions for the owner

**16.1 The balance number — the one that decides whether this works.** (§8.4.)
`ATHLETIC_STRIDE_SPREAD`, the ratio of stride between the best and worst pet. Recommend **1.6×**,
tuned down rather than up. Too wide and a studying child loses to a luckier animal and the maths is
decoration; too narrow and the pet stops mattering and the collection loses its point. This is the
number to watch on the sofa in the first session.

**16.2 Is §8.8 enough?** (Carried from Rev.1; **Rev.6 resolved the scope half.**) The mitigations
that sat here as suggestions — per-event medals, personal-best framing, private bot practice, the
recap — are now committed v1 scope with phases (§8.8, decision 0.15). What remains open is
observational: watch the first family session for whether they are enough, and in particular whether
losing *with* a handicap (§8.3.1) reads as fair or as patronising to the child holding it.

**16.3 Which challenges first, and pitched at what age?** Recommend `tap` + `arithmetic` in Phase 2
(§12), with the arithmetic ladder starting at sums within 10. Worth asking the parents what the
children are actually working on — times tables, spellings, something else — because the first
challenge that matches this week's homework is the one that gets permission.

**16.4 Field size — and it is two numbers now, not one.** The owner said 5–10 pets. With teams
(§6.5) those separate:

- **entrants per event** — **5**, matching the owner's *"5 people (configurable 1–5)"* and
  `ROOM_MAX_PLAYERS` in `SPEC_PET_ARENA_ROOMS.md` §8. (Rev.1 recommended 6 before the room spec
  existed; the two must not disagree, and the owner's number wins.) With human players the practical
  limit is *devices*, not pets — five entrants means five children, or fewer plus bots.
- **pets on the stage at once** — recommend **capping at `teamSize`**, by running team events one leg
  at a time. Six relay teams is twenty-four pets; `PetStage` will mount them but a phone will not read
  them, and one-leg-at-a-time is also how a relay looks on television.

Both are named constants.

**16.4a Do older pets age out?** New poses only reach **new** pets — bundles are immutable, so an
existing pet can never gain `bounce` without a fresh build (§10.2). A family's first pets will
gradually be locked out of the newest events. That is the business model working, but it is also a
child's favourite pet becoming ineligible, which lands differently. Worth deciding now whether that
is accepted, softened (new events lean on old poses where possible — §6.4 already does), or given a
rebuild path.

**16.5 Whose pets may enter?** **Answered by Rev.5** for the multi-device case: up to five players in
a room, own devices, spectators by URL — specified in `SPEC_PET_ARENA_ROOMS.md`. What remains open
here is narrower: whether a player may enter a pet they do **not** own (borrowed from a friend's
house) or only their own. Recommend **own house only** — it needs no sharing model, and the store
adopt path already exists for anyone who wants a copy of someone else's pet.

**16.6 How visible are the stats?** Showing the six bars on a pet card makes the design→performance
link legible, which is what the children asked for. Recommend **visible** — the link is the feature,
and a hidden stat is indistinguishable from a random one. It also lets a child reason about *why*
they lost, which is the difference between a game and a slot machine.

**16.7 Confirm the slots number** (§12) before anything is raised, and check what the children are
actually hitting — 50 saved pets is high enough that something else may be stopping them.
