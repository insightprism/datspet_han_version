"""Every `SPEC_X §N` citation resolves to a section that actually exists.

CLAUDE.md makes citations load-bearing: "code comments cite them by section…
Read the cited spec section before changing code that references one." A
citation that points at a section which no longer exists is worse than no
citation — it sends the reader somewhere confidently wrong.

WHY THIS EXISTS NOW: SPEC_PET_ARENA was split on 2026-08-03 into the athletics
contract (§2–§5, this repo — DatsPet MINTS a pet's stats) and the game (§6
onward, which moved to datsme_me with the code). 81 section citations across two
repos had to land on the right side of that cut.

The split deliberately did NOT renumber: §2–§5 kept their numbers in
SPEC_PET_ATHLETICS and §6+ kept theirs in SPEC_PET_ARENA, so the rule was purely
mechanical — major section 2-5 means athletics, anything else means the game.
That is what made 81 edits safe. This test is what proves the rule was applied
correctly, and it keeps proving it as either spec is edited.

Skips when datsme_me is not checked out beside this repo: the game's specs live
there now, and a DatsPet clone on its own should not fail for the absence of a
sibling.
"""
import os
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PEER = REPO.parent / "datsme_me"

SPECS = {
    "SPEC_PET_ATHLETICS":    REPO / "docs" / "SPEC_PET_ATHLETICS.md",
    "SPEC_PET_ARENA":        PEER / "docs" / "SPEC_PET_ARENA.md",
    "SPEC_PET_ARENA_ROOMS":  PEER / "docs" / "SPEC_PET_ARENA_ROOMS.md",
    "SPEC_PET_ARENA_LOUNGE": PEER / "docs" / "SPEC_PET_ARENA_LOUNGE.md",
    "SPEC_PET_ARENA_VENUE":  PEER / "docs" / "SPEC_PET_ARENA_VENUE.md",
    "SPEC_ARENA_MIGRATION":  PEER / "docs" / "SPEC_ARENA_MIGRATION.md",
}

# Where citations are written. Data files count: the athletics tables carry
# them, and those are exactly the files a split can strand.
SEARCH_DIRS = ["webui", "pet_factory", "web/src", "docs", "scripts"]
SUFFIXES = {".py", ".ts", ".tsx", ".json", ".md", ".sh"}

CITATION = re.compile(r"(SPEC_[A-Z_]+) §([0-9]+(?:\.[0-9]+)*)")
HEADING = re.compile(r"^#{2,4} §?([0-9]+(?:\.[0-9]+)*)", re.M)


def _sections(path: Path) -> set:
    return {m.group(1) for m in HEADING.finditer(path.read_text())}


def _iter_files():
    for d in SEARCH_DIRS:
        root = REPO / d
        if not root.is_dir():
            continue
        for p in root.rglob("*"):
            if p.suffix not in SUFFIXES:
                continue
            if "node_modules" in p.parts or ".next" in p.parts:
                continue
            # Not itself: this file DOCUMENTS the citation rules (it names
            # "SPEC_PET_ARENA §2-§5" to explain what moved), and a checker that
            # flags its own prose is a checker nobody keeps.
            if p.resolve() == Path(__file__).resolve():
                continue
            yield p


def test_every_spec_citation_resolves():
    missing_specs = [n for n, p in SPECS.items() if not p.exists()]
    if missing_specs:
        pytest.skip(f"specs not reachable (peer repo absent?): {missing_specs}")

    known = {name: _sections(path) for name, path in SPECS.items()}
    checked = 0
    broken = []
    for f in _iter_files():
        try:
            text = f.read_text()
        except (UnicodeDecodeError, OSError):
            continue
        for m in CITATION.finditer(text):
            spec, sec = m.group(1), m.group(2)
            if spec not in known:
                continue          # a spec this test does not track; not its business
            checked += 1
            # A citation resolves if the exact section exists, or its parent
            # does — "§7.4" is legitimate when the file only headings "§7".
            if sec in known[spec] or sec.split(".")[0] in known[spec]:
                continue
            broken.append(f"{f.relative_to(REPO)}: {spec} §{sec}")

    # A floor, not a target: it exists so a broken search (wrong dirs, wrong
    # suffixes, a regex typo) fails loudly instead of passing vacuously. DatsPet
    # carried 23 of these the day the split landed — the game's specs took the
    # rest with them — so 15 leaves room to delete a few without a false alarm
    # while still catching "found nothing".
    assert checked >= 15, f"only {checked} citations found — the search is probably broken"
    assert not broken, (
        "citations point at sections that do not exist in the named spec:\n  "
        + "\n  ".join(sorted(set(broken))))


def test_the_athletics_split_did_not_leave_a_stale_pointer():
    """The §2-§5 rule, asserted directly.

    A citation of SPEC_PET_ARENA §2..§5 means someone either wrote a new one
    against the pre-split numbering or reverted a repointed line. Both resolve
    "successfully" — SPEC_PET_ARENA has no §2 heading, but the parent-match
    above would not save them and the reader lands in the wrong document.
    """
    if not SPECS["SPEC_PET_ARENA"].exists():
        pytest.skip("peer repo absent")
    offenders = []
    for f in _iter_files():
        try:
            text = f.read_text()
        except (UnicodeDecodeError, OSError):
            continue
        for m in CITATION.finditer(text):
            if m.group(1) == "SPEC_PET_ARENA" and m.group(2).split(".")[0] in {"2", "3", "4", "5"}:
                offenders.append(f"{f.relative_to(REPO)}: {m.group(0)}")
    assert not offenders, (
        "these cite SPEC_PET_ARENA §2-§5, which moved to SPEC_PET_ATHLETICS:\n  "
        + "\n  ".join(sorted(set(offenders))))
