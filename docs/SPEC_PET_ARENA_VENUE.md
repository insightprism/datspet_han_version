# SPEC_PET_ARENA_VENUE — the arena as a sports venue: who's here, who competes, who talks

**Status: Rev.2 (2026-08-03) — DRAFT FOR OWNER REVIEW; NOTHING BUILT.** §14 lists the calls that
are the owner's. Phase A is in-app; Phase B is a joint build with the DatsMe host and executes
only after its own cross-repo review.

> ### Rev.2 — friends on the floor, and a claim Rev.1 got wrong
>
> The owner: *"when someone goes into the arena, they will see everyone that is in the arena. will
> you also highlight which ones are your friends, and list them first."*
>
> Answering it turned up an error in Rev.1. §5 said a partner *"cannot query friendship… by
> design"* and §12 turned that into *"no friend list inside DatsPet."* Checked against the host's
> code rather than its prose: the capability registry ships nine capabilities, none reads
> connections, and the only partner read route is the profile one — so **the "cannot" was true, but
> "by design" was not.** The host's protocol §12.2 explicitly anticipates additive scopes, and
> `groups.read_memberships` already grants a partner a low-risk read on the user's own social
> memberships. The scope had simply never been defined.
>
> Three changes: §2.5 specifies **floor ordering**, which Rev.1 omitted and which is a live defect
> at floor scale (the shipped lounge sort reshuffles on every heartbeat); §5 and §12 are corrected
> to say *not yet scoped* rather than *never*, with the ids-only line kept permanent; §14.6 puts
> the friend tier to the owner. The capability itself is drafted for the host as
> [`PROPOSAL_DPP_PARTNER_READS`](../../datsme_me/docs/PROPOSAL_DPP_PARTNER_READS.md).
>
> **Nothing in Phase A depends on any of it.** V0 ordering needs no host data, and the friend tier
> is `required: false` — ungranted, the floor behaves exactly as Rev.1 described.

> **⚠ PLACEMENT PENDING — see [`SPEC_ARENA_MIGRATION`](SPEC_ARENA_MIGRATION.md).** The arena may
> move out of DatsPet and into DatsMe as an internal service. **The product design in this spec is
> unaffected** — the venue model, the floor, canned signals, the 🤝 bridge and §2.5's ordering all
> stand. What changes is the *mechanism*: friends come from PostgreSQL rather than a capability, so
> §5's `connections.read` discussion and §12's ids-only rule become moot, and §6's host-delivered
> invites stop being a cross-repo build. **§1.3 is RETIRED** (owner, 2026-08-03): playing requires a
> DatsMe account and a pet; watching requires nothing (migration §5.2, §5.2.1).

**Companion to `SPEC_PET_ARENA_LOUNGE` (the named rooms) and `SPEC_PET_ARENA_ROOMS` (the
ephemeral contest), built beside them, replacing neither.** This spec owns the venue's SOCIAL
layer: who can be seen, who can be challenged, and where communication lives. It also absorbs
and supersedes SPEC_PET_ARENA_LOUNGE §4.3 ("the flow when the friend is not present") — the
host-delivered invitation is specced HERE (§6), grounded in what the host actually has.

**Where this came from.** The owner, after playing the lounge live on staging (2026-08-03):

> "The game itself worked but a bit clunky. Communication for inviting or challenging people is
> hard. Also there is no communication that can be had. I cannot look at who is available now…
> it would be nice to know who is currently signed in that is available to be challenged."

And the frame that organizes the whole design:

> "Think of the arena as a sports competition location. People can come in as contestants or
> observers. Anyone can be an observer (public), but contestants can only be DatsMe users. For
> communication chat, for DatsMe you can only communicate with someone if they are your friends.
> If DatsPet wants to use DatsMe chat and communication, it will have to follow this logic."

The owner also named the tension honestly: friendship-gated challenges force people to connect
(a positive) but make discovery hard and annoying (a negative). §1 resolves it by layering.

**The one-line summary:** competing is open, talking requires friends. A challenge is a
structured card, not a conversation — so any contestant may challenge any contestant — while
free-form communication stays on DatsMe, governed by DatsMe's own friends-only rule, which this
app follows and never rebuilds.

---

## §1 The venue model

Three layers, strictly ordered; each layer includes everything below it.

