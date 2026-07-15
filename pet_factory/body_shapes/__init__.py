"""body_shapes — the body-shape vocabulary as content, not code
(SPEC_PET_DESIGNER_FLOW §7.2).

A body SHAPE (thin / normal / chubby) is a **step-2 design modifier** — it answers
"what should MY corgi look like", not "which animal am I starting from". That
placement is the whole point (§0.1): step 1 takes exactly one input, the animal, so
picking a curated base can never be invalidated by a design choice. Rev.1 of the spec
put shape in step 1 and it silently discarded the vetted base.png for an unvetted
txt2img roll — this subpackage exists in the shape it does to make that impossible.

Naming: **`body_shape`, never "body type"** — the latter is taken repo-wide for the
motion taxonomy (quadruped/avian/serpentine; SPEC_MOTION_PROFILES, tiers.json's _doc).
Two meanings for one term would confuse every future reader.

What it provides:
  - load_shapes()            — the parsed shapes.json, cached.
  - list_shapes()            — the shapes, in file order (the browser's menu).
  - default_shape_key()      — the key that means "don't change the body".
  - prompt_fragment(key)     — the words to prepend to the DESIGN string; "" for the
                               default and for anything unknown. NEVER reaches the browser.
  - is_default(key)          — True for the default key, and for empty/None/unknown.

Boundary (§7.2): this module owns the vocabulary; it never composes a prompt (the web
tier's compose_design does) and never renders (the engine does). The engine never learns
the word "fat" — it receives an opaque composed string, exactly as it already does for
colour and accessories.

Posture: pure stdlib. It is imported by the GPU-less web tier, so it must never grow an
ML dependency (CLAUDE.md; pinned by test_pool_mode_never_imports_the_ml_factory).

Never raises: an unknown key resolves to "no fragment" rather than an error, the same
posture as motion_profiles' resolution and tiers' entitlement. A typo in a request must
degrade to "normal", never 500 a design.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Optional

_DIR = Path(__file__).resolve().parent
_SHAPES_FILE = _DIR / "shapes.json"

_LOCK = threading.Lock()
_SHAPES: Optional[dict] = None


def load_shapes() -> dict:
    """The parsed shapes.json, read once and cached (it ships read-only)."""
    global _SHAPES
    if _SHAPES is None:
        with _LOCK:
            if _SHAPES is None:
                _SHAPES = json.loads(_SHAPES_FILE.read_text())
    return _SHAPES


def list_shapes() -> list[dict]:
    """Every shape, in file order — the order the browser renders them.

    Returns the public shape only: {key, label, is_default}. `prompt_fragment` is
    deliberately withheld, the same posture (and for the same reason) as the tier
    table — prompt wording is calibrated server-side content, not the browser's
    business (§7.2).
    """
    default = default_shape_key()
    return [
        {"key": s["key"], "label": s.get("label", s["key"].title()),
         "is_default": s["key"] == default}
        for s in load_shapes().get("shapes", [])
    ]


def default_shape_key() -> str:
    """The key meaning "leave the body alone"."""
    return load_shapes().get("default", "normal")


def _shape(key: Optional[str]) -> Optional[dict]:
    if not key:
        return None
    for s in load_shapes().get("shapes", []):
        if s["key"] == key:
            return s
    return None


def prompt_fragment(key: Optional[str]) -> str:
    """The words this shape contributes to the composed DESIGN string.

    "" for the default, for None/empty, and for any unknown key — so a caller can
    always prepend the result unconditionally. The default's fragment being exactly
    ""  is what makes "normal" mean "no words added" rather than "the word normal
    added", and a guard test pins it.
    """
    s = _shape(key)
    return s.get("prompt_fragment", "") if s else ""


def is_default(key: Optional[str]) -> bool:
    """True when this shape asks for no change to the body.

    Empty/None → True (the caller didn't pick), and an UNKNOWN key → True as well:
    it contributes no fragment (above), so treating it as anything else would let a
    typo claim the design was modified.
    """
    if not key:
        return True
    if _shape(key) is None:
        return True
    return key == default_shape_key()
