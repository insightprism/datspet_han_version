"""pet_factory — animal name → a ready-to-use DatsMe pet bundle (.zip).

    from pet_factory import make_pet_zip
    breed_id, zip_bytes = make_pet_zip("red panda")

The heavy factory module (numpy/PIL/requests, and rembg→onnxruntime at generation
time) is imported LAZILY via module __getattr__ (PEP 562). This keeps two things true:
  - `from pet_factory import make_pet_zip` still works — factory loads on first access.
  - `import pet_factory.motion_profiles` (pure JSON/data — no ML deps) does NOT drag
    in factory, so the GPU-less web tier can read motion profiles without the ML stack
    (SPEC_DEPLOY_PETDATSME_POOL §A.4 / SPEC_MOTION_PROFILES §5.1).
"""
__all__ = ["make_pet_zip", "pack_datsme_bundle", "render_design_still"]
__version__ = "1.0.0"

_LAZY = frozenset(__all__)


def __getattr__(name):
    # PEP 562: resolve the factory exports on first attribute access.
    if name in _LAZY:
        from . import factory
        return getattr(factory, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(list(globals().keys()) + list(_LAZY))
