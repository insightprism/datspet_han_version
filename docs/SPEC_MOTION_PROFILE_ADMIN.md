# SPEC — Motion-Profile Admin (role-gated CRUD for the movement registry)

**Status:** Design — **Rev.2** (2026-07-14), for review. An admin surface to create, edit,
duplicate, and delete motion profiles (`pet_factory/motion_profiles/*.json` + `registry.json`)
through a UI, gated by DatsMe's existing `system_admin` role. Builds on
**`docs/SPEC_MOTION_PROFILES.md`** (the movement layer this edits) and reuses the DPP launch
mechanism from **`docs/SPEC_DATSPET_DPP_INTEGRATION.md`**. Grounded against the working tree.

**Rev.2 — reconciled with `docs/SPEC_DATSPET_FRONT_DOOR.md`.** That spec is now the **owner of the
shared bounce/mint plumbing** (the DatsPet `/launch` `return` param and the host mint-and-redirect
helper); this spec **consumes** it and is a thin sibling: `require_system_admin` + an `adm` claim
over the same helper. Build the front door first (§8 note). Also corrected: the host dependency is
**`require_system_admin`** (`datsme_me/api/auth.py:356`), not `require_admin`.

**Author's intent (verbatim goal):** "I would like to have an admin page that allows for the
creation, edit, update and delete of each motion profile … pulling up an existing motion json
file, to do full CRUD. Automatic registration of new motion, edit and deletion. Duplicate of an
existing motion to edit. Make a link to this admin page in the tool bar. It is an admin page, so
should be accessible to people with admin role."

**Repos touched:** `datsme-pet-factory_wu` (the admin page + API + a loader reload hook) and
**one small `datsme_me` change** (an admin-launch endpoint that mints a launch token carrying an
`adm` claim for `system_admin` users — a thin wrapper over the shared mint helper the front-door
spec builds). No change to the partner SDK.

**Dependency:** this spec assumes **`docs/SPEC_DATSPET_FRONT_DOOR.md` ships first**. It provides
(a) DatsPet `/launch`'s validated `return` path param (the admin bounce sets `return=/admin/motions`),
and (b) the host shared mint-and-redirect helper (`login-launch` and `admin-launch` are two thin
wrappers over it). Building the admin bounce before the front door would mean building that plumbing
once here and refactoring it there — so the front door lands first.

---

## 0. The core decisions (read this first)

1. **No new auth system in DatsPet.** DatsPet has no login/accounts today — its only identity is
   the DatsMe launch cookie (`docs/SPEC_DATSPET_DPP_INTEGRATION.md`). DatsMe already has a proven
   admin system (`User.role='system_admin'`, `require_system_admin` in `auth.py`). We **reuse it** rather
   than hand-roll a password page guarding file writes — a hand-rolled login on a file-mutating
   surface is exactly the liability to avoid. The admin gate is an **`adm` claim in the launch
   JWT**, verified by the same HMAC path DatsPet already trusts for pet scoping.

2. **The editor is the guardian of the engine's content contract.** The motion loader
   (`pet_factory/motion_profiles/__init__.py`) and its guard test
   (`pet_factory/tests/test_motion_profiles.py`) define exactly what a valid profile is (§3). The
   admin **must not be able to write a profile the guard test would reject** — every save runs the
   identical validation server-side and refuses on failure. This keeps "editable by an admin" from
   ever meaning "can break the build or a live generation."

3. **This is a content editor, not an engine change.** It edits *data* (`*.json`), never the
   loader/engine. A new profile authored here is picked up by the existing resolver with zero code
   change — the same "engine reads the record and acts" boundary the whole motion layer rests on.

4. **Writes are only safe where the filesystem is writable and authored-from.** On the GPU-less prod
   web tier the package is a **read-only `--no-deps -e` install** (deploy spec Rev.6): a write there
   would mutate an install that a redeploy overwrites, and expose a file-write surface on the public
   host. So the admin's *write* endpoints are gated to **admin-launched sessions only**, and the
   intended authoring workflow is: **edit on a writable instance → the profile is a normal repo file
   → deploy it like any other content** (identical to the base-catalog curate-then-ship flow). §7
   details the prod posture and the two supported operating modes.

---

## 1. What a motion profile is (the contract the editor enforces)

Grounded in `pet_factory/motion_profiles/__init__.py` + `registry.json`. A profile is one JSON file
named `<key>.json`, indexed by one `registry.json` entry. The editor produces exactly this shape and
enforces exactly these rules.

