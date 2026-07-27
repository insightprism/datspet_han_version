"""GPU memory hygiene (SPEC_GPU_MEMORY_HYGIENE §7) — F2 loud cutout failure, F4 verified
ComfyUI eviction, and the measured constants both rest on.

ZERO GPU, ZERO model load, ZERO network: the cutout session is a plain `object()`,
`factory._remove_bg` is stubbed, and `requests` is stubbed per test — the same patterns
`test_gpu_fail_fast_and_progress.py` already uses, so this file runs on the standard
`pytest pet_factory/tests webui/tests` gate.

F1 (the ORT arena cap) is NOT implemented yet, so §7.1's provider-options test is deliberately
absent — see the spec's §2.4. `_CUTOUT_WORKING_SET_BYTES` already carries F1's measured budget
because F4's watermark is derived from it.
"""
import logging
import time

import pytest
from PIL import Image

from pet_factory import factory


def _frames(n, size=(32, 32)):
    return [Image.new("RGB", size, (10, 20, 30)) for _ in range(n)]


def _boom(*_a, **_k):
    raise RuntimeError("CUDA out of memory")


@pytest.fixture
def live_cutout_session(monkeypatch):
    """A fake live session so `_CUTOUT.get()` never builds the real birefnet model."""
    monkeypatch.setattr(factory._CUTOUT, "_session", object())


# ---- F1: the arena options reach ORT, and the fail-fast survives them (§7.1) ------------

def _capture_new_session(monkeypatch, providers_returned):
    """Stub `rembg.new_session` and CAPTURE the kwargs it was handed.

    The capture is the point. `test_gpu_fail_fast_and_progress.py`'s stub discards them, which
    is right for what that file tests and useless here: a stub that ignores `providers` cannot
    tell whether we passed an options tuple or the bare list we passed before F1, so a test
    built on it would pass either way."""
    seen = {}

    def _stub(*args, **kwargs):
        seen.update(kwargs)
        return _FakeSession(providers_returned)

    import rembg
    monkeypatch.setattr(factory._CUTOUT, "_session", None)   # reset the managed session cache
    monkeypatch.setattr(rembg, "new_session", _stub)
    return seen


class _FakeInner:
    def __init__(self, providers):
        self._providers = providers

    def get_providers(self):
        return self._providers


class _FakeSession:
    def __init__(self, providers):
        self.inner_session = _FakeInner(providers)


def test_the_arena_options_are_actually_passed_to_the_cuda_provider(monkeypatch):
    """Pins our half of the rembg contract: the CUDA provider must arrive as a
    `(name, options)` TUPLE carrying all three knobs, with CPU left bare.

    Worth stating what this canNOT cover. rembg forwards `providers` to ORT only because
    `BaseSession.__init__` pops it when `isinstance(providers, list)` — verified by hand against
    rembg 2.0.69 / onnxruntime 1.23.2 by building a real session and reading
    `get_provider_options()` back. If a rembg upgrade changed that, the options would be
    silently DROPPED and the cap would stop applying with no error anywhere. Proving otherwise
    needs a real GPU session, which this zero-GPU gate cannot have. So: this test pins what we
    send, the pinned dependency versions cover what rembg does with it, and §11 records the gap.
    """
    seen = _capture_new_session(monkeypatch, ["CUDAExecutionProvider", "CPUExecutionProvider"])
    factory._rembg()

    providers = seen["providers"]
    assert isinstance(providers, list), "rembg only forwards `providers` when it is a list"
    cuda, cpu = providers
    assert cpu == "CPUExecutionProvider", "CPU stays unparameterized — CPU-only nodes fall back"

    name, options = cuda
    assert name == factory._CUTOUT_PROVIDER
    assert options == {
        "device_id": factory._CUTOUT_DEVICE_ID,
        "gpu_mem_limit": factory._CUTOUT_GPU_MEM_LIMIT_BYTES,
        "arena_extend_strategy": factory._CUTOUT_ARENA_STRATEGY,
    }


def test_passing_provider_options_does_not_disarm_the_gpu_fail_fast(monkeypatch):
    """§2.3's non-obvious invariant, and the one that would fail SILENTLY in the bad direction.

    The fail-fast reads `inner_session.get_providers()` and looks for the plain string
    "CUDAExecutionProvider". If passing a `(name, options)` tuple made ORT report the providers
    in some richer shape, that `in` check would quietly stop matching — and a GPU node would go
    back to running the cutout on CPU at ~1/12 speed with the guard silently disarmed, which is
    the exact 2026-07-21 incident F3 exists to prevent. ORT returns bare NAME strings either way
    (verified against a real options-carrying session); this pins it."""
    _capture_new_session(monkeypatch, ["CPUExecutionProvider"])   # CUDA absent despite the options
    monkeypatch.setenv("PET_FACTORY_REQUIRE_GPU", "1")

    with pytest.raises(RuntimeError, match="CUDA"):
        factory._rembg()

    _capture_new_session(monkeypatch, ["CUDAExecutionProvider", "CPUExecutionProvider"])
    monkeypatch.setenv("PET_FACTORY_REQUIRE_GPU", "1")
    assert factory._rembg() is not None      # bare names still satisfy the check


