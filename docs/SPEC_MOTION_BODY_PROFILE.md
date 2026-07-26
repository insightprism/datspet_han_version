# SPEC — Body profile: composing movement prompts from what an animal *is*

**Status:** **PARKED — do not implement** (decided 2026-07-26). **Rev.3**, and nothing in §7
has shipped: there is no `pet_factory/body_profile/`, no `default_body_profile` on any motion
profile, no `body_profile_classify` purpose, and the string `clade` appears in no code file.
Rev.1/Rev.2's three commits (`0e9ac3e`, `497967d`, `2064ae7`) touched this document and
nothing else. Rev.3 re-grounds the spec against the working tree after the motion-profile
work that landed *after* Rev.2, corrects what that made stale, adds §0.0 (what this delivers
and what it is worth) and §2.4 (the silence, measured) — and then, on that evidence, parks it.

### Why it is parked (read before reviving it)

Rev.3's own measurements are the argument against building it now. Recorded here so the next
reader gets the ledger rather than the pitch:

- **The defect class has fired once.** One prompt-content defect has shipped in this repo's
  history (the hovering dragon, §0.1). The repo-wide sweep that fixed it — `908e855`, every
  `sleep` prompt in every profile — was **19 lines across 5 files**. That is the observed cost
  of the failure mode this spec eliminates, and it is small.
- **Three instances before consolidating** (repo `CLAUDE.md`). One instance, not three. A
  registry + composer + classifier built against a single observed example is exactly the
  single-element abstraction that rule exists to prevent.
- **§2.4 measures silence, not badness.** 37 of 57 poses are silent about a limb; **no
  generated output was reviewed**, so none of the 37 is a confirmed defect. The pose-anchor
  work was validated against real clips on 2026-07-24 and the motion system is currently
  working — that is the baseline any migration has to beat.
- **The dominant cost is review, not code.** Steps 1–2 are days of data files. Step 3 retires
  114 overrides one at a time, each gated on a human watching a ~3-minute GPU build, to change
  output that presently looks right. Worst ratio in the plan.
- **`humanoid` is the counter-example that holds.** Authored by hand in `b8a8d56`, nearly
  clean on both surfaces (§2.4). Careful authoring works at this scale. The spec's real claim
  is that it does not work *durably* — and durability is a bet on growth that has not happened
  yet.

**The cheaper thing to build first, when something does bite.** Declare each profile's limb
groups as one field — `body_parts: ["legs","wings","tail"]` — and add one guard test asserting
that every enabled pose either names each declared group or records an explicit
`{"tail": null}` ("considered, contributes nothing"). Seven small data edits and one test
file. The hovering dragon fails it. This is **not** a lesser version of this spec — it is a
strict subset: `body_parts` *is* §1.2's `limbs`, and the explicit `null` *is* §3's rule. The
full spec builds on that field rather than replacing it, so nothing is thrown away and no
transition layer is needed. (Deliberately not built on 2026-07-26 either — recorded, not
queued.)

**What would unpark this:** body types growing past ~10 (five → seven happened in one day, so
this is plausible); a **second** prompt-content defect shipping; or a review of real generated
output finding that the §2.4 silence actually shows on screen. Any one of those turns the
three-instances objection into evidence, and the spec below is then ready to build as written.

Replaces per-body-type hand-written motion prompts with prompts **composed** from a small
structured description of the animal: its clade, limbs, surface, size, habitat and primary
motion. The goal is that the engine can write an accurate `walk` prompt for a turtle, a dog, a
human and a dragon *without anyone having authored four walk prompts* — because the data says
how each of those bodies walks.

**What Rev.3 corrects (all of it stale-since-Rev.2):**

| was | is, as of 2026-07-26 |
|---|---|
| "today's five profiles" (§4.3, §6) | **seven** — `primate` and `humanoid` landed in `b8a8d56` |
| `winged_flyer.walk` reads *"hovering forward with steady wing beats"* (§0.1) | hand-fixed in `908e855`, one commit **after** Rev.2. It now names the wings explicitly. The origin story is now history, not a live defect — and the way it was fixed is itself the argument (§0.1) |
| per-pose free text = `action` + `suffix` (§0.1, §6) | **two** free-text surfaces per pose. Every one of the 57 enabled poses also carries a `pose_prompt` anchor clause (`control.pose`, `SPEC_MOTION_PROFILES` §3.9.1) with its own AI drafter (`ai_purposes/pose_clause.json`). 114 hand-authored fields, not 57 — §4.4 |
| `compose_pose_prompt` at `motion_profiles/__init__.py:215` (§4.1) | `:241` |
| "surface is already resolved per animal today" (§1.3) | three of the six values exist (`fur`/`feathers`/`scales`); `skin`/`chitin`/`slime` are **new** and not free to add (§1.3) |
| §7 step 3 starts with `winged_flyer`'s `walk`/`run` | those two are exactly the ones already hand-fixed. Step 3 is re-pointed on measured evidence (§2.4, §7) |
| §7 step 6 reconciles `primary_motion` with `signature_pose` | `signature_pose` **does not exist either** — `SPEC_BUNDLE_MOTION_CONTRACT` §3.4 is unimplemented. There is nothing to reconcile; there is one field to define once (§7) |

Builds on **`docs/archive/SPEC_MOTION_PROFILES.md`** (the body-type registry that resolves
which poses exist) and **`docs/SPEC_MOTION_PROFILE_ADMIN.md`** (the Motion Lab that authors
and previews them). Grounded against the working tree.

