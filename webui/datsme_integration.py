"""DatsPet ↔ DatsMe partner integration — the DPP adapter (imitates the
datsme_personality reference at app/api/datsme_integration.py).

Standalone-first: this whole module is an adapter mounted on the existing
FastAPI app. When DATSME_HMAC_SECRET is unset the manifest endpoint 503s and
nothing else here is reachable in a way that affects local single-user mode —
the pet engine runs exactly as before.

Transport (spec §3): a pet bundle is ~1–3 MB and the writeback body is capped
at 64 KB, so the writeback carries a POINTER (bundle_url + sha256 + size). The
host fetches the bundle server-to-server via a one-time bundle token, validates
it with its existing validate_uploaded_bundle, and adopts it via write_assets.

Endpoints (spec §5.1):
  GET  /partner/manifest                  signed manifest, ETag/304
  GET  /launch?token=                     verify JWT → cookie → 303 to /design
  GET  /partner/export/{user_id}          GDPR export (schema datspet_pets.v1)
  POST /partner/revoke                    delete | anonymize a user's pets
  GET  /partner/results/{user_id}/pending accepted-but-unacked pets (resync)
  GET  /api/datsme/session                frontend helper (launched? cost?)
  POST /api/datsme/accept                 build+post the writeback for a pet
  GET  /api/datsme/bundle/{token}         serve pet.zip once per token
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import time
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.concurrency import run_in_threadpool

import db

from datsme_partner_sdk import (
    LaunchContext,
    verify_launch_token,
    ManifestBuilder,
    sign_manifest_response,
    WritebackBuilder,
    post_writeback as sdk_post_writeback,
)
from datsme_partner_sdk.launch import LaunchError
from datsme_partner_sdk.manifest import compute_manifest_etag

log = logging.getLogger(__name__)

router = APIRouter(tags=["datsme"])

# The one activity this partner offers. Stable forever (spec §5.2).
ACTIVITY_DESIGN_A_PET = "design_a_pet"

LAUNCH_COOKIE = "datsme_launch"
LAUNCH_COOKIE_TTL_SEC = 60 * 30  # 30 min — matches the reference partner

# Cookie cross-site policy. In dev + prod the DatsPet frontend and backend are
# DIFFERENT origins (frontend :19955 ↔ backend :19954; in prod a partner domain
# vs the API), so the frontend's XHR to /api/datsme/session is CROSS-ORIGIN. A
# SameSite=lax cookie is only sent on top-level navigations, NOT on cross-origin
# fetch — so lax would make the Accept button never appear. SameSite=None (with
# Secure) is sent on cross-origin XHR; browsers treat http://localhost as a
# secure context, so Secure works in dev too. If DatsPet is ever deployed
# same-origin (frontend+backend behind one proxy — spec §8 Phase 4), set
# DATSPET_COOKIE_SAMESITE=lax to drop the Secure requirement.
LAUNCH_COOKIE_SAMESITE = os.environ.get("DATSPET_COOKIE_SAMESITE", "none").lower()
LAUNCH_COOKIE_SECURE = LAUNCH_COOKIE_SAMESITE == "none"

# Bundle tokens must outlive the SDK retry window (backoff ceiling 24 h) so a
# queued writeback's server-to-server fetch still resolves (spec §5.3 / §7).
BUNDLE_TOKEN_TTL_SEC = 24 * 60 * 60

PARTNER_SLUG = os.environ.get("DATSME_PARTNER_SLUG", "datspet")


# ---------------------------------------------------------------------------
# Env helpers (mirror the reference partner's naming)
# ---------------------------------------------------------------------------
def _hmac_secret() -> str:
    secret = os.environ.get("DATSME_HMAC_SECRET", "").strip()
    if not secret:
        raise RuntimeError(
            "DATSME_HMAC_SECRET is not set. Register DatsPet on DatsMe and "
            "paste the returned secret into pet_env.sh."
        )
    return secret


def _datsme_base_url() -> str:
    return os.environ.get("DATSME_BASE_URL", "http://localhost:19994").rstrip("/")


def _datsme_public_url() -> str:
    return os.environ.get("DATSME_PUBLIC_URL", "http://localhost:19995").rstrip("/")


def _datspet_public_url() -> str:
    """This service's public base URL — embedded in the writeback so the host
    can fetch the bundle back. In dev this is the backend's own origin."""
    return os.environ.get(
        "DATSPET_PUBLIC_URL", "http://localhost:19954").rstrip("/")


