"""DatsPet ↔ DatsMe partner integration — the DPP adapter (imitates the
datsme_personality reference at app/api/datsme_integration.py).

Standalone-first: this whole module is an adapter mounted on the existing
FastAPI app. When DATSME_HMAC_SECRET is unset the manifest endpoint 503s and
nothing else here is reachable in a way that affects local single-user mode —
the pet engine runs exactly as before.

Transport: a pet reaches DatsMe through the PULL channel — the user checks out on
the host's own import page, and the host fetches the bundle server-to-server via a
one-time bundle token, validates it, and adopts it. DatsPet never pushes and never
triggers a charge; it serves bytes to an authenticated host request
(SPEC_DATSPET_FEDERATED_SESSION §6).

Endpoints:
  GET  /partner/manifest                  signed manifest, ETag/304
  GET  /launch?token=                     verify JWT → cookie → 303 to /design
  GET  /partner/export/{user_id}          GDPR export + the pull's offer list
  POST /partner/revoke                    delete | anonymize a user's pets
  GET  /partner/results/{user_id}/pending always empty — nothing is ever owed (§4.6)
  POST /partner/imported/{user_id}        the host's post-checkout ack
  GET  /api/datsme/session                frontend helper (launched? stale? cost?)
  GET  /api/datsme/signout                federated sign-out (§4.1)
  GET  /api/datsme/signed-out             the origin-translation hop back (§4.4)
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
from urllib.parse import quote

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.concurrency import run_in_threadpool
from starlette.background import BackgroundTask

import db
import owner_scope

from datsme_partner_sdk import (
    LaunchContext,
    verify_launch_token,
    ManifestBuilder,
    sign_manifest_response,
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
# Matched to the host's LAUNCH_TOKEN_TTL, because resolve_owner_scope re-verifies
# the token on every request: a cookie that outlived its token would only produce
# `stale`, and one that died first would drop the user to anonymous a beat early.
#
# The old rationale here was that the cookie had to outlive the JWT "so the user
# doesn't lose the Accept action while the token is still valid". There is no
# Accept: purchases run on the pull checkout, authenticated by the user's own
# 30-day DatsMe session, so nothing token-authenticated happens at the end of a
# build any more (SPEC_DATSPET_FEDERATED_SESSION §4.3). What a long design session
# needs now is RENEWAL — the session endpoint reports token_expires_in and the
# client silently re-launches (§4.2) — not a longer cookie.
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

# Bundle tokens must outlive the gap between the host LISTING an item (which mints
# the token) and the user confirming the checkout, which is human-paced — a user may
# open the import page and confirm the next day.
BUNDLE_TOKEN_TTL_SEC = 24 * 60 * 60

PARTNER_SLUG = os.environ.get("DATSME_PARTNER_SLUG", "datspet")

# The declared price bases an export item may carry (SPEC_PET_STORE §7).
# `per_pose` is the existing designed-pet formula; `store_flat` maps to the
# host's flat `credit_pet_store_cost` knob. The wire strings are a host
# contract — change them only with the host's pet_writeback in the same breath.
PRICE_BASIS_PER_POSE = "per_pose"
PRICE_BASIS_STORE_FLAT = "store_flat"


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
            # Opt this export into the DPP pull (SPEC_DPP_DATA_TRANSFER_CHANNEL
            # §5.3). All three are required together — the host's conformance
            # check fails a manifest that declares transferable without the other
            # two, and its registry independently decides ingestibility, so these
            # are a request, not a grant.
            transferable=True,
            ingest_target="user.pet",
            max_bytes=10 * 1024 * 1024,   # host clamps to its own 32 MB ceiling
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
def launch(request: Request, token: str | None = None,
           return_path: str | None = Query(None, alias="return")):
    """Verify a DatsMe launch JWT → set the launch cookie → 303 to the frontend.

    Lands on /design?from=datsme by default, or on a validated `return` path when
    the bounce supplies one (front-door §3.1: sign-in uses return=/design, the
    admin bounce uses return=/admin/motions). An admin launch (token carries
    adm=true) additionally sets the datspet_admin cookie (admin spec §2.3).

    An `rsx` (resync) claim is accepted and IGNORED. It used to short-circuit into
    a writeback, which was the push path's recovery channel; there is no push any
    more (SPEC_DATSPET_FEDERATED_SESSION §6.2a). The host is unchanged and may
    still mint one from a stale row, and a user who clicks a recovery link deserves
    a working page rather than a 404 — so this lands on the designer like any other
    launch.
    """
    try:
        ctx: LaunchContext = verify_launch_token(token or "", _hmac_secret())
    except LaunchError as e:
        raise HTTPException(status_code=401, detail=str(e))

    if ctx.raw_claims.get("rsx"):
        log.info("launch: ignoring rsx claim %r — the push path is retired (§6.2a)",
                 ctx.raw_claims.get("rsx"))

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
    # Claim this browser's anonymous work, HERE — the moment it gains a DatsMe
    # identity (SPEC_DATSPET_FEDERATED_SESSION §4.5 c). Doing it at launch rather
    # than at hand-off means the house, the designer and every other surface
    # inherit it without repeating the step, and a user who designed something
    # before signing in still has it (and can still build with it) afterwards.
    #
    # The anon cookie is deliberately NOT cleared here — it survives until
    # sign-out. A row can land microseconds after this sweep (a build already
    # running finalizes into a pet), and the /api/pets/claim backstop needs the
    # anon id to reach it. It carries no authority while a launch cookie exists:
    # resolve_owner_scope prefers the launch cookie unconditionally.
    anon_owner = request.cookies.get(owner_scope.ANON_COOKIE)
    moved = owner_scope.claim_anon_owner(anon_owner, ctx.user_id, ctx.activity_id)
    if any(moved.values()):
        log.info("launch: claimed %s from %s for %s", moved, anon_owner, ctx.user_id)

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


def verified_launch_user_id(cookie: dict) -> Optional[str]:
    """The DatsMe user_id from a parsed launch cookie, or None if its token no
    longer verifies. VERIFY, never parse: the user_id decides which user's rows a
    write is scoped to, so a forged or expired cookie must not reach another user's
    scope.

    The caller distinguishes "no cookie" from "cookie that failed here" — those are
    different states and collapsing them is what put a signed-in user's minute-61
    pet into the anonymous pool (SPEC_DATSPET_FEDERATED_SESSION §0.7). Used by
    owner_scope.resolve_owner_scope, which is the only identity door.
    """
    try:
        return verify_launch_token(cookie["token"], _hmac_secret()).user_id
    except (LaunchError, RuntimeError, KeyError):
        return None


def resolve_launch_activity(request: Request) -> Optional[str]:
    """The VERIFIED activity id this caller launched under, or None.

    Same posture as owner_scope.resolve_owner_scope: re-verify the JWT rather than
    trust the cookie blob. Used to stamp provenance on a claimed pet
    (SPEC_DATSPET_HOUSE_ADOPT §3.3), the way the retired push path's _bind_pending
    did — so a pet claimed at sign-in carries the same shape of record.
    """
    cookie = _read_launch_cookie(request)
    if cookie is None:
        return None
    try:
        return verify_launch_token(cookie["token"], _hmac_secret()).activity_id
    except (LaunchError, RuntimeError):
        return None


def resolve_launch_capabilities(request: Request) -> list[str]:
    """The caller's VERIFIED DPP launch capabilities, or [] for standalone.
    Drives tier resolution (SPEC_PET_DESIGNER_PLATFORM §5.3). Like
    owner_scope.resolve_owner_scope, we re-verify the JWT rather than trust the cookie:
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