**Repos touched:** `datsme-pet-factory_wu` only. `CANONICAL_POSES` is unchanged (§0.5), so
the bundle contract, the sheet layout and the DatsMe host are all untouched.

**Dependency:** none. Ships behind an override (§4.3) so existing profiles keep their
current prompts until each is migrated.

---

## 0.0 What this delivers, and what it is worth

**The problem, stated as it actually is today.** A pet's motion comes from free text a human
typed into a JSON file. Seven body-type profiles × 7–9 enabled poses = 57 poses, each with a
motion prompt *and* an anchor clause: **114 hand-authored prompt fields** (§2.4). Nothing
checks any of them. A string can describe the
wrong gait, name the wrong limb, or — the failure that actually shipped — say nothing at all
about a limb the animal has, and the pipeline will render exactly what it was told at ~3
minutes of GPU per pet, pack it into a bundle, and hand it to the DatsMe host to drive.

**The deliverable.** Three things, and only the first is new machinery:

1. **A body profile** (§2) — six axes describing what an animal *is* physically:
   `clade · limbs · surface · size · habitat · primary_motion`. Six values, no prose.
2. **Clause registries** (§3) — one data file per axis value, mapping canonical pose → the
   clause that axis contributes to that pose. `wings.json` knows what wings do during `walk`
   (*folded at its sides, not beating*) once, for every winged animal that will ever exist.
3. **A composer** (§4) — concatenates the clauses the body profile selects. It names no
   animal, no clade and no limb; it walks the vector and joins what the registries hold.

**The value, in the order it pays out:**

- **It deletes a defect class rather than a defect.** "Every limb the animal has gets a clause
  in every pose" (§0.2) is enforceable because the body profile *declares* the limbs — a
  missing clause fails the build (§5.1) instead of shipping. The hovering dragon could not be
  expressed, not merely could not recur. Today's equivalent guarantee is that somebody
  remembered.
- **New body types stop costing prompts.** Adding an eighth body type today means authoring
  ~20 more strings and reviewing them by eye; `primate` and `humanoid` (`b8a8d56`) cost
  exactly that. Under composition it costs **one six-value vector** — and a body plan nobody
  has anticipated (a six-legged mythic thing with a fluke) composes without an author,
  because the axes are additive rather than a matrix (§0.3).
- **The long tail collapses.** Wolf, coyote and husky share one vector (§2.3), so they share
  one reviewed set of prompts. The unit of quality control becomes ~12 real body plans instead
  of an open-ended list of animals.
- **A wrong prompt becomes attributable and fixable once.** The Lab shows which axis produced
  which clause (§5.3); fixing the clause fixes every animal that shares it. Free text can only
  be fixed one profile at a time, which is why `908e855` had to touch every `sleep` prompt in
  the repo by hand.
- **It is checkable without a GPU.** A vector that cannot name its animal is under-described
  (§2.2), and that is a round-trip a fast model can run in a second (§5.2) against a build
  that costs three minutes of RTX 3090 — and against a defect that otherwise surfaces only
  when a user watches their pet skate along the floor.

**What it does not do.** It does not add poses (`CANONICAL_POSES` is frozen, §0.5), does not
change the bundle contract or touch the host, and does not change a single generated frame
until a human retires an override pose by pose (§4.3, §7 step 3). Steps 1–2 are inert by
construction.

---

## 0. The core decisions (read this first)

1. **A prompt is composed, not authored.** Today each profile carries a free-text `action` +
   `suffix` per pose, **plus** a free-text anchor clause (§4.4). Free text has no structure to
   check, which is how `winged_flyer`'s `walk` came to read *"hovering forward with steady
   wing beats"* — a hover prompt wearing the name `walk`, describing wings and never
   mentioning legs. It generated exactly what it said, and the DatsMe host then translated
   that pet along the floor as a ground gait: a dragon skating on its belly, flapping.

   **That prompt is fixed** (`908e855`, one commit after Rev.2): it now reads *"walking on its
   legs … legs and feet cycling through one complete stride, wings kept folded at its sides …
   no wing flapping, no hovering"*. **How it was fixed is the argument for this spec, not
   against it.** A human noticed, hand-edited one string in one file, and the same sweep had
   to hand-edit every `sleep` prompt in the repo to name the limb that moves. Nothing about
   that fix is checkable, transferable to the eighth body type, or able to tell a considered
   wording from an oversight — and §2.4 measures how many of the other 113 strings are still
   silent about a limb. Composition makes the omission impossible to *express*; a hand-fix
   only makes one instance of it absent.

2. **Every limb the animal has gets a clause in every pose.** This is the single rule that
   kills that entire defect class. Silence about a limb is the bug.

3. **The axes are additive, not a matrix.** Six independent axes each contribute one clause;
   they concatenate. `legs.json` never needs a reptile variant, because clade contributes
   the stance clause separately. Nine clades × six surfaces × five sizes is a large product
   on paper and is **never enumerated** — there is no furry fish.

4. **The description must identify the animal.** If a vector cannot name the creature, it is
   not describing enough to prompt it (§2.2). This is both the design test and a runtime
   validation (§5.2).

5. **`CANONICAL_POSES` is frozen.** Clade decides how the ten existing poses *look* and which
   are *enabled* — it may not add `bask`, `preen` or `groom`. Those need a `runtime_role`,
   host-side ambient weighting and a sheet-layout slot; adding one is a cross-repo contract
   change, not factory data. Deliberately out of scope so this spec ships alone.

6. **Composition is the default; the Motion Lab may override.** A composed prompt is
   produced for every pose. An authored override pins one pose for one body profile when a
   human sees something the model cannot (§4.3). The override is explicit and visible, so
   drift is detectable rather than silent — which is exactly what free text was not.

