# Integrating pet_factory into DatsMe — cleanly and safely

This is a concrete plan for adding a **"Make your own pet"** feature to DatsMe,
written against DatsMe's actual architecture (FastAPI + central Postgres +
per-user SQLite; Next.js frontend).

**Two non-negotiable design goals** (read this first):

1. **Fully ignorable.** If this feature breaks, is disabled, or its GPU worker
   is offline, DatsMe must run *exactly* as it does today. Nothing in the core
   paths changes.
2. **Neat and removable.** All new backend code lives in one folder
   (`apps/pets/pet_gen/`); the frontend gets one component. Removing the feature
   is: delete those files, delete one wrapped `include_router` line, drop one
   table. Done.

`pet_factory` is **never imported by DatsMe.** It only runs on the GPU box.

---

## The shape of it

```
  BROWSER (Next.js)         DATSME API (FastAPI, no GPU)              GPU BOX
  ────────────────         ────────────────────────────             ───────
  "Make my pet: fox"  POST  /api/pets/gen/create                     worker.py
   poll status              • new table pet_gen_jobs (Postgres)      • polls DatsMe (HTTPS+token)
   pet appears in house     • worker endpoints (token)        ⇄      • import pet_factory
                            • on complete → reuse DatsMe's            • make_pet_zip("fox")
                              validate + create_pet + write_assets    • uploads .zip back
                            NEVER imports pet_factory
```

The queue is [`examples/queue_server.py`](examples/queue_server.py) rewritten as
a DatsMe router; the worker is [`examples/worker.py`](examples/worker.py) run as-is.

---

## Backend — all new, all in `apps/pets/pet_gen/`

```
apps/pets/pet_gen/
  __init__.py         # exports pet_gen_router
  models.py           # PetGenJob (its own table)
  routes.py           # the router (user endpoints + worker endpoints)
  config.py           # PET_GEN_ENABLED flag lookup
```

Nothing in existing files (`pet_routes.py`, `pet_service.py`,
`pet_assets_service.py`, `pet_models.py`) is edited. The feature **reuses** them.

### The one — and only — edit to a core file

`api/main.py`, wrapped so a broken module can never stop the app from booting:

```python
# Pet generation (optional feature — isolated). If it fails to import for any
# reason, DatsMe boots and runs normally without it.
try:
    from apps.pets.pet_gen import pet_gen_router
    app.include_router(pet_gen_router)
except Exception as e:
    logging.getLogger(__name__).warning("pet_gen disabled: %s", e)
```

That try/except is the heart of goal #1: **the feature can fail completely and
DatsMe is unaffected.**

### The table (`models.py`)

A single new table in the central Postgres — no foreign keys into existing
tables, so dropping it touches nothing else:

```python
class PetGenJob(Base):
    __tablename__ = "pet_gen_jobs"
    id         = Column(String, primary_key=True)
    user_id    = Column(String, index=True)     # who asked (set at create time)
    animal     = Column(String)
    status     = Column(String, default="queued")   # queued|processing|done|error
    breed_id   = Column(String, nullable=True)
    pct        = Column(Float, default=0.0)
    msg        = Column(String, default="")
    error      = Column(String, nullable=True)
    created_at = Column(Float)
```

### The routes (`routes.py`)

**User-facing** (normal DatsMe auth):

```python
@pet_gen_router.post("/api/pets/gen/create")
def create_job(body: CreateReq,
               user: User = Depends(get_current_user),
               social_db: Session = Depends(get_social_db)):
    if not pet_gen_enabled(social_db):
        raise HTTPException(503, "Pet generator is off")
    # optional: cap queued jobs per user
    jid = uuid4().hex[:12]
    social_db.add(PetGenJob(id=jid, user_id=user.id, animal=body.animal.strip()[:60],
                            status="queued", created_at=time.time()))
    social_db.commit()
    return {"job_id": jid}

@pet_gen_router.get("/api/pets/gen/{jid}")
def job_status(jid: str, user: User = Depends(get_current_user),
               social_db: Session = Depends(get_social_db)):
    j = social_db.query(PetGenJob).filter_by(id=jid, user_id=user.id).first()
    if not j: raise HTTPException(404)
    return {"status": j.status, "pct": j.pct, "msg": j.msg, "error": j.error,
            "breed_id": j.breed_id}

@pet_gen_router.get("/api/pets/gen-health")
def gen_health(social_db: Session = Depends(get_social_db)):
    return {"enabled": pet_gen_enabled(social_db),
            "worker_online": (time.time() - _last_seen[0]) < 90}
```

**Worker-facing** (shared-secret header, NOT user auth). This is where the pet
gets written into the user's house by **reusing DatsMe's own services** — the
same calls `upload_my_pet` makes, minus the credit charge:

