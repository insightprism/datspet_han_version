# SPEC — Pet Designer Platform (landing + themed pages + base catalog + tiers)

**Status:** Design — **Rev.4** (2026-07-13), **implementation-ready**. Umbrella spec for the DatsPet
designer surface. Builds on **`docs/SPEC_MOTION_PROFILES.md`** (the movement layer — now
**implemented**, commits `464095a`/`6e13aba`) and reuses the deploy/cutover discipline of
**`docs/SPEC_DEPLOY_PETDATSME_POOL.md`** (now Rev.6). Grounded against the working tree.
**Rev.4 — reality sync after the motion-profiles implementation landed.** Phase 1 overshot this
spec's boundary in four ways §8 now reflects: (a) the pose selector + cost hint + `/api/motions`
shipped **inside the current `/design` page** (step 1's extraction hadn't happened), so the
`<PetDesigner>` extraction now carries them along; (b) the **v3 fleet rollout moved from last step
to PREREQUISITE** — the shipped selector sends `poses` params, so deploying any web tier before v3
is on the fleet means user-visible 422s; (c) step 6 must **replace the interim hardcoded
`MAX_SELECTABLE_POSES = 5`** (every user currently gets the plus cap, unpriced) with the resolved
entitlement + server-side per-user enforcement; (d) the base-animal catalog inherits the **data-only
`--no-deps` deploy posture** the motion profiles established (deploy spec Rev.6). Also resolved:
launch animals = **Cat + Dog + General** (§7.5).
**Rev.3** aligns the catalog with the motion spec's specificity levels: catalog entries pin a
**`motion_profile` key at the most specific authored level** (breed → species → animal type, §4.2)
instead of stopping at `body_type` — without this, a catalog Corgi would resolve the coarse
`quadruped` file while free-text "corgi" got the fine `corgi.json`, i.e. the curated path animating
*worse* than free text. The pinned key rides the generate request too (motion spec §5.2), so the pin
governs the build, not just the menu.
**Rev.2** reconciles the tier numbers with the motion spec after a cross-spec audit: the paid cap is
**5 poses** (was 8 — it exceeded the motion `MAX_POSES` ceiling, since raised to 10), and the model
is now **the user freely picks which poses** up to their cap, not a tier-dictated fixed set.
**Author's intent (verbatim goal):** "Have multiple design pages for different animal/body types so
the UI is customized, uncluttered, and easy — e.g. a 'Cat World — design your own cat' page with cat
versions, a themed background, and samples of past builds the user can even adopt. Keep a General
page. Different users may have different capabilities — a base user gets 2 poses, a paying user gets
up to 8, priced by GPU cost. Pull a curated base image the moment an animal/breed is chosen so the
user starts from a picture, not a blank screen — which also makes the body type (and thus the
animation) consistent."
**Repos touched:** `datsme-pet-factory_wu` (frontend pages, web tier, `pet_factory`, pool handler).
`shared_gpu_cpu` and `datsme_me` are **not** modified — with ONE deliberate deferred exception:
the `credit_pet_extra_pose_cost` config knob + manifest-based pose count at adopt (§5.2/§7.1),
a small host-side addition that ships with step 6.

---

## 0. The core architectural decision (read this first)

Two things vary between animal pages, for **different reasons**, so they live in **different places**:

| Concern | Varies by | Lives where | Who changes it |
|---|---|---|---|
| **Theme** — layout, background, copy, sample gallery, "Cat World" vibe | per page, for design/marketing reasons | hand-coded, one component per themed page | design |
| **Generation contract** — body type, poses, base images, pricing/tiers | per body type, for engineering reasons | **shared config** the pages read | engineering |

**A themed page owns its look and hard-codes it freely. It does NOT own a private copy of how
generation, pose-selection, or billing work — it reads those from the shared layer.** This is the
whole design in one sentence, and it is a direct application of the global rule *"things that change
for different reasons live in different places."* Theming changes when marketing wants a new vibe;
the generation contract changes when engineering adds a pose or adjusts pricing. Coupling them would
mean re-testing billing every time you restyle a background — so we don't.

