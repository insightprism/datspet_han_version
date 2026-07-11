# created_pets — test pets generated through the shared GPU pool

Every pet generated during testing lands here, one folder per animal.

## Make a new pet

```bash
cd /home/markly2/claude_code/datsme-pet-factory/created_pets
python3 make_pet.py "cardinal bird"
python3 make_pet.py "red panda"
python3 make_pet.py "penguin"
```

It submits the animal to `pool.datsme.me` (as the `datspet` app), runs the real
pipeline on whichever pool GPU serves `pet_factory` (currently `omen-pet`), downloads
the DatsMe bundle, and unpacks it into `created_pets/<slug>/`:

```
created_pets/
  cardinal_bird/
    cardinal_bird_sprite.png   ← the sprite sheet (open this to see the pet)
    cardinal.zip               ← the full DatsMe breed bundle
    manifest.json              ← walk/idle animation definition
    package.json               ← pet metadata
```

## Notes

- The app key is read from `~/.pool/datspet_key` (already saved). Override with
  `POOL_APP_KEY=<key> python3 make_pet.py ...`.
- Generation takes ~3 minutes (the pipeline runs base sprite → walk → idle →
  cutout → pack on a home 3090).
- This is **output**, not code — the `pet_factory` library that *makes* pets lives
  in `../pet_factory/`; the pool handler in `../pool_handler/`.
