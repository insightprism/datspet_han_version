#!/usr/bin/env python3
"""_node_build_check — prove a pet node can actually BUILD A PET. Not a probe.

Run by `roll_pet_fleet.sh --verify-build` on each node, from that node's own checkout and
under its worker unit's environment. Prints exactly one verdict line and exits 0/1.

WHY THIS EXISTS (2026-07-26 deploy)
-----------------------------------
Arming F3 on omen-pet, the reviewer "verified" the cutout by calling `factory._remove_bg()`
directly. It failed on an 822 MB arena allocation, three times, and omen was very nearly
reported as a broken node. **The node was fine.** The probe was wrong, because the cutout's
memory conditions are CREATED BY THE PIPELINE:

    make_pet_zip:  ... generate ... -> _evict_comfy_models_for_cutout()  -> cutout
                                       ^ frees ~18 GB. Skip it and the cutout cannot fit.

That is `SPEC_GPU_MEMORY_HYGIENE` §11.4's lesson, written that same morning and then broken
twice in a day. So the rule is baked in here instead of trusted to whoever is deploying:
**a pet node is verified by a real `make_pet_zip`, never by touching the cutout directly.**

It also removes two whole classes of deploy-time papercut. This file lives in the repo that
every node already has checked out, so verifying a node needs no ssh heredoc (which broke a
run on `\\"` inside an f-string) and no ad-hoc `python /tmp/x.py` (which broke another by
leaving the repo off `sys.path`).

The check that matters is the ALPHA CHANNEL. The product is a transparent sprite, so a build
that "succeeds" with an opaque one has failed at the only thing it is for.
"""
import io
import os
import sys
import zipfile

# Default to the cheapest build that still exercises the whole pipeline: poses=None gives
# walk+idle (the REQUIRED_POSES), which is ~2 min rather than the ~8 min an 8-pose build costs.
# Every stage that can fail — base sprite, anchors, Wan loops, eviction, cutout, packing — runs
# either way; more poses buys repetition, not coverage.
ANIMAL = os.environ.get("NODE_BUILD_CHECK_ANIMAL", "black bat")


def main() -> int:
    try:
        from pet_factory import make_pet_zip
    except Exception as e:
        print(f"VERDICT FAIL import pet_factory: {type(e).__name__}: {e}")
        return 1

    try:
        breed_id, zip_bytes = make_pet_zip(ANIMAL)
    except Exception as e:
        # CutoutFailed lands here too — which is the point. Post-F2 a broken matte is a failed
        # build, so this is exactly the signal a node-level check should surface.
        print(f"VERDICT FAIL build: {type(e).__name__}: {str(e)[:180]}")
        return 1

    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
        sheet = [n for n in zf.namelist() if n.endswith("_sprite.png")][0]
        from PIL import Image
        alpha = Image.open(io.BytesIO(zf.read(sheet))).getchannel("A").getextrema()
    except Exception as e:
        print(f"VERDICT FAIL unpack: {type(e).__name__}: {e}")
        return 1

    # extrema[0] == 255 means NOTHING is transparent — the white-background failure F2 exists
    # to stop shipping. A sheet-level read is coarse (one opaque frame among many still passes);
    # `SPEC_GPU_MEMORY_HYGIENE` §1's per-frame walk is the strict version, run against a bundle.
    if alpha[0] >= 255:
        print(f"VERDICT FAIL opaque sprite (alpha={alpha}) — built, but nothing is transparent")
        return 1

    print(f"VERDICT OK breed={breed_id} alpha={alpha} real-transparency")
    return 0


if __name__ == "__main__":
    sys.exit(main())
