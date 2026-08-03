# SPEC_PET_ARENA_LOUNGE — permanent rooms where pets find their next race

**Status: Rev.2 (2026-08-03) — L0–L2 BUILT (local, not deployed); L3 unbuilt.** Built on "proceed"
with the §14 *recommended* answers as defaults — every one of them is content or a one-line change,
so the owner's review can still revise them cheaply. §15 records the as-built notes.

**Companion to `SPEC_PET_ARENA_ROOMS`, built on top of it, never instead of it.** That spec owns the
*contest* — an ephemeral race room that lives exactly as long as the game. This one owns the *front
door* — the permanent, named places where players discover each other, see who is racing, and mint
those contests. Different lifetimes, different safety posture, different spec.

**Where this came from.** The owner, after approving the rooms work:

> "There is an arena room which is permanent. Maybe there can be room 1, room 2, room 3… people can
> go into the room and see who is competing. They can also see a list of people who is in the room,
> and they can text or invite that person for a challenge."

**This is SPEC_PET_ARENA_ROOMS §13's tripwire firing** — "the first request for chat or public room
listings… changes what this feature is, and none should be added by extension." The tripwire's demand
was that this become its own product with its own duty-of-care review, and this spec is that review.
The race room underneath does not change at all.

**The one-line summary:** a lounge is *furniture, not an event* — a permanently-named place holding a
presence list of **pets** (never people), a "now racing" board, and a challenge button. Accepting a
challenge mints an ordinary ephemeral race room (SPEC_PET_ARENA_ROOMS) tagged with the lounge it came
from. Nothing in a lounge persists except its name.

---

## §0 The decisions (proposed — §14 holds the ones that are the owner's)

| # | Decision | Choice |
|---|---|---|
| 0.1 | What a lounge is | **Content, not state** — a fixed table of named lounges shipped as data (§2.1). Users cannot create, rename or delete lounges. |
| 0.2 | What persists | **Only the lounge definitions.** Presence, challenges and the racing board are in-memory on the single worker, exactly like `ROOMS` (§2.2). A restart empties every lounge and loses nothing. |
| 0.3 | Who may enter | **DatsMe-signed-in users only** (§3.1). No anonymous presence, ever — unlike a race room's link-spectators, a lounge is a *discovery* surface and discovery of children by strangers is the thing §6 exists to prevent. |
| 0.4 | Identity shown | **The pet, never the person** (§3.2). The presence list is "Kenji Girl, Spark Rhino…" — composed pet names, the arena's existing vocabulary. No DatsMe usernames, no avatars of people, no profile links. |
| 0.5 | Communication | **Structured challenge objects only** (§4). No chat, no free text, no DMs. "Text that person" happens on DatsMe, where conversation already lives with the host's protections. |
| 0.6 | Challenge delivery | **In-lounge only for v1** — both pets are present, so the challenge travels over the lounge's own SSE stream (§4.2). Reaching a friend who is NOT in DatsPet is a host-side channel and is honestly deferred (§4.3, §13). |
| 0.7 | The contest itself | **An ordinary SPEC_PET_ARENA_ROOMS room**, minted on acceptance, tagged `lounge_id`, listed on the lounge's racing board while it lives, watchable via its R3 spectator URL (§5). Rooms stay ephemeral; the owner's rule — "the room service lasts just as long as the game ends" — is preserved by construction. |
| 0.8 | Transport | **The R0-proven stack**: one SSE stream per lounge viewer + small POSTs. Same heartbeats, same location blocks, no new protocol (§3.3). |
| 0.9 | Presence lifetime | **Heartbeat-reaped.** A pet that stops heartbeating for `LOUNGE_PRESENCE_TTL_S` leaves the list. The reaper is the same maintenance-thread sweep the rooms spec uses (§2.3). |

### 0.10 The posture that must not change

1. **The game does not learn about lounges.** Events, challenges (the arithmetic kind), stats and the
   race integrator never ask where a room came from. `lounge_id` is an opaque tag on a room, read only
   by the lounge board.
2. **Race rooms stay exactly as SPEC_PET_ARENA_ROOMS specifies.** A lounge-minted room and a
   code-shared room are the same object; the private challenge flow (call a friend, share a code)
   keeps working with every lounge empty.
