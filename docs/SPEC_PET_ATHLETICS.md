# SPEC_PET_ATHLETICS — what a pet's numbers are, and who writes them

**Status: Rev.1 (2026-08-03) — SPLIT OUT OF `SPEC_PET_ARENA`, content unchanged.** Sections §2–§5
are that spec's text verbatim; nothing here is new. What changed is ownership: the game moved to
DatsMe (`../../datsme_me/docs/SPEC_ARENA_MIGRATION.md`) and this half did not.

**This is the contract between the factory and the game.** DatsPet **mints** a pet's athletics block
at build time and writes it into `manifest.json`; the game **reads** it and never writes it. Two
products, one interface, and this file is the interface.

**Section numbers are deliberately NOT renumbered.** §2–§5 keep the numbers they had, and the game
spec keeps §6 onward, so every `SPEC_PET_ARENA §N` citation already in either repo stays
semantically correct — only the document name changes. The gap where §6–§12 used to be is the
price of that, and it is much cheaper than re-pointing 81 citations by hand.

**Who reads what:**

| | writes | reads |
|---|---|---|
| DatsPet (`webui/pet_athletics.py`, `pet_factory/athletics/`) | ✅ mints at build | ✅ |
| The game (`../../datsme_me/petgame_sidecar/`) | never | ✅ every race |

**The game's half is `../../datsme_me/docs/SPEC_PET_ARENA.md`** — events, the race loop, challenges,
fairness, monetization. It cites §2 and §5 of this file across repos, which is correct: it consumes
the contract it does not own.

---

## §0 The decisions that belong to the contract

*(The other rows live in the game spec. Numbers preserved — 0.3, 0.4 and 0.8 are the athletics
decisions; the rest were never about the numbers.)*