# ---- F2: a failed matte fails the build (§7.2) -----------------------------------------

def test_cutout_failure_raises_instead_of_shipping_opaque_alpha(live_cutout_session, monkeypatch):
    """The 2026-07-26 behaviour change: birefnet raising used to become a fully-opaque alpha
    and STILL return valid zip bytes at progress 1.0 — a white-backed pet reported as success.
    It must now raise, and it must not hand back bytes."""
    monkeypatch.setattr(factory, "_remove_bg", _boom)

    with pytest.raises(factory.CutoutFailed) as excinfo:
        factory.pack_datsme_bundle({"walk": _frames(3)}, "b", "B")

    # The exception has to say WHICH frame died — a build that fails without naming the pose
    # sends you back to the GPU log to find out (§3.2).
    err = excinfo.value
    assert err.pose_name == "walk"
    assert err.frame_index == 0                      # fails on the FIRST bad frame, not at the end
    assert isinstance(err.cause, RuntimeError)
    assert "CUDA out of memory" in str(err)


def test_cutout_failure_aborts_the_pose_instead_of_mixing_matted_and_opaque_frames(
        live_cutout_session, monkeypatch):
    """Tolerance is ZERO frames, so a mid-pose failure must not produce a sheet where frames
    1-2 are matted and frame 3 is a white rectangle — that is a visible white flash mid-walk."""
    calls = {"n": 0}

    def _fails_on_the_third(img):
        calls["n"] += 1
        if calls["n"] >= 3:
            raise RuntimeError("provider fell over")
        return img.convert("RGBA")

    monkeypatch.setattr(factory, "_remove_bg", _fails_on_the_third)

    with pytest.raises(factory.CutoutFailed) as excinfo:
        factory.pack_datsme_bundle({"walk": _frames(8)}, "b", "B")

    assert excinfo.value.frame_index == 2            # stopped there; did not matte the other 5
    assert calls["n"] == 3


def test_fallback_budget_is_build_wide_not_per_pose(live_cutout_session, monkeypatch):
    """`_CUTOUT_MAX_FALLBACK_FRAMES` is a budget for the whole BUNDLE, but `prep()` runs once
    per pose — so a counter scoped inside it would silently mean N *per pose*, i.e. up to 8N
    opaque frames in an 8-pose build. Invisible at the shipped 0, which is exactly why it needs
    a test: the constant advertises itself as revisitable, and the semantics must survive that."""
    monkeypatch.setattr(factory, "_CUTOUT_MAX_FALLBACK_FRAMES", 1)
    seen = {"n": 0}

    def one_bad_frame_in_each_pose(img):
        seen["n"] += 1
        if seen["n"] in (1, 4):                  # frame 0 of walk, then frame 0 of idle
            raise RuntimeError("transient")
        return img.convert("RGBA")

    monkeypatch.setattr(factory, "_remove_bg", one_bad_frame_in_each_pose)

    with pytest.raises(factory.CutoutFailed) as excinfo:
        factory.pack_datsme_bundle({"walk": _frames(3), "idle": _frames(3)}, "b", "B")

    # walk spent the single tolerated frame; idle's failure must exhaust the BUILD budget.
    # Per-pose scoping would let both through and ship a bundle with two white flashes.
    assert excinfo.value.pose_name == "idle"
    assert excinfo.value.frame_index == 0


def test_the_provider_line_goes_through_the_logger_not_stdout(monkeypatch, caplog):
    """B1's record (SPEC_GPU_MEMORY_HYGIENE §11.2). It was a bare `print`, which on a pool node
    lands in `run_handler`'s JSON-lines **stdout protocol** and survives only as the worker's
    "non-JSON handler stdout dropped" warning. Logging puts it on stderr, which the worker reads
    into its heartbeat `stderr_tail` deliberately.

    Pinned because a `print` here is the easy, natural thing to write, and reverting to one
    would silently move the line back into the result channel."""
    import rembg

    class _Inner:
        def get_providers(self):
            return ["CUDAExecutionProvider", "CPUExecutionProvider"]

    class _Session:
        inner_session = _Inner()

    monkeypatch.setattr(factory._CUTOUT, "_session", None)
    monkeypatch.setattr(rembg, "new_session", lambda *a, **k: _Session())

    with caplog.at_level("INFO", logger="pet_factory.factory"):
        factory._rembg()

    assert any("rembg providers" in r.getMessage() for r in caplog.records), (
        "the provider line must be a log record, not a print to stdout")


