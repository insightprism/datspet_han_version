"""Who owns a row — the ONE door to caller identity (SPEC_DATSPET_FEDERATED_SESSION §4.5).

Every pet, reference and job carries an owner. This module decides what that owner
is for a given request, mints the anonymous one when there is no DatsMe identity
yet, and moves everything one anonymous owner holds onto a real user at sign-in.

Why it is its own module rather than part of datsme_integration.py: the claim sweep
runs inside `launch()` (datsme_integration) and must reach the *reference* store
(app.py), and app.py already imports datsme_integration. Putting the sweep in either
one is a circular import. What lives here — the anon cookie, the resolver, the
exclusion set, the claim registry — all changes for the same reason, and both
modules import it. The webui/ layering stays one-directional.

THREE OWNER STATES, and the difference between two of them is load-bearing:

    standalone   DATSME_HMAC_SECRET unset. owner_id is None, rows are NULL, and
                 nothing here does anything. Today's single-user local box.
    active       A launch cookie whose token verifies → the DatsMe user_id.
    anonymous    Integrated, no launch cookie → "anon:<uuid4>", carried in an
                 httponly cookie so it is per-BROWSER, not one shared pool.
    stale        A launch cookie that no longer verifies. NOT anonymous — see below.

`resolve_launch_identity` used to collapse "no cookie" and "stale cookie" into
None, and that collapse was a live defect: at minute 61 a signed-in user's next pet
was written into the anonymous scope, where (before the exact-match fix) every other
signed-in user could see and claim it. A stale cookie now raises 401 session_stale
and the browser renews (§4.2/§4.7); it never silently downgrades.
"""

from __future__ import annotations

import os
import uuid
from typing import Callable, NamedTuple, Optional

from fastapi import HTTPException, Request

# The anonymous owner id is an opaque per-browser SCOPING value — not an identity.
# It authenticates nobody, grants nothing, and selects rows and nothing else. The
# prefix keeps that legible in the database and makes `claimable` a property of the
# value rather than a nullability accident.
ANON_OWNER_PREFIX = "anon:"
ANON_COOKIE = "datspet_anon"
# Only has to outlive one anonymous design session; 30 days matches the host's own
# sliding window, so a returning anonymous visitor still finds their pets.
ANON_COOKIE_TTL_SEC = 30 * 24 * 60 * 60

# Server-to-server surfaces: no browser, so no Set-Cookie. NAMED because the set is
# not derivable from one prefix — the bundle fetch is the DatsMe host's own HTTP
# client calling an /api/datsme/ path, not a /partner/ one.
NO_COOKIE_PREFIXES = ("/partner/", "/api/datsme/bundle/")

# The error code the frontend branches on (§4.7). A structured code, never a message
# match: a client that string-matches an error breaks when the copy is edited.
SESSION_STALE_CODE = "session_stale"


class OwnerScope(NamedTuple):
    """The caller's resolved owner, and whether their launch cookie went stale.

    owner_id is None ONLY in standalone mode. In integrated mode it is either the
    DatsMe user_id or this browser's anon id — never None, so a write always lands
    in a scope somebody can reach.
    """
    owner_id: Optional[str]
    is_stale: bool = False

    @property
    def is_anonymous(self) -> bool:
        return is_anon_owner(self.owner_id)


def is_anon_owner(owner_id: Optional[str]) -> bool:
    """True for a per-browser anonymous owner. The bool() guard is not noise: on a
    standalone box every owner is None and a bare .startswith is an AttributeError
    on the house's main read path."""
    return bool(owner_id) and owner_id.startswith(ANON_OWNER_PREFIX)


def _mint_anon_owner_id() -> str:
    return ANON_OWNER_PREFIX + uuid.uuid4().hex


def _is_integrated() -> bool:
    """Whether a DatsMe host is configured. Local import keeps this module free of
    an import-time dependency on datsme_integration (which imports app-level things)."""
    return bool(os.environ.get("DATSME_HMAC_SECRET", "").strip())


def resolve_owner_scope(request: Request) -> OwnerScope:
    """The caller's owner scope. PURE — reads, never mints (the middleware mints).

    Order matters: a launch cookie always wins over an anon cookie, because after
    sign-in the browser holds BOTH (the anon cookie is deliberately kept until
    sign-out so a late-arriving row can still be swept — see claim_anon_owner).
    """
    if not _is_integrated():
        return OwnerScope(None, False)

    import datsme_integration as dpp

    cookie = dpp._read_launch_cookie(request)
    if cookie is not None:
        user_id = dpp.verified_launch_user_id(cookie)
        if user_id is not None:
            return OwnerScope(user_id, False)
        # Present but unverifiable. NOT anonymous — that is the §0.7 defect.
        return OwnerScope(None, True)

    anon = request.cookies.get(ANON_COOKIE)
    if is_anon_owner(anon):
        return OwnerScope(anon, False)
    # Minted by the middleware for THIS request; the cookie lands on the response.
    return OwnerScope(getattr(request.state, "anon_owner_id", None), False)