7. **Both prompt surfaces are composed, or the guarantee is a half-guarantee.** Since the
   pose-anchor work landed, each pose carries a motion prompt *and* a static anchor clause,
   and the anchor is silent about a limb just as often as the prompt is (§2.4: 33 of 57 each).
   Composing only the motion prompt would leave §0.2's rule true of one surface and false of
   the other — the same body plan, described twice, checked once. The clause files answer both
   because a limb clause has a moving form and a still form; §4.4 states the shape and §7
   sequences it after the motion prompt lands.

---

## 1. The six axes

Each axis is a **closed vocabulary**, small enough to be a dropdown, and each value carries a
**defined movement meaning**. That definition is the payload — it is what the composer emits
and what makes a turtle's walk differ from a dog's.

### 1.1 `clade` — how the body carries itself (9)

The axis that limb counts cannot express: a lizard and a dog have identical inventories
(4 legs, 1 tail) and completely different walks.

| value | stance | spine | cadence |
|---|---|---|---|
| `mammal` | legs directly beneath the body | flexes vertically with the stride | sprung, continuous |
| `primate` | legs beneath, torso semi-upright | flexes, shoulders roll | deliberate, hands often in contact |
| `humanoid` | fully upright, hands free | torso stable, hips counter-rotate | even, heel-to-toe |
| `bird` | upright over two legs, body horizontal | stiff torso, neck absorbs motion | quick, head-bobbing |
| `reptile` | **limbs sprawled to the sides, belly low** | **undulates side to side** | deliberate, stop-start |
| `amphibian` | crouched, limbs splayed | compresses and extends | hop-pause, explosive |
| `fish` | no stance — suspended | axial undulation head to tail | continuous, gliding |
| `insect` | rigid, legs radiating | none — exoskeleton does not flex | alternating tripod, jerky |
| `mythic` | as its limb plan implies | as its limb plan implies | weight-driven (see `size`) |

### 1.2 `limbs` — what actually moves (5 groups)

| group | values |
|---|---|
| `legs` | 0 · 2 · 4 · 6 · 8 |
| `arms` | 0 · 2 (with hands) |
| `wings` | 0 · 2 · 4 |
| `tail` | none · plain · prehensile · fluke |
| `fins` | 0 · 2 · 4+ |

### 1.3 `surface` — secondary motion (6)

**Half of this axis already exists** — `animal_catalog` tags `surface`,
`design_axes/surface_keywords.json` classifies a typed name, and the `coat`/`plumage`/`scales`
design axes gate on it. This spec adds a *second consumer* of that resolution. Rev.3 states
the boundary precisely, because Rev.2 implied the whole axis was free:

- **`fur`, `feathers`, `scales` are live** — those are the only three surfaces
  `surface_keywords.json` knows, and the only three with a design axis behind them.
- **`skin`, `chitin`, `slime` are new**, and adding one is **not** a one-line edit on the
  design-axes side: a surface value with no matching surface axis changes which axes a user
  sees at step 2 (`SPEC_PET_DESIGN_AXES` §3.3). Either the value ships motion-only — resolved
  for prompting, absent from `surface_keywords.json` — or it ships with an axis. **Recommended:
  motion-only.** The two consumers ask different questions (*how does the covering move* vs.
  *what can the user restyle*), and forcing one vocabulary to serve both is what makes a
  clockwork octopus need a coat dropdown.
- **`null` is a real answer.** `surface_keywords.json` has no fallback by design — an unmatched
  name resolves to `null` and gets universal axes only. The composer must therefore treat a
  missing surface as *contributes no clause*, exactly like a `null` limb group (§3), never as
  an error and never as an implied `fur`.

| value | what it does when the body moves |
|---|---|
| `fur` | ripples along the flanks with each stride, settles when still |
| `feathers` | ruffle at the shoulders, splay on landing |
| `scales` | plates shift and catch the light; no soft deformation |
| `skin` | taut, bare, no secondary motion |
| `chitin` | rigid segments articulate at the joints; nothing flexes |
| `slime` | glistens, wet highlights shift |

### 1.4 `size` — timing and weight (5)

`tiny · small · medium · large · huge`. Two creatures with an identical body plan move
oppositely at opposite ends of this axis: a mouse skitters at high frequency with no
apparent weight; an elephant places each foot slowly with visible mass and momentum.

### 1.5 `habitat` — a SET of the media it moves through (1–3 of 3)

`ground · air · water` — and an animal may hold **any combination**, because plenty do:

| animal | habitats | consequence |
|---|---|---|
| dog | `[ground]` | one travel gait family |
| sparrow | `[ground, air]` | hops **and** flies — two |
| duck | `[ground, air, water]` | walks, flies **and** swims — three |
| frog, crocodile, penguin | `[ground, water]` | two, and the gaits look nothing alike |
| fish | `[water]` | one |

**This is a set, not a single value, and that is a movement fact rather than a taxonomy
nicety.** A duck's legs do three different things — a waddling stride, tucked under in
flight, webbed paddling underwater — and a model that forces it to pick one medium cannot
describe two of them. The pose vocabulary already separates `walk`/`fly`/`swim`, so the
clause registries need no new machinery: `legs.json` simply has an entry per pose, and a
three-habitat animal reaches three of them.

Two derived rules:

- **Eligible travel poses = the union over the set.** `ground` admits `walk`/`run`, `air`
  admits `fly`, `water` admits `swim`. A duck is eligible for all four; a fish for one.