def test_zero_fallback_tolerance_is_the_shipped_decision():
    """`_CUTOUT_MAX_FALLBACK_FRAMES` exists so the choice is visible and revisitable. If someone
    raises it, the two tests above stop describing the shipped behaviour — fail here first."""
    assert factory._CUTOUT_MAX_FALLBACK_FRAMES == 0


def test_a_successful_cutout_still_returns_bytes(live_cutout_session, monkeypatch):
    """The happy path is unchanged — F2 must not have turned a working build into a raise."""
    monkeypatch.setattr(factory, "_remove_bg", lambda img: img.convert("RGBA"))
    out = factory.pack_datsme_bundle({"walk": _frames(2), "idle": _frames(2)}, "b", "B")
    assert isinstance(out, bytes) and len(out) > 0


# ---- F2: the GPU is still handed back on the new raise path (§7.3) ----------------------

def test_cutout_failure_still_releases_the_session(monkeypatch, tmp_path):
    """`make_pet_zip`'s `finally` must survive `CutoutFailed`, or a failed build leaves
    birefnet's arena pinned on the card until the idle watchdog notices 5 minutes later.

    Driven through `make_pet_zip`, NOT `pack_datsme_bundle` — the release lives in the former's
    `finally` and the latter has none (§3.2). Every ComfyUI hop is stubbed, so no GPU, no HTTP.
    """
    released = []
    monkeypatch.setattr(factory._CUTOUT, "_session", object())
    monkeypatch.setattr(factory._CUTOUT, "release", lambda: released.append(True))

    monkeypatch.setattr(factory, "_base_sprite", lambda *a, **k: tmp_path / "base.png")
    monkeypatch.setattr(factory, "_run", lambda *a, **k: "out.webp")
    monkeypatch.setattr(factory, "_wait_stable", lambda *a, **k: None)
    monkeypatch.setattr(factory, "_frames_rgba", lambda *a, **k: _frames(2))
    monkeypatch.setattr(factory, "_evict_comfy_models_for_cutout", lambda: None)
    monkeypatch.setattr(factory, "_remove_bg", _boom)

    with pytest.raises(factory.CutoutFailed):
        factory.make_pet_zip("red panda")

    assert released == [True], "the cutout session must be released even when the build fails"


# ---- F4: the eviction read-back (§7.4, §7.5) --------------------------------------------

class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _stats(*devices):
    return _FakeResponse({"devices": list(devices)})


def _device(index, vram_free):
    return {"name": f"cuda:{index}", "type": "cuda", "index": index,
            "vram_total": 25556615168, "vram_free": vram_free}


def test_free_poll_selects_the_device_by_index_not_by_position(monkeypatch):
    """A 2-GPU box reports BOTH cards. Reading `devices[0]` would silently measure the wrong
    card the moment the cutout's device stops being ComfyUI's primary (§5.2)."""
    monkeypatch.setattr(factory.requests, "get",
                        lambda *a, **k: _stats(_device(1, 1), _device(0, 12345)))
    assert factory._comfy_vram_free(device_id=0) == 12345
    assert factory._comfy_vram_free(device_id=1) == 1


def test_free_poll_returns_none_for_a_device_that_is_not_reported(monkeypatch):
    """An absent device is `None` (visibly unknown in the log), never 0 — which would read as
    'the card is full' and is the opposite of the truth."""
    monkeypatch.setattr(factory.requests, "get", lambda *a, **k: _stats(_device(0, 999)))
    assert factory._comfy_vram_free(device_id=3) is None


def test_free_poll_stops_as_soon_as_the_target_is_met(monkeypatch):
    """The point of F4 is replacing a blind sleep with a read-back: when the eviction lands
    immediately, the build must not sit through the poll interval for nothing."""
    monkeypatch.setattr(factory.requests, "post", lambda *a, **k: None)
    monkeypatch.setattr(factory.requests, "get",
                        lambda *a, **k: _stats(_device(0, factory._FREE_TARGET_VRAM_BYTES + 1)))
    slept = []
    monkeypatch.setattr(factory.time, "sleep", lambda s: slept.append(s))

    factory._evict_comfy_models_for_cutout()
    assert slept == [], "target already met — nothing to wait for"


