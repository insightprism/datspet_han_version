# SPEC_PET_STORE — The Pet Store: a database-backed shop of ready-made pets

**Status: Rev.13 (2026-07-31) — PHASE 1 LIVE IN PRODUCTION; PHASES 1a, 1b AND 2
BUILT AND DEPLOYED NOWHERE.** There is no Phase 3 — §13's table is the whole
plan, and §14.5 is the build ledger for what has not shipped. Phase 1 deployed host-first (§13) to staging and then production
the same day, C1-verified 14/14 on both tiers, with the §12 store E2E passing on
staging's real infrastructure (flat 50 quoted + charged; the pose formula would
have said 110). §14 is the as-built ledger and the only place to read for "what
is done"; §14.4 records the deploys. **§10 is now a build-ready specification
rather than a sketch** — it needs owner sign-off before code, and §10.0 records
the constraints that moved the design.

**Everything this spec defines is now LIVE IN PRODUCTION** — Phase 1 earlier,
and 1a/1b/2 on 2026-07-31 (§14.6). §1–§13 describe the design in its finished state; §14 is the ledger
of what actually exists.

Supersedes the file-based samples surface of `SPEC_DATSPET_CATALOG_PURCHASE`
(archived, executed 2026-07-30) — see §8 for exactly what it absorbs and retires.

<details><summary>Revision history</summary>

**Rev.2 (2026-07-30)** — draft for owner review. Folded in the owner's pricing
direction (the price is a host knob; its value is not this spec's concern) and
the design-review fixes: the AI draft is best-effort, the migration publishes the
already-live sample (no empty-shop window), host-first deploy order, tag
normalization, and Phase 2 mint hardening on the host side.

**Rev.3 (2026-07-31)** — accepted for implementation. Four readiness
clarifications, all since verified against the built code (§14): intake-from-pet
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
double-count.

It records the **amount**, and a first draft of this section wrongly said it
should not. "DatsPet must never *compute* a price" is a real rule; "therefore do
not record one" does not follow. The host already has the exact charge —
`handle_target_user_pet` returns `credits_charged`, the import route sums it —
and then builds its partner notification from ids alone, dropping the figure one
line later. So the host sends what it already computed (`items:
[{id, credits_charged}]`, additive beside `item_ids`, which third-party partners
read today), and a missing amount is NULL rather than 0, because a free
re-import delta makes zero a legitimate value. Unlike an AI call's cost, a pet's
charge is **not** recoverable after the fact — it depends on a knob that moves
and a per-import delta — so recording it at transaction time is the only way it
exists at all. Reports are then a `GROUP BY`, with no aggregate columns to
drift.

Views stay unbuilt and are a genuinely harder problem (§1.5.4): one cached
listing payload and a 24-hour preview cache mean there is no request to count
without a purpose-built beacon.

**Rev.11 (2026-07-31)** — an independent review of the 1a/1b/2 build found a
set of defects **every one of which lived in a path no test exercised**, while
all gates were green. The headline: **the reward loop was dead end to end.**
Three breaks interlocked — the host rebuilt its writeback response from three
fixed keys and discarded the handler's per-award `results`; the partner treated
every 4xx as permanent, so the 401 a burnt nonce produces (i.e. the SECOND
donation of any session — the case §10.0 constraint 1 names) marked rewards
`declined` forever; and the idempotency key ignored the launch, so a retry
presented same-key/different-bytes and earned a 409 after the host had already
paid. Fixed together, with the tests §10.11 named and nobody wrote.

Also corrected: a batch handler that raised mid-loop and rolled back the whole
session, un-paying awards the same response reported as `awarded` (now a
SAVEPOINT per entry, validation before any award); a sale recorded against the
wrong buyer when the acked pet belonged to someone else (append-only, so
permanent); a migration that could strand every listing in `intake` forever if
it crashed between the ALTERs and the backfill (now re-entrant); an outbox that
a single malformed URL could stall for every partner behind it; two
partner-scoped tables missing from all four §22a surfaces, now with a *derived*
guard so the next one cannot ship unlisted; and a `PUT` that erased an archive
reason whenever a client omitted the field.

§10.7.3's "a retry is byte-identical" was **false as built** and is rewritten
rather than quietly dropped — the way it was wrong is the useful part.

</details>

---

## §0 What this is, and the decisions already made

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

Five product decisions are fixed inputs to this design. The first four were
made by the owner on 2026-07-30; 0.4 was revised and 0.5 added on 2026-07-31
(Rev.7 and Rev.8):

| # | Decision | Choice |
|---|---|---|
| 0.1 | Scope of v1 | **Admin-curated only.** Donations are Phase 2, shipped separately. |
| 0.2 | Pricing | **A flat host-side credit knob** (`credit_pet_store_cost`), set at the host admin credits screen like every other knob. One price for any store pet, regardless of poses. Expected at or below the design formula (a store adopt burns no GPU; designing does) and possibly equal to it — the value is the owner's dial, never this spec's concern. DatsMe remains the only charger. |
| 0.3 | Descriptions | **AI-drafted from the pet's portrait, admin-edited before it reaches the shelf.** Revised 2026-07-31: the draft is *invoked* (the ✨, behind a confirm), never produced as a side effect of stocking — §4. |
| 0.4 | Donor reward | **One social point, awarded at the donate click.** Revised twice on 2026-07-31: from credits to social points (Rev.7 — gifting and donating pay *social* points on DatsMe, `award_generosity_reward`, and reputation is the right currency for a prosocial act), then from award-at-approval to award-at-donation (Rev.8, with §0.5 below). |
| 0.5 | What donating means | **A donation is a gift, and it is final** (Rev.8). The pet transfers to store inventory at the click — into `intake` (§1.4) — and the donor cannot get it back. The admin decides only what reaches the shelf, never whether to accept. The model is a charity shop: once it is donated, it is gone. |

### §0.6 The posture that must not change

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
which is exact-match on owner *as a security invariant* (`webui/db.py:401-411`,
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
    first_shelved_at REAL,                           -- NULL until first
    shelved; freezes `animal` (§1.3)
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
input — the read-time boundary where comparing sources is allowed is named in
§7.2), and **any adoption or view counter** (§1.5).

### §1.3 Listing metadata: two kinds of facts, two sources

- **Mechanical facts** are derived from the bundle at insert and are never
  editable: `breed_id`, `pose_count`, pose names (read from
  `manifest["animations"]` at read time). Editing these would let a listing
  lie about its artifact.
- **`animal` is seeded, then confirmed** (Rev.3). A bundle carries no
  canonical species key — a typed-animal pet's `breed_id`
  (`white_snow_leopard`) appears in no `catalog.json`. Stocking seeds it by
  catalog breed lookup, falling back to the last word of `breed_id`, and the
  admin may correct it **while the row has never been on the shelf**; the
  sellability validator refuses to shelve an empty one. **Once a row has been
  shelved the value is frozen for good** — including if it is later moved to
  `backroom` or `archived` — because the shop's filter chips and any shopper's
  memory of the listing depend on it. (Rev.9: under the old boolean "not
  published" and "never published" were the same thing; under four states they
  are not, so the rule names the stronger one. It needs a
  `first_shelved_at REAL` column, §1.2.)
- **Merchandising facts** are authored: `display_name`, `description`,
  `tags_json`, `status`, `admin_note`. The AI drafts the first two-and-a-half
  (§4) when asked; the admin owns the final text.

Tags are plain lowercase strings, not an enum. The design-axes vocabulary
(`pet_factory/design_axes/`) is a natural *source* of tag suggestions, but the
store does not enforce it — a closed tag vocabulary is an abstraction with one
consumer today, and the three-instances rule says wait.

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

The precise write rules, because the boolean's behaviour does not translate
one-to-one:

- **The validator runs on any write that leaves the row `shelf`**, not only on
  the transition into it. A re-save of a live listing is the moment to catch a
  row whose bytes went bad after shelving, and it is what the code does today
  (`store_admin.py`, on `published=true`) — keeping it means one rule, not two.
- **`animal` is frozen once `first_shelved_at` is set** (§1.3), not merely while
  the row is on the shelf. Under the boolean these were the same condition;
  under four states they are not, and the weaker reading would let a shelf →
  backroom → re-animal → shelf round trip change a listing shoppers had already
  filtered on.
- **`first_shelved_at` is stamped by the store, never by the client** — set on
  the first write that results in `status='shelf'`, never overwritten, never
  cleared. It is a derived fact like `bundle_sha256`, not an editable field.
- **An unknown status is a 422 with the allowed set in the message.** The four
  values are a named constant (`STORE_STATUSES`) beside `STORE_MAX_TAGS`, and
  the ai-tag door's gate becomes `status == 'shelf'` → 409, replacing its
  `published` check.
- **A PUT carrying both field edits and a status change applies the edits
  first**, then evaluates the status — so a request that fixes `animal` *and*
  shelves the row in one call behaves like the two calls in the order the admin
  would have made them.

**One status for all inventory, not a donation field.** A donated pet and an
admin-stocked pet have the same four states, so the status lives on the
inventory row and the engine never asks which one it is looking at (§1.2). A
useful consequence: an admin's unfinished draft and an untriaged donation are
both `intake`, and it is the *badge* — a read-time join to the donation ledger
— that tells them apart. The difference lives where §1.2 and §7.2 say it should.

**Unsellable is NOT a status.** A row whose bundle fails the validator is
broken because its *bytes* are, and `_admin_view` recomputes that on every
read. Storing it would let the row disagree with its own bundle, which is the
one thing §1.2 exists to prevent.

**Migration.** Three columns arrive together — `status`, `admin_note` and
`first_shelved_at` (§1.3) — and `published` leaves in the same step. It runs in
`init_db`'s established ALTER-if-missing block (`webui/db.py`, the pattern
`source_store_pet_id` already uses, §7.2), guarded on `PRAGMA table_info` so it
is a no-op on every boot after the first:

```
if "status" not in store_cols:                  # one-shot, guarded
    ALTER TABLE store_pets ADD COLUMN status TEXT NOT NULL DEFAULT 'intake'
    ALTER TABLE store_pets ADD COLUMN admin_note TEXT NOT NULL DEFAULT ''
    ALTER TABLE store_pets ADD COLUMN first_shelved_at REAL
    UPDATE store_pets SET status='shelf', first_shelved_at=created_at
      WHERE published=1
    ALTER TABLE store_pets DROP COLUMN published      -- SQLite ≥3.35; boxes are 3.37
```

`_SCHEMA`'s `CREATE TABLE` is edited in the same change for fresh databases —
`CREATE TABLE IF NOT EXISTS` never touches an existing one, so both paths are
required and neither is optional.

The old column does not linger behind a compatibility shim: a transition layer
would mean two sources of truth for "is this for sale", which is the failure
this revision exists to remove.

**Rollback is a file restore, not a `git revert`, and that is a deliberate
trade.** Dropping `published` makes the previous release unable to read the
table, so Phase D's normal rollback does not work for this deploy. Rather than
keep a dual-written column to preserve it — which would reintroduce exactly the
ambiguity being removed — **copy `datspet.db` before running the migration** and
restore that file if the deploy is rolled back. This is affordable precisely
here and would not be everywhere: the store holds one row per environment
today, and the pets table is untouched by this change. The deploy checklist
gets that copy as a named step beside B9.

### §1.5 The transaction record — who, how much, when, which pet

A store keeps transactions. This one does not yet — not because the facts are
unknown, but because nothing writes them down: the sale is confirmed by the
host, the buyer is on the row, and the amount is computed by the host and
discarded in transit. §1.5.3 is the ledger that fixes all three. Rev.9
specifies it and does not build it.

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

#### §1.5.3 The fix: an append-only transaction ledger

A store is a store: **who bought it, how much they paid, when, and which pet**
is the basic record, and all four are known at the moment of sale.

```sql
CREATE TABLE IF NOT EXISTS store_sales (
    pet_id         TEXT PRIMARY KEY,  -- the adopted copy; UNIQUE, so a retried
                                      -- host notification cannot double-count
    store_pet_id   TEXT NOT NULL,     -- WHAT was sold (the listing)
    buyer_user_id  TEXT NOT NULL,     -- WHO bought it (external_user_id)
    credits_paid   INTEGER,           -- HOW MUCH the host actually charged;
                                      -- NULL = the host did not report it
    sold_at        REAL NOT NULL      -- WHEN (unix epoch float, matching pets)
);
```

- **One insert, in a handler that already exists.** `partner_imported` already
  loops the acked pet ids and already has each row in hand; the ledger row goes
  in beside `stamp_writeback_acked`, guarded so a designed pet (no
  `source_store_pet_id`) writes nothing.
- **`pet_id` is the primary key, and that is the idempotency.** The host may
  re-notify. The existing stamp survives that naturally because it overwrites;
  an INSERT does not, so the key does that job. `INSERT OR IGNORE`, never an
  UPDATE — **append-only ledgers stay append-only**, the `ai_usage` rule.
- **The ledger outlives everything.** Deleting the listing, archiving it, or the
  buyer emptying their house all leave the sale intact, the way the donation
  ledger outlives the pet it became (§10.2). History is not tidied.

##### The amount: reported by the host, never computed here

DatsPet must never *derive* a price — the host is the only pricer (§0.6.1), the
amount is a knob that moves, and a re-import charges a delta rather than the
full cost. But "do not compute it" and "do not record it" are different rules,
and only the first one is right. **The host already has the exact figure and
discards it one line before it tells us:**

- `handle_target_user_pet` returns `credits_charged` per item
  (`pet_writeback.py:576`) — the real charge, after the delta rule.
- The import route collects those into `results` and even sums them
  (`import_routes.py:419`).
- Then it builds `landed = [r["id"] …]` and calls `notify_partner_imported`
  with **ids only** (`import_routes.py:429`), dropping the amount it is holding.

So the host-side change is to send what it already computed.
`notify_partner_imported` gains an **`items`** array alongside the existing
`item_ids`, with `item_ids` derived from the same list at build time so the two
can never disagree. Additive rather than a reshape, because `/partner/imported`
is a documented third-party endpoint and other partners read `item_ids` today.

```jsonc
{
  "export_type": "datspet_pets.v1",
  "item_ids": ["a1b2c3", "d4e5f6"],            // unchanged; other partners read this
  "items": [                                    // new, one entry per id above
    {"id": "a1b2c3", "store_pet_id": "smpl9303", "credits_charged": 50},
    {"id": "d4e5f6", "store_pet_id": null,       "credits_charged": 110}
  ]
}
```

Wire rules, so both sides can be built independently:

- `credits_charged` is an **integer ≥ 0**, or absent/`null` when the host cannot
  state it. Absent means unknown → `credits_paid` NULL (never 0, above).
- `store_pet_id` is the partner's own listing id, echoed back from the export
  item, or `null` for a designed pet. It exists so a late retry can record a
  sale whose pet row is gone.
- `items` is **advisory and additive**: `item_ids` remains the authoritative
  list of what landed. A partner that ignores `items` behaves exactly as today.
- The partner **validates leniently**: an entry whose `id` is not in `item_ids`
  is ignored; a malformed or negative `credits_charged` is treated as unknown
  (NULL), not as an error. A notification is never rejected over the enrichment
  — rejecting it would turn a reporting problem into a lost acknowledgement.

