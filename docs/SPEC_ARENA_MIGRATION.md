# SPEC_ARENA_MIGRATION — the game moves to DatsMe, the factory keeps the pets

**Status: Rev.5 (2026-08-03) — IMPLEMENTATION-READY, NO EXTERNAL DEPENDENCIES. Both repos are
owned and operated by the same person; §12's items are decisions and work, not requests to anyone.**
§12 lists the calls that
are the owner's; §5 lists the seams that must be decided **before** any code moves. A0 is a
one-day infrastructure probe that needs no game code, depends on no open question, and blocks
everything after it.

**Readiness, per phase, because "is it ready" has no single answer:**

| Phase | State | Needs |
|---|---|---|
| **Census** (§5.1.2) | **Runnable now.** One query per environment (§6.1.2). | nothing |
| **A0** | **Runnable now.** Fully specified in §6.1. | a port for a ~20-line stub, and a manual nginx edit on DatsMe staging (§6.1.1) |
| **A1** | **Runnable now**, once 12.6 is decided — a decision, not a request. | the introspection endpoint in `datsme_me`, the CSRF port |
| **A2** | After A1. §4.3/§4.4 stand on host routes verified to exist. | nothing new |
| **A3** | After the census resolves 12.9 either way. | possibly one serializer field in `datsme_me` |
| **A4–A6** | After the above. | nothing new |

**There is no external dependency anywhere in this plan.** Rev.3 said A0 was "ready now"; Rev.4
"corrected" that to "blocked on host access" and was **wrong** — `datsme_me` is the same owner's
repo, sitting beside this one, with a documented deploy path (`datsme_me/CLAUDE.md` §Staging Deploy
Sequence, `ssh root@5.161.70.13`). What §12.6/12.7/12.9 actually are: **decisions to make and code to
write in the other repo.** Nobody is being asked for anything.

**What is still true, and is the only real constraint:** A0 lands on *different infrastructure* —
another repo, another box, another deploy pipeline — and **nginx is not part of DatsMe's deploy
sequence at all.** All eleven steps are git/npm/systemctl; nginx is never mentioned, so the
`deploy/nginx.staging.conf` in that repo is a reference copy and the live config is changed by hand
on the box. That is the same trap already recorded for DatsPet (`nginx-default.conf` is
*production's*) in a second repo. §6.1.1.

> ### Rev.5 — there was never a second party
>
> Rev.1–Rev.4 were written as though DatsMe belonged to someone else. §12 called its items "host
> asks"; Rev.4 invented an access blocker on top of that; a review request was addressed to
> *"whoever owns DatsMe's auth."* **All of it was wrong — both repos have the same owner and sit
> side by side** (`datsme-pet-factory_wu` and `datsme_me`).
>
> What changes:
>
> - **Nothing is blocked externally.** 12.6, 12.7 and 12.9 are decisions to make and code to write
>   in `datsme_me`, not requests awaiting a reply. The readiness table is now an ordering, not a
>   dependency graph.
> - **The critical path is pure engineering sequence:** census → 12.6 → A0 → A1 → A2 → A3 → …
>
> What does NOT change, and would be the wrong lesson to draw:
>
> - **The DPP protocol discipline stands, and is not ceremony.** Capabilities, consent screens and
>   AM-N amendments exist for the **user** — a person consenting to DatsPet reading their pet list
>   is a product mechanism, not an inter-team formality. `pets.read_owned` is still built as a real
>   capability with a real consent screen. What disappears is the approval theatre, not the protocol.
> - **§2.3's "the factory stays a partner" survives untouched.** It was argued from **hardware** —
>   GPU, deploy shape, `SPEC_DATSME_MULTI_NODE` §8's fleet role — and never from trust. Common
>   ownership does not move a GPU.
> - **§0.14.3 still forbids reading `datsme_me`'s per-user tables.** That rule is about *coupling*,
>   not permission: a service reading another service's private schema turns a schema change into a
>   cross-service outage no matter who owns both. Owning both makes the shortcut *easier*, which
>   makes the rule more load-bearing, not less.
>
> The one thing Rev.4 got right and keeps: A0 lands on another repo, another box, and a deploy
> pipeline that **never touches nginx** — so that config is changed by hand. Same class of trap as
> DatsPet's production-config-on-staging incident, in a second repo.

> ### Rev.4 — the reviewer's findings verified, and three gaps they left
>
> Rev.3 was a review pass by another hand. **Its two substantive findings were re-verified against
> the host and both hold** — `pet_service.pet_dict()` really does return ten fields with no
> `source_item_id` (`api/apps/pets/pet_service.py:326`), and `arena_lounges.py:365` really does call
> `_seat_from_presence(challenger, …)` from inside `accept_challenge`, the *target's* request. Its
> §4.3 "one call, not two" holds too: `list_my_pets` depends on `get_current_user_db`
> (`pet_routes.py:183`), which calls `get_current_user`. Rev.3's corrections stand as written.
>
> Rev.4 closes what Rev.3 left open:
>
> 1. **The census was circular.** Rev.3 moved it from A3 to A1 — but A1 is blocked on the host
>    12.6/12.7 being decided, and the census exists to decide whether 12.9 is needed at all. A measurement that gates a question cannot sit behind the phase awaiting that question's
>    answer. **It now runs before A0**, where it belongs: zero dependencies of any kind.
> 2. ~~**"A0 MAY START NOW" was true about decisions and false about access.**~~ **WRONG — see
>    Rev.5.** There is no access boundary; `datsme_me` is the same owner's repo. What survives from
>    this item is only that A0 lands on *different infrastructure* with a deploy pipeline that never
>    touches nginx (§6.1.1).
> 3. **A0 and the census were prose, not artifacts.** New **§6.1** gives the nginx blocks, both
>    assertions as runnable commands, and the census SQL — verified against the dev database, which
>    immediately corrected the figure: 46 unstamped, but **26** unstamped *and owned*, and only the
>    latter can be restatted.
>
> *(The cross-repo inconsistency this note flagged was resolved in Rev.5, which reframed the
> `datsme_me` documents from review requests into a work list — see §12.)*

> ### Rev.3 — two decisions that the data path could not execute
>
> Rev.2 fixed the plumbing and then recorded two conclusions the plumbing cannot carry out. Both are
> the same failure mode Rev.2 was good at catching, one layer further in.
>
> **§5.1 resolved the nudge anchor to a ladder whose middle rung is unreadable.** The ladder is
> stamped `identity_nudges` → `source_item_id` → host `Pet.id`, and rung 2 does the work: it is what
> keeps existing pets' stats intact on migration day. But **`source_item_id` is not exposed by any
> host response** — `pet_service.pet_dict()` (`../datsme_me/api/apps/pets/pet_service.py:326-338`)
> returns ten fields and that is not one of them, and a sweep of `../datsme_me/api/**.py` finds the
> column only on the model, its index, and DPP writeback internals. §4.3 made `/api/pets/me` the
> ownership path precisely so the arena would not read per-user tables (§0.14.3), so the rung is
> unreachable by construction. **§5.1 is rewritten and the field becomes work item #4 on the `datsme_me` side (§12.9).**
>
> **§4.4.1 covers rooms; the lounge is not a room.** `webui/arena_lounges.py:322` reads *another
> player's* manifest during the **acceptor's** request — the owner's cookie is not present and no
> room exists yet. §4.4.1's invariant ("each pet is fetched by its own owner's session, at the moment
> that owner volunteers it") simply does not reach it. **New §4.4.2 applies the same rule one seam
> earlier, at lounge entry**, and §1.2's table row is corrected.
>
> Three smaller corrections: §4.4.1's memory figure was a floor presented as a ceiling; §4.3 needed
> one call, not two, on the join path; and §0 numbered two different things `0.12`.
>
> ### Rev.2 — the data plan was built on a spec, not on code
> 
> A verification pass against both repos confirmed §1 (the dependency measurements), §3.1.1 (the
> cookie finding), §3.2 (the port band), §5.1 (the nudge-anchor facts) and §5.4. It **failed** §4.
> 
> **Rev.1's §4.3 and §4.4 stood on `SPEC_DATSME_MULTI_NODE`, which is marked "Status: proposed (not
> implemented)" and whose `home_node` appears in ZERO lines of `../datsme_me/api/**.py`.** There is
> one node today. So "publish a projection" and "fetch over the node→node channel" were not seams to
> plug into — they were a request to implement the first slice of multi-node, in another repo, as a
> prerequisite. A2 was described as "the only genuinely new plumbing"; it was the largest item in
> the plan and it was in someone else's codebase.
> 
> **What replaced them was already built.** `../datsme_me/api/apps/pets/pet_routes.py` ships
> `GET /api/pets/me` (:181), `/api/pets/{id}/sheet.png` (:704) and `/api/pets/{id}/manifest.json`
> (:789), behind `_authorized_asset_session` (:515) with ETag/304 answered from a digest column
> before the BLOB is read (`SPEC_PET_ASSET_DELIVERY_AND_CACHE`). Same origin, cookie flows, no new
> protocol. **§4.3, §4.4 and the whole of Rev.1's §4.7 (a 2 GiB content-addressed SQLite cache) are
> deleted rather than fixed.** A2 shrinks to almost nothing.
> 
> Four more corrections, each from code: **§4.1** described half the auth path and its `DATSME_SECRET_KEY`
> requirement contradicts §4.6.1's containment claim (B2); **CSRF was absent entirely**, and
> same-origin cookie auth is precisely the condition that requires it — new §4.8 (B3); **§2.4 solved
> the athletics share for Python only**, while 16 TypeScript imports escape the repo (B4); **§2.1
> under-counted the frontend move** by five external imports (B5). New §2.6 states what gets *built*,
> which Rev.1 never did.
> 
> **§12 status after the 2026-08-03 clearing pass** *(superseded by Rev.3's readiness table above —
> 12.9 was opened after this was written).* **Answered by the owner:** 12.2 and 12.8 —
> playing requires a DatsMe account *and* a pet; watching requires nothing, and the public link is
> deliberate (§5.2, §5.2.1). **Resolved by verification:** 12.1 (ports), 12.3 (nudge anchor), plus
> §5.0's runtime diff and §5.4's `StatBars` disposition — three of which **corrected** what Rev.1
> asserted. **Still open: three.** 12.4 wants one word from the owner; **12.6 and 12.7 belong to the
> host** and are the only things blocking A1. *(12.4 answered 2026-08-03 — two left.)*

