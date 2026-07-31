# SPEC_PET_STORE — The Pet Store: a database-backed shop of ready-made pets

**Status: Rev.9 (2026-07-31) — PHASE 1 LIVE IN PRODUCTION; PHASE 2 SPECIFIED,
NOT STARTED.** Phase 1 deployed host-first (§13) to staging and then production
the same day, C1-verified 14/14 on both tiers, with the §12 store E2E passing on
staging's real infrastructure (flat 50 quoted + charged; the pose formula would
have said 110). §14 is the as-built ledger and the only place to read for "what
is done"; §14.4 records the deploys. **§10 is now a build-ready specification
rather than a sketch** — it needs owner sign-off before code, and §10.0 records
the three constraints that moved the design. **Rev.9's shelf lifecycle (§1.4)
changes a LIVE Phase 1 table** and is specified but not built.

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
(the `ai_usage` rule), donations require a DatsMe identity, and unstamped legacy
pets are refused.

**Rev.7 (2026-07-31)** — the donor reward is **one social point, not credits**
(owner decision, §0.4). On DatsMe a prosocial act pays social points —
`award_generosity_reward` already does exactly this for gifting, daily cap and
all — so donating should too. Mechanically it is a smaller change than it
sounds: `_record_ledger_transaction` takes `ledger_type` as a parameter, and
the host's writeback dispatch is the same plugin registry either way. It also
*shrinks* the design: the capability drops to `low` risk (a social point is not
money), the knob ships **on** at 1 instead of off at 0 because there is no money
printer to disarm, and §10.7.5's threat model falls from "drains the platform's
money supply" to "reputation inflation, capped per donor per day". §10.7.6 is
new and states plainly what a social point is and is not worth today — including
that the social→credit conversion endpoint has no frontend caller yet.

**Rev.8 (2026-07-31)** — **a donation is a gift, and it is final** (owner
decision, §0.5), and the social point is awarded **at the donate click** rather
than at an admin's approval. The pet transfers straight into store inventory as
an `intake` row; the admin decides only what reaches the shelf. The analogy
the owner gave is the right one: you do not get your sofa back from the charity
shop because they chose not to display it.

This is the largest simplification Phase 2 has had. Deleted outright: the
review queue as a workflow, the `pending/approved/rejected/returned` lifecycle,
the approve and reject endpoints, the return-on-reject path, the Restore
action, the per-donor pending cap, the bytes in the donation table, and the
admin's fourth page section. `store_donations` becomes a pure append-only
ledger — donor, what it became, whether the thank-you landed — and Phase 2's
entire admin surface becomes **one badge and one sort** on the Phase 1 shelf
table (§10.4). It also retired one of §10.0's three constraints: with no return
path, DatsPet's missing draft-purge clock stopped mattering.

Two things get *harder*, and both are stated where they belong rather than
buried. The award loses its human gate, so the daily cap becomes the
load-bearing anti-farming defence and must never be disabled (§10.7.5). And a
mistaken donation is unrecoverable through the product, so the confirm dialog
has to say "permanent" in those words (§10.5, §10.9).

**Rev.9 (2026-07-31)** — the `published` boolean becomes a four-state
**`status`** (§1.4): `intake` → `shelf` → `backroom` → `archived`. A boolean
could not tell apart the three different reasons a pet is not for sale, and
those three are exactly what an admin acts on — the inbox, the thing held back
deliberately, and the thing decided against. Names follow §0.5's charity-shop
model and say what is true of the row rather than what someone is doing to it
(`intake`, not "under review" — nothing is under review until someone opens it;
`backroom`, not "back shelf", because it pairs with `shelf` the way a shop
does). `archived` absorbs "rejected", because rejected-on-arrival and
pulled-from-sale are one fact with one behaviour, and the reason belongs in
`admin_note` rather than in a second state.

Every transition is free except the one gate that already existed: moving TO
`shelf` runs the sellability validator. Unsellable stays *derived*, never a
status. The status lives on `store_pets` for all inventory rather than on
donations, so the engine still never asks where a row came from — an admin's
unfinished draft and an untriaged donation are both `intake`, and the read-time
"donated by" badge is what distinguishes them.

Migration is one step with no dual-write: add `status`, backfill from
`published`, drop `published` (SQLite 3.37 on these boxes supports
`DROP COLUMN`). It touches a live table in three environments, so §13 gives it
its own small deploy between Phase 1 and Phase 2.

New §1.5 answers a question this raised — and corrects a first answer that was
too pessimistic. **The store already knows exactly how many times a listing was
sold and to whom**: the host confirms every purchase with a signed
`POST /partner/imported/{user_id}`, and DatsPet stamps `writeback_acked_at` on
the adopted copy, which carries both `source_store_pet_id` and the buyer's
`external_user_id`. The count is one WHERE clause today.

The flaw is *where* it is kept, not whether it is known: that row lives in the
buyer's house and `delete_pet` is a hard delete, so a user tidying up silently
decrements a number meant to record history. §1.5.3 specifies the fix as an
append-only `store_sales` ledger written where the ack already lands — one
insert, `pet_id` as the primary key so a retried host notification cannot
double-count, and deliberately **no price column**, because DatsPet is not the
pricer and a stale copy of the host's knob would be a number two systems
disagree about. Views stay unbuilt and are a genuinely harder problem (§1.5.4):
one cached listing payload and a 24-hour preview cache mean there is no request
to count without a purpose-built beacon.

</details>

---

## §0 What this is, and the four decisions already made

