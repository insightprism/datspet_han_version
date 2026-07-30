# SPEC — DatsPet Catalog Purchase (browse ready-made pets, buy with credits)

> **CLOSED & ARCHIVED — 2026-07-30. Executed in full and verified on staging with a real purchase.**
>
> A signed-out visitor can pick a ready-made pet, adopt it, sign in afterwards, and end up owning
> it. Driven end to end on `pet-staging.datsme.me`, not argued:
>
> | Step | Verified |
> |---|---|
> | Signed-out visitor on `/catalog` | tile renders, preview 200 |
> | **Adopt** | pet created under `anon:0d52a1f6…`, draft, 3.5 MB bundle |
> | Sign-in bounce | `return=/catalog?adopted=27fb99f2b045` — the id survives the hop |
> | Return | **claimed** to the DatsMe user, **kept**, activity stamped |
> | Resume | fired automatically → host checkout |
> | Host quote | White Snow Leopard · 8 poses · **110 credits**, sha verified |
> | **Purchase** | **charged 110, matching the quote exactly**; pet in the DatsMe house; DatsPet acked 20:09:23 |
>
> `verify_deployment.sh` 14/14. 563 tests, `tsc` clean, vitest 32, preflight PASSED with
> `/catalog.html` in the export.
>
> **STAGING ONLY, deliberately.** Production stays at `fe8ba0c` pending several more specs — the
> owner's sequencing, not a blocker. Note for whoever deploys it: prod's `/catalog` currently
> answers **200 while serving the landing page**, because `try_files … /index.html` catches the
> missing route. A status code will not tell you whether this shipped; check the page says
> "Ready-made pets".
>
> **Gate 0 was REVISED, not met as originally written (§0.1).** Rev.1–3 required "every catalog
> animal has ≥1 sample" and called it blocking. That encoded a stocking preference as a build
> gate — `dog` is deliberately unstocked, by the owner's decision — so the gate was rewritten to
> the property that actually fails silently: *every promoted sample is sellable*. That one is
> enforced per-sample, with a floor so the suite cannot pass over an empty set. The stock list is
> reported: `[catalog] stocked: cat | not stocked: dog`.
>
> **What this work found outside its own scope:**
>
> 1. **`--muted` was not theme-aware, site-wide on the host.** `applyUserColors` overrode `--bg`,
>    `--text`, `--card`, `--accent`, `--border` per user but never `--muted`, which kept a
>    dark-theme white-at-60%. On a light user theme every `var(--muted)` string rendered at
>    **1.13:1** — invisible. It hid the reason an import was refused behind text that could not be
>    read: the page said "see below" and below was blank. Fixed in `datsme_me` (`7c38a7e5`,
>    `676682b4`): derived from `--text` via `color-mix` at 72%, **measured** at 5.14:1 light /
>    10.07:1 dark. 62% was tried first and rejected at 3.88:1 — under WCAG AA.
> 2. **A refusal reason was styled as a subtitle.** Now full-strength `--text`: it is the answer to
>    "why did nothing happen?", not a caption.
> 3. **`adopt_sample` does not enforce `can_adopt_samples`** (§0.6). The gate is advisory; a direct
>    POST succeeds. Harmless while both tiers are `true`, a silent hole the moment one is not.
>    Setting that flag needs a server check, which is a deliberate §3 exception.

**Status:** Design — **Rev.3.1** (2026-07-30), implementation-ready. A browse-and-adopt surface for
the pre-made sample pets in the animal catalog: pick one, and it goes through the *same* host
checkout a designed pet does. Zero new backend, zero new money code, one new page.

**Split from `docs/archive/SPEC_DATSPET_FEDERATED_SESSION.md`** (Rev.2 §2.5 / §5.4), which specified
this inline before the content gap was found. That spec was the hard dependency — this one consumes
its shared hand-off helper (§5.2 there) and its owner-scope model (§4.5 there), and adds neither.
**It is now CLOSED, executed and verified on staging, so the dependency is satisfied** and nothing
here waits on it.

**Repos touched:** `datsme-pet-factory_wu` only — one page, two test files, and the sample bundles
themselves. No `datsme_me` change. No SDK change.