- **`primary_motion` (§1.6) is still exactly one** — the medium the animal is *most* itself
  in. A duck is a swimmer that also walks and flies. That single value is what the tier cap
  must never clip (`SPEC_BUNDLE_MOTION_CONTRACT` §3.4), which is why it stays singular even
  though the habitat is not.

This resolves what Rev.1 deferred as an `amphibious` habitat. A fourth enum value would have
been wrong: it collapses three genuinely different combinations (`ground+water`,
`ground+air`, all three) into one label, and the whole point of the axis is that the
combination determines which gaits exist.

### 1.6 `primary_motion` — the signature gait (7)

`walk · run · fly · swim · slither · hop · climb`

The one motion the animal is *for*. It has two jobs beyond prompting:

- it is the pose that must never be dropped when the tier cap clips a build
  (`SPEC_BUNDLE_MOTION_CONTRACT` §3.4 — this is that spec's `signature_pose`, and the two
  should read the same field rather than duplicating it);
- it tells the composer which pose gets the animal's most specific description.

---

## 2. The body profile

### 2.1 Shape

```json
{
  "clade": "mythic",
  "limbs": { "legs": 4, "arms": 0, "wings": 2, "tail": "plain", "fins": 0 },
  "surface": "scales",
  "size": "huge",
  "habitat": ["ground", "air"],
  "primary_motion": "fly"
}
```

A dragon walks *and* flies, so its habitat set holds both — which is exactly why the tier
cap dropping `fly` (`SPEC_BUNDLE_MOTION_CONTRACT` §3.4) produced a bundle that could still
walk and was still wrong: `primary_motion` said what the animal was *for*, and the clip that
depicted it was the one discarded.

### 2.2 It identifies the animal — the design test

| vector | animal |
|---|---|
| `humanoid · skin · 2 arms · 2 legs` | human |
| `primate · fur · 2 arms · 2 legs · no tail` | ape |
| `primate · fur · 2 arms · 2 legs · prehensile tail` | monkey |
| `mammal · fur · 4 legs · plain tail · medium` | dog |
| `reptile · scales · 4 legs · plain tail · small` | **turtle / lizard** |
| `bird · feathers · 2 legs · 2 wings · small` | sparrow |
| `mythic · scales · 4 legs · 2 wings · huge` | dragon |
| `mythic · scales · 2 legs · 2 arms · 2 wings` | gargoyle |
| `mythic · skin · 2 arms · 0 legs · fluke · water` | mermaid |
| `fish · scales · 0 limbs · fluke · 4 fins` | fish |
| `reptile · scales · 0 limbs · no fins` | snake |
| `insect · chitin · 6 legs · 4 wings · tiny` | dragonfly |

Human separates from ape on `surface` alone; monkey from ape on `tail` alone. If a proposed
axis value never changes which animal a reader names, it is not carrying movement
information and does not belong.

### 2.3 The vector is a cache key

Wolf, coyote and husky all resolve to `mammal · fur · 4 legs · plain tail · medium · ground`
— one vector, one set of composed prompts. The long tail collapses onto a small set of real
combinations. §2.2's twelve rows exist as *named* plans so common animals resolve with no
model call; an unnamed vector still composes, so the table never gates.

### 2.4 The silence, measured (Rev.3)

Rev.1 argued from one anecdote. Here is the whole repo, surveyed 2026-07-26 against the
working tree. **Method:** for each of the 7 registered profiles, take the limb groups its body
plan implies (`quadruped` → legs + tail; `winged_flyer` → legs + wings + tail; `serpentine` →
body; and so on), and for each *enabled* pose ask whether the motion prompt (`action` +
`suffix`) and the anchor clause (`control.pose`) mention that group at all — a
case-insensitive word match on the group's obvious vocabulary (`leg|paw|foot|feet|stride`,
`wing`, `tail|fluke`, `fin|flipper`, `arm|hand|knuckle`).

| profile | limb groups | enabled poses | motion prompt silent | anchor silent | either |
|---|---|---|---|---|---|
| `aquatic` | 2 | 7 | 3 | 5 | 5 |
| `avian` | 2 | 9 | 7 | 6 | 7 |
| `humanoid` | 2 | 9 | 2 | 0 | 2 |
| `primate` | 2 | 8 | 4 | 5 | 5 |
| `quadruped` | 2 | 8 | **8** | 7 | **8** |
| `serpentine` | 1 | 7 | 1 | 2 | 2 |
| `winged_flyer` | 3 | 9 | **8** | **8** | **8** |
| **total** | | **57** | **33** | **33** | **37** |

**37 of 57 poses (65%) are silent about at least one limb the body has, on at least one
surface.** Both surfaces fail at the same rate, independently — which is why §0.7 scopes both.

Three readings that matter more than the headline number:

- **The default profile is the worst.** `quadruped` — what every unmatched animal resolves to
  (`registry.default`) — never mentions the tail in *any* of its eight poses, including `walk`
  and `run`. The most-used body type in the factory animates a tail nobody described.
- **`winged_flyer` is still the worst-off overall despite the hand-fix.** `908e855` corrected
  `walk` and `run`; the other seven poses remain silent about legs, tail, or both. Fixing the
  two poses somebody had *noticed* left 78% of that profile untouched — the precise reason
  §7's step 3 no longer starts there (§7).
- **`humanoid` is nearly clean** (2 silent, 0 anchors) **because it is the newest**, authored
  in `b8a8d56` by someone with this defect fresh in mind. That is the honest counter-argument
  and it is worth stating: a careful author *can* get this right. They cannot get it right
  *durably* — `humanoid` is one profile, authored once, with no mechanism holding it there
  when the tenth pose or the eighth body type arrives.

