# SPEC — DatsPet Front Door (public landing + "Sign in with DatsMe")

**Status:** Design — **Rev.2** (2026-07-14), for review. A public landing page at the DatsPet
root URL with **Sign in with DatsMe** (a launch-token bounce — no DatsPet accounts, ever) and
**Create a DatsMe account** (routes out to DatsMe's own signup). The landing also explains what
DatsPet is and how it relates to DatsMe. Builds on **`docs/SPEC_DATSPET_DPP_INTEGRATION.md`**
(the launch/writeback machinery this reuses). Grounded against both working trees (appendix).

**This spec OWNS the shared bounce/mint plumbing** that `docs/SPEC_MOTION_PROFILE_ADMIN.md` consumes:
(a) DatsPet `/launch`'s validated `return` path param (§3.1), (b) the host **shared mint-and-redirect
helper** that `login-launch` and the admin's `admin-launch` are thin wrappers over (§2.1), and
(c) the additive `extra_claims` param on `mint_launch_token` (§2.1). Build this spec **first**; the
admin bounce is then this flow + `require_system_admin` + an `adm` claim.

**Rev.2 — reconciled with the admin spec.** Resolved open question #5: the admin variant is a
**separate thin endpoint** (`admin-launch`), not a `?admin=1` flag on `login-launch` — it carries a
different dependency (`require_system_admin`) and claim, and mixing them would fold an authorization
branch into the sign-in path. Both are wrappers over the one shared helper (§2.1).

**Author's intent (verbatim goal):** "we do need a front door so when user goes to datspet url,
it lands on the landing page, and there should be a user can sign in using the datsme
credential, and also if it can sign up for an account, but then it will route out to datsme
signup process. so this can be the public landing page, and we can describe some basic things
about the datspet and datsme relationship."

**Repos touched:** `datsme-pet-factory_wu` (landing page, `/launch` return-path support,
session/logout endpoints) and `datsme_me` (one GET bounce endpoint + one reusable consent page).
No SDK change.

---

## 0. The core decisions (read this first)

1. **"Sign in with DatsMe" is a launch-token bounce, not a login form.** DatsPet has no user
   table, no passwords, no session store of its own — its only identity is the DatsMe launch JWT
   (`webui/datsme_integration.py`, `resolve_launch_identity`). The front door does not change
   that: the Sign-in button sends the browser to a new DatsMe endpoint that (a) uses the
   existing DatsMe session, or bounces through DatsMe's login page first, then (b) mints a
   normal `design_a_pet` launch token and redirects back to DatsPet's existing `/launch`. After
   the bounce, the user is in **exactly the state a DatsMe-initiated "Design a pet" launch
   produces** — same cookie, same capabilities, same Accept/adopt flow. One session model, two
   entrances.

2. **Sign-up lives on DatsMe, full stop.** The landing's "Create a DatsMe account" link goes to
   DatsMe's `/signup`. DatsPet never proxies, brands, or wraps the signup form — one account,
   one signup, one place credentials exist. (Signup already starts a session immediately —
   `routes/auth.py:331` sets the auth cookie before email verification, and no DPP launch path
   gates on `email_verified` — so a fresh account can sign in to DatsPet right away.)

3. **Consent stays on the host, as a reusable page.** `pets.write` is **risk=medium**
   (`apps/dpp/capabilities.py:89`), and `should_auto_grant` only auto-grants *low*-risk caps —
   so a first-time user always needs a consent step. Today that consent UX exists only as an
   inline dialog behind DatsMe's own launch buttons (`settings/pet/page.tsx`,
   `ActivityEditor.tsx`). A GET bounce can't show a dialog, so the bounce endpoint redirects
   first-time users to a small new DatsMe page that reuses the existing
   `components/integrations/ConsentDialog.tsx` + `pending-consent` + `grant` APIs, then resumes
   the bounce. This page is **partner-generic** — the next partner front door uses it unchanged.

