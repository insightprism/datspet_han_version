# SPEC — The bundle owner fields (one pet, one owner)

**Status:** **READY TO IMPLEMENT — Rev.12 (2026-07-30).** Three `owner_*` fields in
`manifest.json` recording who may bring a pet to life on DatsMe and since when, plus a reserved
`fingerprint` mark. **DatsPet stamps the unsold state at mint; DatsMe stamps the owner at every
transfer.** One field carries the owner, and it is the DatsMe **slug** (or group tag) — the thing a
human can look up.

**Phases 1 and 2 are BUILT and green** (2026-07-30) — DatsPet `71f3632` (584 pass), DatsMe
`325b6909` (38/38 new, in-process). Verified end to end across both repos on a real 3.58 MB bundle.
**The host's gate ships observe-first (`PET_OWNER_ENFORCEMENT=observe`) and nothing is deployed**;
flipping to `enforce` is its own step, gated on §6.16. Phase 3 is unstarted and optional. See §9.

> ## Rev.12 — the owner is a slug, and the HOST writes it
>
> Rev.11 split the owner into a machine key (`owner_ref`, the DatsMe user id) and a human label
> (`owner_name`, the display name), and had **DatsPet** stamp the buyer at `keep`. Walking the
> actual lifecycle — mint → purchase → gift — showed both halves were wrong, and two checks against
> the host tree settled it:
>
> **1. `name_slug` is effectively immutable.** It is assigned once at signup
> (`../datsme_me/api/routes/auth.py:261`, `f"{first_name}.{next_number}"`) and **no rename path
> exists anywhere in the host tree** — every other reference is a read. Rev.11's whole justification
> for an opaque id was §7.2's "names are mutable, a rename strands the bundle". That risk is
> hypothetical, and it was inherited from Rev.2 without ever being checked. With it gone, the id
> bought nothing and cost the one property that matters for a portable record: **a human can read a
> slug and look it up**; `u_7f3c1a92b4e5` tells them nothing. So `owner_ref` is deleted and
> `owner_name` carries the slug (§1.2).
>
> **2. Every ownership change happens on DatsMe, and the host already holds the slug at both
> sites.** DatsPet only ever *mints*; it never sells and never gifts.
>
> | Event | Where it happens | Identity in hand |
> |---|---|---|
> | pet is built | DatsPet | nobody — it is unsold |
> | a user buys it | the host's checkout → `handle_target_user_pet` | `user_slug`, captured at `pet_writeback.py:293` |
> | the owner gifts it | the host's `accept_offer` | the recipient, by construction |
>
> `pet_writeback.py:293` already does `user_slug = user.name_slug` — deliberately, before the commit
> expires it — and `write_assets(manifest_json=…)` is in the same function. The slug costs the host
> nothing at either site. So Rev.11's plan for DatsPet to *fetch* the buyer's slug (a partner
> profile read on the purchase path) is deleted along with the problem it solved.
>
> **What follows from the split, all of it simplification:**
>
> - **The digest-ordering trap (Rev.11 §2.4b) disappears.** DatsPet serves a `factory` bundle whose
>   advertised `bundle_sha256` matches; the host verifies it and *then* rewrites the manifest as it
>   stores. DatsPet never restamps a bundle it has already published, so there is no ordering to get
>   wrong and no `db.restamp_bundle` (§2.4).
> - **DatsPet's `keep` stamp is deleted** (Rev.11 §2.4c), and with it every question about where the
>   buyer's identity comes from. DatsPet needs no DatsMe identity to stamp anything.
> - **The owner chooser moves to the host** (§5). Choosing "adopt this to my group" belongs on the
>   page where the transfer and the money are, not on the partner that built the sprite. DatsPet
>   needs no ownership UI at all, ever.
> - **The two ingest doors stop being the same check** (§4.2). Import is a *transfer* — a `factory`
>   bundle arriving there is the normal case and gets stamped. Upload is an *access check* — a
>   `factory` bundle arriving there was never bought, and is refused.
>
> **Rev.11's re-grounding still stands** and is not re-litigated here: the push path is gone
> (`e23253e`), `claim_unowned_pets` was replaced by `claim_anon_pets`, `SPEC_DPP_FEDERATED_LOGIN.md`
> does not exist, and DatsPet has no session table. Those corrections are why this spec no longer
> mentions Accept, `_post_pet_writeback`, or an `slg` launch claim.
>
> **Kept from earlier revisions:** the no-DRM decision (§0.1), flat top-level fields (§0.4), the
> `factory` category (§1.1), manifest-not-a-fourth-zip-member (§1.5), `fingerprint` as a
> stamped-once reserved mark (§1.7), one-writer-one-reader (§2.1/§2.2), the deliberate
> two-implementation duplication (§2.3a), and **the one hard-won lesson — never suppress the
> `transfer` block on an owner condition** (§2.5), which Rev.12 makes sharper: under this design
> *every* pet DatsPet exports is `factory`, so that filter would suppress 100% of the pull channel.

**Repos touched:** `datsme-pet-factory_wu` (mint stamp + reader) — Phase 1, self-contained.
`datsme_me` (the two transfer stamps + the ingest ladder) — Phase 2. `datsme_me` again (the group
chooser on the checkout page) — Phase 3, only if group licensing becomes a product.

**Ship order — one real constraint.** DatsPet's mint stamp goes first, or the host's ladder ships
**warn-only** until it has. §4.3 refuses a bundle with no owner fields, so a host that enforces
before DatsPet stamps would refuse every pet in flight. The reverse order is safe: stamped fields no
reader consults are inert — which is exactly why Phase 1 ships alone. Pinned by §6.16.

---

## 0. The core decisions (read this first)

