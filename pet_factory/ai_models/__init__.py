"""ai_models — the AI model catalog as content, not code (SPEC_DATSPET_AI_ENGINE §2).

A data subpackage beside `tiers/` and `design_axes/`: one `catalog.json` of model
facts plus this pure-stdlib read layer. Importable with NO ML dependency, so the
GPU-less web tier (`webui/ai_engine.py`) reads it freely — the same posture the
other four registries established.

What it provides:
  - load_catalog()          — the parsed catalog.json, validated on first read, cached.
  - list_models()           — every entry (the admin's read-only Model catalog table).
  - entry(model_id)         — one model's facts, or None.
  - resolve(tier)           — the AVAILABLE model a tier resolves to, via
                              `default_for_tiers`. A purpose asks for a tier; the
                              catalog answers with the current model (§3/§6).
  - price(model_id, in, out) — the derived USD cost of a call, from `cost_per_mtok`.
                              Cost is NEVER stored (§5) — a stored price freezes at
                              call time; deriving it keeps a pricing correction fixable.
  - tier_keys()             — the closed tier vocabulary (what a purpose's `tier`
                              must be one of); passed to the purpose validator so
                              ai_purposes/ need not import this package.

Boundary (§0.1): the engine owns the model catalog + this read layer; it never
imports a consumer, never mentions a species, and has no opinion about pets. A
feature contributes purpose files (ai_purposes/); it never touches this catalog.

Self-validating (§0/§2): `validate_catalog` is the single definition of a valid
catalog — the guard test (tests/test_ai_models.py) and this loader both call it.
The spec asks the catalog to "validate itself at import time … a malformed catalog
raises CatalogError and the app refuses to start." This repo's other registries
validate lazily (first access), so — reconciling the two — validation runs on the
FIRST `load_catalog()`, cached thereafter: a malformed catalog raises CatalogError
the moment anything touches the engine, while unrelated imports stay cheap. The
real catalog is valid, so this never fires in practice; a bad edit is caught by the
build guard long before deploy.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Optional

_DIR = Path(__file__).resolve().parent
_CATALOG_FILE = _DIR / "catalog.json"

_LOCK = threading.Lock()
_CATALOG: Optional[dict] = None

# Closed sets — the guard test and the loader both enforce membership.
PROVIDERS = {"anthropic", "google", "openai"}
TIERS = {"fast", "balanced", "capable"}
STATUSES = {"draft", "available", "deprecated", "retired"}


class CatalogError(RuntimeError):
    """The catalog is malformed. Raised on first read (and by the guard test's
    validator) so a bad entry can never price a call — it stops the engine cold."""

    def __init__(self, message: str, errors: Optional[list[str]] = None):
        super().__init__(message)
        self.errors = errors or [message]


def validate_catalog(data: dict) -> list[str]:
    """Return a list of human-readable errors for a candidate catalog (empty =
    valid). The single definition of "valid", shared by the guard test and the
    loader (§2, catalog rules 1–5; rules 6–7 are cross-layer and live in the
    purpose guard, which is where purposes are known)."""
    errors: list[str] = []

    models = data.get("models")
    if not isinstance(models, list) or not models:
        return ["models must be a non-empty list"]

    ids: set[str] = set()
    available_defaults: dict[str, list[str]] = {}  # tier -> [model ids claiming it]

    for m in models:
        if not isinstance(m, dict):
            errors.append(f"model {m!r} must be an object")
            continue
        mid = m.get("id")
        if not isinstance(mid, str) or not mid.strip():
            errors.append(f"every model needs a non-empty string id — got {mid!r}")
            continue
        # Rule 1: ids unique; provider/tier/status in their closed sets.
        if mid in ids:
            errors.append(f"duplicate model id {mid!r}")
        ids.add(mid)
        if m.get("provider") not in PROVIDERS:
            errors.append(f"{mid}: provider must be one of {sorted(PROVIDERS)} — got {m.get('provider')!r}")
        if m.get("tier") not in TIERS:
            errors.append(f"{mid}: tier must be one of {sorted(TIERS)} — got {m.get('tier')!r}")
        status = m.get("status")
        if status not in STATUSES:
            errors.append(f"{mid}: status must be one of {sorted(STATUSES)} — got {status!r}")
        if not isinstance(m.get("vision"), bool):
            errors.append(f"{mid}: vision must be a boolean")

        # Rule 5: cost_per_mtok present and positive on EVERY entry — a usage row
        # must always price, so even a retired model carries live rates.
        cost = m.get("cost_per_mtok")
        if not isinstance(cost, dict):
            errors.append(f"{mid}: cost_per_mtok must be an object with input+output")
        else:
            for k in ("input", "output"):
                v = cost.get(k)
                if isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0:
                    errors.append(f"{mid}: cost_per_mtok.{k} must be a positive number — got {v!r}")

        # Rule 2: only status "available" may appear in default_for_tiers.
        dft = m.get("default_for_tiers", [])
        if not isinstance(dft, list):
            errors.append(f"{mid}: default_for_tiers must be a list")
            dft = []
        for tier in dft:
            if tier not in TIERS:
                errors.append(f"{mid}: default_for_tiers names unknown tier {tier!r}")
                continue
            if status != "available":
                errors.append(f"{mid}: only an available model may be a default for {tier!r} (status={status!r})")
            available_defaults.setdefault(tier, []).append(mid)

        # Rule 4: deprecated/retired MUST carry a replacement_id that resolves.
        if status in ("deprecated", "retired"):
            rep = m.get("replacement_id")
            if not isinstance(rep, str) or not rep.strip():
                errors.append(f"{mid}: {status} models must carry a replacement_id")
            # resolution checked in the second pass below (needs all ids)

    # Second pass — replacement_id resolves to a known id.
    for m in models:
        if isinstance(m, dict) and m.get("status") in ("deprecated", "retired"):
            rep = m.get("replacement_id")
            if isinstance(rep, str) and rep.strip() and rep not in ids:
                errors.append(f"{m.get('id')!r}: replacement_id {rep!r} names no model in the catalog")

    # Rule 3: every tier in the closed set has EXACTLY ONE available default, so
    # resolve(tier) is total (a purpose that names a tier always resolves — §4).
    for tier in sorted(TIERS):
        claimers = available_defaults.get(tier, [])
        if len(claimers) == 0:
            errors.append(f"tier {tier!r} has no available default model")
        elif len(claimers) > 1:
            errors.append(f"tier {tier!r} has more than one default: {claimers}")

    return errors


def load_catalog() -> dict:
    """The parsed catalog.json, validated on FIRST read and cached (it ships
    read-only). A malformed catalog raises CatalogError here (§0)."""
    global _CATALOG
    if _CATALOG is None:
        with _LOCK:
            if _CATALOG is None:
                # Read at CALL time (not import) so a test's monkeypatched
                # _CATALOG_FILE governs the read, like the other registries.
                data = json.loads(_CATALOG_FILE.read_text())
                errs = validate_catalog(data)
                if errs:
                    raise CatalogError("ai model catalog is malformed", errs)
                _CATALOG = data
    return _CATALOG


def reload() -> None:
    """Drop the in-memory cache so the next read re-reads (and re-validates) disk.
    The catalog is admin-READ-ONLY (§6), so nothing in the app calls this; it
    exists for the test harness, mirroring the other registries' reload()."""
    global _CATALOG
    with _LOCK:
        _CATALOG = None