def require_owner(request: Request) -> Optional[str]:
    """The caller's owner id, or 401 session_stale if their launch cookie lapsed.

    The dependency every JSON endpoint uses. Image endpoints deliberately do NOT
    (§4.7): <img> has no 401 handler, so they keep their 404 posture and let the
    page's next JSON call be what triggers the renewal.
    """
    scope = resolve_owner_scope(request)
    if scope.is_stale:
        raise HTTPException(401, {
            "code": SESSION_STALE_CODE,
            "message": "Your DatsMe session needs refreshing — reloading will restore it.",
        })
    return scope.owner_id


async def anon_owner_middleware(request: Request, call_next):
    """Mint the per-browser anonymous owner id, once, on the first request that
    could need one.

    Middleware and NOT an injected `Response` parameter, for a reason that is easy
    to get wrong: FastAPI merges cookies set on an injected Response only when the
    handler returns a NON-Response value. A handler returning a raw FileResponse
    silently drops them — and /api/reference/{id}.png is owner-scoped AND returns a
    raw FileResponse. An <img> load would mint an id, lose the cookie, and the next
    request would mint a different one, orphaning the reference and every pet built
    from it. Middleware sets the cookie on the real outgoing response whatever its
    type.
    """
    minted = None
    if (_is_integrated()
            and not request.url.path.startswith(NO_COOKIE_PREFIXES)
            and not _has_launch_cookie(request)
            and not is_anon_owner(request.cookies.get(ANON_COOKIE))):
        minted = _mint_anon_owner_id()
        request.state.anon_owner_id = minted

    response = await call_next(request)

    # A Set-Cookie on a publicly cacheable response is a SHARED anonymous identity
    # the moment anything caches it. Checked on the RESPONSE rather than a path
    # list, so a new cacheable endpoint is excluded automatically instead of by
    # somebody remembering to. (The pet-asset headers already reason this way:
    # _IMMUTABLE_ASSET_CACHE is `private` so a shared proxy can never serve one
    # user's pet to another.)
    if minted and "public" not in response.headers.get("cache-control", "").lower():
        from datsme_integration import LAUNCH_COOKIE_SAMESITE, LAUNCH_COOKIE_SECURE
        response.set_cookie(
            key=ANON_COOKIE, value=minted, max_age=ANON_COOKIE_TTL_SEC,
            httponly=True, samesite=LAUNCH_COOKIE_SAMESITE, secure=LAUNCH_COOKIE_SECURE,
        )
    return response


def _has_launch_cookie(request: Request) -> bool:
    from datsme_integration import LAUNCH_COOKIE
    return LAUNCH_COOKIE in request.cookies


# ---------------------------------------------------------------------------
# The claim sweep — everything one anonymous owner holds, moved at once
# ---------------------------------------------------------------------------
# A claim handler moves rows from one owner to another and returns how many it
# moved. Each owner-stamping module registers its own at import; adding another
# owner-stamped store is ONE registration, not an edit to claim_anon_owner. Three
# concrete stores exist today (pets, jobs, references), which is what makes the
# registry earned rather than speculative.
#
# `ai_usage` carries an external_user_id too and is DELIBERATELY not registered.
# It is an append-only ledger — "a re-run is a NEW row, never an UPDATE" — and a
# claim handler would rewrite history to make cost attribution tidier. Anonymous
# AI spend stays attributed to the anon id that incurred it. Do not "complete" the
# registry by adding it.
ClaimHandler = Callable[[str, str, Optional[str]], int]
_CLAIM_HANDLERS: list[tuple[str, ClaimHandler]] = []


def register_claim_handler(store: str, handler: ClaimHandler) -> None:
    """Register a store's owner-reassignment handler. Idempotent per store name so
    a re-imported module cannot double-register."""
    for i, (name, _) in enumerate(_CLAIM_HANDLERS):
        if name == store:
            _CLAIM_HANDLERS[i] = (store, handler)
            return
    _CLAIM_HANDLERS.append((store, handler))


def claim_anon_owner(from_owner: Optional[str], to_owner: str,
                     activity_id: Optional[str] = None) -> dict:
    """Move everything an anonymous owner holds onto a real DatsMe user.

    Runs at LAUNCH (the moment the browser gains a DatsMe identity), not at
    hand-off: doing it there means the house, the designer and every other surface
    inherit it without repeating the step, and the user's in-flight work survives
    signing in halfway through it.

    Keyed by OWNER, never by a list of pet ids — at launch there is no list, and two
    of the three stores are not pets. A no-op (0 rows everywhere) is the normal case
    for a user who signed in before designing anything.
    """
    if not is_anon_owner(from_owner) or not to_owner or from_owner == to_owner:
        return {}
    moved = {}
    for store, handler in _CLAIM_HANDLERS:
        try:
            moved[store] = handler(from_owner, to_owner, activity_id)
        except Exception as e:  # one store's failure must not strand the others
            print(f"[owner_scope] claim handler {store!r} failed: {e}", flush=True)
            moved[store] = 0
    return moved
