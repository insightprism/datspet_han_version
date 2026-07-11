"""pet_factory — animal name → a ready-to-use DatsMe pet bundle (.zip).

    from pet_factory import make_pet_zip
    breed_id, zip_bytes = make_pet_zip("red panda")
"""
from .factory import make_pet_zip, pack_datsme_bundle, render_design_still

__all__ = ["make_pet_zip", "pack_datsme_bundle", "render_design_still"]
__version__ = "1.0.0"