4. **The landing is public and standalone-safe.** It renders marketing content with zero auth.
   In integrated mode it offers Sign in / Sign up / Continue designing; in standalone mode
   (`DATSME_HMAC_SECRET` unset) it hides the DatsMe buttons and offers "Start designing (local
   mode)". Rev.1 does **not** change design-page gating: `/design` stays reachable
   (`/make` is deleted — SPEC_PET_DESIGNER_FLOW §11)
   exactly as today (anonymous = base tier, adopt requires the launch session). Whether
   generation itself should require sign-in on the public host is a separate decision (§9.3).

5. **One bounce mechanism, shared with the admin spec.** DatsPet's `/launch` gains a safe
   `return` path parameter here; SPEC_MOTION_PROFILE_ADMIN's admin bounce
   (`return=/admin/motions`, `adm` claim) rides the same mechanism. On the host, the admin-launch
   endpoint should be a thin sibling of this one (same mint+redirect helper; it adds
   `require_system_admin` — note: that is the dependency's real name, `api/auth.py:356`, not
   `require_admin`). Build the shared parts once, here (§8 ordering note).

---

## 1. The flows

### 1.1 Signed-in DatsMe user (steady state — every visit after the first)
```
pet.datsme.me/  (landing)
   └─ [Sign in with DatsMe] ──▶ datsme.me/api/integrations/login-launch
                                     ?activity=design_a_pet&return=/design
        ├─ get_current_user (session cookie) ✓
        ├─ consent already granted ✓  (one-time; medium-risk caps persist per user+partner)
        ├─ mint_launch_token(user, "design_a_pet", "datspet")   # existing machinery: nonce,
        │                                                        # cap claim, health gate
        └─ 303 ──▶ pet.datsme.me/launch?token=<jwt>&return=/design
                      ├─ verify_launch_token (existing HMAC path)
                      ├─ set datsme_launch cookie (existing)
                      └─ 303 ▶ /design?from=datsme     (return path, validated)
```

### 1.2 Not signed in on DatsMe
Same, except `login-launch` has no session → `302 → datsme.me/login?next=<login-launch URL,
urlencoded>`. The login page already honors a same-origin `?next=` (`login/page.tsx` — it
rejects off-origin and protocol-relative values), and in prod `/api` is served on the same
origin as the web app (`deploy/nginx.production.conf:29`), so after login the browser lands
back on `login-launch` and continues as §1.1.

### 1.3 First-time user (consent not yet granted)
`login-launch` calls the same consent logic `POST /api/integrations/launch` uses; where the
POST returns `409 consent_required` (handled today by an inline dialog), the GET instead
`302 → datsme.me/integrations/consent?activity=design_a_pet&next=<login-launch URL>`. The new
page loads `GET /api/integrations/pending-consent/{activity}`, renders `ConsentDialog`, POSTs
the grant, then navigates to `next` — which now mints cleanly. Decline → back to the DatsPet
landing with `?signin=declined` (landing shows a toast, stays public).

### 1.4 No DatsMe account yet
Landing → **[Create a DatsMe account]** → `datsme.me/signup`. Rev.1 does not thread a return
path through signup (signup hard-routes to `/verify-email`, `signup/page.tsx:42`); after
verifying, the user returns to DatsPet and clicks Sign in — which is now instant (§1.1, since
signup already created the session). Threading `next` through signup → verify-email is a
contained DatsMe-web enhancement, deferred (§9.2).

### 1.5 Failure postures (all fail toward the public landing, never a dead end)
- Host down / partner health gate trips (`mint_launch_token` raises "unavailable") →
  `302 → {partner origin}/?signin=unavailable`; landing toasts "DatsMe is unavailable right now."
- Token invalid/expired at DatsPet `/launch` → existing 401 behavior (unchanged).
- `login-launch` reached with an unknown/partner-less activity → 400 (same rule as the POST).

---

## 2. DatsMe changes (the host side — you deploy)

