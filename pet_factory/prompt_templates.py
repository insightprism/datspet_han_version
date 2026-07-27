"""prompt_templates — the still-prompt sentence templates, as pure data.

The anchor/base still prompt is *template + content*: this module owns the template
(the house style — cartoon, side profile, flat shading, the backdrop), while the
motion profile owns the `{pose}` clause and the caller owns `{animal}`. Splitting them
is the engine-vs-content line: the style is identical for every animal and every pose,
the posture is per-body-type content that grows a file at a time.

Extracted from factory.py so the GPU-less web tier can READ the templates without
importing numpy/PIL — the motion admin's prompt preview shows an author the exact
string their clause lands in (SPEC_MOTION_PROFILE_ADMIN §5). Pure strings, no imports,
no ML dependency: this module must stay importable on a box with no GPU stack.

`factory._base_prompt` / `_remix_prompt` remain the generation-side entry points and
delegate here, so there is ONE definition of each sentence, not one per consumer.

The companion motion-prompt template lives in `motion_profiles.MOTION_PROMPT_TEMPLATE`
(already pure), next to the action/suffix content it interpolates.
"""
from __future__ import annotations

# The posture word the still is drawn in when a profile/pose supplies none.
# A profile overrides it with `base_pose`; a pose overrides that with its
# `control.pose` anchor clause.
DEFAULT_POSE = "standing"

# THE BACKDROP the pet is drawn on (SPEC_MATTE_BACKDROP). It used to be "white
# background", and that phrase was the single biggest source of broken sprites in this
# pipeline: a pale pet on a white field is the one input birefnet cannot segment. Measured
# on a white snow leopard through Wan to the matte — on white the matte came back a LINE
# DRAWING (97k px of a ~160k body) and the hole fill added 103k, i.e. the repair was
# drawing the animal. On cyan the same pet needs ZERO repair.
#
# Why cyan specifically, when the sprite-generation literature says magenta or green:
#   - it is NOT a chroma key. Z-Image will not draw a flat key (measured backdrop
#     std-dev: grey 4, green 38, cyan/magenta 58-65 — it paints a scene, not a screen), so
#     birefnet still does the segmenting and the backdrop's job is only to make the subject
#     separable. Flatness turned out to be irrelevant; cyan vignettes hard and mattes
#     perfectly, because a segmentation model reads shape, not colour uniformity.
#   - NO fixed backdrop survives a pet of its own colour — white breaks white pets, grey
#     breaks grey pets (a flat grey corgi: fill+ 47,407). So the choice is about which
#     colour is hardest to hit, and cyan is the only candidate absent from the designer's
#     ten-colour palette. Reaching it takes typing "teal" into free text.
#   - natural animals in the danger zone do NOT break it: a cyan parakeet, a peacock and a
#     green parrot all matte cleanly on cyan, and each needs LESS repair than on white.
#     Real animals carry barring, eyes and shading that a flat artificial recolour lacks.
#
# Changing this phrase re-draws every pet, so it is a content decision. Keep it in sync
# with `factory.STILL_BACKDROP_RGB`, which is the same decision as a pixel (§9 I5).
STILL_BACKDROP = "flat vivid cyan background"

# The same decision as a PIXEL, for the places that paint the field instead of asking a
# model to draw it (`factory._prep_reference_image` pads and flattens onto it). It lives
# HERE, beside the phrase, because a backdrop split across two modules is a backdrop that
# will eventually disagree with itself — `factory` re-exports it rather than redefining it.
# A tuple needs no imports, so this module stays pure data and GPU-less-safe.
# MEASURED from what the model actually draws for the phrase above: across six renders its
# cyan field came out RGB(88-104, 208-236, 183-222).
STILL_BACKDROP_RGB = (100, 230, 215)

# From-scratch still (Z-Image txt2img). "facing right" is load-bearing: DatsMe
# authors pets facing right and mirrors them for leftward movement, so the source
# must face right.
BASE_STILL_TEMPLATE = (
    "a cute cartoon {animal}, side profile view, facing right, {pose}, "
    "soft pastel colors, muted palette, simple flat shading, " + STILL_BACKDROP + ", "
    "storybook style"
)

# Still redrawn FROM a reference image (img2img). Deliberately DROPS the "soft pastel
# colors, muted palette" clause of the base template: a remix description is usually
# about changing the colour ("purple monkey"), and the pastel clause fights the
# requested colour harder than the source image does. Repeating the description
# ("exactly {animal}") helps it win over the source's original colours.
REMIX_STILL_TEMPLATE = (
    "a cute cartoon {animal}, exactly {animal}, side profile view, "
    "facing right, {pose}, rich saturated colors, simple flat shading, "
    + STILL_BACKDROP + ", storybook style"
)


def base_still_prompt(animal: str, pose: str = DEFAULT_POSE) -> str:
    """Render the from-scratch still prompt. A per-pose anchor (§3.9.1 pose_prompt)
    passes its clause as `pose`, so the anchor is the SAME sentence as the base with
    only the posture changed — the fly anchor and the walk anchor stay the same animal."""
    return BASE_STILL_TEMPLATE.format(animal=animal, pose=pose)


def remix_still_prompt(animal: str, pose: str = DEFAULT_POSE) -> str:
    """Render the redraw-from-reference still prompt (same `pose` contract as
    `base_still_prompt`, so a reference-based pet's fly anchor matches its designed
    still's palette)."""
    return REMIX_STILL_TEMPLATE.format(animal=animal, pose=pose)


# The CURATION still (animal_catalog/generate_candidates.py, generate_sample.py). It is
# deliberately different from the two above — "full body, centered", because a curated
# base.png wants the whole animal in frame — and it is used differently: the rendered
# string is passed as the `animal` of a real build, so one of the templates above wraps it
# and supplies the backdrop. It must therefore carry NO background clause of its own.
#
# It lives here, with the other sentences, because it was duplicated verbatim in both of
# those scripts and both hardcoded "plain white background" — so the backdrop existed in
# three places and two of them would have been missed. `test_prompt_templates` explicitly
# excluded this sentence for exactly that reason; now there is one of it.
CURATION_STILL_TEMPLATE = (
    "a cute cartoon {species}, side profile view, facing right, standing, "
    "full body, centered, simple flat shading, storybook style"
)


def curation_still_prompt(species: str) -> str:
    """The from-scratch prompt for a CURATED base still (SPEC_PET_DESIGNER_PLATFORM §4.5)."""
    return CURATION_STILL_TEMPLATE.format(species=species)
