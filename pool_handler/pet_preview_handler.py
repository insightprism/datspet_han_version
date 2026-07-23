"""pet_preview — shared_gpu_cpu task handler for DatsPet's design-page preview.

Sibling of pet_factory_handler.py, and installed the same way. It exists as a SEPARATE
task (spec §A.3, decision A3-a) rather than reusing pet_factory because the preview needs
different params (a reference image + strength, no full build), a different result shape
(a PNG, not a .zip), and a different timeout (~10 s redraw vs the build's ~3 min).

It wraps the reference API unchanged:
    from pet_factory import render_design_still
    render_design_still(description, reference_image, strength) -> png_bytes
    render_design_still(description)                            -> png_bytes   # v2

v2 (SPEC_PET_DESIGNER_FLOW §7.5) makes `reference_image_b64` OPTIONAL, which gives this
one task both of the flow's still-rendering jobs:

    with a reference    → img2img redraw    = step 2's preview            (~10 s)
    without a reference → txt2img archetype = step 1's long-tail cache miss (~10 s)
                                              ("what does a blue jay look like")

Extended rather than split (§7.5): this task and pet_factory are deliberately separate
because they differ on params AND result AND timeout. txt2img vs img2img differ on params
only, and only by OMISSION — the weakest possible case for a split, and one that would
leave two ~95%-identical handlers to sync on every node forever. Same Z-Image model, same
resolution, same 180 s cold-start bound.

**v2 is not backward-compatible for NEW traffic**: a no-b64 submit 422s on a v1 node
(`required: ["reference_image_b64"]`). v2 ⊇ v1 for existing b64 traffic, so rollback is
safe, but both nodes must be v2 before any no-b64 traffic ships — the fleet gate, §10.1.

Contract (same as pet_factory_handler):
- run(params, ctx) runs in the worker's handler subprocess; heavy imports stay out of the pool.
- ctx.progress(pct, msg) is the pct/msg an app polls.
- ctx.result_file(path) hands back the PNG; the path must be inside ctx.result_dir.

Install onto every pet-capable node alongside pet_factory (Part B):
    pool-install-handler pet_preview_handler.py --restart <gpu worker unit>
"""
import base64
import binascii
from pathlib import Path

METADATA = {
    "task": "pet_preview",
    "version": "3",
    # SAME GPU profile as pet_factory, so the CPU-only worker can never claim a preview
    # (R3-3) — a preview redraws through the same ComfyUI img2img pipeline.
    "needs": {"gpu": 1, "vram_gb": 20, "gpu_backend": "cuda", "cpu": 2, "ram_gb": 8},
    # 180 s, not 60 (R3-3): a warm redraw is ~10 s, but the FIRST job on a cold ComfyUI
    # loads the Z-Image model and can exceed 60 s. The watchdog bound is authoritative from
    # the claiming node's advertised meta, so it must cover a cold start — while staying far
    # under the build's 900 s so a hung preview releases the GPU slot in minutes, not 15.
    "timeout_s": 180,
    "preemptible": "abort",
    "params_schema": {
        "type": "object",
        "properties": {
            # base64 PNG/JPEG — the still to redraw. OPTIONAL as of v2: omit it and
            # the task draws the archetype from `description` instead (§3.3).
            "reference_image_b64": {"type": "string"},
            # 250: the composed design string reaches ~240 chars worst case
            # (render_design_still itself imposes no length limit locally).
            "description": {"type": "string", "maxLength": 600},
            # Only meaningful alongside a reference — how far the redraw drifts from it.
            "strength": {"type": "number", "minimum": 0.3, "maximum": 0.9},
            # v3 (SPEC_UPLOAD_LIKENESS §2.2, Phase 3): cut the subject out of the
            # reference photo before the redraw, so the img2img follows the animal (or
            # person), not the background. The web tier sends this only when its
            # `upload_isolate` switch is on, and only for the upload door — step 2's
            # preview reference is already a clean sprite. Optional; default off. Must be
            # DECLARED here or a request carrying it 422s (additionalProperties:false).
            "isolate_subject": {"type": "boolean"},
        },
        # Nothing is required — a bare description draws an archetype; a reference +
        # description redraws it; isolate_subject only refines an upload redraw.
        "required": [],
        "additionalProperties": False,
    },
    "result_kind": "bytes",   # the redrawn PNG
}


def run(params, ctx):
    from pet_factory import render_design_still

    description = params.get("description", "")
    b64 = params.get("reference_image_b64")

    if b64:
        # Redraw a reference toward the design — step 2's preview.
        try:
            raw = base64.b64decode(b64, validate=True)
        except (binascii.Error, ValueError) as e:
            raise ValueError(f"reference_image_b64 is not valid base64: {e}") from e

        ref = Path(ctx.result_dir) / "reference_image"
        ref.write_bytes(raw)

        # v3: isolate the subject first when the web tier asked for it (upload door with
        # the `upload_isolate` switch on). render_design_still runs the cutout on the
        # worker's GPU and degrades to the raw photo on any failure — so a VRAM-tight node
        # falls back rather than erroring (SPEC_UPLOAD_LIKENESS §2.2).
        ctx.progress(10.0, "redrawing your design…")
        png_bytes = render_design_still(description, str(ref), params.get("strength", 0.85),
                                        isolate=bool(params.get("isolate_subject", False)))
    else:
        # Draw the archetype from scratch — step 1's long-tail branch. No strength:
        # there is no source to drift from, and passing one would be a lie.
        ctx.progress(10.0, "drawing your animal…")
        png_bytes = render_design_still(description)

    ctx.progress(100.0, "preview ready")

    out = Path(ctx.result_dir) / "preview.png"
    out.write_bytes(png_bytes)
    ctx.result_file(str(out))
