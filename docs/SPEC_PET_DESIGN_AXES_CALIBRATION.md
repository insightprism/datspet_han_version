# SPEC — Design-Axes Recalibration (the re-runnable pass, and the reminder that tells you when)

**Status:** proposed, rev.4 (2026-07-16)
**Extends:** `SPEC_PET_DESIGN_AXES` §8 Phase 3 (the one-time calibration pass) — this spec makes
that pass a permanent, incremental, self-reminding tool instead of a one-shot script.
**Integrates with:** `SPEC_PET_DESIGN_AXES_ADMIN` (implemented 2026-07-16) — §6 gives the admin
surface one endpoint + one badge so a look-owner edit surfaces its own recalibration need.

**Rev.4 changelog (pre-implementation — the strength-recompute gap):**
1. **The cell strength is a TWO-SOURCE formula, and it is the predicate's — not the render
   tool's** (§2, §3, §8). A cell's `strength` is `effective_strength(picks)` (base 0.85
   raised by each picked axis's declared `min_strength`) **then** `max`'d with
   `compose_design`'s *returned* `min_strength` (the colour-word/species conflict — this is
   why `bluejay/color_only` is 0.9 with no picks at all: "blue" in "blue jay" fights the
   recolor). Both inputs are pure-CPU. The single function that computes it,
   `effective_strength(picks, color, species)`, lives in `webui/design_calibration.py` (the
   predicate module), and the render tool **imports it** rather than keeping its own copy —
   the scratchpad's `effective_strength` lived in the render script, which is exactly how the
   tool and predicate would drift and the predicate would mark *stale* what the tool renders
   *fresh*. One knower (decision 0.2 applied to strength).

**Rev.2 changelog (pre-implementation review fixes):**
1. **The expected substrate is DECLARED in `matrix.json`, model included** (§0.3, §3) — the
   CPU-only gate can't import `pet_factory.factory` to learn the live `ZIMAGE_UNET` (that's
   the ML stack), so it compares manifest header against matrix *declaration*, both data;
   the render tool refuses to run when the live model disagrees with the declaration.
   Swapping the model = editing `matrix.json` = a deliberate stale-the-world act. The header
   also records the ComfyUI version — the one substrate drift fixed-seed determinism doesn't
   survive.
2. **Per-cell `rendered_at` added to the manifest schema** (§3, §8) — rev.1's "renders newer
   than the stamp" had no timestamp to compare.
3. **Lazy-import discipline named** (§2, §6): `app.py` imports `design_admin` at module top
   *before* `compose_design` is defined, so `design_calibration` must import `app` inside its
   functions (and the admin endpoint imports `design_calibration` the same way), or the cycle
   lands on a partially-initialized module.
4. **§6 endpoint path corrected** to the implemented router prefix
   (`/api/admin/design/calibration-status`) and the response shape specified so the Features
   tab can map cell verdicts back to per-option badges.
5. **Phase 0 adopts from `calibration_snapshot_20260716/`** (the durable repo-local copy),
   not the ephemeral session scratchpad; and it adopts the **v2-at-0.9 renders** for the
   coat/plumage/scales cells — those axes now carry `min_strength: 0.9`, so the round-1
   0.85 renders for them would (correctly) read *stale* on day one, failing Phase 0's own
   all-current gate.