**This supersedes the placement question across `SPEC_PET_ARENA*`.** Those specs remain the
authority on what the game *is* — events, rooms, lounges, the venue's social layer. This one owns
**where it runs and how it gets there**, and nothing else.

**Where this came from.** The owner, after a week in which the arena needed three separate DatsMe
partner capabilities in a row:

> "the pet game is attached to a module for datspet, what if it is a module for datsme instead.
> wouldn't that simplify everything"

and, on the decisive fact:

> "datspet uses datsme login credential… **dats pet game also needs datsme, but doesn't need
> datspet**"

and, on the shape:

> "the arena will be a little resource intensive, so should probably have its own server… give it
> its own frontend and backend api"

**The one-line summary:** the arena is a DatsMe product that happens to live in DatsPet's repo. It
moves to its own service on its own box, mounted **same-origin** under `datsme.me/arena`, sharded
**by room**, reading identity and relationships from DatsMe's shared PostgreSQL. DatsPet keeps the
factory — including minting each pet's athletics — and stays a partner for a **hardware** reason.

---

## §0 The decisions

| # | Decision | Choice |
|---|---|---|
| 0.1 | Where the arena runs | **Its own FastAPI service on its own box** (§3.2). Not inside DatsMe's web tier, not inside DatsPet. |
| 0.2 | How it is reached | **Same-origin path routing** — `datsme.me/arena/*` and `/api/arena/*` (§3.1). **Not** a subdomain (§3.1.1 — the cookie finding). |
| 0.3 | Frontend | **Its own**, served by its own box under Next's `basePath` (§3.3). DatsMe's web tier is never rebuilt for a race feature. |
| 0.4 | Scaling | **Shard by room code, never by user** (§3.4). This is the rule that must not be violated later. |
| 0.5 | Identity | **DatsMe session cookie**, resolved by **introspection against DatsMe's backend** rather than local JWT decode (§4.1). No launch token, no capability, no consent screen — and no signing key on the arena box (§4.1.1). |
| 0.6 | Friends | **PostgreSQL `relationships`** directly — the shared layer that is already source of truth (§4.2). |
| 0.7 | Pet ownership | **`GET /api/pets/me` on the host**, called server-side with the user's own cookie (§4.3). It resolves identity *and* ownership in one call. No projection, no new host route. |
| 0.8 | Pet bytes and manifests | **The host's existing `/api/pets/{id}/sheet.png` and `/manifest.json`**, always fetched with the **owner's own** credential at the moment they volunteer the pet — at room join (§4.4.1) or at lounge entry (§4.4.2) — and held for the life of that room or presence. No node protocol, no global cache. |
| 0.9 | Athletics | **Minted by DatsPet at build, unchanged** (§4.5). Both sides read through one shared tables package. |
| 0.10 | The factory | **Stays a partner** — because it needs a GPU, not because of trust (§2.3). |
| 0.11 | The arena's own storage | **None at all.** No database, no schema, no cache on disk (§4.6). Room-lifetime assets live in memory with the room, exactly as `SPEC_PET_ARENA_ROOMS` §4.3 already specifies. |
| 0.12 | CSRF | **Ported, not inherited** (§4.8). Same-origin cookie auth *requires* it; a separate FastAPI process gets none of DatsMe's middleware. |
| 0.13 | Who may play vs watch | **Play requires a DatsMe account AND a pet; watching requires nothing** (§5.2, §5.2.1 — owner, 2026-08-03). The asymmetry is the funnel, not a compromise. |

### 0.14 The posture that must not change

*(Numbered 0.14, not 0.12: Rev.2 gave this section the same number as the CSRF row in the table
above, and §8 and §11 both cite it by number.)*

1. **Shard by room, not by user.** A race is the unit that shares memory. `--workers 1` stays
   load-bearing *per process* (`SPEC_PET_ARENA_ROOMS` §2.1); horizontal scale comes from disjoint
   room sets, never from two processes sharing one room.
2. **Same origin, always.** The moment the arena moves to a subdomain, the session cookie stops
   arriving and somebody widens it to `.datsme.me` — which ships DatsMe's bearer JWT to every
   partner box (§3.1.1). The path mount is a security decision, not a convenience.
3. **Go through the host's own routes, never its private schema.** Ownership and assets are read via
   `GET /api/pets/me` and `/api/pets/{id}/sheet.png` (§4.3, §4.4); PostgreSQL is touched only for
   `relationships` (§4.2), which is already the shared layer by design. A separate service reading
   another service's per-user tables is a shared database with extra steps. **This rule is why
   §5.1's anchor is a `datsme_me` serializer change (§12.9) rather than a direct read of
   `pets.source_item_id` — the
   shortcut exists, and taking it is how this becomes a shared database.**
4. **The arena never calls the factory.** Its only factory-derived input is the `athletics` block,
   which travels inside the bundle (§4.5). If the arena ever imports from `pet_factory` beyond the
   shared tables package, this migration has failed.

---

## §1 The evidence — measured, not argued

Recorded here because the next person to read this will reasonably ask "how entangled was it?"

### 1.1 Coupling to generation: zero

```
grep -rl "make_pet_zip|render_design_still|comfy|ComfyUI|PET_GEN_BACKEND|pool_client"
      over webui/arena_*.py + web/src/arena/   →   0 files
```

The arena never touches ComfyUI, the compute pool, the GPU, or the designer. The one thing that
makes DatsPet DatsPet is not involved.

### 1.2 Coupling to DatsPet: three symbols

| Symbol | Call site | Used for | Becomes (§4) |
|---|---|---|---|
| `db.get_pet` | `arena_rooms.py:611` | asset bytes for the room-scoped route | the host's `/api/pets/{id}/sheet.png`, fetched at join by the owner, held in the room (§4.4.1) |
| `db.get_pet` | `arena_lounges.py:322` | **another player's** manifest, read during the *acceptor's* request | fetched at **lounge entry** by that pet's own owner and held on the presence record (§4.4.2) |
| `db.get_pet_for_owner` | `arena_rooms.py:248`, `arena_lounges.py:221` | scoped variant — the ownership gate | `GET /api/pets/me`, which resolves identity and ownership in one call (§4.3) |
| `owner_scope.resolve_owner_scope` | `arena_rooms.py:247`, `arena_lounges.py:118` | who is calling | DatsMe session, by introspection (§4.1.1) |

**The two `db.get_pet` rows are not the same problem, and Rev.2 collapsed them into one.** The room
call site is served by §4.4.1's "fetched by its own owner, when they volunteer it." The lounge call
site is not: it runs inside a *different* user's request, with no room in existence yet. §4.4.2
exists because of that row.

Plus `from pet_factory import athletics` — **packaging, not dependency**: that package imports only
`hashlib, json, threading, pathlib, typing`. 17 JSON files and a stdlib loader that happen to sit
in the factory's namespace, which is exactly why the GPU-less production posture works for it.

### 1.3 Reverse dependency: a leaf

Everything in DatsPet that knows the arena exists:

```
webui/app.py:223,224      import arena_rooms   + include_router
webui/app.py:229,230      import arena_lounges + include_router
webui/app.py:1967,1975    two sweep_* calls on the maintenance thread
web/src/app/arena/page.tsx, web/src/app/arena/watch/page.tsx
```

Six lines and two page files, against 1,267 lines of arena backend and 5,997 lines of arena
frontend. **Nothing in the factory depends on the arena.**

### 1.4 The pet runtime exists on the host — but has DIVERGED (corrected in Rev.2)

Rev.1 said the host's `web/src/pet/` was "a compatible superset" on the strength of matching
filenames. **§5.0's diff was run and that is false.** Same lineage, drifted in *both* directions:

| File | State |
|---|---|
| `behaviorRegistry.ts`, `personality.ts` | identical |
| `manifest.ts`, `types.ts` | ±2 lines |
| `viewport.ts` | host +29 |
| `PetCanvas.tsx` | host +57 |
| `useAnimationLoop.ts` | host +256 |
| `petStore.ts` | host +299 |
| `index.ts` | host +4, **DatsPet +27** |

And `locomotion/` is not a superset at all — it is **a different design**:

```
DatsPet  (3):  quadruped.ts  registry.ts  types.ts
DatsMe   (9):  bindProfile.ts  habitats.ts  integrators.ts  profiles/
               vocabulary.json  registry.ts  types.ts  locomotion.test.ts  __fixtures__
```

DatsPet's is a strategy registry (`registry.ts:39` maps `mammalian_quadruped → quadruped`);
**`quadruped.ts` has no counterpart on the host.** The host rebuilt locomotion around profiles and a
vocabulary.

**This does not weaken the migration case** — §1.1–§1.3 carry that, and they were measured. It
changes one thing: **the arena must bring its own runtime, which §2.5 already specified. That
disposition is now forced rather than chosen**, and §3.3's own-frontend decision stops being a
preference and becomes a requirement.