3. **No parallel social system.** Friendship, conversation, notifications and identity belong to the
   host. The lounge's entire social vocabulary is: *present*, *racing*, *challenge*, *accept*,
   *decline*.
4. **`--workers 1` remains load-bearing** — lounge presence is in-process state like `JOBS` and
   `ROOMS`, and the same pinned test covers all three.

---

## §1 What this needs that the rooms work does not already build

| | State after SPEC_PET_ARENA_ROOMS R3 |
|---|---|
| A place to discover opponents | **none** — rooms are unguessable codes shared out-of-band |
| Presence ("who is here") | **none** |
| Any surface listing pets to strangers | **none** — §6 there forbids listing *rooms*; this spec adds listing *pets*, gated by §3.1/§6 here |
| Challenge objects between users | **none** |
| A "now racing" board with watch links | **none** — R3's spectator URL exists but nothing advertises it |

Everything else — the ephemeral room, the SSE transport, the server referee, the spectator URL, the
nginx blocks, the reaper — is the rooms spec's work, already proven (R0) or already specified (R1–R3).

---

## §2 The lounge

### 2.1 Lounges are content

```
webui/lounges.json
{
  "lounges": [
    { "id": "lounge_1", "label": "Room 1", "emoji": "🥇" },
    { "id": "lounge_2", "label": "Room 2", "emoji": "🥈" },
    { "id": "lounge_3", "label": "Room 3", "emoji": "🥉" }
  ]
}
```

A fixed, shipped table — the same engine-vs-content posture as every registry in this repo. Adding a
lounge is a JSON edit; the runtime iterates whatever is there and never branches on a lounge id.
Labels are the owner's to choose (§14.1); ids are stable once minted.

Deliberately NOT user-created: user-minted permanent spaces need moderation, naming review, and an
ownership model — a different product again. Three shipped rooms is how "room 1, room 2, room 3"
stays simple.

### 2.2 Presence is in-memory state

```python
LOUNGES_STATE: dict[str, LoungeState] = {}   # lounge_id → state
LOUNGES_LOCK = threading.Lock()

@dataclass
class LoungePresence:
    pet_id: str            # the pet the user chose to walk in with
    pet_label: str         # "Kenji Girl" — composed name, the ONLY public identity
    owner_key: str         # internal only: the DatsMe user id; never serialized
    last_seen_at: float    # heartbeat-reaped (§2.3)

@dataclass
class LoungeState:
    present: dict[str, LoungePresence]   # presence token → entry
    challenges: dict[str, Challenge]     # pending, short-lived (§4)
    racing: dict[str, RacingEntry]       # room code → board entry (§5)
    seq: int                             # SSE event id, the rooms-spec pattern
```

The `JOBS`/`ROOMS` pattern, third instance — which is exactly the repo's three-instances rule for
knowing the shape is right. A restart empties the lounges; everyone's client reconnects and re-enters;
nothing of value is lost.

### 2.3 Reaping

- Presence entries older than `LOUNGE_PRESENCE_TTL_S` are swept by the maintenance thread.
- Pending challenges older than `CHALLENGE_TTL_S` are swept — an unanswered challenge quietly expires;
  no rejection is delivered, which is kinder between children anyway.
- Racing-board entries die when their room dies (the room reaper already exists; the board entry
  holds only the room code and asks `ROOMS` whether it is still alive).

---

## §3 Entering, and who sees what

### 3.1 Signed-in only

Entering a lounge requires the DatsMe launch session (`owner_scope` resolving to an external user) —
the same gate every owner-scoped surface already uses. An anonymous browser can play solo arena all
day; it cannot enter a lounge, appear on any list, or send a challenge. This single rule removes the
worst class of stranger-danger before it exists: there are no anonymous participants anywhere in the
social surface.

**Spectating a race from the board still works signed-out** — that is R3's link-spectator, unchanged.
The gate is on *being listed and being contactable*, not on watching.

### 3.2 The pet is the identity

On entry the user picks which of their pets walks in (default: their active/last-raced pet). The
presence list renders pet thumbnail + composed name — `"Kenji Girl"` — and *nothing else*. No DatsMe
username, no join time, no streak, no profile link. Two children who know each other recognize each
other's pets (that is how the playground works); a stranger learns only that a cartoon leopard is
present.