1. **This is deliberately light protection, not DRM.** Anyone who unzips a bundle can edit these
   fields. That is an accepted outcome, not a gap to close: a pet costs $0.50–$1, and the cost of
   real enforcement (signatures, key distribution, a claim registry, revocation) exceeds the value
   being protected. **Do not add a signature to these fields** without revisiting this section — a
   previous design round specified HMAC signing, seat counts, and a global claim table, and all of
   it was cut on purpose.

2. **The bundle records the owner; the host decides what that means.** The manifest carries a
   category, a name, and a timestamp. DatsMe resolves the name using data only DatsMe has. The
   factory never learns what a group is, and the host never learns how a bundle was built.

3. **Ownership changes through ONE function per repo, never by hand.** Mint, purchase and gift are
   the same operation with different arguments: *set these three fields together, now*. Each repo
   has exactly one writer (§2.1) and one reader (§2.2). Three fields written in four places by hand
   is three fields that will disagree within a month.

4. **Three fields, flat, at the manifest top level.** `owner_category` / `owner_name` /
   `owner_transferred_at`. Flat rather than nested, matching the existing top-level related group
   (`view_kind` / `native_facing` / `mirroring_policy`) — this manifest has no precedent for a
   nested block, and `animsFromManifest` on the host copies a fixed field list, so top-level
   additive keys are the shape it already tolerates.

5. **The name is a NAME — the slug a human can look up (Rev.12).** `sara.1`, not `u_7f3c1a92b4e5`.
   Three reasons, in order of weight:

   - **A portable record must be readable, or it is not a record.** The whole point of putting this
     in the artifact rather than only in the host's DB is that someone holding the file can see who
     it belongs to. An opaque id defeats that, and it defeats third-party verification too: a slug
     resolves at `GET /api/profiles/{name_slug}` (`api/routes/me_content.py:1072`) for anyone.
   - **Slugs are unique and, in practice, permanent.** `name_slug` is `unique=True`
     (`api/social_models.py:70`), minted once at signup, with no rename path in the host tree.
     Contrast `display_name` (`:76`), which has no unique constraint and must never resolve an
     owner — that is why Rev.11's "label" field is gone rather than kept alongside.
   - **The writer always has it for free.** The host stamps, and the host holds the `User`.

   **If a rename path is ever added to DatsMe, this decision must be revisited** — see §7.2, which
   is now the only place the mutable-name risk lives.

6. **The manifest is a portable *record*; the host's DB is the *authority*.** DatsMe already holds
   the real ownership facts — `PetOwnership` (`api/social_models.py:1636`), whose contract is
   exactly `(pet_id, user_id, source, created_at)`. The manifest fields are a **derived copy** that
   travels with the artifact. **Where the two disagree, the host wins.** Never write host logic that
   trusts the manifest over the database. §2.5's timestamp rule is this principle made concrete.

---

## 1. The fields

Top level of `manifest.json`:

```json
{
  "schema_version": "pet_manifest.v1",
  "fingerprint": "datspet",
  "owner_category": "individual",
  "owner_name": "sara.1",
  "owner_transferred_at": "2026-07-30T14:22:05Z",
  "columns": 8, "rows": 4,
  "animations": { … }
}
```

### 1.1 `owner_category`

| Value | `owner_name` holds | Who may bring it to life |
|---|---|---|
| `"factory"` | `"datspet"` | **nobody** — minted, not yet sold |
| `"individual"` | a DatsMe user slug (`sara.1`) | only that user |
| `"group"` | a group's normalized tag (`#black#zebra`) | the group's owner and its active members |
| `"public"` | `""` (empty) | anyone — the standard/free pets |

A closed vocabulary both repos agree on: an unknown category is **refused**, never treated as
`public`, so a future fifth value cannot fail open on a reader that predates it.

**Why `factory` and not `individual` for the unsold state.** A freshly built pet does need an owner
— blank fields would be a third state to special-case everywhere. But it cannot be `individual`
with the name `datspet`: `individual` means *"resolve this against `User.name_slug`"*, and
`datspet` is not a DatsMe user. The host would refuse the bundle for the misleading reason "user not
found" and log a phantom missing-user error for **every unsold pet in existence**. One extra value
in the vocabulary makes the state explicit, keeps the ladder honest, and costs one row in this table.

**Two namespaces, and the category says which.** A user slug and a group tag are different
namespaces, so a name that exists as both is not a coin flip — the category selects the lookup
(§4.1). This is the concrete win from having an explicit category at all.

### 1.2 `owner_name`

The DatsMe name that resolves: `User.name_slug` for `individual`, `Group.normalized_tag` for
`group`. `"datspet"` while factory-owned, `""` when the category is `public` (which needs no
subject). Never a display name, and never an internal id (§0.5).

### 1.3 `owner_transferred_at`

**When the current owner became the owner.** Written at mint, then rewritten at every ownership
change:

| Event | becomes |
|---|---|
| pet is built | build time (owner: `factory` / `datspet`) |
| a user buys it | the ownership row's `created_at` (owner: the buyer) |
| the owner gifts it | gift-accept time (owner: the recipient) |

So the field always answers the same question — *since when does the current owner hold it* — and is
never empty. A pet that has never been sold truthfully reports when the factory made it.

**At the purchase site it is read from `PetOwnership.created_at`, not from `now()`** — see §2.5.
That is what makes a re-import idempotent, and it is §0.6 made concrete: the manifest is a copy of
the DB, so it should be *derived from* the DB rather than independently invented.