### 1.5 The inverse: what the arena needs from DatsMe

Identity, friends, presence, ownership, invitations, and the pets themselves. Every social feature
drafted for the venue in the last week required a new partner capability. **Three capabilities in
one week is not bad luck; it is what a misplaced boundary feels like from the inside.**

---

## §2 What moves, what stays, what is shared

### 2.1 Moves to the arena service

| | |
|---|---|
| `webui/arena_rooms.py` | 1,267 lines with `arena_lounges.py` |
| `webui/arena_lounges.py` | |
| `web/src/arena/**` | 5,997 lines TS/TSX |
| `web/src/app/arena/page.tsx`, `arena/watch/page.tsx` | become the new app's routes |
| `pet_factory/athletics/events/*.json` | via the shared package (§2.4) |

**And five external imports Rev.1 did not mention.** Individually trivial; collectively the
difference between "moves nearly unchanged" and a week:

**Rev.1 guessed the dispositions and got four of five backwards.** Measured 2026-08-03 — consumers
of each, split by whether they are inside `web/src/arena/`:

| Import | Arena uses | **Non-arena** uses | Disposition |
|---|---|---|---|
| `@/pet` | 7 | — | **Duplicate** — forced by §1.4's diff |
| `@/lib/api` | 10 | (adapter) | **Split** the arena block out; §2.2 deletes it from DatsPet |
| `@/lib/petName` | 2 | **2** — `app/house`, `lib/api` | **Duplicate** — DatsPet keeps its own |
| `@/lib/petFirstNames` | 1 | **3** — `app/house`, `lib/petName(.test)` | **Duplicate** — DatsPet keeps its own |
| `@/components/PosePlayer` | 1 | **8** — designer, catalog, motion lab, `PoseGallery` | **Duplicate** — DatsPet keeps its own |
| `@/components/PetThumbnail` | 1 | **4** — `app/house`, `DesignStep`, `PetJobResult`, `PosePlayer` | **Duplicate** — DatsPet keeps its own |
| `@/components/ModalOverlay` | 1 | **7** — admin store, catalog, designer, `ConfirmModal` | **Rebuild** on the arena's own shell (§3.3) |

**The correction matters:** Rev.1 said "move" for four components that DatsPet's designer, house,
catalog, motion lab and Pet Store depend on. **Moving any of them breaks DatsPet.** Every one is a
copy-and-keep, and the arena's copies then diverge freely — which is correct, because they will be
styled for a different shell.

**Nothing on this list may be deleted from DatsPet.** The only thing §2.2 removes is the arena's own
block inside `lib/api.ts`.

### 2.2 Deleted from DatsPet

The six lines in `app.py` (§1.3), the two page files, and the arena's `api.ts` endpoint block. Per
CLAUDE.md, the cleanup is part of this change, not a follow-up — a dual-mount transition period is
explicitly **not** wanted (§10).

### 2.3 Stays in DatsPet

The factory: ComfyUI, the pool, the design flow, the Pet Store, the house page — and
**`webui/pet_athletics.py`**, which mints a pet's athletics block at build (`app.py:655`). Stats are
the pet's identity, created with the pet, visible before purchase, and the stored block is what
preserves a pet's character across a nudge-algorithm change (`SPEC_PET_ARENA` §5.3 — which has
already happened once, in `e33fea0`). Verified working against real packer output 2026-08-03.

DatsPet stays a **partner** because it needs a GPU and a different deploy shape —
`SPEC_DATSME_MULTI_NODE` §8 already contemplates DatsPet GPU workers as fleet nodes.
**Separate for hardware is real; separate for history is debt.**

### 2.4 Shared: the athletics tables — ONE source, published TWICE

`pet_factory/athletics/` is needed by both sides — by the factory to *mint*, by the arena to *read* a
stale or absent block (`resolve_athletics` §5.1 precedence).

**Rev.1 said "a pip package" and solved half the problem.** The harder half is TypeScript:
`web/src/arena/declarations.ts` reaches the tables with **16 raw relative imports** that escape the
web root — `../../../pet_factory/athletics/{movement_classes,modifiers,identity,tuning,bots,handicaps}.json`
and `events/*.json` — and `web/src/arena/raceEngine.test.ts:6` does the same for
`athletics/tests/fixtures/race_vectors.json`. `web/tsconfig.json` maps only `@/* → ./src/*`; nothing
else makes those paths resolve. **In a standalone arena repo they do not exist, and a pip package
does not help a TS build.**

**Requirement: one source of truth, published to both ecosystems** — pip for the Python referee, npm
(or a build-time copy step from a single checked-in directory) for the TS engine. Two hand-maintained
copies is the one outcome that must not happen, because the failure is silent: the browser and the
referee would disagree about a race and nothing would error.

**`race_vectors.json` is the artifact that proves the publish worked.** It is the only guarantee that
the TS engine and the Python referee compute the same result, §8 leans on it, and it currently lives
*inside* the Python package's test fixtures. It must ship in **both** published artifacts, and the
cross-engine test must run in **both** repos' CI. `TABLE_VERSION` catches a table skew; only the
fixture catches an engine skew.

### 2.5 Deliberately duplicated: the pet runtime

The arena's frontend carries its own `web/src/pet/`; DatsMe's web keeps its own for the house. **Two
runtimes, two products** — racing versus displaying.

**§5.0's diff makes this forced, not chosen** (§1.4): the two `locomotion/` directories are
different designs, and DatsPet's `quadruped.ts` has no host counterpart. The arena cannot adopt the
host's runtime; it must carry the one its races were tuned against.

Record it as intentional duplication (CLAUDE.md) anyway, because the *reason* matters: someone who
sees two similar trees in six months and consolidates them will re-couple the two deploys **and**
silently repoint the arena onto a locomotion engine its race vectors were never validated against.

### 2.6 The cost, both directions

Rev.1 quantified what *moves* and never what gets *built*. Both, plainly:

**Moves — trivial, and that is the genuinely good news:**

| | |
|---|---|
| Python | 1,267 lines (`arena_rooms.py` + `arena_lounges.py`) |
| TypeScript | 5,997 lines (`web/src/arena/**`) |
| Tests | **1,068 lines** — `test_arena_rooms.py` 559, `test_arena_lounges.py` 396, `test_arena_stream.py` 113 |
| Deleted from DatsPet | 6 lines + 2 pages |

**Built new — this is the actual project:**

a repo · a box · a deploy pipeline · nginx changes on the host's **prod *and* staging** · a Next
shell · an auth adapter and a DatsMe introspection endpoint (§4.1.1) · a CSRF middleware port (§4.8)
· a dual-published athletics package with cross-engine CI (§2.4) · an ownership read path (§4.3) ·
the room-scoped asset proxy (§4.4.1) · **the lounge's entry-time manifest fetch (§4.4.2)** · **the
empty-house funnel step (§5.2.2)**.

**Three host-side items, and the list is closed** (§10): the introspection endpoint, the renewal
answer (§12.7), and one serializer field (§12.9).

**Three deploy targets across three repos** — DatsPet, the arena, and `datsme_me`, the last of which
deploys by `reset --hard origin/master` and **is the login path for the entire platform**.

#### 2.6.1 Blast radius — say it plainly

Today a bad arena deploy takes down a game. **After the move, a bad nginx edit on the host takes down
authentication.** §3.2's separate-box argument covers the *runtime* side of that — an arena overload
cannot starve login, which is real and remains true. It does **not** cover the *config* side: the
`/arena` and `/api/arena` location blocks live in the same file as `/api` and `/`, and that file
serves `datsme.me`.

That is the honest price of same-origin, and it is why A0 lands on **staging** with a stub and why
every nginx change here touches two files. The mitigation is procedure, not architecture.

---

## §3 Target topology

### 3.1 Same-origin path routing

```nginx
location /arena      { proxy_pass http://<arena-box>:19992; }   # the arena's own frontend
location /api/arena  { proxy_pass http://<arena-box>:19993; }   # the arena API
location /api        { proxy_pass http://172.18.0.1:19994; }    # DatsMe backend (unchanged)
location /           { proxy_pass http://172.18.0.1:19995; }    # DatsMe frontend (unchanged)
```

nginx matches the longest prefix, so `/api/arena` must be declared alongside `/api`; both existing
blocks are untouched.

#### 3.1.1 Why not `arena.datsme.me`

The session cookie is set with `{"samesite": "lax", "secure": not is_dev_env()}` and **no `domain`
attribute** (`../datsme_me/api/auth.py:76`). It is therefore host-scoped: a subdomain would never
receive it. The "fix" is to widen it to `.datsme.me` — which would ship DatsMe's bearer JWT to
`pet.datsme.me`, `pet-staging.datsme.me` and `pool.datsme.me`.

