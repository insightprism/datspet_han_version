"""The reference layer (SPEC_PET_DESIGNER_FLOW §3, §7.3, §7.4, §10.2).

These are the guard tests for the spec's central rule (§0.1):

    Step 1 takes exactly one input — WHICH ANIMAL. Every "what should it look like"
    input is step 2.

`test_curated_pick_never_touches_the_gpu` and `test_step1_ignores_design_fields` are
what mechanise it. Rev.1 of the spec put body shape in step 1, which silently turned a
curated cache HIT into a MISS — discarding a human-approved base.png for an unvetted
txt2img roll, disclosed to the user as nothing but "~10 s". These tests make that
regression un-shippable rather than merely discouraged.

Zero-GPU: _render_still is stubbed. A test that needed a GPU would not run in CI, and
the properties worth pinning here are about routing and access, not pixels.
"""
import importlib
import io
import os
import sys

import pytest
from PIL import Image
from fastapi.testclient import TestClient

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WEBUI = os.path.join(REPO, "webui")
for p in (WEBUI, REPO):
    if p not in sys.path:
        sys.path.insert(0, p)


@pytest.fixture
def app_mod(tmp_path, monkeypatch):
    """A fresh app bound to a temp DB + output dir. Mirrors test_motions_endpoint's
    fixture — conftest's shared `client` mounts only the DPP router, so it cannot
    reach /api/reference."""
    out_dir = tmp_path / "out"; out_dir.mkdir()
    monkeypatch.setenv("PETMAKER_OUTPUT_DIR", str(out_dir))
    monkeypatch.setenv("PETMAKER_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("DATSME_HMAC_SECRET", "test-secret")
    import db as db_mod
    importlib.reload(db_mod)
    db_mod._conn = None
    db_mod.DB_PATH = tmp_path / "t.db"
    db_mod.OUTPUT_DIR = out_dir
    db_mod.init_db()
    import app as a
    importlib.reload(a)
    return a


@pytest.fixture
def client(app_mod):
    return TestClient(app_mod.app)


@pytest.fixture
def no_gpu(app_mod, monkeypatch):
    """Stub the renderer and record every call. Returns the call log, so a test can
    assert on what WOULD have been rendered — including that nothing was."""
    calls = []

    def fake_render(description, request, owner, reference_path=None, strength=None,
                    isolate=False):
        calls.append({"description": description, "reference_path": reference_path,
                      "strength": strength, "isolate": isolate})
        buf = io.BytesIO()
        Image.new("RGB", (64, 64), (10, 20, 30)).save(buf, "PNG")
        return buf.getvalue()

    monkeypatch.setattr(app_mod, "_render_still", fake_render)
    return calls


def _upload(name="photo.png", mime="image/png"):
    buf = io.BytesIO()
    Image.new("RGB", (80, 60), (200, 100, 50)).save(buf, "PNG")
    buf.seek(0)
    return {"image": (name, buf, mime)}


# ── §0.1: the archetype rule, mechanised ─────────────────────────────────────

def test_curated_pick_never_touches_the_gpu(client, no_gpu):
    """A curated breed is a CACHE HIT: free, instant, vetted (§3.3).

    The curated base.png is a human-approved best-of-N from the same _base_prompt
    path (generate_candidates.py → promote_candidate.py). Rendering here would throw
    that curation away — which is exactly what Rev.1's shape-keyed fast-path rule did.
    """
    r = client.post("/api/reference", data={"catalog_animal": "cat", "catalog_breed": "tabby"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["generated"] is False
    assert body["source"] == "catalog"
    assert body["motion_profile"], "a curated pick must carry its pinned profile"
    assert no_gpu == [], "a curated pick must not reach a renderer"


def test_step1_ignores_design_fields(client, no_gpu):
    """Step 1 accepts ONE input: which animal (§0.1).

    Posting design fields to the fill endpoint must not change what it does — no
    branch, no extra render, no downgrade off the curated base. If a future change
    makes body_shape a step-1 input, this fails.
    """
    r = client.post("/api/reference", data={
        "catalog_animal": "cat", "catalog_breed": "tabby",
        "body_shape": "fat", "color": "purple", "accessories": "wizard hat",
    })
    assert r.status_code == 200, r.text
    assert r.json()["generated"] is False
    assert no_gpu == [], "a design field must never cost a curated pick its cache hit"


def test_every_shape_and_colour_keeps_the_curated_base(client, no_gpu):
    """The property stated as a sweep: NO design choice can turn a hit into a miss."""
    for shape in ("thin", "normal", "fat", "nonsense"):
        for colour in ("purple", "", "black"):
            r = client.post("/api/reference", data={
                "catalog_animal": "dog", "catalog_breed": "corgi",
                "body_shape": shape, "color": colour})
            assert r.status_code == 200
            assert r.json()["generated"] is False
    assert no_gpu == []


# ── the doors ────────────────────────────────────────────────────────────────

def test_long_tail_animal_draws_an_archetype(client, no_gpu):
    """A cache MISS: ~10 s, unvetted, and honest — there was never a curated blue jay.
    The prompt must be the bare animal, with NO design in it (§3.2)."""
    r = client.post("/api/reference", data={"animal": "blue jay"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "txt2img"
    assert body["generated"] is True
    # The body type is classified + pinned at FILL time now (motion_resolver: AI with a
    # keyword fallback — §3.5). With no API key in tests it falls back to keyword, and
    # "blue jay" resolves to avian (a keyword this profile now owns).
    assert body["motion_profile"] == "avian"
    assert len(no_gpu) == 1
    assert no_gpu[0]["description"] == "blue jay"
    assert no_gpu[0]["reference_path"] is None, "an archetype is txt2img, not img2img"


def test_upload_reference_is_redrawn_not_animated_asis(client, no_gpu):
    """§3.5 — the whole point of the upload door.

    Today an uploaded photo reaches Wan I2V raw (remix_strength stays None →
    make_pet_zip's as-is branch), and a photo is not the side-profile flat-shaded
    sprite the animator needs. The redraw must happen at FILL time, with a real
    strength, so the user sees the sprite before paying for a 3-minute build.
    """
    r = client.post("/api/reference", data={"animal": "corgi"}, files=_upload())
    assert r.status_code == 200, r.text
    assert r.json()["source"] == "upload"
    assert len(no_gpu) == 1
    assert no_gpu[0]["reference_path"] is not None, "the upload must be the img2img source"
    assert no_gpu[0]["strength"] is not None, "as-is is the bug; a redraw needs a strength"
    # SPEC_UPLOAD_LIKENESS §2.2, decision 6a — isolation is gated by the `upload_isolate`
    # flag, DEFAULT OFF. So a plain upload does not isolate; the gate is exercised in
    # test_upload_isolation_is_gated_by_the_flag below.
    assert no_gpu[0]["isolate"] is False, "isolation is off until an admin flips the flag"


@pytest.mark.parametrize("sent,expected", [
    (0.4, 0.4),      # "faithful" — keep the photo's look
    (0.85, 0.85),    # "sprite"   — animates best
    (0.05, 0.3),     # clamped to the floor
    (9.0, 0.9),      # clamped to the ceiling
])
def test_upload_redraw_strength_is_the_users_choice(client, no_gpu, sent, expected):
    """§3.5: likeness vs animation quality is a real trade and only the user knows
    which side they want — "faithful" keeps their photo's look but preserves the
    photographic pose Wan I2V animates badly; "sprite" animates reliably but looks
    redrawn. The server takes the number and clamps it; it does not decide."""
    r = client.post("/api/reference", data={"strength": sent}, files=_upload())
    assert r.status_code == 200, r.text
    assert no_gpu[-1]["strength"] == expected


def test_upload_without_an_animal_hint_still_works(client, no_gpu):
    """`animal` is a HINT on the upload door, not a requirement — a photo already
    says what the animal is; the name only sharpens the redraw prompt."""
    r = client.post("/api/reference", files=_upload())
    assert r.status_code == 200, r.text
    assert r.json()["source"] == "upload"


# ── SPEC_UPLOAD_LIKENESS §2.5: the upload captioner (lever E / Phase 2.1) ─────
#
# The AI engine's first real consumer. With a key set, the upload door reads the
# photo (image_triage gates, pet_likeness names it) and — when the noun field is
# empty — prefills the noun and extends the redraw. The human's typed word wins,
# and any failure / not-an-animal / no-key degrades to today's manual field. The
# one Anthropic seam (ai_engine._call_model) is mocked; no network.

def _mock_caption(app_mod, monkeypatch, *, is_subject=True, subject="parakeet",
                  features="green and yellow"):
    import json
    monkeypatch.setenv("DATSPET_AI_API_KEY", "test-key")

    def fake_model(**kw):
        props = kw["output_schema"].get("properties", {})
        if "is_subject" in props:                     # image_triage
            return json.dumps({"is_subject": is_subject, "usable": is_subject,
                               "reason": "clear subject" if is_subject else "a screenshot"}), \
                {"input_tokens": 10, "output_tokens": 5}
        return json.dumps({"subject": subject, "features": features,           # pet_likeness
                           "description": f"a {features} {subject}"}), \
            {"input_tokens": 20, "output_tokens": 10}

    monkeypatch.setattr(app_mod.ai_engine, "_call_model", fake_model)


def test_upload_empty_field_is_captioned_by_the_ai(client, no_gpu, app_mod, monkeypatch):
    """The whole point of lever E: upload a photo with no noun → the AI names it.
    The reference carries the suggestion (so the door can prefill the field), and
    the redraw draws THAT subject with the AI's cue — not the generic 'pet'."""
    _mock_caption(app_mod, monkeypatch)
    body = client.post("/api/reference", files=_upload()).json()
    assert body["suggested_subject"] == "parakeet"
    assert body["description"] == "parakeet"                          # clean noun on the record
    assert no_gpu[-1]["description"] == "parakeet, green and yellow"  # noun + cue to the redraw
    assert no_gpu[-1]["isolate"] is False                            # flag default OFF (decision 6a)


def test_upload_isolation_is_gated_by_the_flag(client, no_gpu, app_mod):
    """SPEC_UPLOAD_LIKENESS §2.2, decision 6a — the `upload_isolate` switch gates the
    cutout on the upload door: OFF (default) → isolate=False; ON → isolate=True. This
    is the A/B harness AND the fleet gate (the pool param ships only when on)."""
    import db
    # Default OFF → no isolation.
    client.post("/api/reference", files=_upload())
    assert no_gpu[-1]["isolate"] is False
    # Flip the flag ON → the next upload isolates.
    db.set_setting("upload_isolate", "true")
    client.post("/api/reference", files=_upload())
    assert no_gpu[-1]["isolate"] is True
    # Flip it back OFF → isolation stops.
    db.set_setting("upload_isolate", "false")
    client.post("/api/reference", files=_upload())
    assert no_gpu[-1]["isolate"] is False


def test_upload_of_a_person_is_captioned_not_rejected(client, no_gpu, app_mod, monkeypatch):
    """The subject may be a PERSON, not only an animal (users animate themselves and
    other people): triage passes a person and the captioner names them, so the noun
    prefills and the redraw draws a person — not a fallback to 'pet'."""
    _mock_caption(app_mod, monkeypatch, subject="woman", features="long brown hair, red shirt")
    body = client.post("/api/reference", files=_upload()).json()
    assert body["suggested_subject"] == "woman"
    assert body["description"] == "woman"
    assert no_gpu[-1]["description"] == "woman, long brown hair, red shirt"


def test_typed_noun_wins_and_skips_the_ai(client, no_gpu, app_mod, monkeypatch):
    """decision 3 — the human's word wins: a typed noun is used verbatim and the AI
    is not consulted at all (no suggestion, no cue)."""
    _mock_caption(app_mod, monkeypatch)
    body = client.post("/api/reference", data={"animal": "corgi"}, files=_upload()).json()
    assert body["suggested_subject"] is None
    assert body["description"] == "corgi"
    assert no_gpu[-1]["description"] == "corgi"


def test_not_a_subject_degrades_to_the_manual_field(client, no_gpu, app_mod, monkeypatch):
    """Triage gates: a screenshot (is_subject False) degrades to today's behaviour —
    no suggestion, subject 'pet' — never a confident wrong caption."""
    _mock_caption(app_mod, monkeypatch, is_subject=False)
    body = client.post("/api/reference", files=_upload()).json()
    assert body["suggested_subject"] is None
    assert body["description"] == "pet"


def test_captioner_is_inert_without_a_key(client, no_gpu, monkeypatch):
    """No key → the captioner never runs; an empty-field upload behaves exactly as
    before (subject 'pet'). The engine stays optional — the door works turned off."""
    monkeypatch.delenv("DATSPET_AI_API_KEY", raising=False)
    body = client.post("/api/reference", files=_upload()).json()
    assert body["suggested_subject"] is None
    assert body["description"] == "pet"


def test_ai_toggle_off_skips_the_captioner_even_on_an_empty_field(client, no_gpu, app_mod, monkeypatch):
    """The 'AI enabled' toggle turned OFF sends ai_caption=false. Even with the engine
    configured AND an empty noun field, the captioner must NOT run — an empty field
    draws 'pet'. The toggle disables the server captioner, not just the UI field."""
    _mock_caption(app_mod, monkeypatch)  # engine on + mocked, but the flag gates it off
    body = client.post("/api/reference",
                       data={"ai_caption": "false"}, files=_upload()).json()
    assert body["suggested_subject"] is None
    assert body["description"] == "pet"


def test_ai_toggle_off_uses_the_typed_noun(client, no_gpu, app_mod, monkeypatch):
    """Toggle off + a typed noun → the user's word is used, the AI is not consulted."""
    _mock_caption(app_mod, monkeypatch)
    body = client.post("/api/reference",
                       data={"ai_caption": "false", "animal": "corgi"}, files=_upload()).json()
    assert body["suggested_subject"] is None
    assert body["description"] == "corgi"


# ── the exactly-one-source guard (§7.4) ──────────────────────────────────────

def test_catalog_plus_upload_is_refused(client, no_gpu):
    """The hole this closes for free: today start_job guards base_pet_id+image but
    NOT catalog_*+image, and its elif chain lets catalog silently win and DROP the
    upload. One guard at the fill point closes every pair by construction."""
    r = client.post("/api/reference",
                    data={"catalog_animal": "cat", "catalog_breed": "tabby"},
                    files=_upload())
    assert r.status_code == 400
    assert no_gpu == []


def test_catalog_plus_free_text_animal_is_refused(client, no_gpu):
    r = client.post("/api/reference", data={
        "catalog_animal": "cat", "catalog_breed": "tabby", "animal": "blue jay"})
    assert r.status_code == 400


def test_no_source_at_all_is_refused(client, no_gpu):
    r = client.post("/api/reference", data={})
    assert r.status_code == 400


def test_unknown_catalog_breed_404s(client, no_gpu):
    r = client.post("/api/reference", data={"catalog_animal": "cat", "catalog_breed": "nope"})
    assert r.status_code == 404


def test_bad_mime_is_refused(client, no_gpu):
    r = client.post("/api/reference", files={"image": ("x.txt", io.BytesIO(b"nope"), "text/plain")})
    assert r.status_code == 400
    assert no_gpu == []


def test_oversize_upload_is_refused(client, no_gpu, app_mod, monkeypatch):
    monkeypatch.setattr(app_mod, "MAX_UPLOAD_BYTES", 10)
    r = client.post("/api/reference", files=_upload())
    assert r.status_code == 413


# ── the record + the store (§7.3) ────────────────────────────────────────────

def test_reference_png_round_trips(client, no_gpu):
    ref = client.post("/api/reference", data={"animal": "blue jay"}).json()
    r = client.get(ref["image_url"])
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"


def test_expired_reference_400s_rather_than_500s(client, no_gpu):
    """§7.3: the sweep is 24 h and a user can outlive it. They get told to start
    over — never a stack trace."""
    r = client.post("/api/generate", data={"reference_id": "deadbeef0000"})
    assert r.status_code == 400
    assert "expired" in r.json()["detail"].lower()


def test_malformed_reference_id_404s(client, no_gpu):
    assert client.get("/api/reference/not-alnum!.png").status_code == 404


def test_body_shapes_endpoint_never_leaks_prompt_wording(client):
    """§7.2 — the same posture as the tier table: the browser learns its options,
    never the calibrated wording behind them."""
    body = client.get("/api/body-shapes").json()
    assert body["default"] == "normal"
    assert {s["key"] for s in body["shapes"]} == {"thin", "normal", "fat"}
    for s in body["shapes"]:
        assert set(s) == {"key", "label", "is_default"}


# ── generate reads the record, never the origin (§6) ─────────────────────────

def test_generate_animates_the_reference_as_is(client, no_gpu, app_mod, monkeypatch):
    """§1: the web tier ALWAYS uses the engine's as-is branch, because the still was
    already approved. Redrawing at build time would re-roll the look after the user
    said yes to it."""
    seen = {}

    def fake_thread(target=None, args=(), kwargs=None, daemon=None):
        seen.update(kwargs or {})

        class _T:
            def start(self): pass
        return _T()

    ref = client.post("/api/reference", data={"catalog_animal": "cat",
                                              "catalog_breed": "tabby"}).json()
    monkeypatch.setattr(app_mod.threading, "Thread", fake_thread)
    r = client.post("/api/generate", data={"reference_id": ref["reference_id"]})
    assert r.status_code == 200, r.text
    assert seen["remix_strength"] is None, "the reference path must never redraw"
    assert seen["reference_image"] is not None
    # Resolved at FILL time and carried on the record — not re-derived here.
    assert seen["motion_profile"] == ref["motion_profile"]
    assert seen["description"] == "tabby"


def test_generate_description_is_the_short_species_phrase(client, no_gpu, app_mod, monkeypatch):
    """§7.3: the record carries "purple corgi", not the ~240-char composed design
    string. Generate is always as-is now, so this steers only the motion prompts, the
    breed_id slug and the default name — and make_pet_zip truncates it at [:60], which
    is what would silently break the §5.1 parity contract if it were the long one."""
    seen = {}

    def fake_thread(target=None, args=(), kwargs=None, daemon=None):
        seen.update(kwargs or {})

        class _T:
            def start(self): pass
        return _T()

    ref = client.post("/api/reference", data={"catalog_animal": "dog",
                                              "catalog_breed": "corgi"}).json()
    preview = client.post("/api/preview", data={
        "reference_id": ref["reference_id"], "color": "purple",
        "accessories": "wizard hat", "body_shape": "fat"}).json()

    assert preview["description"] == "purple corgi"
    assert len(preview["description"]) < 60

    monkeypatch.setattr(app_mod.threading, "Thread", fake_thread)
    client.post("/api/generate", data={"reference_id": preview["reference_id"]})
    assert seen["description"] == "purple corgi"


# ── preview: a reference in, a reference out (§6.1) ──────────────────────────

def test_preview_takes_a_reference_and_returns_a_reference(client, no_gpu):
    ref = client.post("/api/reference", data={"catalog_animal": "cat",
                                              "catalog_breed": "tabby"}).json()
    out = client.post("/api/preview", data={"reference_id": ref["reference_id"],
                                            "color": "purple"}).json()
    assert set(out) == set(ref), "one record shape, or the frontend must branch on which it holds"
    assert out["reference_id"] != ref["reference_id"], "a design mints a NEW reference"
    assert out["source"] == "design"


def test_preview_composes_shape_into_the_design_not_the_archetype(client, no_gpu):
    """The rule, observed end-to-end: the shape fragment must appear in the REDRAW
    prompt (step 2), and the archetype it redraws must be the untouched curated base."""
    ref = client.post("/api/reference", data={"catalog_animal": "dog",
                                              "catalog_breed": "corgi"}).json()
    assert no_gpu == []                      # step 1 was free

    client.post("/api/preview", data={"reference_id": ref["reference_id"],
                                      "body_shape": "fat", "color": "purple"})
    assert len(no_gpu) == 1
    assert "chubby and round" in no_gpu[0]["description"]
    assert no_gpu[0]["reference_path"] is not None, "step 2 redraws the archetype"


def test_preview_refuses_an_empty_design(client, no_gpu):
    """§4.1, widened for shape and free text: designing nothing is ADOPTING, and the
    zero-GPU adopt path exists for that."""
    ref = client.post("/api/reference", data={"animal": "blue jay"}).json()
    r = client.post("/api/preview", data={"reference_id": ref["reference_id"],
                                          "body_shape": "normal"})
    assert r.status_code == 400


def test_preview_has_no_source_exception(client, no_gpu):
    """§4.2 — Rev.1 relaxed this guard when source == "txt2img", which is a branch on
    where the record came from: its own §0 rule, violated. A txt2img archetype is an
    archetype like any other, so it needs a design like any other."""
    ref = client.post("/api/reference", data={"animal": "dragon"}).json()
    assert ref["source"] == "txt2img"
    assert client.post("/api/preview", data={"reference_id": ref["reference_id"]}).status_code == 400
    ok = client.post("/api/preview", data={"reference_id": ref["reference_id"],
                                           "color": "purple"})
    assert ok.status_code == 200


def test_free_text_reaches_the_prompt(client, no_gpu):
    """Decision #4 — the unbounded escape hatch that makes the §4.6 palette trim safe."""
    ref = client.post("/api/reference", data={"animal": "dragon"}).json()
    assert no_gpu[-1]["description"] == "dragon", \
        "step 1 drew the ARCHETYPE — no design in the archetype prompt (§0.1)"

    client.post("/api/preview", data={"reference_id": ref["reference_id"],
                                      "extra": "made of clockwork gears"})
    # [-1] is the preview: the long-tail door already spent a render on the archetype.
    assert "made of clockwork gears" in no_gpu[-1]["description"]


def test_shape_change_forces_full_strength(client, no_gpu):
    """§4.4 reason 3: a silhouette change fights the source exactly like a conflicting
    colour word does, so it uses the same trigger. The curated corgi is normal-shaped
    and would win at a gentle denoise."""
    ref = client.post("/api/reference", data={"catalog_animal": "dog",
                                              "catalog_breed": "corgi"}).json()
    out = client.post("/api/preview", data={"reference_id": ref["reference_id"],
                                            "body_shape": "fat", "strength": 0.3}).json()
    assert no_gpu[0]["strength"] == 0.9
    assert out["min_strength"] == 0.9, "the record must carry the clamp so the UI can show it"


# ── owner scoping (§7.3) ─────────────────────────────────────────────────────

def test_reference_is_owner_scoped(client, no_gpu, app_mod, monkeypatch):
    """A reference can now be a user's uploaded PHOTO. GET /api/preview/{id} has no
    ownership check today; its replacement must have the rule rows get — and 404, not
    403, so it never confirms the id exists."""
    monkeypatch.setattr(app_mod.datsme_integration, "resolve_launch_identity",
                        lambda request: "user-a")
    ref = client.post("/api/reference", data={"animal": "blue jay"}).json()

    monkeypatch.setattr(app_mod.datsme_integration, "resolve_launch_identity",
                        lambda request: "user-b")
    assert client.get(ref["image_url"]).status_code == 404
    assert client.post("/api/generate",
                       data={"reference_id": ref["reference_id"]}).status_code == 404
    assert client.post("/api/preview", data={"reference_id": ref["reference_id"],
                                             "color": "purple"}).status_code == 404


def test_standalone_references_stay_readable(client, no_gpu):
    """owner is None for a standalone caller — unowned content is visible, mirroring
    _can_access. Scoping must not lock the standalone user out of their own box."""
    ref = client.post("/api/reference", data={"animal": "blue jay"}).json()
    assert client.get(ref["image_url"]).status_code == 200


def test_padded_reference_id_never_500s(client, no_gpu):
    """The PNG endpoint's whole contract is "404, and nothing else" (§7.3) — and it was
    the one endpoint that could 500.

    _load_reference validates the STRIPPED id, but this endpoint rebuilt the path from
    the RAW param: " abc" passed validation, then FileResponse was handed a path that
    does not exist → unhandled 500. Not a scoping bypass (the owner check ran on the
    stripped id), but a 500 on the endpoint that promised it could not produce one.

    Stripping is the ESTABLISHED contract, not a new leniency: /api/preview and
    /api/generate both accept a padded id and 200 today, because they read the id back
    off the record (`ref["id"]`) instead of trusting the param. This endpoint was the
    odd one out; now it agrees. The point of the test is that NOTHING here 500s.
    """
    ref = client.post("/api/reference", data={"catalog_animal": "cat",
                                              "catalog_breed": "tabby"}).json()
    rid = ref["reference_id"]
    assert client.get(f"/api/reference/{rid}.png").status_code == 200

    for padded in (f"%20{rid}", f"{rid}%20", f"%09{rid}"):
        code = client.get(f"/api/reference/{padded}.png").status_code
        assert code != 500, f"{padded!r} 500s — the raw param reached the path again"
        assert code == 200, f"{padded!r} gave {code}; strip is the contract (preview/generate agree)"

    # A genuinely absent id is still the honest 404 — stripping must not turn "missing"
    # into "found".
    assert client.get("/api/reference/deadbeef0000.png").status_code == 404
    assert client.get("/api/reference/not-alnum!.png").status_code == 404
