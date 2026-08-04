# SPEC_PET_OWNERSHIP — DatsMe owns the house, DatsPet owns the workshop, and nothing syncs

**Status: Rev.2 (2026-08-03) — DRAFT FOR OWNER REVIEW; NOTHING BUILT.** §14 lists the calls that
are the owner's. O0 ships alone and needs nothing from the host; O1 onward is a joint build with
DatsMe and executes only after its own cross-repo review.

> **⚠ SCOPE PENDING — read [`SPEC_ARENA_MIGRATION`](../../datsme_me/docs/SPEC_ARENA_MIGRATION.md) first.** If the arena
> moves to DatsMe, most of this spec is retired with it: the borrowed roster, the digest matching,
> the roster-scoped asset route and the never-persist discipline all existed to cross a boundary
> that migration removes. **What survives is factory-only** — the house page's "✓ In DatsMe (21)"
> against a 12-pet house (§1), which is a DatsPet surface and a real defect regardless of where the
> arena lives. On that decision this spec narrows to that surface and keeps `pets.read_owned`;
> §11's O4 (arena entrant validation) is superseded outright. **O0 is unaffected either way.**

> ### Rev.2 — the transport was wrong, and the host had already written the shape
>
> Rev.1 delivered ownership as a **claim on the launch JWT**. That does not survive the protocol's
> own §8.1: the token is handed over as
> `launch_url: "<partner.base_url>/partner/launch?token=<jwt>"` — a **URL query parameter**. At
> `MAX_PETS_PER_USER = 50` the roster is ~9 KB raw and ~12 KB base64url-encoded. It does not fit,
> and a design that only fails at the 13th pet is worse than one that fails at review.
>
> **The mechanism is now a launch-bound endpoint** (§3), fetched once per session. Everything the
> claim design was defending survives intact — resolve once, hold in memory, never persist, die
> with the session — because those were properties of *how DatsPet treats the answer*, not of how
> it arrives.
>
> Two things found while correcting it:
>
> 1. **The host→partner channel already exists and DatsPet already implements all of it** —
>    `/partner/manifest`, `/partner/export/{user_id}`, `/partner/imported/{user_id}`,
>    `/partner/revoke`, host-signed with `verify_host_signature`. Rev.1 read as though a channel
>    had to be built. It does not. The gap is one *direction of read*, which
>    `SPEC_DPP_DATA_TRANSFER_CHANNEL` §7 names "Direction B" and records as unspecified-but-shaped,
>    with a stated trigger: *"it gets built when a partner asks."*
> 2. **The host predicted this spec's defect in writing** (§1.1), when AM-6 added §13.5.
>
> The host-side ask is now one merged document covering both partner reads DatsPet needs:
> [`PROPOSAL_DPP_PARTNER_READS`](../../datsme_me/docs/PROPOSAL_DPP_PARTNER_READS.md).

**Companion to `SPEC_PET_ARENA*`, and a GATE on them.** The arena requires that *a user may only
compete with pets they own* (owner, 2026-08-03). DatsPet cannot honor that today, because it does
not know what anyone owns — it knows what it once delivered. This spec establishes ownership as a
first-class, borrowed fact; the arena consumes it (§11, O4). Nothing here is arena-specific, which
is why it is not in the arena specs.

**Where this came from.** The owner, on the requirement:

> "i want it so a user can only use pets they own to compete. the issue is that the pet that the
> user owned on datsme and datspet are not guarantee to sync because datsme know the true
> ownership, datspet has the inventory and history… **the single source of ownership is really
> datsme.**"

And on the cause:

> "the reason why they can be out of sync is that datsme has a pet limitation. i think 12 at this
> time, so sometimes, the user will remove their pets. this can happen when they gift or just plain
> delete for inventory."

**The evidence, from the owner's own two screens (2026-08-03):** DatsPet's house page reads
**"✓ In DatsMe (21)"**. DatsMe's My Pets reads **"Up to 12 pets in your house."** At least nine of
those twenty-one cannot be there. **The badge is not at risk of drifting; it is already wrong.**