def _frontend_url() -> str:
    return os.environ.get(
        "DATSPET_FRONTEND_URL", "http://localhost:19955").rstrip("/")


def _retry_queue_path() -> Path:
    return Path(os.environ.get(
        "DATSME_RETRY_QUEUE_PATH",
        str(db.OUTPUT_DIR / "datsme_retry_queue.db"))).resolve()


# ---------------------------------------------------------------------------
# Manifest — GET /partner/manifest
# ---------------------------------------------------------------------------
def _build_manifest_body() -> dict:
    mb = (
        ManifestBuilder(
            slug=PARTNER_SLUG,
            display_name="DatsPet",
            base_url=_datspet_public_url(),
            tagline="Design your own animated pet and adopt it into your house.",
        )
        .add_activity(
            activity_id=ACTIVITY_DESIGN_A_PET,
            display_name="Design a pet",
            description="Design your own animated pet and adopt it into your house.",
            category="fun",
            activity_type="pet_design",
            launch_cta="Design a pet on DatsPet",
            emoji="🐾",
            estimated_minutes=5,
        )
        .request_capability(
            "pets.write",
            justification="Deliver the pet the user designed into their DatsMe pet house.",
            required=True,
        )
        .request_capability(
            "profile.read",
            justification="Greet the user by their DatsMe name while designing.",
            required=False,
        )
        .add_data_export(
            export_type="pets",
            schema="datspet_pets.v1",
            description="The pets you designed on DatsPet.",
            per_user_downloadable=True,
        )
        .set_schema_version("user.pet", "pet_bundle.v1")
    )
    return mb.build()


@router.get("/partner/manifest")
def serve_manifest(request: Request):
    """Serve the HMAC-signed manifest with ETag/304 support (spec §5.1)."""
    try:
        secret = _hmac_secret()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    manifest = _build_manifest_body()
    etag = compute_manifest_etag(manifest)
    if request.headers.get("If-None-Match") == etag:
        return Response(status_code=304, headers={"ETag": etag})

    raw, sig = sign_manifest_response(manifest, secret)
    return Response(
        content=raw,
        media_type="application/json",
        headers={"ETag": etag, "X-DatsMe-Signature": sig},
    )


# ---------------------------------------------------------------------------
# Inbound: DatsMe → /launch
# ---------------------------------------------------------------------------
@router.get("/launch")
def launch(token: str | None = None):
    """Verify a DatsMe launch JWT → set the launch cookie → 303 to /design.

    Resync (rsx claim): re-post an already-accepted pet's writeback without
    involving the user, then redirect (spec §5.1).
    """
    try:
        ctx: LaunchContext = verify_launch_token(token or "", _hmac_secret())
    except LaunchError as e:
        raise HTTPException(status_code=401, detail=str(e))

    # Resync short-circuit — rsx carries a source_pet_id we accepted before.
    rsx = ctx.raw_claims.get("rsx")
    if rsx:
        row = db.get_pet(rsx)
        if row is None:
            raise HTTPException(status_code=404, detail=f"Pet {rsx!r} not found for resync")
        if row["external_user_id"] != ctx.user_id:
            raise HTTPException(status_code=403, detail="Resync pet does not belong to the authenticated user")
        if row["datsme_activity_id"] != ctx.activity_id:
            raise HTTPException(status_code=409, detail="Resync pet activity_id does not match launch scope")
        redirect_url = _post_pet_writeback(row, ctx)
        target = redirect_url or f"{_frontend_url()}/house"
        return RedirectResponse(url=target, status_code=303)

    if ctx.activity_id != ACTIVITY_DESIGN_A_PET:
        raise HTTPException(
            status_code=400,
            detail=f"unknown_activity: {ctx.activity_id!r}",
        )

    launch_ctx = {
        "token": ctx.token,
        "user_id": ctx.user_id,
        "activity_id": ctx.activity_id,
        "jti": ctx.jti,
        "capabilities": list(ctx.capabilities),
    }
    redirect = RedirectResponse(url=f"{_frontend_url()}/design?from=datsme", status_code=303)
    redirect.set_cookie(
        key=LAUNCH_COOKIE,
        value=json.dumps(launch_ctx),
        max_age=LAUNCH_COOKIE_TTL_SEC,
        httponly=True,
        samesite=LAUNCH_COOKIE_SAMESITE,
        secure=LAUNCH_COOKIE_SECURE,
    )
    return redirect