### 1.1 File shape (`<key>.json`)
```json
{
  "key": "quadruped",
  "level": 3,
  "movement_class": "mammalian_quadruped",
  "keywords": ["dog", "cat", "..."],
  "poses": {
    "walk":  { "enabled": true,  "runtime_role": "active", "action": "walking", "suffix": ", ..." },
    "idle":  { "enabled": true,  "runtime_role": "rest",   "action": "sitting calmly", "suffix": ", ..." },
    "run":   { "enabled": true,  "runtime_role": "active", "action": "...", "suffix": ", ..." },
    "sleep": { "enabled": true,  "runtime_role": "timed",  "action": "...", "suffix": ", ..." },
    "sit":   { "enabled": true,  "runtime_role": "timed",  "action": "...", "suffix": ", ..." },
    "eat":   { "enabled": true,  "runtime_role": "timed",  "action": "...", "suffix": ", ..." },
    "jump":  { "enabled": true,  "runtime_role": "triggered", "action": "...", "suffix": ", ..." },
    "play":  { "enabled": true,  "runtime_role": "triggered", "action": "...", "suffix": ", ..." },
    "swim":  { "enabled": false },
    "fly":   { "enabled": false }
  }
}
```

### 1.2 Registry entry (`registry.json` → `profiles[]`)
```json
{ "key": "quadruped", "file": "quadruped.json", "label": "Four-legged mammal", "level": 3 }
```
Plus the top-level `"default"` key naming the fallback profile (currently `quadruped`).

### 1.3 Validation rules (the exact guard-test contract — a save that violates ANY is rejected)
Every rule below is already asserted by `pet_factory/tests/test_motion_profiles.py`. The admin's
server-side validator is the *same checks*, run before writing, so the on-disk state after any admin
operation would pass the guard test verbatim.

- **Canonical pose set (complete).** `poses` keys == `CANONICAL_POSES` exactly:
  `walk, idle, run, sleep, sit, eat, jump, play, swim, fly` — all ten present, no extras
  (`test_every_profile_declares_full_canonical_pose_set`). No inheritance: each file lists all ten.
- **walk + idle enabled.** Both `REQUIRED_POSES` must be `enabled: true`
  (`test_walk_and_idle_enabled_in_every_profile`).
- **Enabled poses are complete.** Every `enabled: true` pose has a non-empty `action` and a
  `runtime_role` ∈ `ALLOWED_ROLES` = `{rest, active, timed, triggered}`
  (`test_enabled_poses_have_action_and_valid_role`). A disabled pose may be just `{"enabled": false}`.
- **Level in range.** `1 ≤ level ≤ 4` (`test_valid_level_in_allowed_range`).
- **Key ↔ registry ↔ filename agree.** `file`'s `key` == registry `key` == `<key>.json`; `level`
  matches between file and registry entry (`test_every_file_parses_and_key_matches_registry`).
- **Keywords globally unique.** No keyword (case-insensitive) is claimed by two profiles
  (`test_keywords_unique_across_all_profiles`) — the classifier's determinism depends on it. The
  editor checks a new/edited profile's keywords against **all other** profiles and rejects a clash,
  naming the conflicting profile.
- **`movement_class` required + non-empty** (used by `pack_datsme_bundle`; the loader reads it).
- **`default` must resolve.** Deleting or renaming the profile named by `registry.default` is
  refused (`test_registry_parses_and_default_resolves` would break) — see §4.4.
- **`key` is a safe slug.** `^[a-z][a-z0-9_]*$` — it becomes a filename and a URL path segment, so
  the API also re-guards it (no traversal). Reject anything else at the form and the endpoint.

### 1.4 Backward-compat pin (must stay green)
`test_quadruped_walk_idle_reproduce_today_verbatim` asserts the `quadruped` walk/idle prompts are
byte-identical to today's. The editor does not special-case this — but a save that edits
`quadruped`'s walk/idle wording **will** trip that test. The UI surfaces a warning when editing the
`default` profile's required poses ("editing this changes the baseline every un-matched animal
uses"); it does not block (an admin may intend it), but the guard test remains the backstop.

---

## 2. Authentication & authorization (the `adm` claim)