**The one-line summary of the design:** ownership is not stored by DatsPet and therefore cannot
drift — it is read from the host once per launch, held as a roster in memory, and dies with the
session. **No sync job, no webhook, no reconciliation, no repair script.**

---

## §0 The decisions

| # | Decision | Choice |
|---|---|---|
| 0.1 | Who is authoritative for ownership | **DatsMe, always and only.** DatsPet never forms an opinion (§2). |
| 0.2 | How DatsPet learns it | **One launch-bound host read per session** (§3) — `GET /api/partner/pets/{user_id}`, the shape `SPEC_DPP_DATA_TRANSFER_CHANNEL` §7 already recorded. Not a JWT claim (§3.2), not a poll. |
| 0.3 | Where DatsPet stores it | **Nowhere.** Session-resolved, gone on expiry (§3.4). A fact you do not store cannot drift. |
| 0.4 | What `writeback_acked_at` means | **A delivery receipt** — "I sent this once." True, historical, DatsPet's own. It stops meaning "they have it" (§2.1). |
| 0.5 | Pets DatsPet did not build | **Shown as owned, not raceable, not editable** (§4.3). Honest beats invisible. |
| 0.6 | Gifted-in pets | **Matched by asset digest**, rendered from DatsPet's existing bytes under a roster-scoped route (§5). No transfer. |
| 0.7 | Removal on DatsMe | **Archived in DatsPet, never deleted** (§6). The workshop is an archive. |
| 0.8 | Bytes | **Nothing new is copied anywhere** (§7). Both sides already hold what they need, deliberately. |

### 0.9 The posture that must not change

1. **DatsPet never decides ownership.** Not from its own rows, not from a cache, not from a
   heuristic. If any code path answers "does this user own this pet?" from local state, this design
   has been undone.
2. **The roster is never persisted.** Not a column, not a table, not a file, not a long-lived
   in-process cache keyed by user. §10 pins this with a test because it is the one shortcut that
   will look like a performance win.
3. **`_scope_clause` is not widened.** SPEC_PET_STORE §1.2 — *"exactly the bug the exact-match fix
   removed."* Roster-scoped access is a separate capability route (§5.2), never a loosened owner
   check.
4. **Standalone DatsPet keeps working with no host at all.** No roster means no house — the surface
   hides, it does not fabricate.

---

## §1 The defect, precisely

**As it stood until O0 shipped** (`webui/db.py`, 2026-08-03):

```python
d["in_datsme"] = d.pop("writeback_acked_at") is not None
```

> **O0 renamed it** to `sent_to_datsme`, and the badge to "✓ Sent to DatsMe". **The name is now
> honest; the gap below is unchanged.** DatsPet still cannot know what is in the house — it knows
> only what it delivered. Everything from here describes the gap, not the label.

`writeback_acked_at` records *"the host acknowledged my delivery at time T."* That is a true,
immutable, historical fact and it is DatsPet's own to keep. `in_datsme` renames it into a
present-tense assertion — *"this pet is in the house right now"* — that DatsPet has no way to know.

**"I sent it" is not "they have it."** Two consequences follow mechanically:

- **The field is monotonic.** It goes `false → true` and can never go back. No deletion, gift, or
  eviction can unset it, because nothing tells DatsPet those happened. The count only ever climbs.
- **Arrivals are invisible.** A pet gifted *to* the user was never sent *by* DatsPet, so no receipt
  exists and it can never appear — which is why the second half of the owner's requirement ("if he
  got a new pet from a friend, the new pet should be reflected on datspet") fails too.

One field, both symptoms.

### 1.1 The host wrote this defect down before we hit it

AM-6's rationale for adding protocol §13.5, written 2026-07-16:

> "A *pull* deletes your acknowledgment channel… you never see the outcome, so an imported item
> stays un-acked in your records forever and **your UI lies about it**… **Do not** treat this as the
> source of truth for whether an item exists on DatsMe; treat it as **a hint to refresh your own**."

That is "✓ In DatsMe (21)" described in advance, by the host, in the protocol DatsPet implements.

**It also exposes a gap on the host side:** §13.5 instructs partners to *refresh* from a source that
was never specified — Direction B (`SPEC_DPP_DATA_TRANSFER_CHANNEL` §7) is exactly the missing
half. The advice is correct and, today, unimplementable. §3 is what makes it implementable.

