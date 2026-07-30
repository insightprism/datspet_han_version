# SPEC — DatsPet Federated Session (sign in, sign out, stay signed in) + one purchase path

> **CLOSED & ARCHIVED — 2026-07-30. Executed in full and verified on staging.**
>
> Every build step in §9 is done, and the two gates that decide it were run against
> `pet-staging.datsme.me`, not argued:
>
> **The acceptance criterion, in ONE browser.** sara signed in (6 pets) → signed out
> (anonymous house: **0**) → **wu signed in on the same browser and saw exactly his 11**,
> none of sara's, nothing marked claimable → sara returned and had her original 6
> byte-for-byte, with none of wu's leaked. That is the thing this spec was written for.
>
> **The full DPP round trip** (`scripts/e2e_design_a_pet.sh`, on the box): launch → cookie →
> archetype → preview → a real GPU build → claim + keep → the host quoted 50 credits from the
> declared basis without fetching bytes → **charged 50 exactly once** → **a re-checkout quoted
> 0** → the pet landed in the DatsMe house as `partner_datspet`. Also verified by hand: the
> silent re-launch (600 s → renewed to 3584, no login page) and its loop guard (with
> `?renewed=1` present it correctly did **not** renew again).
>
> **DEPLOYED TO STAGING ONLY.** Production is deliberately still at `fe8ba0c` — Rule 0 is
> satisfied (staging is ahead and verified), and the production deploy is a separate,
> explicitly-requested act. Nothing in this spec is waiting on it.
>
> **What this spec created and handed off, rather than left undone:**
>
> 1. **The designer's resume** — a three-minute build used to die on any navigation, which this
>    work found by signing out mid-build. Specified and built, but it is a designer concern, so
>    it lives in **`SPEC_PET_DESIGNER_FLOW` §8.3**, not here.
> 2. **The catalog purchase surface** — split to **`SPEC_DATSPET_CATALOG_PURCHASE.md`** and
>    **blocked on content, not code**: no sample bundles ship (`animal_catalog`'s catalog
>    animals are `cat` and `dog`, and the only sample zip in the tree sits under
>    `_candidates/`, which is not a catalog animal). Its Gate 0 is that content.
> 3. **Four dev-only assumptions in the E2E script**, each of which made the staging run this
>    spec asks for impossible: a hardcoded sibling path to the host repo, a mandatory local
>    ComfyUI probe on a GPU-less tier, `PYRUN` chaining `. .env` with `&&` (it exits 2 on a
>    box, so every host query silently returned nothing and the script blamed the user id), and
>    a filter on `source=='partner'` when the host writes `partner_<slug>`. All fixed. A gate
>    that cannot run is not a gate.
>
> **One behaviour to know, not a defect:** signing out revokes the DatsMe session row, but a
> DatsMe tab left open elsewhere can mint a new one within seconds. DatsPet's half is correct —
> row revoked, all three cookies cleared. Whether an open host tab should silently
> re-authenticate after a revoke is a host question.

**Status:** Design — **Rev.4** (2026-07-30), implementation-ready. Makes DatsPet behave like an ordinary
website with a federated identity provider: a user signs in, stays signed in until they choose
to leave, signs out for real, and a *second* user can then sign in on the same browser and see
**nothing of the first**. Along the way it removes the reason the session was ever load-bearing
for money, by consolidating **two** purchase paths into **one**.

Builds on **`docs/SPEC_DATSPET_FRONT_DOOR.md`** (which owns the bounce/mint plumbing this
extends) and **`docs/SPEC_DATSPET_HOUSE_ADOPT.md`** (which owns the pull checkout this
consolidates onto). Grounded against both working trees — see the appendix.

**This spec OWNS** (a) the host's **logout bounce** (§3.1), the third sibling of `login-launch`
and `admin-launch`; (b) DatsPet's **silent re-launch** renewal rule (§4.2); (c) the **owner-scope
model** — the retirement of the shared anonymous pool in favour of a per-browser anonymous owner
(§4.5); and (d) the **retirement of the push writeback as DatsPet's purchase path**, including the
resync back door (§6). It also owns the **shared hand-off helper** (§5.2) that every purchase
surface calls, including the ones specified elsewhere.

**Split out:** the catalog purchase surface is **`docs/SPEC_DATSPET_CATALOG_PURCHASE.md`** — it
depends on §5.2's helper and is blocked on content, not code (decision 12).

**Repos touched:** `datsme-pet-factory_wu` (signout endpoint, session fields, renewal, owner
scoping, Adopt rewiring, push-path deletion) and `datsme_me` (one GET logout bounce + one
extracted helper). No SDK change. No host-side deletion — see §6.4.

---

## Acceptance criterion (the one test this spec exists to pass)

> On one browser: **user A** signs in with DatsMe credentials, designs a pet, adopts it (paying
> credits), and signs out. **User B** then signs in on that same browser and sees **an empty
> house** — none of A's pets, claimable or otherwise — designs their own pet, and buys it. A
> then signs back in and still has exactly their own pets.

Every gate in §9 is subordinate to this one. **A 303 landing on the right page proves nothing.**
Rev.1 could not pass this test as written; §4.5 is why, and is the largest change in Rev.2.

---

## What changed in Rev.4 (implementation-readiness pass on Rev.3)

Rev.3's five changes were each re-checked against both trees and **all five validated** — the
injected-`Response` cookie-drop, the `not_pending`/`claim` coupling, `revoke_user`'s `anonymize`,
the citation fixes, and the catalog split (confirmed: catalog animals are `cat` and `dog`, the only
sample zip in the tree is `animal_catalog/_candidates/cat/samples/snowleopard.zip`, and no
`<animal>/samples` directory exists, so `list_samples` returns `[]` for both). Rev.4 changes only
what an implementer would have hit on day one.

| # | Change | Why |
|---|---|---|
| 1 | **§4.5 (c) is a sweep across THREE owner-stamped stores, keyed by owner id** — not a claim of a pet-id list. New §4.5 (d) defines the claim-handler registry. | Rev.3 claimed pets only. **References** are owner-stamped in a JSON sidecar (`app.py:696-725`, visibility at `:729-734`), so signing in mid-design orphans the designer's own reference and `/api/reference/{id}.png`, `preview_design`, and `start_job` all 404 (`app.py:1198`, `:1501`) — on the exact flow the front door invites. **Jobs** capture the owner at submit (`app.py:1542`) and stamp the finished pet from it (`app.py:595`, pool path `:478`), so signing in during a ~3-min build yields a pet the signed-in user cannot see. Neither is reachable by a pet-id list: at launch there is no list. |
| 2 | **§4.5 (a) gains an exclusion set and a cacheability rule.** | `/api/datsme/bundle/{token}` is server-to-server (`datsme_integration.py:823`) but is **not** under `/partner/`, so Rev.3's single prefix test would have hung a `Set-Cookie` on the host's bundle fetch. And a `Set-Cookie` on a `Cache-Control: public` response is a shared anon id if anything caches it — `app.py:1378`, `:1405` are public. The codebase already reasons this way: `_IMMUTABLE_ASSET_CACHE` is `private` precisely so *"never a shared proxy that could serve another user"* (`app.py:1748-1750`). |
| 3 | **New §4.7 — the `session_stale` contract**, plus §5.3's single client interceptor. | Rev.3 said "callers raise 401" without saying which. `GET /api/datsme/session` **must not** 401: it is the endpoint that tells the frontend to renew, so a 401 there deadlocks the renewal it is supposed to trigger. Image endpoints must keep their 404 posture or an `<img>` hangs. |
| 4 | **§4.2 cites the host's validator too** (`routes.py:36-42`, `:45-55`). | The `?renewed=1` marker traverses the **host's** `_safe_return` before DatsPet's `_safe_return_path`. Verified: the host charset is the same `/[A-Za-z0-9/_\-?=&.]*` and `_append_return` quotes with `safe='/?=&'`, so the marker survives — but the spec was resting that on the wrong validator. |
| 5 | **§4.5 states that `ANON_COOKIE` survives launch** and dies only at sign-out. | The hand-off's claim backstop (§2.4 step 1a) needs `from_owner`, and a row can land microseconds after the launch sweep. Clearing the anon cookie at launch would remove the only key that reaches those rows. |

---

## What changed in Rev.3 (validation pass on Rev.2)

Rev.2's seven changes were each checked against both trees and **all seven validated** — the
owner-scope defect (§4.5), the `rsx` back door (§6.2a), the backend-origin mismatch (§3.1.4), the
claim-vs-keep correction (§5.2), the `?renewed=1` guard, and the silent-non-offer rows are all
confirmed by the code they cite. Rev.3 changes only what that validation found missing.

| # | Change | Why |
|---|---|---|
| 1 | **§4.5 (a) mints the anon id in middleware**, not on an injected `Response`. | FastAPI merges an injected `Response`'s cookies **only when the handler returns a non-Response value**. `/api/reference/{id}.png` is explicitly *"Owner-scoped"* and returns a raw `FileResponse` (`app.py:1095-1113`), so Rev.2 would have dropped the `Set-Cookie` there, minted a *different* id on the next request, and orphaned the user's work. |
| 2 | **§4.6 also deletes `purge_drafts`' `not_pending` clause** (`db.py:357-359`). | `claim_unowned_pets` **sets `datsme_activity_id`** (`db.py:462`), so once §4.5 (c) claims at launch, every claimed-but-unadopted draft matches `(datsme_activity_id IS NOT NULL AND writeback_acked_at IS NULL)` and becomes **unpurgeable forever**. Rev.2 retired the pending *list* but left the same retired semantics encoded in the purge guard — and its own migration note leaned on a startup purge that §4.5 (c) would have disabled for exactly those rows. |
| 3 | **§4.5 (b) adds `revoke_user`** to the lockstep list. | Its `anonymize` action sets `external_user_id=NULL` (`db.py:478-483`) and documents the rows as *"standalone/orphaned"*. Under exact-match on an integrated box they become invisible to everyone. A consumer of the NULL rule that Rev.2's sweep list did not name. |
| 4 | **The catalog purchase surface is split out** into `docs/SPEC_DATSPET_CATALOG_PURCHASE.md`; Rev.2's §2.5 and §5.4 are gone, Rev.2's §2.6 became §2.5, and build step 10 is removed. *(Rev.4 note: §5.4 exists again as "Nothing to purge from browser storage", shifted down by the new §5.3 — it is not the deleted catalog section.)* | Rev.2's backend claims were all correct, but **no sample bundles ship**: `_samples_dir` resolves `_DIR/<animal>/samples` gated on catalog membership (`animal_catalog/__init__.py:160-164`), the catalog animals are `cat` and `dog`, and the only sample zip in the repo sits under `_candidates/cat/samples/`, which is not a catalog animal. `GET /api/catalog` returns `samples: []` today, so the section's own guard test would pass on an empty set — a false green. Blocked on content, not code, and the acceptance criterion does not depend on it. |
| 5 | Minor: `api/auth.py:68` (not `:56`) for the `samesite: "lax"` literal; §0.9 notes that the checkout **page** and the checkout **API** are different paths. | Citation accuracy, and a reader could otherwise conflate `/import/datspet` with `/api/integrations/import/datspet`. |

