# SPEC — The bundle owner fields (one pet, one owner)

**Status:** READY TO IMPLEMENT — Rev.9 (2026-07-30). Adds three `owner_*` fields to
`manifest.json` recording who may bring a pet to life on DatsMe and since when, a reserved
`fingerprint` mark, **one transfer primitive** that is the only thing that ever writes the owner
fields, and a partner read endpoint so the buyer can confirm the name before paying. Grounded
against the working tree of both repos.

> **Rev.10 (2026-07-30) — the login architecture changed under this spec; re-pointed, not redesigned.**
> DatsPet's login is now `../../datsme_me/docs/SPEC_DPP_FEDERATED_LOGIN.md` (federated redirect);
> `SPEC_DPP_PARTNER_HOSTED_LOGIN.md` and `SPEC_DATSPET_OWN_LOGIN.md` (password forwarding) were
> **declined**. Four consequences, all in this spec's favour except the last:
>
> 1. **§2.6's two identity paths collapse into one.** There is no `password-verify` returning
>    `name_slug`, because there is no password endpoint. Every signed-in DatsMe user now arrives
>    through the launch exchange, so the `slg` claim is the **only** source of the buyer's slug —
>    one path to build and test instead of two.
> 2. **`slg` is now a closed decision, not a hope.** `SPEC_DPP_FEDERATED_LOGIN` §14.4 rules it in
>    for step 1 (§6 there). Rev.6 recorded it as "specified, none of it built"; it is still unbuilt,
>    but it is no longer at risk of being dropped with a feature.
> 3. **§2.6's "don't reconstruct the slug from the typed username" gets *stronger*.** DatsPet never
>    sees a typed DatsMe username at all now. And when partner-local accounts arrive
>    (`SPEC_DPP_FEDERATED_LOGIN` §11 step 2), the typed username is a **local** identifier that is
>    explicitly *not* a `name_slug` — "a local user named `sara.1` is not the DatsMe user `sara.1`"
>    (that spec's §2). Reconstruction would not merely be imprecise; it would resolve to the wrong
>    person.
> 4. **§3.3 loses its precedent — OPEN ITEM.** §3's owner-check was justified as the *second*
>    partner→host call authorized by partner signature with no launch token, after
>    `verify_credential()`. That endpoint does not exist now, and no shipped call has that shape:
>    `fetch_partner_profile` requires `X-DatsMe-Launch-Token`
>    (`api/sdk/datsme_partner_sdk/profile_client.py:44-68`) and the writeback carries one too. **The
>    design is unchanged and still sound — §3.3's argument stands on its own merits (there is no
>    `user_id` to key a grant row on) — but it is now the FIRST call of its kind and must establish
>    the pattern rather than inherit it.** That makes §3 a host change; see §3.3.
>
> **Rev.9** — fixes a **blocking** defect Rev.7 introduced and Rev.8 kept: §2.4c's
> "omit the `transfer` block for a `factory` pet" would have suppressed it for *every* pet house
> adopt exists to move (its target state, house-adopt §3.3, is exactly that), and its self-heal
> justification cited the push path's retry drain, which never touches a pull-channel pet. The pull
> channel's stamp site is **claim** (`webui/app.py:1683`), not checkout — claim already precedes
> exportability, so §2.4b is satisfied for free. Adds §2.4d's invariant (**the stamp mirrors
> `external_user_id`**), which makes this and §5.2 one rule; corrects §5.0's wire (the house calls
> `claimPets`, not `acceptPetToDatsme`); drops stale launch-token text from §5.1; re-verifies
> citations.
>
> **Rev.8 — IMPLEMENTATION READY.** Closes the last five gaps: §3.1's owner-check drops
> launch-token auth and `viewer_relation` for a partner-signed existence check (the design-time
> call has no live token under `SPEC_DATSPET_OWN_LOGIN` §0.3); §2.3 names the module homes; §2.3's
> "shared test vector" becomes one owned fixture plus a vendored-copy checksum; §5.0 mounts the
> chooser on the Accept surface with `designFlow.ts` untouched; §5.2 resolves anonymous use —
> `factory` already meant "unsold", so no new state.
>
> **Rev.7** — four defects, all from the spec modelling the DPP **push** path and being blind to
> the **pull** path (`SPEC_DATSPET_HOUSE_ADOPT`, live on staging): the persisted
> `bundle_sha256`/`size_bytes` columns must move with the bytes (§2.4a); the pull channel shares
> the ingest so a `factory` pet reaches §4.1's ladder (§2.4c); Rev.6's "landed" overstated a DRAFT
> dependency (§2.6); and the header contradicted §4.3 on ship order (now stated as one constraint).
>
> **Rev.6** — §2.6's identity dependency is **specified** host-side: the `slg` launch claim,
> `name_slug` on `password-verify`'s 200, and a `name_slug` column in DatsPet's session store
> (`SPEC_DPP_PARTNER_HOSTED_LOGIN` §3/§3.2, `SPEC_DATSPET_OWN_LOGIN` §3.2). None of it is built yet
> — see §2.6. Also corrects a wrong premise in Rev.5: sign-in is slug-only, not email-or-slug.
>
> **Rev.5** — adds §2.6, where the buyer's `name_slug` comes from. The launch token already
> carries a name (`nm` = `display_name`, the one the nav greets you with) but **not** the slug, and
> only the slug resolves.
>
> **Rev.4** — adds `fingerprint` (§1.6): a stamped-once issuer mark with **no consumer yet**,
> reserved for a future use. It is documented here rather than left as a bare string precisely so
> that a later cleanup pass does not delete it as dead weight.
>
> **Rev.3** — the three owner fields are written by **exactly one function per repo**
> (`transfer_pet_ownership`, §2.1), called at every ownership change: mint, purchase, gift. Adds
> the **`factory` category** for the minted-but-unsold state — a pet has to be *somebody's*
> before it is sold, and it cannot be `individual` (§1.1). Adds the second DatsPet stamp site at
> Accept, with the digest-ordering constraint that makes it non-obvious (§2.4).
>
> **Rev.2** — the single `owner` string became three fields. The explicit category deletes
> Rev.1's user-vs-group lookup guessing (§3.2).

**Repos touched:** `datsme-pet-factory_wu` (stamp + verify + UI) and `datsme_me` (one launch
claim, one read endpoint, the ingest check, the transfer re-stamp).

**Ship order — one real constraint.** DatsPet's stamp goes first, or the host's ladder ships
**warn-only** until it has. §4.3 refuses a bundle with no owner fields, so a host that enforces
before DatsPet stamps would refuse every pet in flight. The reverse order is safe: stamped fields
no reader consults are inert. Pinned by §6.12.

