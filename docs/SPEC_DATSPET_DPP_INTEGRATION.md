# SPEC — DatsPet as a DatsMe Partner App (DPP Integration)

**Status:** ✅ IMPLEMENTED + E2E-verified live · 2026-07-11 (Phases 0–3 done, both repos)
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

**Bugs found + fixed during live E2E** (all now covered by tests; see §6/§7):
DetachedInstanceError (capture `pet.id` in-session), event-loop self-deadlock on
the blocking writeback POST (`run_in_threadpool` + 60 s timeout), long name
rejection (truncate to `MAX_NAME_LEN`), and the cross-origin launch cookie
(`SameSite=None; Secure`, §5.5). One non-DPP infra bug also surfaced: a relative
`PET_FACTORY_COMFY_OUTPUT` broke generation — fixed in `pet_env.sh`/`factory.py`.

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

## 2. What exists today (verified in code, not from the protocol spec's prose)

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
| `GET /partner/manifest` | `ManifestBuilder(slug="datspet", display_name="DatsPet", base_url=$DATSPET_PUBLIC_URL)` + one activity (below) + `.request_capability("pets.write", justification="Deliver the pet the user designed into their DatsMe pet house.", required=True)` (+ optional `.request_capability("profile.read", justification="Greet the user by their DatsMe name while designing.")`) — NB `justification` is a REQUIRED kwarg on the SDK — + `.add_data_export(export_type="pets", schema="datspet_pets.v1")` + `.set_schema_version("user.pet", "pet_bundle.v1")` (SDK signature is `set_schema_version(target, version)`; `add_activity` params are keyword-only); signed via `sign_manifest_response`, ETag/304 support. 503 if `DATSME_HMAC_SECRET` unset. **This declaration only registers if the host ships fix B-1 first (§6.1).** |
| `GET /launch?token=` | `verify_launch_token` → 401 on `LaunchError`; map `aid` `design_a_pet` (400 `unknown_activity` otherwise); set cookie `datsme_launch` = `{token, user_id, activity_id, jti, capabilities}` httponly/samesite=lax/1800 s; 303 → `{FRONTEND_URL}/design?from=datsme`. Honor `rsx` claim (resync: re-post an existing accepted pet, ownership + activity checks, then redirect). |
| `GET /partner/export/{user_id}` | All pets rows for that `external_user_id` (schema `datspet_pets.v1`), host-signature-verified request. |
| `POST /partner/revoke` | `{user_id, action: delete\|anonymize}` → delete rows+folders / null `external_user_id`. |
| `GET /partner/results/{user_id}/pending` | Accepted-but-unacked pets (`writeback_acked_at IS NULL`) for resync. |
| `GET /api/datsme/session` | (frontend helper, not conformance) returns `{launched: bool, user_id?, capabilities?}` from the cookie so the UI can show "Designing for <DatsMe user>" and the Accept button. |
| `POST /api/datsme/accept` | Body `{pet_id}`. Requires launch cookie; re-verifies token; pet must exist. Mints a **one-time bundle token**, builds + posts the writeback (below), on 200 stamps `writeback_acked_at` + clears draft flag, returns `{redirect_url}` (DatsMe `redirect_to` resolved against `DATSME_PUBLIC_URL`); on transient failure enqueues the SDK retry queue and still returns the local success page state. |
| `GET /api/datsme/bundle/{token}` | Serves the pet's `pet.zip` per token (single-**successful**-download, 24 h expiry to cover the SDK retry window, constant-time compare). This is what `bundle_url` points at — NOT the regular `/api/pets/{id}/zip`. |

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
- **Initial Accept POST** (inline, our code): copy the personality partner's
  classification (`datsme_integration.py:~517-527`) — network error / 5xx /
  {401, 408, 429} → enqueue in the SDK retry queue and tell the user the pet will
  arrive automatically; any other 4xx (e.g. 400 `validation_failed`, 409
  `activity_mismatch`/house-full, 402 insufficient credits) → permanent, surface
  the structured error on the result card, do NOT enqueue.
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

### 5.5 Frontend changes (small)
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

- All the DPP invariants come free: HMAC on manifest + writeback, ±5 min drift,
  one-time nonce, idempotency cache, kill switch, fail-closed 401s.
- Bundle tokens: 128-bit random, single-successful-download, **24 h expiry**
  (matches the SDK retry queue's backoff ceiling so a queued writeback's fetch
  still works), bound to one pet; the bundle endpoint is exempt from any
  session logic.
- SSRF: host only fetches from the registered partner origin, no redirects.
- DatsMe down at Accept → SDK retry queue (up to 24 h); UI tells the user the pet
  will arrive automatically; resync (`rsx`) and `/pending` cover longer gaps.
- Launch cookie expired mid-design (>30 min) → Accept returns 401 with a
  "return to DatsMe and relaunch" message; the draft is preserved (drafts scoped
  to the user survive relaunch; the draft-purge rule becomes per-user).
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

**Phase 4 — production posture (LATER, not yet done):** public HTTPS for DatsPet
(e.g. `pets.datsme.me` behind one reverse proxy so frontend+backend share an
origin and the launch cookie is first-party), rate limits, retry-queue drain
scheduler, monitoring.

## 9. Open questions for review
1. ~~Credit charge for partner pets~~ **RESOLVED + SHIPPED: pets cost credit
   points. `credit_pet_design_cost` shipped with default `"100"` (matches
   adoption — a designed pet is an acquisition; admin-tunable, set 0 for free).**
   Charged at Accept only. Still open for PRODUCT to revisit: is 100 the right
   number, and should the cost be pre-authorized before the ~3-min build rather
   than only at Accept? (Current: charged at Accept; the button shows the cost up
   front via `DATSPET_DESIGN_COST` so it isn't a surprise.)
2. ~~`activity_type` value~~ **RESOLVED (code-verified): no host allowlist —
   `activity_type` is a free String column (`dpp/models.py:122`), so
   `pet_design` is accepted; the `collection_append` fallback is unnecessary.**
3. Should Accept ALSO leave a `user.collection` pointer row (so the pet shows in
   any future "collections" UI), or is My Pets enough? (Proposed: My Pets only.)
4. Draft retention when launched: per-user drafts currently purged on next
   generation — keep, or give DatsMe users a small persistent workshop?
5. Where DatsPet runs in production (Hetzner CPU box can't generate — the GPU
   queue/worker split from `DESIGN_SPEC_HETZNER_LOCAL_GPU.md` applies to the
   generation path; the partner endpoints themselves are CPU-only).

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
