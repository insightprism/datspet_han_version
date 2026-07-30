"""Sample bundles are CONTENT, and content can be half-formed (§4 step 1).

Two different invariants live here, and the split is deliberate:

**Every promoted sample must be sellable.** A bundle whose manifest will not parse
declares no `pose_count`, so `_export_item` omits its `transfer` block and the host
skips it with a log line — the pet is simply *absent* from the checkout with nothing
shown to the user (SPEC_DATSPET_FEDERATED_SESSION §2.5). That is the worst failure
shape this repo has: silent, and only visible to whoever reads the host's logs. It
is a hard invariant and it is enforced below.

**Every catalog animal should have at least one sample.** That is a *release*
question, not a correctness one — an animal with no `samples/` directory is legal
and simply offers nothing. It is reported rather than asserted, because a red suite
is not the right way to say "the dog shelf is empty": it would block every unrelated
deploy until somebody spends GPU time, and a test that must be ignored to work is a
test that stops being read.

Gate 0 in SPEC_DATSPET_CATALOG_PURCHASE is the thing that closes the gap; this file
makes its state impossible to lose track of.
"""
import json
import os
import sys
import zipfile

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from pet_factory import animal_catalog as ac  # noqa: E402


def _promoted():
    """(animal_key, sample_key) for every promoted sample in the live catalog."""
    return [(a["key"], s["key"])
            for a in ac.list_animals()
            for s in ac.list_samples(a["key"])]


def test_there_is_at_least_one_promoted_sample_anywhere():
    """The floor. With none, every assertion below passes over an empty set — the
    empty-set false green `deploy/CHECKLIST.md` §E exists to prevent, and the exact
    state this catalog was in before `promote_sample.py cat snowleopard`."""
    assert _promoted(), (
        "no promoted samples — the catalog page would ship with nothing to sell. "
        "Stage one with generate_sample.py, then promote_sample.py <animal> <key>."
    )


@pytest.mark.parametrize("animal,sample", _promoted())
def test_a_promoted_sample_is_sellable(animal, sample):
    """Parses, declares poses, and has a portrait.

    `pose_count` is the DECLARED pricing basis: the host quotes from it without
    fetching bytes, then verifies it against the artifact at ingest. A sample that
    cannot produce one is not merely unpriced — it is un-offered, silently.
    """
    bundle = ac.sample_bundle_path(animal, sample)
    assert bundle and bundle.is_file(), f"{animal}/{sample}: bundle missing"

    with zipfile.ZipFile(bundle) as z:
        names = z.namelist()
        manifests = [n for n in names if n.endswith("manifest.json")]
        assert manifests, f"{animal}/{sample}: no manifest.json in the bundle"
        manifest = json.loads(z.read(manifests[0]))
        assert any(n.endswith(".png") for n in names), \
            f"{animal}/{sample}: no sprite sheet in the bundle"

    poses = manifest.get("animations")
    assert isinstance(poses, dict) and poses, \
        f"{animal}/{sample}: no animations — the host cannot quote it, so it is never offered"

    # The gallery tile. A sample with no portrait renders as a blank card.
    assert ac.sample_preview_path(animal, sample), f"{animal}/{sample}: no preview.png"


def test_report_which_animals_still_have_no_sample(capsys):
    """Gate 0's state, printed rather than asserted (see the module docstring).

    Run with `-s` to see it. It fails only if the catalog itself is empty, which
    would mean something far more broken than a missing sample.
    """
    animals = ac.list_animals()
    assert animals, "the catalog has no animals at all"

    empty = [a["key"] for a in animals if not ac.list_samples(a["key"])]
    with capsys.disabled():
        if empty:
            print(f"\n  [Gate 0] no samples yet for: {', '.join(empty)} "
                  f"— the catalog page shows an empty shelf for these.")
        else:
            print("\n  [Gate 0] every catalog animal has at least one sample.")
