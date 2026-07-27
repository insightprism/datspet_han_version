"""ai_engine — the one dispatch path for DatsPet AI calls (SPEC_DATSPET_AI_ENGINE §4).

`call_purpose(purpose_key, …)` resolves the purpose → resolves its tier through the
model catalog → fills the prompt templates → calls Anthropic with structured outputs
→ records a usage row → returns the validated object. It mirrors DatsMe's
`call_ai_purpose_with_usage` shape (purpose key in, (result, usage) out) at DatsPet's
scale.

Web tier only (CLAUDE.md's GPU-less posture): no GPU, no ML packages, one HTTPS call.
`anthropic`/`httpx` are imported LAZILY inside `_call_model`, so importing this module
costs nothing and needs no ML stack — and the tests monkeypatch `_call_model` to run
the whole dispatch/record/return path with no network and no `anthropic` installed.
`pool_client.py` is the precedent: one adapter that owns one backend's calls, with its
own typed errors.

Standalone-first (the `datsme_integration` posture): with `DATSPET_AI_API_KEY` unset
the whole engine is inert — `call_purpose` raises `AIUnavailable`, which every caller
degrades on. The value is the platform's Anthropic key, copied into the gitignored
`pet_env.local.sh` under DatsPet's own name (§4/§16).

Two corrections this engine bakes in versus DatsMe (§1): NO `temperature` (it 400s on
every current model), and structured outputs via `output_config.format` instead of
prompt-and-parse (the schema lives on the purpose, and the API guarantees the shape).

The seam (§11): this module names NO purpose key. Every key reaching it is a caller's
argument — a literal purpose key here would re-couple what §0.1 separated, and the
guard test (webui/tests/test_ai_engine.py) fails the build on one.
"""
from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass
from typing import Optional

import db
from pet_factory import ai_models, ai_purposes

API_KEY_ENV = "DATSPET_AI_API_KEY"

# Thinking is sent EXPLICITLY on every call rather than left to the model's default.
# A purpose's `max_tokens` budgets its JSON ANSWER (32 tokens for a profile key), but
# on a thinking-by-default model it caps thinking + answer TOGETHER: the model spends
# the whole budget reasoning, returns an empty text block, and the JSON parse fails.
# That reads as a model failure and degrades silently to each caller's fallback — so
# flipping one purpose's `tier` from "fast" to "balanced" could downgrade it to its
# offline path with nothing in the logs to say so. Declaring it here means a tier or
# catalog edit cannot change what `max_tokens` means. Measured against every model in
# ai_models/catalog.json: all accept it.
THINKING_DISABLED = {"type": "disabled"}

# `stop_reason` when the model ran out of `max_tokens` mid-answer. A truncated reply is
# a normal 200 carrying a fragment — nothing raises on its own, which is exactly how
# this stayed invisible. Checking it is what makes truncation loud.
STOP_REASON_TRUNCATED = "max_tokens"


class AIUnavailable(RuntimeError):
    """The engine cannot serve this call right now: the API key is unset, or the
    purpose is switched off. Callers DEGRADE on this (the standalone-first
    posture) — it is not a bug, it is "the AI path is not available"."""


class AIError(RuntimeError):
    """A call was attempted and failed: an unknown purpose key, a bad image
    contract, an API error, or output that was not valid JSON. Distinct from
    AIUnavailable — this is a real failure a caller surfaces, not a degrade."""


class AITruncated(AIError):
    """The model hit `max_tokens` before finishing its JSON, so the answer is a
    fragment rather than an object. A SUBCLASS of AIError so every caller that
    already degrades keeps degrading unchanged — what it adds is a name in the
    ai_usage ledger's `error_code` and a message naming the knob to turn, instead
    of a bare JSONDecodeError that blames the model for the budget.

    It carries the tokens the call really billed: a truncated call is a PAID call,
    and the ledger must not record it as zero (§5)."""

    def __init__(self, message: str, *, input_tokens: int = 0, output_tokens: int = 0):
        super().__init__(message)
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


@dataclass(frozen=True)
class Usage:
    """What one call spent — the return companion to the result, and the shape the
    ai_usage ledger row is built from. Cost is NOT here: it is derived at read time
    from the catalog (§5), never carried on the call."""
    purpose_key: str
    model_id: str
    input_tokens: int
    output_tokens: int


def is_available() -> bool:
    """True when the engine is configured (the key is set). The admin reads this
    to show status without spending a token."""
    return bool(os.environ.get(API_KEY_ENV, "").strip())


def _api_key() -> str:
    key = os.environ.get(API_KEY_ENV, "").strip()
    if not key:
        raise AIUnavailable(
            f"{API_KEY_ENV} is not set — the AI engine is inert. Paste the platform "
            "Anthropic key into pet_env.local.sh under that name (SPEC_DATSPET_AI_ENGINE §16)."
        )
    return key


class _SafeDict(dict):
    """A missing template variable renders as the literal {key} rather than
    raising — the same posture the purpose validator checks against, so what
    ships is what was validated."""
    def __missing__(self, key):
        return "{" + key + "}"


def _fill(template: str, variables: Optional[dict]) -> str:
    if not template or not variables:
        return template or ""
    return template.format_map(_SafeDict(variables))


