# SPEC_PET_ARENA_ROOMS — a room five players can race in, and anyone can watch

**Status: Rev.5 (2026-08-03) — R0–R3 BUILT, DEPLOYED TO STAGING, VERIFIED E2E.** R0: transport
proven (stream survives both proxies 95 s; verify_deployment §7 is the permanent gate). R1:
create/join/lobby — lobbies fill live across devices. R2: the race — batched impulses up, 10 Hz
authoritative ticks down, the server referee (`simulate_entrant`, fixture-pinned) publishes
standings; §7's two clamps and the §4.3 room-scoped asset routes (membership is the capability;
sheet+manifest only). R3: the spectator URL — `/arena/{code}` serves the watch shell via nginx
(quoted-brace regex; see deploy §E 2026-08-03), anonymous viewers stream the race live, and the
standings ride every snapshot for the RESULT_TTL window so late arrivals see who won. E2E: a
browser player raced a scripted rival and lost fairly (referee-scored); two scripted racers were
spectated anonymously on staging start to standings. Remaining: R4 (team events in rooms), §14
owner calls (14.4 spectator questions — currently NOT shown), and the prod deploy on request.
The venue's SOCIAL layer — who is visible/challengeable, and where communication lives — is
`SPEC_PET_ARENA_VENUE` (Rev.1); rooms stay the contest it mints.

> ### Rev.5 — the players are any DatsMe user, not only children
>
> The owner, correcting the framing Rev.1–Rev.4 carried: the field of five is **any DatsMe users —
> adults, teenagers, children, anyone**. This spec was written as though every racer were a child,
> and that was never the product. Two friends agreeing on a room code over a DatsMe call (Rev.3)
> are as likely to be adults as kids.
>
> **What changed: the prose, and nothing else.** No constant moves. The two numbers that read as
> though they had been tuned for children were not: `MAX_IMPULSE_RATE_HZ` (§7, §8) is sized by the
> top of genuine *tapping* (SPEC_PET_ARENA §8.6), which no adult exceeds either, and the §8.5 mash
> guard only gets safer as the knowing player gets faster.
>
> **What did NOT change: §6.** The safety floor stays exactly as written — unguessable codes, no
> listing, no player names, no chat. Only its justification moves: from *"the players are
> children"* to *"the room mints a link anyone can forward, and nothing on the server knows how old
> the person opening it is."* A surface that may seat a nine-year-old is designed for the
> nine-year-old regardless of who else is in the lobby, so a wider audience is a reason to keep
> that floor rather than to loosen it. §13's tripwires stand unchanged.

> ### Rev.3 — the owner's go, and the story the product is for
>
> > "A user at his home can call her friend (using DatsMe of course), and say I challenge you to a
> > race. She signs on to DatsPet, and goes into an agreed-upon room and has the contest. You can
> > make the room service just as long as the game ends… it is almost like a LiveKit chat: it
> > produces a room, people go in there to chat — but in this case, people go into the room and
> > compete against each other."
>
> Three things this confirms, all already in the design: rooms are **ephemeral** (§0.7 — the room
> lives exactly as long as the contest plus a short results window); there is a **caretaker** (§2.4
> — the reaper on the existing maintenance thread is "the person that takes care of that"); and the
> LiveKit analogy is the architecture minus the media server — mint a room, meet by code, compete,
> evaporate. The challenge itself travels over DatsMe (a call), not over anything this spec builds —
> the room code is just something friends tell each other.

> ### Rev.2 — the pre-build review: three corrections and a lobby field, no design change
>
> The review that produced `SPEC_PET_ARENA.md` Rev.6 turned up four things here:
>
> 1. **The `Last-Event-ID` replay buffer is bounded** (§3.2, §8). Rev.1 promised replay of missed
>    events without bounding the history that implies — the one unbounded memory growth in the
>    design. A per-room ring buffer (`ROOM_REPLAY_BUFFER_EVENTS`) caps it; a client further behind
>    gets a state snapshot instead.
> 2. **Endpoint URLs are minted in `web/src/lib/api.ts`** (§4.2), the project's one-adapter rule.
>    The transport client owns lifecycle — batching, reconnection, `Last-Event-ID` — never URLs.
> 3. **§9.1 placed events in `web/src/arena/`** — stale against SPEC_PET_ARENA §6.1a, which this
>    spec's own server-authority design depends on. Corrected.
> 4. **The handicap** (SPEC_PET_ARENA §8.3.1, new there) is set by the host in the lobby, broadcast
>    to everyone before the countdown, and applied by the same integrator (§2.2).