UTC, ISO-8601, `Z` suffix — per the repo-wide datetime rule. On DatsPet, produce it with
`pet_ownership.utc_now_iso()` / `epoch_to_utc_iso()`; on DatsMe with the host's `utc_now()` helper.
Never a bare `.isoformat()`. Note this is the *wire* convention: DatsPet's `datspet.db` stores unix
epoch floats, so the stamp converts at the bundle boundary rather than leaking the storage format
into the artifact.

**Named `_at`, not `_date`**, because it carries a time and because `_at` is the timestamp
convention in both repos (`created_at`, `expires_at`, `claimed_at`).

### 1.4 What DatsPet's own copy says — a known asymmetry

After a purchase, the host's copy of the bundle says `individual` / `sara.1`. **DatsPet's stored
copy still says `factory`**, because DatsPet is never told the slug and never restamps.

That is accepted, and it is honest rather than merely convenient: DatsPet holds the **unsold master**
and DatsMe holds the **licensed copy**. §0.6 already says the host DB is the authority, and the
licensed artifact is the one the host re-emits (`build_bundle_zip`).

The visible consequence is small and worth naming: a user who downloads their pet from DatsPet's
own `/api/pets/{pet_id}/zip` gets a `factory`-stamped master. **If that ever matters**, the cheap
fix is to stamp on the host's post-checkout ack (`POST /partner/imported/{user_id}`,
`webui/datsme_integration.py:796`), which would need the ack payload to carry the slug and would
bring back a four-column restamp on DatsPet. Deliberately not specified here — do not build it
speculatively.

### 1.5 Why `manifest.json` and not a fourth zip member

The host rebuilds bundles from stored assets with `build_bundle_zip`
(`../datsme_me/api/apps/pets/pet_assets_service.py:349`), which writes **only** sprite +
`manifest.json` + `package.json`. A `license.json` member would be silently dropped the first time
the host re-exported the pet at `GET /api/pets/me/{pet_id}/bundle`. `manifest_json` by contrast is
stored verbatim in `pet_assets`, carried into the recipient's copy on a gift
(`pet_gift_service.py:412`), and re-emitted on every export. It is the only place a field survives
every path — which matters more under Rev.12 than before, because the host is now the writer and
the host's re-export is how an owner ever sees the field.

`package.json` was also rejected: it is **optional** on the host (`pet_assets_service.py` synthesizes
one when absent), so a field there is not guaranteed to round-trip.

### 1.6 `schema_version`

Leave at `pet_manifest.v1`. Nothing on the host reads it (`SPEC_BUNDLE_MOTION_CONTRACT` §2.4
verified this), so a bump buys only a version to cite in a bug report, and all four fields are
additive.

### 1.7 `fingerprint` — reserved, stamped once, DatsPet only

```json
"fingerprint": "datspet"
```

A mark identifying what issued the bundle. **Nothing reads it today.** It is reserved for a future
use, and is stamped now because bundles are immutable artifacts: a pet minted before the field
exists can never carry it, and back-filling means regenerating pets at GPU cost. Stamping an inert
field costs one string per bundle; not stamping it costs every pet built before the day it matters.

**It is NOT an owner field, and the distinction is load-bearing:**

- **Written once, at mint, by DatsPet only.** The owner fields change at every transfer *and are
  written by the host*; the fingerprint never changes and the host never writes it. Different
  cadence, different writer, different repo — so `transfer_pet_ownership` must not touch it, and
  every host-side stamp must preserve it.
- **The value is a named constant** (`BUNDLE_FINGERPRINT = "datspet"`), not an inline literal — and
  a **separate** constant from the `factory` state's `owner_name`, even though both are the string
  `"datspet"` today. They mean different things, and the whole point of a placeholder is that its
  value will change; the factory owner name must not change with it.

**Zero host work, ever.** The field survives every path for free: `manifest_json` is stored verbatim
in `pet_assets`, `animsFromManifest` copies a fixed field list and ignores unknown keys, and
`build_bundle_zip` re-emits the manifest whole. It needs no reader, no validation, no migration.

**Do not delete this field for being unused.** That is the whole reason this section exists: it will
read as dead weight to a cleanup pass, and it is not. When a consumer is designed, this section is
where the reader gets specified.

---

## 2. The transfer primitive and its call sites

### 2.1 The writer — two levels, and only the inner one is shared

```python
set_pet_ownership(manifest_json, *, category, name, at) -> manifest_json   # THE writer
transfer_pet_ownership(zip_bytes, *, category, name, at) -> (zip_bytes, manifest_json)
```

**`set_pet_ownership` is the ownership primitive**, and it is `str → str`. It sets the three fields
on a manifest and returns the new text. **It is the only code in either repo that writes an
`owner_*` field.** Mint, purchase and gift are three calls with different arguments.

**The zip wrapper is DatsPet's alone.** The host stores a pet's *parts*, not its bundle —
`write_assets(…, manifest_json: str, …)` (`pet_assets_service.py:105`) — and rebuilds archives on
demand with `build_bundle_zip`. So neither host stamp site ever opens a zip; each is one line:

```python
parsed["manifest_json"] = set_pet_ownership(
    parsed["manifest_json"], category=INDIVIDUAL, name=user_slug, at=ownership_created_at)
```

DatsPet needs the wrapper because its stored artifact *is* the zip (`pets.bundle_zip`), and because
`bundle_sha256` is derived from those bytes. **This split is what §2.3a's duplication actually
covers**: the ~20 shared lines are the manifest-level writer and reader, not the zip plumbing. The
host copies less than half of this file.

It validates its own arguments: category in the closed set, `name` non-empty unless the category is
`public`, `at` a UTC ISO string ending in `Z`. A bad call fails loudly at the call site rather than
writing a bundle the other side will refuse — a bad stamp is otherwise silent until ingest, where it
surfaces as "licensed to someone else" on a pet the buyer just paid for.