**Path routing buys a separate box with zero auth change:** same origin, cookie flows, no CORS.
(It does **not** give CSRF for free — same-origin cookie auth is what *requires* CSRF protection,
and a separate process inherits none of DatsMe's middleware. See §4.8.) This is also the same nginx-location shape the arena already runs on today, so §5's proxy
lessons transfer directly.

### 3.2 Boxes and ports

Its own box, for a reason that is measured rather than assumed: the arena holds long-lived SSE
connections, ticks at a fixed 10 Hz regardless of load, and runs a CPU-bound referee under a global
lock — **~4.3 ms per room per tick, ceiling ~20 concurrently racing rooms**
(`SPEC_PET_ARENA_ROOMS` §13). Co-tenanting that with login and messaging means each starves the
other and an arena overload takes down authentication. Separate box = separate failure domain.

Ports, taken from the **occupied** host band (`../datsme_me/CLAUDE.md:101`) rather than guessed:

| Service | prod | staging |
|---|---|---|
| DatsMe frontend | 19995 | 29995 |
| DatsMe backend | 19994 | 29994 |
| **PostgreSQL** | **19993** | — |
| **TTS sidecar** | **19992** | 29992 |
| Emulator viewer | 19991 | — |
| Gotenberg | 19990 | 29990 |
| **arena API** | **19989** | **29989** |
| **arena frontend** | **19988** | **29988** |

**19989/19988 is not a guess — it is the host's own written rule.** `../datsme_me/CLAUDE.md:117`:
*"the next service goes to `x9989` and downward."* The arena is the next service.

**Rev.1 originally proposed 19993/19992 and both were already taken** — PostgreSQL and the TTS
sidecar. The correction is recorded because "pick a free number in the band" is the kind of thing
that gets re-guessed by someone who did not read line 117.

### 3.3 Its own frontend

A Next app with `basePath: "/arena"`, built the way DatsPet already builds a static export. **An
arena UI change deploys the arena box and nothing else** — DatsMe's web tier is never rebuilt for a
race feature, which is the whole point of the separation.

Cost, stated: navigating between DatsMe and the arena is a full page load rather than a client
transition, and the arena carries its own shell rather than DatsMe's nav. Acceptable, and the same
seam the current launch flow already has.

### 3.4 Shard by room, never by user

DatsMe routes by `users.home_node`. **The arena must route by room code**, because five players
homed to five different nodes have to land in one process.

Rooms are ephemeral and self-contained, so N arena processes own disjoint room sets — a consistent
hash on the room code at nginx, `--workers 1` preserved per process. **No broker, no Redis.**
`SPEC_PET_ARENA_ROOMS` §13's tripwire ("the move is a broker and it is a real project") is answered
by choosing the right shard key instead of buying infrastructure.

This is also the sharpest reason the arena must not live inside DatsMe's web tier: **it does not
shard on the same key.**

---

## §4 Where each piece of data comes from

### 4.1 Identity

Rev.1 said "validated against PostgreSQL `user_sessions`, mirroring `get_current_user`." That
described half the path and understated what mirroring costs. The real path
(`../datsme_me/api/auth.py:378`) is six steps:

```
_decode_request_token(request)   # JWT decode against DATSME_SECRET_KEY (auth.py:23)
→ load User from PostgreSQL
→ _session_ok(...)               # user_sessions revocation check
→ _maybe_rotate_credential(...)  # RE-MINTS the token and re-sets the cookie   ← WRITE
→ _ensure_csrf_cookie(...)       #                                            ← WRITE
→ throttled activity tracking    #                                            ← WRITE
```

**Three of the six are writes, and the first one needs a minting key.**

#### 4.1.1 The arena does NOT hold `DATSME_SECRET_KEY`

`SECRET_KEY = os.environ.get("DATSME_SECRET_KEY")` (`../datsme_me/api/auth.py:23`) is a **symmetric
HS key**. A box holding it can *mint* a session for any user, not merely verify one. Putting it on
the arena box would make §4.6.1's SELECT-only grant meaningless as a boundary — a service that can
forge any user's identity does not need write access to the social database to do damage.

**Decision: the arena resolves identity by introspection, not by local decode.** It forwards the
request's cookie to a small DatsMe endpoint that runs the real `get_current_user` inside DatsMe's own
process and returns the resolved user id. Consequences, all of them wanted:

- **No signing key ever leaves DatsMe.** The arena can verify a session it is shown; it cannot
  invent one.
- **The three writes happen where write access already exists** — rotation, CSRF backfill and
  activity tracking run in DatsMe's process, not the arena's. §4.6.1's SELECT-only role becomes
  *true* rather than aspirational.
- **Introspect once per connection, not per request** (§4.6): resolve at session/stream start, hold
  the user id for that connection's life. A race does not re-introspect at 10 Hz.

The alternative considered and rejected: **asymmetric signing**, where DatsMe signs RS256 and the
arena verifies with a public key. It is cleaner in principle and needs no round trip, but it changes
the host's token format for every existing client — a platform-wide migration to serve one new
service. Revisit only if introspection latency proves to matter, which at once per connection it
will not.

#### 4.1.2 The unsolved half: sliding-session renewal

`_maybe_rotate_credential` re-sets the cookie **on the response**. Under introspection that response
goes to the arena, not to the browser — so a player who spends an hour in the arena and never loads a
DatsMe page would never rotate, and the cookie could expire underneath them mid-race.

Two candidate answers: the arena **forwards the introspection response's `Set-Cookie`** to the
browser (works, standard, slightly fiddly), or DatsMe exposes an explicit renew call the arena's
frontend pings. **This needs the host's input and is §12.7.** It is small, and it is exactly the
class of thing that is invisible until a real user has been in a lounge for fifty minutes.

`owner_scope.resolve_owner_scope` is replaced wholesale either way. Note what it resolves today:
DatsMe identity, borrowed through DatsPet. The migration removes a detour.

### 4.2 Friends

PostgreSQL `relationships` (`../datsme_me/api/social_models.py:338`) — already the source of truth
(*"PostgreSQL is source of truth for relationships"*). The arena reads the shared layer.

**`connections.read` is retired** (§9). There is no capability, no consent screen, no ids-only
compromise, and no §7-Direction-B argument to win.

### 4.3 Pet ownership — an existing route, not a projection

**Rev.1 proposed a published projection into PostgreSQL and that was wrong.** It cited
`SPEC_DATSME_MULTI_NODE` §5.2, but that spec is **"Status: proposed (not implemented)"** and
`home_node` appears in **zero** lines of `../datsme_me/api/**.py`. There is one node. The projection
does not exist, nothing publishes into it, and building it would have meant implementing the first
slice of multi-node in another repo as a prerequisite for this one.

**What exists instead:** `GET /api/pets/me` (`../datsme_me/api/apps/pets/pet_routes.py:181`) — the
launch user's own pets, already the host's authoritative answer.

The arena calls it **server-side, forwarding the user's cookie**, at session start. Server-side
because ownership is a *gate* — "only compete with pets you own" is not a claim the browser may
make about itself.

**No new host route, no projection, no capability, no schema.** When multi-node is actually built,
this call keeps working: it is the host's own route and the host owns the routing.

**And it is one call, not two.** `list_my_pets` depends on `get_current_user_db`
(`../datsme_me/api/apps/pets/pet_routes.py:183`), which resolves the session inside DatsMe's process
before it answers. So on the join and lounge-entry paths the arena does **not** introspect and then
list — the list *is* the introspection, and a 200 proves both "this cookie is a live session" and
"these are that user's pets." §4.1.1's introspection endpoint is for the paths that need identity
without ownership: stream attach, impulse POSTs, lounge presence.

**What it does not carry: `source_item_id`.** `pet_service.pet_dict()` returns ten fields
(`../datsme_me/api/apps/pets/pet_service.py:326-338`) and that is not one of them. §5.1 needs it,
which is why §12.9 is a `datsme_me` change.

### 4.4 Pet bytes — the host's existing asset route

**Rev.1's node→node fetch is deleted for the same reason as §4.3**: it targeted infrastructure that
does not exist.

The host already ships the whole delivery path, and it is better than what Rev.1 proposed to build:

| | |
|---|---|
| `GET /api/pets/{pet_id}/sheet.png` | `../datsme_me/api/apps/pets/pet_routes.py:704` |
| `GET /api/pets/{pet_id}/manifest.json` | `:789` |
| gate | `_authorized_asset_session` (`:515`) → `_resolve_pet_owner` (`:122`) + `_enforce_visibility` (`:474`) |
| already built | ETag/`If-None-Match`/304 (`_asset_etag` `:587`, `_if_none_match_hit` `:609`), WebP negotiation, and a **304 answered from a digest column before the BLOB is read** (`SPEC_PET_ASSET_DELIVERY_AND_CACHE` §4.A) |

Same origin, cookie flows, no new protocol, no cross-node hop.

#### 4.4.1 The one thing that does not fit: the anonymous spectator

`_enforce_visibility` is a visibility ladder over *host* identity. It will never serve an
**unauthenticated** viewer — and `SPEC_PET_ARENA_ROOMS` §14.1 deliberately does, because the whole
point of the spectator URL is a link you send to a grandparent.

**So a room-scoped grant survives — but as a thin proxy over the route above, not a new protocol
plus a byte cache.** The mechanism needs nothing from the host:

1. A player **joins** a room. That request carries **their own** cookie, and they are choosing to
   enter their pet.
2. At that moment the arena fetches *their* sheet and manifest from the host **using their
   credential**. The arena never impersonates anyone: each pet is fetched by its own owner's
   session, at the moment that owner volunteers it.
3. The bytes are held **in the room**, and the room-scoped route
   (`SPEC_PET_ARENA_ROOMS` §4.3) serves them to players and anonymous spectators alike — same
   route, same **sheet-and-manifest-only** rule, **never `bundle_zip`**, and dying with the room.

This is `SPEC_PET_ARENA_ROOMS` §4.3 unchanged in intent — *"membership in a live room is the
capability"* — with the byte source repointed from a local blob to the host's route.

**Memory, not disk:** ≤5 sheets per room at a measured 2.3 MB average (max 6.4 MB) is ~11 MB per
room. That is room state on a dedicated box, and it evaporates on reap exactly as every other part
of a room does.

**~220 MB is a FLOOR, not a ceiling — Rev.2 had this backwards.** §3.2's ~20 is the CPU ceiling for
concurrently *racing* rooms; a room also holds its sheets while it sits in the lobby and through
`ROOM_RESULT_TTL_S` after finishing, and `ROOM_IDLE_TTL_S` is 15 minutes. **Live rooms outnumber
racing rooms**, so size the box against live-room count and add lounge presences (§4.4.2). The
tripwire is memory pressure, not the racing ceiling, and they are different numbers — measure the
live-room high-water mark on staging before sizing prod.

#### 4.4.2 The lounge — the same rule, one seam earlier

**A lounge is not a room, and §4.4.1 does not reach it.** `webui/arena_lounges.py:322`
(`_seat_from_presence`) reads *another player's* manifest to resolve their stats when a challenge is
accepted — inside the **acceptor's** request. That pet's owner is not the caller, their cookie is not
present, and no room exists yet to hold anything. The one invariant §4.4.1 rests on is unavailable
exactly there.

**The fix is the same rule applied at lounge entry, and the code already has the hook.** A player
enters a lounge with their own pet and their own cookie (`arena_lounges.py:211`, gated at `:221`):

1. At **entry**, the arena fetches that pet's `manifest.json` from the host **with the entrant's own
   credential** — the same act, the same moment, the same justification as §4.4.1's join fetch.
2. The manifest (and its `resolve_athletics` result) is held on the **presence record**, not
   globally.
3. `_seat_from_presence` then reads what presence already holds. It performs no fetch, needs no
   credential, and stops being a cross-user read.
4. It dies when the presence lapses, exactly as `SPEC_PET_ARENA_LOUNGE` already specifies.

**Sheets are not fetched at lounge entry today, and that is not luck.** `_snapshot`
(`arena_lounges.py:166-188`) publishes `presence_id`, `pet_id` and `pet_label` only — pet thumbnails
are explicitly deferred (`web/src/arena/lounge/LoungeView.tsx:15`). Manifests are the whole
requirement now.

**Forward note, so the next person does not invent a second mechanism:** `SPEC_PET_ARENA_VENUE`
plans presence with pets *visible*. When that ships, the lounge needs a lounge-scoped asset grant of
exactly §4.4.1's shape — fetched at entry by the owner, served from presence, dying with it, **sheet
and manifest only, never `bundle_zip`**. Add it here; do not build a third path.

### 4.5 Athletics

Unchanged in behavior. DatsPet stamps at build; the arena calls `resolve_athletics`, which handles
present, stale and absent blocks with defined precedence and **forbids branching on which path
ran**. That property is what makes this migration low-risk: the arena can score *any* pet it
meets — store, gifted, another partner's, or built before the stamp existed.

---

### 4.6 The arena holds NO TRUTH and NO DISK STATE

The environment pattern is already established on both sides and the arena simply follows it: one
PostgreSQL server per box, the **database name** carrying the environment.

| env | database | reached via |
|---|---|---|
| local | `datsme_social` @ `localhost:19993` | `DATABASE_URL` in `api/.env` |
| staging | `datsme_staging_social` | `DATABASE_URL` on the staging box |
| prod | `datsme_social` | `DATABASE_URL` on the prod box |

**What falls out of it is the good part: the arena needs no store of its own.**
`SPEC_PET_ARENA_ROOMS` §0.10.4 already forbids one — *"No new SQLite table. A room is transient
state, and the store is for things that outlive a request."* Rooms and lounges are in-memory dicts;
nothing is persisted; §2.4 already accepts that a restart ends live races.

So the arena service stores **nothing on disk at all** — no schema, no migrations, no backups, no
cache file. Room assets (§4.4.1) live in memory with the room and die with it. Deploying the arena
is copying a binary and restarting; there is no state to preserve, migrate, or back up.

Identity, ownership and friends are resolved per connection (§4.1, §4.3) and held for that
connection's life — never written down.

#### 4.6.1 Read-only against PostgreSQL — and NOT the security boundary

The arena's only direct PostgreSQL read is **`relationships`** (§4.2) — already the shared layer,
already source of truth. Identity and ownership go through the host's own routes instead (§4.1.1,
§4.3), so the arena **writes nothing**: sessions are resolved by introspection rather than minted,
and the three writes inside `get_current_user` happen in DatsMe's process (§4.1.1).