**Rev.3.1 (2026-07-30) — correction pass on Rev.3.** Rev.3's five findings were re-derived
independently and **all five hold**. Three of its *justifications* did not, and one of those put a
real bug in its own proposed code:

| | Rev.3 said | Actually |
|---|---|---|
| §0.4, §1.1, change #2 | the helper "silently **no-ops**" for a signed-out visitor, so the branch is `!session.import_url` | `import_url` is present while signed out, so the guard never fires and `claimPets` **401s and throws**. The branch is **`!session.launched`** — as `house/page.tsx:101` already has it. Fixed in all three places. |
| step 3 | `_samples_dir` "never consulted `catalog.json`" | It does (`:161` → `_animal` → `list_animals`). It never looks for a `samples` *key*; samples are discovered on disk. Reason corrected, conclusion unchanged — the note is still stale. |
| §0.6 | (not covered) | `adopt_sample` does not enforce `can_adopt_samples` at all, so the flag is **not enforceable** without a backend change. Added, because the lever looks pullable and isn't. |

Everything else in Rev.3 is accepted as written, including both product decisions it deferred:
**two adopts of one sample = two charges** (the sample is a template, not a licence), and **the page
owns the sign-in bounce** (the helper is shared with the house, which never hits the case).

**What changed in Rev.3** (all five found by re-verifying Rev.2's claims against the tree — Rev.2
refreshed its appendix and stopped there, so the body's assertions had never been re-run):

| # | Change | Why |
|---|---|---|
| 1 | **§4's step-3 gate is corrected**, and §1.1 gains the row it was hiding. | *"a second checkout of the same sample charges 0"* is **false**. `source_item_id` is the DatsPet **pet id** — a fresh `uuid4` minted per adopt (`app.py:1499`) — not the sample key. Two adopts of one sample = two pet ids = two full charges. As written the gate fails at verification, or worse provokes a backend "fix" that §3 forbids. |
| 2 | **§0.4's sign-in routing is corrected.** The bounce is the page's job, not the helper's. | Rev.2 asserted behavior the shared helper does not have. *(Rev.3.1: Rev.3 said the helper "silently no-ops" for a signed-out visitor. It does not — `import_url` is set whenever `integrated`, never gated on `launched`, so the guard does not fire and `claimPets` **401s and throws**. The branch condition is `!session.launched`, and getting this wrong put a real bug in Rev.3's own §0.4 snippet.)* |
| 3 | **§4 gains the endpoint tests.** Rev.2 listed only the *content* guard test. | `api.ts` says it in capitals — *"NO TESTS … reviving this means writing them"* — and grep still finds zero across `webui/tests` and `pet_factory/tests`. §0.2 leans on "the backend already exists"; it exists **untested**, and this page is its first real consumer. |
| 4 | **Body citations refreshed.** Rev.2's change #4 refreshed the appendix only. | §0.2/§1/§1.1 still carried Rev.1 numbers: adopt `1408` → **1475**, catalog `1327-1360` → **1394**, entitlement `1381` → **1448**, house cap `1418-1422` → **1490**. A spec that says *"an appendix that says 'verified' has to be"* owes its body the same. |
| 5 | **New §0.6** — the business lever this spec cites is not configured. | Platform §4.4's *"free adopt, paid generate"* is quoted as the reason the endpoint was kept, but **both** tiers set `can_adopt_samples: true`. The gate in §2 is always open today. |

**What changed in Rev.2** (all four found by re-verifying Rev.1 against the tree):

| # | Change | Why |
|---|---|---|
| 1 | **§2's component reuse is withdrawn.** The page gets its own small grid. | `BaseGalleryDialog` renders **breeds** (`base_image_url`), not samples (`preview_url`) — different data, different shape — and its own docstring says *"Do NOT reintroduce a `view` prop to make this multi-purpose again."* What is genuinely shared is `getCatalog()` and the preview URL, not the component. |
| 2 | **Gate 0 is half done and was never as large as Rev.1 implied.** `cat/snowleopard` is promoted and live; only `dog` remains. | Rev.1 never mentioned `promote_sample.py`, the tool that exists for exactly this. `SPEC_PET_DESIGNER_FLOW` §11.2 had already recorded that the staged sample was one command from being real. |
| 3 | **New §0.5** answering "isn't this the house-pet source we rejected?" | Any reader who knows the designer's §2.1/§3.9 will ask it on sight. It deserves the answer inline, not a re-derivation. |
| 4 | Citations refreshed; they had drifted the same day. | `adopt_sample` moved 1408 → **1476** and friends, when `/api/pets/unsaved` landed. An appendix that says "verified" has to be. |