**Companion to `SPEC_PET_ARENA.md`, not part of it.** That spec owns the *game* — events,
qualification, stats, challenges, the impulse stream. This one owns the *session* — how five devices
share one race, how a stranger watches it over a URL, and what has to change on the box for that to
work. Different concerns, different change cadence, different specs.

**Where this came from.** The owner:

> "So 5 people (configurable 1–5) can play at the same time with their own devices, and you need to
> make a room that allows for playing that is viewable by everyone. We may even turn that into a URL
> so visitors can go to the URL and watch in real time."

**This is SPEC_PET_ARENA §11's tripwire firing**, written before it was needed and quoted here
because it names the whole problem: *"the moment results are shared… client-computed stats stop being
adequate and the simulation has to move server-side."*

**The one-line summary of the design:** the room is a `JOBS`-shaped in-memory dict on a
single-worker FastAPI process; players POST batched impulses; everyone reads one SSE stream. **No
WebSocket, no Redis, no new database table.**

**The headline risk is not the code — it is two nginx layers**, and one of them has already cost this
project a day (§5). Read §5 before estimating this.

---

## §0 The decisions

| # | Decision | Choice |
|---|---|---|
| 0.1 | Where room state lives | **In memory, on the single backend process** — the `JOBS`/`JOBS_LOCK` pattern that already exists (§2.1). No table, no Redis. |
| 0.2 | Transport down (server → clients) | **SSE**, one stream per viewer, with heartbeats (§3.2). Not WebSocket (§3.1). |
| 0.3 | Transport up (players → server) | **Batched POST**, ~200 ms of impulses per request, each impulse carrying its own timestamp (§3.3). |
| 0.4 | Who is authoritative | **The server**, from the impulse log. Clients render their own pet optimistically and reconcile (§3.4). |
| 0.5 | Spectators | **Read-only, by unguessable URL, no account** (§4). They receive the same stream players do, minus the ability to send. |
| 0.6 | Asset access for pets you do not own | **A room-scoped route**, alive only while the room is (§4.3). `_scope_clause` is not widened. |
| 0.7 | Room lifetime | **Ephemeral.** A room dies with the process and on idle timeout. Nothing is persisted, so nothing is lost (§2.4). |
| 0.8 | Safety on a shareable link | **Unguessable codes, no listing, no player names by default, short lifetimes** (§6). Players are any DatsMe user; the floor is set by the youngest one who could be in the room, not the average one. |
| 0.9 | Cheating | **Bounded, not eliminated** — the no-DRM posture, plus a plausible-rate clamp (§7). |

### 0.10 The posture that must not change

1. **The game does not learn about rooms.** Events, challenges and stats consume an impulse stream
   (SPEC_PET_ARENA §7.1) and must never ask whether it came from a local player, a bot, or the
   network. If an event file ever imports anything from this spec's modules, the boundary has broken.
2. **Solo and hot-seat play keep working with the server switched off.** Rooms are additive; players
   sharing one sofa and one device need no network.
3. **`--workers 1` is a load-bearing precondition**, not an implementation detail (§2.1).
4. **No new SQLite table.** A room is transient state, and the store is for things that outlive a
   request.

---

## §1 What this needs that does not exist

Honest inventory. Everything below is new.

| | State today |
|---|---|
| WebSocket usage anywhere in the tree | **none** |
| SSE / `text/event-stream` usage | **none** |
| Any real-time push to a browser | **none** — every surface is request/response or polled (`/api/job`) |
| Multi-client shared session state | **none** |
| Unauthenticated access to a pet asset | `store_preview` only (`webui/pet_store.py:65`), and that is deliberately public inventory |
| nginx `Upgrade`/`Connection` headers | **absent** (`deploy/nginx-default.conf`) |
| nginx `proxy_buffering off` | **absent** — and SSE does not work without it (§5.1) |