**Counterpart surfaces already in place:** `api/apps/dpp/profile_routes.py` (the partner-read
pattern this copies), `api/social_models.py:338` `Relationship` (membership), `:964` `Group`
(tag + owner).

---

## 0. The core decisions (read this first)

1. **This is deliberately light protection, not DRM.** Anyone who unzips a bundle can edit
   these fields. That is an accepted outcome, not a gap to close: a pet costs $0.50–$1, and the
   cost of real enforcement (signatures, key distribution, a claim registry, revocation)
   exceeds the value being protected. **Do not add a signature to these fields** without
   revisiting this section — a previous design round specified HMAC signing, seat counts, and a
   global claim table, and all of it was cut on purpose.

2. **The bundle records the owner; the host decides what that means.** DatsPet writes a
   category, a name, and a timestamp. DatsMe resolves the name — using data only DatsMe has.
   The factory never learns what a group is, and the host never learns how a bundle was built.

3. **Ownership changes through ONE function, never by hand.** Mint, purchase, and gift are the
   same operation with different arguments: *set these three fields together, now*. Each repo
   has exactly one writer (§2.1) and exactly one reader (§2.2). Every call site — including the
   ones added later — goes through them. Three fields written in four places by hand is three
   fields that will disagree within a month.

4. **Three fields, flat, at the manifest top level.** `owner_category` / `owner_name` /
   `owner_transferred_at`. Flat rather than nested, matching the existing top-level related
   group (`view_kind` / `native_facing` / `mirroring_policy`) — this manifest has no precedent
   for a nested block, and `animsFromManifest` on the host copies a fixed field list, so
   top-level additive keys are the shape it already tolerates.

5. **The name is a *name*, not an id.** DatsPet cannot resolve DatsMe ids, and the buyer types a
   name. Names are mutable, so a rename can strand a bundle that has never been adopted —
   accepted at this bar (§7.2).

6. **The manifest is a portable *record*; the host's DB is the *authority*.** DatsMe already
   holds the real ownership facts — `PetOwnership` (Postgres, `api/social_models.py:1636`) plus
   `pet_assets.created_at`. The manifest fields are a copy that travels with the artifact, so a
   user can see what they hold outside the platform. **Where the two disagree, the host wins.**
   Never write host logic that trusts the manifest over the database.

---

## 1. The fields

Top level of `manifest.json`:

```json
{
  "schema_version": "pet_manifest.v1",
  "fingerprint": "datspet",
  "owner_category": "individual",
  "owner_name": "black_zebra.1",
  "owner_transferred_at": "2026-07-29T14:22:05Z",
  "columns": 8, "rows": 4,
  "animations": { … }
}
```

### 1.1 `owner_category`

| Value | `owner_name` holds | Who may adopt |
|---|---|---|
| `"factory"` | `"datspet"` | **nobody** — minted, not yet sold |
| `"individual"` | a DatsMe user slug (`black_zebra.1`) | only that user |
| `"group"` | a DatsMe group tag (`black_zebra`) | the group's owner and its active members |
| `"public"` | `""` (empty) | anyone — the standard/free pets |

A closed vocabulary both repos agree on: an unknown category is **refused**, never treated as
`public`, so a future fifth value cannot fail open on a host that predates it.

**Why `factory` and not `individual` for the minted state.** A freshly built pet does need an
owner — that part of the sketch is right, and blank fields would be a third state to
special-case everywhere. But it cannot be `individual` with the name `datspet`: `individual`
means *"resolve this against `User.name_slug`"*, and `datspet` is not a DatsMe user. The host
would refuse the bundle for the misleading reason "user not found" and log a phantom missing-user
error for every unsold pet. One extra value in the vocabulary makes the state explicit, keeps the
ladder honest, and costs one row in this table.

### 1.2 `owner_name`

The typed DatsMe name — a user slug or a group tag. `"datspet"` while factory-owned, `""` when
the category is `public` (which needs no subject). Never an id (§0.5).

### 1.3 `owner_transferred_at`

**When the current owner became the owner.** Written at mint alongside the other two, then
rewritten at every ownership change:

| Event | becomes |
|---|---|
| pet is built | build time (owner: `factory` / `datspet`) |
| buyer accepts it | accept time (owner: the buyer) |
| owner gifts it | gift-accept time (owner: the recipient) |

So the field always answers the same question — *since when does the current owner hold it* —
and is never empty. A pet that has never been sold truthfully reports when the factory made it.

UTC, ISO-8601, `Z` suffix — per the repo-wide datetime rule. Produce it with the project's
`utc_isoformat()` / `utc_now()` helpers, never a bare `.isoformat()`. Note this is the *wire*
convention: DatsPet's own `datspet.db` stores unix epoch floats, so the stamp converts at the
boundary rather than leaking the storage format into the bundle.

**Named `_at`, not `_date`**, because it carries a time and because `_at` is the timestamp
convention in both repos (`created_at`, `expires_at`, `claimed_at`).

### 1.4 Why `manifest.json` and not a fourth zip member

The host rebuilds bundles from stored assets with `build_bundle_zip`
(`datsme_me/api/apps/pets/pet_assets_service.py:288`), which writes **only** sprite +
`manifest.json` + `package.json`. A `license.json` member would be silently dropped the first
time the host re-exported the pet at `GET /api/pets/me/{pet_id}/bundle`. `manifest_json` by
contrast is stored verbatim in `pet_assets`, carried into the recipient's copy on a gift
(`pet_gift_service.py:412`), and re-emitted on every export. It is the only place a field
survives every path.

`package.json` was also rejected: it is **optional** on the host (`pet_assets_service.py:203`
synthesizes one when absent), so a field there is not guaranteed to round-trip.

### 1.5 `schema_version`

Leave at `pet_manifest.v1`. Nothing on the host reads it (`SPEC_BUNDLE_MOTION_CONTRACT` §2.4
verified this), so a bump buys only a version to cite in a bug report, and all four fields are
additive.

### 1.6 `fingerprint` — reserved, stamped once

```json
"fingerprint": "datspet"
```

A mark identifying what issued the bundle. **Nothing reads it today.** It is reserved for a
future use, and is stamped now because bundles are immutable artifacts: a pet minted before the
field exists can never carry it, and back-filling means regenerating pets at GPU cost. Stamping
an inert field costs one string per bundle; not stamping it costs every pet built before the day
it matters.

**It is NOT an owner field, and the distinction is load-bearing:**

- **Written once, at mint only.** The owner fields change on every transfer; the fingerprint
  never changes. Different change cadence, different writer — so `transfer_pet_ownership` (§2.1)
  must not touch it, and every later stamp must preserve it.
