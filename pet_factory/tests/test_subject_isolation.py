"""Subject isolation for the upload door (SPEC_UPLOAD_LIKENESS §2.2, §7).

ZERO GPU, ZERO model load. `_crop_to_subject` is pure PIL, and every test that
touches the ML boundary stubs `_remove_bg` — so this whole file runs on the
standard `pytest pet_factory/tests webui/tests` gate. That is the entire reason
§2.2 split the geometry (`_crop_to_subject`) from the ML call (`_remove_bg`): the
failure rules are the part most likely to be wrong, and they must be testable
without a card.
"""
import pytest
from PIL import Image

from pet_factory import factory


def _rgba(size, subject_box=None):
    """A transparent RGBA canvas with an optional opaque subject rectangle."""
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    if subject_box is not None:
        img.paste((200, 120, 40, 255), subject_box)
    return img


# ---- _crop_to_subject — the geometry, no ML -------------------------------------------

def test_crops_a_small_subject_to_dominate_the_frame():
    # 350×350 subject in 1000×1000 → 12% area: above the 5% floor, below the 95% ceiling.
    img = _rgba((1000, 1000), subject_box=(100, 100, 450, 450))
    out = factory._crop_to_subject(img)
    assert out is not img                                    # it actually cropped
    ow, oh = out.size
    sub = out.getchannel("A").getbbox()
    sub_area = (sub[2] - sub[0]) * (sub[3] - sub[1])
    assert sub_area / (ow * oh) >= 0.80                      # subject now fills the frame


def test_fully_transparent_returns_the_input_unchanged():
    img = _rgba((500, 500))                                  # no subject at all — a wall/screenshot
    assert factory._crop_to_subject(img) is img             # identity, not a copy-equal


def test_subject_below_the_area_floor_returns_the_input():
    # 140×140 in 1000×1000 = ~2% area — a tiny crop upscaled to 1024 is mush.
    img = _rgba((1000, 1000), subject_box=(10, 10, 150, 150))
    assert factory._crop_to_subject(img) is img


def test_fully_opaque_returns_the_input():
    img = Image.new("RGBA", (500, 500), (10, 20, 30, 255))  # bbox is the whole frame → no-op crop
    assert factory._crop_to_subject(img) is img


def test_subject_at_the_edge_clamps_and_does_not_crash():
    # Subject flush against the top-left corner: the margin would go negative and must clamp.
    img = _rgba((1000, 1000), subject_box=(0, 0, 300, 300))
    out = factory._crop_to_subject(img)
    ow, oh = out.size
    assert 0 < ow <= 1000 and 0 < oh <= 1000                # valid crop, no black border, no crash


# ---- _prep_reference_image(isolate=…) — the wiring ------------------------------------

def _bytes(path):
    return path.read_bytes()


def test_default_path_is_byte_identical_and_never_calls_remove_bg(tmp_path, monkeypatch):
    """No `isolate` argument ⇒ today's behaviour, exactly. This is the test that
    fails loudest if someone later makes isolation the default."""
    src = tmp_path / "photo.png"
    Image.new("RGBA", (800, 600), (30, 60, 90, 255)).save(src)

    # If the default path so much as touches the ML boundary, this raises.
    monkeypatch.setattr(factory, "_remove_bg",
                        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("must not run")))

    a = _bytes(factory._prep_reference_image(src))
    b = _bytes(factory._prep_reference_image(src, isolate=False))
    assert a == b                                            # deterministic, and both untouched


def test_cutout_raise_degrades_to_the_raw_photo(tmp_path, monkeypatch):
    """`_remove_bg` raising — the 2026-07-21 GPU-node failure — must yield the same
    bytes as no isolation at all, not a broken door (§2.2)."""
    src = tmp_path / "photo.png"
    Image.new("RGBA", (800, 600), (30, 60, 90, 255)).save(src)

    baseline = _bytes(factory._prep_reference_image(src, isolate=False))

    def _boom(*_a, **_k):
        raise RuntimeError("CUDA provider failed to load")
    monkeypatch.setattr(factory, "_remove_bg", _boom)

    degraded = _bytes(factory._prep_reference_image(src, isolate=True))
    assert degraded == baseline                             # caught, logged, fell back


def test_isolate_crops_pads_and_backdrops(tmp_path, monkeypatch):
    """A successful cutout produces a square, BACKDROP-backed image cropped to the
    subject — strictly smaller than the un-isolated pad of the same wide photo.

    This used to assert a WHITE pad, and that assertion is why SPEC_MATTE_BACKDROP §9 I3
    exists: the upload door cuts the subject out here and then composites it onto this
    canvas, so white here re-created the unsegmentable white-on-white the backdrop change
    removes — for every uploaded pet, no matter what the prompt said."""
    src = tmp_path / "photo.png"
    Image.new("RGBA", (1000, 600), (30, 60, 90, 255)).save(src)

    # Stub the ML call: return an RGBA whose subject is a 300×300 opaque block,
    # everything else transparent — exactly what birefnet hands back.
    def _fake_remove_bg(_img):
        return _rgba((1000, 600), subject_box=(200, 150, 500, 450))
    monkeypatch.setattr(factory, "_remove_bg", _fake_remove_bg)

    isolated = factory._prep_reference_image(src, isolate=True)
    plain = factory._prep_reference_image(src, isolate=False)

    iso = Image.open(isolated)
    assert iso.width == iso.height                          # padded to square
    assert iso.width < Image.open(plain).width             # cropped: smaller than the full pad
    assert iso.getpixel((0, 0)) == factory.STILL_BACKDROP_RGB   # composited onto the backdrop