---

## What changed in Rev.2 (for reviewers of Rev.1)

| # | Change | Why |
|---|---|---|
| 1 | **New §4.5 — owner scope.** The anonymous pool is per-browser, not global; `_scope_clause` stops unioning `NULL` into every signed-in user's view; an expired launch cookie fails closed instead of falling back to standalone. | Rev.1's step-5 gate was unreachable: `db.py:315` shows every signed-in user *every* unowned pet, marked `claimable` (`db.py:301`). Rev.1 §7.5 asserted the opposite. |
| 2 | **New §6.2a — the resync back door.** `_post_pet_writeback` has a second caller Rev.1 never listed (the `rsx` branch at `datsme_integration.py:243-252`, fed by the host's `sync-pending` mint at `routes.py:293`). | Rev.1's deletion list would have left a dangling caller, and a kept-but-unadopted pet would have been advertised as "pending" and pushed — charging without a checkout, through the very door §6 closes. |
| 3 | **§3.1 step 4 rewritten** — the logout bounce returns to a *DatsPet backend path*, not to the partner origin's `/`. | `partner_origin(launch_base_url)` is DatsPet's **backend** origin (`datsme_integration.py:133-137` says so outright). In dev that is :19954, not the :19955 landing. Prod hides it; dev breaks. |
| 4 | **§2.4 / §5.2 corrected** — the hand-off is claim-*and*-keep, in one shared helper. | Rev.1 said `keep`; the house actually calls `claimPets` (`house/page.tsx:139-147`). They fix different preconditions and both are needed. |
| 5 | **New §2.6 / §5.4 — buy from the catalog.** *(Rev.3: split out to `SPEC_DATSPET_CATALOG_PURCHASE.md`.)* | It is half of the stated goal and Rev.1 did not mention it. The backend already exists (`app.py:1408`); only the surface is missing — and, Rev.3 found, the content too. |
| 6 | **§4.2 renewal guard** is a return-path query marker, not a cookie. | Removes two constants and a TTL to tune; `_safe_return_path` already admits `?` and `=` (`datsme_integration.py:101`). |
| 7 | §2.5 gains the two silent-non-offer failure rows; §7.5 corrected. | A pet that cannot be quoted is skipped by the host with no user-facing reason (`import_routes.py:238-244`). After §6 that is the *only* way a purchase can fail to appear. |

---

## 0. The core decisions (read this first)

1. **Federated login already works and is not changed.** The flow the author describes — land on
   DatsPet, sign in with DatsMe credentials on DatsMe's page, route back verified — is fully
   built. `_login_launch_impl` bounces a signed-out caller to the host's login page and resumes
   (`datsme_me/api/apps/dpp/routes.py:156`). It is *invisible today only because the host session
   is alive*, so `if user is None` never fires. **Nothing to build here. §2.1 documents it as the
   baseline the rest of the spec assumes.**

2. **The missing half is logout, and it must be a top-level navigation.** DatsPet's
   `POST /api/datsme/logout` clears only DatsPet's own two cookies
   (`webui/datsme_integration.py:530`); it cannot touch the host's session cookie on another
   origin. So the browser must *visit* the host to be signed out of it. This is the first cause
   of "only one user can use the browser at a time": sign-out leaves the host session intact, so
   the next sign-in silently re-mints the same user.

3. **The second cause is the shared anonymous pool, and it is not a session bug at all.**
   `_scope_clause` gives a signed-in caller `external_user_id IS NULL OR external_user_id = me`
   (`db.py:310-315`), and `list_saved_pets` marks every unowned row `claimable` (`db.py:301`).
   So user B, freshly signed in, sees every pet any anonymous visitor ever kept — and may claim
   and buy them. Fixing logout alone does **not** produce an empty house for B. §4.5 owns this.

4. **The GET logout bounce is authenticated by the partner-signed launch token, not by a
   secret.** A GET that ends a session is otherwise a CSRF vector (any page could embed it). The
   caller must present the launch JWT it already holds; the host verifies it with the partner's
   `hmac_secret` and checks `pid == partner.slug` — the exact primitive already used for
   writeback verification (`service.py:802`). This is OIDC's `id_token_hint` pattern, assembled
   from parts already in the tree. **Expiry is deliberately NOT enforced on this path** (§3.1):
   logout grants no privilege, and refusing to log out a user whose token just lapsed is the
   worst possible failure mode.

5. **Nobody is logged out after 60 minutes — that was never the DatsMe login.** Three distinct
   lifetimes exist (§1). The DatsMe session is **720 h / 30 days, sliding** (re-minted every 24 h;
   `datsme_config.py:76`, `:82`). Only DatsPet's *copy of the assertion* expires at 60 min.

6. **Do not extend `LAUNCH_TOKEN_TTL`. Renew it invisibly instead.** A long-lived launch token
   breaks **revocation propagation**: sign-out-everywhere, a disabled account, or credential
   rotation on the host would leave DatsPet serving the old user for weeks. The fix is **silent
   re-launch** (§4.2) — when the token has lapsed but the host session is alive, bounce through
   `login-launch` and return instantly with no prompt. Net effect is exactly the author's ask:
   *signed in until you choose to sign out*, bounded by the host's own sliding 30 days.

7. **An expired launch cookie must fail closed, never fall back to "standalone".** Today
   `resolve_launch_identity` returns `None` for *both* "no cookie" and "cookie present, token
   unverifiable" (`datsme_integration.py:314-330`). Those are different states and the collapse is
   load-bearing: at minute 61 a signed-in user's next pet is written with `external_user_id`
   unset (`app.py:973`, `:1195`, `:1420`), i.e. straight into the pool decision 3 describes.
   **The session lapse manufactures cross-user-visible pets.** §4.5 splits the states.

8. **The host is already the sole authority on money — the author's proposed flow is the one
   that exists.** DatsPet never asserts a price or a balance. The host prices from the **fetched
   bundle's manifest, never a partner claim**, refuses to charge above what it quoted, checks
   house-full *before* charging, and 402s before any mutation
   (`pet_writeback.py:315-362`). `pet_design_cost()` on the DatsPet side is display-only and
   documents itself as best-effort (`datsme_integration.py:571`). A leaked launch token cannot
   drain a balance or redirect value anywhere; the worst it can do is adopt a pet into that same
   user's own house, keyed at-most-once.

9. **Therefore: one purchase path, and it is the pull checkout.** Two paths exist today (§6.1).
   The **pull** — `GET/POST /api/integrations/import/{partner_slug}` (`import_routes.py:199`,
   `:269`) — already does precisely what the author describes: authenticated by the user's own
   30-day DatsMe session, it quotes without fetching bytes, shows the price the host is then
   *bound* to, verifies the echoed `sha256` + `quoted_credits` as a **binding checkout**, calls
   `require_credits` (402 on insufficient funds), charges from the bytes, and notifies DatsPet.
   DatsPet's house already hands off to it (`web/src/app/house/page.tsx:147`). **Adopt becomes a
   link into that same checkout, and the push writeback is retired as a purchase path.**

   *Two different paths, easily conflated:* `import_url` → `{DATSME_PUBLIC_URL}/import/datspet` is
   the host's **Next.js checkout page** (`datsme_me/web/src/app/import/[partner]/page.tsx:9`
   documents the `?items=` shape); `/api/integrations/import/{slug}` is the **API** that page
   calls (`import_routes.py:47` sets the `/api/integrations` prefix). DatsPet navigates to the
   page and never calls the API.

10. **Retiring the push means retiring what *feeds* the push, not just the POST.** The resync
    channel exists to re-deliver a writeback that never landed: the host's `sync-pending` asks
    DatsPet what it never acked (`routes.py:243`), mints an `rsx` launch token per pending item
    (`routes.py:282-293`, `service.py:645`), and DatsPet's `/launch` short-circuits into
    `_post_pet_writeback` (`datsme_integration.py:243-252`). DatsPet's pending list is
    `writeback_acked_at IS NULL AND datsme_activity_id IS NOT NULL` (`db.py:384-393`) — which,
    once nothing is ever pushed, describes **every kept-but-unadopted pet**. Left in place, the
    consolidation would be undone by its own recovery path. §6.2a closes it, with no host change.

