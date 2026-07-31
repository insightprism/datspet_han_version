# SPEC_PET_DESIGN_PROVENANCE — how a pet was designed, kept on purpose

**Status: Rev.2 (2026-07-31) — DRAFT FOR OWNER REVIEW; NOTHING BUILT.** No code, no
migration, no deploy. §0 is the decision set that needs sign-off; everything after it is the
consequence of those decisions.

> ### Rev.2 — the prompt ships in the bundle
>
> Rev.1 kept the design record entirely private and published only an opaque `design_ref`. **The
> owner's direction is that the prompt is useful to know about a pet and belongs in the bundle**, so
> Rev.2 puts a `design` block in `manifest.json` carrying the composed prompt and the structured
> picks. §3.4 is the mechanism, §3.6 records what publishing costs so it is a decision on the record
> rather than an oversight, and §5 narrows to the one input that stays private by default.
>
> One fact found while designing the mechanism **supports** the direction and kills the obvious
> alternative: DatsMe stores a pet as three *parts* — `write_assets(sheet_png, manifest_json,
> package_json)` (`../datsme_me/api/apps/pets/pet_assets_service.py:100`) — and `build_bundle_zip`
> (`:349`) rebuilds the archive from exactly those three. **A fourth zip member does not survive the
> first host import.** `manifest.json` is not merely the best carrier; it is the only durable one.
>
> The private ledger of Rev.1 is **kept, not replaced** (§3.3). The bundle answers "what is this
> pet"; the ledger answers "what did people build and what happened to it", and only the ledger
> survives a deleted pet (§8.2) — which is the corpus's negative class.

Today every design input a user supplies is destroyed within the build that consumes it. The
composed prompt is discarded at `webui/app.py:1342`, the axis picks are function locals in
`preview_design` that never leave the request, the reference sidecar that holds the typed text is
swept at 24 h (`webui/app.py:1842`), and the seed that actually decided what the pet looks like is
minted inside `_base_sprite` (`pet_factory/factory.py:991`) and never returned to anyone. A pet in
the house is an artifact with no recoverable origin.

This spec records that origin. Two uses, in priority order:

1. **A corpus.** Design inputs joined to outcomes — kept, adopted, taken to DatsMe, thrown away —
   so that "which choices produce pets people actually want" becomes a query instead of a hunch.
2. **Recovery.** Given a pet, answer "what was this built from" for support, for debugging a
   regression, and for rebuilding a bundle that was lost.

Better store-listing text is a *consequence* of having this record, not a justification for it, and
is deliberately out of scope (§10).

**The record lives in two places, and they are not redundant.** A `design` block in
`manifest.json` travels with the pet and answers "what is this" for whoever holds it. A private
append-only ledger in `datspet.db` answers "what did people build, and what became of it" — the
corpus question — and is the only half that survives a pet being deleted. §3 sets out which fields
go where and why the split is not duplication.

**The packer does not write either of them.** `pack_datsme_bundle` cannot see the design inputs
(§1.3: three of thirteen facts, and not the prompt), and does not need to: the web tier already
patches `manifest.json` twice after the bundle comes back (`webui/app.py:618-623`). That existing
seam is the whole mechanism (§3.4).

**Repos touched:** `datsme-pet-factory_wu` only, for Phases 1–3. `datsme_me` is untouched — §6
verifies its bundle validator tolerates unknown manifest keys and its ownership writer preserves
them by an explicit documented rule.

---

## §0 The decisions, in one place

| # | Question | Decision |
|---|---|---|
| 0.1 | Where does the record live? | **Both:** a `design` block in `manifest.json` (travels with the pet) *and* a private append-only ledger in `datspet.db` (survives the pet, joins to outcomes). Never a column on `pets` (§3.2). |
| 0.2 | What does the bundle publish? | **The composed prompt, the structured picks, the species/colour/accessories, the door, and a `design_ref`** — the `design` block of §3.5, written by the mechanism of §3.4. |
| 0.3 | What is recorded? | **Both** the structured inputs *and* the composed prompt string, plus a `compose_version`. Neither derives the other safely (§2.2). |
| 0.4 | Free text the user typed? | **Held privately; excluded from the published prompt by default**, via a second `compose_design` call with `extra=""` (§5.2). A one-line change if the owner wants it in. |
| 0.5 | Does the packer participate? | **No.** `pack_datsme_bundle` is unchanged; SPEC_PET_OWNER_FIELD §2.4's boundary holds and §7 rules on why. |
| 0.6 | Does the ledger die with the pet? | **No.** No foreign key, no cascade. A deleted pet is the corpus's negative class (§8.2). |
| 0.7 | Back-fill existing pets? | **No, and it is not possible.** The epoch is marked instead (§13). |
| 0.8 | May a provenance failure fail a build? | **Never.** Best-effort write, logged, swallowed (§8.4). |

### 0.9 The posture that must not change