---

## 0. The core decisions

### 0.1 Content is the gate, and it is now half cleared

**`cat` has a real sample; `dog` does not.** As of 2026-07-30:

```
cat: [{'key': 'snowleopard', 'has_preview': True}]
dog: []
```

`pet_factory/animal_catalog/cat/samples/snowleopard.{zip,png}` is promoted and live —
`GET /api/catalog` serves it, and `POST /api/catalog/cat/samples/snowleopard/adopt` returns a
pet id. The bundle carries **8 poses** (`walk, idle, run, sleep, sit, eat, jump, play`) and is a
post-`SPEC_MATTE_REPAIR_ORDER`-F1 build measuring 161 hard-zero px, already verified on a live
DatsMe profile.

**The tool for this exists and Rev.1 did not mention it.** `promote_sample.py` is the only step
that touches the live catalog, deliberately manual, exactly like base-image promotion:

```bash
python3 pet_factory/animal_catalog/promote_sample.py --list       # what is staged
python3 pet_factory/animal_catalog/promote_sample.py cat snowleopard
```

`pet_factory/animal_catalog/**/*.zip` is deliberately un-gitignored so curated bundles ship as
content (`CLAUDE.md`).

**Gate 0 — REVISED, and the revision is the point (2026-07-30).** Rev.1–3 made it *"every catalog
animal has ≥1 promoted sample"* and called it blocking. That is the wrong invariant, on two
grounds:

- **It is not a correctness property.** An animal with no `samples/` directory is legal —
  `list_samples` returns `[]`, the page renders no tiles for it, and nothing misbehaves. "The dog
  shelf is empty" is a merchandising judgement, and the owner has made it: **no dog sample is
  wanted.** A gate that encodes one person's stocking preference as a build blocker will be walked
  past, and a gate that gets walked past teaches everyone to walk past gates.
- **What actually breaks silently is the OTHER thing.** A promoted bundle whose manifest will not
  parse declares no `pose_count`, so the host skips it with a log line and the pet is simply absent
  from the checkout — no error, nothing on screen, visible only to whoever reads the host's logs
  (SPEC_DATSPET_FEDERATED_SESSION §2.5). That is the property worth a hard gate.