### 2.1 The flow (the "bounce" model)
```
DatsPet toolbar: [Admin]  ── click ──▶  /admin/motions
   │
   ├─ has valid admin cookie?  ──yes──▶  render the admin page
   │
   └─ no ──▶  redirect to  https://datsme.me/api/integrations/admin-launch?return=/admin/motions
                  │  (DatsMe host — NEW endpoint; thin sibling of login-launch)
                  ├─ require_system_admin (session must be a system_admin) ─ 403 if not
                  ├─ <shared mint helper> + extra_claims={"adm": true}
                  └─ 303 redirect ──▶  https://pet.datsme.me/launch?token=<jwt>&return=/admin/motions
                          │  (DatsPet — /launch, already honors `return` per front-door §3.1)
                          ├─ verify_launch_token (existing HMAC path)
                          ├─ claims["adm"] is true?  ──▶ set datspet_admin cookie (this spec's addition)
                          └─ 303 ▶ /admin/motions  (the validated `return` path)
```

### 2.2 DatsMe host change (the one `datsme_me` edit — you deploy)
A single new endpoint, **a thin sibling of the front-door spec's `login-launch`** — the same shared
mint-and-redirect helper (SPEC_DATSPET_FRONT_DOOR §2.1), swapping the dependency and adding one claim:
```
GET /api/integrations/admin-launch?return=<path>
  - require_system_admin               # auth.py:356 — 403 for non-admins (NOT require_admin)
  - <shared helper>: resolve activity → partner, mint_launch_token(..., extra_claims={"adm": True})
  - 303 → the partner /launch URL with &return=<validated path>
```
- Reuses the front door's shared helper (activity-resolve + mint) and its `return`-validation rule
  (path-only, no `//`, no scheme). The **only** differences from `login-launch` are the dependency
  (`require_system_admin` vs. `get_current_user`) and `extra_claims={"adm": True}`.
- `mint_launch_token` gains an optional `extra_claims: dict | None` param — **specified in the front
  door spec** as the shared addition; this spec only *uses* it. The JWT already carries arbitrary
  claims via the claim set the SDK exposes as `raw_claims`, so **no SDK schema change** and no
  partner-side change to read it.
- Uses `activity_id="design_a_pet"` (the existing registered activity) — the `adm` claim, not the
  activity id, is the authority. (A distinct `pet.admin` activity is not required and would need
  partner-catalog registration; avoid it.)
- The endpoint mints an admin launch **only** for a live `system_admin` session — the trust root is
  DatsMe's own login + role, unchanged.

### 2.3 DatsPet verification (server-authoritative, every request)
- `/launch` already honors a validated `return` path (SPEC_DATSPET_FRONT_DOOR §3.1) — the admin
  bounce arrives as `…/launch?token=<jwt>&return=/admin/motions`. This spec **adds one thing** to
  that handler: after `verify_launch_token`, if `ctx.raw_claims.get("adm") is True`, also set a
  **separate admin cookie** `datspet_admin` (HttpOnly, SameSite=None;Secure in prod, ~1h TTL matching
  the launch token) whose value is the same verified token. A normal "Design a pet" launch never sets
  this cookie. (The `return` redirect itself is unchanged — it already lands the browser on
  `/admin/motions`.)
- `require_admin_launch(request)` (new helper): read `datspet_admin`, **re-verify the JWT**
  (never trust the cookie blob), assert `claims["adm"] is True`. On any failure → 401/403. This
  guards **every** admin API endpoint (§4) and the page's own data loads. Mirrors
  `resolve_launch_identity`'s "verify, don't parse" discipline (a forged/expired cookie falls back
  to *no admin*, never elevated).
- **The `adm` claim is the sole gate.** There is no separate DatsPet admin list — "who is an admin"
  is owned entirely by DatsMe's `role='system_admin'`. Revoking admin on DatsMe (or the token
  expiring, ~1h) revokes DatsPet admin.

### 2.4 The toolbar link
The DatsPet toolbar (`web/src/app/layout.tsx`) gains an **Admin** link → `/admin/motions`. (The
front-door spec owns the toolbar's other changes; this adds one link.) It is not hidden (no secret
URLs), because the page itself is gated: a non-admin who clicks it bounces to the host, fails
`require_system_admin`, and sees DatsMe's own 403 — never the editor. Recommended: render the Admin
link **only when a `datspet_admin` cookie is present** (the session endpoint can expose an `admin:
bool`), so non-admins don't see a link that just bounces to a 403 — the security does not depend on
hiding it, but the UX is cleaner.

