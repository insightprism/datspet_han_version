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
import json
import secrets
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from fastapi import APIRouter, Body, HTTPException, Request
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

# Server-timed countdown (§2.3): five devices starting on their own clocks is
# five different races. Matches the solo arena's COUNTDOWN_SECONDS.
ROOM_COUNTDOWN_S = 3

# A pet label on a lobby card — pet names cap at 24 chars plus a surname.
ROOM_PET_LABEL_MAX = 48


# ---------------------------------------------------------------------------
# R1 — the room store (§2). The JOBS pattern: in-memory dicts of live objects
# under one lock, on a process pinned to --workers 1 (§2.1, test-pinned).
# ---------------------------------------------------------------------------

@dataclass
class RoomPlayer:
    token: str                 # capability; never serialized to other clients
    pet_id: str
    pet_label: str             # "Kenji Girl" — the only identity shown (§6)
    handicap_name: str
    is_host: bool
    joined_at: float
    impulses: list = field(default_factory=list)   # R2


@dataclass
class Room:
    code: str
    host_token: str
    event_key: str             # opaque here (§9.1) — the game interprets it
    challenge_key: str
    difficulty: str
    question_seed: int         # ONE seed per room — the fairness rule (§8.3)
    max_players: int
    players: dict[str, RoomPlayer] = field(default_factory=dict)
    state: str = "lobby"       # lobby | countdown | racing | finished
    created_at: float = 0.0
    countdown_ends_at: Optional[float] = None
    finished_at: Optional[float] = None
    last_activity_at: float = 0.0
    seq: int = 0
    # Ring buffer of (seq, sse_frame) for Last-Event-ID replay (§3.2, Rev.2).
    events: deque = field(default_factory=lambda: deque(maxlen=ROOM_REPLAY_BUFFER_EVENTS))
    # Live subscribers: (event_loop, asyncio.Queue). POST handlers run in the
    # threadpool, streams in the event loop — call_soon_threadsafe bridges.
    subscribers: list = field(default_factory=list)


ROOMS: dict[str, Room] = {}
ROOMS_LOCK = threading.Lock()


def _now() -> float:
    return time.time()


def _advance_state(room: Room) -> None:
    """Lazy countdown → racing transition: the gun time was broadcast when the
    host started, so no timer thread is needed — any reader past the gun sees
    (and records) the racing state."""
    if room.state == "countdown" and room.countdown_ends_at is not None \
            and _now() >= room.countdown_ends_at:
        room.state = "racing"


def _snapshot(room: Room) -> dict:
    """The public view — tokens never leave the server; players are their
    pets (§6)."""
    _advance_state(room)
    return {
        "code": room.code,
        "state": room.state,
        "event_key": room.event_key,
        "challenge_key": room.challenge_key,
        "difficulty": room.difficulty,
        "question_seed": room.question_seed,
        "max_players": room.max_players,
        "countdown_ends_at": room.countdown_ends_at,
        "server_now": _now(),
        "players": [
            {"pet_id": p.pet_id, "pet_label": p.pet_label,
             "handicap_name": p.handicap_name, "is_host": p.is_host}
            for p in sorted(room.players.values(), key=lambda p: p.joined_at)
        ],
    }


def _sse_frame(seq: int, event: str, data: dict) -> str:
    return f"id: {seq}\nevent: {event}\ndata: {json.dumps(data)}\n\n"


def _broadcast(room: Room, event: str, data: dict) -> None:
    """Called under ROOMS_LOCK. Stamps the room's monotonic seq, records the
    frame in the replay ring, and wakes every live stream."""
    room.seq += 1
    frame = _sse_frame(room.seq, event, data)
    room.events.append((room.seq, frame))
    for loop, queue in room.subscribers:
        loop.call_soon_threadsafe(queue.put_nowait, frame)


def _get_room(code: str) -> Room:
    room = ROOMS.get(code)
    if room is None:
        raise HTTPException(status_code=404, detail="no such room")
    return room


def _clean_label(label: object) -> str:
    text = " ".join(str(label or "").split())[:ROOM_PET_LABEL_MAX]
    return text or "A mystery pet"


def sweep_rooms(now: Optional[float] = None) -> int:
    """§2.4 — called from app.py's maintenance loop every tick. Idle rooms and
    long-finished rooms are reaped; subscribers get a room_closed event and
    their streams end."""
    now = _now() if now is None else now
    reaped = 0
    with ROOMS_LOCK:
        for code in list(ROOMS):
            room = ROOMS[code]
            _advance_state(room)
            idle = now - room.last_activity_at > ROOM_IDLE_TTL_S
            done = room.finished_at is not None \
                and now - room.finished_at > ROOM_RESULT_TTL_S
            if idle or done:
                _broadcast(room, "room_closed",
                           {"reason": "idle" if idle else "finished"})
                del ROOMS[code]
                reaped += 1
    return reaped


# ---------------------------------------------------------------------------
# R1 routes (§4.1)
# ---------------------------------------------------------------------------