---

## §2 What this needs that does not exist

| | State today |
|---|---|
| Any DatsPet knowledge of current host ownership | **none** |
| A capability that reads what a user owns | **none** — the host ships 9, none of them this |
| A partner→host read of anything but the profile | **none** — "Direction B", recorded as unspecified-but-shaped (`SPEC_DPP_DATA_TRANSFER_CHANNEL` §7) |
| A digest index over DatsPet's own sheets | **none** — `bundle_sha256` exists; the *sheet* digest does not (§5.1) |

**The channel is NOT part of the gap** — this is the correction Rev.2 makes. The host→partner call
channel is built, host-signed, and DatsPet already implements every inbound route of it:
`/partner/manifest`, `/partner/export/{user_id}`, `/partner/imported/{user_id}` (AM-6),
`/partner/revoke`, `/partner/results/{user_id}/pending`, with `verify_host_signature` wired
(`webui/datsme_integration.py`). What is missing is one *direction of read*, and §7 already records
its shape and its trigger: *"it gets built when a partner asks."*

Three other things that **do** exist and carry the design:

- **`GET /api/partner/profile/{user_id}`** — the one existing partner→host read, whose
  authorization (AM-9: host-mintage + live consent) §3 reuses verbatim rather than inventing.
- **`MAX_PETS_PER_USER = 50`**, default 12 in practice (`../datsme_me/api/apps/pets/pet_service.py:20`).
  The ownership set is small by construction and needs no paging.
- **`bundle_tokens`** and **rooms §4.3** — two existing precedents for an asset route authorized by
  something other than ownership (§5.2).

---

## §3 The ownership read

### 3.1 Shape

```
GET /api/partner/pets/{user_id}          # launch-token authorized, AM-9 pattern
→ {
    "pets": [
      {"pid": "<host Pet.id>", "src": "datspet", "sid": "<source_item_id>",
       "sha": "<sheet_sha256>", "label": "Joe Leopard"},
      {"pid": "…", "src": "store", "sid": null, "sha": "…", "label": "Peaches Tabby"}
    ],
    "count": 9,
    "slots_remaining": 3
  }
```

`label` rides so §4.3's unmatched rows can render at all; it is the user's own pet's name, disclosed
to the user's own session. **No owner ids, no other users, nothing about anyone else, and no
bytes** — the route is a manifest of what is owned, never a path to assets.

### 3.2 Read once per session — not polled, and not a JWT claim

**Not polled.** The roster is fetched at session start and held for the session. Re-reading per race
or per page would put a live host dependency inside a game loop and buy nothing: the answer cannot
change usefully faster than a user can act on it (§12's honest cost).

**Not a JWT claim, which was Rev.1's design.** Protocol §8.1 delivers the token as
`launch_url: "<partner.base_url>/partner/launch?token=<jwt>"` — a URL query parameter. At
`MAX_PETS_PER_USER = 50` the roster is ~9 KB raw, ~12 KB encoded. It does not fit, and the failure
would appear only for users with large houses.

**What the claim design was protecting survives unchanged:** resolve once, hold in memory, never
persist, die with the session (§3.4). Those are properties of how DatsPet *treats* the answer, not
of how it arrives.

**On §12's "no background reads":** this read exists only inside a live, host-minted, currently
consented launch (§3.3). There is no read without a user who just clicked in — which is the thing
that rationale protects. Protocol §12.4 requires exactly this argument be made head-on; the merged
proposal makes it.

### 3.3 What it costs on the host

A capability — **`pets.read_owned`**, risk tier `low`, `required: false` — plus one route mirroring
`profile_routes.py`'s authorization verbatim: `sub` match, **host-mintage** (the `jti` must match a
live `IntegrationNonce`, presence-checked not burned), and **live consent** from the grant table.

AM-9 is why the last two are non-negotiable: launch tokens are HMAC-signed with the secret the
partner also holds, so JWT claims alone are partner-forgeable, and a route authorizing on claims
would let a forged token read a stranger's inventory.