**Gate 0, as enforced:** *every promoted sample is sellable* — parses, declares poses, has a
preview. `pet_factory/tests/test_catalog_samples.py` asserts it per sample, plus a floor ("at least
one promoted sample exists anywhere") that prevents the whole suite passing over an empty set.
Which animals are stocked is reported, not asserted.

### 0.2 The backend already exists — this is a surface, not a feature

- `POST /api/catalog/{animal}/samples/{sample}/adopt` (`webui/app.py:1475`) copies a stored sample
  bundle into the caller's house as a **draft**, via the **same insert path a generated pet takes**,
  minus the build. Its docstring calls it *"generation-free (zero GPU)"*. It is already
  owner-scoped and already enforces the house cap.
- `GET /api/catalog` (`webui/app.py:1394`) already returns, per animal,
  `samples: [{key, preview_url}]`.
- The tier table already carries the entitlement (`can_adopt_samples`,
  `pet_factory/tiers/tiers.json`), surfaced by `GET /api/entitlement` (`webui/app.py:1448`).

**"Already exists" is not "already works."** None of the three has a single test — see §4 step 2,
which is where Rev.2's build order was short. The endpoint is *written*; this page is the first
thing that will ever *exercise* it.

What is missing is a page. The client helpers were deleted with the themed pages, and their
absence is **recorded, not accidental** — `web/src/lib/api.ts:245-269` says the endpoint *"still
EXISTS… Platform §4.4 calls it the zero-GPU business lever — free users steered to adopt, paid
users generate — so it is kept deliberately rather than lost by attrition."* This spec is that
note being cashed in.

### 0.3 A second entrance to one checkout, never a second checkout

The adopt action ends in `handOffToDatsme(...)` — the single helper owned by
`SPEC_DATSPET_FEDERATED_SESSION` §5.2. A sample pet is priced by the host from the **bytes of its
bundle**, exactly like a designed pet, by the same `price_user_pet` call
(`datsme_me/api/apps/dpp/pet_writeback.py:100-108`). **This spec introduces no pricing, no
balance check, and no charge.** If it ever appears to need one, that is the signal that the
hand-off helper was reimplemented instead of reused.

### 0.4 Anonymous browsing is fine; anonymous *buying* is not

A signed-out visitor may browse and may adopt — the adopted pet lands under their per-browser
anonymous owner id (`SPEC_DATSPET_FEDERATED_SESSION` §4.5). The purchase needs a host session, and
claim-at-launch binds their anon-owned pet to the DatsMe user on the way back. This works only
because that spec landed first; without it, an anonymous adopt would drop into the shared pool.

**The sign-in bounce is the page's job, not the helper's.** Rev.2 said *"the hand-off routes them
through `signin_url` first"* — it does not. `handOffToDatsme` opens with

```ts
if (petIds.length === 0 || !session.import_url) return;   // web/src/lib/api.ts:1119
```

**and that guard does NOT catch a signed-out visitor.** `import_url` is built whenever the backend
is `integrated`; it is never gated on `launched` (`datsme_integration.py`, the session endpoint —
verified live: signed out returns `launched: false` *with* a populated `import_url`). So the helper
falls through to `claimPets`, which requires a launch and **401s — the call throws.**

That is deliberate, not a gap: the helper's contract is *claim → keep → navigate* for a user who
already has a session, and the house page handles the other case by never rendering the action
(`house/page.tsx:101`, `canAdopt = session?.launched && session?.import_url`). **The signal to
branch on is `launched`, not `import_url`** — the house already gets this right, and any surface
that copies the helper's own guard instead will throw on the exact path it meant to support.

The catalog page wants the opposite posture — **adopt first, then sign in** — because the whole
point is that a visitor can commit to a pet before they have an account. So the page owns a short
branch the helper deliberately does not have:

```
POST …/adopt                      → { pet_id }        adopt succeeds under the anon owner
if (!session.launched)            → push ?adopted=<pet_id>, then datsmeSignInUrlForHere(session)
else                              → handOffToDatsme([pet_id], session)
on mount with ?adopted=<id> and a live session → resume handOffToDatsme([id], session)

                                   ^ `launched`, NOT `import_url`: the latter is present while
                                     signed out, so branching on it sends an anonymous visitor
                                     into handOffToDatsme, where claimPets 401s and throws.
```

Stashing the pet id in the query is **the designer's `?job=` pattern, not a new one**:
`currentReturnPath` (`api.ts:1032-1040`) carries path *and* query precisely so that "sign in and
come back" cannot drop work in flight, and `datsmeSignInUrlForHere` (`api.ts:1027`) replaces the
prebuilt `return=/design` rather than appending a second one. The host's `_safe_return`
(`datsme_me/api/apps/dpp/routes.py:36-42`) is a **shape check, not an allowlist**, so
`/catalog?adopted=<id>` passes with no host change — §"Repos touched" holds.

This is *routing*, and §0.3's tripwire is about *pricing* and the claim-keep-navigate *order*. Both
of those stay inside the helper, untouched. If the page ever finds itself reordering claim/keep, or
computing a number, that is the tripwire firing.

### 0.5 This is not the house-pet source, and the difference is the direction

A reader who knows `SPEC_PET_DESIGNER_FLOW` will object immediately: §2.1 and §3.9 **reject** a
finished pet as a step-1 source, because *"step 2 already ran on it"* — starting there means
designing a design, and the modifiers compound where the user cannot see them. A sample pet is
exactly such a finished design. So why is this allowed?

**Because nothing here feeds the designer.** §2.1 governs what step 1 may accept as *input*. This
spec never puts a sample into step 1; it sells the finished pet as-is and hands it to the host
checkout. The pet the user buys is the pet they looked at — the property §2.1 exists to protect,
arrived at from the other direction.

The rule that would be violated is *"a sample may be used as a base to design from."* That is
**not** proposed here, and if it is ever proposed it must go back through §2.1 rather than around
it.

### 0.6 The business lever this spec keeps citing is not actually pulled

Platform §4.4's *"free users steered to adopt, paid users generate"* is quoted here (§0.2) and in
`api.ts:252-253` as the reason the endpoint was kept alive through the themed-page deletion. It is
a good reason. But **both** tiers in `pet_factory/tiers/tiers.json` currently set
`can_adopt_samples: true` (`:9` and `:17`), so §2's entitlement gate is **always open today** and
the segmentation is aspirational, not shipped.

Nothing here should change that, and the gate stays exactly as §2 specifies — reading the flag
rather than assuming it. The point of building the surface is that the lever *becomes* pullable;
pulling it is a one-line `tiers.json` edit and an owner's pricing decision, on its own clock.

Recorded so the next reader does not mistake the §4.4 quote for a description of live behavior, and
so nobody goes looking for the missing segmentation code. There isn't any: it is a data edit.

**But the flag is NOT enforceable today, and whoever pulls the lever needs to know that.**
`adopt_sample` does not consult the tier table at all (`app.py:1475-1506` — zero references to
`tiers_mod`, `resolve_entitlement` or `can_adopt_samples`). §2's gate is the PAGE hiding a button;
a direct `POST /api/catalog/{animal}/samples/{sample}/adopt` still succeeds. Harmless while both
tiers are `true`, and a silent hole the moment one is set `false`: a one-line data edit that looks
like it works and does not.

This is also the odd one out in this repo. `/api/generate` clips poses **server-side**
(`app.py:815-818`) rather than trusting the browser, and the tier-table posture elsewhere is that
the browser only ever sees its own resolved entitlement. Adopt predates that discipline.

**So: setting `can_adopt_samples: false` on a tier requires a server check in `adopt_sample`, and
that is a deliberate §3 exception** — a real backend change, to be justified when the lever is
actually pulled, not smuggled in with the page. This spec does not make it, because it does not
pull the lever.

---

## 1. The flow

```
user browses /catalog                    ← GET /api/catalog already carries each animal's
                                            samples + preview URLs (app.py:1394)
user clicks "Adopt this one"
   1. POST /api/catalog/{animal}/samples/{sample}/adopt   ← app.py:1475, zero GPU, returns pet_id
                                                            (draft=1, owner = caller's owner id)
   1a. signed out? → ?adopted=<pet_id> + datsmeSignInUrlForHere, resume on return (§0.4).
                     The helper no-ops without a session; the page owns this bounce.
   2. handOffToDatsme([pet_id], session)  ← the SAME helper the designer and house use
                                             (claim if anon-owned → keep if draft → navigate)
   3. …identical from here: host quote → user confirms → require_credits → charge from the
      bytes → ingest → POST /partner/imported ack
```

Steps 2 and 3 are quoted from `SPEC_DATSPET_FEDERATED_SESSION` §2.4 and are **not** restated as
requirements here — if the two ever disagree, that spec wins.

### 1.1 Failure postures

| Situation | Result |
|---|---|
| Signed-out visitor adopts | Adopt succeeds under the anon owner. **The page** stashes `?adopted=<pet_id>` and sends them to `datsmeSignInUrlForHere`; claim-at-launch binds the pet on return and the page resumes the hand-off (§0.4). The helper itself **throws** without a session (`claimPets` 401s — its `import_url` guard does not catch this, because `import_url` is present while signed out), so the page must branch on `session.launched` *before* calling it. Do not expect the helper to redirect, and do not expect it to fail quietly. |
| **User adopts the same sample twice** | **Two pets, two full charges — and that is correct.** Each adopt mints a fresh pet id (`app.py:1499`), and the host's business key is `(partner_slug, source_item_id)` where `source_item_id` **is that pet id** (`pet_writeback.py:251`). Two snow leopards are two pets and two sales, exactly as two designed pets would be. Nothing dedupes by *sample key* — not in DatsPet, not on the host — and nothing should: the sample is a template, not a licence. |
| Same adopted pet checked out twice | Charges **0** the second time — same pet id, so `_already_charged` finds it (`import_routes.py:148-166`). This is the row Rev.2 conflated with the one above. |
| Entitlement `can_adopt_samples` false | The action is not rendered. Tier data decides, never a branch in the page. (Today no tier sets it false — §0.6.) |
| House at cap | `adopt_sample` already 409s before inserting (`_enforce_house_not_full`, `app.py:1490`) — the user is not handed a draft they cannot keep. |
| Sample bundle has no parseable `pose_count` | The host **silently omits it** from the checkout (`import_routes.py:234-240`). This is the inherited failure row from `SPEC_DATSPET_FEDERATED_SESSION` §2.5 and is exactly what Gate 0's guard test exists to make impossible. |
| Insufficient credits | Host 402 on its own page, next to the balance. Nothing charged; the pet stays kept in DatsPet. |

---

## 2. The page (`web/src/app/catalog/page.tsx`)

- **Data:** two reads the app already owns — `fetchCatalog()` (`GET /api/catalog`, the SAME endpoint
  and shape the designer's step 1 uses) and `fetchEntitlement()` for the gate below, plus
  `getDatsmeSession()` for the hand-off, exactly as `house/page.tsx` does. Share the *readers*, not
  a component. (Rev.1 and Rev.2 both called this `getCatalog()`; the function is `fetchCatalog`,
  `api.ts:211`.)

  **Do NOT reuse `BaseGalleryDialog`** (Rev.1 said to, wrongly). It renders **breeds**
  (`base_image_url`), not samples (`preview_url`) — different field, different meaning — and its
  docstring forbids exactly the change that would be needed: *"Do NOT reintroduce a `view` prop to
  make this multi-purpose again; if a second view is ever genuinely needed, make it fully
  controlled."* A grid of `<img src={preview_url}>` with an adopt button per tile is a dozen lines
  and owes nothing to the dialog. Sharing the endpoint is what stops the two drifting; sharing a
  component would be paying a coupling cost for a layout that is not the same.
- **Adopt:** `POST /api/catalog/{animal}/samples/{sample}/adopt` → `{pet_id}` → **either**
  `handOffToDatsme([pet_id], session)` when there is a session, **or** the sign-in bounce of §0.4
  when there is not. The client helper deleted at `api.ts:245-269` comes back — its own note says
  the six lines cost nothing to write again, and step 3 of §4 rewrites that note in the same commit.
  Handle the 409 from a full house as a message, not a thrown page: the endpoint checks the cap
  before inserting, so there is nothing to clean up.
- **Gating:** read `GET /api/entitlement` and hide the action when `can_adopt_samples` is false.
  No capability strings in the browser (the tier-table posture).
- **Entry points:** the landing hero and the **house's empty state**. An empty house is precisely
  where "browse ready-made pets" belongs, and it is the moment a new user is most likely to want
  one.

---

## 3. What this deliberately does not do

- **No new backend.** If a change under `webui/` becomes necessary, stop — it means §0.3 was
  violated.
- **No pricing, balance, or charge logic.** Host-authoritative, unchanged.
- **No second checkout page**, and no partner-side quote display beyond the existing estimate.
- **No sample *authoring* tooling.** Gate 0 is a content task done with the existing pipeline;
  building a sample-builder UI is a separate question.
- **No new nav item** — the two entry points in §2 are enough while the designer remains the
  primary flow.
- **No new hand-off logic.** The one thing that *is* new client-side is the sign-in bounce in §0.4,
  and it is deliberately outside the helper: it is routing, built from `datsmeSignInUrlForHere`,
  which already exists. Claim/keep/navigate ordering and anything numeric stay in
  `handOffToDatsme`. If the page starts reordering those or computing a price, §0.3 has fired.
- **No dedupe of repeat adopts.** Explicitly considered and rejected — see the §1.1 row. A user who
  adopts the same sample twice gets two pets and pays twice, which is what two pets cost.

---

## 4. Build order

**Gate 0 — content (blocking, HALF DONE).** `cat/snowleopard` is promoted and live (§0.1). One
`dog` sample remains: `generate_sample.py` → review → `promote_sample.py dog <key>`. That is a GPU
build and a curation decision, not engineering.

1. **Guard test first.** Every `pet_factory/animal_catalog/<animal>/samples/*.zip` parses to a
   `pose_count`, and every animal the catalog offers has ≥1 sample. This is a **content
   invariant**, so it lives with the other catalog guard tests in `pet_factory/tests`, not in the
   web tier. Writing it before the page is what stops the empty-set false green: **it must fail
   today** — and it does, on `dog`, which is exactly the state that makes it a real test rather
   than a decorative one. Gate 0's remaining half is what makes it pass.
2. **Endpoint tests — `adopt_sample` has none, and Rev.2's build order forgot them.** `api.ts` says
   so in capitals: *"NO TESTS (An earlier version of this comment claimed 'still tested
   server-side'. That was false — grep finds zero. Said plainly now: reviving this means writing
   them.)"* Re-verified for Rev.3: still zero, across `webui/tests` **and** `pet_factory/tests`.
   §0.2's "the backend already exists" is true and load-bearing, and it has never been executed by
   anything but a manual curl. In `webui/tests`, cover: the happy path returns a pet id owned by
   the caller and the bundle round-trips; a second owner cannot see the first's adopted pet (the
   WHERE-clause scoping, which is the whole identity model); a full house 409s **before** the
   insert, not after; an unknown animal or sample 404s; a non-alnum key 404s without touching the
   filesystem. Step 1's test guards the *content*; this one guards the *endpoint* — different
   failure, different file. *Gate: `.venv/bin/python -m pytest webui/tests pet_factory/tests` clean.*
