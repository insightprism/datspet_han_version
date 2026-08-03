"""Arena lounges — the permanent front door to the races (SPEC_PET_ARENA_LOUNGE).

A lounge is FURNITURE, not an event (§0.1): a fixed, shipped table of named
rooms (lounges.json) holding in-memory presence, pending challenges, and a
racing board. Accepting a challenge mints an ordinary EPHEMERAL race room
(arena_rooms.mint_room) tagged with the lounge — the owner's rule that "the
room service lasts just as long as the game ends" survives by construction.

The §6 posture, mechanically enforced here:
- signed-in DatsMe users only (§3.1) — no anonymous presence, ever; the gate
  is OwnerScope.is_anonymous, and a lounge 401s what a race room would admit;
- the pet is the identity (§3.2) — the presence list serializes pet label and
  pet id, never the owner; owner ids stay server-side for the one-lounge rule;
- nothing free-text (§4.1) — a challenge is a closed schema of key picks; an
  unknown field is rejected, not stored;
- no history (§6) — presence and challenges evaporate on TTL; a restart
  empties every lounge and loses nothing.

The SSE machinery is the rooms module's pattern COPIED, not extracted — two
instances (ROOMS, lounges) is below the three-instances bar, recorded in the
lounge spec's build notes.
"""
from __future__ import annotations

import asyncio
import json
import secrets
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import StreamingResponse

import arena_rooms
import db
import owner_scope
from pet_factory import athletics

router = APIRouter(prefix="/api/arena")

# §8 — named values; no literal reaches a call site.
LOUNGE_PRESENCE_TTL_S = 90     # missed ~3 heartbeats and you have left
LOUNGE_HEARTBEAT_S = 30        # client presence POST cadence
CHALLENGE_TTL_S = 120          # an unanswered challenge quietly expires (§2.3)
LOUNGE_MAX_PRESENT = 40        # a list a phone can render; entries past it 409
# The lounge stream reuses the rooms module's heartbeat cadence — one
# constant, one owner (§8 there): arena_rooms.SSE_HEARTBEAT_S.
# NO replay ring here, deliberately: unlike a room's tick deltas, every
# lounge event carries the FULL lounge snapshot, so a reconnect is made
# whole by the snapshot-first frame alone.


def _load_lounges() -> dict:
    return json.loads(
        (Path(__file__).parent / "lounges.json").read_text())


LOUNGES: dict = {entry["id"]: entry for entry in _load_lounges()["lounges"]}


@dataclass
class LoungePresence:
    token: str                 # capability; never serialized
    presence_id: str           # public handle challenges target
    pet_id: str
    pet_label: str             # "Kenji Girl" — the only identity shown (§3.2)
    owner_id: str              # server-side only: the one-lounge rule (§14.4)
    last_seen_at: float = 0.0


@dataclass
class Challenge:
    id: str
    from_presence: str
    to_presence: str
    event_key: str
    challenge_key: str
    difficulty: str
    created_at: float
    expires_at: float
    # Set on accept: how the CHALLENGER claims their seat (§4.2 step 3) —
    # handed out only in the claim response, never broadcast.
    room_code: Optional[str] = None
    challenger_room_token: Optional[str] = None
    challenger_lounge_token: Optional[str] = None


@dataclass
class LoungeState:
    present: dict[str, LoungePresence] = field(default_factory=dict)   # token →
    challenges: dict[str, Challenge] = field(default_factory=dict)     # id →
    racing: set = field(default_factory=set)                           # room codes
    seq: int = 0
    subscribers: list = field(default_factory=list)   # (event_loop, queue)


LOUNGES_STATE: dict[str, LoungeState] = {}
LOUNGES_LOCK = threading.Lock()


def _now() -> float:
    return time.time()


def _state(lounge_id: str) -> LoungeState:
    if lounge_id not in LOUNGES:
        raise HTTPException(status_code=404, detail="no such lounge")
    return LOUNGES_STATE.setdefault(lounge_id, LoungeState())


def _require_signed_in(request: Request) -> str:
    """§3.1 — no anonymous presence, ever. A lounge is a DISCOVERY surface:
    every listed pet must have a DatsMe owner the host can hold accountable.
    (Race rooms deliberately stay looser — a code shared between friends.)"""
    owner = owner_scope.resolve_owner_scope(request)
    if owner.owner_id is None or owner.is_anonymous:
        raise HTTPException(status_code=401,
                            detail="lounges are for signed-in DatsMe users")
    return owner.owner_id


def _sse_frame(seq: int, event: str, data: dict) -> str:
    return f"id: {seq}\nevent: {event}\ndata: {json.dumps(data)}\n\n"