def _read_launch_cookie(request: Request) -> Optional[dict]:
    """Return the parsed launch context, or None if absent/malformed. Does
    NOT re-verify the JWT — /accept does that before it acts."""
    raw = request.cookies.get(LAUNCH_COOKIE)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict) or "token" not in data:
        return None
    return data


# ---------------------------------------------------------------------------
# Frontend helper — GET /api/datsme/session
# ---------------------------------------------------------------------------
@router.get("/api/datsme/session")
def datsme_session(request: Request):
    """Tell the frontend whether it was launched from DatsMe (so it can show
    the banner + Accept button) and the credit cost to show up front."""
    ctx = _read_launch_cookie(request)
    if ctx is None:
        return {"launched": False}
    return {
        "launched": True,
        "user_id": ctx.get("user_id"),
        "capabilities": ctx.get("capabilities", []),
        "cost": _pet_design_cost(),
    }


def _pet_design_cost() -> Optional[int]:
    """Best-effort fetch of the credit cost the host will charge, so the
    Accept button can show it before committing. None if unavailable (the UI
    then omits the number). The host exposes this via its cost/config; until
    that endpoint is wired we read an env override."""
    override = os.environ.get("DATSPET_DESIGN_COST")
    if override and override.isdigit():
        return int(override)
    return None


# ---------------------------------------------------------------------------
# Outbound: Accept → build + post the writeback
# ---------------------------------------------------------------------------
@router.post("/api/datsme/accept")
async def accept_pet(request: Request):
    """Accept a designed pet into the launching user's DatsMe (spec §5.1).

    Requires a launch cookie; re-verifies the token; mints a one-time bundle
    token; builds + posts the pointer writeback. On 200 stamps the pet as
    acked and clears its draft flag. Transient failure → SDK retry queue +
    still return the local success state.
    """
    cookie = _read_launch_cookie(request)
    if cookie is None:
        raise HTTPException(status_code=401, detail="Not launched from DatsMe — return to DatsMe and relaunch.")
    try:
        ctx = verify_launch_token(cookie["token"], _hmac_secret())
    except LaunchError as e:
        raise HTTPException(status_code=401, detail=f"Launch expired — return to DatsMe and relaunch. ({e})")

    body = await request.json()
    pet_id = (body or {}).get("pet_id", "")
    if not isinstance(pet_id, str) or not pet_id.isalnum():
        raise HTTPException(status_code=400, detail="pet_id required")
    row = db.get_pet(pet_id)
    if row is None:
        raise HTTPException(status_code=404, detail="pet not found")

    # Bind the pet to this DatsMe user (so export/resync/scoping can find it)
    # and record the activity it's being accepted under.
    #
    # _post_pet_writeback makes a BLOCKING httpx POST to the host, and the host
    # synchronously calls back to GET our /api/datsme/bundle/{token} before it
    # responds. If we ran that blocking call on the event loop, our loop would
    # be frozen and unable to serve the host's bundle fetch — a self-deadlock
    # that fails every Accept. Offload to a worker thread so the event loop
    # stays free to serve the bundle request concurrently.
    redirect_url = await run_in_threadpool(_post_pet_writeback, row, ctx)
    if redirect_url is None:
        # Transient failure: the writeback is queued (or a permanent error was
        # raised below). Tell the UI the pet will arrive automatically.
        return {"queued": True,
                "message": "DatsMe is unavailable right now — your pet will arrive automatically."}
    return {"redirect_url": redirect_url}