Consequence: **adding "Dragon Lair" is a themed page + (if new) a body-type/catalog entry — never a
reimplementation of pose logic or billing.** Restyling Cat World touches only Cat World.

---

## 1. The four layers

```
                    ┌─────────────────────────────────────────┐
                    │  LANDING PAGE  /design                    │
                    │  "What do you want to make?"              │
                    │  tiles: Cat World · Dog World · … · General│
                    └───────────────┬─────────────────────────┘
                                    │ routes by body-type key
             ┌──────────────────────┼──────────────────────────┐
             ▼                      ▼                           ▼
    ┌─────────────────┐   ┌─────────────────┐        ┌─────────────────┐
    │  THEMED PAGE     │   │  THEMED PAGE     │  …     │  GENERAL PAGE    │
    │  /design/cat     │   │  /design/dog     │        │  /design/general │
    │  (hand-themed)   │   │  (hand-themed)   │        │  (today's page)  │
    └────────┬─────────┘   └────────┬─────────┘        └────────┬─────────┘
             └──────────────────────┴──── read shared config ───┘
                                    │
          ┌─────────────────────────┼──────────────────────────┐
          ▼                         ▼                            ▼
   BASE-ANIMAL CATALOG      MOTION-PROFILE REGISTRY        TIER / ENTITLEMENTS
   (curated base images,    (SPEC_MOTION_PROFILES.md —     (pose-count + pricing,
    breeds, → body type)      how each body type moves)      per user tier)
```

Each layer grows by **adding data/content**, not code: a folder, a JSON entry, a themed component.

- **Layer 1 — Landing page** (§2): the front door; routes to a themed page by body-type key.
- **Layer 2 — Themed pages** (§3): per-animal, hand-designed; render controls + samples from shared config.
- **Layer 3 — Base-animal catalog** (§4): curated base images per animal/breed, each pre-tagged with
  its body type. Feeds both the instant-base-image UX and the sample/adopt gallery.