| Layer | Who | What they can do | Status |
|---|---|---|---|
| **Observer** | anyone with a link (public) | watch any race via `/arena/{code}` | LIVE (rooms R3) |
| **Contestant** | any signed-in DatsMe user | stand on the arena floor (§2), challenge and be challenged via structured cards (§3), send canned signals (§4), race | Phase A |
| **Friend** | DatsMe friends (host-verified) | free-form chat and calls on DatsMe's own surfaces; receive host-delivered challenge invites when not present (§6) | Phase B |

Three consequences, each load-bearing:

- **1.1 Challenging is not communication.** A challenge card is a closed schema of picks
  (event, challenge type, difficulty) with no field free text could live in — the same §4.1
  posture the lounge spec established. DatsMe's friends-only rule governs *conversation*; a
  scoreboard handshake is not conversation. This is what keeps discovery open (the owner's
  "negative" avoided) without touching the host's communication rules.
- **1.2 Friendship is an incentive, never a gate on competing.** You race a stranger at a meet
  by both showing up. What friendship unlocks is everything beyond the scoreboard: talking
  about the race (on DatsMe), and summoning a friend who is not here (§6). The owner's
  "positive" — races turning into friendships — survives as the 🤝 bridge (§5), offered at
  exactly the moment two strangers have just had a good race.
- **1.3 ~~The anonymous couch player keeps the code room.~~ RETIRED 2026-08-03** — reversed the
  same day it was made, once the arena's placement changed. **Owner:** *"you need a DatsMe account
  in order to play, just like you need a datsme account to design and buy pets. if you don't have a
  datsme pet, it is not possible for you to play."* The original call was made about a **partner**
  surface; on `datsme.me` the platform's own rule governs, and racing is gated exactly as designing
  and buying are. **Playing requires an account and a pet; watching requires nothing** — the public
  spectator link is deliberate, and is how someone who watched a race becomes someone who plays one
  (`SPEC_ARENA_MIGRATION` §5.2, §5.2.1). Every DISCOVERY surface — the floor, the named rooms —
  remains signed-in-only, unchanged: nobody can be *found* who hasn't signed in.

---

## §2 The arena floor — "who is available right now"

The headline fix. Today you can only see people who already walked into the same numbered room;
the floor is the venue's open ground that every contestant can stand on.

### 2.1 What it is

One global presence surface. A signed-in user on the arena page flips **"🏁 Up for a race"** ON
and their pet appears on the floor — visible to every other contestant, with a ⚔️ Challenge
button right there. Flip it OFF (or leave, or go quiet past the TTL) and the pet vanishes. The
toggle defaults **OFF** (§14.2): being visible is a choice made each visit, never ambient.

### 2.2 The floor is a lounge without walls — content, not code

The lounge machinery (presence + heartbeats + TTL reaping + challenge cards + accept/claim +
snapshot-first SSE) is exactly what the floor needs; what differs is *rules*, and the rules
become **registry data** (engine-vs-content):

```jsonc
// lounges.json, Rev.2 of the registry
{"lounges": [
  {"id": "floor",    "kind": "floor", "label": "The Arena Floor", "emoji": "🏁",
   "exclusive": false, "max_present": 100},
  {"id": "lounge_1", "kind": "room",  "label": "Room 1", "emoji": "🥇",
   "exclusive": true,  "max_present": 40},
  …
]}
```

- `exclusive` — the one-lounge-at-a-time rule (lounge spec §14.4) becomes one-**exclusive**-
  lounge-at-a-time: entering Room 2 walks you out of Room 1, but the FLOOR coexists with any
  room. A pet on the floor and in Room 1 reads as one child in the venue, visible on the open
  ground and hanging out in a room — which is how a real venue works.
- `max_present` — per-entry capacity; the floor's is larger and §14.1 owns the overflow story.
- `kind` — presentation only (the floor renders as an availability list, rooms as hangouts).
  The backend never branches on it; every behavioral difference rides `exclusive`/`max_present`.

Adding the floor is therefore **one JSON entry plus the two data fields** — the enforcement
tests extend, the engine does not fork. The four test questions hold (§9).

### 2.3 The front door moves

