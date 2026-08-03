"""Arena lounges (SPEC_PET_ARENA_LOUNGE §3, §4, §5, §10) — presence,
challenges, the racing board.

What each case protects:
- the §3.1 gate: no anonymous presence, EVER — an anon cookie and a bare
  browser both 401; a race room would admit both, a lounge must not;
- the pet is the identity (§3.2): no serialized presence carries an owner id
  or a capability token, and you can only show a pet from YOUR house;
- one lounge at a time (§14.4), and re-entering replaces rather than clones;
- the challenge card is a CLOSED schema (§4.1): unknown fields 422, only
  racing events, only a present target, never yourself;
- accept mints an ordinary ephemeral room (host = challenger, tagged with
  the lounge) and each half gets exactly its own seat — the challenger's
  token is released only to the presence that issued the card (§4.2);
- the board lists lounge-minted rooms only and forgets them when the room
  dies; private code-shared rooms never appear (§5);
- the sweeper (§2.3): silent presence leaves, unanswered challenges
  evaporate quietly, and nothing survives it that the TTLs say is dead;
- the stream opens with a full snapshot, and a wedged subscriber is dropped
  rather than grown (the rooms pattern, §3.3).
"""
import asyncio
import importlib
import json
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WEBUI = os.path.join(REPO, "webui")
for p in (WEBUI, REPO):
    if p not in sys.path:
        sys.path.insert(0, p)

from conftest import anon_cookies, launch_cookies, make_pet  # noqa: E402

USER_A = "lounge-user-a"
USER_B = "lounge-user-b"


