"""Base-sprite selector pins (SPEC_PET_DESIGNER_FLOW §7.1, §10.2).

`_base_sprite` is the ONE place the pipeline's starting image is decided. Both
entry points route through it:

    render_design_still(...)  → _base_sprite(...)   # the ~10 s design still
    make_pet_zip(...)         → _base_sprite(...)   # the 3-min build's base stage

The headline test here is **the parity pin** (§5.1):

    "The previewed still IS the base sprite make_pet_zip would have produced."

Before the refactor that contract was held by DUPLICATION — factory.py repeated the
prep + clamp + _img2img_wf(_remix_prompt(...)) sequence in two places, and two copies
of a contract drift. Now it is structural, and this file is what keeps it that way: if
someone re-forks the base-image logic, the parity test fails.

Zero-GPU — `_run` is stubbed to capture the workflow ComfyUI *would* have received,
which is the thing actually worth asserting on.
"""
import copy

import pytest
from PIL import Image

from pet_factory import factory

FIXED_SEED = 424242


class _StopAfterBase(Exception):
    """Raised from the stubbed _run to abort make_pet_zip once its base stage has
    handed us the workflow — we want the base stage, not a 3-minute build."""


@pytest.fixture
def reference_png(tmp_path):
    """A real on-disk image: _prep_reference_image opens it with PIL for real."""
    path = tmp_path / "ref.png"
    Image.new("RGB", (640, 480), (120, 180, 90)).save(path)
    return path


@pytest.fixture
def capture_workflow(monkeypatch, tmp_path):
    """Run a callable and return the workflow dict handed to the FIRST _run call.

    Stubs the three things that would otherwise need a GPU, a clock, or a random:
      - _run              → capture + abort
      - _wait_stable      → no-op (it polls a file that will never appear)
      - random.randint    → FIXED_SEED, so make_pet_zip (which mints its own seed
                            internally and takes no seed param) matches an injected one
      - _prep_reference_image → a FIXED path. It mkstemps a fresh file per call, so
                            two runs would differ on the image path alone — an
                            incidental difference that would mask the real ones
                            (prompt builder, seed, denoise, workflow shape).
    """
    prepped = tmp_path / "prepped.png"
    Image.new("RGB", (640, 640), (255, 255, 255)).save(prepped)

    def run(fn):
        seen = []

        def fake_run(wf, timeout=360):
            seen.append(copy.deepcopy(wf))
            raise _StopAfterBase

        monkeypatch.setattr(factory, "_run", fake_run)
        monkeypatch.setattr(factory, "_wait_stable", lambda *a, **k: None)
        monkeypatch.setattr(factory, "_prep_reference_image", lambda src: prepped)
        monkeypatch.setattr(factory.random, "randint", lambda a, b: FIXED_SEED)
        try:
            fn()
        except _StopAfterBase:
            pass
        assert seen, "no workflow was submitted"
        return seen[0]

    return run


# ── the parity pin — this IS §5.1 ────────────────────────────────────────────

def test_design_still_and_build_base_stage_are_byte_identical(capture_workflow, reference_png):
    """§5.1: for identical args + seed, the still the user approves and the base
    sprite the build starts from are the SAME workflow, down to the byte."""
    # Short on purpose: make_pet_zip truncates `animal` at [:60] and
    # render_design_still does not, so parity only holds for the short species
    # phrase §7.3 requires the reference record to carry. A 240-char composed
    # design string would silently break this contract — that is the point.
    animal = "purple corgi"

    still_wf = capture_workflow(
        lambda: factory.render_design_still(animal, reference_png, 0.85, seed=FIXED_SEED)
    )
    build_wf = capture_workflow(
        lambda: factory.make_pet_zip(animal, reference_image=reference_png, remix_strength=0.85)
    )

    assert still_wf == build_wf


def test_parity_holds_for_the_text_branch_too(capture_workflow):
    """The long-tail archetype (§3.3): no reference on either side."""
    still_wf = capture_workflow(
        lambda: factory.render_design_still("blue jay", seed=FIXED_SEED)
    )
    build_wf = capture_workflow(lambda: factory.make_pet_zip("blue jay"))
    assert still_wf == build_wf


# ── branch selection ─────────────────────────────────────────────────────────

def test_no_reference_takes_the_text_branch(capture_workflow):
    wf = capture_workflow(lambda: factory.render_design_still("blue jay", seed=FIXED_SEED))
    classes = {node["class_type"] for node in wf.values()}
    assert "EmptySD3LatentImage" in classes      # txt2img: latent from nothing
    assert "VHS_LoadImagePath" not in classes    # …and no source image
    assert wf["6"]["inputs"]["text"] == factory._base_prompt("blue jay")
    assert wf["9"]["inputs"]["seed"] == FIXED_SEED


def test_reference_plus_strength_takes_the_remix_branch(capture_workflow, reference_png):
    wf = capture_workflow(
        lambda: factory.render_design_still("purple corgi", reference_png, 0.85, seed=FIXED_SEED)
    )
    classes = {node["class_type"] for node in wf.values()}
    assert "VHS_LoadImagePath" in classes        # img2img: latent from the reference
    assert "EmptySD3LatentImage" not in classes
    # _remix_prompt, NOT _base_prompt — the design applier, not the archetype
    # drawer (§0.2). Swapping these silently ruins every recolor.
    assert wf["6"]["inputs"]["text"] == factory._remix_prompt("purple corgi")
    assert wf["6"]["inputs"]["text"] != factory._base_prompt("purple corgi")


def test_reference_alone_is_as_is_and_never_reaches_comfyui(monkeypatch, reference_png):
    """make_pet_zip's as-is branch: animate the reference exactly, no redraw.
    This is the branch the whole flow relies on — generate always runs it (§1)."""
    def explode(*a, **k):
        raise AssertionError("as-is must not submit a workflow")

    monkeypatch.setattr(factory, "_run", explode)
    out = factory._base_sprite("corgi", reference_image=reference_png)
    assert out.exists()


# ── the denoise clamp ────────────────────────────────────────────────────────

@pytest.mark.parametrize("strength,expected", [
    (0.1, 0.3),     # below the floor → floor
    (5.0, 0.9),     # above the ceiling → ceiling
    (0.85, 0.85),   # in range → untouched
])
def test_strength_is_clamped_to_the_calibrated_range(capture_workflow, reference_png,
                                                     strength, expected):
    wf = capture_workflow(
        lambda: factory.render_design_still("corgi", reference_png, strength, seed=FIXED_SEED)
    )
    assert wf["9"]["inputs"]["denoise"] == expected


# ── the guard ────────────────────────────────────────────────────────────────

def test_still_renderer_refuses_as_is(reference_png):
    """§7.1: as-is is meaningless for a *still* renderer — it would hand the caller
    back the bytes they already have. Only the animator has a use for that branch."""
    with pytest.raises(ValueError, match="requires a strength"):
        factory.render_design_still("corgi", reference_png)
