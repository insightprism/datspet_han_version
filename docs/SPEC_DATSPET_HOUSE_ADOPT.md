# SPEC — Adopt to DatsMe from the Pet House

**Status:** rev.4 (2026-07-30) — **IMPLEMENTED and verified end-to-end** against the live
host. This is the partner side of `SPEC_DPP_DATA_TRANSFER_CHANNEL` (its **Phase 2d**); the
authoritative wire contract is now the amended protocol itself:
`keep_SPEC_DATSME_PARTNER_PROTOCOL.md` §7.2a, §13.3a, §13.3b, §13.5 (AM-3..AM-7). Where this
document and the protocol disagree, the protocol wins.

> **Rev.4 (2026-07-30) — this pull is now the ONLY purchase path, and the hand-off is
> shared.** `SPEC_DATSPET_FEDERATED_SESSION` §6 retired the push writeback
> (`POST /api/datsme/accept`), its retry queue, and its resync channel. Three consequences
> for this document:
>
> 1. **Every purchase entrance lands here.** The post-design Adopt and (later) the catalog
>    page do exactly what the house does. DatsPet holds no credential that can trigger a
>    charge, and a lapsed launch token can no longer cost a user a purchase — the checkout
>    authenticates against the user's own 30-day DatsMe session.
> 2. **The claim-keep-navigate sequence lives in one helper**, `handOffToDatsme` in
>    `web/src/lib/api.ts`. Where rev.3 said "claim first, navigate second", the full order is
>    claim → keep → navigate: the host skips drafts, so a pet that was never kept is not
>    offered either. Do not reimplement the sequence per surface.
> 3. **`claimable` changed meaning** (federated-session §4.5). It used to mean "an unclaimed
>    LOCAL pet", when `_scope_clause` showed every signed-in caller every unowned row. Scoping
>    is exact-match now and an anonymous browser owns its work under an `anon:` id, so
>    `claimable` means "this caller's own pet, not yet bound to their DatsMe id". Sign-in
>    normally claims everything already; the endpoint is the backstop for a pet finished after
>    that sweep, and it is keyed by owner rather than by a list of ids.

**Rev.3 changelog — what building it changed (each moved an implementation decision):**

1. **`pose_count` is a required top-level field on every export item** (§13.3b — the
   *declared pricing basis*). Rev.2 predates the amendment and never mentions it. The host
   quotes from the declaration without fetching bytes, then verifies it at ingest against
   `len(manifest["animations"])` of the fetched zip — a mismatch is a 409
   `pricing_basis_mismatch`, and an ABSENT declaration makes the item un-importable
   (absence is not zero; `pose_count: 0` is legitimate). We derive it from the
   `manifest_json` column, which `_unpack_bundle` stores verbatim from the zip, so column
   and artifact cannot drift — pinned by test, and verified 0 disagreements across every
   existing pet.
2. **Digests are derived inside `insert_pet`, not passed by call sites** (rev.2 §3.1 said
   "call sites pass `bundle_sha256=`"). A value that is a pure function of `bundle_zip`
   must not be independently settable — optional params with zero callers is exactly how
   every row sat NULL for months, and a future call site cannot forget what it cannot pass.
3. **`claimable` was added to the pet list** alongside `in_datsme`. The browser must know
   *which* selected ids need `/api/pets/claim` before the handoff; deriving it client-side
   would have meant leaking `external_user_id`.
4. **§9.1 is decided: claim-on-select shipped** (not hide-Adopt). §9.3 is resolved: a
   pulled pet is `draft=0`, and `purge_drafts` only sweeps draft rows, so the NULL
   `datsme_activity_id` the ack writes is safe.
5. **The end-to-end gate ran against the live host and caught two host bugs**, both since
   fixed and pinned in the host's own suite: omitting `pose_count` bypassed the binding
   quote (user quoted 100, charged 300), and the checkout re-derived the RAW quote while
   the list discounted — blocking EVERY re-import as `price_changed`. The fix is the
   host's `_effective_quote` (`max(0, raw − already_charged)`), one formula for list,
   checkout, and handler. Gate results: fresh 6-pose import quoted 300/charged 300;
   unchanged re-import quoted 0/charged 0; bundle upgraded to 8 poses re-listed at exactly
   the 100 delta and charged it; one host row throughout (cumulative 400); the §13.5 ack
   crossed the wire host-signed and stamped `writeback_acked_at` (activity NULL) both
   times; the host's real 15-minute manifest poll reconciled our `transferable`
   declaration unprompted, proving the content-derived ETag in practice.