**It is a no-op when nothing changed.** If the manifest already carries this `(category, name)`,
**the input is returned unchanged — the same object**, so a caller can test
`result is manifest_json` to know nothing was written (and DatsPet's wrapper skips re-compressing a
3.5 MB archive). Both host stamp sites re-run for one pet — a re-checkout, a re-gift — and without
this rule "since when do you own this" would drift to "when you last clicked buy". It keys on
`(category, name)` only: a re-run with a later `at` for the same owner is precisely the case being
suppressed.

**It patches the manifest; it never rebuilds one.** Load the JSON, set the three owner keys, dump it
back. Every other key — `fingerprint`, the animations, the geometry, the view blocks, anything a
future spec adds — passes through untouched. Rebuilding a manifest from a known field list is how
`fingerprint` would silently vanish on the first gift, and how the next additive field would too.

### 2.2 The reader

```python
read_pet_ownership(manifest_json) -> (category, name, at)
```

Used by the host's ingest ladder (§4), by any "owned by" display, and by both repos' tests. Missing
fields come back as `(None, None, None)` — the caller decides what that means (the host refuses; a
display shows "unknown"), so absence is never silently coerced into a category. It must not raise on
an unparseable manifest: it is a display and gating helper, not a validator.

### 2.3 Where the code lives

**DatsPet: `webui/pet_ownership.py`** — both functions plus the constants (`BUNDLE_FINGERPRINT`, the
`factory` name, the category vocabulary). A new file rather than an addition to an existing one
because all three candidates are the wrong owner: `db.py` is the byteless record view, `app.py` is
the HTTP surface, and `datsme_integration.py` is the DPP adapter. All three *call* it; none should
*be* it. **Built (Phase 1).**

**DatsMe: `api/apps/pets/pet_ownership.py`**, beside `pet_assets_service.py`, which is what both
stamp sites and the ladder call.

### 2.3a Two implementations, deliberately

The same ~25 lines exist in both repos. That duplication is intentional and must not be "fixed" by
extracting a shared module.

**Not in the partner SDK.** `datsme_partner_sdk` is a real shared dependency (DatsPet installs it
editable from `../datsme_me/api/sdk`), so it is the tempting home — but it is the *generic DPP
protocol* SDK, serving every partner. Pet-bundle internals are one app's content model, and putting
them there would make every future partner's SDK carry DatsPet's zip layout. The SDK stays protocol;
the bundle stays app.

What keeps the two copies honest is **one owned fixture plus a checksum**, not a vague "shared test
vector" — two repos cannot share a file, and two independently-maintained copies of a fixture drift
exactly like the code they were meant to police.

- **DatsPet owns it**: `webui/tests/fixtures/owner_fields.json` — the case table (every category, the
  empty-name public case, a `fingerprint`, and a deliberately unknown nested key), plus the rejected
  cases.
- **DatsMe vendors it** verbatim to `api/tests/fixtures/owner_fields.json`, and its test asserts the
  file's **sha256 matches the value pinned in that test**. A drifted copy fails loudly with a message
  naming the owning repo, instead of silently testing something else.
- Both sides then run `read(write(x)) == x` over the table.

The direction matters: DatsPet mints bundles, so it owns the wire cases. If the host needs a new
case it lands in DatsPet's fixture and is re-vendored — the same direction the bundle itself flows.

### 2.4 DatsPet's call sites — TWO, both at mint

DatsPet never sells and never gifts, so it never writes an owner. It writes the **unsold state**, and
that is all.

Both sites hold the bytes before any row exists, and `insert_pet` derives `bundle_sha256` /
`size_bytes` from whatever bytes it is handed (`webui/db.py:216`). So the stamp goes **upstream of
the insert** and the derived columns are correct by construction.

**Mint — `_finalize_pet_from_zip` (`webui/app.py:588`).** Already unpacks the bundle via
`_unpack_bundle` (`:563`), shared by fresh generation and pool reattach, and is the last point before
the row is stored. Stamps `factory` / `datspet` / build time, plus `fingerprint`.

**Curated samples — `adopt_sample` (`webui/app.py:1476`).** Same shape, same position: it unpacks a
stored sample bundle and calls `insert_pet` directly. Stamps `public` / `""` / now, plus
`fingerprint`.

**Not in `pack_datsme_bundle`.** That runs on pool GPU nodes
(`pool_handler/pet_factory_handler.py`), which must never hold identity or partner state. Rendering
and ownership change for different reasons and belong in different places. A welcome consequence:
`pet_factory/tests/test_pack_bundle_layout.py` — which pins the packer's exact manifest field set —
needs no change, because the packer's output is unchanged.

**There is no restamp, and no `db.restamp_bundle`.** Rev.11 needed one because DatsPet stamped the
buyer onto an already-stored row. Under Rev.12 nothing on DatsPet ever rewrites a stored bundle, so
the four-column setter and the whole "stamp before the digest is published" ordering trap are gone.
If a future change reintroduces a restamp, it must move `bundle_zip`, `manifest_json`,
`bundle_sha256` and `size_bytes` in one UPDATE — those columns are documented as derived-never-passed
at `webui/db.py:220`, and a stale digest surfaces as the host refusing the fetch, i.e. in
house-adopt rather than in the code that changed.

### 2.5 DatsMe's call sites — TWO, one per kind of transfer

**Purchase — `handle_target_user_pet` (`../datsme_me/api/apps/dpp/pet_writeback.py:207`).** The
incoming bundle is `factory`; buying it is what assigns an owner. Everything needed is already in
scope: `validate_uploaded_bundle` at `:280` has parsed the manifest, `user_slug = user.name_slug` is
captured at `:293` (deliberately, before the commit expires ORM attributes), and
`write_assets(manifest_json=…)` is in the same function. One line between them — no zip work,
because the host stores parts (§2.1):

