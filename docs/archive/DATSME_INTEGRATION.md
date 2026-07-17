> **ARCHIVED 2026-07-16 — never built; superseded.** This isolation-first plan to embed pet
> generation *inside* the DatsMe host was never implemented. The shipped architecture inverts it:
> DatsPet is a standalone DPP partner app that DatsMe launches and receives writebacks from — see
> `docs/SPEC_DATSPET_DPP_INTEGRATION.md` (live, E2E-verified) and `docs/SPEC_DATSPET_HOUSE_ADOPT.md`.
> Kept for historical reference; do not implement from this document.

# Integrating pet_factory into DatsMe — cleanly and safely

A concrete plan for a **"Make your own pet"** feature, written against DatsMe's
*actual* conventions (verified by reading `docs/datsme_coding_rules.md`,
`docs/ARCHITECTURE_LIMITATIONS.md`, `docs/CONFIGURABLE_FEATURES.md`,
`docs/GUIDE_SQLITE_AT_SCALE.md`, the `SPEC_PET_PHASE_*` specs,
`REVIEW_PET_FEATURE_DESIGN_RISKS.md`, and the `lessons_learned/` sqlite notes).

**Design goals**

1. **Fully ignorable at runtime.** If the feature is off, buggy, or its GPU
   worker is down, DatsMe runs exactly as today.
2. **Neat & removable.** New backend code is a couple of prefixed files inside
   `apps/pets/`; removing the feature is a short, well-defined checklist.

`pet_factory` is **never imported by DatsMe** — only by the GPU worker.

> How "fully ignorable" is achieved *the DatsMe way*: a **runtime feature flag**
> (disable instantly, no deploy) + a **self-contained module** nothing else
> imports + FastAPI's per-request isolation (a bug in a pet endpoint is a 500 on
> *that* request, never the app). DatsMe deliberately **fails loud at boot** and
> does *not* wrap `include_router` in try/except — swallowing import errors is an
> anti-pattern here (see `lessons_learned/learned_sqlalchemy_renamed_column_swallowed_by_cors_20260521.md`).
> So: register the router plainly, and rely on the flag + module boundaries.

---

## The shape

```
  BROWSER (Next.js)         DATSME API (FastAPI, no GPU)              GPU BOX
  ────────────────         ────────────────────────────             ───────
  "Make my pet: fox"  POST  /api/pets/gen/create                     worker.py
   poll status              • table pet_gen_jobs (Postgres)          • polls DatsMe (HTTPS + signed)
   pet appears in house     • flag pet_gen_enabled (system_config)  ⇄ • import pet_factory
                            • on complete → REUSE DatsMe's own         • make_pet_zip(animal, breed_id="ai_<uuid>")
                              validate + create_pet + write_assets     • uploads .zip back
                            NEVER imports pet_factory
```

---

## Backend — new files inside `apps/pets/`, matching the existing flat layout

DatsMe's pets module is **flat, prefix-named files** (`pet_routes.py`,
`pet_service.py`, `pet_assets_service.py`), and `ARCHITECTURE_LIMITATIONS.md`
("colocation forces context") cites exactly this directory as the model. So:

```
apps/pets/pet_gen_routes.py     # the router (user + worker endpoints)
apps/pets/pet_gen_config.py     # feature-flag defaults + reader (system_config)
# PetGenJob model goes in social_models.py (see below) — NOT a new models file
```