11. **The consolidation is what makes the session question easy.** Once purchases run on the pull
    channel, token expiry can never cost a user a purchase, because purchases do not use the
    token. "So long as the user is logged in, they can buy" becomes literally true — the checkout
    authenticates against the host's own session. Silent re-launch drops from a *correctness*
    requirement to a UX nicety, and the constraint documented at `datsme_integration.py:66-71`
    ("the cookie must outlive the JWT the writeback carries, because designing can take many
    minutes") **dissolves** — nothing token-authenticated happens at the *end* of a build any
    more (§4.3).

12. **The catalog is a second entrance to the same checkout — and it is split out.** Rev.2
    specified it here; Rev.3 moved it to **`docs/SPEC_DATSPET_CATALOG_PURCHASE.md`** for one
    reason: **no sample bundles ship today.** `_samples_dir` resolves `_DIR/<animal>/samples` and
    is gated on catalog membership (`animal_catalog/__init__.py:160-164`); the catalog animals are
    `cat` and `dog`; the only sample zip in the tree is under `_candidates/cat/samples/`, which is
    not a catalog animal. `GET /api/catalog` therefore returns `samples: []` for every animal, so
    the surface would ship with nothing to sell and its guard test would pass on an empty set — a
    false green. It is blocked on **content, not code**, and the acceptance criterion does not
    depend on it. What stays here is the part it consumes: the shared hand-off helper (§5.2) and
    the owner scope (§4.5), so that spec adds a page and no checkout logic.

13. **Identity is stamped in three stores, so "claim" is a sweep, not a list.** Pets carry it in a
    column, references in a JSON sidecar (`app.py:696-725`), and jobs in memory plus a row
    (`app.py:1542`, `db.py:495`). Every one of them is read for access control, and every one of
    them is written *before* the user has signed in — that is what "design first, sign in to adopt"
    means. So the moment of sign-in must move all three at once, keyed by the anonymous owner id
    (§4.5 (c)). A claim that takes a list of pet ids cannot express this: at launch there is no
    list, and two of the three stores are not pets.

14. **Standalone mode stays inert.** With `DATSME_HMAC_SECRET` unset there is no host, no
    `signout_url`, no anonymous owner id, no renewal, and no checkout. Every field this spec adds
    is None, `external_user_id` stays NULL exactly as documented (`db.py:11-12`), and every flow
    degrades to today's local behavior. The standalone-first posture is not weakened.

---

## 1. The fact base

### 1.1 The three lifetimes

| # | Lifetime | Value | Defined at | Expires means |
|---|---|---|---|---|
| 1 | **DatsMe login** (host session + `token` cookie) | **720 h = 30 days**, sliding | `datsme_config.py:76`; rotation every 24 h at `:82`; cookie `max_age` at `api/auth.py:91` | The real logout. `revoke_session` also kills it server-side. |
| 2 | **Launch token** (`exp`) | 60 min | `service.py:58` — `LAUNCH_TOKEN_TTL` | DatsPet stops recognizing the user. |
| 3 | **DatsPet launch cookie** (`max_age`) | 60 min | `datsme_integration.py:71` | Same, one beat earlier. Deliberately matched to #2. |

The host's own comment settles the premise (`datsme_config.py:73`): *"Activity slides the row and
rotation re-mints the JWT, so an active user never hits this; an idle user is signed out after the
full window."*

Because `resolve_launch_identity` **re-verifies the JWT on every request** rather than parsing the
cookie (`datsme_integration.py:314`), #2 is the binding constraint: at 60 minutes DatsPet goes cold
while DatsMe still knows exactly who the user is for another 29 days. **That gap is the first bug.**

### 1.2 The owner scope (the second bug)

`external_user_id` is a nullable column, NULL meaning "standalone/local" (`db.py:64`, `:11-12`).
The read rule is not exact-match:

```python
# db.py:310-315  — TODAY
def _scope_clause(external_user_id):
    if external_user_id is None:
        return "external_user_id IS NULL", ()            # standalone: the unowned pets
    return "(external_user_id IS NULL OR external_user_id=?)", (external_user_id,)
```

Three consequences, all verified:

- **Every signed-in user sees every unowned pet**, from every anonymous visitor, and `db.py:301`
  stamps them `claimable: true` so the house offers a claim button on them.
- **`claim_unowned_pets` binds by pet id alone** (`app.py:1683-1706`) — there is no check that the
  claimer is the browser that made the pet, because until now there was nothing to check against.
- **An expired token routes a signed-in user's writes into that pool** (decision 7).

This design is correct for what it was written for: a single-user local box, where "unowned" and
"mine" are the same set. It is wrong for `pet.datsme.me`, where the front door invites anonymous
design (`SPEC_DATSPET_FRONT_DOOR` §9.3) before sign-in.

### 1.3 Two purchase paths, one of them with a back door

See §6.1 for the table and §0.10 for the resync channel that keeps the push alive even after its
button is gone.

---

## 2. The flows

### 2.1 Sign in (already built — baseline, unchanged)

```
DatsPet landing  ──"Sign in with DatsMe"──▶  host GET /api/integrations/login-launch
                                              ?activity=design_a_pet&return=/design
   host: user is None?
     yes ──▶ /login?next=<relative path>  ──▶ credentials ──▶ resume next
     (first time) ──▶ /integrations/consent?activity=…&next=… ──▶ grant ──▶ resume
   host: mint launch JWT ──303──▶ DatsPet /launch?token=…&return=/design
   DatsPet: verify signature ──▶ set datsme_launch ──▶ claim this browser's
            anonymous pets (§4.5) ──▶ land on /design
```

Cited: `routes.py:58` (`_login_bounce`), `:156` (signed-out branch), `:169` (consent detour),
`:197` (`login_launch`); DatsPet `datsme_integration.py:226` (`launch`), `:277` (cookie set).
The claim step is the only addition, and §4.5 explains why it belongs at launch rather than at
hand-off time.

### 2.2 Sign out (new — §3.1 + §4.1)

```
DatsPet nav ──"Sign out"──▶ DatsPet GET /api/datsme/signout
   303 response, and ON THAT SAME RESPONSE: delete datsme_launch + datspet_admin
                                            + datspet_anon        ← §4.5
   ──▶ host GET /api/integrations/logout-launch
            ?token=<launch JWT>&return=/api/datsme/signed-out
        host: verify token signature + pid (ignore exp)
        host: revoke_session(own token cookie's jti)   ← server-side teeth
        host: delete token + csrf_token cookies
        ──303──▶ <partner BACKEND origin from pid>/api/datsme/signed-out
   DatsPet GET /api/datsme/signed-out ──303──▶ <frontend origin>/   ← §3.1.4
   DatsPet landing renders the signed-out state
```

Both sessions are now genuinely over, and the browser carries no anonymous identity inherited from
the previous user. A different user clicking "Sign in with DatsMe" hits `if user is None` and gets
a real login page, and lands in an empty house. **This is the acceptance criterion.**

### 2.3 Stay signed in — silent re-launch (new — §4.2)

```
page load ──▶ GET /api/datsme/session
   token_expires_in < LAUNCH_RENEW_THRESHOLD_SEC ?
     no  ──▶ render normally
     yes ──▶ top-level navigate to signin_url with return=<current path>?renewed=1
        host session alive (≤30 days)  ──▶ instant round trip, no prompt ──▶ render
        host session dead              ──▶ real login page (correct — they are logged out)
   arriving with ?renewed=1 already set ──▶ do NOT renew again; render what we have
```

The `?renewed=1` marker on the return path *is* the loop guard — no cookie, no TTL constant. A
host that declines (revoked consent, tripped health gate) therefore costs exactly one extra
navigation instead of an infinite redirect loop, which is the single most likely way this feature
breaks in production.

### 2.4 Buy a pet you designed (consolidated — §5.2)

```
design finishes ──▶ pet row exists, owned by this browser's owner id, draft=1
user clicks "Adopt into my DatsMe house"
   1. handOffToDatsme([pet_id])                    ← the ONE shared helper (§5.2)
        a. POST /api/pets/claim   if the pet is still anon-owned  (app.py:1683)
        b. POST /api/pets/{id}/keep  if draft=1    (app.py:1708; enforces house cap)
        c. navigate to ${import_url}?items=<pet_id>
   2. host GET /api/integrations/import/datspet   ← the user's own 30-day session authenticates
        quote from the DECLARED pose_count; no bytes fetched; shows real balance
   3. user confirms
   4. host POST /api/integrations/import/datspet  ← binding: echoes sha256 + quoted_credits
        sha moved   → "changed", charge nothing
        price moved → refused, charge nothing
        require_credits → 402 if funds are short, BEFORE any mutation
        fetch bundle server-to-server → price from the BYTES → charge at-most-once → ingest
   5. host POST /partner/imported/{user_id} ──▶ DatsPet stamps writeback_acked_at
```

Steps 1a and 1b are the only new wiring, and neither needs new state. `draft=1` already means
"scratch, purgeable, not offered" (the host skips drafts at `import_routes.py:134-138`), and
`draft=0` already means "saved in DatsPet, offerable" (`app.py:1678` — *"Drafts are excluded (join
via /keep)"*). "Kept but not yet adopted" is an existing, legitimate state — and after §6.2a it is
no longer mistaken for "a writeback we owe the host".

**1a and 1b are both required and are not interchangeable.** Claim binds ownership; keep clears
the draft flag. A pet designed while signed in needs only (b); a pet designed anonymously and then
signed in for needs both — and Rev.1's single `keep` would have left it invisible to
`/partner/export` (exact-match, `db.py:396`), i.e. silently absent from the checkout page.

### 2.5 Failure postures (all fail toward a usable page, never a dead end)

| Situation | Result |
|---|---|
| Logout bounce: token signature invalid | Host 400s → DatsPet cookies are *already* cleared by its own 303, so the user is locally signed out; landing shows signed-out. |
| Logout bounce: host unreachable | DatsPet cookies cleared; user lands on DatsPet signed-out with a notice that the DatsMe session may persist. |
| Renewal: partner health gate tripped | Host bounces to `/?signin=unavailable` — the existing posture (`routes.py:179`). The `?renewed=1` marker prevents a loop. |
| Renewal: consent revoked since last launch | Host redirects to the consent page, user re-grants, resumes. |
| Request arrives with a launch cookie whose token no longer verifies | **401 `session_stale`** (§4.5) — never a silent downgrade to the anonymous scope. The frontend renews and retries. |
| Checkout: insufficient credits | Host 402 on its own page, next to the balance. Nothing charged, pet stays kept in DatsPet. |
| Checkout: user abandons | Pet stays kept in DatsPet, unadopted. Re-checkout later is free of penalty. |
| **Pet has no `pose_count`** (unparseable manifest) | `_export_item` omits the `transfer` block (`datsme_integration.py:882-891`) and the host skips it with a log line (`import_routes.py:234-240`) — the pet is silently **absent** from the checkout. After §6 this is the only way a purchase can fail to appear, so it needs a user-facing reason: the house/designer must show "this pet can't be adopted yet" rather than an item that isn't there. (`SPEC_DATSPET_CATALOG_PURCHASE.md` §1.1 inherits this row: a shipped sample bundle with an unparseable manifest fails the same silent way, which is what its Gate 0 guard test exists to prevent.) |
| **Pet still anon-owned at checkout** | Impossible via the shared helper (step 1a), which is precisely why the helper is shared rather than reimplemented per surface. |

---

## 3. Host changes (`datsme_me` — deploy first)

### 3.1 `GET /api/integrations/logout-launch` (new, in `apps/dpp/routes.py`)

The third sibling of `login-launch` / `admin-launch`, and the only new endpoint in this spec.

```
GET /api/integrations/logout-launch?token=<launch JWT>&return=<relative path>
```

1. **Verify the token** with the partner's `hmac_secret`, and require `claims["pid"] ==
   partner.slug`. Reuse the decode already written at `service.py:802` — extract it as a shared
   helper rather than copying it (the repo's convention: `admin_common.py` "reused by
   PARAMETERIZING, not copying"; `_login_launch_impl` backing two wrappers).
   **Decode with `verify_exp: False`.** Document why inline: logout confers nothing, and a user
   whose token lapsed 30 seconds ago must still be able to sign out.
2. **Revoke the host session.** Decode the *request's own* `token` cookie → `jti` →
   `revoke_session(social_db, user_id, jti)`. Same best-effort loop as
   `POST /api/auth/logout` (`api/routes/auth.py:1067`), and it must be **extracted and shared**
   with it, not duplicated.
   - The launch token's `jti` is the **nonce** id, not the session id — never use it to pick a
     session.
   - Because only the caller's own cookie is revoked, no partner can log out a different user.
     The launch token authenticates the *redirect target*, not the *subject*.
   - Skipping this is the classic half-logout: cookie gone, session row still live.
3. **Clear cookies** with matching attributes: `delete_cookie("token", **auth_cookie_kwargs())`
   and the same for `csrf_token`. Attributes must match `set_auth_cookie` or browsers ignore the
   deletion — the D01-4 incident recorded at `api/routes/auth.py:1079`.
4. **Redirect back to a server-resolved origin — which is the partner's *backend*.** Partner from
   the verified `pid` → `partner.launch_base_url` → `service.partner_origin()` (`service.py:445`),
   then append the validated `return` path. **Never** accept a full URL from the query string;
   same posture as `_partner_origin_for_activity` (`routes.py:187`) and the "Bug 2" server-side
   decline target (`routes.py:170`).

   **The origin this yields is DatsPet's API origin, not its web origin.**
   `launch_base_url` comes from the manifest's `base_url` = `_datspet_public_url()`, whose own
   comment reads *"In dev this is the backend's own origin"* (`datsme_integration.py:133-137`),
   while the landing page lives at `_frontend_url()` (`:140-142`) — :19954 vs :19955 in dev. They
   coincide in production only because one nginx vhost serves both. **Therefore the `return` path
   this spec sends is a DatsPet *backend* path, `/api/datsme/signed-out` (§4.4), which performs
   the origin translation `/launch` already performs.** Sending `return=/` would land the user on
   the FastAPI root in dev and pass review in prod — the exact dev/prod parity seam that has cost
   this project days before.

   *Recorded, out of scope:* the existing `?signin=unavailable` bounce (`routes.py:179`) has the
   same latent mismatch. It is not touched here; it is noted so the next reader does not mistake
   this spec's asymmetry for an oversight.

*Gate:* signed-in user + valid token → 303 to the partner backend origin, `token`/`csrf_token`
cleared, session row revoked; a subsequent `login-launch` renders the login page. Forged or
foreign-partner token → 400, no session touched.

### 3.2 Extracted, not duplicated

- `_verify_partner_launch_token(social_db, token, *, verify_exp)` — from `service.py:802`; used
  by writeback verify and by §3.1.
- `_revoke_and_clear(request, response, social_db)` — from `api/routes/auth.py:1067-1081`; used
  by `POST /api/auth/logout` and by §3.1.

### 3.3 Explicitly not changed

`login-launch`, `admin-launch`, `sync-pending`, the consent page, `mint_launch_token` (including
its `resync_hint` parameter), `LAUNCH_TOKEN_TTL`, pricing, `require_credits`, the import routes,
`apply_writeback`, the writeback transport, the partner manifest, and the SDK.
**`LAUNCH_TOKEN_TTL` stays 60 min** (decision 6).

That `sync-pending` is unchanged is deliberate and is what forces §6.2a to be done on the DatsPet
side: the host will keep offering resync to any partner that reports pending items, so DatsPet
must stop reporting them rather than ask the host to stop asking.

### 3.4 Host-side prerequisites — verified present, do not rebuild

Everything §3.1 leans on already exists. Checked, so the implementer does not re-derive it:

| Needed by | Already there |
|---|---|
| §3.1 step 2 | **`revoke_session(social_db, user_id, jti)`** — `api/session_store.py:402`. Ownership-checked, idempotent, returns `False` rather than raising. |
| §3.1 step 3 | **The matched-attribute delete.** `auth_cookie_kwargs()` carries `samesite`/`secure` (`api/auth.py:56-68`); `set_cookie` and `delete_cookie` both default to `path=/`, so they match. `api/routes/auth.py:1079-1081` is the pattern to copy. |
| §0.4's CSRF argument | **GET is exempt from the CSRF middleware** — `_SAFE_METHODS` at `api/csrf.py:41`, checked at `:94`. A session-ending GET therefore passes with no CSRF token, which is exactly why the partner-HMAC check carries the whole authentication weight. State it; do not add a second mechanism. |
| The acceptance criterion | **`get_optional_user` consults the session row** via `_session_ok` and fails soft (`api/auth.py:339-353`). This — not the cookie delete — is what makes the next `login-launch` render a login page for user B. It also kills the host web app's localStorage JWT at the same instant, so there is no second identity to clean up. |
| §0.9's checkout | **The host checkout already handles signed-out**: the page bounces through login and returns with the `?items=` selection intact (`web/src/app/import/[partner]/page.tsx:133-139`). |
| "buy with credit points" | **Credit acquisition exists** — `GET /api/credits/me`, `POST /api/credits/convert` (points→credits), the monthly allowance distributor, `POST /api/credits/admin/grant`, and gifting (`api/social_ledger/social_ledger_routes.py:188-242`, `:410`, `:427`). No new money code. |

**Two per-environment facts to verify on the box, not infer:**

1. **Each DatsMe host's `datspet` partner row must carry that environment's `launch_base_url`.**
   `slug` is a primary key (`api/apps/dpp/models.py:46`), so there is exactly one row per host, and
   §3.1 step 4 resolves the logout redirect origin *from that row*. A staging host whose row points
   at production's DatsPet backend would sign staging users out into production. Same class as the
   `deploy/nginx-default.conf` trap — check the row on each box.
2. **The test users need a nonzero credit balance** before the acceptance criterion is run, or "B
   buys a pet" 402s and the run proves nothing. Allowance, conversion, or an admin grant — decide
   which before the staging pass, not during it.

**One consequence to write down rather than discover:** signing out on DatsPet revokes the DatsMe
**session row**, so any other DatsMe tab that user has open is signed out too. That is a correct
federated logout and it is what makes the two-user test work — but it is a visible behavior change
on the host.

---

## 4. DatsPet backend changes (`webui/`)

### 4.1 `GET /api/datsme/signout` (new) — replaces the POST as the nav's action

One endpoint that clears DatsPet's cookies **on the same response** that redirects to §3.1, so
the clear and the hop cannot half-fail:

- Read the launch cookie. If a signature-valid token is present (expired is fine), build the
  host `logout-launch` URL with `return=/api/datsme/signed-out` and 303 to it.
- If no cookie/token, 303 to DatsPet's own landing (local-only logout) — the user already
  appears signed out, so this is mostly unreachable.
- **Always** `delete_cookie` all three DatsPet cookies — `LAUNCH_COOKIE`, `ADMIN_COOKIE`, and
  `ANON_COOKIE` (§4.5) — on that response, with the same `samesite`/`secure` attributes the
  setters used (`datsme_integration.py:539-544` already does this correctly for the first two;
  keep that shape and add the third).
- Standalone (`DATSME_HMAC_SECRET` unset): clear cookies, 303 to landing, never touch a host URL.

**Clearing `ANON_COOKIE` is not housekeeping — it is half the acceptance criterion.** If the
anonymous browser id survives sign-out, user B inherits user A's pre-sign-in pets and the house is
not empty.

`POST /api/datsme/logout` is **kept** as the local-only primitive (it is what the standalone path
and the tests use) but is no longer what the nav calls. Its docstring must stop implying it is the
whole of sign-out and point at §4.1.

### 4.2 `GET /api/datsme/session` grows two fields (additive)

| Field | Meaning |
|---|---|
| `signout_url` | The host `logout-launch` URL, prebuilt server-side **exactly as `signin_url`/`import_url` already are** (`datsme_integration.py:491-506`) — the frontend never hardcodes a DatsMe origin. None unless integrated *and* a launch cookie is present. |
| `token_expires_in` | Seconds until the verified token's `exp`, so the client can decide to renew. Computed from the **verified** token, never the cookie blob. |

Silent re-launch is driven by these two plus the existing `signin_url`. Named constant (no inline
literals):

- `LAUNCH_RENEW_THRESHOLD_SEC` — renew on page load when `token_expires_in` falls below it.
  Proposed **900 s (15 min)**: comfortably longer than any single page interaction, far shorter
  than the 60 min window, so a normal visit renews at most once.

The loop guard is the `?renewed=1` marker on the return path (§2.3), not a cookie. `signin_url` is
prebuilt with `return=/design` (`:494`), so the client **replaces** that query parameter rather
than appending a second one — via the `URL` API, which reads the origin off the server-supplied
string and never hardcodes it. **The marker crosses two validators and one quoting step, and all three were checked.** The return
path is validated by the **host** first (`_safe_return`, `routes.py:36-42`), quoted onto the launch
URL with `quote(safe, safe='/?=&')` (`_append_return`, `routes.py:45-55`), and re-validated by
**DatsPet** on arrival (`_safe_return_path`, `datsme_integration.py:92-103`). Both charsets are the
same `/[A-Za-z0-9/_\-?=&.]*`, and the quoting leaves `?` and `=` intact, so `/design?renewed=1`
survives end to end with **no validator change in either repo**. A test must pin it in both: if the
host silently drops the marker, §2.3 degrades to an infinite redirect loop — the exact failure the
guard exists to prevent, arriving through the one component this spec does not otherwise touch.
(Note the marker must contain no `&`: a second parameter would be split by the outer query string.
One flag is all the guard needs.)

### 4.3 The TTL rationale at `datsme_integration.py:66-71` must be rewritten

Today it reads: *"Must be >= the host's LAUNCH_TOKEN_TTL (60 min) so the browser session outlives
the JWT the writeback carries — designing a pet (GPU build + review) can take many minutes, and if
the cookie lapsed first the user would lose the Accept action while the token was still valid."*

After §6 there is **no token-authenticated act at the end of a build**, so that constraint is
gone. Replace it with the renewal rationale, and cite this spec. Leaving the stale comment in
place would send the next reader down the retired path.

### 4.4 `GET /api/datsme/signed-out` (new) — the origin translation hop

A three-line backend endpoint: 303 to `_frontend_url()` + `/`, optionally carrying a
`?signedout=1` notice flag the landing already knows how to render (`PublicLanding.tsx:40-58`
reads and strips notice params). It exists because the host can only redirect to the partner
origin it has registered, which is the API origin (§3.1.4). It is the exact mirror of what
`/launch` does on the way in, and it means the frontend origin stays a DatsPet-side fact that no
host row has to know.

### 4.5 Owner scope — the per-browser anonymous owner (**new; the acceptance criterion lives here**)

Five parts, all in `webui/`, that together make "an empty house for user B" true.

**(a) One resolver, three states.** `resolve_launch_identity` collapses "no cookie" and "stale
cookie" into `None` (`:314-330`). Split them:

```python
# webui/owner_scope.py — the ONE door to caller identity
class OwnerScope(NamedTuple):
    owner_id: Optional[str]   # None only in standalone mode
    is_stale: bool            # launch cookie present but its token no longer verifies

def resolve_owner_scope(request: Request) -> OwnerScope   # PURE: reads, never mints
```

**Why a new module rather than `datsme_integration.py`.** The claim sweep (§4.5 (c)) runs inside
`launch()` and must reach the **reference** store, which `app.py` owns; `app.py` already imports
`datsme_integration`, so putting the sweep in either file is a circular import. `owner_scope.py`
holds what changes for one reason — the anon cookie, the resolver, the exclusion set, the claim
registry — and both modules import *it*. The `webui/` layering stays one-directional.

- **Standalone** (`DATSME_HMAC_SECRET` unset): `owner_id=None` — today's behavior, unchanged.
- **Launch cookie verifies**: `owner_id = <DatsMe user_id>`.
- **Launch cookie present, token does not verify**: `is_stale=True`. Callers raise
  **401 `session_stale`**; the frontend renews (§4.2) and retries. It must never be treated as
  anonymous — that is decision 7's bug.
- **No launch cookie, integrated**: `owner_id = ANON_OWNER_PREFIX + <uuid4 hex>`, read from
  `ANON_COOKIE` (`datspet_anon`) — or from `request.state.anon_owner_id` when the middleware below
  minted one for *this* request. Same `httponly`/`samesite`/`secure` attributes as the launch
  cookie; `ANON_OWNER_PREFIX` and `ANON_COOKIE_TTL_SEC` named, not inlined.

**The anon id is minted in ASGI middleware, never on an injected `Response`.** The resolver stays
pure and cookie-setting happens in exactly one place:

```python
# webui/owner_scope.py — policy lives here; app.py registers it in one line

# Server-to-server surfaces: no browser, no Set-Cookie. NAMED, because the set is
# not derivable from a single prefix — the bundle fetch is the host's httpx client
# calling an /api/datsme/ path (datsme_integration.py:823), not a /partner/ one.
NO_COOKIE_PREFIXES = ("/partner/", "/api/datsme/bundle/")

async def anon_owner_middleware(request: Request, call_next):
    minted = None
    if _is_integrated() \
            and not request.url.path.startswith(NO_COOKIE_PREFIXES) \
            and LAUNCH_COOKIE not in request.cookies \
            and ANON_COOKIE not in request.cookies:
        minted = ANON_OWNER_PREFIX + uuid.uuid4().hex
        request.state.anon_owner_id = minted          # visible to this request
    response = await call_next(request)
    # A Set-Cookie on a publicly cacheable response is a SHARED anonymous identity
    # the moment anything caches it. Checked on the RESPONSE, not a path list, so a
    # new cacheable endpoint is excluded automatically instead of by remembering to.
    if minted and "public" not in response.headers.get("cache-control", ""):
        response.set_cookie(ANON_COOKIE, minted, max_age=ANON_COOKIE_TTL_SEC,
                            httponly=True, samesite=LAUNCH_COOKIE_SAMESITE,
                            secure=LAUNCH_COOKIE_SECURE)
    return response
```

The two `Cache-Control: public` responses today are the catalog images (`app.py:1378`, `:1405`);
neither needs an owner, so dropping the mint there costs nothing and the next owner-needing request
mints normally. This is the same reasoning the pet-asset headers already record —
`_IMMUTABLE_ASSET_CACHE` is `private` deliberately, *"never a shared proxy that could serve another
user"* (`app.py:1748-1750`). A guard test pins it: no response may carry both `Set-Cookie:
datspet_anon` and a public `Cache-Control`.

**Why middleware and not a `Response` parameter.** FastAPI merges cookies set on an *injected*
`Response` only when the handler returns a **non-Response value**. A handler that returns a
`FileResponse`/`RedirectResponse`/`StreamingResponse` directly silently drops them — and
`/api/reference/{reference_id}.png` is explicitly *"Owner-scoped, unlike the /api/preview/{id} it
replaces"* and returns a raw `FileResponse` (`app.py:1095-1113`). That endpoint is a plausible
**first** owner-needing request in the anonymous flow: an `<img>` load would mint an id, drop the
cookie, and the next request would mint a *different* one — orphaning the reference and every pet
built from it. Middleware sets the cookie on the real outgoing response whatever its type, so the
id exists from the very first request with no ordering dependency on the frontend having called
`/api/datsme/session` first.

*Gate for this piece:* a request to `/api/reference/{id}.png` from a cookieless browser comes back
carrying `Set-Cookie: datspet_anon=…`, and a second request reuses that id rather than minting a
new one. Neither `/partner/*`, nor `/api/datsme/bundle/*`, nor any `Cache-Control: public`
response ever gets one.

**(b) The scope clause becomes exact-match.**

```python
# db.py:310-315 — AFTER
def _scope_clause(external_user_id):
    if external_user_id is None:
        return "external_user_id IS NULL", ()      # standalone box: the local pets
    return "external_user_id=?", (external_user_id,)
```

The union is what leaked. `_can_access` (`app.py:1607-1611`) and the reference-scope mirror
(`app.py:730-734`) change in lockstep — this is the "sweep the whole codebase" rule; a
single-site fix here is a false negative by construction, because the same `ext is None or ...`
shape appears in three places.

**`revoke_user`'s `anonymize` action is a fourth consumer of the NULL rule** (`db.py:478-483`) —
not the same code shape, which is exactly why a grep for the shape misses it: it sets
`external_user_id=NULL` and its docstring calls the result *"standalone/orphaned"*. Under
exact-match on an **integrated** box those rows become invisible to everyone rather than
standalone-visible, so the docstring must be corrected to say what it now does — GDPR-anonymize is
effectively a soft delete there. Do not "fix" this by re-introducing a NULL union; invisible is the
correct outcome for a row whose owner asked to be forgotten. On a standalone box the behavior is
unchanged. `export_pets` (`db.py:396`) and `/partner/imported`'s ownership check
(`datsme_integration.py:941`) were already exact-match and need no change.

`claimable` (`db.py:301`) becomes `bool(owner) and owner.startswith(ANON_OWNER_PREFIX)` — the
`bool(owner)` guard is not defensive noise: on a standalone box every row's owner is `None` and the
bare `.startswith` is an `AttributeError` on the house's main read path. Since the scope is now
exact-match, the only anon-owned rows a caller can see are that caller's own — which is exactly
what "claimable" should always have meant.

**(c) Claiming is a sweep of everything one anon owner holds — keyed by owner, not by pet id.**

```python
# webui/owner_scope.py
def claim_anon_owner(from_owner: str, to_owner: str, activity_id: Optional[str]) -> dict
#   for handler in _CLAIM_HANDLERS: handler(from_owner, to_owner, activity_id)
#   returns {store: rows_moved} for the log line
```

Today's `claim_unowned_pets` binds by pet id alone (`app.py:1683-1706`), which — combined with the
union clause (b) removes — let a signed-in user claim a pet they had merely *seen* in a shared
house. It is
replaced, not adapted: at launch there **is no pet-id list**, and a list could not carry the two
non-pet stores anyway.

**Three stores stamp an owner, and all three must move together:**

| Store | Stamped at | Read at | If it doesn't move |
|---|---|---|---|
| **pets** (`pets.external_user_id`) | `insert_pet` | `_scope_clause` (`db.py:310`) | the user's own pets vanish at sign-in |
| **references** (`owner` in `{id}.json`) | `_save_reference` (`app.py:696-725`) | `_reference_visible` (`app.py:729-734`) | signing in mid-design 404s the designer's own reference (`app.py:1198`, `:1501`) — **the front door's headline flow** |
| **jobs** (`Job.external_user_id` + the `jobs` row) | submit (`app.py:1542`), persisted by `record_pool_job` (`db.py:495`) | the finished pet is stamped from it (`app.py:595`, pool path `:478`); `stop_job` checks it (`:1592`) | signing in during a ~3-min build produces a pet its own owner cannot see |

The reference sweep rewrites the `owner` field in each matching sidecar under `PREVIEW_DIR`. It is
a directory scan, which is acceptable because it runs **once per sign-in** and the directory is
already swept at 24 h by `_cleanup_transients` — bounded by construction. Do not build an index for
it until the scan is measured to matter.

Claiming runs **at launch** (§2.1), not at hand-off: the moment the browser gains a DatsMe
identity is the moment its anonymous work becomes that user's, and doing it there means every
downstream surface (house, designer, and the catalog spec's page) inherits it without repeating the
step.

**`ANON_COOKIE` is NOT cleared at launch.** It survives until sign-out (§4.1), for two reasons: a
row can be written microseconds *after* the launch sweep (the worker thread finalizing a build the
sweep just re-stamped), and the hand-off helper's claim backstop (§2.4 step 1a) needs `from_owner`
to reach it. Clearing it at launch would throw away the only key to those rows. It carries no
authority while a launch cookie is present — the resolver prefers the launch cookie unconditionally
— so retaining it leaks nothing.

**(d) The claim registry (the "adding a fourth store" test).** `_CLAIM_HANDLERS` is a list each
owner-stamping module appends to at import: `db.py` registers the pets+jobs handler, `app.py`
registers the references handler. Adding a fourth owner-stamped store is **one registration**, not
an edit to `claim_anon_owner` — the same plugin/registry posture as `behaviorRegistry.ts` and
`motion_profiles/registry.json`. Three concrete instances exist today, which is what makes the
registry earned rather than speculative.

*Guard test:* grep `webui/` for writes that persist an owner value; every such module must appear
in `_CLAIM_HANDLERS`. A store that stamps an owner and does not register is the exact bug this
section exists to prevent, and it is mechanically detectable.

**(e) Enforcement.** A guard test asserts that no module under `webui/` calls
`resolve_launch_identity` directly any more — `resolve_owner_scope` is the only door. The
docstring at `:314` already claims identity is "resolved ONE way everywhere"; this makes the
claim testable rather than aspirational.

**Migration.** Pre-existing rows with `external_user_id IS NULL` on an *integrated* deployment
become invisible to everyone once (b) lands. That is correct — they were a shared pool nobody
owned — and per the pre-launch posture no back-compat is owed. Drafts are purged at startup
already (`app.py:1614`); any saved strays can be deleted by an ops sweep. **Standalone installs
are unaffected**: their rows are NULL and their scope is `IS NULL`.

### 4.6 The "pending writeback" concept retires — both of its readers

Two places read `(datsme_activity_id IS NOT NULL AND writeback_acked_at IS NULL)` as "a writeback
we owe the host". After §6 nothing is ever owed, and **both** must go, or the retired concept keeps
acting on live data.

**(a) The pending list.** `GET /partner/results/{user_id}/pending`
(`datsme_integration.py:978-993`) must return a constant empty list, and
`db.list_pending_writebacks` (`db.py:384-393`) is deleted. In a pull model nothing is pending: the
host fetches when the user checks out, and a pet that was never checked out is not an owed delivery
— it is just a pet. The endpoint itself stays (the DPP protocol requires partners to serve it) with
a docstring that says why it is empty by construction.

Leaving it as-is is the failure mode decision 10 describes: every kept-but-unadopted pet matches
the predicate, so the host would mint an `rsx` token for each and re-open the push path this spec
closes.

**(b) The draft-purge exemption — `not_pending` (`db.py:357-359`).** Delete the clause outright,
from all three purge scopes:

```python
# db.py:357-359 — DELETE. Nothing is ever "pending writeback" after §6.
not_pending = "(datsme_activity_id IS NULL OR writeback_acked_at IS NOT NULL)"
```

It exists to protect a pet whose *queued* writeback hadn't drained yet — *"a queued Accept whose
retry hasn't drained yet must survive, or the retry would 404 the bundle and the pet would be
lost."* §6.2 deletes that retry queue, so the thing it protects no longer exists.

**Leaving it in place is a leak, not a no-op**, and the interaction is easy to miss:
`claim_unowned_pets` **sets `datsme_activity_id`** (`db.py:462`), so once §4.5 (c) claims at launch,
every claimed-but-unadopted draft matches the predicate and becomes **exempt from every purge
scope, permanently**. Anonymous scratch pets would accumulate forever, and §4.5's migration note
would be leaning on a startup purge that this very change had disabled for exactly those rows.

**Deleting it is safe** because the hand-off calls `keep` *before* navigating to the checkout
(§2.4 step 1b), so any pet in a live checkout is already `draft=0` and outside every purge scope.
A draft, after this change, is only ever what the name says: scratch the user never saved.

*Gate:* a claimed, kept-but-unadopted pet survives a purge (it is not a draft); a claimed pet the
user never kept is purged (it is); and neither leaves a row behind that no scope can reach.

### 4.7 The `session_stale` contract — which endpoints 401, and which must not

"Callers raise 401" is not implementable as written: two classes of endpoint must not, and one of
them would deadlock the renewal it is meant to trigger.

| Endpoint class | On `is_stale` | Why |
|---|---|---|
| JSON API (`/api/pets*`, `/api/design-axes`, `/api/reference` writes, `/api/job/*` mutations, `/api/catalog/*/adopt`) | **401** `{"detail": {"code": "session_stale"}}` | The frontend renews (§5.3) and retries. A structured `code` — not a message match — because the client branches on it. |
| **`GET /api/datsme/session`** | **200**, with `launched: false` and a new **`stale: true`** field | This is the endpoint that *tells* the frontend to renew. A 401 here means the client can never learn why it was rejected, and the renewal loop never starts. It is the one endpoint that must always answer. |
| Image/asset GETs (`/api/reference/{id}.png`, `/api/pets/{id}/sheet.png`) | **404**, unchanged | `<img>` has no 401 handler; a broken image is the honest outcome, and `reference_image` already collapses every failure to 404 *"so a broken `<img>` is the whole story"* (`app.py:1100-1110`). The page's next JSON call raises the 401 that starts the renewal. |
| `/partner/*` and `/api/datsme/bundle/*` | unchanged | Host-signed, no browser cookie, no launch cookie to be stale — the same `NO_COOKIE_PREFIXES` set §4.5 (a) excludes from minting. |

`stale: true` is additive and standalone-inert: it is absent (or `false`) whenever there is no
launch cookie, so nothing existing reads a new meaning into an old response.

### 4.8 Explicitly not changed

Capability/tier resolution, the admin cookie and `require_admin_launch`, `/partner/export`,
`/api/datsme/bundle/{token}`, `/partner/imported/{user_id}`, `_safe_return_path`, and the
host-signature verifier `_require_host_signature`.

(`/api/datsme/bundle/{token}` and `_safe_return_path` appear in §4.5 (a) and §4.2 respectively, but
neither is *modified*: the bundle path is added to a middleware exclusion set, and
`_safe_return_path`'s existing charset is asserted by a new test. Both keep their current code.)

---

## 5. DatsPet frontend changes (`web/`)

### 5.1 Sign out becomes a navigation

`datsmeLogout()` in `src/lib/api.ts:915` currently `fetch`es the POST. It becomes a top-level
navigation to `session.signout_url` — a `fetch` cannot clear a cross-origin cookie, and the host
cookie is `samesite: "lax"` (`api/auth.py:68`), so it would not even be sent. Both call sites
change through that one helper: `components/NavAuth.tsx:67` and
`components/PublicLanding.tsx:69`. `src/lib/api.ts` remains the only file that knows a URL.

### 5.2 One hand-off helper, used by every purchase surface

```ts
// src/lib/api.ts — the only place that knows the checkout URL shape
export async function handOffToDatsme(petIds: string[], session: DatsmeSession): Promise<void>
//   1. claimPets(ids that are claimable)      → POST /api/pets/claim      (api.ts:53)
//   2. keepPet(ids that are still draft)      → POST /api/pets/{id}/keep  (api.ts:849)
//   3. window.location.href = `${session.import_url}?items=${ids.join(",")}`
```

Two callers here: the house (replacing the inline sequence at `app/house/page.tsx:128-147`) and
the post-design Adopt action (replacing `acceptPetToDatsme`, `api.ts:938`). The catalog surface in
`SPEC_DATSPET_CATALOG_PURCHASE.md` is the third and **adds no new checkout code** — that is the
point of extracting the helper here rather than there. The house's existing decision comments —
*claim first, navigate second*; *cancel does NOT unclaim* — move into the helper with them; they
are the reasoning that makes the order correct and they must not be left behind in a file that no
longer performs the sequence.

The price hint may keep using `session.cost`, but its copy should read as an estimate — the host's
checkout shows the binding number.

### 5.3 One interceptor turns `session_stale` into a renewal

`src/lib/api.ts` already funnels every request through its own fetch helpers, so the stale→renew
rule belongs there and nowhere else:

```ts
// src/lib/api.ts — the ONE place that reacts to a stale launch session
//   on 401 with detail.code === "session_stale":
//     if the current URL already carries ?renewed=1 → surface the error (do not loop)
//     else → window.location.href = renewUrl(session.signin_url, currentPath + "?renewed=1")
```

Without this, every call site grows its own copy of the renewal decision and the `?renewed=1`
guard — which is precisely how a redirect loop gets shipped in one component and not the other. It
is also why §4.7 makes the code a **structured field** rather than a message: a client that
string-matches an error message is a client that breaks when the copy is edited.

### 5.4 Nothing to purge from browser storage

`web/src/` uses **no `localStorage` or `sessionStorage`** — a full-tree grep returns zero hits. All
per-user state is server-side and cookie-scoped, and every flow here is a full-page navigation,
which resets in-memory state. In most apps this is where the previous user leaks; here it is
already clean. **Do not add browser-persisted user state**; it would silently create the leak this
spec exists to prevent — and note that §4.5's anon id is deliberately an httponly *cookie*, not
browser storage, so sign-out can actually clear it.

---

## 6. The consolidation — one purchase path

### 6.1 What exists today

| Path | Entry | Authenticated by | Money |
|---|---|---|---|
| **Push** | `POST /api/datsme/accept` (`datsme_integration.py:592`) | launch token (60 min) | DatsPet posts a pointer writeback; host fetches, prices, charges |
| **Push, re-entered** | host `sync-pending` → `rsx` launch → `/launch` short-circuit (`routes.py:243`/`:293`, `datsme_integration.py:243-252`) | launch token | same, with no user present at all |
| **Pull** | `${import_url}?items=…` → host checkout (`import_routes.py:199`, `:269`) | the user's own DatsMe session (30 days) | host quotes → user confirms → host charges |

Three entrances to the same outcome, with different auth lifetimes, different failure modes, and
two places pricing can drift. The pull path is strictly better: it is user-present, on the origin
where the balance lives, binding on the quote, and unaffected by DatsPet's session state.

### 6.2 Delete (DatsPet side)

- `accept_pet` — `POST /api/datsme/accept` (`datsme_integration.py:592`)
- `_post_pet_writeback` (`:657`) and its `WritebackBuilder` / `sdk_post_writeback` use
- `_enqueue_writeback_retry` and `drain_retry_queue` (`:783`) — the retry queue exists solely to
  land a *push* that failed transiently; a pull has no such state. Also drop `_retry_queue_path`
  (`:145`), the `datsme_retry_queue.db` file, and **the drain call plus `RETRY_DRAIN_EVERY_S` in
  `_maintenance_loop` (`app.py:1838-1849`)** — the loop keeps running for the transient sweep, so
  this is a removal from inside it, not a removal of it.
- The post-success local finalize at `:706-707` — the pull's equivalent already exists and is
  host-signed (`POST /partner/imported/{user_id}`, `:906`).
- Frontend: `acceptPetToDatsme` (`api.ts:938`), the `AcceptResult` interface (`:922`), and the
  Accept button's error branches for "session expired while designing" — a class of failure this
  consolidation removes outright.

Per the standing rule, these go **in the same change** as §5.2, not as a follow-up.

### 6.2a The resync back door (**new in Rev.2 — do not skip**)

`_post_pet_writeback` has a second caller: the `rsx` short-circuit inside `launch()`
(`datsme_integration.py:243-252`). Deleting the function without it is a build break; deleting the
branch without §4.6 is a live regression. Both halves:

1. **Delete the `rsx` branch.** An `rsx` claim on an inbound launch is thereafter **ignored** —
   the launch proceeds normally and the user lands on the designer. It must not 404 or 500: the
   host is explicitly unchanged (§3.3) and may still mint one from a stale row, and a user who
   clicks a recovery link deserves a working page, not an error. Log it once at info level.
2. **Report nothing pending** (§4.6), so the host never mints one in the first place.

Together these are what make the retirement real. With only (1), a stale pending row produces a
confusing no-op launch; with only (2), the dead branch survives as a loaded gun.

*Note for the reviewer:* the host's resync surface has **no UI** — `sync-pending`'s own docstring
records that the "Sync missing results" control was never built (`routes.py:254-263`). That is why
this back door was invisible in Rev.1, and why it is worth stating in the spec rather than
discovering during step 8.

### 6.3 What the deletion also removes

- The `idempotency_key = ctx.jti` "one accept per launch" mechanism. The host's
  `(source_partner_slug, source_item_id)` key is strictly stronger — it dedups *across* launches,
  which the jti never did (already noted at `datsme_integration.py:634-640`).
- The 60 s blocking-writeback timeout and the event-loop self-deadlock it guards against
  (`:642-648`). In a pull, DatsPet is a passive server; there is no re-entrant call to deadlock.
- The "your DatsMe session expired while designing" 401 — structurally impossible afterwards.

### 6.4 Do NOT delete (host side)

`apply_writeback` and the writeback transport are **not** dead code. `service.py:1258` states the
design explicitly: *"the same dispatch serves a pushed writeback (context built from a burned
launch nonce) and a pulled import (context built from the user's own session), and neither the
dispatcher nor the handlers can tell which — that is the engine/content line."* The push transport
is the generic DPP protocol for every partner; DatsPet simply stops being one of its callers.
`pet_writeback.py` is shared by both and is untouched. `sync-pending` likewise stays: it is
partner-generic, and DatsPet opts out of it by having nothing pending (§4.6).

---

## 7. Security notes

1. **The GET logout is CSRF-safe by construction** — it requires a partner-HMAC-signed token
   (§0.4). A third-party page cannot forge one. Worst case for a *replayed* token is that the
   replayer logs the victim out, which is the same outcome as the victim clicking the button.
2. **Revocation now propagates in both directions.** Host logout revokes the session row; DatsPet
   clears its cookies; and because the launch token stays 60 min with renewal *through* the host,
   a host-side revocation takes effect within one renewal window rather than never.
3. **`verify_exp: False` is scoped to exactly one endpoint** and to a non-privilege-granting act.
   It must not be reachable from any other verify path — hence the explicit keyword argument on
   the shared helper rather than a module-level flag.
4. **Money is unchanged and remains host-authoritative** (§0.8). This spec *reduces* DatsPet's
   financial surface to zero by removing the only path where a DatsPet-held credential triggered
   a charge.
5. **Per-user isolation is what this spec ADDS; it was not already there.** Rev.1 claimed the
   `external_user_id` WHERE clauses already enforced it. They do not: `_scope_clause` unions the
   unowned rows into every signed-in caller's view (`db.py:310-315`) and `claim_unowned_pets`
   binds by pet id alone (`app.py:1683-1706`). §4.5 (b) and (c) are the fix, and the acceptance
   criterion is the test. `/partner/imported`'s ownership check (`datsme_integration.py:941`) and
   `export_pets`' exact match (`db.py:396`) were already correct and are unchanged.
6. **The anonymous owner id is not an identity.** It is an opaque per-browser scoping value with
   no credential, no cross-device meaning, and no privilege: it selects rows and nothing else.
   Naming it `anon:<uuid4>` keeps that legible in the database and makes `claimable` a property of
   the value rather than a nullability accident. It does not make DatsPet an identity authority
   (§8).
7. **Third-party cookie restrictions are survivable** because every step is a top-level
   navigation. The one thing that must never be attempted is a background/iframe renewal: the
   host cookie is `samesite: "lax"` and would not be sent (§5.1).

---

## 8. What this deliberately does not do

- **No DatsPet accounts, passwords, or session store.** `SPEC_DATSPET_FRONT_DOOR` §7 still holds.
  A DatsPet-minted long-lived *identity* cookie was considered and **rejected**: it would make
  DatsPet an identity authority, so host-side revocation would stop propagating. §4.5's anon id is
  deliberately the opposite of that — it authenticates nobody, expires without consequence, and is
  destroyed at sign-out.
- **No change to `LAUNCH_TOKEN_TTL`** (decision 6).
- **No change to pricing, consent, capabilities, or tiers.**
- **No account switcher UI** ("switch user" without a full sign-out) — sign out then sign in is
  the whole requirement.
- **No "remember me" / trusted-device concept.** The host's sliding 30 days already is that.
- **No change to anonymous/standalone design gating** — still `SPEC_DATSPET_FRONT_DOOR` §9.3.
  §4.5 changes *who owns* an anonymous pet, never *whether* one may be designed.
- **No host-side deletion**, and no new host endpoint beyond §3.1.
- **No catalog purchase surface** — split to `docs/SPEC_DATSPET_CATALOG_PURCHASE.md`, which
  consumes §5.2's helper and §4.5's owner scope and adds no checkout logic of its own
  (decision 12).

---

## 9. Build order

Cross-repo, and the host must lead. Per `deploy/CHECKLIST.md` Rule 0, **staging always ships
before production**, and `scripts/verify_deployment.sh <url>` is the gate that counts — every
deploy failure on this app so far has been a false green.

0. **Host: extract the two shared helpers** (§3.2), no behavior change.
   *Gate: existing auth + writeback suites green.*
1. **Host: `logout-launch`** (§3.1).
   *Gate: valid token → 303 + cookies cleared + session row revoked, and the next `login-launch`
   renders the login page; forged/foreign `pid` → 400, session untouched; expired-but-valid token
   still logs out.*
2. **Host: deploy to staging.** DatsPet must not reference the endpoint before it exists.
3. **DatsPet: owner scope** (§4.5) — new `webui/owner_scope.py` (resolver, middleware, claim
   registry), exact-match clause, claim-at-launch sweep, `revoke_user` docstring, guard tests.
   Lands **before** the sign-out work, because sign-out's whole purpose is to reset it.
   *Gate — all seven:*
   1. *Anonymous browser 1 and anonymous browser 2 cannot see each other's pets.*
   2. *A request carrying an expired launch cookie gets 401 `session_stale` — never an anonymous
      scope — **except `GET /api/datsme/session`, which answers 200 with `stale: true`** (§4.7).*
   3. ***`/api/reference/{id}.png` from a cookieless browser returns `Set-Cookie: datspet_anon=…`
      and the next request reuses that id*** (the raw-`FileResponse` case §4.5 (a) exists for);
      `/partner/*` and `/api/datsme/bundle/*` never get one; **no response carries both
      `Set-Cookie: datspet_anon` and a public `Cache-Control`.**
   4. ***Sign in mid-design: a reference created anonymously is still loadable — and buildable —
      immediately after the launch, with no "Your reference expired" and no 404.***
   5. ***Sign in mid-build: a job submitted anonymously finishes into a pet the signed-in user can
      see in their house*** (the §4.5 (c) job sweep), and `stop_job` still accepts it.
   6. *Standalone (`DATSME_HMAC_SECRET` unset) behavior is bit-for-bit unchanged.*
   7. *No direct caller of `resolve_launch_identity` remains, and every owner-stamping module
      appears in `_CLAIM_HANDLERS`.*
4. **DatsPet: `signout_url` + `token_expires_in`** on the session endpoint (§4.2), plus
   `GET /api/datsme/signed-out` (§4.4). Additive.
   *Gate: fields present when integrated + launched, None otherwise; the signed-out hop lands on
   the FRONTEND origin in dev, where backend ≠ frontend — the prod-only test would pass either way.*
5. **DatsPet: `GET /api/datsme/signout`** (§4.1).
   *Gate: one response clears all three cookies and 303s to the host; standalone 303s locally.*
6. **DatsPet: nav + landing use the navigation** (§5.1).
   *Gate: **the acceptance criterion**, run by hand end to end. A 303 landing on the right page
   proves nothing.*
7. **DatsPet: silent re-launch + `?renewed=1` guard** (§4.2) **and the single client interceptor**
   (§5.3).
   *Gate: with the token forced near expiry, a page load renews with no visible login; with the
   host session cleared, it lands on the login page **once** and does not loop; **the marker
   survives the host round trip** — assert `?renewed=1` is present in the URL DatsPet finally lands
   on, since both validators and `_append_return`'s quoting sit between the two ends (§4.2).*
8. **DatsPet: the shared hand-off helper; Adopt runs the checkout** (§5.2).
   *Gate: a freshly designed pet is offered by the host's import listing with a quote, and a
   confirm charges exactly once; a second checkout of the same pet charges 0; a pet designed
   anonymously and adopted after sign-in appears in the listing (this is the claim-vs-keep test
   Rev.1 would have failed).*
9. **DatsPet: delete the push path** (§6.2) **and the resync back door** (§6.2a, §4.6) — same
   change as step 8, no dual-write layer left behind.
   *Gate: full `webui/tests` + `pet_factory/tests` green; `npx tsc --noEmit` clean (unused checks
   catch the orphaned client helpers); no reference to `/api/datsme/accept` anywhere; the pending
   endpoint returns `[]` for a user with kept-but-unadopted pets; an inbound launch carrying an
   `rsx` claim lands on the designer and posts nothing; **a claimed-but-unkept draft is purged**
   (the `not_pending` exemption is gone — §4.6 (b)) while a claimed-and-kept pet survives.*
10. **Rewrite the TTL comment** (§4.3) and update `docs/SPEC_DATSPET_HOUSE_ADOPT.md` to note that
    the pull is now the *only* purchase path and that the hand-off is a shared helper.
11. **Full DPP round-trip E2E** (`./scripts/e2e_design_a_pet.sh`) against staging, then the
    acceptance criterion by hand on staging, then production.

**Not in this spec's build order:** the catalog purchase surface, split to
`docs/SPEC_DATSPET_CATALOG_PURCHASE.md`. It depends on step 8's helper, so it can only start after
step 8 lands — and on curated sample bundles, which do not exist yet (decision 12).

---

## 10. Open questions for review

1. **`LAUNCH_RENEW_THRESHOLD_SEC` = 900 s?** Longer renews more often for no benefit; shorter
   risks a lapse mid-interaction. 15 min is the proposal, not a measurement.
2. **Should renewal be automatic on page load, or only when the session is actually needed?**
   Automatic is simpler and invisible; on-demand is fewer host round trips. The `?renewed=1` guard
   is required either way. Proposal: automatic, because a stale nav greeting is itself a bug.
3. **`ANON_COOKIE_TTL_SEC`?** It only has to outlive one anonymous design session. Proposal: 30
   days, matching the host's window, so a returning anonymous visitor finds their pets — but a
   short value (hours) is defensible and leaks less. This is the one §4.5 knob with no obviously
   right answer.
4. **Does the post-design Adopt want a one-item checkout URL, or should it reuse the multi-select
   shape?** `?items=<id>` already supports one; the question is whether the host's checkout page
   reads well for a single fresh pet or wants a `from=design` presentation hint.
5. **Should sign-out offer "sign out of DatsPet only"?** Ending both is the requirement; a
   partner-only sign-out is a strictly smaller action (today's `POST /api/datsme/logout`) that
   could stay reachable. Proposal: no — two sign-out buttons is a confusing surface.
6. **Should the DatsPet nav show the balance** now that purchases happen host-side? It would
   need a host read per page load. Proposal: no; the checkout shows it authoritatively.
7. **Does `_enforce_house_not_full` at keep time (`app.py:1720`) still belong** once the host
   also checks house-full before charging (`pet_writeback.py:340`)? Both are correct — local
   fails fast, host is authoritative — but the local one now rejects before the user has
   committed anything. Proposal: keep both; verify the two error messages don't contradict.
8. **Should `ANON_COOKIE` be `SameSite=None` like the launch cookie, or `Lax`?** §4.5 (a) copies
   the launch cookie's attributes for consistency, and the two-origin dev split (`:19955` frontend
   → `:19954` backend) means the frontend's XHR is cross-origin, which forces `None`+`Secure`
   exactly as `datsme_integration.py:76-83` documents. Proposal: copy them, and revisit only if
   DatsPet ever moves same-origin (front-door §8 Phase 4), when both cookies change together.

---

## Appendix — grounding (verified 2026-07-30, Rev.4)

Every claim above was read in the working trees, not recalled. Rev.4 re-verified every Rev.3
citation; **all held** — including the catalog-content finding, re-checked directly: `catalog.json`
lists exactly `cat` and `dog`, the only `*.zip` under `animal_catalog/` is
`_candidates/cat/samples/snowleopard.zip`, and no `<animal>/samples` directory exists, so
`list_samples` returns `[]` for both animals. Bolded entries are the ones Rev.4 added or corrected.
Catalog-only citations live in `docs/SPEC_DATSPET_CATALOG_PURCHASE.md`'s own appendix.

**`datsme-pet-factory_wu`** — `webui/datsme_integration.py`: `:66-83` cookie names/TTL/samesite,
`:92-103` `_safe_return_path` (charset admits `?` `=` `&`), `:133-137` `_datspet_public_url`
("*In dev this is the backend's own origin*"), `:140-142` `_frontend_url`, `:154-199` manifest
(`base_url=_datspet_public_url()`), `:226` `launch`, `:243-252` **the `rsx` resync short-circuit**,
`:277` cookie set, `:299` `_read_launch_cookie`, `:314-330` `resolve_launch_identity` (re-verifies;
returns None for BOTH absent and stale), `:353` capabilities, `:468` `_has_valid_admin_cookie`,
`:484-526` `datsme_session` + prebuilt `signin_url` (`return=/design`) / `signup_url` /
`import_url`, `:530-546` `datsme_logout`, `:548` `require_admin_launch`, `:571` `pet_design_cost`
(best-effort/display), `:592` `accept_pet`, `:642-648` threadpool + deadlock note, `:657`
`_post_pet_writeback`, `:706-707` ack+keep, `:783` `drain_retry_queue`, `:853` `/partner/export`,
`:873-891` `_export_item` (**omits `transfer` when `bundle_sha256` or `pose_count` is absent**),
`:906` `/partner/imported/{user_id}`, `:941` ownership check, `:978-993`
`/partner/results/{user_id}/pending`, `:999` `_require_host_signature`.
`webui/db.py`: `:11-12` NULL = standalone, `:64` `external_user_id`, `:273` `list_saved_pets`,
`:288-304` **`claimable` = unowned**, `:306-315` **`_scope_clause` unions NULL into every signed-in
caller**, `:318` `keep_pet`, `:335` `delete_pet`, `:346-364` `purge_drafts` (**`:357-359`
`not_pending` exempts any activity-stamped unacked pet from EVERY scope** — Rev.3 §4.6 (b)),
`:384-393` **`list_pending_writebacks`
(`writeback_acked_at IS NULL AND datsme_activity_id IS NOT NULL`)**, `:396-416` `export_pets`
(exact match), `:425` `count_saved_pets`, `:438-468` `claim_unowned_pets` (**binds on
`WHERE id=? AND external_user_id IS NULL`, and `:462` SETS `datsme_activity_id`** — the coupling
behind §4.6 (b)), `:471-485` `revoke_user` (**`anonymize` → `external_user_id=NULL`**).
`webui/app.py`: `:660-666` **the reference sidecar layout (`{id}.json` holds `owner`; swept at 24 h
by `_cleanup_transients`)**, `:696-725` **`_save_reference` stamps `owner`**, `:729-734`
`_reference_visible` (the reference scope mirror), `:737-758` **`_load_reference` — 404 "not
yours" / 400 "expired"**, `:973`/`:1100`/`:1146`/`:1195`/`:1420` owner
from `resolve_launch_identity` on the write paths, `:1095-1113` **`/api/reference/{id}.png` —
"Owner-scoped" AND returns a raw `FileResponse`** (the case §4.5 (a)'s middleware exists for),
`:1198`/`:1501` **`_load_reference` on the design + build paths** (what breaks if references are not
swept — §4.5 (c)), `:478`/`:595` **the finished pet is stamped `external_user_id=job.external_user_id`**,
`:1542` **the job captures the owner at submit**, `:1572-1573` `job_status` (**unscoped — polling
survives a sign-in**), `:1592` `stop_job`'s owner check, `:1378`/`:1405` **the two
`Cache-Control: public` responses**, `:1748-1750` **`_IMMUTABLE_ASSET_CACHE` is `private` —
*"never a shared proxy that could serve another user"***,
`:1607-1611` `_can_access`, `:1614` draft purge,
`:1666` house config, `:1675-1681` `list_pets` (drafts excluded), `:1683-1706` `claim_pets`
(**binds by pet id alone**), `:1708-1726` `keep_pet` + house cap, `:1798` `RETRY_DRAIN_EVERY_S`,
`:1838-1849` `_maintenance_loop` retry drain (`TRANSIENT_SWEEP_EVERY_S` is the separate reason the
loop survives).
`web/src/lib/api.ts`: `:23` `API_URL` (empty in dev → same-origin proxy), `:53` `claimPets`,
`:849` `keepPet`, `:886` `DatsmeSession`, `:915` `datsmeLogout`, `:922` `AcceptResult`, `:938`
`acceptPetToDatsme`.
`web/src/components/NavAuth.tsx:67`; `web/src/components/PublicLanding.tsx:40-71`;
`web/src/app/house/page.tsx:100, 128-147`; `web/src/app/design/general/BaseGalleryDialog.tsx`.
No `localStorage`/`sessionStorage` anywhere under `web/src/`. No password/user-table primitives
anywhere (`bcrypt`, `passlib`, `argon2`, `CREATE TABLE users`, `session_token`: zero hits).

`webui/db.py` (cont.): `:76-83` **the `jobs` table carries `external_user_id`**, `:495-508`
`record_pool_job` (**persists it**), `:107-118` `ai_usage` also carries it (anonymous rows now read
`anon:…` rather than NULL — a reporting nuance, not a behavior change).
`webui/datsme_integration.py` (cont.): `:823` **`GET /api/datsme/bundle/{token}` — server-to-server
but NOT under `/partner/`** (the second `NO_COOKIE_PREFIXES` entry, §4.5 (a)).

**`datsme_me`** — `api/apps/dpp/routes.py`: `:36-42` **`_safe_return` (host-side charset —
admits `?` `=`)**, `:45-55` **`_append_return` (`quote(safe, safe='/?=&')`)** — together the
proof that `?renewed=1` survives the round trip (§4.2), `:58` `_login_bounce`, `:143-184` `_login_launch_impl`,
`:156` signed-out branch, `:179` `?signin=unavailable`, `:187` `_partner_origin_for_activity`,
`:197` `login_launch`, `:210` `admin_launch`, `:243-306` **`sync-pending`** (`:254-263` "the
user-facing affordance is NOT yet built", `:282-293` resync mint with
`resync_hint=partner_result_id`). `api/apps/dpp/service.py`: `:58` `LAUNCH_TOKEN_TTL = 60 min`,
`:445` `partner_origin`, `:457-473` `mint_launch_token(resync_hint=…)`, `:645` **`claims["rsx"]`**,
`:653` mint with `partner.hmac_secret`, `:802-818` verify with `partner.hmac_secret` + `pid` check,
`:1210` `_IMPORT_ADAPTERS`, `:1258` `apply_writeback` (push/pull indistinguishable), `:1550`
`fetch_partner_export`. `api/apps/dpp/import_routes.py`: `:47` router prefix
`/api/integrations`, `:112` `_export_items`, `:134-138` draft skip, `:199-265` quote listing
(`:234-240` **skips an item with no usable pricing basis, log line only**), `:269` binding
checkout. `api/apps/dpp/pet_writeback.py`: `:100-108` `price_user_pet`, `:315-321` price from
fetched bytes, `:329` `pricing_basis_mismatch`, `:340` house-full before charge, `:357-362`
`require_credits` / "402 before any mutation". `api/auth.py`: `:37` `create_token`, `:56`
`auth_cookie_kwargs` (`samesite: lax`), `:70-98` `set_auth_cookie`. `api/routes/auth.py`: `:1054`
logout, `:1067-1077` best-effort revoke, `:1079-1081` matched-attribute delete.
`api/datsme_config.py`: `:73` the sliding-window comment, `:76` `TOKEN_EXPIRE_HOURS = 720`, `:82`
`SESSION_ROTATE_AFTER_HOURS = 24`.
`web/src/app/import/[partner]/page.tsx`: `:9` the `?items=` URL shape, `:30-32` preselection not a
filter, `:127` param read, `:133-139` **the signed-out bounce that preserves `?items=`** (§3.4).
**Rev.4 host-prerequisite citations (§3.4):** `api/session_store.py:402-414` `revoke_session`;
`api/auth.py:56-68` `auth_cookie_kwargs` (**`samesite: "lax"` is at `:68`**), `:70-98`
`set_auth_cookie`, `:339-353` **`get_optional_user` → `_session_ok`, fails soft**;
`api/csrf.py:41` **`_SAFE_METHODS = {"GET","HEAD","OPTIONS"}`**, `:94` the exemption check;
`api/apps/dpp/models.py:46` **`PartnerApp.slug` is the primary key — one partner row per host**;
`api/social_ledger/social_ledger_routes.py:188` `/api/credits/me`, `:217` `/api/credits/convert`,
`:242` `/api/credits/gift`, `:410` monthly allowance, `:427` admin grant;
`api/social_ledger/social_ledger_service.py:501` `require_credits`.