Drafted for the host alongside `connections.read` in one document — the two share a posture (the
host asserts, the partner receives, ids only, no bytes) and should be reviewed together:
[`PROPOSAL_DPP_PARTNER_READS`](../../datsme_me/docs/PROPOSAL_DPP_PARTNER_READS.md).

**`required: false` matters:** ungranted, DatsPet degrades to today's DatsPet-scoped behavior with
the house surface hidden. A user who declines loses a feature, never access to their own work.

### 3.4 Lifetime

The roster lives exactly as long as the launch session (≤60 min, AM-1). It is resolved once at
session start into an in-memory roster and is **never written anywhere**. A restart loses it; the
next launch supplies it again.

---

## §4 Resolution — three buckets, one table

Each roster entry resolves against DatsPet's own inventory in order:

1. **`src == "datspet"` and `sid` matches a pet row** → direct hit. DatsPet built it and holds the
   bytes. Fully raceable, editable, re-adoptable.
2. **No `sid`, but `sha` matches a sheet digest** (§5.1) → a DatsPet-built pet that changed hands,
   because gifting deliberately strips the business key (`pet_gift_service.py:428`). Raceable
   under §5.2. **This is what makes gifted pets work.**
3. **No match** → a store pet, an upload, or another partner's pet. **Shown as owned, not raceable
   and not editable**, with a link out to DatsMe. DatsPet has no bytes and §12.4 blocks getting
   them.

### 4.1 The house page becomes three filters over one table

There is **one row per pet and one copy of the bytes**. The tabs are a `WHERE` clause — the same
shape as `external_user_id` scoping — never a second store:

| Tab | Derived from | Meaning |
|---|---|---|
| **In your DatsMe house** | the ownership roster | what you own right now |
| **Not adopted yet** | `writeback_acked_at IS NULL` | designed here, never sent |
| **No longer in your house** | acked once, absent from the roster | gifted away, deleted, or evicted for space |

The third tab is where the receipt finally gets an honest job: it answers *"did I ever send this?"*,
which DatsPet knows, instead of *"is it there now?"*, which only DatsMe knows.

### 4.2 Copies, counted

| State | DatsPet | DatsMe | Total |
|---|---|---|---|
| Designed, never adopted | 1 | — | **1** |
| Adopted, in the house | 1 | 1 | **2** |
| Archived (removed/gifted away) | 1 | — | **1** |

