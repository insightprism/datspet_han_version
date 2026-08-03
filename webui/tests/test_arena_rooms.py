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

from conftest import ANON_OWNER, anon_cookies, make_pet  # noqa: E402


@pytest.fixture()
def rooms(dpp_env):
    """Router-only app over the per-test DB — entering a pet is owner-scoped
    (F1), so every create/join seeds a pet the caller can see and carries the
    anon cookie."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import arena_rooms
    importlib.reload(arena_rooms)
    arena_rooms.db = dpp_env["db"]
    arena_rooms.owner_scope = importlib.import_module("owner_scope")
    app = FastAPI()
    app.include_router(arena_rooms.router)
    client = TestClient(app, cookies=anon_cookies())
    client._db = dpp_env["db"]
    return client, arena_rooms


def seed_pet(client, pet_id, owner=ANON_OWNER):
    make_pet(client._db, pet_id=pet_id, external_user_id=owner)
    return pet_id


def make_room(client, max_players=3, **over):
    body = {"event_key": "hurdles", "challenge_key": "arithmetic",
            "difficulty": "sums_10", "pet_id": "roomhostpet0",
            "pet_label": "Kenji Girl", "max_players": max_players, **over}
    if not client._db.get_pet(body["pet_id"]):
        make_pet(client._db, pet_id=body["pet_id"], external_user_id=ANON_OWNER)
    r = client.post("/api/arena/rooms", json=body)
    assert r.status_code == 200
    return r.json()


def join(client, code, pet_id, **over):
    seed_pet(client, pet_id)
    return client.post(f"/api/arena/rooms/{code}/join",
                       json={"pet_id": pet_id, **over})


def test_create_join_capacity_and_lifecycle(rooms):
    client, _ = rooms
    made = make_room(client, max_players=3)
    code = made["code"]
    assert made["room"]["state"] == "lobby"
    assert made["room"]["players"][0]["is_host"] is True

    for i in (1, 2):
        r = join(client, code, f"seededpet{i}", pet_label=f"Pet {i}")
        assert r.status_code == 200
    full = join(client, code, "seededpetX")
    assert full.status_code == 409
    seed_pet(client, "seededpetN")
    assert client.post("/api/arena/rooms/nope/join",
                       json={"pet_id": "seededpetN"}).status_code == 404

    snap = client.get(f"/api/arena/rooms/{code}").json()["room"]
    assert [p["pet_label"] for p in snap["players"]] == \
        ["Kenji Girl", "Pet 1", "Pet 2"]
    # Tokens never leave the server (§6).
    assert "token" not in json.dumps(snap)


def test_only_the_host_starts_and_lobby_closes(rooms):
    client, _ = rooms
    made = make_room(client)
    code = made["code"]
    joined = join(client, code, "hostgatepet1").json()

    r = client.post(f"/api/arena/rooms/{code}/start",
                    json={"token": joined["player_token"]})
    assert r.status_code == 403
    r = client.post(f"/api/arena/rooms/{code}/start",
                    json={"token": made["host_token"]})
    assert r.status_code == 200
    assert r.json()["room"]["state"] == "countdown"
    assert r.json()["room"]["countdown_ends_at"] is not None
    # The lobby is closed to newcomers the moment the countdown exists.
    late = join(client, code, "latepet00001")
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
        t = threading.Thread(target=lambda: join(
            client, code, "streampet001", pet_label="Late Pet"))
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
    join(client, code, "replaypet001")         # seq 2
    join(client, code, "replaypet002")         # seq 3

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


# ---------------------------------------------------------------------------
# R2 — racing (§3.3, §3.4, §7) and the room-scoped assets (§4.3)
# ---------------------------------------------------------------------------

def _start_racing(client, arena_rooms, code, host_token):
    r = client.post(f"/api/arena/rooms/{code}/start", json={"token": host_token})
    assert r.status_code == 200
    with arena_rooms.ROOMS_LOCK:
        arena_rooms.ROOMS[code].countdown_ends_at = time.time() - 0.001
    snap = client.get(f"/api/arena/rooms/{code}").json()["room"]
    assert snap["state"] == "racing"


def test_impulses_gate_clamps_and_referee_ticks(rooms):
    client, arena_rooms = rooms
    made = make_room(client, event_key="sprint_100")
    code, host_token = made["code"], made["host_token"]

    # Not racing yet — impulses 409.
    r = client.post(f"/api/arena/rooms/{code}/impulses",
                    json={"token": host_token, "impulses": [{"at": 100}]})
    assert r.status_code == 409
    _start_racing(client, arena_rooms, code, host_token)

    # A stranger token 403s.
    assert client.post(f"/api/arena/rooms/{code}/impulses",
                       json={"token": "nope", "impulses": []}).status_code == 403

    # §7: impulses spaced under 1/MAX_IMPULSE_RATE_HZ are discarded and the
    # player flagged; out-of-window timestamps never count.
    gap = 1000.0 / arena_rooms.MAX_IMPULSE_RATE_HZ
    batch = [{"at": 0.0}, {"at": gap / 4}, {"at": gap + 1},
             {"at": -50.0}, {"at": 10_000_000.0}]
    r = client.post(f"/api/arena/rooms/{code}/impulses",
                    json={"token": host_token, "impulses": batch})
    body = r.json()
    assert body["accepted"] == 2          # 0.0 and gap+1
    assert body["rate_flagged"] is True

    # The tick broadcasts referee positions computed by the AUTHORITATIVE
    # integrator — bit-identical to calling it directly.
    assert arena_rooms.tick_racing_rooms() == 1
    with arena_rooms.ROOMS_LOCK:
        room = arena_rooms.ROOMS[code]
        frame = [f for _, f in room.events if "event: tick" in f][-1]
        payload = json.loads(frame.split("data: ", 1)[1])
        from pet_factory import athletics
        expected = athletics.simulate_entrant(
            room.event, room.players[host_token].stats,
            room.players[host_token].handicap,
            room.players[host_token].impulses, room.question_seed, 0)
    pos = payload["positions"][0]
    assert pos["distance_m"] == round(expected["distance_m"], 2)
    assert pos["rate_flagged"] is True


def test_time_limit_ends_the_race_with_authoritative_standings(rooms):
    client, arena_rooms = rooms
    made = make_room(client, event_key="sprint_100")
    code, host_token = made["code"], made["host_token"]
    j = join(client, code, "rivalpet0001", pet_label="Rival").json()
    _start_racing(client, arena_rooms, code, host_token)

    # Host covers ground; the rival never answers.
    client.post(f"/api/arena/rooms/{code}/impulses",
                json={"token": host_token,
                      "impulses": [{"at": i * 500.0} for i in range(10)]})
    with arena_rooms.ROOMS_LOCK:
        arena_rooms.ROOMS[code].countdown_ends_at = \
            time.time() - arena_rooms.ROOMS[code].event["time_limit_s"] - 1
    arena_rooms.tick_racing_rooms()

    snap = client.get(f"/api/arena/rooms/{code}").json()["room"]
    assert snap["state"] == "finished"
    with arena_rooms.ROOMS_LOCK:
        room = arena_rooms.ROOMS[code]
        frame = [f for _, f in room.events if "event: result" in f][-1]
    standings = json.loads(frame.split("data: ", 1)[1])["standings"]
    assert [p["pet_label"] for p in standings][0] == "Kenji Girl"
    assert standings[0]["distance_m"] > standings[1]["distance_m"]
    # A finished room reaps after ROOM_RESULT_TTL_S.
    with arena_rooms.ROOMS_LOCK:
        arena_rooms.ROOMS[code].finished_at = \
            time.time() - arena_rooms.ROOM_RESULT_TTL_S - 1
    assert arena_rooms.sweep_rooms() == 1


def test_rooms_host_racing_events_only(rooms):
    client, _ = rooms
    r = client.post("/api/arena/rooms", json={
        "event_key": "long_jump", "challenge_key": "arithmetic",
        "difficulty": "sums_10", "pet_id": "p1"})
    assert r.status_code == 422
    assert "racing events only" in r.json()["detail"]


def test_room_assets_capability_is_membership_not_ownership(rooms):
    client, arena_rooms = rooms
    made = make_room(client)
    code = made["code"]
    # The READ is unscoped (§4.3): a caller with NO cookies at all — a link
    # spectator — fetches an entered pet's assets.
    from fastapi.testclient import TestClient
    anon = TestClient(client.app)
    r = anon.get(f"/api/arena/rooms/{code}/pets/roomhostpet0/sheet.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert "no-cache" in r.headers["cache-control"]
    r = anon.get(f"/api/arena/rooms/{code}/pets/roomhostpet0/manifest.json")
    assert r.status_code == 200
    # A pet NOT entered 404s — even one that exists and the caller owns.
    seed_pet(client, "notinroom001")
    assert anon.get(
        f"/api/arena/rooms/{code}/pets/notinroom001/sheet.png").status_code == 404
    # And there is NO zip route — watching a race is not taking the pet.
    assert anon.get(
        f"/api/arena/rooms/{code}/pets/roomhostpet0/zip").status_code == 404


def test_entering_a_pet_you_cannot_see_404s(rooms):
    """F1 — the capability is closed at the ENTRANCE: naming someone else's
    pet id (published to every spectator) must not seat it, on create or on
    join, so a room can never launder asset access to a pet the caller could
    not already fetch."""
    client, arena_rooms = rooms
    make_pet(client._db, pet_id="victimpet001", external_user_id="user-victim")

    r = client.post("/api/arena/rooms", json={
        "event_key": "sprint_100", "challenge_key": "arithmetic",
        "difficulty": "sums_10", "pet_id": "victimpet001"})
    assert r.status_code == 404

    code = make_room(client)["code"]
    r = client.post(f"/api/arena/rooms/{code}/join",
                    json={"pet_id": "victimpet001"})
    assert r.status_code == 404

    # A cookie-less caller cannot enter ANY owned pet.
    from fastapi.testclient import TestClient
    anon = TestClient(client.app)
    r = anon.post("/api/arena/rooms", json={
        "event_key": "sprint_100", "challenge_key": "arithmetic",
        "difficulty": "sums_10", "pet_id": "roomhostpet0"})
    assert r.status_code == 404


def test_room_records_its_host_owner_and_never_serializes_it(rooms):
    """Lounge seam (§2.2 there): the room knows who opened it, for scoping
    admin-ish actions — and no public view ever carries it."""
    client, arena_rooms = rooms
    made = make_room(client)
    with arena_rooms.ROOMS_LOCK:
        assert arena_rooms.ROOMS[made["code"]].host_owner == ANON_OWNER
    assert "host_owner" not in json.dumps(made["room"])
    assert arena_rooms.room_is_alive(made["code"]) is True
    assert arena_rooms.room_is_alive("nope") is False


def test_late_arrival_sees_standings_in_the_snapshot(rooms):
    """The result must not be a one-shot event: a viewer arriving after the
    finish (or a client that reconnected fresh) reads the standings off any
    snapshot for the RESULT_TTL window."""
    client, arena_rooms = rooms
    made = make_room(client, event_key="sprint_100")
    code, host_token = made["code"], made["host_token"]
    assert made["room"]["standings"] is None
    _start_racing(client, arena_rooms, code, host_token)
    with arena_rooms.ROOMS_LOCK:
        arena_rooms.ROOMS[code].countdown_ends_at = \
            time.time() - arena_rooms.ROOMS[code].event["time_limit_s"] - 1
    arena_rooms.tick_racing_rooms()
    snap = client.get(f"/api/arena/rooms/{code}").json()["room"]
    assert snap["state"] == "finished"
    assert snap["standings"] is not None
    assert snap["standings"][0]["pet_label"] == "Kenji Girl"
