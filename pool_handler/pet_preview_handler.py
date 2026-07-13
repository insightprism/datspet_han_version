"""pet_preview — shared_gpu_cpu task handler for DatsPet's design-page preview.

Sibling of pet_factory_handler.py, and installed the same way. It exists as a SEPARATE
task (spec §A.3, decision A3-a) rather than reusing pet_factory because the preview needs
different params (a reference image + strength, no full build), a different result shape
(a PNG, not a .zip), and a different timeout (~10 s redraw vs the build's ~3 min).

It wraps the reference API unchanged:
    from pet_factory import render_design_still
    render_design_still(description, reference_image, strength) -> png_bytes

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
    "version": "1",
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
            "reference_image_b64": {"type": "string"},   # base64 PNG/JPEG — the base still to redraw
            "description": {"type": "string", "maxLength": 200},
            "strength": {"type": "number", "minimum": 0.3, "maximum": 0.9},
        },
        "required": ["reference_image_b64"],
        "additionalProperties": False,
    },
    "result_kind": "bytes",   # the redrawn PNG
}


def run(params, ctx):
    from pet_factory import render_design_still

    try:
        raw = base64.b64decode(params["reference_image_b64"], validate=True)
    except (binascii.Error, ValueError) as e:
        raise ValueError(f"reference_image_b64 is not valid base64: {e}") from e

    ref = Path(ctx.result_dir) / "reference_image"
    ref.write_bytes(raw)

    ctx.progress(10.0, "redrawing your design…")
    png_bytes = render_design_still(
        params.get("description", ""),
        str(ref),
        params.get("strength", 0.85),
    )
    ctx.progress(100.0, "preview ready")

    out = Path(ctx.result_dir) / "preview.png"
    out.write_bytes(png_bytes)
    ctx.result_file(str(out))