3. **Restore the client helpers** (`adoptSample`, `catalogSamplePreviewUrl`) in `src/lib/api.ts` —
   **and rewrite the note at `api.ts:245-269` in the same change, not after.** That note is now
   stale in a way that actively misleads: it says *"catalog.json defines no `samples` at all, so
   `_samples_dir()` returns None for every animal"*. Both halves are wrong, though not the way
   Rev.3 first claimed. `_samples_dir` **does** consult `catalog.json` — line 161 is
   `if _animal(animal_key) is None: return None`, and `_animal` reads `list_animals()`
   (`animal_catalog/__init__.py:160-164`, `:67-68`). What it never does is look for a `samples`
   *key* there: samples are **discovered on disk**, so the accurate statement is "returns None if
   the animal is not in the catalog, or if `<animal>/samples/` does not exist." Before the promote
   the directory was missing; now `cat/samples/` exists and is served. A tombstone left standing over a revived feature is exactly the
   stale comment this repo deletes on sight. *Gate: `npx tsc --noEmit` clean.*
4. **The page + entry points** (§2).
   *Gate: browse → adopt → checkout charges exactly once for a sample pet; re-checking out **that
   same adopted pet** charges 0 (the host's `(partner_slug, source_item_id)` key, where
   `source_item_id` is the **DatsPet pet id**, not the sample key); a **second adopt of the same
   sample** charges again in full, which is the intended behaviour, not a bug (§1.1); a signed-out
   visitor's adopt survives the sign-in round trip and appears in their house afterwards.*
