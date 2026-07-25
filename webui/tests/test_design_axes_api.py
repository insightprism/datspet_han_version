"""The design-axes web surface (SPEC_PET_DESIGN_AXES §3/§4/§10).

Endpoint gating: the SERVER owns surface filtering — a bird is offered plumage
and never coat, an unknown creature only the universal axes, and the browser
renders what it is handed. Plus the axis_picks contract on /api/preview:
registry-driven validation, never-raises robustness, and the widened
"designing nothing is adopting" guard.

Zero-GPU: _render_still is stubbed, same as test_reference_flow.
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
    calls = []

    def fake_render(description, request, owner, reference_path=None, strength=None,
                    isolate=False, base_pose="standing"):
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


def _axes_for(client, reference_id=""):
    qs = f"?reference_id={reference_id}" if reference_id else ""
    r = client.get(f"/api/design-axes{qs}")
    assert r.status_code == 200, r.text
    return {a["axis"]: a for a in r.json()["axes"]}


# ── endpoint gating (§4/§10) ─────────────────────────────────────────────────

def test_a_catalog_cat_is_offered_coat_never_plumage(client, no_gpu):
    ref = client.post("/api/reference", data={"catalog_animal": "cat",
                                              "catalog_breed": "tabby"}).json()
    axes = _axes_for(client, ref["reference_id"])
    assert "coat" in axes and "body" in axes and "pattern" in axes and "expression" in axes
    assert "plumage" not in axes and "scales" not in axes


def test_a_typed_bird_is_offered_plumage_never_coat(client, no_gpu):
    """§3.2: 'a blue jay' keyword-resolves to feathers at FILL time."""
    ref = client.post("/api/reference", data={"animal": "blue jay"}).json()
    axes = _axes_for(client, ref["reference_id"])
    assert "plumage" in axes
    assert "coat" not in axes and "scales" not in axes


def test_an_unknown_creature_gets_universal_axes_only(client, no_gpu):
    """§3.3 — the clockwork octopus: two of the three Tier 1 controls stay;
    only the surface-specific one is withheld. Never a wrong option."""
    ref = client.post("/api/reference", data={"animal": "a clockwork octopus"}).json()
    axes = _axes_for(client, ref["reference_id"])
    assert set(axes) == {"body", "pattern", "expression"}


def test_an_upload_without_a_name_gets_universal_axes_only(client, no_gpu):
    """§3.4: a photo carries no reliable surface signal."""
    ref = client.post("/api/reference", files=_upload()).json()
    assert set(_axes_for(client, ref["reference_id"])) == {"body", "pattern", "expression"}


def test_an_upload_with_a_typed_name_promotes_via_the_keyword_map(client, no_gpu):
    ref = client.post("/api/reference", data={"animal": "penguin"}, files=_upload()).json()
    assert "plumage" in _axes_for(client, ref["reference_id"])


def test_no_reference_id_degrades_to_universal_axes(client):
    assert set(_axes_for(client)) == {"body", "pattern", "expression"}
    assert set(_axes_for(client, "deadbeef0000")) == {"body", "pattern", "expression"}


def test_design_axes_never_serializes_a_prompt_fragment(client, no_gpu):
    ref = client.post("/api/reference", data={"animal": "dragon"}).json()
    for axes in (_axes_for(client), _axes_for(client, ref["reference_id"])):
        for a in axes.values():
            assert set(a) == {"axis", "label", "kind", "default", "options"}
            for o in a["options"]:
                assert set(o) == {"key", "label", "is_default"}


def test_a_design_preview_keeps_the_surface(client, no_gpu):
    """§3: the surface rides the reference chain like motion_profile does — a
    design never changes the animal, so the redesigned bird still sees plumage."""
    ref = client.post("/api/reference", data={"animal": "blue jay"}).json()
    out = client.post("/api/preview", data={"reference_id": ref["reference_id"],
                                            "color": "purple"}).json()
    assert "plumage" in _axes_for(client, out["reference_id"])
    # SPEC_UPLOAD_LIKENESS §2.2 — the OTHER half of "one call site": step 2's preview
    # redraws an already-clean sprite, so it must NOT isolate (a cutout there is wasted
    # work and a real risk of eating the subject). The preview call is the last one.
    assert no_gpu[-1]["isolate"] is False, "the preview must not run subject isolation"


# ── axis_picks on /api/preview (§4) ──────────────────────────────────────────

def test_axis_picks_compose_into_the_redraw_prompt(client, no_gpu):
    ref = client.post("/api/reference", data={"catalog_animal": "dog",
                                              "catalog_breed": "corgi"}).json()
    r = client.post("/api/preview", data={
        "reference_id": ref["reference_id"],
        "axis_picks": '{"body": "fat", "pattern": "spotted", "coat": "fluffy", '
                      '"expression": "grumpy"}'})
    assert r.status_code == 200, r.text
    prompt = no_gpu[-1]["description"]
    assert "chubby and round" in prompt
    assert "spotted" in prompt
    assert "with fluffy fur" in prompt
    assert "grumpy" in prompt


def test_a_surface_pick_that_mismatches_the_animal_is_ignored(client, no_gpu):
    """§4 defense in depth: the menu already hid plumage from a corgi; a
    hand-crafted request must not get further."""
    ref = client.post("/api/reference", data={"catalog_animal": "dog",
                                              "catalog_breed": "corgi"}).json()
    r = client.post("/api/preview", data={
        "reference_id": ref["reference_id"],
        "axis_picks": '{"plumage": "ruffled"}'})
    assert r.status_code == 400, "a filtered-out pick is not a design"
    ok = client.post("/api/preview", data={
        "reference_id": ref["reference_id"],
        "axis_picks": '{"plumage": "ruffled", "pattern": "striped"}'})
    assert ok.status_code == 200
    assert "ruffled" not in no_gpu[-1]["description"]
    assert "striped" in no_gpu[-1]["description"]


def test_malformed_axis_picks_never_500(client, no_gpu):
    """The never-raises posture at the endpoint: garbage degrades to 'no
    picks' (a 400 for an empty design), not a 500."""
    ref = client.post("/api/reference", data={"animal": "blue jay"}).json()
    for garbage in ("not json", '["a","list"]', '{"pattern": 7}', '{"a": {"b": 1}}'):
        r = client.post("/api/preview", data={"reference_id": ref["reference_id"],
                                              "axis_picks": garbage})
        assert r.status_code == 400, f"{garbage!r} → {r.status_code}"