Two things that **do** exist and carry most of the design:

- **`JOBS` + `JOBS_LOCK`** (`webui/app.py`) — an in-memory dict of live objects guarded by a lock,
  polled by clients, on a process that is pinned to one worker. A room is the same shape.
- **`bundle_tokens`** (`webui/db.py:132`) — the precedent for time-boxed, capability-style access to
  bytes a caller would not otherwise be allowed to fetch.

---

## §2 The room

### 2.1 In memory, and why that is right rather than lazy

```python
ROOMS: dict[str, Room] = {}
ROOMS_LOCK = threading.Lock()
```

The deployment already pins the backend to one process, and says so in the unit file
(`deploy/datspet-backend.service:9`): *"`--workers 1` is REQUIRED, not tuning… `JOBS`/`JOBS_LOCK` are
in-memory and the SQLite store uses a single module-level connection."*

So shared in-process state is not a compromise here — it is the established architecture, with a
guard already written down. A room is `JOBS` with more members.

**What this buys:** no Redis, no pub/sub, no serialization, no new dependency, no new failure mode,
and a race that reads and writes state in microseconds.

**What it costs, stated plainly:** a backend restart ends every live race, and the design cannot
scale past one box. Both are acceptable for a room that exists for the length of one race, and both
are recorded in §13 as the tripwire for revisiting.

**If `--workers 1` is ever lifted, this design breaks silently** — two workers means two `ROOMS`
dicts and players randomly landing in different rooms. That constraint is already load-bearing for
`JOBS`; this makes it more so, and §12 pins it with a test that reads the unit file.

### 2.2 Shape

```python
@dataclass
class Room:
    code: str                     # unguessable, the URL segment (§6.1)
    host_owner: Optional[str]     # who opened it; scoping for admin actions only
    event_key: str                # SPEC_PET_ARENA §6.1
    challenge_key: str            # §8.1 there
    difficulty: str
    question_seed: int            # ONE seed for the room — §8.3 there, the fairness rule
    max_players: int              # 1–5, the owner's configurable field size
    players: dict[str, Player]    # join token → player
    state: str                    # lobby | countdown | racing | finished
    started_at: Optional[float]
    last_activity_at: float       # idle reaping (§2.4)
    seq: int                      # monotonic, the SSE event id (§3.2)
```

A `Player` carries their entrant (one pet, or a team — SPEC_PET_ARENA §6.5), their **handicap**
(SPEC_PET_ARENA §8.3.1 — set by the host in the lobby, broadcast to everyone before the countdown,
applied by the same integrator), their accumulated impulse log, and their current position.
**Nothing here is a new domain concept**: an entrant, a handicap, an impulse and a position are all
the game spec's vocabulary.

### 2.3 Lifecycle

`lobby` → `countdown` → `racing` → `finished`, and the transitions are the obvious ones. Two rules
worth stating because they are where this kind of thing goes wrong:

- **The countdown is server-timed and broadcast**, never client-timed. Five devices starting on their
  own clocks is five different races.
- **A race ends when every player finishes or the event's time limit expires.** A player who wanders
  off must not hold four others hostage; the event declares the limit and the room enforces it.

### 2.4 Death

- **Idle timeout** — no impulse and no join for `ROOM_IDLE_TTL_S` (default 15 min) and the room is
  reaped.
- **Finished timeout** — a `finished` room lingers `ROOM_RESULT_TTL_S` (default 5 min) so everyone
  can read the result, then goes.
- **Process restart** — everything dies. Acceptable: nothing here is a possession, and a re-race
  costs nothing.

Reaping runs on the maintenance thread that already exists (`webui/app.py`, the DPP retry drain and
transient sweep), not a new one.

---

## §3 Transport

### 3.1 Why not WebSocket

WebSocket is the instinctive answer and it is the wrong one **for this box**:

- It needs `proxy_set_header Upgrade` / `Connection "upgrade"` on **both** nginx layers (§5), and the
  outer one is not in this repo.
