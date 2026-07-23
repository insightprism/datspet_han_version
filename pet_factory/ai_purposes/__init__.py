"""ai_purposes — the AI purpose registry as content, not code
(SPEC_DATSPET_AI_ENGINE §3).

One JSON per purpose plus a `registry.json` naming them — the design_axes pattern,
applied to prompts. Each purpose owns its own model *tier*, prompts, params, and
output schema, so configuring an AI usage is a data edit, never an engine change.
Pure stdlib: importable on the GPU-less web tier with no ML dependency and no
migration (the tiers/ precedent — data, not a DB table).

What it provides:
  - load()               — registry.json + every registered purpose file, cached.
  - list_purposes()      — every purpose (the admin's editable Purpose registry).
  - get(purpose_key)     — one purpose's full config, or None (the engine reads
                           this to build a call).
  - keys()               — the registered purpose keys.

Boundary (§0.1): a purpose carries a *tier string*, not a pinned model id — the
engine resolves the tier through ai_models at call time (a model swap stays one
edit in the catalog). This package therefore imports NOTHING else: not ai_models,
not a consumer. Cross-layer validity (does the tier resolve? does an image purpose
resolve to a vision model?) is a guard test's job (tests/test_ai_purposes.py), not
a runtime import — the same discipline animal_catalog uses for motion-profile keys.

Never raises: an unknown purpose key resolves to None, and a registry entry whose
file is missing is skipped at runtime and FAILS THE BUILD in test_ai_purposes.py.
Runtime resilience is not permission to ship a half-formed entry.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Optional

_DIR = Path(__file__).resolve().parent

_LOCK = threading.Lock()
_CACHE: Optional[dict] = None


def load() -> dict:
    """registry.json + every registered purpose file, read once and cached (they
    ship read-only). Paths resolve from _DIR at CALL time, not import time, so the
    admin tests' monkeypatched temp dir governs every read."""
    global _CACHE
    if _CACHE is None:
        with _LOCK:
            if _CACHE is None:
                registry = json.loads((_DIR / "registry.json").read_text())
                order: list[str] = []
                purposes: dict[str, dict] = {}
                for entry in registry.get("purposes", []):
                    key = entry.get("key")
                    if not key:
                        continue
                    path = _DIR / f"{key}.json"
                    if not path.is_file():
                        # Runtime degrades (never-raises); the build does not —
                        # the guard test asserts file↔registry parity.
                        continue
                    purposes[key] = json.loads(path.read_text())
                    order.append(key)
                _CACHE = {"registry": registry, "purposes": purposes, "order": order}
    return _CACHE


def reload() -> None:
    """Drop the in-memory cache so the next read re-reads disk. Called by the
    admin write path (ai_purposes.admin) after a successful purpose edit so the
    engine and the admin list reflect the change with no restart."""
    global _CACHE
    with _LOCK:
        _CACHE = None


def keys() -> list[str]:
    """The registered purpose keys, in registry order."""
    return list(load()["order"])


def list_purposes() -> list[dict]:
    """Every purpose's full config, in registry order. The admin surface is
    gated, so it edits the full shape (prompts included) — unlike the browser,
    which never sees a purpose at all."""
    data = load()
    return [data["purposes"][k] for k in data["order"]]


def get(purpose_key: str) -> Optional[dict]:
    """One purpose's full config by key, or None for an unknown key (never
    raises). The engine calls this, then raises its own typed error on None."""
    return load()["purposes"].get(purpose_key)