- **Layer 4 — Motion profiles (spec'd) + tiers** (§5): the shared generation contract every page sits on.

---

## 2. Layer 1 — the landing page

**Route:** `/design` becomes the landing page (today's form moves to `/design/general`, §3.3).
**Content:** a tile per available "world" — Cat World, Dog World, Dragon Lair, …, plus **General**.
The tile list is **data-driven** from the catalog (§4): each catalog animal that has a themed page
registered appears as a tile; General is always present as the long-tail/power path.

Routing carries the body-type key forward: a Cat tile → `/design/cat`. Nothing about generation
happens here — it is pure navigation + merchandising (a tile can show a hero image and a one-liner).

**DPP note:** the DatsMe "Design a pet" launch currently deep-links to `/design?from=datsme`
(`webui/datsme_integration.py`). It continues to land on the landing page — the launch cookie is
origin-scoped, not path-scoped, so it survives navigation to any themed page (verified: the cookie
is set on the host, §C.5 of the deploy spec). A launched user picks a world like anyone else.

---

## 3. Layer 2 — themed animal pages

### 3.1 The shape of a themed page
A themed page (e.g. `web/src/app/design/cat/page.tsx`) is a **hand-authored** component: its own
background ("Cat World"), copy ("Design your own cat"), and layout. It is free to look like nothing
else. What it does NOT hand-roll is the generation machinery — it composes shared pieces:

- **A shared `<PetDesigner>` core** — the color picker, accessory picker, strength control, pose
  selector, preview, and submit. This is the current `/design` form logic extracted into a reusable
  component that takes its options as props/config. Themed pages drop it in and style around it.
- **The pose selector** reads the catalog-pinned motion profile (via `/api/motions?profile=<key>`,
  SPEC_MOTION_PROFILES §4) — so Cat World shows quadruped poses, a bird page shows avian poses,
  with **zero per-page pose logic**.
- **The base image + breed picker** reads the catalog (§4) for that animal.
- **The sample gallery** reads the catalog's pre-built samples (§4.4).

So the themed page is: `<CatThemeChrome>` wrapping `<BreedPicker animal="cat" />`,
`<PetDesigner motionProfile={breed.motion_profile} />`, and `<SampleGallery animal="cat" />` — the
profile key coming from the selected catalog entry (§4.2). The chrome is bespoke;
the three children are shared and config-fed.

### 3.2 Why not one config-driven page rendering all themes
Considered and rejected. A single page that theme-switches on a config blob would either (a) constrain
every animal to one layout (defeats the "uncluttered, customized per animal" goal) or (b) grow a
per-animal branching monster inside one file. Hand-authored theme chrome per page is the right call —
**the theme is genuinely bespoke content.** The discipline that keeps it maintainable is §0: the
*chrome* is per-page, the *contract* is shared. (This is the answer to "one page vs. many": many
themed shells, one shared engine.)

### 3.3 "General" is the current page, preserved
Today's `/design` (the color/accessory/strength form over any house pet — `web/src/app/design/page.tsx`)
becomes `/design/general` **unchanged in behavior**. It is the power-user / long-tail path: free-text,
redesign-any-house-pet, no theming, everything exposed. It is also the fallback for any animal not yet
in the catalog. Building themed pages never removes it.

### 3.4 Uncluttering is the point
The current general page shows every control at once (color + 25 accessories + strength + preview) for
every pet. A themed cat page can show *cat-relevant* choices, cat breeds, and cat samples — fewer
decisions, more guidance. Same engine underneath; a calmer surface on top. That reduction in
decision-load is the product value the goal names.

---

## 4. Layer 3 — the base-animal catalog

### 4.1 The insight this solves
Better motion prompts (SPEC_MOTION_PROFILES) improve animation, but they can't fix a bad **base
image**: the Wan I2V model animates whatever proportions/view the still gives it, so an
inconsistent base yields inconsistent motion regardless of prompt quality. A **curated base-image
library** fixes it at the source — a known-good, side-profile, right-facing base per animal/breed
guarantees the input the animator needs. This is why the catalog and the motion registry are **one
system**: the catalog entry declares the body type, which resolves the motion profile, so base image
and movement are authored together and always agree.

### 4.2 Layout
```
pet_factory/animal_catalog/
├── catalog.json                 # master index: animals → motion_profile, themed?, breeds
├── cat/
│   ├── tabby/base.png           # curated, side-profile, right-facing base sprite
│   ├── siamese/base.png
│   └── black/base.png
├── dog/
│   └── ...
└── bird/
    └── robin/base.png
```

`catalog.json`:
```json
{
  "animals": [
    { "key": "cat",  "label": "Cat",  "motion_profile": "cat", "themed_page": "cat",
      "breeds": [ {"key": "tabby", "label": "Tabby"}, {"key": "siamese", "label": "Siamese"} ] },
    { "key": "dog",  "label": "Dog",  "motion_profile": "dog", "themed_page": "dog",
      "breeds": [ {"key": "corgi", "label": "Corgi", "motion_profile": "corgi"},
                  {"key": "labrador", "label": "Labrador"} ] },
    { "key": "bird", "label": "Bird", "motion_profile": "avian", "themed_page": "bird",
      "breeds": [ {"key": "robin", "label": "Robin"} ] }
  ]
}
```

Each catalog entry pins a **`motion_profile`** key — the link into the motion registry — at the
**most specific level that has an authored file** (SPEC_MOTION_PROFILES §3.7, Rev.3): a breed row
carries its own `motion_profile` when a level-1 file exists (`corgi` → `corgi.json`); otherwise it
inherits the animal row's key (a species file like `dog.json`, or the animal-type root like
`avian.json`). Resolution for a catalog animal is therefore **authored, not inferred** — and, by
construction, **always at least as specific as what free-text keyword matching would find**. (This
pinning matters: if the catalog stopped at body type, a catalog Corgi would resolve the coarse
`quadruped` file while a General user *typing* "corgi" got the fine `corgi.json` — the curated
premium path animating *worse* than free text. The pinned key inverts that back: curated ≥ free-text
fidelity, always.) The keyword classifier from SPEC_MOTION_PROFILES §3.5 remains only for the
General free-text path. A guard test asserts every pinned `motion_profile` key exists in the motion
registry — a catalog entry cannot point at a missing profile.

**Deploy posture (Rev.4):** `animal_catalog/` is data-only content inside the `pet_factory` package —
it inherits the exact deploy story the motion profiles established (deploy spec Rev.6): it reaches the
GPU-less web tiers via the `--no-deps -e` install, adds no ML dependency, and content additions follow
the node-first ordering habit where the workers need them (base images ride to workers as
`reference_image_b64`, so workers do NOT need the catalog itself — only the web tier reads it).

### 4.3 Instant base image + how it feeds generation
- Pick animal → breed → the base PNG displays **immediately** (a static file load, no generation).
  The user starts from a picture, not a blank screen.
- On "Create my design", the base image is the img2img source: the existing remix pipeline
  (`make_pet_zip(reference_image=…, remix_strength=…)`, `factory.py`) redraws *from the curated base*
  toward the user's color/accessory prompt. **No cold-start Z-Image generation** for catalog animals —
  the curated file replaces the from-scratch base still, which is both faster and more consistent.
- New endpoints: `GET /api/catalog` (the animal/breed tree) and `GET /api/catalog/{animal}/{breed}/base.png`
  (the base image). Both read-only, cacheable.

### 4.4 Samples / adopt-a-premade
The catalog also stores **finished sample pets** per animal (fully-built bundles, not just bases). A
themed page's gallery surfaces them: "cats people made". A user can **adopt a pre-made one directly** —
which skips generation entirely (**zero GPU cost**), a useful tier/business lever (free users may be
steered to adopt; paid users generate custom). Mechanically, adopt = copy the stored bundle into the
user's house (the same insert path a generated pet takes, minus the build).

### 4.5 Authoring the bases (the honest cost)
Curated bases are **authored assets** — the consistency guarantee is only as good as the curation.
Bootstrapping approach (recommended): a **generate-then-curate** batch tool produces candidate bases
via the existing Z-Image path for a target animal/breed list; a human approves the good ones into the
catalog. The un-curated long tail falls back to on-the-fly generation via the General path. So this is
"curate the common animals, generate the rest," never "hand-draw everything up front."

---

## 5. Layer 4 — tiers & the shared generation contract

### 5.1 Tiers are orthogonal to body type
"Base user = 2 poses, paid user = up to 5" is an **entitlement**, independent of which animal. A paid
cat and a paid bird both get to pick up to the paid cap from their body type's available poses. So
tiers are a **separate config table**, not baked into pages:

```json
// tiers.json  (server-side; the browser only learns the caller's resolved entitlement)
{
  "tiers": {
    "base": { "max_poses": 2, "price_per_extra_pose": 0,  "can_generate": true, "can_adopt_samples": true },
    "plus": { "max_poses": 5, "price_per_extra_pose": 50, "can_generate": true, "can_adopt_samples": true }
  },
  "default_tier": "base"
}
```

**The user freely chooses *which* poses, up to `max_poses`** (not a fixed set the tier dictates).
walk+idle are always included (required, SPEC_MOTION_PROFILES §3.4); the remaining slots
(base: 0 extra; plus: up to 3 extra) are the user's pick from the body type's available poses —
run, sleep, sit, eat, swim/fly, etc. `max_poses` caps the pose selector (SPEC_MOTION_PROFILES §4/§8):
a base user sees walk+idle locked and everything else upsell-tagged; a plus user checks up to 5
total. **Ceiling relationship:** the motion spec's `MAX_POSES=10` is the absolute platform ceiling
(= the full canonical pose set); the tier `max_poses` is the per-user cap *under* it (2/5). They no
longer conflict — 5 ≤ 10. Realized builds stay ≤5 poses (~7 min), comfortably under the 900 s
watchdog, so no handler-timeout change is needed at launch (SPEC_MOTION_PROFILES §8).

> **Note (pose availability):** the poses a user picks from are the **auto-driven** ones the runtime
> plays today (`active`/`rest`/`timed`). The `triggered` poses (`jump`, `play`) are authored in the
> profiles but **hidden from the selector** until a DatsMe trigger is wired (SPEC_MOTION_PROFILES §7),
> so tier caps count against the *visible* menu — a user never pays for a pose that won't move.

### 5.2 Pricing wires to pose count (Rev.4: defaults set — all admin-tunable)
Each generated pose is real GPU cost (~75 s), so price scales with pose count. This ties into DatsMe's
**existing credit system** — `credit_pet_design_cost` is charged today at Accept
(SPEC_DATSPET_DPP_INTEGRATION, currently a flat 100).

**The formula and defaults (every number a config knob, none load-bearing):**

```
charge at Accept = credit_pet_design_cost  +  extra_poses × credit_pet_extra_pose_cost
                   (default 100)              (default 50 per pose beyond walk+idle)
```

So: walk+idle pet = **100** (unchanged from today); a 5-pose pet = 100 + 3×50 = **250**. The 50 tracks
the marginal GPU (~75 s/pose vs the ~3-min base build) as a clean round number — deliberately *not*
precision-priced, since it's admin-tunable anyway. The full price is surfaced **before** the user
commits (the cost hint, SPEC_MOTION_PROFILES §4.2, plus the session `cost` field the launch banner
already shows) — never a surprise at Accept.

**Charging mechanics — server-authoritative from the artifact.** The host (DatsMe) is the only party
that can charge credits, and it should not trust a partner-claimed pose count. It doesn't have to:
the host **fetches the bundle at Accept** (§C.4 of the deploy spec) and the manifest's `animations`
map *is* the pose count. Charge = base + `max(0, len(animations) − 2)` × extra-pose cost, computed
from the fetched artifact itself. **This needs one small host-side addition** (the
`credit_pet_extra_pose_cost` config knob + the count-from-manifest at adopt) — the ONE deliberate
exception to this spec's "no `datsme_me` change" guard, deferred to when step 6 ships. **Until it
lands, charging stays flat 100** regardless of poses (extra poses are effectively free — acceptable:
the entitlement cap still bounds GPU, and the UI already displays the intended full price).
**Adopting a sample (§4.4) is generation-free → cheapest/free tier lever.**

### 5.3 Where entitlement is resolved
The web tier resolves the caller's tier (from the DPP launch identity / DatsMe user, or "base" for
standalone) and returns the effective entitlement to the themed page. **The browser never sees the
tier table** — only its own resolved `{max_poses, can_adopt, upsell_copy}` — same posture as the
pool app key (server-side secrets never reach the client, deploy spec Finding 9).

