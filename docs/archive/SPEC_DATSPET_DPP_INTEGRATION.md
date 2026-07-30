# SPEC — DatsPet as a DatsMe Partner App (DPP Integration)

> **CLOSED & ARCHIVED — 2026-07-30. Built, E2E-verified, and half-retired since. This is a
> build record, not a design to implement from.**
>
> **What it built that still runs.** The partner surface in `webui/datsme_integration.py` is
> this spec's work and is load-bearing today: the signed manifest, `GET /launch` + the
> `datsme_launch` cookie, `/partner/export`, `/partner/revoke`, `GET /api/datsme/bundle/{token}`
> with its single-successful-download token, the §5.4 SQLite store, host-signature fail-closed
> auth, and per-user scoping as a WHERE clause. On the host, `user.pet` and its three additive
> registry entries (`datsme_me/api/apps/dpp/pet_writeback.py`) are live and are what the pull
> checkout charges and adopts through — federated §6.4 says explicitly: do not delete them.
>
> **What was retired.** `SPEC_DATSPET_FEDERATED_SESSION` §6 consolidated the two purchase paths
> onto the PULL checkout: the user checks out on the host's own import page, authenticated by
> their own 30-day DatsMe session, and the host fetches the bundle server-to-server. DatsPet
> holds no credential that can trigger a charge. Gone with it: `POST /api/datsme/accept`, the
> writeback POST, the SDK retry queue, and the resync (`rsx`) launch. §4's diagram and §5.3 are
> that dead path. They are kept rather than deleted because the *payload shape* survived the
> transport: the host's `build_user_pet_import_payload` maps a pull item onto the same
> `pet_bundle.v1` body, so the handler cannot tell the two transports apart.
>
> **Corrected against both working trees on this date.** Every section that asserted current
> behaviour has been checked against `webui/datsme_integration.py`, `webui/db.py`, `web/src/`
> and `datsme_me/api/apps/dpp/`, and fixed where it had drifted — the §5.1 endpoint table (four
> live routes were missing, three rows were wrong), §5.4's scoping rule, §5.5's frontend,
> §6.2's dispatch signature and pricing, §7's expiry posture, §8's Phase 4, and §9's open
> questions. Corrections are marked **[2026-07-30]**; the original text is left in place
> wherever it is still the reason a thing is the way it is.
>
> **Living successors:** `docs/archive/SPEC_DATSPET_FRONT_DOOR.md` (sign-in, the bounce/mint plumbing),
> `docs/archive/SPEC_DATSPET_FEDERATED_SESSION.md` (session lifetimes, sign-out, owner scope,
> the purchase consolidation), `docs/SPEC_DATSPET_HOUSE_ADOPT.md` (the pull checkout and the
> export's `transfer` block), `docs/SPEC_DATSPET_CATALOG_PURCHASE.md` (the catalog surface),
> `docs/SPEC_MOTION_PROFILE_ADMIN.md` (the admin launch that reuses §5.1's `/launch`),
> `docs/RUNBOOK_DPP_E2E.md` + `scripts/e2e_design_a_pet.sh` (the runnable round trip).

**Status:** ✅ IMPLEMENTED + E2E-verified live · 2026-07-11 (Phases 0–3 done, both repos) ·
**CLOSED 2026-07-30**
**Repos touched:** `datsme-pet-factory` (this repo — the partner) and `datsme_me` (the host)
**Reference partner:** `datsme_personality` (imitate `app/api/datsme_integration.py`)
**Protocol:** DatsMe Partner Protocol v1 — `datsme_me/docs/keep_SPEC_DATSME_PARTNER_PROTOCOL.md`,
onboarding: `datsme_me/docs/GUIDE_DPP_PARTNER_ONBOARDING.md`
**E2E runbook:** `docs/RUNBOOK_DPP_E2E.md` · **registration:** `scripts/register_datspet.sh`

---

## 0. Implementation status (as-built, 2026-07-11)

All four phases shipped and verified end-to-end against a live DatsMe host +
Postgres. A test user designed pets on DatsPet and they appeared, playable, in
their DatsMe My Pets (source="partner"), credits charged.

**What was built beyond the original spec text:**
- **DatsMe-side entry point (§5.6, NEW):** a "🐾 Design a pet" button in DatsMe's
  My Pets (`web/src/app/[slug]/settings/pet/page.tsx`) that mints the launch via
  `POST /api/integrations/launch` and redirects to DatsPet — plus the in-place
  **consent dialog** (reuses `components/integrations/ConsentDialog.tsx`) for the
  first-use `pets.write` grant. The original spec assumed this button existed; it
  didn't, so it was added.
- **Registration bootstrap:** first registration uses `--skip-validation` because
  the host verifies the manifest signature against the secret it *generates*
  (chicken-and-egg on a cold partner). See §8 / runbook.

**Bugs found + fixed during live E2E:** DetachedInstanceError (capture `pet.id`
in-session), event-loop self-deadlock on the blocking writeback POST
(`run_in_threadpool` + 60 s timeout), long name rejection (truncate to
`MAX_NAME_LEN`), and the cross-origin launch cookie (`SameSite=None; Secure`,
§5.5). One non-DPP infra bug also surfaced: a relative `PET_FACTORY_COMFY_OUTPUT`
broke generation — fixed in `pet_env.sh`/`factory.py`.

**Security + scoping hardening (2026-07-12, post-review):**
- **Host-signed `/partner/*`:** export/revoke/pending were permissive (200 on a
  missing/wrong signature — a live data-loss vector on revoke). Now fail-closed
  (401 unless correctly host-signed over `<METHOD> <path> <ts>.`+body, ±5 min
  drift). Root-caused into the SDK: new `verify_host_signature()` /
  `sign_host_request()` (`datsme_partner_sdk.host_signature`) so it isn't
  hand-rolled per partner. *(The reference personality partner has the same hole
  — it should adopt the SDK helper too.)*
- **Per-user scoping:** generation now reads the launch cookie
  (`resolve_launch_identity`, which VERIFIES the JWT) and stamps
  `job.external_user_id`; list/keep/delete/preview/purge are scoped to the
  caller (own + unclaimed-local pets; never another user's). Accept enforces
  ownership (404 on another user's pet; 409 if already adopted elsewhere).

**Test coverage (actual, not aspirational):**
- Partner (`webui/tests/`, pytest): `test_partner_auth.py` (8 — host-sig
  fail-closed + no-mutation-on-401 + envelope binding), `test_scoping.py` (4 —
  two-user isolation, cross-user 404, purge-scope), `test_accept_fixes.py`
  (3 — SameSite=None cookie, expired-token permanent-401-not-queued).
  **[2026-07-30]** Still 9/4/3 files-and-counts, but two of them now guard the
  *absence* of the push path: `test_accept_fixes.py` asserts `POST
  /api/datsme/accept` 404s and `test_scoping.py`'s cross-user case moved off it.
  The DPP suite has since grown `test_pull_export.py` (17 — the export's
  `transfer` block, the ack channel, token minting), `test_federated_session.py`
  (19 — sign-out, renewal, owner scope, the ignored `rsx` claim),
  `test_front_door.py`, and `test_retry_and_token.py` (4 — purge scope after the
  queue's removal, single-successful-download).
- Host (`datsme_me/api/tests/`): `test_user_pet_writeback.py` (15 — full
  round-trip via the REAL `mint_launch_token`/nonce path + stub bundle server:
  happy adopt+charge, echo→409, both cap layers, bad-sha→400, house-full→409,
  no-credits→402-no-side-effects — asserted in the user's SQLite + ledger),
  `test_dpp_registry_consistency.py` (5 — the four-registry drift guard).
- Every fix above has a reversion-failing test (verified by reverting each).

---

## 1. Goal

A DatsMe user clicks **"Design a pet"** inside DatsMe → lands on the DatsPet site
already identified (no separate login) → designs a pet (the existing `/` Describe and
`/design` pages, with the built-in ~10 s preview) → clicks **Accept** → the pet is
transmitted to DatsMe and appears
in the user's **My Pets** (Settings → Pet, 3 slots, ★ active shows on profile) as a
real, playable pet — bytes copied into the user's own DatsMe storage
(adoption-as-copy), exactly as if uploaded via "Upload a pet bundle (.zip)".

DatsPet remains fully usable standalone (the personality app's principle:
*standalone first, integrated second — integration is an adapter layer, not a
dependency*).

**[2026-07-30] The goal still holds; two nouns in it moved.** (a) There is no
`/` Describe + `/design` pair any more — there is exactly ONE designer,
`/design/general`, the three-step archetype → design → animation flow of
`SPEC_PET_DESIGNER_FLOW`; `/design` 307s to it and is still where `/launch`
lands, so the deep-link target in §5.1 is unchanged. (b) The user no longer
clicks **Accept** on DatsPet. They keep the pet, then hand off to the host's own
import page (`{DATSME_PUBLIC_URL}/import/{slug}?items=…`) and check out there
against their own DatsMe session. Everything after that sentence — bytes copied
into the user's own storage, adoption-as-copy, identical to an upload — is
exactly what still happens, via the same `user.pet` handler.

## 2. What exists today (verified in code, not from the protocol spec's prose)

> **[2026-07-30] "Today" here means 2026-07-11 — this is the pre-build fact base**,
> deliberately left as it was. Its DatsPet paragraph ("No users, no SQLite, no
> partner endpoints yet") describes the starting line, not the current tree. The
> host paragraph is still broadly accurate — `service.py` remains the consolidated
> implementation — with the dispatch signature the exception (§6.2).

**Corrections to the protocol spec's module map:** the host implementation is
consolidated in `datsme_me/api/apps/dpp/service.py` (mint / authenticate / dispatch)
and `routes.py`. The files the spec names (`writeback.py`, `launch.py`, `registry.py`,
`health.py`) do not exist. Cite `service.py`.

### Host (datsme_me) — already built
- DPP platform: launch-token mint (`service.py:431`, 15-min TTL, HS256 JWT with
  claims `iss/sub/aid/pid/jti/iat/exp/cap/dpp[/rsx]`), one-time nonce burn
  (`burn_launch_nonce`, `service.py:732`), writeback endpoint `POST /api/integrations/result`
  (`routes.py:174`) with Stripe-style HMAC (`t=<ts>,v1=<hex>` over `f"{ts}."+body`,
  ±5 min drift), required `X-DatsMe-Idempotency-Key` (24 h idempotency cache),
  single atomic commit of burn+apply+cache.
- Target dispatch registry `_TARGET_HANDLERS` (`service.py:1017`) with two handlers:
  `identity.activity` (`service.py:838`) and `user.collection` (`service.py:929`).
  `apply_writeback` invokes every handler as **`handler(nonce, payload, visibility)`**
  (`service.py:1075`) — nothing else is passed; in particular the writeback body's
  `target_schema_version` is NOT read anywhere in the writeback path today.
  Capability gate per target (`REQUIRED_CAPABILITY_BY_TARGET`, `service.py:827`).
  Adding a target is registry entries + a handler — no engine changes (registry ✓).
- Manifest gate: `validate_manifest` REJECTS any manifest declaring a
  `protocol.schema_versions` target/version the host doesn't list in
  `SUPPORTED_SCHEMA_VERSIONS` (`manifest.py:55`; rejection at `manifest.py:211-219`,
  "the host has to ship the new version first — Decision 2, no coexistence").
- Partner SDK (`api/sdk/datsme_partner_sdk/`): `verify_launch_token`,
  `WritebackBuilder`, `sign_writeback`/`post_writeback`, `ManifestBuilder` +
  `sign_manifest_response`, capability helpers, SQLite retry queue
  (backoff 60 s → 24 h), `testkit` (mint test tokens), and a conformance CLI
  (`datsme_partner_conformance`, 17 checks).
- Registration: `api/scripts/register_partner_app.py --slug --name --launch-base
  --manifest-url` — probes manifest/export/revoke first, prints the HMAC secret once.
- Pets module: `validate_uploaded_bundle(zip_bytes)` (≤32 MB, zip-safety,
  manifest.animations) and `write_assets(user_db, pet_id=…, sheet_png=…,
  manifest_json=…, package_json=…, source=…, source_breed_id=…)`
  (`pet_assets_service.py:96`); the create-then-assets-then-ownership ordering to
  copy is `upload_my_pet` (`pet_routes.py:273-332`).

### Partner reference (datsme_personality) — the file to imitate
`app/api/datsme_integration.py`: `GET /partner/manifest` (signed, ETag/304),
`GET /launch?token=` (verify → httponly cookie `datsme_launch`, 30 min → 303 to the
activity page), `GET /partner/export/{user_id}`, `POST /partner/revoke`,
`GET /partner/results/{user_id}/pending` (resync), writeback build/post with the
transient-vs-permanent retry split, `writeback_acked_at` stamping, and post-success
redirect back to DatsMe.

### DatsPet (this repo) — already built
Frontend routes `/` (Describe), `/design` (with built-in preview pane), `/house`
(Next.js :19955); FastAPI backend (:19954);
draft/save model, per-pet folders in `webui/datspet_output/` with `pet.json`
records, bundle download endpoint. **No users, no SQLite, no partner endpoints yet.**

## 3. The two hard facts that shape this design

1. **Writeback bodies are capped at 64 KB** (`MAX_WRITEBACK_BODY_BYTES`,
   `service.py:57` → HTTP 413). A pet bundle is ~1–3 MB. **Pet bytes can never travel
   inside a writeback.**
2. **`user.collection` is a pointer store**, not an asset store: its `collection.v1`
   item schema is exactly `{external_id, title, public_url, content_type[, excerpt]}`
   (`service.py:891-926`) writing a `PartnerCollectionItem` row in shared Postgres.
   The protocol spec's "Adopt a Pet" example payload (`{pet_id, name, species,
   adopted_at}`) would fail its own host's validation, and a pointer would not make
   the pet *playable* in My Pets. **A real pet needs a net-new writeback target that
   copies bytes into the user's own DatsMe storage via `write_assets` (per-user
   SQLite — territory the collection handler never touches).**

**Decision: fetch-URL transport + new target `user.pet`.** The writeback carries a
small pointer (URL + checksum); the host fetches the bundle from DatsPet
server-to-server, validates it with the *existing* `validate_uploaded_bundle`, and
adopts it via the *existing* `write_assets` path. Bytes stay partner-hosted until
the moment of adoption-as-copy — consistent with the platform's pointer philosophy
AND with the pets module's copy-on-adopt philosophy. This is additive-only (new
target = new registry entry), which v1's compatibility rule allows.

## 4. Architecture

> **[2026-07-30] This diagram is the RETIRED push flow.** From `POST
> /api/datsme/accept` rightward it no longer exists. What replaced it: the user
> keeps the pet, DatsPet's house hands off to `{host}/import/datspet?items=…`,
> the host lists the items from the signed `GET /partner/export/{user_id}`,
> quotes each from its **declared** `pose_count` without fetching bytes, and on
> checkout fetches `transfer.pointer_url` server-to-server — the same
> SSRF-guarded fetch, the same `validate_uploaded_bundle`, the same
> `write_assets` adoption drawn below, entered from a different transport
> (`SPEC_DATSPET_HOUSE_ADOPT` §3; `SPEC_DATSPET_FEDERATED_SESSION` §6). The
> left-hand column — launch mint, cookie, design — is unchanged.

```
DatsMe (host :19994/:19995)                 DatsPet (partner :19954/:19955)
────────────────────────────                ────────────────────────────────
Settings→Pet "Design a pet" ─┐
  mint launch JWT (15 min)   │
  303 ────────────────────────►  GET /launch?token=…        (backend :19954)
                                   verify_launch_token (SDK)
                                   httponly cookie `datsme_launch` (30 min)
                                   303 → :19955/design?from=datsme
                                 user designs / previews / accepts
                                 POST /api/datsme/accept {pet_id}
                                   builds writeback:
                                   target user.pet · pet_bundle.v1
                                   payload = POINTER (≤64 KB):
                                     {activity_id, breed_id, display_name,
                                      bundle_url, bundle_sha256, size_bytes}
                                   sign + POST ────────────►
POST /api/integrations/result
  authenticate (HMAC, drift, JWT)
  idempotency cache · nonce burn
  _handle_target_user_pet:        ◄──── GET {bundle_url}  (server-to-server,
    origin allowlist = partner.base_url        one-time token, ≤32 MB)
    sha256 + size check
    validate_uploaded_bundle()
    create_pet + write_assets(source="partner")
    + ownership row  (same ordering as upload_my_pet)
  200 {redirect_to:/settings/pet} ────►  303 user back to DatsMe My Pets ★
```

## 5. Part A — DatsPet partner surface (imitate personality)

New adapter module `webui/datsme_integration.py` (one file, like the reference),
mounted on the existing FastAPI app. Uses `datsme_partner_sdk` (import path:
installed from `datsme_me/api/sdk/`; pin as a path dependency in dev).

### 5.1 Endpoints (conformance-required set)
| Route | Behavior |
|---|---|
| `GET /partner/manifest` | `ManifestBuilder(slug="datspet", display_name="DatsPet", base_url=$DATSPET_PUBLIC_URL)` + one activity (below) + `.request_capability("pets.write", justification="Deliver the pet the user designed into their DatsMe pet house.", required=True)` (+ optional `.request_capability("profile.read", justification="Greet the user by their DatsMe name while designing.")`) — NB `justification` is a REQUIRED kwarg on the SDK — + `.add_data_export(export_type="pets", schema="datspet_pets.v1")` + `.set_schema_version("user.pet", "pet_bundle.v1")` (SDK signature is `set_schema_version(target, version)`; `add_activity` params are keyword-only); signed via `sign_manifest_response`, ETag/304 support. 503 if `DATSME_HMAC_SECRET` unset. **This declaration only registers if the host ships fix B-1 first (§6.1).** **[2026-07-30]** The export declaration additionally opts into the pull — `transferable=True, ingest_target="user.pet", max_bytes=10 MB` (the host clamps to its own 32 MB ceiling). All three are required together and are a *request*: the host's registry independently decides ingestibility. |
| `GET /launch?token=` | `verify_launch_token` → 401 on `LaunchError`; map `aid` `design_a_pet` (400 `unknown_activity` otherwise); set cookie `datsme_launch` = `{token, user_id, activity_id, jti, capabilities}` httponly/samesite=lax/1800 s; 303 → `{FRONTEND_URL}/design?from=datsme`. ~~Honor `rsx` claim (resync: re-post an existing accepted pet, ownership + activity checks, then redirect).~~ **[2026-07-30]** As-built: cookie TTL is **3600 s** (§7) and SameSite is `none`+Secure (§5.5), the blob also carries `display_name` (the `nm` claim, cosmetic — re-read from the verified token), an `adm=true` claim additionally sets the `datspet_admin` cookie (`SPEC_MOTION_PROFILE_ADMIN` §2.3), a validated same-origin `?return=` path overrides the default landing (`SPEC_DATSPET_FRONT_DOOR`), and the launch **claims this browser's anonymous pets** for the arriving user (`claim_anon_owner`, federated §4.5c). An `rsx` claim is now **accepted and IGNORED** — honoring it would re-open the retired push path through a back door (federated §6.2a), so it is logged and dropped rather than 400'd. |
| `GET /partner/export/{user_id}` | All pets rows for that `external_user_id` (schema `datspet_pets.v1`), host-signature-verified request. **[2026-07-30]** This became the pull's product catalog: each item now also carries `pose_count` (the declared pricing basis) and, when the row can be transferred honestly, a `transfer` block `{pointer_url, sha256, size_bytes, content_type}` with a **freshly minted** bundle token per listing. Omitted — never half-built — when the row has no digest or no parseable pose count, because the host refuses to quote an item with no declared basis (`SPEC_DATSPET_HOUSE_ADOPT` §3.2). |
| `POST /partner/revoke` | `{user_id, action: delete\|anonymize}` → delete rows+folders / null `external_user_id`. |
| `POST /partner/imported/{user_id}` | **[2026-07-30] NEW — the pull's acknowledgment channel.** Host-signed `{item_ids: […]}`; stamps `writeback_acked_at` on each pet that user actually owns. A push learns the pet landed from its own 200; a pull is passive and never sees the outcome, so without this `in_datsme` would read false forever for a pulled pet. `activity_id` stays NULL — a pull has no activity and inventing one would put a lie in the record. |
| `GET /partner/results/{user_id}/pending` | ~~Accepted-but-unacked pets (`writeback_acked_at IS NULL`) for resync.~~ **[2026-07-30]** Returns `{"pending": []}`, always. The endpoint stays because the protocol requires partners to serve it, and an empty list is how DatsPet opts OUT of the host's resync channel without a host change. **That opt-out is load-bearing:** after the retirement the old query describes every kept-but-unadopted pet, so left alone the host would mint a resync launch for each one and re-open the path the consolidation closed (federated §4.6a). |
| `GET /api/datsme/session` | (frontend helper, not conformance) returns `{launched: bool, user_id?, capabilities?}` from the cookie so the UI can show "Designing for <DatsMe user>" and the Accept button. **[2026-07-30]** Grew into the frontend's whole identity surface, all built server-side so the browser never hardcodes a DatsMe origin: `integrated`, `signin_url`, `signup_url`, `import_url` (where the house's Adopt hands off), `signout_url` (the host logout bounce), `admin`, `display_name`, `cost`, and `token_expires_in` (from the **verified** `exp`) which drives the silent re-launch. It is also **the one endpoint that never 401s on a stale session** — a lapsed cookie answers `{launched: false, stale: true}`, because 401ing here would deadlock the renewal it exists to trigger (federated §4.7). |
| ~~`POST /api/datsme/accept`~~ | **[2026-07-30] RETIRED — the endpoint 404s and a test pins that.** Was: body `{pet_id}`, requires launch cookie, re-verifies token, mints a one-time bundle token, builds + posts the writeback, stamps `writeback_acked_at`, returns `{redirect_url}`; transient failure → SDK retry queue. Replaced by the pull checkout on the host, authenticated by the user's own DatsMe session (federated §6.2). |
| `GET /api/datsme/bundle/{token}` | Serves the pet's `pet.zip` per token (single-**successful**-download, 24 h expiry to cover the SDK retry window, constant-time compare). This is what `bundle_url` points at — NOT the regular `/api/pets/{id}/zip`. **[2026-07-30]** Unchanged and now the *only* way bytes reach the host; the token is burned in a `BackgroundTask` after the bytes are sent, so a failed transfer leaves it usable for the host's next attempt. The 24 h TTL no longer covers a retry queue — see §7. |
| `GET /api/datsme/signout` | **[2026-07-30] NEW** (federated §4.1). A navigation, not an XHR: clears all three DatsPet cookies and bounces to the host's `logout-launch`. |
| `GET /api/datsme/signed-out` | **[2026-07-30] NEW** (federated §4.4). The origin-translation hop — the host may only redirect to our registered API origin, so this is what forwards the browser to the frontend. |
| `POST /api/datsme/logout` | **[2026-07-30]** The local cookie-clear, kept as the non-navigational form. |

### 5.2 Manifest activity
```python
.add_activity(
    activity_id="design_a_pet",          # stable forever
    display_name="Design a pet",
    description="Design your own animated pet and adopt it into your house.",
    category="fun",
    activity_type="pet_design",          # net-new type; see Part B catalog note
    launch_cta="Design a pet on DatsPet",
    emoji="🐾", estimated_minutes=5,
)
```

### 5.3 Writeback body (`pet_bundle.v1`, pointer ≤ 64 KB)

> **[2026-07-30] RETIRED as a transport, SURVIVING as a shape.** DatsPet builds and
> posts nothing; there is no `WritebackBuilder` call and no retry queue in this repo.
> But the pull did not invent a second payload — the host's
> `build_user_pet_import_payload` maps a `datspet_pets.v1` export item onto exactly
> the body below (`activity_id: None`, `bundle_url` ← `transfer.pointer_url`, plus
> `pose_count` as the quote basis), so the `user.pet` handler receives the same shape
> either way and cannot tell which transport produced it. Read the payload spec as
> current and the posting/retry mechanics as history. The one clause with a live
> consequence is the last one: bundle tokens are single-**successful**-download, which
> is now what makes a failed *checkout* fetch retryable.
```python
WritebackBuilder(ctx)
  .target("user.pet", schema_version="pet_bundle.v1")
  .payload({
      "activity_id": ctx.activity_id,
      "breed_id":     pet.breed_id,
      "display_name": pet.display_name,
      "bundle_url":   f"{DATSPET_PUBLIC_URL}/api/datsme/bundle/{one_time_token}",
      "bundle_sha256": sha256(zip_bytes),
      "size_bytes":   len(zip_bytes),
      "source_pet_id": pet.id,           # for export/resync correlation
  })
  .build()   # idempotency_key defaults to ctx.jti — one accept per launch
```
Posted with `post_writeback` (SDK signs; `X-DatsMe-Idempotency-Key` = body key).

**Retry classification — two different splits exist in the codebase; DatsPet uses
both, each in its own place, deliberately:**
- **Initial Accept POST** (inline, our code): network error / 5xx / {408, 429}
  → enqueue in the SDK retry queue ("arrives automatically"). **401 → PERMANENT**
  (relaunch prompt), NOT queued — this is a deliberate divergence from the
  personality reference, which queues 401. The reference can, because its
  writeback fires seconds after launch so its token is never stale; DatsPet's
  writeback fires at the END of a multi-minute design session, so a 401 means
  the launch TOKEN expired — and the retry queue re-sends the SAME stored token,
  so queuing a 401 would retry-forever-and-never-deliver (a silent black hole).
  We surface "session expired — relaunch, your design is saved". Other 4xx (400
  `validation_failed`, 409 house-full, 402 insufficient credits) → permanent,
  surface the structured error. *(As-built: the Accept handler also re-verifies
  the cookie token locally BEFORE calling the host, so the common expiry case is
  caught instantly without a round-trip; the writeback-time 401 branch is the
  belt-and-suspenders for drift.)*
- **Queued drains** (SDK code, unmodified): `drain_due` (`retry.py:~135`) applies
  its own stricter rule — retries until 200, burns ANY 4xx except 401 as permanent
  (`attempts += 99`, operator looks). We accept that: a request that was transient
  at Accept time but comes back 4xx on drain is genuinely broken and should stop.
Note: a retried fetch needs a working bundle URL — the retry queue stores the
body verbatim, so bundle tokens must be *reusable until first successful
download*, then burned (single-successful-use, not single-request), and must not
expire while a writeback sits in the ≤24 h retry window (hence token TTL = 24 h,
matching the SDK backoff ceiling — consistent in §5.1 and §7).

### 5.4 DatsPet persistence — SQLite migration (prerequisite)
Move from `pet.json`-per-folder to **one SQLite DB** (`datspet.db`), mirroring the
personality app's shape and the earlier storage discussion:

- `pets(id, breed_id, display_name, created_at, draft, external_user_id NULL,
  datsme_activity_id NULL, writeback_acked_at NULL, sheet_png BLOB,
  manifest_json TEXT, package_json TEXT, bundle_zip BLOB)` — blobs in-DB matches
  DatsMe's own `pet_assets` pattern; index on `external_user_id`.
- `jobs(id, status, progress, message, created_at, external_user_id NULL)`.
- `bundle_tokens(token, pet_id, expires_at, downloaded_at NULL)`.
- Retry queue stays in the SDK's own `datsme_retry_queue.db`.

**Scoping rule:** when launched from DatsMe, generation/jobs/drafts/house are
filtered by `external_user_id`; standalone (no cookie) uses `external_user_id IS
NULL` — the local single-user mode keeps working unchanged. The API surface the
frontend uses does not change (the four test questions hold: new source of
identity, no engine forks).

**[2026-07-30] The three tables are as-built and still current** (`webui/db.py`;
plus `app_settings` and `ai_usage`, which other specs added). Two corrections:

- **`external_user_id IS NULL` is no longer what "not launched" means.** That
  read made every anonymous visitor share ONE pool — on a public deployment, one
  stranger's house. Anonymous work now belongs to a **per-browser anonymous
  owner** (`owner_scope.ANON_COOKIE`); `resolve_owner_scope` prefers the launch
  cookie unconditionally and falls back to that id, and a launch **claims** the
  browser's anonymous rows for the arriving user. This is still a WHERE clause
  and still not an engine fork — the identity source got one more case, not a
  branch (`SPEC_DATSPET_FEDERATED_SESSION` §4.5, the acceptance criterion that
  spec exists to pass).
- **The SDK retry-queue DB is gone with the push path.** `purge_drafts` lost its
  `not_pending` exemption along with it — after the retirement that clause
  matched every claimed pet and would have made claimed drafts unpurgeable
  forever (federated §4.6b, pinned by `test_retry_and_token.py`).

### 5.5 Frontend changes (small)

> **[2026-07-30]** The session read, the banner and the cookie note below are
> current — `web/src/lib/api.ts` is still the one adapter and still uses
> `localhost`. What changed is the action: there is no Accept button and no 402/409
> handling on the result card, because DatsPet no longer initiates a charge. The
> house's **Adopt** action calls the shared hand-off helper (federated §5.2), which
> `keep()`s the selected pets and navigates to `${session.import_url}?items=a,b,c`;
> price, credits and house-full all resolve on the host's checkout page now. A
> `session_stale` response anywhere triggers the silent re-launch (federated §5.3)
> instead of the "session expired — relaunch" copy below.

- `/design` and `/` read `GET /api/datsme/session`; when launched, show a banner
  ("Designing for your DatsMe profile") and swap the result card's primary action
  from "💾 Save to the pet house" to **"✓ Accept — send to my DatsMe (N credits)"**
  (calls `/api/datsme/accept`, then `window.location = redirect_url`). The cost `N`
  is read from `GET /api/datsme/session` (the backend fetches it from the host's
  cost/config once per launch) so the user sees the price before committing.
- On a 402 from Accept, the card shows the insufficient-credits message and keeps
  the draft; on 409 (house full), shows that verbatim.
- Keep Save-to-house as the secondary action (a user may want both — Save-to-house
  is free/local, Accept costs credits).
- **Launch cookie is `SameSite=None; Secure`** (`datsme_integration.py`), NOT lax:
  DatsPet's frontend (:19955) and backend (:19954) are different origins, so the
  frontend's `getDatsmeSession()` XHR is cross-origin and a lax cookie would never
  be sent → the Accept button would never appear. `None`+`Secure` rides
  cross-origin XHR (browsers treat `http://localhost` as a secure context).
  Configurable via `DATSPET_COOKIE_SAMESITE=lax` for a same-origin-proxy deploy
  (§8 Phase 4). CORS: `allow_credentials=True` + explicit frontend origin.

### 5.6 DatsMe-side entry point (host UI — the "Design a pet" button)
The flow starts in DatsMe, so DatsMe's **My Pets** page
(`datsme_me/web/src/app/[slug]/settings/pet/page.tsx`) gets a **"🐾 Design a
pet"** button next to "Adopt another pet" / "Upload a pet bundle". It:
- Calls `POST /api/integrations/launch {activity_id: "design_a_pet"}` (the same
  endpoint personality activities use) → `window.location = launch_url`.
- On `409 consent_required` (first use — `pets.write` is risk=medium, never
  auto-granted), fetches `GET /api/integrations/pending-consent/design_a_pet` and
  shows the shared **`ConsentDialog`** (required: pets.write; optional:
  profile.read). On approve → `POST /api/integrations/grant` → re-launch.
- Requires the activity to be in DatsMe's catalog first: the manifest reconciler
  (`apps/dpp/manifest.py:refresh_partner_manifest`) ingests `design_a_pet` +
  its capability requests after registration. This is what makes the launch
  endpoint resolve the partner for the activity.

## 6. Part B — DatsMe host additions (net-new, ~1 file + THREE registry entries)

`api/apps/dpp/pet_writeback.py` (new handler file) + three registry entries:

### 6.1 The three registry entries (all additive)
1. **`SUPPORTED_SCHEMA_VERSIONS["user.pet"] = {"pet_bundle.v1"}`**
   (`manifest.py:55`). Without this, DatsPet's manifest is REJECTED at
   registration — `validate_manifest` refuses any declared target/version the
   host doesn't list (`manifest.py:211-219`). This is the registration-time
   schema gate and **must ship before Phase 3 registration** (see §8).
2. `_TARGET_HANDLERS["user.pet"] = _handle_target_user_pet` (`service.py:1017`).
3. `REQUIRED_CAPABILITY_BY_TARGET["user.pet"] = "pets.write"` (`service.py:827`) —
   **new capability**, risk=medium (like `collection.write`) → always shown on
   the consent screen; one `Capability` entry added in `capabilities.py`.

### 6.2 The handler — real dispatch interface
`apply_writeback` calls every handler as **`handler(nonce, payload, visibility)`**
(`service.py:1075`) — there is no `partner`/`claims`/`schema_version` argument, and
nothing in the writeback path reads the body's `target_schema_version` today.
**Decision: no per-writeback schema check in the handler** — version enforcement
happens once, at manifest registration time, via the §6.1 gate (the alternative —
extending `apply_writeback` to thread `target_schema_version` through — modifies
shared engine code for all targets and is rejected as contradicting this spec's
additive-only stance; revisit only when a `pet_bundle.v2` actually exists).

**[2026-07-30] The dispatch signature changed, and for exactly this spec's
reason.** Handlers are now called as **`handler(ctx, payload, visibility)`** where
`ctx` is an `IngestContext(user_id, partner_slug, source_ref, activity_id,
granted_caps)` (`service.py:978`). A writeback arrives on a burned launch nonce; a
pull arrives on the user's own session and has **no nonce at all** — so the nonce
could not stay in the signature without either forking the engine per transport or
synthesizing a fake nonce, i.e. putting a lie in the record. `activity_id` is
`None` on a pull, which is why the echo-check below passes naturally instead of
being special-cased, and why `user.pet` is in `PULLABLE_TARGETS` while
`user.collection` is not (a target whose business key includes the activity cannot
be pulled — a registry rule, not a branch). The schema-version decision below
still stands: `pet_bundle.v2` does not exist. The handler itself lives in
`apps/dpp/pet_writeback.py` exactly as specified — it was never merged into
`service.py`.

`def _handle_target_user_pet(nonce, payload, visibility=None):`
1. Echo-check: `payload.get("activity_id") != nonce.activity_id` → 409
   `activity_mismatch` (copy the exact pattern from the identity handler,
   `service.py:852`; user identity likewise comes from `nonce.user_id`).
2. **Fetch guard:** `bundle_url` must be http(s) AND its origin must equal the
   registered `partner.base_url` origin (SSRF allowlist); follow no redirects;
   timeout 30 s; stream with a hard 32 MB cap (`PET_BREED_BUNDLE_MAX_BYTES`).
3. Verify `sha256(body) == payload.bundle_sha256` and `len == size_bytes`
   (else 400 `validation_failed`).
4. `parsed = validate_uploaded_bundle(body)` — the exact validator user uploads
   pass through today.
5. **Charge credits first (402 before any mutation).** Partner-designed pets cost
   credit points, like DatsMe Personality and AI usage. Reuse the existing charge
   path: read the cost from social-ledger config and `require_credits(...)` exactly
   as `_charge_adoption` does (`pet_routes.py:151-166`), but keyed on a **dedicated
   config key `credit_pet_design_cost`** (new; add to `social_ledger_config.py`
   next to `credit_pet_adoption_cost=100` / `credit_ai_vision_cost=5` /
   `credit_document_import_cost=2` — admin-tunable, default TBD by product). Charge
   BEFORE the fetch/validate/adopt writes so an insufficient-credits user gets a
   clean 402 with no side effects (the `_charge_adoption` docstring's invariant:
   credits gone iff pet created). This deduction commits atomically with the
   ownership row in the same Postgres commit (step 8), mirroring `create_my_pet`
   step 4 (`pet_routes.py:266-268`).
   **[2026-07-30] The cost is no longer flat.** `price_user_pet(social_db,
   pose_count)` is THE one pricing formula: `credit_pet_design_cost` plus
   `credit_pet_extra_pose_cost` per pose above the base count. Two callers, one
   function, deliberately — the checkout quotes it from the export's **declared**
   `pose_count` (no bytes fetched) and the handler charges it from the **fetched**
   bundle's real count, and the declaration is verified against the artifact at
   ingest (`pricing_basis_mismatch`) so the host never charges above the quote. If
   those were two expressions they would diverge the first time either config key
   moved.
6. Adopt with the `upload_my_pet` ordering (`pet_routes.py:273-332`): open the
   user's DB (`open_user_database_context`, defined `user_db.py:174`; the identity
   handler's call at `service.py:867` is the usage pattern to copy),
   `pet_service.create_pet(source="partner", …)` respecting
   `max_pets_per_user` (surface 409 `validation_failed` with a friendly detail if
   the house is full — checked BEFORE the credit charge so a full-house user is
   never charged), `write_assets(source="partner", source_breed_id=…)`, commit,
   then the Postgres ownership row + credit deduction.
   **`create_pet` required kwargs (`pet_service.py:206`): `breed_id, name,
   personality_profile` (plus optional `source`, `visibility`, `max_pets`).** A
   designed pet carries no personality profile, so the handler mirrors
   `upload_my_pet` exactly (`pet_routes.py:299-317`): `name =
   pet_service.validate_name(f"My {parsed['display_name']}")`,
   `personality_profile = copy.deepcopy(config.get("personality_defaults", {}))`.
   Note the source values differ per call, as in the upload path:
   `create_pet(source="partner")` but `write_assets(source="partner")` /
   `_write_ownership(source="partner")` — upload uses `"user_uploaded"` for
   `create_pet` and `"upload"` for the other two; pick one `"partner"`-family
   value set and keep it consistent. `breed_id`/`source_breed_id` come from the
   validated bundle (`parsed["breed_id"]`, from its `package.json`), NOT from the
   writeback payload, so a partner cannot spoof a breed id the bundle doesn't
   contain.
7. Return `{saved: true, pet_id, credits_charged, redirect_to: "/settings/pet"}` —
   the host wraps this and the partner redirects the browser; the DatsPet result
   card can show "N credits charged".

**Implementation lessons — found + fixed during the live E2E (2026-07-11):**
- **Capture `pet.id` as a plain str INSIDE the `open_user_database_context`
  block.** Accessing `pet.id` after the block (in the Postgres ownership write /
  log / return) raises `DetachedInstanceError` — the ORM instance is detached
  once the session closes, and `commit()` expires its attributes. Grab
  `pet_id = pet.id` right after `create_pet`.
- **Truncate the name to `MAX_NAME_LEN` (32) before `validate_name`.**
  Partner-generated display names are long ("Monkey With Bright Purple Fur And
  Black Hat"); `f"My {name}"` blows the 32-char cap and `validate_name` REJECTS
  (doesn't truncate), failing a valid adoption. Cap with `[:MAX_NAME_LEN]` first.
- **`max_pets_per_user` is platform config (12 in this deployment), not 3.** The
  spec's "3 slots" is the default; don't hardcode it — read the config.

**Partner-side (Accept path) lesson:** the writeback POST is a BLOCKING call and
the host synchronously calls back to fetch the bundle, so it must NOT run on the
event loop — offload with `run_in_threadpool` (an `async def` Accept that runs
the blocking POST inline self-deadlocks: the frozen loop can't serve the host's
bundle fetch). Also raise the SDK `post_writeback` timeout (10 s default is too
tight for fetch+validate+adopt; use ~60 s) so a success isn't misreported as
"queued".

Catalog note — **resolved**: `activity_type` has NO allowlist on the host. It is
a free `String` column (`dpp/models.py:122`) and `validate_manifest` checks only
presence, not value — so `activity_type="pet_design"` is accepted as-is. No
`collection_append` fallback needed.

## 7. Security & failure modes

> **[2026-07-30] Corrections to this section, in one place.** (a) The bundle
> token's 24 h TTL survives, but its *reason* changed: there is no retry queue to
> outlive, and the export mints a **fresh** token per listing, so the TTL now
> only has to cover the gap between a user opening the host's import page and
> checking out. (b) The launch-expiry bullet's remedy is superseded — nothing
> token-authenticated happens at the end of a build any more, so a long design
> session no longer needs a long token; it needs **renewal**. `session` reports
> `token_expires_in` and the client silently re-launches before the lapse, with a
> `?renewed=1` loop guard (federated §4.2/§4.3). The 60-min TTL stays.
> (c) 402/409 are no longer surfaced by DatsPet — the charge and the house-full
> check happen on the host's checkout page, which is also where the user sees the
> price, so "the user has already spent GPU time before we know they can't afford
> it" is now answered by quoting **before** the checkout rather than by a message
> on the result card. (d) The SSRF allowlist, the one-time nonce, the idempotency
> cache and the host-signature fail-closed rule are unchanged and still the
> perimeter.

- All the DPP invariants come free: HMAC on manifest + writeback, ±5 min drift,
  one-time nonce, idempotency cache, kill switch, fail-closed 401s.
- Bundle tokens: 128-bit random, single-successful-download, **24 h expiry**
  (matches the SDK retry queue's backoff ceiling so a queued writeback's fetch
  still works), bound to one pet; the bundle endpoint is exempt from any
  session logic.
- SSRF: host only fetches from the registered partner origin, no redirects.
- DatsMe down at Accept → SDK retry queue (up to 24 h); UI tells the user the pet
  will arrive automatically; resync (`rsx`) and `/pending` cover longer gaps.
- **Launch token/cookie expiry mid-design.** The launch JWT authenticates the
  writeback and is checked at Accept time; if it lapses, Accept 401s. **As-built
  fix: `LAUNCH_TOKEN_TTL` raised 15 min → 60 min** (`service.py`) so a design +
  ~3-min GPU build + review comfortably fits — 15 min was tuned for quick
  activities and a pet workflow outgrew it (this is what caused the real 401s
  markly.1 hit). The DatsPet cookie was raised to match (60 min). On genuine
  expiry, Accept surfaces a "session expired — relaunch, your design is saved"
  message (401, permanent, NOT queued — see retry classification §5.3); the pet
  survives as a saved local pet, so relaunch + re-Accept works. Replay stays
  bounded because the nonce is one-time.
- User's house full (3 slots) → 409 surfaced verbatim on the DatsPet result card
  (checked before the credit charge — a full-house user is never charged).
- **Insufficient credits → 402 at Accept.** The charge happens on the host in the
  writeback handler, so the user has already spent GPU time designing before we
  know they can't afford it. Mitigation: DatsPet's Accept button shows the cost up
  front (`credit_pet_design_cost` surfaced via the manifest/profile read or a small
  host cost endpoint), and the 402 is surfaced on the result card as "Not enough
  credits — the design is saved as a draft; add credits and Accept again." The
  draft is NOT purged on a 402 (design preserved for a retry after top-up). ←
  *this is why the charge lives at Accept, not at generation: generation is the
  free local step; the credit cost is the act of adopting into DatsMe.*
- GPU busy / generation failures: unchanged local behavior; DPP is untouched
  until Accept.

## 8. Phased implementation plan

*(All phases ✅ DONE + verified 2026-07-11. Details below kept as the build
record; ✅ markers note what actually shipped / differed.)*

**✅ Phase 0 — prerequisite refactor (DatsPet only, no DatsMe coupling):**
SQLite migration (§5.4) with `external_user_id` columns nullable; API unchanged;
all existing pages keep working. *Ship + verify standalone.*

**✅ Phase 1 — partner surface (DatsPet):** FIRST, install the SDK — it is NOT in
this repo's venv today: path-pin `datsme_partner_sdk` from
`datsme_me/api/sdk/datsme_partner_sdk/` (dev: `pip install -e` the sdk dir or
add it to `sys.path` via the same mechanism personality uses). Then
`webui/datsme_integration.py` with all §5.1 endpoints, testkit-minted tokens
(`make_test_launch_token(*, hmac_secret, user_id=…, activity_id=…,
partner_slug=…, capabilities=…, ttl_seconds=900)`) for local tests; frontend
session banner + Accept button. *Gate: conformance CLI passes all 17 recorded
checks — exact invocation: `python3 -m datsme_partner_conformance --base-url
http://localhost:19954 --slug datspet --secret <hmac>` (those are its only
flags; `--manifest-url` belongs to the registration script, not this CLI).*

**✅ Phase 2 — host additions (datsme_me):** the three §6.1 registry entries
(`SUPPORTED_SCHEMA_VERSIONS["user.pet"]`, `_TARGET_HANDLERS`,
`REQUIRED_CAPABILITY_BY_TARGET` + `pets.write` in `capabilities.py`) and the
`_handle_target_user_pet(nonce, payload, visibility)` handler with
fetch/validate/charge/adopt; host-side tests mirroring `test_sdk_roundtrip.py`
plus a full fetch round-trip against a stub partner. **Phase 2 MUST land before
Phase 3** — without the `SUPPORTED_SCHEMA_VERSIONS` entry, registration's
manifest probe rejects DatsPet's declared `user.pet/pet_bundle.v1`.

**✅ Phase 3 — registration + E2E (DONE — used --skip-validation bootstrap, see runbook):** `register_partner_app.py --slug datspet
--name "DatsPet" --launch-base http://localhost:19954/launch --manifest-url
http://localhost:19954/partner/manifest` (`--launch-base` → the stored
`launch_base_url`; the script probes manifest/export/revoke before committing);
paste the once-printed secret into `pet_env.local.sh` (gitignored); end-to-end: DatsMe → design →
preview → Accept → pet appears in My Pets → set ★ active → visible on profile.

**✅ Phase 4 — production posture (DONE, differently than sketched):** DatsPet
runs on public HTTPS — prod `pet.datsme.me` (:19954) and the staging twin
`pet-staging.datsme.me` (:29954), procedure in `deploy/CHECKLIST.md`, gated by
`scripts/verify_deployment.sh`. Three deltas from the sketch: the host is
`pet.datsme.me`, not `pets.`; frontend and backend are still **separate origins**
(static export + API vhost), so the launch cookie remains `SameSite=None; Secure`
and `DATSPET_COOKIE_SAMESITE=lax` stays the unused same-origin escape hatch; and
the retry-queue drain scheduler was never needed — the queue it would drain was
retired. Generation in prod runs `PET_GEN_BACKEND=pool` on a GPU-less box
(`SPEC_DEPLOY_PETDATSME_POOL`).

## 9. Open questions for review — **all closed [2026-07-30]**
1. ~~Credit charge for partner pets~~ **RESOLVED + SHIPPED: pets cost credit
   points. `credit_pet_design_cost` shipped with default `"100"` (matches
   adoption — a designed pet is an acquisition; admin-tunable, set 0 for free).**
   Charged at Accept only. Still open for PRODUCT to revisit: is 100 the right
   number, and should the cost be pre-authorized before the ~3-min build rather
   than only at Accept? (Current: charged at Accept; the button shows the cost up
   front via `DATSPET_DESIGN_COST` so it isn't a surprise.)
   **[2026-07-30] CLOSED — the "when" question dissolved with the push path.**
   The charge is not at Accept because there is no Accept: the user is quoted an
   exact price on the host's checkout page *before* anything is fetched, charged
   or written, and confirms there. The flat number also went away — pricing is
   `credit_pet_design_cost + extra poses × credit_pet_extra_pose_cost` (§6.2
   step 5), so a bigger pet costs more. Verified live: a 50-credit quote from the
   declared basis, charged 50 exactly once, and a re-checkout of the same pet
   quoted **0**. `DATSPET_DESIGN_COST` survives as an env override that only
   feeds the designer's price hint, not the charge.
2. ~~`activity_type` value~~ **RESOLVED (code-verified): no host allowlist —
   `activity_type` is a free String column (`dpp/models.py:122`), so
   `pet_design` is accepted; the `collection_append` fallback is unnecessary.**
3. Should Accept ALSO leave a `user.collection` pointer row (so the pet shows in
   any future "collections" UI), or is My Pets enough? (Proposed: My Pets only.)
   **[2026-07-30] CLOSED as proposed — My Pets only, and the reason hardened.**
   `user.collection`'s business key includes `activity_id`, which a pull does not
   have; that is precisely why it is **not** in `PULLABLE_TARGETS` while
   `user.pet` (keyed on `source_partner_slug, source_item_id`) is. Writing a
   collection row alongside would have re-introduced a push-only dependency into
   the one path that no longer pushes.
4. Draft retention when launched: per-user drafts currently purged on next
   generation — keep, or give DatsMe users a small persistent workshop?
   **[2026-07-30] CLOSED — kept, scoped.** A new generation still supersedes the
   caller's unsaved draft (`app.py:_purge_drafts(owner)`), but only **that
   caller's**: a launched user's Generate can no longer delete another user's or
   the local user's in-progress draft. The persistent workshop is the house — a
   kept pet is not a draft, and the hand-off `keep()`s before navigating, so a pet
   in a live checkout is `draft=0` and out of every purge scope.
5. Where DatsPet runs in production (Hetzner CPU box can't generate — the GPU
   queue/worker split from `archive/DESIGN_SPEC_HETZNER_LOCAL_GPU.md` applies to the
   generation path; the partner endpoints themselves are CPU-only).
   **[2026-07-30] CLOSED — answered by §8 Phase 4.** `pet.datsme.me` on a GPU-less
   Hetzner box with `PET_GEN_BACKEND=pool`; the bespoke queue/worker split was
   *not* built (`SPEC_DEPLOY_PETDATSME_POOL` §2 says do not), the shared
   `../shared_gpu_cpu` pool carries generation instead. The observation that the
   partner endpoints are CPU-only is what made the lazy-import posture in
   `CLAUDE.md` (§"The GPU-less posture") both possible and load-bearing.

## 10. Consistency checks (global engineering rules)
- *New variant without engine change?* ✓ `user.pet` is a registry entry; DatsPet's
  identity source is a nullable column, not a fork.
- *New feature without touching unrelated files?* ✓ one adapter file per side,
  plus three declared registry entries on the host (§6.1) — all additive; no
  existing handler or dispatch code changes.
- *Third-party integration without modifying owned paths?* ✓ adoption reuses
  `validate_uploaded_bundle`/`write_assets` unchanged.
- *Bug isolation?* ✓ standalone mode has zero DPP code in its path; kill switch
  and partner-disable isolate the integration end-to-end.
