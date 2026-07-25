# SPEC — Bundle motion contract (emit the specificity we resolved)

**Status:** **READY TO IMPLEMENT** — **Rev.2** (2026-07-25). Widens what
`pack_datsme_bundle` writes into a DatsMe breed bundle so the host can animate a pet at the
**same specificity this factory already resolved it at**, and so the poses a user pays GPU
for actually play. Builds on **`docs/archive/SPEC_MOTION_PROFILES.md`** (the movement layer
that resolves the profile) and **`docs/SPEC_MOTION_PROFILE_ADMIN.md`** (the editor that
authors it). Grounded against the working tree.

**Counterpart spec:** `../datsme_me/docs/SPEC_DATSME_MOTION_ENGINE.md` — the host-side
runtime motion engine that consumes this. That spec is the reason this one exists; read its
§1.5 for the host's verification of what we transmit today.

> **Rev.2 — the host half has SHIPPED (`datsme_me` 8f23469d, 2026-07-25), and this spec is
> now the remaining work.** What changed for us:
>
> - **The one ordering constraint is lifted** (§3.1). The host's trigger fix is in, so
>   `loop: false` on a `triggered` pose is safe to emit today.
> - **Nothing here is load-bearing for correctness any more, and that is deliberate.** The
>   host repaired W3 and W5 on its own side — profile-owned `timedClipWeight` and
>   `timedDwellMs` now make every `timed` pose we ship both selectable and able to hold on
>   screen, and its posture gate falls back to sheet-level `view_kind`. So the poses users
>   pay GPU for already play, on bundles we have already shipped, with no change from us.
>   **§2 is the item with real remaining value**: the specificity we resolve and then throw
>   away is fidelity the host cannot recover by any other means.
> - **The host now tolerates our current output exactly**, and has a committed fixture
>   (`web/src/pet/locomotion/__fixtures__/redCardinal.manifest.json`) plus a factory-shape
>   contract test asserting it. Changing what `pack_datsme_bundle` writes will not break a
>   host that has not shipped the reader — every field here stays optional — but it is worth
>   knowing which side the safety net is on.
> - **The red cardinal flies.** `avian_biped` resolves to a real avian profile with `fly` as
>   its travel gait, and it lands rather than freezing mid-air. `parakeet_v2` moved onto the
>   avian profile via the `bird` alias and correctly degrades to the ground habitat, because
>   its bundle ships no `fly` clip — a live illustration of why §2's `resolution` list and
>   §9.2.3's canonicalization are worth doing.

**Repos touched:** `datsme-pet-factory_wu` only. Every host-side repair (weights, dwell,
trigger dispatch) is deliberately **not** asked of this repo (§4). No partner-SDK change, no
DPP change, no ComfyUI/workflow change, **no extra GPU cost** — everything here is metadata
written at pack time plus data added to profile JSON.

**Dependency:** none. Ships independently of the host engine; every field is additive and
optional, and the host tolerates absence (§5).

---

## 0. The core decisions (read this first)

1. **The bundle is the only channel.** The host cannot ask us anything at animation time —
   it fetches a zip once, stores the manifest **verbatim**
   (`../datsme_me/api/apps/pets/pet_assets_service.py:198-201` validates only that
   `animations` is a dict), and animates from it forever. Anything we resolve and don't
   write down is lost.

2. **Two profiles, one taxonomy.** Ours (`motion_profiles/*.json`) answers *how do I draw
   this body type's clips* — Wan prompts per pose. The host's answers *how does this body
   type move on the page* — habitat, gaits, speeds. They are complementary, not competing,
   and neither should absorb the other. **This spec adds the join key** so both can resolve
   at the same specificity.

3. **Behavior policy stays host-owned.** We must **not** start emitting `rest_exit_weight` /
   `rest_dwell_ms` / `run_arrival_weight`, even though their absence is currently breaking
   things (§1, W5). Content that dictates runtime behavior is the inversion our own
   engine-vs-content rule forbids, and the host has agreed to own it
   (`SPEC_DATSME_MOTION_ENGINE` §3.4). See §4.