rev.1 proposed a rival mechanism (per-pet idempotency keys + a house writeback); it was
wrong and is superseded (Appendix A). rev.2 was written against the channel spec's rev.3
draft; this rev records the as-built contract.

**Depends on:** host `SPEC_DPP_DATA_TRANSFER_CHANNEL` Phases **0, 2a, 2b, 2c**.
**Blocked until those ship** — §8 states the gate per item.
**Reuses:** `SPEC_DATSPET_DPP_INTEGRATION` (bundle tokens, the export, the signed-request
family), `SPEC_DATSPET_FRONT_DOOR` (the launch bounce and its `return` path).

Give the pet house a **Adopt to DatsMe** action, so a signed-in DatsMe user can send pets
they already own — not just the one they just built — into their DatsMe pet house.

**Two entrances, one surface.** A `🏠 Pet House` button on DatsMe deep-links the user into
their DatsPet house to pick what to send (§1.0); signing in on DatsPet lands them on the
same house with the same action (§1.0b). The house is the picker in both directions —
DatsMe never renders a gallery of pets it does not own.

Today the house offers `⬇ DatsMe zip`, whose tooltip describes the workaround this spec
replaces: *"Download the DatsMe breed bundle — upload it in DatsMe under Settings → Pet."*

---

## 0. The core decisions (read this first)

1. **Adopt is a LINK, not a writeback.** This is the whole of what rev.1 got wrong. A launch
   nonce authorizes exactly ONE successful writeback (`burn_launch_nonce` filters
   `used_at IS NULL` and 401s otherwise), so no key, no batch, and no retry scheme makes a
   house of Adopt buttons work over the push path. The host's channel replaces the writeback
   with a link to a DatsMe-hosted import page, which pulls from our export. **We call no API
   to adopt.** The house builds a URL.

2. **Multi-select is REQUIRED, not a nicety.** Adopt navigates away — the user lands on
   DatsMe. A per-card Adopt link therefore costs one full-page bounce **per pet**, which is
   exactly the "re-launch per item" posture the host spec supersedes (its §10.5). The entire
   value of the channel is *one bounce for N pets*. So the house selects, then acts once.
   Shipping per-card links would deliver the new mechanism with the old flow's cost.

3. **We delete our dead 409 rather than extend it.** Host §0.3 proved
   `datsme_integration.py:600-601` unreachable: its condition requires
   `owner is not None and owner != ctx.user_id`, which line 598 already 404s. It has never
   fired. rev.1 proposed extending it; it should be **removed**, with the re-adopt semantic
   coming from the host's §3.3 upsert instead.

4. **Re-adopt becomes free and idempotent — we do not block it.** Host §3.3 keys the pet and
   the charge to `(partner_slug, source_item_id)`. rev.1's §0.4 ("v1 blocks re-adopt") is
   **reversed**, not fulfilled. The house must not build a "you already have this" gate; it
   shows state (§4.1) and lets the host decide. Re-clicking Adopt is safe and costs 0.

5. **Two of our columns already exist for this and nothing writes them.** `bundle_sha256`
   and `size_bytes` are in the `pets` schema (`db.py:66-67`) and are optional params on
   `insert_pet` (`db.py:162-163`) — with **zero call sites passing them** (verified: no hits
   for `bundle_sha256=` in `webui/`). They are always NULL. The export's `transfer` block
   needs both per item, and computing them live would load every pet's blob into a list
   request. §3.1 wires them. (This is the same "declared, never wired" shape the host spec
   is about — we have it too.)

6. **The frontend never hardcodes a DatsMe origin — including the import URL.** Front-door
   §3.2's rule already applies: the backend hands the browser its DatsMe URLs. `PARTNER_SLUG`
   is env-overridable (`os.environ.get("DATSME_PARTNER_SLUG", "datspet")`), so
   `/import/datspet` is **not** a constant we may inline. §3.5 adds `import_url` to the
   session payload, built server-side from `_datsme_public_url()` + `PARTNER_SLUG`.

