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
        conn.commit()
    _migrate_legacy_folders()


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
               bundle_sha256: Optional[str] = None,
               size_bytes: Optional[int] = None) -> None:
    with _lock:
        conn = _connect()
        conn.execute(
            """INSERT OR REPLACE INTO pets
               (id, breed_id, display_name, created_at, draft, external_user_id,
                bundle_sha256, size_bytes, sheet_png, manifest_json,
                package_json, bundle_zip)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (pet_id, breed_id, display_name, created_at, 1 if draft else 0,
             external_user_id, bundle_sha256, size_bytes, sheet_png,
             manifest_json, package_json, bundle_zip),
        )
        conn.commit()


def get_pet(pet_id: str) -> Optional[sqlite3.Row]:
    with _lock:
        return _connect().execute(
            "SELECT * FROM pets WHERE id=?", (pet_id,)).fetchone()


def list_saved_pets(external_user_id: Optional[str] = None) -> list[dict]:
    """Saved (non-draft) pets, newest first, scoped to the caller's identity.
    Returns the same summary shape the frontend has always received:
    {id, breed_id, display_name, created_at}."""
    with _lock:
        conn = _connect()
        if external_user_id is None:
            rows = conn.execute(
                """SELECT id, breed_id, display_name, created_at FROM pets
                   WHERE draft=0 AND external_user_id IS NULL
                   ORDER BY created_at DESC""").fetchall()
        else:
            rows = conn.execute(
                """SELECT id, breed_id, display_name, created_at FROM pets
                   WHERE draft=0 AND external_user_id=?
                   ORDER BY created_at DESC""", (external_user_id,)).fetchall()
    return [dict(r) for r in rows]


def keep_pet(pet_id: str) -> Optional[dict]:
    """Clear the draft flag. Returns the summary record, or None if absent."""
    with _lock:
        conn = _connect()
        cur = conn.execute("UPDATE pets SET draft=0 WHERE id=?", (pet_id,))
        conn.commit()
        if cur.rowcount == 0:
            return None
        row = conn.execute(
            "SELECT id, breed_id, display_name, created_at, draft FROM pets WHERE id=?",
            (pet_id,)).fetchone()
    return dict(row) if row else None


def delete_pet(pet_id: str) -> bool:
    with _lock:
        conn = _connect()
        cur = conn.execute("DELETE FROM pets WHERE id=?", (pet_id,))
        conn.commit()
        return cur.rowcount > 0


def purge_drafts(external_user_id: Optional[str] = "__all__") -> list[str]:
    """Delete unsaved drafts and return their ids (so the caller can drop the
    matching in-memory Job). external_user_id="__all__" purges every user's
    drafts (startup); None purges only standalone drafts; a value purges that
    user's drafts (a DatsMe user iterating without accepting)."""
    with _lock:
        conn = _connect()
        if external_user_id == "__all__":
            rows = conn.execute("SELECT id FROM pets WHERE draft=1").fetchall()
            conn.execute("DELETE FROM pets WHERE draft=1")
        elif external_user_id is None:
            rows = conn.execute(
                "SELECT id FROM pets WHERE draft=1 AND external_user_id IS NULL").fetchall()
            conn.execute(
                "DELETE FROM pets WHERE draft=1 AND external_user_id IS NULL")
        else:
            rows = conn.execute(
                "SELECT id FROM pets WHERE draft=1 AND external_user_id=?",
                (external_user_id,)).fetchall()
            conn.execute(
                "DELETE FROM pets WHERE draft=1 AND external_user_id=?",
                (external_user_id,))
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
    the record view, schema datspet_pets.v1."""
    with _lock:
        rows = _connect().execute(
            """SELECT id, breed_id, display_name, created_at, draft,
                      datsme_activity_id, writeback_acked_at
               FROM pets WHERE external_user_id=?
               ORDER BY created_at DESC""", (external_user_id,)).fetchall()
    return [dict(r) for r in rows]


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
# Jobs — the in-memory Job dataclass stays the live status object; this table
# only records identity scoping so a restart mid-queue doesn't lose whose job
# it was. (Live progress remains in memory; the DB is not polled per tick.)
# ---------------------------------------------------------------------------
def upsert_job(*, job_id: str, status: str, progress: float, message: str,
               created_at: float, external_user_id: Optional[str] = None) -> None:
    with _lock:
        conn = _connect()
        conn.execute(
            """INSERT OR REPLACE INTO jobs
               (id, status, progress, message, created_at, external_user_id)
               VALUES (?,?,?,?,?,?)""",
            (job_id, status, progress, message, created_at, external_user_id))
        conn.commit()


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