4. **Additive and default-inert** — the same safety property as `SPEC_MOTION_PROFILES` §6.
   Every new manifest field is optional, every new profile field defaults to today's
   behavior, and a host that has not shipped the consuming engine sees no change.

---

## 1. What we transmit today, and what it costs

`pack_datsme_bundle` (`pet_factory/factory.py:403-470`) writes a sprite PNG,
`package.json` = `{breed_id, display_name, movement_class}`, and a manifest of
`schema_version`, grid dims, `animations{name: {frames, fps, loop, runtime_role}}`,
`view_kind`/`native_facing`/`mirroring_policy`, `movement_class`.

| | What we do | What it costs on the host |
|---|---|---|
| **W1** | We resolve a profile with **four specificity levels** (`motion_profiles/__init__.py:160-185`, `SPEC_MOTION_PROFILES` §3.7) and then transmit only `movement_class` — the level-3 bucket. `profile.key` and `profile.level` are in scope at pack time (`factory.py:693`) and discarded. | The host can only ever resolve at body-type granularity. **The day a `corgi.json` level-1 profile exists, the host still receives `mammalian_quadruped` and animates a corgi with Great Dane kinematics** — the exact failure §3.7 was written to prevent, one layer down. |
| **W2** | The catalog resolves a **breed-level** pinned key (`animal_catalog/__init__.py:78-90`, breeds `corgi`/`labrador`/`tabby`/`siamese`) and the reference record carries `catalog_animal` / `catalog_breed` / the AI-classified noun (`webui/app.py:893,911`). None of it reaches the zip. | Same as W1, and it means the *curated* door — our highest-fidelity path — hands the host no more information than free-text does. |
| **W3** | `"loop": True` is hardcoded for **every** pose (`factory.py:449`), including `timed` and `triggered` ones, and we never emit `timed_buffer_ms`. | The host's timed branch computes `dur = loop ? timed_buffer_ms : natural + buffer`; with `loop:true` and no buffer that is **0 ms** — a `sleep`/`sit`/`eat` pose exits the frame it enters. |
| **W4** | We emit no **per-animation `view` block**; sheet-level view fields are constants (`factory.py:464`). The values are accurate *by construction* (every prompt says "side profile view, facing right") — but the coupling is invisible. | The host's sprite-tilt gate reads per-animation `view.view_kind`, gets `undefined`, and **tilt is dead on every bundle we ship**. And a future prompt change would make the manifest lie with nothing to catch it. |
| **W5** | We emit no behavior weights (correctly — §0.3), and the host's default strategy only names `walk`/`run`. | **Every `timed` pose a user pays for — `sleep`, `sit`, `eat` — is generated, packed, stored, and never selected.** With builds tier-capped at 2–5 poses, up to three of the five offered are invisible. *Host-side fix; listed here because it invalidates a promise we made.* |

### 1.1 Two claims in `SPEC_MOTION_PROFILES` §2 that are not true of the host

That spec's verification table is otherwise accurate and was checked against real code on
2026-07-13. Two cells were wrong, and W5 is their consequence:

- **`pick_weight` does not drive wander selection.** The host parses it
  (`web/src/pet/manifest.ts:71`) and **reads it nowhere**. The field that actually routes
  rest-exit is `rest_exit_weight`, which we do not emit.
- **§7's promise — *"`timed` (sleep) is auto-reachable from rest — generate it and the pet
  will play it on its own"* — has never held.** It needs a positive `rest_exit_weight`
  (absent) *and* a non-zero dwell (W3). Both are now being fixed, one per repo.

The correction belongs in this spec rather than in an edit to the archived one: that
document is CLOSED, and the fix is a new contract, not a re-statement of the old one.

---

## 2. The wire change — `pet_manifest.v1.1`

### 2.1 A `motion` block on the manifest

```json
"schema_version": "pet_manifest.v1.1",
"movement_class": "mammalian_quadruped",
"motion": {
  "profile_key": "corgi",
  "profile_level": 1,
  "resolution": ["breed:corgi", "species:dog", "class:mammalian_quadruped"]
}
```