### 2.5 Logout (shared with the front door)
The front-door spec's `POST /api/datsme/logout` (SPEC_DATSPET_FRONT_DOOR §3.3) already clears the
`datspet_admin` cookie alongside `datsme_launch`. This spec adds no separate logout — signing out of
DatsPet ends the admin session too.

---

## 3. Loader support the admin needs (small additions to the motion package)

The loader caches the registry + profiles in memory (`_REGISTRY`, `_PROFILE_CACHE`) and never
reloads — correct for the read-only runtime, but the admin must see its own writes. Two additions,
both in `pet_factory/motion_profiles/__init__.py`, pure-data, no ML:

- **`reload()`** — clear `_REGISTRY` and `_PROFILE_CACHE` under the existing `_LOCK` so the next read
  re-reads disk. Called after every successful admin write so `/api/motions`, the pose menu, and the
  next generation immediately reflect the change (no restart).
- **`validate_profile(raw: dict, *, registry, existing_key=None) -> list[str]`** — the §1.3 rules as
  a reusable function returning a list of human-readable errors (empty = valid). The guard **test**
  and the admin **endpoint** both call it, so "valid" means one thing in exactly one place. (The
  guard test is refactored to assert `validate_profile()==[]` for each shipped file — same coverage,
  single source of truth.)
- **`write_profile(raw, *, label) / delete_profile(key)`** — the file+registry mutation primitives
  (write `<key>.json`, upsert/remove the registry entry, keep `registry.json` sorted + stable), each
  validating before writing and calling `reload()` after. The API layer is thin over these.

These live in a new `pet_factory/motion_profiles/admin.py` submodule so the read path
(`__init__.py`) stays free of write logic; `__init__` re-exports `reload`/`validate_profile` for the
web tier.

---

## 4. DatsPet API (new — `webui/motion_admin.py`, an APIRouter)

