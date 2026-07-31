# SPEC_PET_STORE — The Pet Store: a database-backed shop of ready-made pets

Rev.2 (2026-07-30) — **draft for owner review; nothing in this spec is built.**
Supersedes the file-based samples surface of `SPEC_DATSPET_CATALOG_PURCHASE`
(archived, executed 2026-07-30) — see §8 for exactly what it absorbs and retires.
Rev.2 folds in the owner's pricing direction (the price is a host knob; its
value is not this spec's concern) and the design-review fixes: the AI draft is
best-effort, the migration publishes the already-live sample (no empty-shop
window), host-first deploy order, tag normalization, and Phase 2 mint
hardening on the host side.
Rev.3 (2026-07-31) — **accepted for implementation.** Readiness
clarifications: publish-from-pet reads its source pet through the caller's
own owner scope (§3.2); the export seam names `export_pets` (§7.2); the
physical sample files outlive the §8 code retirement by one deploy cycle
(the migration script must read them); and `animal` moved from derived to
seeded-and-confirmed (§1.3) — a typed-animal bundle carries no canonical
species key to derive it from.

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

## §10 Phase 2 — donations (design sketch; detailed spec section before build)

Everything below is decision-level. Phase 2 gets its own revision of this spec
before implementation, but these decisions are made now so Phase 1 doesn't
paint over them.

### §10.1 The donate door

- Trigger surfaces: a **Donate to store** action on house cards, and the
  house-full message ("house full — remove one to make room, **or donate
  one**").
- Eligibility: **only your own designed pets** — the donate endpoint reads the
  bundle's ownership category via the existing `read_pet_ownership` and
  accepts `factory` only. This one check excludes store-adopted and
  sample-adopted pets (`public` stamp), closing the laundering loop
  (adopt cheap from the store → donate back → collect reward) with zero new
  bookkeeping.

### §10.2 The queue

New table `store_donations`: bundle bytes + donor `external_user_id` +
`submitted_at` + `status` (`pending` / `approved` / `rejected`) + admin note.
Donating **moves** the pet: the house row is deleted at submission — freeing
the slot immediately is the product point. Append-only status transitions;
the row is the audit trail. (If the table is owner-stamped it registers a
claim handler — one line, per the registry.)

### §10.3 Review

`store_admin.py` grows `GET /api/admin/store/donations`,
`POST .../donations/{id}/approve`, `POST .../donations/{id}/reject`.
Approve = the sellability validator (§5.3, third caller) → insert an
**unpublished** `store_pets` row (then the normal caption/edit/publish flow)
→ trigger the reward (§10.5). Reject = the bundle returns to the donor's
house **as a draft** (the existing unsaved-pets recovery lane; drafts don't
count against the cap, and the donor can keep it if room exists). The
re-inserted draft gets a fresh `created_at` so the draft-purge clock restarts
at rejection, not submission — a slow review must not let the returned pet
evaporate before the donor sees it.

### §10.4 Ownership at approval

A donated bundle arrives `factory`/`datspet` (guaranteed by §10.1 — the
donor's name was never in DatsPet's copy, per SPEC_PET_OWNER_FIELD). It is
already in the store's unsold state; **no ownership write is needed**, and
§2.4's "do not reintroduce an owner write" stays intact.

### §10.5 The reward, and why it can't be farmed

The owner chose credits-on-approval. The abuse to design against: generating
is free in credits (it costs DatsPet GPU time), so generate → donate → reward
is a money printer unless gated.

- **The mint event is the admin's approval click, and only that.** No reward
  at submission, none at publication. A human is the gate on every credit.
- New host knob **`credit_pet_donation_reward`**, suggested launch value
  small (e.g. 10 — a reward, not an income).
- **Per-user pending cap** (e.g. 3): the donate door 409s while a user has 3
  donations awaiting review, keeping queue spam bounded and reviewable.
- Mechanics: a signed partner→host call on the **inbound writeback family**
  (`/api/integrations/*`, `authenticate_writeback`) — not `/partner/*`, which
  is the host→partner *outbound* family. Idempotent on donation id, minting a
  ledger credit to the donor (nearest precedent:
  `maybe_award_completion_credit` firing on an activity writeback). Specified
  in detail in the Phase 2 revision.
- **Host-side defense in depth.** Partner-initiated minting is a new trust
  surface, and the host cannot verify that an admin actually clicked approve
  — the mint request just arrives signed with the partner secret. So the
  reward knob ships **defaulting to 0** (a kill switch until the owner arms
  it), and the host enforces a per-partner daily mint cap
  (`credit_pet_donation_daily_cap`). A compromised partner secret must be a
  bounded nuisance, never a money printer.

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
- **No notifications to donors** on approve/reject (DatsPet has no channel);
  the house's donation status is visible on next visit. Revisit in Phase 2 if
  it stings.

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
| 2 | donations | its own spec revision first (§10 expanded), then queue + review + reward |

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