### 2.1 `GET /api/integrations/login-launch` (new, in `apps/dpp/routes.py`)
Partner-generic; nothing in it names DatsPet.

```
GET /api/integrations/login-launch?activity=<activity_id>&return=<path>
  1. current_user (optional dependency):
       none → 302 {WEB_ORIGIN}/login?next=<urlencoded self URL>
  2. Resolve activity → partner via the activity catalog's partner_launch
     (identical lookup to POST /launch, routes.py:41-67). Unknown/no-partner → 400.
  3. Consent check (same helper path the POST uses):
       missing required grants → 302 {WEB_ORIGIN}/integrations/consent
                                     ?activity=<id>&next=<urlencoded self URL>
  4. result = mint_launch_token(social_db, user, activity_id, partner_slug)
       ValueError("unavailable") → 302 {origin(partner.launch_base_url)}/?signin=unavailable
  5. 303 → f"{result['launch_url']}&return={validated_return}"
```
- **`return` validation:** must match `^/[A-Za-z0-9/_\-?=&]*$` and not start with `//` — a
  path on the *partner's* origin, forwarded opaquely; DatsPet re-validates on arrival (§3.1).
  Default when absent: omit the param (partner's `/launch` uses its own default).
- **The shared helper (a named deliverable, `apps/dpp/service.py`):**
  `resolve_and_mint_launch(social_db, user, activity_id, *, extra_claims=None) -> {launch_url,...}`
  — extract the POST `/launch` body's activity-resolve + consent-check + health-gate + mint sequence
  into this one function. Then:
  - `POST /api/integrations/launch` (existing) → thin wrapper (unchanged behavior).
  - `GET /api/integrations/login-launch` (this spec) → thin wrapper.
  - `GET /api/integrations/admin-launch` (SPEC_MOTION_PROFILE_ADMIN §2.2) → thin wrapper:
    `require_system_admin` + `extra_claims={"adm": True}`.
  All three call the **same** helper, so activity-resolution, consent, and health-gating can never
  drift between the DatsMe-side button, the front-door sign-in, and the admin bounce.
- **`mint_launch_token` gains `extra_claims: dict | None = None`** (additive; merged into the JWT
  claim set the SDK already exposes as `raw_claims`). Used only by the admin wrapper today; **no SDK
  schema change**, no partner-side change to read it. This param is owned by THIS spec (both consumers
  reference it here) so there is one definition.
- **CSRF note:** this is a state-light GET (it inserts an `IntegrationNonce`, as every mint
  does) reachable by top-level navigation — the same shape as an OAuth authorize endpoint. The
  worst a forced navigation achieves is launching the victim into *their own* DatsPet session.
  Accepted; documented here so it isn't "discovered" later.

### 2.2 `web/src/app/integrations/consent/page.tsx` (new, partner-generic)
Query: `activity`, `next` (same-origin-or-path rules as login's `next`). Auth-gated (redirects
to `/login?next=` itself if signed out). Loads `pending-consent/{activity}`, renders the
existing `ConsentDialog` (`components/integrations/ConsentDialog.tsx`) full-page, on approve
POSTs the grant then `window.location = next`; on decline navigates to the partner origin root
with `?signin=declined` (derived server-side into the payload, or passed as `decline_to`).
If nothing is pending (user already granted, e.g. back-button), skip straight to `next`.

### 2.3 Explicitly not changed
- `POST /api/integrations/launch` behavior (DatsMe-side buttons keep their inline dialog).
- Signup/verify-email pages (Rev.1 — §9.2).
- The SDK, the manifest, capabilities, writeback — untouched.

---

## 3. DatsPet backend changes (`webui/datsme_integration.py`)

### 3.1 `/launch` honors a `return` path (additive)
After the existing verify + cookie logic, if a `return` query param is present and matches
`^/[A-Za-z0-9/_\-?=&]*$` (and not `//`-prefixed), redirect to `{_frontend_url()}{return}`
instead of the hardcoded `/design?from=datsme`. Invalid or absent → today's default, unchanged.
This is the same mechanism SPEC_MOTION_PROFILE_ADMIN's admin bounce consumes
(`return=/admin/motions`) — implement once here.

### 3.2 `GET /api/datsme/session` grows the landing's needs (additive fields)
Today it returns `{launched, user_id, capabilities, cost}` / `{launched: false}`. Add:
- `integrated: bool` — whether `DATSME_HMAC_SECRET` is configured (landing hides all DatsMe
  buttons when false; this is the standalone switch).
- `signin_url: str | None` — pre-built
  `{DATSME_PUBLIC_URL}/api/integrations/login-launch?activity=design_a_pet&return=/design`.
- `signup_url: str | None` — `{DATSME_PUBLIC_URL}/signup`.
- `admin: bool` — whether a valid `datspet_admin` cookie is present (verified, not parsed). Lets the
  toolbar show the Admin link only to admins (SPEC_MOTION_PROFILE_ADMIN §2.4). Always `false` until
  that spec sets the cookie — harmless to add now, so the admin spec needs no session-endpoint edit.

The frontend never hardcodes a DatsMe origin — it renders the URLs this endpoint hands it
(per the one-adapter-per-backend rule; `web/src/lib/api.ts` is that adapter).

### 3.3 `POST /api/datsme/logout` (new, small)
Clears the `datsme_launch` cookie **and the `datspet_admin` cookie** (`delete_cookie` with the same
samesite/secure attributes) and returns `{ok: true}`. This ends the **DatsPet** session only — the
landing labels it "Sign out of DatsPet" and the copy notes the DatsMe session itself is managed on
DatsMe. Clearing `datspet_admin` here (even though this spec doesn't set it — the admin spec does) is
deliberate: logout is the one place that owns "end the DatsPet session," so it clears every
DatsPet-issued cookie. Harmless when `datspet_admin` is absent.

---

## 4. The landing page (`web/src/app/page.tsx` → new `PublicLanding` component)

> ⚠️ **Superseded in part (SPEC_PET_DESIGNER_FLOW §11):** `DesignLanding` and `/make` are
> DELETED. `/design` no longer renders the world tiles — it 307s to `/design/general` (in
> nginx for prod, `deploy/nginx-default.conf`; the Next route is the dev half). It is still
> the DPP deep-link target and still must answer, which is the only part of this section
> that still binds. Original text follows.

`/` becomes the public front door. `DesignLanding` keeps rendering at `/design` (the DPP
deep-link target — commit 53da4fd made it the home; this spec moves the home back out in favor
of the front door, `/design` itself is untouched). `/make` and `/house` unchanged. Styled with
the existing app tokens (`globals.css`), toasts + `ConfirmModal` per the project UI rules.

### 4.1 States (driven by one `GET /api/datsme/session` call on mount)
| Session state | Hero actions |
|---|---|
| `integrated && launched` | **Continue designing →** (`/design`), "Signed in via DatsMe" chip, Sign out |
| `integrated && !launched` | **Sign in with DatsMe** (`signin_url`), **Create a DatsMe account** (`signup_url`) |
| `!integrated` (standalone) | **Start designing** (`/design`) — no DatsMe buttons, "local mode" note |
| fetch failed | Same as standalone, plus a non-blocking "couldn't reach the server" toast |

`?signin=unavailable` / `?signin=declined` in the URL → the matching toast, then param is
cleaned from the URL (replaceState).

### 4.2 Content (draft copy — edit freely, structure is the spec)
- **Hero:** "Design your own animated pet." Sub: "Describe it or pick a breed — DatsPet builds
  a living, walking, playing pet you can adopt into your DatsMe house."
- **How it works (3 steps):** ① Pick a base or describe your animal → ② DatsPet generates it
  and brings it to life, pose by pose → ③ Adopt it — it walks home to your DatsMe pet house.
- **DatsPet ♥ DatsMe (the relationship section the author asked for):**
  - "DatsPet is a partner app of DatsMe. One account is all you need — you sign in *with*
    DatsMe, on DatsMe's own page. DatsPet never sees or stores your password; it receives a
    signed, expiring pass that says who you are."
  - "Pets you adopt live in your DatsMe house, next to everything else you do there. Your pet
    data is yours: export or delete it any time from DatsMe's data controls." (True today:
    `/partner/export`, `/partner/revoke`.)
  - "No DatsMe account? Creating one takes a minute — and it works across every DatsMe partner
    app, not just DatsPet."
- **Footer:** links to DatsMe, and the standalone note where applicable.

### 4.3 Toolbar (`web/src/app/layout.tsx`)
Add "Home" pointing at `/` if the current Home link's target changes meaning; otherwise the nav
(Home / Make / House) stays as-is. No auth state in the toolbar for Rev.1 — the landing owns
sign-in UX (§9.4 for the optional signed-in chip).

---

## 5. Security notes (all reuse, no new trust surface)

- **Trust root unchanged:** DatsMe login + HMAC launch JWT. DatsPet still verifies (never
  parses) the token on every identity-bearing request (`resolve_launch_identity`).
- **Open-redirect hardening in three places, same rule each:** DatsMe login's `next`
  (already enforced), `login-launch`'s `return` (§2.1), DatsPet `/launch`'s `return` (§3.1) —
  path-only, no `//`, no scheme.
- **No enumeration change:** the landing is public and states nothing about any account.
- **Logout is cookie-clearing only** — no server session exists on DatsPet to invalidate; the
  JWT expiring (~60 min) remains the backstop, exactly as today.

---

## 6. Dev-mode caveat (two-origin dev vs one-origin prod)

In prod, web + `/api` share one origin (nginx), so the login `next=` hop works. In dev, DatsMe
web (:19995) does not proxy `/api` (:19994), so the *signed-out* leg of the bounce would 404
after login.

**RESOLVED (Rev.2) — option (a) implemented:** `datsme_me/web/next.config.mjs` now has a
**dev-only** `rewrites()` mapping `/api/:path*` → `http://localhost:19994/api/:path*` (override with
`DEV_API_ORIGIN`). It is skipped when `NODE_ENV=production` (nginx owns `/api` there), so dev matches
prod's one-origin shape and every same-origin assumption in this flow holds in both. The DatsMe dev
web server must be **restarted** to pick up the config change.

---

## 7. What this deliberately does not do

- No DatsPet accounts, password reset, profile page, or session store.
- No change to generation gating (anonymous base-tier design still works — §9.3 to revisit).
- No signup return-threading (§9.2).
- No merging of the repos/apps: shared identity is a property of the token flow, not the
  codebase. DatsPet remains the reference DPP partner.

---

## 8. Build order

0. **DatsPet `/launch` `return` param** (§3.1) — shared with the admin spec; land first.
   *Gate: valid path honored; absent/invalid falls back to `/design?from=datsme`; `//` and
   absolute URLs rejected (unit tests).*
1. **Session additions + logout** (§3.2, §3.3). *Gate: standalone reports `integrated: false`
   and null URLs; integrated reports both URLs; logout clears the cookie and `launched` flips.*
2. **Landing page** (§4). *Gate: all four states render (mock the session endpoint); toast
   params fire once; standalone shows no DatsMe buttons.*
3. **Host: shared mint helper + `login-launch`** (§2.1) — refactor POST `/launch` onto the
   helper first, then the GET. *Gate: signed-in mints and lands on `/design` via the bounce;
   signed-out passes through login and completes; unknown activity 400s; existing POST launch
   tests stay green.*
4. **Host: consent page** (§2.2). *Gate: a fresh user (no grant) is detoured, approves, lands
   signed-in on DatsPet; decline lands on the landing with the toast; an already-granted user
   skips straight through.*
5. **Host deploy + end-to-end** (§1.1–1.4 walked on staging, incl. a brand-new account
   through signup → verify → sign-in).

**DEPLOY ORDERING IS A HARD CONSTRAINT (resolved — deploy the HOST first).** `signin_url` is
non-null whenever DatsPet is integrated; there is **no host-readiness gate**. So if DatsPet's
front door ships before `datsme_me`'s `login-launch` endpoint, the Sign-in button targets a URL
that 404s. **Deploy `datsme_me` (host) first, then DatsPet.** The "button renders only when
`signin_url` is non-null" guard protects the *standalone* case (no DatsMe host at all) — it does
**not** protect against a *missing host endpoint* on an integrated instance. A
`DATSME_LOGIN_LAUNCH_READY` flag was considered and rejected as needless: host-first ordering is
simpler and has no failure window (§9.1).

---

## 9. Open questions for review

1. ~~**Rollout coupling**~~ — **RESOLVED (Rev.3): deploy the HOST first, no readiness flag.**
   `signin_url` is always non-null when integrated (no host-readiness gate), so an integrated
   DatsPet whose host lacks `login-launch` would 404 the Sign-in button. Host-first ordering is
   simpler than an env flag and has no failure window. See §8.
2. **Signup threading** — thread `?next=` through signup → verify-email so a brand-new user
   lands back on DatsPet automatically? (Contained DatsMe-web change; Rev.1 defers.)
3. **Anonymous design on the public host** — the landing now gives a clear signed-in path;
   should anonymous generation on prod eventually require sign-in (GPU cost control), or stay
   open as the demo/top-of-funnel? (Separate spec if pursued — it touches tier gating.)
4. **Signed-in state in the toolbar** — add a small chip/avatar later, or keep auth UX
   landing-only?
5. ~~**Endpoint name**~~ — **RESOLVED (Rev.2):** two thin endpoints (`login-launch`,
   `admin-launch`) over one shared helper, not a `?admin=1` flag. The admin one carries a different
   dependency (`require_system_admin`) and claim; folding it into the sign-in path would put an
   authorization branch in the user login flow. See §2.1.

---

### Appendix — grounding (verified 2026-07-14)
- DatsPet identity = launch JWT only; verify-don't-parse: `webui/datsme_integration.py`
  (`/launch` :196, `resolve_launch_identity` :262, session endpoint :305, cookie attrs :81).
- Host mint machinery (nonce, cap claim, consent gate, health gate):
  `datsme_me/api/apps/dpp/service.py` (`mint_launch_token` :440; consent/auto-grant logic in
  the mint body; `should_auto_grant` in `apps/dpp/capabilities.py:245`).
- `pets.write` risk=medium: `apps/dpp/capabilities.py:86-90` → consent always required once.
- Existing launch entry is POST-only (`apps/dpp/routes.py:41`, prefix `/api/integrations`,
  routes.py:30) — frontend redirects itself (`settings/pet/page.tsx:465-513`), including the
  inline consent dialog on 409.
- Consent dialog component to reuse: `web/src/components/integrations/ConsentDialog.tsx`.
- Login page honors same-origin `?next=`: `datsme_me/web/src/app/login/page.tsx:49-67`;
  signup does not and routes to `/verify-email`: `signup/page.tsx:42`.
- Signup starts a session pre-verification: `datsme_me/api/routes/auth.py:331` (cookie set);
  no `email_verified` gate on the DPP launch path.
- Prod one-origin proxy: `datsme_me/deploy/nginx.production.conf:29` (`location /api`).
- Current DatsPet home = `DesignLanding` at `/` and `/design`: `web/src/app/page.tsx`
  (commit 53da4fd context).
- Admin-bounce sibling this shares plumbing with: `docs/SPEC_MOTION_PROFILE_ADMIN.md` §2
  (note: the host dependency's real name is `require_system_admin`, `api/auth.py:356`).