One pet per user per lounge; entering with a different pet replaces the entry. A user may be present
in only one lounge at a time (§14.4) — presence elsewhere is silently moved, so the lists never show
one child in three places.

### 3.3 Transport

`GET /api/arena/lounges/{id}/stream` — SSE, the R0-proven stack: heartbeats under the outer proxy's
cliff, served through the same nginx `^/api/arena/.*stream` location block that already exists (no
conf change needed — the R0 regex was written to cover every future arena stream). Events: presence
joins/leaves, challenge created/accepted/expired, racing-board changes. Fixed tick not required —
lounge events are sparse; they broadcast as they happen with the heartbeat filling silence.

Presence heartbeat: the client POSTs `/api/arena/lounges/{id}/presence` every
`LOUNGE_HEARTBEAT_S` while the tab is open; closing the tab lets the TTL reap the entry.

---

## §4 Challenges

### 4.1 The object

```json
{ "from_pet": "Kenji Girl", "event_key": "hurdles", "challenge_key": "arithmetic",
  "difficulty": "sums_10", "expires_at": 1754170000 }
```

A challenge is a **canned, structured object** — the challenger picks an event and a question type
from the same setup vocabulary the arena already has, and the UI renders it as a card: *"🚧 Kenji
Girl challenges you to Hurdles (Maths · sums to 10)!"* There is no free-text field anywhere on it.
That is the whole §6 posture: everything a child can transmit is chosen from menus.

### 4.2 The flow (both present — v1)

1. A taps a pet on the presence list → "Challenge" → picks event/challenge → POST.
2. B's stream delivers the card; B taps **Accept** (or Decline, or ignores it into expiry).
3. On accept, the server mints an ordinary race room (SPEC_PET_ARENA_ROOMS `POST /api/arena/rooms`
   semantics) with the challenge's event/challenge/difficulty, host = challenger, tagged `lounge_id`,
   and hands both clients their tokens. Both UIs navigate straight into the room lobby; the ordinary
   countdown and race follow.
4. The room appears on the lounge's racing board (§5) until it dies.

The race room neither knows nor cares that a challenge minted it (§0.10.1) — it sees a create and two
joins.

### 4.3 The flow (friend not present — deferred, and why honestly)

"Invite my friend who isn't on DatsPet right now" requires delivering a message to a user who has no
open connection to this app — that is a **host-side channel** (a DatsMe chat message or notification
carrying a deep link). Two hard facts from this repo's history make this a separate, cross-repo phase:
the DPP has **no background partner→user delivery** (writebacks are launch-bound — a lesson already
paid for), and a cross-repo feature can ship 100% dead with every unit gate green (also paid for). So
v1 keeps out-of-lounge invitation where it already works today: the owner's original story — call or
text the friend *on DatsMe*, meet in a lounge or share a room code. §13 tripwires the host-delivered
invite as its own project with the host repo in the room.

---

## §5 The racing board

Each lounge lists contests minted from it that are still alive: *"🏁 Joe Leopard vs Jazz Phoenix —
Hurdles, 40 s in — Watch"*. Watch is R3's spectator URL. Entries show pet names and the event —
never the score of a child who is losing (the room's own spectator view shows the race; the board is
just a door). When the room is reaped, the entry vanishes with it.

A race minted privately (code shared between friends, no lounge) appears on **no** board — unlisted
stays unlisted.

---

## §6 Children, restated for a discovery surface

The rooms spec's §6 protected an *unlisted* thing. A lounge is a *listed* thing, so the rules are
stricter, and each maps to a §0 decision:

- **No anonymous entry** (§3.1). Every present pet has a signed-in DatsMe owner the host can hold
  accountable.
- **Pets, never people** (§3.2). No real names, no usernames, no profile links, no photos.
- **Nothing free-text** (§4.1). Every transmittable thing is chosen from a menu. There is no way to
  type at another child anywhere in this product.
- **No history.** Presence and challenges evaporate; there is no log of who was in a lounge, no
  record of who challenged whom, nothing to subpoena a child's social graph from.