**Rev.3 changelog (pre-implementation verification — the snapshot manifest was READ,
not assumed):**
1. **Phase 0 is a reconciliation, not a pure data move** (§3, §9). The snapshot's
   `manifest.json` records the twelve coat/plumage/scales option cells at **0.85** — the
   v2-at-0.9 pass wrote PNGs into `v2_at_090/` but never wrote its entries back — so
   adoption must rewrite those entries' strength to 0.9 alongside adopting the PNGs.
   `python/scales-patterned` has **no v2 render at all**, and the combo cells are
   internally inconsistent (bluejay's recorded at 0.9, tabby's and python's at 0.85), so
   whichever recipe the tool defines, a few cells read *stale* on day one. Phase 0
   therefore needs ComfyUI up for a small heal run (~1 min GPU); its gate now says so.
2. **`_base` cells specified** (§3, §8). The four per-animal baseline renders in the
   snapshot are **expected cells** — the undesigned reference the reviewer compares every
   option against — with `description` = the representative's species and
   `strength: null` (nothing composed, so no clamp ran). The schema guard requires the
   fields on every cell; a null strength is legal only where `picks`, `color`, and
   `accessories` are all empty.
3. **The combo recipes have a named source of truth** (§2, §3): the Phase 3 scratchpad
   scripts — preserved durably at `calibration_snapshot_20260716/calibrate_axes.py`
   (+ `calibrate_axes_v2.py`), since `/tmp` does not survive a reboot — are what actually
   produced the measurements. The promoted tool lifts their recipes verbatim; re-deriving
   the recipes from this spec's prose is how day-one staleness gets invented.
4. **`rendered_at` format pinned** (§3): ISO-8601 UTC with the `Z` suffix
   (`%Y-%m-%dT%H:%M:%SZ` — the shape `datsme_integration._utc_now_iso` already uses),
   never a naive local timestamp.
5. **`calibration_renders/` gets its `.gitignore` entry in Phase 0** (§9) — the renders
   are regenerable at the fixed seed; the manifest is the durable record.

---

## 0. The core decisions (read this first)

1. **Calibration is a measurement with a durable record, not an event.** The Phase 3 run
   proved every fragment live / non-destructive / subject-preserving *as composed on a given
   substrate*. What made it true is recorded in a committed **calibration manifest**: per cell,
   the exact composed description and strength; in a header, the substrate (seed, model, base
   strength). Anything that would change what production composes or renders makes the record
   visibly stale — that visibility *is* the reminder.

2. **Staleness is derived, never authored.** No `"calibrated": true` flag ever appears in an
   axis file — a hand-set flag goes stale silently, which is the exact failure this spec
   exists to prevent. One pure, CPU-only predicate compares the registry-derived *expected
   matrix* against the manifest: recompose every expected cell (no GPU) and diff
   `(description, strength)` against what was measured. Three verdicts per cell:
   **current** (measured, unchanged), **missing** (never measured — new option/axis/surface),
   **stale** (measured, but the composition or substrate has since changed).

3. **The matrix is data, derived from the registry — and it DECLARES the substrate.**
   Surfaces come from `design_axes.known_surfaces()`; a small `matrix.json` maps each
   surface to its representative animal (tabby → fur, blue jay → feathers, python → scales)
   plus the fixed unknown-surface probe (the clockwork octopus). **A surface with no
   representative fails the check** — the half-formed-entry rule from `registry.json`,
   applied to calibration. That is the "new surface class" reminder, mechanically.
   The substrate (seed, base strength, **and the expected `zimage_unet`**) is declared here
   as data (rev.2): the CPU-only predicate compares manifest header against this
   declaration — never importing the ML stack to ask the live value — and the render tool
   refuses to run when the live `factory.ZIMAGE_UNET` disagrees with the declaration.
   Changing the model is an edit to `matrix.json`: deliberate, diffable, and it stales the
   world by design.

4. **Re-runs are incremental by default.** The renderer skips *current* cells, re-renders
   *missing* and *stale* ones, at the fixed seed from the manifest substrate — so a new
   "downy" plumage option costs ~4 renders (~1 min GPU), not the full ~13-minute matrix.
   `--full` exists for substrate changes, where everything is stale by definition.

5. **The gate is mechanical freshness; human review is recorded, not build-gated.** CI can
   verify "every expected cell was rendered from the current composition." It cannot verify
   that a human looked. A build-red that clears by stamping `--mark-reviewed` without looking
   is the same-surface-test fallacy — so the guard test gates on freshness only, and the
   review stamp is reported by `--check` (a warning, with the command that clears it), never
   a CI failure.

---

## 1. What triggers recalibration (the taxonomy the tool detects)

| Change | Detected as | Cost to clear |
|---|---|---|
| New **option** on an existing axis (e.g. admin adds "downy" plumage) | cells *missing* for that option across applicable animals | ~1 render per applicable animal (~10 s each) |
| New **axis** (Tier 2: material, aura, …) | all that axis's option cells *missing* | one column of the matrix (~minutes) |
| New **surface class** (e.g. `shell` for turtles) | `known_surfaces()` has a surface with no `matrix.json` representative → **check fails with "add a representative"**; once added, all its cells *missing* | one row of the matrix (~minutes) |
| **Fragment / clause_slot / position / min_strength edit** | affected cells *stale* (recomposed description or strength differs from manifest) | just the touched cells |
| **Substrate change** — seed, base strength, expected `zimage_unet` (all `matrix.json` edits), or a `compose_design` ordering change | manifest header ≠ `matrix.json` declaration (CPU-detectable), or mass description drift → **everything stale**. A ComfyUI upgrade is recorded in the header at render time but is NOT CPU-detectable — the render tool warns on its next run | full matrix (~13 min GPU) + full human re-review |
| New **animal or breed** on an existing surface | **nothing** — axes are calibrated per surface, not per animal; a corgi is a catalog tag | zero |
| Features that never reach the composed prompt | **nothing** | zero |

---

## 2. The tool — `scripts/calibrate_design_axes.py`

Promoted from the Phase 3 scratchpad scripts, preserved at
`calibration_snapshot_20260716/calibrate_axes.py` + `calibrate_axes_v2.py` (rev.3 — the
session scratchpad they were born in is `/tmp` and does not survive a reboot). Same
production path: `webui`'s `compose_design` for the prompt,
`pet_factory.render_design_still` for the pixels, and the app's strength clamp — which the
tool does **not** re-implement: it imports `design_calibration.effective_strength` (rev.4,
§0.1), the same function the predicate recomputes with, so a rendered cell and a
freshness-checked cell can never disagree on strength. The combo recipes are lifted from
those scripts **verbatim**, because they are what produced the measurements the manifest
records. Modes:

- **(default) render** — incremental: render *missing* + *stale* cells only, skip *current*
  ones; update their manifest entries; print the per-cell log. Needs ComfyUI up on
  `PET_FACTORY_COMFY_URL` (`source pet_env.sh` first, like every factory entry point).
- **`--check`** — CPU-only, no GPU, no ComfyUI: print the per-cell verdict table
  (current / missing / stale + reason), the review-stamp status, and exit non-zero if any
  cell is not current. Every failure line ends with the command that fixes it.
- **`--full`** — delete all renders + manifest cells, re-render everything (substrate
  changes).
- **`--sheet`** — build one contact-sheet PNG per animal from the current renders (PIL
  montage, labels from cell keys) — the artifact the human actually reviews; §8 Phase 3
  said it from the start: the GPU is cheap, the eyeballing is the real cost.
- **`--mark-reviewed`** — stamp the manifest header (`reviewed: {date, notes}`) after the
  human has eyeballed the sheet against the Tier C bar (`SPEC_PET_DESIGN_AXES` §12.4).
  Renders newer than the stamp ⇒ `--check` reports "rendered but unreviewed."

The staleness predicate, the expected-matrix builder, and the strength function
(`effective_strength`, rev.4) are **importable pure functions in
`webui/design_calibration.py`** (CPU-only; uses `app.compose_design` +
`pet_factory.design_axes`, never the GPU path). The CLI, the guard test, and the admin
endpoint (§6) all call these same functions — one knower, three surfaces.

`effective_strength(picks, color, species)` replicates `/api/preview`'s clamp exactly:
start at `matrix.json`'s `base_strength` (0.85), raise to any picked axis's declared
`min_strength` (`design_axes.axis_composition`, ignoring default picks), then take the
`max` with `compose_design(species, color, [], picks)`'s returned `min_strength` (the
colour-word/species conflict), and clamp to ≤ 0.9. The predicate recomputes each cell's
`(description, strength)` with `compose_design` + this function and diffs against the
manifest — so getting only the axis half (and missing the colour-word half) is the bug
that would mark `bluejay/color_only` perpetually *stale*.

