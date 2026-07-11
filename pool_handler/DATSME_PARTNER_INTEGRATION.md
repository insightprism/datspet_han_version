# DatsPet ⇄ DatsMe — partner-protocol integration design

**What this answers:** how to make DatsPet a proper **DatsMe partner** (via the DatsMe Partner
Protocol, DPP) so a user can adopt a pool-generated pet *through DatsMe's standard partner flow*
— the same way the Personality partner works — instead of the current manual "generate zip →
click Upload."

**Reviewed sources (read, not assumed):**
- `datsme_me/docs/keep_SPEC_DATSME_PARTNER_PROTOCOL.md` — the DPP spec (v1.0-dev). Notably it
  uses **"DatsMe Pets" as its canonical partner-#2 example throughout** (§3.4).
- `datsme_me/api/apps/dpp/` — the built host-side DPP module (registry, manifest, launch,
  writeback, targets). Real and working; the Personality + HarpSee partners use it.
- `datsme_me/api/apps/pets/pet_routes.py` + `pet_assets_service.py` — DatsMe's existing pet
  ingestion (`POST /api/pets/me/upload`, `write_assets`), already proven with our cardinal.
- `datsme_personality/` — the live reference partner.
- The pool: `shared_gpu_cpu` + this repo's `pool_handler/` (the cardinal was generated through it).

---

## 1. The three systems, and where DPP fits

```
  pet-factory (this repo)      shared_gpu_cpu pool          DatsMe (datsme_me)
  ─ makes the pet ─            ─ delivers the compute ─     ─ owns the user + the pet ─
  make_pet_zip(animal)         routes to a GPU, runs it,    stores pet assets on the
  → sprite + manifest → .zip   returns the .zip bytes       user's node; animates it
```