7. **The export/house scoping asymmetry is ours to fix, and it is a blocker for the pull
   (§2).** The host cannot see it and cannot fix it.

---

## 1. The flows

### 1.0 Entrance A — `🏠 Pet House` from DatsMe (survives rev.1 unchanged)
```
DatsMe /settings/pet   [🐾 Design a pet]  [🏠 Pet House]  [⬆ Upload a pet bundle]
                                              └─ href = /api/integrations/login-launch
                                                        ?activity=design_a_pet&return=/house
   ├─ get_current_user ✓        (signed out → /login?next=… ; first-time → consent page)
   ├─ resolve_and_mint_launch(user, "design_a_pet")     # existing machinery
   ├─ _safe_return("/house") ✓  (host routes.py:36 — charset validator, not an allowlist)
   └─ 303 ──▶ pet.datsme.me/launch?token=<jwt>&return=/house
                 └─ verify → set cookie → 303 ──▶ /house
```
**Host cost: one anchor tag, no backend.** The launch cookie is still required — not to
adopt, but because `/api/pets` scopes the house on `external_user_id`. Identity to *see*
your pets; no token at all to *transfer* them.

Reuse `design_a_pet`: it is the only activity our manifest declares
(`datsme_integration.py:162-176`) and it already requests `pets.write`, so existing consent
covers this entrance. A new activity would cost a second consent prompt for a capability
already granted. See §9.2.

### 1.0b Entrance B — sign in on DatsPet, then visit the house
`PublicLanding` → `Sign in with DatsMe` → the same bounce (`return=/design`, hardcoded
server-side at `datsme_integration.py:469`) → the house via the nav. Same cookie, same
action. No new work.

### 1.1 Select and adopt (the primary path)
```
/house  ── GET /api/datsme/session ─▶ {launched: true, import_url: "https://datsme.me/import/datspet"}
        ── GET /api/pets ──────────▶ [{id, …, in_datsme: false}]

  cards render a selection checkbox when launched
        └─ [✓ Adopt 3 pets to DatsMe]
              ├─ POST /api/pets/claim {pet_ids}      ← §3.3, only if any are unclaimed
              └─ window.location = `${import_url}?items=p1,p2,p3`
                    │
                    │  ── everything below is the HOST's, per its §2.1 ──
                    ├─ user's own DatsMe session (no launch token, no nonce)
                    ├─ host-signed GET /partner/export/{user_id} → our export
                    ├─ per item: fetch pointer_url → verify sha256 → price from the bundle
                    ├─ confirm: "Import 3 pets from DatsPet — 500 credits" (itemized, exact)
                    └─ on confirm: charge + ingest; then POST /partner/imported/{user_id}
                                                       └─▶ §3.4 stamps writeback_acked_at
```

### 1.2 Already imported
`in_datsme: true` → the card shows a static `✓ In DatsMe` chip and is **still selectable**.
Re-import is free and updates in place (host §3.3), so this is information, not a gate.

### 1.3 Standalone or not signed in
`{launched: false}` → no checkboxes, no Adopt action; the card is exactly what ships today
(`⬇ DatsMe zip` + `🗑 Remove`). Standalone mode (`DATSME_HMAC_SECRET` unset) stays inert.

### 1.4 Failure postures
The house's failure surface collapses to almost nothing, because it no longer performs the
transfer. Everything below the link is the host's to report.

| Condition | Surface |
|---|---|
| Launch cookie expired | `/api/pets` returns the standalone set; the user re-enters via §1.0. No 401-mid-adopt to handle — there is no adopt call. |
| Claim POST fails (§3.3) | Inline on the card; do not navigate. |
| Item missing from the export | The host's import list omits it (host §2.1). §2 exists so this cannot happen for a pet we displayed. |
| Host down | The link 502s on DatsMe's origin. Nothing local to roll back — we wrote nothing. |

---

## 2. The scoping asymmetry (blocker — ours alone to fix)

**`export_pets` and the house disagree about which pets exist.**

```python
# db.py:290 — export_pets: EXACT match. Unclaimed pets are invisible.
"... FROM pets WHERE external_user_id=?"

# db.py:204 — _scope_clause, launched caller: NULL-inclusive.
"(external_user_id IS NULL OR external_user_id=?)"
```

