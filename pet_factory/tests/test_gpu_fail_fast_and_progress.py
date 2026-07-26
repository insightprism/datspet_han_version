"""GPU birefnet fail-fast (spec item A) + per-frame cutout progress (item B) — pins the
2026-07-21 incident-fix behavior. Zero GPU / zero model load: onnxruntime's new_session and
factory._remove_bg are stubbed."""
import time

import pytest
from PIL import Image

from pet_factory import factory


class _FakeInner:
    def __init__(self, providers):
        self._p = providers

    def get_providers(self):
        return self._p


class _FakeSession:
    def __init__(self, providers):
        self.inner_session = _FakeInner(providers)


def _stub_new_session(monkeypatch, providers):
    import rembg
    monkeypatch.setattr(factory._CUTOUT, "_session", None)   # reset the managed session cache
    monkeypatch.setattr(rembg, "new_session", lambda *a, **k: _FakeSession(providers))


# ---- item A: fail fast on a GPU node, keep the CPU fallback otherwise -------------------

def test_fail_fast_when_gpu_required_but_cpu_only(monkeypatch):
    _stub_new_session(monkeypatch, ["CPUExecutionProvider"])
    monkeypatch.setenv("PET_FACTORY_REQUIRE_GPU", "1")
    with pytest.raises(RuntimeError, match="CUDA"):
        factory._rembg()


def test_no_fail_when_cuda_present(monkeypatch):
    _stub_new_session(monkeypatch, ["CUDAExecutionProvider", "CPUExecutionProvider"])
    monkeypatch.setenv("PET_FACTORY_REQUIRE_GPU", "1")
    assert factory._rembg() is not None            # CUDA active → no raise


def test_cpu_fallback_allowed_when_not_required(monkeypatch):
    _stub_new_session(monkeypatch, ["CPUExecutionProvider"])
    monkeypatch.delenv("PET_FACTORY_REQUIRE_GPU", raising=False)
    assert factory._rembg() is not None            # CPU-only node keeps the graceful fallback


# ---- item B: the cutout stage reports progress per frame (feeds the pool stall timer) ----

def test_cutout_emits_per_frame_progress(monkeypatch):
    monkeypatch.setattr(factory._CUTOUT, "_session", object())        # a live fake → skip the model load
    monkeypatch.setattr(factory, "_remove_bg", lambda img: img.convert("RGBA"))
    walk = [Image.new("RGB", (256, 256), (0, 0, 0)) for _ in range(3)]
    idle = [Image.new("RGB", (256, 256), (0, 0, 0)) for _ in range(2)]
    calls = []
    factory.pack_datsme_bundle({"walk": walk, "idle": idle}, "b", "B",
                               on_frame=lambda done, total: calls.append((done, total)))
    # one monotonic beat per frame; total = every frame across all poses (3 + 2)
    assert calls == [(1, 5), (2, 5), (3, 5), (4, 5), (5, 5)]


# ---- the managed cutout session: single-instance, released on build end, idle-killed --------

def test_cutout_session_is_single_instance_and_release_frees_it(monkeypatch):
    """get() returns ONE session (reused), and release() drops it so onnxruntime hands the
    GPU arena back — the leak fix. Fake session (object) to skip the birefnet model load."""
    mgr = factory._CutoutSession()
    monkeypatch.setattr(mgr, "_new_session", lambda: object())
    s1 = mgr.get()
    assert s1 is not None
    assert mgr.get() is s1               # single instance — the same session is reused
    mgr.release()
    assert mgr._session is None          # freed: next cutout re-creates lazily
    assert mgr.get() is not s1           # ...and it IS a fresh one


def test_cutout_session_idle_watchdog_reclaims_a_missed_release():
    """A build that never called release() (crash, direct pack caller) can't leak forever —
    the watchdog destroys the session after IDLE_TIMEOUT_S of no use. Fast timeouts for the test."""
    mgr = factory._CutoutSession()
    mgr.IDLE_TIMEOUT_S = 0.2
    mgr._POLL_S = 0.05
    mgr._new_session = lambda: object()
    mgr.get()                            # creates + starts the watchdog
    assert mgr._session is not None
    for _ in range(60):                  # up to 3s; watchdog should reclaim within ~0.25s
        if mgr._session is None:
            break
        time.sleep(0.05)
    assert mgr._session is None, "idle watchdog should have reclaimed the unused session"
