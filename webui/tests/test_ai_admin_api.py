"""API tests for the AI engine admin (SPEC_DATSPET_AI_ENGINE §6).

Exercises webui/ai_admin.py against a TEMP copy of the ai_purposes dir + an
isolated temp DB (dpp_env), with the admin gate satisfied — mirroring
test_design_admin_api.py. The one Anthropic seam is monkeypatched for the
Test-configuration path; no network, no GPU.
"""
import importlib
import shutil
from pathlib import Path

import pytest


@pytest.fixture()
def ai_client(dpp_env, tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from pet_factory import ai_purposes as ap
    from pet_factory.ai_purposes import admin as ap_admin

    # Temp writable copy of the purposes dir, so edits don't touch the real files.
    src = Path(ap.__file__).resolve().parent
    dst = tmp_path / "ai_purposes"
    dst.mkdir()
    for f in src.glob("*.json"):
        shutil.copy(f, dst / f.name)
    monkeypatch.setattr(ap, "_DIR", dst)
    monkeypatch.setattr(ap_admin, "_DIR", dst)
    ap.reload()

    monkeypatch.setenv("DATSPET_AI_API_KEY", "test-key")

    import ai_admin
    importlib.reload(ai_admin)
    monkeypatch.setattr(ai_admin.datsme_integration, "admin_user_id", lambda request: "admin-1")
    monkeypatch.setattr(ai_admin, "_writable", lambda: True)

    app = FastAPI()
    app.include_router(ai_admin.router)
    app.dependency_overrides[ai_admin.datsme_integration.require_admin_launch] = lambda: None
    client = TestClient(app)
    client._ai_admin = ai_admin
    client._db = dpp_env["db"]
    yield client
    ap.reload()


# ── status ───────────────────────────────────────────────────────────────────

def test_status_reports_configured_and_counts(ai_client):
    body = ai_client.get("/api/admin/ai/status").json()
    assert body["available"] is True and body["writable"] is True
    # connectivity_check (engine) + image_triage + pet_likeness (§2.5) + motion_classify (§3.5)
    # + pose_clause (SPEC_MOTION_LAB §2) + store_listing (SPEC_PET_STORE §4).
    assert body["purpose_count"] == 6 and body["model_count"] == 3


# ── purposes: read ───────────────────────────────────────────────────────────

def test_list_purposes_and_tiers(ai_client):
    body = ai_client.get("/api/admin/ai/purposes").json()
    assert set(body["tiers"]) == {"fast", "balanced", "capable"}
    keys = [p["purpose_key"] for p in body["purposes"]]
    assert keys == ["connectivity_check", "image_triage", "pet_likeness",
                    "motion_classify", "pose_clause", "store_listing"]
    by_key = {p["purpose_key"]: p for p in body["purposes"]}
    assert by_key["connectivity_check"]["tier"] == "fast"
    # the consumer captioner purposes are image-input (SPEC_UPLOAD_LIKENESS §2.5)
    assert by_key["pet_likeness"]["input"] == "image"
    assert by_key["image_triage"]["input"] == "image"
    # the store listing draft reads a portrait (SPEC_PET_STORE §4)
    assert by_key["store_listing"]["input"] == "image"


def test_get_one_purpose_full_json(ai_client):
    body = ai_client.get("/api/admin/ai/purposes/connectivity_check").json()
    assert body["purpose"]["purpose_key"] == "connectivity_check"
    assert body["purpose"]["output_schema"]["additionalProperties"] is False
    assert "fast" in body["tiers"]


def test_get_unknown_purpose_404(ai_client):
    assert ai_client.get("/api/admin/ai/purposes/nope").status_code == 404


# ── purposes: edit ───────────────────────────────────────────────────────────

def test_edit_max_tokens_goes_live(ai_client):
    from pet_factory import ai_purposes as ap
    p = ai_client.get("/api/admin/ai/purposes/connectivity_check").json()["purpose"]
    p["max_tokens"] = 128
    r = ai_client.put("/api/admin/ai/purposes/connectivity_check", json={"purpose": p})
    assert r.status_code == 200, r.text
    assert ap.get("connectivity_check")["max_tokens"] == 128


def test_edit_toggle_active(ai_client):
    from pet_factory import ai_purposes as ap
    p = ai_client.get("/api/admin/ai/purposes/connectivity_check").json()["purpose"]
    p["is_active"] = False
    assert ai_client.put("/api/admin/ai/purposes/connectivity_check",
                         json={"purpose": p}).status_code == 200
    assert ap.get("connectivity_check")["is_active"] is False


def test_edit_invalid_tier_422_with_validator_errors(ai_client):
    p = ai_client.get("/api/admin/ai/purposes/connectivity_check").json()["purpose"]
    p["tier"] = "supreme"
    r = ai_client.put("/api/admin/ai/purposes/connectivity_check", json={"purpose": p})
    assert r.status_code == 422
    assert r.json()["detail"]["error"] == "validation_failed"
    assert any("tier" in e for e in r.json()["detail"]["errors"])


def test_edit_banned_schema_keyword_422(ai_client):
    """The §11 rule reaches the admin: a save that adds a keyword structured
    outputs ignores is refused with the guard test's own error."""
    p = ai_client.get("/api/admin/ai/purposes/connectivity_check").json()["purpose"]
    p["output_schema"]["properties"]["echo"] = {"type": "string", "maxLength": 4}
    r = ai_client.put("/api/admin/ai/purposes/connectivity_check", json={"purpose": p})
    assert r.status_code == 422
    assert any("maxLength" in e for e in r.json()["detail"]["errors"])


def test_edit_unknown_purpose_404(ai_client):
    p = ai_client.get("/api/admin/ai/purposes/connectivity_check").json()["purpose"]
    p["purpose_key"] = "ghost"
    assert ai_client.put("/api/admin/ai/purposes/ghost",
                         json={"purpose": p}).status_code == 404


# ── models: read-only catalog ────────────────────────────────────────────────

def test_models_are_read_only_catalog(ai_client):
    body = ai_client.get("/api/admin/ai/models").json()
    ids = [m["id"] for m in body["models"]]
    assert ids == ["claude-opus-4-8", "claude-sonnet-5", "claude-haiku-4-5"]
    # there is no write verb on the catalog
    assert ai_client.put("/api/admin/ai/models", json={}).status_code in (404, 405)
    assert ai_client.post("/api/admin/ai/models", json={}).status_code in (404, 405)


# ── usage: derived cost by purpose ───────────────────────────────────────────

def test_usage_derives_cost_by_purpose(ai_client):
    import time
    db = ai_client._db
    now = time.time()
    db.insert_ai_usage(ts=now, purpose_key="connectivity_check",
                       model_id="claude-haiku-4-5", input_tokens=1000,
                       output_tokens=500, ok=True)
    db.insert_ai_usage(ts=now, purpose_key="connectivity_check",
                       model_id="claude-haiku-4-5", input_tokens=0,
                       output_tokens=0, ok=False, error_code="529")
    body = ai_client.get("/api/admin/ai/usage").json()
    row = next(p for p in body["purposes"] if p["purpose_key"] == "connectivity_check")
    assert row["calls"] == 2 and row["ok_calls"] == 1 and row["error_calls"] == 1
    # haiku $1/$5 per MTok → 1000 in + 500 out = 0.001 + 0.0025 = 0.0035
    assert row["est_cost_usd"] == pytest.approx(0.0035)
    assert body["total_cost_usd"] == pytest.approx(0.0035)


# ── Test configuration button ────────────────────────────────────────────────

def test_test_configuration_success_records_a_row(ai_client, monkeypatch):
    import json as _json
    monkeypatch.setattr(ai_client._ai_admin.ai_engine, "_call_model",
                        lambda **k: (_json.dumps({"ok": True, "echo": "pong"}),
                                     {"input_tokens": 9, "output_tokens": 3}))
    body = ai_client.post("/api/admin/ai/test").json()
    assert body["ok"] is True
    assert body["model"] == "claude-haiku-4-5"
    assert body["input_tokens"] == 9 and body["output_tokens"] == 3
    assert body["est_cost_usd"] == pytest.approx(9 / 1e6 * 1 + 3 / 1e6 * 5)
    # the real usage row landed
    assert ai_client._db.ai_usage_summary()[0]["ok_calls"] == 1


def test_test_configuration_degrades_cleanly_when_unavailable(ai_client, monkeypatch):
    def unavailable(*a, **k):
        raise ai_client._ai_admin.ai_engine.AIUnavailable("no key")
    monkeypatch.setattr(ai_client._ai_admin.ai_engine, "call_purpose", unavailable)
    body = ai_client.post("/api/admin/ai/test").json()
    assert body["ok"] is False and body["kind"] == "unavailable"


# ── writability ──────────────────────────────────────────────────────────────

def test_writes_refused_409_when_read_only(ai_client, monkeypatch):
    monkeypatch.setattr(ai_client._ai_admin, "_writable", lambda: False)
    p = ai_client.get("/api/admin/ai/purposes/connectivity_check").json()["purpose"]
    assert ai_client.put("/api/admin/ai/purposes/connectivity_check",
                         json={"purpose": p}).status_code == 409
    # reads still work
    assert ai_client.get("/api/admin/ai/purposes").status_code == 200
    assert ai_client.get("/api/admin/ai/models").status_code == 200