- **Visibility is the owner's call** (§14.2): open-to-all-signed-in versus friends-gated. Friends
  gating needs a host friendship query (cross-repo); the spec recommends starting open-to-signed-in
  *because the identity is a cartoon pet*, and tightening if the host relationship makes friends
  queries cheap.
- **Tripwires unchanged**: the first request for free chat, reactions, persistent records or user-
  created rooms is a new product conversation, not an extension.

---

## §7 Cheating

Nothing new. The race room's clamps (SPEC_PET_ARENA_ROOMS §7) apply to lounge-minted rooms
identically. A forged challenge card is a race invitation — the worst it can do is start a race.

---

## §8 Named values

In `webui/arena_lounges.py`, per CLAUDE.md.

```
LOUNGE_PRESENCE_TTL_S   = 90     # missed ~3 heartbeats and you have left
LOUNGE_HEARTBEAT_S      = 30     # client presence POST cadence
CHALLENGE_TTL_S         = 120    # an unanswered challenge quietly expires
LOUNGE_MAX_PRESENT      = 40     # a lounge list a phone can render; joins 409 past it
```

(SSE heartbeat cadence is the rooms module's `SSE_HEARTBEAT_S` — one constant, one owner.)

---

## §9 The four test questions

1. **New variant, engine change?** No. A new lounge is a `lounges.json` row. A new challengeable
   event is the arena's own event JSON — the challenge card reads the same declarations the setup
   screen does.
2. **New feature, unrelated files?** No. One new backend module (`arena_lounges.py`), one new
   frontend directory (`web/src/arena/lounge/`), a router registration. The rooms module gains one
   optional `lounge_id` tag on room creation; nothing else is touched.
3. **Third-party integration, owned code paths?** The v1 lounge involves the host only for what
   already exists (the launch session). §4.3's host-delivered invite is deliberately deferred
   *because* it would touch host code — when it comes, it is a host-repo feature consuming a DatsPet
   deep link, not a modification of this app's paths.
4. **Bug in one variant, shared debugging?** The transport is shared with rooms — deliberately, it is
   the same proven stack. A lounge-state bug lives in `arena_lounges.py` alone.

---

## §10 Guard tests

**`webui/tests/test_arena_lounges.py`**

- Anonymous entry 401s; a signed-in entry appears on the list with the pet label and nothing else —
  the serialized presence object is asserted to contain **no `owner_key`** (the "no people" rule as a
  test, not a review note).
- Entering a second lounge moves the presence; entering with a second pet replaces it.
- Presence past `LOUNGE_PRESENCE_TTL_S` is reaped; a heartbeat refreshes it.
- The 41st entry 409s (`LOUNGE_MAX_PRESENT`).
- A challenge delivers to the target's stream, expires after `CHALLENGE_TTL_S`, and cannot carry any
  field beyond the schema (extra keys rejected — the no-free-text rule as a test).
- Accepting mints a room whose event/challenge/difficulty match the card, tagged with the lounge id;
  declining or expiry mints nothing.
- The racing board lists a live lounge-minted room, drops it when the room dies, and **never lists a
  room created without a lounge tag** — unlisted stays unlisted.
- `lounges.json` guard: every row has id/label/emoji, ids unique — the half-formed-registry-entry
  test every registry here carries.

---

## §11 Rollout

Depends on SPEC_PET_ARENA_ROOMS **R1–R2 first** (a challenge must have a room to mint into; the board
wants R3 for Watch links but can ship listing-only before it).

| Phase | Ships | Status |
|---|---|---|
| **L0** | `lounges.json` + presence: enter, see the pet list, leave, reaping. The lounge page renders. | **BUILT** 2026-08-03 |
| **L1** | Challenges: card → accept → minted room → both players in the room lobby. | **BUILT** 2026-08-03 |
| **L2** | The racing board, with Watch links once rooms-R3 exists. | **BUILT** 2026-08-03 (Watch links live — R3 exists) |
| **L3** | Host-delivered invitations (§4.3) — cross-repo, specced separately when reached. | unbuilt |

---

## §12 Deliberately not done

- **No user-created lounges.** Three shipped rooms until real crowding is measured.
- **No chat, no reactions, no emoji, no typing at other users, anywhere.**
- **No persistent anything** — no presence history, no challenge log, no head-to-head records. (The
  first leaderboard request is SPEC_PET_ARENA §11's other tripwire and needs its own review.)
- **No cross-lounge search** ("find Kenji Girl") — discovery is walking into a room, like a real one.
- **No lounge capacity tuning UI, no moderation tools** — until §13 says otherwise.

---

## §13 Tripwires

- **A stranger-contact incident or complaint** → friends-gating (§14.2) stops being optional;
  revisit with the host in the room.
- **The first request for free text between users** → different product, full stop.
- **Lounges regularly at `LOUNGE_MAX_PRESENT`** → more lounges is a JSON edit; *smarter matchmaking*
  is a design conversation.
- **Host-delivered invites get built** (§4.3 / L3) → cross-repo spec, and the unit-gates-cannot-see-
  cross-repo-loops lesson applies: it ships with a live two-repo E2E, not green unit tests.
- **Anyone proposes persisting who-was-where** → §6's "no history" rule is load-bearing; a retention
  decision about children's social data needs the owner explicitly.

---

## §14 Open questions for the owner

**14.1 Lounge names.** "Room 1 / Room 2 / Room 3" (your words), or themed — "The Paddock", "The
Schoolyard", "The Stadium"? Pure content either way; ids stay stable.

**14.2 Who can see into a lounge?** Recommend **any signed-in DatsMe user** for v1 — the listed
identity is a cartoon pet, and no free text exists — tightening to friends-of-someone-present if the
host's friendship data becomes cheap to query. Confirm you are comfortable with signed-in-but-
unacquainted children seeing each other's *pets* in a list.

**14.3 Does a challenge pre-commit the event?** Recommend **yes** (the card carries event + question
type, the accept goes straight to the countdown) — it keeps the moment snappy and the room lobby
still shows what was agreed. The alternative — accept first, negotiate in the lobby — adds a
conversation surface we otherwise avoided.

**14.4 One lounge at a time per user?** Recommended yes (§3.2) — a child appearing in three rooms at
once reads as three children to everyone else.

**14.5 Spectator counts on the board?** "3 watching" is fun but is also a popularity number attached
to children's races. Recommend **no** for v1.

---

## §15 As built (Rev.2, 2026-08-03)

Backend `webui/arena_lounges.py` + `webui/lounges.json`; frontend `web/src/arena/lounge/`
(`LoungeView` + `useLoungeStream`) entered from SetupScreen step 7, landing back in the ordinary
room phase. Rooms-side seams exactly the two §1 predicted: a `lounge_id` tag on
`Room`/`mint_room` and `room_snapshot_if_alive` beside `room_is_alive` — the board never touches
`ROOMS` or its lock.

**§14 defaults chosen** (all cheap to revise): 14.1 `Room 1/2/3` with 🥇🥈🥉 (a JSON edit to
retheme); 14.2 any signed-in DatsMe user; 14.3 yes — the card pre-commits event + challenge +
difficulty (the challenger's current setup picks); 14.4 yes — entering a lounge silently leaves
the others; 14.5 no spectator counts.

**Deviations from the letter of Rev.1, and why:**
- **No Last-Event-ID replay ring on the lounge stream.** Unlike a room's tick deltas, every lounge
  event carries the full lounge snapshot, so a reconnect is made whole by the snapshot-first frame;
  a ring would be dead weight. (The SSE machinery is otherwise the rooms pattern *copied*, not
  extracted — two instances is under the three-instances bar.)
- **§3.2's pet thumbnails are a paw glyph for now** — same deferral as the room lobby's roster;
  there is deliberately no lounge-scoped asset route until an owner asks for portraits here.
- **The challenger's seat is a claim, not a push:** accept mints the room and stores the host seat
  on the challenge; the challenger's browser claims it with their presence token the moment the
  card turns `accepted` on their stream. Tokens ride only direct responses, never broadcasts.

**Verification:** the §10 guard list is `webui/tests/test_arena_lounges.py` (13 cases), plus an
isolated-backend HTTP E2E on :19964 (anon 401 at the real door, presence privacy on the wire,
challenge→accept→claim→start, board truth, snapshot-first SSE, room-scoped assets for a
lounge-minted room). Suites at build: 745 pytest / tsc clean / 114 vitest.