```python
parsed["manifest_json"] = set_pet_ownership(
    parsed["manifest_json"], category=INDIVIDUAL, name=user_slug,
    at=ownership_created_at)                                        # then write_assets
```

**Take `at` from the ownership row, not from `now()`.** Read `PetOwnership` for this `pet_id` before
stamping: present → reuse its `created_at`; absent (a first purchase) → `utc_now()`. This is what
makes a **re-checkout idempotent** — the host's import is already re-runnable (a re-checkout quotes
0), and a `now()` stamp would silently relabel the transfer date on every retry. It is also §0.6
applied: the manifest is a copy of the DB, so it derives its timestamp from the DB.

The behavior this relies on is already there: `_write_ownership`
(`../datsme_me/api/apps/pets/pet_routes.py:86`) updates only `user_id` and `source` on an existing
row and **never touches `created_at`**. Note the ordering — it runs *after* `write_assets`, so on a
first purchase the row does not exist yet when the manifest is stamped; both values are minted at
that import and may differ by microseconds, which is immaterial for a display copy.

**Gift — `accept_offer` (`../datsme_me/api/apps/pets/pet_gift_service.py:445`).** It already copies
`manifest_json` into the recipient's row (`:412`) inside the one commit that re-points
`PetOwnership`. The stamp is one call in code already writing that field, in the transaction that
already makes the transfer atomic — which is exactly why ownership can never half-move. Stamp
`individual` / `recipient.name_slug` / **gift-accept time**.

**The two sites derive `at` differently, and that asymmetry is deliberate — do not "unify" it.**
The gift path has its own `PetOwnership` upsert (`pet_gift_service.py:523-531`, deliberately not
`_write_ownership`, "which commits on its own"), and it likewise preserves `created_at` on an
existing row. So a gifted pet's ownership row still carries the *original purchase* date. Deriving
the gift's `at` from it would report the wrong date for the new owner. The purchase site derives
from the DB because a re-checkout is a genuine re-run of the same transfer; a gift is a new transfer
and takes the wall clock.

**A group pet gifted to a member becomes an individual pet.** That is the honest reading of a
transfer: the recipient now holds it personally. Whether a group pet should be giftable *out* of its
group is a policy question this spec does not decide; today's transfer path has no such restriction
and this spec adds none.

**`_export_item` gains NO owner condition — the trap, preserved.** `webui/datsme_integration.py:763`
keeps exactly its existing honesty gates (no digest, no `pose_count`, no block).

> **Correction, recorded — the one lesson worth carrying forward.** An earlier revision specified
> suppressing the `transfer` block for a `factory` pet, justified by a retry drain that would
> "complete the Accept and offer it next time". That was false twice over: the drain belonged to the
> push path, which no longer exists, and a pull-channel pet never had a queued writeback to drain.
> **Under Rev.12 the filter would be even more destructive: every pet DatsPet exports is `factory`
> by design, so it would suppress 100% of the pull channel** — a logged refusal turned into a total
> silent outage. The error was treating "unsold" as "broken". Unsold is the normal state of a pet
> that is for sale.

---

## 3. The group check (Phase 3 — DatsMe builds this)

**Only needed when group licensing becomes a product**, and note where it now lives: under Rev.12
the group choice is made **on the host's checkout page** (§5), so the host resolves the tag with a
local query. There is no partner-facing endpoint, no new authorization category, no HMAC-signed
partner call, and no DatsPet client.

That is a direct saving from moving the stamp to the host. Rev.11 needed
`GET /api/partner/owner-check` — the first partner→host call with no user context, a new
authorization shape to get right — purely because DatsPet was choosing the owner. It is deleted.

What remains is host-local:

- Resolve `Group.normalized_tag == normalize(typed tag)`.
- Show the group's display name and member count for confirmation.
- **Do not check membership at choose time.** §4.1's ladder re-checks it at every ingest door, and
  that check is the authoritative one.

---

## 4. What DatsMe checks at ingest (Phase 2)

One resolver reading through `read_pet_ownership` (§2.2), called at both doors — but the two doors
ask **different questions**, and Rev.12 makes that explicit rather than pretending one ladder serves
both.

### 4.1 The access ladder, keyed on `owner_category`

*Question: may this user bring this bundle to life?*

| `owner_category` | Passes when |
|---|---|
| `"public"` | always — no lookup, `owner_name` ignored |
| `"individual"` | `user.name_slug == owner_name` |
| `"group"` | `Group.normalized_tag == owner_name` resolves (`api/social_models.py:978`, `unique=True`), **and** (`Group.owner_id == user.id` **or** an active `Relationship(user_id=user.id, entity_type="group", entity_id=group.id, relationship_type="member", status="active")`) |
| `"factory"` | **never** — an unsold pet is nobody's |
| unknown value, missing fields, or a name that does not resolve | never |

`ix_relationship_lookup` (`api/social_models.py:369`) already indexes exactly
`(entity_type, entity_id, relationship_type, status)`, so the membership check is one indexed query.
No new membership concept and no new index.

Resolution is direct — the declared category selects the lookup, so a name that exists as both a
user slug and a group tag is unambiguous. Use `resolve_user_from_slug` (`api/user_db.py:341`), the
helper `GET /api/profiles/{name_slug}` already uses.

`owner_transferred_at` is **not** part of the gate — it is provenance, recorded and displayed, never
a condition. Nothing expires.

### 4.2 The two doors ask different questions

**1. The DPP checkout — `handle_target_user_pet` (`pet_writeback.py:207`). This is a TRANSFER.**