Today the lounges are step 7 of a long setup form — the owner's "clunky." The arena page gains
a **"🏟️ Play with someone"** surface at the top level: the floor list (with the toggle), the
named-room doors, and the join-by-code box together. The solo setup flow (steps 1–6) remains
the "practice track" path and keeps its own start button. Picks still travel the same way: a
challenge from the floor carries the challenger's current picks, exactly like a room challenge.

### 2.4 What the floor shows — and refuses to show

Same §3.2 posture as the lounge, restated because the floor is bigger: **the pet is the whole
identity.** Pet label, pet id (for the eventual thumbnail), a presence handle. Never an owner
id, never a DatsMe name or slug, never join times, never "last seen", never counts of races
won. The floor also carries the venue's "🏁 Racing now" rail: races minted from floor
challenges are tagged `floor` the same way lounge races are tagged with their lounge — watchable
by anyone (observer layer), listing pet names and the event only.

### 2.5 Ordering — and why it is a V0 item, not a polish item

Rev.1 never said how the list is ordered, and what shipped for lounges sorts by `last_seen_at`
(`webui/arena_lounges.py:175`). **Every heartbeat therefore reshuffles the list.** On a five-person
lounge nobody notices; on a floor of `FLOOR_MAX_PRESENT` = 100 it is a list that churns under your
thumb while you reach for a ⚔️ button. Ordering is load-bearing the moment the list is long.

**The V0 rule, needing no host data:**

1. **People you have raced this visit**, most recent first. DatsPet already owns this relationship —
   it is what "Rematch?" (§3) rides on — and it is the best available answer to *"who would I
   actually want to challenge."*
2. **Everyone else**, by arrival order, stable. A pet that is already on the floor never moves
   because it heartbeated.

Sort keys must be stable across snapshots: a row may only move when someone joins, leaves, or
becomes rematch-eligible — never on a heartbeat.

**The V2 rule, if `connections.read` is granted (§5):** friends rank above strangers within each
group, and a friend's row carries a **⭐ badge and no name**. A badge keeps §2.4 intact; a name
would break the pet-is-the-identity rule for the *whole* list, since once names appear for friends
the pet-only rows read as second-class. The owner call is §14.6; the capability is
[`PROPOSAL_DPP_PARTNER_READS`](../../datsme_me/docs/PROPOSAL_DPP_PARTNER_READS.md).

**The friend set is fetched once per launch and cached for the launch lifetime** (≤60 min), never
per snapshot — a presence surface re-renders continuously and must never become a per-frame host
query. This is a commitment the proposal makes on DatsPet's behalf (§4.4 there).

---

## §3 Challenging from the floor

Identical machinery to the lounge challenge (SPEC_PET_ARENA_LOUNGE §4): a closed card —
challenger's picks, target's presence handle — accept mints an ordinary ephemeral race room with
both pets seated, the challenger claims their seat off the stream, the room dies on its TTLs.
Nothing new is built here; the floor simply gives the card somewhere to be sent *from* without
prior coordination. Declining stays a local dismiss (no rejection is delivered — kinder between
children, lounge spec §2.3); an ignored card evaporates on its TTL.

One addition: **"Rematch?"** on the results screen is a one-tap re-challenge — the same card,
same picks, sent back to the opponent's presence (if they are still on the floor or in the
room's lounge). It is a challenge, not a message; it reuses the card path end to end.

---

## §4 Canned signals — communication without a keyboard

The middle ground the venue can offer without touching DatsMe's friends-only rule: a **closed
vocabulary of taps**, shipped as content (`signals.json`), rendered as small broadcast cards.

- A signal is `{from_presence, to_presence, signal_key}` — three ids, no payload. Unknown
  `signal_key` → 422; an extra field → 422. Free text has no field to live in, same as
  challenges (§1.1). The §13 tripwire of the lounge spec is REAFFIRMED: the first request for
  typed text between users is a different product and a full stop.
- Proposed starting vocabulary (§14.3 — the owner approves the actual list):
  `wave` 👋 (floor/room), `good_race` 🏁 (results), `wow` 🤩 (results/spectating).
- Signals are ephemeral: rendered when received, evaporate after `SIGNAL_TTL_S`, never stored,
  never counted, no history. A signal to someone who left is silently dropped.
- Rate-limited per sender (`SIGNAL_MIN_INTERVAL_S`) so a signal cannot be turned into a
  character stream by rhythm.