def test_poll_budget_starts_after_the_post_not_before_the_first_read(monkeypatch):
    """The `before` read and the `/free` POST can each burn a full `_COMFY_HTTP_TIMEOUT_S`. A
    deadline anchored before them is already spent when the loop starts, so the read-back never
    runs — and it fails precisely when a sluggish ComfyUI makes the read-back most valuable.
    Here the two pre-loop hops (0.30 s) deliberately exceed the whole poll budget (0.25 s)."""
    polls = {"n": 0}

    def slow_get(*_a, **_k):
        time.sleep(0.15)
        polls["n"] += 1
        return _stats(_device(0, 1))             # never meets the target — keeps the loop going

    monkeypatch.setattr(factory.requests, "get", slow_get)
    monkeypatch.setattr(factory.requests, "post", lambda *a, **k: time.sleep(0.15))
    monkeypatch.setattr(factory, "_FREE_POLL_TIMEOUT_S", 0.25)
    monkeypatch.setattr(factory, "_FREE_POLL_INTERVAL_S", 0.01)

    factory._evict_comfy_models_for_cutout()

    # 2 reads happen before the loop (`before`, then the first `after`). A third proves the
    # loop actually got to re-read; anchoring the deadline at the start yields exactly 2.
    assert polls["n"] >= 3, "the poll budget was consumed by the pre-loop HTTP hops"


def test_free_poll_timeout_warns_and_proceeds(monkeypatch, caplog):
    """An unreachable ComfyUI (or one that never reclaims) must NOT abort the build: once the
    arena is bounded the cutout no longer depends on the eviction landing, so this is advisory
    (§0.5). A raise here would turn a slow build into no pet at all."""
    def _unreachable(*_a, **_k):
        raise ConnectionError("connection refused")

    monkeypatch.setattr(factory.requests, "get", _unreachable)
    monkeypatch.setattr(factory.requests, "post", _unreachable)
    monkeypatch.setattr(factory, "_FREE_POLL_TIMEOUT_S", 0.2)
    monkeypatch.setattr(factory, "_FREE_POLL_INTERVAL_S", 0.05)

    with caplog.at_level(logging.WARNING, logger="pet_factory.factory"):
        factory._evict_comfy_models_for_cutout()     # must return, not raise

    emitted = [r.getMessage() for r in caplog.records]
    assert any("did NOT reach the target" in m for m in emitted)
    assert any("/free unreachable" in m for m in emitted)


def test_the_eviction_success_line_is_emitted_at_info_with_the_numbers(monkeypatch, caplog):
    """The success line IS the measurement F4 exists to produce — it is the only place the
    reclaimed VRAM is ever recorded. Two ways to lose it, both seen:

      1. Logging it below the level the process keeps. The first cut of F4 used `log.info` when
         nothing configured root logging, so `logging.lastResort` applied (WARNING and above
         only) and a WORKING eviction logged nothing while a broken one did. `webui/app.py` now
         calls `basicConfig`, and `webui/tests/test_logging_visibility.py` pins that end; this
         pins THIS end — that the report is emitted at INFO and carries the numbers.
      2. Reporting the outcome without the values, which is a status nobody can act on.
    """
    monkeypatch.setattr(factory.requests, "post", lambda *a, **k: None)
    monkeypatch.setattr(factory.requests, "get",
                        lambda *a, **k: _stats(_device(0, factory._FREE_TARGET_VRAM_BYTES + 1)))

    with caplog.at_level(logging.INFO, logger="pet_factory.factory"):
        factory._evict_comfy_models_for_cutout()

    info = [r for r in caplog.records if r.levelno == logging.INFO]
    assert info, "the SUCCESS path must leave a record, not just the failure path"
    msg = info[-1].getMessage()
    assert "landed" in msg
    assert "vram_free" in msg and "target" in msg    # the numbers, not just a verdict
    assert "MiB" in msg


def test_free_poll_reports_unknown_rather_than_zero_when_stats_are_unreadable(monkeypatch):
    """`_mib(None)` must stay legible — a log line reading '0 MiB free' would send the reader
    hunting a memory leak that isn't there."""
    assert factory._mib(None) == "unknown"
    assert factory._mib(6 * 1024**3) == "6144 MiB"


# ---- the measured constants (§7.6) -------------------------------------------------------

def test_cutout_budget_constants_are_named_and_above_the_measured_floor():
    """§2.6 swept the arena: 4 GiB FAILS (ORT raises on an 822 MB activation), 6 GiB is the
    smallest cap measured to pass. The old '> the model size' bound would have waved through
    the broken 4 GiB value, because birefnet's 214 MB on disk is not the relevant floor — the
    measured working set is. This test is what catches a future model swap invalidating §2.6.
    """
    MEASURED_FLOOR_BYTES = 6 * 1024**3           # smallest cap observed to pass (§2.6 row 11)
    assert factory._CUTOUT_WORKING_SET_BYTES >= MEASURED_FLOOR_BYTES
    assert factory._CUTOUT_PEAK_TOLERANCE_BYTES > 0      # the CUDA context lives outside the arena
    assert factory._CUTOUT_DEVICE_ID >= 0


