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
import re
import secrets
import time
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.concurrency import run_in_threadpool
from starlette.background import BackgroundTask

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
from datsme_partner_sdk.host_signature import (
    HostSignatureError,
    verify_host_signature,
)

log = logging.getLogger(__name__)

router = APIRouter(tags=["datsme"])

# The one activity this partner offers. Stable forever (spec §5.2).
ACTIVITY_DESIGN_A_PET = "design_a_pet"

LAUNCH_COOKIE = "datsme_launch"
# Must be >= the host's LAUNCH_TOKEN_TTL (60 min) so the browser session
# outlives the JWT the writeback carries — designing a pet (GPU build + review)
# can take many minutes, and if the cookie lapsed first the user would lose the
# Accept action while the token was still valid. 60 min matches the host window.
LAUNCH_COOKIE_TTL_SEC = 60 * 60  # 60 min — matches host LAUNCH_TOKEN_TTL

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

# Admin cookie (SPEC_MOTION_PROFILE_ADMIN §2.3). Set ONLY when a launch token
# carries adm=true (an admin-launch bounce, minted for a system_admin). Same
# attributes + TTL as the launch cookie; holds the same verified token so admin
# endpoints re-verify (never parse) it. A normal "Design a pet" launch never sets it.
ADMIN_COOKIE = "datspet_admin"


def _safe_return_path(return_path: Optional[str]) -> Optional[str]:
    """Validate a `return` query param as a same-origin path before redirecting to
    it (open-redirect guard, front-door §3.1 / §5). Accepts only a path that starts
    with a single '/' and contains a conservative charset; rejects '//' (protocol-
    relative → off-origin) and anything with a scheme. Returns the path or None."""
    if not return_path:
        return None
    if not return_path.startswith("/") or return_path.startswith("//"):
        return None
    if not re.fullmatch(r"/[A-Za-z0-9/_\-?=&.]*", return_path):
        return None
    return return_path

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
def launch(token: str | None = None, return_path: str | None = Query(None, alias="return")):
    """Verify a DatsMe launch JWT → set the launch cookie → 303 to the frontend.

    Lands on /design?from=datsme by default, or on a validated `return` path when
    the bounce supplies one (front-door §3.1: sign-in uses return=/design, the
    admin bounce uses return=/admin/motions). An admin launch (token carries
    adm=true) additionally sets the datspet_admin cookie (admin spec §2.3).

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
        # The user's DatsMe display name (nm claim), so the nav can greet them
        # without a profile round-trip. Cosmetic — the session endpoint re-reads
        # it from the VERIFIED token, so a tampered cookie can't spoof a name.
        "display_name": ctx.raw_claims.get("nm"),
    }
    # Where to land: a validated same-origin `return` path, else today's default.
    safe_return = _safe_return_path(return_path)
    target = f"{_frontend_url()}{safe_return}" if safe_return else f"{_frontend_url()}/design?from=datsme"
    redirect = RedirectResponse(url=target, status_code=303)
    redirect.set_cookie(
        key=LAUNCH_COOKIE,
        value=json.dumps(launch_ctx),
        max_age=LAUNCH_COOKIE_TTL_SEC,
        httponly=True,
        samesite=LAUNCH_COOKIE_SAMESITE,
        secure=LAUNCH_COOKIE_SECURE,
    )
    # Admin bounce (admin spec §2.3): an adm=true launch also gets the admin cookie
    # (same verified token; admin endpoints re-verify it). A normal launch does not.
    if ctx.raw_claims.get("adm") is True:
        redirect.set_cookie(
            key=ADMIN_COOKIE,
            value=ctx.token,
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


def resolve_launch_identity(request: Request) -> Optional[str]:
    """Trusted DatsMe user_id for scoping, or None for standalone/local mode.

    Shared by the engine (app.py: generation, listing, draft purge) and the
    Accept path so identity is resolved ONE way everywhere. We VERIFY the JWT
    (not just parse the cookie): the user_id decides which user's pets a write
    is scoped to, so a forged/expired cookie must not be able to write into
    another user's scope — it falls back to None (standalone), never someone
    else's id. When DATSME_HMAC_SECRET is unset (pure standalone) this always
    returns None without error.
    """
    cookie = _read_launch_cookie(request)
    if cookie is None:
        return None
    try:
        ctx = verify_launch_token(cookie["token"], _hmac_secret())
    except (LaunchError, RuntimeError):
        # Expired/invalid token, or no secret configured → treat as standalone.
        return None
    return ctx.user_id


def resolve_launch_capabilities(request: Request) -> list[str]:
    """The caller's VERIFIED DPP launch capabilities, or [] for standalone.
    Drives tier resolution (SPEC_PET_DESIGNER_PLATFORM §5.3). Like
    resolve_launch_identity, we re-verify the JWT rather than trust the cookie:
    a tier grants a higher pose cap + adopt permission, so a forged cookie must
    not be able to claim capabilities the token doesn't carry — an invalid token
    falls back to [] (base tier), never elevated. The verified token's
    capabilities are authoritative; the cookie's cached copy is not trusted."""
    cookie = _read_launch_cookie(request)
    if cookie is None:
        return []
    try:
        ctx = verify_launch_token(cookie["token"], _hmac_secret())
    except (LaunchError, RuntimeError):
        return []
    return list(ctx.capabilities)


