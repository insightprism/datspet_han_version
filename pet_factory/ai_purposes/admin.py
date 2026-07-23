"""ai_purposes.admin — the WRITE path for the purpose registry
(SPEC_DATSPET_AI_ENGINE §6).

The read path lives in `__init__.py` (get/list_purposes, cached). This module is
the mutation side the admin surface uses: validate a purpose against the exact
guard-test contract, then write the file and bust the in-memory cache. Pure data,
no ML — imports on the GPU-less web tier like the rest of the package, and imports
NOTHING from a consumer (the seam, §11).

Boundary (§0.2, mirroring design_axes.admin): `validate_purpose` is the SINGLE
definition of "a valid purpose" — the guard test (tests/test_ai_purposes.py) and
the admin endpoint both call it, so the admin can never save a purpose the build
would reject: an unknown tier, a non-positive max_tokens, an output_schema using a
keyword structured outputs silently ignores (§11 — a false guarantee is worse than
none), an undeclared prompt placeholder that would ship the literal `{hint_clause}`
to the model.

The tier vocabulary is passed IN (`valid_tiers`) rather than imported, exactly as
design_axes.admin takes `registry`: it keeps ai_purposes/ from importing ai_models,
so the two engine halves stay independently importable. The admin router and the
guard test both source it from `ai_models.tier_keys()`.

The admin EDITS existing purposes only (tier / max_tokens / prompts / active — §6).
A purpose is CONTRIBUTED as a file by a consuming feature (§0.1), not created in the
admin; so there is no create/delete here, only write_purpose(existing_key=…).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from . import _DIR, _LOCK, reload as _reload_cache

# A purpose key becomes a filename AND a URL path segment — the same conservative
# slug the other registries use.
_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")

VALID_INPUTS = {"text", "image"}

# Keywords structured outputs ACCEPTS: type/enum/const/required, additionalProperties
# (=false), $ref/$def/anyOf/allOf, and string `format`. The API silently IGNORES the
# numeric, string-length, and array-length constraints below — so a purpose author
# who writes `"minimum": 0` gets a bound the model will not honor. The validator
# REJECTS them rather than ship a false guarantee (§11). This bites the deferred
# likeness_score scorer's 0–100 integers, not the captioner's string/enum output.
_BANNED_SCHEMA_KEYWORDS = {
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
    "minLength", "maxLength", "minItems", "maxItems", "uniqueItems",
}

_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


class _SafeDict(dict):
    """format_map helper: a missing key renders as the literal {key} rather than
    raising — the same posture the engine's template fill uses, so validation
    sees exactly what the engine would."""
    def __missing__(self, key):
        return "{" + key + "}"


def _template_errors(field: str, text: str, declared: set[str]) -> list[str]:
    """Errors for one prompt template: malformed braces, and any placeholder not
    declared in template_vars (the §11 guard — an undeclared placeholder is one
    that would silently ship as the literal `{hint_clause}`)."""
    errors: list[str] = []
    if not isinstance(text, str) or not text.strip():
        return [f"{field} is required and must be a non-empty string"]
    try:
        text.format_map(_SafeDict())  # catches unbalanced / malformed braces
    except (ValueError, IndexError) as e:
        errors.append(f"{field} has malformed template braces: {e}")
        return errors
    used = set(_PLACEHOLDER_RE.findall(text))
    undeclared = used - declared
    if undeclared:
        errors.append(
            f"{field} uses undeclared placeholder(s) {sorted(undeclared)} — declare "
            "them in template_vars (the caller must supply every one, or the model "
            "receives the literal braces)"
        )
    return errors


def _schema_errors(schema, path: str = "output_schema") -> list[str]:
    """Recursively validate a purpose's output_schema against the structured-output
    contract: object nodes carry additionalProperties:false, and NO node uses a
    keyword the API silently ignores."""
    errors: list[str] = []
    if not isinstance(schema, dict):
        return [f"{path} must be an object"]
    banned = _BANNED_SCHEMA_KEYWORDS & set(schema.keys())
    for kw in sorted(banned):
        errors.append(
            f"{path} uses {kw!r}, which structured outputs silently ignores — remove "
            "it (the model will not honor the bound; §11)"
        )
    if schema.get("type") == "object":
        if schema.get("additionalProperties") is not False:
            errors.append(f"{path} is an object and must set additionalProperties: false")
        props = schema.get("properties")
        if not isinstance(props, dict):
            errors.append(f"{path} object needs a properties map")
        else:
            for name, sub in props.items():
                errors.extend(_schema_errors(sub, f"{path}.properties.{name}"))
        if not isinstance(schema.get("required"), list):
            errors.append(f"{path} object needs a required list")
    if schema.get("type") == "array":
        items = schema.get("items")
        if isinstance(items, dict):
            errors.extend(_schema_errors(items, f"{path}.items"))
    for key in ("anyOf", "allOf", "oneOf"):
        for i, sub in enumerate(schema.get(key, []) or []):
            errors.extend(_schema_errors(sub, f"{path}.{key}[{i}]"))
    return errors


def validate_purpose(
    raw: dict,
    *,
    valid_tiers: set,
    existing_key: Optional[str] = None,
) -> list[str]:
    """Return a list of human-readable errors for a candidate purpose (empty =
    valid). The EXACT contract the guard test asserts — the one definition of
    "valid", shared by the test and the admin endpoint (§0.2, §11).

    `valid_tiers`: the catalog's tier vocabulary (ai_models.tier_keys()), passed
    in so this module need not import ai_models.
    """
    errors: list[str] = []

    key = raw.get("purpose_key")
    if not isinstance(key, str) or not _KEY_RE.match(key):
        errors.append(
            f"purpose_key must match {_KEY_RE.pattern!r} (lowercase, digits, underscore) — got {key!r}"
        )

    for field in ("display_name", "description"):
        if not isinstance(raw.get(field), str) or not raw[field].strip():
            errors.append(f"{field} is required and must be a non-empty string")

    tier = raw.get("tier")
    if tier not in valid_tiers:
        errors.append(f"tier must be one of {sorted(valid_tiers)} — got {tier!r}")

    mt = raw.get("max_tokens")
    if isinstance(mt, bool) or not isinstance(mt, int) or mt <= 0:
        errors.append(f"max_tokens must be a positive integer — got {mt!r}")

    if raw.get("input") not in VALID_INPUTS:
        errors.append(f"input must be one of {sorted(VALID_INPUTS)} — got {raw.get('input')!r}")

    tvars = raw.get("template_vars", [])
    if not isinstance(tvars, list) or not all(isinstance(v, str) for v in tvars):
        errors.append("template_vars must be a list of strings (the placeholders the caller supplies)")
        tvars = []
    declared = set(tvars)

    errors.extend(_template_errors("system_prompt", raw.get("system_prompt"), declared))
    errors.extend(_template_errors("user_prompt_template", raw.get("user_prompt_template"), declared))

    if "output_schema" not in raw:
        errors.append("output_schema is required (structured outputs declare the shape)")
    else:
        schema = raw["output_schema"]
        if not isinstance(schema, dict) or schema.get("type") != "object":
            errors.append("output_schema must be an object schema (type: object)")
        errors.extend(_schema_errors(schema))

    if not isinstance(raw.get("is_active"), bool):
        errors.append("is_active must be a boolean")

    if not isinstance(raw.get("_doc"), str) or not raw["_doc"].strip():
        errors.append("_doc is required — content files carry their own rationale")

    return errors


# ---------------------------------------------------------------------------
# Write primitive. Validates, mutates the file, then busts the loader cache so
# the change is live immediately. Edit-only: purposes are contributed as files
# by features (§0.1), so there is no create/delete here.
# ---------------------------------------------------------------------------
class PurposeWriteError(ValueError):
    """A write refused for a content reason. `errors` carries the validate_purpose
    list when the cause was validation; else a single message."""

    def __init__(self, message: str, errors: Optional[list[str]] = None):
        super().__init__(message)
        self.errors = errors or [message]


def load_registry() -> dict:
    """The raw registry.json (re-read from disk each call — the admin needs the
    live on-disk state, not the cached copy)."""
    return json.loads((_DIR / "registry.json").read_text())


def _registry_keys(registry: dict) -> list[str]:
    return [e["key"] for e in registry.get("purposes", []) if e.get("key")]


def _purpose_file(key: str) -> Path:
    return _DIR / f"{key}.json"


def write_purpose(raw: dict, *, existing_key: str, valid_tiers: set) -> dict:
    """Validate + write an EXISTING purpose's file (tier / max_tokens / prompts /
    active edits, §6), then reload the cache. `existing_key` must already be
    registered; the key is immutable (a purpose is a contributed file, not renamed
    in the admin). Returns {key}. Raises PurposeWriteError otherwise."""
    with _LOCK:
        registry = load_registry()
        keys = _registry_keys(registry)
        key = raw.get("purpose_key")

        errs = validate_purpose(raw, valid_tiers=valid_tiers, existing_key=existing_key)
        if errs:
            raise PurposeWriteError("purpose failed validation", errs)

        if existing_key not in keys:
            raise PurposeWriteError(f"purpose {existing_key!r} does not exist")
        if key != existing_key:
            raise PurposeWriteError(
                f"purpose_key is immutable here (got {key!r}, editing {existing_key!r}); "
                "a purpose is contributed as a file, not renamed in the admin"
            )

        tmp = _purpose_file(key).with_suffix(".json.tmp")
        tmp.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n")
        tmp.replace(_purpose_file(key))

    _reload_cache()
    return {"key": key}