- **The value is a named constant** (`BUNDLE_FINGERPRINT = "datspet"`), not an inline literal —
  and it is a **separate** constant from the `factory` state's `owner_name` (§1.1), even though
  both are the string `"datspet"` today. They mean different things, and the whole point of a
  placeholder is that its value will change; the factory-owner name must not change with it.
  Sharing one constant here would couple two facts that only coincidentally agree.

**Zero host work today.** The field survives every path for free: `manifest_json` is stored
verbatim in `pet_assets`, `animsFromManifest` copies a fixed field list and ignores unknown keys,
and `build_bundle_zip` re-emits the manifest whole. It needs no reader, no validation, and no
migration — it simply arrives and stays.

**Do not delete this field for being unused.** That is the whole reason this section exists: it
will read as dead weight to a cleanup pass, and it is not. When a consumer is designed, this
section is where the reader gets specified.

---

## 2. The transfer primitive

### 2.1 The writer

One function per repo, identical contract:

```python
transfer_pet_ownership(zip_bytes, *, category, name, at) -> (zip_bytes, manifest_json)
```

It opens the bundle, sets the three fields on `manifest.json`, re-zips, and returns both the new
bytes and the new manifest text so the caller can store them together. **It is the only code in
either repo that writes an `owner_*` field.** Mint, purchase, and gift are three calls with
different arguments — not three implementations.

On DatsPet the returned pair is persisted **only** through `db.restamp_bundle` (§2.4a), which
re-derives the two digest columns in the same UPDATE. That is why this function returns both
values instead of just the zip.

It validates its own arguments: category in the closed set, `name` non-empty unless the category
is `public`, `at` a UTC ISO string. A bad call fails loudly at the call site rather than writing
a bundle the other repo will refuse.

**It patches the manifest; it never rebuilds one.** Load the JSON, set the three owner keys, dump
it back. Every other key — `fingerprint`, the animations, the geometry, the view blocks, anything
a future spec adds — passes through untouched. Rebuilding a manifest from a known field list is
how `fingerprint` would silently vanish on the first gift, and how the next additive field would
too.

### 2.2 The reader

```python
read_pet_ownership(manifest_json) -> (category, name, at)
```

Used by the host's ingest ladder (§4.1), by DatsPet's pet list and detail views, and by anything
that ever wants to display "owned by". Missing fields come back as `(None, None, None)` — the
caller decides what that means (the host refuses; a display shows "unknown"), so absence is
never silently coerced into a category.

### 2.3 Where the code lives

**DatsPet: a new module, `webui/pet_ownership.py`.** Both functions plus the constants
(`BUNDLE_FINGERPRINT`, the `factory` owner name, the category vocabulary — §1.6, §8). It is a new
file rather than an addition to an existing one because all three current candidates are the wrong
owner: `db.py` is the byteless record view (it documents itself that way and never reads
`bundle_zip`), `app.py` is the HTTP surface, and `datsme_integration.py` is the DPP adapter. All
three *call* the primitive; none of them should *be* it. `db.restamp_bundle` (§2.4a) stays in
`db.py` — it is a store write, and the store is its correct home.

**DatsMe: `api/apps/pets/pet_ownership.py`**, beside `pet_assets_service.py`, which is what the
ingest ladder calls.

### 2.3a Two implementations, deliberately

The same ~20 lines exist in both repos. That duplication is intentional and must not be "fixed" by
extracting a shared module.

**Not in the partner SDK.** `datsme_partner_sdk` is a real shared dependency (DatsPet installs
it editable from `../datsme_me/api/sdk`), so it is the tempting home — but it is the *generic DPP
protocol* SDK, serving every partner. Pet-bundle internals are one app's content model, and
putting them there would make every future partner's SDK carry DatsPet's zip layout. The SDK
stays protocol; the bundle stays app.

What keeps the two copies honest is **one owned fixture plus a checksum**, not a vague "shared test
vector" — two repos cannot share a file, and two independently-maintained copies of a fixture drift
exactly like the code they were meant to police.

- **DatsPet owns it**: `webui/tests/fixtures/owner_fields.json` — the case table (every category,
  the empty-name public case, a `fingerprint`, and a deliberately unknown key), plus the expected
  read-back for each.
- **DatsMe vendors it** verbatim to `api/tests/fixtures/owner_fields.json`, and its test asserts
  the file's **sha256 matches the value pinned in that test**. A drifted copy fails loudly with a
  message naming the owning repo, instead of silently testing something else.
- Both sides then run `read(write(x)) == x` over the table.

The direction matters: DatsPet mints bundles, so it owns the wire cases. If the host needs a new
case, it lands in DatsPet's fixture and is re-vendored — which is the same direction the bundle
itself flows.

### 2.4 The DatsPet call sites

**Mint — `_finalize_pet_from_zip` (`webui/app.py:580`).** Already unpacks the bundle via
`_unpack_bundle` (`:555`), shared by fresh generation and pool reattach, and the last point
before the row is stored. Stamps `factory` / `datspet` / now.

**Not in `pack_datsme_bundle`.** That runs on pool GPU nodes
(`pool_handler/pet_factory_handler.py`), which must never hold identity or partner state.
Rendering and ownership change for different reasons and belong in different places. A welcome
consequence: `pet_factory/tests/test_pack_bundle_layout.py` — which pins the packer's exact
manifest field set — needs no change, because the packer's output is unchanged.

**Purchase — the top of `_post_pet_writeback` (`webui/datsme_integration.py:657`).** The pet is
built as a *draft*; ownership moves to the buyer at Accept, where `keep_pet(..., external_user_id=
ctx.user_id)` already runs (`:707`). Stamp `individual` (or `group` / `public`, per the buyer's
confirmed choice) with the accept time.

#### 2.4a Re-stamping moves FOUR things, through one writer

`bundle_sha256` and `size_bytes` are **columns** (`webui/db.py:67-68`), derived inside
`insert_pet` and documented there as *"DERIVED here, never passed… a pure function of
`bundle_zip`, so letting a caller supply them is only a chance to be wrong"* (`:218`). There is
no setter — the sole existing writer is the one-time backfill `UPDATE` at `:158`.

So re-stamping the bytes must move `bundle_zip`, `manifest_json`, `bundle_sha256`, and
`size_bytes` **atomically**. Add one writer:

```python
db.restamp_bundle(pet_id, zip_bytes, manifest_json)   # re-derives all four in ONE UPDATE
```

It re-derives the digest and size rather than accepting them, preserving `insert_pet`'s stated
discipline. **`transfer_pet_ownership`'s returned bytes+manifest are persisted only through it** —
which is why §2.1 returns both values rather than just the zip. `pose_count` is unaffected: the
stamp never touches `animations`.