@router.post("/rooms")
def create_room(payload: dict = Body(...)):
    """Create a room and enter it as host. Returns the code friends share and
    the host's token (which IS their player token)."""
    max_players = payload.get("max_players", ROOM_MAX_PLAYERS)
    if not isinstance(max_players, int) or not 1 <= max_players <= ROOM_MAX_PLAYERS:
        raise HTTPException(status_code=422,
                            detail=f"max_players must be 1..{ROOM_MAX_PLAYERS}")
    for key in ("event_key", "challenge_key", "difficulty", "pet_id"):
        if not payload.get(key):
            raise HTTPException(status_code=422, detail=f"{key} is required")

    code = secrets.token_urlsafe(ROOM_CODE_BYTES)
    host_token = secrets.token_urlsafe(16)
    now = _now()
    host = RoomPlayer(
        token=host_token, pet_id=str(payload["pet_id"]),
        pet_label=_clean_label(payload.get("pet_label")),
        handicap_name=str(payload.get("handicap_name") or "none"),
        is_host=True, joined_at=now)
    room = Room(
        code=code, host_token=host_token,
        event_key=str(payload["event_key"]),
        challenge_key=str(payload["challenge_key"]),
        difficulty=str(payload["difficulty"]),
        question_seed=secrets.randbits(31),
        max_players=max_players,
        created_at=now, last_activity_at=now)
    room.players[host_token] = host
    with ROOMS_LOCK:
        ROOMS[code] = room
        _broadcast(room, "player_joined",
                   {"pet_label": host.pet_label, "room": _snapshot(room)})
    return {"code": code, "host_token": host_token, "room": _snapshot(room)}


@router.post("/rooms/{code}/join")
def join_room(code: str, payload: dict = Body(...)):
    if not payload.get("pet_id"):
        raise HTTPException(status_code=422, detail="pet_id is required")
    with ROOMS_LOCK:
        room = _get_room(code)
        _advance_state(room)
        if room.state != "lobby":
            raise HTTPException(status_code=409, detail="race already starting")
        if len(room.players) >= room.max_players:
            raise HTTPException(status_code=409, detail="room is full")
        token = secrets.token_urlsafe(16)
        player = RoomPlayer(
            token=token, pet_id=str(payload["pet_id"]),
            pet_label=_clean_label(payload.get("pet_label")),
            handicap_name=str(payload.get("handicap_name") or "none"),
            is_host=False, joined_at=_now())
        room.players[token] = player
        room.last_activity_at = _now()
        _broadcast(room, "player_joined",
                   {"pet_label": player.pet_label, "room": _snapshot(room)})
        return {"player_token": token, "room": _snapshot(room)}


@router.post("/rooms/{code}/start")
def start_room(code: str, payload: dict = Body(...)):
    """Host only (§10). The countdown is server-timed and broadcast — five
    devices starting on their own clocks is five different races (§2.3)."""
    with ROOMS_LOCK:
        room = _get_room(code)
        _advance_state(room)
        if payload.get("token") != room.host_token:
            raise HTTPException(status_code=403, detail="only the host starts the race")
        if room.state != "lobby":
            raise HTTPException(status_code=409, detail="already started")
        room.state = "countdown"
        room.countdown_ends_at = _now() + ROOM_COUNTDOWN_S
        room.last_activity_at = _now()
        _broadcast(room, "countdown", {"room": _snapshot(room)})
        return {"room": _snapshot(room)}


@router.get("/rooms/{code}")
def room_snapshot(code: str):
    with ROOMS_LOCK:
        return {"room": _snapshot(_get_room(code))}


# ---------------------------------------------------------------------------
# R1 — the stream (§3.2). Players and spectators read the same stream; only
# POSTs are token-gated.
# ---------------------------------------------------------------------------

async def _room_stream(code: str, last_event_id: Optional[int]):
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    with ROOMS_LOCK:
        room = ROOMS.get(code)
        if room is None:
            yield _sse_frame(0, "room_closed", {"reason": "gone"})
            return
        subscriber = (loop, queue)
        room.subscribers.append(subscriber)
        # Reconnect inside the ring → replay the gap. Fresh (or too far
        # behind) → a state snapshot (§3.2 Rev.2).
        replay: list[str] = []
        if last_event_id is not None and room.events \
                and room.events[0][0] <= last_event_id + 1:
            replay = [f for s, f in room.events if s > last_event_id]
        else:
            replay = [_sse_frame(room.seq, "snapshot", {"room": _snapshot(room)})]
    try:
        for frame in replay:
            yield frame
        while True:
            try:
                frame = await asyncio.wait_for(queue.get(), timeout=SSE_HEARTBEAT_S)
                yield frame
                if "event: room_closed" in frame:
                    return
            except asyncio.TimeoutError:
                yield ": heartbeat\n\n"
                with ROOMS_LOCK:
                    if code not in ROOMS:
                        return
    finally:
        with ROOMS_LOCK:
            live = ROOMS.get(code)
            if live is not None and subscriber in live.subscribers:
                live.subscribers.remove(subscriber)


@router.get("/rooms/{code}/stream")
def room_stream(request: Request, code: str, last_event_id: Optional[str] = None):
    # EventSource reconnects with a Last-Event-ID HEADER; the query param is
    # the curl/test convenience. Header wins when both are present.
    raw = request.headers.get("last-event-id", last_event_id)
    parsed: Optional[int] = None
    if raw is not None:
        try:
            parsed = int(raw)
        except ValueError:
            parsed = None
    return StreamingResponse(
        _room_stream(code, parsed),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


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
