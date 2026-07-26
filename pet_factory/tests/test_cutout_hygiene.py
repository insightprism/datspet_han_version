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

    with caplog.at_level("WARNING"):
        factory._evict_comfy_models_for_cutout()     # must return, not raise

    assert any("did NOT reach the target" in r.getMessage() for r in caplog.records)


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
