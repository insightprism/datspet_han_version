"""Web-tier motion-profile resolution: AI classifier first, keyword fallback.

`motion_profiles` is pure data (GPU-less, no AI deps), so its keyword `_classify`
can't call the AI engine. This module — in the web tier, which HAS the engine —
asks a fast/Haiku purpose (`motion_classify`) which body type an animal is, so the
registry needs no exhaustive per-profile keyword list (SPEC_MOTION_PROFILES §3.5).
It always degrades safely: the AI answer is validated against the LIVE registry,
and any miss (engine off, error, or an unknown key) falls back to
`motion_profiles.resolve_motion_profile` (keyword) — so resolution never raises and
standalone / no-API-key mode still works.

The keyword lists therefore become the OFFLINE fallback, not something to maintain
exhaustively. Confirmed AI results are cached per animal string; a keyword fallback
is NOT cached, so a transient engine outage self-heals on the next call.
"""
from pet_factory import motion_profiles as mp

import ai_engine

# animal (lowercased) -> confirmed AI profile key. Only successful, validated AI
# classifications land here; a keyword fallback is never cached (so it retries the
# AI next time the engine is back). Per-process, resets on restart.
_cache: dict[str, str] = {}


def invalidate() -> None:
    """Drop the cached AI classifications. Called by the motion-profile admin write
    path after every successful mutation, because a profile's `label` IS the
    classifier's description of that body type (`_profiles_block`) — editing a label
    to fix a misclassification would otherwise change nothing for any animal already
    classified in this process, and the author would conclude the label is unused.
    The registry cache next door (mp.reload) is already dropped on the same event;
    this is the same invalidation for the layer above it."""
    _cache.clear()


def _profiles_block() -> str:
    """The `{profiles}` prompt block — one `key — label (movement_class)` line per
    live profile, so the model chooses from exactly what the registry ships."""
    return "\n".join(
        f"{p['key']} — {p['label']} ({p['movement_class']})"
        for p in mp.list_profiles()
    )


def classify(animal: str) -> tuple[str, str]:
    """`(profile_key, source)` — the resolution AND which path produced it.

    `source` is "ai" or "keyword". The Motion Lab shows it: an author needs to know
    whether the answer came from the classifier (what a build will use) or from the
    keyword fallback (what a build uses only when the engine is down), because the two
    can disagree — "komodo dragon" matched winged_flyer's `dragon` keyword for weeks
    while the classifier said quadruped. Cached AI answers still report "ai": the source
    describes what decided the key, not whether this call paid for it.

    Never raises. Safe at reference-fill time (the pinned key travels on the record and
    is loaded verbatim at build, §5.2)."""
    name = (animal or "").strip()
    if not name:
        return mp.resolve_motion_profile(name).key, "keyword"   # → registry default
    cached = _cache.get(name.lower())
    if cached:
        return cached, "ai"
    valid = {p["key"] for p in mp.list_profiles()}
    try:
        result, _usage = ai_engine.call_purpose(
            "motion_classify",
            variables={"animal": name, "profiles": _profiles_block()},
        )
        chosen = (result.get("profile_key") or "").strip()
        if chosen in valid:
            _cache[name.lower()] = chosen                 # cache CONFIRMED AI results only
            return chosen, "ai"
    except (ai_engine.AIUnavailable, ai_engine.AIError):
        pass                                             # engine inert / errored → keyword
    return mp.resolve_motion_profile(name).key, "keyword"  # keyword fallback (not cached)


def resolve_motion_key(animal: str) -> str:
    """The motion-profile key for `animal`: AI classifier → keyword → default. The
    caller that only needs the key; `classify` is the same resolution with its source."""
    return classify(animal)[0]