```python
@pet_gen_router.post("/api/pets/gen/claim")
def claim(social_db=Depends(get_social_db), _=Depends(require_worker)):
    j = social_db.query(PetGenJob).filter_by(status="queued")\
                 .order_by(PetGenJob.created_at).first()
    if not j: return {}
    j.status = "processing"; social_db.commit()
    return {"job_id": j.id, "animal": j.animal}

@pet_gen_router.post("/api/pets/gen/complete")
async def complete(job_id: str = Form(...), breed_id: str = Form(...),
                   file: UploadFile = File(...),
                   social_db=Depends(get_social_db), _=Depends(require_worker)):
    j = social_db.query(PetGenJob).filter_by(id=job_id).first()
    if not j: raise HTTPException(404)
    try:
        body = await file.read(pet_assets_service._admin_helpers()[0] + 1)
        parsed = pet_assets_service.validate_uploaded_bundle(body)   # SAME validator as upload
        user_db = open_user_database(j.user_id)                      # write into ASKER's SQLite
        try:
            pet = pet_service.create_pet(user_db, breed_id=parsed["breed_id"],
                    name=pet_service.validate_name(f"My {parsed['display_name']}"),
                    personality_profile={}, source="ai_generated",
                    activate_new=False, visibility="public",
                    max_pets=pet_service.DEFAULT_MAX_PETS_PER_USER)
            pet_assets_service.write_assets(user_db, pet_id=pet.id,
                    sheet_png=parsed["sheet_png"], manifest_json=parsed["manifest_json"],
                    package_json=parsed["package_json"], source="ai_generated",
                    source_breed_id=parsed["breed_id"])
            user_db.commit()
        finally:
            user_db.close()
        _write_ownership(social_db, pet_id=pet.id, user_id=j.user_id, source="ai_generated")
        j.status = "done"; j.breed_id = parsed["breed_id"]; social_db.commit()
    except Exception as e:
        j.status = "error"; j.error = str(e)[:300]; social_db.commit()   # never a partial pet
    return {"ok": True}
```

(`progress` and `fail` endpoints are trivial — just update the row. Copy the
shapes from `examples/queue_server.py`.)

Note it **does not charge credits** — "make your own pet" is free. If you want a
charge, call `require_credits(...)` in `create_job` like the adoption path does.

---

## Frontend — one addition, mirrors the existing upload

In `web/src/app/[slug]/settings/pet/page.tsx`, next to the existing
"⬆ Upload a pet bundle (.zip)" button, add a "🪄 Make your own pet" input +
button. It's the same pattern as `handleUploadBundle`, but posts `{animal}` and
polls:

```ts
async function handleGenerate(animal: string) {
  const r = await fetch(`${apiBase}/api/pets/gen/create`, {
    method: "POST", headers: { "Content-Type": "application/json", ...authHeaders() },
    credentials: "include", body: JSON.stringify({ animal }),
  });
  const { job_id } = await r.json();
  const t = setInterval(async () => {
    const j = await (await fetch(`${apiBase}/api/pets/gen/${job_id}`,
                                 { credentials: "include", headers: authHeaders() })).json();
    setProgress(j.pct, j.msg);
    if (j.status === "done")  { clearInterval(t); reloadPets(); }   // pet already in the house
    if (j.status === "error") { clearInterval(t); flashError(j.error); }
  }, 1500);
}
```

Gate the whole UI on `GET /api/pets/gen-health`: hide/disable the button when
`enabled` is false or `worker_online` is false. So when the GPU box is off, users
just don't see a broken feature — and the rest of Settings → Pet works normally.

---

## The GPU box (outside DatsMe)

```bash
pip install "git+https://github.com/jeffhancook/datsme-pet-factory"
QUEUE_URL=https://<datsme-api>  WORKER_TOKEN=<secret>  python -m examples.worker
```
(with ComfyUI + models running — see README). This is the only place
`pet_factory` is imported.

---

## Failure modes — every one degrades to "feature just isn't there"

| What breaks | What happens | Is DatsMe core affected? |
|-------------|--------------|--------------------------|
| `pet_gen` module import error | `main.py` try/except logs a warning, skips the router | **No** — app boots normally |
| Feature flag `PET_GEN_ENABLED` off | `create` returns 503; frontend hides the button | **No** |
| GPU worker offline | health shows `worker_online:false`; button disabled; queued jobs wait | **No** |
| Generation fails / bad bundle | `complete` catches it, marks job `error`, writes **nothing** | **No** — no partial pet, existing pets untouched |
| Whole feature is buggy | Turn the flag off, or remove the files (below) | **No** |

Because the `complete` handler runs the **same `validate_uploaded_bundle`** and
**same `write_assets`** as the existing upload button, a generated pet can never
be "more dangerous" than a hand-uploaded one.

---

## Removing the feature entirely

1. Delete `apps/pets/pet_gen/` and the frontend component.
2. Delete the wrapped `include_router` block in `main.py`.
3. `DROP TABLE pet_gen_jobs;`

DatsMe is byte-for-byte back to today. No core file was ever modified.
