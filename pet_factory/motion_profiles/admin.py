"""motion_profiles.admin — the WRITE path for the movement registry (content editing).

The read path lives in `__init__.py` (resolve/load, cached). This module is the
mutation side the admin surface uses (SPEC_MOTION_PROFILE_ADMIN §3): validate a
profile against the exact guard-test contract, then write/delete the file +
registry entry and bust the in-memory cache. Pure data, no ML — imports on the
GPU-less web tier like the rest of the package.

Boundary (§0.2/§0.3): `validate_profile` is the SINGLE definition of "a valid
profile" — the guard test and the admin endpoint both call it, so the admin can
never write a profile the build would reject. Writing is data-only; the engine
(`make_pet_zip`) is untouched and reads whatever the resolver returns.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from . import (
    ALLOWED_CONTROL_KINDS,
    ALLOWED_ROLES,
    CANONICAL_POSES,
    REQUIRED_POSES,
    _DIR,
    _LOCK,
    reload as _reload_cache,
)

# A profile key becomes a filename AND a URL path segment — a conservative slug
# (§1.3): lowercase start, then lowercase/digits/underscore. No traversal, no dots.
_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")

_MIN_LEVEL, _MAX_LEVEL = 1, 4

# The three fields of a view block (SPEC_BUNDLE_MOTION_CONTRACT §3.3). Shape only —
# whether the values are `side`/`right` (today's prompt discipline) is a build-guard
# assertion on shipped content, not a write-time rule that would reject a future
# top-down profile.
_VIEW_KEYS = ("view_kind", "native_facing", "mirroring_policy")


def _view_errors(view: object, where: str) -> list[str]:
    """Shape-check a view block: an object with three non-empty string fields."""
    if not isinstance(view, dict):
        return [f"{where} must be an object with {list(_VIEW_KEYS)}"]
    errs: list[str] = []
    for k in _VIEW_KEYS:
        v = view.get(k)
        if not isinstance(v, str) or not v.strip():
            errs.append(f"{where}.{k} must be a non-empty string")
    return errs


def _registry_path() -> Path:
    return _DIR / "registry.json"


def load_registry() -> dict:
    """The raw registry.json (re-read from disk each call — the admin needs the
    live on-disk state, not the cached copy)."""
    return json.loads(_registry_path().read_text())


def _registry_keys(registry: dict) -> set[str]:
    return {e["key"] for e in registry.get("profiles", [])}


def validate_profile(
    raw: dict,
    *,
    registry: dict,
    existing_key: Optional[str] = None,
) -> list[str]:
    """Return a list of human-readable errors for a candidate profile (empty =
    valid). The EXACT §1.3 contract the guard test asserts — the one definition of
    "valid", shared by the test and the admin endpoint.

    `existing_key`: when editing/duplicating, the key being written; keyword
    uniqueness ignores that key's own current keywords (you're replacing them).
    None for a create.
    """
    errors: list[str] = []

    # --- key: safe slug ---
    key = raw.get("key")
    if not isinstance(key, str) or not _KEY_RE.match(key):
        errors.append(
            f"key must match {_KEY_RE.pattern!r} (lowercase, digits, underscore) — got {key!r}"
        )
        # Without a usable key the rest is moot, but keep validating what we can.

    # --- level: 1..4 ---
    level = raw.get("level")
    try:
        level_int = int(level)
        if not (_MIN_LEVEL <= level_int <= _MAX_LEVEL):
            errors.append(f"level must be {_MIN_LEVEL}..{_MAX_LEVEL} — got {level!r}")
    except (TypeError, ValueError):
        errors.append(f"level must be an integer {_MIN_LEVEL}..{_MAX_LEVEL} — got {level!r}")

    # --- movement_class: non-empty ---
    mc = raw.get("movement_class")
    if not isinstance(mc, str) or not mc.strip():
        errors.append("movement_class is required and must be a non-empty string")

    # --- view: required sheet-level block (§3.3) ---
    # Making it explicit (rather than the packer's old hardcoded constants) is the
    # whole point of §3.3: the prompts say "side profile, facing right" *because*
    # the profile declares it, and the guard test can assert the two agree.
    view = raw.get("view")
    if view is None:
        errors.append(f"view is required (object with {list(_VIEW_KEYS)})")
    else:
        errors.extend(_view_errors(view, "view"))

    # --- base_pose: optional posture word for the base still (default "standing") ---
    # The posture the shared base sprite is drawn in; the factory feeds it to
    # _base_prompt in place of "standing" so aquatic bodies draw horizontal. Optional
    # (omitting it keeps "standing"); when present it must be a real non-empty phrase.
    base_pose = raw.get("base_pose")
    if base_pose is not None and (not isinstance(base_pose, str) or not base_pose.strip()):
        errors.append("base_pose must be a non-empty string when present")

    # --- poses: exactly the canonical set, no more/less ---
    poses = raw.get("poses")
    if not isinstance(poses, dict):
        errors.append("poses must be an object")
        poses = {}
    pose_keys = set(poses.keys())
    canonical = set(CANONICAL_POSES)
    if pose_keys != canonical:
        missing = canonical - pose_keys
        extra = pose_keys - canonical
        if missing:
            errors.append(f"poses missing required canonical keys: {sorted(missing)}")
        if extra:
            errors.append(f"poses has non-canonical keys: {sorted(extra)}")

    # --- per-pose rules ---
    for name in CANONICAL_POSES:
        spec = poses.get(name)
        if not isinstance(spec, dict):
            if name in pose_keys:
                errors.append(f"pose {name!r} must be an object")
            continue
        enabled = bool(spec.get("enabled", False))
        if enabled:
            action = spec.get("action")
            if not isinstance(action, str) or not action.strip():
                errors.append(f"pose {name!r} is enabled but has no non-empty action")
            role = spec.get("runtime_role")
            if role not in ALLOWED_ROLES:
                errors.append(
                    f"pose {name!r} runtime_role {role!r} not in {sorted(ALLOWED_ROLES)}"
                )

        # --- optional control block (§3.9.1) ---
        # A control never removes the prompt fallback: an enabled pose still needs a
        # valid action/suffix (checked above), so a pose with no supported control
        # kind degrades to the loop-only path. Here we only pin the block's SHAPE.
        control = spec.get("control")
        if control is not None:
            if not isinstance(control, dict):
                errors.append(f"pose {name!r} control must be an object")
            elif control.get("kind") not in ALLOWED_CONTROL_KINDS:
                errors.append(
                    f"pose {name!r} control.kind {control.get('kind')!r} not in "
                    f"{sorted(ALLOWED_CONTROL_KINDS)}"
                )
            elif control["kind"] == "pose_prompt":
                clause = control.get("pose")
                if not isinstance(clause, str) or not clause.strip():
                    errors.append(
                        f"pose {name!r} control kind 'pose_prompt' requires a non-empty 'pose' clause"
                    )

        # --- loop / timed_buffer_ms / view (§3.1/§3.2/§3.3) ---
        loop = spec.get("loop", True)
        if not isinstance(loop, bool):
            errors.append(f"pose {name!r} loop must be a boolean")
        elif enabled and spec.get("runtime_role") == "triggered" and loop:
            # A reaction plays once and returns to rest; a looping trigger holds its
            # last frame forever on the host. The authoring rule §3.1 mandates.
            errors.append(f"pose {name!r} is 'triggered' and must declare loop: false")

        buf = spec.get("timed_buffer_ms")
        if buf is not None and (not isinstance(buf, int) or isinstance(buf, bool) or buf <= 0):
            errors.append(f"pose {name!r} timed_buffer_ms must be a positive integer when present")

        pose_view = spec.get("view")
        if pose_view is not None:
            errors.extend(_view_errors(pose_view, f"pose {name!r} view"))

    # --- walk + idle must be enabled ---
    for req in REQUIRED_POSES:
        spec = poses.get(req)
        if not (isinstance(spec, dict) and bool(spec.get("enabled", False))):
            errors.append(f"required pose {req!r} must be enabled")

    # --- keywords globally unique (case-insensitive), across OTHER profiles ---
    keywords = raw.get("keywords", [])
    if not isinstance(keywords, list):
        errors.append("keywords must be a list")
        keywords = []
    # Build the set of keywords claimed by every OTHER profile.
    claimed: dict[str, str] = {}
    for entry in registry.get("profiles", []):
        if entry["key"] == existing_key:
            continue  # replacing this profile's own keywords
        try:
            other = json.loads((_DIR / entry["file"]).read_text())
        except (OSError, json.JSONDecodeError):
            continue
        for kw in other.get("keywords", []):
            claimed[kw.lower()] = entry["key"]
    seen_in_self: set[str] = set()
    for kw in keywords:
        if not isinstance(kw, str) or not kw.strip():
            errors.append(f"keyword {kw!r} must be a non-empty string")
            continue
        low = kw.lower()
        if low in claimed:
            errors.append(f"keyword {kw!r} already claimed by profile {claimed[low]!r}")
        if low in seen_in_self:
            errors.append(f"keyword {kw!r} listed twice in this profile")
        seen_in_self.add(low)

    return errors


# ---------------------------------------------------------------------------
# Write / delete primitives (§3). Each validates, mutates file + registry
# atomically-ish, then busts the loader cache so the change is live immediately.
# ---------------------------------------------------------------------------
class ProfileWriteError(ValueError):
    """A write/delete refused for a content reason. `errors` carries the
    validate_profile list when the cause was validation; else a single message."""

    def __init__(self, message: str, errors: Optional[list[str]] = None):
        super().__init__(message)
        self.errors = errors or [message]


def _profile_file(key: str) -> Path:
    return _DIR / f"{key}.json"


def _write_registry(registry: dict) -> None:
    """Persist registry.json with stable, sorted-by-key ordering so diffs stay
    small and deterministic (the `default` + `profiles` shape is preserved)."""
    registry = dict(registry)
    registry["profiles"] = sorted(registry.get("profiles", []), key=lambda e: e["key"])
    tmp = _registry_path().with_suffix(".json.tmp")
    tmp.write_text(json.dumps(registry, indent=2) + "\n")
    tmp.replace(_registry_path())


def write_profile(raw: dict, *, label: str, existing_key: Optional[str] = None) -> dict:
    """Validate + write a profile file and upsert its registry entry, then reload
    the cache. `existing_key` set → an update (the key must already be registered);
    None → a create (the key must NOT exist). Returns the registry entry written.
    Raises ProfileWriteError on validation failure or a create/update key clash."""
    with _LOCK:
        registry = load_registry()
        keys = _registry_keys(registry)
        key = raw.get("key")

        errs = validate_profile(raw, registry=registry, existing_key=existing_key)
        if errs:
            raise ProfileWriteError("profile failed validation", errs)

        if existing_key is None:
            if key in keys:
                raise ProfileWriteError(f"profile {key!r} already exists")
        else:
            if existing_key not in keys:
                raise ProfileWriteError(f"profile {existing_key!r} does not exist")
            if key != existing_key:
                raise ProfileWriteError(
                    f"key rename not supported here (got {key!r}, editing {existing_key!r}); "
                    "duplicate under the new key + delete the old"
                )

        level = int(raw["level"])
        # Write the profile file (temp → rename for atomicity).
        tmp = _profile_file(key).with_suffix(".json.tmp")
        tmp.write_text(json.dumps(raw, indent=2) + "\n")
        tmp.replace(_profile_file(key))

        # Upsert the registry entry.
        entry = {"key": key, "file": f"{key}.json", "label": label, "level": level}
        profiles = [e for e in registry.get("profiles", []) if e["key"] != key]
        profiles.append(entry)
        registry["profiles"] = profiles
        _write_registry(registry)

    _reload_cache()
    return entry


def delete_profile(key: str, *, pinned_by: Optional[list[str]] = None) -> None:
    """Remove a profile file + its registry entry, then reload. Refuses to delete
    the `default` profile, or one still pinned by a catalog entry (pinned_by is the
    list of catalog references the caller resolved — non-empty → refuse). Raises
    ProfileWriteError otherwise."""
    with _LOCK:
        registry = load_registry()
        if key == registry.get("default"):
            raise ProfileWriteError(f"cannot delete the default profile {key!r}")
        if key not in _registry_keys(registry):
            raise ProfileWriteError(f"profile {key!r} does not exist")
        if pinned_by:
            raise ProfileWriteError(
                f"profile {key!r} is still pinned by catalog entries: {pinned_by}",
            )
        registry["profiles"] = [e for e in registry["profiles"] if e["key"] != key]
        _write_registry(registry)
        f = _profile_file(key)
        if f.exists():
            f.unlink()
    _reload_cache()


def duplicate_profile(src_key: str, *, new_key: str, new_label: str) -> dict:
    """Clone src_key's file under new_key (rewriting the `key` field and CLEARING
    keywords — they must be unique, so the admin re-adds non-conflicting ones),
    write + register + reload. Returns the new profile's full JSON dict."""
    with _LOCK:
        registry = load_registry()
        if src_key not in _registry_keys(registry):
            raise ProfileWriteError(f"source profile {src_key!r} does not exist")
        if not _KEY_RE.match(new_key or ""):
            raise ProfileWriteError(f"new key {new_key!r} is not a valid slug")
        if new_key in _registry_keys(registry):
            raise ProfileWriteError(f"profile {new_key!r} already exists")
        raw = json.loads(_profile_file(src_key).read_text())
    raw["key"] = new_key
    raw["keywords"] = []   # unique constraint — the clone starts keyword-free
    write_profile(raw, label=new_label, existing_key=None)
    return raw
