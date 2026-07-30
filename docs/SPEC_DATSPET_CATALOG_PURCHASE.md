# SPEC — DatsPet Catalog Purchase (browse ready-made pets, buy with credits)

**Status:** Design — **Rev.2** (2026-07-30), implementation-ready. A browse-and-adopt surface for
the pre-made sample pets in the animal catalog: pick one, and it goes through the *same* host
checkout a designed pet does. Zero new backend, zero new money code, one new page.

**Split from `docs/archive/SPEC_DATSPET_FEDERATED_SESSION.md`** (Rev.2 §2.5 / §5.4), which specified
this inline before the content gap was found. That spec was the hard dependency — this one consumes
its shared hand-off helper (§5.2 there) and its owner-scope model (§4.5 there), and adds neither.
**It is now CLOSED, executed and verified on staging, so the dependency is satisfied** and nothing
here waits on it.

**What changed in Rev.2** (all four found by re-verifying Rev.1 against the tree):

| # | Change | Why |
|---|---|---|
| 1 | **§2's component reuse is withdrawn.** The page gets its own small grid. | `BaseGalleryDialog` renders **breeds** (`base_image_url`), not samples (`preview_url`) — different data, different shape — and its own docstring says *"Do NOT reintroduce a `view` prop to make this multi-purpose again."* What is genuinely shared is `getCatalog()` and the preview URL, not the component. |
| 2 | **Gate 0 is half done and was never as large as Rev.1 implied.** `cat/snowleopard` is promoted and live; only `dog` remains. | Rev.1 never mentioned `promote_sample.py`, the tool that exists for exactly this. `SPEC_PET_DESIGNER_FLOW` §11.2 had already recorded that the staged sample was one command from being real. |
| 3 | **New §0.5** answering "isn't this the house-pet source we rejected?" | Any reader who knows the designer's §2.1/§3.9 will ask it on sight. It deserves the answer inline, not a re-derivation. |
| 4 | Citations refreshed; they had drifted the same day. | `adopt_sample` moved 1408 → **1476** and friends, when `/api/pets/unsaved` landed. An appendix that says "verified" has to be. |

**Repos touched:** `datsme-pet-factory_wu` only — one page, one guard test, and the sample bundles
themselves. No `datsme_me` change. No SDK change.

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

So the remaining content work is **one dog sample** (`generate_sample.py` → review → promote), not
an open-ended curation project. `pet_factory/animal_catalog/**/*.zip` is deliberately un-gitignored
so curated bundles ship as content (`CLAUDE.md`).

**Gate 0 (blocking):** every catalog animal has ≥1 promoted sample with a preview and a parseable
`pose_count`. Half satisfied. Shipping the page with `dog: []` would give half the catalog an empty
shelf — and §4's guard test, which must fail today, is what keeps that from passing quietly.

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

- **Data:** one `GET /api/catalog` call — the SAME endpoint and the same shape the designer's
  step 1 reads. Share the reader (`getCatalog()`), not a component.

  **Do NOT reuse `BaseGalleryDialog`** (Rev.1 said to, wrongly). It renders **breeds**
  (`base_image_url`), not samples (`preview_url`) — different field, different meaning — and its
  docstring forbids exactly the change that would be needed: *"Do NOT reintroduce a `view` prop to
  make this multi-purpose again; if a second view is ever genuinely needed, make it fully
  controlled."* A grid of `<img src={preview_url}>` with an adopt button per tile is a dozen lines
  and owes nothing to the dialog. Sharing the endpoint is what stops the two drifting; sharing a
  component would be paying a coupling cost for a layout that is not the same.
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

**Gate 0 — content (blocking, HALF DONE).** `cat/snowleopard` is promoted and live (§0.1). One
`dog` sample remains: `generate_sample.py` → review → `promote_sample.py dog <key>`. That is a GPU
build and a curation decision, not engineering.

1. **Guard test first.** Every `pet_factory/animal_catalog/<animal>/samples/*.zip` parses to a
   `pose_count`, and every animal the catalog offers has ≥1 sample. This is a **content
   invariant**, so it lives with the other catalog guard tests in `pet_factory/tests`, not in the
   web tier. Writing it before the page is what stops the empty-set false green: **it must fail
   today** — and it does, on `dog`, which is exactly the state that makes it a real test rather
   than a decorative one. Gate 0's remaining half is what makes it pass.
2. **Restore the client helpers** (`adoptSample`, `catalogSamplePreviewUrl`) in `src/lib/api.ts`.
   *Gate: `npx tsc --noEmit` clean.*
3. **The page + entry points** (§2).
   *Gate: browse → adopt → checkout charges exactly once for a sample pet; a second checkout of
   the same sample charges 0 (the host's `(partner_slug, source_item_id)` key); a signed-out
   visitor's adopt survives the sign-in round trip and appears in their house afterwards.*
4. **Deploy staging → verify → production**, per `deploy/CHECKLIST.md` Rule 0.

**Dependency: SATISFIED.** `SPEC_DATSPET_FEDERATED_SESSION` is closed and archived — its step 8
(the shared `handOffToDatsme` helper) landed, and the whole spec was verified on staging including
a real charge and a two-user browser handover. Nothing here is waiting on it.

---

## 5. Open questions

1. **How many samples per animal, and who curates them?** The guard test enforces ≥1; the product
   question is whether a browse page reads as a catalog with two entries. Proposal: 3–4 per animal
   before shipping the page.
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

## Appendix — grounding (verified 2026-07-30)

`webui/app.py` (**re-verified 2026-07-30 after the federated-session work moved them**): `:1395`
`/api/catalog` (**carries `samples` + `preview_url`**), `:1449` `/api/entitlement`, `:1464` sample
preview, `:1476` `adopt_sample` (*"generation-free (zero GPU)"*, draft, same insert path,
owner-scoped, enforces the house cap). Confirmed live end to end: `/api/catalog` returns the
snowleopard tile and the adopt POST returns `{'pet_id': ..., 'display_name': 'White Snow Leopard'}`.
`pet_factory/animal_catalog/__init__.py`: `:160-164` **`_samples_dir` = `_DIR/<animal>/samples`,
gated on catalog membership**, `:167-179` `list_samples` (globs `*.zip`, alnum keys only), `:187`
`sample_bundle_path`, `:196` `sample_preview_path`.
`pet_factory/animal_catalog/catalog.json`: animals = `cat`, `dog`.
`promote_sample.py` — the manual promote step (`--list`, then `<animal> <key>`); **the tool Rev.1
omitted**. `cat/samples/snowleopard.{zip,png}` is now promoted; the bundle's manifest declares 8
animations, so `pose_count` parses. `dog` has no sample — the remaining half of Gate 0.
`SPEC_PET_DESIGNER_FLOW` §11.2 (why the UI was removed, and that the sample was one promote away).
`pet_factory/tiers/tiers.json`: `can_adopt_samples`.
`web/src/lib/api.ts:205-214`: the deleted-helper note (endpoint *"still EXISTS"*, kept
deliberately). `web/src/app/design/general/BaseGalleryDialog.tsx`: the gallery tree to reuse.
`datsme_me/api/apps/dpp/pet_writeback.py:100-108` `price_user_pet` (same pricing for both);
`datsme_me/api/apps/dpp/import_routes.py:234-240` (silent skip of an unquotable item).