**A missing amount is NULL, never 0.** If the notification carries no figure —
an older host, or a partner tier deployed ahead of the host — the sale is
recorded with `credits_paid` NULL. Zero is a legitimate value (a re-import
delta can genuinely be free), so collapsing "unknown" into "free" would put a
lie in the ledger. This is the same trap the pricing path already fell into
once with an absent `pose_count` (`quote_user_pet_import`'s "missing is not
zero" note) — the fix there is the rule here.

**Why store the amount when `ai_usage` deliberately does not store cost.** The
rules only look alike. An AI call's cost is recoverable forever from a stable
per-model price catalog, so storing it would duplicate a derivable fact. A pet's
charge depends on a host knob that changes over time and on a per-import delta —
**it is not recoverable after the fact from anything DatsPet or the host retains
in a queryable form.** Record it at transaction time or lose it. That is what
makes this a transaction record rather than a cache.

##### Reporting falls out of the shape

"Revenue by listing", "sales this month", "which animals sell" are all a
`GROUP BY` over this table. **No aggregate columns, no counters, no running
totals** — those are the things that drift from the rows they summarise. The
per-sale row is the fact; every report is a read.

**Revoke (forget-me) anonymises the buyer, it does not delete the sale.**
`db.revoke_user` touches `pets` only today (`webui/db.py:572-594`); Phase 1a
extends it to `UPDATE store_sales SET buyer_user_id='' WHERE buyer_user_id=?`.
The transaction stays — a shop's books are not a personal record and deleting
them would make revenue depend on who has left — but the person is no longer
named. That is why the DDL above allows an empty string rather than making
`buyer_user_id` nullable: NULL would be ambiguous with "we never knew".

**Phase 1a writes; it does not read.** No admin sales screen, no report route,
no `db.py` aggregate ships with it. The point of 1a is that the rows start
existing — reporting can be built any time afterwards against a table that is
already accumulating, and building it now would mean designing a report with no
data to design against. §13 scopes 1a to exactly three things for this reason.

**Where it lives:** `store_sales` goes in `_SCHEMA` (`webui/db.py`), created by
`init_db` like every other table, plus an index on `store_pet_id` because every
report groups by it.

**Buyer identity is stored, and shown only where it earns its place.**
`buyer_user_id` is what makes the ledger auditable and answers "did this reach a
real person". Merchandising decisions need counts, not names, so the shelf view
defaults to counts and a per-listing sales figure; surfacing buyer identity is
its own decision with its own reason, not a free consequence of having the
column.

##### The capture mechanism, and the delivery guarantee it needs

Nothing new is built to carry this. The message already exists, is already
signed, and already arrives at the right moment:

1. The buyer hands off. The host quotes, charges (`require_credits`), and
   creates the pet in her DatsMe house. `credits_charged` is the real figure.
2. The host POSTs `/partner/imported/{user_id}` on DatsPet, HMAC-signed with
   the partner secret (`notify_partner_imported`).
3. `partner_imported` verifies the signature over the exact raw bytes, and
   already refuses to stamp a pet the named user does not own.
4. Beside the `stamp_writeback_acked` it already performs, it inserts the sale.

The two edits are ~3 lines on the host (pass the results it already has instead
of just their ids) and ~5 on DatsPet (one guarded `INSERT OR IGNORE`). No new
endpoint, no new auth, no polling, and no outbound call from DatsPet, which has
never called the host at all (§10.0).

**But that message is fire-and-forget today, and financial records may not
be.** `notify_partner_imported` is best-effort by design: it sits outside any
try the import depends on, its result is discarded, and it never retries. The
host's own reasoning — a failed ack "costs a stale chip in the partner's UI,
never a lost or duplicated pet" — is correct for a badge and **wrong for a
transaction**. A dropped notification would become a silently missing sale, and
since the amount is unrecoverable afterwards (above), it would be gone for
good.

So this path must be **at-least-once**, and it is safe to make it so precisely
because of the key already specified above — `pet_id` is the primary key and
the insert is `INSERT OR IGNORE`, so a redelivery writes nothing. **The
idempotency that stops double-counting is the same property that makes retry
possible**; without it, retrying would corrupt the ledger, and without
retrying, the ledger has holes. They ship together or not at all.

**The mechanism is an outbox on the host, not a retry loop in the request.**
Retrying in place inside the import handler fails on both counts that matter:
it adds the whole backoff window to a shopper's checkout response (the call
sits at `import_routes.py:429`, before the response is returned at `:434`), and
it is *not* at-least-once anyway — a worker restart mid-backoff loses the sale
permanently, which is the exact loss this section exists to prevent. So:

1. The import handler **writes a row** to a new `partner_notifications` table
   (partner slug, user id, export type, the `items` payload, `attempts`,
   `next_attempt_at`, `delivered_at`) inside the transaction that already
   commits the pets and the charge. If that transaction commits, the
   notification is owed; if it rolls back, there was no sale to report.
2. It then attempts delivery **once, inline, best-effort** — the current
   behaviour, so the happy path keeps today's latency and today's "a partner
   outage never fails a checkout" guarantee. Success stamps `delivered_at`.
3. Anything still undelivered is retried by a **periodic job on the existing
   APScheduler** (`api/apps/dpp/scheduler.py`, which already runs
   `partner_health` at 60 s and `nonce_reap` daily), with exponential backoff
   and a bounded attempt count. Exhausted rows stay in the table, undelivered
   and visible — a queryable list of sales the partner does not know about is
   the right failure mode, and far better than a log line.

This is new host infrastructure (there is no outbox or task table today, and
the SDK's `retry.py` is a *partner*-side queue, not the host's), and it is the
substantial part of Phase 1a. It is worth it here and was not worth it for a
badge, which is exactly why the notification was fire-and-forget until now.

**Two rules the retry adds on the partner side.** A late redelivery may arrive
after the buyer has deleted the pet or been revoked, and
`partner_imported` skips any id whose pet row is gone
(`datsme_integration.py:855-857`). That guard must stay for the *stamp* — there
is nothing to stamp — but the **ledger insert must not depend on it**, or a
retry that arrives after a house cleanup would record nothing and the sale
would vanish exactly as §1.5.2 describes. The insert therefore takes its
`store_pet_id` from the notification payload when the pet row is absent, which
means the host must send it: `items: [{id, store_pet_id, credits_charged}]`.
And a row already present is left untouched (`INSERT OR IGNORE`), so a first
delivery that carried no amount keeps `credits_paid` NULL even if a later retry
carries one — acceptable, and the reason the host sends the amount from the
start rather than adding it later.

Two rules that follow, and both belong in the tests:

- **A retry must remain free.** The guard is not "the host promises to send
  once" — it is the primary key. Anything that later makes the insert
  conditional on absence-of-row-then-write reintroduces the race the key
  removes.
- **A failed ack still must not fail the purchase.** The retry is on the host's
  side of the wire, after the charge and the pet both committed. Nothing about
  this may make a partner outage able to break a checkout.

#### §1.5.4 Views are a different problem, and not a cheap one

There is no view counter and adding one is not a WHERE clause. The shop paints
from **one cacheable listing response** (§6.1), so there is no per-pet request
to count, and `preview.png` ships a 24-hour cache header
(`PREVIEW_CACHE_CONTROL`, §3.1) precisely so it
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
pattern (`webui/app.py:170-208`).

> **Reading this against the code:** §3 describes the surface **after Phase 1b**
> (§1.4). What ships today uses the `published` boolean it replaces — so
> `status`, `admin_note`, the four-state transitions and the renamed `db.py`
> functions below are the *target*, not the current tree. §14.1 records what is
> actually built.

### §3.1 `webui/pet_store.py` — the public shop (read + adopt)