def _broadcast(lounge_id: str, state: LoungeState, event: str, data: dict) -> None:
    """Called under LOUNGES_LOCK — the rooms pattern: monotonic seq, wedged
    subscribers dropped (their EventSource reconnects into a fresh snapshot)."""
    state.seq += 1
    frame = _sse_frame(state.seq, event, data)
    for subscriber in list(state.subscribers):
        loop, queue = subscriber

        def push(queue=queue, subscriber=subscriber):
            try:
                queue.put_nowait(frame)
            except asyncio.QueueFull:
                with LOUNGES_LOCK:
                    live = LOUNGES_STATE.get(lounge_id)
                    if live is not None and subscriber in live.subscribers:
                        live.subscribers.remove(subscriber)
        loop.call_soon_threadsafe(push)


def _board(state: LoungeState) -> list[dict]:
    """§5 — live lounge-minted contests, by asking the rooms module (the
    room_is_alive seam, never ROOMS under its lock). Pet names and the event;
    never a losing child's score."""
    entries = []
    for code in sorted(state.racing):
        snapshot = arena_rooms.room_snapshot_if_alive(code)
        if snapshot is None:
            continue
        entries.append({
            "room_code": code,
            "event_key": snapshot["event_key"],
            "state": snapshot["state"],
            "pet_labels": [p["pet_label"] for p in snapshot["players"]],
        })
    return entries


def _snapshot(lounge_id: str, state: LoungeState) -> dict:
    lounge = LOUNGES[lounge_id]
    return {
        "id": lounge_id,
        "label": lounge["label"],
        "emoji": lounge["emoji"],
        "present": [
            {"presence_id": p.presence_id, "pet_id": p.pet_id,
             "pet_label": p.pet_label}
            for p in sorted(state.present.values(),
                            key=lambda p: p.last_seen_at)
        ],
        "challenges": [
            {"id": c.id, "from_presence": c.from_presence,
             "to_presence": c.to_presence, "event_key": c.event_key,
             "challenge_key": c.challenge_key, "difficulty": c.difficulty,
             "accepted": c.room_code is not None,
             "expires_at": c.expires_at}
            for c in state.challenges.values()
        ],
        "racing": _board(state),
        "server_now": _now(),
    }


# ---------------------------------------------------------------------------
# The lounge list + presence (L0)
# ---------------------------------------------------------------------------

@router.get("/lounges")
def list_lounges():
    with LOUNGES_LOCK:
        return {"lounges": [
            {"id": lid, "label": entry["label"], "emoji": entry["emoji"],
             "present": len(LOUNGES_STATE.get(lid, LoungeState()).present)}
            for lid, entry in LOUNGES.items()
        ]}


@router.get("/lounges/{lounge_id}")
def lounge_snapshot(lounge_id: str):
    with LOUNGES_LOCK:
        return {"lounge": _snapshot(lounge_id, _state(lounge_id))}


@router.post("/lounges/{lounge_id}/enter")
def enter_lounge(request: Request, lounge_id: str, payload: dict = Body(...)):
    """Walk in with ONE pet. Entering again replaces your pet; entering a
    different lounge moves you (§14.4 — a child in three rooms at once reads
    as three children). The pet must be YOURS to show (§3.2 via the same
    owner-scoped read as room seating)."""
    owner_id = _require_signed_in(request)
    pet_id = str(payload.get("pet_id") or "")
    if not pet_id:
        raise HTTPException(status_code=422, detail="pet_id is required")
    row = db.get_pet_for_owner(pet_id, owner_id)
    if row is None:
        raise HTTPException(status_code=404, detail="that pet is not in your house")

    with LOUNGES_LOCK:
        state = _state(lounge_id)
        # One lounge at a time: leave everywhere else, silently.
        for other_id, other in LOUNGES_STATE.items():
            for token, presence in list(other.present.items()):
                if presence.owner_id == owner_id:
                    del other.present[token]
                    _broadcast(other_id, other, "presence_changed",
                               {"lounge": _snapshot(other_id, other)})
        if len(state.present) >= LOUNGE_MAX_PRESENT:
            raise HTTPException(status_code=409, detail="this room is full")
        presence = LoungePresence(
            token=secrets.token_urlsafe(16),
            presence_id=secrets.token_urlsafe(6),
            pet_id=pet_id,
            pet_label=arena_rooms._clean_label(payload.get("pet_label")),
            owner_id=owner_id,
            last_seen_at=_now())
        state.present[presence.token] = presence
        _broadcast(lounge_id, state, "presence_changed",
                   {"lounge": _snapshot(lounge_id, state)})
        return {"presence_token": presence.token,
                "presence_id": presence.presence_id,
                "lounge": _snapshot(lounge_id, state)}


@router.post("/lounges/{lounge_id}/presence")
def presence_heartbeat(lounge_id: str, payload: dict = Body(...)):
    with LOUNGES_LOCK:
        state = _state(lounge_id)
        presence = state.present.get(str(payload.get("token")))
        if presence is None:
            raise HTTPException(status_code=404, detail="not in this room")
        presence.last_seen_at = _now()
        return {"ok": True}