# ---------------------------------------------------------------------------
# Pool attribution labels — advisory "requested by" metadata sent with each
# pool job so the pool dashboard can show who/what asked for it. This is the
# ONE place the incoming request is turned into {user, device}; the pool client
# just forwards the flat string→string dict it's handed (never sees the browser).
# ---------------------------------------------------------------------------

def classify_device(user_agent: Optional[str]) -> str:
    """Classify an HTTP User-Agent into a coarse device bucket for the pool's
    "requested by" column. Substring checks only (no UA-parsing dependency):

      iPhone/iPad/iPod/iOS → "ios"; Android → "android"; a known desktop OS
      with a browser token → "desktop"; anything else → "unknown".

    The Android check precedes the desktop-OS check because Android UAs also
    carry "Linux". No request/UA at all (a background/server context) is the
    caller's concern — it passes None here only if it wants the "unknown"
    bucket; pool_labels omits `device` entirely instead."""
    if not user_agent:
        return "unknown"
    ua = user_agent.lower()
    if any(t in ua for t in ("iphone", "ipad", "ipod", "ios")):
        return "ios"
    if "android" in ua:
        return "android"
    if any(os_t in ua for os_t in ("windows", "macintosh", "mac os", "linux", "cros")) \
            and any(b in ua for b in ("mozilla", "chrome", "safari", "firefox", "edg")):
        return "desktop"
    return "unknown"


def pool_labels(request: Optional[Request], owner: Optional[str]) -> dict[str, str]:
    """Build the flat {user, device} label dict for a pool submit from the
    current request + resolved launch identity.

      user   — the verified DatsMe user_id (`owner`), or "anonymous" when
               standalone/unauthenticated. It's a stable id, safe to display on
               an internal dashboard (never a secret/token).
      device — classify_device() of the request's User-Agent. Omitted (not sent)
               when there's no request context (background/server submit) — labels
               are additive, so a missing key is fine.

    Values are clamped to < 64 chars to honor the pool's string→string label
    contract. Returns a plain dict; the caller merges it into the submit body."""
    labels: dict[str, str] = {"user": (owner or "anonymous")[:63]}
    if request is not None:
        labels["device"] = classify_device(request.headers.get("user-agent"))[:63]
    return labels


# ---------------------------------------------------------------------------
# Frontend helper — GET /api/datsme/session
# ---------------------------------------------------------------------------
def _is_integrated() -> bool:
    """True when this DatsPet instance is wired to a DatsMe host (a launch secret
    is configured). False = standalone/local mode, where the front door hides all
    DatsMe sign-in buttons (front-door §0.4)."""
    try:
        _hmac_secret()
        return True
    except RuntimeError:
        return False


