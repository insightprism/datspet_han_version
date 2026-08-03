"""Arena rooms R1 (SPEC_PET_ARENA_ROOMS §2, §3.2, §4.1) — create/join/lobby.

What each case protects (§10's R1 subset):
- capacity is enforced server-side (the sixth join 409s), unknown codes 404,
  and a room past its lobby refuses joins — the UI is never the gate;
- only the host token starts the race; a player token 403s;
- ONE question seed per room, carried in every snapshot — the fairness rule
  (SPEC_PET_ARENA §8.3) across devices, where it actually matters;
- tokens never leak: no serialized player object carries one;
- the stream: a fresh subscriber gets a snapshot, a live subscriber sees a
  join the moment it happens, a reconnect inside the ring replays exactly
  the gap, and one behind the ring gets a snapshot instead (§3.2 Rev.2);
- the reaper closes idle rooms (streams get room_closed; the code 404s).
"""
import asyncio
import importlib
import json
import os
import sys
import threading
import time

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WEBUI = os.path.join(REPO, "webui")
for p in (WEBUI, REPO):
    if p not in sys.path:
        sys.path.insert(0, p)


@pytest.fixture()
def rooms():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import arena_rooms
    importlib.reload(arena_rooms)
    app = FastAPI()
    app.include_router(arena_rooms.router)
    return TestClient(app), arena_rooms


def make_room(client, max_players=3, **over):
    body = {"event_key": "hurdles", "challenge_key": "arithmetic",
            "difficulty": "sums_10", "pet_id": "pet0",
            "pet_label": "Kenji Girl", "max_players": max_players, **over}
    r = client.post("/api/arena/rooms", json=body)
    assert r.status_code == 200
    return r.json()


def test_create_join_capacity_and_lifecycle(rooms):
    client, _ = rooms
    made = make_room(client, max_players=3)
    code = made["code"]
    assert made["room"]["state"] == "lobby"
    assert made["room"]["players"][0]["is_host"] is True

    for i in (1, 2):
        r = client.post(f"/api/arena/rooms/{code}/join",
                        json={"pet_id": f"pet{i}", "pet_label": f"Pet {i}"})
        assert r.status_code == 200
    full = client.post(f"/api/arena/rooms/{code}/join", json={"pet_id": "petX"})
    assert full.status_code == 409
    assert client.post("/api/arena/rooms/nope/join",
                       json={"pet_id": "p"}).status_code == 404

    snap = client.get(f"/api/arena/rooms/{code}").json()["room"]
    assert [p["pet_label"] for p in snap["players"]] == \
        ["Kenji Girl", "Pet 1", "Pet 2"]
    # Tokens never leave the server (§6).
    assert "token" not in json.dumps(snap)


def test_only_the_host_starts_and_lobby_closes(rooms):
    client, _ = rooms
    made = make_room(client)
    code = made["code"]
    joined = client.post(f"/api/arena/rooms/{code}/join",
                         json={"pet_id": "p1"}).json()

    r = client.post(f"/api/arena/rooms/{code}/start",
                    json={"token": joined["player_token"]})
    assert r.status_code == 403
    r = client.post(f"/api/arena/rooms/{code}/start",
                    json={"token": made["host_token"]})
    assert r.status_code == 200
    assert r.json()["room"]["state"] == "countdown"
    assert r.json()["room"]["countdown_ends_at"] is not None
    # The lobby is closed to newcomers the moment the countdown exists.
    late = client.post(f"/api/arena/rooms/{code}/join", json={"pet_id": "p2"})
    assert late.status_code == 409
    # And the countdown lapses into racing without any timer thread.
    _, arena_rooms = rooms
    with arena_rooms.ROOMS_LOCK:
        arena_rooms.ROOMS[code].countdown_ends_at = time.time() - 1
    assert client.get(f"/api/arena/rooms/{code}").json()["room"]["state"] == "racing"


def test_one_seed_per_room_and_it_travels(rooms):
    client, _ = rooms
    a = make_room(client)
    b = make_room(client)
    assert isinstance(a["room"]["question_seed"], int)
    assert a["room"]["question_seed"] != b["room"]["question_seed"]
    snap = client.get(f"/api/arena/rooms/{a['code']}").json()["room"]
    assert snap["question_seed"] == a["room"]["question_seed"]


def _collect(gen, n):
    """Pull n frames from the async stream generator, then close it."""
    async def run():
        frames = []
        try:
            for _ in range(n):
                frames.append(await asyncio.wait_for(gen.__anext__(), timeout=5))
        finally:
            await gen.aclose()
        return frames
    return asyncio.run(run())


def test_fresh_subscriber_gets_snapshot_then_live_events(rooms):
    client, arena_rooms = rooms
    code = make_room(client)["code"]

    async def run():
        gen = arena_rooms._room_stream(code, None)
        first = await asyncio.wait_for(gen.__anext__(), timeout=5)
        assert "event: snapshot" in first
        # A join lands from another thread while the stream is live — the
        # exact production shape (POSTs in the threadpool, stream on the loop).
        t = threading.Thread(target=lambda: client.post(
            f"/api/arena/rooms/{code}/join",
            json={"pet_id": "p9", "pet_label": "Late Pet"}))
        t.start()
        frame = await asyncio.wait_for(gen.__anext__(), timeout=5)
        t.join()
        assert "event: player_joined" in frame
        assert "Late Pet" in frame
        await gen.aclose()
    asyncio.run(run())


def test_reconnect_replays_the_gap_or_snapshots(rooms):
    client, arena_rooms = rooms
    code = make_room(client)["code"]           # seq 1: host joined
    client.post(f"/api/arena/rooms/{code}/join", json={"pet_id": "p1"})  # seq 2
    client.post(f"/api/arena/rooms/{code}/join", json={"pet_id": "p2"})  # seq 3

    frames = _collect(arena_rooms._room_stream(code, 1), 2)
    assert [f.splitlines()[0] for f in frames] == ["id: 2", "id: 3"]

    # Older than the ring holds → a snapshot, never an unbounded replay.
    with arena_rooms.ROOMS_LOCK:
        room = arena_rooms.ROOMS[code]
        while room.events and room.events[0][0] < 3:
            room.events.popleft()
    frames = _collect(arena_rooms._room_stream(code, 1), 1)
    assert "event: snapshot" in frames[0]


def test_idle_rooms_are_reaped_and_streams_told(rooms):
    client, arena_rooms = rooms
    code = make_room(client)["code"]
    with arena_rooms.ROOMS_LOCK:
        arena_rooms.ROOMS[code].last_activity_at = \
            time.time() - arena_rooms.ROOM_IDLE_TTL_S - 1
    assert arena_rooms.sweep_rooms() == 1
    assert client.get(f"/api/arena/rooms/{code}").status_code == 404
    # The closing broadcast is in the ring the moment before deletion — a
    # subscriber connected at reap time receives room_closed and ends.
    frames = _collect(arena_rooms._room_stream(code, None), 1)
    assert "room_closed" in frames[0]
