#!/usr/bin/env python3
"""calibrate_design_axes — the re-runnable design-axis calibration pass
(SPEC_PET_DESIGN_AXES_CALIBRATION §2).

Promoted from the Phase 3 scratchpad scripts (preserved at
calibration_snapshot_20260716/calibrate_axes.py). Same production path: webui's
compose_design for the prompt, pet_factory.render_design_still for the pixels —
and the strength clamp is NOT re-implemented here: it comes from
design_calibration.effective_strength, the same function the freshness predicate
uses, so a rendered cell and a checked cell never disagree (§0.1 / rev.4).

Modes:
  (default) render   incremental — render missing + stale cells, skip current
  --check            CPU-only verdict table; exit 1 if any cell isn't current
  --full             delete every render + manifest cell, then render all
  --sheet            build one contact-sheet PNG per animal from current renders
  --mark-reviewed    stamp the manifest header after eyeballing the sheets

Render modes need ComfyUI up on PET_FACTORY_COMFY_URL (source pet_env.sh first),
and refuse to run when the live model disagrees with matrix.json's declaration.

Run:
  source pet_env.sh
  .venv/bin/python scripts/calibrate_design_axes.py --check
  .venv/bin/python scripts/calibrate_design_axes.py            # heal missing/stale
  .venv/bin/python scripts/calibrate_design_axes.py --sheet
  .venv/bin/python scripts/calibrate_design_axes.py --mark-reviewed "notes"
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
for p in (str(REPO / "webui"), str(REPO)):
    if p not in sys.path:
        sys.path.insert(0, p)

import design_calibration as dc  # noqa: E402  (the one knower — §2)
from pet_factory import animal_catalog as animal_catalog_mod  # noqa: E402

_RENDERS_DIR = REPO / "calibration_renders"


def _utc_now_iso() -> str:
    # ISO-8601 UTC with the Z suffix (§3, matching datsme_integration._utc_now_iso).
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_manifest(manifest: dict) -> None:
    dc._MANIFEST_FILE.write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# --check (CPU-only)
# ---------------------------------------------------------------------------
def cmd_check() -> int:
    result = dc.check()
    order = {"stale": 0, "missing": 1, "current": 2}
    cells = sorted(result["cells"], key=lambda c: (order[c["verdict"]], c["animal"], c["cell"]))
    n_bad = sum(1 for c in cells if c["verdict"] != "current")
    for c in cells:
        if c["verdict"] == "current":
            continue
        reason = f" — {c['reason']}" if c["reason"] else ""
        print(f"  {c['verdict'].upper():8} {c['animal']}/{c['cell']}{reason}")
    print()
    if n_bad:
        print(f"{n_bad} cell(s) not current. Heal them with:")
        print("    source pet_env.sh && .venv/bin/python scripts/calibrate_design_axes.py")
    else:
        print(f"all {len(cells)} cells current.")
    stamp = result["reviewed"]
    if not stamp:
        print("NOT REVIEWED — after healing, eyeball the sheets and run --mark-reviewed.")
    elif result["unreviewed_render_count"]:
        print(f"{result['unreviewed_render_count']} cell(s) rendered since the last review "
              f"({stamp.get('at')}). Re-review and run --mark-reviewed.")
    return 1 if n_bad else 0


# ---------------------------------------------------------------------------
# render (default) + --full
# ---------------------------------------------------------------------------
def _require_matching_model() -> None:
    """Refuse to render when the live model disagrees with matrix.json's
    declaration (§0.3) — rendering against a different substrate would silently
    poison the record. Reading factory.ZIMAGE_UNET drags in the ML stack; fine,
    render modes run on the GPU dev box."""
    from pet_factory import factory
    declared = dc.load_matrix()["substrate"]["zimage_unet"]
    if factory.ZIMAGE_UNET != declared:
        sys.exit(f"live model {factory.ZIMAGE_UNET!r} != matrix.json declaration "
                 f"{declared!r} — a model swap is a --full substrate change; edit "
                 f"matrix.json's zimage_unet deliberately, then re-render everything.")


def _base_png_path(animal: str) -> Path:
    return _RENDERS_DIR / animal / "_base.png"


def _render_base(exp: dict, seed: int):
    """The undesigned baseline: a catalog copy if declared, else a txt2img of the
    species. Returns (description, strength=None) — nothing composed."""
    from pet_factory import render_design_still
    dest = _base_png_path(exp["animal"])
    dest.parent.mkdir(parents=True, exist_ok=True)
    base = exp.get("base")
    if base and base.startswith("catalog:"):
        _, ref = base.split(":", 1)
        ca, cb = ref.split("/", 1)
        src = animal_catalog_mod.base_image_path(ca, cb)
        if src is None:
            sys.exit(f"catalog base {ref!r} not found for {exp['animal']}/_base")
        shutil.copyfile(src, dest)
    else:
        dest.write_bytes(render_design_still(exp["species"], seed=seed))
    return exp["species"], None


def _render_designed(exp: dict, seed: int):
    """An option/combo cell: img2img redraw off the animal's _base at the cell's
    composed strength. Returns (description, strength)."""
    import app
    from pet_factory import render_design_still
    base_png = _base_png_path(exp["animal"])
    if not base_png.is_file():
        # The base is the reference every design redraws; render it first.
        _render_base(exp, seed)
    description, _, _ = app.compose_design(
        exp["species"], exp["color"], list(exp["accessories"]), exp["picks"], "")
    strength = dc.effective_strength(exp["picks"], exp["color"], exp["species"])
    dest = _RENDERS_DIR / exp["animal"] / f"{exp['cell']}.png"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(render_design_still(description, reference_image=base_png,
                                         strength=strength, seed=seed))
    return description, strength


def cmd_render(full: bool) -> int:
    _require_matching_model()
    matrix = dc.load_matrix()
    seed = matrix["substrate"]["seed"]

    if full:
        if _RENDERS_DIR.exists():
            shutil.rmtree(_RENDERS_DIR)
        manifest = _fresh_manifest(matrix)
    else:
        manifest = dc.load_manifest()

    verdicts = {(c["animal"], c["cell"]): c for c in dc.check(matrix, manifest)["cells"]}
    cells_by_key = {(c["animal"], c["cell"]): c for c in manifest["cells"]}

    # _base cells first — every designed cell redraws off its animal's base.
    expected = dc.expected_cells(matrix)
    expected.sort(key=lambda e: (e["animal"], 0 if e["is_base"] else 1))

    n = 0
    for exp in expected:
        key = (exp["animal"], exp["cell"])
        if verdicts.get(key, {}).get("verdict") == "current":
            continue
        if exp["is_base"]:
            desc, strength = _render_base(exp, seed)
        else:
            desc, strength = _render_designed(exp, seed)
        cells_by_key[key] = {
            "animal": exp["animal"], "cell": exp["cell"],
            "description": desc, "strength": strength,
            "picks": exp["picks"], "color": exp["color"],
            "accessories": exp["accessories"], "extra": "",
            "file": f"calibration_renders/{exp['animal']}/{exp['cell']}.png",
            "rendered_at": _utc_now_iso(),
        }
        n += 1
        print(f"  rendered {exp['animal']}/{exp['cell']}  s={strength}  «{desc}»")

    manifest["cells"] = sorted(cells_by_key.values(), key=lambda c: (c["animal"], c["cell"]))
    manifest["substrate"] = matrix["substrate"]
    _write_manifest(manifest)
    print(f"\nrendered {n} cell(s); manifest updated.")
    return 0


def _fresh_manifest(matrix: dict) -> dict:
    return {"substrate": matrix["substrate"], "reviewed": None, "cells": []}


# ---------------------------------------------------------------------------
# --sheet
# ---------------------------------------------------------------------------
def cmd_sheet() -> int:
    from PIL import Image
    manifest = dc.load_manifest()
    by_animal: dict[str, list[dict]] = {}
    for c in manifest["cells"]:
        by_animal.setdefault(c["animal"], []).append(c)
    out_dir = _RENDERS_DIR / "_sheets"
    out_dir.mkdir(parents=True, exist_ok=True)
    thumb, cols, pad = 200, 5, 10
    for animal, cells in by_animal.items():
        cells = sorted(cells, key=lambda c: (c["cell"] != "_base", c["cell"]))
        rows = (len(cells) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * (thumb + pad) + pad, rows * (thumb + pad) + pad),
                          (24, 24, 27))
        for i, c in enumerate(cells):
            src = REPO / c["file"]
            if not src.is_file():
                continue
            im = Image.open(src).convert("RGB")
            im.thumbnail((thumb, thumb), Image.LANCZOS)
            x = pad + (i % cols) * (thumb + pad)
            y = pad + (i // cols) * (thumb + pad)
            sheet.paste(im, (x, y))
        dest = out_dir / f"{animal}.png"
        sheet.save(dest)
        print(f"  {dest}  ({len(cells)} cells)")
    return 0


# ---------------------------------------------------------------------------
# --mark-reviewed
# ---------------------------------------------------------------------------
def cmd_mark_reviewed(notes: str) -> int:
    result = dc.check()
    if not result["all_current"]:
        sys.exit("refusing to mark reviewed while cells are missing/stale — run "
                 "--check, heal, then review the sheets first.")
    manifest = dc.load_manifest()
    manifest["reviewed"] = {"at": _utc_now_iso(), "notes": notes or ""}
    _write_manifest(manifest)
    print(f"marked reviewed at {manifest['reviewed']['at']}.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Design-axis calibration pass.")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true", help="CPU-only verdict table; exit 1 if not all current")
    g.add_argument("--full", action="store_true", help="delete all renders + re-render (substrate change)")
    g.add_argument("--sheet", action="store_true", help="build a contact sheet per animal")
    g.add_argument("--mark-reviewed", nargs="?", const="", metavar="NOTES",
                   help="stamp the manifest header as reviewed")
    args = ap.parse_args()

    if args.check:
        return cmd_check()
    if args.sheet:
        return cmd_sheet()
    if args.mark_reviewed is not None:
        return cmd_mark_reviewed(args.mark_reviewed)
    return cmd_render(full=args.full)


if __name__ == "__main__":
    raise SystemExit(main())