def _call_model(*, model_id: str, system_prompt: str, messages: list,
                max_tokens: int, output_schema: dict) -> tuple[str, dict]:
    """The single place that touches Anthropic. Returns (text, usage_dict).
    Isolated so the tests monkeypatch exactly this seam — everything above it is
    pure dispatch logic that runs with no network.

    Proxy handling is ported verbatim from DatsMe's `_call_anthropic` (a debugged
    environment fact, not a style choice): route through an HTTP proxy if one is
    set, but SKIP a `socks://` one (httpx can't use it), and `trust_env=False` so
    the SDK doesn't re-read the same broken proxy env behind our back.
    """
    api_key = _api_key()
    import anthropic
    import httpx

    proxy_url = os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY")
    if proxy_url and proxy_url.startswith("socks"):
        proxy_url = None  # httpx doesn't support SOCKS — skip it
    http_client = httpx.Client(proxy=proxy_url, trust_env=False)
    client = anthropic.Anthropic(api_key=api_key, http_client=http_client)

    # Structured outputs (§1/§4): the schema is declared on the purpose and the
    # API guarantees the shape. NO temperature — it 400s on every current model.
    response = client.messages.create(
        model=model_id,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=messages,
        thinking=THINKING_DISABLED,
        output_config={"format": {"type": "json_schema", "schema": output_schema}},
    )
    usage = {
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
    }
    if getattr(response, "stop_reason", None) == STOP_REASON_TRUNCATED:
        raise AITruncated(
            f"{model_id} hit max_tokens={max_tokens} before finishing its JSON. Raise "
            f"`max_tokens` on the purpose — it budgets the ANSWER, so a longer schema "
            f"needs more room, and any model that thinks spends this budget first.",
            input_tokens=usage["input_tokens"], output_tokens=usage["output_tokens"],
        )
    text = next((b.text for b in response.content if getattr(b, "type", None) == "text"), "")
    return text, usage


def _record(ts: float, purpose_key: str, model_id: str, input_tokens: int,
            output_tokens: int, *, ok: bool, error_code: Optional[str],
            external_user_id: Optional[str]) -> None:
    """Append one row to the ai_usage ledger. Best-effort (never raises): a usage
    -log hiccup must not fail a call that already spent real tokens — the DatsMe
    posture. The ledger is append-only (§5): a re-run is a NEW row, never an UPDATE."""
    try:
        db.insert_ai_usage(
            ts=ts, purpose_key=purpose_key, model_id=model_id,
            input_tokens=input_tokens, output_tokens=output_tokens,
            ok=ok, error_code=error_code, external_user_id=external_user_id,
        )
    except Exception as e:  # pragma: no cover - defensive
        print(f"[ai_engine] failed to record usage for {purpose_key!r}: {e}", flush=True)


def call_purpose(purpose_key: str, *, image: Optional[bytes] = None,
                 media_type: Optional[str] = None, variables: Optional[dict] = None,
                 external_user_id: Optional[str] = None) -> tuple[dict, Usage]:
    """Resolve a named purpose, make one structured-output call, record usage, and
    return (validated_result, Usage).

    Raises AIUnavailable when the key is unset or the purpose is switched off
    (callers degrade), and AIError for an unknown purpose, a bad image contract,
    an API failure, or output that is not valid JSON.
    """
    _api_key()  # AIUnavailable before any work if the engine is inert

    purpose = ai_purposes.get(purpose_key)
    if purpose is None:
        raise AIError(f"unknown AI purpose {purpose_key!r}")
    if not purpose.get("is_active", False):
        raise AIUnavailable(f"AI purpose {purpose_key!r} is switched off")

    wants_image = purpose.get("input") == "image"
    if wants_image and image is None:
        raise AIError(f"purpose {purpose_key!r} requires an image")
    if image is not None and not wants_image:
        raise AIError(f"purpose {purpose_key!r} does not take an image")
    if wants_image and not media_type:
        raise AIError(f"purpose {purpose_key!r} needs a media_type for its image")

    model = ai_models.resolve(purpose["tier"])  # rule 6 makes this total at runtime
    model_id = model["id"]

    system_prompt = _fill(purpose.get("system_prompt", ""), variables)
    user_prompt = _fill(purpose.get("user_prompt_template", ""), variables)

    if wants_image:
        content = [
            {"type": "image", "source": {"type": "base64",
                                         "media_type": media_type,
                                         "data": base64.b64encode(image).decode()}},
            {"type": "text", "text": user_prompt},
        ]
    else:
        content = user_prompt
    messages = [{"role": "user", "content": content}]

    ts = time.time()
    try:
        text, raw_usage = _call_model(
            model_id=model_id, system_prompt=system_prompt, messages=messages,
            max_tokens=int(purpose["max_tokens"]), output_schema=purpose["output_schema"],
        )
    except AIUnavailable:
        raise
    except AITruncated as e:
        # The API answered and BILLED, then we rejected the fragment — record the real
        # tokens it carries, and re-raise as itself so `error_code` names the budget.
        _record(ts, purpose_key, model_id, e.input_tokens, e.output_tokens, ok=False,
                error_code=type(e).__name__, external_user_id=external_user_id)
        raise
    except Exception as e:
        # The API never billed (no usage to record) — log a zero-token failure row.
        _record(ts, purpose_key, model_id, 0, 0, ok=False,
                error_code=type(e).__name__, external_user_id=external_user_id)
        raise AIError(f"AI call for {purpose_key!r} failed: {e}") from e

    in_tok = int(raw_usage.get("input_tokens", 0) or 0)
    out_tok = int(raw_usage.get("output_tokens", 0) or 0)

    try:
        result = json.loads(text)
    except (json.JSONDecodeError, TypeError) as e:
        # The API billed but the shape was wrong — record the real tokens.
        _record(ts, purpose_key, model_id, in_tok, out_tok, ok=False,
                error_code="bad_output", external_user_id=external_user_id)
        raise AIError(f"purpose {purpose_key!r} returned non-JSON output") from e

    _record(ts, purpose_key, model_id, in_tok, out_tok, ok=True,
            error_code=None, external_user_id=external_user_id)
    return result, Usage(purpose_key=purpose_key, model_id=model_id,
                         input_tokens=in_tok, output_tokens=out_tok)