**Import discipline (rev.2, load-bearing):** `app.py` imports `design_admin` at module top
*before* `compose_design` is defined, so a module-top `import app` anywhere on that chain
lands on a partially-initialized module. `design_calibration` therefore imports `app`
**inside its functions**, and the §6 endpoint imports `design_calibration` the same way.
The render tool additionally reads `pet_factory.factory.ZIMAGE_UNET` (the ML stack — fine,
it runs on the GPU dev box) to refuse a render whose live model disagrees with
`matrix.json`'s declaration; `design_calibration` itself must never import `factory`
(guard-tested, §8).

## 3. The data

- **`pet_factory/design_axes/calibration/matrix.json`** (committed) — the matrix as data:
  ```json
  {
    "substrate": { "seed": 20260716, "base_strength": 0.85,
                   "zimage_unet": "zImageTurbo_turbo.safetensors" },
    "representatives": {
      "fur":      { "key": "tabby",   "species": "tabby",  "base": "catalog:cat/tabby" },
      "feathers": { "key": "bluejay", "species": "blue jay" },
      "scales":   { "key": "python",  "species": "python" }
    },
    "unknown_probe": { "key": "unknown", "species": "a clockwork octopus" },
    "combos": ["color_only", "stack", "stack_strong"]
  }
  ```
  The whole substrate lives here (data), model included (rev.2) — changing any of it is a
  deliberate substrate change that stales the world, by design, and the CPU-only gate can
  see it without importing the ML stack. The §11.6 combo recipes (purple + wizard hat + the
  first surface pick; `stack_strong` adds `body: fat`) stay in the tool — they are the
  test procedure, one file with one reason to change — and are lifted verbatim from the
  preserved scratchpad scripts (§2, rev.3): the recipe that produced the measurement is
  the recipe, and a re-derived one that composes even one word differently marks every
  combo cell stale on day one.