- It is a second protocol with its own reconnection, backpressure and lifecycle semantics, in a
  codebase that has never shipped one.
- It buys bidirectional low latency, and **only one direction needs to be fast.** A player's own pet
  can be rendered locally the instant they answer (§3.4); nobody needs sub-100 ms fidelity on someone
  else's pet.

SSE plus POST gets the same product on infrastructure that is one directive away from supporting it,
using two things every browser and proxy already understands.

**Tripwire:** if a future event needs true bidirectional real-time — a tug-of-war, a pet that reacts
to another pet mid-race — revisit. Racing does not.

### 3.2 Down: one SSE stream, with heartbeats

```
GET /api/arena/rooms/{code}/stream        → text/event-stream
```

Players and spectators subscribe to the same stream; the only difference is that a spectator cannot
POST. Events carry the room's monotonic `seq` as the SSE event id, so a reconnecting client sends
`Last-Event-ID` and the server replays what it missed.

**Broadcast at a fixed tick (`ROOM_TICK_HZ`, default 10), not per impulse.** Five players answering
three times a second is 15 events/s; a 10 Hz tick carrying every position is smaller, smoother, and
bounded regardless of how fast the players get.

**Heartbeats every `SSE_HEARTBEAT_S` (default 15) are not optional** — they are what keeps the outer
proxy from killing the stream (§5.2). A comment line is enough.

**Replay is served from a bounded ring buffer** (Rev.2). The room keeps the last
`ROOM_REPLAY_BUFFER_EVENTS` broadcast events (§8 — a minute of race at the default tick). A
reconnecting client whose `Last-Event-ID` is still inside the buffer gets the gap replayed; one
further behind gets a **full state snapshot** instead — which is also what a fresh subscriber gets
on connect. Without the bound, event history is the one thing in a room that grows without limit,
and a long race with a wedged client would grow it invisibly.

### 3.3 Up: batched POST, timestamps in the payload

```
POST /api/arena/rooms/{code}/impulses
{ "token": "...", "impulses": [{ "at": 1712.4, "quality": 1.0 }, …] }
```

One request per `IMPULSE_BATCH_MS` (default 200), carrying whatever the player produced in that
window. **Each impulse carries its own client timestamp**, which SPEC_PET_ARENA §7.4 already
requires for replay — so batching costs no fidelity: the server reconstructs the true timeline from
the timestamps, not from arrival order.

This matters more than it sounds. Un-batched, five players answering fast is ~15 requests/second
through a rate-limited nginx location (§5.3), and the game would degrade exactly when it got
exciting.

### 3.4 Authority, and the one thing clients do locally

**The server is authoritative.** It holds every impulse log, applies the pet's exchange rate
(SPEC_PET_ARENA §2.3), and computes positions and the result.

**This is only affordable because events are data** (SPEC_PET_ARENA §6.1a). The server reads the same
`athletics/events/*.json` declaration the browser does and runs one generic integrator over it — there
is no per-event Python and no second copy of the game rules. **Rooms therefore host Tier-1 events
only**; the procedural jump events stay solo/hot-seat until someone needs them networked. A shared
race-vector fixture keeps the two integrators from drifting.

**A player's own pet advances locally the instant they answer**, before the server has heard about
it. Without that the game feels broken — a correct answer must move something *now*. The server's
next tick reconciles; because both sides run the same arithmetic over the same impulses, the
correction is normally zero and always small.

Other players' pets are rendered purely from the stream. A 100 ms lag on a rival's position is
invisible in a race that lasts a minute.

**The result is the server's, always.** Whatever a client drew, the finish order comes off the
authoritative log — which is the entire reason this spec exists.

---

## §4 Surfaces

### 4.1 Routes

All under `webui/arena_rooms.py`, one router, the `pet_store.py` / `motion_admin.py` pattern.

