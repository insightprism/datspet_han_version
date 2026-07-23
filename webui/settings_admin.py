"""settings_admin — runtime feature-flag admin (SPEC_UPLOAD_LIKENESS §2.2, decision 6a).

A fourth admin router beside motion_admin / design_admin / ai_admin: a small typed
key/value surface over db.get_setting/set_setting for admin-toggleable flags. The
first (and today the only) flag is `upload_isolate` — subject isolation on the upload
door (Phase 3), default OFF.

Two things distinguish it from the content admins:
  - It is DB-backed, not file-backed, and has NO writability env gate — a feature flag
    must be runtime-writable without a deploy (that is the whole point of a switch).
    Admin auth (require_admin_launch) is the entire gate.
  - Only DECLARED settings (KNOWN_SETTINGS) are writable, each with a type and default,
    so this is a typed switchboard, not an open key/value from the web.

Adding a flag is one entry in KNOWN_SETTINGS plus reading it where it matters — nothing
in the engine or the renderer learns the flag exists.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

import admin_common
import datsme_integration
import db

router = APIRouter(
    prefix="/api/admin/settings",
    dependencies=[Depends(datsme_integration.require_admin_launch)],
)

# The declared switchboard. Each flag carries its type, default, and the human copy the
# Settings tab renders. Today every flag is a bool; widen SettingBody when a second type
# lands (three instances before a general type system).
KNOWN_SETTINGS: dict[str, dict] = {
    "upload_isolate": {
        "type": "bool",
        "default": False,
        "label": "Isolate the subject on uploads",
        "description": (
            "Cut the animal (or person) out of an uploaded photo before the redraw, so "
            "the img2img follows the subject and not the background. Off = today's "
            "pad-to-square. Gates both the local and pool paths; the pool param ships "
            "only when this is on (SPEC_UPLOAD_LIKENESS §2.2)."
        ),
    },
}


def _bool_default_str(key: str) -> str:
    return "true" if KNOWN_SETTINGS[key]["default"] else "false"


def bool_setting(key: str) -> bool:
    """Public read for callers (app.py): the live value of a declared bool flag,
    falling back to its declared default. An undeclared key is off — a flag nobody
    declared cannot be on."""
    meta = KNOWN_SETTINGS.get(key)
    if meta is None or meta["type"] != "bool":
        return False
    return db.get_setting(key, _bool_default_str(key)) == "true"


def _view(key: str) -> dict:
    meta = KNOWN_SETTINGS[key]
    value: object
    if meta["type"] == "bool":
        value = bool_setting(key)
    else:  # pragma: no cover - no non-bool setting yet
        value = db.get_setting(key, None)
    return {
        "key": key,
        "type": meta["type"],
        "label": meta["label"],
        "description": meta["description"],
        "value": value,
        "default": meta["default"],
    }


class SettingBody(BaseModel):
    value: bool  # every declared setting is a bool today; widen when a second type lands


@router.get("")
def list_settings():
    """Every declared flag with its live value — the Settings tab's source."""
    return {"settings": [_view(k) for k in KNOWN_SETTINGS]}


@router.put("/{key}")
def update_setting(key: str, body: SettingBody, request: Request):
    """Flip one declared flag. Unknown key → 404; a non-bool value is rejected by the
    body model (422) before it reaches here. No writability gate: a flag is meant to be
    runtime-toggled by an admin without a deploy."""
    meta = KNOWN_SETTINGS.get(key)
    if meta is None:
        raise HTTPException(404, f"unknown setting {key!r}")
    if meta["type"] != "bool":  # pragma: no cover - no non-bool setting yet
        raise HTTPException(422, f"setting {key!r} is not a boolean")
    db.set_setting(key, "true" if body.value else "false")
    admin_common.audit("settings-admin", request, "set", f"{key}={body.value}")
    return {"updated": _view(key)}