**Therefore the arena connects with a distinct PostgreSQL role holding `SELECT` only.** This is not
a convention to be remembered; it is a grant, and a buggy arena cannot corrupt DatsMe's social data.

**Rev.1 called this the containment boundary. It is not, and the correction matters.** Under Rev.1's
§4.1 the arena would have held `DATSME_SECRET_KEY` — and a box that can mint any user's session does
not need database writes to do harm. A SELECT-only grant on a box holding the platform's signing key
is theatre.

**§4.1.1 is what makes the grant meaningful:** the key stays on DatsMe, the arena introspects, and
the three writes in `get_current_user` happen inside DatsMe's process where write access already
exists. The grant is then an accurate description of the arena's reach rather than a claim
contradicted one section earlier. **If a future arena feature needs to write to the shared layer,
that is a design review, not a grant change** (§11).

### 4.7 No cache — and the test that keeps it that way

**Rev.1 specified a 2 GiB content-addressed SQLite sheet cache. It is deleted.** It existed to
amortise the 11 MB-per-room cross-node fetch that §4.4 no longer performs: the host's route already
answers repeat views with a **304 from a digest column, before the BLOB is read**
(`../datsme_me/api/apps/pets/pet_routes.py:704`, `SPEC_PET_ASSET_DELIVERY_AND_CACHE` §4.A). Building
a second cache in front of a cache, to avoid a fetch that no longer happens, is pure debt.

What survives is the rule that was the best part of it.

#### 4.7.1 Cache the bytes. Never cache the facts.

**Ownership, friendship and identity are resolved live (§4.1, §4.3) and are never written to disk.**
They are mutable facts owned by another system, and a local copy of a mutable host fact is precisely
the defect that produced `SPEC_PET_OWNERSHIP` — a DatsPet surface claiming 21 pets were in a house
that holds 12, because a copy could not learn it had changed.

**The test that separates the two, and the one to apply to anything proposed for this service
later:** *if it were deleted, is anything lost but speed?* A row that fails that test is not a cache
— it is a store, and it does not belong here. §11 tripwires it.

This is also why §4.4.1's room-held assets are not a violation: they die with the room, and
`SPEC_PET_ARENA_ROOMS` §2.4 already specifies that a room's death costs nothing.

### 4.8 CSRF — ported, not inherited

**Rev.1's §3.1.1 listed "CSRF works" as a benefit of same-origin path routing. That was backwards.**
Same-origin cookie authentication is exactly the condition that *requires* CSRF protection: the
browser attaches the `datsme.me` session cookie to any cross-site-initiated request at that origin.

DatsMe enforces it with `CsrfProtectionMiddleware` (`../datsme_me/api/csrf.py:92`), mounted at
`../datsme_me/api/main.py:466-467`. **A separate FastAPI process serving `/api/arena` inherits none
of it.** Without a port, every arena mutation — join, start, impulses, lounge challenge — is an
unprotected cookie-authenticated write on the `datsme.me` origin.

**Port the double-submit check.** It needs **no shared secret** — the cookie half is already set by
DatsMe (`_ensure_csrf_cookie`, non-`httponly` by design so the frontend can read it), and the check
is "does the header match the cookie." That is why this is a small task and not a protocol
negotiation. **It is in A1's definition of done**, because a security control discovered at A5 is a
security control that shipped absent.

---

## §5 The seams — decide these BEFORE code moves

### 5.0 Pre-flight: diff the two pet runtimes (thirty minutes, do it first)

§1.4 compared `web/src/pet/` by **filename**. Same names is not same code, and §3.3's frontend plan
assumes the host's copy is a compatible superset.

**This is an input to the plan, not a phase of it.** Rev.1 scheduled it inside A0/A1 — after the
phase table that depends on its answer.

**DONE 2026-08-03. Result: they have diverged, and the host's is not a superset** (§1.4). Four files
are near-identical, four have drifted substantially toward the host, `index.ts` has drifted in both
directions, and `locomotion/` is a different architecture with a DatsPet file (`quadruped.ts`) that
has no host counterpart. **§2.5's duplication is therefore forced.** Half an hour, and it removed an
assumption the entire frontend plan rested on.

### 5.1 The nudge anchor — the one that silently breaks pets

`identity_nudges_from_pet_id(pet_id)` is what makes two identical designs different individuals.
Today, for a pet with no stored block, those nudges are derived from **DatsPet's** pet id.

**Verified 2026-08-03: 0 of 46 pets in the dev database carry a stamped block** — the stamp landed
35 minutes after the newest pet was built. So *every pet that exists today* derives its nudges live,
from the DatsPet id.

Two facts collide:

- The host carries DatsPet's id as `source_item_id` — but **gifting deliberately strips it**
  (`pet_gift_service.py:431`, `source_item_id=None`). *(Rev.2 cited `:428`; corrected.)*
- The host's own `Pet.id` **is** carried through a gift (`pet_gift_service.py:419`,
  `id=carried["id"]  # PG-3: id carried`).

**RESOLVED 2026-08-03, and CORRECTED in Rev.3. The anchor is: the stamped block's
`identity_nudges` when present; else `source_item_id`; else the host `Pet.id` — and rung 2 requires
one field the host does not currently expose (§12.9).**

> **Rev.3 correction — the ladder was right and unreadable.** Rev.2 recorded this as resolved without
> checking that the arena can *read* rung 2. It cannot. `pet_service.pet_dict()`
> (`../datsme_me/api/apps/pets/pet_service.py:326-338`) returns `id, name, breed_id, slot_index,
> is_active, personality_profile, visibility, source, adopted_at, updated_at` — **no
> `source_item_id`** — and a sweep of `../datsme_me/api/**.py` finds the column only on the model
> (`pet_models.py:115`), its uniqueness index (`:137`), and DPP writeback/import internals. **No host
> response carries it.** §4.3 routes ownership through `/api/pets/me` specifically so the arena never
> reads per-user tables (§0.14.3), so the shortcut is closed by design, not by accident.