So the house shows a launched user their own pets **plus every unclaimed
(`external_user_id IS NULL`) pet**, while the export returns **only their own**. Under the
pull, clicking Adopt on an unclaimed pet links to `?items=<id>`, the host signs the export,
the item is not in the response, and — since `items` is only a filter over an
authoritatively-scoped list (host §2.1) — it silently vanishes from the import page. A pet
visible and selectable in the house is un-importable, with no error anywhere.

**The push path handles this today and the pull cannot.** `accept_pet`'s gate deliberately
permits unclaimed pets, and `_post_pet_writeback` then calls `_bind_pending`
(`datsme_integration.py:709`), which sets `external_user_id = ctx.user_id`. **Adopt-on-push
is claim-on-adopt.** A pull has no equivalent: the export is the source of truth and never
mentions the pet.

**This is not fixable host-side.** Including NULL-owner pets in every user's export would
offer the same pets to every user and let two of them import the same one.

**Decision: claim on select (§3.3).** The house has a launch cookie, so we have
`ctx.user_id` and `ctx.activity_id` — the exact inputs `_bind_pending` already takes. Claim
the selected unclaimed pets *before* navigating, and the export then contains them. This
preserves today's push semantics exactly rather than inventing a rule.

The alternative — hide Adopt on unclaimed pets — is defensible (a clean prod box has none;
they are a dev-mode artifact of standalone-created pets) and is one line. But it silently
changes what a launched user can do, and rev.1 already deferred this decision once as §7.3.
**Decide it here, not after the button makes it visible.** See §9.1.

---

## 3. Backend changes (`webui/`)

### 3.1 Populate `bundle_sha256` + `size_bytes` + `pose_count` (prerequisite for §3.2)
The columns exist and nothing writes them (§0.5). The export needs all three per item and
must not load blobs to get them.

- **As built (rev.3): `insert_pet` derives the digest and size internally** from the
  `bundle_zip` it was handed — the params are REMOVED, not merely populated. Rev.2's plan
  (each call site passes them) recreates the failure mode that produced the NULLs: an
  optional param a new call site can forget.
- **`pose_count` is computed at read time** by `db.pose_count(manifest_json)` =
  `len(manifest["animations"])`, `None` (never 0) when unparseable. The column is the
  zip's `manifest.json` verbatim (`_unpack_bundle`), so declaration and artifact agree by
  construction — and `test_pull_export.py` pins the agreement against the host's exact
  derivation rather than trusting the construction.
- **Backfill** existing rows once at startup, beside `init_db`'s existing legacy migration:
  for rows where `bundle_sha256 IS NULL`, compute from `bundle_zip` and write. Bounded and
  one-time; the blobs are already local.
- `_post_pet_writeback` (`:626`) recomputes the digest per writeback. Leave it — it already
  holds `zip_bytes` for the size check, and a stored digest it did not verify would be a
  trust downgrade on the push path. The columns serve the export, which has no bytes in hand.

*Gate: every pet row has a non-NULL `bundle_sha256` matching `sha256(bundle_zip)`, on both a
fresh insert and a backfilled row.*

### 3.2 The `transfer` block on `/partner/export/{user_id}`
Per host §5.1, **optional per item**; its presence is how a partner opts into transfer.

Build it in the **route** (`export_user_data`, `datsme_integration.py:817`), not in
`db.export_pets`. `db.export_pets` stays the byteless record view it documents itself as
(`db.py:291`), and the route decorates — mirroring how it already wraps the call.

```python
{ "id": "p1", "breed_id": "...", "display_name": "...", "created_at": ..., "draft": false,
  "transfer": {
      "pointer_url": f"{_datspet_public_url()}/api/datsme/bundle/{token}",
      "sha256": row["bundle_sha256"], "size_bytes": row["size_bytes"],
      "content_type": "application/zip",
  } }
```

- **A fresh one-time token per item per export call**, via the existing
  `db.create_bundle_token(token, pet_id, time.time() + BUNDLE_TOKEN_TTL_SEC)`. The host
  fetches at list time and `serve_bundle` burns post-send (single-**successful**-download,
  `datsme_integration.py:787`), so a re-listed page simply mints fresh tokens — a burned one
  never blocks a reload.