Signals answer "there is no communication that can be had" at the level a venue needs —
acknowledgement, sportsmanship, delight — while real conversation remains DatsMe chat between
friends (§5).

---

## §5 The friendship layer and the 🤝 bridge

What the host exploration (2026-08-03) established, and what this spec builds on:

- Friendship on the host is a bilateral `relationships` pair with a full request/accept flow
  (`/api/connections/*`), and **one canonical gate** — `are_friends()` (`api/helpers.py`) —
  already enforces friends-only on chat, calls, group membership, sharing, photo tags, credit
  gifts, and **pet gifting**.
- A partner cannot query friendship and cannot message anyone. The host's partner-protocol spec
  (§11.4 there) states the division for *messaging*: where a partner capability touches it,
  **the host enforces `are_friends` at dispatch**, so the partner never needs the friend list.

**Rev.2 correction — "cannot" is a gap, not a prohibition.** Rev.1 recorded the messaging rule
and then generalized it into a principle, which the host's protocol does not state. Verified
against the host code, not its spec: the registry (`api/apps/dpp/capabilities.py`) ships nine
capabilities and **none of them reads connections**, so today the answer is still no. But the
protocol's §12.2 anticipates exactly this — *"if richer access patterns prove necessary, a
capability can be added post-v1.0 as an additive change"* — and `groups.read_memberships`
(risk tier **low**) is shipping precedent for a partner reading the launch user's *own* social
memberships. The scope was never defined; it was not refused.

The dispatch-enforcement pattern genuinely does not transfer to the floor, and that is the real
finding: the host can enforce `are_friends` when the *host* does the sending, but the floor is a
DatsPet surface that DatsPet renders. Any friendship answer DatsPet can render is one DatsPet has
received — and it cannot be hashed around, because DatsPet already holds every present user's
`external_user_id` and can invert any fingerprint scheme it is handed.

So friends-first (§2.5) is blocked on a capability, and the capability is drafted:
[`PROPOSAL_DPP_PARTNER_READS`](../../datsme_me/docs/PROPOSAL_DPP_PARTNER_READS.md) —
`connections.read`, ids only and never names, `required: false` so this app degrades to Rev.1
behavior without it. Until the host owner accepts it, everything below stands unchanged.

Competing stays open (§1) regardless; everything friendship-gated still *happens on the host*:

- **Talk**: two contestants who want to talk do it in DatsMe chat, which requires friendship,
  exactly as DatsMe already enforces. DatsPet adds nothing and bypasses nothing.
- **The 🤝 bridge**: after a race (and on a received `good_race` signal), the results screen
  offers **"🤝 Add as friend on DatsMe"**. This is Phase B: DatsPet knows both players'
  user ids server-side but deliberately cannot map an opponent to a host profile — so the
  bridge is a host-mediated action (a small host endpoint that turns "opponent of race X" into
  a friend REQUEST from the tapping user, host-side, with the host's own cap/dormant/pending
  rules). The request then lives its normal life in DatsMe. No friendship data ever flows to
  the partner; the partner only initiates.

---

## §6 Host-delivered challenge invites — "challenge a friend who isn't here"

Supersedes SPEC_PET_ARENA_LOUNGE §4.3. This is the deep fix for "inviting people is hard": the
canonical story's first half (a DatsMe call — "I challenge you!") becomes a first-class object.

### 6.1 The grounded design (recommended)

The host already owns the exact structural pattern: **`PetGiftOffer`** — a friend-gated,
pending, expiring, two-party offer with bell + push notification and accept/decline routes
(`api/apps/pets/pet_gift_*`). A **ChallengeOffer** is that object with race parameters instead
of a pet:

1. **Compose (host surface).** From DatsPet, "📣 Invite a DatsMe friend" deep-links to a small
   host page. The friend PICKER lives there — only the host may show a friend list. The
   challenge parameters (event/challenge/difficulty, the challenger's pet) ride the link as the
   offer's payload.
2. **Offer.** The host creates the ChallengeOffer (gated by `are_friends`, host-side), rings
   the bell, sends the push — "🏁 Wu challenges you to a hurdles race!" — with accept/decline.
   Offers expire like gift offers do; a dormant (paused) friendship refuses creation.
3. **Accept → seated.** Accept launches DatsPet with the offer id carried in the launch token's
   host-injected custom claims (the `extra_claims` mechanism that already exists). DatsPet
   mints the room, seats the acceptor, and the host notifies the challenger — "your challenge
   was accepted, come race!" — whose own launch lands them in their seat. First to arrive
   waits in the ordinary room lobby; the room lives and dies by its ordinary TTLs.

### 6.2 The alternative, recorded

The host's capability vocabulary already contains `notifications.send` and
`messaging.send_as_user` — consented-for but with their writeback targets deliberately dormant.
Activating `notifications.send` would let DatsPet push a generic notification instead of the
host owning a ChallengeOffer. Rejected as the primary path: the offer pattern gives pending/
expiry/decline semantics, friend-gating at creation, and a host-native accept surface for free;
a bare notification rebuilds all of that in the partner, and §11.4's division of labor says
the host should own the social object anyway.

### 6.3 The rule this phase must obey

Phase B is a **joint spec and a joint build** (host + DatsPet), and it ships with a live
two-repo E2E — the unit-gates-cannot-see-cross-repo-loops lesson is standing policy. Nothing
in Phase A depends on it.

---

## §7 Children, restated for an open floor

The lounge spec's §6 posture carries over whole; the floor widens visibility, so the knobs are
tighter, not looser:

- Presence is **opt-in per visit** (toggle, default OFF) and evaporates on TTL — no ambient
  tracking, no "online" status stored anywhere, no history of who stood where.
- The pet is the identity everywhere (§2.4). Two children can race and signal without either
  learning anything about the other beyond a pet's name — until BOTH choose the host's
  friendship flow, which is the host's (parental-controls-aware) domain, not ours.
- Signals are closed-vocabulary and unstored; challenges are closed-schema; free text does not
  exist on any DatsPet surface (§4).
- A stranger-contact incident anywhere in the venue trips the lounge spec's §13 response
  (friends-gating discovery becomes the default posture, revisited with the host).

---

## §8 Named values (proposed)

| Name | Value | Why |
|---|---|---|
| `FLOOR_MAX_PRESENT` | 100 (registry `max_present`) | a list a phone can scroll; §14.1 owns overflow |
| `SIGNAL_TTL_S` | 30 | a signal is a moment, not a record |
| `SIGNAL_MIN_INTERVAL_S` | 3 | taps, not a character stream |
| presence TTL / heartbeat | reuse `LOUNGE_PRESENCE_TTL_S` / `LOUNGE_HEARTBEAT_S` | one constant, one owner — the floor IS a lounge |
| challenge TTL | reuse `CHALLENGE_TTL_S` | same card, same lifetime |

---

## §9 The four test questions

- **New variant → engine change?** No. The floor is a `lounges.json` entry; a new signal is a
  `signals.json` entry; a new named room is a JSON entry. The lounge engine reads
  `exclusive`/`max_present` as data.
- **New feature → unrelated files?** No. Phase A touches the lounge module (rule fields), two
  content files, and the arena front door. Phase B touches the host by design, through its own
  spec.
- **Third-party integration → owned code paths?** The host integration goes through the DPP
  channel the host already defines (offers, launch claims); DatsPet's engine doesn't fork.
- **Bug in one variant → shared debugging?** A bad signal key or a bad lounge entry is caught
  by its registry guard; floor rules are data on the same tested machinery.

---

## §10 Guard tests (Phase A)

- Registry: every lounge entry carries `kind`/`exclusive`/`max_present`; ids unique; exactly
  one `kind:"floor"` entry; the build fails on a half-formed entry.
- Exclusivity: entering an exclusive lounge leaves other exclusive lounges; entering or leaving
  the floor never touches room presence, and vice versa.
- Toggle privacy: floor presence serializes pet fields only (no owner ids, no tokens — the
  lounge test extended to the floor); toggle state is never persisted server-side.
- Capacity: the `max_present`+1th walk-in 409s per entry, floor and rooms alike.
- Signals: closed schema (unknown key 422, extra field 422); rate limit enforced; a signal to
  a departed presence drops silently; nothing is stored after `SIGNAL_TTL_S`.
- Rematch: the results-screen rematch produces a byte-identical challenge card (same picks).
- The anonymous 401 guard extends to the floor: an anon cookie cannot stand on it.
- **Ordering is stable across a heartbeat** (§2.5): a snapshot taken before and after every present
  pet heartbeats yields the same row order. This is the churn defect, and it is the one a unit test
  catches trivially and a human never notices until the list is 100 long.
- **If the friend tier ships:** a friend row serializes the ⭐ flag and **no name field** — the same
  assertion the host-side proposal makes (§4.2 there), duplicated deliberately on this side of the
  wire, because it is the boundary and each repo should fail its own build on losing it.

---

## §11 Rollout

| Phase | Ships | Depends on |
|---|---|---|
| **V0** | registry rule fields (`kind`/`exclusive`/`max_present`) + the floor entry + the "Play with someone" front door + floor presence/challenge + **§2.5 stable ordering** | nothing new — lounge machinery |
| **GATE** | **"a user may only compete with pets they own"** (owner, 2026-08-03) is not implementable on any arena surface until ownership is borrowed from the host — [`SPEC_PET_OWNERSHIP`](SPEC_PET_OWNERSHIP.md) O2/O4. Until then every arena surface seats DatsPet-scoped pets and cannot honor the rule. | that spec, not this one |
| **V1** | `signals.json` + signal cards + Rematch on results | V0 |
| **V2** (= lounge L3) | host ChallengeOffer + friend picker surface + `extra_claims` seat landing + the 🤝 bridge + **the ⭐ friend tier on the floor** | its own joint spec + two-repo E2E; the friend tier additionally needs `connections.read` granted (§5) |

---

## §12 Deliberately not done

- **No free text, anywhere, ever** (the standing tripwire).
- **No presence history, no online-status storage, no "last seen".**
- **No friend NAMES inside DatsPet, ever** — the picker and any named list are host surfaces.
  *Rev.2 narrows this from Rev.1's "no friend list at all", which overstated a missing capability
  as a rule (§5).* If `connections.read` is granted, DatsPet holds a set of opaque host user ids
  for the launch's lifetime and nothing else: enough to mark a row ⭐, never enough to build a
  contact list. The ids-only line is the boundary that stays permanent — it is what keeps the
  proposal at risk tier `low`, and it is what keeps §2.4's "the pet is the whole identity" true
  for every row in the list.
- **No leaderboards on the floor** (SPEC_PET_ARENA §11's tripwire still stands).
- **No spectator counts** (lounge §14.5's answer carries over).

---

## §13 Tripwires

- Free-text request → different product, full stop (inherited, reaffirmed).
- A stranger-contact incident → discovery goes friends-gated by default; host consulted.
- Floor regularly at capacity → §14.1's overflow answer gets implemented, not improvised.
- Anyone proposes persisting presence or signals → §7's no-history rule is load-bearing;
  owner decides explicitly or it doesn't happen.

---

## §14 Open questions for the owner

**14.1 Floor overflow.** At `FLOOR_MAX_PRESENT`, what does the 101st contestant see? Recommend:
they can still SEE the floor and challenge from it, but their own toggle waits for space (a
"the floor is packed" note) — visibility is capped, competing is not.

**14.2 Toggle default.** Recommend OFF — standing on the floor is a per-visit choice a child
makes, not a side effect of opening the page. Confirm.

**14.3 The signal vocabulary.** Approve the starting three (`wave` 👋, `good_race` 🏁,
`wow` 🤩), or edit the list — it is one JSON file.

**14.4 Named-room presence lists once the floor exists.** Keep rooms as-is (their own lists,
their own boards), or slim rooms to themed challenge spaces? Recommend keep as-is and let usage
decide.

**14.5 The 🤝 bridge timing.** Offer "Add as friend on DatsMe" only after a completed race
(recommended — shared context first), or also directly from the floor list?

**14.6 Friends first on the floor?** (Owner ask, 2026-08-03 — *"will you also highlight which ones
are your friends, and list them first"*.) Recommend **yes, in two steps**: §2.5's V0 ordering ships
now and needs nothing from the host; the ⭐ friend tier waits on the host owner accepting
`connections.read`. Two things to confirm — that DatsPet holding a set of your friends' opaque host
ids for one launch is acceptable at all (it is the first time any DatsMe social edge reaches this
app), and that **badge-only, no names** is the right stopping point. If the answer to the first is
no, §2.5's V0 rule still stands on its own and the floor is still a large improvement on Rev.1.