def test_a_non_default_axis_pick_alone_is_a_design(client, no_gpu):
    """§4: the 'designing nothing is adopting' guard widened — a pattern pick
    with no colour/accessory/shape/text is a real design; a default pick or a
    typo is not."""
    ref = client.post("/api/reference", data={"animal": "blue jay"}).json()
    ok = client.post("/api/preview", data={"reference_id": ref["reference_id"],
                                           "axis_picks": '{"expression": "grumpy"}'})
    assert ok.status_code == 200
    for non_design in ('{"expression": "neutral"}', '{"pattern": "no_such_option"}',
                       '{"no_such_axis": "spotted"}'):
        r = client.post("/api/preview", data={"reference_id": ref["reference_id"],
                                              "axis_picks": non_design})
        assert r.status_code == 400, f"{non_design!r} claimed to be a design"


def test_body_shape_field_stays_an_alias_for_one_cycle(client, no_gpu):
    """§4: the old body_shape Form field aliases axis_picks['body'] — an
    already-shipped frontend keeps working through the deprecation cycle. An
    explicit axis_picks body wins over the alias."""
    ref = client.post("/api/reference", data={"catalog_animal": "dog",
                                              "catalog_breed": "corgi"}).json()
    r = client.post("/api/preview", data={"reference_id": ref["reference_id"],
                                          "body_shape": "fat"})
    assert r.status_code == 200
    assert "chubby and round" in no_gpu[-1]["description"]

    client.post("/api/preview", data={"reference_id": ref["reference_id"],
                                      "body_shape": "fat",
                                      "axis_picks": '{"body": "thin"}'})
    assert "slender and slim" in no_gpu[-1]["description"]
    assert "chubby" not in no_gpu[-1]["description"]


def test_an_axis_min_strength_clamps_like_body_always_did(client, no_gpu):
    """The silhouette rule, now data (§2/§6): body.json declares 0.9 and the
    clamp must survive the migration — asserted here end-to-end and in the
    golden test at the composer."""
    ref = client.post("/api/reference", data={"catalog_animal": "dog",
                                              "catalog_breed": "corgi"}).json()
    out = client.post("/api/preview", data={"reference_id": ref["reference_id"],
                                            "axis_picks": '{"body": "fat"}',
                                            "strength": 0.3}).json()
    assert no_gpu[-1]["strength"] == 0.9
    assert out["min_strength"] == 0.9
