"""reward_delivery — telling DatsMe a user donated, and recording what it said
(SPEC_PET_STORE §10.7).

**DatsPet awards nothing.** It has no ledger, no balance and no write access to
DatsMe's. All this module does is send a signed message naming donations the
store accepted, and write down the answer. The amount is never on the request:
a partner that could name a figure could name a bigger one, so the host reads
its own knob and may decline. `capped`, `disabled` and `capability_not_granted`
are all normal answers.

**This is the first outbound call DatsPet has ever made**, and the reversal is
deliberate. The push path was retired because PET delivery is better as a pull
— bundles are megabytes, need quotes, and the host's checkout already owns
idempotency. None of that applies to a 200-byte notice that carries no bytes
and moves no pet. What survives is the rule that mattered: DatsPet still never
charges, never quotes, and never moves a pet by push.

Timing (§10.7.1): the award is EARNED at the donate click, but a writeback
needs a live launch token, so delivery rides whichever request has one — the
donate call itself when she is launched, her next launch otherwise. The
donation row is the retry queue; there is no drain tick and no scheduler.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

import db

log = logging.getLogger(__name__)

#: The wire contract (§10.7.4). Both halves of a two-repo change, so they move
#: together or not at all.
AWARD_TARGET = "user.social_award"
AWARD_SCHEMA_VERSION = "social_award.v1"
AWARD_REASON = "pet_donation"

#: One writeback per launch (the nonce burns), so a donor's owed awards travel
#: as one batch. Bounded to match the host's own per-call limit — the rest stay
#: owed and ride the launch after this one.
MAX_AWARDS_PER_BATCH = 50

#: Host outcome → the state we record. Every one of these is TERMINAL: the host
#: has answered and will not change its mind, so asking again would only annoy
#: it and could confuse a donor who was already told a number.
_OUTCOME_STATES = {
    "awarded": db.REWARD_DELIVERED,
    "duplicate": db.REWARD_DELIVERED,
    "capped": db.REWARD_CAPPED,
    "disabled": db.REWARD_DISABLED,
}


def _idempotency_key(donation_ids: list[str]) -> str:
    """Derived from the donation ids, NOT the launch jti.

    The SDK's builder defaults to the jti, which is wrong here: a retry happens
    on a LATER launch with a different jti, and the host's replay cache would
    then see a new key for the same work. Deriving it from the content makes a
    retry byte-identical to the attempt it repeats.
    """
    return "award-" + "-".join(sorted(donation_ids))


def deliver_owed_rewards(owner: Optional[str], launch_token: Optional[str],
                         *, timeout_seconds: float = 10.0) -> int:
    """Ask the host to recognise this donor's owed donations. Returns the number
    of rows settled. NEVER raises — a reward is not worth failing a page for.

    Callers pass the raw launch JWT they already hold; without one there is
    nothing to authenticate with and the rows simply stay owed.
    """
    if not owner or not launch_token:
        return 0
    try:
        owed = db.owed_donations(owner)[:MAX_AWARDS_PER_BATCH]
    except Exception as e:                       # noqa: BLE001
        log.info("reward delivery: could not read owed donations: %s", e)
        return 0
    if not owed:
        return 0

    ids = [row["id"] for row in owed]
    try:
        results = _post_awards(ids, launch_token, timeout_seconds)
    except _PermanentRefusal as e:
        # The donor revoked the capability that pays her, or the host rejected
        # the request outright. Terminal: retrying a 4xx forever is the failure
        # mode that turns a bug into a loop.
        log.info("reward delivery refused permanently (%s) — marking declined", e)
        now = time.time()
        for donation_id in ids:
            db.settle_donation_reward(donation_id, state=db.REWARD_DECLINED,
                                      points_awarded=None, settled_at=now)
        return len(ids)
    except Exception as e:                       # noqa: BLE001
        # Transient. Leave them owed; the next launch tries again.
        log.info("reward delivery deferred: %s", e)
        return 0

    now = time.time()
    settled = 0
    for entry in results:
        donation_id = entry.get("award_key")
        state = _OUTCOME_STATES.get(entry.get("outcome"))
        if not donation_id or state is None:
            continue                              # unknown verdict → stays owed
        points = entry.get("points_awarded")
        if db.settle_donation_reward(
                donation_id, state=state,
                points_awarded=points if isinstance(points, int) else None,
                settled_at=now):
            settled += 1
    return settled


class _PermanentRefusal(RuntimeError):
    """A 4xx. The host will answer the same way next time."""


def _post_awards(donation_ids: list[str], launch_token: str,
                 timeout_seconds: float) -> list[dict]:
    """Sign and POST one batch, returning the per-entry results.

    Imported lazily so this module stays importable on a box with no partner
    secret configured — the standalone posture, where nothing here ever runs.
    """
    import datsme_integration
    from datsme_partner_sdk.writeback import post_writeback

    body = {
        "launch_token": launch_token,
        "target": AWARD_TARGET,
        "target_schema_version": AWARD_SCHEMA_VERSION,
        "payload": {"awards": [{"award_key": i, "reason": AWARD_REASON}
                               for i in donation_ids]},
        "idempotency_key": _idempotency_key(donation_ids),
    }
    resp = post_writeback(
        datsme_base_url=datsme_integration._datsme_base_url(),
        partner_slug=datsme_integration.PARTNER_SLUG,
        hmac_secret=datsme_integration._hmac_secret(),
        body=body, timeout_seconds=timeout_seconds)

    if 400 <= resp.status_code < 500:
        raise _PermanentRefusal(f"HTTP {resp.status_code}: {resp.text[:200]}")
    if resp.status_code >= 500:
        raise RuntimeError(f"HTTP {resp.status_code}")
    data = resp.json()
    results = data.get("results")
    return results if isinstance(results, list) else []