**Why missing the columns fails silently and in the wrong feature.** Accept would still pass — it
verifies against the digest computed inline at `:662`. But the pull channel serves the *new* bytes
against the *stale stored* digest (`_export_item`, `:889-899`), and the host refuses it at
`pet_writeback.py:273`. The bug lands in house-adopt, not in the code that was changed.

#### 2.4b The rule: stamp before any digest is PUBLISHED

Two places publish a digest, and the stamp must precede both:

| Publisher | Where |
|---|---|
| the Accept writeback | `sha256(row["bundle_zip"])`, `webui/datsme_integration.py:661-662` |
| the pull channel's `transfer` block | `row["bundle_sha256"]`, `_export_item`, `:889-899` |

Stamp after either and the served bytes disagree with the advertised digest — an integrity error
that points at the bundle rather than at the ordering.

#### 2.4c The pull channel's stamp site is CLAIM

House adopt (`SPEC_DATSPET_HOUSE_ADOPT`) reaches the **same ingest**: `service.py:1149` routes
checkout to `handle_target_user_pet` (`pet_writeback.py:207`), which calls the shared
`validate_uploaded_bundle` at `:280`. So a pulled pet passes §4.1's ladder and must be stamped
before it is offered.

**It cannot be stamped at checkout.** Adopting is a **link, not an API call**
(`web/src/app/house/page.tsx:39`, citing house-adopt §0.1): the user selects, DatsPet calls
`claimPets` and navigates to the host's import page (`page.tsx:144-147`), and the host then pulls
from `/partner/export/`. DatsPet has no further step in the flow, and `_export_item` publishes the
digest before the host fetches — §2.4b forbids a stamp after that.

**The site is `POST /api/pets/claim` (`webui/app.py:1683`).** Its own docstring names it as the
pull channel's analogue of the push path's binding: *"Claiming first is what the push path already
does implicitly via `_bind_pending`; the pull needs it done explicitly."* Claim runs **before** the
pet is exportable — house-adopt §3.3's gate is exactly that — so it satisfies §2.4b for free. The
endpoint's job becomes **bind *and* stamp**:

- **The house selection carries the choice.** `claimPets` gains `owner_category` / `owner_name`
  (§5.0), and the chooser mounts on the selection surface.
- **Call it for every selected id, not only `claimable` ones.** Today `page.tsx:144-146` filters
  `p.claimable`, so a pet **bound at mint** — every pet a DPP-launched user builds, since
  `_finalize_pet_from_zip` passes `external_user_id=job.external_user_id` — has no claim moment at
  all. Widening is safe and anticipated: `claim_unowned_pets` documents that "a row already owned
  by this caller is a no-op (the house claims a whole selection, most of which is normally already
  theirs)" and leaves another user's row untouched via the WHERE (`webui/db.py:451-454`).
- **Drive the stamp from the requested ids, NOT from `claim_unowned_pets`'s return value.** That
  function returns only the ids it *newly* bound (`db.py:440`), which excludes precisely the
  bound-at-mint pet this widening exists to cover. Stamp every requested id whose row is owned by
  the caller after the claim — reusing the same scoping the endpoint already relies on, so a caller
  can never stamp a pet that was never theirs.
- **Not blocked on §2.6.** With no slug available the buyer types the name (§5.1), so the pull path
  ships on day one without the login work.

