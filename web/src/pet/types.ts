/**
 * Shared type definitions for the pet runtime.
 *
 * These mirror the shape of the manifest fields written by
 * datsPet's Step 6 (build_sprite_sheet). When this file is copied to
 * datsme/web/src/components/pet/types.ts, no changes are needed —
 * datsme will receive the same manifest format.
 */

export type RuntimeRole = "rest" | "active" | "timed" | "triggered";

/**
 * Camera angle the sprite is authored at. Per
 * docs/SPEC_PET_FACING.md §5.1. Descriptive metadata; the actual
 * mirroring rule lives on `mirroring_policy`.
 */
export type ViewKind = "side" | "front" | "three_quarter" | "top_down";

/**
 * Native facing direction for `kind: side` sprites; `"none"` for any
 * view where left/right doesn't apply (top_down, front-view portraits,
 * three-quarter when not mirror-able).
 */
export type NativeFacing = "right" | "left" | "none";

/**
 * The rule the runtime applies when the pet's locomotion / cursor flips
 * its facing field. Replaces the older unconditional `scaleX(-1)` flip.
 *
 *   "flip"            — sprite is authored facing right; mirror when
 *                       moving left. (Today's default for side-view.)
 *   "none"            — never apply scaleX(-1). Correct for top_down,
 *                       front-view, and 3/4 sprites that look broken
 *                       when mirrored.
 *   "flip-from-left"  — sprite authored facing left; mirror when moving
 *                       right (the inverse of "flip"). Rare.
 */
export type MirroringPolicy = "flip" | "none" | "flip-from-left";

/**
 * Per-animation facing block. Mirrors the `view` object Step 6 writes
 * onto each animation entry per
 * docs/SPEC_PER_ANIMATION_FACING.md. Optional because manifests
 * written before that spec landed don't carry it; absent → consumer
 * inherits from sheet-level `mirroringPolicy` on PetSheet.
 *
 * Field naming follows the manifest's snake_case for the three machine
 * fields (so the JSON shape passes through unchanged) plus a
 * description string for human consumers reading the manifest cold.
 */
export interface ViewBlock {
  view_kind:        ViewKind;
  native_facing:    NativeFacing;
  mirroring_policy: MirroringPolicy;
  description?:     string;
}

/**
 * One animation entry from the manifest. Required fields are `frames`,
 * `fps`, `loop`. Other fields are role-dependent (only present on
 * animations whose role uses them) — older manifests may omit them.
 */
export interface AnimationSpec {
  frames: number[];
  fps: number;
  loop: boolean;

  // Role classification — drives which auto-state-machine branch
  // owns this animation. Optional because pre-D2.C manifests don't
  // carry it; auto state machine treats absent as "do not auto-play".
  runtime_role?: RuntimeRole;

  // ACTIVE-role knobs
  pick_weight?: number;

  // REST-exit / RUN-arrival routing weights
  rest_exit_weight?: number;
  run_arrival_weight?: number;

  // REST dwell window before exiting
  rest_dwell_ms?: [number, number];

  // TIMED-role buffer added to the natural duration (loop=false) or
  // used as the entire dwell (loop=true).
  timed_buffer_ms?: number;

  // Per-animation facing block. Optional — when absent the runtime
  // inherits from sheet-level `mirroringPolicy` on PetSheet.
  view?: ViewBlock;
}

export type AnimationsMap = Record<string, AnimationSpec>;

/**
 * Per-instance render state. The current code only ever has one
 * instance — there is one pet on the page. The shape is preserved
 * (rather than collapsed) because datsme may eventually want a "pet
 * + companion" or "pet + ghost-of-friend" rendering, and the engine
 * already supports that case.
 */
export interface PetInstance {
  stageEl: HTMLElement | null;
  petEl: HTMLElement | null;
  x: number;
  y: number;
  targetX: number | null;
  targetY: number | null;
}

/**
 * Sprite-sheet metadata + the animations map. This is the unit of
 * "what pet are we rendering" — replacing it switches breeds.
 *
 * The `view*` / `nativeFacing` / `mirroringPolicy` fields mirror the
 * three new manifest fields written by Step 6 (docs/SPEC_PET_FACING.md).
 * All three are optional — manifests written before the spec landed
 * omit them, in which case the runtime falls back to "flip".
 */
export interface PetSheet {
  sheetUrl: string;
  /** per-cell source size in px (e.g. 256). */
  sourceFrame: number;
  sheetCols: number;
  sheetRows: number;
  anims: AnimationsMap;

  viewKind?:        ViewKind;
  nativeFacing?:    NativeFacing;
  mirroringPolicy?: MirroringPolicy;

  /**
   * Declared movement class from datsPet Step 6. The host's
   * LOCOMOTION_REGISTRY resolves this to a per-frame strategy at
   * sheet-bind time. Optional — manifests written before
   * docs/SPEC_PET_LOCOMOTION_REGISTRY.md landed omit it, in which
   * case the runtime falls back to the quadruped strategy.
   */
  movementClass?: string;
}
