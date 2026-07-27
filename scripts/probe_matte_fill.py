#!/usr/bin/env python3
"""probe_matte_fill — what the hole fill did to a shipped bundle (SPEC_MATTE_REPAIR_ORDER §1).

    .venv/bin/python scripts/probe_matte_fill.py <bundle.zip> [more.zip ...]

Prints the §1 per-pose table: filled %, hard-zero px, glaring %. Reads a bundle and
nothing else, so it runs on any .zip on the box — a build's output, a curated sample, or
the .zip the Motion Lab's pack stage writes (§12.2), which is the point of the Lab
writing one at all: ONE instrument, both surfaces.

THE ARITHMETIC IS NOT HERE. `pet_factory.factory.matte_fill_damage` owns it, and this
script is its first caller (§6 step 0). A metric written inside scripts/ would be
unreachable from `webui/motion_lab.py`, which needs the same numbers under the Lab's
packed tile — and a Lab number that can disagree with a probe number is worse than no
number at all.

**Reading it.** `hard-zero` is the one that decides — but read the PER FRAME column, not
the raw count. Opaque pure black is arithmetically impossible from a *matte* (§0.1), so a
large count is the defect; a handful of pixels per frame is the sprite's own ink (an eye
pupil, a nose), which the count cannot distinguish once the repair moves off the resampled
cell. Measured either side of F1 on the same 16 frames: 9,831 px/frame vs 3.3.

`filled` is NOT a defect on its own — the otter bundle had 23% of its subject hole-filled
and shipped clean, because soft holes only dim a pixel slightly (§1.1). And POST-F1 it is
not even a fill count: the `alpha == 255` signature that separated filled pixels from
genuine foreground was a property of the buggy path (§7). Do not read a low `filled` as
success and do not read a high one as damage — F3's per-pose WARNING is what tells you the
repair still runs, and the per-frame column is what tells you whether it mattered.
"""
import io
import json
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from PIL import Image                                          # noqa: E402

from pet_factory import factory                                # noqa: E402


def _sheet_and_manifest(bundle: Path):
    with zipfile.ZipFile(bundle) as z:
        sheet_name = next(n for n in z.namelist() if n.endswith("_sprite.png"))
        manifest = json.loads(z.read("manifest.json"))
        return Image.open(io.BytesIO(z.read(sheet_name))).convert("RGBA"), manifest


def _pose_cells(sheet: Image.Image, manifest: dict, frames: list) -> Image.Image:
    """The cells of ONE animation, laid out in a strip — so a per-pose number is measured
    over that pose's pixels only. `idle` being 41% damaged while the bundle averages 12%
    is the kind of thing a sheet-wide number hides (§1's snow leopard row)."""
    cols = manifest.get("columns", 8)
    fw = manifest.get("frame_width", 256)
    fh = manifest.get("frame_height", 256)
    strip = Image.new("RGBA", (fw * max(1, len(frames)), fh), (0, 0, 0, 0))
    for i, idx in enumerate(frames):
        cell = sheet.crop(((idx % cols) * fw, (idx // cols) * fh,
                           (idx % cols) * fw + fw, (idx // cols) * fh + fh))
        strip.paste(cell, (i * fw, 0))
    return strip


def probe(bundle: Path) -> int:
    """Print one bundle's table. Returns its hard-zero px PER FRAME, which is what the
    verdict is read off — see `factory.MATTE_DAMAGE_PX_PER_FRAME` for why a raw count
    stopped being a usable gate once the repair moved onto the matte."""
    sheet, manifest = _sheet_and_manifest(bundle)
    whole = factory.matte_fill_damage(sheet)
    total_frames = sum(len(a.get("frames") or []) for a in (manifest.get("animations") or {}).values())
    print(f"\n{bundle}")
    print(f"  {'pose':<12} {'filled':>8} {'hard-zero':>12} {'per frame':>10} {'glaring':>9}")
    for pose, anim in sorted((manifest.get("animations") or {}).items()):
        frames = anim.get("frames") or []
        if not frames:
            continue
        d = factory.matte_fill_damage(_pose_cells(sheet, manifest, frames))
        per_frame = d.hard_zero_px / len(frames)
        flag = "  ← DAMAGED" if per_frame > factory.MATTE_DAMAGE_PX_PER_FRAME else ""
        print(f"  {pose:<12} {d.filled_pct:>7.1%} {d.hard_zero_px:>12,} {per_frame:>10.1f} "
              f"{d.glaring_pct:>8.1%}{flag}")
    per_frame = whole.hard_zero_px / max(1, total_frames)
    print(f"  {'BUNDLE':<12} {whole.filled_pct:>7.1%} {whole.hard_zero_px:>12,} {per_frame:>10.1f} "
          f"{whole.glaring_pct:>8.1%}   (pet's own median luma {whole.intact_luma})")
    return per_frame


def main(argv: list) -> int:
    if not argv:
        print(__doc__.strip().splitlines()[2].strip())
        return 2
    damaged = [str(b) for b in argv
               if probe(Path(b)) > factory.MATTE_DAMAGE_PX_PER_FRAME]
    print()
    if damaged:
        print(f"DAMAGED: {len(damaged)} of {len(argv)} bundle(s) carry opaque black fill")
    else:
        print(f"clean: no hard-zero fill in {len(argv)} bundle(s)")
    # Exit 0 either way: this is an instrument, not a gate. A CI gate that failed on the
    # KNOWN-damaged baselines (which §7 requires stay damaged) would be unrunnable.
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
