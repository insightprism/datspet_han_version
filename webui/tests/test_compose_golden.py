"""Golden composition test (SPEC_PET_DESIGN_AXES §10, Phase 0 — load-bearing).

Every tuple below was captured from compose_design AS IT WAS BEFORE the
design_axes migration (body_shape a positional string, the 0.9 silhouette rule
hardcoded). The migration to the slot-ordered, registry-driven composer must
reproduce them byte-identically — the FULL returned tuple, `min_strength`
included, not just the composed string. The 0.9 rule moved from code to
`body.json` data; a migration that composed identical strings while dropping
the 0.9 would silently weaken every body-shape render.

If an intentional wording change ever lands (a Phase 3 calibration), these
values change WITH it, in the same commit, with the render evidence.
"""
import importlib
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WEBUI = os.path.join(REPO, "webui")
for p in (WEBUI, REPO):
    if p not in sys.path:
        sys.path.insert(0, p)


@pytest.fixture(scope="module")
def compose(tmp_path_factory):
    out = tmp_path_factory.mktemp("golden_out")
    os.environ["PETMAKER_OUTPUT_DIR"] = str(out)
    os.environ["PETMAKER_DB_PATH"] = str(out / "t.db")
    import db as db_mod
    importlib.reload(db_mod)
    import app as app_mod
    importlib.reload(app_mod)
    return app_mod.compose_design


# (species, color, accessories, axis_picks, extra) -> the pre-migration tuple.
# Body picks ride axis_picks["body"] — the same vocabulary shapes.json carried.
GOLDEN = [
    (("corgi", "", [], {}, ""),
     ("corgi", "Corgi", None)),
    (("corgi", "purple", [], {}, ""),
     ("vivid purple corgi, recolored entirely purple", "Purple Corgi", None)),
    (("corgi", "purple", ["wizard hat"], {}, ""),
     ("vivid purple corgi wearing a wizard hat, recolored entirely purple",
      "Purple Corgi", None)),
    (("corgi", "purple", ["wizard hat", "sunglasses"], {"body": "fat"}, ""),
     ("chubby and round vivid purple corgi wearing a wizard hat, sunglasses, "
      "recolored entirely purple", "Purple Corgi", 0.9)),
    (("corgi", "", [], {"body": "fat"}, ""),
     ("chubby and round corgi", "Corgi", 0.9)),
    (("corgi", "", [], {"body": "thin"}, ""),
     ("slender and slim corgi", "Corgi", 0.9)),
    (("corgi", "", [], {"body": "normal"}, ""),
     ("corgi", "Corgi", None)),
    (("corgi", "", [], {"body": "nonsense"}, ""),
     ("corgi", "Corgi", None)),
    (("corgi", "purple", ["emerald crown"], {"body": "thin"}, "made of clockwork gears"),
     ("slender and slim vivid purple corgi wearing an emerald crown, "
      "made of clockwork gears, recolored entirely purple", "Purple Corgi", 0.9)),
    # The species-name colour conflict (§4.4 / _COLOR_WORDS): the empirical
    # blue-jay case — the fight that defined min_strength.
    (("blue jay", "emerald", [], {}, ""),
     ("vivid emerald blue jay, recolored entirely emerald", "Emerald Blue Jay", 0.9)),
    (("blue jay", "", [], {"body": "fat"}, "glowing feathers"),
     ("chubby and round blue jay, glowing feathers", "Blue Jay", 0.9)),
    (("panda", "purple", ["bow tie"], {}, ""),
     ("vivid purple panda wearing a bow tie, recolored entirely purple",
      "Purple Panda", None)),
    # Vowel/plural accessory grammar: "an octopus costume", bare "sunglasses".
    (("octopus", "", ["octopus costume"], {}, "eight tiny hats"),
     ("octopus wearing an octopus costume, eight tiny hats", "Octopus", None)),
]


@pytest.mark.parametrize("inputs,expected", GOLDEN)
def test_composition_is_byte_identical_to_pre_migration(compose, inputs, expected):
    species, color, accessories, picks, extra = inputs
    assert compose(species, color, accessories, picks, extra) == expected


def test_unknown_axis_keys_compose_to_nothing(compose):
    """§4 defense in depth at the composer: an axis the registry doesn't know is
    inert — identical output to no picks at all, never an error."""
    assert compose("corgi", "purple", [], {"bogus_axis": "whatever"}, "") == \
        compose("corgi", "purple", [], {}, "")


def test_empty_and_none_picks_are_equivalent(compose):
    assert compose("corgi", "", [], None, "extra") == \
        compose("corgi", "", [], {}, "extra")