**The caveat, stated so the number is not oversold.** A keyword miss is not automatically a
defect: a sleeping bird's legs are folded under it and arguably contribute nothing, and a
regex cannot tell a considered omission from an oversight. **That is exactly the finding.**
Free text cannot distinguish those two either — the reader cannot, the guard test cannot, and
the model certainly cannot. Under §3 the same case is an explicit `null`: *considered, and it
contributes nothing.* The survey does not claim 37 bugs; it claims **37 unanswered questions**,
and the deliverable is that the answer becomes a value in a file rather than an inference from
silence.

---

## 3. Clause registries — one file per axis value

Same plugin pattern as `motion_profiles/` and `design_axes/`: one self-contained file plus a
registry entry, and adding a value never edits a consumer.

```
body_profile/
  registry.json
  clades/    mammal.json  reptile.json  bird.json  insect.json  …
  limbs/     legs.json  arms.json  wings.json  tail.json  fins.json
  surfaces/  fur.json  feathers.json  scales.json  skin.json  chitin.json  slime.json
  sizes/     tiny.json … huge.json
```

Each file maps **canonical pose → clause**. Where a count changes the description rather
than a number, the clause is keyed by count:

```json
// limbs/legs.json
{ "walk": { "2": "two legs alternating through a full stride, feet placing and pushing off",
            "4": "four legs cycling in a diagonal-pair gait, paws placing and pushing off",
            "6": "six legs moving in alternating tripods",
            "0": null },
  "fly":  { "*": "legs tucked up beneath the body" },
  "swim": { "*": "legs trailing, contributing little" } }

// limbs/wings.json
{ "walk": "wings kept folded at its sides, not beating",
  "run":  "wings folded back against the body",
  "fly":  "wings beating through a full downstroke-upstroke cycle",
  "sleep": "wings tucked close, one draped over the body" }

// clades/reptile.json
{ "_stance": "limbs sprawled out to the sides, belly low to the ground",
  "_spine":  "body undulating side to side with each step",
  "_cadence": "deliberate, stop-start" }
```

`null` means *this limb group contributes nothing to this pose* — an explicit answer, which
is what distinguishes "considered and irrelevant" from the silence that produced the
hovering dragon.

---

## 4. Composition

### 4.1 The rule

```
prompt(pose) = base(animal)
             + clade.stance + clade.spine
             + Σ limb_clause(group, count, pose)      for every group present
             + surface_clause(pose)
             + size_cadence(pose)
             + shared suffix (in place, no camera movement, no panning)
```

`compose_pose_prompt` (`motion_profiles/__init__.py:241`) keeps its signature and its
byte-identical output for any profile not yet migrated (§4.3). Today that function is a
one-line `MOTION_PROMPT_TEMPLATE.format(animal, pose.action, pose.suffix)` — the whole
composition step is the concatenation this spec replaces it with.

### 4.2 Worked — the four walks

Same rules, four bodies, four correct prompts:

- **turtle** `reptile · scales · 4 legs · small` → *four legs cycling in a diagonal-pair
  gait · limbs sprawled to the sides, belly low · body undulating side to side · scale plates
  shifting and catching the light · deliberate, stop-start pace*
- **dog** `mammal · fur · 4 legs · plain tail · medium` → *four legs cycling in a
  diagonal-pair gait · legs directly beneath the body · spine flexing with each stride · tail
  swaying for balance · fur rippling along the flanks · steady mid-paced cadence*
- **human** `humanoid · skin · 2 legs · 2 arms` → *two legs alternating through a full
  stride · fully upright, hands free · torso stable, hips counter-rotating · arms swinging in
  counter-rhythm to the legs · even heel-to-toe cadence*
- **dragon** `mythic · scales · 4 legs · 2 wings · plain tail · huge` → *four legs cycling in
  a diagonal-pair gait · **wings kept folded at its sides, not beating** · tail swaying
  counter to the body · scale plates shifting · slow, ponderous, each footfall carrying
  visible weight*

The bolded clause is the one whose absence produced the bug — and which a human has since
typed into `winged_flyer.json` by hand (`908e855`). Under composition it cannot be absent for
*any* winged body, because the body profile declares wings and §5.1 fails the build if
`wings.json` has no `walk` entry. The difference between the two is not the wording; it is
that one of them holds for the next winged animal and the next pose without anyone
remembering.

### 4.3 Override — the Motion Lab keeps its job

A pose may pin an authored prompt for a given body profile:

```json
"overrides": { "walk": { "action": "…", "suffix": "…", "_why": "author's note" } }
```

Composition runs for everything else. An override is explicit, listed in the Lab, and
covered by §5.3's report — the opposite of free text, where every prompt was silently
hand-made and nothing could tell a considered wording from an oversight. Migration is
therefore incremental: **today's seven profiles** (`aquatic`, `avian`, `humanoid`, `primate`,
`quadruped`, `serpentine`, `winged_flyer`) start fully overridden — 57 poses, every one
pinned — and lose overrides pose by pose as composed output is reviewed in the Lab. Day one
is therefore provably a no-op: every prompt is an override, so every prompt is today's.

### 4.4 The second surface — the anchor clause (Rev.3)

Since the pose-anchor work landed, a pose carries **two** prompts, not one, and both come from
the same body plan:

| surface | field | consumed by | drafted by |
|---|---|---|---|
| motion prompt | `action` + `suffix` | Wan I2V loop (`compose_pose_prompt`) | a human |
| anchor clause | `control.pose` | the Z-Image anchor still, swapped in for `base_pose` (`anchor_clause`, `SPEC_MOTION_PROFILES` §3.9.1) | a human, optionally drafted by `ai_purposes/pose_clause.json` |