- **`pet_factory/design_axes/calibration/manifest.json`** (committed) — the record:
  substrate header (seed, base strength, `zimage_unet` and the ComfyUI version as observed
  at render time — the version is informational: fixed-seed determinism doesn't survive a
  sampler change, and the header is where that shows up after the fact), `reviewed` stamp,
  and one entry per cell: `{animal, cell, description, strength, picks, color, accessories,
  file, rendered_at}`. `rendered_at` (rev.2) is what makes "rendered but unreviewed"
  computable against the review stamp; its format is ISO-8601 UTC with the `Z` suffix
  (rev.3, `%Y-%m-%dT%H:%M:%SZ`). Small (tens of KB) — this is what CI diffs against.
- **`_base` cells are expected cells** (rev.3). Each representative (and the unknown
  probe) carries one `_base` cell: the undesigned baseline the reviewer compares every
  option against — "visibly changes the still *vs baseline*" needs the baseline on the
  sheet. Its expected `description` is the representative's species exactly (no
  composition ran) and its `strength` is `null` (no design, so no clamp) — the one place
  a null strength is legal (§8). It goes *stale* like any cell: rename a representative's
  species in `matrix.json` and its `_base` recomposes differently.
- **Renders** — `calibration_renders/<animal>/<cell>.png` at repo root, **gitignored**
  (~45 MB of PNGs; regenerable at the fixed seed). The manifest, not the pixels, is the
  durable record.
- These live in a **subdirectory** of `design_axes/` precisely so the existing
  axis-file ↔ registry-entry pairing test (which pairs top-level `*.json`) is untouched —
  no new exemption list entry.