def _has_valid_admin_cookie(request: Request) -> bool:
    """True iff the request carries a datspet_admin cookie whose token verifies AND
    carries adm=true (admin spec §2.3). Verify, never parse — a forged cookie is
    not admin. Used by the session endpoint (to show the toolbar link) and by
    require_admin_launch (to gate the admin API)."""
    raw = request.cookies.get(ADMIN_COOKIE)
    if not raw:
        return False
    try:
        ctx = verify_launch_token(raw, _hmac_secret())
    except (LaunchError, RuntimeError):
        return False
    return ctx.raw_claims.get("adm") is True


@router.get("/api/datsme/session")
def datsme_session(request: Request):
    """Tell the frontend whether it was launched from DatsMe (so it can show the
    banner + Accept button), the credit cost to show up front, and the front-door
    fields (integrated mode + the sign-in/sign-up URLs the landing renders)."""
    integrated = _is_integrated()
    # The DatsMe web origin the sign-in/up flows live on (front-door §3.2). The
    # frontend never hardcodes a DatsMe origin — it renders what we hand it.
    signin_url = signup_url = None
    if integrated:
        public = _datsme_public_url()
        signin_url = f"{public}/api/integrations/login-launch?activity={ACTIVITY_DESIGN_A_PET}&return=/design"
        signup_url = f"{public}/signup"
    ctx = _read_launch_cookie(request)
    base = {
        "integrated": integrated,
        "signin_url": signin_url,
        "signup_url": signup_url,
        "admin": integrated and _has_valid_admin_cookie(request),
    }
    if ctx is None:
        return {**base, "launched": False}
    # Re-read the display name from the VERIFIED token (nm claim), not the cookie
    # blob — so a tampered cookie can't spoof the greeting name. None if the token
    # predates the nm claim (older host) or fails verification.
    display_name = None
    try:
        verified = verify_launch_token(ctx["token"], _hmac_secret())
        display_name = verified.raw_claims.get("nm")
    except (LaunchError, RuntimeError, KeyError):
        display_name = None
    return {
        **base,
        "launched": True,
        "user_id": ctx.get("user_id"),
        "display_name": display_name,
        "capabilities": ctx.get("capabilities", []),
        "cost": pet_design_cost(),
    }


@router.post("/api/datsme/logout")
def datsme_logout():
    """End the DatsPet session: clear the launch cookie AND the admin cookie
    (front-door §3.3). This ends the DatsPet session only — the DatsMe session is
    managed on DatsMe. Clearing datspet_admin here (even though the front door
    doesn't set it — the admin flow does) is deliberate: logout owns 'end the
    DatsPet session', so it clears every DatsPet-issued cookie. Harmless if absent."""
    from fastapi.responses import JSONResponse
    resp = JSONResponse({"ok": True})
    for cookie in (LAUNCH_COOKIE, ADMIN_COOKIE):
        resp.delete_cookie(
            key=cookie,
            samesite=LAUNCH_COOKIE_SAMESITE,
            secure=LAUNCH_COOKIE_SECURE,
        )
    return resp


def require_admin_launch(request: Request) -> None:
    """Gate for the admin API (admin spec §2.3). Raises 401 unless the request
    carries a valid datspet_admin cookie (verified adm=true). Import this as a
    dependency on every admin endpoint. Server-authoritative on every request —
    the cookie is re-verified, never trusted as a parsed blob."""
    if not _has_valid_admin_cookie(request):
        raise HTTPException(status_code=401, detail="admin access required")


def admin_user_id(request: Request) -> Optional[str]:
    """The verified admin's DatsMe user_id (for the audit line), or None. Reads the
    datspet_admin cookie and re-verifies the token — same trust discipline as
    require_admin_launch. Call only after require_admin_launch has passed."""
    raw = request.cookies.get(ADMIN_COOKIE)
    if not raw:
        return None
    try:
        ctx = verify_launch_token(raw, _hmac_secret())
    except (LaunchError, RuntimeError):
        return None
    return ctx.user_id


