# SPEC — Design Axes Admin (edit the design vocabulary + each animal's design profile, from the frontend)

**Status:** proposed, rev.2 (2026-07-16)
**The admin surface for:** `SPEC_PET_DESIGN_AXES` (the data model — axes, surfaces, the catalog join).
**Mirrors:** `SPEC_MOTION_PROFILE_ADMIN` — the same pattern that already lets an admin edit
motion profiles at `/admin/motions`. This is deliberately not a new pattern; it is the motion
admin, applied to design.

**Rev.2 changelog (post-review corrections):**
1. **Surface-axis delete guard added** (§2, §8) — deleting a surface axis still referenced by
   the catalog is refused, mirroring motion admin's catalog-pin delete guard. Rev.1 listed
   "used by" but let the delete through: the one path to an admin-created state the build
   rejects, violating §0.2's own invariant.
2. **Read-only refusals are `409`, not `403`** — matching what motion admin's
   `_require_writable` actually raises (`webui/motion_admin.py:49`); rev.1 said 403.
3. **`_writable()` is parameterized, not copied** (§2) — motion's version checks the *motion*
   dir and `MOTION_ADMIN_WRITABLE` specifically; the shared helper takes (content dir,
   override env var) so design passes its own.
4. **`surface_default` renamed `surface_default`** — "coat" is the fur axis's name; a bird's
   default is a plumage option. The field names the surface slot, not one surface's
   vocabulary.

Motion profiles are already editable from the frontend: `/admin/motions` lists each profile
with Edit / Duplicate / Delete / New, gated by the admin cookie, read-only on prod. Design
axes should be editable the same way — so the look owner can add "downy" plumage or set a
Persian's coat default without a code change or a deploy. Two things are editable here, and
they map to the two data stores of `SPEC_PET_DESIGN_AXES`:

1. **The design vocabulary** — the axes and their options (the `design_axes/` registry).
2. **Each animal's design profile** — its surface, and any per-breed overrides (the
   `animal_catalog` fields `SPEC_PET_DESIGN_AXES` added).

---

## 0. The core decisions (read this first)

1. **Reuse the motion-admin architecture verbatim; do not invent one.** Motion admin is three
   layers (`SPEC_MOTION_PROFILE_ADMIN`): a **pure-data write path** in the content package
   (`pet_factory/motion_profiles/admin.py`) whose `validate_profile` is the *single* definition
   of "valid" — shared with the guard test, so the admin can never write what the build would
   reject; a **thin HTTP layer** (`webui/motion_admin.py`) gated by `require_admin_launch`; and
   a **list+editor page** (`web/src/app/admin/motions/page.tsx`). Design admin is the same three
   layers, pointed at design data. Every hard problem — the shared validator, the admin gate,
   the read-only-prod posture, the audit log — is already solved; copy it.

2. **The validator is the contract, and it is shared with the guard tests.** This is the
   load-bearing invariant of the whole admin surface (`SPEC_MOTION_PROFILE_ADMIN` §0.2): the
   function the admin calls to check a write is the *same* function `SPEC_PET_DESIGN_AXES` §10's
   guard tests call. So the admin physically cannot save an axis with an empty non-default
   fragment, a surface with no axis, or a catalog `surface` that resolves to nothing — the same
   things that fail the build. The admin surface can never drift from the build's rules because
   there is one rule.

3. **Two editable concerns, one admin area, presented as two tabs.** The vocabulary (axes) and
   the per-animal profile (surface + overrides) are different data stores that change for
   different reasons (`SPEC_PET_DESIGN_AXES` §0.4), so they get separate write paths and
   separate validators — but one page, `/admin/design`, with a **Features** tab and an
   **Animals** tab, because to the look owner it is one job: "configure how pets can be
   designed." One admin nav entry, one gate, one read-only banner.

4. **Read-only on prod — author on dev, exactly like motion.** Prod shows the same "read-only
   instance — author on dev" banner motion admin shows; writes refuse with `409` (what
   `_require_writable` actually raises — rev.1 said 403). Design vocabulary and
   catalog surface tags are curated content authored on dev and shipped as files (the same
   lifecycle as base images and motion profiles), so prod is a read replica. `_writable()`
   from motion admin is reused by **parameterizing** it (content dir + override env var), not
   by copying it — the motion version checks the *motion* dir and `MOTION_ADMIN_WRITABLE`
   specifically.

