"""pet_factory — shared_gpu_cpu task handler for DatsMe pet generation.

This is DatsPet's *handler* for the shared_gpu_cpu pool (design spec §11.3). It lives HERE, in
the application repo — it is installed onto pool GPU nodes, and is never imported by or added to
the shared_gpu_cpu engine (the independence boundary). The pool provides the GPU + supervision;
this handler provides the meaning.

It wraps the reference API unchanged:
    from pet_factory import make_pet_zip
    make_pet_zip(animal, on_progress=cb(msg, fraction), breed_id=None,
                 reference_image=None, remix_strength=None, display_name=None)
        -> (breed_id, zip_bytes)

Install onto a pool node that has the pet pipeline (ComfyUI + models, see README):
    pool-install-handler pet_factory_handler.py --restart pool-worker-gpu0

Contract:
- run(params, ctx) executes INSIDE the worker's handler subprocess (its own process group),
  so pet_factory's heavy imports (torch/ComfyUI clients/rembg) never touch the pool process.
- ctx.progress(pct, msg) beats become the pct/msg an app polls.
- ctx.result_file(path) hands back the .zip; the path must be inside ctx.result_dir.

v2 (spec §A.2): the design flow is not "text → pet" — it previews an img2img redraw of a base
pet or an uploaded photo, then animates that exact still. A pool worker on another machine
cannot see the web tier's local reference-image path, so v2 carries the image bytes in the
params as `reference_image_b64` (plus `remix_strength` and `display_name`). Without this, a
preview/redesign/upload silently generates a text-only pet (Finding 1). The three new fields
are OPTIONAL, so a v1-shaped `{animal}` submit still works — which keeps the fleet cutover safe.
"""
import base64
import binascii
from pathlib import Path

METADATA = {
    "task": "pet_factory",
    "version": "2",
    # A CUDA card with enough VRAM for the Z-Image + Wan 2.2 pipeline. The dispatcher will
    # route pet jobs only to nodes that satisfy this — never the CPU-only worker.
    "needs": {"gpu": 1, "vram_gb": 20, "gpu_backend": "cuda", "cpu": 2, "ram_gb": 8},
    "timeout_s": 900,            # ~3 min typical on a 3090; 15 min is the watchdog kill bound
    "preemptible": "abort",     # not checkpointable — a preempted pet restarts from scratch
    "params_schema": {
        "type": "object",
        "properties": {
            "animal": {"type": "string", "minLength": 1, "maxLength": 60},
            "breed_id": {"type": "string"},   # optional slug override
            # v2 (§A.2) — all optional, so a v1 {animal}-only submit still validates.
            "reference_image_b64": {"type": "string"},   # base64 PNG/JPEG; the redraw/upload still
            "remix_strength": {"type": "number", "minimum": 0.3, "maximum": 0.9},
            "display_name": {"type": "string", "maxLength": 60},
        },
        "required": ["animal"],
        "additionalProperties": False,
    },
    # The DatsMe breed bundle (.zip). Large (~120-270 MB) — see design spec §4.4 on switching
    # to result_kind "url" if pet/video volume makes the dispatcher funnel bite.
    "result_kind": "bytes",
}


def run(params, ctx):
    # Imported inside run() so discovery/validation on a node without the pipeline still works
    # (the handler advertises), and only an actual job needs the heavy deps.
    from pet_factory import make_pet_zip

    def on_progress(msg, fraction):
        # reference callback is (message, fraction 0..1); the pool wants (pct 0..100, msg)
        ctx.progress(round(float(fraction) * 100, 1), str(msg))

    # v2: if the web tier sent the reference image, decode it to a temp file inside
    # this handler's own result_dir and hand make_pet_zip the path (it re-normalizes
    # via _prep_reference_image regardless, so a decoded PNG/JPEG is safe).
    reference_image = None
    b64 = params.get("reference_image_b64")
    if b64:
        try:
            raw = base64.b64decode(b64, validate=True)
        except (binascii.Error, ValueError) as e:
            raise ValueError(f"reference_image_b64 is not valid base64: {e}") from e
        reference_image = Path(ctx.result_dir) / "reference_image"
        reference_image.write_bytes(raw)

    breed_id, zip_bytes = make_pet_zip(
        params["animal"],
        on_progress=on_progress,
        breed_id=params.get("breed_id"),
        reference_image=str(reference_image) if reference_image else None,
        remix_strength=params.get("remix_strength"),
        display_name=params.get("display_name"),
    )

    out = Path(ctx.result_dir) / f"{breed_id}.zip"
    out.write_bytes(zip_bytes)
    ctx.result_file(str(out))