| route | who | what |
|---|---|---|
| `POST /api/arena/rooms` | signed-in or anon owner | create; returns `{code, host_token}` |
| `POST /api/arena/rooms/{code}/join` | anyone with the code | join with an entrant; returns `{player_token}`; 409 when full or racing |
| `POST /api/arena/rooms/{code}/start` | host token only | lobby → countdown |
| `POST /api/arena/rooms/{code}/impulses` | player token | §3.3 |
| `GET /api/arena/rooms/{code}/stream` | anyone with the code | §3.2 — players and spectators alike |
| `GET /api/arena/rooms/{code}/pets/{petId}/sheet.png` | anyone with the code | §4.3 |
| `GET /arena/{code}` | anyone with the code | the page; renders player or spectator UI depending on whether the browser holds a player token |

**One URL for playing and watching** — the owner's *"turn that into a URL so visitors can go to the
URL and watch."* A visitor without a token watches; a visitor who joins plays. No second link to
share, no mode to explain.

### 4.2 The frontend

`web/src/arena/room/` — the transport client, the lobby, and the spectator view. **`web/src/arena/`
game code is untouched**: the room hands the same impulse stream to the same event simulator
(§0.10.1).

**Endpoint URLs are minted in `web/src/lib/api.ts`** (Rev.2), the project's one-adapter rule —
including the `EventSource` URL for §3.2's stream. The transport client here owns *lifecycle*:
batching (§3.3), reconnection, `Last-Event-ID` bookkeeping, the player token. If a URL string ever
appears in `web/src/arena/room/`, the adapter rule has broken.

### 4.3 Serving assets for pets you do not own

A spectator must render five pets they have no claim to. Today `/api/pets/{id}/sheet.png` is
owner-scoped and served `Cache-Control: private` (`webui/app.py`), and **widening `_scope_clause` is
explicitly forbidden** — SPEC_PET_STORE §1.2 calls it *"exactly the bug the exact-match fix
removed."*

So the room mints its own access instead: **a room-scoped asset route** that serves the sheet for a
pet **currently entered in that room**, to any caller holding the room code, for as long as the room
lives. The pet's owner scope is never consulted and never widened; membership in a live room is the
capability, exactly as `bundle_tokens` makes a one-time download the capability for the DPP pull.

Two rules:

- **Sheet and manifest only.** Never `bundle_zip` — watching a race is not a licence to take the pet.
- **Dies with the room.** No lingering public URL for anyone's pet after the race.

---

## §5 The deployment seam — read this before estimating

**Every deploy failure in this project so far has been a false green** (CLAUDE.md), and the two
incidents most relevant to this feature were both proxies. This section is the risk.

### 5.1 SSE does not work behind nginx without `proxy_buffering off`

`deploy/nginx-default.conf`'s `/(api|partner|launch)` block sets `proxy_http_version 1.1` and
`proxy_read_timeout 300`, but **not** `proxy_buffering off`. Without it nginx buffers the response
and the browser receives nothing until the buffer flushes — the race appears frozen and then jumps.
It looks like an application bug and it is not.

The stream route needs its own `location` block with buffering off.

### 5.2 The OUTER proxy will cut the stream at ~60 s

This one is already documented from a previous incident: the outer `nginx-proxy` vhost has **no
`proxy_read_timeout`**, so it uses the 60 s default — which is what produced a 504 at 60.2 s on a
cold typed-animal draw. **A race lasts minutes. An SSE stream would be cut mid-race.**

`proxy_read_timeout` is an *idle* timeout and resets on every byte, so **§3.2's heartbeat is the
fix**, not a nicety: a comment line every 15 s keeps the connection alive through both layers with no
change to the outer proxy at all. That is the main reason SSE-with-heartbeats beats WebSocket here —
it needs nothing from the layer this repo does not own.

Belt and braces: `EventSource` reconnects automatically, and §3.2's `Last-Event-ID` replay means a
drop costs a frame, not a race.

### 5.3 The rate limiter will throttle the impulse stream

The `/(api|partner|launch)` block carries `limit_req zone=datspet_api burst=20 nodelay`. Five players
POSTing every 200 ms is 25 req/s sustained — it would be throttled, and the failure would look like
lag rather than a 429 in anyone's face.

Impulse and stream routes need **their own `location` block and their own zone**, sized for the tick
rate rather than for a human clicking Generate.

