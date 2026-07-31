# SPEC_PET_STORE — The Pet Store: a database-backed shop of ready-made pets

**Status: Rev.6 (2026-07-31) — PHASE 1 LIVE IN PRODUCTION; PHASE 2 SPECIFIED,
NOT STARTED.** Phase 1 deployed host-first (§13) to staging and then production
the same day, C1-verified 14/14 on both tiers, with the §12 store E2E passing on
staging's real infrastructure (flat 50 quoted + charged; the pose formula would
have said 110). §14 is the as-built ledger and the only place to read for "what
is done"; §14.4 records the deploys. **§10 is now a build-ready specification
rather than a sketch** — it needs owner sign-off before code, and §10.0 records
the three constraints that moved the design.

Supersedes the file-based samples surface of `SPEC_DATSPET_CATALOG_PURCHASE`
(archived, executed 2026-07-30) — see §8 for exactly what it absorbs and retires.

<details><summary>Revision history</summary>

**Rev.2 (2026-07-30)** — draft for owner review. Folded in the owner's pricing
direction (the price is a host knob; its value is not this spec's concern) and
the design-review fixes: the AI draft is best-effort, the migration publishes the
already-live sample (no empty-shop window), host-first deploy order, tag
normalization, and Phase 2 mint hardening on the host side.

**Rev.3 (2026-07-31)** — accepted for implementation. Four readiness
clarifications, all since verified against the built code (§14): publish-from-pet
reads its source pet through the caller's own owner scope (§3.2); the export seam
names `export_pets` (§7.2); the physical sample files outlive the §8 code
retirement by one deploy cycle (the migration script must read them); and
`animal` moved from derived to seeded-and-confirmed (§1.3) — a typed-animal
bundle carries no canonical species key to derive it from.

**Rev.4 (2026-07-31)** — status corrected from "nothing is built" to as-built,
which it had stopped being. Adds §14 (as-built ledger) and §8.1 (the retirement
ordering rule the build violated). Records that the host's price-basis test ran
nowhere and how that was fixed.

**Rev.5 (2026-07-31)** — deployed. §14.4 records the staging and production
deploys, the E2E results, and the completed §8 sample-file deletion.

**Rev.6 (2026-07-31)** — Phase 2 specified for build. §10 goes from a
decision-level sketch to a buildable section, and three of the sketch's
assumptions did not survive contact with the code (§10.0): a host writeback is
bound to a 60-minute launch token, so the mint **cannot** fire at the admin's
approval click and instead rides the donor's next launch (§10.7); neither host
pull channel delivers in the background, so an approved reward is *owed* until
the donor appears; and DatsPet has no draft-purge clock, so a rejected pet comes
back as a **kept** pet, not a draft that the donor's next Design click would
destroy (§10.5). Also settled here: no claim handler for the donation ledger
(the `ai_usage` rule), donations require a DatsMe identity, unstamped legacy
pets are refused, and the reward knob ships at **0**.

</details>

---

## §0 What this is, and the four decisions already made

A user today can only bring a pet to life that she designed herself (~3 min of
GPU, priced by pose count at DatsMe's checkout). The Pet Store adds the other
door: **browse a shelf of ready-made pets — with portraits, descriptions, and
searchable tags — and adopt one instantly, for one flat price** (the owner's
knob — typically below designing, which burns real GPU, but possibly equal;
§0.2). Later, a user whose 50-pet house is full can **donate** a pet she
made to the store; an admin reviews it, and on approval she earns credits.

The store is not a new idea in this codebase — adopt-a-premade shipped to
staging as `SPEC_DATSPET_CATALOG_PURCHASE` and was verified with a real
purchase. What that spec deliberately did not build is exactly what this one
does: a **database-backed inventory** (so admins can stock production at
runtime — prod's content dirs are read-only by design), **listing metadata**
(descriptions, tags, search), **a store price**, and **donations**.

Four product decisions were made by the owner on 2026-07-30 and are fixed
inputs to this design:

| # | Decision | Choice |
|---|---|---|
| 0.1 | Scope of v1 | **Admin-curated only.** Donations are Phase 2, shipped separately. |
| 0.2 | Pricing | **A flat host-side credit knob** (`credit_pet_store_cost`), set at the host admin credits screen like every other knob. One price for any store pet, regardless of poses. Expected at or below the design formula (a store adopt burns no GPU; designing does) and possibly equal to it — the value is the owner's dial, never this spec's concern. DatsMe remains the only charger. |
| 0.3 | Descriptions | **AI-drafted from the pet's portrait, admin-edited before publishing.** |
| 0.4 | Donor reward | **Credits, minted at admin approval** — never at submission. §10.5 carries the anti-farming design this choice requires. |

### §0.5 The posture that must not change

Three rules inherited from prior specs are load-bearing here and repeated
because the store touches all of them:

1. **One checkout.** Adopting a store pet ends in `handOffToDatsme` exactly
   like a designed pet (SPEC_DATSPET_CATALOG_PURCHASE §0.3). DatsPet renders
   no prices, holds no balance, and cannot charge. If the store page ever
   appears to need a pricing call, the hand-off helper was reimplemented
   instead of reused.
2. **DatsPet writes only unsold ownership states** (SPEC_PET_OWNER_FIELD
   §2.4). Store inventory is `factory`-state content; the buyer is stamped by
   the host at its checkout, never here.
3. **The GPU-less posture.** Every new `webui/` module in this spec imports
   stdlib + FastAPI + the existing webui PIL pin only. No ML imports.

---

## §1 Vocabulary and data model

### §1.1 Words

- **Store pet** — one row of store inventory: bundle bytes + listing metadata.
  Content, not a user's pet. Nobody owns it; adopting it *copies* it.
- **Listing** — the browser-facing slice of a store pet: name, description,
  tags, animal, pose count, preview. Never the bundle bytes.
- **Published** — a store pet visible to shoppers. Unpublished rows exist so
  an admin can stage, caption, and edit before going live.
- **Donation** (Phase 2) — a user's own designed pet submitted to the store
  queue. Becomes a store pet only through admin approval.

### §1.2 The `store_pets` table (new, in `datspet.db`)

A **separate table**, not flagged rows in `pets` — and this is a boundary
decision, not a convenience. The `pets` table is scoped by `_scope_clause`,
which is exact-match on owner *as a security invariant* (`webui/db.py:341-352`,
guarded by `test_scoping.py`). A store pet is visible to everyone; no owner
value can express that, and widening the clause is exactly the bug the
exact-match fix removed. Separate table, separate read path, zero contact with
the scoping rule. It also passes the change-cadence test: a house pet changes
for user-lifecycle reasons (draft, keep, delete, writeback); a store pet
changes for merchandising reasons (description, tags, published). Different
reasons, different places.

```sql
CREATE TABLE IF NOT EXISTS store_pets (
    id              TEXT PRIMARY KEY,   -- minted once at creation, never changes
    display_name    TEXT NOT NULL,
    breed_id        TEXT NOT NULL,
    animal          TEXT NOT NULL,      -- catalog animal key ("cat"), the top-level filter
    description     TEXT NOT NULL DEFAULT '',
    tags_json       TEXT NOT NULL DEFAULT '[]',  -- JSON array of lowercase strings
    pose_count      INTEGER NOT NULL,   -- derived from manifest at insert (like bundle_sha256)
    published       INTEGER NOT NULL DEFAULT 0,
    created_at      REAL NOT NULL,      -- unix epoch float, matching pets
    bundle_sha256   TEXT NOT NULL,      -- derived at insert
    size_bytes      INTEGER NOT NULL,   -- derived at insert
    preview_png     BLOB NOT NULL,      -- portrait for cards, extracted at insert
    sheet_png       BLOB NOT NULL,
    manifest_json   TEXT NOT NULL,
    package_json    TEXT,
    bundle_zip      BLOB NOT NULL
);
```

Blobs in-row, mirroring `pets` (`webui/db.py:1-19`) — one store, one pattern.
Derived columns (`pose_count`, `bundle_sha256`, `size_bytes`, `preview_png`)
are computed inside the insert function from the bytes it is handed, so a row
can never disagree with its own bundle — the same by-construction rule
`insert_pet` already follows.

Deliberately **absent**: any owner column (nobody owns inventory), any
`draft` column (`published` is the store's own word and does not interact with
the draft purge sweeps), any source/provenance column (§2 — a store pet that
arrived by donation is indistinguishable at runtime from one an admin made;
donor facts live on the Phase 2 donation row, which is audit, not engine
input).

### §1.3 Listing metadata: two kinds of facts, two sources

- **Mechanical facts** are derived from the bundle at insert and are never
  editable: `breed_id`, `pose_count`, pose names (read from
  `manifest["animations"]` at read time). Editing these would let a listing
  lie about its artifact.
- **`animal` is seeded, then confirmed** (Rev.3). A bundle carries no
  canonical species key — a typed-animal pet's `breed_id`
  (`white_snow_leopard`) appears in no `catalog.json`. Publish-from-pet seeds
  it by catalog breed lookup, falling back to the last word of `breed_id`,
  and the admin may correct it **while the row is unpublished**; the
  sellability validator refuses to publish an empty one. Once published it is
  fixed — the shop's filter chips depend on it.
- **Merchandising facts** are authored: `display_name`, `description`,
  `tags_json`, `published`. The AI drafts the first two-and-a-half (§4); the
  admin owns the final text.

Tags are plain lowercase strings, not an enum. The design-axes vocabulary
(`pet_factory/design_axes/`) is a natural *source* of tag suggestions, but the
store does not enforce it — a closed tag vocabulary is an abstraction with one
consumer today, and the three-instances rule says wait.

---

## §2 The four test questions, answered up front

Per the owner's global preferences, run before any code:

1. *Will adding a new variant require an engine change?* — Adding a store pet
   is an `INSERT`. Adding a tag is editing a JSON array. Adding an AI purpose
   is one content file. No runtime change for any of them.
2. *Will adding a feature require touching unrelated files?* — The store is
   two new backend modules, one new admin page, one evolved shop page, and
   additive `db.py` functions. The pets/jobs/designer paths are untouched
   except the two named seams: one nullable column on `pets` (§7.2) and the
   claim-registry line if Phase 2 adds an owner-stamped table.
3. *Will a third-party integration require modifying owned code paths?* — The
   host integration is additive: a new field on the export item, a new price
   basis in the host's one pricing function, one new knob. The existing
   designed-pet lane is untouched.
4. *Will a bug in one variant force debugging shared code?* — A broken store
   bundle cannot reach shoppers: the publish gate runs the shared sellability
   validator (§5.3), the same function the guard tests run. A store bug lives
   in `pet_store.py`/`store_admin.py`; the house and designer never call them.

---

## §3 Backend surface

Two new modules, one concern each, both following the established router
pattern (`webui/app.py:170-208`):

### §3.1 `webui/pet_store.py` — the public shop (read + adopt)

| Route | Auth | Returns |
|---|---|---|
| `GET /api/store` | none (anonymous browsing, §0.4 of the catalog spec) | `{pets: [Listing]}` — **published rows only**, newest first. `Listing = {id, display_name, animal, breed_id, description, tags, pose_count, poses, preview_url}`. Never bytes, never unpublished rows. |
| `GET /api/store/{id}/preview.png` | none (an `<img>` has no 401 handler — `owner_scope.py:120-122` precedent) | the `preview_png` blob, long cache headers — safe because a preview is immutable per id (derived once at insert; redraft touches only text). 404 for unknown *or unpublished* ids — unpublished must be invisible, not just unlisted. |
| `POST /api/store/{id}/adopt` | `require_owner` | `{pet_id, display_name, breed_id}` |

**Adopt** is the existing adopt-a-sample primitive re-pointed at the DB, and
keeps its exact order (`app.py:1491-1535`): resolve store row (404 if missing
or unpublished) → `require_owner` → **entitlement check, now enforced
server-side** (§9) → `_enforce_house_not_full` 409 → stamp
`public` ownership + fingerprint on a copy of the bundle → `insert_pet` as a
draft owned by the caller, with `source_store_pet_id` set (§7.2). Fresh
`pet_id` per adopt: two adopts = two pets = two flat charges, the same
"template, not a licence" rule samples had.

After adopt, the flow is the unchanged normal one: the draft appears, the user
keeps it, `handOffToDatsme` prices and charges on the host. No new checkout.

### §3.2 `webui/store_admin.py` — admin CRUD (the `motion_admin.py` template)

Mounted with `dependencies=[Depends(datsme_integration.require_admin_launch)]`,
audited via `admin_common.audit`, **no writability gate** — this is DB-backed
for exactly the reason `settings_admin.py` is: stocking prod must not require
a deploy.

| Route | Does |
|---|---|
| `GET /api/admin/store` | all rows (published and not), listing shape + `published` |
| `GET /api/admin/store/{id}` | one row, full metadata |
| `POST /api/admin/store/publish-from-pet` | body `{pet_id}` — **the stocking door**, §5. The source pet is read through the caller's OWN owner scope (the same scoped access keep/delete use): an admin publishes only a pet she can see in her house, never an arbitrary row by id. |
| `PUT /api/admin/store/{id}` | edit `display_name`, `description`, `tags`, `animal` (unpublished rows only, §1.3), `published`. Tags are normalized on write — lowercased, trimmed, deduplicated, capped by named constants (`STORE_MAX_TAGS = 16`, `STORE_MAX_TAG_LEN = 32`). Flipping `published: true` re-runs the sellability validator (§5.3) and refuses on failure — the admin cannot ship a listing the build would reject. |
| `POST /api/admin/store/{id}/redraft` | re-run the AI listing draft (§4), overwriting description/tags **only if the row is unpublished** — a live listing is the admin's text |
| `DELETE /api/admin/store/{id}` | remove from inventory. Copies already adopted into houses are unaffected (they are copies). |

### §3.3 `webui/db.py` additions

`db.py` stays the one store module. Additive functions only:
`insert_store_pet` (derives the four derived columns; the only writer),
`list_store_pets(published_only)`, `get_store_pet`, `update_store_listing`,
`set_store_published`, `delete_store_pet`. The existing `pets` functions are
untouched except `insert_pet` learning the nullable `source_store_pet_id`
passthrough (§7.2).

---

## §4 The AI listing draft

A new AI purpose — **one content file**, `pet_factory/ai_purposes/store_listing.json`
— in the existing purpose registry (`pet_factory/ai_purposes/registry.json`;
`webui/ai_engine.py` is the call layer and deliberately names no purpose key),
alongside `pet_likeness`. Not a reuse of `pet_likeness`: that purpose serves
the upload door and changes with it; a store listing changes with
merchandising. Same registry, different content file — the plugin pattern
doing its job.

Input: the pet's portrait (the `preview_png` extracted at publish). Output
contract: `{display_name_suggestion, description, tags}` — a shopper-facing
paragraph (2–3 sentences, warm, concrete: colors, markings, mood) and 4–8
lowercase tags.

Runs **only when an admin triggers it** (`publish-from-pet` and `redraft`),
metered in the existing `ai_usage` ledger. It never runs on a shopper request
and never publishes anything by itself — the admin edit-then-publish step is
the quality gate for prose exactly as the sellability validator is for bytes.

The draft is **best-effort**: if the AI call fails or no key is configured,
`publish-from-pet` still creates the row with empty description and tags —
the admin writes by hand, or hits redraft once AI is available. Stocking is
never blocked on AI availability.

---

## §5 Stocking the store (v1: admins only)

### §5.1 The flow — the designer *is* the authoring tool

1. An admin designs a pet through the **normal three-step designer** — on
   production this runs on the pool like any user's pet. No parallel
   authoring surface, no CLI, no GPU box required.
2. From the admin store page, she picks that pet from her house and hits
   **Publish to store** (`POST /api/admin/store/publish-from-pet`). This
   **copies** the pet's bundle into a new *unpublished* `store_pets` row
   (her house copy remains hers), extracts the portrait, derives the
   mechanical facts, seeds `display_name` from the house pet's name, and runs
   the AI draft (§4) — whose `display_name_suggestion` is shown in the editor
   as a suggestion, never auto-applied.
3. She edits the name, description, and tags in the admin editor, then flips
   **published**. The row appears in the shop on the next listing fetch.

Copy, not move, at step 2 — the same semantics adoption already has, and it
keeps the admin's house pet and the store row on their separate lifecycles.

### §5.2 Portrait extraction

`publish-from-pet` extracts a portrait from the sprite sheet's idle frame,
using the webui PIL pin (the logic exists in
`pet_factory/animal_catalog/generate_sample.py:_portrait_from_bundle`; it is
**moved** — not imported — into the webui boundary as part of §8's
retirement, since `pet_factory` scripts are being deleted and `webui` must not
import through the lazy ML boundary for a pure-PIL crop).

### §5.3 The sellability validator — one function, two callers

`webui/store_validation.py` (or a function in `pet_store.py` if it stays
small): a bundle is **sellable** iff it unpacks, has a sprite sheet, a
parseable manifest with a non-empty `animations` map, a portrait, a
non-empty display name, and a non-empty `animal` (the shop's filter chips
depend on it). This is the current guard-test checklist
(`pet_factory/tests/test_catalog_samples.py`) lifted into a shared function —
the `validate_design_profile` pattern: **the admin is blocked at publish and
the build is blocked at test by the same code.** Phase 2's approval door is
this same function's third caller.

---

## §6 The shop frontend

### §6.1 The page

`web/src/app/catalog/page.tsx` **evolves in place** into the Pet Store. The
URL stays `/catalog`: both entry points (landing hero, house empty state)
already link there, the static-export route already exists, and a URL is an
address, not a name. The visible title becomes **"The Pet Store"**.

The page reads `GET /api/store` (replacing the per-animal samples of
`GET /api/catalog`, which loses its `samples` key in §8) and renders:

- **Search box** — case-insensitive substring match over name + description +
  tags.
- **Animal filter** — chips derived from the animals present in the listing
  (never a hardcoded list).
- **Tag filter** — tap a tag on any card to filter by it.
- **Cards** — portrait, name, animal, description, tags, pose count. **No
  price** (§0.5.1): the copy stays "you'll see the exact cost on DatsMe
  before anything is charged", and makes **no cheaper-than-designing claim**
  — the relation between the two prices is a host knob (§0.2) that can change
  under the page. The host's checkout remains the one place a number appears.
- **Adopt this one** — the existing adopt handler, including the
  adopt-then-sign-in resume via `?adopted=<pet_id>`, re-pointed at
  `POST /api/store/{id}/adopt`.

**All filtering is client-side** over the one cacheable listing response.
Inventory is dozens-to-hundreds for years; a server query layer is an
abstraction with no second consumer. The tripwire for revisiting: when the
listing payload itself gets heavy (~200+ rows), filtering moves server-side
— that is a `pet_store.py` change, not a page rewrite.

### §6.2 Admin page

`web/src/app/admin/store/page.tsx`, following the existing admin surfaces:
inventory table (published state visible at a glance), the publish-from-pet
picker (reads the admin's own house via the existing `listPets()`), and the
listing editor (name, description, tags, publish toggle, redraft button).
Linked from the admin nav exactly as motions/design/ai/settings are.

### §6.3 `api.ts`

New client functions in the one adapter: `fetchStoreListings`,
`adoptStorePet`, `storePreviewUrl`, plus the admin calls. The retired sample
helpers (§8) are deleted in the same change — no dual client surface.

---

## §7 Pricing: one new basis on the host

### §7.1 The principle

DatsPet's only pricing input today is `pose_count`, declared per export item
and re-derived by the host from the fetched bytes. The store adds a second
**declared price basis**, not a special case: each export item states how it
is priced, and the host maps basis → formula. Runtime reads the record;
pricing is content.

### §7.2 DatsPet side

- `pets` gains a nullable column `source_store_pet_id TEXT` (ALTER-if-missing
  migration, the established `init_db` pattern). Set by store adopt (§3.1),
  NULL for designed pets. This is the *record* of how the pet came to be —
  the read-time boundary where comparing sources is allowed.
- `_export_item` (`webui/datsme_integration.py:773-804`) adds
  `price_basis: "store_flat"` when `source_store_pet_id` is set, else
  `price_basis: "per_pose"`. `pose_count` stays declared either way (the host
  still validates the artifact against it). The byteless record view that
  feeds it — `export_pets` (`webui/db.py`) — includes the column in its
  SELECT; forgetting that seam silently prices every store pet per-pose.

### §7.3 DatsMe side (small, named, additive)

- New credit knob **`credit_pet_store_cost`** in
  `api/social_ledger/social_ledger_config.py`, admin-editable on the credits
  screen like its siblings. Its launch value is the owner's dial (§0.2); this
  spec fixes the mechanism, not the number. Distinct from
  `credit_pet_adoption_cost`, which prices the host's *own* platform-catalog
  storefront — a different door, untouched here.
- `quote_user_pet_import` and the charge site in
  `api/apps/dpp/pet_writeback.py` price by the item's declared basis:
  `store_flat` → the knob; `per_pose` (or absent, for old partners) → the
  existing `price_user_pet` formula. Quote and charge keep using the same
  function so they cannot drift, and the quote-binding invariant (host never
  charges above the quote) is untouched.
- Idempotent re-delivery is unchanged: keyed on `(partner_slug,
  source_item_id)`, and each store adopt mints a fresh pet id, so each is its
  own purchase — deliberate, as today.

---

## §8 The store subsumes file samples — finish the refactor

Two premade-pet systems may not coexist. In the same phase the store ships:

- **Migrate**: a one-shot `scripts/migrate_samples_to_store.py` reads each
  `pet_factory/animal_catalog/<animal>/samples/<key>.{zip,png}` and inserts a
  **published** `store_pets` row — a shipped sample is already-live,
  guard-tested public content, and migrating it unpublished would open a
  window where the shop replaces the sample grid with an empty shelf. The
  shipped `.png` becomes `preview_png` (no PIL in the script), the sample key
  title-cased becomes the name, and the description starts as a one-line
  deterministic caption the admin polishes afterwards (redraft is available).
  Run once per environment. Today that is exactly one pet (cat/snowleopard).
  **The script reads the physical files, so they must still exist when it
  runs** (Rev.3): the sample *code* retires in the Phase 1 commit, but the
  content files under `<animal>/samples/` are deleted only after the last
  environment has migrated — a named line on the deploy checklist, not a
  leftover.
- **Retire**: `list_samples` / `sample_bundle_path` / `sample_preview_path`,
  the `samples` key on `GET /api/catalog`, `POST
  /api/catalog/{animal}/samples/{sample}/adopt` and its preview route, the
  sample grid on the catalog page, the sample client helpers in `api.ts`,
  `generate_sample.py`, `promote_sample.py`, the `_candidates/*/samples/`
  staging dirs, and — one deploy cycle later, per the Migrate note — the
  sample files themselves. `test_adopt_sample.py` and
  `test_catalog_samples.py` are replaced by the store equivalents (§12).
- **Keep**: everything about breeds — `catalog.json`, `base.png` curation
  (`generate_candidates.py`, `promote_candidate.py`), the designer's base
  images. Those are designer inputs, not store inventory.
- **Fix stale docs in the same change**: `CLAUDE.md:88` and
  `SPEC_PET_DESIGNER_FLOW` §11.2 still claim adopt-a-premade has no UI;
  after this spec they should describe the store.

Pre-launch, no back-compat (the standing rule): the sample endpoints get no
deprecation window.

### §8.1 The retirement ordering rule — learned here, not theorised

**The backend surface and the frontend that calls it retire in the SAME commit.**

The Phase 1 build broke this and the tree stopped compiling. `app.py` and
`animal_catalog/__init__.py` dropped the sample routes and `api.ts` dropped
`adoptSample` / `catalogSamplePreviewUrl` / the `samples` key, while
`catalog/page.tsx` still imported and called all three — five `tsc` errors, so
`npm run build` could not run at all.

That is worse than an ordinary bug, because of what the deploy checklist already
records: **a build that dies leaves the previous `.next` in place with an
unchanged `BUILD_ID`**, so the deploy reports success and silently serves the old
bundle. A retirement that lands backend-first is therefore not "briefly broken",
it is a false-green deploy waiting to happen.

Fixed in the build; recorded here because the next retirement will be tempted the
same way. A `tsc --noEmit` on the frontend is the cheapest possible check that a
backend retirement was complete, and it belongs in the same commit.

---

## §9 Entitlement, enforced server-side

`can_adopt_samples` (renamed nowhere — the field name is the contract; its
meaning is "may adopt premade pets") is today advisory only: the catalog spec
§0.6 documents that a direct POST bypasses it. The store adopt endpoint closes
this: `resolve_launch_capabilities` → `resolve_entitlement` →
`can_adopt_samples` is checked **in `POST /api/store/{id}/adopt`**, 403 on
false. The tier table stays the one place the entitlement is defined; both
tiers keep it `true` today, so nothing user-visible changes until the
business lever is pulled.

---

## §10 Phase 2 — donations (specified for build, Rev.6)

A user gives a pet she designed back to the store; an admin reviews it; on
approval she earns credits. It is the supply side of the store: Phase 1 makes
every listing cost the owner admin time and GPU minutes, and this makes the
users the supply. It is also the pressure valve on the 50-pet house cap —
donating frees a slot *and* pays, where deleting just frees a slot.

The owner's four Phase 1 decisions (§0) carry over unchanged. Decision 0.4 —
**credits, minted at admin approval, never at submission** — is the one that
shapes everything below.

### §10.0 Three constraints found in design, before any code

The Rev.2 sketch assumed three things the code does not do. Each was checked
against the two repos and each moved the design; they are recorded here because
a reader who skips them will re-propose the sketch.

1. **A host writeback is bound to a launch, and the donor is not present at
   approval.** `authenticate_writeback` (`datsme_me/api/apps/dpp/service.py:807`)
   requires a `launch_token` in the body — a JWT whose `jti` names an unburned
   `IntegrationNonce`, `LAUNCH_TOKEN_TTL` 60 minutes — and the burn is one-time
   (`burn_launch_nonce`, `:893`). An admin clicking approve on Tuesday has no
   launch token for a donor who left on Monday, and could not keep one alive if
   she did. **The mint therefore cannot fire at the approval click.** §10.7
   moves it to the donor's next launch, which is the moment a valid token
   exists.
2. **Neither host pull channel is a background delivery channel.**
   `/sync-pending` (`routes.py:304`) carries *metadata* only — it turns partner
   rows into launch URLs and has no scheduler job and no UI caller today. The
   import pull *does* reach `apply_writeback`, but it is `PULLABLE_TARGETS`-gated
   and checkout-shaped (`_IMPORT_ADAPTERS` requires a `quote`). Nothing in the
   system delivers a partner-originated event to a user who is not clicking.
   So a reward is *owed* until the donor appears; the owed state is the queue.
3. **DatsPet drafts are volatile — there is no purge clock.** `purge_drafts`
   (`webui/db.py:436`) is an unconditional `DELETE … WHERE draft=1`, fired at
   startup and on *every* `/api/generate` by that caller. The sketch's "the
   rejected pet returns as a draft with a fresh `created_at` so the purge clock
   restarts" describes a clock that does not exist: the returned pet would die
   at the donor's next Design click or the next backend restart. §10.5 returns
   it as a **kept** pet instead.

A fourth, smaller one: **DatsPet has no outbound HTTP stack at all.** The push
path was deleted, not disabled (`webui/app.py:1876`, `datsme_integration.py:9`),
and `httpx` there is a dead import. §10.7.3 is explicit that this is new code
and why it is worth adding.

### §10.1 Vocabulary and the donate door

- **Donation** — one `store_donations` row: the bundle bytes, the donor, a
  status, and the reward's delivery state. It is a **ledger row**, not a pet.
- **Owed** — an approved donation whose reward has not yet reached the host.
- **Delivered** — the host acknowledged the award; the credit exists.

**Who may donate.** Three gates, all server-side, in this order:

1. **A DatsMe identity.** `owner_scope.require_owner` plus a non-anonymous
   `external_user_id`. A standalone/anonymous user has no account for credits to
   land in, so the door 403s rather than accepting a donation it can never pay.
   This is also why §10.2 registers no claim handler (see there).
2. **The entitlement.** New tier field `can_donate` (`pet_factory/tiers/`),
   resolved exactly like `can_adopt_samples` — `resolve_launch_capabilities` →
   `resolve_entitlement` → 403. It ships `true` on both tiers, so nothing is
   user-visible until the lever is pulled; it exists so that turning donations
   off is a data edit, not a deploy.
3. **Her own designed pet.** `read_pet_ownership(row["manifest_json"])[0]` must
   equal `FACTORY_CATEGORY` (`webui/pet_ownership.py:194`). A store-adopted pet
   carries `public` and is refused — that one check closes the laundering loop
   (adopt cheap → donate back → collect) with no new bookkeeping.
   **A pet with no owner fields at all is refused**, not assumed: legacy and
   folder-migrated rows read `(None, None, None)`, and `pet_ownership`'s rule is
   that absence is never coerced into a category. A donor with such a pet can
   rebuild it; a wrong guess here mints credits for provenance nobody knows.

**Trigger surfaces** (§10.9): a **Donate** action on house cards, and the
house-full line extended to "house full — remove one to make room, **or donate
one**".

### §10.2 The `store_donations` table

Append-only in spirit: `status` transitions forward and the row is the audit
trail. It lives in `datspet.db` beside `store_pets`, and it holds the bytes,
because a donation that has left the house must survive review even if the
donor deletes everything else.

```sql
CREATE TABLE IF NOT EXISTS store_donations (
    id                TEXT PRIMARY KEY,   -- minted once, the reward's idempotency key
    external_user_id  TEXT NOT NULL,      -- the donor; NEVER NULL (§10.1 gate 1)
    display_name      TEXT NOT NULL,
    breed_id          TEXT NOT NULL,
    pose_count        INTEGER NOT NULL,   -- derived at insert
    bundle_sha256     TEXT NOT NULL,      -- derived at insert
    size_bytes        INTEGER NOT NULL,   -- derived at insert
    preview_png       BLOB NOT NULL,      -- extracted at insert (the review card)
    sheet_png         BLOB NOT NULL,
    manifest_json     TEXT NOT NULL,
    package_json      TEXT,
    bundle_zip        BLOB NOT NULL,
    submitted_at      REAL NOT NULL,
    status            TEXT NOT NULL,      -- pending | approved | rejected | returned
    reviewed_at       REAL,
    admin_note        TEXT NOT NULL DEFAULT '',
    store_pet_id      TEXT,               -- set on approve: what it became
    reward_state      TEXT NOT NULL DEFAULT 'none',  -- none|owed|delivered|declined
    reward_delivered_at REAL
);
```

Derived columns are computed inside `insert_donation` from the bytes it is
handed — the by-construction rule `insert_pet` and `insert_store_pet` follow.

**`status` and `reward_state` are two axes, deliberately.** Status is the
admin's decision; reward state is a delivery fact that moves on its own clock
(§10.7) and can retry without re-deciding anything. Collapsing them would make
"approved but not yet paid" unrepresentable, which is the normal state for as
long as the donor stays away.

**No claim handler, and this is the rule not an omission.** `owner_scope.py:185`
is explicit that `ai_usage` is deliberately unregistered because a claim handler
rewrites an append-only ledger's history. `store_donations` is the same shape,
and §10.1's first gate means a donation can never be created under an anonymous
id in the first place — so there is nothing for a handler to move. **Do not
"complete" the registry by adding it.**

### §10.3 The donate endpoint

`POST /api/pets/{pet_id}/donate` in a new `webui/donations.py` (`require_owner`,
the store's module-per-concern pattern; stdlib + FastAPI + the webui PIL pin —
the GPU-less posture).

Order, and it is the adopt order read backwards:

1. `require_owner` → non-anonymous check (§10.1 gate 1) → 403.
2. `resolve_entitlement().can_donate` → 403.
3. `db.get_pet_for_owner(pet_id, external_user_id=owner)` → 404 if absent **or
   not hers** (scoped read, no TOCTOU — the store admin's publish door uses the
   same one).
4. `read_pet_ownership` category must be `factory` → 422 with the reason.
5. **Pending cap**: a donor with `DONATION_PENDING_CAP` (3, a named constant)
   rows in `pending` gets 409. Queue spam is bounded at the door, and the cap is
   what makes "a human reviews every credit" survive contact with volume.
6. `sellability_errors` (§5.3, its third caller) → 422 if the bundle could never
   be sold. Refusing here is kinder than accepting a donation the admin must
   reject, and it is the same function the publish gate and the build use.
7. Insert the donation row (`pending`, `reward_state='none'`), extract the
   portrait with the admin's own `_portrait_from_bundle`, then **delete the
   house row** — insert first, delete second, so a crash between them leaves a
   duplicate (recoverable) rather than a vaporised pet (not).
8. Drop the in-memory `JOBS` entry for that pet id, as `delete_pet`'s route
   wrapper does.

**Donating moves the pet** (the slot frees immediately — that is the product
point), and the move is *the donor's copy only*: nothing about a donation
touches another user's house, and the bundle keeps its `factory`/`datspet`
stamp all the way through (§10.6).

### §10.4 Review — the admin door

`store_admin.py` grows the donation routes under the same router (same
`require_admin_launch` dependency, same `admin_common.audit` tag):

| Route | Does |
|---|---|
| `GET /api/admin/store/donations` | the queue: pending first, then recently reviewed. Listing shape + donor id + `reward_state` |
| `POST /api/admin/store/donations/{id}/approve` | body `{admin_note?}` |
| `POST /api/admin/store/donations/{id}/reject` | body `{admin_note}` — a reason is required; the donor sees it (§10.8) |

**Approve** = `sellability_errors` re-run (bytes can only have gone stale, never
fresh) → `insert_store_pet` as an **unpublished** row, which then walks the
normal §5 caption/edit/publish path → `status='approved'`, `store_pet_id` set →
**`reward_state='owed'`**. The mint does not happen here (§10.0 constraint 1);
approval only makes it owed. Publishing stays a separate, later click, so an
approved-but-unpublished donation is a normal state.

**Reject** = `status='rejected'` + the note, then the return in §10.5.

Deleting a store pet that came from a donation leaves the donation row alone —
it is audit, and the store row's later life is not the donor's business.

### §10.5 Return on reject — as a kept pet, not a draft

The sketch said "returns to the donor's house as a draft". §10.0 constraint 3
kills that: drafts are destroyed by the donor's next Design click. So:

- Reject re-inserts the bundle into the donor's house with `draft=0` — a kept
  pet, the state it was in when she donated it — under a **fresh `pet_id`**
  (the original id is gone and may have been reused in her local state), and
  sets `status='returned'`.
- **If her house is full at that moment**, the re-insert is skipped and the row
  stays `rejected` with its bytes. The donor sees it in §10.8's list with a
  **Restore** action that runs the same re-insert, cap-checked, when she has
  made room. A rejected donation is never silently destroyed and never forces
  her over the cap.
- Rejection pays nothing: `reward_state` stays `'none'`. There is no path from
  `rejected` to a credit.

### §10.6 Ownership at approval — still nothing to write

A donated bundle arrives `factory` / `datspet` (guaranteed by §10.1 gate 3), and
that is already the store's unsold state. **No ownership write happens on the
donation path at all** — not at donate, not at approve, not at publish. The
buyer is stamped by the host at its checkout, exactly as for an admin-made
listing. SPEC_PET_OWNER_FIELD §2.4's "DatsPet writes only unsold ownership
states" stands untouched, and a store pet that arrived by donation remains
indistinguishable at runtime from one an admin made (§1.2).

### §10.7 The reward — how a credit actually reaches the donor

#### §10.7.1 The shape the constraints force

Approval makes a reward **owed**. Delivery happens the next time the donor
launches DatsPet from DatsMe, because that is the only moment a valid launch
token for *that donor* exists (§10.0.1). The donation row is the retry queue:
`owed` survives restarts, deploys and failed attempts, and needs no separate
retry store, no drain tick, and no scheduler.

Consequence to state plainly: **the reward is not instant.** A donor who never
returns is never paid. That is acceptable — DatsPet has no notification channel
(§11), the credits are usable only on DatsMe anyway, and the alternative is a
background push channel the host does not offer.

#### §10.7.2 One writeback per launch, so awards batch

`authenticate_writeback` burns the launch nonce, and the burn is one-time — so
a launch carries **one** writeback. A donor with three owed rewards therefore
gets **one** writeback carrying **three** award entries, not three writebacks.
The payload is a list keyed by donation id; the host mints each idempotently
(§10.7.4). At a few dozen bytes per entry this is nowhere near
`MAX_WRITEBACK_BODY_BYTES` (64 KB).

#### §10.7.3 DatsPet side — the first outbound call

New module `webui/reward_delivery.py`. One concern: turn `owed` rows into a
signed POST and record the outcome.

- **Trigger**: the donor's launch. `datsme_integration.launch` already verifies
  the token and stores the **raw JWT in the launch cookie** (re-verified per
  request at `:349`), so the raw token needed for the writeback body is in hand
  for the whole session — this is the fact that makes the design work, and it
  is worth pinning with a test.
- **Delivery is best-effort and off the critical path.** The launch redirect
  must never wait on the host: a failed or slow mint may not break a donor's
  visit. Fire it after the response is on its way (the existing
  `run_in_threadpool`/background pattern), and on any failure leave
  `reward_state='owed'` — the next launch retries. **No new retry queue.**
- **Signing**: the SDK's `sign_writeback` + `post_writeback`
  (`datsme_me/api/sdk/datsme_partner_sdk/writeback.py`) — already installed,
  never yet imported here. `WritebackBuilder` is *not* used: it defaults the
  idempotency key to the launch `jti`, which is wrong for us (a retry on a later
  launch must reuse the same key). **The idempotency key is derived from the
  donation ids in the batch**, so a retry is byte-identical and the host's
  replay cache and business key both recognise it.
- **On HTTP 200**: mark every id in the batch `delivered` with a timestamp. On
  anything else: leave them `owed`, log, and let the next launch try. On a
  host-side refusal that is permanent (`capability_not_granted`), mark them
  `declined` so a revoked capability does not retry forever — `declined` is
  visible in the admin queue and re-armable.

**This reverses "DatsPet never pushes" and the reversal is deliberate.** The
push path was retired because *pet delivery* is better as a pull: bundles are
megabytes, need quotes, and the host's import checkout already owns idempotency.
None of that applies to a 200-byte reward notice that mints nothing on DatsPet's
side and carries no bytes. The rule that survives is the one that mattered:
**DatsPet still never charges, never quotes, and never moves a pet by push.**
`SPEC_DATSPET_FEDERATED_SESSION` §6.2a should record this narrowing when Phase 2
lands.

#### §10.7.4 Host side — four registry entries, one table, two knobs

The host's writeback dispatch is a plugin registry, so this is content, not
engine (`test_dpp_registry_consistency.py` is the guard that fails a half-formed
entry — it defines the checklist):

1. `_TARGET_HANDLERS["user.credit_award"]` (`service.py:1233`) → a thunk into a
   new `apps/dpp/credit_award.py`, the way `user.pet` thunks into
   `pet_writeback.py` rather than growing `service.py`.
2. `REQUIRED_CAPABILITY_BY_TARGET["user.credit_award"] = "credits.award"`
   (`service.py:1033`).
3. `SUPPORTED_SCHEMA_VERSIONS` entry (`manifest.py:57`).
4. A new `Capability("credits.award", "Award you credits", risk=…)`
   (`capabilities.py:46`).
   **Risk must be `medium`, not `low`** — not because the user is endangered
   (they are not; this only ever adds), but because `should_auto_grant`
   (`capabilities.py:222`) auto-grants *any* low-risk capability to an official
   partner without a consent screen, and the platform's money supply is not
   something to grant silently. Medium forces the screen where the user reads
   "DatsPet can award you credits."
   **Not** added to `PULLABLE_TARGETS` — this target is push-only.

**Idempotency: a new social-DB table with a unique business key.**
`partner_credit_awards(partner_slug, award_key)` unique — `award_key` is the
donation id — plus `user_id`, `amount`, `created_at`. Modelled on
`uq_partner_collection_external` (`models.py:242`) for the key shape and on the
Stripe webhook's **claim-before-mint** ordering (`payment_service.py:396`): insert
the claim row first, in the same transaction as the ledger row, so a duplicate
delivery loses the race on the unique index instead of minting twice.
Deliberately *not* the replay cache (24 h TTL, and a donor who returns on day 3
would double-mint) and *not* the launch nonce (it bounds a launch, not a
donation — the exact bug `pet_writeback.py:466` records for pets).

**The mint itself** follows `award_activity_completion_credits`
(`social_ledger_service.py:471`): a platform-style award from `datsme.1` with no
debit, one `LedgerTransaction`, and the caller owning the commit.

**Two knobs**, both in `SOCIAL_LEDGER_CONFIG_DEFAULTS` and both in
`CREDIT_CONFIG_KEYS` — the Phase 1 lesson (a seeded knob missing from that list
is invisible to the admin screen), now guarded by the subset test:

- `credit_pet_donation_reward` — **default `"0"`**. The reward ships *off*.
  Turning it on is a deliberate admin act after the owner has watched the queue.
  A zero amount short-circuits the mint but still marks the donation delivered,
  so donors are not paid retroactively when the knob later moves.
- `credit_pet_donation_daily_cap` — the per-partner ceiling, enforced
  lock-then-count-then-insert exactly like `award_generosity_reward`
  (`social_ledger_service.py:739`), which is the house pattern for a daily cap.
  A partner over its cap gets a refusal the partner records as `owed` and
  retries tomorrow.

**Partner-scoped bookkeeping**: `partner_credit_awards` is partner-scoped, so it
must be added to the eviction/purge delete list (`admin_routes.py:713`), the
divorce-preview counts (`:497`), and `write_partner_bundle` (`audit_bundle.py:177`)
— protocol §22a requires every partner-scoped table be expressible as
`DELETE … WHERE partner_slug = ?`.

#### §10.7.5 Why it cannot be farmed

Generating is free in credits (it costs the owner GPU), so generate → donate →
reward is a money printer unless every step is gated. It is:

- **A human mints every credit.** The only transition into `owed` is the admin's
  approve click. No reward at submission, none at publication.
- **Only your own designed pets** (§10.1 gate 3) — a store-adopted pet is
  `public` and refused, so credits cannot be laundered through the shelf.
- **Three pending per donor** (§10.3 step 5) — the queue stays reviewable, which
  is what makes the human gate real rather than nominal.
- **The knob ships at 0** and the daily cap bounds the blast radius of a stolen
  partner secret to one day's worth of credits.
- **The award is idempotent on donation id**, so replaying a captured writeback
  mints nothing.

The residual risk, stated rather than hidden: a compromised `DATSME_HMAC_SECRET`
lets an attacker mint up to the daily cap per day until the partner is disabled.
That is why the cap is not optional and why `credits.award` is a consented
capability the user can revoke.

### §10.8 What the donor sees

§11's "the house's donation status is visible on next visit" cannot work as
written — §10.3 deletes the house row, so there is no card left to carry a
status. Instead: a **Donations** section on the house page, fed by
`GET /api/donations` (own rows only, scoped like every other read).

Per row: the portrait, the name, the status, the admin's note when rejected, and
— for `rejected` rows whose pet has not been returned — the **Restore** action
(§10.5). Credits are never named or counted here: DatsPet renders no balances
(§0.5.1), so a delivered reward reads "accepted for the store", and the number
lives on DatsMe where it always has.

This is a section on a page the donor already visits, not a new route and not a
nav entry. The house page already carries a capacity readout and a selection
bar; a third block is the smallest surface that answers "what happened to my
pet?".

### §10.9 Frontend

- **House card action** — the per-card row (`house/page.tsx`, currently the
  DatsMe-zip anchor + Remove) gains **Donate**, behind the same confirm-modal
  shape Remove uses, since donating also removes the card. It renders only when
  the pet is donatable, which needs one new **projected field** on the pet list
  (`donatable`), computed the way `in_datsme` / `claimable` already are —
  a projection, never a visibility rule the client is trusted to enforce.
- **House-full line** gains ", or donate one".
- **Admin queue** is a **fourth `<section>` on the existing store admin page**,
  not a new route: the admin nav is hand-rolled per page, so a new route means
  editing five unrelated pages — precisely the "touching unrelated files" §2
  forbids — and the reviewer wants the shelf editor adjacent anyway (approve →
  unpublished row → the editor already on that page).
- **`api.ts`** gains `donatePet`, `listMyDonations`, `restoreDonation`, and the
  admin donation calls, in the one adapter.

### §10.10 The four test questions, for Phase 2

1. *New variant → engine change?* No. A new donation is a row; the reward
   amount is a knob; a new writeback target is four registry entries a guard
   test polices.
2. *New feature → unrelated files?* The donate door is a new module; the queue
   is a new table; the admin queue is a section on a page that already exists.
   The named seams are one projected field on the pet list, one tier field, and
   the launch hook that fires delivery.
3. *Third-party integration → modifying owned paths?* The host side is four
   registry entries, one handler module, one table, two knobs. `user.pet`,
   `identity.activity` and `user.collection` are untouched.
4. *Bug in one variant → debugging shared code?* Donation bugs live in
   `donations.py` / `reward_delivery.py` / `credit_award.py`. The shared code
   they touch is the sellability validator — one function, three callers, whose
   whole point is that all three agree.

### §10.11 Guard tests

- `webui/tests/test_donations.py` — each gate refuses for its own reason
  (anonymous 403, entitlement 403, not-yours 404, `public` pet 422, unstamped
  legacy pet 422, unsellable 422, fourth pending 409); a successful donate
  removes the house row and creates exactly one `pending` row; the donation is
  invisible to another owner.
- `webui/tests/test_donation_review.py` — the admin gate on every route;
  approve creates an **unpublished** store row and sets `owed`; reject returns
  the pet as a **kept** pet with a fresh id; reject into a full house leaves it
  restorable and does not exceed the cap; no path from `rejected` to a reward.
- `webui/tests/test_reward_delivery.py` — owed rows batch into ONE writeback per
  launch; the body carries the raw launch token from the cookie; a non-200
  leaves rows `owed` (retry on the next launch); a 200 marks them `delivered`
  once and a second launch sends nothing; the idempotency key is derived from
  the donation ids, so a retry is byte-identical.
- Host `api/tests/test_credit_award.py` (in-process, registered in
  `test_all.py` — the §14.2 rule): the four registry entries are consistent;
  a missing `credits.award` grant 403s; the same donation id delivered twice
  mints once (the unique key); the daily cap refuses beyond it; a reward of 0
  is a no-op that still succeeds. Plus the existing
  `test_dpp_registry_consistency.py`, which must stay green.
- Frontend: `tsc --noEmit` + vitest; the Donate button renders only for
  `donatable` rows.
- E2E: extend `scripts/e2e_adopt_store_pet.sh`'s shape with a donation pass —
  donate → approve → relaunch as the donor → verify the host ledger shows one
  award and a second relaunch adds none.

### §10.12 Rollout

| Step | Ships | Why this order |
|---|---|---|
| 2a | Host: capability, target, handler, table, knobs (reward knob at **0**) | The partner cannot deliver to a host that has no target; deploying the host first is inert because nothing calls it yet |
| 2b | DatsPet: donate door, queue, admin review, donor surface — **no reward delivery** | Donations can be collected and reviewed while the reward is still off; the queue fills with real content before any credit moves |
| 2c | DatsPet: reward delivery on launch | The only step that can move money; ships once 2a is verified live |
| 2d | The owner raises `credit_pet_donation_reward` off 0 | A deliberate act, after watching the queue |

Staging before production at every step (Rule 0), and 2c's verification is the
E2E above run against staging's real host, not a unit test.

### §10.13 Deliberately not done in Phase 2

- **No instant reward.** It lands on the donor's next launch (§10.7.1). Revisit
  only if the host grows a real background delivery channel.
- **No notifications.** DatsPet has no channel; §10.8's list is the surface.
- **No donor-visible credit amounts** in DatsPet — the host renders numbers
  (§0.5.1).
- **No editing a donation after submission.** It is a ledger row; a donor who
  wants a different pet donates a different pet.
- **No partner-side reward for a rejected donation**, and no appeal flow. The
  note is the answer.
- **No auto-approval**, however good the bundle looks. The human gate is the
  anti-farming design (§10.7.5), not a placeholder for a classifier.

---

## §11 Deliberately not done

- **No user-visible prices in DatsPet** — the host quotes, DatsPet doesn't
  (§0.5.1). Revisit only as its own decision.
- **No store pet as a design base** — the archetype rule
  (SPEC_PET_DESIGNER_FLOW §2.1) stands; a store pet is a finished design.
- **No dedupe of repeat adopts** — a store pet is a template, not a licence.
- **No closed tag vocabulary / no server-side search** — both have named
  tripwires (§1.3, §6.1) instead of speculative structure.
- **No seller marketplace** (users setting prices, revenue shares): out of
  scope entirely; donations + flat pricing are the whole economy.
- **No host-side store**: the DatsMe "platform catalog" (SystemConfig JSON +
  files) is untouched; the store lives on the partner side where quotes,
  idempotency, and checkout already exist.
- **No notifications to donors** on approve/reject (DatsPet has no channel).
  Status lives in the Donations section of the house page (§10.8) — *not* on
  the pet's own card, which the donation deleted. Revisit if it stings.

---

## §12 Guard tests and verification

New tests, same culture (shared validators, floor tests, scoping):

- `webui/tests/test_store.py` — listing shows published only; unpublished id
  404s on preview *and* adopt; adopt copies into the caller's house with
  `source_store_pet_id` set and `public` stamp; house-full 409s before
  insert; entitlement 403 when `can_adopt_samples` false (the §9 fix, proven
  server-side); adopted copies are invisible to other owners (scoping).
- `webui/tests/test_store_admin.py` — gate required on every route;
  publish-from-pet derives mechanical facts that match the bundle; publish
  refuses an unsellable bundle (shared validator); redraft refuses on a
  published row.
- **Floor test**: at least one *published* store pet exists after the §8
  migration script runs against a fixture — the store can't silently launch
  empty.
- **Export pricing test** (`webui/tests`): a pet with `source_store_pet_id`
  exports `price_basis: "store_flat"`; a designed pet exports `per_pose`.
- Host side (`datsme_me/api/tests`): quote and charge for a `store_flat` item
  use the knob; `per_pose` and legacy basis-less items are unchanged.
- Frontend: `tsc --noEmit` + vitest; a small test for the client filter
  function (search/tags/animal) — the one piece of page logic worth pinning.
- E2E: extend the `scripts/e2e_design_a_pet.sh` pattern with a store pass —
  publish-from-pet → shop → adopt → hand off → verify the host charged the
  flat knob and acked.

---

## §13 Rollout

| Phase | Ships | Contains |
|---|---|---|
| 0 | this spec, reviewed | owner sign-off on §1–§9; §10 acknowledged as sketch |
| 1 | the store | `store_pets` + `pet_store.py` + `store_admin.py` + AI purpose + shop page + admin page + §7 host pricing + §8 sample retirement + §9 enforcement + §12 tests |
| 2 | donations | **specified in §10 (Rev.6); awaiting owner sign-off.** Ships in four steps (§10.12): host registry+table+knobs → donate door + queue + review → reward delivery → the owner raises the reward knob off 0 |

Phase 1 is one coherent release with a fixed internal order: **the host
deploys §7.3 first.** A host that does not yet know `store_flat` would quote
store pets per-pose (the quote binds, so no silent overcharge — but the wrong
number on day one); the reverse direction is safe (a new host treats an
absent basis as `per_pose`). Then the DatsPet web tier, staging before
production as always, verified by the §12 E2E pass.

Before the production flip, the shelf is stocked: the migrated sample plus
whatever the owner wants on it via §5 (the count is the owner's call). The
launch checklist line is: *the store must not be visibly emptier than the
sample grid it replaced.*

---

## §14 As built (Rev.4) — the ledger

Phase 1 is **code-complete in both repos and deployed nowhere.** Read this section
rather than the prose above when the question is "what is done".

### §14.1 Built and green

| Area | Where | Gate |
|---|---|---|
| `store_pets` table + `source_store_pet_id` ALTER | `webui/db.py` | — |
| Six store functions (`insert_store_pet` … `delete_store_pet`) | `webui/db.py` | — |
| Public shop + adopt | `webui/pet_store.py` | `test_store.py` |
| Admin CRUD + `_seed_animal` | `webui/store_admin.py` | `test_store_admin.py` |
| Sellability validator | `webui/store_validation.py` | shared by both callers |
| AI listing purpose | `pet_factory/ai_purposes/store_listing.json` | registry guard |
| Migration script | `scripts/migrate_samples_to_store.py` | ran once per environment; its input files are now deleted (§14.4) |
| `price_basis` on export items | `webui/datsme_integration.py` | — |
| Shop page (`/catalog` evolved) + admin page + `api.ts` | `web/src/app/{catalog,admin/store}` | `tsc`, vitest, `storeFilter` test |
| **Host** `credit_pet_store_cost` knob | `social_ledger_config.py:54` (default 50) | — |
| **Host** basis at quote **and** charge | `pet_writeback.py:188`, `:404` | `test_pet_store_price_basis.py` |
| §8 retirement | sample routes/helpers/scripts gone; content files deleted 2026-07-31 (§14.4) | `tsc` clean |

**Gates:** DatsPet 593 pass (20 store) · `tsc` clean · vitest 36 · 0 lint errors.
Host: owner-fields 70/70, price-basis 10/10, app imports clean.

### §14.2 Two defects the readiness pass found

**The host's price-basis test ran nowhere.** It was written pytest-style; the api
venv has no pytest and it was never registered in `test_all.py`, so the suite was
green having never executed one assertion about **what a user is charged**. That
is the exact false-green shape this project keeps meeting. Converted to the house
in-process convention (`TestResults` + `run()`) and registered — 10/10, on the
interpreter the app itself runs.

*The rule this yields:* on this host, a new test is in-process and registered, or
it does not exist. pytest-style is reserved for the `_CAMPAIGN_PYTEST_GATES` list,
which at least skips **loudly**.

**The frontend did not compile.** §8.1 — backend retirement landed before the page
that called it. Fixed; the ordering rule is now written down.

### §14.3 What is genuinely left

1. ~~**Deploy.**~~ Done — §14.4.
2. **Stock the shelf deeper** — the migrated sample satisfies the launch line
   (*not visibly emptier than the grid it replaced*), but one pet is a thin
   store. Count, captions, and the knob's value are the owner's calls; the §5
   flow is live in both environments.
3. ~~**Delete the sample content files.**~~ Done — §14.4 (rides the next deploy).
4. ~~**The §12 E2E store pass.**~~ Done — dev stack and staging, §14.4.
5. **§10 donations** — unstarted by design. The revision it was waiting on is
   written (Rev.6): §10 is now build-ready and needs the owner's sign-off, not
   more design. Nothing about it is coded in either repo.

### §14.4 Deployed (Rev.5, 2026-07-31)

Host-first (§13), staging before production, all in one day:

| Tier | Commit | Verification |
|---|---|---|
| DatsMe staging host | `f120feb7` | knob live (50); clean journal |
| DatsPet staging web | `0a3f63e1` | C1 `verify_deployment.sh` **14/14**; §12 store E2E **PASSED on staging** (markly.3: flat 50 quoted + charged; per-pose would say 110) |
| DatsMe prod host | `f120feb7` | knob live (50); clean journal; BUILD_ID rolled |
| DatsPet prod web | `0a3f63e1` | C1 **14/14**; shelf serves the migrated sample; `/design` 307 intact |

B9 migration ran once per environment (idempotent re-runs verified no-op). The
§8 sample content files and their interim guard test
(`test_sample_migration_input.py`, which asked for deletion alongside them) are
deleted in dev and ship with the next deploy cycle — the migration script
remains, now a no-op, for any future `<animal>/samples/` drop-in.

Operational notes from the deploys: the staging vhost served 403/500 for ~3
minutes when a rebuild replaced `out/` without the B8 vhost restart (the bind
mount follows the directory inode — B8 is unconditional for a reason); and
staging's live nginx conf carries a house-asset location block that exists
neither in the repo conf nor on prod — a drift to reconcile deliberately, not
during a deploy.