The reasoning for the ladder itself, from the verified facts rather than preference:

1. **For a stamped pet the question does not arise.** `resolve_athletics` reuses the block's stored
   `identity_nudges` even when re-deriving a stale block — identity survives a rebalance *and* a
   nudge-algorithm change, and the block travels inside the manifest, so it survives gifting too.
2. **For an unstamped pet, `source_item_id` is DatsPet's pet id** — the exact value the nudges were
   derived from today. Using it means the 46 existing pets keep the stats they already have when the
   arena moves. Anchoring straight to the host `Pet.id` would silently restat every one of them on
   migration day.
3. **Host `Pet.id` is the fallback because it survives gifting** (`pet_gift_service.py:419`) where
   `source_item_id` does not (`:431`).

**That set is bounded and closing, which is the actual mitigation.** Every pet built since
2026-08-02 11:24 carries its nudges in the manifest (§2.3, verified against real packer output).
Only pets built *before* that are exposed, and only if gifted before being re-stamped.

#### 5.1.1 Rung 2 is a closing-window rung, and that is what makes the change small

`source_item_id` is not a permanent part of the anchor. It exists for exactly one bounded,
**shrinking** population: pets built before the stamp landed, which derive their nudges live from
the DatsPet id today. Every pet built after it carries its own nudges and never consults rung 2.
Rung 2 goes quiet on its own.

That framing is what §12.9 amounts to: **one read-only field on a serializer, to carry a migration
window, harmless thereafter.** Not a route, not a schema change, not a capability. It is worth
stating that plainly even with one owner, because a field added "just for the migration" is exactly
the kind of thing that outlives its reason unnoticed.

#### 5.1.2 Run the census BEFORE ratifying, not after

Rev.2 listed the census as the mitigation and scheduled it after the decision it should inform.
**Reverse that.** The census is what tells you which of these you are actually choosing between:

- **Few unstamped pets on staging and prod** → drop rung 2 entirely, anchor stamped → host `Pet.id`,
  withdraw §12.9, and accept a handful of restatted pets. **No host change at all.**
- **Many** → §12.9 is worth asking for, because the alternative is silently restatting every one of
  them on migration day.

The dev box has **46** unstamped pets. Staging and prod must be **counted, not extrapolated**
(CLAUDE.md: verify per-environment state — and this is precisely the case that rule exists for,
since dev is the box where pets get built for testing and is the least representative of the three).

**The census is a one-query job with no dependencies, and it runs BEFORE A0** (§6.1.2).

*Rev.3 moved it from A3 to A1 and did not go far enough — that is circular.* A1 is blocked on the
12.6/12.7 being decided, and the census exists to decide whether 12.9 is needed at all. A
measurement that gates a decision cannot sit behind the phase that waits for that decision. It has
**zero** dependencies — no service, no box, no decision, just a query against each environment's
database — so it belongs ahead of everything.

**The honest limit that survives either branch:** an **unstamped** pet that is **gifted** loses its
original nudges irrecoverably — the gift destroys `source_item_id` (`pet_gift_service.py:431`) and
there is no stored block to fall back on. The information is gone, not mis-addressed. No anchor
choice recovers it.

### 5.2 Anonymous code-room players — RESOLVED: there are none

**Owner, 2026-08-03:**

> "you need a DatsMe account in order to play, just like you need a datsme account to design and buy
> pets. **if you don't have a datsme pet, it is not possible for you to play.**"

`SPEC_PET_ARENA_VENUE` §1.3 ("a shared room code… stays open to anonymous players", owner call the
same day) is **retired**. It was decided about a *partner* surface; the arena now runs on
`datsme.me`, and the platform's own rule applies — designing, buying and racing are all
account-gated, and racing is no different from the other two.

**Two consequences, both simplifications:**

1. **The arena service needs no guest identity path for contestants.** Every mutating route resolves
   a real DatsMe user (§4.1.1). This removes a whole surface that would have needed its own
   duty-of-care review.
2. **Owning a pet is the entry condition, not just a per-entrant rule.** §4.3's `GET /api/pets/me`
   gate is what enforces it, and a signed-in user with an empty house cannot join — which needs a
   real UX answer rather than a disabled button (§5.2.2).

#### 5.2.2 The empty-house path is the funnel's last step

A user who has signed in *because they watched a race* (§5.2.1) arrives with no pets. "Join" must
route them to getting one — DatsPet's designer or the Pet Store — not to a dead control. This is
the one new surface this decision creates, and it is small.

#### 5.2.1 Spectators — RESOLVED: anonymous, and deliberately so

**Owner, 2026-08-03:**

> "as for watching, **anyone can watch**. in fact, i was going to put that as a public link so people
> can observe, and if they want to participate, they will need to sign on to datsme."

So the asymmetry is the design, not a compromise: **watching is the front door.** The public
spectator link is an acquisition path — see a race, sign up, get a pet, play — and §5.2.2 is its
last step.

This means the arena **deliberately serves a DatsMe user's pet sheet to an unauthenticated stranger
from inside the `datsme.me` origin**, stepping outside the host's own `_enforce_visibility` ladder,
which never does that. §4.4.1 is the mechanism and it is now load-bearing rather than an edge case.

