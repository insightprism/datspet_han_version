#!/usr/bin/env python3
"""probe_cutout_arena — the re-runnable sweep behind SPEC_GPU_MEMORY_HYGIENE §2.6.

`_CUTOUT_GPU_MEM_LIMIT_BYTES` and `_CUTOUT_ARENA_STRATEGY` are not chosen values, they are
measured ones, and §2.6's table is the only justification either has. A table nobody can re-run
is exactly the unfalsifiable claim that spec exists to stop accepting — hence this file (§11.6).

Re-run it when: the cutout model changes, onnxruntime or rembg is upgraded, the guard test's
band is questioned, or a new GPU joins the fleet.

    # the sweep that produced §2.6 (needs a GPU with ~16 GB free)
    source pet_env.sh && python3 scripts/probe_cutout_arena.py --sweep

    # just check today's shipped constants, through the real factory path
    source pet_env.sh && python3 scripts/probe_cutout_arena.py --shipped

Two things the first version of this probe got wrong, preserved here so a re-run cannot repeat
them:

  * **Run at least 3 frames.** The arena's high-water lands on the SECOND inference, not the
    first (6426 MiB then 14618 MiB, then flat). A one-frame probe measures 6.4 GB and concludes
    there is nothing to fix — which is, on the evidence, exactly how the "~6.4 GB" figure in
    factory.py's original comment came about.
  * **Measure THIS PROCESS, not the device.** `nvidia-smi --query-gpu=memory.used` includes
    ComfyUI's ~17.8 GB and anything else sharing the card, so a device-level reading says
    nothing about the cutout. Match on our own pid.

`--device` selects a card via CUDA_VISIBLE_DEVICES so the sweep can run on an idle GPU while
ComfyUI keeps the other. Note that under that mask the provider's `device_id: 0` IS the selected
physical card; in production `_CUTOUT_DEVICE_ID = 0` means physical cuda:0.
"""
from __future__ import annotations

import argparse
import gc
import os
import subprocess
import sys
import time

MIB = 1024 * 1024
GIB = 1024 * MIB

# The Wan loop output size (factory._loop_wf's width/height) — the real frame the cutout sees.
# Peak is input-size-independent (rembg normalizes to birefnet's 1024^2 graph; 256px and 704px
# measured identical), so this is about fidelity to production, not about the number.
FRAME_PX = 704
FRAMES = 4                    # >= 3; see the module docstring

# The §2.6 sweep. Ordered so the two interesting boundaries are obvious in the output: the
# failure floor between 4096 and 6144, and the growth cliff between 10240 and 12288.
SWEEP = [
    (None, "kNextPowerOfTwo"),      # today's pre-F1 default: expect ~14618 MiB
    (None, "kSameAsRequested"),     # strategy alone, uncapped: expect ~11408 MiB
    (4096, "kNextPowerOfTwo"),      # expect FAIL
    (6144, "kNextPowerOfTwo"),
    (8192, "kNextPowerOfTwo"),      # the shipped cap
    (10240, "kNextPowerOfTwo"),
    (12288, "kNextPowerOfTwo"),     # expect the cliff: benefit gone
    (16384, "kNextPowerOfTwo"),     # expect ~uncapped
    (6144, "kSameAsRequested"),     # expect FAIL — why kNextPowerOfTwo is the shipped strategy
    (8192, "kSameAsRequested"),
]


