"""webui/db.py — the single SQLite store for Pet Maker (datspet.db).

Replaces the old pet.json-per-folder layout. One database is the source of
truth for every pet, job, and bundle token; pet bytes (sprite sheet, manifest,
package.json, the .zip bundle) live in-row as blobs, mirroring DatsMe's own
`pet_assets` pattern (bytes in the DB, not loose files). The engine and the API
read/write here instead of touching the filesystem.

Identity scoping (the whole reason this exists — see the DPP integration spec
§5.4): every pet and job carries a nullable `external_user_id`.
  - standalone / local single-user mode  → external_user_id IS NULL
  - launched from DatsMe                  → external_user_id = the DatsMe user
The API surface the frontend uses does not change; scoping is a WHERE clause,
never a fork in the engine.

Stdlib sqlite3 only (no SQLAlchemy dependency): the schema is three small
tables and every access goes through the helpers here, so the query surface
stays tiny and auditable. All timestamps are unix epoch floats (time.time()),
matching the pre-migration pet.json `created_at`.
"""
import hashlib
import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

import owner_scope
import pet_ownership

# The DB lives next to the pet output dir so "move the collection elsewhere"
# (PETMAKER_OUTPUT_DIR) moves the pets with it. One file, one source of truth.
_DEFAULT_OUTPUT_DIR = Path(__file__).parent / "datspet_output"
OUTPUT_DIR = Path(os.environ.get(
    "PETMAKER_OUTPUT_DIR", str(_DEFAULT_OUTPUT_DIR))).expanduser()
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = Path(os.environ.get(
    "PETMAKER_DB_PATH", str(OUTPUT_DIR / "datspet.db"))).expanduser()

# sqlite3 connections are not safe to share across threads by default, and the
# generation worker runs in a daemon thread. A single module-level connection
# guarded by a lock keeps writes serialized (they already are — one GPU job at
# a time) and avoids "SQLite objects created in a thread…" errors.
_conn: Optional[sqlite3.Connection] = None
_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA foreign_keys=ON")
    return _conn


_SCHEMA = """
CREATE TABLE IF NOT EXISTS pets (
    id                  TEXT PRIMARY KEY,
    breed_id            TEXT NOT NULL,
    display_name        TEXT NOT NULL,
    created_at          REAL NOT NULL,
    draft               INTEGER NOT NULL DEFAULT 1,
    external_user_id    TEXT,              -- NULL = standalone/local
    datsme_activity_id  TEXT,              -- set when accepted into DatsMe
    writeback_acked_at  REAL,             -- set when the host acks the writeback
    bundle_sha256       TEXT,
    size_bytes          INTEGER,
    sheet_png           BLOB NOT NULL,
    manifest_json       TEXT NOT NULL,
    package_json        TEXT,
    bundle_zip          BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pets_external_user ON pets(external_user_id);

CREATE TABLE IF NOT EXISTS jobs (
    id                  TEXT PRIMARY KEY,
    status              TEXT NOT NULL,
    progress            REAL NOT NULL DEFAULT 0,
    message             TEXT,
    created_at          REAL NOT NULL,
    external_user_id    TEXT
);

-- The Pet Store inventory (SPEC_PET_STORE §1.2). A SEPARATE table from pets, on
-- purpose: store pets are visible to everyone, and no owner value in the scoped
-- pets table can express that — widening _scope_clause is exactly the bug the
-- exact-match fix removed. No owner column (nobody owns inventory), no draft
-- column (`status` is the store's own word; the draft purge sweeps never
-- touch it). Derived columns (pose_count, bundle_sha256, size_bytes) are
-- computed in insert_store_pet from the bytes it is handed, so a row can never
-- disagree with its own bundle.
CREATE TABLE IF NOT EXISTS store_pets (
    id              TEXT PRIMARY KEY,
    display_name    TEXT NOT NULL,
    breed_id        TEXT NOT NULL,
    animal          TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    tags_json       TEXT NOT NULL DEFAULT '[]',
    pose_count      INTEGER NOT NULL,
    -- SPEC_PET_STORE §1.4: intake | shelf | backroom | archived. Replaced a
    -- `published` boolean, which could not tell apart the three different
    -- reasons a pet is not for sale — and those three are what an admin acts on.
    status          TEXT NOT NULL DEFAULT 'intake',
    admin_note      TEXT NOT NULL DEFAULT '',
    -- Stamped by the store on the first move to `shelf`, never cleared. It is
    -- what freezes `animal` (§1.3): under the old boolean "not published" and
    -- "never published" were the same condition; under four states they are
    -- not, and the weaker rule would let shelf -> backroom -> re-animal ->
    -- shelf change a listing shoppers had already filtered on.
    first_shelved_at REAL,
    created_at      REAL NOT NULL,
    bundle_sha256   TEXT NOT NULL,
    size_bytes      INTEGER NOT NULL,
    preview_png     BLOB NOT NULL,
    sheet_png       BLOB NOT NULL,
    manifest_json   TEXT NOT NULL,
    package_json    TEXT,
    bundle_zip      BLOB NOT NULL
);
-- Backs the uniqueness guard both stocking doors run (§5.4). NOT a UNIQUE
-- index: environments that predate the guard already hold duplicates, and a
-- UNIQUE index would make init_db fail on boot rather than let the admin
-- resolve them. The invariant is enforced at the doors; this only makes the
-- lookup free.
CREATE INDEX IF NOT EXISTS idx_store_pets_bundle_sha
    ON store_pets(bundle_sha256);

CREATE TABLE IF NOT EXISTS bundle_tokens (
    token               TEXT PRIMARY KEY,
    pet_id              TEXT NOT NULL,
    expires_at          REAL NOT NULL,
    downloaded_at       REAL,             -- first successful download; NULL until then
    FOREIGN KEY (pet_id) REFERENCES pets(id) ON DELETE CASCADE
);

-- Runtime settings (SPEC_UPLOAD_LIKENESS §2.2, decision 6a) — a small key/value
-- store for admin-toggleable feature flags (the first is `upload_isolate`). In the
-- DB, not a content file, because a feature flag must be runtime-writable without a
-- deploy — the `tiers/` `default_tier` launch-lever posture. Values are TEXT; the
-- settings admin declares the type per known key and validates on write.
CREATE TABLE IF NOT EXISTS app_settings (
    key                 TEXT PRIMARY KEY,
    value               TEXT NOT NULL,
    updated_at          REAL NOT NULL
);

-- AI engine usage ledger (SPEC_DATSPET_AI_ENGINE §5). Append-only: a re-run is a
-- NEW row, never an UPDATE. Cost is NOT stored — it is derived at read time from
-- the model catalog's cost_per_mtok, so a pricing correction stays fixable and a
-- retired model's historical rows still price. `external_user_id` follows db.py's
-- existing identity scoping (a value = the DatsMe user; NULL = standalone).
CREATE TABLE IF NOT EXISTS ai_usage (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    ts                  REAL NOT NULL,
    purpose_key         TEXT NOT NULL,
    model_id            TEXT NOT NULL,
    input_tokens        INTEGER NOT NULL DEFAULT 0,
    output_tokens       INTEGER NOT NULL DEFAULT 0,
    ok                  INTEGER NOT NULL DEFAULT 1,   -- 1 = call succeeded, 0 = failed
    error_code          TEXT,                          -- set only when ok=0
    external_user_id    TEXT
);
CREATE INDEX IF NOT EXISTS idx_ai_usage_ts ON ai_usage(ts);
CREATE INDEX IF NOT EXISTS idx_ai_usage_purpose ON ai_usage(purpose_key);

-- The store's transaction record (SPEC_PET_STORE §1.5.3): who bought a store
-- pet, how much the HOST charged, when, and which listing. Append-only — a
-- re-delivered notification writes nothing (pet_id is the key), never an
-- UPDATE. It outlives everything it references: deleting the listing, the
-- buyer emptying their house, or the buyer being forgotten all leave the row.
--
-- credits_paid is NULLABLE and NULL means "the host did not tell us" — NOT
-- zero, which is a legitimate amount (a re-import delta can genuinely be
-- free). buyer_user_id goes EMPTY (not NULL) on revoke, so "forgotten" stays
-- distinguishable from "never knew".
CREATE TABLE IF NOT EXISTS store_sales (
    pet_id          TEXT PRIMARY KEY,   -- the adopted copy; the idempotency key
    store_pet_id    TEXT NOT NULL,      -- WHAT was sold
    buyer_user_id   TEXT NOT NULL,      -- WHO bought it ('' once forgotten)
    credits_paid    INTEGER,            -- HOW MUCH; NULL = host did not report
    sold_at         REAL NOT NULL       -- WHEN (unix epoch float)
);
CREATE INDEX IF NOT EXISTS idx_store_sales_listing ON store_sales(store_pet_id);

-- Donations (SPEC_PET_STORE §10.2). An append-only LEDGER, not a queue: under
-- §0.5 a donation is final, so the pet is already store inventory by the time
-- a row exists here and there is no verdict to track. It holds no bytes for
-- the same reason — those live in store_pets.
--
-- Deliberately NOT registered with the claim registry (owner_scope.py): it is
-- an append-only ledger, a claim handler would rewrite history, and §10.1's
-- first gate means a donation can never be created under an anonymous id in
-- the first place. Do not "complete" the registry by adding it.
--
-- reward_state tracks DELIVERY, not the admin's decision, because those move
-- on different clocks: the point is earned at the click and delivered when the
-- donor next launches. points_awarded is what the HOST said it gave — NULL
-- until it answers, and the number the donor is thanked with (§10.8).
CREATE TABLE IF NOT EXISTS store_donations (
    id                  TEXT PRIMARY KEY,   -- the award key the host dedupes on
    external_user_id    TEXT NOT NULL,      -- the donor; NEVER NULL (§10.1)
    store_pet_id        TEXT NOT NULL,      -- what it became
    display_name        TEXT NOT NULL,      -- as donated; the shelf may rename it
    donated_at          REAL NOT NULL,
    reward_state        TEXT NOT NULL,      -- owed|delivered|capped|disabled|declined
    points_awarded      INTEGER,
    reward_delivered_at REAL
);
CREATE INDEX IF NOT EXISTS idx_store_donations_donor
    ON store_donations(external_user_id);
CREATE INDEX IF NOT EXISTS idx_store_donations_owed
    ON store_donations(reward_state);
-- The §10.4 read-time join, run once per row of the admin inventory. Without
-- it that badge costs a full scan of every donation ever made, per listing.
CREATE INDEX IF NOT EXISTS idx_store_donations_store_pet
    ON store_donations(store_pet_id);
"""