- **Keep `BUNDLE_TOKEN_TTL_SEC` at 24 h.** The pull needs seconds, but the push path's retry
  queue needs 24 h (`SPEC_DATSPET_DPP_INTEGRATION` §5.3). One constant, two uses; do not
  fork it for a window the pull does not care about.
- **`pointer_url` must share our `launch_base_url` origin** (host §5.1's rule; their
  `_fetch_bundle` pins to it). `_datspet_public_url()` is that origin — assert it rather
  than assume, since a misconfigured `DATSPET_PUBLIC_URL` would fail every import with an
  origin refusal and no local symptom.
- Omit `transfer` for rows with a NULL `bundle_sha256` (pre-backfill) rather than emit a
  half-block — the host skips an item it cannot verify, which is the correct failure.

*Gate: the export is byte-free; each item's `sha256` matches the served bytes; `pointer_url`
resolves exactly once and 404s on the second fetch; the origin matches `launch_base_url`.*

### 3.3 Claim on select — `POST /api/pets/claim` (closes §2)
```python
@app.post("/api/pets/claim")   # launch-cookie required; body {pet_ids: [...]}
```
For each id the caller may access (`_scope_clause`) whose `external_user_id IS NULL`, bind
it to the caller exactly as the push path does. Reuse `_bind_pending`'s update rather than
writing a second one — it already sets `external_user_id` + `datsme_activity_id` without
acking, which is precisely the state we want: owned, exportable, not yet imported.

Already-owned ids are a no-op (not an error) — the house calls this for a whole selection
and must not fail because most of it was already claimed. Ids owned by *another* user are
skipped silently; they were never visible to this caller anyway.

*Gate: claiming an unclaimed pet makes it appear in that user's `/partner/export/`; claiming
another user's pet changes nothing and does not leak its existence.*

### 3.4 `POST /partner/imported/{user_id}` — the host's ack (host §5.5)
Host-signed, in the same family as `/partner/revoke`. Body `{export_type, item_ids}`. For
each id, `db.stamp_writeback_acked(...)` so the house's `in_datsme` tells the truth after a
pull.

- **Must be host-signed** — `_require_host_signature(request, raw)` over the exact raw bytes,
  then parse *those same bytes*, exactly as `revoke_user` does (`:847`). This endpoint marks
  pets as delivered; an unsigned caller could mark everything adopted.
- `stamp_writeback_acked` takes an `activity_id`. **A pull has no activity** (host §5.2:
  `IngestContext.activity_id` is `None`). Store NULL rather than inventing one — the column
  is nullable, and a fake activity id is exactly the "lie in the engine" the host spec
  refuses to write. Verify nothing reads `datsme_activity_id` for equality first;
  `purge_drafts`' `not_pending` clause reads it (`db.py:253`) and must be checked.

*Gate: an unsigned POST 401s; a signed one flips `in_datsme` for exactly the named ids; a
pulled pet is absent from `/partner/results/{user_id}/pending`.*

### 3.5 `import_url` + `in_datsme`
- **`/api/datsme/session`** gains `import_url` when integrated:
  `f"{_datsme_public_url()}/import/{PARTNER_SLUG}"`. Built server-side for the same reason
  `signin_url` is (front-door §3.2, §0.6 above).
- **`list_saved_pets`** (`db.py:194`) projects `writeback_acked_at IS NOT NULL AS in_datsme`.
  `_scope_clause` is untouched — this adds a column, not a visibility rule. Cast to a real
  `bool` at the boundary so the JSON carries `true`/`false`, not `1`/`0`.

### 3.6 Delete the dead 409
Remove `datsme_integration.py:600-601`. It is unreachable (§0.3) and its message
("pet already adopted by another user") describes a rule the host now enforces properly by
business key. Leave the 404 at `:598` — that one works and is load-bearing.

---

## 4. Frontend changes (`web/`)

### 4.1 `house/page.tsx`
- Fetch `getDatsmeSession()` alongside `listPets()` on mount; both are independent.
- **Selection state** when `session.launched`: a checkbox per card, plus a sticky action bar
  showing `✓ Adopt N pets to DatsMe`. No per-card Adopt link (§0.2).
