# SPEC — DatsPet Catalog Purchase (browse ready-made pets, buy with credits)

**Status:** Design — **Rev.1** (2026-07-30), for review. **BLOCKED on content, not code** — see
§0.1. A browse-and-adopt surface for the pre-made sample pets in the animal catalog: pick one, and
it goes through the *same* host checkout a designed pet does. Zero new backend, zero new money
code, one new page.

**Split from `docs/SPEC_DATSPET_FEDERATED_SESSION.md`** (Rev.2 §2.5 / §5.4), which specified this
inline before the content gap was found. That spec is the **hard dependency**: this one consumes
its shared hand-off helper (§5.2 there) and its owner-scope model (§4.5 there), and adds neither.

**Repos touched:** `datsme-pet-factory_wu` only — one page, one guard test, and the sample bundles
themselves. No `datsme_me` change. No SDK change.

---

## 0. The core decisions

### 0.1 This is blocked on curated sample bundles, and that is the whole gate

**There are no shipped samples today.** Verified:

- `_samples_dir(animal_key)` resolves `_DIR / animal_key / "samples"` and returns `None` unless
  `_animal(animal_key)` exists — i.e. the animal must be in the catalog
  (`pet_factory/animal_catalog/__init__.py:160-164`).
- The catalog's animals are exactly `cat` and `dog` (`animal_catalog/catalog.json`).
- The only sample `.zip` anywhere in the tree is
  `pet_factory/animal_catalog/_candidates/cat/samples/snowleopard.zip`, and `_candidates` is **not**
  a catalog animal.

So `list_samples()` returns `[]` for every animal and `GET /api/catalog` serves `samples: []`
today. Shipping the page first would produce an empty browse surface, and the §4 guard test would
**pass on an empty set** — a false green, the failure class `deploy/CHECKLIST.md` §E exists to
prevent.

**Gate 0 (blocking, precedes every build step):** at least one curated sample bundle per catalog
animal is committed under `pet_factory/animal_catalog/<animal>/samples/<key>.zip` with a matching
`<key>.png` preview, and each yields a parseable `pose_count`. `pet_factory/animal_catalog/**/*.zip`
is deliberately un-gitignored precisely so curated bundles ship as content (`CLAUDE.md`), so this
is a content task, not an infrastructure one.

### 0.2 The backend already exists — this is a surface, not a feature

- `POST /api/catalog/{animal}/samples/{sample}/adopt` (`webui/app.py:1408`) copies a stored sample
  bundle into the caller's house as a **draft**, via the **same insert path a generated pet takes**,
  minus the build. Its docstring calls it *"generation-free (zero GPU)"*. It is already
  owner-scoped and already enforces the house cap.
- `GET /api/catalog` (`webui/app.py:1327-1360`) already returns, per animal,
  `samples: [{key, preview_url}]`.
- The tier table already carries the entitlement (`can_adopt_samples`,
  `pet_factory/tiers/tiers.json`), surfaced by `GET /api/entitlement` (`webui/app.py:1381`).

What is missing is a page. The client helpers were deleted with the themed pages, and their
absence is **recorded, not accidental** — `web/src/lib/api.ts:205-214` says the endpoint *"still
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
anonymous owner id (`SPEC_DATSPET_FEDERATED_SESSION` §4.5). The purchase needs a host session, so
the hand-off routes them through `signin_url` first, and claim-at-launch binds their anon-owned
pet to the DatsMe user on the way back. This works only because that spec landed first; without
it, an anonymous adopt would drop into the shared pool.

---

## 1. The flow