def init_db() -> None:
    """Create tables if absent, then one-time-migrate any legacy
    pet.json/pet.zip folders into the DB. Idempotent — safe every startup."""
    with _lock:
        conn = _connect()
        conn.executescript(_SCHEMA)
        # Opt-1 (spec §A.6): the jobs table gained the pool-job linkage columns.
        # ALTER-if-missing so existing DBs migrate in place on startup.
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(jobs)")}
        for col in ("pool_job_id", "description", "display_name"):
            if col not in cols:
                conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} TEXT")
        # SPEC_PET_STORE §7.2: how the pet came to be. Set by store adopt, NULL
        # for designed pets — the declared price basis the DPP export reads.
        pet_cols = {r["name"] for r in conn.execute("PRAGMA table_info(pets)")}
        if "source_store_pet_id" not in pet_cols:
            conn.execute("ALTER TABLE pets ADD COLUMN source_store_pet_id TEXT")
        # Pet naming (owner ask 2026-08-02): the child's own FIRST name for the
        # pet; display composes "«pet_name» «animal»" ("Joe Leopard") at read
        # time. NULL = unnamed → the breed display_name shows as before. A
        # rename never rewrites display_name, the bundle, or anything the DPP
        # export reads — the bundle stays immutable.
        if "pet_name" not in pet_cols:
            conn.execute("ALTER TABLE pets ADD COLUMN pet_name TEXT")
        # SPEC_PET_STORE §1.4 — the shelf lifecycle replaces the `published`
        # boolean. One-shot and guarded on the column's absence, so it is a
        # no-op on every boot after the first. `published` is DROPPED rather
        # than left behind a shim: two sources of truth for "is this for sale"
        # is the failure this replaces. Rollback for this deploy is a restore
        # of datspet.db, which the deploy checklist takes first.
        # RE-ENTRANT, not once-only. sqlite3 autocommits each ALTER on its own,
        # so a crash between adding the columns and running the backfill used to
        # leave `status` present — which a single `"status" not in store_cols`
        # guard reads as "already migrated", skipping the backfill FOREVER and
        # leaving every listing stuck in `intake`: a silently empty shop.
        #
        # So the two steps are guarded independently. Adding columns keys on the
        # columns; the backfill-and-drop keys on `published` still existing.
        # A partial run completes on the next boot, and a finished one is a
        # no-op because `published` is gone.
        store_cols = {r["name"]
                      for r in conn.execute("PRAGMA table_info(store_pets)")}
        if store_cols:
            for col, ddl in (
                ("status", "ALTER TABLE store_pets ADD COLUMN status TEXT "
                            "NOT NULL DEFAULT 'intake'"),
                ("admin_note", "ALTER TABLE store_pets ADD COLUMN admin_note "
                               "TEXT NOT NULL DEFAULT ''"),
                ("first_shelved_at", "ALTER TABLE store_pets ADD COLUMN "
                                     "first_shelved_at REAL"),
            ):
                if col not in store_cols:
                    conn.execute(ddl)
            if "published" in store_cols:
                # Backfill then drop, in ONE explicit transaction: the drop is
                # what marks this step done, so it must not land without the
                # UPDATE that gives the rows their state.
                conn.execute("BEGIN")
                try:
                    conn.execute(
                        "UPDATE store_pets SET status='shelf', "
                        "first_shelved_at=created_at WHERE published=1")
                    conn.execute(
                        "ALTER TABLE store_pets DROP COLUMN published")
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
        conn.commit()
    _migrate_legacy_folders()
    _backfill_bundle_digests()


