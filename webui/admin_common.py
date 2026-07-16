"""admin_common — the shared writability gate + audit line for content admins.

Extracted from motion_admin (SPEC_PET_DESIGN_AXES_ADMIN rev.2 §2: "reused by
PARAMETERIZING, not copying" — the motion version checked the *motion* dir and
MOTION_ADMIN_WRITABLE specifically). Each content admin passes its own content
directory and override env var; the policy is one place:

  - Writes are allowed on a writable/dev instance; on the deployed prod web
    tier (read-only --no-deps install, PET_GEN_BACKEND=pool) they refuse with
    409 unless the operator opts in via the override env var. Reads always work.
  - Every write logs who/op/what.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import HTTPException, Request

import datsme_integration


def writable(content_dir: Path, override_env: str) -> bool:
    if os.environ.get(override_env, "").strip() == "1":
        return True
    # Default: writable only when the content dir is actually writable on disk
    # AND we're not in pool (prod) mode. Local/dev instances author freely.
    if os.environ.get("PET_GEN_BACKEND", "local").strip().lower() == "pool":
        return False
    return os.access(content_dir, os.W_OK)


def require_writable(is_writable: bool, override_env: str, what: str) -> None:
    """Raise the 409 read-only refusal unless `is_writable`. Takes the BOOLEAN,
    not the dir — each admin passes its own (possibly test-monkeypatched)
    `_writable()` result, so the module-level seam the API tests patch keeps
    working after the extraction."""
    if not is_writable:
        raise HTTPException(
            status_code=409,
            detail=(f"this instance is read-only for {what} — author on a "
                    f"writable/dev instance and deploy (set {override_env}=1 "
                    "to override)"),
        )


def audit(tag: str, request: Request, op: str, what: str) -> None:
    who = datsme_integration.admin_user_id(request) or "unknown"
    print(f"[{tag}] {who} {op} {what}", flush=True)