5. **The Animals tab edits a NARROW slice of the catalog — never the curated structure.** It
   may write only the *design-profile* fields (`surface`, `surface_default`, `surface_options`);
   it must not touch `base.png`, breed identity, `motion_profile`, or anything that a promote
   script owns. A guard on the write path enforces the allowed field set, so a design edit can
   never corrupt a vetted base image.

6. **It grows by data, like everything else here.** A Tier 2 axis (material, aura) added to the
   registry appears in the Features tab automatically — no admin code changes. A new surface (a
   "shell" for turtles) appears in the Animals tab's surface dropdown automatically. The four
   test questions (§8) hold for the admin exactly as they hold for the data.

---

## 1. Layer 1 — the pure-data write paths (content packages)

Two write modules, each mirroring `pet_factory/motion_profiles/admin.py` (`load_registry`,
the shared `validate_*`, `write_*`/`delete_*` primitives that validate → mutate file+registry →
bust cache; pure stdlib, no ML — importable on the GPU-less web tier).

### 1.1 `pet_factory/design_axes/admin.py` — the vocabulary write path
- `load_registry()` — the raw `registry.json` + axis files, re-read each call (the admin needs
  live disk, not the cached view).
- `validate_axis(axis, registry)` — **the single definition of a valid axis**, shared with
  `SPEC_PET_DESIGN_AXES` §10's guard tests. Enforces: a default option whose fragment is `""`;
  every non-default option has a non-empty fragment (a control that does nothing fails); `kind`
  ∈ {universal, surface}; a surface axis declares an `applies_to`; `clause_slot` present;
  `position` ∈ {prefix, suffix}. Returns the error list the guard test asserts on.
- `write_axis(axis, *, existing_key)` / `delete_axis(key)` — validate, then write the axis file
  + registry entry, then bust the cache. `AxisWriteError` carries the validator's error list,
  exactly like `ProfileWriteError`.

### 1.2 `pet_factory/animal_catalog/admin.py` — the per-animal design-profile write path
- `set_design_profile(animal_key, breed_key, *, surface, surface_default, surface_options)` —
  writes ONLY those fields onto the catalog entry (§0.5), leaving `base.png`, `motion_profile`,
  and identity untouched. `breed_key` optional: unset edits the animal-level default that
  breeds inherit; set edits one breed's override.
- `validate_design_profile(...)` — **shared with the catalog guard test** (`SPEC_PET_DESIGN_AXES`
  §10 "catalog surface integrity"): `surface` must match some surface axis's `applies_to`;
  `surface_default` / each `surface_options` entry must be a real option key of that surface's
  axis. A typo can't ship a breed whose surface axis silently never appears — the admin is
  blocked at save, the build is blocked at test, by the same function.
- The allowed-field guard (§0.5) lives here: the write refuses any key outside the design-
  profile set.

---

## 2. Layer 2 — the HTTP layer (`webui/design_admin.py`)

One router, mirroring `webui/motion_admin.py`:
```python
router = APIRouter(prefix="/api/admin/design",
                   dependencies=[Depends(datsme_integration.require_admin_launch)])
```
- Reuses motion admin's `_writable()` / `_require_writable()` (read-only prod → `409`) by
  **parameterizing** them — the shared helper takes (content dir, override env var), motion
  passing (`motion_profiles/`, `MOTION_ADMIN_WRITABLE`) and design passing (`design_axes/`,
  `DESIGN_ADMIN_WRITABLE`) — and `_audit()` (logs `who op what`, e.g. `[design-admin] markly
  wrote axis 'plumage'`).