- The action: `POST /api/pets/claim` with the selection, then
  `window.location = \`${session.import_url}?items=${ids.join(",")}\``.
  Claim first, navigate second — a failed claim must not send the user to an import page
  that will silently drop the item (§2).
- `in_datsme: true` renders a `✓ In DatsMe` chip; the card stays selectable (§1.2).
- Cost is **not** shown here. The host prices from the fetched bundle because pose counts
  are read from the manifest and never partner-claimed (host §0.6); any number we render is
  a guess that will disagree with the confirm page. Say *"You'll see the exact cost before
  anything is charged"* and let DatsMe be the one that quotes.

### 4.2 `PetSummary` — `api.ts:35`
```ts
export interface PetSummary {
  id: string; breed_id: string; display_name: string; created_at: number;
  in_datsme: boolean;   // already in the user's DatsMe house (§3.5)
}
```

### 4.3 What the frontend does NOT grow
- **No `useAcceptPet` extraction.** rev.1 called for it. The house makes no accept call, so
  there is no retry/401/402 semantic to share. `PetJobResult` keeps its accept logic
  unchanged and un-lifted. Do not extract an abstraction for one caller.
- **No cost label, no credit math, no re-adopt gate.** All host-side now.

---

## 5. Manifest (`_build_manifest_body`, `datsme_integration.py:182`)

```python
.add_data_export(
    export_type="pets", schema="datspet_pets.v1",
    description="The pets you designed on DatsPet.",
    per_user_downloadable=True,
    transferable=True,          # NEW — we opt in (host §5.3)
    ingest_target="user.pet",   # NEW — names an existing host _TARGET_HANDLERS entry
    max_bytes=10 * 1024 * 1024, # NEW — our declared per-item ceiling; host clamps to its own
)
```
Requires the host's SDK change first (`manifest.py:113` takes exactly four params today).
Host §5.3 also requires the three keys be emitted **conditionally**, or every partner's
manifest ETag shifts and the fleet refetches — that is the host's to get right, but our
manifest is the one that proves it.

*Gate: our `/partner/manifest` still validates under conformance #9; the ETag is stable
across a no-op redeploy.*

---

## 6. What this deliberately does not do

- **No writeback from the house.** Adopt is a link (§0.1).
- **No per-card Adopt.** One selection, one bounce (§0.2).
- **No re-adopt gate, no 409, no `in_datsme` enforcement.** Information only (§0.4).
- **No cost display on the house** (§4.1).
- **No change to the push path.** `PetJobResult`'s design→accept→eject flow is correct for
  its job: one pet, one launch, one nonce. It is not deprecated and does not fork.
- **No removal of `⬇ DatsMe zip`.** It stays for standalone users and as the escape hatch
  when the host is down.
- **No import direction (DatsMe → DatsPet).** Host §7 records it as unspecified with no
  consumer. We are not the consumer today.

---

## 7. Security

- **The export gains bytes-by-pointer, not bytes.** Still host-signed
  (`_require_host_signature`), still user-scoped by path. `pointer_url` is a fresh one-time
  token per call, origin-pinned, burned on first successful download.
- **`/api/pets/claim` is launch-gated and scope-checked** — it can only bind pets the caller
  could already see and act on (`_scope_clause`), which is the same rule `keep`/`delete`
  enforce. It cannot take a pet from another user.
- **`/partner/imported/{user_id}` is host-signed over raw bytes.** Unsigned → 401.
- **No new origin trust.** `pointer_url` uses `_datspet_public_url()`; `import_url` uses
  `_datsme_public_url()`. Both are existing, already-validated config.
- **The consent story strengthens.** rev.1's flow charged credits on the strength of a
  60-minute launch token. This one charges on an active, non-revoked `PartnerCapabilityGrant`
  plus an explicit itemized confirm on the site that holds the ledger.

---

## 8. Build order

**Nothing here ships before host Phase 0.** Host §11: *"Phase 0 fixes a bug that is producing
duplicate pets and double charges in production today."* Adding a second adopt entrance on
top of an unfixed duplicate bug multiplies it.

