"""Guard tests for the body_shapes vocabulary (SPEC_PET_DESIGNER_FLOW §7.2, §10.2).

Same posture as test_tiers / test_motion_profiles: the data is content, and these are
the tests that fail the build on a half-formed entry so the admin/author can't ship one.
"""
import json

import pytest

from pet_factory import body_shapes as bs


def test_default_fragment_is_exactly_empty():
    """The one invariant that carries meaning: "normal" must contribute NO words.

    If the default ever gained a fragment, "normal corgi" would compose to something
    other than "corgi" — and the design string for a user who touched nothing would
    stop matching the design string for a user who never saw the control. The default
    is the absence of a choice; it must read as the absence of words.
    """
    assert bs.prompt_fragment(bs.default_shape_key()) == ""


def test_exactly_one_default_and_it_exists():
    data = bs.load_shapes()
    keys = [s["key"] for s in data["shapes"]]
    assert data["default"] in keys, "default names a shape that isn't in the list"
    assert len(keys) == len(set(keys)), "duplicate shape keys"
    assert sum(1 for k in keys if k == data["default"]) == 1


def test_every_shape_is_fully_formed():
    """A half-formed entry fails the build, not a user's design."""
    for s in bs.load_shapes()["shapes"]:
        assert s.get("key"), "a shape has no key"
        assert s.get("label"), f"{s['key']} has no label"
        assert "prompt_fragment" in s, f"{s['key']} has no prompt_fragment"
        assert isinstance(s["prompt_fragment"], str)
        assert s["prompt_fragment"] == s["prompt_fragment"].strip(), \
            f"{s['key']}'s fragment has loose whitespace — it gets prepended verbatim"


@pytest.mark.parametrize("key", ["nonsense", "", None, "NORMAL"])
def test_unknown_keys_resolve_rather_than_raise(key):
    """Never-raises, like motion-profile resolution: a typo degrades to "no change",
    it does not 500 a design. Note "NORMAL" — keys are case-sensitive, so a
    mis-cased key is simply unknown."""
    assert bs.prompt_fragment(key) == ""
    assert bs.is_default(key) is True


def test_non_default_shapes_actually_contribute_words():
    """The mirror of the invariant above: a shape that isn't the default MUST carry a
    fragment, or the control would be a no-op the user can still click."""
    non_default = [s for s in bs.load_shapes()["shapes"]
                   if s["key"] != bs.default_shape_key()]
    assert non_default, "a vocabulary with only a default is not a vocabulary"
    for s in non_default:
        assert s["prompt_fragment"], f"{s['key']} is selectable but changes nothing"
        assert bs.is_default(s["key"]) is False


def test_list_shapes_never_leaks_prompt_wording():
    """§7.2: prompt_fragment is calibrated server-side content and must not reach the
    browser — the same posture as the tier table. Leaking it invites a client to
    compose its own prompt, which is how the server stops being authoritative."""
    for s in bs.list_shapes():
        assert set(s) == {"key", "label", "is_default"}
    assert sum(1 for s in bs.list_shapes() if s["is_default"]) == 1


def test_shapes_json_is_pure_data():
    """The GPU-less gate in miniature (CLAUDE.md): this subpackage ships to a web tier
    with no ML stack, so it must stay stdlib-parseable content with no import cost."""
    data = json.loads((bs._SHAPES_FILE).read_text())
    assert set(data) >= {"_doc", "default", "shapes"}
    assert data["_doc"], "content files carry their own rationale"
