"""Pins for the pool attribution labels — the {user, device} "requested by"
metadata sent with each pool job (advisory display only).

Three layers, all network- and GPU-free:
  - classify_device(): the User-Agent → bucket substring rules.
  - pool_labels(): request + owner → the flat {user, user_id, device} dict —
    user prefers the readable `nm` display name (falling back to user_id, then
    "anonymous"), user_id kept alongside for lookup, plus the device-omitted case.
  - pool_client.submit(): labels is additive — present in the body only when
    non-empty, so a submit without it is byte-for-byte the pre-feature body.
"""
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WEBUI = os.path.join(REPO, "webui")
for p in (WEBUI, REPO):
    if p not in sys.path:
        sys.path.insert(0, p)

import pytest

import datsme_integration as di
import pool_client


# --- classify_device: the UA substring rules ---------------------------------

@pytest.mark.parametrize("ua,expected", [
    # iOS — any of iPhone/iPad/iPod/iOS
    ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Safari/604.1", "ios"),
    ("Mozilla/5.0 (iPad; CPU OS 16_5 like Mac OS X) AppleWebKit", "ios"),
    # Android wins over its own "Linux" token
    ("Mozilla/5.0 (Linux; Android 14; Pixel 8) Chrome/120", "android"),
    # Desktop OS + a browser token
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0", "desktop"),
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari/605", "desktop"),
    ("Mozilla/5.0 (X11; Linux x86_64) Firefox/121.0", "desktop"),
    ("Mozilla/5.0 (X11; CrOS x86_64) Chrome/120", "desktop"),
    # Non-browser / opaque agents → unknown
    ("curl/8.4.0", "unknown"),
    ("python-urllib/3.11", "unknown"),
    ("", "unknown"),
    (None, "unknown"),
])
def test_classify_device(ua, expected):
    assert di.classify_device(ua) == expected


def test_android_beats_desktop_linux():
    # An Android UA also carries "Linux" — the Android check must come first so
    # a phone is never misfiled as a desktop.
    ua = "Mozilla/5.0 (Linux; Android 13; SM-G991B) AppleWebKit Chrome/119 Mobile"
    assert di.classify_device(ua) == "android"


# --- pool_labels: request + owner → the label dict ---------------------------

class _Req:
    """Minimal stand-in for a Starlette Request. pool_labels reads
    headers.get('user-agent') for device and cookies.get(...) for the readable
    display name (via resolve_launch_display_name). `cookies` lets a test inject
    a real launch cookie; empty by default (no launched name → user = user_id)."""
    def __init__(self, ua=None, cookies=None):
        self.headers = {"user-agent": ua} if ua is not None else {}
        self.cookies = cookies or {}


def test_pool_labels_falls_back_to_user_id_without_readable_name():
    # No launch cookie → no nm → user falls back to the user_id (never blank), and
    # user_id is NOT duplicated since it already equals `user`.
    labels = di.pool_labels(_Req("Mozilla/5.0 (Windows NT 10.0) Chrome/120"), "user-abc")
    assert labels == {"user": "user-abc", "device": "desktop"}
    assert "user_id" not in labels


def test_pool_labels_anonymous_when_no_owner():
    # Standalone / unauthenticated → user is the literal "anonymous", never blank
    # or a token. No user_id to add.
    labels = di.pool_labels(_Req("curl/8.4.0"), None)
    assert labels == {"user": "anonymous", "device": "unknown"}
    assert "user_id" not in labels


def test_pool_labels_omits_device_without_request():
    # A background/server submit (no request) omits device entirely — labels are
    # additive, so a missing key is fine and the pool shows only the user.
    labels = di.pool_labels(None, "user-xyz")
    assert labels == {"user": "user-xyz"}
    assert "device" not in labels


def test_pool_labels_values_clamped_under_64_chars():
    # The pool's label contract is string→string with short values; a pathological
    # id is truncated so we never send an over-long value.
    labels = di.pool_labels(None, "u" * 200)
    assert len(labels["user"]) < 64


# --- the readable-name path: user = nm claim, user_id kept alongside ----------

def _launch_cookie_with_nm(nm):
    """A datsme_launch cookie blob carrying the given nm claim, signed with the
    conftest test secret — the same shape /launch sets. user_id is 'user-A'."""
    from datsme_partner_sdk.testkit import make_test_launch_token
    from jose import jwt
    from conftest import TEST_SECRET
    tok = make_test_launch_token(
        hmac_secret=TEST_SECRET, user_id="user-A", activity_id="design_a_pet",
        partner_slug="datspet", capabilities=["pets.write"], ttl_seconds=1800)
    claims = jwt.decode(tok, TEST_SECRET, algorithms=["HS256"])
    claims["nm"] = nm
    tok = jwt.encode(claims, TEST_SECRET, algorithm="HS256")
    return json.dumps({"token": tok})


def test_pool_labels_prefers_readable_name_and_keeps_user_id(dpp_env):
    # A launched user with an nm claim → user shows the readable NAME, and the
    # UUID is kept under user_id for unambiguous lookup.
    req = _Req("Mozilla/5.0 (Windows NT 10.0) Chrome/120",
               cookies={"datsme_launch": _launch_cookie_with_nm("markly")})
    labels = di.pool_labels(req, "user-A")
    assert labels["user"] == "markly"
    assert labels["user_id"] == "user-A"
    assert labels["device"] == "desktop"


def test_pool_labels_no_user_id_when_name_equals_owner(dpp_env):
    # Defensive: if the readable name happened to equal the user_id, user_id is
    # not sent twice (it adds no signal).
    req = _Req(cookies={"datsme_launch": _launch_cookie_with_nm("user-A")})
    labels = di.pool_labels(req, "user-A")
    assert labels["user"] == "user-A"
    assert "user_id" not in labels


# --- pool_client.submit: labels is additive ----------------------------------

def _capture_body(monkeypatch):
    captured = {}

    class _Resp:
        def read(self):
            return json.dumps({"job_id": "jid-1"}).encode()

    def fake_req(method, path, *, body=None, timeout=60):
        captured["method"] = method
        captured["path"] = path
        captured["body"] = body
        return _Resp()

    monkeypatch.setattr(pool_client, "_req", fake_req)
    return captured


def test_submit_includes_labels_when_present(monkeypatch):
    captured = _capture_body(monkeypatch)
    pool_client.submit("pet_factory", {"animal": "cardinal bird"},
                       labels={"user": "u-1", "device": "ios"})
    assert captured["path"] == "/api/jobs"
    assert captured["body"] == {
        "task": "pet_factory",
        "params": {"animal": "cardinal bird"},
        "labels": {"user": "u-1", "device": "ios"},
    }


def test_submit_omits_labels_key_when_absent(monkeypatch):
    # No labels → the body is exactly the pre-feature shape (no `labels` key).
    captured = _capture_body(monkeypatch)
    pool_client.submit("pet_factory", {"animal": "x"})
    assert "labels" not in captured["body"]
    assert captured["body"] == {"task": "pet_factory", "params": {"animal": "x"}}


def test_submit_omits_labels_key_when_empty(monkeypatch):
    # An empty dict is falsy → treated the same as absent (additive, no-op).
    captured = _capture_body(monkeypatch)
    pool_client.submit("pet_factory", {"animal": "x"}, labels={})
    assert "labels" not in captured["body"]