- **`profile_key` / `profile_level`** — the profile we actually resolved, and how specific it
  was. Provenance: admin display, host telemetry, debugging "why does this pet move like
  that".
- **`resolution`** — the operative field: an **ordered, most-specific-first list of lookup
  keys**. The host tries each against its own registry and uses the first it has a profile
  for; if it has none, it falls back to the class rung, which is always last and always
  present.

**Why the ordered list rather than flat `species` / `breed` fields.** It keeps *specificity
semantics* on this side, where the four-level model lives, and leaves the host owning only
"which rungs do I have profiles for". When we add a level-0 (individual pet) or split
species into genus/species, we prepend a key and **no host change is required**. The
namespace prefixes (`breed:` / `species:` / `class:`) are the entire shared convention.

`movement_class` stays exactly where it is, unchanged, as the last rung — so a host that
ignores `motion` entirely behaves precisely as today.

### 2.2 Where each rung comes from

| Rung | Source | Present when |
|---|---|---|
| `breed:<key>` | `catalog_breed` on the reference record (`webui/app.py:897`), or `profile.key` when the resolved profile is level 1 | catalog door with a breed selected, or a level-1 profile matched |
| `species:<key>` | `catalog_animal`, or `profile.key` when the resolved profile is level 2 | catalog door, or a level-2 profile matched |
| `class:<movement_class>` | `profile.movement_class` | **always** |

Rungs whose source is absent are simply omitted — the list is never padded with guesses.
The txt2img door (free-text "blue jay") yields `["class:avian_biped"]` today and gains a
`species:` rung for free the moment the AI classifier's noun is carried onto the record.

### 2.3 `package.json`

Mirror the same block, for the same reason `movement_class` is already mirrored: the host's
admin catalog reads `package.json` while the runtime reads `manifest.json`
(`../datsme_me/api/routes/admin.py:1219-1233`). Divergence between the two files is a
split-fact the host has to detect; keeping them identical costs one line.

### 2.4 The schema bump is provenance only

Nothing on the host reads the pet manifest's `schema_version` (verified: no reader in
`datsme_me/web/src/pet/` or `api/apps/pets/`). Bumping to `v1.1` is safe and buys us a
version to point at in a bug report. It is not a gate and must never become one — the host's
forgiveness rule (render whatever arrives) is correct.

---

## 3. Per-pose emission fixes

### 3.1 `loop` becomes profile data (W3)

Add an optional `loop` to the `Pose` model (`motion_profiles/__init__.py:55-63`), defaulting
to `True` so every existing profile is byte-identical. The packer reads
`pose.loop` instead of the literal `True` at `factory.py:449`.

Authoring rule, enforced by the guard test: **a `triggered` pose declares `loop: false`.** A
jump that loops is not a jump. `active` and `rest` poses stay `true`; `timed` poses choose
(`sleep` loops for a buffer; a one-shot stretch does not).

> **Host coordination — UNBLOCKED as of 2026-07-25.** This was the one ordering constraint
> in the spec: the host's auto state machine never drove `triggered` clips, so a
> `loop: false` triggered pose would have held its last frame indefinitely. That is fixed
> and committed (`datsme_me` 8f23469d). The mechanism ended up simpler than the version
> this spec was written against — rather than the trigger owning the exit, the state
> machine's existing timed branch widened its condition to
> `runtime_role === "timed" || runtime_role === "triggered"`, so **one place owns every
> return to rest** and the trigger hook schedules nothing. Ship §3.1 whenever you like.

### 3.2 `timed_buffer_ms` becomes profile data (W3)

Optional per-pose, emitted only when authored. It is the host's `timed` dwell input; absent,
the host applies its own profile default. We author it only where the *content* implies a
duration (a `sleep` loop that should hold ~6 s), never as a behavior knob — the line is
"how long is this clip meaningful", not "how often should the pet sleep".

### 3.3 View fields become profile data (W4)

Add to each profile file:

```json
"view": { "view_kind": "side", "native_facing": "right", "mirroring_policy": "flip" }
```