The pool is the **compute** layer (any GPU makes the pet). DPP is the **user-consent + data-
sovereignty** layer (how the pet legitimately becomes *this user's* pet on DatsMe). They are
orthogonal and both needed: the pool answers "who has a spare GPU," DPP answers "did the user
ask for this, and does the result land on their node."

---

## 2. The one hard design fact — DPP writebacks are tiny; a pet is a 1 MB asset

This is the crux, verified in the DatsMe code:

- A DPP **writeback** is a small signed JSON record. `dpp/service.py` literally notes *"a
  writeback is a few hundred bytes, so 64 KB is vastly more than needed."*
- The `user.collection` target stores an **`item`** with `title`, `excerpt`, and a
  **`public_url`** (an `http(s)` link, validated) — i.e. **a card that references content the
  partner hosts**, not the content itself. (`_validate_collection_item`, `service.py`.)
- A pet is a **~1 MB sprite-sheet bundle** (BLOB). It cannot ride a writeback inline, and it
  should not — DPP deliberately keeps writebacks small.

**Therefore the pet's *bytes* and the pet's *consent/record* travel by two different paths.**
DatsMe already has the bytes path: `POST /api/pets/me/upload` → `write_assets()` stores the
sprite/manifest as a `pet_assets` BLOB on the user's node (this is what our cardinal used, and
it already satisfies sovereignty — the pet lives on the user's DatsMe node, not on DatsPet).

So the integration is **not** "cram the zip into a writeback." It is: **use DPP for the launch
+ consent + the small record, and reuse DatsMe's existing pet-asset ingestion for the bytes.**

---

## 3. Recommended design — DPP launch, pool compute, existing asset path for bytes

Two clean options; recommendation first.

### Option A (recommended) — DatsPet is a DPP partner; the pet-asset write stays host-internal

The DatsPet partner app implements the standard three DPP callbacks (`build_manifest`,
`handle_launch`, `on_action_complete`) exactly like Personality. The novelty is only in *where
the 1 MB lands*:

```
1. LAUNCH   User clicks "Adopt a Pet" on DatsMe → DatsMe mints a launch token
            (capabilities: identity.activity.write [required], feed.post [optional])
            → redirects to the DatsPet partner app.

2. CHOOSE   In the DatsPet partner UI the user picks an animal ("cardinal bird").

3. GENERATE DatsPet submits {task: pet_factory, params:{animal}} to the POOL
            (pool.datsme.me) — the compute layer. Pool returns the .zip bytes.
            (This is exactly what created_pets/make_pet.py already does.)

4. LAND THE BYTES  DatsPet hands the bytes to DatsMe's existing pet ingestion for
            this user. Two sub-options for the byte transfer (see §4); the clean one
            is a host-side "adopt from partner" that pulls the bytes using the launch
            token, so the pet_assets BLOB is written by DatsMe, on the user's node.

5. WRITEBACK  DatsPet sends the standard small DPP writeback — the *record* of the
            adoption (target identity.activity or user.collection): breed_id, name,
            a thumbnail public_url, adopted_at. Tiny JSON, per spec.

6. LIVE     The pet is a pet_assets row owned by the user; PetCanvas animates it on
            the profile — identical to today's manual upload, just reached through
            the consented partner flow.
```

**Why this is right:** it uses DPP for exactly what DPP is for (consent, identity, the durable
record, sovereignty/export/revoke) and reuses DatsMe's *already-built, already-proven* pet-asset
storage for the bytes. No new "big binary over DPP" mechanism — which the spec deliberately
avoids. The pool stays a pure compute layer that neither DatsMe nor DPP needs to know about.

### Option B — skip DPP; keep the manual/scripted upload

What we did for the cardinal: generate via the pool, then `POST /api/pets/me/upload`. Works, but
it is **outside** the partner protocol: no consent screen, no capability grants, no partner
registry entry, no export/revoke wiring, no "Adopt a Pet" activity in DatsMe's Available list. Fine
for testing; not how a real partner ships. **Use A for the product.**

---

## 4. The byte-transfer seam (the only genuinely new piece)

Everything else is standard DPP or standard pet-upload. The one thing DPP doesn't already define
is *how the 1 MB gets from the partner to the user's node*. Three ways, cleanest first:

1. **Host-pull via a partner asset endpoint (recommended).** The DatsPet writeback (or a
   `public_url` in the collection item) points at a short-lived partner URL that serves the
   generated `.zip`. On writeback, DatsMe fetches it (authenticated by the launch token / HMAC),
   validates it with the *existing* `validate_uploaded_bundle`, and writes `pet_assets`. Bytes
   land on the user's node; DatsPet never has standing access. This mirrors HarpSee's
   `public_url` pattern and needs a small host-side "adopt-from-partner-bundle" path (a thin
   wrapper over the code already in `pet_routes.upload_my_pet`).
2. **Partner-push to the existing upload endpoint using the launch token.** DatsPet calls
   `POST /api/pets/me/upload` on the user's behalf, authorized by the launch token instead of a
   user session. Reuses `upload_my_pet` almost verbatim; needs that route to accept a launch-token
   auth path. Simple, but puts the big POST on the partner→host path.
3. **User-mediated (today's manual path), automated in the partner UI.** The partner UI downloads
   the zip in the browser and posts it to `/api/pets/me/upload` with the user's own session. No
   host change at all, but it isn't a clean server-to-server partner flow.

**Recommendation: (1).** It keeps writebacks tiny (spec-compliant), keeps the bytes off the
DPP channel, reuses DatsMe's bundle validator, and lands assets on the user's node via the
existing storage path.

---

## 5. Concrete work list

**Pool (shared_gpu_cpu) — already done.** `pet_factory` runs on `omen-pet`; a submit returns the
`.zip`. Nothing to change. (The future `pool_client` library, spec §12, just makes the DatsPet
partner's call to the pool a one-liner instead of hand-rolled HTTP.)

**DatsPet partner app (new, in this repo or a `datspet-partner/` service) — the real work:**
- Install the DatsMe partner SDK; implement the three callbacks (mirror `datsme_personality`):
  - `build_manifest()` — one activity `adopt_virtual_pet`, capability `identity.activity.write`
    (required) + `feed.post` (optional); declare the export/revoke endpoints.
  - `handle_launch(ctx)` — render the "pick an animal" UI.
  - `on_action_complete()` — after the pool returns the bundle, host the zip at a short-lived
    URL and emit the small writeback (record + `public_url` to the bundle).
- Implement the sovereignty endpoints (`/partner/export/{user_id}`, `/partner/revoke`) — the SDK
  provides base classes; for pets these are near-trivial (DatsPet stores little per user — the
  pet bytes already live on DatsMe's side once adopted).
- Submit-to-pool logic (the `make_pet.py` flow, server-side).
- Register with DatsMe: `POST /api/partners/register {slug:"datsme_pets", ...}` → get the HMAC
  secret. **No DatsMe code change to register** (that's the whole point of DPP §3.2).

**DatsMe host (datsme_me) — small, one-time:**
- Add the byte-transfer seam of §4 option 1: an "adopt-from-partner-bundle" path that, on a pet
  writeback, fetches the partner-hosted zip, runs the *existing* `validate_uploaded_bundle`, and
  calls the *existing* `write_assets`. This is a thin new target/handler, not a rewrite — the
  ingestion and storage already exist and are proven (our cardinal).
- Optionally define a `pet.asset` DPP target (or reuse `user.collection` with an asset-bundle
  `public_url` convention) — a spec decision for the DatsMe protocol owner.

---

## 6. Why this is the natural fit (and largely pre-thought)

The DPP spec **already names DatsMe Pets as its worked example of partner #2** (§3.4): the
manifest, the `adopt_virtual_pet` activity, the capability set. The protocol was designed with
pets in mind. The *only* thing the spec's pet example glossed is that a pet carries a 1 MB asset
— and DatsMe *already* solved asset ingestion for pets independently (`/api/pets/me/upload` +
`write_assets`, which our cardinal used successfully). So the integration is: **connect two
things that already exist** — DPP's consent/launch/record flow and DatsMe's pet-asset storage —
with one small host-side "adopt-from-partner-bundle" seam, and the pool underneath as the GPU
that makes the pet.

**Sovereignty is already satisfied:** once adopted, the pet's bytes are a `pet_assets` BLOB on
the user's DatsMe node. DatsPet going offline doesn't affect the user's pet (DPP invariant 6).
The user can export/delete it via DatsMe. That is exactly what the partner protocol promises.

---

## 7. Open questions for the DatsMe protocol owner

1. **New `pet.asset` target vs. `user.collection` + `public_url` bundle convention?** Either
   works; the former is cleaner long-term, the latter needs zero new target. (§4, §5.)
2. **Byte-transfer direction** — host-pull (recommended) vs. partner-push to `/api/pets/me/upload`
   via launch-token auth. (§4.)
3. **Does adopting through the pool consume DatsMe credits** (`credits.consume` capability)?
   Pets currently charge an adoption fee host-side (`_charge_adoption`); decide whether the
   partner flow reuses that or the partner charges.
4. **Which DatsPet — the reference `pet_factory` or the full `datsPet` app — becomes the
   registered partner service** that hosts `/partner/manifest` etc.