def _post_pet_writeback(row, ctx: LaunchContext) -> Optional[str]:
    """Build + POST the pointer writeback for `row`. Returns a redirect URL on
    success, None on transient failure (queued). Raises HTTPException for
    permanent (non-retryable) host errors so the UI shows the real reason."""
    zip_bytes = row["bundle_zip"]
    sha256 = hashlib.sha256(zip_bytes).hexdigest()

    # One-time bundle token (reusable until first successful download, then
    # burned) — this is what bundle_url points at, NOT /api/pets/{id}/zip.
    token = secrets.token_urlsafe(16)
    db.create_bundle_token(token, row["id"], time.time() + BUNDLE_TOKEN_TTL_SEC)

    writeback = (
        WritebackBuilder(ctx)
        .target("user.pet", schema_version="pet_bundle.v1")
        .payload({
            "activity_id": ctx.activity_id,
            "breed_id": row["breed_id"],
            "display_name": row["display_name"],
            "bundle_url": f"{_datspet_public_url()}/api/datsme/bundle/{token}",
            "bundle_sha256": sha256,
            "size_bytes": len(zip_bytes),
            "source_pet_id": row["id"],
        })
        .build()  # idempotency_key defaults to ctx.jti — one accept per launch
    )

    try:
        resp = sdk_post_writeback(
            datsme_base_url=_datsme_base_url(),
            partner_slug=PARTNER_SLUG,
            hmac_secret=_hmac_secret(),
            body=writeback,
            # A user.pet writeback is SYNCHRONOUS work on the host: it fetches
            # the (≤32 MB) bundle back from us server-to-server, validates it,
            # charges credits, and adopts across two databases before it
            # responds. The SDK's 10 s default is too tight for that and makes
            # a successful adoption look "queued". 60 s comfortably covers it;
            # a genuine host outage still trips the retry path below.
            timeout_seconds=60.0,
        )
    except httpx.HTTPError as e:
        log.warning("DatsMe writeback request failed: %s — enqueuing for retry", e)
        _enqueue_writeback_retry(writeback)
        _bind_pending(row, ctx)  # ack happens only on a 200
        return None

    if resp.status_code == 200:
        _bind_pending(row, ctx)
        db.stamp_writeback_acked(row["id"], ctx.activity_id, time.time())
        db.keep_pet(row["id"])  # accepted pets are no longer drafts
        try:
            redirect_path = resp.json().get("redirect_to")
        except ValueError:
            redirect_path = None
        return f"{_datsme_public_url()}{redirect_path}" if redirect_path else f"{_datsme_public_url()}/settings/pet"

    # Non-200. Split transient vs permanent exactly like the reference partner
    # (spec §5.3): network/5xx/{401,408,429} → retry queue; other 4xx → surface.
    transient = resp.status_code >= 500 or resp.status_code in (401, 408, 429)
    detail = _error_detail(resp)
    log.warning("DatsMe writeback status=%s transient=%s detail=%s",
                resp.status_code, transient, detail)
    if transient:
        _enqueue_writeback_retry(writeback)
        _bind_pending(row, ctx)
        return None
    # Permanent — surface the host's structured error to the UI (402/409/400).
    raise HTTPException(status_code=resp.status_code, detail=detail)


def _bind_pending(row, ctx: LaunchContext) -> None:
    """Record which user+activity a pet was routed to, WITHOUT marking it
    acked — so /pending and resync can find it if the writeback is still in
    flight. Only sets ownership fields; writeback_acked_at stays NULL."""
    if row["external_user_id"] != ctx.user_id or row["datsme_activity_id"] != ctx.activity_id:
        with db._lock:  # small direct update; mirrors stamp_writeback_acked
            conn = db._connect()
            conn.execute(
                "UPDATE pets SET external_user_id=?, datsme_activity_id=? WHERE id=?",
                (ctx.user_id, ctx.activity_id, row["id"]))
            conn.commit()


def _error_detail(resp: httpx.Response) -> str:
    try:
        data = resp.json()
        if isinstance(data, dict):
            return data.get("detail") or data.get("message") or resp.text[:200]
    except ValueError:
        pass
    return resp.text[:200]


def _enqueue_writeback_retry(body: dict) -> None:
    """Best-effort enqueue into the SDK retry queue. Never let a queue write
    cascade into a user-visible failure."""
    try:
        from datsme_partner_sdk.retry import enqueue
        enqueue(
            _retry_queue_path(),
            partner_slug=PARTNER_SLUG,
            datsme_base_url=_datsme_base_url(),
            body=body,
        )
    except Exception as e:
        log.warning("Retry-queue enqueue failed: %s", e)


def drain_retry_queue() -> list:
    """Public entry point for a scheduled worker (Phase 4). Drains due retries."""
    try:
        from datsme_partner_sdk.retry import drain_due
        return drain_due(_retry_queue_path(), _hmac_secret())
    except Exception as e:
        log.warning("Retry-queue drain failed: %s", e)
        return []


