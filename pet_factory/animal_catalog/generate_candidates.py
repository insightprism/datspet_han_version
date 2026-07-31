#!/usr/bin/env python3
"""generate_candidates — the generate-then-curate batch tool (SPEC_PET_DESIGNER_
PLATFORM §4.5). Produces CANDIDATE base stills for each catalog breed so a human
can review and promote the good ones into the live catalog. It never promotes
anything itself — curation is a human judgment call (§4.5).

Mechanics
---------
For each breed in catalog.json, submit N `pet_factory` builds to the shared pool
with a breed-accurate, from-scratch base prompt (no reference image → the pipeline
runs the Z-Image base stage exactly as `_base_prompt` intends: side profile,
facing right, plain background). Each finished bundle's idle frame is the candidate
base still. Candidates land in a STAGING dir, never in `<breed>/base.png`:

    pet_factory/animal_catalog/_candidates/<animal>/<breed>/candidate_{1..N}.png

Then a human runs promote_candidate.py to copy a chosen candidate into base.png.

Usage
-----
    # all breeds, 2 candidates each (default):
    python3 pet_factory/animal_catalog/generate_candidates.py
    # one breed, 3 candidates:
    python3 pet_factory/animal_catalog/generate_candidates.py --animal dog --breed corgi -n 3

Requires a pool app key (POOL_APP_KEY or ~/.pool/datspet_key) and a v3 fleet with
pet_factory workers. Runs OFF the live web tier — it imports pool_client directly.
Builds are ~3 min each; the tool prints progress and keeps going on a per-job error.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import zipfile
from pathlib import Path

_DIR = Path(__file__).resolve().parent
_REPO = _DIR.parent.parent
# pool_client lives in webui/ (the one pool adapter) — reuse it, don't re-implement.
sys.path.insert(0, str(_REPO / "webui"))
import pool_client  # noqa: E402

from pet_factory import prompt_templates  # noqa: E402

_CANDIDATES_ROOT = _DIR / "_candidates"


def _base_prompt(animal: str) -> str:
    """The from-scratch base-still prompt — ONE definition, in prompt_templates. This
    script used to carry its own copy ending in a hardcoded backdrop clause; after
    SPEC_MATTE_BACKDROP that would have put two different backdrops in one sentence,
    since this string is wrapped by a real build's template."""
    return prompt_templates.curation_still_prompt(animal)


def _idle_frame_from_bundle(zip_bytes: bytes) -> bytes:
    """Extract the first idle (else walk) frame from a built bundle as a PNG —
    the candidate base still.

    (This used to say "same crop math as app.extract_base_frame". That function is
    gone — it served the house-pet base door, which the designer no longer has
    (SPEC_PET_DESIGNER_FLOW §11). The crop below is now the only copy.)"""
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


def _catalog_breeds(animal_filter=None, breed_filter=None):
    catalog = json.loads((_DIR / "catalog.json").read_text())
    for a in catalog.get("animals", []):
        if animal_filter and a["key"] != animal_filter:
            continue
        for b in a.get("breeds", []):
            if breed_filter and b["key"] != breed_filter:
                continue
            # The prompt species = "<breed label> <animal label>", e.g. "Corgi Dog",
            # "Tabby Cat" — breed-accurate and unambiguous to the base prompt.
            label = b.get("label", b["key"])
            species = f"{label} {a.get('label', a['key'])}".strip().lower()
            yield a["key"], b["key"], species


def generate(animal_filter=None, breed_filter=None, n=2, timeout_s=900.0):
    breeds = list(_catalog_breeds(animal_filter, breed_filter))
    if not breeds:
        print(f"no matching breeds (animal={animal_filter}, breed={breed_filter})")
        return
    print(f"generating {n} candidate(s) for {len(breeds)} breed(s) via the pool "
          f"({pool_client._pool_url()})\n")
    staged = []
    for animal, breed, species in breeds:
        out_dir = _CANDIDATES_ROOT / animal / breed
        out_dir.mkdir(parents=True, exist_ok=True)
        prompt = _base_prompt(species)
        for i in range(1, n + 1):
            tag = f"{animal}/{breed} candidate {i}/{n}"
            print(f"[{tag}] submitting: {prompt!r}")
            try:
                def on_progress(msg, frac, _tag=tag):
                    print(f"  [{_tag}] {int(frac*100):3d}%  {msg}", flush=True)
                # No reference_image_b64 → from-scratch base build. display_name
                # keeps the bundle self-describing; poses default to walk+idle.
                zip_bytes = pool_client.run_to_result(
                    "pet_factory",
                    {"animal": prompt, "display_name": f"{species} candidate {i}"},
                    on_progress=on_progress, poll_interval=4.0, timeout_s=timeout_s)
                png = _idle_frame_from_bundle(zip_bytes)
                out = out_dir / f"candidate_{i}.png"
                out.write_bytes(png)
                staged.append(str(out.relative_to(_REPO)))
                print(f"  [{tag}] -> {out.relative_to(_REPO)} ({len(png)} bytes)\n")
            except Exception as e:
                print(f"  [{tag}] FAILED: {e}\n", flush=True)
    print("=== staged candidates (review, then promote_candidate.py) ===")
    for s in staged:
        print("  " + s)
    if not staged:
        print("  (none succeeded)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--animal", default=None, help="limit to one animal key (e.g. dog)")
    ap.add_argument("--breed", default=None, help="limit to one breed key (e.g. corgi)")
    ap.add_argument("-n", type=int, default=2, help="candidates per breed (default 2)")
    ap.add_argument("--timeout", type=float, default=900.0, help="per-build timeout seconds")
    args = ap.parse_args()
    generate(args.animal, args.breed, args.n, args.timeout)