A `factory` bundle here is the **normal case**: an unsold pet is being sold. Running §4.1's ladder
unchanged would refuse every purchase, because `factory` never passes it.

So the import door runs a transfer step *first*:

| Incoming | Action |
|---|---|
| `factory` | **admit and stamp the buyer** (§2.5). The sale is what assigns the owner |
| `individual` == the importing user | admit; re-stamp is a no-op (§2.1) — this is the re-checkout path |
| `individual` != the importing user | **refuse** — this pet is licensed to someone else |
| `group`, importing user is owner/member | admit; do not re-stamp — it stays the group's |
| `group`, otherwise | refuse |
| `public` | admit; **do not stamp** — public stays public |
| missing / unknown | refuse (§4.3) |

This is also **the last moment before credits are charged**: a name that resolves to nothing here
means a pet nobody can ever adopt, including the buyer. Fail the import with the real reason rather
than charging for an unusable pet.

**2. `POST /api/pets/me/upload` (`pet_routes.py:277`). This is an ACCESS CHECK, and it is the door
that matters.** It accepts any zip from any user by design ("Does NOT consult the platform
catalog"), which is where the "buy one pet, hand the zip to 50 friends" hole lives. Run §4.1's
ladder as written — including refusing `factory`, which here means "you got this bundle without
buying it".

On deny return **409 with the real reason** ("this pet is licensed to someone else") — a deliberate
divergence from `_enforce_visibility`'s never-403 rule (`pet_routes.py:457`), which exists to avoid
disclosing that a private pet *exists*. Here the uploader already holds the bytes, so nothing is
disclosed by explaining the refusal, and a silent 404 would be a support ticket.

The shared half belongs beside `validate_uploaded_bundle` (`pet_assets_service.py:226`), which both
doors already call and which the file documents as kept "in lockstep" — one function, two callers,
no drift.

### 4.3 Bundles with no owner fields

**Refuse at the upload door.** Defaulting absent-to-public would make the fields opt-out, and then
any hand-made zip walks in and the mechanism is decorative. Pets already adopted are never
re-validated, so nothing in a user's house breaks; only a fresh upload hits this.

**This is the whole reason for §6.16's ordering gate.** Ship the ladder warn-only until DatsPet's
mint stamp is live in the same environment.

---

## 5. The user-facing surface

### 5.1 DatsPet has no ownership UI, and never needs one

DatsPet stamps `factory` at mint and nothing else, so there is nothing for a buyer to choose, type,
or confirm on the partner side. **No component, no chooser, no `designFlow.ts` change, no api.ts
signature change, in any phase.** This is the clearest single consequence of moving the stamp to the
host, and it should not be undone quietly.

Optionally, surface it read-only: the pet detail view can render "Owned by {owner_name} since
{owner_transferred_at}" through `read_pet_ownership` — noting §1.4, DatsPet's own copy reads
`factory` even after a sale, so the honest local rendering is "unsold" rather than a name.

### 5.2 The group choice lives on the host's checkout page (Phase 3)

Choosing "adopt this to my group" belongs where the transfer and the money are. On the host's import
page: category defaults to *me* (nothing to type), with an option to switch to a group and type a
tag, resolved locally (§3) and confirmed before purchase. A tag that resolves to nothing is a
warning, not a block — the buyer may proceed, and their pet will not be adoptable. That is their
call and their mistake to make (§0.1).

### 5.3 No DatsMe identity — `factory` already covers it

A pet has an owner iff someone bought it. Everything before that is `factory`, and there is no
second state to invent:

| State | `owner_category` | Behavior |
|---|---|---|
| standalone deployment (no host secret) | `factory` | renders locally; `export_pets` is keyed on the DatsMe id, so it is not exportable at all |
| integrated, not signed in (`anon:<uuid4>`) | `factory` | same — not exportable, nothing to suppress |
| signed in, not yet purchased | `factory` | exportable and offered; the sale is what stamps it |
| purchased | `individual` (or `group`) | adoptable per §4.1 |
| gifted onward | `individual` | re-stamped to the recipient (§2.5) |

Anonymous use stays fully supported: base-tier pet making with no login keeps working, and
`external_user_id IS NULL` remains the standalone case. Those pets need no answer invented for them
— an unsold pet is exactly what `factory` means.

---

## 6. Guard tests

**Shared (both repos, same committed fixture)**
1. `read_pet_ownership(transfer_pet_ownership(z, …))` returns exactly what was written, over every
   case in `owner_fields.json` — plus, on the DatsMe side, the vendored fixture's sha256 matches the
   value pinned in the test, failing with a message that names DatsPet as the owning repo (§2.3a).
2. A transfer **preserves every non-owner key**, `fingerprint` included, plus a deliberately unknown
   nested key the fixture carries for exactly this purpose. This is the test that stops §1.7's field
   being lost on the first sale or gift.
3. A stamp no reader would accept is refused at the call site: unknown category, empty name for a
   non-`public` category, a name on `public`, a non-`Z` timestamp.
4. A second identical stamp is a no-op — same bytes, and `owner_transferred_at` unchanged (§2.1).

**DatsPet (Phase 1)**
5. A freshly built pet's bundle carries `factory` / `datspet` / a parseable UTC `Z` timestamp, and
   `fingerprint == BUNDLE_FINGERPRINT`. Its stored `bundle_sha256` matches the **stamped** bytes —
   proof the stamp ran upstream of `insert_pet` (§2.4).
6. `adopt_sample` stamps `public` with an empty name, same digest assertion.
7. Non-manifest zip members survive a stamp **byte for byte** and keep their names —
   `_unpack_bundle` matches members by name, so a renamed member is an unrenderable pet.
8. **`_export_item` still offers a `factory` pet.** The forbidden filter (§2.5), pinned. Under
   Rev.12 this covers every exportable pet, not an edge case.
9. An anonymous build mints `factory` and reaches no user's `export_pets`.
10. A standalone build (`DATSME_HMAC_SECRET` unset) mints `factory` and works end to end.
11. `test_pack_bundle_layout.py` is unchanged and still passes — proof the packer's contract did not
    move.

**DatsMe (Phase 2)**
12. **The purchase stamp.** A `factory` bundle imported by `sara.1` is stored as `individual` /
    `sara.1`, and `build_bundle_zip` re-emits those fields — the property that makes the record
    portable at all.
13. **A re-checkout does not relabel the transfer date.** Import the same pet twice; the second
    import leaves `owner_transferred_at` at the first `PetOwnership.created_at` (§2.5).
14. The access ladder: public / self / group-owner / group-member pass; non-member, wrong user,
    `factory`, unknown category, missing fields and an unresolvable name are all refused.
15. **The two doors differ.** A `factory` bundle is **admitted and stamped** at the checkout door and
    **refused** at the upload door (§4.2). An `individual` bundle belonging to someone else is
    refused at both. A bundle with no owner fields is refused at the upload door (§4.3).
15b. `accept_offer` rewrites all three owner fields to the recipient with a fresh timestamp, leaves
    `fingerprint` intact, and the recipient can re-upload their own exported bundle afterwards.

**Ordering (deploy gate)**
16. With the host's ladder enforcing and DatsPet **not** yet stamping, every ingest is refused — so
    the ladder ships **warn-only** (log, admit) until DatsPet's mint stamp is live in that
    environment, and the switch to enforcing is its own deploy step. The reverse order needs no gate:
    a stamp no reader consults changes nothing.

---

## 7. Known limits (all accepted)

1. **The fields are plaintext.** Unzip, edit, re-zip. Accepted per §0.1. This makes them a *record*,
   not proof in the cryptographic sense — the host's database is the authority (§0.6), and these
   fields are the copy that travels with the file.
2. **Slugs are permanent only because nothing renames them.** `name_slug` is `unique=True` and
   minted once at signup, and **no rename path exists in the host tree today** — that verified fact
   is what §0.5 rests on. If a rename feature is ever added, an un-imported bundle stamped with the
   old slug is stranded, and this decision must be revisited. The mitigation, if it comes to that,
   is a slug-history table on the host, not a change to the bundle format.
3. **Nobody verifies the buyer belongs to the group they typed.** They paid; the group's members
   benefit. If this ever needs closing, the cheap version is a host-side `Group.owner_id ==
   importing user` check at the checkout door — one line, deliberately not specified here.
4. **Group licensing is legitimate mass distribution.** One purchase can serve a group up to
   `max_group_members` (default 500, `api/social_db.py:636`). That is the feature working as asked,
   not a defect. Pricing it is a product decision outside this spec.
5. **One timestamp, not a chain.** `owner_transferred_at` records the *current* owner's start,
   overwriting the previous value — the bundle carries no transfer history. If a provenance trail is
   ever wanted, the natural form is an append-only list of `{category, name, at}` entries (the
   repo's append-only-ledger rule), and the single field remains its last element. Out of scope.
6. **The sprite sheet is always extractable** from any rendered pet. What these fields protect is a
   pet *living on DatsMe*, which is where the value is.
7. **DatsPet's own copy stays `factory` after a sale** — §1.4. Accepted; the cheap fix is named
   there and deliberately unbuilt.
8. **The checkout door's enforcement value is modest.** `/partner/export/{user_id}` is exact-match on
   the DatsMe id and the host imports into that user's house, so identity is already bound there.
   The real value of the ladder is concentrated in the **upload door** (§4.2 door 2) and the **gift
   path**. Stated plainly so the ladder is not oversold.

---

## 8. Consistency checks (repo-wide rules)

- **Engine vs. content** — no runtime code branches on *who* the owner is. One function writes the
  fields per repo, one reads them, and the host resolves them through a single ladder keyed on
  category. Neither side branches on the owner's identity anywhere else.
- **Things that change for the same reason live together** — every ownership change now lives on the
  host, because that is where every ownership change *happens*. Rev.11 split one concept across two
  repos and paid for it with an identity-plumbing problem that vanished when the boundary moved.
- **Intentional duplication** — the two `transfer_pet_ownership` implementations are a deliberate
  repo boundary, not a missed abstraction (§2.3a). Pinned by one owned fixture plus a vendored-copy
  checksum, not shared code.
- **No inline literals** — `BUNDLE_FINGERPRINT`, the `factory` name, and the category vocabulary are
  named constants in one discoverable place per repo, never strings typed at a call site (§1.7).
- **Additive fields survive by patching, not rebuilding** — the transfer primitive preserves every
  key it does not own, which is what makes `fingerprint` and every future field safe (§2.1).
- **UTC everywhere** — `owner_transferred_at` is ISO-8601 with a `Z` suffix produced by each repo's
  helper (§1.3), and the stores keep their own formats.
- **GPU-less posture** — nothing here touches `pet_factory`; DatsPet's stamp is web-tier only, and
  `pet_ownership.py` imports `json`, `zipfile` and `datetime` and nothing else.
- **Standalone-first** — with no host secret DatsPet still mints, stamps and renders pets (§5.3).
- **Specs cited from code** — the stamp sites and the ladder carry `SPEC_PET_OWNER_FIELD §2.4` /
  `§2.5` / `§4.1` references, per the repo convention.

---

## 9. Phasing

| Phase | Scope | Repo | Depends on | State |
|---|---|---|---|---|
| **1** | `pet_ownership.py`, `fingerprint`, the two mint stamps (§2.4), the owned fixture, tests 1–11 | **DatsPet only** | **nothing** | **BUILT** 2026-07-30 |
| **2** | The two transfer stamps (§2.5), the access ladder + the two doors (§4), tests 12–15b | DatsMe | — | **BUILT** 2026-07-30 (`325b6909`) |
| **2b** | Flip `PET_OWNER_ENFORCEMENT=observe` → `enforce`, staging then prod | DatsMe (config) | Phase 1 **deployed** in that environment (§6.16) | **not done** — see §9.2 |
| **3** | The group chooser on the host's checkout page (§5.2) | DatsMe | Phase 2; **only if group licensing becomes a product** | not started, ~1 day |

### 9.1 What Phase 1 shipped, for whoever picks up Phase 2

- **`webui/pet_ownership.py`** — `transfer_pet_ownership` (the one owner writer),
  `stamp_bundle_fingerprint` (separate writer, different cadence, DatsPet only — §1.7),
  `read_pet_ownership`, `utc_now_iso` / `epoch_to_utc_iso`, and the category vocabulary as named
  constants. This is the file DatsMe copies (§2.3a) — the host's version needs the same primitive
  and the vendored fixture.
- **`webui/app.py`** — the two mint stamps, both upstream of `insert_pet`. Nothing else.
- **`webui/tests/fixtures/owner_fields.json`** — the owned case table. **DatsMe vendors this
  verbatim and pins its sha256**; it already carries the `individual` and `group` cases the host
  will write, so Phase 2 does not need to add wire cases.
- **`webui/tests/test_pet_ownership.py`** — 20 tests. Test 2 (preserve every non-owner key) and
  test 4 (the no-op rule) are the two the host must also pass; the rest are DatsPet's mint sites.
- **`webui/tests/conftest.py`** — `make_pet` now builds a real zip via a shared `make_bundle_zip`,
  and `test_pull_export._bundle` delegates to it. It previously inserted the stub
  `b"PK\x03\x04zip"`; a fixture that lies about its shape only postpones the failure.

**Verified beyond the unit tests**, on a real 3.58 MB catalog bundle: the full lifecycle —
mint (`factory`/`datspet`) → purchase (`individual`/`sara.1`) → gift (`individual`/`wu.1`) — with
every non-manifest member byte-identical, every pre-existing manifest key preserved, and
`fingerprint` surviving all three stamps.

**What Rev.11 built and Rev.12 removed**, so it is not reinstated by accident: `owner_ref`, the
`keep` stamp (`_stamp_bundle_owner`), and `db.restamp_bundle`. Each is dead under this design, and
the reasons are in §2.4 and §0.5. Test
`test_keeping_a_pet_does_not_touch_the_bundle` pins `keep`'s return to being a pure draft-flag
clear, so the stamp cannot creep back in unnoticed.

### 9.1a What Phase 2 shipped (DatsMe `325b6909`)

- **`api/apps/pets/pet_ownership.py`** — the vendored primitive (`set_pet_ownership`,
  `read_pet_ownership`) plus the ladder (`check_bundle_access`), the checkout-door variant
  (`enforce_transfer_access`), `buying_assigns_owner`, and the rollout gate
  (`enforcement_mode`). Manifest-level throughout — it never opens a zip.
- **`pet_writeback.handle_target_user_pet`** — the checkout gate + the purchase stamp, with
  `_ownership_started_at` deriving `at` from `PetOwnership.created_at`.
- **`pet_gift_service.accept_offer`** — the gift stamp, using accept time, with `_name_slug`.
- **`pet_routes.upload_my_pet`** — the access gate, placed **before** `_charge_adoption`.
- **`api/tests/fixtures/owner_fields.json`** — vendored, sha256 pinned in `test_pet_ownership.py`.
- **`api/tests/test_pet_ownership.py`** — 38 in-process checks, registered in `test_all.py`.

### 9.2 The remaining step is a config flip, not code

`PET_OWNER_ENFORCEMENT` defaults to `observe`: the ladder logs a self-identifying refusal and
**admits**. That is the host repo's own rule (`CLAUDE.md`, *"gates ship observe-first with
self-identifying failure logs"*) and it is what makes §6.16 safe by construction rather than by
remembering.

The order, and the reason for each step:

1. **Deploy DatsPet (Phase 1) to staging.** Until it runs, no bundle carries the fields.
2. **Deploy DatsMe (Phase 2) to staging.** Still observing — it cannot refuse anything.
3. **Build a pet and adopt it.** Confirm the imported manifest reads `individual` / the buyer's
   slug, and that `owner_transferred_at` does not move on a re-checkout.
4. **Read the refusal log.** `grep pet_owner_refused` — every line is an honest refusal class or a
   bug, and this is the measurement the observe phase exists to produce. Expect lines for any pet
   minted *before* step 1.
5. **Flip staging to `enforce`.** Re-run the adopt and an upload.
6. **Then production, staging-first as always.**

Do not flip enforcement in an environment whose DatsPet has not shipped Phase 1: §4.3 refuses a
bundle with no owner fields, so every pet minted before the stamp would be refused at the upload
door. That is exactly the failure the observe phase is designed to surface as a log line instead of
an outage.

### 9.3 Why Phase 1 is worth shipping alone

Bundles are immutable artifacts: every pet minted before the stamp exists can never carry
`fingerprint` or a `factory` mark, and back-filling means regenerating at GPU cost. That is §1.7's
argument applied to the whole feature — stamping early is cheap, stamping late is impossible. It is
inert until Phase 2 gives it a reader, which is exactly what makes it safe to ship first.

**Phase 2 is where the value is.** Phase 1 alone is provenance; the leak at
`POST /api/pets/me/upload` stays open until the ladder ships.