def test_the_arena_cap_stays_inside_the_band_where_it_actually_does_something():
    """**The most important assertion in this file**, because it guards the only way F1 can fail
    SILENTLY.

    Peak-vs-cap is a cliff, not a slope (§2.6): the cap buys the full 14618 → 6426 MiB saving
    anywhere in [6144, 10240] MiB, and buys NOTHING from 12288 upward, where the arena resumes
    opportunistic growth. Both edges have to be pinned:

      - too low  → `CutoutFailed` on the first frame. Loud, immediate, self-announcing; this
                   assertion is a convenience.
      - too high → no error, no failed test, no symptom, no benefit. The fix is simply gone.

    And "the cap looks tight, let's raise it" is the natural instinct after any memory scare —
    which lands exactly in the dead band. So the upper bound is the assertion that earns its
    keep. If you are here because this test failed after you raised the cap: re-measure first
    (§2.6, ≥3 frames), and move this bound only with numbers.
    """
    LOWEST_CAP_THAT_WORKS = 6 * 1024**3       # 4096 MiB FAILS; 6144 MiB passes (§2.6 rows 11-12)
    HIGHEST_CAP_STILL_BOUNDED = 10 * 1024**3  # 10240 MiB → 6424 MiB; 12288 MiB → 12570 (rows 8, +)

    cap = factory._CUTOUT_GPU_MEM_LIMIT_BYTES
    assert LOWEST_CAP_THAT_WORKS <= cap <= HIGHEST_CAP_STILL_BOUNDED, (
        f"_CUTOUT_GPU_MEM_LIMIT_BYTES is {cap // 1024**2} MiB, outside the measured band "
        f"[{LOWEST_CAP_THAT_WORKS // 1024**2}, {HIGHEST_CAP_STILL_BOUNDED // 1024**2}] MiB. "
        "Below it the cutout raises CutoutFailed on the first frame; above it the arena resumes "
        "growing to ~14.6 GB and the cap silently buys NOTHING — same build, same speed, no "
        "error, no symptom. If you raised this after a memory scare, that is the trap: re-read "
        "the cliff table in factory.py's constants band and re-measure (>=3 frames) before "
        "moving this bound.")
    assert factory._CUTOUT_ARENA_STRATEGY == "kNextPowerOfTwo", (
        "kSameAsRequested needs a higher cap to work at all and settles ~574 MiB higher on this "
        "model — ORT's generic 'use kSameAsRequested when short of memory' advice does not hold "
        "here, and §2.6 rows 6 vs 11 are the measurement")


def test_the_cap_and_the_requirement_are_separate_numbers():
    """They answer different questions and merging them breaks something either way: the cap is
    the CEILING (what ORT may hoard), the working set is the REQUIREMENT (what the cutout needs,
    and therefore what F4's free-VRAM watermark is built from).

    Capping at the requirement leaves ~1 GiB over the failure floor; deriving the watermark from
    the cap makes the eviction poll demand 11 GiB and warn when 8 GiB free was perfectly fine.
    The spec proposed exactly this merge before the cliff was measured, so the trap is real."""
    assert factory._CUTOUT_GPU_MEM_LIMIT_BYTES > factory._CUTOUT_WORKING_SET_BYTES, (
        "the arena CEILING must sit above the measured REQUIREMENT — if they are the same "
        "number, either the cap has ~1 GiB of margin over the failure floor or F4's watermark "
        "has been derived from the ceiling and will warn when free VRAM was fine")
    assert factory._FREE_TARGET_VRAM_BYTES == (factory._CUTOUT_WORKING_SET_BYTES
                                               + factory._CUTOUT_PEAK_TOLERANCE_BYTES), (
        "F4's watermark must be built from the REQUIREMENT, not the arena ceiling (§5.2)")


def test_free_target_is_derived_from_the_requirement_not_from_observed_free_vram():
    """The watermark must mean 'enough for the cutout to fit', not 'whatever the box had spare
    when we looked'. A B4-derived target would certify a broken eviction (§5.2)."""
    assert factory._FREE_TARGET_VRAM_BYTES == (factory._CUTOUT_WORKING_SET_BYTES
                                               + factory._CUTOUT_PEAK_TOLERANCE_BYTES)


def test_poll_budget_is_bounded_and_actually_polls():
    """A timeout below one interval would never re-read; an unbounded one would hang a build
    behind a wedged ComfyUI."""
    assert 0 < factory._FREE_POLL_INTERVAL_S < factory._FREE_POLL_TIMEOUT_S
    assert factory._FREE_POLL_TIMEOUT_S <= 60
    assert factory._COMFY_HTTP_TIMEOUT_S > 0