```
user browses /catalog                    ← GET /api/catalog already carries each animal's
                                            samples + preview URLs (app.py:1327-1360)
user clicks "Adopt this one"
   1. POST /api/catalog/{animal}/samples/{sample}/adopt   ← app.py:1408, zero GPU, returns pet_id
                                                            (draft=1, owner = caller's owner id)
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
| Signed-out visitor adopts | Adopt succeeds under the anon owner; hand-off routes to `signin_url`; claim-at-launch binds it on return. |
| Entitlement `can_adopt_samples` false | The action is not rendered. Tier data decides, never a branch in the page. |
| House at cap | `adopt_sample` already 409s before inserting (`app.py:1418-1422`) — the user is not handed a draft they cannot keep. |
| Sample bundle has no parseable `pose_count` | The host **silently omits it** from the checkout (`import_routes.py:234-240`). This is the inherited failure row from `SPEC_DATSPET_FEDERATED_SESSION` §2.5 and is exactly what Gate 0's guard test exists to make impossible. |
| Insufficient credits | Host 402 on its own page, next to the balance. Nothing charged; the pet stays kept in DatsPet. |

---

## 2. The page (`web/src/app/catalog/page.tsx`)

- **Data:** one `GET /api/catalog` call. **Reuse the designer's gallery components** —
  `web/src/app/design/general/BaseGalleryDialog.tsx` already renders this exact tree for step 1 of
  the designer. One endpoint, one shape, two presentations; do not build a second catalog reader.
- **Adopt:** `POST /api/catalog/{animal}/samples/{sample}/adopt` → `{pet_id}` →
  `handOffToDatsme([pet_id], session)`. The client helper deleted at `api.ts:205-214` comes back —
  its own note says the six lines cost nothing to write again.
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

---

## 4. Build order

**Gate 0 — content (blocking).** Curated sample bundles committed per §0.1, each with a preview
and a parseable `pose_count`.

1. **Guard test first.** Every `pet_factory/animal_catalog/<animal>/samples/*.zip` parses to a
   `pose_count`, and every animal the catalog offers has ≥1 sample. This is a **content
   invariant**, so it lives with the other catalog guard tests in `pet_factory/tests`, not in the
   web tier. Writing it before the page is what stops the empty-set false green: **it must fail
   today**, and Gate 0 is what makes it pass.
2. **Restore the client helpers** (`adoptSample`, `catalogSamplePreviewUrl`) in `src/lib/api.ts`.
   *Gate: `npx tsc --noEmit` clean.*
3. **The page + entry points** (§2).
   *Gate: browse → adopt → checkout charges exactly once for a sample pet; a second checkout of
   the same sample charges 0 (the host's `(partner_slug, source_item_id)` key); a signed-out
   visitor's adopt survives the sign-in round trip and appears in their house afterwards.*
4. **Deploy staging → verify → production**, per `deploy/CHECKLIST.md` Rule 0.

**Dependency:** step 2 cannot start until `SPEC_DATSPET_FEDERATED_SESSION` build step 8 (the
shared hand-off helper) has landed.

---

## 5. Open questions

1. **How many samples per animal, and who curates them?** The guard test enforces ≥1; the product
   question is whether a browse page reads as a catalog with two entries. Proposal: 3–4 per animal
   before shipping the page.
2. **Should samples be priced differently from designed pets?** They cost no GPU, which is
   Platform §4.4's "business lever" framing. Today the host prices both from pose count, so a
   sample is cheap only if it has few poses. Changing that is a **host credit-config** question
   (`credit_pet_design_cost`), explicitly out of scope here, but it is the obvious follow-on.
3. **Does the catalog page need the pet runtime** (live animated previews) or are the static
   preview PNGs enough? Proposal: PNGs — `preview_url` already exists and the designer's gallery
   uses exactly that.

---

## Appendix — grounding (verified 2026-07-30)

`webui/app.py`: `:1327-1360` `/api/catalog` (**carries `samples` + `preview_url`**), `:1381`
`/api/entitlement`, `:1396` sample preview, `:1404-1406` preview `FileResponse`, `:1408-1438`
`adopt_sample` (*"generation-free (zero GPU)"*, draft, same insert path, owner-scoped, house cap at
`:1418-1422`).
`pet_factory/animal_catalog/__init__.py`: `:160-164` **`_samples_dir` = `_DIR/<animal>/samples`,
gated on catalog membership**, `:167-179` `list_samples` (globs `*.zip`, alnum keys only), `:187`
`sample_bundle_path`, `:196` `sample_preview_path`.
`pet_factory/animal_catalog/catalog.json`: animals = `cat`, `dog`.
`find pet_factory/animal_catalog -name '*.zip'` → **only**
`_candidates/cat/samples/snowleopard.zip` (not a catalog animal) — the §0.1 blocker.
`pet_factory/tiers/tiers.json`: `can_adopt_samples`.
`web/src/lib/api.ts:205-214`: the deleted-helper note (endpoint *"still EXISTS"*, kept
deliberately). `web/src/app/design/general/BaseGalleryDialog.tsx`: the gallery tree to reuse.
`datsme_me/api/apps/dpp/pet_writeback.py:100-108` `price_user_pet` (same pricing for both);
`datsme_me/api/apps/dpp/import_routes.py:234-240` (silent skip of an unquotable item).