All 57 enabled poses across all 7 profiles carry an anchor clause today, and §2.4 measures 33
of them silent about a limb — the same rate as the motion prompts, failing independently.
Rev.2 did not mention this surface at all, which made §0.2's rule quietly half-true.

**They are one composition with two projections, not two systems.** A limb clause has a
**moving** form (*"four legs cycling in a diagonal-pair gait, paws placing and pushing off"*)
and a **still** form (*"legs mid-stride, one forward and one back"*) — the same fact about the
same limb, phrased for a video prompt or for a single anchor frame. So each clause file gains
a parallel key rather than a parallel file:

```json
// limbs/legs.json
{ "walk": { "4": { "motion": "four legs cycling in a diagonal-pair gait, paws placing and pushing off",
                   "static": "legs mid-stride, one forward and one back, side profile" },
            "0": null } }
```

Three consequences worth pinning:

- **`pose_clause.json` keeps its job and gets a better input.** It drafts for a *human* who
  edits before saving (that is its stated contract). Under composition it drafts a
  **clause-file entry** — reviewed once, reused by every animal sharing that axis value —
  instead of one profile's one pose. Its `movement_class` + example-animal input becomes the
  vector, which is strictly more information.
- **The anchor is not a shorter motion prompt.** It is static posture, no camera or lighting
  directions, no species name — the discipline `pose_clause.json` already enforces. A composer
  that emitted the motion clause into the anchor would regress the anchor work, so `static` is
  authored, never derived.
- **§5.1's completeness test covers both keys.** A clause file with `motion` and no `static`
  fails the build, for the same reason a missing pose entry does.

**Sequencing:** the motion prompt migrates first (§7 steps 1–3) because that is where the
known defect shipped and where the Lab preview already shows the result. The anchor follows as
step 3b against clause files that already exist. Composing the anchor is **not** optional work
to be dropped for scope: leaving it hand-authored keeps 33 silent strings and half the
guarantee (§0.7).

---

## 5. Classification and validation

### 5.1 Guard tests

- **Completeness.** For every body profile in §2.2's named table, and for every *enabled*
  pose, **every limb group present resolves to a clause or an explicit `null`** — in **both**
  the `motion` and `static` forms (§4.4). A missing entry fails the build. This is the
  hovering-dragon test, and it is the mechanized form of §2.4's survey: the same question,
  asked by the build instead of by a regex after the fact.
- **Closed vocabularies.** Every axis value in a body profile exists in its registry; every
  registry file covers every canonical pose.
- **Clade completeness.** Every clade declares `_stance`, `_spine`, `_cadence`.
- **Primary-motion agreement.** A profile's `primary_motion` is an enabled pose. It is the
  same field the tier cap must never clip; see §7 step 6 for why there is one field to define
  rather than two to reconcile.
- **No pose invention.** The union of all clause files' keys is a subset of
  `CANONICAL_POSES` (§0.5).

### 5.2 The classifier — one purpose, round-tripped

A single `body_profile_classify` purpose (`ai_purposes/`, `tier: fast`) returns the whole
vector in one call, following `motion_classify.json`'s established shape: the **live**
vocabularies are passed in as template vars and the answer is validated caller-side, so the
purpose file never lists values and adding one never edits it.

```json
{ "clade": "reptile", "limbs": {"legs": 4, "tail": "plain"},
  "surface": "scales", "size": "small", "habitat": ["ground"],
  "primary_motion": "walk" }
```