# ── SPEC_MATTE_REPAIR_ORDER §5: repair the matte before the geometry ─────────────────────
#
# The defect these pin: `_fill_holes_alpha` ran ONE LINE AFTER `_fit_square`, so the fill
# made holes opaque whose colour the premultiplying resample had already annihilated —
# painting the animal's own body pure black at full opacity. Measured across every bundle
# on the box (§1): the penguin lost 41% of its subject, the staging snow leopard's idle
# frames 41%. It hid for months because a blacked-out belly on a black-and-white bird
# reads as a stylistic choice (§1.2).
#
# FIXTURES ARE GENERATED, not committed: there is no precedent for binaries under
# pet_factory/tests, and the obvious real-data fixture (friendlypup.zip) is scheduled for
# regeneration in §8 — a test keyed to it would change inputs the moment the fix ships.
# The real-matte equivalence run (128/128 channels) is §7's gate, against a bundle, where
# it can be re-run rather than frozen.

_PALE_FUR = (245, 244, 243)      # the colour the fill must NOT replace with black


def _matte_with_hole(size=64, *, hole_alpha=0, hole=(24, 40)):
    """A pale square subject on transparent background, with one INTERIOR hole in the
    matte. `hole_alpha=0` is a hard miss (colour annihilated); 130 is a soft one."""
    import numpy as np
    a = np.zeros((size, size), np.uint8)
    a[4:size - 4, 4:size - 4] = 255
    lo, hi = hole
    a[lo:hi, lo:hi] = hole_alpha
    return Image.fromarray(a, "L")


def _pale_frame(size=64):
    return Image.new("RGB", (size, size), _PALE_FUR)


def _pack_one_frame(monkeypatch, frame, matte, frame_size=256):
    """Run ONE frame through the real packer with the cutout stubbed to return `matte`,
    and hand back the packed cell. The seam is `_remove_bg`, so everything after it —
    putalpha, the repair, _fit_square, the sheet paste — is the shipped code."""
    import io
    import zipfile

    def fake_remove_bg(img):
        out = img.convert("RGBA")
        out.putalpha(matte.resize(img.size, Image.NEAREST))
        return out

    monkeypatch.setattr(factory, "_remove_bg", fake_remove_bg)
    monkeypatch.setattr(factory._CUTOUT, "_session", object())
    zip_bytes = factory.pack_datsme_bundle({"walk": [frame]}, "t", "T", frame_size=frame_size)
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        name = next(n for n in z.namelist() if n.endswith("_sprite.png"))
        sheet = Image.open(io.BytesIO(z.read(name))).convert("RGBA")
    return sheet.crop((0, 0, frame_size, frame_size))


