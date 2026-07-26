"""Golden pins for the prompt sentence templates (pet_factory/prompt_templates.py).

The templates were extracted out of factory.py so the GPU-less web tier can read them
for the admin's prompt preview. Two things must stay true after that move:

  (a) The rendered sentences are byte-identical to what the factory sent before —
      a wording change re-rolls every pet's look, so it has to be deliberate enough
      to update this file.
  (b) There is ONE definition of each sentence. `factory._base_prompt` must BE the
      shared function, not a second copy that drifts from it.

(`animal_catalog/generate_candidates.py` keeps its own deliberately different curation
prompt — "full body, centered", no pastel clause — and is not covered here.)
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from pet_factory import motion_profiles as mp          # noqa: E402
from pet_factory import prompt_templates as pt         # noqa: E402

BASE_GOLDEN = (
    "a cute cartoon red dragon, side profile view, facing right, standing, "
    "soft pastel colors, muted palette, simple flat shading, white background, "
    "storybook style"
)
REMIX_GOLDEN = (
    "a cute cartoon purple corgi, exactly purple corgi, side profile view, "
    "facing right, standing, rich saturated colors, simple flat shading, "
    "white background, storybook style"
)


def test_base_still_prompt_is_unchanged():
    assert pt.base_still_prompt("red dragon") == BASE_GOLDEN


def test_remix_still_prompt_is_unchanged():
    assert pt.remix_still_prompt("purple corgi") == REMIX_GOLDEN


def test_pose_clause_replaces_only_the_posture():
    """The anchor is the SAME sentence as the base with one slot swapped — that
    sameness is what keeps the fly anchor and the walk anchor the same animal."""
    base = pt.base_still_prompt("red dragon")
    anchor = pt.base_still_prompt("red dragon", "wings fully extended mid-beat")
    assert anchor == base.replace("standing", "wings fully extended mid-beat")


def test_factory_delegates_rather_than_redefining():
    """One definition, not one per consumer — the whole reason for the module."""
    from pet_factory import factory
    assert factory._base_prompt is pt.base_still_prompt
    assert factory._remix_prompt is pt.remix_still_prompt


def test_samplers_run_at_cfg_one_which_is_why_there_is_no_negative_prompt():
    """The load-bearing guard behind removing the negative prompt.

    Classifier-free guidance is `negative + cfg * (positive - negative)`; at cfg 1.0
    that is exactly `positive` and the negative conditioning cancels out. Both models
    are distilled and trained for cfg 1 (Z-Image-Turbo 8-step, Wan + LightX2V 4-step).

    MEASURED on the GPU box, 2026-07-26: one seed, one positive prompt, three negatives
    (the authored one, empty, and one naming the subject itself) → byte-identical PIXELS
    in all three, while changing the POSITIVE changed them. So the negative was deleted
    rather than made per-species.

    If a future model raises cfg above 1.0 this test goes red — which is the signal that
    negatives are live again and the question "should it vary per animal?" (primates have
    hands; the old negative banned them) has to be answered for real.
    """
    from pet_factory import factory
    still = factory._static_image_wf("a prompt", 1)
    remix = factory._img2img_wf("a prompt", "/tmp/x.png", 1)
    loop = factory._loop_wf("a prompt", "/tmp/x.png", 1)
    assert still["9"]["inputs"]["cfg"] == 1.0
    assert remix["9"]["inputs"]["cfg"] == 1.0
    assert loop["13"]["inputs"]["cfg"] == 1.0
    assert loop["14"]["inputs"]["cfg"] == 1.0
    # ...and while cfg is 1.0, every negative conditioning input stays empty. The nodes
    # themselves must remain: ComfyUI's samplers require a `negative` input.
    assert still["7"]["inputs"]["text"] == ""
    assert remix["7"]["inputs"]["text"] == ""
    assert loop["11"]["inputs"]["text"] == ""


def test_no_negative_prompt_constant_survives():
    """The removal has to be complete: a leftover NEG would be exactly the silent,
    looks-live-but-isn't value the deletion was about."""
    from pet_factory import factory
    assert not hasattr(pt, "STILL_NEGATIVE")
    assert not hasattr(pt, "MOTION_NEGATIVE")
    assert not hasattr(factory, "NEG")
    assert not hasattr(factory, "MOTION_NEG")


def test_motion_template_composes_the_same_prompt_as_before():
    """MOTION_PROMPT_TEMPLATE became a named constant so the admin preview can render
    it; compose_pose_prompt must still emit the identical string."""
    profile = mp.resolve_motion_profile("red dragon")
    walk = profile.pose("walk")
    assert mp.compose_pose_prompt("red dragon", walk) == (
        f"cute cartoon red dragon {walk.action}, side profile, facing right{walk.suffix}"
    )


def test_templates_import_without_the_ml_stack():
    """prompt_templates is read by webui on a box where numpy/PIL are absent, so it
    must carry no ML dependency of its own (the deploy gate is `import numpy` failing)."""
    import pet_factory.prompt_templates as module
    src = open(module.__file__).read()
    for banned in ("import numpy", "import PIL", "from PIL", "import torch", "import rembg"):
        assert banned not in src