| # | Decision | Choice |
|---|---|---|
| 0.3 | Where stats come from | **Minted at BUILD TIME and written into `manifest.json`** as an `athletics` block (owner's instruction, §4). |
| 0.4 | Uniqueness | **Two sources, deliberately separated** (§7.5 in the game spec): permanent per-attribute identity nudges decoded from the pet id (Rev.7 — deterministic), and a small per-race roll that makes each running of an event different. |
| 0.8 | Legacy pets | **Every pet ever built can compete on day one**, via a read-time derivation from facts already in its manifest (§5). |

### 0.14 The posture that must not change

*(Items 1 and 3 govern the game and live there. These two are the contract's.)*

2. **No species names in code.** Stats derive from declared data (`movement_class`, the pose set, the
   design block), never from `if species == "cheetah"`. Same rule the motion system already lives
   under.
4. **The GPU-less posture.** The content package is pure data — stdlib only — which is what lets
   `pet_factory.athletics` be importable on a box with no ML stack.

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

### 3.4 The identity nudges — uniqueness decoded from the pet id

**The pet id is the athlete** (Rev.7, the owner's design). Three bounded modifiers — one per
attribute — decoded from the id: sha256 of the UTF-8 id, one 4-byte segment per attribute, folded
onto ±`identity_nudge_range` (`athletics/identity.json`, default `±0.08`). Wide enough that two
identical designs are distinguishable, narrow enough that design still dominates — and each
attribute takes its own segment, so identity has *shape*, not just level. This is the owner's
*"certain things can be random to provide uniqueness to the animal"* made deterministic: same id →
same athlete, forever, on any device, with nothing stored and no asset fetched.

---

## §4 The manifest block, and where it is written

### 4.1 The block

```json
"athletics": {
  "schema_version": "pet_athletics.v1",
  "table_version": "athletics.v1",
  "speed": 0.71, "power": 0.42, "endurance": 0.63,
  "land": 0.95, "water": 0.30, "air": 0.05,
  "identity_nudges": { "speed": 0.031, "power": -0.052, "endurance": 0.012 },
  "poses": ["walk", "idle", "run", "jump"],
  "minted_at": "2026-08-02T11:04:19Z"
}
```

`identity_nudges` are stored **as their own field as well as being folded into the attributes** —
belt and braces: they are always re-derivable from the pet id (§3.4), and storing them *also*
survives a future change to the nudge algorithm itself (§5.3). Losing that would mean a balance
patch or an algorithm tweak silently gives every pet a new personality.

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
2. Absent → **derive** from `movement_class` + `animations` + the pet id, with modifiers skipped
   when there is no design block, and the identity nudges decoded per §3.4/§5.2.

The arena calls only the resolver. **Nothing in the game ever branches on whether a pet was minted
with a block** — that would be a provenance branch, which §0.14 forbids.

### 5.2 A stable identity for a pet that never got a block

Nothing extra is needed: the nudges derive from the pet id (§3.4), which every context that races
a pet already has — the browser fetched the pet *by* id. Same id → same athlete, forever, with
nothing persisted and no asset fetched. (Rev.1–6 derived this from a hash of the sheet bytes; the
id is the identity itself rather than a proxy for it, and Rev.7 swapped to it.)

Three properties worth stating: it is stable across devices and reloads; it is **not** stable
across a rebuild of the same design — a rebuild mints a new id, which is correct, because that is
a different pet; and an adopted copy of a store pet carries its own id, so two children adopting
the same listing get **different athletes** — the uniqueness goal working.

### 5.3 Re-minting when the balance table changes

Balance will be wrong at first. A `table_version` bump means stored blocks are stale, and the rule
is: **the resolver recomputes from `table_version` mismatch rather than trusting a stale block**,
reusing the stored `identity_nudges` so identity survives (§4.1) — even across a change to the
nudge algorithm itself. No migration, no GPU, no re-download — the inputs are all still in the
manifest.

This is why §4.1 stores the raw inputs and the nudges rather than only the final six numbers.

---


---

## §13 The four test questions

1. **New variant → engine change?** No. A new movement class is a row in `movement_classes.json`;
   a new design modifier is a row in `modifiers.json`. `resolve_athletics` reads tables.
2. **New feature → unrelated files?** No. The mint is one call at one seam
   (`webui/app.py`'s finalize), and the tables are data.
3. **Third-party integration → owned code paths?** No. The block travels inside the bundle; a
   consumer reads it or derives it, and never asks this repo for anything.
4. **Bug in one variant → shared debugging?** Honest exception: `resolve_athletics` is shared by
   every pet. It is pure — manifest in, numbers out — so it is fixture-testable without a pet, a
   GPU or a network.

---

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
- Re-minting under a bumped `table_version` **preserves `identity_nudges`** — the
  identity-survives-rebalance rule (§4.1). This is the one that will actually catch a regression.


**`pet_factory/tests/test_pack_bundle_layout.py`** — **unchanged, and that is the assertion.** If it
needs an edit, game rules have reached the packer.

---


---

## §15 Deliberately not done

- **No stat editing.** The numbers derive from what the pet already is; a slider would make them an
  input rather than an identity.
- **No per-species tables.** §0.14.2.
- **No re-stamping of existing pets.** The stamp runs once at build, upstream of `insert_pet` so
  `bundle_sha256` covers it — re-stamping would change a pet's byte identity, which is the store's
  only per-pet key.

---

## §16 Open questions

**16.1 Should the store display stats on a listing?** If it does, it must read them through
`resolve_athletics`, **never** `manifest["athletics"]` directly: pets are stamped once and never
re-stamped, so after a `TABLE_VERSION` bump a raw read shows the old numbers while the game races
the new ones — a bug that looks exactly like the game cheating.

**16.2 The two copies of `pet_factory/athletics/`.** The game runs its own copy
(`../../datsme_me/petgame_sidecar/athletics/`). They are guarded against drift by a test on the
game's side, but the real answer is one source published twice
(`../../datsme_me/docs/SPEC_ARENA_MIGRATION.md` §2.4). Until then the guard is what keeps the debt
visible rather than silent.

**16.3 `events/` is dead weight here.** Nothing in DatsPet's production code reads an event
declaration — only `pet_factory/tests/test_athletics.py` does. The events belong with the game;
splitting the package along the same line as this spec would remove the duplication.