Every endpoint depends on `require_admin_launch`. All read-only responses are safe to the admin only
(they expose full profile internals). Keys are re-validated against `^[a-z][a-z0-9_]*$` at the
boundary regardless of form validation.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/admin/motions` | Registry + a summary of every profile (key, label, level, movement_class, enabled-pose count, keyword count). Drives the list pane. |
| GET | `/api/admin/motions/{key}` | One profile's full JSON (the edit form's source). 404 if absent. |
| POST | `/api/admin/motions` | **Create.** Body = full profile + label. Validates (§1.3), writes `<key>.json`, adds the registry entry, `reload()`. 409 if key exists. |
| PUT | `/api/admin/motions/{key}` | **Update.** Validates, overwrites the file, updates the registry entry (label/level), `reload()`. 404 if absent. |
| DELETE | `/api/admin/motions/{key}` | **Delete.** Removes the file + registry entry, `reload()`. **Refused (409)** if `key == registry.default`, or if the key is still pinned by a live catalog entry (guard against orphaning `animal_catalog` pins — see §6). |
| POST | `/api/admin/motions/{key}/duplicate` | **Duplicate.** Body = `{new_key, new_label}`. Clones `{key}.json` under `new_key` (rewriting the `key` field), **clears the clone's `keywords`** (they must be unique — the admin re-adds non-conflicting ones), writes + registers + `reload()`. Returns the new profile for immediate editing. |

- **Validation errors → 422** with the `validate_profile()` error list, rendered inline by the form.
- **Every write is atomic-ish:** validate → write temp → rename → update registry → reload. A failure
  before the registry update leaves no half-registered file; the endpoint reports the failure.
- **Audit line:** each successful write logs `who` (the admin user_id from the token), the op, and the
  key (stdout, matching the app's existing `print(..., flush=True)` logging) so there's a trail of who
  changed which profile.

---

## 5. DatsPet admin UI (new — `web/src/app/admin/motions/page.tsx`)

A two-pane admin, styled with the existing app tokens (not a separate visual system).

- **Gate:** on mount, `GET /api/admin/motions`; a 401/403 triggers the bounce to
  `datsme.me/dpp/admin-launch?return=/admin/motions`. A brief "Checking admin access…" state, then
  either the editor or a redirect.
- **Left pane — profile list:** every registry profile (key, label, level, movement_class, N enabled
  poses). A **+ New profile** button and, per row, **Edit / Duplicate / Delete**. The `default`
  profile is badged and its Delete is disabled.
- **Right pane — the editor (strict schema-guided form):**
  - **Header fields:** `key` (slug-validated; locked when editing an existing profile — a rename is
    delete+create, offered explicitly), `label`, `level` (1–4 select), `movement_class`,
    `keywords` (tag input; live-checks uniqueness against other profiles and flags a clash inline).
  - **Pose rows:** the 10 canonical poses as fixed rows. Each: `enabled` toggle; when enabled,
    `runtime_role` (select: rest/active/timed/triggered), `action` (text), `suffix` (textarea).
    Disabled poses collapse to just the toggle. walk+idle can't be disabled (enforced + explained).
  - **Raw-JSON peek (read-only by default):** a collapsible panel showing the exact JSON that will be
    written, so an admin can eyeball it. (A future rev may make it editable; Rev.1 keeps writes
    form-driven to stay inside the schema.)
  - **Actions:** **Save** (POST/PUT; on 422 shows the validator's error list against the offending
    fields), **Duplicate**, **Delete** (confirm modal — shared `ConfirmModal`, never `window.confirm`,
    per the project UI rules), **Revert**.
  - **Live feedback:** non-blocking success/error via the shared toast pattern; blocking validation the
    admin must acknowledge via the confirm modal in OK-only mode.
- **Change-takes-effect note:** after a successful save the UI confirms "Live now — the pose menu and
  new generations use this immediately" (because the endpoint called `reload()`).

---

## 6. Cross-layer safety (interactions this must not break)

- **Catalog pins (`animal_catalog/catalog.json`).** A catalog entry pins a `motion_profile` key
  (SPEC_PET_DESIGNER_PLATFORM §4.2); the catalog guard test asserts every pin resolves. So **delete**
  refuses (409) when the target key is still pinned by any catalog entry, naming them — otherwise the
  catalog guard test would go red and curated animals would fall back to coarser motion. (Rename =
  delete+create carries the same check.)
- **Keyword uniqueness** is validated *across the whole registry* on every create/edit, so the
  classifier stays deterministic (§1.3).
- **The `default` profile** can be edited but not deleted/renamed, and editing its walk/idle warns
  about the backward-compat pin (§1.4).
- **Cache coherence:** `reload()` after every write means `/api/motions`, the design-page pose menu,
  and the next `make_pet_zip` all see the change with no restart. (In `pool` mode the *workers* resolve
  their own profiles from their own copy — see §7.2 for how an edit reaches generation there.)

---

## 7. Deploy posture & operating modes

### 7.1 Two modes, one gate
- **Local / writable instance (authoring):** `PET_GEN_BACKEND=local` (or any instance whose
  `pet_factory` is a normal writable checkout). The admin writes real files you then commit + deploy.
  This is the **intended authoring workflow** and mirrors base-catalog curation.
- **Deployed prod web tier (`--no-deps -e`, read-only-ish):** the admin page still gates on the `adm`
  claim, but **write endpoints refuse with a clear 409** ("this instance is not writable — author on a
  dev instance and deploy") unless an explicit `MOTION_ADMIN_WRITABLE=1` opt-in is set. Default-off so
  the public host never exposes a live filesystem-write surface, and so edits can't be silently lost on
  the next redeploy. Read/list is allowed (an admin can inspect prod's live profiles).

### 7.2 How an authored profile reaches generation
- **Web tier** picks it up immediately via `reload()`.
- **Pool workers** resolve profiles from *their own* installed `pet_factory` (the handler carries the
  pinned key; the worker loads it locally). So a new/edited profile is live end-to-end only once the
  **workers** have the file — i.e. after the normal deploy that ships `pet_factory` to the fleet
  (same node-first ordering the motion + catalog content already follow). The admin UI states this for
  writes on a pool-backed instance ("saved here; ships to the GPU fleet on the next deploy").
- This is why §0.4 frames the admin as **author-then-deploy**, not "hot-patch prod generation."

### 7.3 What deploys where
- DatsPet page + API + loader hooks: ride the normal DatsPet deploy (frontend rebuild + backend
  restart). No host dependency for the *code*.
- The `datsme_me` `/dpp/admin-launch` endpoint: a host deploy you run. Until it ships, the bounce
  target 404s and the admin page is unreachable — DatsPet degrades safely (no admin, no writes),
  never crashes.

---

## 8. Build order

**Prerequisite — `docs/SPEC_DATSPET_FRONT_DOOR.md` steps 0 + 3 shipped:** DatsPet `/launch` honors a
validated `return` path (front-door §3.1), and the host has the shared mint-and-redirect helper +
`extra_claims` on `mint_launch_token` (front-door §2.1). This spec's auth is a thin addition on top.

0. **Loader support** (§3): `admin.py` with `validate_profile` / `write_profile` / `delete_profile`
   / `reload`; refactor the guard test to consume `validate_profile`. *Gate: existing 16 motion tests
   still green via the shared validator; new unit tests for write/delete/duplicate + each rejection.*
   (Independent of the front door — can be built in parallel.)
1. **DatsPet admin cookie + gate** (§2.3): in the (front-door-extended) `/launch`, set `datspet_admin`
   when `adm` is true; add `require_admin_launch`. *Gate: a token without `adm` is refused admin; with
   `adm` unlocks; a forged/expired cookie → no admin.*
2. **DatsPet admin API** (§4): `webui/motion_admin.py`, all endpoints behind `require_admin_launch`,
   over the §3 primitives. *Gate: full CRUD + duplicate against a temp profiles dir in tests; delete
   refused for `default` and for catalog-pinned keys; invalid saves 422 with the error list.*
3. **DatsPet admin UI** (§5) + the toolbar Admin link. *Gate: create → edit → duplicate → delete
   round-trip in the browser on a local instance; pose menu reflects a new profile immediately.*
4. **Host admin-launch endpoint** (§2.2) — the one `datsme_me` change: a thin `require_system_admin`
   + `extra_claims={"adm": True}` wrapper over the front door's shared helper. *Gate: a `system_admin`
   bounce mints an `adm` token and lands on the editor; a non-admin gets 403 at the host; you deploy it.*
5. **Prod-posture guard** (§7.1): the `MOTION_ADMIN_WRITABLE` opt-in + the read-only refusal. *Gate:
   writes 409 on a non-writable instance without the opt-in; reads still work.*

---

## 9. Consistency checks (global engineering rules)

- **New variant without an engine change?** ✓ A new profile is a JSON file the existing resolver
  reads; the admin writes data, never engine code.
- **Things that change for different reasons live apart?** ✓ Read path (`__init__.py`) vs. write path
  (`admin.py`); the validator is the single shared definition of "valid".
- **Third-party/host integration without modifying owned paths?** ✓ Reuses DatsMe's role system via
  one additive host endpoint + an additive `extra_claims`; no SDK schema change, no partner-side read.
- **Bug isolation?** ✓ A bad admin save is caught by `validate_profile` before it touches disk; a bad
  deploy of a profile is caught by the guard test; the `default` + catalog-pin guards prevent
  orphaning downstream layers.
- **No new auth to secure?** ✓ The trust root stays DatsMe's login + `system_admin`; DatsPet stores no
  passwords and mints no identity of its own.

---

## 10. Open questions for review
1. **Rename UX** — Rev.1 makes rename = delete+create (key is the filename). Acceptable, or do you
   want an explicit atomic rename that rewrites the catalog pins that reference the old key too?
2. **Editable raw-JSON** — Rev.1 keeps writes form-driven (raw JSON is read-only preview). Want the
   raw editor to be writable (with the same server validation) in Rev.1, or defer?
3. **Prod writability** — is author-on-dev-then-deploy the right default (§7.1), or do you want live
   prod editing enabled (accepting the read-only-install caveat) behind the opt-in from day one?
4. **Audit depth** — stdout audit line (Rev.1) enough, or do you want a persisted admin-action log
   (who/when/what, queryable)?

---

### Appendix — grounding (verified 2026-07-14)
- Loader + validation constants: `pet_factory/motion_profiles/__init__.py`
  (`CANONICAL_POSES`, `REQUIRED_POSES`, `ALLOWED_ROLES`, `MAX_POSES`, `_REGISTRY`, `_PROFILE_CACHE`).
- The guard-test contract the editor must satisfy: `pet_factory/tests/test_motion_profiles.py`.
- Launch verify path DatsPet already trusts: `webui/datsme_integration.py`
  (`verify_launch_token`, `resolve_launch_identity`, `LaunchContext.raw_claims`).
- Host token minting + role system: `datsme_me/api/apps/dpp/service.py` (`mint_launch_token`),
  `datsme_me/api/auth.py` (`require_system_admin`, line 356), `datsme_me/api/social_models.py`
  (`User.role` = `user | system_admin | system`).
- Toolbar to add the link to: `web/src/app/layout.tsx`.
- Catalog pins the delete guard must respect: `pet_factory/animal_catalog/catalog.json`.