@router.post("/lounges/{lounge_id}/leave")
def leave_lounge(lounge_id: str, payload: dict = Body(...)):
    with LOUNGES_LOCK:
        state = _state(lounge_id)
        if state.present.pop(str(payload.get("token")), None) is not None:
            _broadcast(lounge_id, state, "presence_changed",
                       {"lounge": _snapshot(lounge_id, state)})
        return {"ok": True}


# ---------------------------------------------------------------------------
# Challenges (L1) — canned cards, no free text anywhere (§4.1)
# ---------------------------------------------------------------------------

CHALLENGE_FIELDS = {"token", "to", "event_key", "challenge_key", "difficulty"}


@router.post("/lounges/{lounge_id}/challenge")
def create_challenge(lounge_id: str, payload: dict = Body(...)):
    """A structured card: challenger's picks from the same closed setup
    vocabulary the arena already has. §4.1's no-free-text rule is a SCHEMA
    rule: an unknown field is a 422, not a stored string."""
    extra = set(payload) - CHALLENGE_FIELDS
    if extra:
        raise HTTPException(status_code=422,
                            detail=f"unknown fields: {sorted(extra)}")
    event = athletics.load_event(str(payload.get("event_key") or ""))
    if event is None or event.get("procedure") != "race":
        raise HTTPException(status_code=422,
                            detail="challenges are racing events only")
    with LOUNGES_LOCK:
        state = _state(lounge_id)
        challenger = state.present.get(str(payload.get("token")))
        if challenger is None:
            raise HTTPException(status_code=403, detail="not in this room")
        target = next((p for p in state.present.values()
                       if p.presence_id == str(payload.get("to"))), None)
        if target is None:
            raise HTTPException(status_code=404, detail="they have left the room")
        if target.token == challenger.token:
            raise HTTPException(status_code=422, detail="challenge someone else")
        challenge = Challenge(
            id=secrets.token_urlsafe(8),
            from_presence=challenger.presence_id,
            to_presence=target.presence_id,
            event_key=str(payload["event_key"]),
            challenge_key=str(payload["challenge_key"]),
            difficulty=str(payload["difficulty"]),
            created_at=_now(),
            expires_at=_now() + CHALLENGE_TTL_S)
        state.challenges[challenge.id] = challenge
        _broadcast(lounge_id, state, "challenge_created",
                   {"lounge": _snapshot(lounge_id, state)})
        return {"challenge_id": challenge.id,
                "lounge": _snapshot(lounge_id, state)}


def _seat_from_presence(presence: LoungePresence, is_host: bool) -> arena_rooms.RoomPlayer:
    """The lounge already verified this pet at entry; stats resolve the same
    way room seating does — the server's own copy."""
    row = db.get_pet(presence.pet_id)
    try:
        manifest = json.loads(row["manifest_json"]) if row else {}
    except (TypeError, ValueError):
        manifest = {}
    return arena_rooms.RoomPlayer(
        token=secrets.token_urlsafe(16),
        pet_id=presence.pet_id,
        pet_label=presence.pet_label,
        handicap_name="none",
        is_host=is_host,
        joined_at=_now(),
        stats=athletics.resolve_athletics(manifest, presence.pet_id),
        handicap=1.0)


@router.post("/lounges/{lounge_id}/challenge/{challenge_id}/accept")
def accept_challenge(lounge_id: str, challenge_id: str, payload: dict = Body(...)):
    """The TARGET accepts → an ordinary ephemeral race room is minted with
    both pets seated (host = challenger, §4.2), tagged with this lounge for
    the board. The response carries the ACCEPTOR's seat; the challenger
    claims theirs with their own presence token."""
    with LOUNGES_LOCK:
        state = _state(lounge_id)
        challenge = state.challenges.get(challenge_id)
        if challenge is None or challenge.expires_at < _now():
            raise HTTPException(status_code=404, detail="that challenge has expired")
        if challenge.room_code is not None:
            raise HTTPException(status_code=409, detail="already accepted")
        acceptor = state.present.get(str(payload.get("token")))
        if acceptor is None or acceptor.presence_id != challenge.to_presence:
            raise HTTPException(status_code=403, detail="this challenge is not yours")
        challenger = next((p for p in state.present.values()
                           if p.presence_id == challenge.from_presence), None)
        if challenger is None:
            del state.challenges[challenge_id]
            raise HTTPException(status_code=404, detail="they have left the room")

        event = athletics.load_event(challenge.event_key)
        if event is None:
            # The event vocabulary changed under a pending card — dissolve it.
            del state.challenges[challenge_id]
            raise HTTPException(status_code=404, detail="that event has retired")
        host = _seat_from_presence(challenger, is_host=True)
        room = arena_rooms.mint_room(
            event=event, event_key=challenge.event_key,
            challenge_key=challenge.challenge_key,
            difficulty=challenge.difficulty,
            max_players=2, host=host, host_owner=challenger.owner_id,
            lounge_id=lounge_id)
        guest = _seat_from_presence(acceptor, is_host=False)
        with arena_rooms.ROOMS_LOCK:
            room.players[guest.token] = guest
            room.last_activity_at = _now()
            arena_rooms._broadcast(room, "player_joined",
                                   {"pet_label": guest.pet_label,
                                    "room": arena_rooms._snapshot(room)})
            room_view = arena_rooms._snapshot(room)

        challenge.room_code = room.code
        challenge.challenger_room_token = room.host_token
        challenge.challenger_lounge_token = challenger.token
        state.racing.add(room.code)
        _broadcast(lounge_id, state, "challenge_accepted",
                   {"lounge": _snapshot(lounge_id, state)})
        return {"code": room.code, "player_token": guest.token,
                "my_lane": 1, "room": room_view}