Degradation follows `webui/motion_resolver.py` exactly: any invalid field falls back to the
**motion profile's declared default body profile** (quadruped → `mammal · fur · 4 legs ·
plain tail · medium`), so classification only ever *refines* and never starts from nothing.
Resolution never raises; standalone/no-API-key mode still works.

**Round-trip check.** Because a vector names its animal (§2.2), the classifier can be
verified cheaply: classify `"gorilla"` → vector → ask the model *"what animal is this?"* → a
non-ape answer means the classification is wrong. One fast call against a ~3-minute GPU
build is worth it; run it when the resolved vector is unnamed, i.e. exactly when confidence
is lowest.

### 5.2.1 Growing the axes from confusions, not from opinion

A failed round-trip is more than a failed check. If `"pangolin"` classifies to a vector that
names back as `"armadillo"`, **two animals share a vector** — the axis set has no feature
separating them. That is the same signal the 1970s `ANIMAL` program acted on when it guessed
wrong and asked *"what question would have told them apart?"*, and it is the only evidence
worth growing this registry on.

Log every collision as `{animal, vector, named_back}`. A human reviews the queue and asks
**one** question, which is the whole gate:

> Does the distinguishing feature change **how the animal moves**?

- **Yes** → it is a candidate axis value, on evidence. *Pangolin vs. armadillo: overlapping
  keratin scales that flex versus a rigid bony shell. That is a different secondary motion —
  a new `surface` value earns its place.*
- **No** → the shared vector is **correct**, and both animals should genuinely animate alike.
  Record the pair as resolved so it stops resurfacing. *Wolf vs. coyote: same gait, same
  everything that moves. One vector is the right answer, not a gap.*

**The gate exists because the obvious growth path is the wrong one.** Plenty of features
discriminate animals beautifully and say nothing about movement — diet, colour, whether it is
a pet, whether it is bigger than a breadbox. An axis set optimised for *identification* would
fill up with those and end up naming animals brilliantly while prompting none of them.
Identification is this spec's validation; movement is its objective. Every axis value must
answer to §1's test — it names a stance, a limb behaviour, a secondary motion, or a cadence —
or it does not go in, however well it splits the space.

### 5.3 Lab surface

The Motion Lab shows, per pose: the resolved vector, each contributing clause **attributed to
its axis**, the composed result, and whether an override is pinned. An author who disagrees
with the output can then see *which axis* produced the wording and fix the clause for every
animal that shares it, rather than hand-patching one profile.

### 5.4 Seeding from public trait databases — references, not a dependency

Open animal-trait databases exist and are worth harvesting **once, offline, to seed §2.3's
named-vector table**. They are deliberately not a runtime dependency (see the boundary at the
end of this section). Surveyed 2026-07-26:

| source | what it gives us | usable for |
|---|---|---|
| [EOL TraitBank](https://media.eol.org/traitbank) — ~1.7M taxa, 11M+ trait records from 50+ sources, Darwin Core / semantic-web terms ([registry](https://kghub.org/kg-registry/resource/eol-traitbank/eol-traitbank.html)) | habitat, life history, some body attributes | `habitat`, partial |
| [AnimalTraits](https://www.nature.com/articles/s41597-022-01364-9) — curated body mass, metabolic rate, brain size, hand-extracted from peer-reviewed papers, plain CSV ([repo](https://github.com/animaltraits/animaltraits.github.io)) | **real body-mass numbers** | `size` bucket thresholds |
| [Wikidata](https://www.wikidata.org/wiki/Q729) (public SPARQL) / GBIF | taxonomy, complete and free | `clade` |
| [Animal locomotion](https://en.wikipedia.org/wiki/Animal_locomotion) (survey article) | the locomotion-mode vocabulary itself | sanity-checking `primary_motion` |

**The useful finding is what is missing.** No database records limb counts or integument as
traits, because in biology they are *implied by taxonomy* — nobody writes a row saying "bird:
2 legs, 2 wings, feathers." Our axes look unusual to a biologist precisely because they make
explicit what biology encodes in the clade.

That inverts into the seeding strategy: **clade largely implies the rest of the vector.**

```
Wikidata taxon → bird → 2 legs, 2 wings, feathers, plain tail, [ground, air]
```

A taxonomy join populates most of a body profile mechanically, and the classifier (§5.2)
earns its keep on the **exceptions** — penguins and ostriches that cannot fly, snakes as
legless reptiles, whales as legless mammals, bats as flying mammals. That is a short
enumerable list, not an open problem. It is also why each motion profile carries a
`default_body_profile` (§6): that field is the join point where taxonomy lands.

**The boundary — why none of these is the source of truth:**

1. **No mythic creatures.** Dragons, gargoyles, mermaids and phoenixes are a real fraction of
   this factory's output, and no biological database will ever carry them. Any external
   source is structurally incapable of covering the catalog.
2. **Wrong granularity, on purpose.** These are taxonomic and fine-grained; §1's axes are
   coarse by design. Collapsing 1.7M taxa onto 9 clades is lossy deliberately — the question
   is *how does it move*, not *what is it*.
3. **Patchy exactly where we need it.** Locomotion and body covering are among the least
   consistently populated fields, because they are the least useful for ecology research.

So: harvest once into the named-vector table, use AnimalTraits' mass figures to set defensible
`tiny`…`huge` cutoffs rather than guessing, and keep resolution entirely in-repo. Recorded
here so the next person does not spend a week evaluating trait databases to reach the same
conclusion.

---

## 6. What this changes in `motion_profiles/`

Responsibilities split; nothing is deleted until its overrides are retired (§4.3).

| owns | before | after |
|---|---|---|
| `movement_class`, `level`, `keywords`, `view`, `base_pose`, enabled poses | motion_profile | **unchanged** |
| per-pose `action` / `suffix` | motion_profile (free text) | composed; profile keeps only overrides |
| per-pose anchor clause (`control.pose`) | motion_profile (free text, §4.4) | composed `static` form; profile keeps only overrides |
| body plan | *nowhere* | body profile (§2) |
| how a limb behaves per pose | *nowhere* | clause registry (§3) |

Each motion profile gains a `default_body_profile` — the vector to use when classification is
unavailable, which is also what makes the **seven** current profiles work unchanged on day
one. The seeding is mechanical, and stating it here is what makes step 2 a half-day rather
than a design exercise:

| profile | `default_body_profile` |
|---|---|
| `quadruped` (registry default) | `mammal · fur · 4 legs · plain tail · medium · [ground] · walk` |
| `avian` | `bird · feathers · 2 legs · 2 wings · small · [ground, air] · fly` |
| `winged_flyer` | `mythic · scales · 4 legs · 2 wings · plain tail · large · [ground, air] · fly` |
| `aquatic` | `fish · scales · 0 legs · fluke · 4+ fins · medium · [water] · swim` |
| `serpentine` | `reptile · scales · 0 limbs · medium · [ground] · slither` |
| `primate` | `primate · fur · 2 legs · 2 arms · plain tail · medium · [ground] · climb` |
| `humanoid` | `humanoid · skin · 2 legs · 2 arms · no tail · medium · [ground] · walk` |

Two of these are lossy on purpose and the classifier (§5.2) exists to refine them:
`winged_flyer` covers dragons (`scales`) and bats (`fur`) alike, and `aquatic` covers fish
(`scales`) and dolphins (`skin`) — the mixed-surface classes
`design_axes/surface_keywords.json` already documents as the reason surface is not a motion
field. The default is the coarse-but-correct floor, never the answer.

---

## 7. Implementation order

**Not started, and not to be started** — this spec is PARKED (see the status block). The order
below is what to follow *if* one of the unpark triggers fires; it is not a queue.

1. **Registries + composer, no wiring.** `body_profile/` files, `compose()`, §5.1 guard
   tests. Nothing calls it; the build gate proves the data is complete.
2. **Default body profiles** on the **seven** motion profiles (§6's table), and the composer
   wired behind a full override set — output is byte-identical to today, and the Lab can show
   composed vs. authored side by side.
3. **Retire motion-prompt overrides pose by pose**, reviewing in the Lab, **worst-first by
   §2.4's measurement**:
   1. **`quadruped`** — 8 of 8 poses silent, and it is `registry.default`, so it is what every
      unmatched animal gets. Highest blast radius in the repo.
   2. **`winged_flyer`** — 8 of 9 silent. Note the change from Rev.2, which named `walk` and
      `run` first: those two are precisely the poses `908e855` already hand-fixed. Rev.2's
      instinct was to start where somebody had *noticed* a bug; §2.4 says to start where the
      unanswered questions actually are, and the seven other poses in that profile are where
      they are.
   3. **`avian`** (7 of 9), then `aquatic` and `primate` (5 each), `serpentine` (2),
      `humanoid` (2, last — it is nearly clean).
3b. **Retire anchor-clause overrides** (§4.4) on the same worst-first order, once each
   profile's motion prompts are composed and reviewed.
4. **Seed the named-vector table** (§5.4) — one offline taxonomy join plus AnimalTraits mass
   figures for the `size` cutoffs. Cheap, and it means the classifier is only ever consulted
   for animals the table misses.
5. **Classifier** (§5.2) + round-trip check, and the confusion queue (§5.2.1).
6. **Define the signature pose once.** Rev.2 wrote this step as "point
   `SPEC_BUNDLE_MOTION_CONTRACT` §3.4's `signature_pose` at `primary_motion`." As of
   2026-07-26 **that field does not exist** — §3.4 is the unimplemented part of an otherwise
   shipped spec, and `signature_pose` appears in no code or data file. So there is nothing to
   reconcile and no migration to write; there is one field, needed by two consumers, to be
   added once. **Whichever spec ships first owns the name, and the other reads it** — if §3.4
   lands first (it is marked highest-priority there), this spec's `primary_motion` **is**
   `signature_pose` and §1.6 is its second consumer, not a second field. Coordinating this now
   costs one sentence; discovering it later costs a dual-write.

Steps 1–2 are inert by construction — every prompt is an override, so every prompt is today's.
Step 3 is where generated output changes, one pose at a time, each reviewable before it ships.

---

## 8. Consistency checks (repo-wide rules)

- **Engine vs. content.** The composer names no animal, no clade and no limb — it walks the
  body profile and concatenates whatever the registries hold. Every value is a data file.
- **Plugin + registry with a guard test that fails on a half-formed entry** — §5.1, matching
  `motion_profiles/` and `design_axes/`.
- **GPU-less posture.** `body_profile/` is pure data, imports nothing, and stays importable
  on the web tier. No ML dependency enters `pet_factory`'s data subpackages.
- **Adding an axis value is one file + one registry line**; adding a canonical pose is one
  line per clause file, and §5.1 fails until every file has it.
- **Specs are cited by section from code comments**, per repo convention.
- **The four test questions** (repo `CLAUDE.md`), answered:
  *Does a new body type require an engine change?* No — one vector, and the composer never
  learns its name. *Does a new feature touch unrelated files?* No — a new axis value is one
  file plus one registry line; `legs.json` never learns about reptiles. *Does a third-party
  integration modify owned paths?* Not applicable — §5.4's trait databases are harvested
  offline into data and are never a runtime dependency. *Does a bug in one variant force
  debugging shared code?* This is the one to watch: a clause file **is** shared across every
  animal with that axis value, which is the whole payoff (fix once, fixes all) and also the
  blast radius (break once, breaks all). The override (§4.3) is the escape hatch that keeps a
  single bad animal from being a reason to edit shared data.

---

## 9. Open items

- **Multi-limb animals beyond the table** — tentacles (octopus) and claws (crab) are named in
  §2.2 but have no clause file in the v1 registry set. One file each when a real pet needs
  one; the composer needs no change.
- **Where the new surface values live** (Rev.3). §1.3 recommends `skin`/`chitin`/`slime` ship
  motion-only, resolved for prompting and absent from `design_axes/surface_keywords.json`, so
  a new movement fact does not silently change which dropdowns a user sees at step 2. That
  splits one word across two vocabularies and wants a decision, not a default —
  `SPEC_PET_DESIGN_AXES`' owner should confirm before step 1 writes the files.
- **The catalog is not yet a source of vectors** (Rev.3). `animal_catalog/catalog.json` holds
  two entries, both `fur`/`quadruped`, so in practice §5.4's seeding lands in the named-vector
  table and the keyword map, not the catalog. Worth revisiting if the catalog grows: two
  places that resolve an animal's body facts is one more than the design allows.
- **The host's habitat model is singular.** §1.5 makes habitat a set on the factory side,
  which is correct for prompting: a duck needs `walk`, `fly` and `swim` clauses. The DatsMe
  host still binds **one** habitat per pet and only two gait slots, so a duck that ships all
  three clips will animate in one medium. That is a host-side limit, tracked there, and it
  does not block this spec — the clips are correct either way, and a bundle that depicts
  more than the host can currently drive is the right failure direction.
