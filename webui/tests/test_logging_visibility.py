"""The backend must configure root logging (SPEC_GPU_MEMORY_HYGIENE §5, §11.2).

Before this landed, nothing in the app configured logging at all, so the root logger had no
handler and Python's `logging.lastResort` applied: WARNING and above reached stderr, INFO was
silently DROPPED. uvicorn does not fix this — its dictConfig defines only `uvicorn*` loggers
(verified: root handlers are `[]` after uvicorn configures itself).

The cost was a false green in the observability layer itself: the verified-eviction report
logs its SUCCESS at INFO and its failures at WARNING, so a working eviction produced no
record while a broken one did. "It worked" and "it never ran" looked identical.

These tests patch `logging.basicConfig` and reload the app rather than inspecting root's
handlers, deliberately: pytest's own logging plugin attaches handlers to root, so an
assertion about root would pass whether or not the app configured anything — the tautology
this file exists to avoid.
"""
import importlib
import logging

import pytest


@pytest.fixture()
def captured_basic_config(monkeypatch):
    """Reload the app with `logging.basicConfig` stubbed, and hand back what it was called
    with. Returns `{}` if the app never configured logging — which is the regression."""
    calls = {}
    monkeypatch.setattr(logging, "basicConfig", lambda **kw: calls.update(kw))

    def _reload():
        import app as app_mod
        importlib.reload(app_mod)
        return calls

    return _reload


def test_backend_configures_root_logging_at_a_level_that_keeps_info(captured_basic_config):
    """Deleting the basicConfig call, or defaulting it to WARNING, silently re-breaks every
    INFO-level report the factory makes. That is invisible in every other test."""
    calls = captured_basic_config()

    assert calls, ("the backend must configure root logging itself — uvicorn configures only "
                   "its own loggers and leaves root handler-less, which drops INFO")
    assert calls["level"] <= logging.INFO, (
        f"root log level {calls['level']} discards INFO, so the eviction report's success "
        "line would never be recorded")


def test_a_bogus_log_level_env_falls_back_instead_of_killing_the_boot(monkeypatch,
                                                                     captured_basic_config):
    """`DATSPET_LOG_LEVEL` is operator-set, so a typo must degrade to the default rather than
    raise at import and take the whole backend down with it."""
    monkeypatch.setenv("DATSPET_LOG_LEVEL", "NOT_A_REAL_LEVEL")
    calls = captured_basic_config()
    assert calls["level"] == logging.INFO


def test_the_log_level_is_operator_overridable(monkeypatch, captured_basic_config):
    """A pool node drowning in INFO needs a lever that is not a code change."""
    monkeypatch.setenv("DATSPET_LOG_LEVEL", "warning")      # case-insensitive on purpose
    calls = captured_basic_config()
    assert calls["level"] == logging.WARNING


# ---- the pool handlers configure their OWN process (§11.8) ------------------------------

import importlib.util          # noqa: E402
import os                      # noqa: E402
import sys                     # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HANDLERS = ("pet_factory_handler", "pet_preview_handler")


def _load_handler_capturing_basic_config(monkeypatch, name):
    """Import a pool handler from source with `logging.basicConfig` stubbed, and return what it
    was called with. The handler runs in a subprocess the pool worker spawns, so it is the only
    thing that can configure that process's logging."""
    calls = {}
    monkeypatch.setattr(logging, "basicConfig", lambda **kw: calls.update(kw))
    path = os.path.join(REPO, "pool_handler", f"{name}.py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return calls


@pytest.mark.parametrize("handler", HANDLERS)
def test_pool_handlers_configure_logging_so_info_survives_in_their_subprocess(monkeypatch,
                                                                             handler):
    """`pool_worker/spawn.py` runs each handler as `python -m pool_worker.run_handler <file>`,
    and `run_handler` configures no logging — so without this the handler's process has a
    handler-less root, `logging.lastResort` applies, and every INFO record is discarded. That is
    what kept F4's verified-eviction success line invisible on pool nodes."""
    calls = _load_handler_capturing_basic_config(monkeypatch, handler)
    assert calls, f"{handler} must configure logging — nothing upstream of it does"
    assert calls["level"] <= logging.INFO


@pytest.mark.parametrize("handler", HANDLERS)
def test_pool_handlers_log_to_stderr_because_stdout_is_the_result_protocol(monkeypatch,
                                                                          handler):
    """**The one that matters.** `run_handler` uses stdout as a JSON-lines protocol — progress
    beats plus exactly one terminal result. Logging to stdout would inject non-JSON lines into
    the result channel. stderr is read separately into the worker's heartbeat `stderr_tail`,
    which is where operational output belongs."""
    calls = _load_handler_capturing_basic_config(monkeypatch, handler)
    assert calls.get("stream") is sys.stderr, (
        f"{handler} must log to stderr — stdout is run_handler's JSON result protocol")
