#!/usr/bin/env python3
"""promote_interactive — walk the staged base candidates breed by breed and
promote the ones you pick, in one sitting (SPEC_PET_DESIGNER_PLATFORM §4.5). A
local, human-driven CLI — no web server, no auth surface. It only ever COPIES a
chosen candidate to `<breed>/base.png`; you make every call.

Run from the repo root:
    python3 pet_factory/animal_catalog/promote_interactive.py

For each catalog breed with staged candidates it prints the candidate numbers +
their file paths (open them in any image viewer, or use the contact-sheet
artifact), then asks which to promote. Enter a number to promote, or press Enter
to skip that breed. At the end it offers to restore each fully-curated animal's
`themed_page` (so the landing tiles light up) and to run the guard test.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

_DIR = Path(__file__).resolve().parent
_REPO = _DIR.parent.parent
_CANDIDATES_ROOT = _DIR / "_candidates"
_CATALOG = _DIR / "catalog.json"


def _candidates(animal: str, breed: str) -> list[int]:
    cdir = _CANDIDATES_ROOT / animal / breed
    if not cdir.is_dir():
        return []
    return sorted(int(f.stem.split("_")[-1]) for f in cdir.glob("candidate_*.png"))


def _prompt(msg: str) -> str:
    try:
        return input(msg).strip()
    except (EOFError, KeyboardInterrupt):
        print("\naborted — nothing further promoted.")
        sys.exit(0)


def main() -> None:
    catalog = json.loads(_CATALOG.read_text())
    print("Interactive base promotion (SPEC §4.5). For each breed, enter a candidate")
    print("number to promote, or press Enter to skip. Ctrl-C aborts.\n")
    promoted_any = False
    curated: dict[str, bool] = {}   # animal -> every breed now has a live base?

    for a in catalog["animals"]:
        animal = a["key"]
        all_breeds_live = True
        print(f"=== {a.get('label', animal)} World ===")
        for b in a["breeds"]:
            breed = b["key"]
            live = _DIR / animal / breed / "base.png"
            nums = _candidates(animal, breed)
            live_note = " [a base.png already exists]" if live.is_file() else ""
            if not nums:
                print(f"  {b.get('label', breed)} ({animal}/{breed}): no staged candidates — skipping{live_note}")
                if not live.is_file():
                    all_breeds_live = False
                continue
            print(f"  {b.get('label', breed)} ({animal}/{breed}): candidates {', '.join(map(str, nums))}{live_note}")
            for n in nums:
                print(f"      {n}: {(_CANDIDATES_ROOT / animal / breed / f'candidate_{n}.png').relative_to(_REPO)}")
            choice = _prompt(f"    promote which for {breed}? (number / Enter to skip): ")
            if not choice:
                if not live.is_file():
                    all_breeds_live = False
                print(f"    skipped {breed}\n")
                continue
            if not choice.isdigit() or int(choice) not in nums:
                print(f"    '{choice}' is not one of {nums} — skipping {breed}\n")
                if not live.is_file():
                    all_breeds_live = False
                continue
            src = _CANDIDATES_ROOT / animal / breed / f"candidate_{choice}.png"
            live.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, live)
            promoted_any = True
            print(f"    ✓ promoted candidate {choice} -> {live.relative_to(_REPO)}\n")
        curated[animal] = all_breeds_live
        print()

    if not promoted_any:
        print("nothing promoted.")
        return

    # Offer to restore themed_page for animals whose every breed now has a base.
    to_restore = [a for a in catalog["animals"]
                  if curated.get(a["key"]) and a.get("themed_page") is None
                  and a.get("_themed_page_when_curated")]
    if to_restore:
        names = ", ".join(a.get("label", a["key"]) for a in to_restore)
        ans = _prompt(f"restore themed_page (landing tiles) for {names}? (y/N): ")
        if ans.lower() == "y":
            for a in to_restore:
                a["themed_page"] = a.pop("_themed_page_when_curated")
            # Drop the now-stale launch-gate note if every animal is curated.
            if all(curated.get(a["key"]) for a in catalog["animals"]):
                catalog.pop("_LAUNCH_GATE", None)
            _CATALOG.write_text(json.dumps(catalog, indent=2) + "\n")
            print(f"  ✓ restored themed_page for {names} (catalog.json updated)")
        else:
            print("  left themed_page as-is (tiles stay hidden until you restore them)")

    ans = _prompt("run the catalog guard test now? (Y/n): ")
    if ans.lower() != "n":
        print()
        subprocess.run([sys.executable, "-m", "pytest",
                        "pet_factory/tests/test_animal_catalog.py", "-q"], cwd=_REPO)


if __name__ == "__main__":
    main()
