"""pet_factory — shared_gpu_cpu task handler for DatsMe pet generation.

This is DatsPet's *handler* for the shared_gpu_cpu pool (design spec §11.3). It lives HERE, in
the application repo — it is installed onto pool GPU nodes, and is never imported by or added to
the shared_gpu_cpu engine (the independence boundary). The pool provides the GPU + supervision;
this handler provides the meaning.

It wraps the reference API unchanged:
    from pet_factory import make_pet_zip
    make_pet_zip(animal, on_progress=cb(msg, fraction), breed_id=None) -> (breed_id, zip_bytes)

Install onto a pool node that has the pet pipeline (ComfyUI + models, see README):
    pool-install-handler pet_factory_handler.py --restart pool-worker-gpu0

Contract:
- run(params, ctx) executes INSIDE the worker's handler subprocess (its own process group),
  so pet_factory's heavy imports (torch/ComfyUI clients/rembg) never touch the pool process.
- ctx.progress(pct, msg) beats become the pct/msg an app polls.
- ctx.result_file(path) hands back the .zip; the path must be inside ctx.result_dir.
"""
from pathlib import Path

METADATA = {
    "task": "pet_factory",
    "version": "1",
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

    breed_id, zip_bytes = make_pet_zip(
        params["animal"],
        on_progress=on_progress,
        breed_id=params.get("breed_id"),
    )

    out = Path(ctx.result_dir) / f"{breed_id}.zip"
    out.write_bytes(zip_bytes)
    ctx.result_file(str(out))
