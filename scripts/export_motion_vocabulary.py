#!/usr/bin/env python3
"""Export the movement-class vocabulary as a generated artifact (SPEC_BUNDLE_MOTION_CONTRACT §7).

DatsPet owns this vocabulary upstream: it is derived from
`pet_factory/motion_profiles/registry.json` + each profile's `movement_class`. The
DatsMe host consumes the `classes` list to replace its hand-maintained copies
(datsme_me `web/src/pet/locomotion/vocabulary.json`, `api/routes/admin.py`) — see
`../datsme_me/docs/SPEC_DATSME_MOTION_ENGINE.md` §4.2.

We publish `classes` (the canonical strings) + `profiles` (provenance: key/level/
movement_class). We deliberately do NOT publish `aliases`: legacy/partner strings
(`parakeet_v2` -> "bird") are HOST policy for immutable bundles the factory never
emitted, so the host keeps that table itself and merges our `classes` into its own
vocabulary.json.

Run from anywhere (pet_factory is installed editable):
    python scripts/export_motion_vocabulary.py            # (re)write motion_vocabulary.json
    python scripts/export_motion_vocabulary.py --check    # exit 1 if the artifact is stale

A guard test (pet_factory/tests/test_motion_profiles.py) asserts the checked-in
artifact matches a fresh export, so drift fails the build.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from pet_factory import motion_profiles as mp

_MP_DIR = Path(mp.__file__).resolve().parent
REPO_ROOT = _MP_DIR.parents[1]
ARTIFACT = REPO_ROOT / "motion_vocabulary.json"

VERSION = 1


def build_vocabulary() -> dict:
    """The vocabulary dict `{version, classes, profiles}`, derived from the registry.

    Deterministic: profiles in registry key order, `classes` de-duplicated
    first-seen — so a fresh export is byte-stable and the drift guard is meaningful.
    """
    reg = json.loads((_MP_DIR / "registry.json").read_text())
    entries = sorted(reg["profiles"], key=lambda e: e["key"])
    classes: list[str] = []
    profiles: list[dict] = []
    for e in entries:
        prof = mp.load_motion_profile(e["key"])
        profiles.append({"key": prof.key, "level": prof.level,
                         "movement_class": prof.movement_class})
        if prof.movement_class not in classes:
            classes.append(prof.movement_class)
    return {"version": VERSION, "classes": classes, "profiles": profiles}


def _serialize(doc: dict) -> str:
    return json.dumps(doc, indent=2) + "\n"


def main(argv: list[str]) -> int:
    fresh = build_vocabulary()
    if "--check" in argv:
        if not ARTIFACT.exists():
            print(f"{ARTIFACT} does not exist — run without --check to create it", file=sys.stderr)
            return 1
        if json.loads(ARTIFACT.read_text()) != fresh:
            print(f"{ARTIFACT} is stale — run: python scripts/export_motion_vocabulary.py",
                  file=sys.stderr)
            return 1
        print(f"{ARTIFACT.name} is in sync ({len(fresh['classes'])} classes)")
        return 0
    ARTIFACT.write_text(_serialize(fresh))
    print(f"wrote {ARTIFACT} ({len(fresh['classes'])} classes, {len(fresh['profiles'])} profiles)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
