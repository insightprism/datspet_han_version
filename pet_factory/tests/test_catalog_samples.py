"""Sample bundles are CONTENT, and content can be half-formed (§4 step 1).

Two different invariants live here, and the split is deliberate:

**Every promoted sample must be sellable.** A bundle whose manifest will not parse
declares no `pose_count`, so `_export_item` omits its `transfer` block and the host
skips it with a log line — the pet is simply *absent* from the checkout with nothing
shown to the user (SPEC_DATSPET_FEDERATED_SESSION §2.5). That is the worst failure
shape this repo has: silent, and only visible to whoever reads the host's logs. It
is a hard invariant and it is enforced below.

**Which animals are stocked is a merchandising choice, not an invariant.** An animal
with no `samples/` directory is legal: `list_samples` returns `[]`, the page renders
no tiles for it, nothing misbehaves. So it is REPORTED, never asserted — the owner
decides what is worth curating (as of 2026-07-30: `cat` yes, `dog` deliberately not),
and a test encoding that preference would be a build blocker for a stocking decision.

This is the revised Gate 0 in SPEC_DATSPET_CATALOG_PURCHASE §0.1: the hard gate is
sellability, the stock list is information.
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


def test_report_which_animals_are_stocked(capsys):
    """Which animals carry samples, printed rather than asserted (see the module
    docstring). Information for whoever is deciding what to curate next.

    Run with `-s` to see it. It fails only if the catalog itself is empty, which
    would mean something far more broken than an unstocked animal.
    """
    animals = ac.list_animals()
    assert animals, "the catalog has no animals at all"

    empty = [a["key"] for a in animals if not ac.list_samples(a["key"])]
    with capsys.disabled():
        stocked = [a["key"] for a in animals if ac.list_samples(a["key"])]
        print(f"\n  [catalog] stocked: {', '.join(stocked) or 'none'}"
              f"{'  |  not stocked: ' + ', '.join(empty) if empty else ''}")
