"""Arena rooms — live multi-device racing (SPEC_PET_ARENA_ROOMS).

R0 ships the TRANSPORT PROOF, not the game: §11 orders infrastructure first
because two of the spec's three risks are proxy behaviour that cannot be
observed on a dev box (§5 — the inner nginx buffers SSE to death without
`proxy_buffering off`, and the outer proxy kills idle streams at its 60 s
default). The stream probe below is what `scripts/verify_deployment.sh`
holds open for 90+ seconds against the real deployed URL — past the outer
proxy's cliff — before any room code is written over the transport.

The canonical story (owner, 2026-08-02): a user calls her friend on DatsMe —
"I challenge you to a race" — the friend signs into DatsPet, they meet in an
agreed room, and the room lives exactly as long as the contest. Ephemeral by
design (§0.7): rooms die on finish + idle timeout, reaped by the maintenance
thread that already exists (§2.4). Like a LiveKit room, minus the media
server: mint, meet, compete, evaporate.

R1 adds create/join/lobby, R2 the race itself (§11). Room state will be the
`JOBS`-shaped in-memory dict on this single-worker process (§2.1) — which is
why `--workers 1` stays load-bearing (§0.10.3, pinned by test).
"""
from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/api/arena")

# §8 — named values; no literal reaches a call site. The room constants are
# declared with the module so R1/R2 build on the reviewed numbers, not fresh
# guesses.
ROOM_CODE_BYTES = 8            # secrets.token_urlsafe → ~11 chars, unguessable (§6)
ROOM_MAX_PLAYERS = 5           # the owner's configurable 1–5
ROOM_IDLE_TTL_S = 900
ROOM_RESULT_TTL_S = 300
ROOM_TICK_HZ = 10              # broadcast rate (§3.2)
ROOM_REPLAY_BUFFER_EVENTS = 600  # Last-Event-ID ring buffer (§3.2)
IMPULSE_BATCH_MS = 200         # client-side batching (§3.3)
MAX_IMPULSE_RATE_HZ = 10       # the plausible-rate clamp (§7)

# §5.2 — MUST stay under the outer proxy's 60 s idle default. This value is
# set by infrastructure, not taste: the outer nginx-proxy vhost has no
# proxy_read_timeout, so its 60 s default cuts any stream that goes quiet
# longer than this. Pinned by test_arena_stream.py.
SSE_HEARTBEAT_S = 15

# The probe outlives the deployment gate's 90 s hold (§10) and then closes
# on its own — it exists to be measured, not to accumulate connections.
STREAM_PROBE_MAX_S = 150


async def _probe_stream():
    """An SSE body shaped exactly like the future room stream (§3.2): one
    immediate event, then heartbeat comment lines. The immediate event lets
    a unit test read the stream without waiting out a heartbeat interval."""
    started = time.monotonic()
    yield f"event: probe\ndata: {{\"heartbeat_s\": {SSE_HEARTBEAT_S}}}\n\n"
    while time.monotonic() - started < STREAM_PROBE_MAX_S:
        await asyncio.sleep(SSE_HEARTBEAT_S)
        yield ": heartbeat\n\n"


@router.get("/stream-probe")
def arena_stream_probe():
    """R0's whole surface: hold this open through both nginx layers. The
    deployment check asserts a heartbeat arrives AND the stream is still
    open past 90 s — the outer proxy's 60 s cliff is invisible anywhere
    but the real deployed URL."""
    return StreamingResponse(
        _probe_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store",
            # Belt over the nginx location's braces: X-Accel-Buffering
            # disables buffering per-response even if the location block
            # is ever lost in a conf rewrite (§5.1).
            "X-Accel-Buffering": "no",
        },
    )