**Archiving subtracts a copy.** The host's `PetAssets` is 1:1 under FK cascade, so leaving the house
removes the host's copy. The one two-copy state is deliberate on both sides: the host copies so the
pet survives DatsPet entirely (*"from that moment forward the storefront is irrelevant to
rendering"* — `pet_models.py:143`), and DatsPet keeps its copy because it is the factory and the
archive. **This design adds no bytes anywhere.**

### 4.3 Unmatched rows are shown, not hidden

A pet the user owns that DatsPet cannot render still appears, greyed, labelled *not raceable here*.
Hiding it would make the roster silently disagree with the house the roster just described — which is
the same class of lie §1 is removing.

---

## §5 Gifted pets

### 5.1 The digest index

DatsPet stores `sheet_png` as its own column (`webui/db.py:71`); the host stores `sheet_sha256`
(`pet_models.py:187`). Matching needs DatsPet to index `sha256(sheet_png)` over its own rows —
cheap, and derived, never authoritative.

**It only works if both digests cover byte-identical bytes.** Any re-encode along
build → bundle → fetch → store breaks the match *silently*, and the symptom is "gifting just
doesn't work." §10 pins it with a real round-trip rather than a unit assertion.

### 5.2 Serving bytes for a pet the caller does not own in DatsPet

The recipient's session must render bytes attached to a row scoped to the **donor**. Widening the
owner scope is forbidden (§0.9.3), so the roster becomes the capability instead:

**A roster-scoped asset route** serves **sheet and manifest only** for a pet in the caller's current
ownership roster, for as long as the session lives. The owner scope is never consulted and never
widened.

This is the **third instance** of a pattern already reviewed twice here — `bundle_tokens` (a
one-time download is the capability) and `SPEC_PET_ARENA_ROOMS` §4.3 (room membership is the
capability, *"sheet and manifest only… never `bundle_zip`"*). Same rule applies: **never
`bundle_zip`.** Owning a pet in your house is not a licence to export someone's design bundle out
of DatsPet.

### 5.3 What a gifted pet does NOT become

It does **not** enter the recipient's workshop or archive, and cannot be redesigned. Bundles carry
the original designer's typed words (`SPEC_PET_DESIGN_PROVENANCE`); minting a workshop row for the
recipient would attribute someone else's design to them. It stays the donor's design that the
recipient now owns — which is what a gift is. §14.1 is the owner's call to revisit.

---

## §6 Archive, never delete

A pet leaving the house moves tabs. **Nothing is deleted from DatsPet, ever**, and this is now
load-bearing rather than tidy: under §5.2, a gifted pet renders from the **donor's** row. If the
donor hard-deleted it, the recipient's pet would silently become unraceable — DatsMe still has its
copy, and §12.4 blocks fetching it back.

**One user deleting a pet can break another user's pet.** That makes hard delete a guard test
(§10), not a convention.

---

## §7 What this deliberately does not move

**No bytes cross the wire.** The response is ids, digests and labels. DatsPet already holds the bytes
for everything it built; the host already holds the bytes for everything in the house. The problem
was never storage location — it was **two systems holding an opinion about one fact**. This removes
the opinion and leaves both stores exactly where they are.

---

## §8 Named values

In `webui/` per CLAUDE.md — no literal reaches a call site.

```
OWNED_PETS_MAX_ENTRIES  = 50    # host MAX_PETS_PER_USER; a larger response is malformed, not paged
SHEET_DIGEST_ALGO       = "sha256"   # must match the host's sheet_sha256 (§5.1)
```

The roster's lifetime is **not** a DatsPet constant: it is the launch token's TTL, owned by the host
(AM-1, 60 min). Naming a local copy would invite it drifting from the thing that actually expires.

---

## §9 The four test questions

1. **New variant → engine change?** No. A new pet *source* (another partner, a new store lane) is an
   unmatched roster entry — §4.3 renders it with no DatsPet change. The engine reads the roster; it
   never branches on `src`.
2. **New feature → unrelated files?** No. The house page's filter, one session resolver, one asset
   route, one derived index. `db.py` loses a derived field and gains no column.
3. **Third-party → owned code paths?** The host side is one additive capability plus a mint call
   site, through the DPP process the protocol already defines.
4. **Bug in one variant → shared debugging?** Honest exception: **the resolver is shared** by all
   three buckets. A resolution bug affects every pet at once. Mitigated by it being pure — roster in,
   roster out, no I/O — so it is fixture-testable without a host.

---

## §10 Guard tests

**`webui/tests/test_ownership.py`**

- **The roster is never persisted.** Resolve a roster, restart the process, assert the roster is empty
  and no column/table holds it. *This is the most valuable test here* — caching the roster is the one
  shortcut that will look like a performance win and is exactly the bug being removed.
- `in_datsme` **is gone from the API response**, and `writeback_acked_at` is exposed as a
  send-receipt only. A grep-level guard, because the rename is the whole fix.
- A pet acked but **absent from the roster** lands in *No longer in your house*, never in-house.
- A pet **present in the roster but never acked** (gifted in) renders in-house.
- A roster entry with **no `sid` but a matching `sha`** resolves to the built row.
- A roster entry matching **nothing** renders as owned-not-raceable and never 500s.
- **Standalone session:** no roster → the house surface is hidden, and no code path consults
  ownership.
- **Hard delete is refused** — a pet row can be archived, never removed (§6).
- **`_scope_clause` is unchanged** — extend `test_scoping.py` rather than trusting a review.

**Roster-scoped assets**

- Serves sheet and manifest for a pet in the caller's roster; **404s for a pet that is not**,
  including one the caller *does* own in DatsPet — the roster is the capability, not ownership.
- **Never serves `bundle_zip`** (§5.2). A separate assertion, because "add the zip route for
  convenience" is the obvious future mistake.

**Cross-repo (the one that actually counts)**

- **A live two-repo round trip: build a pet, adopt it, gift it to a second user, launch as that user,
  and race it.** Per the standing lesson, a signed cross-repo feature once shipped 100% dead with
  every unit gate green. §5.1's digest equality is only provable here.

---

## §11 Rollout

Each phase is independently shippable and independently visible — the owner asked to see the impact
in isolation.

| Phase | Ships | Depends on |
|---|---|---|
| **O0** | ✅ **SHIPPED 2026-08-03** — "✓ In DatsMe" → **"✓ Sent to DatsMe"**, and the API field `in_datsme` → `sent_to_datsme` with it. §10's grep-guard ("the rename is the whole fix") is satisfied: the old name survives only in `db.py`'s note recording why it changed. | nothing — the field already meant this |
| **O1** | Host `pets.read_owned` + the ownership roster | joint spec + host review |
| **O2** | Session resolver + the three tabs live from the roster | O1 |
| **O3** | Sheet-digest index + roster-scoped asset route → gifted pets raceable | O2 |
| **O4** | **Arena entrant validation against the roster** — the gate | O2 (O3 for gifted entrants) |

**O0 first, and alone.** It cost nothing, needed no host, and stopped a surface asserting something
false to every user today — including the owner's screenshot.

**Shipped 2026-08-03.** Scope was the label *and* the field: leaving `p.in_datsme` in code behind a
badge reading "Sent to DatsMe" would have preserved the same lie one layer down, and §10 names the
rename as the fix. `webui/db.py:513-526` now carries the reason the old name was wrong, so the next
reader finds the explanation at the source rather than in a spec. Gates: 520 backend tests, 114
vitest, `tsc --noEmit` clean. **The underlying gap is untouched** — DatsPet still cannot know what
is in the house, and O1/O2 are still what answers it.

**O4 is the gate on `SPEC_PET_ARENA*`.** "Only pets you own may compete" is not implementable before
O2; until then the arena seats DatsPet-scoped pets and cannot honor the rule.

---

## §12 Deliberately not done

- **No sync job, no webhook, no reconciliation, no repair script.** There is nothing to reconcile.
- **No cached ownership**, at any layer, for any duration (§0.9.2).
- **No new bytes anywhere** (§7).
- **No host→partner byte export.** §12.4 there stands; unmatched pets stay unrenderable (§4.3).
- **No workshop row for gifted pets** (§5.3) — provenance, §14.1.
- **No hard delete** (§6).
- **No widening of `_scope_clause`** (§0.9.3).

---

## §13 Tripwires

- **Anyone proposes caching the roster "for performance"** → that is the defect this spec removes,
  restated as an optimization. Full stop.
- **The host raises `MAX_PETS_PER_USER` materially** → `OWNED_PETS_MAX_ENTRIES` and the response-size
  assumption get revisited; a roster is not a paged list.
- **A request to redesign a gifted pet** → §14.1's provenance decision, the owner's.
- **§12.4 ever opens for host bytes** → §4.3's third bucket becomes raceable and this spec revises.
- **A second partner starts delivering pets** → nothing here changes (§9.1), but the archive's
  "what DatsPet built" boundary should be re-read before assuming it still reads naturally.

---

## §14 Open questions for the owner

**14.1 Should receiving a DatsPet-built pet mint a workshop row for the recipient?** Recommend
**no** (§5.3) — the bundle carries the original designer's typed words, and a gift transfers
ownership, not authorship. Saying yes makes gifted pets redesignable and archivable, and needs an
attribution answer first.

**14.2 Is the archive visible by default, or behind a toggle?** Recommend **a visible tab** — "where
did my pet go?" is the exact question the current UI cannot answer, and hiding it re-creates a
smaller version of the same silence.

**14.3 Should the ownership read return the house's remaining slots?** Recommend **yes** — one integer. It is
the direct fix for the pain that started this: at 12/12 the user gets *"your house is full — free a
slot on DatsMe"* before adopting, instead of discovering it at the charge screen. It costs one field
and removes a class of dead-end.

**14.4 What should the arena do with an owned-but-unrenderable pet (§4.3)?** Recommend showing it
in the entrant picker, disabled, with the reason — rather than omitting it, which reads as the pet
having vanished.