### 5.4 And the repo's own trap

`deploy/nginx-default.conf` **is production's** — it hardcodes `:19954`. Copying it onto staging
silently points staging at the production backend. This is written in CLAUDE.md because it cost a
day. Every nginx change in this spec touches both files, and `scripts/verify_deployment.sh <url>` is
the gate that counts.

---

## §6 A link anyone can open, and the floor that sets

Players are **any DatsMe user** — adults, teenagers, children, whoever holds the code. The room
cannot tell which, and it produces a link that can be forwarded past everyone who was meant to have
it. Those two facts together, not an assumption about anyone's age, are what these rules answer.

**The floor is set by the youngest player who could be in the room.** A surface that may seat a
nine-year-old is designed for the nine-year-old regardless of who else is in the lobby — so a wider
audience is a reason to keep every rule below, never a reason to relax one. Nothing here costs an
adult anything.

- **Codes are unguessable** — `secrets.token_urlsafe`, ≥ 64 bits, never sequential, never derived
  from a pet id, an owner id or a timestamp. A guessable code is a stranger in the room.
- **Rooms are never listed.** No index, no directory, no "public rooms" surface, no search. The only
  way in is a link somebody chose to share.
- **No player names by default.** A player is their pet. If a display name is ever added it is
  chosen per room, not drawn from the DatsMe profile, and never persisted — nobody's real name
  should be reachable from a link forwarded to a group chat, and least of all a minor's.
- **Rooms are short-lived** (§2.4). A shared link stops working, which is the correct default for
  something forwarded to people the host did not choose.
- **Spectators cannot act.** No sending, no joining mid-race without the code, no chat. **There is no
  chat in this design and adding one is a different product** with a different duty of care (§13).
- **The pet is the only thing shown.** Not the owner, not the house, not the pet's design provenance
  block — a bundle carries the designer's typed words (SPEC_PET_DESIGN_PROVENANCE), and a spectator
  view has no business rendering them.

**Tripwire:** the first request for chat, for public room listings, or for persistent room history.
Each one changes what this feature is, and none should be added by extension.

---

## §7 Cheating, bounded

The no-DRM posture holds (SPEC_PET_ARENA §11): a player can edit their own bundle's stats, and the
server reads the stats their device sent.

Two cheap bounds, and deliberately nothing more:

- **A plausible-rate clamp.** Impulses arriving faster than `MAX_IMPULSE_RATE_HZ` (default 10/s — far
  above any human answering arithmetic, and at the top of genuine tapping) are discarded, and the
  player is flagged in the room's own state. This catches the obvious script without pretending to
  be anti-cheat.
- **Timestamps are clamped to the race window.** An impulse dated before the start or after the
  finish does not count.

**Do not build more.** The value being protected is a friendly race; the cost of real integrity
(server-side stat resolution, signed bundles, replay validation) exceeds it by a wide margin, and
SPEC_PET_OWNER_FIELD §0.1 already made this argument once for a thing worth actual money.

---

## §8 Named values

In `webui/arena_rooms.py`, per CLAUDE.md — no literal reaches a call site.

```
ROOM_CODE_BYTES        = 8       # secrets.token_urlsafe → ~11 chars, unguessable (§6)
ROOM_MAX_PLAYERS       = 5       # the owner's configurable 1–5
ROOM_IDLE_TTL_S        = 900
ROOM_RESULT_TTL_S      = 300
ROOM_TICK_HZ           = 10      # broadcast rate (§3.2)
ROOM_REPLAY_BUFFER_EVENTS = 600  # Last-Event-ID ring buffer — one minute at ROOM_TICK_HZ; older gaps get a snapshot (§3.2)
SSE_HEARTBEAT_S        = 15      # MUST stay under the outer proxy's 60 s (§5.2)
IMPULSE_BATCH_MS       = 200     # client-side batching (§3.3)
MAX_IMPULSE_RATE_HZ    = 10      # the clamp (§7)
```

`SSE_HEARTBEAT_S` carries a comment naming §5.2. It is the one constant here whose value is set by
infrastructure rather than by taste, and someone will eventually "tidy" it upward.