5. **Deploy staging → verify → production**, per `deploy/CHECKLIST.md` Rule 0.

**Dependency: SATISFIED.** `SPEC_DATSPET_FEDERATED_SESSION` is closed and archived — its step 8
(the shared `handOffToDatsme` helper) landed, and the whole spec was verified on staging including
a real charge and a two-user browser handover. Nothing here is waiting on it.

---

## 5. Open questions

1. **How many samples per animal, and who curates them? — THIS IS THE SHIP DECISION, still open.**
   The guard test enforces ≥1, which is a *correctness* floor, not a *product* one: the catalog is
   two animals, so ≥1 ships a "browse" page over two tiles. Proposal unchanged — **3–4 per animal
   before the page goes live.** Size it honestly before agreeing to it: 6–8 *accepted* samples at a
   realistic curation accept rate is 15–30 GPU builds plus taste passes, which is **more elapsed
   work than every engineering step in §4 combined**. The code is roughly a day and a half; the
   content is not. This question, not the build order, decides when this ships.
2. **~~Should samples be priced differently?~~ SETTLED — not this spec's question.** The host
   prices a sample from pose count exactly as it prices a designed pet, and the numbers are
   host-side credit config (`credit_pet_design_cost`, `credit_pet_extra_pose_cost`) which the owner
   sets independently of anything here. Nothing in this spec reads, displays or depends on a
   price. Recorded only so the next reader does not re-open it: the surface is the deliverable,
   the numbers are a knob.
