"""house_capacity — the house-scaling policy (SPEC house-scaling), one place.

Extracted from app.py when the Pet Store arrived (SPEC_PET_STORE §3.1): the
store's adopt endpoint lives in its own router module and must enforce the same
cap as /api/generate and /keep, and a policy two routers share belongs to
neither. Env-var knobs are read at CALL time so they are tunable without a
restart — the DATSPET_DESIGN_COST posture.

The house grows forever, and the cost is on the CLIENT (a phone decodes a full
sprite sheet per card + PetStage actor), so these bound what a mobile tab must
hold: the cap bounds total pets (and disk), the page size bounds what is
mounted at once. Neither is a client constant — the browser reads both from
/api/house.
"""
from __future__ import annotations

import os
from typing import Optional

from fastapi import HTTPException

import db

HOUSE_MAX_PETS_ENV = "PETMAKER_HOUSE_MAX_PETS"
HOUSE_PAGE_SIZE_ENV = "PETMAKER_HOUSE_PAGE_SIZE"
DEFAULT_HOUSE_MAX_PETS = 50
DEFAULT_HOUSE_PAGE_SIZE = 10


def house_max_pets() -> int:
    try:
        return max(1, int(os.environ.get(
            HOUSE_MAX_PETS_ENV, str(DEFAULT_HOUSE_MAX_PETS))))
    except ValueError:
        return DEFAULT_HOUSE_MAX_PETS


def house_page_size() -> int:
    try:
        return max(1, int(os.environ.get(
            HOUSE_PAGE_SIZE_ENV, str(DEFAULT_HOUSE_PAGE_SIZE))))
    except ValueError:
        return DEFAULT_HOUSE_PAGE_SIZE


def enforce_house_not_full(owner: Optional[str]) -> None:
    """Block a new pet from joining a full house (SPEC house-scaling). We BLOCK,
    never evict — a pet's bundle is irreplaceable, so the user removes one by
    hand. Counted against the caller's own visible house."""
    cap = house_max_pets()
    if db.count_saved_pets(owner) >= cap:
        raise HTTPException(
            409, f"Your pet house is full ({cap} pets). Remove one to make room.")
