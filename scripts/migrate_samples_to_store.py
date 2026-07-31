#!/usr/bin/env python3
"""migrate_samples_to_store — one-shot: file samples → Pet Store rows
(SPEC_PET_STORE §8).

Reads every `pet_factory/animal_catalog/<animal>/samples/<key>.{zip,png}` pair
and inserts a **published** store_pets row: a shipped sample is already-live,
guard-tested public content, and migrating it unpublished would open a window
where the shop replaces the sample grid with an empty shelf. The shipped .png
becomes the preview (no PIL here), the key title-cased becomes the name, and
the description starts as a one-line deterministic caption the admin polishes
afterwards (redraft is available).

Globs the directories DIRECTLY — the animal_catalog sample helpers are retired
(§8) and this script is the one reader the leftover files have. Run once per
environment, with pet_env.sh sourced so PETMAKER_OUTPUT_DIR/PETMAKER_DB_PATH
point at that environment's DB:

    source pet_env.sh && python3 scripts/migrate_samples_to_store.py

Idempotent on bundle_sha256: a sample whose bytes are already in the store is
skipped, so a re-run is a no-op. After the LAST environment has migrated, the
sample files themselves are deleted (the §8 Rev.3 deploy-checklist line).
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "webui"))
sys.path.insert(0, str(REPO_ROOT))

import db  # noqa: E402  (webui/db.py — needs the sys.path line above)
import store_validation  # noqa: E402

CATALOG_DIR = REPO_ROOT / "pet_factory" / "animal_catalog"

#: The §8 deterministic starter caption — one honest line, not AI prose.
def _starter_description(display_name: str, animal: str) -> str:
    return f"{display_name} — a ready-made {animal}, adoptable right away."


def _existing_digests() -> set[str]:
    with db._lock:
        rows = db._connect().execute(
            "SELECT bundle_sha256 FROM store_pets").fetchall()
    return {r["bundle_sha256"] for r in rows}


def migrate() -> int:
    db.init_db()
    seen = _existing_digests()
    migrated = 0
    for zip_path in sorted(CATALOG_DIR.glob("*/samples/*.zip")):
        animal = zip_path.parent.parent.name
        key = zip_path.stem
        preview_path = zip_path.with_suffix(".png")
        if not preview_path.is_file():
            print(f"SKIP {animal}/{key}: no {preview_path.name} portrait")
            continue

        bundle_zip = zip_path.read_bytes()
        digest = hashlib.sha256(bundle_zip).hexdigest()
        if digest in seen:
            print(f"ok   {animal}/{key}: already in the store (sha {digest[:12]}…)")
            continue

        # The bundle parts, read the way app._unpack_bundle does.
        with zipfile.ZipFile(zip_path) as z:
            sheet_png = next((z.read(n) for n in z.namelist()
                              if n.endswith(store_validation.SPRITE_SUFFIX)), None)
            manifest_json = z.read(store_validation.MANIFEST_MEMBER).decode("utf-8")
            package_json = (z.read("package.json").decode("utf-8")
                            if "package.json" in z.namelist() else None)

        display_name = key.title()
        breed_id = key
        if package_json:
            try:
                pkg = json.loads(package_json)
                display_name = pkg.get("display_name", display_name)
                breed_id = pkg.get("breed_id", breed_id)
            except json.JSONDecodeError:
                pass

        preview_png = preview_path.read_bytes()
        errors = store_validation.sellability_errors(
            bundle_zip=bundle_zip, preview_png=preview_png,
            display_name=display_name, animal=animal)
        if errors:
            print(f"SKIP {animal}/{key}: not sellable: {'; '.join(errors)}")
            continue

        db.insert_store_pet(
            store_id=f"smpl{digest[:8]}",   # deterministic → stable across envs
            display_name=display_name, breed_id=breed_id, animal=animal,
            description=_starter_description(display_name, animal),
            tags=[animal], created_at=time.time(), preview_png=preview_png,
            sheet_png=sheet_png, manifest_json=manifest_json,
            package_json=package_json, bundle_zip=bundle_zip,
            published=True,
        )
        seen.add(digest)
        migrated += 1
        print(f"MIGRATED {animal}/{key} -> published store pet smpl{digest[:8]}")
    print(f"done: {migrated} migrated, store now holds "
          f"{len(db.list_store_pets(published_only=False))} pets")
    return migrated


if __name__ == "__main__":
    migrate()