def pet_design_cost() -> Optional[int]:
    """Best-effort fetch of the base credit cost the host will charge, so the
    Accept button + the designer's price hint can show it before committing.
    None if unavailable (the UI then omits the number). Public because the
    entitlement endpoint in app.py reads it too — a cross-module surface, not a
    private helper. The host exposes this via its cost/config; until that
    endpoint is wired we read an env override."""
    override = os.environ.get("DATSPET_DESIGN_COST")
    if override and override.isdigit():
        return int(override)
    return None


# Back-compat alias — some call sites (and tests) reference the old private name.
_pet_design_cost = pet_design_cost


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
    except LaunchError:
        # Token expired (or otherwise invalid) — the partner detects this
        # locally before even calling the host, so the user gets an instant,
        # clear relaunch prompt. Same message as the writeback-time 401 branch.
        raise HTTPException(
            status_code=401,
            detail="Your DatsMe session expired while designing. Return to "
                   "DatsMe and click “Design a pet” again — your design is "
                   "saved here, just re-Accept it.",
        )

    body = await request.json()
    pet_id = (body or {}).get("pet_id", "")
    if not isinstance(pet_id, str) or not pet_id.isalnum():
        raise HTTPException(status_code=400, detail="pet_id required")
    row = db.get_pet(pet_id)
    if row is None:
        raise HTTPException(status_code=404, detail="pet not found")

    # Ownership gate: a user may only Accept a pet that is unclaimed (local,
    # external_user_id IS NULL) or already theirs. 404 (not 403) so we don't
    # leak that another user's pet_id exists. And once a pet has been acked
    # under one user, it can't be re-accepted under a different user.
    owner = row["external_user_id"]
    if owner is not None and owner != ctx.user_id:
        raise HTTPException(status_code=404, detail="pet not found")
    if row["writeback_acked_at"] is not None and owner is not None and owner != ctx.user_id:
        raise HTTPException(status_code=409, detail="pet already adopted by another user")

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
        _bind_pending(row, ctx)  # binds external_user_id = ctx.user_id
        db.stamp_writeback_acked(row["id"], ctx.activity_id, time.time())
        db.keep_pet(row["id"], external_user_id=ctx.user_id)  # now owned; clear draft
        try:
            redirect_path = resp.json().get("redirect_to")
        except ValueError:
            redirect_path = None
        return f"{_datsme_public_url()}{redirect_path}" if redirect_path else f"{_datsme_public_url()}/settings/pet"

    # Non-200. Classify transient (retry) vs permanent (surface):
    #   5xx / 408 / 429  → transient host hiccup; queue and it recovers.
    #   401              → the launch TOKEN is dead (expired / wrong secret).
    #                      The retry queue re-sends the SAME stored token, so a
    #                      401 can NEVER self-heal — queuing it would retry
    #                      forever and silently never deliver. Treat as
    #                      permanent and tell the user to relaunch. (This is
    #                      where we deliberately diverge from the personality
    #                      reference, which queues 401 — its writebacks fire
    #                      seconds after launch, so its tokens are never stale;
    #                      a pet design can outlive even the 60-min window.)
    #   other 4xx        → validation/credits/house — surface the host's error.
    detail = _error_detail(resp)
    transient = resp.status_code >= 500 or resp.status_code in (408, 429)
    log.warning("DatsMe writeback status=%s transient=%s detail=%s",
                resp.status_code, transient, detail)
    if transient:
        _enqueue_writeback_retry(writeback)
        _bind_pending(row, ctx)
        return None
    if resp.status_code == 401:
        raise HTTPException(
            status_code=401,
            detail="Your DatsMe session expired while designing. Return to "
                   "DatsMe and click “Design a pet” again — your design is "
                   "saved here, just re-Accept it.",
        )
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
    """Public entry point for a scheduled worker (Phase 4). Drains due retries
    AND finalizes each success locally: a writeback that finally lands must
    stamp the pet acked + clear its draft, exactly as the inline Accept does on
    a 200. Without this the pet stays a purgeable draft and is lost — the SDK's
    generic drain can't know about our per-pet local state, so we do it here."""
    try:
        from datsme_partner_sdk.retry import drain_due
    except Exception as e:
        log.warning("Retry-queue drain import failed: %s", e)
        return []
    try:
        results = drain_due(_retry_queue_path(), _hmac_secret())
    except Exception as e:
        log.warning("Retry-queue drain failed: %s", e)
        return []

    for pending, status, _detail in results:
        if status != 200:
            continue
        try:
            body = json.loads(pending.body_json)
            payload = body.get("payload") or {}
            pet_id = payload.get("source_pet_id")
            activity_id = payload.get("activity_id")
            if pet_id and db.get_pet(pet_id) is not None:
                db.stamp_writeback_acked(pet_id, activity_id, time.time())
                # The pet is already bound to its user (Accept bound it before
                # queuing); clear the draft under that owner.
                row = db.get_pet(pet_id)
                db.keep_pet(pet_id, external_user_id=row["external_user_id"])
                log.info("retry-drain finalized pet=%s (acked + kept)", pet_id)
        except Exception as e:
            log.warning("Could not finalize drained writeback: %s", e)
    return results


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
    # Burn AFTER the bytes are sent, via a BackgroundTask — single-SUCCESSFUL-
    # download. If we burned before returning and the transfer then failed, the
    # host's retry would 404 and the pet would never arrive. Burning post-send
    # means a failed fetch leaves the token usable for the queued retry; only a
    # completed transfer consumes it.
    return Response(
        content=pet["bundle_zip"],
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{pet["breed_id"]}.zip"'},
        background=BackgroundTask(db.burn_bundle_token, token),
    )