---

## 6. Integration map (what each layer touches)

| Layer | Frontend | Web tier (`webui/app.py`) | `pet_factory` / catalog | Handler |
|---|---|---|---|---|
| Landing | new `/design` page | — | reads `catalog.json` for tiles | — |
| Themed pages | new `/design/{animal}` + extracted `<PetDesigner>` | — | — | — |
| Base catalog | breed picker + base image + samples | `GET /api/catalog`, base/sample serving, adopt endpoint | new `animal_catalog/` dir + loader | — |
| Motion (**DONE** — implemented) | pose selector (shipped; step 1 relocates it) | `GET /api/motions`, `poses` on generate (shipped) | motion profiles + pose loop (shipped) | **v3** (shipped in repo; fleet rollout = step 0) |
| Tiers | pose caps + upsell + cost hint | tier resolution, cost computation | `tiers.json` loader | — |

- **The one shared UI extraction:** today's `/design/page.tsx` form logic → a reusable `<PetDesigner>`
  component (the "contract" half of §0). Themed pages compose it; General uses it bare.
- **The one API-client rule holds:** every endpoint URL stays in `web/src/lib/api.ts` (the single
  adapter — verified it is already the sole place, `api.ts`). New endpoints (`/api/catalog`,
  `/api/motions`, adopt, tier) are added there, nowhere else.
