"""The arena stream transport (SPEC_PET_ARENA_ROOMS §3.2, §5.2) — R0.

What each case protects:
- SSE_HEARTBEAT_S stays UNDER the outer proxy's 60 s idle default. This is
  the spec's one constant set by infrastructure rather than taste; someone
  will eventually "tidy" it upward and silently kill every live race a
  minute in, in production only, to whoever is watching (§5.2).
- The probe stream is a real event-stream: correct media type, an immediate
  event (so clients and tests need not wait out a heartbeat), buffering
  disabled per-response, and heartbeats that actually arrive on schedule.
- `--workers 1` stays load-bearing in BOTH unit files (§0.10.3): room state
  is in-process, and two workers means two ROOMS dicts with players landing
  in different rooms — a silent break the spec pins here.
"""
import importlib
import os
import re
import sys
import time

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WEBUI = os.path.join(REPO, "webui")
for p in (WEBUI, REPO):
    if p not in sys.path:
        sys.path.insert(0, p)


@pytest.fixture()
def stream_client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import arena_rooms
    importlib.reload(arena_rooms)
    app = FastAPI()
    app.include_router(arena_rooms.router)
    return TestClient(app), arena_rooms


def test_heartbeat_stays_under_the_outer_proxy_cliff():
    import arena_rooms
    assert arena_rooms.SSE_HEARTBEAT_S < 60, (
        "SSE_HEARTBEAT_S must stay under the outer nginx-proxy's 60 s idle "
        "default (SPEC_PET_ARENA_ROOMS §5.2) or every stream dies mid-race "
        "in production only")


def test_probe_is_an_event_stream_with_an_immediate_event(stream_client, monkeypatch):
    client, arena_rooms = stream_client
    # Shrink the probe: closing a TestClient stream drains the generator, and
    # the real one runs STREAM_PROBE_MAX_S of wall clock.
    monkeypatch.setattr(arena_rooms, "SSE_HEARTBEAT_S", 0.05)
    monkeypatch.setattr(arena_rooms, "STREAM_PROBE_MAX_S", 0.15)
    with client.stream("GET", "/api/arena/stream-probe") as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        assert r.headers["x-accel-buffering"] == "no"
        first = next(r.iter_text())
        assert "event: probe" in first
        assert str(arena_rooms.SSE_HEARTBEAT_S) in first


def test_heartbeats_arrive_on_schedule(stream_client, monkeypatch):
    client, arena_rooms = stream_client
    monkeypatch.setattr(arena_rooms, "SSE_HEARTBEAT_S", 0.05)
    monkeypatch.setattr(arena_rooms, "STREAM_PROBE_MAX_S", 0.3)
    started = time.monotonic()
    with client.stream("GET", "/api/arena/stream-probe") as r:
        body = "".join(r.iter_text())
    elapsed = time.monotonic() - started
    assert body.count(": heartbeat") >= 3
    assert elapsed < 5


def test_workers_1_is_pinned_in_both_unit_files():
    for unit in ("deploy/datspet-backend.service",
                 "deploy/datspet-staging-backend.service"):
        path = os.path.join(REPO, unit)
        if not os.path.exists(path):
            continue
        text = open(path).read()
        exec_lines = [l for l in text.splitlines() if l.startswith("ExecStart")]
        assert exec_lines, f"{unit}: no ExecStart"
        assert any(re.search(r"--workers\s+1\b", l) for l in exec_lines), (
            f"{unit}: --workers 1 is LOAD-BEARING (SPEC_PET_ARENA_ROOMS "
            "§2.1) — JOBS and ROOMS are in-process state; two workers means "
            "players silently landing in different rooms")