@router.post("/lounges/{lounge_id}/challenge/{challenge_id}/claim")
def claim_challenge_seat(lounge_id: str, challenge_id: str,
                         payload: dict = Body(...)):
    """The CHALLENGER's half of the accept: their room seat, released only to
    the presence token that issued the challenge."""
    with LOUNGES_LOCK:
        state = _state(lounge_id)
        challenge = state.challenges.get(challenge_id)
        if challenge is None or challenge.room_code is None:
            raise HTTPException(status_code=404, detail="nothing to claim")
        if str(payload.get("token")) != challenge.challenger_lounge_token:
            raise HTTPException(status_code=403, detail="this seat is not yours")
        room_view = arena_rooms.room_snapshot_if_alive(challenge.room_code)
        if room_view is None:
            raise HTTPException(status_code=404, detail="the room is gone")
        return {"code": challenge.room_code,
                "player_token": challenge.challenger_room_token,
                "my_lane": 0, "room": room_view}


# ---------------------------------------------------------------------------
# The stream — same shape as a room's (§3.3 there)
# ---------------------------------------------------------------------------

async def _lounge_stream(lounge_id: str):
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue(
        maxsize=arena_rooms.SUBSCRIBER_QUEUE_MAX)
    with LOUNGES_LOCK:
        if lounge_id not in LOUNGES:
            yield _sse_frame(0, "lounge_closed", {"reason": "gone"})
            return
        state = _state(lounge_id)
        subscriber = (loop, queue)
        state.subscribers.append(subscriber)
        first = _sse_frame(state.seq, "snapshot",
                           {"lounge": _snapshot(lounge_id, state)})
    try:
        yield first
        while True:
            try:
                frame = await asyncio.wait_for(
                    queue.get(), timeout=arena_rooms.SSE_HEARTBEAT_S)
                yield frame
            except asyncio.TimeoutError:
                yield ": heartbeat\n\n"
                with LOUNGES_LOCK:
                    live = LOUNGES_STATE.get(lounge_id)
                    if live is None or subscriber not in live.subscribers:
                        return
    finally:
        with LOUNGES_LOCK:
            live = LOUNGES_STATE.get(lounge_id)
            if live is not None and subscriber in live.subscribers:
                live.subscribers.remove(subscriber)


@router.get("/lounges/{lounge_id}/stream")
def lounge_stream(lounge_id: str):
    return StreamingResponse(
        _lounge_stream(lounge_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Reaping (§2.3) — rides app.py's maintenance tick with the room sweep
# ---------------------------------------------------------------------------

def sweep_lounges(now: Optional[float] = None) -> int:
    """Presence past its TTL leaves; expired challenges evaporate (no
    rejection is delivered — kinder between children); board entries whose
    room died vanish. Broadcasts once per lounge that changed."""
    now = _now() if now is None else now
    swept = 0
    with LOUNGES_LOCK:
        for lounge_id, state in LOUNGES_STATE.items():
            changed = False
            for token, presence in list(state.present.items()):
                if now - presence.last_seen_at > LOUNGE_PRESENCE_TTL_S:
                    del state.present[token]
                    changed = True
            for cid, challenge in list(state.challenges.items()):
                unanswered = (challenge.room_code is None
                              and challenge.expires_at < now)
                room_gone = (challenge.room_code is not None
                             and not arena_rooms.room_is_alive(challenge.room_code))
                if unanswered or room_gone:
                    del state.challenges[cid]
                    changed = True
            for code in list(state.racing):
                if not arena_rooms.room_is_alive(code):
                    state.racing.discard(code)
                    changed = True
            if changed:
                _broadcast(lounge_id, state, "presence_changed",
                           {"lounge": _snapshot(lounge_id, state)})
                swept += 1
    return swept
