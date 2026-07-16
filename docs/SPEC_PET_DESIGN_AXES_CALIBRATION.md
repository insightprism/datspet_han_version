# SPEC — Design-Axes Recalibration (the re-runnable pass, and the reminder that tells you when)

**Status:** proposed, rev.1 (2026-07-16)
**Extends:** `SPEC_PET_DESIGN_AXES` §8 Phase 3 (the one-time calibration pass) — this spec makes
that pass a permanent, incremental, self-reminding tool instead of a one-shot script.
**Integrates with:** `SPEC_PET_DESIGN_AXES_ADMIN` (proposed) — §6 gives the admin surface one
endpoint + one badge so a look-owner edit surfaces its own recalibration need.

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

3. **The matrix is data, derived from the registry.** Surfaces come from
   `design_axes.known_surfaces()`; a small `matrix.json` maps each surface to its
   representative animal (tabby → fur, blue jay → feathers, python → scales) plus the
   fixed unknown-surface probe (the clockwork octopus). **A surface with no representative
   fails the check** — the half-formed-entry rule from `registry.json`, applied to
   calibration. That is the "new surface class" reminder, mechanically.

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
| **Substrate change** — seed, `ZIMAGE_UNET`, base strength, `compose_design` ordering | header mismatch (or mass description drift) → **everything stale** | full matrix (~13 min GPU) + full human re-review |
| New **animal or breed** on an existing surface | **nothing** — axes are calibrated per surface, not per animal; a corgi is a catalog tag | zero |
| Features that never reach the composed prompt | **nothing** | zero |

---

## 2. The tool — `scripts/calibrate_design_axes.py`

Promoted from the Phase 3 scratchpad script (same production path: `webui`'s
`compose_design` for the prompt, `pet_factory.render_design_still` for the pixels, the app's
strength clamp replicated). Modes:

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

The staleness predicate and expected-matrix builder are **importable pure functions in
`webui/design_calibration.py`** (CPU-only; imports `app.compose_design` +
`pet_factory.design_axes`, never the GPU path). The CLI, the guard test, and the admin
endpoint (§6) all call these same two functions — one knower, three surfaces.

## 3. The data

- **`pet_factory/design_axes/calibration/matrix.json`** (committed) — the matrix as data:
  ```json
  {
    "substrate": { "seed": 20260716, "base_strength": 0.85 },
    "representatives": {
      "fur":      { "key": "tabby",   "species": "tabby",  "base": "catalog:cat/tabby" },
      "feathers": { "key": "bluejay", "species": "blue jay" },
      "scales":   { "key": "python",  "species": "python" }
    },
    "unknown_probe": { "key": "unknown", "species": "a clockwork octopus" },
    "combos": ["color_only", "stack", "stack_strong"]
  }
  ```
  The seed lives here (data), not in code — changing it is a deliberate substrate change
  that stales the world, by design. The §11.6 combo recipes (purple + wizard hat + the
  first surface pick; `stack_strong` adds `body: fat`) stay in the tool — they are the
  test procedure, one file with one reason to change.
- **`pet_factory/design_axes/calibration/manifest.json`** (committed) — the record:
  substrate header (seed, base strength, `ZIMAGE_UNET` as observed at render time),
  `reviewed` stamp, and one entry per cell: `{animal, cell, description, strength, picks,
  color, accessories, file}`. Small (tens of KB) — this is what CI diffs against.
- **Renders** — `calibration_renders/<animal>/<cell>.png` at repo root, **gitignored**
  (~45 MB of PNGs; regenerable at the fixed seed). The manifest, not the pixels, is the
  durable record.
- These live in a **subdirectory** of `design_axes/` precisely so the existing
  axis-file ↔ registry-entry pairing test (which pairs top-level `*.json`) is untouched —
  no new exemption list entry.
- **Adopt, don't re-burn:** Phase 0 seeds `manifest.json` and `calibration_renders/` from
  the 2026-07-16 Phase 3 run currently sitting in an **ephemeral session scratchpad**
  (`/tmp/claude-…/scratchpad/calibration/`) — that output is lost on reboot; adopting it
  is the first task, not a re-render.

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

## 6. Admin-surface integration (ships with `SPEC_PET_DESIGN_AXES_ADMIN`, not before)

- **`GET /api/admin/design-axes/calibration-status`** — returns the §2 predicate's output
  (per-cell verdicts + review stamp), admin-gated like the rest of that surface. It calls
  `webui/design_calibration.py`; no new logic.
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
  `known_surfaces()` surface + unknown probe appears in the expected matrix; a surface
  without a representative raises with the add-a-representative message.
- **Freshness gate:** the §4 guard test itself (missing/stale ⇒ fail, `warn` knob honored).
- **Purity:** `webui/design_calibration.py` imports no GPU/ComfyUI path (extends the
  existing GPU-less posture guard).
- **Manifest schema:** header requires seed + base strength; every cell entry carries
  description + strength (the two staleness inputs) — a cell without them fails, so the
  predicate can never silently skip one.

## 9. Phasing / build order

| Phase | Scope | Gate |
|---|---|---|
| **0** | Promote the scratchpad script to `scripts/calibrate_design_axes.py`; `matrix.json` + manifest schema; **adopt the 2026-07-16 run's output** into `manifest.json` + `calibration_renders/` before it evaporates; incremental render + `--full` + `--sheet` + `--mark-reviewed`. | `--check` on the adopted manifest reports every cell *current*; a scratch fragment edit flips exactly its cells to *stale*; deleting a render's manifest entry flips it to *missing*; incremental run heals both. |
| **1** | `webui/design_calibration.py` (predicate + expected-matrix builder), `--check` wired to it, the guard test, the `DESIGN_CALIBRATION_GATE` knob. | Suite green on the adopted manifest; adding a dummy option to `pattern.json` turns the build red with the §5 command in the failure text; `warn` knob downgrades it. |
| **2** | Admin endpoint + badge — lands **inside** the `SPEC_PET_DESIGN_AXES_ADMIN` implementation as one of its list-view fields. | Adding an option via the admin UI shows the badge on save; running §5 clears it on refresh. |

Phases 0 and 1 ship together (the record without the reminder is a diary; the reminder
without the record has nothing to check). Phase 2 rides the admin spec's own schedule.
