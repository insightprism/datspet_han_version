#!/usr/bin/env python3
"""promote_sample — human-in-the-loop promote step for staged sample pets
(SPEC_PET_DESIGNER_PLATFORM §4.4/§4.5). After reviewing a staged sample from
generate_sample.py, a person runs THIS to copy it into the live catalog as
`<animal>/samples/<key>.{zip,png}`. The only step that touches the live catalog;
deliberately manual, like base-image promotion.

Usage
-----
    python3 pet_factory/animal_catalog/promote_sample.py dog friendlypup
    python3 pet_factory/animal_catalog/promote_sample.py --list
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

_DIR = Path(__file__).resolve().parent
_REPO = _DIR.parent.parent
_CANDIDATES_ROOT = _DIR / "_candidates"


def list_staged():
    root = _CANDIDATES_ROOT
    found = sorted(root.glob("*/samples/*.zip")) if root.is_dir() else []
    if not found:
        print("no staged samples (run generate_sample.py first)")
        return
    print("staged samples:")
    for f in found:
        animal = f.parent.parent.name
        key = f.stem
        has_png = (f.parent / f"{key}.png").is_file()
        print(f"  {animal}/{key}  (portrait: {'yes' if has_png else 'MISSING'})  ->  "
              f"promote with: promote_sample.py {animal} {key}")


def promote(animal: str, key: str):
    src_zip = _CANDIDATES_ROOT / animal / "samples" / f"{key}.zip"
    src_png = _CANDIDATES_ROOT / animal / "samples" / f"{key}.png"
    if not src_zip.is_file():
        print(f"ERROR: no such staged sample: {src_zip.relative_to(_REPO)}")
        print("run promote_sample.py --list to see what's staged")
        sys.exit(1)
    dest_dir = _DIR / animal / "samples"
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src_zip, dest_dir / f"{key}.zip")
    print(f"promoted {src_zip.relative_to(_REPO)} -> {(dest_dir / f'{key}.zip').relative_to(_REPO)}")
    if src_png.is_file():
        shutil.copyfile(src_png, dest_dir / f"{key}.png")
        print(f"promoted portrait -> {(dest_dir / f'{key}.png').relative_to(_REPO)}")
    else:
        print("WARNING: no portrait staged — the gallery tile will show a 🐾 placeholder")
    print("now run: python3 -m pytest pet_factory/tests/test_animal_catalog.py")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("animal", nargs="?")
    ap.add_argument("key", nargs="?")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()
    if args.list or not (args.animal and args.key):
        list_staged()
    else:
        promote(args.animal, args.key)
