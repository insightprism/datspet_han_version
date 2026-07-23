"""ai_admin — the DatsPet admin API for the AI engine (SPEC_DATSPET_AI_ENGINE §6).

The third admin router, following motion_admin / design_admin exactly:
`APIRouter(prefix="/api/admin/ai", dependencies=[Depends(require_admin_launch)])`,
the adm-claim cookie, `admin_common.writable()` gating, the audit line. Thin HTTP
shaping over the engine's pure-data write path (ai_purposes.admin.write_purpose)
and read layers (ai_models, ai_purposes, db.ai_usage_summary, ai_engine).

Three surfaces (§6):
  - Purpose registry — per purpose: tier, max_tokens, prompts, active. EDITABLE,
    written through the same validate_purpose the guard test uses, so the admin
    can never save what the build would reject.
  - Model catalog — READ-ONLY. A catalog edit is a code change with a guard test;
    exposing it to runtime CRUD is how the two get out of sync (§6).
  - Usage — calls / tokens / est. cost, by purpose, over a window. Cost is DERIVED
    here from ai_models.price at read time (§5), never stored.

Plus Test configuration: one real call_purpose("connectivity_check") — the whole
point of the engine/consumer split is that this path is demonstrable with zero
product features built (§3.1). The purpose key lives HERE (a caller's argument),
never in the engine (§11).
"""
from __future__ import annotations

import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

import admin_common
import ai_engine
import datsme_integration
import db
from pet_factory import ai_models
from pet_factory import ai_purposes
from pet_factory.ai_purposes import admin as ap_admin

router = APIRouter(
    prefix="/api/admin/ai",
    dependencies=[Depends(datsme_integration.require_admin_launch)],
)


def _writable() -> bool:
    return admin_common.writable(ai_purposes._DIR, "AI_ADMIN_WRITABLE")


def _require_writable() -> None:
    admin_common.require_writable(_writable(), "AI_ADMIN_WRITABLE", "AI purposes")


def _audit(request: Request, op: str, what: str) -> None:
    admin_common.audit("ai-admin", request, op, what)


def _purpose_summary(p: dict) -> dict:
    return {
        "purpose_key": p.get("purpose_key"),
        "display_name": p.get("display_name", p.get("purpose_key")),
        "description": p.get("description", ""),
        "tier": p.get("tier"),
        "max_tokens": p.get("max_tokens"),
        "input": p.get("input"),
        "is_active": bool(p.get("is_active", False)),
    }


class PurposeBody(BaseModel):
    purpose: dict  # the full <key>.json content


# ---------------------------------------------------------------------------
# Status — the tab header (is the engine configured? can we write?).
# ---------------------------------------------------------------------------
@router.get("/status")
def status():
    return {
        "available": ai_engine.is_available(),
        "writable": _writable(),
        "purpose_count": len(ai_purposes.keys()),
        "model_count": len(ai_models.list_models()),
    }


# ---------------------------------------------------------------------------
# Purposes — the editable registry (§6). Reads always work.
# ---------------------------------------------------------------------------
@router.get("/purposes")
def list_purposes():
    return {
        "writable": _writable(),
        "available": ai_engine.is_available(),
        "tiers": sorted(ai_models.tier_keys()),
        "purposes": [_purpose_summary(p) for p in ai_purposes.list_purposes()],
    }


@router.get("/purposes/{key}")
def get_purpose(key: str):
    """One purpose's full JSON (the edit form's source — prompts included; this
    gated surface is where prompt wording IS the business)."""
    if not ap_admin._KEY_RE.match(key):
        raise HTTPException(404, "purpose not found")
    p = ai_purposes.get(key)
    if p is None:
        raise HTTPException(404, "purpose not found")
    return {"purpose": p, "tiers": sorted(ai_models.tier_keys()), "writable": _writable()}


@router.put("/purposes/{key}")
def update_purpose(key: str, body: PurposeBody, request: Request):
    """Edit a purpose (tier / max_tokens / prompts / active). Written through the
    shared validator, so a save the build would reject 422s here instead."""
    _require_writable()
    if not ap_admin._KEY_RE.match(key):
        raise HTTPException(404, "purpose not found")
    try:
        entry = ap_admin.write_purpose(
            body.purpose, existing_key=key, valid_tiers=ai_models.tier_keys())
    except ap_admin.PurposeWriteError as e:
        # absent purpose → 404; a validation failure → 422 (bad input)
        if len(e.errors) == 1 and "does not exist" in e.errors[0]:
            raise HTTPException(404, e.errors[0])
        raise HTTPException(422, {"error": "validation_failed", "errors": e.errors})
    _audit(request, "wrote", f"purpose {entry['key']!r}")
    return {"updated": entry}


# ---------------------------------------------------------------------------
# Model catalog — READ-ONLY (§6). A catalog edit is a code change + guard test.
# ---------------------------------------------------------------------------
@router.get("/models")
def list_models():
    return {"models": ai_models.list_models()}


# ---------------------------------------------------------------------------
# Usage — calls / tokens / est. cost by purpose over a window (§5). Cost is
# DERIVED here from the catalog, never stored.
# ---------------------------------------------------------------------------
@router.get("/usage")
def usage(days: int = 30):
    """Per-purpose usage over the last `days` (0 = all time). Est. cost is derived
    from ai_models.price on the per-model token sums, then aggregated by purpose."""
    since = time.time() - days * 86400 if days and days > 0 else None
    rows = db.ai_usage_summary(since)
    by_purpose: dict[str, dict] = {}
    total_cost = 0.0
    for r in rows:
        cost = ai_models.price(r["model_id"], r["input_tokens"], r["output_tokens"])
        total_cost += cost
        agg = by_purpose.setdefault(r["purpose_key"], {
            "purpose_key": r["purpose_key"], "calls": 0, "ok_calls": 0,
            "error_calls": 0, "input_tokens": 0, "output_tokens": 0,
            "est_cost_usd": 0.0, "models": [],
        })
        agg["calls"] += r["calls"]
        agg["ok_calls"] += r["ok_calls"] or 0
        agg["error_calls"] += r["error_calls"] or 0
        agg["input_tokens"] += r["input_tokens"]
        agg["output_tokens"] += r["output_tokens"]
        agg["est_cost_usd"] = round(agg["est_cost_usd"] + cost, 6)
        if r["model_id"] not in agg["models"]:
            agg["models"].append(r["model_id"])
    return {
        "days": days,
        "total_cost_usd": round(total_cost, 6),
        "purposes": list(by_purpose.values()),
    }


# ---------------------------------------------------------------------------
# Test configuration — one real connectivity_check call (§3.1). Always 200: the
# admin renders the reason on a degrade rather than showing an error page.
# ---------------------------------------------------------------------------
@router.post("/test")
def test_configuration(request: Request):
    _audit(request, "ran", "connectivity test")
    try:
        result, usage = ai_engine.call_purpose("connectivity_check")
    except ai_engine.AIUnavailable as e:
        return {"ok": False, "kind": "unavailable", "reason": str(e)}
    except ai_engine.AIError as e:
        return {"ok": False, "kind": "error", "reason": str(e)}
    return {
        "ok": True,
        "model": usage.model_id,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "est_cost_usd": ai_models.price(usage.model_id, usage.input_tokens, usage.output_tokens),
        "result": result,
    }