def _backfill_bundle_digests() -> None:
    """Fill bundle_sha256/size_bytes on rows written before insert_pet derived them
    (SPEC_DATSPET_HOUSE_ADOPT §3.1). Every pre-existing row has them NULL, and the
    DPP export cannot offer a `transfer` block for a row it cannot hash.

    One-time and self-limiting: once filled, the WHERE matches nothing, so this is
    a single cheap query on every subsequent boot. Bounded by the pets already on
    this machine, and the bytes are local — no fetch, no network.
    """
    with _lock:
        conn = _connect()
        rows = conn.execute(
            "SELECT id, bundle_zip FROM pets WHERE bundle_sha256 IS NULL"
        ).fetchall()
        for row in rows:
            conn.execute(
                "UPDATE pets SET bundle_sha256=?, size_bytes=? WHERE id=?",
                (hashlib.sha256(row["bundle_zip"]).hexdigest(),
                 len(row["bundle_zip"]), row["id"]),
            )
        if rows:
            conn.commit()


# ---------------------------------------------------------------------------
# One-time migration: datspet_output/<id>/{pet.json,sheet.png,manifest.json,
# pet.zip} → a pets row. Reads the same fields list_pets/keep/zip used before.
# A folder already represented in the DB is skipped, so re-running is a no-op.
# ---------------------------------------------------------------------------
def _migrate_legacy_folders() -> None:
    for record_path in OUTPUT_DIR.glob("*/pet.json"):
        folder = record_path.parent
        pet_id = folder.name
        try:
            with _lock:
                exists = _connect().execute(
                    "SELECT 1 FROM pets WHERE id=?", (pet_id,)).fetchone()
            if exists:
                continue
            record = json.loads(record_path.read_text())
            sheet = (folder / "sheet.png")
            manifest = (folder / "manifest.json")
            bundle = (folder / "pet.zip")
            # Only complete folders migrate; a half-finished job (no sheet/zip)
            # is dropped exactly as _purge_drafts would have.
            if not (sheet.exists() and manifest.exists() and bundle.exists()):
                continue
            package_json = None
            zip_bytes = bundle.read_bytes()
            import io, zipfile
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
                if "package.json" in z.namelist():
                    package_json = z.read("package.json").decode("utf-8")
            insert_pet(
                pet_id=pet_id,
                breed_id=record.get("breed_id", pet_id),
                display_name=record.get("display_name", pet_id),
                created_at=record.get("created_at", time.time()),
                draft=bool(record.get("draft", False)),
                sheet_png=sheet.read_bytes(),
                manifest_json=manifest.read_text(),
                package_json=package_json,
                bundle_zip=zip_bytes,
                external_user_id=None,
            )
        except (json.JSONDecodeError, OSError, KeyError):
            continue