- **Axes** (`/axes`): `GET` list (each axis + its "used by" — the animals whose *resolved*
  surface maps to it, the design analog of motion's "pinned by"), `GET /axes/{key}`, `POST`,
  `PUT /{key}`, `DELETE /{key}` → `design_axes.admin`.
- **Delete guard (rev.2 — §0.2's invariant applied to deletes):** `DELETE /axes/{key}` on a
  surface axis still referenced by any catalog entry's resolved `surface` refuses with `409`
  naming the blockers — the design analog of motion admin's catalog-pin delete guard
  (`_catalog_pins_for`). Without it, deleting `plumage.json` while a bird tags `feathers`
  would create exactly the broken state the build guard rejects. Universal axes carry no
  catalog reference and delete freely (the option-level validators still apply).
- **Animals** (`/animals`): `GET` the animal/breed tree with each entry's resolved surface +
  overrides; `PUT /animals/{animal}[/{breed}]` sets the design profile → `animal_catalog.admin`.
- Validation errors from the shared validators surface as `422` with the error list, so the
  editor pane can show them inline — the same shape motion admin returns.

---

## 3. Layer 3 — the frontend page (`web/src/app/admin/design/page.tsx`)

Mirrors `web/src/app/admin/motions/page.tsx`: an admin-gate check, a list, an editor pane, the
"read-only instance — author on dev" banner, inline validator errors, a delete confirm. Two
tabs:

### 3.1 Features tab (the vocabulary — the direct motion-admin parallel)
Each axis is a card, exactly like a motion profile card: name, `kind` (universal/surface), and
for a surface axis its **used by: cat, dog, rabbit** line (mirroring motion's "pinned by").
Edit / Duplicate / Delete, and **+ New axis**. The editor pane edits the axis: its options
(add / remove / reorder), each option's label + `prompt_fragment`, and the axis-level
`clause_slot` / `position` / `min_strength` / `applies_to`. Adding "downy" to plumage is: open
plumage → add an option → Save. Adding a whole Tier 2 axis is **+ New axis**.

### 3.2 Animals tab (the per-animal design profile — the "animal body profile" editor)
A table of animals → breeds. Each row shows the **surface** (a dropdown of the surface axes'
`applies_to` values — fur / feathers / scales / …) and expands to per-breed overrides:
`surface_default` (a dropdown of that surface axis's options) and `surface_options` (a multi-select
to restrict the list — e.g. Sphynx → only hairless). An animal-level row sets the default all
its breeds inherit; a breed row overrides it. This is where "Persian defaults to long-haired"
and "this bird has feathers" are set, from the frontend, no deploy.

Because the *server* resolves surface and filters axes (`SPEC_PET_DESIGN_AXES` §4), nothing here
duplicates that logic — the Animals tab writes the classification; the design step reads it.

### 3.3 Nav
An **Admin → Design** entry beside the existing **Admin → Motions**, gated by the same
adm-claim cookie (the toolbar already shows "Admin" for a valid admin session).

---

## 4. Read-only / prod posture

Identical to motion admin (§0.4): prod is a read replica showing the banner; writes refuse
with `409` via the reused `_require_writable()`. Authoring happens on dev, and the edited files (axis JSON, catalog
JSON) ship to prod through the normal deploy — the same content lifecycle as motion profiles
and base images. No new prod write surface, no new trust boundary.

---

## 5. Security

- **Gate:** `require_admin_launch` — the adm-claim cookie, reused unchanged. No new auth.
- **Blast radius:** the vocabulary write path touches only `design_axes/`; the catalog write
  path touches only the design-profile fields of `animal_catalog` (§0.5, enforced) — never a
  base image, never motion. A compromised or fat-fingered design edit cannot corrupt a curated
  base or a motion profile.
- **Validation before write, always** — the shared validator runs on every write, so the admin
  cannot persist an axis or a surface the build would reject. The failure mode is a 422 with
  reasons, never a half-written registry.
- **Audit:** every write logs who/op/what, reusing motion admin's `_audit`.

---

## 6. The four test questions

- **New variant → engine/admin change?** No. A new axis or option is data the Features tab
  already edits; a new surface is a dropdown value the Animals tab already offers. The admin is
  axis- and surface-count-agnostic.
- **New feature → touch unrelated files?** No. The two write paths are self-contained; the HTTP
  and frontend layers iterate whatever the registries/catalog contain.
- **Third-party integration → modify owned paths?** N/A.
- **Bug in one variant → debug shared code?** Isolated. A bad plumage option can't affect coat
  or any motion profile; the catalog write path can't reach a base image. The shared validators
  are small and guard-tested.

---

## 7. Phasing / build order

| Phase | Scope | Gate |
|---|---|---|
| **A** | `design_axes/admin.py` (`validate_axis` shared with §10 guards, write/delete); `/api/admin/design/axes` incl. the surface-axis delete guard; the **Features** tab. | An admin edits an option's fragment and the design step reflects it; an invalid axis is 422'd with the same errors the guard test asserts; deleting a catalog-referenced surface axis is 409'd naming the blockers; prod 409s writes. |
| **B** | `animal_catalog/admin.py` (`validate_design_profile` shared with the catalog guard; allowed-field guard); `/api/admin/design/animals`; the **Animals** tab. | Setting a breed's surface changes which surface axis the design step shows; an out-of-range `surface_default` is 422'd; a write to a non-design field is refused; a base image is provably untouched. |

Phase A is the direct motion-admin mirror and ships first (it is the vocabulary, the thing most
like `/admin/motions`). Phase B adds the catalog write path — the genuinely new piece — and
gates on the allowed-field guard so it can never scratch a curated base. Both depend on
`SPEC_PET_DESIGN_AXES` Phases 1–2 existing (there must be axes and a `surface` field to edit).

**Implemented 2026-07-16 (Phases A + B), with three as-built deviations, each recorded where
it lives:**

1. **Duplicate is CLIENT-side** (prefill the editor as a create), not motion's server-side
   clone: a surface axis's `applies_to` is unique, so a written clone would be invalid until
   edited — prefill lets the admin fix it before the file exists. Same UX, no invalid
   intermediate state.
2. **`surface_default` is persisted + validated but READ-INERT, and the Animals tab does not
   offer it yet** — its semantics are genuinely unresolved (§9.5). Writing a field nothing
   reads would gaslight the look owner; the schema slot exists so resolving it later is a
   read-layer change, not a migration.
3. **The allowed-field guard has two layers:** structurally at the write path (explicit
   keyword args + whole-entry preservation) and `extra="forbid"` on the HTTP body, so an
   unknown field dies at parse. The shared `_writable()` was extracted to
   `webui/admin_common.py` (dir + override env parameterized), exactly per rev.2 §2.

---

## 8. Guard tests

- **Validator parity (the load-bearing one):** the admin's `validate_axis` /
  `validate_design_profile` ARE the functions `SPEC_PET_DESIGN_AXES` §10's build guards call —
  asserted by importing the same symbol in both. If they ever diverge, the build fails.
- **Read-only prod refuses writes with `409`** (reuses motion admin's test).
- **Surface-axis delete guard (rev.2):** deleting a surface axis referenced by any catalog
  entry's resolved surface is refused with `409` naming the referencing animals; deleting an
  unreferenced axis succeeds. The design mirror of motion's catalog-pin delete-guard test.
- **Allowed-field guard:** a catalog write carrying `base_png` / `motion_profile` / an unknown
  key is refused; only `surface` / `surface_default` / `surface_options` pass.
- **Round-trip:** write an axis via the admin path → the design step's `/api/design-axes`
  reflects it; set a surface via the admin path → the axis filter changes for that animal.
- **Gate:** every `/api/admin/design/*` route 401s without the adm cookie (reuses motion admin's
  gate test).

---

## 9. Open questions

1. **One page or two?** This spec proposes one page, two tabs (§0.3). If the Animals tab grows
   (per-breed defaults across many breeds), it may warrant its own route — deferred until the
   table is real.
2. **Preview-in-admin.** Motion admin doesn't render a pet; should the design admin show a
   sample sprite for an edited axis? Valuable but it needs GPU (a preview call), so it is a
   later enhancement, not core CRUD.
3. **Bulk surface assignment.** Setting `surface` one breed at a time is fine for a small
   catalog; a "set all cat breeds to fur" bulk action is a nicety if the catalog grows large.
4. **Who authors vocabulary vs profiles?** The look owner likely owns both, but the two tabs
   could carry different sub-permissions later; the single adm gate is enough for now.
5. **`surface_default` semantics — OPEN, and blocking its UI.** "Persian defaults to
   long-haired" can mean (a) *preselect* long-haired (it then composes words and counts as a
   design — violating "the default is the absence of a choice"), or (b) *treat it as the
   no-op* (its curated base already looks long-haired — but then picking "natural" is a
   selectable option that changes nothing, the §12 dead-control class inverted). Neither is
   right yet, which is exactly why `SPEC_PET_DESIGN_AXES` §11.1 deferred it. The field is
   persisted, validated (a typo still can't ship), and read-inert; the Animals tab omits it
   until this is decided.

---

### Appendix — grounding (verified 2026-07-16)

| Claim | Evidence |
|---|---|
| Motion admin is a thin HTTP layer over a pure-data write path; validator shared with the guard test | `webui/motion_admin.py:1-9`; `pet_factory/motion_profiles/admin.py:1-9` |
| Router gated by the adm-claim cookie | `webui/motion_admin.py:26-27` (`require_admin_launch`) |
| Read-only-on-prod posture + audit already exist | `webui/motion_admin.py:36,46,83` (`_writable`, `_require_writable`, `_audit`) |
| The catalog "pinned by" mapping the design "used by" mirrors | `webui/motion_admin.py:60` (`_catalog_pin_map`) |
| `validate_profile` is the single definition of valid | `pet_factory/motion_profiles/admin.py:51` |
| Frontend admin page: gate + list + editor + read-only banner | `web/src/app/admin/motions/page.tsx:38-44,154` |
| The design data model these edit (axes, surface, catalog join) | `SPEC_PET_DESIGN_AXES` §1, §3 |
