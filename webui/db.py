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

CREATE TABLE IF NOT EXISTS bundle_tokens (
    token               TEXT PRIMARY KEY,
    pet_id              TEXT NOT NULL,
    expires_at          REAL NOT NULL,
    downloaded_at       REAL,             -- first successful download; NULL until then
    FOREIGN KEY (pet_id) REFERENCES pets(id) ON DELETE CASCADE
);
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
               bundle_zip: bytes, external_user_id: Optional[str] = None) -> None:
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
                bundle_sha256, size_bytes, sheet_png, manifest_json,
                package_json, bundle_zip)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (pet_id, breed_id, display_name, created_at, 1 if draft else 0,
             external_user_id, hashlib.sha256(bundle_zip).hexdigest(),
             len(bundle_zip), sheet_png,
             manifest_json, package_json, bundle_zip),
        )
        conn.commit()


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


def list_saved_pets(external_user_id: Optional[str] = None) -> list[dict]:
    """Saved (non-draft) pets, newest first, scoped to the caller's identity.
    Uses the SAME visibility rule as keep/delete/access (_scope_clause): a
    standalone caller sees the local (unowned) pets; a launched user sees their
    own pets AND any still-unclaimed local pets — so what you can see you can
    act on, uniformly. Returns {id, breed_id, display_name, created_at}."""
    clause, params = _scope_clause(external_user_id)
    with _lock:
        rows = _connect().execute(
            f"""SELECT id, breed_id, display_name, created_at,
                       writeback_acked_at, external_user_id FROM pets
                WHERE draft=0 AND {clause}
                ORDER BY created_at DESC""", params).fetchall()
    # in_datsme: already in the caller's DatsMe house. A projected column, NOT a
    # visibility rule — _scope_clause is untouched. Stamped by a push Accept or by
    # the host's post-import ack (SPEC_DATSPET_HOUSE_ADOPT §3.4). Cast to a real
    # bool so the JSON carries true/false rather than SQLite's 1/0.
    #
    # claimable: visible to this caller but not yet owned by them, i.e. an
    # unclaimed local pet. The house shows these (_scope_clause is NULL-inclusive)
    # but export_pets is exact-match, so they are invisible to the host's import
    # until claimed — §2's asymmetry. The browser needs to know which ids to claim
    # before linking out.
    out = []
    for r in rows:
        d = dict(r)
        d["in_datsme"] = d.pop("writeback_acked_at") is not None
        owner = d.pop("external_user_id")
        d["claimable"] = external_user_id is not None and owner is None
        out.append(d)
    return out


# A pet is accessible to a caller iff it is local (external_user_id IS NULL) or
# owned by that caller. Enforced in the WHERE clause of every scoped mutation so
# ownership is checked atomically with the write (no TOCTOU). The SQL fragment +
# params are built by _scope_clause so keep/delete stay identical.
def _scope_clause(external_user_id: Optional[str]) -> tuple[str, tuple]:
    if external_user_id is None:
        # Standalone caller: only the local (unowned) pets.
        return "external_user_id IS NULL", ()
    # Launched caller: their own pets OR still-unclaimed local pets.
    return "(external_user_id IS NULL OR external_user_id=?)", (external_user_id,)


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

    NEVER purges a pet with a PENDING writeback (routed to DatsMe —
    datsme_activity_id set — but not yet acked): a queued Accept whose retry
    hasn't drained yet must survive, or the retry would 404 the bundle and the
    pet would be lost. Such pets are always drafts until the ack clears them.
    """
    # A pet is "pending writeback" iff it was routed to DatsMe but not acked.
    # Excluding it from every purge scope protects the retry-queue window.
    not_pending = "(datsme_activity_id IS NULL OR writeback_acked_at IS NOT NULL)"
    if external_user_id == "__all__":
        scope, params = "1=1", ()
    elif external_user_id is None:
        scope, params = "external_user_id IS NULL", ()
    else:
        scope, params = "external_user_id=?", (external_user_id,)
    where = f"draft=1 AND {scope} AND {not_pending}"
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


def list_pending_writebacks(external_user_id: str) -> list[dict]:
    """Accepted-but-unacked pets for resync (writeback_acked_at IS NULL but
    the pet was routed to DatsMe, i.e. it has an activity id pending)."""
    with _lock:
        rows = _connect().execute(
            """SELECT id, breed_id, display_name, created_at FROM pets
               WHERE external_user_id=? AND writeback_acked_at IS NULL
                 AND datsme_activity_id IS NOT NULL
               ORDER BY created_at DESC""", (external_user_id,)).fetchall()
    return [dict(r) for r in rows]


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
                      bundle_sha256, size_bytes, manifest_json
               FROM pets WHERE external_user_id=?
               ORDER BY created_at DESC""", (external_user_id,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["pose_count"] = pose_count(d.pop("manifest_json"))
        out.append(d)
    return out


def claim_unowned_pets(pet_ids: list[str], external_user_id: str,
                       activity_id: Optional[str]) -> list[str]:
    """Bind unclaimed (external_user_id IS NULL) pets to a DatsMe user. Returns the
    ids actually claimed.

    Why this exists (SPEC_DATSPET_HOUSE_ADOPT §2): the house shows a launched user
    `(external_user_id IS NULL OR external_user_id=?)` but export_pets is exact
    match, so an unclaimed pet is visible-and-selectable here yet invisible to the
    host's import — it would silently vanish from the import list with no error.
    The push path never had this problem because _post_pet_writeback's
    _bind_pending claims the pet as it adopts; a pull has no equivalent, so the
    claim has to happen before we hand the user off.

    Only NULL-owner rows are touched: a row already owned by this caller is a
    no-op (the house claims a whole selection, most of which is normally already
    theirs), and a row owned by ANOTHER user is left alone — it was never visible
    to this caller, and the WHERE makes that atomic rather than check-then-write.
    """
    if not pet_ids:
        return []
    claimed = []
    with _lock:
        conn = _connect()
        for pet_id in pet_ids:
            cur = conn.execute(
                """UPDATE pets SET external_user_id=?, datsme_activity_id=?
                   WHERE id=? AND external_user_id IS NULL""",
                (external_user_id, activity_id, pet_id))
            if cur.rowcount:
                claimed.append(pet_id)
        conn.commit()
    return claimed


def revoke_user(external_user_id: str, action: str) -> int:
    """delete → remove the user's pet rows; anonymize → null their
    external_user_id (the pets become standalone/orphaned). Returns count."""
    with _lock:
        conn = _connect()
        if action == "delete":
            cur = conn.execute(
                "DELETE FROM pets WHERE external_user_id=?", (external_user_id,))
        else:  # anonymize
            cur = conn.execute(
                "UPDATE pets SET external_user_id=NULL WHERE external_user_id=?",
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