---

## §9 The four test questions

1. **Will adding a new variant require an engine change?** No. A new Tier-1 event is a JSON
   declaration in `pet_factory/athletics/events/` (SPEC_PET_ARENA §6.1a) — which is precisely what
   lets the room server score it with no new Python — and a new challenge is a file in
   `web/src/arena/challenges/`; the room stores `event_key`/`challenge_key` as opaque strings and
   never interprets them.
2. **Will adding a feature require touching unrelated files?** No. One new backend module, one new
   frontend directory, one new nginx location block. `app.py` gains a router registration; `db.py` is
   untouched; the designer, store, DPP adapter and pet runtime are untouched.
3. **Will a third-party integration require modifying owned code paths?** No. DatsMe is not involved
   at all — a room is a partner-side surface over pets that already exist.
4. **Will a bug in one variant force debugging shared code?** Mostly no, with one honest exception:
   **the transport is genuinely shared** — every event runs over the same SSE stream. A transport bug
   affects every event at once. That is inherent to having one transport, and the mitigation is that
   it is thin (§3) and its failure modes are §5's, not the game's.

---

## §10 Guard tests

**`webui/tests/test_arena_rooms.py`**

- Create → join × 5 → the sixth join **409s**; `max_players` is enforced server-side, not by the UI.
- Join with an unknown code 404s; join a `racing` room 409s.
- **Only the host token may start.** A player token 403s.
- **One question seed per room:** two players' generated sequences are identical (the fairness rule,
  SPEC_PET_ARENA §8.3, now across devices where it actually matters).
- **Handicaps are broadcast before the countdown and applied in the authoritative result**
  (SPEC_PET_ARENA §8.3.1) — every player and spectator can see them, because a hidden handicap is
  the failure §8.3 there forbids.
- **The rate clamp** discards impulses above `MAX_IMPULSE_RATE_HZ` and keeps the rest.
- **Out-of-window timestamps** are dropped.
- Idle reaping removes a room past `ROOM_IDLE_TTL_S`; a finished room survives `ROOM_RESULT_TTL_S`
  and then does not.
- **The asset route serves sheet and manifest for an entered pet, and 404s for a pet not in the
  room** — including a pet the caller *does* own, because the room is the capability, not ownership.
- **The asset route never serves `bundle_zip`** (§4.3). A separate assertion, because "add the zip
  route for convenience" is the obvious future mistake.
- **`_scope_clause` is unchanged** — extend `test_scoping.py` rather than trusting a review.

**`webui/tests/test_arena_stream.py`**

- The stream emits a heartbeat within `SSE_HEARTBEAT_S` on an idle room. **This is the §5.2 test and
  it is the most valuable one here** — it fails on a box where somebody raised the heartbeat above
  the outer proxy's timeout, which is otherwise a bug that only appears in production, only after a
  minute, and only to whoever is watching.
- `Last-Event-ID` replays missed events and does not replay delivered ones; an id older than the
  ring buffer yields a **state snapshot, not an unbounded replay**, and the buffer never holds more
  than `ROOM_REPLAY_BUFFER_EVENTS` (§3.2).
- A spectator (no player token) receives the stream and is **403ed on POST**.

**Deployment (`scripts/verify_deployment.sh`, extended)**

- Open a stream against the **real deployed URL** and assert a heartbeat arrives, then assert the
  stream is **still open after 90 seconds** — past the outer proxy's 60 s. Per CLAUDE.md, every deploy
  failure so far has been a false green, and this is the one check that would catch §5.2 in the
  environment where it actually bites.

---

## §11 Rollout

| Phase | Ships | Notes |
|---|---|---|
| **R0** | nginx location blocks (stream + impulses), on **staging first**, with the §10 deployment check | Infrastructure before code. If §5 cannot be made to work, everything after this is wasted. |
| **R1** | Room create/join/lobby, no racing — five devices in a lobby seeing each other appear | Proves the transport end to end with no game logic involved |
| **R2** | Racing: impulses, ticks, authoritative result. **Tier-1 events only** (SPEC_PET_ARENA §6.1a) — the server scores with one generic integrator over the event's JSON declaration; no per-event Python. | The feature |
| **R3** | Spectator URL + room-scoped assets | The watchable part |
| **R4** | Team events in rooms (SPEC_PET_ARENA §6.5) | After solo rooms are proven |