| Route | Auth | Returns |
|---|---|---|
| `GET /api/store` | none (anonymous browsing, §0.4 of the catalog spec) | `{pets: [Listing]}` — **`status = 'shelf'` only**, newest first. `Listing = {id, display_name, animal, breed_id, description, tags, pose_count, poses, preview_url}`. Never bytes, never an off-shelf row. |
| `GET /api/store/{id}/preview.png` | none (an `<img>` has no 401 handler — `owner_scope.py:120-122` precedent) | the `preview_png` blob, `Cache-Control: public, max-age=86400` — 24 h, the `PREVIEW_CACHE_CONTROL` constant — safe because a preview is immutable per id (derived once at insert; ai-tag touches only text). 404 for unknown *or off-shelf* ids — intake, backroom and archived must be invisible, not merely unlisted. |
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
| `GET /api/admin/store` | all rows in every state, newest-first so `intake` surfaces without a queue. Built row-by-row through the **same `_admin_view` builder the detail route uses** — the list and the detail are field-for-field identical, and a test asserts it. It served the raw byteless projection until 2026-07-31, which silently dropped `donated_by` and `sellability_errors`: the list is the only surface that renders either, so both were unreachable in production while every gate was green. |
| `GET /api/admin/store/{id}` | one row, full metadata: the listing shape + `status` + `admin_note` + `first_shelved_at` (the editor gates the animal field on it) + `donated_by` (§10.4) + `sellability_errors` (§5.3) |
| `GET /api/admin/store/{id}/preview.png` | the portrait **in every shelf state**. The shopper's preview route (§3.1) resolves through the shelf gate and 404s anything off it — correct there and exactly wrong here, since most of this surface is `intake`. Same bytes, same 24 h immutability, but `Cache-Control: private` (`ADMIN_PREVIEW_CACHE_CONTROL`) because it is served from behind the admin gate. Pointing the admin at the shopper's route made every donation a broken image. |
| `POST /api/admin/store/intake-from-pet` | body `{pet_id}` — **the stocking door**, §5.1. **MOVES** the pet: the `intake` store row is written, then the house row is deleted. The source is read through the caller's OWN owner scope (the same scoped access keep/delete use): an admin stocks only a pet she can see in her house, never an arbitrary row by id. A lost delete race withdraws the store row and 409s. |
| `PUT /api/admin/store/{id}` | edit the AUTHORED fields: `display_name`, `description`, `tags`, `animal` (only while `first_shelved_at` is NULL — §1.3), `admin_note`. **Carries no `status`.** Tags are normalized on write — lowercased, trimmed, deduplicated, capped by named constants (`STORE_MAX_TAGS = 16`, `STORE_MAX_TAG_LEN = 32`). If the row is *currently* shelved the sellability gate re-runs (§5.3), so an edit can never make a live listing unsellable in place. |
| `POST /api/admin/store/{id}/status` | **the triage door** — body `{status, admin_note?}` and nothing else. One shelf move, no prior read, so it cannot clobber text someone is editing in another tab. Moving to `shelf` runs the sellability validator (§5.3) and refuses on failure; every other transition is free (§1.4). This is the route a script or an agent drives, and the one behind the per-row control in §6.2c. |
| `POST /api/admin/store/{id}/ai-tag` | write description + tags with AI (§4) — the ONE generator of listing text, overwriting both, **only if the row is off the shelf** (a live listing is the admin's text, and regenerating it would change what shoppers are reading) |
| `DELETE /api/admin/store/{id}` | remove from inventory. Copies already adopted into houses are unaffected (they are copies). |

### §3.3 `webui/db.py` additions

`db.py` stays the one store module. Six write/read functions plus the shared
`store_listing_view` projection both routers serve:
`insert_store_pet` (derives the four derived columns; the only writer),
`list_store_pets(shelf_only)`, `get_store_pet`, `update_store_listing`,
`set_store_status`, `delete_store_pet`.

Plus `list_store_rows(shelf_only=False)` — FULL rows for the admin inventory.
The byteless `list_store_pets` projection cannot back that surface: "sellable"
is defined over the bundle (§5.3), so the admin list has to read the blobs to
show the same verdict the publish gate enforces. That cost is accepted on a
cold, single-user, admin-only route; inventing a cheaper second definition of
sellable is how the list and the gate start disagreeing. The shopper's hot
route keeps the byteless projection.

Three of those names change in Phase 1b and the rename is part of that phase's
work, not a silent drift: `list_store_pets(published_only)` →
`list_store_pets(shelf_only)`, `set_store_published` → `set_store_status`, and
`insert_store_pet(published=…)` → `insert_store_pet(status=…)`. Callers to sweep
are `pet_store.py`, `store_admin.py` **and `scripts/migrate_samples_to_store.py`**,
which passes `published=True` and would otherwise break at runtime on the next
sample drop-in. The existing `pets` functions are
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

**Why not draft at intake-from-pet, which is where Rev.1–Rev.8 put it?**
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
   **Move to intake** (`POST /api/admin/store/intake-from-pet`). This **moves**
   the pet into a new `intake` `store_pets` row — the house row is deleted —
   extracts the portrait, derives the mechanical facts, and seeds
   `display_name` from the house pet's name. The description and tags start
   **empty**: the AI is never run by stocking (§4). She writes them, or taps ✨
   and confirms — and that draft's `display_name_suggestion` is offered beside
   the name field, never auto-applied.
3. She edits the name, description, and tags in the ⓘ dialog, then sets the
   row's state to **`shelf`**. The row appears in the shop on the next listing
   fetch.

**Move, not copy, at step 2 — corrected 2026-07-31.** Rev.1–Rev.14 specified a
copy "so the two lifecycles stay separate", which sounded principled and was
wrong in practice: the leftover house pet cannot be sold, holds a house slot,
duplicates ~3 MB of bundle, and — because the picker shows no sign of what is
already stocked — invites stocking the same pet twice. Within one session of
real use that produced two Vampires and two Blue Butterflies in staging
inventory, and the owner's verdict was the right one: *"it should be removed
from your house stock (like gifting), otherwise you will have two vampires,
which doesn't have any value."*

The deeper reason it is right: this is **the same transfer a donation performs**
(§10.5), so the store now has exactly ONE way to acquire a pet rather than two
that behave differently. `intake-from-pet` follows the donate door's order and
race handling exactly — store row written FIRST, house row deleted second (a
crash between them leaves a recoverable duplicate rather than a vaporised pet),
and a lost delete race withdraws the store row and 409s. It differs in one
respect only: **no donation ledger row is written**, because an admin stocking
her own pet is not a gift and earns no social points. That also keeps
`donated_by` correctly NULL for anything an admin stocked herself (§10.4).

Because it is destructive to the house, the button opens a confirm — the same
shape the donate door uses, for the same reason.

### §5.2 Portrait extraction

`intake-from-pet` extracts a portrait from the sprite sheet's idle frame,
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
the build is blocked at test by the same code.** Phase 2's donate door is this
same function's third caller (§10.1).

---

### §5.4 What uniquely identifies a pet — and what does not

**A manifest carries no per-pet unique id.** This is worth stating plainly
because two fields look like one and neither is:

| Field | What it actually is | Unique per pet? |
|---|---|---|
| `fingerprint` | the **issuer** mark — the literal string `datspet`, stamped once at mint (SPEC_PET_OWNER_FIELD §1.7) | **No.** Identical on every pet ever built |
| `reference_id` | the step-1 reference **image**, a designer input to `POST /api/generate`; a design mints a NEW one | **No**, and it never reaches the bundle |
| `owner_name` / `owner_category` | who holds it now — changes on every transfer | No |
| `display_name` | what a human called it | **No.** Staging held two `Vampire` rows that were genuinely different pets |
| `bundle_sha256` | SHA-256 of the bundle bytes, derived by `insert_store_pet` | **Yes** — the only per-pet identity the store has |

So the store's identity for a pet is **its bytes**, and there is precedent:
`migrate_samples_to_store.py` has always been idempotent on `bundle_sha256`.

**The invariant: the store never holds the same bundle twice.** Both stocking
doors — `intake-from-pet` (§5.1) and the donate door (§10) — look the digest up
via `db.store_pet_id_with_bundle` and refuse with **409** before writing
anything. "Before" is load-bearing on both: each door *removes the source pet*,
so a duplicate caught afterwards would cost someone their pet rather than a
click. The admin's refusal names the listing that already holds those bytes.

It is enforced at the doors and **not** as a `UNIQUE` index, deliberately:
environments that predate the guard already hold duplicates (staging carried two
byte-identical `Blue Butterfly` rows from the copy-era stocking door), and a
UNIQUE index would make `init_db` fail at boot instead of letting an admin
resolve them. `idx_store_pets_bundle_sha` makes the lookup free without that
hazard. If every environment is ever cleaned, promoting it is a one-line change.

Note what this correctly does **not** catch: two pets designed separately are
different bytes and are two legitimate listings even when they share a name.
Keying on `display_name` or `breed_id` would have refused the second Vampire,
which was a real pet.

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
- **Tag filter** — a chip row under the animal chips, most-used tag first
  (`tagsPresent`, capped at `TAG_CHIP_LIMIT`; ties break alphabetically so the
  bar does not reshuffle between refreshes). An ACTIVE tag is always shown even
  when it falls outside the top slice, or a rare tag could not be cleared once
  chosen.
- **Cards** — portrait, name, animal, and **the pose names**. **No
  price** (§0.6.1): the copy stays "you'll see the exact cost on DatsMe
  before anything is charged", and makes **no cheaper-than-designing claim**
  — the relation between the two prices is a host knob (§0.2) that can change
  under the page. The host's checkout remains the one place a number appears.

**Description and tags are NOT on the card** (corrected 2026-07-31). They were
until an owner looked at a real shelf: the picture already says what the pet is,
so the prose was decoration, and the tags were vocabulary for the filter rather
than something to read per row. Rendering both made card height depend on how
much text a listing happened to carry — a shelf of four showed three nearly
empty cards beside one wall of prose and eight tag chips.

Both stay in the listing payload and both stay **searchable**: `filterListings`
still matches over name + description + tags, and a test asserts a query
matching only the now-hidden text still finds the pet. Hiding them from the card
had to tidy the layout without deleting a feature.

The tag filter moved **up into the bar** rather than away, because tapping a tag
on a card was the only way to SET it — the chip at the top merely cleared it.

**Pose names replace the pose count.** "8 poses" was the one fact on the card a
shopper could not act on; it does not say whether the bird flies. The names are
already in the listing (`store_listing_view` derives `poses` from the manifest),
so this renders data that was being fetched and thrown away.
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
inventory table (status visible at a glance, newest first), the intake-from-pet
picker (reads the admin's own house via the existing `listPets()`), and the
listing editor (name, description, tags, the four-state status selector and
`admin_note` of §1.4, and the ✨ that writes description + tags — §4, behind its
confirm).
Linked from the admin nav exactly as motions/design/ai/settings are.

Two things the first build got wrong, both found by an owner testing a real
donation on 2026-07-31 and both fixed the same day:

- **The section is "Inventory", never "Shelf".** It lists all four states, and
  heading it "Shelf" told the admin a row sitting in `intake` was already for
  sale. The stocking button says "Copy to store", for the same reason: it
  copies to `intake` (§5.1), not onto the shelf.
- **Opening the editor scrolls it into view.** It renders *below* the inventory,
  so on any list longer than a screen "Edit" appeared to do nothing — and since
  the shelf state lived in that panel, the surface read as "I cannot promote
  this pet". Superseded the same day by §6.2c, which removes the reason to
  leave the row at all.

### §6.2c The row owns the lifecycle; the dialog owns the text

The fix above made the editor reachable. It did not make it *right*: moving one
pet one state still meant opening a whole form. The two things change for
different reasons and on different clocks —

| | changes | lives in |
|---|---|---|
| **Shelf state** | every triage pass, potentially hundreds a day | the **row**, inline |
| **Name, description, tags, animal, note** | written once, rarely revisited | a **dialog** behind ⓘ |

so they are two controls and, behind them, two routes (§3.2).

**The row** is one line: portrait, name, `animal · N poses`, the sellability
warning when there is one, a four-state `<select>`, a **Save that appears only
when the selection differs from what is stored**, ⓘ, and ✕. Picking a state
does not commit it — a select that saves on `change` fires on a stray scroll
wheel, and this is the one list where a mis-set state puts a pet in front of
shoppers. The dirty row is outlined in gold, so a triage pass shows at a glance
what is unsaved. Rows **never reorder on save**: a listing that jumps to the top
when its state changes moves the next row under the cursor, which is how a pass
mis-files a pet. Only intake-from-pet prepends, because that row is genuinely
new.

**Removed from the row:** the 🎁 donated badge. It cost a permanent column of
width on every line to say something about a minority of rows that changes no
decision — donor identity is provenance, not triage. It moves into the ⓘ dialog
next to the id, which is where the rest of the provenance already is. §10.4's
requirement is that the donor be *visible to the admin*, not that it occupy the
list.

**Removed from the dialog:** the shelf-state selector. Two places to change one
thing is how they come to disagree.

`admin_note` stops being conditional on `archived` — the state control is no
longer in the dialog, so there is no moment there to ask. It is a plain optional
field; nothing enforces it, because a required one would only ever collect the
word "no".

### §6.2b The admin editor after Phase 1b

§13 calls 1b "DatsPet only", which is true of the repos and misleading about the
work: the admin page is built around a boolean and every part of that has to
move. What exists today and what replaces it:

| Today | After 1b |
|---|---|
| `EditorState.published: boolean` | `status: StoreStatus` (the four-value union) + `admin_note: string` |
| Two buttons: "Save draft" / "Publish to shop" | **One Save**, plus a four-way status control; the save is what applies the chosen status |
| Table cell renders `published`/`staging` | Renders the status, with `intake` visually distinct — it is the inbox |
| AI button, animal field and hint gated on `!published` | Gated on `status !== 'shelf'` (ai-tag) and on `first_shelved_at == null` (animal, §1.3) |
| `StoreAdminListing.published` in `api.ts`; PUT body `{…, published}` | `status` + `admin_note` + read-only `first_shelved_at`; PUT body matches |

Two behaviours worth stating rather than leaving to taste:

- **The inventory table defaults to newest-first** so `intake` rows surface
  without a queue. That sort is what makes Phase 2's "one badge and one sort"
  claim true (§10.4), and it ships here rather than there.
- **Archiving asks for a note, shelving does not.** `admin_note` is optional in
  the schema, but the UI prompts for it on the way to `archived` — the one
  transition whose reason nobody will remember in three months. Nothing enforces
  it server-side; a required field would just collect the word "no".

The shopper-facing `Listing` shape (§3.1) gains **nothing**: `status` is an
admin fact, and the public listing is `shelf` rows by definition, so exposing it
would be a field with one possible value. `db.store_listing_view` keeps emitting
it for the admin view, and `pet_store.py` keeps popping it — the same shape the
`published` flag has today.

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

A user gives a pet she designed back to the store and is thanked with a social
point on the spot; the admin decides only whether it reaches the shelf. It is
the supply side of the store: Phase 1 makes
every listing cost the owner admin time and GPU minutes, and this makes the
users the supply. It is also the pressure valve on the 50-pet house cap —
donating frees a slot *and* pays, where deleting just frees a slot.

§0's decisions carry over. Decision 0.4 —
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

And one standing fact rather than a constraint: **DatsPet has never called the
host.** It is a pull-only
partner: the push path was deleted, not disabled (`webui/app.py:1876`), and the
`httpx` import left at `datsme_integration.py:40` is its only residue. (`httpx`
is a pinned dependency used by `ai_engine`, so what is missing is the writeback
*caller*, not the library.) §10.7.3 is
explicit that this is new code and why it is worth adding.

### §10.1 The donate door

**Donating is giving, and giving is final.** The model is a charity shop, not a
consignment desk: the donor hands the pet over, is thanked on the spot, and the
shop decides what goes on the shelf. She does not get it back, and there is no
verdict she is waiting on.

That one rule is what makes Phase 2 small. It removes a review queue, its
`pending`/`approved`/`rejected`/`returned` lifecycle, an approve/reject pair of
endpoints, a return path, a
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
   seeded by `_seed_animal(breed_id)`, exactly as intake-from-pet does;
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
    reward_state        TEXT NOT NULL,     -- owed | delivered | capped | disabled | declined
    points_awarded      INTEGER,           -- what the HOST said it gave; NULL until it answers
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
**read-time join** from this ledger, which is exactly the boundary §7.2 names —
the record of how something came to be is a read-time fact, never an engine
input.

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
(§0.6.1).

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

**DatsPet awards nothing. It asks, and DatsMe decides.** This is the same
posture as pricing (§0.6.1), and it is worth stating in its own words because
the shorthand "the donation pays a social point" invites the wrong picture:

- DatsPet has **no ledger, no balance, and no write access to DatsMe's**. The
  only thing it can do is send a signed message naming a donation it approved.
- **DatsPet never DECIDES a figure.** It names no amount when asking; the host
  reads its own knob. What comes back is the host's report of what it actually
  did, which DatsPet stores and repeats — the same way it records what the host
  charged for a sale (§1.5.3). Repeating the host's answer is not pricing.
- **The host may decline, and declining is normal, not an error.** The knob at
  0 (`disabled`), the donor already thanked today (`capped`), the capability
  revoked (`capability_not_granted`) — each is a legitimate answer that DatsPet
  records and stops asking about.
- So the partner's side of this is *bookkeeping*: which donations it has told
  the host about, and what the host said. Whether a point exists is DatsMe's
  fact, held in DatsMe's ledger, and DatsPet never displays it (§0.6.1).

What Phase 2 adds to DatsPet is therefore the ability to **make a request**,
not the ability to pay. Everything below is about getting that request
delivered exactly once and recording the answer.

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
  never yet imported here. `WritebackBuilder` is *not* used: it builds the body
  from a `LaunchContext` and defaults the idempotency key to the launch `jti`.
  **The key is derived from the donation ids AND the launch that is sending
  them** (Rev.11). An earlier draft said "the donation ids, so a retry is
  byte-identical"; that was wrong as built, and the way it was wrong is worth
  keeping: the signed body embeds the current launch JWT, so a retry from a
  LATER launch has the same key and different bytes — which the host correctly
  answers `idempotency_key_reuse` 409, *after having already paid*. Including
  the launch makes a retry byte-identical **within** a launch (the cache
  replays it) and a fresh key **across** launches (no false conflict). Real
  duplicate protection was never the cache's job anyway: it is the host's
  `partner_social_awards` unique key, which answers a re-delivery with
  `duplicate` outcomes that settle the rows.
- **Outcomes**: HTTP 200 marks every id in the batch `delivered` and stores
  the `points_awarded` the host reported, so the thank-you survives a reload
  and never has to be recomputed.
- **A 4xx is not automatically permanent, and getting that wrong killed the
  normal case** (Rev.11). One launch carries one writeback because the nonce
  burns, so the SECOND donation of a session posts with a spent nonce and gets
  a **401** — as does any session past the 60-minute token TTL. Treating "any
  4xx" as terminal marked those `declined` and destroyed a reward the donor had
  earned. **401, 409 and 429 leave the rows `owed`**; other 4xx are the genuine
  refusals (`capability_not_granted`) and are terminal. A per-entry
  `capped` verdict from the host marks that row `capped` — **terminal, never
  retried**; the donor gave several things and was thanked once, which is what
  a daily cap means. A permanent refusal (`capability_not_granted`) marks them
  `declined` — terminal, because the donor revoked the capability that pays
  her; a later re-grant does not retroactively re-arm them, and no admin screen
  exists to (§10.4). A `disabled` verdict (the knob is 0) is recorded as such
  and is likewise terminal. Anything else leaves them `owed` for the next
  launch.

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
   security posture.** `should_auto_grant` (`capabilities.py:245`) auto-grants
   low-risk capabilities to official partners without a consent screen. For a
   *credit* award that would have been wrong — credits are money and buy GPU
   work — which is why the credit version of this section required `medium`.
   Social points are reputation: they buy nothing, gate nothing (§10.7.6), and
   only ever add. A consent screen reading "DatsPet can award you social points"
   asks the user to authorise a gift to themselves.
   **Not** added to `PULLABLE_TARGETS` — this target is push-only.

**The wire contract, so either side can be built first.** Target
`user.social_award`, schema `social_award.v1`. The payload is a batch (§10.7.2 —
one writeback per launch):

```jsonc
// POST /api/integrations/result  →  body.payload
{ "awards": [ { "award_key": "<donation id>", "reason": "pet_donation" } ] }
```

**The direction is what matters, and the two directions differ.** DatsPet may
not NAME an amount when asking — a partner that could name a figure could name
a bigger one — so the request carries no number and the host reads its own
knob. But the host REPORTING what it did is a different act, and it is exactly
what the sale path already does (`credits_charged`, §1.5.3). So the response
carries both the verdict and the figure:

```jsonc
{ "results": [
    { "award_key": "…", "outcome": "awarded",   "points_awarded": 1 },
    { "award_key": "…", "outcome": "duplicate", "points_awarded": 1 },
    { "award_key": "…", "outcome": "capped",    "points_awarded": 0 }
] }
```

- `awarded` → the partner marks it `delivered` and stores `points_awarded`.
- `duplicate` → also `delivered`; `points_awarded` is what the FIRST delivery
  wrote, read off the host's claim row, so a retry reports the same number
  rather than a fresh one.
- `capped` → `capped`, terminal, never retried (§10.7.3). `points_awarded` is
  0, and 0 is unambiguous here because the outcome word already says why.
- `disabled` → the knob is 0; terminal, and *not* an error — the owner turned
  it off deliberately.
- An entry missing from `results` stays `owed` and rides the next launch.

This is what lets the donor be thanked accurately (§10.8). Without the figure,
DatsPet could only say "thanked" — or, worse, hardcode a number that a knob
change would quietly turn into a lie.

Transport failures map the way §10.7.3 already states: a permanent
`capability_not_granted` (403) marks the batch `declined`; **any other 4xx is
also terminal** — a 400 the partner keeps retrying forever is the failure mode
that turns a bug into a loop — while 5xx, timeouts and network errors leave the
batch `owed`.

**Idempotency: a new social-DB table with a unique business key.**
`partner_social_awards(partner_slug, award_key)` unique — `award_key` is the
donation id — plus `user_id`, `amount`, `created_at`. Modelled on
`uq_partner_collection_external` (`models.py:247`) for the key shape and on the
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
`CREDIT_CONFIG_KEYS`, so no admin screen could see it — the guard that now
prevents a repeat lives in `api/tests/test_pet_store_price_basis.py`. The full list for
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

An earlier draft said donation status would be "visible on the house on the
next visit". It cannot be: §10.3 deletes the house row, so there is no card
left to carry a status. And under Rev.8 there is no status to watch either: the donation
completed the moment she clicked. What remains worth showing is the record of
what she gave.

A **Donations** section on the house page, fed by `GET /api/donations` (own rows
only, scoped like every other read): the name, when she gave it, and the
thank-you. Nothing is actionable — no restore, no appeal, no verdict — which is
the point of the model.

**The capability is REQUIRED, and no user is ever asked for it (Rev.13).**

DatsMe gates a launch on required capabilities and auto-grants the low-risk
ones inline for an `official` partner. `social.award` is required, low risk,
and DatsPet is official — so it is granted silently at launch, every existing
user picks it up on their next visit, and nobody sees a screen. Measured on
staging: a user holding only `pets.write` came out of one launch holding
`social.award` too, and her next donation was thanked.

**Why not ask.** A DPP launch is authenticated by DatsMe, minted by DatsMe, for
a DatsMe user. Asking that same user to grant a first-party partner permission
to *give them points* is ceremony — there is no third party and nothing to
protect them from. Capabilities gate ACTIONS rather than identity, which is why
`credits.consume` is high risk however the user signed in; but that reasoning
only bites when an action can COST something, and this one can only add.

An earlier revision asked at the donate door, reasoning that a donation is
irreversible and that is the moment worth interrupting. The irreversible thing
is the *pet*, and the confirm dialog already says so — the extra screen was
only ever about the points. That code survives as a fallback: if a user somehow
lacks the grant, the dialog still says this pet earns nothing and offers the
consent page, rather than taking a pet and silently failing to pay for it.

**The trade, recorded rather than buried:** a required capability is one the
user cannot decline and cannot meaningfully revoke, because the next launch
re-grants it. Accepted here because the capability can only ever award, never
spend. It would NOT be acceptable for one that costs the user anything.

**It has to be `required` to get there.** Auto-grant only ever runs over the
required set (`mint_launch_token` filters `PartnerCapabilityRequest.required ==
True`), so an *optional* capability is never granted automatically at any tier
— and the launch gate never prompts for one either. An earlier attempt promoted
the partner to `official` while leaving the capability optional; it granted
nothing, which is how this was found.

**The thank-you names the number, and the number is the host's.** A delivered
row reads *"Thank you — DatsMe credited you 1 social point."* using
`points_awarded` exactly as the host reported it (§10.7.4), never a figure
DatsPet computed or remembered from a knob it does not own. Before the host has
answered, the row reads *"thank-you on its way"*; when the host declined —
capped for the day, or the reward turned off — it reads that the pet was
accepted and says nothing about points, because nothing was given.

This does not cross §0.6.1. That rule forbids DatsPet from **quoting a price or
holding a balance** — a number it computed, or a running total that can go
stale. Echoing what the host just said it did is neither: it is the same act as
recording `credits_paid` on a sale (§1.5.3). What stays off this page is any
*total* — "you have 47 social points" is a balance, and balances live on
DatsMe.

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
  — the status column and the newest-first sort ship in **Phase 1b**, which
  Phase 2 depends on (§13), so by the time donations ship the inbox is
  already there.
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
  creates exactly one store row in `intake`, and one ledger row pointing at
  it** — and the new store pet is invisible on the public shelf until an admin
  moves it to `shelf`, which is the test that proves donations cannot
  self-shelve.
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
  retried; a **401/409/429 leaves the rows owed** and a later launch settles
  them; a lost response settles on the retry via `duplicate` rather than being
  declined; the idempotency key is stable within a launch and differs across
  launches.
- The donor-facing cases live in `test_donations.py` beside the rest rather
  than a separate `test_donation_thanks.py` — a delivered award stores the host's
  `points_awarded` and the donor's row renders that number, not a constant; a
  `capped` or `disabled` outcome says the pet was accepted and claims no
  points; a `duplicate` reports the FIRST award's figure rather than a fresh
  one; no page anywhere renders a point TOTAL (that is a balance, §0.6.1).
- Host `api/tests/test_social_award.py` (in-process, registered in
  `test_all.py` — the §14.2 rule): the four registry entries are consistent;
  a missing `social.award` grant 403s; the same donation id delivered twice
  pays once (the unique key); **the daily cap refuses the second award in a UTC
  day — the test that pins Rev.8's load-bearing defence** (§10.7.5); a reward
  amount of 0 is a no-op that still succeeds; the award writes
  `ledger_type="social"` with its OWN transaction_type, so it cannot borrow the
  gift reward's daily cap. **Plus a five-place registration guard** — every
  `*_social_reward_*` and `credit_pet_*` knob is in all five places of §10.7.4:
  `SOCIAL_LEDGER_CONFIG_DEFAULTS`, `CREDIT_CONFIG_KEYS`, the admin render array,
  the `isAward`/`isCost` label list beside it, and `TRANSACTION_LABELS`
  (§10.7.4 calls the fourth place the `isAward` list; it is the same array).
  Phase 1 shipped a knob that
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
  numbers (§0.6.1). The donor's Social Point History is where the award appears.
- **No per-donor donation cap** at launch (§10.1), and no reward for quantity:
  the daily cap means the second donation of a day is thanked with nothing.

---

## §11 Deliberately not done

- **No user-visible prices in DatsPet** — the host quotes, DatsPet doesn't
  (§0.6.1). Revisit only as its own decision.
- **No store pet as a design base** — the archetype rule
  (SPEC_PET_DESIGNER_FLOW §2.1) stands; a store pet is a finished design.
- **No dedupe of repeat adopts** — a store pet is a template, not a licence.
- **No closed tag vocabulary / no server-side search** — the second has a named
  tripwire (§6.1, ~200+ rows); the first has the three-instances rule (§1.3)
  instead of speculative structure.
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
  intake-from-pet derives mechanical facts that match the bundle; publish
  refuses an unsellable bundle (shared validator); **intake-from-pet never
  invokes the AI** (§4 — the guard against the auto-draft coming back); ai-tag
  refuses on a shelved row.
- `webui/tests/test_store_sales.py` (§1.5.3) — the ack writes exactly one sale
  row carrying buyer, listing, amount and time; a REPEATED host notification
  writes no second row (the `pet_id` key); a notification with no amount
  records `credits_paid` NULL, **not 0** (the "missing is not zero" rule) while
  a genuinely free re-import records 0; a designed pet's ack writes nothing;
  deleting the buyer's house pet and deleting the listing both leave the sale
  row intact; a **revoked** buyer's sale survives with `buyer_user_id` emptied,
  not deleted. A retry that arrives **after** the buyer deleted the pet still
  records the sale, from the `store_pet_id` on the notification — the case the
  pet-row guard would otherwise silently drop. Host side:
  `notify_partner_imported` sends the per-item amount it already computed,
  `item_ids` still matches the enriched `items` exactly, a partner returning 500
  forever never fails the checkout that already committed, and **an undelivered
  notification is still owed after a process restart** — the test that separates
  a real outbox from an in-process retry loop. Host tests are in-process and
  registered in `test_all.py`, per §14.2's rule; `test_dpp_import_pull.py` also
  asserts the ack body and must be updated with it.
- `webui/tests/test_store_status.py` (Phase 1b) — a shopper sees `shelf` rows and
  only those: `intake`, `backroom` and `archived` are absent from the listing
  and 404 on BOTH preview and adopt (invisible, not merely unlisted). Every
  transition is allowed except one: moving to `shelf` runs the sellability
  validator and refuses a broken bundle, while `backroom` and `archived`
  accept it — you may keep something you cannot sell. `archived` is reversible.
  The migration backfills `shelf` from `published=1` and `intake` from `0`,
  stamps `first_shelved_at` on the backfilled rows, adds `admin_note`, and
  leaves no `published` column (no dual source of truth) — run twice, it is a
  no-op the second time. `animal` is refused once `first_shelved_at` is set even
  when the row has since moved to `backroom`, which is the case the old boolean
  could not express. An unknown status value is a 422 naming the allowed set.
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
  intake-from-pet → shop → adopt → hand off → verify the host charged the
  flat knob and acked.

---

## §13 Rollout

Five pieces of work, not three. Rev.9 and §1.5 added two that are **extensions
of the shipped store, not part of donations** — Phase 2 stays exactly what the
owner has always been told it is.

| Phase | Ships | Repos | Depends on | Status |
|---|---|---|---|---|
| 0 | this spec, reviewed | — | — | done |
| 1 | the store | DatsPet + host | — | **live in production** (§14.4) |
| 1a | **the transaction ledger** (§1.5.3) — `store_sales`, the amount on the imported notification, and making that notification at-least-once | DatsPet + host | Phase 1 | **built + review-hardened, not deployed** (§14.5) |
| 1b | **the shelf lifecycle** (§1.4) — `published` → four-state `status`, with the migration | DatsPet only | Phase 1 | **built + review-hardened, not deployed** (§14.5) |
| 2 | **donations** (§10) | DatsPet + host | Phase 1 **and 1b** | **built + review-hardened, not deployed** (§14.5) |

**There is no Phase 3.** Phase 2 is the last one this spec defines; everything
beyond it is either the deploy of what exists, an owner's merchandising call,
or one of the named tripwires in §11 / §10.13 that only becomes work if its
condition is actually met.

**Why 1a and 1b are not folded into Phase 2.** Neither has anything to do with
donations. 1a is about sales that are happening *today* through the shipped
store; 1b is about inventory an admin manages *today*. Attaching them to
donations would hold live-store fixes hostage to a feature that has not been
signed off, and would make Phase 2 a bundle whose parts fail for unrelated
reasons — the thing §2's second test question exists to prevent.

**Suggested order: 1a, then 1b, then 2** — and only the last arrow is a real
dependency.

- **1a first because it is the only one losing something.** Every sale that
  completes before it ships is a transaction with no record, and the amount is
  unrecoverable afterwards (§1.5.3). Nothing degrades while 1b or 2 wait.
- **1b before 2 is a genuine dependency**: donations land in `intake`, which
  does not exist until the lifecycle ships.
- **1a and 1b are independent of each other** and could ship in either order or
  together; the ordering above is urgency, not coupling.

Deploy ceremony differs, and it is worth knowing before planning:

- **1a is a two-repo change** and follows the Phase 1 rule — **host first**, so
  the amount is being sent before the partner starts recording it. A DatsPet
  tier deployed first simply records `credits_paid` NULL until the host catches
  up, which the NULL-is-not-zero rule already handles correctly.
- **1b is DatsPet-only**, but it is a schema change to a live table in three
  environments (§1.4). Staging first, and verify the shelf still serves its pet
  afterwards — deploy checklist C5 is exactly that check.
- **2 has its own internal order**, given in §10.12.

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

## §14 As built — the ledger

**Phase 1 is live in production** (§14.4 records the deploys). Phases 1a, 1b and
2 are BUILT and deployed nowhere (§14.5). Read this section rather than the
prose above when the question is "what is done" — §1–§13 describe the design in
its finished state, and a design being described here is not evidence it runs.

### §14.1 Built and green

| Area | Where | Gate |
|---|---|---|
| `store_pets` table + `source_store_pet_id` ALTER | `webui/db.py` | — |
| Store functions (`insert_store_pet` … `delete_store_pet`), on the `published` boolean | `webui/db.py` | — |
| Public shop + adopt | `webui/pet_store.py` | `test_store.py` |
| Admin CRUD + `_seed_animal` | `webui/store_admin.py` | `test_store_admin.py` |
| Sellability validator | `webui/store_validation.py` | shared by both callers |
| AI listing purpose | `pet_factory/ai_purposes/store_listing.json` | registry guard |
| Migration script | `scripts/migrate_samples_to_store.py` | ran once per environment; its input files are deleted in the repo (§14.3) |
| `price_basis` on export items | `webui/datsme_integration.py` | — |
| Shop page (`/catalog` evolved) + admin page + `api.ts` | `web/src/app/{catalog,admin/store}` | `tsc`, vitest, `storeFilter` test |
| **Host** `credit_pet_store_cost` knob | `social_ledger_config.py:54` (default 50) | — |
| **Host** basis at quote **and** charge | `pet_writeback.py:188`, `:404` | `test_pet_store_price_basis.py` |
| §8 retirement | sample routes/helpers/scripts gone; content files deleted **in the repo** 2026-07-31, still on the boxes until the next deploy (§14.3) | `tsc` clean |

**Gates:** DatsPet 593 pass (20 store) · `tsc` clean · vitest 36 · 0 lint errors.
Host: owner-fields 70/70, price-basis 10/10, app imports clean.

### §14.2 Three defects found after the build

**The host's price-basis test ran nowhere.** It was written pytest-style; the api
venv has no pytest and it was never registered in `test_all.py`, so the suite was
green having never executed one assertion about **what a user is charged**. That
is the exact false-green shape this project keeps meeting. Converted to the house
in-process convention (`TestResults` + `run()`) and registered — 10/10, on the
interpreter the app itself runs.

*The rule this yields:* on this host, a new test is in-process and registered, or
it does not exist. pytest-style is reserved for the `_CAMPAIGN_PYTEST_GATES` list,
which at least skips **loudly**.

**The store price knob reached no admin screen.** `credit_pet_store_cost`
shipped seeded, charged, and absent from `CREDIT_CONFIG_KEYS`, so the host's
credits screen could neither show nor edit it — decision 0.2's "the owner's
dial" was unreachable except by a direct DB write. Found in the post-deploy
review, fixed with a subset guard test in
`api/tests/test_pet_store_price_basis.py`. §10.7.4 generalises it: registration
is five places, and a knob missing from any one of them is invisible.

**The frontend did not compile.** §8.1 — backend retirement landed before the page
that called it. Fixed; the ordering rule is now written down.

### §14.3 What is genuinely left

**Every phase this spec defines is now built. Nothing after Phase 1 is
deployed.** What remains is shipping, stocking, and a short list of things
deliberately not done.

1. **Deploy 1a, 1b and 2** — §13's order, staging before production, with the
   `datspet.db` backup before 1b (checklist B8b: that migration drops a column,
   so rollback is a file restore). 1a is the one with a cost to waiting — every
   store sale that completes before it ships is a transaction whose amount
   cannot be reconstructed afterwards.
2. **Stock the shelf deeper** — one migrated sample satisfies the launch line
   (*not visibly emptier than the grid it replaced*), but one pet is a thin
   store. Count, captions and the knobs' values are the owner's calls; the §5
   flow is live in both environments.
3. **Turn donations on when ready** — `pet_donation_social_reward_amount`
   ships at 1 and the daily cap at 1. Both are live knobs; 0 on either disables
   the reward rather than uncapping it (§10.7.5).
4. **The deliberately-not-done lists stand** (§11, §10.13, §1.5.4). None is a
   phase. Each becomes work only if its named tripwire trips: server-side
   filtering at ~200+ listings (§6.1), a closed tag vocabulary at three
   consumers (§1.3), a daily donation cap if inventory spam becomes real
   (§10.1), a sales *reporting* surface once the ledger has rows worth reading
   (§1.5.3 ships write-only on purpose), and view counting only as a
   purpose-built beacon with its own privacy argument (§1.5.4).
5. **Design provenance is a different spec**, not a phase of this one —
   `SPEC_PET_DESIGN_PROVENANCE.md`, draft, nothing built.

### §14.6 Deployed — 1a, 1b and 2 (Rev.12, 2026-07-31)

Host-first (§13), staging verified before production, both tiers at the same
commit (Rule 0). DatsPet `79bf3b3c`; host `cd7c2ff0` (prod picked it up inside
`868bfe9e`).

| Check | Staging | Production |
|---|---|---|
| C1 `verify_deployment.sh` | **14/14** | **14/14** |
| 1b migration on real data | `published` dropped; the shelved row → `shelf` + `first_shelved_at` stamped; two others → `intake` | same, on its one row |
| Store E2E (incl. the sale ledger) | **PASSED** — charged 50, `store_sales` recorded 50 | shelf serves; C5 pass |
| Donation E2E (the reward loop) | **PASSED** — donor's social balance moved 10 → 11, claim row written, re-delivery paid nothing | — |
| Shop surface in a real browser | only the `shelf` row visible; no price; no admin state leaked | same |

`datspet.db` was copied before each restart (B8b) — 93 MB staging, 251 MB
production — because 1b drops a column and rollback is a file restore.

**What only the live run could find.** The donation E2E failed on its first
execution, twice, for two different real reasons:

1. **DatsPet's manifest never requested `social.award`.** The user could
   therefore never grant it, the host correctly answered
   `capability_not_granted`, and the donation was marked `declined` — *after*
   the donor had irreversibly given the pet away. Every unit test passed
   because they stub the HTTP call entirely.
2. **The E2E read the wrong database.** It sourced `pet_env.sh`, but a deployed
   box takes its env from `webui/.env`; it reported a sale as missing that had
   been recorded correctly. A false failure is safer than a false pass and is
   still a bug in a check whose job is to be believed.

**The rollout fact to carry forward: `datspet` is `community` tier, so
`social.award` does NOT auto-grant** (that needs `official` + low risk).
Every existing user must consent on a later launch. Until they do, donations
complete and settle `declined` — so the donor surface says so plainly rather
than thanking someone who received nothing. Verified deliberately in both
directions on staging: `declined` without the grant, `delivered` with it.

### §14.5 Built after the Phase 1 deploy, shipped nowhere

| Phase | DatsPet | Host | Gates |
|---|---|---|---|
| 1a | `b4d35d0` | `485b2e86` | — |
| 1b | `2256ed3` | — | — |
| 2 | `99bf84d` | `a1b0bef1` | — |
| **review hardening (Rev.11)** | this commit | this commit | 641 pytest · tsc · vitest 36 · host 28/28 + 14/14 + 16/16 + registry 5/5 |

`pre-phase-2` is tagged in both repos as the rewind point before Phase 2
(DatsPet `4f8c31c`, host `485b2e86` — the host tag deliberately points at the
store commit, not its HEAD, because unrelated work landed there since).

**What the review pass changed, and why it matters more than the count.** Every
critical finding sat in a path no test touched, and the suite was green
throughout. The reward loop had never actually run end to end: the partner's
tests stubbed the host's response and handed themselves a `results` array the
real route does not send. A stub that answers the way you hope is not a test of
the thing you built.

Defects worth remembering rather than just recording:

- **The response shape was the whole break.** A handler can return anything it
  likes; if the route lifts two keys and drops the rest, a target that answers
  per item cannot work. Fixed generically (`build_writeback_response`) so the
  next target needs no route change — which was supposed to be the point of
  dispatching on a registry.
- **"Any 4xx is permanent" killed the normal case.** One launch carries one
  writeback, so the second donation of a session ALWAYS 401s. The spec named
  that constraint in §10.0 and the code contradicted it anyway.
- **A mid-loop raise un-paid its neighbours.** Validating the whole batch before
  awarding anything, and a SAVEPOINT per entry, are what make one bad entry cost
  only itself.
- **A once-only migration guard can strand a partial run forever.** Keying the
  backfill on `published` still existing, rather than on `status` being absent,
  makes it re-entrant.
- **A wrong-owner row is not an absent row.** §1.5.3's "do not depend on the pet
  row existing" is about ABSENCE; a row belonging to someone else is a
  contradiction, and writing a sale from it mis-attributes a purchase
  permanently.

Two earlier build defects, both caught by tests within seconds:

- **A helper inserted between `@router.post` and its handler silently rebound
  the route to the helper.** A decorator attaches to whatever follows it.
- **A test fixture built a bundle with no animations**, so the sellability gate
  refused the donation. The gate was right; the fixture was lying.

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
deleted in the repo and reach the boxes on the next deploy — the one-cycle
rollback buffer §8 asks for — the migration script
remains, now a no-op, for any future `<animal>/samples/` drop-in.

Operational notes from the deploys: the staging vhost served 403/500 for ~3
minutes when a rebuild replaced `out/` without the B8 vhost restart (the bind
mount follows the directory inode — B8 is unconditional for a reason); and
staging's live nginx conf carries a house-asset location block that exists
neither in the repo conf nor on prod — a drift to reconcile deliberately, not
during a deploy.
