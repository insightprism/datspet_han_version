"""Pins for the pool attribution labels — the {user, device} "requested by"
metadata sent with each pool job (advisory display only).

Three layers, all network- and GPU-free:
  - classify_device(): the User-Agent → bucket substring rules.
  - pool_labels(): request + owner → the flat {user, device} dict, with the
    anonymous fallback and the no-request (device-omitted) case.
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
    """Minimal stand-in for a Starlette Request — pool_labels only reads
    headers.get('user-agent')."""
    def __init__(self, ua=None):
        self.headers = {"user-agent": ua} if ua is not None else {}


def test_pool_labels_launched_user_desktop():
    labels = di.pool_labels(_Req("Mozilla/5.0 (Windows NT 10.0) Chrome/120"), "user-abc")
    assert labels == {"user": "user-abc", "device": "desktop"}


def test_pool_labels_anonymous_when_no_owner():
    # Standalone / unauthenticated → user is the literal "anonymous", never blank
    # or a token.
    labels = di.pool_labels(_Req("curl/8.4.0"), None)
    assert labels == {"user": "anonymous", "device": "unknown"}


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