def own_vram_mib() -> int:
    """VRAM held by THIS process, in MiB. 0 if we hold none (or nvidia-smi is unavailable)."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-compute-apps=pid,used_memory", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return 0
    for line in out.strip().splitlines():
        pid, used = (part.strip() for part in line.split(","))
        if int(pid) == os.getpid():
            return int(used)
    return 0


def _subject_frame():
    """A frame with a real subject on a light ground — birefnet on a flat fill is not a
    representative matte."""
    from PIL import Image
    img = Image.new("RGB", (FRAME_PX, FRAME_PX), (240, 240, 240))
    for x in range(FRAME_PX // 4, FRAME_PX * 3 // 4):
        for y in range(FRAME_PX // 4, FRAME_PX * 3 // 4):
            img.putpixel((x, y), (180, 90, 40))
    return img


def measure(cap_mib, strategy, frames=FRAMES):
    """Build one session at (cap, strategy), run `frames` mattes, return (ok, peak_mib, note)."""
    import onnxruntime as ort
    ort.preload_dlls()
    from rembg import new_session, remove

    options = {"device_id": 0, "arena_extend_strategy": strategy}
    if cap_mib is not None:
        options["gpu_mem_limit"] = cap_mib * MIB
    session = new_session("birefnet-general-lite",
                          providers=[("CUDAExecutionProvider", options), "CPUExecutionProvider"])

    if "CUDAExecutionProvider" not in session.inner_session.get_providers():
        return False, 0, "CUDA provider did not load — fix the CUDA libs before trusting anything"

    img, peak = _subject_frame(), 0
    try:
        for _ in range(frames):
            out = remove(img, session=session)
            peak = max(peak, own_vram_mib())
        lo, hi = out.convert("RGBA").getchannel("A").getextrema()
        note = "matte ok" if lo == 0 and hi == 255 else f"SUSPECT alpha extrema ({lo}, {hi})"
        return True, peak, note
    except Exception as e:
        # An over-tight cap surfaces here, as an ORT arena allocation failure. In the build this
        # is what F2 turns into CutoutFailed.
        return False, 0, f"{type(e).__name__}: {str(e)[:120]}"
    finally:
        del session
        gc.collect()
        time.sleep(1)


def run_sweep():
    print(f"{'cap':>10}  {'strategy':<18} {'result':<8} {'peak':>10}   note")
    print("-" * 88)
    for cap_mib, strategy in SWEEP:
        ok, peak, note = measure(cap_mib, strategy)
        cap = "none" if cap_mib is None else f"{cap_mib} MiB"
        print(f"{cap:>10}  {strategy:<18} {'ok' if ok else 'FAIL':<8} "
              f"{(str(peak) + ' MiB') if ok else '—':>10}   {note}")
    print("\nExpected shape (SPEC_GPU_MEMORY_HYGIENE §2.6): FAIL at 4096; a FLAT ~6426 MiB across "
          "6144-10240;\nthen the cliff — 12288 jumps back to ~12570 and 16384 to ~14620. If the "
          "flat band has moved,\nthe guard test's bounds and the shipped cap both need revisiting.")


def run_shipped():
    """Measure the constants as actually shipped, through the real factory path — the managed
    session, the real fail-fast, the real _remove_bg. This is §2.6 row 17."""
    from pet_factory import factory

    print(f"shipped constants: cap={factory._CUTOUT_GPU_MEM_LIMIT_BYTES // MIB} MiB  "
          f"strategy={factory._CUTOUT_ARENA_STRATEGY}  device_id={factory._CUTOUT_DEVICE_ID}")
    session = factory._rembg()
    options = session.inner_session.get_provider_options()["CUDAExecutionProvider"]
    print(f"ORT read-back:     gpu_mem_limit={options['gpu_mem_limit']}  "
          f"strategy={options['arena_extend_strategy']}  device_id={options['device_id']}")
    print(f"get_providers():   {session.inner_session.get_providers()}  <- fail-fast still armed")
    del session       # hold NO reference, or release() below cannot collect the session

    img, peak = _subject_frame(), 0
    for i in range(FRAMES):
        started = time.time()
        out = factory._remove_bg(img)
        peak = max(peak, own_vram_mib())
        print(f"  frame {i}: {time.time() - started:5.2f}s  own={own_vram_mib()} MiB  "
              f"alpha={out.convert('RGBA').getchannel('A').getextrema()}")

    factory._CUTOUT.release()
    time.sleep(2)
    print(f"\npeak={peak} MiB (uncapped baseline was 14618 MiB); "
          f"after release(): {own_vram_mib()} MiB")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--sweep", action="store_true", help="the full §2.6 cap/strategy sweep")
    mode.add_argument("--shipped", action="store_true",
                      help="measure today's constants through the real factory path")
    ap.add_argument("--device", type=int, default=None,
                    help="physical GPU to run on, via CUDA_VISIBLE_DEVICES (e.g. the idle card "
                         "while ComfyUI keeps the other)")
    args = ap.parse_args()

    if args.device is not None:
        # Must precede any CUDA initialisation, hence before the factory/ORT imports below.
        os.environ["CUDA_VISIBLE_DEVICES"] = str(args.device)
        print(f"CUDA_VISIBLE_DEVICES={args.device} — the provider's device_id 0 is that card\n")

    run_sweep() if args.sweep else run_shipped()
    return 0


if __name__ == "__main__":
    sys.exit(main())