3. **Does the catalog page need the pet runtime** (live animated previews) or are the static
   preview PNGs enough? Proposal: PNGs — `preview_url` already exists and the designer's gallery
   uses exactly that.

---

## Appendix — grounding (re-verified 2026-07-30 for Rev.3)

**Rev.3 additions — the five facts that corrected the body.** `webui/app.py:1499`: the adopt mints
`uuid.uuid4().hex[:12]` **per call**, so the pet id is per-adopt, never per-sample.
`datsme_me/api/apps/dpp/pet_writeback.py:251`: `source_item_id = payload.get("source_pet_id")` —
the host's business key **is** that pet id; `import_routes.py:148-166` `_already_charged` keys on it.
`web/src/lib/api.ts:1119`: `if (petIds.length === 0 || !session.import_url) return;` — the
signed-out no-op; `house/page.tsx:101` `canAdopt` is how the house works around it; `api.ts:1027`
`datsmeSignInUrlForHere` + `:1032-1040` `currentReturnPath` (path **and** query) are the pieces the
catalog page uses instead. `datsme_me/api/apps/dpp/routes.py:36-42` `_safe_return` is a **regex
shape check, not an allowlist**, so `/catalog?adopted=<id>` needs no host change.
`pet_factory/tiers/tiers.json:9` and `:17`: **both** tiers set `can_adopt_samples: true` (§0.6).
**Zero tests** for `adopt_sample` anywhere in `webui/tests` or `pet_factory/tests` — grep confirms
`api.ts`'s own capitalised warning is still accurate (§4 step 2).

