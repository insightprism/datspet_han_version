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

# UPDATED 2026-07-27 for SPEC_MATTE_BACKDROP: `white background` -> `flat vivid cyan
# background`. This file existing is what made that a deliberate act rather than a silent
# re-roll of every pet — which is exactly its job (see (a) above). The backdrop is now a
# named constant, so these pins carry it by reference: a future hue change fails the
# `pt.STILL_BACKDROP in ...` assertions in test_cutout_hygiene rather than here.
BASE_GOLDEN = (
    "a cute cartoon red dragon, side profile view, facing right, standing, "
    "soft pastel colors, muted palette, simple flat shading, "
    + pt.STILL_BACKDROP + ", storybook style"
)
REMIX_GOLDEN = (
    "a cute cartoon purple corgi, exactly purple corgi, side profile view, "
    "facing right, standing, rich saturated colors, simple flat shading, "
    + pt.STILL_BACKDROP + ", storybook style"
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


# ── SPEC_MATTE_BACKDROP: ONE owner for the backdrop ──────────────────────────────────────

def test_the_backdrop_is_defined_in_exactly_one_module():
    """The backdrop existed in FIVE places before this was consolidated: both still
    templates, `factory._prep_reference_image`'s white pad, and a curation sentence
    duplicated verbatim in generate_candidates.py and generate_sample.py — the last two
    hardcoding "plain white background" where nothing would have caught them (this file's
    own docstring used to exempt them).

    So this walks the package and fails if a background phrase is written anywhere except
    `prompt_templates`. A backdrop split across modules is a backdrop that will eventually
    disagree with itself, and the failure mode is silent: a pet drawn on the wrong field."""
    import re
    from pathlib import Path

    pkg = Path(pt.__file__).resolve().parent
    owner = Path(pt.__file__).resolve()
    phrase = re.compile(r"\b(?:white|cyan|teal|grey|gray|green|magenta)\s+background\b", re.I)
    offenders = []
    for path in pkg.rglob("*.py"):
        if path.resolve() == owner or "tests" in path.parts or "__pycache__" in path.parts:
            continue
        for n, line in enumerate(path.read_text().splitlines(), 1):
            code = line.split("#")[0]                      # prose in comments is fine
            if phrase.search(code):
                offenders.append(f"{path.relative_to(pkg)}:{n}: {line.strip()}")
    assert not offenders, (
        "a background phrase is hardcoded outside prompt_templates:\n  " + "\n  ".join(offenders))


def test_the_pixel_backdrop_is_re_exported_not_redefined():
    """§9 I5 — `factory.STILL_BACKDROP_RGB` must BE the one in prompt_templates, not a
    second tuple that happens to match today. Identity, not equality: two equal literals
    drift the moment one of them is edited."""
    from pet_factory import factory
    assert factory.STILL_BACKDROP_RGB is pt.STILL_BACKDROP_RGB


def test_the_curation_prompt_carries_no_backdrop_of_its_own():
    """The curation sentence is passed as the `animal` of a real build, so a template wraps
    it and supplies the backdrop. A background clause here would put TWO backdrops in one
    prompt — which is what both curation scripts used to do."""
    rendered = pt.curation_still_prompt("tabby cat")
    assert "background" not in rendered, f"the curation prompt names a backdrop: {rendered!r}"
    # …and it is what the templates wrap, so the pair composes to exactly one backdrop.
    wrapped = pt.base_still_prompt(rendered)
    assert wrapped.count("background") == 1