# ---------------------------------------------------------------------------
# Export — GET /partner/export/{user_id}
# ---------------------------------------------------------------------------
@router.get("/partner/export/{user_id}")
def export_user_data(user_id: str, request: Request):
    """Return all DatsPet-owned pets for a DatsMe user (schema datspet_pets.v1).
    Empty exports array (not 404) when the user has none. Host-signed (GET, no
    body)."""
    _require_host_signature(request)
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
    """Delete or anonymize all DatsPet-owned pets for a DatsMe user_id.

    Destructive — MUST be host-signed. We verify over the EXACT raw bytes the
    host signed, then parse those same bytes (never re-read the stream)."""
    raw = await request.body()
    _require_host_signature(request, raw)
    try:
        body = json.loads(raw or b"{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid JSON body")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")
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
    """Pets accepted for a user that never acked a successful writeback.
    Host-signed (GET, no body)."""
    _require_host_signature(request)
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
def _require_host_signature(request: Request, body: bytes = b"") -> None:
    """Fail-closed verification that a request really came from the DatsMe host.

    The host signs its outbound calls to our destructive endpoints
    (export/revoke/pending) over the full envelope (`<METHOD> <path> <ts>.` +
    body). We reject anything not correctly signed — a missing, malformed,
    stale, or mismatched signature all → 401. Delegates to the SDK's
    verify_host_signature so the scheme stays in lockstep with the host and
    isn't hand-rolled per partner. `path` uses the raw ASGI path (no query),
    matching how the host builds `path` in _sign_host_request.
    """
    try:
        verify_host_signature(
            hmac_secret=_hmac_secret(),
            signature_header=request.headers.get("X-DatsMe-Signature"),
            method=request.method,
            path=request.url.path,
            body=body,
        )
    except HostSignatureError:
        # Do NOT reveal which check failed (missing vs stale vs mismatch).
        raise HTTPException(status_code=401, detail="unauthorized")


def _utc_now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _epoch_to_iso(epoch: float) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
