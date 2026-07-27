#!/usr/bin/env python3
"""generate_sample — stage a REAL adoptable sample pet for a catalog animal
(SPEC_PET_DESIGNER_PLATFORM §4.4/§4.5). A sample is a finished, breed-accurate
bundle a user can adopt GPU-free; like curated bases, it is authored content that
a human reviews before it goes live.

This tool builds a real multi-pose pet via the pool and stages it as:

    pet_factory/animal_catalog/_candidates/<animal>/samples/<key>.zip   (the bundle)
    pet_factory/animal_catalog/_candidates/<animal>/samples/<key>.png   (portrait)

It does NOT write into the live catalog's `<animal>/samples/` — a person runs
promote_sample.py to move a reviewed sample into place. This is why the earlier
mislabeled hedgehog-as-dog sample was removed outright: a sample must be a real,
correctly-labeled pet of that animal, staged and reviewed, never a relabel.

Usage
-----
    python3 pet_factory/animal_catalog/generate_sample.py --animal dog --breed corgi --key friendlypup
    # poses default to walk+idle+run+sit (a lively showcase); override with --poses.
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import zipfile
from pathlib import Path

_DIR = Path(__file__).resolve().parent
_REPO = _DIR.parent.parent
sys.path.insert(0, str(_REPO / "webui"))
import pool_client  # noqa: E402

from pet_factory import prompt_templates  # noqa: E402

_CANDIDATES_ROOT = _DIR / "_candidates"


def _portrait_from_bundle(zip_bytes: bytes) -> bytes:
    from PIL import Image
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        sheet_name = next(n for n in z.namelist() if n.endswith("_sprite.png"))
        manifest = json.loads(z.read("manifest.json").decode())
        sheet = Image.open(io.BytesIO(z.read(sheet_name)))
    anims = manifest.get("animations", {})
    frames = (anims.get("idle") or anims.get("walk") or {}).get("frames") or [0]
    idx = frames[0]
    cols = manifest.get("columns", 8)
    fw = manifest.get("frame_width", 256)
    fh = manifest.get("frame_height", 256)
    cell = sheet.crop(((idx % cols) * fw, (idx // cols) * fh,
                       (idx % cols + 1) * fw, (idx // cols + 1) * fh))
    buf = io.BytesIO()
    cell.save(buf, "PNG")
    return buf.getvalue()


def generate_sample(animal, breed, key, poses, motion_profile, timeout_s=900.0):
    catalog = json.loads((_DIR / "catalog.json").read_text())
    a = next((x for x in catalog["animals"] if x["key"] == animal), None)
    if a is None:
        print(f"unknown animal {animal!r}"); sys.exit(1)
    b = next((x for x in a["breeds"] if x["key"] == breed), None)
    if b is None:
        print(f"unknown breed {animal}/{breed!r}"); sys.exit(1)
    species = f"{b.get('label', breed)} {a.get('label', animal)}".lower()
    # ONE definition of the curation sentence (prompt_templates), shared with
    # generate_candidates.py. It carries no background clause: this string is passed as the
    # `animal` of a real build, whose template supplies the backdrop (SPEC_MATTE_BACKDROP).
    prompt = prompt_templates.curation_still_prompt(species)
    # Pin the catalog motion profile (the curated path, §4.2).
    profile = motion_profile or b.get("motion_profile") or a.get("motion_profile")
    poses_pkg = {p: True for p in poses}

    print(f"building sample {animal}/{key}: {prompt!r}\n  poses={poses} profile={profile}")

    def on_progress(msg, frac):
        print(f"  {int(frac*100):3d}%  {msg}", flush=True)

    params = {"animal": prompt, "display_name": f"{b.get('label', breed)}",
              "poses": poses_pkg}
    if profile:
        params["motion_profile"] = profile
    zip_bytes = pool_client.run_to_result(
        "pet_factory", params, on_progress=on_progress, poll_interval=4.0, timeout_s=timeout_s)

    out_dir = _CANDIDATES_ROOT / animal / "samples"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{key}.zip").write_bytes(zip_bytes)
    (out_dir / f"{key}.png").write_bytes(_portrait_from_bundle(zip_bytes))
    print(f"\nstaged sample: {(out_dir / f'{key}.zip').relative_to(_REPO)} "
          f"({len(zip_bytes)} bytes) + portrait")
    print("review, then promote with promote_sample.py")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--animal", required=True)
    ap.add_argument("--breed", required=True)
    ap.add_argument("--key", required=True, help="sample key (alphanumeric — becomes the URL/path segment)")
    ap.add_argument("--poses", default="walk,idle,run,sit",
                    help="comma-separated poses to build (default walk,idle,run,sit)")
    ap.add_argument("--motion-profile", default=None, help="override the pinned profile key")
    ap.add_argument("--timeout", type=float, default=900.0)
    args = ap.parse_args()
    if not args.key.isalnum():
        print("--key must be alphanumeric (it becomes a URL/path segment)"); sys.exit(1)
    poses = [p.strip() for p in args.poses.split(",") if p.strip()]
    generate_sample(args.animal, args.breed, args.key, poses, args.motion_profile, args.timeout)