1. **Provenance is a read-time fact, never an engine input.** No runtime path may branch on a
   provenance row. This is the same rule SPEC_PET_STORE §10 states for donor attribution — "the
   record of how something came to be is a read-time fact, never an engine input" — and the same
   rule the reference sidecar already lives under (`webui/app.py:703`: *"`source` is recorded for
   support and telemetry ONLY. No runtime path may branch on it"*).
2. **The GPU-less posture.** Everything this spec adds to `webui/` is stdlib + FastAPI. No ML
   import, no filesystem content.
3. **Append-only.** A re-run is a new row, never an `UPDATE` — the `ai_usage` rule
   (`webui/db.py:138`), applied here for the same reason.

---

## §1 What exists today, and where

The starting facts were verified against the tree on 2026-07-31. Two of them needed correction, and
both corrections change the design, so they are stated first.

### 1.1 Correction — the composed prompt does not reach `make_pet_zip` on the designer flow

The submitted premise was that `compose_design`'s return value becomes `params["animal"]`
(`webui/app.py:470`) and arrives as `make_pet_zip`'s first argument
(`pet_factory/factory.py:1072`). That is true for the **CLI** (`make_pet.sh`, `examples/cli.py`) and
for the **Motion Lab** still path. It is **not** true for the web designer, which is the only flow
that has design inputs to record at all.

The actual chain:

| Step | Endpoint | What happens to the composed string |
|---|---|---|
| 2 — design | `preview_design`, `webui/app.py:1266` | `compose_design` builds it (`:1330`), `_render_still` sends it to the renderer (`:1338`) — this is where it does its work |
| 2 — record | `_save_reference`, `webui/app.py:731` | **discarded.** The new reference stores `display_name.lower()` — "purple corgi" — and the code says so at `:1342`: *"The new record carries the SHORT species phrase … NOT the ~240-char composed design string"* |
| 3 — build | `start_job`, `webui/app.py:1511` | reads `description = ref.get("description")` (`:1547`) — the short phrase — and passes **that** to `run_pet_job` → `_generate_via_pool` → `params["animal"]` |

So on a designer build, `params["animal"]` is `"purple corgi"`, not the composed prompt. The prompt
that decided the look was spent one step earlier, on a still the user then locked.

**Consequence:** the composed prompt has exactly one moment of existence — inside `preview_design`.
Any design that records it at build time, in the packer, or from the pool params records the wrong
string. This is decisive for §3.

### 1.2 Correction — the seed is unrecoverable everywhere, and it is the *still's* seed that matters

`make_pet_zip` mints `seed = random.randint(1, 2**31)` at `pet_factory/factory.py:1111` and never
returns it. But on the web designer's build, `_base_sprite` takes the **as-is** branch
(`pet_factory/factory.py:958` — reference present, `remix_strength` always `None`, pinned by
`start_job`'s comment at `:1595`), and that branch never touches the seed. Every other seed in a
build is the fixed constant `_ANCHOR_SEED = 42` (`pet_factory/factory.py:93`).

The randomness that produced the pet's appearance happened in the **still**, at
`render_design_still` → `_base_sprite` → `seed = random.randint(1, 2**31)`
(`pet_factory/factory.py:991`), during `/api/reference` or `/api/preview`. `_render_still`
(`webui/app.py:862`) passes no seed on either backend, and the `pet_preview` pool handler has no
`seed` param at all (`pool_handler/pet_preview_handler.py:69-92`).

**Consequence:** "reproducible" is not achievable by recording alone. It requires making the seed an
*input* — a param the web tier mints and passes down — which is a pool-handler schema change and
therefore a fleet roll. That is why it is Phase 3 (§9.3) and not Phase 1.

### 1.3 The recoverability audit

Thirteen facts are worth recording. Where each one actually exists:

| Fact | Lives at | Visible in the web tier | Visible at pack time |
|---|---|---|---|
| typed animal / subject noun | `create_reference`, `webui/app.py:1034` | ✅ on the reference record | ❌ |
| step-1 door (`catalog`/`txt2img`/`upload`) | `_save_reference` `source`, `webui/app.py:731` | ✅ | ❌ |
| curated identity (`catalog_animal`/`catalog_breed`) | reference record | ✅ | ❌ |
| colour / accessories / free text | `preview_design` form fields, `webui/app.py:1266` | ✅ request-local | ❌ |
| axis picks `{axis: option}` | `preview_design` local `picks`, `webui/app.py:1320` | ✅ request-local | ❌ |
| **composed prompt** | `preview_design` local `description`, `webui/app.py:1330` | ✅ request-local, then discarded | ❌ |
| effective strength | `preview_design` local, `webui/app.py:1335` | ✅ request-local | ❌ |
| reference chain (ref₁ → ref₂) | sidecar files, 24 h TTL | ✅ | ❌ |
| tier / capabilities at build | `start_job`, `webui/app.py:1575` | ✅ request-local | ❌ |
| pose set | form → param | ✅ | ✅ (param) |
| motion profile key | reference record → param | ✅ | ✅ (param) |
| `pose_anchor` | derived from `ref["source"]` | ✅ | ✅ (param) |
| still seed | `pet_factory/factory.py:991` | ❌ | ❌ (worker-local, never returned) |

**The web tier sees twelve of thirteen. The packer sees three.** That asymmetry is the whole
answer to "where should this live", and no amount of plumbing changes it without moving design
state onto GPU nodes — which §7 rules out on its own grounds.

### 1.4 There is no build ledger today

`webui/db.py`'s `jobs` table looks like one and is not. It is written only by `record_pool_job`
(`webui/db.py:604`), only for pool jobs, purely as reattach linkage, and the row is **deleted at
either terminal state** (`delete_pool_job`, `webui/db.py:619`). Local-backend builds write no row at
all. A failed build leaves nothing; a successful build leaves only the `pets` row.

Worse for a corpus: `purge_drafts` (`webui/db.py:436`) hard-deletes every unsaved draft and
`delete_pet` (`webui/db.py:425`) hard-deletes on request. **The negative class — pets the user
built and then rejected — is erased today.** §8.2 is the response.

---

## §2 What to record

### 2.1 The unit of record is one BUILD, assembled from the reference

A provenance row describes one build. It is assembled at `start_job` from two sources:

- **the reference record** — which already carries the step-1 and step-2 facts, because
  SPEC_PET_DESIGNER_FLOW §7.3's whole design is *"resolved once at fill time and carried on the
  record"*. `_save_reference` (`webui/app.py:731`) is where a design becomes a record, and it is
  where the missing design fields belong.
- **the build request** — pose set, motion profile, resolved tier, owner scope.

This is not a new pattern. It is the pattern, applied to fields that were left out of it.

**What `_save_reference` must start carrying** (Phase 1, §9.1): `parent_reference_id`,
`axis_picks`, `color`, `accessories`, `extra_text`, `composed_prompt`, `prompt_public`,
`effective_strength`, `compose_version`. `_reference_record` (`webui/app.py:711`) — the browser-facing projection — gains
**none** of them: it is already documented as deliberately withholding fields (`owner` is excluded
there as *"an access-control fact, not the caller's data"*), and the same reasoning covers the
design fields. Note the asymmetry this creates and keep it: the *finished bundle* publishes the
prompt (§3.5), the *design-in-progress API* does not. A step-2 response is a working surface, not a
record of a thing that exists.

### 2.2 Both the structure and the string — and why neither derives the other

Record the axis picks **and** the composed prompt.

The tempting economy is to store `{"body": "fat", "pattern": "spotted"}` and re-derive the prompt
from `compose_design` when needed. It does not hold, and the code says why:
`webui/app.py:375-378` marks the clause ordering **"NOT YET CALIBRATED"** and pending a GPU session.
The composer is expected to change. A prompt re-derived next year from picks recorded this year is
a different string than the model actually saw, and a corpus that silently substitutes one for the
other is a corpus that cannot answer questions about wording.

The reverse derivation is worse: parsing picks back out of a prompt string is exactly the
translation-function-between-two-engines that CLAUDE.md names as a red flag.

So: both, plus **`compose_version`** — a named constant bumped whenever `compose_design`'s output
changes for the same inputs. Without it, "these two pets used the same picks" is unanswerable
across a calibration change. The constant lives beside the composer and is asserted by a golden
test that already exists (`webui/tests/test_compose_golden.py`) — that test's fixtures *are* the
definition of a version boundary, so bumping it becomes part of the same edit that updates them.

### 2.3 The minimum that makes a build reproducible

Reproducing a build means producing the same bytes, which needs five things:

| Ingredient | Recorded in Phase 1 | Reproducible? |
|---|---|---|
| the composed prompt | ✅ | yes |
| the base image identity (reference chain + door + catalog id) | ✅ | the curated case yes; the generated case only if the still can be redrawn |
| effective strength | ✅ | yes |
| **the still seed** | ❌ → Phase 3 | **no, today** |
| the render environment (Z-Image / Wan / birefnet / ComfyUI versions) | ❌ → tripwire (§10) | no |

**Phase 1 does not claim reproducibility, and must not say it does.** It makes builds
*comparable* — same picks, same prompt, different outcomes — which is what the corpus needs first.
Phase 3 adds the seed and makes reproduction real for everything except a model upgrade.

Naming this honestly is the point: an "origin record" that people believe reproduces builds, and
then does not, is worse than one that says what it covers.

---

## §3 Where it lives, and the mechanism that puts it there

### 3.1 `manifest.json` — the travelling half

A bundle survives export, host import, purchase, gift and adoption, and a manifest key goes with it.
That is the property nothing else has, and it is why the design block lives here.

Two constraints shape *how*, and both are settled facts rather than preferences:

- **It must be `manifest.json`, not a new zip member.** DatsMe stores a pet's *parts* —
  `write_assets(sheet_png, manifest_json, package_json)`
  (`../datsme_me/api/apps/pets/pet_assets_service.py:100`) — and `build_bundle_zip` (`:349`) rebuilds
  the archive from exactly those three. A `design.json` member survives inside DatsPet's own
  `pets.bundle_zip` blob and is then **silently dropped the first time the pet reaches the host**.
  That failure is invisible until someone looks for the file a year later. SPEC_PET_OWNER_FIELD §1.5
  reached the same conclusion for the owner fields and it holds here for a harder reason.
- **It must not be `package.json`.** `pet_factory/tests/test_pack_bundle_layout.py:64-70` pins that
  file's contents with an exact-equality assertion, and the host's validator reads `breed_id` and
  `display_name` out of it as identity. It is a three-field identity card; the design block is not
  identity.

### 3.2 Columns on `pets` — rejected

Two reasons, both structural:

- **Wrong lifetime.** The corpus needs the row for pets that were *deleted* — that is the negative
  class (§8.2). Columns on `pets` die with the row in `purge_drafts` (`webui/db.py:436`) and
  `delete_pet` (`webui/db.py:425`), which deletes precisely the evidence that matters most.
- **Wrong change cadence.** `pets` changes when the house changes. Provenance changes when the
  design vocabulary changes. Different reasons ⇒ different places.

### 3.3 The private ledger — the half that survives the pet

`design_provenance`, a new table in `datspet.db`, joined at read time on `pet_id`.

**Why both, when the manifest already carries the design.** The two answer different questions and
have different lifetimes:

| | the `design` block | the ledger |
|---|---|---|
| lives in | the bundle, wherever it goes | `datspet.db` |
| survives `purge_drafts` / `delete_pet` | **no — the bundle is deleted with the pet** | **yes** |
| survives a build that never produced a pet | no — there is no bundle | yes |
| holds the user's free text | no, by default (§5.2) | yes |
| holds the seed, tier, reference chain | no — build internals, not pet identity | yes |
| queryable in aggregate | no | yes |

The first two rows are the whole argument. The corpus's most valuable rows are the pets people
**threw away**, and those have no bundle to read. Reading provenance out of `pets.bundle_zip` would
mean the corpus can only ever see successes — which is the one shape of dataset guaranteed to teach
the wrong lesson.

This is the shape the repo already uses twice for exactly this kind of record: `ai_usage`
(`webui/db.py:138`) is an append-only ledger scoped by `external_user_id` and read only in
aggregate; Phase 2 of the store specifies `store_donations` the same way and states the rule
outright — *"Donor attribution is a read-time join from this ledger … the record of how something
came to be is a read-time fact, never an engine input"* (SPEC_PET_STORE §10). A third instance of a
pattern with two live instances is not speculative abstraction; it is using what is there.

It is a **separate table**, not columns, for the SPEC_PET_STORE §1.2 reason restated: `pets` is
scoped by `_scope_clause` (`webui/db.py:401`), exact-match as a security invariant, and a ledger
that must outlive its pet has no business inside that clause.

### 3.4 THE MECHANISM — how the prompt reaches the zip

This is the section the design turns on. It has three moves, and **none of them touches the packer,
the pool handler, or the fleet.**

#### Move 1 — the design facts ride the reference record

The composed prompt exists for the duration of one request (§1.1). `preview_design`
(`webui/app.py:1266`) already ends by minting a new reference through `_save_reference`
(`webui/app.py:731`); today it stores the short display phrase and drops everything else at
`webui/app.py:1342`. It stores the design facts instead — prompt, picks, colour, accessories,
strength, parent reference id.

This is not a new pattern, it is *the* pattern: SPEC_PET_DESIGNER_FLOW §7.3 is titled by its own
payoff comment at `webui/app.py:1540-1544` — *"The record already carries all of it, resolved once at
FILL time"*. The design fields were simply left out of the record that was built to hold them.

`_reference_record` (`webui/app.py:711`) — the browser-facing projection — gains **none** of them.
It already withholds fields on principle (`owner` is excluded as *"an access-control fact, not the
caller's data"*), so the composed prompt joins that list.

#### Move 2 — `start_job` writes the ledger row, and the ledger is the carrier

`start_job` (`webui/app.py:1511`) holds `ref` and the build params. It assembles the full record and
writes the `design_provenance` row **keyed on `job.id`** — which is the same value `insert_pet` later
uses as `pet_id` (`webui/app.py:625`).

**The block is not stashed on the `Job` object, and that is a correction worth recording.** The
obvious move is the `pool_labels` precedent (`webui/app.py:262-265`: *"captured from the request AT
SUBMIT-HANDLER TIME — generation runs on a background thread where the request … is gone, so it must
be carried here"*). It is wrong here, because `Job` is in-memory and there is a **third** path into
finalize: the pool-reattach at startup (`webui/app.py:655`) rebuilds a `Job` from the `jobs` row
after a process restart, and `record_pool_job` (`webui/db.py:604`) persists only
`pool_job_id / description / display_name / created_at / external_user_id`. A design block carried
on `Job` would be silently lost on exactly the builds that survive a restart — rare, invisible, and
undebuggable a month later.

The ledger row is already durable, so it is the carrier. No `Job` field is added.

#### Move 3 — stamp the manifest from the ledger, after the bundle comes back

`_finalize_pet_from_zip` (`webui/app.py:600`) is where a finished bundle becomes a stored pet, and
**it already patches `manifest.json` twice**, at `webui/app.py:618-623`:

```python
zip_bytes, _ = pet_ownership.stamp_bundle_fingerprint(zip_bytes)
zip_bytes, manifest_json = pet_ownership.transfer_pet_ownership(zip_bytes, …)
db.insert_pet(…)
```

The design block is a third patch at the same seam, using the same machinery: `_apply_to_bundle`
(`webui/pet_ownership.py:249`) rewrites the zip carrying **every member across under its original
name and in its original order**, because *"`app._unpack_bundle` matches members by name … a renamed
member is an unrenderable pet"*.

It reads the block back with `db.design_block(job.id)` — a **projection of the ledger row**, defined
in one place (§4.4). `job.id` is in scope on all three entry paths including reattach, so the block
survives a restart.

Four properties fall out of this position, and each is a reason it is the right one:

1. **Both backends converge here.** Local `make_pet_zip` and pool `drive_to_result` both land in
   `_finalize_pet_from_zip` (`webui/app.py:557`), and so does the pool-reattach path after a restart
   (`webui/app.py:655`). One write site, not three.
2. **It is upstream of `insert_pet`**, which *derives* `bundle_sha256` and `size_bytes` from whatever
   bytes it is handed (`webui/db.py:248`). So the digest covers the stamped bytes by construction and
   nothing ever restamps a stored row — the exact ordering rule SPEC_PET_OWNER_FIELD §2.4 established.
3. **The packer is untouched**, so `pet_factory/tests/test_pack_bundle_layout.py` needs no change and
   §7's pool boundary holds with no argument required.
4. **It is patch, not rebuild.** Every existing manifest key — geometry, `animations`, the view
   blocks, `movement_class`, the owner fields — passes through untouched.

**One efficiency note that falls out of the §6.1 extraction:** three sequential stamps mean three
full zip rewrites. `patch_bundle_manifest` should take a *list* of patch functions and apply them in
one open/rewrite, making the mint cheaper than it is today rather than more expensive.

#### What this does NOT require

| | |
|---|---|
| a change to `pack_datsme_bundle` | no |
| a change to either pool handler's `params_schema` | no |
| a fleet roll | **no** |
| a change to `make_pet_zip`'s signature | no |
| a DatsMe code change | no (§6) |
| a migration on `pets` | no |

### 3.5 The `design` block

```json
"design": {
  "schema_version": "pet_design.v1",
  "design_ref": "9f2c40ab7e1d4c88",
  "prompt": "chubby vivid purple corgi with a spotted coat wearing a top hat, recolored entirely purple",
  "compose_version": "compose.v1",
  "species": "corgi",
  "color": "purple",
  "accessories": ["top hat"],
  "picks": { "body": "fat", "pattern": "spotted", "coat": "spotted" },
  "door": "catalog",
  "catalog_animal": "dog",
  "catalog_breed": "corgi",
  "strength": 0.85,
  "built_at": "2026-07-31T09:14:02Z"
}
```

**One nested object, not flat top-level keys** — and this deliberately diverges from
SPEC_PET_OWNER_FIELD §0.4, which chose flat. The reason that spec chose flat is that its fields are
read *at a gate*, one at a time, and written by two different actors in two different repos. The
design block is written once by one writer, read as a unit, and never partially updated. Nesting
also makes "remove the design" one `del`, which §5.3 needs.

Field notes:

- **`prompt`** — the composed design string, exactly as `compose_design` returned it, minus the free
  text (§5.2). This is the field the owner asked for.
- **`picks`** — `{axis_key: option_key}`, the browser's own vocabulary. These are the keys the
  browser *sent*; publishing them back reveals nothing it did not already have.
- **`design_ref`** — random, opaque, 16 hex chars. Never derived from the owner, the anon cookie, the
  `reference_id` (owner-scoped, appears in URLs), or a hash of the design. It is the join key back to
  the ledger, and it is what makes a bundle found in the wild resolvable.
- **`built_at`** — UTC ISO-8601 with a `Z` suffix, via `pet_ownership.utc_now_iso()`
  (`webui/pet_ownership.py:85`). The bundle's wire format for time is already decided; do not invent
  a second one.
- **Absent for pets that were not designed.** A store adopt (`webui/pet_store.py:70`) copies an
  existing bundle and inherits whatever block it carried. A CLI pet has no block. Absence reads as
  "unknown", never as "no design" — the `read_pet_ownership` posture (`webui/pet_ownership.py:194`).

### 3.6 What publishing costs, on the record

This is a deliberate reversal of a shipped posture, and it is written down so it is a decision
rather than a drift.

`design_axes` `prompt_fragment` values are withheld from the browser on purpose —
`webui/app.py:1233`: *"`prompt_fragment` is calibrated server-side wording and never reaches the
browser, same posture as the tier table"*, pinned by SPEC_PET_DESIGN_AXES §4 and a guard test in
that spec's verification table (`docs/SPEC_PET_DESIGN_AXES.md:497`). The composed `prompt` **is**
those fragments, concatenated. Publishing it publishes the vocabulary.

Two things follow, and both are acceptable — the point is that they are chosen:

- **The withholding rule narrows rather than disappears.** `/api/design-axes` keeps withholding
  fragments, because the menu should not preview them and the browser has no use for them. What
  changes is that a *built* pet discloses the wording that made it. Those are different claims and
  the endpoint's docstring must be corrected to say so, or it becomes a lie that someone later
  "restores" (§12 pins this).
- **The tier-table analogy no longer holds and should stop being cited for fragments.** The tier
  table is withheld because knowing other tiers' entitlements is an upsell surface. Fragment wording
  was withheld by association, not by its own argument. SPEC_PET_DESIGN_AXES §4 should record that.

**What is not on the table:** the free text (§5.2), and the ledger's build internals — seed, tier,
reference chain, owner. Those are not "what this pet is"; they are how the factory ran.

---

## §4 The data model

### 4.1 The table

```sql
-- Design provenance (SPEC_PET_DESIGN_PROVENANCE). Append-only: a re-run is a NEW
-- row, never an UPDATE — the ai_usage rule. NO FOREIGN KEY to pets, deliberately:
-- the row must outlive purge_drafts and delete_pet, because "the user built this
-- and threw it away" is the corpus's negative class (§8.2). Contrast
-- bundle_tokens (db.py:114), which DOES cascade — a token for a deleted pet is
-- garbage; a provenance row for a deleted pet is the finding.
CREATE TABLE IF NOT EXISTS design_provenance (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    design_ref          TEXT    NOT NULL UNIQUE,  -- the opaque id stamped in the manifest
    pet_id              TEXT    NOT NULL,         -- == jobs/pets id; NOT a foreign key
    created_at          REAL    NOT NULL,         -- unix epoch float (db.py's format)
    schema_version      TEXT    NOT NULL,         -- "design_provenance.v1"
    compose_version     TEXT    NOT NULL,         -- which compose_design produced the prompt

    -- What the user chose (step 1 + step 2)
    door                TEXT    NOT NULL,         -- catalog | txt2img | upload
    species             TEXT    NOT NULL,         -- the noun the design was composed against
    color               TEXT    NOT NULL DEFAULT '',
    accessories_json    TEXT    NOT NULL DEFAULT '[]',
    extra_text          TEXT    NOT NULL DEFAULT '',   -- the free-text escape hatch; PRIVATE (§5.2)
    picks_json          TEXT    NOT NULL DEFAULT '{}', -- {axis_key: option_key}
    composed_prompt     TEXT    NOT NULL,         -- what the renderer actually saw; PRIVATE
    prompt_public       TEXT    NOT NULL,         -- the same prompt with the free-text clause
                                                  -- omitted (compose_design(..., extra="")).
                                                  -- IDENTICAL to composed_prompt when the user
                                                  -- typed no free text, which is the common case.
    display_name        TEXT    NOT NULL,

    -- What the engine did with it
    reference_id        TEXT,                     -- ref₂: the still that was animated
    parent_reference_id TEXT,                     -- ref₁: the archetype it was designed from
    catalog_animal      TEXT,
    catalog_breed       TEXT,
    surface             TEXT,                     -- fur | feathers | scales | NULL
    motion_profile      TEXT,
    poses_json          TEXT    NOT NULL DEFAULT '{}',
    effective_strength  REAL,
    pose_anchor         INTEGER NOT NULL DEFAULT 1,
    still_seed          INTEGER,                  -- NULL until Phase 3 (§9.3)

    -- The context the build ran in
    tier                TEXT,
    external_user_id    TEXT                      -- NULL = standalone (db.py's convention)
);
CREATE INDEX IF NOT EXISTS idx_provenance_pet ON design_provenance(pet_id);
CREATE INDEX IF NOT EXISTS idx_provenance_created ON design_provenance(created_at);
```

`picks_json` is a JSON object rather than a column per axis on purpose: **adding an axis must not be
a migration.** That is the first of the four test questions (§11) and the reason `design_axes/` is a
registry in the first place.

### 4.2 Named values, no literals

Per CLAUDE.md, every value gets a name. In `webui/design_provenance.py`:

```
PROVENANCE_SCHEMA_VERSION = "design_provenance.v1"
DESIGN_BLOCK_SCHEMA       = "pet_design.v1"     # the manifest block's own version
COMPOSE_VERSION           = "compose.v1"        # bump with webui/tests/test_compose_golden.py
DESIGN_BLOCK_KEY          = "design"            # the manifest key
DESIGN_REF_BYTES          = 8                   # → 16 hex chars, the repo's id width
MAX_COMPOSED_PROMPT_CHARS = 600                 # the pool schema's transport bound, mirrored
MAX_EXTRA_TEXT_CHARS      = MAX_EXTRA_CHARS     # imported from app, never retyped
```

### 4.3 Where the code lives

A new module, `webui/design_provenance.py`, on the `pet_ownership.py` precedent
(SPEC_PET_OWNER_FIELD §2.3: *"`db.py` is the byteless record view, `app.py` is the HTTP surface … All
three call it; none should be it"*). It owns:

- the constants above;
- `mint_design_ref()`;
- `record_from_reference(ref, *, pet_id, poses, motion_profile, pose_anchor, tier,
  external_user_id) -> dict` — assembling the ledger row from a reference record plus build params,
  so `start_job` gains a call rather than twenty lines;
- **`public_block(row) -> dict`** — the projection of §4.4, the *one* definition of what is
  published;
- `set_design_block(manifest_json, block) -> manifest_json` and
  `stamp_design_block(zip_bytes, block) -> (bytes, manifest_json)` — the writers, idempotent with
  `pet_ownership`'s same-object no-op contract;
- **`strip_design_block(manifest_json) -> manifest_json`** — the removal used at the one seam where a
  pet stops being its designer's (§5.3).

`db.py` owns `insert_design_provenance(**row)`, `design_block(pet_id)` (fetch + project), and the
read-time join query (§8.3). Imports are stdlib only.

### 4.4 The manifest block is a PROJECTION of the ledger row, defined once

`public_block(row)` is the only place that decides what is published. It is a **whitelist**, never a
blacklist:

```python
PUBLIC_FIELDS = ("design_ref", "prompt_public", "compose_version", "species", "color",
                 "accessories", "picks", "door", "catalog_animal", "catalog_breed",
                 "strength", "built_at")
```

Whitelist, because the failure modes are asymmetric. A field forgotten from a whitelist is a field
missing from a bundle — annoying, fixable, and it fails toward silence. A field forgotten from a
blacklist is `still_seed`, `tier`, `external_user_id`, `composed_prompt` or `extra_text` shipped to
strangers permanently, and it fails toward disclosure. Every future column added to
`design_provenance` is private until someone adds its name to this tuple, which is the direction the
mistake should point.

The projection renames exactly two fields, and only to keep the block readable to a human holding
the file: `prompt_public → prompt` and `accessories_json → accessories` (parsed). Note which side of
that rename `composed_prompt` sits on — **it is not published at all**; `prompt_public` is
(§5.2).

A guard test pins the tuple against the table's columns and **fails on any new column that is
neither listed nor explicitly named as private** — the half-formed-registry-entry rule this repo
applies to `motion_profiles` and `design_axes`, applied to a disclosure boundary.

---

## §5 Privacy — the rule for text a user typed

### 5.1 Three doors produce free text

1. **The typed-animal box** (`create_reference`, `webui/app.py:1034`) — `animal`, up to 60 chars,
   unconstrained.
2. **The `extra` escape hatch** (`preview_design`, `webui/app.py:1266`) — documented as *"the
   unbounded escape hatch"* at `webui/app.py:419`.
3. **An upload's subject noun** — and uploads are photographs, which
   SPEC_UPLOAD_LIKENESS exists because they are sometimes photographs of **people**. `app.py:1131`
   records an incident where the pipeline drew a dog from a photo of a person.

None of these is a menu selection. All of them are a human writing a sentence.

Two of the three are *names* — a species noun the user chose for their own pet. Publishing "corgi"
or "my cat Biscuit" as the species of a pet named after it discloses nothing the pet's own
`display_name` doesn't already say, and `display_name` has shipped in `package.json` since the
beginning (`pet_factory/factory.py:947`). Those ship.

**`extra` is different in kind.** It is documented in the composer itself as *"the unbounded escape
hatch"* (`webui/app.py:419`) — the field with no menu, no vocabulary, and no length discipline
beyond a character cap. It is where a user writes a sentence, and the only one of the three that is
not answering the question "what animal is this".

### 5.2 The rule — one carve-out, and it costs one line

> **The free-text field is held privately and omitted from the published prompt. Everything else
> about the design ships.**

The mechanism is almost free, and it exists because `compose_design` is a pure function of its
arguments (`webui/app.py:348`):

```python
prompt_full   = compose_design(species, color, accessories, picks, extra)[0]   # → ledger, private
prompt_public = compose_design(species, color, accessories, picks, "")[0]     # → the bundle
```

Two calls to a pure string function, no GPU, no branch in any engine, no per-record flag. When the
user typed no free text — the common case — the two strings are **identical** and the bundle carries
the exact prompt that was rendered.

`extra`'s position in the composed string is what makes this clean: it sits immediately before the
recolor clause (`webui/app.py:418-422`, deliberately, so the calibrated tail still wins), so removing
it leaves every other clause in its calibrated order. This is not a coincidence to rely on silently —
a golden test pins that `prompt_public` equals `prompt_full` with exactly that clause removed, so a
future reordering of the composer cannot quietly make the two diverge in some other way.

**Why this carve-out and not the whole prompt.** The exposure that matters is narrow and nameable:
a pet only reaches a stranger through a DatsMe **gift**, or through the store — either an admin
publishing their *own* house pet (`webui/store_admin.py:194`, read through the admin's own owner
scope) or, in the unbuilt Phase 2, a **user donation**, which SPEC_PET_STORE §0.5 makes irreversible
at the click. Colour, body shape and accessories on a shelf pet are product information. A sentence
someone wrote about their own pet, sitting in a stranger's file forever, is not.

**Not opt-in.** A per-pet "publish my prompt" checkbox was rejected: it makes the corpus non-uniform
in exactly the way that biases learning, meaningful consent to permanent third-party publication is
not obtainable from a design-page checkbox, and it introduces a per-record flag that some path will
eventually branch on — which §0.9 forbids.

**If the owner wants the free text published too**, it is one argument: pass `extra` to the second
call and drop the column split. That decision is §14.2, and it is reversible only forward — bundles
already minted keep whatever they were minted with.

### 5.3 The removal seam — one place, for the one transfer that matters

A `design` block is removable, and there is exactly one seam where removal is correct: **the point at
which a pet stops being its designer's.** Today no such transfer exists in DatsPet — an admin
publishes their own pet, and a store adopt copies inventory. Phase 2 of the store adds one:
`donate`, which SPEC_PET_STORE §10 specifies and which is unbuilt.

**Requirement on that unbuilt spec, recorded here so it is not a retrofit:** the donate handler calls
`design_provenance.strip_design_block(...)` as part of the same transfer that moves the pet into
inventory. The donor's ledger row is untouched — the corpus keeps it — and the shelf pet carries
none of the donor's design text.

This is a removal at a **transfer**, not a flag on a record: the same shape as the ownership stamp,
which also fires at transfers and is also not a per-pet setting. Nothing branches on a stored value.

### 5.4 The ledger's own boundary

The ledger holds the free text and the full prompt. Same posture as the reference sidecar, which
stores the typed description and the AI's caption on disk today (`webui/app.py:731`), and as
`ai_usage`: internal, owner-scoped, never served.

- **No browser surface reads `design_provenance` in Phase 1.** Not the house page, not the pet card,
  not the store listing, not the admin. Corpus reads are direct DB / export only. (What the *bundle*
  publishes is §4.4's projection, which is a different question and already answered.)
- **Nothing private in the ledger is ever passed to an AI purpose.** A live risk, not a theoretical
  one: `_draft_listing` (`webui/store_admin.py:114`) already sends a portrait to a model, and
  provenance is the obvious thing to feed it next. `prompt_public` and `picks` are fair game there;
  `composed_prompt` and `extra_text` are not, because that would send a user's sentence to a
  third-party API and print derived text on a public shelf. §10 records the whole listing question
  as deliberately not done.
- **Tripwire:** the first time an admin surface needs to display a provenance row, that is the moment
  to decide the redaction rule for *display* — an easier question than this one, because a page can
  be changed and a bundle cannot.

---

## §6 Contract impact — who reads the manifest

Phase 1 changes **no** contract. Everything here is Phase 2 (the `design` block).

| Reader | Location | Effect of one new top-level key | Action |
|---|---|---|---|
| the packer's layout test | `pet_factory/tests/test_pack_bundle_layout.py:41-70` | **None.** It asserts the member set exactly and `package.json` exactly, but reads manifest keys individually — **there is no exact key-set assertion on the manifest**, verified. And the packer is unchanged anyway. | none — the §7 welcome consequence |
| `_unpack_bundle` | `webui/app.py:574` | None. Reads `manifest.json` verbatim into a string. | none |
| `db.pose_count` | `webui/db.py:279` | None. Reads `animations` only. | none |
| the client pet runtime | `web/src/pet/manifest.ts:62` (`animsFromManifest`), `web/src/pet/types.ts` | None. `RawManifest` is a structural interface; extra properties are legal, and `animsFromManifest` explicitly *"strips a manifest's animations down to the fields the engine consumes"*. | none |
| **DatsMe's ingest validator** | `../datsme_me/api/apps/pets/pet_assets_service.py:265-277` | **None — verified.** It requires `manifest.json` to be present, parseable, and to hold an `animations` dict. It does not enumerate keys and does not reject unknown ones. | none |
| **DatsMe's part storage** | `write_assets`, `../datsme_me/api/apps/pets/pet_assets_service.py:100`; `build_bundle_zip`, `:349` | **None — and this is the load-bearing check.** The host persists `manifest_json` as a whole string and rebuilds bundles from it verbatim, so the `design` block survives an import → rebuild → re-download round trip. It would **not** have survived as a fourth zip member (§3.1). | none |
| DatsMe's ownership writer | `../datsme_me/api/apps/pets/pet_ownership.py:126` | **None, by design.** It *"PATCHES the manifest and never rebuilds one … anything a future spec adds — passes through untouched."* This spec is that future spec, and the passthrough rule is what makes the `design` block survive a purchase and a gift. | none |
| the two-repo fixture | `webui/tests/fixtures/owner_fields.json`, vendored to `datsme_me` with a pinned sha256 (SPEC_PET_OWNER_FIELD §2.3a) | The fixture already contains *"a deliberately unknown nested key"*; a real `design` block makes the tolerance explicit — and, being nested, exercises the unknown-**object** case the flat owner fields never did. | **re-vendor the fixture and update the pinned checksum on both sides** — the one cross-repo step in this spec |

### 6.1 The one shipped-code change, flagged

`pet_ownership._apply_to_bundle` (`webui/pet_ownership.py:249`) is the only correct way to patch a
manifest inside a bundle: it carries every member across under its original name and in its original
order, because *"`app._unpack_bundle` matches members by name … a renamed member is an unrenderable
pet"*. Phase 2 needs the same behaviour for a different field.

**Move it to `webui/bundle_manifest.py` as `patch_bundle_manifest(zip_bytes, patch)`**, and have
`pet_ownership.py` call it. Behaviour byte-identical, no test changes.

The boundary is right, and SPEC_PET_OWNER_FIELD §2.1 already drew it: *"the ~20 shared lines are the
manifest-level writer and reader, **not the zip plumbing**"*. The zip plumbing changes when the
bundle layout changes; the owner fields change when the ownership model changes. Two reasons, two
places.

This is a change to shipped, deployed, production code, and it is flagged as such. The alternative —
duplicating fifteen lines — was considered and rejected here: CLAUDE.md's intentional-duplication
rule protects *domain* boundaries so a bug in one cannot reach another, and this is mechanical zip
plumbing where a divergence between two copies is a bug rather than an isolation.

---

## §7 The pool boundary — ruled on

SPEC_PET_OWNER_FIELD §2.4 is explicit: *"Not in `pack_datsme_bundle`. That runs on pool GPU nodes
(`pool_handler/pet_factory_handler.py`), which must never hold identity or partner state. Rendering
and ownership change for different reasons and belong in different places."*

**Does design provenance fall inside that rule?** The literal text says identity and partner state,
and a colour pick is neither. Read literally, provenance is arguably *render* state — the packer is
the renderer, and the renderer knowing what it rendered is not obviously a violation.

**The ruling: provenance stays out of the packer.** Three reasons, in order of force:

1. **The packer does not have the data** (§1.3). It sees three of thirteen facts, and on the
   designer flow not even the composed prompt. Any provenance the packer could write would be a
   partial record that reads as a complete one — the worst possible artifact for a corpus.
2. **Getting the data there requires sending it there.** The pool params schema is
   `additionalProperties: False` (`pool_handler/pet_factory_handler.py:104`), so every field is a
   declared param and a fleet roll. Sending the typed animal, the free text, and the axis picks to
   pool worker nodes puts user-authored content on shared GPU infrastructure that today holds only a
   prompt, an image, and a pose list. That *is* the §2.4 rule in substance even if not in its exact
   words: the pool holds render inputs, not the record of who asked for what.
3. **Change cadence.** The design vocabulary changes when `design_axes/` changes — a JSON edit on
   the web tier, no deploy of anything else. The packer changes when the bundle layout changes. Tie
   them together and every new axis becomes a fleet roll.

**The welcome consequence, exactly as §2.4 records for the owner fields:**
`pet_factory/tests/test_pack_bundle_layout.py` needs no change, because the packer's output is
unchanged.

**The seed is the one honest exception, and it is handled as an input, not an output.** Phase 3
(§9.3) does not have the worker *report* the seed; it has the web tier *mint* it and pass it down.
That keeps the direction of flow one-way — the web tier decides, the pool renders — and keeps the
worker stateless. It costs a `seed` param on `pet_preview` (and on `pet_factory` for the CLI's
branch) and therefore a fleet roll, which is why it ships last.

---

## §8 The corpus — shaping the record so it can answer the question

This section makes sure the record is not useless for learning. It does **not** design a training
pipeline.

### 8.1 Outcome signals that exist today, and where

| Signal | Meaning | Where it lives |
|---|---|---|
| `pets.draft = 0` | the user pressed Keep | `db.keep_pet`, `webui/db.py:408` |
| row missing from `pets` | built, then purged or deleted — **rejected** | `db.purge_drafts` `webui/db.py:436`; `db.delete_pet` `webui/db.py:425` |
| `pets.writeback_acked_at` | the pet reached the user's DatsMe house (projected as `in_datsme`, `webui/db.py:382`) | `db.stamp_writeback_acked`, `webui/db.py:470` |
| `pets.datsme_activity_id` | which DatsMe activity claimed it | same |
| `pets.source_store_pet_id` | this pet was adopted from the shelf, not designed | `webui/db.py:185-189`, set by `adopt_store_pet` |
| `store_pets.published` | an admin put it on the shelf — **a curator's positive vote** | `webui/db.py:95` |
| `store_donations` (Phase 2 of the store) | a user gave the pet away | SPEC_PET_STORE §10.2 |
| — | *"was it still there a month later"*, *"was it rendered"* | **DatsMe's Postgres only.** Not available, and §10 keeps it that way. |

### 8.2 The negative class is the design constraint

"What makes a good pet" is answerable only if bad pets are in the corpus. Today they are deleted
without trace (§1.4). Two rules make them survivable:

1. **No foreign key, no cascade** on `design_provenance.pet_id` (§4.1). A purge or a delete removes
   the pet; the provenance row stays. `LEFT JOIN pets` then yields `NULL`, and *that null is the
   label*: built and not kept.
2. **The row is written at `start_job`, not at finalize.** A build that errors or is cancelled
   leaves a provenance row with no pet — which is also a finding ("this design fails to build"), and
   is free.

This is the single most consequential decision in the spec, and it is worth stating why the
obvious-looking alternative is wrong: adding `ON DELETE CASCADE` for tidiness — as `bundle_tokens`
correctly does (`webui/db.py:114`) — would delete exactly the rows the corpus exists to collect. A
token for a deleted pet is garbage. A provenance row for a deleted pet is the answer.

### 8.3 The join, sketched

```sql
SELECT dp.picks_json, dp.composed_prompt, dp.color, dp.door, dp.species,
       dp.motion_profile, dp.effective_strength, dp.compose_version,
       (p.id IS NOT NULL)                  AS survived,
       (p.draft = 0)                       AS kept,
       (p.writeback_acked_at IS NOT NULL)  AS taken_to_datsme,
       (sp.id IS NOT NULL AND sp.published = 1) AS shelved
FROM design_provenance dp
LEFT JOIN pets       p  ON p.id  = dp.pet_id
LEFT JOIN store_pets sp ON sp.bundle_sha256 = p.bundle_sha256
WHERE dp.schema_version = 'design_provenance.v1';
```

**The store join needs no new column, and must not get one.** SPEC_PET_STORE §1.2 and §10 both
refuse a provenance column on `store_pets`. It is unnecessary: `publish_from_pet`
(`webui/store_admin.py:224`) passes `pet["bundle_zip"]` verbatim, and `insert_store_pet`
(`webui/db.py:775`) derives `bundle_sha256` from those same bytes — exactly as `insert_pet`
(`webui/db.py:248`) does for the house row. **The digest is the join key**, already present on both
tables, and this is a read-time join, which is precisely the boundary the store spec named.

One caveat to record: `adopt_store_pet` re-stamps ownership before insert
(`webui/pet_store.py:98`), so an *adopted copy's* digest differs from the shelf row's. The join above
goes shelf-row → source house pet, which is the direction that holds.

### 8.4 A provenance failure never fails a build

The insert is best-effort: wrapped, logged, swallowed. A user must never lose a three-minute GPU
build because a telemetry row would not write. Precedent: the store's AI listing draft is
best-effort for the same reason (SPEC_PET_STORE §4).

**The failure is coherent, not half-written**, and that falls out of Move 2 (§3.4): the ledger row
is the *source* of the manifest block, so a failed ledger write means `db.design_block(job.id)`
returns nothing and the bundle simply carries no `design` block. There is no state where a bundle
advertises a `design_ref` that resolves to nothing. Absence reads as "unknown", which is the correct
answer and matches `read_pet_ownership`'s posture — absence is never coerced into a value
(`webui/pet_ownership.py:194`).

### 8.5 No claim handler — deliberately

`design_provenance` carries an `external_user_id` and is **not** registered with
`owner_scope.register_claim_handler`. `webui/owner_scope.py:185` states the rule for `ai_usage`:
*"It is an append-only ledger … and a claim handler would rewrite history to make cost attribution
tidier … Do not 'complete' the registry by adding it."*

Same answer, same reason. The pet row moves to the signed-in user at launch (`claim_anon_pets`); the
provenance row keeps the owner who actually did the designing. The corpus joins on `pet_id`, which
is stable across the claim, so nothing is lost. A guard test asserts the absence (§12).

---

## §9 Rollout

Ordered by what each phase needs from anyone else. Phase 1 needs nothing.

### 9.1 Phase 1 — the ledger (ships alone; no fleet, no host, no manifest change)

1. `_save_reference` / `_load_reference` (`webui/app.py:731`) carry the step-2 design fields
   (§2.1). `_reference_record` (`webui/app.py:711`) gains none of them.
2. `preview_design` (`webui/app.py:1266`) writes them onto the new reference — the composed
   `description` it currently discards at `:1342` is stored on the record instead of thrown away,
   alongside the second `compose_design(..., extra="")` call that produces `prompt_public` (§5.2).
   *The rendered still and the reference's short `description` are unchanged; this is additive.*
3. `webui/design_provenance.py`: constants, `mint_design_ref`, `record_from_reference`,
   `public_block`.
4. `db.insert_design_provenance` + `db.design_block(pet_id)` + the `design_provenance` table in
   `_SCHEMA` (`webui/db.py:59`). New table, so no `ALTER` migration — `executescript` creates it on
   next startup.
5. `start_job` (`webui/app.py:1511`) assembles the row and inserts it best-effort, keyed on `job.id`.
   **No `Job` field is added** — §3.4 Move 2 explains why the `pool_labels` precedent does not apply.
6. Guard tests (§12).

**Ship this first and ship it fast.** Every day without it is a day of corpus that cannot be
recovered later (§13's argument, and §1.1's: the prompt is discarded, not merely unstored). It also
means Phase 2 can be turned on for pets already recorded — the ledger has the data, so a later stamp
is a code change rather than a lost cohort.

### 9.2 Phase 2 — the `design` block in the manifest

1. Extract `patch_bundle_manifest` into `webui/bundle_manifest.py`; `pet_ownership.py` calls it
   (§6.1). Take the list-of-patches form (§3.4) so the mint rewrites the zip once, not three times.
2. `design_provenance.stamp_design_block`, called in `_finalize_pet_from_zip` (`webui/app.py:600`)
   **beside the two existing stamps at `:618-623` and upstream of `insert_pet`** — the same derived-
   digest ordering rule `insert_pet` documents at `webui/db.py:248`. It reads the block from
   `db.design_block(job.id)`, so all three finalize entry paths (fresh local, fresh pool, reattach at
   `webui/app.py:655`) behave identically.
3. `adopt_store_pet` (`webui/pet_store.py:70`) is **not** changed: a store adopt copies an existing
   bundle and inherits whatever block it carried. Two adopters of the same shelf pet share a
   `design_ref`, which is true — it is one design.
4. `strip_design_block` exists and is tested, but has **no caller until the store's donate door is
   built** (§5.3). It ships now so that spec has it to call.
5. Re-vendor `owner_fields.json` with a `design` block case; update the pinned sha256 on both repos
   (§6).

No host code change. Ordering is free in both directions: an unknown key is inert to every reader
in §6.

### 9.3 Phase 3 — the seed, and with it real reproducibility

1. `pet_preview_handler.py` gains `seed` in `params_schema` (`:69-92`) → **v4**. Roll the fleet
   first: `additionalProperties: False` means a node without the param **422s** on a request that
   carries it. This is the same gate `isolate_subject` and `pose_anchor` already documented
   (`webui/app.py:910`, `pool_handler/pet_factory_handler.py:99`).
2. `_render_still` (`webui/app.py:862`) mints the seed, passes it on both backends, returns it;
   `_save_reference` stores it; `record_from_reference` copies it to `still_seed`.
3. `make_pet_zip` gains `seed=` (`pet_factory/factory.py:1072`) so the CLI's txt2img/remix branches
   are pinnable too. Inert on the web tier's as-is path (§1.2) — recorded as such, not as a claim
   of coverage.

Only after this phase may anything describe a build as reproducible (§2.3).

---

## §10 Deliberately not done

- **Nothing in the bundle beyond §4.4's whitelist.** The seed, tier, owner, reference chain and the
  free text stay in the ledger. Revisit per field, never as a batch, and never by switching the
  projection to a blacklist.
- **No store-listing AI change.** The listing drafter (`webui/store_admin.py:114`) sees one cropped
  frame and the animal word, and would obviously draft better text with the design record. That work
  is not folded in here: provenance is worth building on its own terms, better listings are a
  consequence, and bundling them would make the privacy boundary (§5.4) a subject of a text-quality
  discussion. **Tripwire:** when it is specified, the question to answer first is which fields may
  reach a third-party model, not which fields would help. (Note that a store pet's manifest will by
  then carry `prompt` and `picks` — so the drafter can read them off the bundle it already holds,
  with no new access to anything private.)
- **No preview-abandonment ledger.** Recording designs that were previewed and never built is a real
  signal ("which prompts produce a still the user rejects"), but it is a different record with a
  different key, no pet, and roughly ten times the row count. **Tripwire:** the first corpus query
  that wants to know *why* a design was abandoned.
- **No render-environment versions** (Z-Image / Wan / birefnet / ComfyUI). Only the worker knows
  them, capturing them means a result-side channel from the pool, and §7 keeps the flow one-way.
  **Tripwire:** the first time a model upgrade makes old and new pets incomparable and someone
  cannot tell which cohort a pet is in.
- **No admin surface for the corpus.** Reads are direct DB in Phase 1. **Tripwire:** §5.4 — the
  first display need is the moment to decide the display-redaction rule.
- **No editing or removing a `design` block through the product.** There is no "hide my prompt"
  control, and `strip_design_block` has exactly one intended caller (§5.3). A user-facing control
  would be a per-record flag by another name, and it could not reach copies already distributed.
- **No host-side outcome feedback.** Whether a pet survives on DatsMe is host state; building a
  channel for it is a DPP protocol change and its own spec.
- **No back-fill.** §13, and it is not a choice — the inputs were never written down.
- **No provenance column on `store_pets`.** SPEC_PET_STORE §1.2 and §10 stand; the digest join
  (§8.3) makes one unnecessary.
- **No signing or tamper-proofing of `design_ref`.** Same posture as the owner fields
  (SPEC_PET_OWNER_FIELD §0.1): anyone who unzips a bundle can edit it. A forged `design_ref` resolves
  to someone else's row or to nothing; neither grants anything, because nothing is gated on it.

---

## §11 The four test questions

1. **Will adding a new variant require an engine/runtime change?** No. A new design axis is a JSON
   file plus a registry entry in `pet_factory/design_axes/`; it lands in `picks_json` with no
   schema change, no migration, and no code edit. A new step-1 door is a new `door` value — a
   string, not a branch.
2. **Will adding a feature require touching unrelated existing files?** Phase 1 touches five seams,
   all named: `_save_reference`, `preview_design`, `start_job`, `db.py`'s schema, and one new
   module. The packer, the pool handlers, the pet runtime, the store and the DPP adapter are
   untouched. Phase 2 adds one stamp beside two existing stamps and one flagged extraction (§6.1).
3. **Will a third-party integration require modifying owned code paths?** No. DatsMe's validator
   tolerates the key today (`pet_assets_service.py:265-277`, verified) and its ownership writer
   preserves it by an explicit documented rule (`pet_ownership.py:126`). The only cross-repo step is
   re-vendoring a test fixture.
4. **Will a bug in one variant force debugging code shared with another variant?** No. Provenance
   is write-only in Phase 1 and read at no runtime path (§0.9). A broken provenance write is
   swallowed (§8.4) and cannot reach a build, a bundle, or a browser. The failure mode is a missing
   row, diagnosable in one table.

---

## §12 Guard tests

Same culture as the rest of the repo: shared validators, floor tests, scoping, and an enforcement
test per rule that could rot.

**`webui/tests/test_design_provenance.py`**

- A designer build writes exactly one row, and every step-2 pick the request carried is present in
  `picks_json`.
- A build from a catalog reference with **no** design writes a row with empty `picks_json` — the
  row exists for every build, not only decorated ones.
- `composed_prompt` on the row equals what `compose_design` returned for those inputs (the two are
  the same string, not a re-derivation).
- **The negative-class test, the important one:** build → `purge_drafts` → the `pets` row is gone and
  the `design_provenance` row remains, with the §8.3 join yielding `survived = 0`. Same for
  `delete_pet`.
- A failed build leaves a row with no pet (`start_job` write position, §8.2).
- **A provenance insert that raises does not fail the build** — monkeypatch the insert to raise,
  assert the job still reaches `done`, the pet is stored, and the bundle carries **no** `design`
  block (the coherent-failure rule, §8.4).
- Append-only: two builds from one reference are two rows; no code path issues an `UPDATE`.
- Scoping: one owner's provenance rows are not returned by another owner's reads (whatever read
  path exists), mirroring `test_scoping.py`.

**`webui/tests/test_design_block.py`** — the bundle side

- A designer build's `manifest.json` carries `design`, and its `prompt` is exactly the string the
  renderer was given (no free text in play) — the round-trip that proves the mechanism.
- **The reattach path produces the same block.** Simulate a restart: write the ledger row, drop
  `JOBS`, drive the pool-reattach entry (`webui/app.py:655`) with the same bundle, assert the block
  is present and identical. This is the test for the trap §3.4 Move 2 names — it would pass
  trivially with a `Job`-carried block and fail exactly when it matters.
- The block survives `pet_ownership.transfer_pet_ownership` and `stamp_bundle_fingerprint` in either
  order (the patch-never-rebuild rule, both sides).
- Every other manifest key is byte-identical to the packer's output; the key set differs by exactly
  `{design}`.
- A store-adopted pet's block is inherited unchanged from the shelf bundle
  (`webui/pet_store.py:70` is not modified).

**`webui/tests/test_provenance_privacy.py`** — the rule of §5, made mechanical

- **The one that matters:** build with `extra = "my daughter Freya"`, `animal = "cat"`, a colour and
  an accessory. Assert that **no member of the resulting zip** — manifest, package, sprite
  filename — contains the substring `Freya`, while `design.prompt` *does* contain the colour and the
  accessory. This is the §5.2 carve-out, verified end to end rather than at the function boundary.
- `prompt_public == compose_design(..., extra="")[0]`, and equals `composed_prompt` exactly when
  `extra` is empty — the golden pin that a composer reorder cannot silently break (§5.2).
- **The whitelist enforcement test:** every column of `design_provenance` is either in
  `PUBLIC_FIELDS` or in an explicit `PRIVATE_FIELDS` tuple, and the two are disjoint and exhaustive.
  A new column fails the build until someone classifies it (§4.4).
- `public_block` output contains no key whose value appears in the private columns —
  a direct assertion that `still_seed`, `tier`, `external_user_id`, `extra_text` and
  `composed_prompt` never reach a bundle.
- `_reference_record` (`webui/app.py:711`) does not serialize `composed_prompt`, `extra_text`, or
  `picks` — the browser projection stays a projection.
- `design_ref` is not derivable from the owner id, the anon cookie, or the `reference_id`: mint many
  under a fixed owner and assert no shared prefix and no substring relationship.
- `strip_design_block` removes `design` and leaves every other key untouched (§5.3), including the
  owner fields.

**`webui/tests/test_design_axes.py`** (extend) — the corrected posture of §3.6

- `/api/design-axes` still withholds `prompt_fragment`. The existing guard stays; what changes is the
  endpoint's docstring at `webui/app.py:1233`, which must stop claiming fragments never reach
  anyone. A stale comment here is how someone later "restores" the old behaviour and silently strips
  the block.

**`webui/tests/test_scoping.py`** (extend)

- `design_provenance` is **not** in the claim-handler registry (§8.5) — the `ai_usage` enforcement
  test, extended to a second ledger rather than duplicated.

**`pet_factory/tests/test_pack_bundle_layout.py`** — **unchanged, and that is the assertion.** The
packer's output is byte-identical; if this file needs an edit, §7 has been violated.

**Cross-repo** — `webui/tests/fixtures/owner_fields.json` gains a `design` block case; the vendored
copy in `datsme_me` is re-vendored and both pinned checksums updated (SPEC_PET_OWNER_FIELD §2.3a).
Two host-side assertions: `validate_uploaded_bundle` accepts a bundle carrying `design`, and a
**full round trip** — import → `write_assets` → `build_bundle_zip` → re-read — returns the block
intact. The second is the one that would have caught the fourth-zip-member mistake (§3.1), so it is
worth having even though the answer is already known.

**Posture** — the existing GPU-less import test covers `webui/design_provenance.py` and
`webui/bundle_manifest.py` automatically; confirm they appear in it.

---

## §13 The retroactive gap

**Every pet built before Phase 1 has no provenance, and it cannot be reconstructed.** Not
"expensively" — at all. The composed prompt was discarded at `webui/app.py:1342` and never written
anywhere; the reference sidecars that held the typed text are swept at 24 h
(`webui/app.py:1842`); the seed was never returned by anything (§1.2). What survives in a bundle is
the species phrase (`package.json` `display_name`), the pose set (`animations`) and the body type
(`movement_class`) — enough to say what the pet *is*, nothing about what was *chosen*.

**Do not back-fill, and do not synthesize.** A row assembled from `breed_id` and `pose_count` would
be indistinguishable from a real one in a query, and would silently teach the corpus that a large
early cohort made no design choices — which is false, and is exactly the kind of quiet corruption
that is unfixable once someone has fitted anything to it.

**What is done instead, and it is enough:**

- `schema_version` on every row, so eras are separable by construction.
- **Every corpus query filters on the presence of a provenance row**, not on `pets`. The join in
  §8.3 starts `FROM design_provenance` for this reason: pre-epoch pets simply are not in it.
- The gap is bounded and shrinking, and it does not drain the way the owner-field legacy population
  does (SPEC_PET_OWNER_FIELD §2.5's gift heals a bundle; nothing heals a lost prompt). It closes
  only by time passing with Phase 1 live.

**Which is the one argument for shipping Phase 1 before the rest of this spec is agreed.** §9.2 and
§9.3 can be argued for as long as they need. Phase 1's cost of delay is permanent.

---

## §14 Open questions for the owner

**14.1 The fragment vocabulary becomes public — confirm.** (§3.6.) Shipping `prompt` means anyone
holding a bundle can read the calibrated `prompt_fragment` wording for every axis the pet used, and
`/api/design-axes`'s "never reaches the browser" comment stops being the whole truth. Nothing breaks;
the wording simply stops being a secret. This is the one consequence of the owner's direction that is
worth confirming explicitly rather than discovering later, and it is **irreversible for pets already
minted** — a bundle in someone's house cannot be unshipped.

**14.2 The free-text carve-out — keep it, or publish everything?** (§5.2.) Default in this spec:
`extra` stays private, at a cost of one extra call to a pure function and a second column. Publishing
it too is one argument change. The recommendation is to keep the carve-out, because `extra` is the
only design input that is a *sentence* rather than a *choice*, and because Phase 2 of the store makes
a user's pet reach strangers by donation. If the owner disagrees, this is a small, clean reversal —
but again only forward.

**14.3 Is Phase 3 wanted at all?** (§9.3.) The only phase that costs a fleet roll. Without it the
corpus is comparative but not reproducible, and §2.3 says so plainly rather than implying otherwise.

**14.4 One thing that is NOT a question.** The ledger is not optional, whatever is decided about the
bundle. Everything in the `design` block dies with its pet, and the pets the corpus most needs to
learn from are the ones that were thrown away (§3.3, §8.2). If only one half of this spec is built,
build the ledger.