def list_models() -> list[dict]:
    """Every model entry, catalog order — the admin's read-only Model catalog."""
    return load_catalog().get("models", [])


def entry(model_id: str) -> Optional[dict]:
    """One model's facts by id, or None. Used to price historical usage rows and
    to answer the admin's catalog table."""
    return next((m for m in list_models() if m.get("id") == model_id), None)


def tier_keys() -> set[str]:
    """The closed tier vocabulary a purpose's `tier` must be one of. Passed to the
    purpose validator so ai_purposes/ never imports this package (the seam, §11)."""
    return set(TIERS)


def resolve(tier: str) -> dict:
    """The AVAILABLE model a tier resolves to, via `default_for_tiers`. A purpose
    asks for a tier; the catalog answers with the current model (§3/§6). Raises
    CatalogError for a tier with no available default — the purpose guard test
    (rule 6) makes that unreachable at runtime, so this is defensive, not a path."""
    for m in list_models():
        if m.get("status") == "available" and tier in (m.get("default_for_tiers") or []):
            return m
    raise CatalogError(f"no available model resolves tier {tier!r}")


def price(model_id: str, input_tokens: int, output_tokens: int) -> float:
    """The derived USD cost of a call from the catalog's `cost_per_mtok` (dollars
    per MILLION tokens). Cost is derived at read time, never stored (§5). A model
    absent from the catalog prices at 0.0 — rule 5 keeps deprecated/retired
    entries so this is unreachable for any id the engine ever wrote, but a since
    fully-removed id degrades to unpriced rather than raising on a usage read."""
    m = entry(model_id)
    if not m:
        return 0.0
    cost = m.get("cost_per_mtok", {})
    in_rate = float(cost.get("input", 0.0))
    out_rate = float(cost.get("output", 0.0))
    return (input_tokens / 1_000_000) * in_rate + (output_tokens / 1_000_000) * out_rate