# ---------------------------------------------------------------------------
# Pets
# ---------------------------------------------------------------------------
def insert_pet(*, pet_id: str, breed_id: str, display_name: str,
               created_at: float, draft: bool, sheet_png: bytes,
               manifest_json: str, package_json: Optional[str],
               bundle_zip: bytes, external_user_id: Optional[str] = None,
               source_store_pet_id: Optional[str] = None) -> None:
    """Persist a pet. `bundle_sha256`/`size_bytes` are DERIVED here, never passed.

    They are a pure function of `bundle_zip`, so letting a caller supply them is
    only a chance to be wrong — and the DPP export publishes the sha256 as the
    integrity claim the host verifies the fetched bytes against
    (SPEC_DATSPET_HOUSE_ADOPT §3.1). They were optional params with zero callers
    passing them, so every row's sha256 was NULL and the export could not have
    offered a `transfer` block at all.
    """
    with _lock:
        conn = _connect()
        conn.execute(
            """INSERT OR REPLACE INTO pets
               (id, breed_id, display_name, created_at, draft, external_user_id,
                source_store_pet_id, bundle_sha256, size_bytes, sheet_png,
                manifest_json, package_json, bundle_zip)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (pet_id, breed_id, display_name, created_at, 1 if draft else 0,
             external_user_id, source_store_pet_id,
             hashlib.sha256(bundle_zip).hexdigest(),
             len(bundle_zip), sheet_png,
             manifest_json, package_json, bundle_zip),
        )
        conn.commit()


def repair_pet_bundle(pet_id: str, *, manifest_json: str,
                      bundle_zip: bytes,
                      sheet_png: Optional[bytes] = None) -> bool:
    """Admin data repair (pet_facing_admin): replace a stored pet's manifest —
    both copies travel together, the column and the zip the caller rebuilt
    from it — and rederive bundle_sha256/size_bytes, which are a pure function
    of the zip (insert_pet's rule; the DPP transfer pointer publishes them).
    A PIXEL repair (flip_sheet_frames) also passes the repaired sheet, which
    must land in the column the runtimes fetch AND ride inside the zip the
    caller rebuilt. This is the deliberate exception to "nothing restamps a
    stored row" (SPEC_PET_OWNER_FIELD §2.4): a repair of what the build
    stamped or drew wrong, through an admin door, never an ordinary flow."""
    with _lock:
        conn = _connect()
        sheet_set, sheet_params = ("", ()) if sheet_png is None \
            else (", sheet_png=?", (sheet_png,))
        cur = conn.execute(
            f"""UPDATE pets SET manifest_json=?, bundle_zip=?,
                               bundle_sha256=?, size_bytes=?{sheet_set}
                WHERE id=?""",
            (manifest_json, bundle_zip,
             hashlib.sha256(bundle_zip).hexdigest(), len(bundle_zip),
             *sheet_params, pet_id),
        )
        conn.commit()
        return cur.rowcount > 0


def pose_count(manifest_json: Optional[str]) -> Optional[int]:
    """`len(manifest["animations"])` — the pet's pose count, and the pricing basis
    the DPP export declares (SPEC_DPP_DATA_TRANSFER_CHANNEL §0.6).

    This MUST agree with the host's `_pose_count_in_bundle`, which counts the
    manifest.json inside the fetched zip: a disagreement is a 409
    `pricing_basis_mismatch` on every import. It does agree by construction —
    `_unpack_bundle` (app.py) reads `manifest.json` verbatim out of the bundle and
    that exact string is this column — and a guard test pins it rather than
    trusting the construction.

    Returns None (not 0) when the count is unknowable. Missing is not zero: the
    host refuses to quote an item with no declared basis, which is correct, and an
    invented 0 would quote the base price for a pet that may have six poses.
    """
    if not manifest_json:
        return None
    try:
        animations = json.loads(manifest_json).get("animations", {})
    except (json.JSONDecodeError, TypeError, AttributeError):
        return None
    return len(animations) if isinstance(animations, dict) else None


def get_pet(pet_id: str) -> Optional[sqlite3.Row]:
    with _lock:
        return _connect().execute(
            "SELECT * FROM pets WHERE id=?", (pet_id,)).fetchone()


def get_pet_for_owner(pet_id: str,
                      external_user_id: Optional[str] = None) -> Optional[sqlite3.Row]:
    """One pet row the caller may access — None when absent OR not theirs. The
    read-side companion of the scoped mutations (same _scope_clause), for
    callers that need the bytes: the store's intake-from-pet reads its source
    pet through this so an admin can publish only a pet she can see in her own
    house (SPEC_PET_STORE §3.2), never an arbitrary row by id."""
    clause, params = _scope_clause(external_user_id)
    with _lock:
        return _connect().execute(
            f"SELECT * FROM pets WHERE id=? AND {clause}",
            (pet_id, *params)).fetchone()


def list_unsaved_pets(external_user_id: Optional[str] = None) -> list[dict]:
    """Finished builds the caller never decided on — drafts, newest first.

    A draft is "scratch the user never saved", and purge_drafts is right to sweep
    it. But a build that FINISHED and simply hasn't been answered yet is not
    scratch: it is three minutes of GPU and the thing the user asked for. Between
    the build finishing and the user pressing Save there is a window, and anything
    that navigates the page — signing out, closing the tab, a stray link, a crash —
    used to end that window with the pet reachable from nowhere. The house excludes
    drafts, and the only other route was a job id that lives in memory and dies with
    the backend. This is the route back (SPEC_PET_DESIGNER_FLOW resume).

    `bundle_zip != x''` is what makes it FINISHED rather than merely started: a row
    is inserted only at finalize, but the guard states the requirement instead of
    relying on that, since a partial row would render an empty result panel.

    Same scope rule as everything else — you see your own, and only your own.
    """
    clause, params = _scope_clause(external_user_id)
    with _lock:
        rows = _connect().execute(
            f"""SELECT id, breed_id, display_name, created_at FROM pets
                WHERE draft=1 AND length(bundle_zip) > 0 AND {clause}
                ORDER BY created_at DESC""", params).fetchall()
    return [dict(r) for r in rows]


def list_saved_pets(external_user_id: Optional[str] = None) -> list[dict]:
    """Saved (non-draft) pets, newest first, scoped to the caller's identity.
    Uses the SAME visibility rule as keep/delete/access (_scope_clause): a
    standalone caller sees the local (unowned) pets; a launched user sees their
    own pets AND any still-unclaimed local pets — so what you can see you can
    act on, uniformly. Returns {id, breed_id, display_name, created_at}."""
    clause, params = _scope_clause(external_user_id)
    with _lock:
        rows = _connect().execute(
            f"""SELECT id, breed_id, display_name, pet_name, created_at,
                       writeback_acked_at, external_user_id, manifest_json
                    FROM pets
                WHERE draft=0 AND {clause}
                ORDER BY created_at DESC""", params).fetchall()
    # sent_to_datsme: this pet was DELIVERED to the caller's DatsMe house at least
    # once — a delivery receipt, not a present-tense ownership fact. Stamped by a
    # push Accept or the host's post-import ack (SPEC_DATSPET_HOUSE_ADOPT §3.4).
    #
    # It was called `in_datsme` until 2026-08-03 and that name was a lie
    # (SPEC_PET_OWNERSHIP §1): the flag is MONOTONIC, so a pet the user has since
    # deleted, gifted, or evicted for space still reads true forever, and a pet
    # that arrived by gift can never read true at all. DatsPet has no way to know
    # the present state — only DatsMe does. "I sent it" is not "they have it."
    # Answering the real question needs `pets.read_owned` (SPEC_PET_OWNERSHIP §3);
    # until then the field says exactly what it knows and nothing more.
    #
    # A projected column, NOT a visibility rule — _scope_clause is untouched.
    # Cast to a real bool so the JSON carries true/false rather than SQLite's 1/0.
    #
    # claimable: this caller's own pet, still held under their ANONYMOUS owner id
    # rather than a DatsMe user id. Such a pet is visible here but invisible to
    # export_pets (exact-match on the DatsMe id), so it would silently vanish from
    # the host's import list — §2's asymmetry, and why the browser needs to know
    # which ids to claim before linking out.
    #
    # Since _scope_clause became exact-match, the only anon-owned rows a caller can
    # see are that caller's own — which is what "claimable" should always have
    # meant. Claim-at-launch (owner_scope.claim_anon_owner) normally empties this
    # set before the house is ever rendered; it stays as the backstop for a row
    # written after that sweep.
    #
    # donatable: this pet is one the user DESIGNED, so the donate door would
    # accept it (SPEC_PET_STORE §10.1 gate 3). A projected column like the two
    # above, never a visibility rule — the door re-checks it server-side, and
    # this only decides whether a button is worth showing. The other two gates
    # (a DatsMe identity, the entitlement) are request-scoped and cannot be
    # answered from a row, so the client ANDs them in; getting that wrong shows
    # a button that 403s, never a donation that should not have happened.
    out = []
    for r in rows:
        d = dict(r)
        d["sent_to_datsme"] = d.pop("writeback_acked_at") is not None
        owner = d.pop("external_user_id")
        d["claimable"] = owner_scope.is_anon_owner(owner)
        category, _n, _a = pet_ownership.read_pet_ownership(d.pop("manifest_json"))
        d["donatable"] = category == pet_ownership.FACTORY_CATEGORY
        out.append(d)
    return out


# A pet is accessible to a caller iff it is owned by exactly that caller. Enforced
# in the WHERE clause of every scoped mutation so ownership is checked atomically
# with the write (no TOCTOU). The SQL fragment + params are built by _scope_clause
# so keep/delete stay identical.
#
# EXACT match (SPEC_DATSPET_FEDERATED_SESSION §4.5 b). This used to union the
# unowned rows into every launched caller's scope — which meant user B, freshly
# signed in, saw every pet any anonymous visitor had ever kept, marked claimable,
# and could claim and buy them. "An empty house for user B" was unreachable while
# that union stood, no matter what sign-out did. Anonymous callers now carry a
# per-browser owner id (owner_scope.ANON_OWNER_PREFIX) instead of sharing NULL, so
# exact match is all that is needed and NULL means only "standalone box".
def _scope_clause(external_user_id: Optional[str]) -> tuple[str, tuple]:
    if external_user_id is None:
        # Standalone install (no DatsMe host): the local, unowned pets.
        return "external_user_id IS NULL", ()
    return "external_user_id=?", (external_user_id,)


def keep_pet(pet_id: str, external_user_id: Optional[str] = None) -> Optional[dict]:
    """Clear the draft flag for a pet the caller may access. Returns the
    summary record, or None if the pet is absent OR not the caller's."""
    clause, params = _scope_clause(external_user_id)
    with _lock:
        conn = _connect()
        cur = conn.execute(
            f"UPDATE pets SET draft=0 WHERE id=? AND {clause}", (pet_id, *params))
        conn.commit()
        if cur.rowcount == 0:
            return None
        row = conn.execute(
            "SELECT id, breed_id, display_name, created_at, draft FROM pets WHERE id=?",
            (pet_id,)).fetchone()
    return dict(row) if row else None


def rename_pet(pet_id: str, pet_name: Optional[str],
               external_user_id: Optional[str] = None) -> bool:
    """Set (or clear, with None) the owner's name for a pet the caller may
    access. False if absent OR not the caller's. Stores the FIRST name only —
    the frontend composes "«pet_name» «animal»" at display time."""
    clause, params = _scope_clause(external_user_id)
    with _lock:
        conn = _connect()
        cur = conn.execute(
            f"UPDATE pets SET pet_name=? WHERE id=? AND {clause}",
            (pet_name, pet_id, *params))
        conn.commit()
        return cur.rowcount > 0


def delete_pet(pet_id: str, external_user_id: Optional[str] = None) -> bool:
    """Delete a pet the caller may access. False if absent OR not the caller's."""
    clause, params = _scope_clause(external_user_id)
    with _lock:
        conn = _connect()
        cur = conn.execute(
            f"DELETE FROM pets WHERE id=? AND {clause}", (pet_id, *params))
        conn.commit()
        return cur.rowcount > 0


def purge_drafts(external_user_id: Optional[str] = "__all__") -> list[str]:
    """Delete unsaved drafts and return their ids (so the caller can drop the
    matching in-memory Job). external_user_id="__all__" purges every user's
    drafts (startup); None purges only standalone drafts; a value purges that
    user's drafts (a DatsMe user iterating without accepting).

    A draft is exactly what the name says: scratch the user never saved.

    There used to be a `not_pending` exemption here, protecting a pet whose QUEUED
    writeback had not drained yet. That retry queue is gone with the push path, and
    leaving the clause would have been a leak rather than a no-op: claim_anon_pets
    stamps datsme_activity_id, so once sign-in claims a browser's work, every
    claimed-but-unkept draft would have matched the predicate and become exempt from
    every purge scope, permanently (SPEC_DATSPET_FEDERATED_SESSION §4.6 b).

    Deleting it is safe because the hand-off calls keep() BEFORE navigating to the
    checkout, so any pet in a live checkout is already draft=0 and outside every
    purge scope.
    """
    if external_user_id == "__all__":
        scope, params = "1=1", ()
    elif external_user_id is None:
        scope, params = "external_user_id IS NULL", ()
    else:
        scope, params = "external_user_id=?", (external_user_id,)
    where = f"draft=1 AND {scope}"
    with _lock:
        conn = _connect()
        rows = conn.execute(f"SELECT id FROM pets WHERE {where}", params).fetchall()
        conn.execute(f"DELETE FROM pets WHERE {where}", params)
        conn.commit()
    return [r["id"] for r in rows]


def stamp_writeback_acked(pet_id: str, activity_id: str, acked_at: float) -> None:
    with _lock:
        conn = _connect()
        conn.execute(
            "UPDATE pets SET datsme_activity_id=?, writeback_acked_at=? WHERE id=?",
            (activity_id, acked_at, pet_id))
        conn.commit()


def export_pets(external_user_id: str) -> list[dict]:
    """Every pet row for a DatsMe user (GDPR export). Bytes excluded — this is
    the record view, schema datspet_pets.v1.

    `pose_count` is the DECLARED pricing basis the host quotes from before it
    fetches anything (SPEC_DPP_DATA_TRANSFER_CHANNEL §0.6); it is a record field,
    not transport, which is why it sits beside breed_id rather than inside the
    route's `transfer` block. `bundle_sha256`/`size_bytes` ARE transport and feed
    that block — they are selected here only because this is the one query that
    already has the row.

    Still byteless: manifest_json is parsed for its animation count and dropped;
    bundle_zip is never read.
    """
    with _lock:
        rows = _connect().execute(
            """SELECT id, breed_id, display_name, created_at, draft,
                      datsme_activity_id, writeback_acked_at,
                      bundle_sha256, size_bytes, manifest_json,
                      source_store_pet_id
               FROM pets WHERE external_user_id=?
               ORDER BY created_at DESC""", (external_user_id,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["pose_count"] = pose_count(d.pop("manifest_json"))
        out.append(d)
    return out


def count_saved_pets(external_user_id: Optional[str] = None) -> int:
    """How many saved (non-draft) pets the caller's house holds — the number the
    cap is enforced against (SPEC house-scaling). Same visibility rule as
    list_saved_pets, so the count equals what the user sees: a standalone caller
    counts the local pets; a launched user counts their own AND unclaimed local
    ones."""
    clause, params = _scope_clause(external_user_id)
    with _lock:
        row = _connect().execute(
            f"SELECT COUNT(*) FROM pets WHERE draft=0 AND {clause}", params).fetchone()
    return row[0]


def claim_anon_pets(from_owner: str, to_owner: str,
                    activity_id: Optional[str] = None) -> int:
    """Move every pet held under one anonymous owner id onto a DatsMe user.

    Keyed by OWNER, not by a list of pet ids (SPEC_DATSPET_FEDERATED_SESSION
    §4.5 c). The old claim_unowned_pets took a list and matched
    `external_user_id IS NULL`, which was two defects in one: at launch there is no
    list to pass, and while the scope clause unioned NULL, "unowned" meant *anyone's*
    anonymous pet, so a signed-in user could claim a pet they had merely seen.

    Why it exists at all (SPEC_DATSPET_HOUSE_ADOPT §2): export_pets is exact-match on
    the DatsMe id, so a pet still under an anon owner is visible in the house yet
    invisible to the host's import — it would vanish from the checkout with no error.

    `activity_id` stamps provenance the same way the push path's _bind_pending did.
    Returns the number of rows moved (0 is the normal case for a user who signed in
    before designing anything).
    """
    if not from_owner or not to_owner or from_owner == to_owner:
        return 0
    with _lock:
        conn = _connect()
        cur = conn.execute(
            """UPDATE pets SET external_user_id=?, datsme_activity_id=?
               WHERE external_user_id=?""",
            (to_owner, activity_id, from_owner))
        conn.commit()
        return cur.rowcount


def claim_anon_jobs(from_owner: str, to_owner: str) -> int:
    """Move persisted pool-job rows from an anonymous owner to a DatsMe user.

    A job captures its owner at SUBMIT and the finished pet is stamped from it, so a
    user who signs in during a ~3-minute build would otherwise end up with a pet
    they cannot see. The in-memory Job objects are swept alongside this by app.py's
    handler — the row and the object are the same fact in two places, and both are
    read after the build finishes.
    """
    if not from_owner or not to_owner or from_owner == to_owner:
        return 0
    with _lock:
        conn = _connect()
        cur = conn.execute(
            "UPDATE jobs SET external_user_id=? WHERE external_user_id=?",
            (to_owner, from_owner))
        conn.commit()
        return cur.rowcount


def revoke_user(external_user_id: str, action: str) -> int:
    """delete → remove the user's pet rows; anonymize → null their
    external_user_id. Returns count.

    NOTE what `anonymize` now means (SPEC_DATSPET_FEDERATED_SESSION §4.5 b). It used
    to leave the rows "standalone/orphaned", i.e. still visible to callers, because
    _scope_clause unioned NULL into every launched caller's scope. Since that clause
    became exact-match, a NULL owner on an INTEGRATED box is reachable by nobody —
    so anonymize is effectively a soft delete there. That is the correct outcome for
    a row whose owner asked to be forgotten; do not "fix" it by reintroducing the
    union. On a standalone install the behavior is unchanged (owner None, scope
    `IS NULL`)."""
    with _lock:
        conn = _connect()
        if action == "delete":
            cur = conn.execute(
                "DELETE FROM pets WHERE external_user_id=?", (external_user_id,))
        else:  # anonymize
            cur = conn.execute(
                "UPDATE pets SET external_user_id=NULL WHERE external_user_id=?",
                (external_user_id,))
        # SPEC_PET_STORE §1.5.3 — the SALE survives being forgotten, the PERSON
        # does not. A shop's books are not a personal record, and deleting them
        # would make revenue depend on who has left; but the buyer stops being
        # named. Empty string rather than NULL keeps "forgotten" distinguishable
        # from "we never knew". Both actions do this: neither `delete` nor
        # `anonymize` is a licence to lose a transaction.
        conn.execute(
            "UPDATE store_sales SET buyer_user_id='' WHERE buyer_user_id=?",
            (external_user_id,))
        conn.commit()
        return cur.rowcount


# ---------------------------------------------------------------------------
# Pool-job persistence (Opt-1, spec §A.6) — the in-memory Job dataclass stays
# the live status object; this table records the web-job ↔ pool-job linkage so
# a web-tier restart can REATTACH to a pool job that is still generating on a
# worker, instead of orphaning it. A row exists only while a pool job is in
# flight: recorded at submit, deleted at either terminal state.
# ---------------------------------------------------------------------------
def record_pool_job(*, job_id: str, pool_job_id: str, description: str,
                    display_name: Optional[str], created_at: float,
                    external_user_id: Optional[str] = None) -> None:
    with _lock:
        conn = _connect()
        conn.execute(
            """INSERT OR REPLACE INTO jobs
               (id, status, progress, message, created_at, external_user_id,
                pool_job_id, description, display_name)
               VALUES (?, 'running', 0, '', ?, ?, ?, ?, ?)""",
            (job_id, created_at, external_user_id,
             pool_job_id, description, display_name))
        conn.commit()


def delete_pool_job(job_id: str) -> None:
    with _lock:
        conn = _connect()
        conn.execute("DELETE FROM jobs WHERE id=?", (job_id,))
        conn.commit()


def list_pool_jobs() -> list[sqlite3.Row]:
    """In-flight pool jobs to reattach on startup (oldest first)."""
    with _lock:
        return _connect().execute(
            """SELECT * FROM jobs WHERE pool_job_id IS NOT NULL
               ORDER BY created_at""").fetchall()


# ---------------------------------------------------------------------------
# Bundle tokens — single-successful-download, 24 h expiry (covers the SDK
# retry window). See spec §5.3 / §7.
# ---------------------------------------------------------------------------
def create_bundle_token(token: str, pet_id: str, expires_at: float) -> None:
    with _lock:
        conn = _connect()
        conn.execute(
            "INSERT INTO bundle_tokens (token, pet_id, expires_at) VALUES (?,?,?)",
            (token, pet_id, expires_at))
        conn.commit()


def resolve_bundle_token(token: str) -> Optional[sqlite3.Row]:
    """Return the token row if it exists, is unexpired, and not yet
    successfully downloaded. None otherwise (caller returns 404)."""
    now = time.time()
    with _lock:
        row = _connect().execute(
            """SELECT * FROM bundle_tokens
               WHERE token=? AND expires_at > ? AND downloaded_at IS NULL""",
            (token, now)).fetchone()
    return row


def burn_bundle_token(token: str) -> None:
    """Mark a token as successfully downloaded (single-successful-use). Called
    only after the bytes are fully served."""
    with _lock:
        conn = _connect()
        conn.execute(
            "UPDATE bundle_tokens SET downloaded_at=? WHERE token=?",
            (time.time(), token))
        conn.commit()


# ---------------------------------------------------------------------------
# The store's transaction ledger (SPEC_PET_STORE §1.5.3). Append-only, like
# ai_usage: one row per sale, never an UPDATE, and every report is a GROUP BY
# over it rather than a counter anyone has to keep in step.
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Donations (SPEC_PET_STORE §10.2). Append-only: statuses move forward, rows
# are never deleted, and the ledger outlives the store pet it became.
# ---------------------------------------------------------------------------
REWARD_OWED = "owed"
REWARD_DELIVERED = "delivered"
REWARD_CAPPED = "capped"
REWARD_DISABLED = "disabled"
REWARD_DECLINED = "declined"

#: Delivery is finished for these — the host answered and will not change its
#: mind, so asking again would only annoy it. `owed` is the only retryable one.
REWARD_TERMINAL = (REWARD_DELIVERED, REWARD_CAPPED, REWARD_DISABLED,
                   REWARD_DECLINED)


def insert_donation(*, donation_id: str, external_user_id: str,
                    store_pet_id: str, display_name: str,
                    donated_at: float) -> None:
    """Record that a user gave a pet. The reward starts `owed` — it is EARNED
    at this moment (§10.7.1) and delivered whenever the donor's next launch
    gives us a token to speak with."""
    with _lock:
        conn = _connect()
        conn.execute(
            """INSERT INTO store_donations
                   (id, external_user_id, store_pet_id, display_name,
                    donated_at, reward_state, points_awarded,
                    reward_delivered_at)
               VALUES (?,?,?,?,?,?,NULL,NULL)""",
            (donation_id, external_user_id, store_pet_id, display_name,
             donated_at, REWARD_OWED))
        conn.commit()


def owed_donations(external_user_id: str) -> list[dict]:
    """This donor's undelivered rewards, oldest first — the batch that rides
    her next launch (§10.7.2). One writeback per launch, so they travel
    together."""
    with _lock:
        rows = _connect().execute(
            """SELECT id, display_name FROM store_donations
                WHERE external_user_id=? AND reward_state=?
                ORDER BY donated_at""",
            (external_user_id, REWARD_OWED)).fetchall()
    return [dict(r) for r in rows]


def settle_donation_reward(donation_id: str, *, state: str,
                           points_awarded: Optional[int],
                           settled_at: float) -> bool:
    """Record what the host said. Only ever moves a row OUT of `owed`, so a
    late duplicate answer cannot overwrite a settled one — the donor was
    already told a number and it must not change under her."""
    if state not in REWARD_TERMINAL:
        raise ValueError(f"not a terminal reward state: {state!r}")
    with _lock:
        conn = _connect()
        cur = conn.execute(
            """UPDATE store_donations
                  SET reward_state=?, points_awarded=?, reward_delivered_at=?
                WHERE id=? AND reward_state=?""",
            (state, points_awarded, settled_at, donation_id, REWARD_OWED))
        conn.commit()
        return cur.rowcount > 0


def donation_for_store_pet(store_pet_id: str) -> Optional[dict]:
    """Who donated this listing, if anyone — the read-time join §10.4 calls the
    admin surface's one new thing. A JOIN and not a column on store_pets, on
    purpose: the engine must never be able to ask where a listing came from
    (§1.2), and a read-time view is exactly the boundary where comparing
    sources is allowed."""
    with _lock:
        row = _connect().execute(
            """SELECT external_user_id, donated_at FROM store_donations
                WHERE store_pet_id=? ORDER BY donated_at LIMIT 1""",
            (store_pet_id,)).fetchone()
    return dict(row) if row else None


def delete_donation(donation_id: str) -> bool:
    """Remove a donation row. The ONE legitimate caller is the donate door
    undoing its own half-finished write when it loses a race — an
    append-only ledger tolerates a row never being published, not one being
    rewritten after it has been reported. Do not reach for this anywhere else.
    """
    with _lock:
        conn = _connect()
        cur = conn.execute("DELETE FROM store_donations WHERE id=?",
                           (donation_id,))
        conn.commit()
        return cur.rowcount > 0


def donations_for_donor(external_user_id: str) -> list[dict]:
    """What she gave, newest first — the Donations section (§10.8). Scoped like
    every other read; a donor sees only her own."""
    with _lock:
        rows = _connect().execute(
            """SELECT id, store_pet_id, display_name, donated_at,
                      reward_state, points_awarded
                 FROM store_donations WHERE external_user_id=?
                ORDER BY donated_at DESC""",
            (external_user_id,)).fetchall()
    return [dict(r) for r in rows]


def insert_store_sale(*, pet_id: str, store_pet_id: str, buyer_user_id: str,
                      credits_paid: Optional[int], sold_at: float) -> bool:
    """Record one sale. Returns True if this call wrote it, False if it was
    already recorded.

    INSERT OR IGNORE, and `pet_id` being the primary key is the whole
    idempotency story: the host's notification is at-least-once, so this WILL
    be called twice for the same sale, and a second call must be a no-op rather
    than a duplicate row or a rewritten amount. That also means a first
    delivery carrying no amount keeps credits_paid NULL even if a retry carries
    one — deliberate, and why the host sends the amount from the start.
    """
    with _lock:
        conn = _connect()
        cur = conn.execute(
            """INSERT OR IGNORE INTO store_sales
                   (pet_id, store_pet_id, buyer_user_id, credits_paid, sold_at)
               VALUES (?,?,?,?,?)""",
            (pet_id, store_pet_id, buyer_user_id, credits_paid, sold_at))
        conn.commit()
        return cur.rowcount > 0


def sales_for_store_pet(store_pet_id: str) -> dict:
    """Sales of one listing: count and total credits. Derived at read time —
    there is no counter column to drift (§1.5.3). `credits` sums only the rows
    whose amount is known; NULLs are excluded by SUM, which is correct: an
    unknown amount must not read as zero revenue."""
    with _lock:
        row = _connect().execute(
            """SELECT COUNT(*) AS n, SUM(credits_paid) AS credits
                 FROM store_sales WHERE store_pet_id=?""",
            (store_pet_id,)).fetchone()
    return {"count": row["n"] or 0, "credits": row["credits"] or 0}


# ---------------------------------------------------------------------------
# AI engine usage ledger (SPEC_DATSPET_AI_ENGINE §5). Append-only — insert_ai_usage
# never updates. Reads aggregate with a GROUP BY (the rollup a platform with orders
# of magnitude more traffic needs is deliberately NOT adopted, §7). Cost is derived
# by the caller from ai_models.price at read time, so this layer returns token sums.
# ---------------------------------------------------------------------------
def insert_ai_usage(*, ts: float, purpose_key: str, model_id: str,
                    input_tokens: int, output_tokens: int, ok: bool,
                    error_code: Optional[str] = None,
                    external_user_id: Optional[str] = None) -> None:
    """Append one usage row (never an UPDATE — a re-run is a new row)."""
    with _lock:
        conn = _connect()
        conn.execute(
            """INSERT INTO ai_usage
               (ts, purpose_key, model_id, input_tokens, output_tokens, ok,
                error_code, external_user_id)
               VALUES (?,?,?,?,?,?,?,?)""",
            (ts, purpose_key, model_id, int(input_tokens), int(output_tokens),
             1 if ok else 0, error_code, external_user_id),
        )
        conn.commit()


def ai_usage_summary(since: Optional[float] = None) -> list[dict]:
    """Per (purpose_key, model_id) usage aggregation, newest activity first.

    Grouped by model as well as purpose because cost is a per-MODEL rate: the
    admin derives USD from ai_models.price(model_id, in, out) per row and sums by
    purpose for display. `since` (a unix-epoch float) bounds the window; None
    means all-time. Returns {purpose_key, model_id, calls, ok_calls, error_calls,
    input_tokens, output_tokens}."""
    where, params = ("WHERE ts >= ?", (since,)) if since is not None else ("", ())
    with _lock:
        rows = _connect().execute(
            f"""SELECT purpose_key, model_id,
                       COUNT(*)                       AS calls,
                       SUM(ok)                        AS ok_calls,
                       SUM(CASE WHEN ok=0 THEN 1 ELSE 0 END) AS error_calls,
                       COALESCE(SUM(input_tokens), 0) AS input_tokens,
                       COALESCE(SUM(output_tokens), 0) AS output_tokens
                FROM ai_usage {where}
                GROUP BY purpose_key, model_id
                ORDER BY MAX(ts) DESC""", params).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Runtime settings (SPEC_UPLOAD_LIKENESS §2.2, decision 6a). A tiny key/value
# store for admin-toggleable flags. Values are TEXT; callers/settings-admin own
# the typing. Runtime-writable (that is the point of a feature flag) — unlike the
# file-based content admins, there is no writability env gate here.
# ---------------------------------------------------------------------------
def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    """The stored value for `key`, or `default` if unset. Never raises."""
    with _lock:
        row = _connect().execute(
            "SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row is not None else default


def set_setting(key: str, value: str) -> None:
    """Upsert one setting (the value replaces any prior — a flag has one live
    value, so this is the one UPDATE-in-place in db.py, deliberately)."""
    with _lock:
        conn = _connect()
        conn.execute(
            """INSERT INTO app_settings (key, value, updated_at) VALUES (?,?,?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value,
                                              updated_at=excluded.updated_at""",
            (key, value, time.time()))
        conn.commit()


def purge_expired_bundle_tokens(grace_s: float = 3600) -> int:
    """Sweep long-expired token rows (resolve already refuses them; this is
    retention hygiene, §7 step 9). The grace keeps recently-expired rows
    around briefly for debugging a failed fetch. Returns rows removed."""
    with _lock:
        conn = _connect()
        cur = conn.execute(
            "DELETE FROM bundle_tokens WHERE expires_at < ?",
            (time.time() - grace_s,))
        conn.commit()
        return cur.rowcount


# ---------------------------------------------------------------------------
# The Pet Store inventory (SPEC_PET_STORE §1.2, §3.3). Unscoped on purpose —
# store pets belong to nobody and are visible to everyone; the routers decide
# what each caller may see (shelf_only for shoppers, everything for the
# admin). Blobs stay in-row like pets. insert_store_pet is the ONLY writer of
# the derived columns.
# ---------------------------------------------------------------------------
#: The shelf lifecycle (SPEC_PET_STORE §1.4). Closed set: an unknown value is
#: refused at the door rather than stored, so a row can never be in a state no
#: reader understands. Only STORE_STATUS_SHELF is visible to shoppers.
STORE_STATUS_INTAKE = "intake"
STORE_STATUS_SHELF = "shelf"
STORE_STATUS_BACKROOM = "backroom"
STORE_STATUS_ARCHIVED = "archived"
STORE_STATUSES = (STORE_STATUS_INTAKE, STORE_STATUS_SHELF,
                  STORE_STATUS_BACKROOM, STORE_STATUS_ARCHIVED)
# ---------------------------------------------------------------------------
def _pose_names(manifest_json: str) -> list[str]:
    """The animation names in manifest order — the listing's `poses` field.
    Empty on an unparseable manifest; sellability (store_validation) is the
    gate that refuses to publish such a bundle, not this read."""
    try:
        animations = json.loads(manifest_json).get("animations", {})
    except (json.JSONDecodeError, TypeError, AttributeError):
        return []
    return list(animations.keys()) if isinstance(animations, dict) else []


def insert_store_pet(*, store_id: str, display_name: str, breed_id: str,
                     animal: str, description: str, tags: list[str],
                     created_at: float, preview_png: bytes, sheet_png: bytes,
                     manifest_json: str, package_json: Optional[str],
                     bundle_zip: bytes,
                     status: str = STORE_STATUS_INTAKE) -> None:
    """Persist one store pet. pose_count / bundle_sha256 / size_bytes are
    DERIVED here (the insert_pet rule): a caller supplying them is only a
    chance to be wrong. Raises ValueError on a manifest whose poses cannot be
    counted — a store row with no countable poses could never be priced or
    sold, so it fails loudly at the stocking door, not silently at checkout."""
    count = pose_count(manifest_json)
    if count is None:
        raise ValueError(
            "store pet manifest has no countable animations — refusing to stock "
            "a bundle that could never be priced (SPEC_PET_STORE §5.3)")
    with _lock:
        conn = _connect()
        conn.execute(
            """INSERT OR REPLACE INTO store_pets
               (id, display_name, breed_id, animal, description, tags_json,
                pose_count, status, first_shelved_at, created_at,
                bundle_sha256, size_bytes,
                preview_png, sheet_png, manifest_json, package_json, bundle_zip)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (store_id, display_name, breed_id, animal, description,
             json.dumps(tags), count, status,
             created_at if status == STORE_STATUS_SHELF else None, created_at,
             hashlib.sha256(bundle_zip).hexdigest(), len(bundle_zip),
             preview_png, sheet_png, manifest_json, package_json, bundle_zip),
        )
        conn.commit()


def store_listing_view(row: sqlite3.Row) -> dict:
    """The byteless listing shape both routers serve (SPEC_PET_STORE §3.1)."""
    try:
        tags = json.loads(row["tags_json"])
    except (json.JSONDecodeError, TypeError):
        tags = []
    return {
        "id": row["id"],
        "display_name": row["display_name"],
        "breed_id": row["breed_id"],
        "animal": row["animal"],
        "description": row["description"],
        "tags": tags if isinstance(tags, list) else [],
        "pose_count": row["pose_count"],
        "poses": _pose_names(row["manifest_json"]),
        "status": row["status"],
        "admin_note": row["admin_note"],
        "first_shelved_at": row["first_shelved_at"],
        "created_at": row["created_at"],
    }


def list_store_pets(shelf_only: bool = True) -> list[dict]:
    """Listings, newest first. Shoppers see `shelf` rows and nothing else; the
    admin passes shelf_only=False and sees every state, with `intake` newest
    first — which is what makes the inbox an ordering rather than a queue."""
    where = f"WHERE status='{STORE_STATUS_SHELF}'" if shelf_only else ""
    with _lock:
        rows = _connect().execute(
            f"""SELECT id, display_name, breed_id, animal, description,
                       tags_json, pose_count, status, admin_note,
                       first_shelved_at, created_at, manifest_json
                FROM store_pets {where}
                ORDER BY created_at DESC""").fetchall()
    return [store_listing_view(r) for r in rows]


def store_bundle_digest(bundle_zip: bytes) -> str:
    """THE store's identity for a pet's bytes — the same digest
    `insert_store_pet` derives and stores as `bundle_sha256`. Named once here
    so the uniqueness guard and the stored column can never drift apart."""
    return hashlib.sha256(bundle_zip).hexdigest()


def store_pet_id_with_bundle(bundle_sha256: str) -> Optional[str]:
    """The listing already holding these exact bytes, or None.

    There is NO per-pet unique id in a manifest to key on: `fingerprint` is the
    constant issuer mark (`datspet` on every pet ever built), `reference_id`
    identifies a step-1 reference IMAGE and never reaches the bundle, and
    `display_name` is not unique — two genuinely different pets can both be
    called "Vampire". The bytes are the only per-pet identity the store has,
    and `migrate_samples_to_store.py` already treats them as one.
    """
    with _lock:
        row = _connect().execute(
            "SELECT id FROM store_pets WHERE bundle_sha256=? LIMIT 1",
            (bundle_sha256,)).fetchone()
    return row["id"] if row else None


def list_store_rows(shelf_only: bool = False) -> list[sqlite3.Row]:
    """FULL store rows, newest first — the admin inventory's reader.

    Deliberately not the byteless `list_store_pets` projection: the admin list
    shows the live sellability verdict, and "sellable" is defined over the
    BUNDLE (§5.3). Sharing one definition with the publish gate is worth
    reading the blobs on a cold, single-user, admin-only route; inventing a
    cheaper second definition of sellable is how the list and the gate start
    disagreeing. The shopper's route keeps the byteless projection.
    """
    where = f"WHERE status='{STORE_STATUS_SHELF}'" if shelf_only else ""
    with _lock:
        return _connect().execute(
            f"SELECT * FROM store_pets {where} ORDER BY created_at DESC").fetchall()


def get_store_pet(store_id: str) -> Optional[sqlite3.Row]:
    """One full store row (blobs included), or None. Callers pick their slice —
    the preview route reads preview_png, adopt reads the bundle members."""
    with _lock:
        return _connect().execute(
            "SELECT * FROM store_pets WHERE id=?", (store_id,)).fetchone()


def update_store_listing(store_id: str, *, display_name: str, description: str,
                         tags: list[str], animal: str,
                         admin_note: Optional[str] = None) -> bool:
    """Rewrite the authored listing fields (SPEC_PET_STORE §1.3). The mechanical
    facts (pose_count, breed_id, the digests) are deliberately not updatable —
    editing them would let a listing lie about its artifact. False if absent."""
    with _lock:
        conn = _connect()
        if admin_note is None:
            cur = conn.execute(
                """UPDATE store_pets SET display_name=?, description=?,
                                         tags_json=?, animal=? WHERE id=?""",
                (display_name, description, json.dumps(tags), animal, store_id))
        else:
            cur = conn.execute(
                """UPDATE store_pets SET display_name=?, description=?,
                                         tags_json=?, animal=?, admin_note=?
                   WHERE id=?""",
                (display_name, description, json.dumps(tags), animal,
                 admin_note, store_id))
        conn.commit()
        return cur.rowcount > 0


def set_store_status(store_id: str, status: str) -> bool:
    """Move a listing between shelf states (SPEC_PET_STORE §1.4). Stamps
    `first_shelved_at` on the FIRST move to `shelf` and never again — it is a
    derived fact like bundle_sha256, not an editable field, and it is what
    freezes `animal` for good (§1.3). Callers validate `status` against
    STORE_STATUSES; this layer refuses an unknown one rather than storing it."""
    if status not in STORE_STATUSES:
        raise ValueError(f"unknown store status {status!r}")
    with _lock:
        conn = _connect()
        if status == STORE_STATUS_SHELF:
            cur = conn.execute(
                """UPDATE store_pets
                      SET status=?,
                          first_shelved_at=COALESCE(first_shelved_at, ?)
                    WHERE id=?""", (status, time.time(), store_id))
        else:
            cur = conn.execute(
                "UPDATE store_pets SET status=? WHERE id=?", (status, store_id))
        conn.commit()
        return cur.rowcount > 0


def delete_store_pet(store_id: str) -> bool:
    """Remove a store pet from inventory. Copies already adopted into houses
    are pets rows and are deliberately unaffected — they are copies."""
    with _lock:
        conn = _connect()
        cur = conn.execute("DELETE FROM store_pets WHERE id=?", (store_id,))
        conn.commit()
        return cur.rowcount > 0