**`SPEC_PET_ARENA_ROOMS` §6 carries over verbatim, and is now protecting a `datsme.me` URL rather
than a partner one:** unguessable codes, never listed, no player names, dies with the room,
**sheet and manifest only — never `bundle_zip`**, and never the provenance block (a bundle carries
the designer's typed words). Those rules were written for exactly this and none of them weaken; what
changed is that the origin on the URL now belongs to the platform, which raises the cost of getting
them wrong rather than lowering it.

### 5.3 Does standalone DatsPet keep an arena?

`SPEC_PET_ARENA_ROOMS` §0.10.2 currently guarantees *"solo and hot-seat play keep working with the
server switched off."* After the migration, the arena requires DatsMe for everything.

**Recommendation: retire the guarantee.** Local arena development moves from DatsPet's stack to
DatsMe's, which is a setup change, not an architectural cost — see §5.3.1.

#### 5.3.1 Local development — resolved, and NOT a parity seam

Rev.1 flagged this as an unresolved risk and was wrong. The reasoning that removes it:

- **DatsMe already requires PostgreSQL locally**, with no fallback — `api/social_db.py:44` raises
  `RuntimeError("DATABASE_URL is not set")`. Every host developer already runs it on 19993. The
  arena depending on PostgreSQL is the same class of dependency the arena already has on DatsPet's
  backend and SQLite today; it is not a new kind of thing.
- **Therefore no dev-mode auth shim is needed.** That was the actual worry — a fake local session
  would mean the real auth path only ever executes on staging. But a real DatsMe runs locally with
  real PostgreSQL and real sessions, so **dev exercises the same code path as prod.** There is no
  seam because there is nothing being faked.

**The rule that keeps it that way: do not build a fake-session mode.** If local arena work ever
needs a shortcut around a real session, that is the moment this becomes a parity seam — and §11
tripwires it.

Residual cost, stated plainly and accepted: an arena developer runs four processes (PostgreSQL,
DatsMe backend, arena API, arena frontend) where two suffice today. Setup, not architecture, and the
host already ships `start_backend_only.sh` / `start_frontend_only.sh` for its half.

### 5.4 `StatBars.tsx` — RESOLVED: it simply moves (Rev.1 had this backwards)

Rev.1 said to hoist it out of `web/src/arena/` before the migration so the Pet Store would not lose
it. **Measured 2026-08-03: `StatBars` has 4 consumers and all 4 are inside `web/src/arena/`**
(`JumpResultsScreen`, `PetProfileModal`, `ResultsScreen`, `SetupScreen`). **Zero outside.** No store
surface displays athletics today.

**So it moves with the arena, and Rev.1's hoist was building for a hypothetical** — the exact
"single-element abstraction" CLAUDE.md warns against. If the Pet Store later wants stat bars it has
everything it needs: DatsPet keeps `resolve_athletics` because it keeps the mint (§2.3), and the
component is presentational. It is the *rule* below that DatsPet must keep, not the component.

**And the rule that goes with it:** a store listing must read stats through `resolve_athletics`,
**never** `manifest["athletics"]` directly. Pets are stamped once and never re-stamped, so after a
`TABLE_VERSION` bump a raw read shows old numbers while the arena races new ones — a bug that looks
exactly like the game cheating.

---

## §6 Phases

Each phase is independently verifiable. **A0 is a gate: if it fails, nothing after it matters.**

| Phase | Ships | Why here |
|---|---|---|
| **Census** | **§5.1.2's unstamped-pet count on staging and prod** (§6.1.2). One query per environment. | Decides whether §12.9 is needed at all, so it precedes the decision. **Zero dependencies — one query per environment.** |
| **A0** | nginx `/arena` + `/api/arena` blocks on DatsMe **staging**, `proxy_buffering off`, pointed at a stub. **Two assertions: (1)** an SSE stream is still open after **90 s**; **(2)** an authenticated request through `/api/arena` **resolves the right user** — i.e. the session cookie actually arrives at the arena box. | §5 cost this project a day once, and R0 is first because proxy behaviour cannot be observed locally. **The cookie half is equally unobservable locally and is the other half of §3.1.1's entire argument** — if the cookie does not arrive, path routing bought nothing and the design is wrong, not late. |
| **A1** | Arena service skeleton on its own box: FastAPI, `--workers 1`, **identity via introspection** (§4.1.1), **the CSRF double-submit port** (§4.8), health endpoint. **No game.** | Proves identity end to end with nothing else in the way. CSRF is here and not later because a control discovered at A5 is a control that shipped absent. |
| **A2** | Ownership via `GET /api/pets/me` and assets via the host's `/api/pets/{id}/sheet.png`, behind the room-scoped proxy (§4.3, §4.4.1), exercised by a throwaway route | **Rev.1 called this "the only genuinely new plumbing" when it was the largest item in the plan and lived in another repo.** Against existing host routes it is now the smallest phase — which is the whole point of B1's correction. |
| **A3** | Move `arena_rooms.py` + `arena_lounges.py`; repoint the **four** call sites (§1.2), **including the lounge's entry-time manifest fetch** (§4.4.2); **dual-published** athletics package with the `race_vectors.json` cross-engine test green in both repos (§2.4). **Precondition: §12.9 answered** (or withdrawn per §5.1.2). | The code moves nearly unchanged; the package does not. The fixture is the gate — a table skew is caught by `TABLE_VERSION`, an engine skew only by that file. The lounge is called out because §1.2's Rev.2 table hid it inside a room row and it is a genuinely different fix. |
| **A4** | The arena frontend as its own Next app under `basePath: "/arena"`, including the five external imports of §2.1 | §2.1's dispositions are per-import; `ModalOverlay` is a rebuild, not a move |
| **A5** | **Delete** the six lines and two pages from DatsPet (§2.2). Retire `connections.read` (§9). | The cleanup is part of the change |
| **A6** | Room-affinity sharding — **only when one process is not enough** | Measured ceiling is ~20 concurrent races; do not pre-build it |

### 6.1 A0 and the census, concretely

Rev.3 described both in prose. Whoever picks this up should not have to re-derive them.

#### 6.1.1 The nginx blocks (DatsMe **staging** first — never prod)

Added to the host's `deploy/nginx.staging.conf`, alongside the existing `/api` and `/` blocks, which
are **not** modified. nginx matches longest-prefix, so `/api/arena` must be declared for it to win
over `/api`:

```nginx
# The arena's own frontend (Next, basePath "/arena")
location /arena {
    proxy_pass http://<arena-box>:29988;
    proxy_http_version 1.1;
    proxy_set_header Host              $host;
    proxy_set_header X-Real-IP         $remote_addr;
    proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}

# The arena API. MUST be declared before/alongside `location /api` — longest
# prefix wins, and this one has to.
location /api/arena {
    proxy_pass http://<arena-box>:29989;
    proxy_http_version 1.1;
    proxy_set_header Host              $host;
    proxy_set_header X-Real-IP         $remote_addr;
    proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    # SSE. Without these the stream buffers and the race appears frozen, then
    # jumps — it looks like an application bug and it is not
    # (SPEC_PET_ARENA_ROOMS §5.1).
    proxy_buffering    off;
    proxy_cache        off;
    proxy_read_timeout 3600s;
    chunked_transfer_encoding off;
}
```

**Two traps this project has already paid for.** `SPEC_PET_ARENA_ROOMS` §5.4: DatsPet's own
`nginx-default.conf` is *production's*, and copying it onto staging silently pointed staging at the
prod backend — cost a day. And per `datsme-pet-factory_wu` memory, nginx regex braces need quoting
and any change must gate on `nginx -t`'s **exit code**, not its output text.

#### 6.1.2 A0's two assertions, and the census query

A0 passes only if **both** of these do. Run against the real staging URL, never localhost:

```bash
# (1) The stream survives past the outer proxy's 60 s idle default.
#     SPEC_PET_ARENA_ROOMS §5.2 — a 504 at 60.2 s is the documented failure.
timeout 95 curl -sN https://<staging-host>/api/arena/_probe/stream | ts | tee /tmp/a0.log
#     PASS: output is still arriving after 90 s.

# (2) The session cookie actually reaches the arena box.
#     This is the other half of §3.1.1's argument; if it fails, path routing
#     bought nothing and the design is wrong, not late.
curl -s -b "token=<a real staging session cookie>"      https://<staging-host>/api/arena/_probe/whoami
#     PASS: returns the SAME user id that GET /api/pets/me returns for that cookie.
```

The stub behind `_probe` is ~20 lines: one `StreamingResponse` emitting a heartbeat every
`SSE_HEARTBEAT_S`, and one route echoing the resolved user. **No game code, no database.**

**The census (§5.1.2), one query per environment** — this is the unstamped-pet count that decides
whether §12.9 is needed at all:

```sql
-- Run against staging's and prod's datspet.db. NOT dev: dev is where pets get
-- built for testing and is the least representative of the three.
SELECT
  COUNT(*)                                                        AS non_draft_pets,
  SUM(json_extract(manifest_json, '$.athletics') IS NULL)          AS unstamped,
  SUM(json_extract(manifest_json, '$.athletics') IS NULL
      AND external_user_id IS NOT NULL)                            AS unstamped_and_owned
FROM pets
WHERE draft = 0;
```

`unstamped_and_owned` is the number that matters, and it is **not** the same as `unstamped`: a pet
with `external_user_id IS NULL` is a standalone/local pet that belongs to no DatsMe user, so it can
never appear in `/api/pets/me` and can never be restatted by this migration.

**Dev reads 46 non-draft, 46 unstamped, but only 26 unstamped-and-owned** — the other 20 are
anonymous and irrelevant here. Query verified against the dev database 2026-08-03. If staging and
prod read near zero on the third column, §12.9 is dropped and the `datsme_me` work list is two
items instead of three.

---

**A5 is not optional and not deferrable.** CLAUDE.md: finish the refactor; a dual-mount transition
layer is how two arenas end up live at once.

---

## §7 The four test questions

1. **New variant → engine change?** No. A new event is still a JSON declaration; a new challenge is
   still a file in the frontend registry. The move does not touch either.
2. **New feature → unrelated files?** **Improved.** Today an arena social feature needs a DPP
   capability, a consent screen, a protocol amendment and a cross-repo E2E. After, it is a query
   against the shared layer.
3. **Third-party integration → owned code paths?** DatsPet's factory keeps its partner adapter
   unchanged. The arena stops being a third party, which is the point.
4. **Bug in one variant → shared debugging?** Honest exception, unchanged from
   `SPEC_PET_ARENA_ROOMS` §9.4: the transport is genuinely shared. The move does not make this
   worse; it moves it onto infrastructure with a bigger blast radius, which is why A0 exists.

---

## §8 Verification

- **A0's two assertions against the real deployed staging URL: the 90-second stream, and that the
  session cookie arrives** (§6). This is `scripts/verify_deployment.sh` §7 repointed and widened, and
  per CLAUDE.md *every deploy failure in this project so far has been a false green* — a status code
  is not the gate.
- **A CSRF test that a cookie-authenticated POST without the matching header is REFUSED** (§4.8).
  The failure mode is silent: everything works in a browser that sends both, and the control is
  simply absent.
- **An introspection test that the arena never sees `DATSME_SECRET_KEY`** (§4.1.1) — assert the
  variable is unset in the arena's environment and that identity still resolves. The temptation to
  "just decode it locally, it's faster" is the whole reason this is a test.
- **The arena's existing suites move with it** (`webui/tests/test_arena_rooms.py`,
  `test_arena_stream.py`, `test_arena_lounges.py`, the race-vector fixture that pins the two
  integrators). They should pass on the new service with only import changes; **if they need logic
  changes, something moved that should not have.**
- **A live two-repo round trip before A5 deletes anything:** build a pet in DatsPet, adopt it into
  DatsMe, gift it to a second user, sign in as that user, and race it. Unit gates on either side do
  not prove a cross-system loop — that lesson is standing policy here.
- **A guard test that the arena imports nothing from `pet_factory` but the shared tables package**
  (§0.14.4).
- **A test that no host fetch ever uses a credential other than the pet owner's** (§4.4.1, §4.4.2).
  Assert that seating a lounge challenge performs **zero** outbound host calls — every manifest it
  needs was fetched at entry by its own owner. This is the test that keeps the arena from quietly
  growing an impersonation path the first time someone finds a pet whose stats it cannot resolve.
- **A test that the nudge anchor resolves the same value before and after the move** (§5.1). Take a
  real unstamped pet, resolve its nudges through DatsPet's current path and through the arena's
  ladder, and assert equality. This is the one defect in the migration that is invisible at runtime:
  nothing errors, the pet is simply a different animal.
- **The `race_vectors.json` cross-engine test green in BOTH repos** (§2.4). `TABLE_VERSION` catches a
  table skew; only this fixture catches the TS engine and the Python referee drifting apart, and it
  fails silently when absent.
- **A guard test that the arena writes nothing to PostgreSQL** — run the suite against the
  SELECT-only role (§4.6.1). A role that is correct in the deploy script and wrong in code is a
  runtime 500 in a race, not a startup error.

---

## §9 What this retires

- **`connections.read`** — deleted from `PROPOSAL_DPP_PARTNER_READS`. The arena reads
  `relationships` directly.
- **Most of `SPEC_PET_OWNERSHIP`** — the borrowed roster, the digest matching, the roster-scoped
  asset route, the never-persist discipline. All of it existed to cross a boundary that is being
  removed.
- **What survives from that spec is factory-only:** the house page still shows "✓ In DatsMe (21)"
  against a 12-pet house, and that defect is real regardless of where the arena lives. It keeps
  `pets.read_owned`, and `SPEC_PET_OWNERSHIP` narrows to that surface.
- **`SPEC_PET_ARENA_VENUE` §5/§12's friendship discussion** — the layered "competing is open,
  talking requires friends" model stays a product decision; the *mechanism* section becomes moot.