Every current profile authors exactly today's constants, so output is unchanged. The packer
emits them at sheet level **and copies the block onto each animation entry**, which is what
revives the host's per-animation tilt gate. A pose may override (a `sleep` curled top-down,
a front-facing `idle`) via an optional per-pose `view`.

The value of the move is that the coupling becomes explicit: the prompts say "side profile,
facing right" *because* the profile declares `side`/`right`, and the guard test can assert
they agree.

---

## 4. Explicitly NOT in scope

- **We do not emit behavior weights.** `rest_exit_weight`, `run_arrival_weight`,
  `rest_dwell_ms`, `pick_weight` stay absent. W5 is repaired host-side by profile-owned
  ambient policy (`SPEC_DATSME_MOTION_ENGINE` §3.4). Emitting them would let a content
  factory dictate a host's runtime behavior — the boundary this repo's engine-vs-content
  rule exists to hold.
- **We do not rename poses to match the host's trigger.** The host's reaction trigger
  hard-codes the clip name `excited`, which our canonical set does not contain; it is being
  changed to select by `runtime_role: "triggered"` so both our `jump`/`play` and legacy
  bundles' `excited` fire. Our canonical pose set (`motion_profiles/__init__.py:39-41`) is
  unchanged.
- **No generation change.** Prompts, anchors, seeds, `_loop_wf`, pose selection, tier caps —
  all untouched. This spec adds no Wan call and no GPU second.

---

## 5. Backward compatibility

- **Old bundles keep working.** The host treats every field here as optional; a manifest
  with no `motion` block resolves by `movement_class` exactly as today.
- **New bundles work on an un-upgraded host.** Unknown manifest keys are ignored by
  `animsFromManifest` (it copies a fixed field list), and `movement_class` is unchanged, so
  a v1.1 bundle on today's host animates identically to a v1 one.
- **Every profile edit is inert by default** — `loop` defaults `True`, `view` is authored to
  today's constants, `timed_buffer_ms` is absent unless authored.
- **The admin editor stays the guardian** (`SPEC_MOTION_PROFILE_ADMIN` §0.2): the new fields
  are validated by the same shared validator the guard tests run, so the admin cannot write a
  profile the build would reject.

---

## 6. Guard tests

Added to `pet_factory/tests/test_motion_profiles.py` and `test_pack_bundle_layout.py`:

1. **Every profile declares `view`**, and its `view_kind`/`native_facing` agree with the
   prompt discipline (`side` / `right`) — the explicit form of today's implicit coupling.
2. **Every `triggered` pose declares `loop: false`**; every `rest`/`active` pose is `true`.
3. **The packer emits `motion.resolution` ending in `class:<movement_class>`**, with keys in
   strictly increasing generality and no duplicates.
4. **`manifest.json` and `package.json` carry identical `movement_class` and `motion`
   blocks** (the split-fact guard).
5. **A per-animation `view` block is emitted for every animation.**
6. **The vocabulary artifact is in sync** — see §7.

---

## 7. Publishing the vocabulary (we own it; the host mirrors it)

The host currently hand-maintains a list of known movement classes in two places, one of
which (`datsme_me/api/routes/admin.py:1162`) still reads `{mammalian_quadruped, dog, cat}` —
which is why the admin import banner calls a correct `avian_biped` bundle "not supported".

We own this vocabulary; they should not be transcribing it. Add
`scripts/export_motion_vocabulary.py` → `motion_vocabulary.json`, generated from
`registry.json` + each profile's `movement_class`:

```json
{ "version": 1,
  "classes": ["mammalian_quadruped", "avian_biped", "aquatic_swimmer",
              "limbless_serpentine", "winged_flyer"],
  "profiles": [{ "key": "avian", "level": 3, "movement_class": "avian_biped" }] }
```

A guard test asserts the checked-in artifact matches a fresh export (fail the build on
drift), and the host consumes the file instead of a hand-typed set. Adding a body type then
propagates to the host's supported-set as a data update, which is what the registry pattern
promised in the first place.

