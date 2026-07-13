#!/usr/bin/env python3
"""promote_candidate — the human-in-the-loop promote step of generate-then-curate
(SPEC_PET_DESIGNER_PLATFORM §4.5). After reviewing the staged candidates from
generate_candidates.py, a person runs THIS to copy a chosen candidate into the
live catalog as `<breed>/base.png`. This is the only step that touches the live
catalog; it is deliberately manual (curation is human judgment, §4.5).

Usage
-----
    # promote candidate 2 for dog/corgi into the live base.png:
    python3 pet_factory/animal_catalog/promote_candidate.py dog corgi 2

    # list what's staged (no promotion):
    python3 pet_factory/animal_catalog/promote_candidate.py --list

The tool refuses to promote a candidate that doesn't exist, and prints the before/
after so the promotion is auditable. It does NOT auto-run the guard test — run it
after promoting:  python3 -m pytest pet_factory/tests/test_animal_catalog.py
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
    if not _CANDIDATES_ROOT.is_dir():
        print("no staged candidates (run generate_candidates.py first)")
        return
    found = sorted(_CANDIDATES_ROOT.glob("*/*/candidate_*.png"))
    if not found:
        print("no staged candidates")
        return
    print("staged candidates:")
    for f in found:
        animal, breed = f.parent.parent.name, f.parent.name
        n = f.stem.split("_")[-1]
        live = _DIR / animal / breed / "base.png"
        marker = " (live base.png exists)" if live.is_file() else ""
        print(f"  {animal}/{breed} candidate {n}  ->  promote with: "
              f"promote_candidate.py {animal} {breed} {n}{marker}")


def promote(animal: str, breed: str, n: int):
    candidate = _CANDIDATES_ROOT / animal / breed / f"candidate_{n}.png"
    if not candidate.is_file():
        print(f"ERROR: no such candidate: {candidate.relative_to(_REPO)}")
        print("run promote_candidate.py --list to see what's staged")
        sys.exit(1)
    dest = _DIR / animal / breed / "base.png"
    dest.parent.mkdir(parents=True, exist_ok=True)
    existed = dest.is_file()
    shutil.copyfile(candidate, dest)
    print(f"promoted {candidate.relative_to(_REPO)} -> {dest.relative_to(_REPO)}"
          f" ({'replaced' if existed else 'new'})")
    print("now run: python3 -m pytest pet_factory/tests/test_animal_catalog.py")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("animal", nargs="?", help="animal key (e.g. dog)")
    ap.add_argument("breed", nargs="?", help="breed key (e.g. corgi)")
    ap.add_argument("n", nargs="?", type=int, help="candidate number to promote")
    ap.add_argument("--list", action="store_true", help="list staged candidates and exit")
    args = ap.parse_args()
    if args.list or not (args.animal and args.breed and args.n):
        list_staged()
    else:
        promote(args.animal, args.breed, args.n)
