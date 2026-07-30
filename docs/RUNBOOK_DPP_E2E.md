# RUNBOOK — DatsPet ↔ DatsMe DPP end-to-end (Phase 3)

This is the operator runbook for the one **live** phase of the DatsPet/DatsMe
integration: registering DatsPet as a partner and driving a full
launch → design → Accept → *pet in My Pets* round trip.

Phases 0–2 (SQLite migration, partner surface, host handler) are code +
verified in-repo. Nothing here changes code — it wires the two running services
together. Implementation reference: `docs/archive/SPEC_DATSPET_DPP_INTEGRATION.md`.

---

## 0. What you need running

| Service | Port (dev) | Start with |
|---|---|---|
| ComfyUI (GPU) | 19953 | `./start_comfyui_only.sh` (DatsPet repo) |
| DatsPet backend | 19954 | `./start_petmaker_backend_only.sh` |
| DatsPet frontend | 19955 | `./start_petmaker_frontend_only.sh` |
| DatsMe Postgres | 19993 | (already up — DatsMe's DB) |
| DatsMe API | 19994 | `datsme_me/start_backend_only.sh` |
| DatsMe frontend | 19995 | `datsme_me/start_frontend_only.sh` |

The DatsMe **host must be able to reach `DATSPET_PUBLIC_URL`** — it fetches the
pet bundle server-to-server during Accept. In pure-local dev,
`http://localhost:19954` works because both run on the same box. In production,
DatsPet needs a real reachable origin (see spec §8 Phase 4).

---

## 1. One-time DatsPet setup

```bash
cd <datsme-pet-factory>

# a. Install deps incl. the partner SDK (path dependency).
.venv/bin/pip install -r webui/requirements.txt
.venv/bin/pip install -e ../datsme_me/api/sdk/

# b. The DPP env is already in pet_env.sh (section 5). Confirm the URLs match
#    your setup; DATSME_HMAC_SECRET stays UNSET until after registration.
```

---

## 2. Register DatsPet (mints the HMAC secret)

Registration generates the secret server-side, then probes DatsPet's manifest
and **verifies its signature against that just-generated secret**. On a cold
first run DatsPet can't yet be signing with a secret it hasn't received — a
chicken-and-egg. So the first registration is done in bootstrap mode
(`--skip-validation`, exactly how the reference `datsme_personality` partner was
registered), then the secret is wired in and all ongoing signature checks pass.

```bash
# DatsPet backend must be running (step 0) so the manifest endpoint exists.
# First-run bootstrap: skip the signature probe.
DATSPET_SKIP_VALIDATION=1 ./scripts/register_datspet.sh
```

The script:
1. loads `DATABASE_URL` from `datsme_me/api/.env`,
2. runs `register_partner_app.py --slug datspet --launch-base … --manifest-url …`,
3. **prints the HMAC secret ONCE.**

Copy that secret. Then:

```bash
# Wire it into pet_env.local.sh (gitignored — secrets never go in pet_env.sh):
#   export DATSME_HMAC_SECRET="<the printed secret>"
$EDITOR pet_env.local.sh

# Restart the DatsPet backend so it signs with the real secret.
./start_petmaker_backend_only.sh
```

**Verify the handshake now works both ways** (the manifest the host will poll is
now signed with the shared secret):

```bash
# 17/17 means the partner surface is fully conformant.
.venv/bin/python -m datsme_partner_conformance \
  --base-url http://localhost:19954 --slug datspet \
  --secret "<the printed secret>"
```

> Re-registering later (after the secret is known) can use the **full** probe:
> pre-seed `DATSME_HMAC_SECRET`, then `./scripts/register_datspet.sh` with
> `DATSPET_SKIP_VALIDATION` unset. On a slug that already exists the script
> errors loudly and creates nothing (safe to re-run).

---

## 3. Make the activity appear in DatsMe's catalog

DatsMe's manifest reconciler polls the partner's `/partner/manifest` and ingests
its activities. After registration, trigger/await a manifest poll so the
`design_a_pet` activity lands in the catalog with
`partner_launch.partner_slug = "datspet"`. (Admin → Connected apps, or the
scheduler's next tick; see `datsme_me/api/apps/dpp/scheduler.py`.)

Confirm the activity is launchable:

```bash
# As a logged-in DatsMe user (needs the session cookie / auth the frontend uses):
#   POST /api/integrations/launch  {"activity_id": "design_a_pet"}
# → 200 with a launch URL, OR 409 consent_required (grant pets.write first).
```

A **409 consent_required** on first launch is expected — `pets.write` is
risk=medium, so DatsMe shows the consent screen. Grant it; subsequent launches
mint the token directly.

---

## 4. The end-to-end flow

1. **In DatsMe** (`http://localhost:19995`), as a logged-in user: open
   Settings → Pet (or Connected apps) and click **"Design a pet"**.
   → DatsMe mints a 15-min launch JWT and 303-redirects to
   `http://localhost:19954/launch?token=…`.
2. **DatsPet `/launch`** verifies the token, sets the httponly `datsme_launch`
   cookie (30 min), and 303s to `http://localhost:19955/design?from=datsme`.
3. **Design page** shows the banner *"Designing for your DatsMe profile"* and,
   on the result card, the primary button **"✓ Accept — send to my DatsMe
   (N credits)"** (N from `DATSPET_DESIGN_COST` / the host cost config).
   Design a pet as normal (describe → preview → generate; ~3 min on the GPU).
4. **Click Accept.** DatsPet mints a one-time bundle token, POSTs the pointer
   writeback (`target user.pet`, `pet_bundle.v1`) to
   `POST /api/integrations/result`.
5. **DatsMe host** authenticates (HMAC + drift + JWT), burns the nonce, runs
   `_handle_target_user_pet`: SSRF-guarded fetch of `bundle_url` from DatsPet →
   sha256/size check → `validate_uploaded_bundle` → charge
   `credit_pet_design_cost` (402 if insufficient) → `create_pet(source="partner")`
   + `write_assets` + ownership → returns `{redirect_to: "/settings/pet"}`.
6. **DatsPet** stamps the pet acked, clears its draft flag, and 303s the browser
   back to `http://localhost:19995/settings/pet`.
7. **In DatsMe → Settings → Pet:** the pet appears in a slot. Set it **★ active**
   → it shows on the profile, fully playable. ✅

---

## 5. Failure modes to expect (all handled)

| Symptom | Meaning | Where |
|---|---|---|
| Accept → 402 on the card | not enough credits; **design preserved as draft** | host charge step |
| Accept → 409 "house full" | 3/3 slots used; **never charged** | host, pre-charge |
| Accept → "will arrive automatically" | DatsMe was down; **queued** in the SDK retry queue | partner transient split |
| Launch → 401 "relaunch" | launch cookie > 30 min old | partner `/accept` |
| Manifest probe fails at registration | DatsPet not running / secret mismatch | step 2 |
| `capabilities.known` fails conformance | host missing `pets.write` | Phase 2 not deployed |

Retry-queue drain (Phase 4) is not automatic yet: to flush queued writebacks,
(RETIRED 2026-07-30 — there is no retry queue. The push writeback and its drain were deleted with the purchase consolidation; a pull has no queued delivery to retry. See `SPEC_DATSPET_FEDERATED_SESSION` §6.2.)

---

## 5b. Running the automated tests

No live services required (they use temp DBs / in-process pipelines), except the
host round-trip needs real Postgres up (:19993) + the `datsme_me/api/.env`.

```bash
# Partner surface (auth fail-closed, per-user scoping, cookie/expiry):
cd <datsme-pet-factory>
.venv/bin/python -m pytest webui/tests/ -q          # 15 tests

# Host writeback round-trip (mints via the REAL nonce path; stub bundle server):
cd <datsme_me>/api && set -a && . .env && set +a
PYTHONPATH="sdk:$(pwd)" python3 -m tests.test_user_pet_writeback     # 15 checks
# Four-registry drift guard:
PYTHONPATH="$(pwd)" python3 -m tests.test_dpp_registry_consistency   # 5 checks
```

> Note for anyone extending these: the host round-trip MUST mint launch tokens
> via `service.mint_launch_token` (creates the IntegrationNonce row). A
> testkit-minted token has no nonce and 401s at `burn_launch_nonce` regardless
> of correctness.

---

## 6. Rollback

The integration is additive and standalone-safe:
- **Turn it off partner-side:** unset `DATSME_HMAC_SECRET` and restart DatsPet —
  the manifest 503s, the partner surface goes inert, local design still works.
- **Turn it off host-side:** disable the partner row (admin), or remove the three
  `user.pet` registry entries. Existing partner-adopted pets are normal pets and
  keep working — nothing to migrate back.