---

## 8. Implementation & cutover order

**The host shipped first — and it has (`datsme_me` 8f23469d, 2026-07-25).** That was the
correct order and the reasoning below is kept because it is the reasoning for the NEXT
cross-repo change too, not just this one. `SPEC_DATSME_MOTION_ENGINE` was implementable
against today's bundles and fixed every user-visible symptom on its own; nothing in *this*
spec produces a visible change until the host consumes it, and §3.1 was hard-blocked on the
host's trigger fix (now lifted).

The decisive argument is asymmetric reversibility: **a bundle is an immutable artifact.**
The host stores the manifest verbatim and animates from it forever, so a field written in the
wrong shape is baked into every pet generated until someone pays the GPU cost to regenerate
them. A host deploy rolls back; shipped zips do not. Define the consumer, prove it against a
real bundle, *then* start stamping permanent data. A secondary benefit: once the host engine
is live it becomes the test harness for this spec — regenerate a bird and watch whether it
flies.

Revised for Rev.2, now that the host is live. Ordered by **value**, since nothing is
blocked any more:

1. **§2 `motion` block** — the one with real remaining value, and the only item the host
   cannot work around from its side. Packer + `make_pet_zip` threading `profile.key` /
   `profile.level` and the record's `catalog_animal` / `catalog_breed`. Inert until the host
   adds `breed:` / `species:` registry entries, which is one line each once bundles carry
   the data.
2. **§7 vocabulary export** — pure data + one script. The host currently hand-maintains
   `web/src/pet/locomotion/vocabulary.json`; this turns it into a regenerated artifact and
   ends the drift permanently. Cheap, and it is the item that makes *our* registry the
   single source it should have been.
3. **§3.1 `loop`** — unblocked (see §3.1). A `jump` that loops is wrong data regardless of
   whether the host currently tolerates it.
4. **§3.3 view fields** — the host now falls back to sheet-level `view_kind`, so tilt is
   already alive on our bundles. What remains is making the prompt↔manifest coupling
   explicit and testable rather than implicit.
5. **§3.2 `timed_buffer_ms`** — lowest urgency: the host's `timedDwellMs` already gives
   every timed pose a real duration. Author one only where the *content* implies a specific
   length.

All five are safe in any order and none of them can break a host that has already shipped —
every field is optional and the host's degradation ladder has a defined answer for each.

---

## 9. Decisions

1. **Ordered `resolution` list, not flat `species`/`breed` fields** (§2.1) — keeps
   specificity semantics on the side that models them, and lets us add a level without a
   host change.
2. **`movement_class` is not deprecated.** It stays a required top-level field and the final
   rung. Removing it would break every existing host read path for no gain.
3. **We do not emit weights** (§4) — the boundary matters more than the convenience.
4. **The schema bump is provenance, not a gate** (§2.4).
5. **A level-1 breed profile is not required by this spec.** Emitting `breed:corgi` when no
   `corgi.json` exists is correct and useful: the host may have its own breed-level motion
   entry even where we have no breed-level *prompt* profile. The two registries are allowed
   to be specific at different rungs — that is exactly what the ordered list buys.

---

## 10. Consistency checks (repo-wide rules)

- **Engine vs. content** — every change is a data field on a profile JSON or metadata copied
  at pack time. No runtime code branches on species, breed, or `movement_class`; the packer
  reads whatever the resolved profile carries.
- **GPU-less posture** — `motion_profiles` and `animal_catalog` stay pure data; nothing added
  here imports numpy/PIL/rembg. The packer already lives behind the lazy ML boundary.
- **Registry with a guard test that fails on a half-formed entry** — §6 extends the existing
  validator, and the admin editor shares it, so an authored profile can never diverge from
  what the build accepts.
- **Adding a body type stays one JSON + one registry line.** Nothing in this spec adds a
  step to that; §7's export is generated, never hand-edited.
- **Specs are cited by section from code comments** — the packer's new fields carry
  `SPEC_BUNDLE_MOTION_CONTRACT §2.1` / `§3.1` references, per the repo convention.