| # | Step | Gate | Blocked on |
|---|---|---|---|
| 1 | §3.1 sha256/size + backfill | every row non-NULL and correct, both paths | — (safe now) |
| 2 | §3.5 `in_datsme` + `import_url` | list returns a real bool; session carries the URL | — (safe now) |
| 3 | §3.6 delete the dead 409 | suite green; the 404 still fires for another user's pet | — (removing unreachable code is a no-op; the re-adopt semantic it *claimed* to provide arrives with host Phase 0 regardless) |
| 4 | §2/§3.3 claim-on-select | claimed pet appears in that user's export | — |
| 5 | §3.2 `transfer` block | byte-free export; sha256 matches; token single-use; origin pinned | host 2b (schema registry) |
| 6 | §5 manifest keys | conformance #9 passes; ETag stable | host SDK `add_data_export` |
| 7 | §3.4 `/partner/imported` ack | unsigned 401s; signed flips `in_datsme` | host 2c |
| 8 | §4 the house UI | — | 5, 6, 7 |
| 9 | **`/verify` end-to-end** | select 3 pets of differing pose counts → confirm on DatsMe → **3 pets land, charged once, itemized total matches, and the house shows all 3 as `✓ In DatsMe`** | host 2c |

Steps 1–4 are useful and safe before the host lands anything. **Steps 8–9 ship with
host 2c, never before** — host §11: *"2c alone puts a user-visible import page in front of an
export that emits no `transfer` block."* The inverse is equally true: our house must not
offer an Adopt link to an import page that does not exist.

**Which host phases this spec actually needs: 0, 2a, 2b, 2c.** Not Phase 1, and not Phase 3.

- **0** — a hard gate for *safety*, not capability: without item identity, re-adopt
  duplicates and double-charges today, and an easy Adopt multiplies a live bug.
- **2a** — a pull has no nonce, and `apply_writeback` fails **open** on the capability check
  without `IngestContext` (host §5.2). No 2a, no ingest — and no consent enforcement.
- **2b** — `data_exports` has never been ingested (zero hits in host `apps/`). Until 2b, §5's
  manifest keys go nowhere.
- **2c** — the import page our link points at. It is a 404 until then.
- **Phase 1 is orthogonal to this spec.** `request_digest` + the 409 protect the *push*
  path; §0.1 removed our writeback, so we have no idempotency key to collide. **This does
  not make Phase 1 optional in general** — it is the only fix for the originally-reported
  bug, which lives in the design flow (`PetJobResult`), survives Phase 0 untouched (Phase 0
  does not touch the idempotency cache), and is still reachable via the
  queued-then-Design-another and back-button paths. That flow correctly stays on push
  forever. **Phase 1 must not be sequenced behind this spec.** Note it carries partner work
  we have not specced: `_error_detail` (`:722`) reads only `detail`/`message`, so the
  structured `code` is unconsumed, and the SDK's `retry.py` burns any non-401 4xx — so
  enforcing 1b before both are fixed converts a silent loss into an immortal pending row
  (host §4.2).
- **Phase 3** (the archive) is the host's legitimacy argument for the standing read
  (host §12.5), not a functional dependency of ours. Their sequencing call, not ours.

---

## 9. Open questions

1. **~~The unclaimed pool — claim or hide?~~ DECIDED (rev.3): claim-on-select, shipped.**
   `POST /api/pets/claim` binds selected unclaimed pets to the caller exactly as
   `_bind_pending` does on the push path, before the handoff. Ownership is enforced in the
   UPDATE's WHERE (atomic), another user's pet is untouched, an already-owned id is a
   no-op. Pinned by three tests in `test_pull_export.py`.
2. **Activity reuse for the `🏠 Pet House` entrance.** We launch `design_a_pet` with
   `return=/house`, so "visit my house" is recorded host-side as a `design_a_pet` activity.
   Slightly a lie; defensible (the pet *was* designed here, and `pets.write` is the
   capability in play); the alternative costs a second consent prompt. Revisit only if the
   host's activity UI makes it confusing.
3. **~~`datsme_activity_id` NULL on a pulled pet~~ RESOLVED (rev.3): safe.**
   `purge_drafts`' `not_pending` clause only applies to `draft=1` rows, and a pullable pet
   is `draft=0` by definition (the host filters drafts from the import list, and only
   saved pets are exported with `transfer`). The ack stamps NULL and nothing mis-sweeps.