**`_export_item` gains no owner condition.** It keeps its existing honesty gates (no digest, no
pose_count). The stamp having already happened at claim is what makes publishing the `transfer`
block safe — adding a `factory` filter there would suppress the block for every pet house adopt
exists to move (house-adopt §3.3's target state is literally *"owned, exportable, not yet
imported"*, which is `factory` under this spec), turning a logged refusal into a silent outage.

> **Correction, recorded.** Rev.7 specified exactly that filter, and justified it with "the retry
> drain (`:813`) completes the Accept, the pet is stamped, and the next listing offers it." That is
> false: `:813` is the **push** path's queued-writeback drain — its own comment reads *"The pet is
> already bound to its user (Accept bound it before queuing)"* — and a pull-channel pet has no
> queued writeback, so nothing would ever drain it. `_bind_pending` (`:745`) also no-ops on an
> already-bound row, so there was no later hook of any kind. The error was treating "not yet
> Accepted" as "unowned" when the store distinguishes them (§2.4d).

#### 2.4d The invariant: the stamp mirrors `external_user_id`

One rule covers every case, and it is the store's own distinction:

| `pets.external_user_id` | owner fields |
|---|---|
| NULL — anonymous / standalone | `factory` / `datspet` |
| set — bound to a DatsMe user | that user (or the group/public they chose) |

Both binding moments therefore stamp: `_bind_pending` on the push path (via §2.4's Accept stamp)
and `/api/pets/claim` on the pull path. §5.2's table is this same rule seen from the UI, and §4.1's
`factory` rung keeps its meaning for a stronger reason — every *offered* pet was stamped before it
was offered, so a `factory` bundle at an ingest door is a genuine escape, not a normal state.

**Curated samples — `adopt_sample` (`webui/app.py:1409`).** Stamps `public` / `""` / now.
This matters only for a *re-upload* of a store bundle; storefront adoption on the host goes
through `create_my_pet` from the platform catalog, not the upload door.

### 2.5 The DatsMe call site

**Gift — `accept_offer` (`datsme_me/api/apps/pets/pet_gift_service.py:445`).** It already copies
`manifest_json` into the recipient's row (`:412`) inside the one commit that re-points
`PetOwnership`. The stamp is one call in code already writing that field, in the transaction that
already makes the transfer atomic — which is exactly why ownership can never half-move.

**A group pet gifted to a member becomes an individual pet.** That is the honest reading of a
transfer: the recipient now holds it personally. Whether a group pet should be giftable *out* of
its group is a policy question this spec does not decide; today's transfer path has no such
restriction and this spec adds none.

### 2.6 Where the buyer's name comes from

`owner_name` needs the **`name_slug`** (`sara.1`) — the unique, resolvable identifier the §4.1
ladder looks up. Neither login model supplies it today, and each is one field short in a
different place.

**What exists now.** The launch token already carries a name: the host mints
`"nm": user.display_name` (`datsme_me/api/apps/dpp/service.py:642`) and DatsPet reads it at
`webui/datsme_integration.py:271` to greet the user in the nav. **That is the display name, not
the slug** — `display_name` has no unique constraint (`api/social_models.py:76`) while `name_slug`
does (`:70`). A nav that reads `sara` sits beside a slug of `sara.1`; the value that renders is
not the value that resolves, and two users may share a display name.

> **ONE path, SPECIFIED, NOT YET IMPLEMENTED.** `../datsme_me`'s working tree has only
> `"nm": user.display_name` (`api/apps/dpp/service.py:642`) — there is no `slg` claim anywhere in
> it. `SPEC_DPP_FEDERATED_LOGIN.md` is **CHOSEN** and `slg` is ruled in for its step 1 (§14.4), but
> unbuilt. Plan the work accordingly: **day one of the owner field ships with an empty owner-name
> input** under the degrade-don't-block rule below. The "common case needs no typing" property
> (§5.1) arrives *with* the login work, not with this spec.
>
> **Rev.10 simplification:** earlier revisions specified *two* sources for the buyer's slug — the
> launch claim and a `password-verify` response. Password forwarding was declined, so there is one
> source. What follows is the whole of it.

**The launch-exchange path — the only path.** The host mints an `slg` claim carrying
`user.name_slug` beside the existing `nm` (`SPEC_DPP_FEDERATED_LOGIN` §6, ruled in by §14.4).
DatsPet reads `ctx.raw_claims.get("slg")` — or better, the typed `LaunchContext.name_slug` that §6
adds to the SDK — following the tolerance pattern already in place for `nm` at
`webui/datsme_integration.py:511-517`: re-read from the **verified** token, never the cookie, and
treat absence as "unknown" so a pre-`slg` host degrades instead of failing. Until the claim exists,
absence is the only case that runs.

**Where it is then kept.** `/launch` exchanges the verified token for a session row
(`SPEC_DPP_FEDERATED_LOGIN` §1.2, §3.3), and that row carries `name_slug TEXT NULL` beside
`display_name` (§3.1) with the same degradation rule: NULL means unknown, never an error. So the
slug is read from the token **once**, at the exchange, and read from the session thereafter — the
stamp at §2.4 does not re-parse a token it no longer holds.

**This is why `name_slug` is a session column and not a derived value.** §3.2 of the login spec
makes the same point from the other side: `external_user_id` is the storage and ownership key,
`name_slug` is the resolvable identity and the correct thing to *stamp*, and `display_name` is a
label that must never resolve an owner. That table and §1.2 of this spec are the same ruling.

**Why DatsPet must not reconstruct the slug from the typed username.** Sign-in is **slug-only**
today — `normalize_email` is a generic strip-and-lowercase normalizer (`api/helpers.py:64`), not
an email-acceptance path, and `api/routes/auth.py:1017` queries `User.name_slug == identifier`
under the comment *"Email is no longer a sign-in identifier."* So the typed string **is** the
slug on the password path, and DatsPet could infer it. It must not, because the inference fails
structurally rather than occasionally:

- The typed string is not canonical — case and surrounding whitespace.
- **DatsPet no longer has a typed DatsMe username to infer from at all.** Under
  `SPEC_DPP_FEDERATED_LOGIN` §0.1 the DatsMe password is typed only on `datsme.me`; the partner
  receives a signed assertion. The inference does not degrade — there is no input to it.
- **A passkey or second factor** likewise has no typed username. Note this argument *improved*: the
  declined spec needed a 409 `second_factor_required` escape hatch for it, whereas the redirect
  inherits DatsMe's authentication improvements automatically (`SPEC_DPP_FEDERATED_LOGIN` §0.1).
- **When local accounts arrive** (that spec's §11 step 2) there *will* be a typed username on
  DatsPet's login page — and inferring a slug from it would be actively wrong, not merely imprecise.
  A local identifier is in the partner's own namespace and "carries no relationship to `name_slug`"
  (§2): a local user named `sara.1` is **not** the DatsMe user `sara.1`. A local session has no
  DatsMe identity at all, which §5.2 already handles as `factory`/unsold.
- It couples our identity resolution to the shape of a form field on a page we do not own.

An identifier is received from the authority that resolved it, never reconstructed from user
input. (An earlier revision of this section justified the ask by claiming the username field
accepts email *or* slug. That was wrong — corrected here rather than quietly dropped, because the
claim was cited to the host team and the reasoning above is what actually holds.)

`name_slug` discloses nothing new in either channel: `GET /api/profiles/{name_slug}`
(`api/routes/me_content.py:1072`) already serves it anonymously.

**What the login spec already gets right for ownership**, and must not lose in review — all four
citations now point at `SPEC_DPP_FEDERATED_LOGIN`, and all four properties survived the change of
architecture because they are partner-side facts that never depended on how the password was checked:

- **§0.5 / §4 — every DatsMe-side effect needs a fresh, user-present launch ticket at the
  transaction.** That is exactly the purchase/transfer moment where §2.4 stamps the buyer. The two
  specs agree without having coordinated: the ownership stamp lands on the one moment that has a
  live ticket, and a powerless session cannot mint an owner claim.
- **§9.4 — a disabled account or changed password surfaces at the transaction, not the session.**
  The detector is the next launch-ticket mint failing; the resolution is re-authenticating. The same
  property protects the stamp: a stale session cannot transfer ownership.
- **§3.1 — the session stores `name_slug`, hashed-token rows, one-of-two identity invariant.** This
  replaces the `verify_credential()` citation Rev.9 relied on (see Rev.10 note 4). The auth basis for
  §3.1's owner-check is now **§3.3's own argument**, not an inherited pattern.
- **§3.1's header note — "`db.py` uses unix epoch floats, honor it".** Consistent with §1.3: the
  stamp converts to ISO-`Z` at the bundle boundary and leaves the store's format alone.

**One dependency to hand back — unchanged in substance, re-pointed.**
`SPEC_DPP_FEDERATED_LOGIN` §4 removes the held launch JWT that `_post_pet_writeback` reads from the
cookie today (`webui/datsme_integration.py:591`). §2.4's purchase stamp lives in that same function
and must stay **above the `sha256`** through that refactor. Whoever implements the login change
should be pointed at §2.4, or the reordering silently breaks every Accept on an integrity error.

That constraint is now carried in **both** specs — `SPEC_DPP_FEDERATED_LOGIN` §4 restates the
byte-identity invariant as a ⚠ box citing §2.4 of this file, and its test 21 pins it
(*"stamp → persist → hash"*). The duplication is deliberate: the ordering is invisible locally and
each spec's implementer must meet it without having read the other.

**Degrade, don't block.** With no slug from either source, pre-fill nothing and let the buyer type
their own name; the check in §5 confirms it. The feature must not depend on which login model
ships first.

---

## 3. The owner-check endpoint (DatsMe builds this)

A direct sibling of the existing partner profile read
(`datsme_me/api/apps/dpp/profile_routes.py`), so the auth, the error shape, and the client
pattern are all already established.

### 3.1 Contract — existence only

```
GET /api/partner/owner-check?category=<individual|group>&name=<typed name>

Headers:  X-DatsMe-Partner:    datspet
          X-DatsMe-Signature:  <partner HMAC over the request, per host_signature.py>

200 →  { "category": "group",
         "name": "black_zebra",
         "found": true,
         "canonical": "#black#zebra",      // name_slug for individual, normalized_tag for group
         "display_name": "Black Zebra Crew",
         "member_count": 34 }              // groups only
```

- **`found: false`** — the name does not resolve in that category. Not an error; a 200 with a
  negative answer, so DatsPet can warn without treating it as a host failure.
- **`factory` and `public` never reach this endpoint.** Neither has a name to resolve.

**No launch token, and no viewer context — this is the Rev.8 correction.** Earlier revisions
copied the profile-read route's `X-DatsMe-Launch-Token` auth and returned a `viewer_relation`
("is the caller in this group?"). Both were wrong for this endpoint:

- **The call happens during design, not at a transaction.** `SPEC_DPP_FEDERATED_LOGIN` §0.5 / §4
  removes the held launch JWT — tickets are minted seconds before a purchase — so there is no live
  token while a buyer is typing a name. An auth basis that only exists at checkout cannot serve a
  typeahead. (This reasoning is architecture-independent: both login candidates removed the held
  token, so the Rev.8 correction stands unchanged under Rev.10.)
- **`viewer_relation` was redundant.** §4.1's ladder re-checks membership at every ingest door
  anyway, and that check is the authoritative one. Asking the host at design time bought a nicer
  confirmation string in exchange for the auth problem above.

So: sign the request as a partner with the SDK's existing primitive
(`datsme_partner_sdk.host_signature.sign_host_request`) — **never hand-roll the HMAC** — carry no
user identity, and return only public facts. A group's
existence, display name, and member count are already visible to any DatsMe user browsing groups.

**Consequence for §5's UI:** the confirmation reads *"#black-zebra — Black Zebra Crew, 34
members"* without *"You are the owner."* Whether the buyer is actually in that group is decided at
ingest, where it has to be decided regardless.

### 3.2 Resolution is direct

The declared category selects the lookup — no ordering, no ambiguity:

- `individual` → `User.name_slug == name` (reuse `resolve_user_from_slug`, the helper
  `GET /api/profiles/{name_slug}` already uses).
- `group` → `Group.normalized_tag == normalize(name)`.

A name that happens to exist as both a user slug and a group tag is not a coin flip — the buyer
said which one they meant. This is the concrete win from Rev.2's explicit category.

### 3.3 Auth and consent

Partner-signature auth, no user context, **no capability, and no consent screen** — because there
is no user whose data is being read. The endpoint answers only "does this name exist, and what is
its public label", which any DatsMe visitor can already see. A capability gate would need a
`(user_id, partner_slug, capability)` grant row (`PartnerCapabilityGrant`), and this call has no
`user_id` to key one on. That argument is self-contained and is the whole justification.

> **Rev.10 — this is now the FIRST partner→host call of its shape, and that is a host change.**
> Rev.9 leaned on `identity.authenticate` / `verify_credential()` as the precedent for
> "partner-signed, no launch token." Password forwarding was declined, so that precedent never
> ships, and **no existing call has this shape**: `fetch_partner_profile` requires
> `X-DatsMe-Launch-Token` (`api/sdk/datsme_partner_sdk/profile_client.py:44-68`) and the writeback
> carries one as well. `host_signature.py`'s `sign_host_request` is the host→partner direction.
>
> Nothing above is invalidated — the reasoning never actually depended on the precedent, only cited
> it. But two things follow that an implementer must not discover late:
>
> - **Sequencing.** This endpoint is a DatsMe change and does not come free with the login work.
>   `SPEC_DPP_FEDERATED_LOGIN` step 1's only host change is the one-line `slg` claim (§14.4); this is
>   a second, separate one. It does not block the login work and the login work does not block it.
> - **It establishes a pattern, so get the shape right once.** A partner-signed call with no user
>   context is a new authorization category on the host. Verify the partner signature, resolve the
>   `PartnerApp`, and **check the signature before anything else** — the ordering lesson the declined
>   spec recorded for `password-verify` (signature before any other gate, or the 401/403 split becomes
>   a partner-slug oracle) transfers directly and is worth keeping even though its origin spec died.
>
> If the owner field must ship before this endpoint exists, §3.4's **degrade-never-block** rule
> already covers it: every failure reads as "unverified", the buyer types their name, and §5 confirms
> it. That is the fallback, and it is not a new one.

Rate-limit it per partner. It is an unauthenticated-by-user endpoint that takes a name and says
whether it exists, so it is an enumeration surface — bounded (the same information is browsable)
but not free. **Confirm the limit with the host**, which owns that policy.

### 3.4 The client on DatsPet's side

`webui/datsme_integration.py` is the one adapter that knows DatsMe endpoint URLs — the owner
check goes there, next to the writeback. Model it on
`datsme_partner_sdk.profile_client.fetch_partner_profile`: two headers, short timeout, structured
error.

**Degrade, never block.** `fetch_partner_profile` raises on any non-200 so callers handle absence
explicitly; do the same and treat *any* failure — network, 5xx, host down, secret unset — as
**"unverified"**, not "invalid". A DatsMe hiccup must not stop someone buying a pet. The buyer
sees "we couldn't check that name right now" and may proceed.

**Standalone posture holds.** `datsme_integration.py` is standalone-first: with
`DATSME_HMAC_SECRET` unset the whole DPP surface is inert. In that mode the check is skipped
(unverified), the owner input still works, and the fields still get stamped. A DatsPet running
with no host must not lose the ability to build a pet.

---

## 4. What DatsMe checks at ingest

One resolver, called at both doors, reading through `read_pet_ownership` (§2.2). Same ladder
shape as `_enforce_visibility` (`api/apps/pets/pet_routes.py:453`) — `public` short-circuits,
otherwise identity is required, otherwise a relationship decides — with a `group` rung where that
one has `friends`.

### 4.1 The ladder, keyed on `owner_category`

| `owner_category` | Passes when |
|---|---|
| `"public"` | always — no lookup, `owner_name` ignored |
| `"individual"` | `user.name_slug == owner_name` |
| `"group"` | `Group.owner_id == user.id` **or** an active member `Relationship(user_id=user.id, entity_type="group", entity_id=group.id, relationship_type="member", status="active")` |
| `"factory"` | **never.** Refuse and log it. Every offered pet is stamped at its binding moment — Accept on the push path, claim on the pull path (§2.4c/§2.4d) — so a `factory` bundle arriving here is a genuine escape, never a normal channel state |
| unknown value, missing fields, or a name that does not resolve | never |

`ix_relationship_lookup` (`api/social_models.py:369`) already indexes exactly
`(entity_type, entity_id, relationship_type, status)`, so the membership check is one indexed
query. No new membership concept and no new index.

`owner_transferred_at` is **not** part of the gate — it is provenance, recorded and displayed,
never a condition. Nothing expires.

### 4.2 The two doors

1. **`POST /api/pets/me/upload`** (`pet_routes.py:273`) — the door that matters. Today it accepts
   any zip from any user by design ("Does NOT consult the platform catalog"). The ladder goes
   here. On deny return **409 with the real reason** ("this pet is licensed to someone else") — a
   deliberate divergence from `_enforce_visibility`'s never-403 rule, which exists to avoid
   disclosing that a private pet *exists*. Here the uploader already holds the bytes, so nothing
   is disclosed by explaining the refusal, and a silent 404 would be a support ticket.

2. **The DPP writeback / Accept** (`api/apps/dpp/pet_writeback.py`) — the owner is the accepting
   user by construction, so this is a cheap consistency check. It is also **the last moment
   before money changes hands**: a name that resolves to nothing here means a pet nobody can ever
   adopt, including the buyer. Fail the Accept with the real reason rather than charging for an
   unusable pet.

The check belongs beside `validate_uploaded_bundle` (`pet_assets_service.py:150`), which both
doors already share and which the file documents as kept "in lockstep" — one function, two
callers, no drift.

### 4.3 Bundles with no owner fields

**Refuse at the upload door.** Defaulting absent-to-public would make the fields opt-out, and
then any hand-made zip walks in and the mechanism is decorative. Pets already adopted are never
re-validated, so nothing in a user's house breaks; only a fresh upload hits this.

---

## 5. The buyer's flow (DatsPet UI)

### 5.0 Where the control mounts — the Accept surface, not the designer

**One shared chooser component, two surfaces, two different wires** — because the two channels are
not the same transfer:

| Surface | Wire | Channel |
|---|---|---|
| `web/src/components/PetJobResult.tsx` — "Accept — send to my DatsMe" (`acceptPetToDatsme` at `:122`) | `acceptPetToDatsme` gains optional `owner_category` / `owner_name` → `accept_pet` passes them to the purchase stamp (§2.4) | push / writeback |
| `web/src/app/house/page.tsx` — the adopt selection (`claimPets` at `:146`) | `claimPets` gains the same two fields → `/api/pets/claim` binds **and** stamps (§2.4c) | pull / link + host fetch |

The house does **not** call `acceptPetToDatsme`: it claims and then navigates
(`page.tsx:144-147`). Treating the two as one wire was a Rev.8 error.

Omitted fields → `individual` plus the signed-in buyer's slug (§2.6); with no slug the buyer types
one (§5.1). Both endpoint URLs live in `web/src/lib/api.ts`, the one adapter.

**It does NOT go in the three-step designer, and `designFlow.ts` is not touched.** The mint stamp
is `factory` (§2.4), so a build needs no owner at all; the choice is only needed at the moment
ownership moves. Threading it through the flow reducer would put a value that cannot invalidate a
build into the one place whose entire job is invalidation — a design change never changes who owns
the pet. Different reasons to change, different homes.

### 5.1 The steps

1. Category defaults to `individual`. The name is pre-filled with the signed-in buyer's
   `name_slug` **once §2.6's login work lands** — until then, and whenever no slug is available,
   the field starts **empty** and the buyer types it. Never pre-fill `display_name`: it will not
   resolve, and a pre-filled wrong answer is worse than a blank one. Day one is the empty case.
2. The buyer may switch the category to `group` and type a tag, or to `public`.
3. On change (debounced) DatsPet calls its own
   `GET /api/datsme/owner-check?category=…&name=…`, which proxies to the host. The **browser
   never calls DatsMe directly** — the partner signing secret is server-side (§3.1), and a
   direct call would be a CORS problem on top of a secrets problem. The frontend reaches it
   through `web/src/lib/api.ts`, the one place frontend endpoint URLs live.
4. Show what came back — *"#black-zebra — Black Zebra Crew, 34 members"* — and require a confirm.
   No "you are the owner" line: §3.1 carries no viewer context, and membership is decided at
   ingest.
5. `found: false` or unverified → warn, allow "use it anyway". If the buyer insists on a name
   that resolves to nothing, the pet will not be adoptable. That is their call and their mistake
   to make (§0.1).

### 5.2 Anonymous use — there is no owner to stamp, and that is correct

**Rev.10 restates this premise, because the old one expires.** Earlier revisions argued: DatsPet has
no account system of its own, so *signed in* implies *has a DatsMe identity*, so every signed-in
buyer has a slug. That held under the declined password-forwarding spec. It **stops holding** at
`SPEC_DPP_FEDERATED_LOGIN` §11 step 2, which adds partner-local accounts — a local user is signed in
and has no DatsMe identity whatsoever ("a local account is not a DatsMe account and never becomes
one", that spec's §0.2).

**The correct premise is a field test, not an auth-method claim:** a buyer has a DatsMe identity
**iff `external_user_id` is set on their session row** (`SPEC_DPP_FEDERATED_LOGIN` §3.1–§3.2), and a
slug iff `name_slug` is additionally populated. Never "iff they are signed in", and never a branch on
*how* they signed in — that spec's §0.3 forbids the branch outright and its test 22 pins the field
test. This is the same posture `CLAUDE.md` requires of the engine and the same discriminator
`external_user_id IS NULL` already carries for standalone pets, so it introduces no new concept.

The conclusion is unchanged, and now covers one more case for free: a session with no
`external_user_id` — anonymous **or** local — has no owner to stamp, and `factory` is already the
answer.

Anonymous use stays supported — `SPEC_DPP_FEDERATED_LOGIN` §0.7: base-tier pet making with no login
at all keeps working, and `external_user_id IS NULL` remains the standalone case. Those pets need no
answer invented for them:

| State | `owner_category` | Behavior |
|---|---|---|
| anonymous / standalone deployment (no host secret) | `factory` | renders locally; never offered for pull (§2.4c); refused at ingest if hand-carried (§4.1) |
| signed in with a DatsMe identity (`external_user_id` set), before purchase | `factory` | same |
| signed in with a **local** account only (`external_user_id IS NULL`) — step 2 | `factory` | same; the owner chooser is not offered, since there is no DatsMe identity to transfer to |
| purchased | `individual` / `group` / `public` | adoptable per §4.1 |

An anonymous pet is simply an unsold pet, which is exactly what `factory` was introduced to mean
(§1.1). If that user later signs in and buys it, the purchase stamp runs then — no migration, no
special case, and **no new state**. The owner chooser is not rendered at all with no session, since
there is nothing to accept into.

---

## 6. Guard tests

**Shared (both repos, same committed fixture)**
1. `read_pet_ownership(transfer_pet_ownership(z, …))` returns exactly what was written, over every
   case in `owner_fields.json` — plus, on the DatsMe side, the vendored fixture's sha256 matches the
   value pinned in the test, failing with a message that names DatsPet as the owning repo (§2.3).
2. A transfer **preserves every non-owner key**, `fingerprint` included, plus a deliberately
   unknown key the fixture carries for exactly this purpose. This is the test that stops §1.6's
   field being lost on the first gift.

**DatsPet**
3. A freshly built pet's bundle carries `factory` / `datspet` / a parseable UTC `Z` timestamp,
   and `fingerprint == BUNDLE_FINGERPRINT`.
4. `_post_pet_writeback` stamps the buyer **before** computing `sha256`, and the digest it sends
   matches the bytes the bundle endpoint serves — the §2.4b trap, pinned.
4a. After a re-stamp, the **stored** `bundle_sha256` and `size_bytes` match the bytes
   `/api/datsme/bundle/{token}` serves — not merely the digest sent in the writeback (§2.4a). This
   is the assertion that catches the columns going stale, which Accept alone cannot detect.
4b. **Claim stamps.** `POST /api/pets/claim` on a never-Accepted pet stamps it, and the subsequent
   `/partner/export/{user_id}` listing offers a `transfer` block whose `sha256` matches the bytes
   `/api/datsme/bundle/{token}` serves (§2.4c). *This replaces a Rev.7/8 test that asserted
   `_export_item` omits the block for a `factory` pet — it pinned the outage.*
4c. **Claim stamps a pet that was already bound at mint** — the `claimable == false` case — so a
   DPP-launched user can house-adopt the pet they just built. Driving the stamp from
   `claim_unowned_pets`'s return value fails this test, which is the point of it.
4d. End to end: a house-adopt purchase of a pet that never went through Accept **succeeds**.
4e. Claim never stamps a row owned by another user, even when its id is passed explicitly.
5. `owner_name` is `""` exactly when the category is `public`, and non-empty otherwise.
6. Curated sample adopt stamps `public`.
7. The owner check degrades to "unverified" (never raises, never blocks) on network failure,
   non-200, and with `DATSME_HMAC_SECRET` unset.
7a. An anonymous build (no session) mints `factory`, renders in the house, and shows no owner
   chooser. It is not exportable at all — `export_pets` is keyed on `external_user_id`, which is
   NULL — so there is nothing to suppress (§5.2, §2.4d).
7b. Accept with no `owner_category`/`owner_name` defaults to `individual` + the buyer's slug; with
   no slug available the UI requires the buyer to type one rather than sending an empty name (§5.0).
8. `test_pack_bundle_layout.py` is unchanged and still passes — proof the packer's contract did
   not move.

**DatsMe**
9. The ladder: public / self / group-owner / group-member pass; non-member, wrong user, `factory`,
   unknown category, missing fields, and unresolvable name are all refused.
10. A bundle with no owner fields is refused at the upload door.
11. `accept_offer` rewrites all three owner fields to the recipient with a fresh timestamp,
    leaves `fingerprint` intact, and the recipient can re-upload their own exported bundle
    afterwards.

**Ordering (deploy gate)**
12. With the host's ladder enforcing and DatsPet **not** yet stamping, every ingest is refused —
    so the ladder ships **warn-only** (log, admit) until DatsPet's stamp is live, and the switch to
    enforcing is its own deploy step. The reverse order needs no gate: a stamp no reader consults
    changes nothing.

---

## 7. Known limits (all accepted)

1. **The fields are plaintext.** Unzip, edit, re-zip. Accepted per §0.1. This makes them a
   *record*, not proof in the cryptographic sense — the host's database is the authority (§0.6),
   and these fields are the copy that travels with the file.
2. **Names are mutable.** A user or group rename strands a bundle that has never been adopted.
   Already-adopted pets are unaffected (the host never re-validates them), so the exposure is the
   minutes between minting and Accept.
3. **Nobody verifies the buyer belongs to the group they typed.** They paid; the group's members
   benefit. If this ever needs closing, the cheap version is a host-side
   `Group.owner_id == accepting user` check at Accept — one line, deliberately not specified here.
4. **Group licensing is legitimate mass distribution.** One purchase can serve a group up to
   `max_group_members` (default 500, `api/social_db.py:636`). That is the feature working as
   asked, not a defect. Pricing it is a product decision outside this spec.
5. **One timestamp, not a chain.** `owner_transferred_at` records the *current* owner's start,
   overwriting the previous value — the bundle carries no transfer history. If a provenance trail
   is ever wanted, the natural form is an append-only list of `{category, name, at}` entries (the
   repo's append-only-ledger rule), and the single field remains its last element. Out of scope
   today.
6. **The sprite sheet is always extractable** from any rendered pet. What these fields protect is
   a pet *living on DatsMe*, which is where the value is.

---

## 8. Consistency checks (repo-wide rules)

- **Engine vs. content** — no runtime code branches on *who* the owner is. One function writes
  the fields, one reads them, and the host resolves them through a single ladder keyed on
  category. Neither side branches on the owner's identity anywhere else.
- **Intentional duplication** — the two `transfer_pet_ownership` implementations are a deliberate
  repo boundary, not a missed abstraction (§2.3a). Pinned by one owned fixture plus a vendored-copy
  checksum, not shared code (§2.3).
- **No inline literals** — `BUNDLE_FINGERPRINT`, the `factory` owner name, and the category
  vocabulary are all named constants in one discoverable place per repo, never strings typed at a
  call site (§1.6).
- **Additive fields survive by patching, not rebuilding** — the transfer primitive preserves every
  key it does not own, which is what makes `fingerprint` and every future field safe (§2.1).
- **One client adapter per backend module** — the owner check lives in
  `webui/datsme_integration.py` beside the writeback, and the frontend reaches it only through
  `web/src/lib/api.ts`.
- **UTC everywhere** — `owner_transferred_at` uses the project's `utc_now()` / `utc_isoformat()`
  helpers with a `Z` suffix (§1.3).
- **GPU-less posture** — nothing here touches `pet_factory`; the stamp is web-tier only, so no
  new import crosses the lazy ML boundary.
- **Standalone-first** — with no host secret the check is skipped and the app still builds pets
  (§3.4).
- **Specs cited from code** — the stamp sites and the ladder carry `SPEC_PET_OWNER_FIELD §2.4` /
  `§4.1` references, per the repo convention.
