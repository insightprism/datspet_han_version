"""Tests for the AI engine dispatch + usage ledger (SPEC_DATSPET_AI_ENGINE §4/§5).

The one Anthropic seam (`_call_model`) is monkeypatched, so the whole dispatch →
record → return path runs with no network and no `anthropic` installed — exactly
the split that lets Phases 1–2 ship keyless and this phase test the wiring. Uses
the shared `dpp_env` fixture (conftest.py) for an isolated temp DB.
"""
import importlib
import json
from pathlib import Path

import pytest


@pytest.fixture()
def engine(dpp_env, monkeypatch):
    """The ai_engine module bound to the temp DB, with the key set. Callers
    monkeypatch `_call_model` per test."""
    monkeypatch.setenv("DATSPET_AI_API_KEY", "test-key")
    import ai_engine as ae
    importlib.reload(ae)  # rebind to the reloaded (temp-DB) db module
    return ae


def _ok_model(text_obj, in_tok=11, out_tok=7):
    def fake(**kwargs):
        fake.seen = kwargs
        return json.dumps(text_obj), {"input_tokens": in_tok, "output_tokens": out_tok}
    return fake


def _truncating_model(engine, in_tok=9, out_tok=32):
    """A seam that answered, billed, and ran out of budget mid-JSON."""
    def fake(**kwargs):
        raise engine.AITruncated(
            f"hit max_tokens={out_tok}", input_tokens=in_tok, output_tokens=out_tok)
    return fake


# ── the happy path: resolve → call → record → return ─────────────────────────

def test_call_purpose_resolves_records_and_returns(engine, dpp_env, monkeypatch):
    fake = _ok_model({"ok": True, "echo": "pong"})
    monkeypatch.setattr(engine, "_call_model", fake)

    result, usage = engine.call_purpose("connectivity_check")

    assert result == {"ok": True, "echo": "pong"}
    # fast tier → haiku, resolved through the catalog (not pinned on the purpose).
    assert usage.model_id == "claude-haiku-4-5"
    assert usage.input_tokens == 11 and usage.output_tokens == 7
    # the purpose's max_tokens + schema reached the model call
    assert fake.seen["model_id"] == "claude-haiku-4-5"
    assert fake.seen["max_tokens"] == 64
    assert fake.seen["output_schema"]["additionalProperties"] is False
    # a single success row landed in the ledger
    summary = dpp_env["db"].ai_usage_summary()
    assert len(summary) == 1
    row = summary[0]
    assert row["purpose_key"] == "connectivity_check"
    assert row["ok_calls"] == 1 and row["error_calls"] == 0
    assert row["input_tokens"] == 11 and row["output_tokens"] == 7


def test_variables_fill_the_prompt(engine, monkeypatch):
    fake = _ok_model({"ok": True, "echo": "x"})
    p = dict(engine.ai_purposes.get("connectivity_check"))
    p["template_vars"] = ["name"]
    p["user_prompt_template"] = "Hello {name}."
    monkeypatch.setattr(engine.ai_purposes, "get", lambda k: p)
    monkeypatch.setattr(engine, "_call_model", fake)

    engine.call_purpose("connectivity_check", variables={"name": "Wu"})
    assert fake.seen["messages"][0]["content"] == "Hello Wu."


# ── degradation: inert / inactive / unknown ──────────────────────────────────

def test_key_unset_raises_aiunavailable(dpp_env, monkeypatch):
    monkeypatch.delenv("DATSPET_AI_API_KEY", raising=False)
    import ai_engine as ae
    importlib.reload(ae)
    assert ae.is_available() is False
    with pytest.raises(ae.AIUnavailable):
        ae.call_purpose("connectivity_check")


def test_inactive_purpose_is_unavailable(engine, monkeypatch):
    p = dict(engine.ai_purposes.get("connectivity_check"))
    p["is_active"] = False
    monkeypatch.setattr(engine.ai_purposes, "get", lambda k: p)
    monkeypatch.setattr(engine, "_call_model", _ok_model({"ok": True}))
    with pytest.raises(engine.AIUnavailable):
        engine.call_purpose("connectivity_check")


def test_unknown_purpose_raises_aierror(engine, monkeypatch):
    monkeypatch.setattr(engine, "_call_model", _ok_model({"ok": True}))
    with pytest.raises(engine.AIError):
        engine.call_purpose("no_such_purpose")


def test_text_purpose_rejects_an_image(engine, monkeypatch):
    monkeypatch.setattr(engine, "_call_model", _ok_model({"ok": True}))
    with pytest.raises(engine.AIError):
        engine.call_purpose("connectivity_check", image=b"x", media_type="image/png")


# ── failures still write a ledger row (§5) ───────────────────────────────────