def resolve_launch_display_name(request: Request) -> Optional[str]:
    """The launched user's human-readable name (the verified `nm` claim), or
    None for standalone / no-name tokens. This is the SAME source the session
    endpoint hands the frontend as "who is logged in" (see the session route's
    display_name), so the pool dashboard shows the name a human recognizes.

    Re-verifies the JWT like the other resolve_launch_* helpers rather than
    trusting the cookie blob — a display name shown on an internal dashboard is
    low-stakes, but resolving it the one trusted way keeps this consistent with
    identity/capability resolution and avoids reading an unverified claim."""
    cookie = _read_launch_cookie(request)
    if cookie is None:
        return None
    try:
        ctx = verify_launch_token(cookie["token"], _hmac_secret())
    except (LaunchError, RuntimeError):
        return None
    nm = ctx.raw_claims.get("nm")
    return nm if isinstance(nm, str) and nm.strip() else None


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
    """Build the flat {user, user_id, device} label dict for a pool submit from
    the current request + resolved launch identity.

      user    — the HUMAN-READABLE name a person recognizes on the dashboard: the
                verified `nm` display-name claim (same source the session endpoint
                reports as "who is logged in"), falling back to the user_id when no
                name is on the token, and to "anonymous" when there is no DatsMe
                user at all — standalone OR a per-browser anonymous owner. Never
                empty.
      user_id — the verified DatsMe user_id, kept alongside for unambiguous lookup
                (the readable name isn't guaranteed unique). Sent only when there
                actually is a launched id — omitted for standalone/anonymous.
      device  — classify_device() of the request's User-Agent. Omitted (not sent)
                when there's no request context (background/server submit) — labels
                are additive, so a missing key is fine.

    Values are clamped to < 64 chars to honor the pool's string→string label
    contract. Returns a plain dict; the caller merges it into the submit body."""
    display_name = resolve_launch_display_name(request) if request is not None else None
    # An anonymous owner is a per-browser SCOPING value, not a person
    # (SPEC_DATSPET_FEDERATED_SESSION §4.5) — so it is NOT a launched id here.
    # Before this test, `owner` was None for every anonymous caller and the two
    # lines below read naturally; once anonymous callers gained an "anon:<uuid4>"
    # id, that id became the dashboard's readable name, `user_id` dropped out
    # (owner == user), and a distinct label value crossed into the shared pool for
    # every browser that ever visited. Anonymous is anonymous on the dashboard.
    launched_owner = None if owner_scope.is_anon_owner(owner) else owner
    # user = readable name > user_id > "anonymous"; never blank.
    user = display_name or launched_owner or "anonymous"
    labels: dict[str, str] = {"user": user[:63]}
    # Keep the id for unambiguous lookup, but only when it adds signal — i.e. a
    # real launched id that differs from what we already put in `user`.
    if launched_owner and launched_owner != user:
        labels["user_id"] = launched_owner[:63]
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
    banner + Adopt button), the credit cost to show up front, and the front-door
    fields (integrated mode + the sign-in/sign-out/sign-up URLs the landing renders).

    THE ONE ENDPOINT THAT NEVER 401s ON A STALE SESSION
    (SPEC_DATSPET_FEDERATED_SESSION §4.7). It is what tells the frontend to renew,
    so answering 401 here would deadlock the renewal it is supposed to trigger. A
    lapsed launch cookie comes back as `launched: false, stale: true` and the client
    silently re-launches (§4.2)."""
    integrated = _is_integrated()
    # The DatsMe web origin the sign-in/up flows live on (front-door §3.2). The
    # frontend never hardcodes a DatsMe origin — it renders what we hand it.
    signin_url = signup_url = import_url = None
    if integrated:
        public = _datsme_public_url()
        signin_url = f"{public}/api/integrations/login-launch?activity={ACTIVITY_DESIGN_A_PET}&return=/design"
        signup_url = f"{public}/signup"
        # Where the house's Adopt action hands off (SPEC_DATSPET_HOUSE_ADOPT §3.5).
        # Built here for the same reason signin_url is: the frontend never hardcodes
        # a DatsMe origin, and PARTNER_SLUG is env-overridable, so "/import/datspet"
        # is not a constant the browser may assume.
        import_url = f"{public}/import/{PARTNER_SLUG}"
    ctx = _read_launch_cookie(request)
    base = {
        "integrated": integrated,
        "signin_url": signin_url,
        "signup_url": signup_url,
        "import_url": import_url,
        "signout_url": None,
        "admin": integrated and _has_valid_admin_cookie(request),
    }
    if ctx is None:
        return {**base, "launched": False}

    # Everything below reads the VERIFIED token, never the cookie blob, so a
    # tampered cookie can spoof neither the greeting name nor the renewal clock.
    try:
        verified = verify_launch_token(ctx["token"], _hmac_secret())
    except (LaunchError, RuntimeError, KeyError):
        # Present but lapsed. Say so plainly instead of 401ing — see the docstring.
        return {**base, "launched": False, "stale": True}

    return {
        **base,
        # The host logout bounce, prebuilt server-side exactly as signin_url and
        # import_url are, so the frontend never hardcodes a DatsMe origin. The
        # `return` is a DatsPet BACKEND path: the host can only redirect to the
        # origin it has registered, which is our API origin, and
        # /api/datsme/signed-out is what translates that to the frontend (§3.1.4).
        "signout_url": (
            f"{_datsme_public_url()}/api/integrations/logout-launch"
            f"?token={quote(ctx['token'], safe='')}&return=/api/datsme/signed-out"
        ),
        "launched": True,
        "stale": False,
        "user_id": ctx.get("user_id"),
        "display_name": verified.raw_claims.get("nm"),
        "capabilities": ctx.get("capabilities", []),
        "cost": pet_design_cost(),
        # Would this user PASS the admin bounce? A display hint, nothing more:
        # `admin` above is the real thing (a verified adm-claim cookie) and is
        # what every admin route gates on. This only decides whether the nav
        # offers an admin entry point at all, so a non-admin is not invited to
        # click something the host will bounce back with ?signin=admin_denied.
        #
        # Read from the VERIFIED token like every other claim here, never the
        # cookie blob. Absent on a pre-`sadm` host → False → the nav simply keeps
        # its current behaviour for that user, which is the safe degradation.
        "system_admin": verified.raw_claims.get("sadm") is True,
        # Seconds until this assertion lapses, so the client can renew BEFORE it
        # does (§4.2). From the verified exp, never the cookie's max_age.
        "token_expires_in": _token_expires_in(verified),
    }


def _token_expires_in(ctx: LaunchContext) -> Optional[int]:
    """Whole seconds until the verified token's `exp`, floored at 0. None when the
    token carries no exp (it always does today; the guard keeps a malformed one from
    turning a session read into a 500)."""
    exp = ctx.raw_claims.get("exp")
    if not isinstance(exp, (int, float)):
        return None
    return max(0, int(exp - time.time()))


def _clear_datspet_cookies(response: Response) -> None:
    """Delete every cookie DatsPet issues, with the attributes their setters used —
    browsers key cookie identity on samesite/secure, so a mismatched delete is
    silently ignored.

    ALL THREE, and the third is not housekeeping (SPEC_DATSPET_FEDERATED_SESSION
    §4.1): if the anonymous owner id survives sign-out, user B inherits user A's
    pre-sign-in pets and the house is not empty — which is the whole point of the
    feature.
    """
    import owner_scope
    for cookie in (LAUNCH_COOKIE, ADMIN_COOKIE, owner_scope.ANON_COOKIE):
        response.delete_cookie(
            key=cookie,
            samesite=LAUNCH_COOKIE_SAMESITE,
            secure=LAUNCH_COOKIE_SECURE,
        )


@router.get("/api/datsme/signout")
def datsme_signout(request: Request):
    """Sign out of BOTH sides, in one hop the browser navigates to.

    We can clear our own cookies but not DatsMe's — they are on a different origin —
    so the browser must visit the host to end the session there. This endpoint
    clears ours on the SAME response that redirects to the host's logout bounce, so
    the clear and the hop cannot half-fail (a cleared partner session with a live
    host session is exactly the state that let only one person use a browser).

    The token is forwarded WITHOUT verifying it here, deliberately. The host
    verifies it against its own copy of the partner secret and is the only
    authority on it; re-checking locally would add a second opinion that can only
    disagree, and an EXPIRED token must still work (the host ignores exp on that
    path, because refusing to sign out a user whose token just lapsed is the worst
    failure mode available) — which the SDK's verifier cannot express. If the token
    is forged the host 400s, and our cookies are already gone by then, so the user
    is still correctly signed out here.

    Standalone, or no launch cookie at all: clear locally and land on our own
    page. There is no host to visit.
    """
    target = f"{_frontend_url()}/"
    ctx = _read_launch_cookie(request)
    if ctx is not None and _is_integrated() and ctx.get("token"):
        target = (f"{_datsme_public_url()}/api/integrations/logout-launch"
                  f"?token={quote(ctx['token'], safe='')}"
                  f"&return=/api/datsme/signed-out")
    response = RedirectResponse(url=target, status_code=303)
    _clear_datspet_cookies(response)
    return response


@router.get("/api/datsme/signed-out")
def datsme_signed_out():
    """The landing hop the host redirects back to after ending its session.

    It exists because the host can only redirect to the origin it has REGISTERED
    for us, which is our API origin (the manifest's base_url), while the landing
    page lives on the frontend origin — :19954 vs :19955 in dev. They coincide in
    production only because one nginx vhost serves both, so a `return=/` would work
    in prod and drop the user on the FastAPI root in dev.

    This is the exact mirror of what /launch does on the way in, and it keeps the
    frontend origin a DatsPet-side fact that no host row has to know.
    """
    response = RedirectResponse(url=f"{_frontend_url()}/?signedout=1", status_code=303)
    # Belt and braces: the signout hop already cleared these, but a user who reaches
    # the host bounce from a stale tab should still land here without them.
    _clear_datspet_cookies(response)
    return response


@router.post("/api/datsme/logout")
def datsme_logout():
    """Clear DatsPet's own cookies and nothing else — the LOCAL primitive.

    This is not "sign out" any more: it cannot touch the DatsMe session, which lives
    on another origin, so on its own it leaves the user signed in there and the next
    sign-in silently re-mints them. GET /api/datsme/signout is the real thing
    (SPEC_DATSPET_FEDERATED_SESSION §4.1) and is what the nav calls.

    Kept because standalone mode and the tests need a way to drop the local cookies
    without a host round trip.
    """
    from fastapi.responses import JSONResponse
    resp = JSONResponse({"ok": True})
    _clear_datspet_cookies(resp)
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
                "data": [_export_item(row) for row in db.export_pets(user_id)],
            }
        ],
    }


def _export_item(row: dict) -> dict:
    """One `datspet_pets.v1` item: the record view, plus an optional `transfer`
    block that opts it into the DPP pull (SPEC_DATSPET_HOUSE_ADOPT §3.2).

    The block is built HERE and not in db.export_pets because minting a token is a
    protocol act, not a record read — db stays the byteless record view it
    documents itself as.

    Omitted when the row cannot be transferred honestly: no digest (a pre-backfill
    row) or no pose_count (an unparseable manifest). The host refuses to quote an
    item with no declared basis and skips one it cannot verify, so a half-block
    would be offered and then fail at ingest. Better absent than broken.
    """
    item = {k: row[k] for k in
            ("id", "breed_id", "display_name", "created_at", "draft",
             "datsme_activity_id", "writeback_acked_at", "pose_count")}
    # SPEC_PET_STORE §7.2 — the declared price basis. A store-adopted pet is
    # priced by the host's flat store knob; everything else keeps the per-pose
    # formula. Declared on the item (like pose_count), so pricing stays content
    # the host maps — never a source branch in the host's engine.
    item["price_basis"] = (PRICE_BASIS_STORE_FLAT if row.get("source_store_pet_id")
                           else PRICE_BASIS_PER_POSE)
    # SPEC_PET_STORE §1.5.3 — which listing this copy came from, echoed back to
    # us in the imported notification. It rides the item rather than being
    # looked up later because a retry can arrive after this pet row is gone,
    # and that is precisely the sale the ledger must still record. NULL for a
    # designed pet, which is how the host knows there is no sale to report.
    item["source_store_pet_id"] = row.get("source_store_pet_id")
    if row["bundle_sha256"] and row["pose_count"] is not None:
        # Fresh single-use token per call: serve_bundle burns it only after a
        # SUCCESSFUL send, and the host fetches at checkout, so a re-listed page
        # simply mints new ones — a burned token never blocks a retry.
        token = secrets.token_urlsafe(16)
        db.create_bundle_token(token, row["id"], time.time() + BUNDLE_TOKEN_TTL_SEC)
        item["transfer"] = {
            # Must share our launch_base_url origin — the host's _fetch_bundle
            # pins to it and follows no redirects.
            "pointer_url": f"{_datspet_public_url()}/api/datsme/bundle/{token}",
            "sha256": row["bundle_sha256"],
            "size_bytes": row["size_bytes"],
            "content_type": "application/zip",
        }
    return item


def _imported_item_details(body: dict, item_ids: list) -> dict:
    """The optional `items` enrichment, keyed by pet id (SPEC_PET_STORE §1.5.3).

    Validated LENIENTLY on purpose. `item_ids` stays the authoritative list of
    what landed; `items` only adds the sale's price and listing id. A malformed
    entry must never turn a reporting problem into a lost acknowledgement, so
    anything unparseable is simply dropped and the sale records what it can —
    with `credits_paid` NULL, which means "unknown" and never zero.
    """
    out: dict = {}
    ids = {i for i in item_ids if isinstance(i, str)}
    for entry in body.get("items") or []:
        if not isinstance(entry, dict):
            continue
        pet_id = entry.get("id")
        if not (isinstance(pet_id, str) and pet_id in ids):
            continue          # an id we were not told landed is not a sale
        raw = entry.get("credits_charged")
        credits = raw if isinstance(raw, int) and not isinstance(raw, bool) \
            and raw >= 0 else None
        store_pet_id = entry.get("store_pet_id")
        out[pet_id] = {
            "credits_charged": credits,
            "store_pet_id": store_pet_id if isinstance(store_pet_id, str)
            and store_pet_id else None,
        }
    return out


@router.post("/partner/imported/{user_id}")
async def partner_imported(user_id: str, request: Request):
    """The host tells us it pulled these items into `user_id`'s DatsMe house
    (SPEC_DPP_DATA_TRANSFER_CHANNEL §5.5 half 2; our §3.4).

    A pull deletes the push's acknowledgment channel — in a writeback the 200 IS
    how we learn the pet landed, but in a pull we are a passive server and never
    see the outcome. Without this, `in_datsme` on the house would read false
    forever for a pulled pet.

    MUST be host-signed: this marks pets as delivered, so an unsigned caller could
    mark the whole house adopted. Verified over the EXACT raw bytes the host
    signed, then those same bytes are parsed — never re-read the stream.

    activity_id stays NULL: a pull has no activity, and inventing one would put a
    lie in the record. Nothing reads that column as "delivery owed" any more —
    purge_drafts' not_pending exemption went with the push path
    (SPEC_DATSPET_FEDERATED_SESSION §4.6 b), and an imported pet is draft=0, so no
    purge scope reaches it regardless.
    """
    raw = await request.body()
    _require_host_signature(request, raw)
    try:
        body = json.loads(raw or b"{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid JSON body")
    item_ids = body.get("item_ids")
    if not isinstance(item_ids, list):
        raise HTTPException(status_code=400, detail="item_ids required")

    details = _imported_item_details(body, item_ids)

    now = time.time()
    acked = []
    for pet_id in item_ids:
        if not (isinstance(pet_id, str) and pet_id.isalnum()):
            continue
        row = db.get_pet(pet_id)
        # Only ack a pet this user actually owns. The host is trusted, but a bug
        # there must not let one user's import stamp another user's pet.
        owned = row is not None and row["external_user_id"] == user_id
        if owned:
            db.stamp_writeback_acked(pet_id, None, now)
            acked.append(pet_id)

        # SPEC_PET_STORE §1.5.3 — the sale is recorded here because this is the
        # moment the host confirms it charged. Deliberately NOT gated on `owned`:
        # this notification is at-least-once, so a retry can arrive after the
        # buyer deleted the pet, and dropping the sale then is exactly the loss
        # the ledger exists to prevent. The listing id comes from the row when
        # it is still there and from the notification when it is not.
        store_pet_id = (row["source_store_pet_id"] if owned else None) \
            or details.get(pet_id, {}).get("store_pet_id")
        if store_pet_id:
            db.insert_store_sale(
                pet_id=pet_id, store_pet_id=store_pet_id,
                buyer_user_id=user_id,
                credits_paid=details.get(pet_id, {}).get("credits_charged"),
                sold_at=now)
    return {"acked": acked}


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
    """Always empty. Host-signed (GET, no body).

    "Pending" meant "a writeback we owe the host but never delivered", which only
    existed because DatsPet used to PUSH. In the pull model the host fetches when
    the user checks out, so a pet that was never checked out is not an owed
    delivery — it is just a pet (SPEC_DATSPET_FEDERATED_SESSION §4.6 a).

    The endpoint stays because the DPP protocol requires partners to serve it, and
    returning an empty list is what opts DatsPet out of the host's resync channel
    WITHOUT a host change. That opt-out is load-bearing, not cosmetic: the old
    query was `datsme_activity_id IS NOT NULL AND writeback_acked_at IS NULL`,
    which after the retirement describes every kept-but-unadopted pet. Left alone,
    the host would mint a resync launch for each one and re-open the push path the
    consolidation closed.
    """
    _require_host_signature(request)
    return {"pending": []}


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