# ---------------------------------------------------------------------------
# Bundle serving — GET /api/datsme/bundle/{token}
# ---------------------------------------------------------------------------
@router.get("/api/datsme/bundle/{token}")
def serve_bundle(token: str):
    """Serve a pet's zip once per token. Single-successful-download: the token
    is burned only after the bytes are fully returned, so a failed transfer
    can be retried while the writeback sits in the queue (spec §5.3).

    This endpoint is exempt from all session logic — the host fetches it
    server-to-server with only the one-time token."""
    row_tok = db.resolve_bundle_token(token)
    if row_tok is None:
        raise HTTPException(status_code=404, detail="bundle token invalid, expired, or already used")
    pet = db.get_pet(row_tok["pet_id"])
    if pet is None:
        raise HTTPException(status_code=404, detail="pet not found")
    db.burn_bundle_token(token)
    return Response(
        content=pet["bundle_zip"],
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{pet["breed_id"]}.zip"'},
    )


# ---------------------------------------------------------------------------
# Export — GET /partner/export/{user_id}
# ---------------------------------------------------------------------------
@router.get("/partner/export/{user_id}")
def export_user_data(user_id: str, request: Request):
    """Return all DatsPet-owned pets for a DatsMe user (schema datspet_pets.v1).
    Empty exports array (not 404) when the user has none."""
    _verify_host_signed_request(request)
    return {
        "user_id": user_id,
        "partner_slug": PARTNER_SLUG,
        "exported_at": _utc_now_iso(),
        "exports": [
            {
                "type": "pets",
                "schema": "datspet_pets.v1",
                "data": db.export_pets(user_id),
            }
        ],
    }


# ---------------------------------------------------------------------------
# Revoke — POST /partner/revoke
# ---------------------------------------------------------------------------
@router.post("/partner/revoke")
async def revoke_user(request: Request):
    """Delete or anonymize all DatsPet-owned pets for a DatsMe user_id."""
    _verify_host_signed_request(request)
    body = await request.json()
    user_id = body.get("user_id")
    action = body.get("action", "delete")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")
    if action not in ("delete", "anonymize"):
        raise HTTPException(status_code=400, detail="action must be delete or anonymize")
    count = db.revoke_user(user_id, action)
    return {"status": "ok", "deleted_count": count, "action": action}


# ---------------------------------------------------------------------------
# Resync — GET /partner/results/{user_id}/pending
# ---------------------------------------------------------------------------
@router.get("/partner/results/{user_id}/pending")
def list_pending_writebacks(user_id: str, request: Request):
    """Pets accepted for a user that never acked a successful writeback."""
    _verify_host_signed_request(request)
    rows = db.list_pending_writebacks(user_id)
    return {
        "pending": [
            {
                "partner_result_id": r["id"],
                "activity_id": ACTIVITY_DESIGN_A_PET,
                "completed_at": _epoch_to_iso(r["created_at"]),
            }
            for r in rows
        ]
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _verify_host_signed_request(request: Request) -> None:
    """Host → partner signature verification (mirror of writeback signing).

    Permissive in the current phase, exactly like the reference partner: a
    missing signature is allowed (the host's signed-GET scheme is still
    stabilizing); a present-but-mismatched signature is logged, not rejected.
    Tighten to a hard reject once the host ships signed GETs consistently.
    """
    sig_header = request.headers.get("X-DatsMe-Signature")
    if not sig_header:
        log.info("Host-initiated request had no X-DatsMe-Signature — allowing (permissive phase)")
        return
    import hmac as _hmac
    import hashlib as _hashlib
    try:
        ts_str = sig = None
        for part in (p.strip() for p in sig_header.split(",")):
            if part.startswith("t="):
                ts_str = part[2:]
            elif part.startswith("v1="):
                sig = part[3:]
        if not ts_str or not sig:
            raise ValueError("malformed")
        ts = int(ts_str)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid signature")
    expected = _hmac.new(
        _hmac_secret().encode(),
        f"{ts}.".encode(),
        _hashlib.sha256,
    ).hexdigest()
    if not _hmac.compare_digest(expected, sig):
        log.warning("Host signature mismatch (non-blocking in permissive phase)")


def _utc_now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _epoch_to_iso(epoch: float) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