- **Handler v3** is shared with SPEC_MOTION_PROFILES — one version bump covers `poses`; the catalog
  base-image path rides as a `reference_image_b64` (the existing v2 transport), so it needs **no new
  handler field** (a curated base is just a reference image the web tier already knows how to send).

---

## 7. Decisions

1. **Tiered charging — RESOLVED (Rev.4): defaults set, all admin-tunable** (§5.2). Base
   `credit_pet_design_cost` = 100 (unchanged), `credit_pet_extra_pose_cost` = 50 per optional pose,
   charged once at Accept, pose count read **server-authoritatively from the fetched bundle's
   manifest** (never partner-claimed). The extra-pose knob is one small deferred `datsme_me`
   addition (the one exception to the no-host-change guard); until it lands, charging stays flat
   100 while the UI shows the intended full price. The numbers are deliberately unceremonious —
   they're config, revisit freely.
2. **Page model — RESOLVED: themed chrome hard-coded, generation contract shared** (§0/§3). Many
   themed shells, one shared `<PetDesigner>` + shared config.
3. **Base authoring — RESOLVED: generate-then-curate, long tail falls back to General** (§4.5).
4. **Doc structure — RESOLVED: this umbrella spec + SPEC_MOTION_PROFILES as the movement layer.**
5. **Which animals get themed pages at launch — RESOLVED (Rev.4): Cat + Dog + General.** The two
   highest-demand quadrupeds get themed pages + curated catalogs first; General remains the
   long-tail path. Expansion after launch is one catalog folder + one themed shell per animal.