def test_a_filled_hole_keeps_the_animals_colour(monkeypatch):
    """§5 test 1 — THE REGRESSION TEST. A hard-zero interior hole in a pale animal must
    come back as the animal's colour, not as opaque black."""
    import numpy as np
    cell = _pack_one_frame(monkeypatch, _pale_frame(), _matte_with_hole())
    px = np.array(cell)
    # The hole's centre, in cell coordinates: the 64² frame scales to fill the cell.
    mid = px[px.shape[0] // 2, px.shape[1] // 2]
    assert mid[3] == 255, "the hole must still be closed — the repair, not its removal"
    assert max(int(mid[0]), int(mid[1]), int(mid[2])) > 200, (
        f"the filled hole came back as {tuple(mid[:3])}, not the animal's fur — the repair "
        "is running after the resample that already destroyed the colour")


def test_no_opaque_pixel_is_black_that_the_matte_cannot_explain(monkeypatch):
    """§5 test 2 — the sheet-wide version: nothing opaque may be near-black unless the
    INPUT frame drew it dark. This is the property `scripts/probe_matte_fill.py` measures
    on shipped bundles, asserted at build time on a frame with no dark pixels at all."""
    import numpy as np
    px = np.array(_pack_one_frame(monkeypatch, _pale_frame(), _matte_with_hole()))
    unexplained = ((px[..., 3] > 200) & (px[..., :3].max(axis=-1) < 45)).sum()
    assert unexplained == 0, f"{unexplained} opaque near-black px from an all-pale frame"


def test_the_matte_is_repaired_before_any_resample(monkeypatch):
    """§5 test 3 — STRUCTURAL, so the ordering cannot silently regress. Capture what
    `_fit_square` is handed and assert its alpha has no border-unreachable transparent
    region: by then the repair must already have happened."""
    import numpy as np
    seen = []
    real_fit = factory._fit_square

    def spy(img, size):
        seen.append(img.copy())
        return real_fit(img, size)

    monkeypatch.setattr(factory, "_fit_square", spy)
    _pack_one_frame(monkeypatch, _pale_frame(), _matte_with_hole())
    assert seen, "_fit_square was never called"
    a = np.array(seen[0].split()[3])
    holes = np.array(factory._fill_holes_alpha(Image.fromarray(a, "L"))) != a
    assert not holes.any(), (
        "the matte handed to _fit_square still has interior holes — the repair is "
        "downstream of the resample, which is the whole defect")


def test_the_vectorized_fill_matches_the_reference_bfs():
    """§5 test 4 — F2's equivalence, against the oracle `_fill_holes_alpha` keeps existing
    for. Includes the case the naive vectorization gets wrong: transparency CONNECTED to
    the border is real background and must stay transparent."""
    import numpy as np
    rng = np.random.default_rng(20260727)
    cases = [
        _matte_with_hole(hole_alpha=0),                      # hard hole
        _matte_with_hole(hole_alpha=130),                    # soft hole
        _matte_with_hole(hole_alpha=0, hole=(4, 20)),        # hole touching the subject edge
        Image.fromarray(np.full((64, 64), 255, np.uint8), "L"),          # no holes at all
        Image.fromarray(np.zeros((64, 64), np.uint8), "L"),              # all background
        Image.fromarray(rng.integers(0, 256, (64, 64), dtype=np.uint8), "L"),   # noise
    ]
    # A donut: a bite out of the border must NOT be filled.
    bite = np.zeros((64, 64), np.uint8)
    bite[4:60, 4:60] = 255
    bite[0:32, 28:36] = 0        # a channel from the border into the subject
    cases.append(Image.fromarray(bite, "L"))

    for i, m in enumerate(cases):
        assert np.array_equal(np.array(factory._repair_matte_holes(m).alpha),
                              np.array(factory._fill_holes_alpha(m))), f"case {i} diverged"


def test_non_hole_pixels_are_unchanged_by_the_repair_move(monkeypatch):
    """§5 test 5 — pins §2.1's byte-identical claim. The repair moves; the resample and
    the paste do not, so every pixel outside a hole must be exactly what it was. Compared
    against a matte with NO hole, where the two orders are trivially equivalent."""
    import numpy as np
    solid = _matte_with_hole(hole_alpha=255)          # subject, no hole
    holed = _matte_with_hole(hole_alpha=0)
    a = np.array(_pack_one_frame(monkeypatch, _pale_frame(), solid))
    b = np.array(_pack_one_frame(monkeypatch, _pale_frame(), holed))
    # Both cells describe the same silhouette; the repair closes the hole in `b`, and
    # nothing else may differ — same alpha everywhere, same colours everywhere.
    assert a.shape == b.shape
    assert np.array_equal(a[..., 3], b[..., 3]), "alpha changed outside the hole"
    assert np.array_equal(a[..., :3], b[..., :3]), "colour changed outside the hole"


def test_the_hard_hole_warning_names_the_pose_and_frame(monkeypatch, caplog):
    """§5 test 6 — F3. Post-repair a matte that dropped a third of the frame is
    cosmetically perfect, which is how this shipped. One WARNING per POSE (not per frame:
    128 lines buries the signal it exists to give), naming the pose and the worst frame,
    and it must never fail the build."""
    frames = [_pale_frame(), _pale_frame(), _pale_frame()]
    with caplog.at_level(logging.WARNING, logger=factory.log.name):
        _pack_one_frame(monkeypatch, frames[0], _matte_with_hole(hole=(10, 54)))
    lines = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert len(lines) == 1, f"expected exactly one warning per pose, got {lines}"
    assert "walk" in lines[0], "the pose must be named"
    assert "frame 0" in lines[0], "the worst frame must be named"


def test_a_small_matte_miss_stays_quiet(monkeypatch, caplog):
    """…and the other half of F3: a routine soft fill says nothing. The otter shipped
    clean with 23% of its subject filled, so a warning on every build would be noise —
    the signal is HARD holes above the threshold (§1.1)."""
    with caplog.at_level(logging.WARNING, logger=factory.log.name):
        _pack_one_frame(monkeypatch, _pale_frame(), _matte_with_hole(hole_alpha=130))
    assert not [r for r in caplog.records if r.levelno == logging.WARNING]


def test_the_matte_thresholds_are_named_constants():
    """§5 test 7 — no literal 160 / 20 / 0.10 at a call site, and the values are the
    calibrated ones. `_fill_holes_alpha`'s default must BE the constant, or the oracle
    and the shipped repair could drift on the one number they share."""
    import inspect
    assert factory._MATTE_HOLE_ALPHA_THR == 160
    assert factory._MATTE_HARD_HOLE_ALPHA == 20
    assert factory._MATTE_HARD_HOLE_WARN_FRACTION == 0.10
    assert (inspect.signature(factory._fill_holes_alpha).parameters["thr"].default
            is factory._MATTE_HOLE_ALPHA_THR)
    src = inspect.getsource(factory._repair_matte_holes) + inspect.getsource(factory.pack_datsme_bundle)
    for literal in ("160", "0.10", "0.1)"):
        assert literal not in src, f"literal {literal!r} at a call site — use the constant"


def test_an_opaque_fallback_matte_is_a_no_op_for_the_repair():
    """§5 test 8 — the dead-session branch. When the cutout fails, `prep` falls back to an
    all-opaque alpha; that matte has no holes, so the repair must do nothing to it and
    must not report damage that would trip F3's warning."""
    import numpy as np
    opaque = Image.fromarray(np.full((64, 64), 255, np.uint8), "L")
    r = factory._repair_matte_holes(opaque)
    assert r.filled_px == 0 and r.hard_px == 0
    assert np.array_equal(np.array(r.alpha), np.array(opaque))


# ── SPEC_MATTE_BACKDROP: the pet is never drawn on its own colour ────────────────────────
#
# `white background` in the still templates was the single biggest source of broken
# sprites here: a pale pet on a white field is the one input birefnet cannot segment, and
# on white a white snow leopard's matte came back a LINE DRAWING with the hole fill adding
# more pixels than the matte returned. These pin the replacement, and in particular pin the
# half that is easy to forget (test 3) — a prompt-only change leaves most pets broken.

def test_neither_still_template_draws_on_white():
    """§2 — the regression test. Both templates, because `_base_prompt` is the CLI's branch
    and `_remix_prompt` is every web build's; fixing one would make them disagree about the
    one thing this spec is about."""
    from pet_factory import prompt_templates as pt
    for template in (pt.BASE_STILL_TEMPLATE, pt.REMIX_STILL_TEMPLATE):
        assert "white background" not in template
        assert pt.STILL_BACKDROP in template
    # …and the rendered sentences, not just the raw templates.
    assert pt.STILL_BACKDROP in pt.base_still_prompt("robin")
    assert pt.STILL_BACKDROP in pt.remix_still_prompt("robin", "mid-stride")


def test_the_backdrop_is_a_named_constant_not_a_literal():
    """§9 I1 — one definition. A literal in either template is how the two drift apart."""
    from pet_factory import prompt_templates as pt
    assert pt.STILL_BACKDROP and isinstance(pt.STILL_BACKDROP, str)
    assert pt.BASE_STILL_TEMPLATE.count(pt.STILL_BACKDROP) == 1
    assert pt.REMIX_STILL_TEMPLATE.count(pt.STILL_BACKDROP) == 1


def test_a_reference_is_padded_onto_the_backdrop_never_white(tmp_path):
    """§9 I3 — THE test that a prompt-only change would fail.

    `_prep_reference_image` pads a non-square reference and flattens transparency, and
    `_base_sprite`'s as-is branch runs it on EVERY web build. With white here, a designed
    or uploaded pet lands back on a white field and the prompt change buys nothing."""
    import numpy as np
    src = tmp_path / "ref.png"
    # Deliberately non-square AND part-transparent: both routes to the canvas colour.
    img = Image.new("RGBA", (64, 32), (10, 20, 200, 255))
    img.putalpha(Image.new("L", img.size, 0))          # fully transparent → canvas shows through
    img.save(src)

    out = np.array(Image.open(factory._prep_reference_image(src)).convert("RGB"))
    corner = tuple(int(v) for v in out[0, 0])
    assert corner != (255, 255, 255), "the reference was padded onto WHITE — §9 I3"
    assert corner == factory.STILL_BACKDROP_RGB, f"padded onto {corner}, not the backdrop"


def test_the_backdrop_phrase_and_pixel_agree():
    """§9 I5 — the backdrop exists twice: as a SENTENCE for the model and as a PIXEL for
    the padding. Nothing else can keep those in sync, so this asserts they describe the
    same colour. If the phrase changes hue, this fails and the RGB must be re-measured
    from what the model actually draws."""
    from pet_factory import prompt_templates as pt
    r, g, b = factory.STILL_BACKDROP_RGB
    assert "cyan" in pt.STILL_BACKDROP, "the phrase moved off cyan — re-measure the RGB"
    # cyan = green and blue high, red low. The one arithmetic claim a word can support.
    assert g > 150 and b > 150 and r < g - 60 and r < b - 60, \
        f"RGB{factory.STILL_BACKDROP_RGB} is not the cyan the phrase asks for"