- **Adopt, don't re-burn — but adoption is a reconciliation, not a copy** (rev.3, from
  reading the snapshot manifest rather than assuming it). Phase 0 seeds `manifest.json`
  and `calibration_renders/` from **`calibration_snapshot_20260716/`** (the durable
  repo-local copy of the Phase 3 run; gitignored, so adoption into the committed manifest
  is what makes the record permanent). The adoption pass:
  1. Rewrite the manifest's `file` paths to the new layout; add the substrate header and
     per-cell `rendered_at` stamps; drop `_petout/` (a throwaway test SQLite, not render
     evidence).
  2. **For the twelve coat/plumage/scales option cells: adopt the `v2_at_090/` PNGs AND
     rewrite the entries' `strength` to 0.9.** The v2 pass wrote pixels, not manifest
     entries — the snapshot records these cells at 0.85, so adopting the PNGs alone still
     reads *stale* (strength is one of the two staleness inputs). Exception:
     **`python/scales-patterned` has no v2 render** — it is a day-one heal (~10 s).
  3. **Pattern cells keep their round-1 0.85 renders.** `v2_at_090/` also holds
     exploratory pattern re-renders (tabby spotted/tuxedo, bluejay spotted) from the
     min_strength probe; pattern's `min_strength` is deliberately `null`, so the 0.85
     renders are the current ones and adopting the v2 pattern PNGs would itself be a
     strength mismatch.
  4. **Expect a small combo heal.** The snapshot's combo cells are internally
     inconsistent — bluejay's recorded at 0.9, tabby's and python's at 0.85 — so
     whichever recipe the tool lifts (§2), a few combo cells read *stale* on day one.
     That is `--check` doing its job; the incremental run heals them (~1 min GPU total
     with scales-patterned). Phase 0 therefore needs ComfyUI up.

  `verdicts.json` (the per-cell human judgments) seeds the first `reviewed` stamp's notes.

## 4. The reminder — where it surfaces

1. **Guard test (the registry-level reminder, CI-enforced):**
   `webui/tests/test_design_axes_calibration.py` — pure CPU, calls the §2 predicate,
   fails the build if any expected cell is *missing* or *stale*, printing the cells and
   the one command to run. Adding an axis, an option, or a surface without recalibrating
   is now a red build with instructions, exactly like a half-formed registry entry. The
   parent spec's stance makes this a fail, not a warn: *an un-calibrated axis is worse
   than none.* Escape knob for spike branches (`policy knob` pattern — one env var, one
   predicate, default strict): `DESIGN_CALIBRATION_GATE=warn` downgrades to a printed
   warning; unset means fail.
2. **`--check`** — the same verdicts on demand, plus the review-stamp warning, for the
   developer mid-edit.
3. **Admin badge (§6)** — the look owner who adds "downy" plumage from the browser sees
   the reminder *in the same screen*, without running anything.

## 5. What a recalibration run looks like (the whole loop)

```bash
# after adding scales option "iridescent" (admin UI or JSON edit):
source pet_env.sh
.venv/bin/python scripts/calibrate_design_axes.py --check     # → python/scales-iridescent MISSING
.venv/bin/python scripts/calibrate_design_axes.py             # renders the 1 missing cell (~10 s)
.venv/bin/python scripts/calibrate_design_axes.py --sheet     # rebuild python's contact sheet
# human eyeballs the sheet against the Tier C bar (§12.4)
.venv/bin/python scripts/calibrate_design_axes.py --mark-reviewed
git add pet_factory/design_axes/ && git commit                # fragment + manifest land together
```

The fragment edit and its measurement update travel in one commit — they change for the
same reason, so they live (and land) together.

## 6. Admin-surface integration (the admin shipped 2026-07-16; this rides on it)