---

## 8. Build order (Rev.4 — synced to the implemented motion layer; General never regresses)

0. **PREREQUISITE — v3 fleet rollout** per **`docs/SPEC_V3_FLEET_ROLLOUT.md`** (the standalone
   runbook; distills SPEC_DEPLOY_PETDATSME_POOL §B.1 to the exact node commands + gate). **Note
   (Rev.5 correction):** the fleet is now **two pet nodes already live** — `omen-pet` AND
   `dual-nvidia-pet` both serve `pet_factory` today (verified `GET /api/pool`), NOT "Omen first then
   add the dual-nvidia card." Both must be upgraded to v3 back-to-back with a `poses`-traffic freeze
   across the mixed window (the runbook §2–3 handles this; v3's optional fields make the window
   degrade to "fewer poses," never a wrong pet). **This is a DEPLOY gate, not a start gate:** steps
   1–5 below can be BUILT in `local` dev mode without the pool; v3 must be fleet-wide before any of
   this **deploys to a pool-backed environment**. **This moved from last step to prerequisite
   (Rev.4):** the shipped pose selector sends `poses` params, so any web-tier deploy of current
   `main` before v3 is fleet-wide means a user picking one optional pose gets a dispatcher 422. No
   platform step DEPLOYS anywhere until this is done. (Web deploys also need the `--no-deps -e`
   install first — deploy spec Rev.6 / deploy/README.md.)
1. **Extract `<PetDesigner>`** from `/design/page.tsx`; move the current page to `/design/general`.
   **Scope grew (Rev.4):** the extraction now carries the implemented pose selector, cost hint,
   `fetchMotions` wiring, and the `PoseGallery`/`PosePlayer` result components along with the
   original controls. *Gate: `/design/general` is byte-identical in behavior to today's
   page-with-selector.*
2. **Landing page** at `/design` with tiles for Cat World, Dog World, General.
   *Gate: `/design` → pick General → the current flow, end to end; DPP launch still works (the
   launch cookie is origin-scoped, so it survives the landing hop — §2).*
