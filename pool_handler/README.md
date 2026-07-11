# pet_factory — shared_gpu_cpu pool handler

This directory holds DatsPet's **task handler** for the [`shared_gpu_cpu`](../../shared_gpu_cpu)
compute pool. It lets pet generation run on any GPU in the pool instead of one hardwired box.

**Why it lives here, not in the pool:** the pool is application-independent — it ships no
application's handler. DatsPet owns `pet_factory`; the pool only defines the *interface*
(`METADATA` + `run(params, ctx)`). This file is *installed onto* pool nodes; the pool never
imports it. (See `shared_gpu_cpu/docs/application_independence_boundary.md`.)

## What it does

`pet_factory_handler.py` wraps the reference API unchanged:

```python
from pet_factory import make_pet_zip
make_pet_zip(animal, on_progress=cb(msg, fraction), breed_id=None) -> (breed_id, zip_bytes)
```

- maps `on_progress(msg, fraction)` → `ctx.progress(pct, msg)` (an app polls these)
- returns the DatsMe `.zip` breed bundle via `ctx.result_file`
- declares `needs = {gpu:1, vram_gb:20, gpu_backend:"cuda", cpu:2, ram_gb:8}` so the pool
  routes pet jobs only to capable CUDA nodes

## Prerequisites on the serving node

A pool worker node that will run pets must have the **full pet pipeline** working locally —
this handler only orchestrates it:

- `pet_factory` importable (this repo installed into the worker's Python environment)
- **ComfyUI running** with the model weights from the repo README (Z-Image-Turbo, Wan 2.2 I2V,
  the VAEs/TEs/LoRAs), and `rembg` for background cutout
- a CUDA GPU with ≥ 20 GB VRAM

A node **without** ComfyUI can still hold the handler (it will advertise `pet_factory`), but its
jobs fail fast — so install this handler only on nodes where pets already generate.

## Install onto a pool node

From a machine with the `shared_gpu_cpu` wheel installed (provides `pool-install-handler`):

```bash
pool-install-handler pet_factory_handler.py --restart pool-worker-gpu0
# on dual-nvidia, also: --restart pool-worker-gpu1
```

That validates the handler, copies it to `~/.pool/handlers/`, and restarts the worker so it
re-advertises. Within seconds `pet_factory` appears in `GET /api/tasks` and on the node's
dashboard card. Run it once per serving node (the pool never pushes to a worker).

## Register DatsPet as a pool application

Once, from an operator machine with the admin token:

```bash
POOL_URL=https://pool.datsme.me pool-register-app datspet
# prints the app key ONCE — put it in DatsPet's backend config
```

## Point DatsPet's backend at the pool

Submit → poll → download, same UX as today:

| step | call |
|---|---|
| submit | `POST https://pool.datsme.me/api/jobs` `{"task":"pet_factory","params":{"animal":"red panda"}}` + `X-App-Key` |
| status | `GET /api/jobs/<id>` → `{status, pct, msg}` (the pet stage messages) |
| result | `GET /api/jobs/<id>/result` → the `.zip` bytes, once `status=="done"` |

Payoff: pets run on **any** eligible pool GPU (all three 3090s), a dead machine's job is
reclaimed and re-run, and the same GPUs serve other tasks when pets are idle.