- **`GET /api/admin/design/calibration-status`** (rev.2 — the implemented router's prefix,
  mounted on `webui/design_admin.py`'s existing router, same gate) — returns the §2
  predicate's output shaped for the badge mapping:
  `{reviewed: {...}|null, unreviewed_render_count, cells: [{animal, axis, option, cell,
  verdict, reason}]}` — `axis`/`option` split out per cell (not just the joined cell key)
  so the Features tab can aggregate verdicts per option without parsing. It imports
  `design_calibration` **lazily inside the endpoint** (§2's import discipline; the router
  is imported by `app.py` before `compose_design` exists). No new logic.
- The axes admin list renders an **"uncalibrated" badge** on any option with a missing or
  stale cell, and a page-level banner naming the §5 command. The badge is read-time
  derived state — the admin never sets or clears it by hand (decision 0.2).
- Prod is read-only for this surface (mirrors motion admin), and the pool/prod boxes have
  no local GPU path — recalibration is a dev-box act; prod only ever *displays* status.

## 7. The four test questions

- **New variant → engine change?** No. A new option/axis recalibrates via a render run +
  manifest update — data only. A new surface adds one `matrix.json` representative — data.
- **New feature → touch unrelated files?** No. The tool, predicate, matrix, and manifest
  are four files that change only for calibration reasons.
- **Third-party integration → modify owned paths?** N/A.
- **Bug in one variant → debug shared code?** Isolated: a bad fragment shows up as *its*
  cell failing review; the predicate and renderer are shared but content-blind.

## 8. Guard tests

- **Predicate coverage:** every registry axis option (non-default) for every
  `known_surfaces()` surface + unknown probe appears in the expected matrix, plus one
  `_base` baseline and the three §3 combo cells per animal (rev.3); a surface
  without a representative raises with the add-a-representative message.
- **Freshness gate:** the §4 guard test itself (missing/stale ⇒ fail, `warn` knob honored).
- **Purity:** `webui/design_calibration.py` imports no GPU/ComfyUI path — in particular
  never `pet_factory.factory`, even to read a model constant; the expected model comes
  from `matrix.json` (extends the existing GPU-less posture guard).
- **Strength parity (rev.4):** the render tool and the predicate compute a cell's strength
  through the *same* `design_calibration.effective_strength` — asserted by importing the
  symbol in both, the way the admin/guard validator parity is asserted. A test pins the
  colour-word case (`effective_strength({}, "purple", "blue jay") == 0.9`) so the
  two-source formula can't regress to the axis-only half.
- **Manifest schema:** header requires seed + base strength + `zimage_unet` (matching
  `matrix.json`'s declaration); every cell entry carries description + strength (the two
  staleness inputs) and `rendered_at` (the review-stamp input) — a cell without them
  fails, so the predicate can never silently skip one. `strength: null` is legal ONLY on
  a cell whose `picks`, `color`, and `accessories` are all empty (the `_base` baselines,
  §3) — a designed cell with a null strength is a half-formed entry and fails (rev.3).

## 9. Phasing / build order

| Phase | Scope | Gate |
|---|---|---|
| **0** | Promote the preserved scratchpad scripts (§2) to `scripts/calibrate_design_axes.py`, combo recipes lifted verbatim; `matrix.json` (substrate declared, model included) + manifest schema (`rendered_at` per cell, `_base` cells expected); **adopt `calibration_snapshot_20260716/`** per the §3 reconciliation — v2 PNGs **and 0.85→0.9 strength rewrites** for the surface-axis cells, pattern cells kept at round-1, `_petout/` dropped, paths rewritten; `.gitignore` entry for `calibration_renders/`; incremental render + `--full` + `--sheet` + `--mark-reviewed`. | `--check` on the adopted manifest reports every cell *current* **after the expected day-one heal run** (`python/scales-patterned` + the stale combo cells, ~1 min GPU — so this gate needs ComfyUI up); a scratch fragment edit flips exactly its cells to *stale*; deleting a render's manifest entry flips it to *missing*; incremental run heals both. |
| **1** | `webui/design_calibration.py` (predicate + expected-matrix builder), `--check` wired to it, the guard test, the `DESIGN_CALIBRATION_GATE` knob. | Suite green on the adopted manifest; adding a dummy option to `pattern.json` turns the build red with the §5 command in the failure text; `warn` knob downgrades it. |
| **2** | Admin endpoint + badge — rides on the **shipped** `/admin/design` surface (rev.2): the endpoint mounts on `design_admin.py`'s router, the badge is a field on the Features tab's existing axis cards. | Adding an option via the admin UI shows the badge on save; running §5 clears it on refresh. |

Phases 0 and 1 ship together (the record without the reminder is a diary; the reminder
without the record has nothing to check). Phase 2 has no external dependency left — the
admin surface it rides shipped 2026-07-16 — so all three phases can land in one pass.