3. **Base-animal catalog** — `pet_factory/animal_catalog/` (cat + dog per §7.5) + loader +
   `/api/catalog` + base-image serving; wire the base image as the img2img source and pass the
   pinned `motion_profile` key on generate (motion spec §5.2). *Gate: pick cat→tabby → base shows
   instantly → generate redraws from it, pinned profile governs the build (assert via manifest
   `movement_class`) → consistent output.* (Bootstraps via generate-then-curate, §4.5; General
   covers the long tail.)
4. ~~Motion profiles + pose selector~~ — **DONE** (SPEC_MOTION_PROFILES implemented: commits
   `464095a` + `6e13aba`; 60 tests green). Landed in the current design page; step 1 relocates it
   into `<PetDesigner>`.
5. **First themed pages** (Cat World, then Dog World) — bespoke chrome around
   `<BreedPicker>`+`<PetDesigner>`+`<SampleGallery>`. *Gate: themed, uncluttered, generates via the
   shared engine; sample-adopt works GPU-free.*
6. **Tiers + charging** — entitlement resolution + selector caps + the resolved pricing (§7.1:
   base 100 + 50/extra pose, all admin-tunable). **Must replace the interim hardcoded
   `MAX_SELECTABLE_POSES = 5`** in the designer with the server-resolved entitlement, add
   **server-side per-user enforcement** (today the only server cap is the global `MAX_POSES=10` —
   every user effectively has the plus cap, unpriced), and land the one deferred host-side piece:
   the `credit_pet_extra_pose_cost` knob + manifest-based pose count at adopt (§5.2). *Gate: a base
   user is capped at 2 poses (walk+idle) with an upsell; a plus user freely picks up to 5; a
   selection over cap is refused/clipped server-side, not just in the UI; a 5-pose Accept charges
   250 (observed in the credit ledger) while a walk+idle Accept still charges 100.*

---

## 9. Consistency checks (global engineering rules)

- **New variant (animal/theme) without an engine change?** ✓ A new animal = a catalog folder + a
  themed shell; pose logic, billing, and generation are shared and untouched.
- **Things that change for different reasons live apart?** ✓ The central decision (§0): bespoke theme
  vs. shared contract, split precisely because they change for different reasons.
- **New feature without touching unrelated files?** ✓ Layers are independently shippable (§8); General
  never regresses; each new endpoint goes through the single API adapter.
- **Third-party/host integration without modifying owned paths?** ✓ `datsme_me` unchanged; tiers ride
  the existing credit system, the catalog base rides the existing `reference_image_b64` transport.
- **Bug isolation?** ✓ A broken Cat World theme can't affect Dog World or General (separate shells);
  a bad catalog entry can't affect the motion engine (separate loaders + guard tests).
- **Three-instances-before-consolidating, applied in reverse:** we do NOT fork `<PetDesigner>` per
  animal — the generation form is shared until a body type's *controls* (not its theme) genuinely
  diverge. Theme divergence is expected and cheap; contract divergence is resisted.

---

### Appendix — grounding (verified 2026-07-13)
- Current single design page + inline color/accessory catalogs (the `<PetDesigner>` extraction
  source): `web/src/app/design/page.tsx:17-46`.
- Single API adapter (the "one client per backend" rule to preserve): `web/src/lib/api.ts:18,38-93`.
- Existing routes (`design`, `house`) under `web/src/app/`.
- img2img remix pipeline the catalog base feeds: `pet_factory/factory.py` (`make_pet_zip`
  `reference_image`/`remix_strength`); reference transport `reference_image_b64` (deploy spec §A.2).
- Credit charge point: `docs/SPEC_DATSPET_DPP_INTEGRATION.md` (`credit_pet_design_cost`, at Accept).
- Motion/pose layer: `docs/SPEC_MOTION_PROFILES.md`.
- Fleet cutover discipline: `docs/SPEC_DEPLOY_PETDATSME_POOL.md` §B.1; the concrete v3 runbook (step 0):
  `docs/SPEC_V3_FLEET_ROLLOUT.md`.
- DPP launch deep-link (survives navigation to themed pages): `webui/datsme_integration.py` (`/launch`).