Register it the same way `pets_router` is — re-exported from the package
`__init__.py` (its docstring says "the main application imports only from this
file"):

```python
# apps/pets/__init__.py — add:
from apps.pets.pet_gen_routes import pet_gen_router

# main.py — next to `from apps.pets import pets_router`:
from apps.pets import pet_gen_router
app.include_router(pet_gen_router)          # plain include, like every other router
```

### The job table — define it in `social_models.py` (that's how Postgres tables register)

DatsMe has **no Alembic**. Central tables are `SocialBase` ORM classes in
`social_models.py`; `init_social_db()` runs `SocialBase.metadata.create_all(...)`
at startup (additive — never drops). A model file that isn't imported into that
metadata graph would simply never create its table. So add:

```python
# in social_models.py, alongside the other central models.
# NOTE: import utc_now from time_utils here (social_models.py imports
# `from time_utils import utc_now` to avoid a circular import via helpers).
class PetGenJob(SocialBase):
    __tablename__ = "pet_gen_jobs"
    id         = Column(String, primary_key=True)
    # FK + CASCADE so jobs vanish with the account (every central table does this)
    user_id    = Column(String, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    animal     = Column(String)
    status     = Column(String, default="queued")   # queued|processing|done|error
    breed_id   = Column(String, nullable=True)
    pct        = Column(Float, default=0.0)
    msg        = Column(String, default="")
    error      = Column(String, nullable=True)
    dedupe_key = Column(String, index=True)          # guard against duplicate pets on retry
    # DatsMe convention: NO `default=` on timestamps — the caller passes
    # created_at=utc_now() (see every model in social_models.py).
    created_at = Column(DateTime, nullable=False)
```

### The feature flag — reuse `system_config` (don't invent one)

Copy the shape of `apps/personal_agent/agent_config.py` (the sanctioned pattern):
a `_CONFIG_DEFAULTS` list of `(key, value, description)`, an `ensure_*` that
inserts missing keys at startup, and a reader. Precedent key:
`("agent_platform_enabled", "yes", ...)`. So use:

```python
# pet_gen_config.py
PET_GEN_CONFIG_DEFAULTS = [("pet_gen_enabled", "yes", "Enable the 'make your own pet' generator")]
def pet_gen_enabled(social_db) -> bool:
    return get_config_value(social_db, "pet_gen_enabled") == "yes"   # helpers.py:get_config_value
```

### The routes (`pet_gen_routes.py`)

**User-facing** (normal auth):

```python
@pet_gen_router.post("/api/pets/gen/create")
def create_job(body: CreateReq, user=Depends(get_current_user), social_db=Depends(get_social_db)):
    if not pet_gen_enabled(social_db):
        raise HTTPException(503, "Pet generator is off")
    dedupe = f"{user.id}:{body.animal.strip().lower()}"          # optional: 1 in-flight per animal
    jid = uuid4().hex[:12]
    social_db.add(PetGenJob(id=jid, user_id=user.id, animal=body.animal.strip()[:60],
                            status="queued", dedupe_key=dedupe, created_at=utc_now()))
    social_db.commit()
    return {"job_id": jid}

@pet_gen_router.get("/api/pets/gen/{jid}")
def job_status(jid, user=Depends(get_current_user), social_db=Depends(get_social_db)):
    j = social_db.query(PetGenJob).filter_by(id=jid, user_id=user.id).first()
    if not j: raise HTTPException(404)
    return {"status": j.status, "pct": j.pct, "msg": j.msg, "error": j.error, "breed_id": j.breed_id}

@pet_gen_router.get("/api/pets/gen-health")
def gen_health(social_db=Depends(get_social_db)):
    return {"enabled": pet_gen_enabled(social_db), "worker_online": _worker_online()}
```

**Worker-facing** — authenticate like DatsMe's other machine callers: a
**hashed** service-account key (`service_accounts` table + `X-Admin-API-Key`
pattern, revocable/audited) or the DPP HMAC-shared-secret pattern. Store a hash,
never plaintext; never commit the secret.

The `complete` handler creates the pet with the **same write calls
`upload_my_pet` uses** — `create_pet` → `write_assets` → `_write_ownership` —
minus the credit charge (creation is free; the docs confirm that's fine). Two
differences from `upload_my_pet`, both deliberate:

- It opens the per-user SQLite via **`open_user_database_context(user_id)`**
  (a worker has no request-scoped user; `GUIDE_SQLITE_AT_SCALE` + the
  sqlite-lifecycle lesson mandate the context manager for worker/arbitrary-user
  writes — never `open + close`, never roll your own engine).
- **`_write_ownership` is currently a private (`_`) function in
  `pet_routes.py`.** Importing another module's private symbol is brittle;
  promote it to a small public helper (e.g. `pet_ownership_service.write_ownership`)
  that both `pet_routes` and `pet_gen_routes` call. (Both files sit in
  `apps/pets/`, so this is a one-line refactor, not new surface.)

Keep the **content-leads ordering** — the user SQLite is committed *before* the
Postgres ownership row (`create_pet` self-commits the pets row; `write_assets`
requires the caller to commit; then ownership):

```python
@pet_gen_router.post("/api/pets/gen/complete")
async def complete(job_id=Form(...), file: UploadFile = File(...),
                   social_db=Depends(get_social_db), _=Depends(require_worker_auth)):
    j = social_db.query(PetGenJob).filter_by(id=job_id).first()
    if not j: raise HTTPException(404)
    try:
        body = await file.read(pet_assets_service._admin_helpers()[0] + 1)
        parsed = pet_assets_service.validate_uploaded_bundle(body)          # SAME validator as upload
        with open_user_database_context(j.user_id) as user_db:              # context manager (prescribed)
            pet = pet_service.create_pet(user_db, breed_id=parsed["breed_id"],
                    name=pet_service.validate_name(f"My {parsed['display_name']}"),
                    personality_profile={}, source="ai_generated",
                    activate_new=False, visibility="public",
                    max_pets=pet_service.DEFAULT_MAX_PETS_PER_USER)
            pet_assets_service.write_assets(user_db, pet_id=pet.id,
                    sheet_png=parsed["sheet_png"], manifest_json=parsed["manifest_json"],
                    package_json=parsed["package_json"], source="ai_generated",
                    source_breed_id=parsed["breed_id"])
            user_db.commit()                                                 # commit assets yourself (docstring)
        _write_ownership(social_db, pet_id=pet.id, user_id=j.user_id, source="ai_generated")
        j.status = "done"; j.breed_id = parsed["breed_id"]; social_db.commit()
    except Exception as e:
        j.status = "error"; j.error = str(e)[:300]; social_db.commit()      # never a partial pet
    return {"ok": True}
```

(`claim` / `progress` / `fail` are trivial row updates — copy the shapes from
[`examples/queue_server.py`](examples/queue_server.py).)

### Two correctness notes the DatsMe pet specs require

- **Namespace the breed_id.** `REVIEW_PET_FEATURE_DESIGN_RISKS.md` Risk #6:
  a synthesized `breed_id` that collides with a platform catalog breed makes the
  frontend show the wrong label/metadata. Have the worker pass a namespaced id —
  `make_pet_zip(animal, breed_id=f"ai_{uuid4().hex}")` — so it can never collide.
  (`make_pet_zip` already accepts a `breed_id` argument, and the manifest now
  carries `schema_version: "pet_manifest.v1"`.)
- **`source` is a free-form string** (no enum/validation), so `"ai_generated"`
  works. If you want to match the two documented vocabularies exactly, the real
  upload route uses `source="user_uploaded"` on `create_pet` and `source="upload"`
  on `write_assets`/`_write_ownership`; pick per-table consistently. Nothing
  branches on `source`, so this is cosmetic.

---

## Frontend — one addition, mirroring the existing upload button

In `web/src/app/[slug]/settings/pet/page.tsx`, next to "⬆ Upload a pet bundle
(.zip)", add a "🪄 Make your own pet" input + button. The create/status/health
calls are plain JSON, so use the page's **`apiFetch`** wrapper (it attaches the
`Bearer` token automatically) — *not* `handleUploadBundle`'s raw `fetch`, which
exists only because it sends a binary blob. For feedback reuse the page's real
helpers **`flashStatus` / `flashError` / `setBusy`** (there's no progress-bar
state today — add one or just show `flashStatus(j.msg)`). Flow: POST `{animal}`
to `/api/pets/gen/create`, poll `/api/pets/gen/{id}`, and on `done` call
`reloadPets()` (the pet is already in the house).

Gate the control on `GET /api/pets/gen-health` — hide/disable it when `enabled`
is false or `worker_online` is false, so an offline GPU box just means the button
isn't there and the rest of Settings → Pet works. **`gen-health` must always
return HTTP 200** (with `{enabled, worker_online}`): `apiFetch` throws on any
non-2xx, so a 503 would make the poll error every tick.

---

## The GPU box (outside DatsMe)

```bash
pip install "git+https://github.com/jeffhancook/datsme-pet-factory"
QUEUE_URL=https://<datsme-api>  WORKER_TOKEN=<signed-secret>  python -m examples.worker
```
(with ComfyUI + models running — see README). Only place `pet_factory` is imported.

---

## Failure modes — everything degrades to "the feature just isn't there"

| What breaks | What happens | DatsMe core affected? |
|-------------|--------------|-----------------------|
| Flag `pet_gen_enabled=no` | `create` → 503; frontend hides the button | **No** (instant, no deploy) |
| GPU worker offline | health `worker_online:false`; button hidden; jobs wait | **No** |
| Worker generation fails | worker calls `/fail`; job → `error`; nothing is written | **No** |
| Invalid bundle at `complete` | rejected by `validate_uploaded_bundle` **before any pet is written**; job → `error` | **No** — same safety as the upload button |
| A pet-gen endpoint throws at runtime | FastAPI returns 500 for *that* request only | **No** |
| Job retried | `dedupe_key` prevents a duplicate pet | **No** |
| `pet_gen` code has an import error | Fails **loud** at boot (by DatsMe convention — caught in CI/dev, not shipped) | boot fails until fixed — *intended*; don't ship a broken module |

Because `complete` runs the **same `validate_uploaded_bundle` + `write_assets`**
as the existing upload button, a generated pet can never be riskier than a
hand-uploaded one.

---

## Removing the feature entirely

1. Delete `apps/pets/pet_gen_routes.py` and `apps/pets/pet_gen_config.py`, the
   frontend control, and the `PetGenJob` class in `social_models.py`.
2. Delete the two `pet_gen_router` lines in `main.py`.
3. `DROP TABLE pet_gen_jobs;` and remove the `pet_gen_enabled` `system_config` row.

DatsMe is back to today — no existing pet code was ever modified.
