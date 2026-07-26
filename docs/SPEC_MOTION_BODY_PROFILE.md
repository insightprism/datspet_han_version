# SPEC — Body profile: composing movement prompts from what an animal *is*

**Status:** Design — **Rev.2** (2026-07-26), for review. Rev.2 makes `habitat` a SET (a
duck walks, flies and swims — §1.5), adds the confusion-driven axis-growth loop (§5.2.1), and
surveys the public trait databases worth seeding from (§5.4). Replaces per-body-type hand-written
motion prompts with prompts **composed** from a small structured description of the animal:
its clade, limbs, surface, size, habitat and primary motion. The goal is that the engine can
write an accurate `walk` prompt for a turtle, a dog, a human and a dragon *without anyone
having authored four walk prompts* — because the data says how each of those bodies walks.

Builds on **`docs/archive/SPEC_MOTION_PROFILES.md`** (the body-type registry that resolves
which poses exist) and **`docs/SPEC_MOTION_PROFILE_ADMIN.md`** (the Motion Lab that authors
and previews them). Grounded against the working tree.

**Repos touched:** `datsme-pet-factory_wu` only. `CANONICAL_POSES` is unchanged (§0.5), so
the bundle contract, the sheet layout and the DatsMe host are all untouched.

**Dependency:** none. Ships behind an override (§4.3) so existing profiles keep their
current prompts until each is migrated.

---

## 0. The core decisions (read this first)

1. **A prompt is composed, not authored.** Today each profile carries a free-text `action` +
   `suffix` per pose. Free text has no structure to check, which is how
   `winged_flyer`'s `walk` came to read *"hovering forward with steady wing beats"* — a
   hover prompt wearing the name `walk`, describing wings and never mentioning legs. It
   generated exactly what it said, and the DatsMe host then translated that pet along the
   floor as a ground gait: a dragon skating on its belly, flapping. Composition makes the
   omission impossible to express.

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

**Already resolved per animal today** — `animal_catalog` tags `surface`,
`design_axes/surface_keywords.json` classifies it, and `coat`/`plumage`/`scales` axes gate on
it. This spec adds a *second consumer*; no new classification, no new vocabulary for the
first three.

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

`compose_pose_prompt` (`motion_profiles/__init__.py:215`) keeps its signature and its
byte-identical output for any profile not yet migrated (§4.3).

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

The bolded clause is the one whose absence produced the bug. Under composition it cannot be
absent, because the body profile declares wings and §5.1 fails the build if `wings.json`
has no `walk` entry.

### 4.3 Override — the Motion Lab keeps its job

A pose may pin an authored prompt for a given body profile:

```json
"overrides": { "walk": { "action": "…", "suffix": "…", "_why": "author's note" } }
```

Composition runs for everything else. An override is explicit, listed in the Lab, and
covered by §5.3's report — the opposite of free text, where every prompt was silently
hand-made and nothing could tell a considered wording from an oversight. Migration is
therefore incremental: today's five profiles start fully overridden and lose overrides pose
by pose as composed output is reviewed in the Lab.

---

## 5. Classification and validation

### 5.1 Guard tests

- **Completeness.** For every body profile in §2.2's named table, and for every *enabled*
  pose, **every limb group present resolves to a clause or an explicit `null`.** A missing
  entry fails the build. This is the hovering-dragon test.
- **Closed vocabularies.** Every axis value in a body profile exists in its registry; every
  registry file covers every canonical pose.
- **Clade completeness.** Every clade declares `_stance`, `_spine`, `_cadence`.
- **Primary-motion agreement.** A profile's `primary_motion` is an enabled pose, and matches
  the `signature_pose` that `SPEC_BUNDLE_MOTION_CONTRACT` §3.4 seeds into the tier cap.
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
| `movement_class`, `level`, `keywords`, enabled poses | motion_profile | **unchanged** |
| per-pose `action` / `suffix` | motion_profile (free text) | composed; profile keeps only overrides |
| body plan | *nowhere* | body profile (§2) |
| how a limb behaves per pose | *nowhere* | clause registry (§3) |

Each motion profile gains a `default_body_profile` — the vector to use when classification is
unavailable, which is also what makes the five current profiles work unchanged on day one.

---

## 7. Implementation order

1. **Registries + composer, no wiring.** `body_profile/` files, `compose()`, §5.1 guard
   tests. Nothing calls it; the build gate proves the data is complete.
2. **Default body profiles** on the five motion profiles, and the composer wired behind a
   full override set — output is byte-identical to today, and the Lab can show composed vs.
   authored side by side.
3. **Retire overrides pose by pose**, reviewing in the Lab. `winged_flyer`'s `walk` and `run`
   first: they are the ones known to have been wrong.
4. **Seed the named-vector table** (§5.4) — one offline taxonomy join plus AnimalTraits mass
   figures for the `size` cutoffs. Cheap, and it means the classifier is only ever consulted
   for animals the table misses.
5. **Classifier** (§5.2) + round-trip check, and the confusion queue (§5.2.1).
6. **Point `SPEC_BUNDLE_MOTION_CONTRACT` §3.4's `signature_pose` at `primary_motion`** so the
   tier cap and the composer read one field.

Steps 1–2 are inert by construction. Step 3 is where generated output changes, one pose at a
time, each reviewable before it ships.

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

---

## 9. Open items

- **Multi-limb animals beyond the table** — tentacles (octopus) and claws (crab) are named in
  §2.2 but have no clause file in the v1 registry set. One file each when a real pet needs
  one; the composer needs no change.
- **The host's habitat model is singular.** §1.5 makes habitat a set on the factory side,
  which is correct for prompting: a duck needs `walk`, `fly` and `swim` clauses. The DatsMe
  host still binds **one** habitat per pet and only two gait slots, so a duck that ships all
  three clips will animate in one medium. That is a host-side limit, tracked there, and it
  does not block this spec — the clips are correct either way, and a bundle that depicts
  more than the host can currently drive is the right failure direction.