def test_api_error_records_a_failure_row(engine, dpp_env, monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("529 overloaded")
    monkeypatch.setattr(engine, "_call_model", boom)
    with pytest.raises(engine.AIError):
        engine.call_purpose("connectivity_check")
    row = dpp_env["db"].ai_usage_summary()[0]
    assert row["ok_calls"] == 0 and row["error_calls"] == 1
    # no tokens billed on a pre-response failure
    assert row["input_tokens"] == 0 and row["output_tokens"] == 0


def test_bad_output_records_real_tokens_and_raises(engine, dpp_env, monkeypatch):
    """The API billed but returned non-JSON — the tokens are real and must be
    recorded even though the call failed."""
    monkeypatch.setattr(engine, "_call_model",
                        lambda **k: ("this is not json", {"input_tokens": 5, "output_tokens": 3}))
    with pytest.raises(engine.AIError):
        engine.call_purpose("connectivity_check")
    row = dpp_env["db"].ai_usage_summary()[0]
    assert row["error_calls"] == 1
    assert row["input_tokens"] == 5 and row["output_tokens"] == 3


# ── the ledger is append-only (§5) ───────────────────────────────────────────

def test_usage_ledger_is_append_only(engine, dpp_env, monkeypatch):
    monkeypatch.setattr(engine, "_call_model", _ok_model({"ok": True, "echo": "p"}, 4, 2))
    for _ in range(3):
        engine.call_purpose("connectivity_check")
    row = dpp_env["db"].ai_usage_summary()[0]
    assert row["calls"] == 3, "a re-run is a NEW row, never an UPDATE"
    assert row["input_tokens"] == 12 and row["output_tokens"] == 6


# ── max_tokens cannot silently truncate ──────────────────────────────────────
#
# A purpose's `max_tokens` budgets its JSON answer, but on a thinking-by-default
# model it caps thinking + answer together: the budget goes on reasoning, the text
# block comes back empty, and the JSON parse fails. Callers degrade on AIError, so
# a one-word `tier` edit could drop a purpose to its offline path with nothing in
# the logs. These lock both halves of the fix — thinking is stated, truncation is
# loud — against the real `_call_model` rather than the monkeypatched seam.

def _fake_anthropic(monkeypatch, *, stop_reason, text='{"ok": true}',
                    in_tok=7, out_tok=3):
    """Stand in for `anthropic.Anthropic`, capturing the request kwargs. Patched on
    the real module because `_call_model` imports it lazily at call time."""
    import anthropic
    from types import SimpleNamespace

    captured = {}

    class FakeMessages:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                content=[SimpleNamespace(type="text", text=text)],
                stop_reason=stop_reason,
                usage=SimpleNamespace(input_tokens=in_tok, output_tokens=out_tok),
            )

    class FakeClient:
        def __init__(self, **kwargs):
            self.messages = FakeMessages()

    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)
    return captured


def _call_the_model(engine, max_tokens=32):
    return engine._call_model(
        model_id="claude-haiku-4-5", system_prompt="s",
        messages=[{"role": "user", "content": "u"}],
        max_tokens=max_tokens, output_schema={"type": "object"},
    )


def test_thinking_is_sent_explicitly_so_max_tokens_budgets_the_answer(engine, monkeypatch):
    captured = _fake_anthropic(monkeypatch, stop_reason="end_turn")
    _call_the_model(engine)
    assert captured["thinking"] == engine.THINKING_DISABLED, (
        "thinking must be stated on every call — leaving it to the model default lets "
        "a tier change silently spend max_tokens on reasoning instead of the answer"
    )


def test_truncated_answer_raises_aitruncated_not_a_json_error(engine, monkeypatch):
    """A truncated reply is a normal 200 carrying a fragment. Unchecked it surfaces
    as a JSONDecodeError that blames the model instead of the budget."""
    _fake_anthropic(monkeypatch, stop_reason=engine.STOP_REASON_TRUNCATED, text='{"ok": tr')
    with pytest.raises(engine.AITruncated) as excinfo:
        _call_the_model(engine, max_tokens=32)
    assert "max_tokens=32" in str(excinfo.value), "the error must name the budget to raise"
    assert excinfo.value.input_tokens == 7 and excinfo.value.output_tokens == 3


def test_aitruncated_still_degrades_callers_that_catch_aierror(engine):
    """Callers (motion_resolver.classify) fall back on AIError. Truncation must keep
    degrading them, not escape as a new unhandled type."""
    assert issubclass(engine.AITruncated, engine.AIError)


def test_truncated_call_records_the_tokens_it_billed(engine, dpp_env, monkeypatch):
    """A truncated call is a PAID call — recording it as zero would understate spend
    in the ledger the cost view reads (§5)."""
    monkeypatch.setattr(engine, "_call_model", _truncating_model(engine, in_tok=9, out_tok=32))
    with pytest.raises(engine.AITruncated):
        engine.call_purpose("connectivity_check")
    row = dpp_env["db"].ai_usage_summary()[0]
    assert row["error_calls"] == 1
    assert row["input_tokens"] == 9 and row["output_tokens"] == 32
    # Read the raw column: `error_code` is what names the budget failure, and no
    # public reader exposes it (ai_usage_summary aggregates), so assert it directly
    # or a re-wrap back into a bare AIError would silently undo the diagnosis.
    code = dpp_env["db"]._connect().execute(
        "SELECT error_code FROM ai_usage ORDER BY ts DESC LIMIT 1").fetchone()[0]
    assert code == "AITruncated"


# ── the seam (§11): the engine names no purpose key ──────────────────────────

def test_engine_source_names_no_purpose_key():
    """A literal purpose key in the engine would re-couple what §0.1 separated —
    every key must arrive as a caller's argument."""
    import ai_engine
    src = Path(ai_engine.__file__).read_text()
    assert "pet_likeness" not in src
    assert "connectivity_check" not in src