**R0 first, and on staging, is not process for its own sake.** Two of the three risks in this spec
are proxy behaviour that cannot be observed locally — the outer proxy does not exist on a dev box.
Prove the stream survives 90 seconds on a real deployed URL before writing the game loop over it.

---

## §12 Deliberately not done

- **No WebSocket** (§3.1). Revisit only for genuinely bidirectional gameplay.
- **No Redis, no external broker, no second process.** In-memory on one worker (§2.1) until a
  measured reason exists.
- **No persisted rooms, results, records or history.** Nothing survives a restart, on purpose. This
  is also what keeps §6 simple: there is no archive of anyone's races to protect.
- **No chat, no reactions, no emoji, no room listing** (§6). Each is a different product with a
  different duty of care.
- **No cross-household pet borrowing.** A player enters pets from their own house; the store adopt
  path already exists for wanting someone else's.
- **No scaling beyond one box.** §13's tripwire.
- **No anti-cheat beyond §7's two clamps.**
- **No spectator interaction of any kind** — no voting, no cheering, no influence on the race.

---

## §13 Tripwires

- **`--workers 1` is lifted** → this design breaks silently, with players landing in different rooms.
  Whoever lifts it owns moving room state out of process.
- **Rooms outgrow one box** — measured concurrent rooms, not imagined ones. The move is a broker and
  it is a real project. *Measured 2026-08-03 (review follow-up): the ticker's referee pass costs
  ~4.3 ms per room per 100 ms tick at the worst realistic log size (~900 impulses/lane × 5 unfinished
  lanes), all under `ROOMS_LOCK` — the ceiling is therefore **~20 concurrently racing rooms** before
  the ticker falls behind and impulse POSTs contend. That is the number that fires this tripwire.*
- **Anyone asks for persistent results, leaderboards or records** → that is the *other* half of
  SPEC_PET_ARENA §11's tripwire, and it needs a table, a retention decision, and a fresh look at §6
  now that named players' performance would be stored — including minors', which is the case that
  sets the retention answer.
- **The first request for chat or public room listings** (§6). *Fired 2026-08-02 — the owner asked
  for permanent listed rooms with presence and invitations. Answered as the tripwire demands: a
  separate product with its own duty-of-care review, [`SPEC_PET_ARENA_LOUNGE`](SPEC_PET_ARENA_LOUNGE.md)
  (Rev.1, owner review pending). Race rooms here stay ephemeral and unlisted; the lounge mints them.*
- **An event needs bidirectional real-time** (§3.1).

---

## §14 Open questions for the owner

**14.1 Does the spectator URL need to work for someone with no DatsPet account at all?** Assumed
**yes** — *"visitors can go to the URL and watch"* reads as a link you send to a grandparent. That is
what makes §4.3's room-scoped asset route necessary. Confirm, because "signed-in viewers only" would
simplify it considerably.

**14.2 Who may start a race — the host only, or a ready-check?** Recommend **host only** for v1: one
player opens the room and starts it, which matches how people actually organise a game among friends
and needs no consensus protocol. A ready-check is nicer and can come later.

**14.3 What happens when a player disconnects mid-race?** Recommend their pet **stops where it is**
and the race continues; they can rejoin with the same token and resume answering. The alternatives —
pausing everyone, or pretending they are still answering — are worse for the other four. Worth
confirming, since it is visible and will happen constantly on phones and tablets.

**14.4 Should a spectator see the questions?** Showing them makes watching genuinely fun — a
spectator can play along from the sofa instead of just watching bars move, and it is what makes the
room worth opening a link for. Recommend **yes**, with the answers hidden until someone gets one.
This is a small feature with a large effect on what the room feels like from outside.

**14.5 One room per user, or many?** No limit is proposed. If rooms are ever abused as free hosting
this becomes a rate-limit question, but there is no reason to solve it before it exists.
