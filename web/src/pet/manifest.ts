/**
 * Manifest hygiene helpers — back-fill missing fields from a stale
 * manifest so the engine has what it needs.
 *
 * The same helpers exist in the vanilla showcase (showcase_init.js);
 * this is the TypeScript port. When this file lands in datsme it'll
 * be doing exactly what datsme's pet runtime needs: take whatever
 * shape the manifest currently has and produce a normalized
 * `AnimationsMap` the engine can consume.
 */

import type {
  AnimationSpec, AnimationsMap, MirroringPolicy, NativeFacing, ViewKind,
} from "./types";

export interface RawManifest {
  columns?: number;
  rows?: number;
  frame_width?: number;
  frame_height?: number;
  animations?: Record<string, Partial<AnimationSpec>>;
  view_kind?:        ViewKind;
  native_facing?:    NativeFacing;
  mirroring_policy?: MirroringPolicy;
  /**
   * Declared movement class (datsPet Step 6). Resolved by the host's
   * LOCOMOTION_REGISTRY at sheet-bind time; manifests written before
   * docs/SPEC_PET_LOCOMOTION_REGISTRY.md landed omit this — runtime
   * falls back to the quadruped strategy when absent.
   */
  movement_class?: string;
}

/**
 * Derive sheet rows from the highest frame index when the manifest's
 * top-level `rows` field is missing. Older manifests predate the rows
 * field; rather than treating them as broken, derive what we need.
 */
export function deriveRows(manifest: RawManifest): number {
  if (typeof manifest.rows === "number" && manifest.rows > 0) {
    return manifest.rows;
  }
  let maxIdx = 0;
  for (const a of Object.values(manifest.animations || {})) {
    for (const f of (a.frames || [])) {
      if (f > maxIdx) maxIdx = f;
    }
  }
  const cols = manifest.columns || 16;
  return Math.floor(maxIdx / cols) + 1;
}

/**
 * Strip a manifest's animations down to the fields the engine consumes,
 * defaulting `fps` and `loop` for entries that omit them.
 *
 * Animations missing `runtime_role` are kept (the engine can still
 * play them when forced) but will be invisible to the auto state
 * machine. That mirrors the vanilla showcase's behavior — and what
 * datsme would see if it ever fetched a stale manifest.
 */
export function animsFromManifest(manifest: RawManifest): AnimationsMap {
  const out: AnimationsMap = {};
  for (const [name, data] of Object.entries(manifest.animations || {})) {
    if (!data.frames || data.frames.length === 0) continue;
    out[name] = {
      frames:             data.frames,
      fps:                typeof data.fps === "number" ? data.fps : 8,
      loop:               typeof data.loop === "boolean" ? data.loop : true,
      runtime_role:       data.runtime_role,
      pick_weight:        data.pick_weight,
      rest_exit_weight:   data.rest_exit_weight,
      run_arrival_weight: data.run_arrival_weight,
      rest_dwell_ms:      data.rest_dwell_ms,
      timed_buffer_ms:    data.timed_buffer_ms,
      // Per-animation facing block (docs/SPEC_PER_ANIMATION_FACING.md).
      // Pass through unchanged when present; absent on pre-spec
      // manifests, in which case the runtime inherits from sheet-level
      // `mirroringPolicy` on PetSheet.
      view:               data.view,
    };
  }
  return out;
}