---

## §10 Deliberately not done

- **No broker, no Redis** (§3.4). Room-sharding instead.
- **No dual mount.** The arena does not run in both places, even briefly (§6, A5).
- **No shared pet runtime package** (§2.5). The duplication is the boundary.
- **No arena inside DatsMe's web tier** — different resource profile, different shard key (§3.2, §3.4).
- **No subdomain** (§3.1.1).
- **No cookie-domain widening**, under any circumstances.
- **No move of the athletics mint** (§2.3).
- **No guest identity for contestants** (§5.2). Playing is account-gated like designing and buying;
  the arena never mints an identity of its own.
- **No disk state on the arena box** (§4.6) — Rev.1's content-addressed sheet cache is deleted, not
  deferred; the host's route already answers repeat views with a 304 from a digest column.
- **No signing key on the arena box** (§4.1.1). Identity is introspected, never decoded locally.
- **No new host routes.** §4.3 and §4.4 use what `pet_routes.py` already ships. The complete list of
  host-side additions contemplated anywhere in this spec is **three**, and it is closed: the
  introspection endpoint (§4.1.1 / §12.6), §12.7's renewal answer, and **one read-only field on an
  existing serializer** (§12.9). Anything a fourth item would buy, re-read §0.14.3 first.
- **No implementation of multi-node as a prerequisite.** Rev.1 required it without saying so; §4.3
  and §4.4 now work on the single node that exists, and keep working when multi-node arrives.

---

## §11 Tripwires

- **Anyone proposes `arena.datsme.me`** → §3.1.1. The cookie fix that follows is a security
  regression across every partner box.
- **Anyone proposes routing the arena by user or `home_node`** → §3.4. Races fragment silently and
  the failure looks like a networking bug.
- **The arena reads a per-user table directly instead of a host route** → §0.14.3. That is a shared
  database, and schema changes become cross-service outages. **`pets.source_item_id` is the live
  temptation** (§5.1): it is one SELECT away and the host does not expose it. Ask for the field
  (§12.9); do not reach into the table.
- **The arena fetches a pet with anyone's credential but its owner's** → §4.4.1, §4.4.2. The moment
  the arena can fetch a pet on behalf of a user who did not volunteer it, it has an impersonation
  path and `_enforce_visibility` is no longer the host's to enforce. The symptom that leads here is
  benign: "seating this challenge needs stats I don't have."
- **An arena feature needs a DPP capability** → something did not actually move; re-read §1.5.
- **Someone consolidates the two pet runtimes** → §2.5, and the two deploys re-couple.
- **Anything is proposed for storage on the arena box** → §4.7.1. Apply the deletion test: if
  removing it loses more than speed, it is a store, not a cache, and it is the `SPEC_PET_OWNERSHIP`
  defect being rebuilt. The arena currently has **no disk state at all** (§4.6), which is the
  cheapest possible starting position to defend.
- **`DATSME_SECRET_KEY` is proposed for the arena box** → §4.1.1. A box that can mint any user's
  session makes §4.6.1's SELECT-only grant meaningless. Introspection exists to avoid exactly this.
- **An arena route is added without the CSRF check** → §4.8. Same-origin cookie auth means every
  unprotected mutation is a cross-site write on `datsme.me`.
- **The athletics tables get hand-copied into the arena repo** → §2.4. Two copies fail silently:
  the browser and the referee disagree about a race and nothing errors.
- **The arena needs to WRITE to the shared PostgreSQL** → §4.6.1. Its role is SELECT-only by grant;
  a write requirement means something was designed on the wrong side of the boundary. Design review,
  not a grant change.
- **Anyone builds a fake-session / dev-auth mode for local arena work** → §5.3.1. A real DatsMe runs
  locally with real sessions; the moment one is faked, dev and prod stop exercising the same auth
  path and this becomes the parity seam it currently is not.
- **A0 cannot be made to work on DatsMe's proxies** → stop. The arena stays where it is, and the
  partner-capability path in `PROPOSAL_DPP_PARTNER_READS` is revived intact.

---

## §12 Open decisions

**All of these are the same person's, on both sides of the wire** (Rev.5). Items that read like
requests to a host — 12.6, 12.7, 12.9 — are decisions to make and code to write in `datsme_me`.
Nothing here waits on a reply.

**12.1 Port band — RESOLVED 2026-08-03.** **19989/19988** (prod), **29989/29988** (staging), per
`../datsme_me/CLAUDE.md:117` ("the next service goes to `x9989` and downward"). Verified unclaimed:
zero occurrences of any of the four across both repos' scripts, configs, services and docs.

**12.2 Anonymous code-room players — ANSWERED 2026-08-03 (§5.2).** Venue §1.3 is **retired**: an
account is required to play, exactly as it is to design and buy. No guest identity path is built.
Owning a pet is the entry condition (§5.2.2).

**12.3 The nudge anchor — RESOLVED 2026-08-03, with one dependency added in Rev.3 (§5.1).** Stamped
`identity_nudges` → `source_item_id` → host `Pet.id`, in that order. Preserves existing pets' stats
on migration day and survives gifting thereafter. **Rung 2 requires §12.9**, and §5.1.2's census
decides whether it is needed at all. **Owner ratification wanted on one point only:** an unstamped
pet that is gifted before being re-stamped loses its original character irrecoverably, and that is
accepted rather than engineered around.

**12.4 The factory's house page keeps `pets.read_owned` — ANSWERED 2026-08-03.** Owner: *"for data
integrity and consistency, i think it would be good to have the factory house page [read] owned."*

The reasoning is the deciding one and worth keeping: **the house page's job is to tell the truth
about where your pets are**, and it cannot do that from a delivery receipt (`SPEC_PET_OWNERSHIP`
§1). That holds whether or not the arena ever moves — which is why this survives the placement
decision while `connections.read` does not.

**12.5 Where does the arena's code live?** Its own repo, or a directory inside `datsme_me` deployed
separately? Recommend **its own repo**: the deploy independence in §3.3 is the reason for the whole
shape, and a directory inside the host repo re-couples it to the host's `reset --hard origin/master`
deploy flow.

> **The `datsme_me` half is tracked in its own repo** as
> [`ARENA_WORK_ON_THE_DATSME_SIDE`](../../datsme_me/docs/ARENA_WORK_ON_THE_DATSME_SIDE.md) — three
> code items and one design call, closed at three. 12.6 and 12.7 live there; 12.9 is listed as
> "measure before writing it," pending §5.1.2's census. `pets.read_owned` (12.4) is independent of
> the placement decision and can proceed on its own.

**12.6 Identity: introspection, or change the token format? — DECIDE, then build in `datsme_me`.**
§4.1.1 recommends
**introspection** — the arena forwards a cookie, DatsMe resolves it, no signing key leaves the host.
The alternative is asymmetric (RS256) signing so the arena can verify with a public key and no round
trip. That is cleaner in principle and is a platform-wide token migration for every existing client.
Confirm introspection, or accept the migration.

**12.7 Sliding-session renewal for a long arena session — DESIGN CALL, `datsme_me` side** (§4.1.2). `_maybe_rotate_credential`
re-sets the cookie on the response — which under introspection goes to the arena, not the browser. A
player who spends an hour in a lounge without loading a DatsMe page would never rotate, and the
cookie could expire mid-race. Forward the introspection response's `Set-Cookie`, or expose a renew
call? **This is answered in `datsme_me`'s session model, not in the arena** — same owner, but
genuinely the other codebase's decision to make.

**12.8 Anonymous spectators — ANSWERED 2026-08-03 (§5.2.1).** Anyone may watch; the public link is
a deliberate acquisition path. `SPEC_PET_ARENA_ROOMS` §6's rules carry over **verbatim** and now
protect a `datsme.me` URL.

**12.9 Expose `source_item_id` on `GET /api/pets/me`? — MEASURE FIRST, then a one-line change in
`datsme_me`.** *(New in Rev.3; reframed in Rev.5 — it was never an "ask".)*

`pet_service.pet_dict()` (`../datsme_me/api/apps/pets/pet_service.py:326-338`) returns ten fields;
`source_item_id` is not among them, and no other host response carries it. **§5.1's nudge anchor
needs it**, and §0.14.3 forbids the alternative of reading `pets.source_item_id` directly.

**What it amounts to: one read-only field added to an existing serializer.** No route, no schema
change, no capability, no consent surface. The value is the DatsPet pet id the host already
stores and already treats as authoritative provenance (`../datsme_me/api/apps/dpp/service.py:1983`).

**Why it is worth a host change:** without it, every pet built before the athletics stamp landed
(2026-08-02 11:24) is **silently restatted on migration day** — same design, different animal, no
error anywhere. With it, they keep the character they have.

**Why it may be withdrawable:** §5.1.2's census. If staging and prod hold few unstamped pets, drop
rung 2, anchor stamped → host `Pet.id`, and ask the host for nothing. **Run the census before
raising this with the host** — it converts a request into either a small justified ask or a
non-issue, and a field should not be added to a shipped serializer on a hunch.

**Sequence, so this is not decided blind:**

1. **Run the census** (§6.1.2) on staging and prod. DatsPet alone, no dependencies.
2. **Near zero** → drop §12.9, anchor stamped → host `Pet.id`, and the `datsme_me` work list stays
   at two (introspection + renewal).
3. **Material** → it becomes item #3 on the `datsme_me` work list, with the measured number as its
   justification (`ARENA_WORK_ON_THE_DATSME_SIDE` §4).

A field added to a shipped serializer outlives the reason it was added, so the count comes first —
which is why step 1 is not optional and why the census moved ahead of A0 (§5.1.2).