`webui/app.py` (**re-verified 2026-07-30 for Rev.3. Rev.2's appendix cited the `def` lines; these
are the `@app.` decorator lines, one above — pick one convention and hold it, since a reader
grepping for the route finds the decorator**): `:1394` `/api/catalog` (**carries
`samples` + `preview_url`**), `:1448` `/api/entitlement`, `:1463` sample preview, `:1475`
`adopt_sample` (*"generation-free (zero GPU)"*, draft, same insert path, owner-scoped, enforces the
house cap at `:1490`). Confirmed live end to end: `/api/catalog` returns the snowleopard tile and
the adopt POST returns `{'pet_id': ..., 'display_name': 'White Snow Leopard'}`.
`pet_factory/animal_catalog/__init__.py`: `:160-164` **`_samples_dir` = `_DIR/<animal>/samples`,
gated on catalog membership**, `:167-179` `list_samples` (globs `*.zip`, alnum keys only), `:187`
`sample_bundle_path`, `:196` `sample_preview_path`.
`pet_factory/animal_catalog/catalog.json`: animals = `cat`, `dog`.
`promote_sample.py` — the manual promote step (`--list`, then `<animal> <key>`); **the tool Rev.1
omitted**. `cat/samples/snowleopard.{zip,png}` is now promoted; the bundle's manifest declares 8
animations, so `pose_count` parses. `dog` has no sample — the remaining half of Gate 0.
`SPEC_PET_DESIGNER_FLOW` §11.2 (why the UI was removed, and that the sample was one promote away).
`pet_factory/tiers/tiers.json`: `can_adopt_samples`.
`web/src/lib/api.ts:245-269`: the deleted-helper note (endpoint *"still EXISTS"*, kept
deliberately) — **now stale and rewritten by §4 step 3**; `:211` `fetchCatalog`.
`web/src/app/design/general/BaseGalleryDialog.tsx`: the gallery **not** to reuse (Rev.2 §2 — it
renders breeds, and its docstring forbids the `view` prop that reuse would need).
`datsme_me/api/apps/dpp/pet_writeback.py:100-108` `price_user_pet` (same pricing for both);
`datsme_me/api/apps/dpp/import_routes.py:234-240` (silent skip of an unquotable item).