4. **Bundle-token churn.** Every export call mints one token per pet — 22 pets, 22 tokens,
   most never fetched if the user filters to 3. `db.py:398` has the expiry DELETE; confirm
   it is actually *called* on a schedule rather than merely defined, or tokens accumulate.
5. **Selection UX on the wandering `PetStage`.** Pets roam the floor; selection lives on the
   cards. Probably right — the stage is play, the cards are admin.

---

## Appendix A — what changed from rev.1, and why

rev.1 (2026-07-15, superseded the same day) proposed fixing the push path and putting an
Adopt button on each card. Every load-bearing claim in it was wrong. Recorded because each
error moved a decision:

| rev.1 claim | Reality |
|---|---|
| §0.2 "unsafe to ship until the key is `jti:pet_id`" | **Superseded** (host §10.1). The SDK's `jti` default is *correct* — it encodes one-writeback-per-launch. A per-pet key makes item two **401** at `burn_launch_nonce` instead of vanishing. Louder, still broken. |
| §0.4 "v1 blocks re-adopt with a 409" | **Reversed** (host §3.3). Re-adopt becomes free and updates in place. Worse, the 409 rev.1 proposed extending is **unreachable dead code** (host §0.3) — rev.1 described a guard that has never once run. |
| §2.1, §2.3 (idempotency + 409) | **Deleted.** |
| §3.1 `useAcceptPet` extraction | **Deleted** — the house makes no accept call. |
| "batch is probably the best in-protocol answer" (in review, not the doc) | **Refuted** (host §10.3): `handle_target_user_pet` opens its own `SocialSessionLocal` and commits internally, so the route's rollback rolls back a different session. A batch failing at item 3 leaves 1–2 committed and charged. |
| §7.1 "upsert on `source_pet_id`, needs host work" | **Delivered** by host §3. We were right that it was the end state, and right about where it lived. |
| §7.2 "a user can queue up several 100-credit charges with no running total" | **Right, and unanswered by the host's rev.1.** Now answered by its §2.1 itemized confirm + §3.3 free re-import. |
| §1.0 the `🏠 Pet House` entrance | **Survives unchanged.** Identity to see the house; no token to transfer. |

What rev.1 got right and this rev keeps: the house is the picker; DatsMe should not render a
gallery of pets it does not own; the entrance is one anchor tag; `design_a_pet` reuse avoids
a second consent prompt.

---

## Appendix B — grounding (verified 2026-07-15)

| Claim | Evidence |
|---|---|
| A launch nonce authorizes exactly ONE writeback | `../datsme_me/api/apps/dpp/service.py:818` `burn_launch_nonce` — `used_at IS NULL` filter, 401 on rowcount≠1 |
| Route order: authenticate → cache → burn → apply | `../datsme_me/api/apps/dpp/routes.py:332-355` |
| Our 409 is unreachable | `datsme_integration.py:598` 404s the exact condition `:600` tests |
| We stamp acked + clear draft on ANY 200 | `datsme_integration.py:668-671` |
| `export_pets` is exact-match; the house is NULL-inclusive | `db.py:290` vs `db.py:204` |
| The push path claims on adopt | `_bind_pending`, `datsme_integration.py:709` |
| `bundle_sha256`/`size_bytes` exist and nothing writes them | `db.py:66-67`, `:162-163`; zero hits for `bundle_sha256=` in `webui/` |
| Bundle tokens are single-**successful**-download, burned post-send | `datsme_integration.py:787-811`; `db.py:375` (`downloaded_at IS NULL`) |
| Token TTL 24 h, sized for the push retry window | `datsme_integration.py:107` |
| Token expiry DELETE exists | `db.py:398` — caller cadence unverified (§9.4) |
| `PARTNER_SLUG` is env-overridable | `datsme_integration.py:109` |
| `design_a_pet` is our only activity; it requests `pets.write` | `datsme_integration.py:162-176` |
| Host `login-launch` takes `return`; `/house` passes its validator | `../datsme_me/api/apps/dpp/routes.py:184`, `:36` |
| `stamp_writeback_acked` takes an activity_id; `purge_drafts` reads it | `db.py:269`, `db.py:253` |