@pytest.fixture()
def lounges(dpp_env):
    """Router-only app over the per-test DB, with BOTH arena modules reloaded
    (the lounge mints rooms through arena_rooms) and rebound to the temp DB."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import arena_rooms
    import arena_lounges
    importlib.reload(arena_rooms)
    importlib.reload(arena_lounges)
    for mod in (arena_rooms, arena_lounges):
        mod.db = dpp_env["db"]
        mod.owner_scope = importlib.import_module("owner_scope")
    app = FastAPI()
    app.include_router(arena_rooms.router)
    app.include_router(arena_lounges.router)
    client = TestClient(app)
    client._db = dpp_env["db"]
    return client, arena_lounges, arena_rooms


def seed_user_pet(client, pet_id, user_id, label="Kenji Girl"):
    make_pet(client._db, pet_id=pet_id, external_user_id=user_id,
             display_name=label)
    return pet_id


def enter(client, user_id, pet_id, lounge_id="lounge_1", label="Kenji Girl",
          seed=True):
    if seed:
        seed_user_pet(client, pet_id, user_id, label=label)
    return client.post(f"/api/arena/lounges/{lounge_id}/enter",
                       json={"pet_id": pet_id, "pet_label": label},
                       cookies=launch_cookies(user_id))


def make_challenge(client, lounge_id, token, to_presence, **over):
    return client.post(f"/api/arena/lounges/{lounge_id}/challenge",
                       json={"token": token, "to": to_presence,
                             "event_key": "hurdles",
                             "challenge_key": "arithmetic",
                             "difficulty": "sums_10", **over})


# ---------------------------------------------------------------------------
# §3.1 — the signed-in gate
# ---------------------------------------------------------------------------

def test_lounges_refuse_anonymous_and_bare_browsers(lounges):
    client, _, _ = lounges
    make_pet(client._db, pet_id="anonownedpet", external_user_id=None)
    body = {"pet_id": "anonownedpet"}
    # An anonymous browser (the id a race room would happily seat) — 401.
    r = client.post("/api/arena/lounges/lounge_1/enter", json=body,
                    cookies=anon_cookies())
    assert r.status_code == 401
    # No cookie at all — the middleware-less router resolves to None — 401.
    assert client.post("/api/arena/lounges/lounge_1/enter",
                       json=body).status_code == 401
    # And nobody entered on either refusal.
    snap = client.get("/api/arena/lounges/lounge_1").json()["lounge"]
    assert snap["present"] == []


def test_entering_requires_a_pet_from_your_own_house(lounges):
    client, _, _ = lounges
    seed_user_pet(client, "petofuserb01", USER_B)
    r = client.post("/api/arena/lounges/lounge_1/enter",
                    json={"pet_id": "petofuserb01"},
                    cookies=launch_cookies(USER_A))
    assert r.status_code == 404
    r = client.post("/api/arena/lounges/lounge_1/enter",
                    json={"pet_id": ""}, cookies=launch_cookies(USER_A))
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# §3.2 — the pet is the identity; §14.4 — one lounge at a time
# ---------------------------------------------------------------------------

def test_presence_serializes_pets_never_owners_or_tokens(lounges):
    client, _, _ = lounges
    entered = enter(client, USER_A, "petofusera01").json()
    assert entered["presence_token"]
    snap = client.get("/api/arena/lounges/lounge_1").json()["lounge"]
    assert [p["pet_label"] for p in snap["present"]] == ["Kenji Girl"]
    dumped = json.dumps(snap)
    assert USER_A not in dumped
    assert entered["presence_token"] not in dumped
    assert "owner" not in dumped
    # The lounge list counts heads without naming anyone.
    listing = client.get("/api/arena/lounges").json()["lounges"]
    assert {l["id"]: l["present"] for l in listing} == \
        {"lounge_1": 1, "lounge_2": 0, "lounge_3": 0}


def test_one_lounge_at_a_time_and_reenter_replaces(lounges):
    client, _, _ = lounges
    enter(client, USER_A, "petofusera01")
    # Re-entering the same lounge with another pet REPLACES, never clones.
    second = enter(client, USER_A, "petofusera02", label="Oreo Girl").json()
    snap = client.get("/api/arena/lounges/lounge_1").json()["lounge"]
    assert [p["pet_label"] for p in snap["present"]] == ["Oreo Girl"]
    # Walking into lounge 2 walks you out of lounge 1.
    enter(client, USER_A, "petofusera02", lounge_id="lounge_2", seed=False)
    assert client.get("/api/arena/lounges/lounge_1").json()["lounge"]["present"] == []
    assert len(client.get("/api/arena/lounges/lounge_2").json()["lounge"]["present"]) == 1
    # The replaced token no longer heartbeats.
    r = client.post("/api/arena/lounges/lounge_2/presence",
                    json={"token": second["presence_token"]})
    assert r.status_code == 404


def test_a_full_lounge_refuses_the_next_walk_in(lounges, monkeypatch):
    client, arena_lounges, _ = lounges
    monkeypatch.setattr(arena_lounges, "LOUNGE_MAX_PRESENT", 2)
    enter(client, USER_A, "petofusera01")
    enter(client, USER_B, "petofuserb01")
    r = enter(client, "lounge-user-c", "petofuserc01")
    assert r.status_code == 409


# ---------------------------------------------------------------------------
# §4.1 — the challenge card is a closed schema
# ---------------------------------------------------------------------------

def test_challenge_card_schema_is_closed(lounges):
    client, _, _ = lounges
    a = enter(client, USER_A, "petofusera01").json()
    b = enter(client, USER_B, "petofuserb01", label="Oreo Girl").json()
    # Free text has no field to live in (§4.1) — an unknown key is a 422.
    r = make_challenge(client, "lounge_1", a["presence_token"],
                       b["presence_id"], message="u stink")
    assert r.status_code == 422
    # Only racing events (the room referee's constraint, unchanged).
    r = make_challenge(client, "lounge_1", a["presence_token"],
                       b["presence_id"], event_key="long_jump")
    assert r.status_code == 422
    # Only someone actually present.
    r = make_challenge(client, "lounge_1", a["presence_token"], "ghost")
    assert r.status_code == 404
    # Never yourself.
    r = make_challenge(client, "lounge_1", a["presence_token"],
                       a["presence_id"])
    assert r.status_code == 422
    # Outsiders hold no presence token and cannot post cards at all.
    r = make_challenge(client, "lounge_1", "not-a-token", b["presence_id"])
    assert r.status_code == 403
    # The well-formed card lands, with an expiry the client can render.
    r = make_challenge(client, "lounge_1", a["presence_token"],
                       b["presence_id"])
    assert r.status_code == 200
    card = client.get("/api/arena/lounges/lounge_1").json()["lounge"]["challenges"][0]
    assert card["from_presence"] == a["presence_id"]
    assert card["to_presence"] == b["presence_id"]
    assert card["accepted"] is False
    assert card["expires_at"] > 0


# ---------------------------------------------------------------------------
# §4.2 — accept mints an ordinary room; each half gets exactly its own seat
# ---------------------------------------------------------------------------

def test_accept_mints_a_lounge_tagged_room_with_both_seats(lounges):
    client, _, arena_rooms = lounges
    a = enter(client, USER_A, "petofusera01").json()
    b = enter(client, USER_B, "petofuserb01", label="Oreo Girl").json()
    made = make_challenge(client, "lounge_1", a["presence_token"],
                          b["presence_id"]).json()
    cid = made["challenge_id"]

    # Only the target may accept.
    r = client.post(f"/api/arena/lounges/lounge_1/challenge/{cid}/accept",
                    json={"token": a["presence_token"]})
    assert r.status_code == 403
    accepted = client.post(
        f"/api/arena/lounges/lounge_1/challenge/{cid}/accept",
        json={"token": b["presence_token"]})
    assert accepted.status_code == 200
    seat_b = accepted.json()
    assert seat_b["my_lane"] == 1
    room = seat_b["room"]
    assert room["max_players"] == 2
    assert [p["pet_label"] for p in room["players"]] == \
        ["Kenji Girl", "Oreo Girl"]
    assert room["players"][0]["is_host"] is True   # host = the challenger

    # The minted room is an ORDINARY room: joinable surface, tagged lounge.
    with arena_rooms.ROOMS_LOCK:
        assert arena_rooms.ROOMS[room["code"]].lounge_id == "lounge_1"

    # A second accept cannot double-mint.
    again = client.post(
        f"/api/arena/lounges/lounge_1/challenge/{cid}/accept",
        json={"token": b["presence_token"]})
    assert again.status_code == 409

    # The challenger claims THEIR seat with their own presence token…
    r = client.post(f"/api/arena/lounges/lounge_1/challenge/{cid}/claim",
                    json={"token": b["presence_token"]})
    assert r.status_code == 403
    claimed = client.post(
        f"/api/arena/lounges/lounge_1/challenge/{cid}/claim",
        json={"token": a["presence_token"]})
    assert claimed.status_code == 200
    seat_a = claimed.json()
    assert seat_a["my_lane"] == 0
    assert seat_a["code"] == room["code"]
    assert seat_a["player_token"] != seat_b["player_token"]
    # …and that token really is the host's: it can start the race.
    r = client.post(f"/api/arena/rooms/{room['code']}/start",
                    json={"token": seat_a["player_token"]})
    assert r.status_code == 200

    # No lounge snapshot ever carried a room token.
    snap = client.get("/api/arena/lounges/lounge_1").json()["lounge"]
    dumped = json.dumps(snap)
    for token in (seat_a["player_token"], seat_b["player_token"]):
        assert token not in dumped


def test_accept_fails_cleanly_when_the_challenger_left(lounges):
    client, _, _ = lounges
    a = enter(client, USER_A, "petofusera01").json()
    b = enter(client, USER_B, "petofuserb01").json()
    cid = make_challenge(client, "lounge_1", a["presence_token"],
                         b["presence_id"]).json()["challenge_id"]
    client.post("/api/arena/lounges/lounge_1/leave",
                json={"token": a["presence_token"]})
    r = client.post(f"/api/arena/lounges/lounge_1/challenge/{cid}/accept",
                    json={"token": b["presence_token"]})
    assert r.status_code == 404
    # The dead card is gone, not lingering.
    assert client.get("/api/arena/lounges/lounge_1").json()["lounge"]["challenges"] == []


# ---------------------------------------------------------------------------
# §5 — the racing board
# ---------------------------------------------------------------------------

def test_board_lists_lounge_rooms_only_and_forgets_dead_ones(lounges):
    client, arena_lounges, arena_rooms = lounges
    a = enter(client, USER_A, "petofusera01").json()
    b = enter(client, USER_B, "petofuserb01", label="Oreo Girl").json()
    cid = make_challenge(client, "lounge_1", a["presence_token"],
                         b["presence_id"]).json()["challenge_id"]
    room = client.post(
        f"/api/arena/lounges/lounge_1/challenge/{cid}/accept",
        json={"token": b["presence_token"]}).json()["room"]

    # A PRIVATE code-shared room, made the ordinary way, never appears (§5).
    seed_user_pet(client, "privatepet01", USER_A, label="Private Pet")
    private = client.post("/api/arena/rooms", json={
        "event_key": "hurdles", "challenge_key": "arithmetic",
        "difficulty": "sums_10", "pet_id": "privatepet01"},
        cookies=launch_cookies(USER_A)).json()

    board = client.get("/api/arena/lounges/lounge_1").json()["lounge"]["racing"]
    assert [e["room_code"] for e in board] == [room["code"]]
    assert board[0]["pet_labels"] == ["Kenji Girl", "Oreo Girl"]
    assert board[0]["event_key"] == "hurdles"
    assert private["code"] not in json.dumps(board)

    # The room dies → the board forgets it on the next sweep.
    with arena_rooms.ROOMS_LOCK:
        del arena_rooms.ROOMS[room["code"]]
    arena_lounges.sweep_lounges()
    assert client.get("/api/arena/lounges/lounge_1").json()["lounge"]["racing"] == []


# ---------------------------------------------------------------------------
# §2.3 — the sweeper: everything evaporates on its TTL
# ---------------------------------------------------------------------------

def test_sweep_reaps_silent_presence_and_stale_challenges(lounges):
    client, arena_lounges, _ = lounges
    a = enter(client, USER_A, "petofusera01").json()
    b = enter(client, USER_B, "petofuserb01").json()
    make_challenge(client, "lounge_1", a["presence_token"], b["presence_id"])

    # Heartbeats hold you in the room across the presence TTL… (the sweep
    # moment sits past BOTH TTLs; the challenge one is the longer.)
    assert arena_lounges.CHALLENGE_TTL_S > arena_lounges.LOUNGE_PRESENCE_TTL_S
    later = arena_lounges._now() + arena_lounges.CHALLENGE_TTL_S + 1
    client.post("/api/arena/lounges/lounge_1/presence",
                json={"token": a["presence_token"]})
    with arena_lounges.LOUNGES_LOCK:
        state = arena_lounges.LOUNGES_STATE["lounge_1"]
        state.present[a["presence_token"]].last_seen_at = later - 1
    arena_lounges.sweep_lounges(now=later)
    snap = client.get("/api/arena/lounges/lounge_1").json()["lounge"]
    # …while the silent one has left, and the unanswered card evaporated
    # with the challenge TTL (quietly — kinder between children, §2.3).
    assert len(snap["present"]) == 1
    assert snap["challenges"] == []


# ---------------------------------------------------------------------------
# §3.3 — the stream: snapshot-first; a wedged subscriber is dropped
# ---------------------------------------------------------------------------

def test_stream_opens_with_a_full_snapshot(lounges):
    client, arena_lounges, _ = lounges
    enter(client, USER_A, "petofusera01")

    async def first_frame():
        gen = arena_lounges._lounge_stream("lounge_1")
        try:
            return await gen.__anext__()
        finally:
            await gen.aclose()

    frame = asyncio.run(first_frame())
    assert "event: snapshot" in frame
    payload = json.loads(frame.split("data: ", 1)[1].strip())
    assert [p["pet_label"] for p in payload["lounge"]["present"]] == ["Kenji Girl"]
    # The generator is gone from the subscriber list once closed.
    with arena_lounges.LOUNGES_LOCK:
        assert arena_lounges.LOUNGES_STATE["lounge_1"].subscribers == []


def test_a_wedged_subscriber_is_dropped_not_grown(lounges):
    client, arena_lounges, _ = lounges

    async def wedge():
        loop = asyncio.get_running_loop()
        queue = asyncio.Queue(maxsize=1)
        queue.put_nowait("wedged")   # full before the broadcast lands
        subscriber = (loop, queue)
        with arena_lounges.LOUNGES_LOCK:
            state = arena_lounges._state("lounge_1")
            state.subscribers.append(subscriber)
        enter(client, USER_A, "petofusera01")
        # Let the call_soon_threadsafe push run on this loop.
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        with arena_lounges.LOUNGES_LOCK:
            return subscriber in state.subscribers

    assert asyncio.run(wedge()) is False


# ---------------------------------------------------------------------------
# §2.1 — the lounge registry is content, guarded like every registry
# ---------------------------------------------------------------------------

def test_lounges_registry_is_well_formed(lounges):
    _, arena_lounges, _ = lounges
    assert len(arena_lounges.LOUNGES) >= 1
    for lounge_id, entry in arena_lounges.LOUNGES.items():
        assert entry["id"] == lounge_id
        assert entry["label"].strip()
        assert entry["emoji"].strip()
    labels = [e["label"] for e in arena_lounges.LOUNGES.values()]
    assert len(set(labels)) == len(labels)