A user today can only bring a pet to life that she designed herself (~3 min of
GPU, priced by pose count at DatsMe's checkout). The Pet Store adds the other
door: **browse a shelf of ready-made pets — with portraits, descriptions, and
searchable tags — and adopt one instantly, for one flat price** (the owner's
knob — typically below designing, which burns real GPU, but possibly equal;
§0.2). Later, a user whose 50-pet house is full can **donate** a pet she
made to the store and is thanked with a social point on the spot — DatsMe's
standard reward for a prosocial act. The pet becomes store inventory
immediately; whether it ever reaches the shelf is the admin's call.

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
| 0.5 | What donating means | **A donation is a gift, and it is final** (Rev.8). The pet transfers to store inventory at the click — into `intake` (§1.4) — and the donor cannot get it back. The admin decides only what reaches the shelf, never whether to accept. The model is a charity shop: once it is donated, it is gone. |
| 0.2 | Pricing | **A flat host-side credit knob** (`credit_pet_store_cost`), set at the host admin credits screen like every other knob. One price for any store pet, regardless of poses. Expected at or below the design formula (a store adopt burns no GPU; designing does) and possibly equal to it — the value is the owner's dial, never this spec's concern. DatsMe remains the only charger. |
| 0.3 | Descriptions | **AI-drafted from the pet's portrait, admin-edited before publishing.** |
| 0.4 | Donor reward | **One social point, awarded at the donate click.** Revised twice on 2026-07-31: from credits to social points (Rev.7 — gifting and donating pay *social* points on DatsMe, `award_generosity_reward`, and reputation is the right currency for a prosocial act), then from award-at-approval to award-at-donation (Rev.8, with §0.5 below). |

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
- **On the shelf** — a store pet visible to shoppers (`status = 'shelf'`,
  §1.4). Every other state is invisible to them, for three different reasons.
- **Donation** (Phase 2) — a user's own designed pet given to the store. It
  becomes an `intake` store pet at the moment of the gift; the admin decides
  only whether it reaches the shelf. There is no queue and no way back (§0.5).

### §1.2 The `store_pets` table (new, in `datspet.db`)

A **separate table**, not flagged rows in `pets` — and this is a boundary
decision, not a convenience. The `pets` table is scoped by `_scope_clause`,
which is exact-match on owner *as a security invariant* (`webui/db.py:341-352`,
guarded by `test_scoping.py`). A store pet is visible to everyone; no owner
value can express that, and widening the clause is exactly the bug the
exact-match fix removed. Separate table, separate read path, zero contact with
the scoping rule. It also passes the change-cadence test: a house pet changes
for user-lifecycle reasons (draft, keep, delete, writeback); a store pet
changes for merchandising reasons (description, tags, shelf status). Different
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
    status          TEXT NOT NULL DEFAULT 'intake',  -- §1.4; replaced `published` in Rev.9
    admin_note      TEXT NOT NULL DEFAULT '',        -- why it was archived / held back
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
`draft` column (`status` is the store's own word and does not interact with the
draft purge sweeps), any source/provenance column (§2 — a store pet that
arrived by donation is indistinguishable at runtime from one an admin made;
donor facts live on the Phase 2 donation row, which is audit, not engine
input), and **any adoption or view counter** (§1.5).

### §1.4 `status` — the shelf lifecycle (Rev.9)

A store pet is in exactly one of four states. Rev.1–Rev.8 had a `published`
boolean, which could not tell apart the three different reasons a pet might not
be for sale — and those three are precisely what an admin needs to act on.

| `status` | Visible to shoppers | Means |
|---|---|---|
| `intake` | no | Arrived; nobody has decided about it yet. The inbox. |
| `shelf` | **yes** | For sale. The only state a shopper can ever see. |
| `backroom` | no | Kept and sellable, deliberately not out front. |
| `archived` | no | Not for sale; kept only as a record. |

The vocabulary is the charity-shop model the owner chose in §0.5, and each
name says what is *true of the row* rather than what someone is doing to it:

- **`intake`, not "under review".** Nothing is under review until an admin opens
  it; the row is simply in the intake area. It also reads correctly for an
  admin-stocked pet whose caption is unfinished — she is not reviewing her own
  work either.
- **`shelf`, not "published" or "store".** The spec and the code already say
  "the shelf" everywhere; `status == 'shelf'` reads as the thing it means, and
  "store" is ambiguous with the store as a whole.
- **`backroom`, not "back shelf".** It pairs with `shelf` the way the shop
  actually works — front of shop, back of shop — and promoting is literally
  moving something forward. "Back shelf" and "shelf" are one word apart, which
  is the kind of pair that gets misread in review.
- **`archived` absorbs "rejected".** Rejected-on-arrival and pulled-from-sale
  are the same fact — not for sale, keep the record — and no code would ever
  treat them differently. Two states with one behaviour is a split that only
  creates bugs; the *reason* goes in `admin_note`, which is free text because
  reasons are.

**Transitions are free.** Any state may move to any other; there is no state
machine to encode because there is no ordering an admin could violate.
`archived` is deliberately **reversible** — a terminal state is what pushes
people toward hard deletes when they change their mind. The one rule that is
not free is the gate: **moving *to* `shelf` runs the sellability validator**
(§5.3) and refuses on failure, exactly as the old publish flip did.

**One status for all inventory, not a donation field.** A donated pet and an
admin-stocked pet have the same four states, so the status lives on the
inventory row and the engine never asks which one it is looking at (§1.2). A
useful consequence: an admin's unfinished draft and an untriaged donation are
both `intake`, and it is the *badge* — a read-time join to the donation ledger
— that tells them apart. The difference lives where §2's rules say it should.

**Unsellable is NOT a status.** A row whose bundle fails the validator is
broken because its *bytes* are, and `_admin_view` recomputes that on every
read. Storing it would let the row disagree with its own bundle, which is the
one thing §1.2 exists to prevent.

**Migration (Rev.9), one step, no dual-write.** `published` is live in three
environments. Add `status`, backfill `shelf` where `published=1` and `intake`
where `0`, then `DROP COLUMN published` — SQLite on these boxes is 3.37, so
`ALTER TABLE … DROP COLUMN` is available. The old column does not linger behind
a compatibility shim: a transition layer here would mean two sources of truth
for "is this for sale", which is the failure this revision exists to remove.

### §1.5 Sales — known but not kept, and views, which are neither

**The store knows exactly how many times a listing was sold, and to whom. It
just throws the evidence away when a buyer tidies up.** Rev.9 records the fix
and does not build it.

#### §1.5.1 The sale is already a precise, host-confirmed event

Nothing has to be inferred. The chain exists end to end today:

1. A store adopt writes a `pets` row carrying `source_store_pet_id` (which
   listing) and `external_user_id` (which DatsMe user) — `webui/pet_store.py`.
2. The buyer hands off; the host quotes, charges, and pulls the bundle.
3. **The host tells us**: a signed `POST /partner/imported/{user_id}` names the
   pet ids it took (`datsme_integration.partner_imported`), and DatsPet stamps
   `writeback_acked_at` on each (`db.stamp_writeback_acked`).

That stamp *is* the sale — it is set only after the host's checkout has run, it
is host-signed, and the handler already refuses to stamp a pet the named user
does not own. The house UI reads it today as `in_datsme`.

So the count is one WHERE clause:

```sql
SELECT COUNT(*) FROM pets
 WHERE source_store_pet_id = ? AND writeback_acked_at IS NOT NULL;
```

and the buyers are the `external_user_id`s on those same rows.

#### §1.5.2 Why that query is still the wrong place to read it

It counts rows in the **buyer's house**, and `delete_pet` is a hard `DELETE`.
A user who sells a pet's slot back — deletes it to make room — silently
decrements a number that is supposed to mean "how many times was this ever
bought". The sale happened; the record of it was collateral damage to an
unrelated action. That divergence is invisible and permanent, and it gets worse
the longer the store runs, which is exactly when the number starts mattering.

#### §1.5.3 The fix: an append-only sale ledger, written where the ack lands

```sql
CREATE TABLE IF NOT EXISTS store_sales (
    pet_id         TEXT PRIMARY KEY,  -- the adopted copy; UNIQUE, so a retried
                                      -- host notification cannot double-count
    store_pet_id   TEXT NOT NULL,     -- which listing was sold
    buyer_user_id  TEXT NOT NULL,     -- external_user_id at the time of sale
    sold_at        REAL NOT NULL
);
```

- **One insert, in a handler that already exists.** `partner_imported` already
  loops the acked pet ids and already has the row in hand; the ledger row goes
  in beside `stamp_writeback_acked`, guarded so a pet with no
  `source_store_pet_id` (a designed pet) writes nothing.
- **`pet_id` is the primary key, and that is the idempotency.** The host may
  re-notify; the stamp is naturally idempotent because it overwrites, but an
  INSERT is not — so the key does that job. `INSERT OR IGNORE`, never an
  UPDATE: **append-only ledgers stay append-only**, the `ai_usage` rule.
- **No price column, deliberately.** DatsPet does not know what the buyer was
  charged and must never guess — the host is the only pricer (§0.5.1), the
  amount is a host knob that changes under us, and a stale copy of it here
  would be a number two systems disagree about. If revenue reporting is ever
  wanted, it is a host-side question against the host's own ledger.
- **Deleting the store listing does not delete its sales.** The ledger outlives
  the inventory row, like the donation ledger outlives the pet it became
  (§10.2). History is not tidied.

Then "how many times was this sold" is a `COUNT` on a table nothing else
mutates, and it stays true through house cleanups, archiving, and deletion of
the listing itself.

**Buyer identity is stored but not casually displayed.** `buyer_user_id` is what
makes the ledger auditable and would answer "did this actually reach a person",
but the admin shelf does not need names to make merchandising decisions — a
count does. Default the admin surface to counts, and treat exposing buyer
identity as its own decision with its own reason, not a free consequence of
having the column.

#### §1.5.4 Views are a different problem, and not a cheap one

There is no view counter and adding one is not a WHERE clause. The shop paints
from **one cacheable listing response** (§6.1), so there is no per-pet request
to count, and `preview.png` ships a 24-hour cache header (§3.1) precisely so it
is *not* re-fetched — counting image loads would undercount by design and miss
every repeat viewer entirely. A real view metric needs a deliberate client-side
beacon: a new surface, a new write path on a public endpoint, and its own
privacy question. It should be argued on its own merits rather than arriving
beside a sale counter because the two sound similar.

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
| `GET /api/store` | none (anonymous browsing, §0.4 of the catalog spec) | `{pets: [Listing]}` — **`status = 'shelf'` only**, newest first. `Listing = {id, display_name, animal, breed_id, description, tags, pose_count, poses, preview_url}`. Never bytes, never an off-shelf row. |
| `GET /api/store/{id}/preview.png` | none (an `<img>` has no 401 handler — `owner_scope.py:120-122` precedent) | the `preview_png` blob, long cache headers — safe because a preview is immutable per id (derived once at insert; ai-tag touches only text). 404 for unknown *or off-shelf* ids — intake, backroom and archived must be invisible, not merely unlisted. |
| `POST /api/store/{id}/adopt` | `require_owner` | `{pet_id, display_name, breed_id}` |

**Adopt** is the existing adopt-a-sample primitive re-pointed at the DB, and
keeps its exact order (`app.py:1491-1535`): resolve store row (404 if missing
or off-shelf) → `require_owner` → **entitlement check, now enforced
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
| `GET /api/admin/store` | all rows in every state, listing shape + `status` + `admin_note`. Default sort newest-first, so `intake` surfaces without a queue |
| `GET /api/admin/store/{id}` | one row, full metadata |
| `POST /api/admin/store/publish-from-pet` | body `{pet_id}` — **the stocking door**, §5. The source pet is read through the caller's OWN owner scope (the same scoped access keep/delete use): an admin publishes only a pet she can see in her house, never an arbitrary row by id. |
| `PUT /api/admin/store/{id}` | edit `display_name`, `description`, `tags`, `animal` (off-shelf rows only, §1.3), `status`, `admin_note`. Tags are normalized on write — lowercased, trimmed, deduplicated, capped by named constants (`STORE_MAX_TAGS = 16`, `STORE_MAX_TAG_LEN = 32`). **Moving to `status: 'shelf'` re-runs the sellability validator** (§5.3) and refuses on failure — the admin cannot shelve a listing the build would reject. Every other transition is free (§1.4). |
| `POST /api/admin/store/{id}/ai-tag` | write description + tags with AI (§4) — the ONE generator of listing text, overwriting both, **only if the row is off the shelf** (a live listing is the admin's text, and regenerating it would change what shoppers are reading) |
| `DELETE /api/admin/store/{id}` | remove from inventory. Copies already adopted into houses are unaffected (they are copies). |

### §3.3 `webui/db.py` additions

`db.py` stays the one store module. Additive functions only:
`insert_store_pet` (derives the four derived columns; the only writer),
`list_store_pets(shelf_only)`, `get_store_pet`, `update_store_listing`,
`set_store_status`, `delete_store_pet`. The existing `pets` functions are
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

Input: the pet's portrait (the `preview_png` extracted at publish) **plus the
pose names** the bundle declares. Output contract:
`{display_name_suggestion, description, tags}` — a shopper-facing paragraph
(2–3 sentences, warm, concrete: colors, markings, mood) and 4–8 lowercase tags.

**Why the poses ride along.** The model is shown exactly ONE still frame — the
idle frame cropped out of the sheet — so appearance is all it can see. The pose
names are the only way it can know what the pet *does*, and they are already a
fact of the bundle (`manifest["animations"]`, the same list the listing serves
as `poses`), so handing them over costs nothing and no new data has to be
kept. It is what lets a shopper search "pounces" and find a pet that actually
has that pose. Two rules the prompt enforces: the model may tag an action
**only if the pose list names it**, and it must never describe how a pose
*looks* — it has not seen those frames. When a pet declares no poses the clause
is empty rather than saying "no poses": an absent fact is silence, not a claim
the model has to reason about.

**It runs on one trigger only: the admin taps ✨ and confirms.** Nothing else
in this spec invokes it — not stocking, not donating, not publishing, and never
a shopper request. A new row's description is empty and its tags are `[]` until
someone asks for words.

This follows the host's **AI-tag** door (`POST /api/ai-tag/{kind}/{id}`), and
deliberately copies its four load-bearing properties:

1. **One call writes both** description and tags. They are one thought about one
   portrait; two buttons would let them disagree.
2. **It overwrites, it does not merge.** Simpler to reason about, and the only
   honest thing to do with generated prose.
3. **Because it overwrites, a confirm stands in front of it** — "This replaces
   the current description and tags." Tapping ✨ never fires the request. That
   dialog is where the overwrite is disclosed, which is the whole reason the
   host has one.
4. **The result is a draft, not a verdict.** It is persisted, re-read into the
   editor, and edited as ordinary text. The name idea is offered as a
   *suggestion* beside the name field and never auto-applied (§5.1).

Failures **surface** (503 unavailable / 502 failed) rather than degrading
silently, and the dialog stays open with the error inline so the admin can
retry — an explicit ask deserves an explicit answer. Usage is metered in the
existing `ai_usage` ledger. DatsPet charges nothing for it: the host's version
debits credits, and this one has no credit concept to debit (the host's own
portability note says credit integration is the optional part).

**Why not draft at publish-from-pet, which is where Rev.1–Rev.8 put it?**
Because "best-effort at stocking" quietly made three promises it should not: it
spent tokens on prose nobody had asked for, it made a model outage part of the
stocking path, and it produced text the admin had to *review to reject* rather
than *ask for*. Explicit invocation costs one tap and removes all three.
*(Changed 2026-07-31 after the owner compared it to DatsMe's AI tagging; the
auto-draft had shipped in Phase 1 and was removed in the same change.)*

---

## §5 Stocking the store (v1: admins only)

### §5.1 The flow — the designer *is* the authoring tool

1. An admin designs a pet through the **normal three-step designer** — on
   production this runs on the pool like any user's pet. No parallel
   authoring surface, no CLI, no GPU box required.
2. From the admin store page, she picks that pet from her house and hits
   **Publish to store** (`POST /api/admin/store/publish-from-pet`). This
   **copies** the pet's bundle into a new `intake` `store_pets` row
   (her house copy remains hers), extracts the portrait, derives the
   mechanical facts, seeds `display_name` from the house pet's name, and runs
   the AI draft (§4) — whose `display_name_suggestion` is shown in the editor
   as a suggestion, never auto-applied.
3. She edits the name, description, and tags in the admin editor, then flips
   the status to **`shelf`**. The row appears in the shop on the next listing
   fetch.

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
inventory table (status visible at a glance, newest first), the publish-from-pet
picker (reads the admin's own house via the existing `listPets()`), and the
listing editor (name, description, tags, publish toggle, and the ✨ that writes
description + tags — §4, behind its confirm).
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
  **`shelf`** `store_pets` row — a shipped sample is already-live,
  guard-tested public content, and migrating it off-shelf would open a
  window where the shop replaces the sample grid with an empty shelf. The
  shipped `.png` becomes `preview_png` (no PIL in the script), the sample key
  title-cased becomes the name, and the description starts as a one-line
  deterministic caption the admin polishes afterwards (✨ is available).
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

## §10 Phase 2 — donations (specified for build, Rev.8)

A user gives a pet she designed back to the store; an admin reviews it; on
the click she is thanked with a social point. It is the supply side of the store: Phase 1 makes
every listing cost the owner admin time and GPU minutes, and this makes the
users the supply. It is also the pressure valve on the 50-pet house cap —
donating frees a slot *and* pays, where deleting just frees a slot.

The owner's four Phase 1 decisions (§0) carry over unchanged. Decision 0.4 —
**one social point, at the donate click** — plus §0.5's "a donation is final"
are what shape everything below. Rev.6 specified the opposite of both (credits,
at an admin's approval, with a review queue and a return path); the owner
replaced them on 2026-07-31 and the design got materially smaller — see §10.5.

### §10.0 Two constraints found in design, before any code

The Rev.2 sketch assumed things the code does not do. Rev.8's "donation is
final" model retired one of them outright (there is no return path, so the
draft-purge problem it hit no longer exists). Two remain, and they shape §10.7:

1. **A host writeback is bound to a launch.** `authenticate_writeback`
   (`datsme_me/api/apps/dpp/service.py:807`) requires a `launch_token` in the
   body — a JWT whose `jti` names an unburned `IntegrationNonce`,
   `LAUNCH_TOKEN_TTL` 60 minutes — and `burn_launch_nonce` (`:893`) makes it
   **one writeback per launch**. Under Rev.8 the donor *is* present when the
   award is earned, so the common case is a live token and immediate delivery;
   but a session older than an hour, a second donation after the nonce is
   burnt, or a host blip all still land off the happy path. Hence §10.7's
   `owed` state — now a fallback rather than the norm.
2. **Neither host pull channel delivers in the background.** `/sync-pending`
   (`routes.py:304`) carries *metadata* only — it turns partner rows into
   launch URLs, and has no scheduler job and no UI caller today. The import
   pull *does* reach `apply_writeback`, but it is `PULLABLE_TARGETS`-gated and
   checkout-shaped (`_IMPORT_ADAPTERS` requires a `quote`). Nothing reaches a
   user who is not clicking, so an undelivered award waits for the donor.

A third, smaller one: **DatsPet has no outbound HTTP stack at all.** The push
path was deleted, not disabled (`webui/app.py:1876`,
`datsme_integration.py:9`), and `httpx` there is a dead import. §10.7.3 is
explicit that this is new code and why it is worth adding.

### §10.1 The donate door

**Donating is giving, and giving is final.** The model is a charity shop, not a
consignment desk: the donor hands the pet over, is thanked on the spot, and the
shop decides what goes on the shelf. She does not get it back, and there is no
verdict she is waiting on.

That one rule is what makes Phase 2 small. It removes a review queue, a
four-state lifecycle, an approve/reject pair of endpoints, a return path, a
restore action, and the entire question of what happens to a returned pet when
the donor's house is full. What is left is a transfer and a thank-you.

**Who may donate.** Three gates, all server-side, in this order:

1. **A DatsMe identity.** `owner_scope.require_owner` plus a non-anonymous
   `external_user_id`. A standalone/anonymous user has no account for a reward
   to land in, so the door 403s rather than accepting a donation it can never
   pay. This is also why §10.2 registers no claim handler (see there).
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
   rebuild it; a wrong guess here pays out for provenance nobody knows.

And one gate on the artifact: the bundle must be **sellable** (§5.3, the
validator's third caller). Under "donation is final" this matters more than it
did under review — an unsellable bundle would be a permanent, unshelvable row
the admin must clean up, paid for with a real social point. Refusing at the door
is the honest answer: 422 with the reason, and she keeps her pet.

**No per-donor donation cap, deliberately.** The Rev.6 design capped pending
donations at 3 to keep a review queue reviewable; there is no queue now. The
farming incentive is capped by the daily reward cap instead (§10.7.5), and
flooding inventory costs the flooder ~3 minutes of design per pet to hand the
admin one `DELETE` — self-limiting, and the wrong economics for an attacker.
*Tripwire:* if junk inventory ever becomes a real cleanup burden, the answer is
a daily donation cap at the door, not a review queue.

### §10.2 What a donation is, in the database

Two writes and a delete, in one place:

1. **The pet becomes inventory immediately** — an `insert_store_pet` row with
   `status='intake'` (§1.4) — the same inbox an admin's own freshly stocked
   pet lands in. It is a store pet from that moment, indistinguishable at
   runtime from one she stocked herself (§1.2). `animal` is
   seeded by `_seed_animal(breed_id)`, exactly as publish-from-pet does;
   `display_name` carries over from the pet; `description` and `tags` start
   **empty** — the AI draft stays admin-triggered and metered (§4), so a
   donation never spends AI budget on a shopper's action.
2. **A donation ledger row** records who gave it.
3. **The house row is deleted** — the slot frees at once, which is the product
   point.

Order matters: **insert the store row first, then the ledger row, then delete
the house row.** A crash mid-way leaves a duplicate (recoverable) rather than a
vaporised pet (not).

```sql
CREATE TABLE IF NOT EXISTS store_donations (
    id                  TEXT PRIMARY KEY,  -- the award's idempotency key
    external_user_id    TEXT NOT NULL,     -- the donor; NEVER NULL (§10.1 gate 1)
    store_pet_id        TEXT NOT NULL,     -- what it became
    display_name        TEXT NOT NULL,     -- as donated; the shelf row may be renamed
    donated_at          REAL NOT NULL,
    reward_state        TEXT NOT NULL,     -- owed | delivered | capped | declined
    reward_delivered_at REAL
);
```

**It holds no bytes.** Under review-then-accept the queue had to carry the
bundle; now the bundle is already in `store_pets` and this row is pure audit —
an `ai_usage`-shaped append-only ledger, not a workflow. If an admin later
deletes the store pet, the donation row stays with a `store_pet_id` that no
longer resolves: that is history, and history does not get rewritten.

**No provenance column on `store_pets`, still.** §1.2's rule holds — the engine
must never be able to ask where a listing came from. Donor attribution is a
**read-time join** from this ledger, which is exactly the boundary §1.2 permits
("only read-time views may compare across sources").

**No claim handler, and this is the rule not an omission.**
`owner_scope.py:185` is explicit that `ai_usage` is deliberately unregistered
because a claim handler rewrites an append-only ledger's history.
`store_donations` is the same shape, and §10.1's first gate means a donation can
never be created under an anonymous id in the first place — so there is nothing
for a handler to move. **Do not "complete" the registry by adding it.**

### §10.3 The donate endpoint

`POST /api/pets/{pet_id}/donate` in a new `webui/donations.py` (`require_owner`,
the store's module-per-concern pattern; stdlib + FastAPI + the webui PIL pin —
the GPU-less posture).

Order:

1. `require_owner` → non-anonymous check (§10.1 gate 1) → 403.
2. `resolve_entitlement().can_donate` → 403.
3. `db.get_pet_for_owner(pet_id, external_user_id=owner)` → 404 if absent **or
   not hers** (scoped read, no TOCTOU — the store admin's publish door uses the
   same one).
4. `read_pet_ownership` category must be `factory` → 422 with the reason.
5. Portrait via the admin's own `_portrait_from_bundle`, then
   `sellability_errors` → 422 if it could never be sold (§10.1).
6. `insert_store_pet(..., status='intake')`.
7. `insert_donation(..., reward_state='owed')`.
8. `delete_pet` (scoped) + drop the in-memory `JOBS` entry, as `delete_pet`'s
   route wrapper does.
9. Attempt reward delivery (§10.7.3). **Never blocks the response** — a slow or
   failing host must not make a donation appear to fail when the pet has already
   changed hands.

The response says what happened in the donor's terms: the pet is donated, and a
social point is on its way or already there. It quotes no balance and no total
(§0.5.1).

### §10.4 The admin's role — the Phase 1 surface, unchanged

There is no approve and no reject. A donated pet is simply a store pet in
**`intake`** (§1.4), and every tool it needs already shipped in Phase 1:

- It appears in `GET /api/admin/store` (which returns every state) in the
  existing inventory table.
- The admin edits name, description, tags and animal with the existing
  `PUT /api/admin/store/{id}`, drafts listing text with the existing
  ✨ ai-tag door (off-shelf rows only — which every donation is), and shelves it
  with the same call. **Publishing still runs the sellability validator**, so
  the shelf gate is unchanged.
- If she does not want it, the existing `DELETE /api/admin/store/{id}` removes
  it. The donation ledger row survives as audit.

**The only new thing on the admin surface is a read-time badge**: rows that
join a donation row show "donated by *<user>*". This is a view-layer join, never
a column on `store_pets` and never a branch in the engine (§1.2). It is what
lets an admin triage new arrivals without a queue: sort the inventory table by
newest, and the `intake` rows are the inbox — which is what that state is for.

So Phase 2's admin work is **one badge and one sort**, not a review workflow.

### §10.5 Donation is final — and what that costs

The donor gives the pet up permanently. There is no return, no appeal, and no
"pending" state she can watch. The confirm dialog must say so in those words
before she agrees (§10.9) — this is the one place in DatsPet where a click
destroys something of hers that cannot be recovered.

Two honest consequences, recorded rather than buried:

- **A mistaken donation is unrecoverable through the product.** An admin can
  see the bundle in the store and could re-publish it, but there is no
  "give it back" path, and building one would resurrect the whole returns
  problem. The mitigation is the confirm dialog, not a mechanism.
- **The store accumulates rows an admin may never want.** That is the
  charity-shop bargain: the shop takes what it is given and decides later.
  `archived` is the disposal (§1.4) — it keeps the bytes and the reason, and it
  is reversible, so hard `DELETE` is reserved for genuine junk. §10.1's
  tripwire covers the day even archiving stops being cheap.

*(Rev.6 specified the opposite — a review queue with approve/reject and a
return-as-a-kept-pet path. The owner replaced it with this model on 2026-07-31;
it deletes a table's worth of lifecycle and, incidentally, the only part of
Phase 2 that depended on DatsPet's non-existent draft-purge clock.)*

### §10.6 Ownership — still nothing to write

A donated bundle arrives `factory` / `datspet` (guaranteed by §10.1 gate 3), and
that is already the store's unsold state. **No ownership write happens on the
donation path at all** — not at donate, not at publish. The buyer is stamped by
the host at its checkout, exactly as for an admin-made listing.
SPEC_PET_OWNER_FIELD §2.4's "DatsPet writes only unsold ownership states" stands
untouched, and a store pet that arrived by donation remains indistinguishable at
runtime from one an admin made (§1.2).

### §10.7 The reward — how a social point reaches the donor

#### §10.7.1 Earned at the donate click, delivered as soon as it can be

The award is earned the moment she donates — that is the product promise, and
with no review step there is nothing to wait for. Delivery is a separate,
mechanical concern:

- **The common case is immediate.** She is in a live DatsMe-launched session, so
  a valid launch token is in the launch cookie (`datsme_integration.py:349`
  re-verifies it per request), and the writeback fires during her donate
  request.
- **When it cannot be immediate, the award is `owed`** and rides her next
  launch. §10.0's constraint 1 lists the ways: a session older than 60 minutes,
  a nonce already burnt by an earlier donation in the same launch, a host blip.
- **The donation row is the retry queue.** `owed` survives restarts, deploys and
  failed attempts; no separate retry store, no drain tick, no scheduler.

#### §10.7.2 One writeback per launch, so awards batch

`authenticate_writeback` burns the launch nonce, so a launch carries **one**
writeback. A donor with three owed awards therefore gets **one** writeback
carrying **three** entries, not three writebacks. At a few dozen bytes per entry
this is nowhere near `MAX_WRITEBACK_BODY_BYTES` (64 KB).

In practice the daily cap (§10.7.4) means at most one award per donor per day is
ever *paid*, so batching mostly exists to let the host mark the rest `capped` in
one round trip rather than leaving them to retry forever.

#### §10.7.3 DatsPet side — the first outbound call

New module `webui/reward_delivery.py`. One concern: turn `owed` rows into a
signed POST and record the outcome. Two triggers, one code path — the donate
endpoint (step 9) and the launch handler.

- **Always off the critical path.** Neither a donation response nor a launch
  redirect may wait on the host. Fire it after the response is on its way (the
  existing `run_in_threadpool`/background pattern); on any failure leave the
  rows `owed`.
- **Signing**: the SDK's `sign_writeback` + `post_writeback`
  (`datsme_me/api/sdk/datsme_partner_sdk/writeback.py`) — already installed,
  never yet imported here. `WritebackBuilder` is *not* used: it defaults the
  idempotency key to the launch `jti`, which is wrong for us (a retry on a later
  launch must reuse the same key). **The idempotency key is derived from the
  donation ids in the batch**, so a retry is byte-identical and both the host's
  replay cache and its business key recognise it.
- **Outcomes**: HTTP 200 marks every id in the batch `delivered`. A per-entry
  `capped` verdict from the host marks that row `capped` — **terminal, never
  retried**; the donor gave several things and was thanked once, which is what
  a daily cap means. A permanent refusal (`capability_not_granted`) marks them
  `declined`, visible in the admin view and re-armable. Anything else leaves
  them `owed` for the next launch.

**This reverses "DatsPet never pushes" and the reversal is deliberate.** The
push path was retired because *pet delivery* is better as a pull: bundles are
megabytes, need quotes, and the host's import checkout already owns idempotency.
None of that applies to a 200-byte award notice that carries no bytes and moves
no pet. The rule that survives is the one that mattered: **DatsPet still never
charges, never quotes, and never moves a pet by push.**
`SPEC_DATSPET_FEDERATED_SESSION` §6.2a should record this narrowing when Phase 2
lands.

#### §10.7.4 Host side — four registry entries, one table, two knobs

The host's writeback dispatch is a plugin registry, so this is content, not
engine (`test_dpp_registry_consistency.py` is the guard that fails a half-formed
entry — it defines the checklist):

1. `_TARGET_HANDLERS["user.social_award"]` (`service.py:1233`) → a thunk into a
   new `apps/dpp/social_award.py`, the way `user.pet` thunks into
   `pet_writeback.py` rather than growing `service.py`.
2. `REQUIRED_CAPABILITY_BY_TARGET["user.social_award"] = "social.award"`
   (`service.py:1033`).
3. `SUPPORTED_SCHEMA_VERSIONS` entry (`manifest.py:57`).
4. A new `Capability("social.award", "Award you social points", risk="low")`
   (`capabilities.py:46`).
   **Low is correct here, and it is the one place the ledger choice changes the
   security posture.** `should_auto_grant` (`capabilities.py:222`) auto-grants
   low-risk capabilities to official partners without a consent screen. For a
   *credit* award that would have been wrong — credits are money and buy GPU
   work — which is why the credit version of this section required `medium`.
   Social points are reputation: they buy nothing, gate nothing (§10.7.6), and
   only ever add. A consent screen reading "DatsPet can award you social points"
   asks the user to authorise a gift to themselves.
   **Not** added to `PULLABLE_TARGETS` — this target is push-only.

**Idempotency: a new social-DB table with a unique business key.**
`partner_social_awards(partner_slug, award_key)` unique — `award_key` is the
donation id — plus `user_id`, `amount`, `created_at`. Modelled on
`uq_partner_collection_external` (`models.py:242`) for the key shape and on the
Stripe webhook's **claim-before-award** ordering (`payment_service.py:396`):
insert the claim row first, in the same transaction as the ledger row, so a
duplicate delivery loses the race on the unique index instead of paying twice.
Deliberately *not* the replay cache (24 h TTL, and a donor who returns on day 3
would be paid twice) and *not* the launch nonce (it bounds a launch, not a
donation — the exact bug `pet_writeback.py:466` records for pets).

**The award itself copies `award_generosity_reward`**
(`social_ledger_service.py:718`) — the function DatsMe already uses to pay a
social point for a prosocial act, and the closest thing the ledger has to a
generic award helper. Its shape is exactly what is needed: keyword-only args, a
config-read amount whose `<= 0` **is** the kill switch, the
`_get_or_create_balance_cache(..., "social", lock=True)` lock taken *before* the
count, a `created_at >= today_start` cap query scoped to its own
`transaction_type`, one `_record_ledger_transaction` with
`ledger_type="social"`, no commit (the caller owns it), and a `bool` return.
`transaction_type` is **`pet_donation_social_reward`** — its own type, not
`gift_generosity_reward`, because sharing a type would silently share that
feature's daily cap (`test_pet_gifting.py:463` pins that the credit-gift and
pet-gift rewards *do* share one, deliberately; donations must not join them).

Wrap the call the way `maybe_award_completion_credit` does
(`identity_engine_service.py:711`): local import, `try/except` that logs and
returns rather than failing the writeback. A reward that cannot be paid leaves
the donation `owed` on the partner side and retries on the next launch.

**Two knobs.** Naming follows the `credit_gift_social_reward_*` precedent —
prefix by the *triggering* feature, `_social_reward_` marks what is paid out.
**Not** `point_*`, which is reserved for the five core platform knobs:

- `pet_donation_social_reward_amount` — **default `"1"`**, matching
  `credit_gift_social_reward_amount`. One point per donation is the
  house rate for a prosocial act. Ships *on*, unlike the credit version which
  had to ship at 0: a social point is not money, so there is no money printer to
  disarm before the first donation lands. `0` still disables it, and the
  disable-by-zero is the same kill switch `award_generosity_reward` uses.
- `pet_donation_social_reward_daily_cap` — **default `"1"`**, per donor per UTC
  day, on this transaction type alone. A donor who gives three pets in one day
  earns one point that day; the rest are marked `capped` and never retried (the
  point was the pet, not the points). Under Rev.8 this cap is also the primary
  anti-farming defence — see §10.7.5 before touching it.

**Registration is FIVE places, not two, and Phase 1 was bitten by missing one.**
`credit_pet_store_cost` shipped seeded and charged but absent from
`CREDIT_CONFIG_KEYS`, so no admin screen could see it (§14.2). The full list for
each new knob:

1. `SOCIAL_LEDGER_CONFIG_DEFAULTS` (`social_ledger_config.py`) — a missing key
   reads `"0"` and silently *disables* the feature.
2. `CREDIT_CONFIG_KEYS` (`routes/admin.py`) — the GET filters and the PUT
   rejects on this list.
3. The ordered render array (`web/src/app/admin/page.tsx`) — it `.filter`s to
   keys present in the response, so a key absent here renders nothing even when
   steps 1–2 are done.
4. The `isAward` list beside it, so the admin form labels it as a payout.
5. `TRANSACTION_LABELS` (`web/src/app/[slug]/settings/points/page.tsx`) — the
   donor's Social Point History humanises transaction types from this map, and
   an unmapped type renders as `pet donation social reward`. Note
   `gift_generosity_reward` is *already* missing there; fixing it in the same
   change is one line.

§10.11's guard test covers all five, not just the subset test Phase 1 added.

**Partner-scoped bookkeeping**: `partner_social_awards` is partner-scoped, so it
must be added to the eviction/purge delete list (`admin_routes.py:713`), the
divorce-preview counts (`:497`), and `write_partner_bundle` (`audit_bundle.py:177`)
— protocol §22a requires every partner-scoped table be expressible as
`DELETE … WHERE partner_slug = ?`.

#### §10.7.5 Why it cannot be farmed — and what changed when the human gate went

**Say the trade-off out loud: Rev.8 removed the human gate from the award.**
Under review-then-approve, "an admin approves every payout" was the primary
anti-farming defence. Donation is now final and instant, so nothing human stands
between `generate → donate` and a social point. What holds is a different, and
frankly more honest, set of limits:

- **One point per donor per UTC day** (`pet_donation_social_reward_daily_cap`).
  This is now the load-bearing defence, not a backstop. A farmer who designs and
  donates fifty pets in a day earns **one** point — the same as a donor who gave
  one. Every additional donation costs them ~3 minutes of design and yields
  nothing. **This knob must never be 0/disabled**; disabling it does not disable
  the reward, it uncaps it.
- **The payout is not money.** One point is nominally 0.1 credit, needs ten
  before conversion is even possible, and conversion has no UI caller today
  (§10.7.6). Farming reputation at 1/day is not a business.
- **Only your own designed pets** (§10.1 gate 3) — a store-adopted pet is
  `public` and refused, so points cannot be laundered through the shelf.
- **The donation is a real cost to the farmer.** Each one permanently gives up a
  pet they spent ~3 minutes of GPU making. Farming here means paying more than
  you take, which is the shape you want.
- **Idempotent on donation id**, so replaying a captured writeback pays nothing.

The abuse that *is* left is not point farming but **inventory spam** — donating
junk to make an admin press `DELETE`. It costs the attacker a design cycle per
row and the owner GPU time; §10.1's tripwire (a daily donation cap at the door)
is the answer if it ever becomes real. The sellability gate at the door already
stops the cheapest version of it.

The residual security risk, stated rather than hidden: a compromised
`DATSME_HMAC_SECRET` lets an attacker award social points — capped per donor per
day, worth 1/10 of a credit each at conversion, and revocable by disabling the
partner. That is a nuisance to clean up, not a loss. Under the credit version of
this design the same compromise would have been a direct drain on the platform's
money supply, which is the strongest argument for the social-point choice — and
it is what makes removing the human gate affordable at all.

#### §10.7.6 What a social point is actually worth — and what it is not

Stated plainly so nobody assumes more:

- **It converts to credits at `credit_social_conversion_ratio` (10:1)** with a
  10-point minimum (`convert_social_to_credits`, `social_ledger_service.py:655`)
  — so one donation reward is nominally 0.1 credit, and ten donations are
  needed before conversion is even possible.
- **The conversion endpoint has no frontend caller today.** `POST
  /api/credits/convert` exists and works, but nothing in `web/src` or
  `native_mobile` calls it. Until that ships, a social point is not spendable.
- **Tiers gate nothing.** Bronze/silver/gold/platinum/diamond are computed from
  the social balance and rendered as a badge and a progress bar; no permission,
  discount, or capability anywhere is keyed on tier. The one thing social points
  *do* gate is voting (`balance >= point_vote_cost`).
- **It is visible.** The donor sees the award in Social Point History and the
  badge on her profile — which is the actual reward being offered: public
  credit for contributing to the shelf.

If the owner later wants donations to pay something spendable, the lever is the
same one either way: raise the amount, or add a second knob that also awards
credits. Nothing in §10.7's mechanics is specific to which ledger is written —
`_record_ledger_transaction` takes `ledger_type` as a parameter — so switching
or adding is a handler change, not a redesign.

### §10.8 What the donor sees

§11's "the house's donation status is visible on next visit" cannot work as
written — §10.3 deletes the house row, so there is no card left to carry a
status. And under Rev.8 there is no status to watch either: the donation
completed the moment she clicked. What remains worth showing is the record of
what she gave.

A **Donations** section on the house page, fed by `GET /api/donations` (own rows
only, scoped like every other read): the name, when she gave it, and whether the
thank-you has landed. Nothing is actionable — no restore, no appeal, no verdict
— which is the point of the model. Point totals are never rendered here: DatsPet
shows no balances (§0.5.1), so a delivered award reads "thanked with a social
point" and the number lives on DatsMe, in the Social Point History where every
other award appears.

It is a section on a page the donor already visits, not a new route and not a
nav entry. If the list stays this thin in practice, folding it into the house's
capacity readout as a single line ("you have donated N pets") is a legitimate
simplification — the surface exists to answer "where did my pet go?", not to
host a workflow.

### §10.9 Frontend

- **House card action** — the per-card row (`house/page.tsx`, currently the
  DatsMe-zip anchor + Remove) gains **Donate**, using the same confirm-modal
  primitive as Remove. **The dialog must say the donation is permanent** in
  those words (§10.5): this is the one control in DatsPet that destroys
  something of the user's with no recovery path, and the reward on the other
  side makes it *more* important to be blunt, not less. It renders only when
  the pet is donatable, which needs one new **projected field** on the pet list
  (`donatable`), computed the way `in_datsme` / `claimable` already are — a
  projection, never a visibility rule the client is trusted to enforce.
- **House-full line** gains ", or donate one".
- **Admin**: no new section. Donations land as `intake` rows in the inventory
  table that already exists (§10.4); the only change is the "donated by" badge
  — the status column and the newest-first sort are Rev.9 Phase 1 work, so by
  the time donations ship the inbox is already there.
- **`api.ts`** gains `donatePet` and `listMyDonations` in the one adapter. No
  admin donation calls exist, because there are no admin donation routes.

### §10.10 The four test questions, for Phase 2

1. *New variant → engine change?* No. A donation is two inserts and a delete;
   the reward amount is a knob; a new writeback target is four registry entries
   a guard test polices.
2. *New feature → unrelated files?* The donate door is a new module, the ledger
   is a new table, and the admin side is a badge on a table that already exists.
   The named seams are one projected field on the pet list, one tier field, and
   the launch hook that fires delivery.
3. *Third-party integration → modifying owned paths?* The host side is four
   registry entries, one handler module, one table, two knobs. `user.pet`,
   `identity.activity` and `user.collection` are untouched.
4. *Bug in one variant → debugging shared code?* Donation bugs live in
   `donations.py` / `reward_delivery.py` / `social_award.py`. The shared code
   they touch is `insert_store_pet` and the sellability validator — one
   function, three callers, whose whole point is that all three agree.

### §10.11 Guard tests

- `webui/tests/test_donations.py` — each gate refuses for its own reason
  (anonymous 403, entitlement 403, not-yours 404, `public` pet 422, unstamped
  legacy pet 422, unsellable 422). A successful donate **removes the house row,
  creates exactly one UNPUBLISHED store row, and one ledger row pointing at
  it** — and the new store pet is invisible on the public shelf until an admin
  publishes it, which is the test that proves donations cannot self-publish.
  The donor's ledger rows are invisible to another owner.
- `webui/tests/test_donation_inventory.py` — a donated row is editable,
  ai-taggable and publishable through the **existing Phase 1 admin routes** with
  no donation-specific endpoint; publishing it still runs the sellability
  validator; deleting the store pet leaves the ledger row intact (audit
  survives disposal); the "donated by" badge is a read-time join and no
  provenance column exists on `store_pets`.
- `webui/tests/test_reward_delivery.py` — a donation in a live launch delivers
  immediately; with an expired token or a burnt nonce it stays `owed` and the
  next launch delivers it; owed rows batch into ONE writeback; the body carries
  the raw launch token from the cookie; a 200 marks them `delivered` once and a
  second launch sends nothing; a `capped` verdict is terminal and never
  retried; the idempotency key is derived from the donation ids, so a retry is
  byte-identical.
- Host `api/tests/test_social_award.py` (in-process, registered in
  `test_all.py` — the §14.2 rule): the four registry entries are consistent;
  a missing `social.award` grant 403s; the same donation id delivered twice
  pays once (the unique key); **the daily cap refuses the second award in a UTC
  day — the test that pins Rev.8's load-bearing defence** (§10.7.5); a reward
  amount of 0 is a no-op that still succeeds; the award writes
  `ledger_type="social"` with its OWN transaction_type, so it cannot borrow the
  gift reward's daily cap. **Plus a five-place registration guard** — every
  `*_social_reward_*` and `credit_pet_*` knob is in
  `SOCIAL_LEDGER_CONFIG_DEFAULTS`, in `CREDIT_CONFIG_KEYS`, in the admin render
  array, and in `TRANSACTION_LABELS` (§10.7.4). Phase 1 shipped a knob that
  failed step 2 and nothing caught it. Plus the existing
  `test_dpp_registry_consistency.py`, which must stay green.
- Frontend: `tsc --noEmit` + vitest; the Donate button renders only for
  `donatable` rows, and its confirm copy names the donation as permanent.
- E2E: extend `scripts/e2e_adopt_store_pet.sh`'s shape with a donation pass —
  donate → verify the pet left the house and arrived in `intake` →
  verify the host ledger shows exactly one social award → publish it → adopt it
  back as a different user, which proves the donated bundle survives the whole
  lane intact.

### §10.12 Rollout

| Step | Ships | Why this order |
|---|---|---|
| 2a | Host: capability, target, handler, table, knobs | The partner cannot deliver to a host that has no target; deploying the host first is inert because nothing calls it yet |
| 2b | DatsPet: donate door + ledger + donor surface, **reward delivery included** | Under Rev.8 the award is earned at the click, so shipping the door without delivery would promise a thank-you the code cannot send. 2a is live by then, so there is nothing to stage around |
| 2c | The owner tunes `pet_donation_social_reward_amount` if 1 is wrong | Optional — the reward ships on at the house rate |

Staging before production at every step (Rule 0), and 2b's verification is the
E2E above run against staging's real host, not a unit test.

*(Rev.6 had a four-step rollout with delivery held back a step, because the
award then fired at an admin's click and could safely lag. Rev.8's award fires
at the donor's click, so door and delivery ship together.)*

### §10.13 Deliberately not done in Phase 2

- **No take-backs.** Donation is final (§10.5) — no return, no appeal, no
  admin "give it back" path. Building one resurrects the whole returns problem
  the model was chosen to delete.
- **No review queue.** A donated pet is an `intake` row and the Phase 1
  admin is the whole toolset (§10.4). If triage ever needs more than a badge and
  a sort, that is a store-admin change, not a donation lifecycle.
- **No AI draft on donation.** Listing text stays admin-triggered and metered
  (§4) — a user action must never spend AI budget.
- **No guaranteed-instant reward.** It is immediate when the donor's launch is
  live and `owed` otherwise (§10.7.1). Revisit only if the host grows a real
  background delivery channel.
- **No notifications.** DatsPet has no channel; §10.8's list is the surface.
- **No donor-visible point or credit amounts** in DatsPet — the host renders
  numbers (§0.5.1). The donor's Social Point History is where the award appears.
- **No per-donor donation cap** at launch (§10.1), and no reward for quantity:
  the daily cap means the second donation of a day is thanked with nothing.

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
- **No notifications to donors** (DatsPet has no channel, and under §0.5 there
  is no verdict to notify about). The record lives in the Donations section of
  the house page (§10.8) — *not* on the pet's own card, which the donation
  deleted.

---

## §12 Guard tests and verification

New tests, same culture (shared validators, floor tests, scoping):

- `webui/tests/test_store.py` — listing shows `shelf` rows only; an off-shelf id
  404s on preview *and* adopt; adopt copies into the caller's house with
  `source_store_pet_id` set and `public` stamp; house-full 409s before
  insert; entitlement 403 when `can_adopt_samples` false (the §9 fix, proven
  server-side); adopted copies are invisible to other owners (scoping).
- `webui/tests/test_store_admin.py` — gate required on every route;
  publish-from-pet derives mechanical facts that match the bundle; publish
  refuses an unsellable bundle (shared validator); **publish-from-pet never
  invokes the AI** (§4 — the guard against the auto-draft coming back); ai-tag
  refuses on a shelved row.
- `webui/tests/test_store_status.py` (Rev.9) — a shopper sees `shelf` rows and
  only those: `intake`, `backroom` and `archived` are absent from the listing
  and 404 on BOTH preview and adopt (invisible, not merely unlisted). Every
  transition is allowed except one: moving to `shelf` runs the sellability
  validator and refuses a broken bundle, while `backroom` and `archived`
  accept it — you may keep something you cannot sell. `archived` is reversible.
  The migration backfills `shelf` from `published=1` and `intake` from `0`, and
  `published` is gone afterwards (no dual source of truth).
- **Floor test**: at least one store pet is on the **shelf** after the §8
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

**Rev.9's status migration ships as its own small deploy**, after Phase 1 and
before Phase 2: it is a schema change to a live table in three environments
(§1.4), it needs no host change, and Phase 2 depends on `intake` existing. Run
it staging-first like everything else, and verify the shelf still serves its
one pet afterwards — C5 is exactly that check.

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

Rev.9's status lifecycle (§1.4) and all of §10 are specified and **not built** —
see §14.3.

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
5. **§1.4's shelf lifecycle (Rev.9)** — specified, NOT built. This one changes
   a live Phase 1 table (`store_pets.published` → `status`), so it is the next
   thing to build and it ships on its own (§13), ahead of Phase 2, which
   assumes `intake` exists.
6. **§10 donations** — unstarted by design. The revision it was waiting on is
   written (Rev.6, reshaped by Rev.7 and Rev.8): §10 is build-ready and needs
   the owner's sign-off, not more design. Nothing about it is coded in either
   repo.
7. **§1.5.3's `store_sales` ledger** — specified, not built. Small (one insert
   in `partner_imported`), and every day it is not built is sales history that
   a buyer's house cleanup can still erase. View counting stays unbuilt and
   unspecified beyond §1.5.4 — it is a beacon, not a counter.

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
