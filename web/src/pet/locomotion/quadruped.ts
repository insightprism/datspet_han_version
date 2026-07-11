/**
 * quadruped — first concrete locomotion strategy.
 *
 * Behaviors:
 *   - Two locomotion gaits: `walk` (slower, short-distance) and `run`
 *     (faster, long-distance). The click-handler computes |dx| and
 *     calls motionAnim(distance); the strategy returns "walk" below
 *     WALK_RUN_THRESHOLD_PX and "run" above. motionPredicate accepts
 *     either name so useAnimationLoop's tick fires for both.
 *   - Per-frame motion integration with arrival epsilon, x then y,
 *     speed selected from the active animation (run is ~2.4× walk).
 *     Vertical speed is shared between gaits.
 *   - Sprite tilt that tracks travel direction, capped at ±MAX_TILT_DEG.
 *     Rotation only renders when the active animation is BOTH side-view
 *     AND a motion animation. For idle, sleep, greeting, or any
 *     front-view authoring, transformExtras returns 0° (settling there
 *     if the cat was previously rotated).
 *   - Strategy-local state (per-instance rotation angle) lives in a
 *     module-scoped WeakMap so different strategies don't see each
 *     other's state and a strategy switch can't leak.
 *
 * See docs/SPEC_PET_LOCOMOTION_REGISTRY.md §5 (transform ordering),
 * §2.4 (WeakMap convention), §2.7 (60° rotation cap rationale).
 */

import type { PetState } from "../petStore";
import type { PetInstance } from "../types";
import type {
  LocomotionStrategy,
  PickArea,
  StageDims,
  TransformExtras,
} from "./types";

/**
 * Run gait — fast locomotion. Mirrors the original
 * HORIZONTAL_SPEED_PX_PER_SEC from useAnimationLoop pre-extraction.
 */
const RUN_SPEED_PX_PER_SEC = 220;

/**
 * Walk gait — slower, used for short-distance clicks. ~40% of run
 * speed reads as a stroll without dragging the cat across the
 * viewport. Tuned by feel against the showcase's 96px display size.
 */
const WALK_SPEED_PX_PER_SEC = 90;

/**
 * Vertical climb speed is shared between gaits — half the run speed.
 * Diagonal travel approximates a 27° slope at run, steeper at walk.
 */
const VERTICAL_SPEED_PX_PER_SEC = 110;

/**
 * Click-distance threshold for picking gait. |dx| below this plays
 * walk; above plays run. 1.5× the pet's display size is "about a
 * pet-and-a-half over" — a small hop that should feel like a
 * stroll rather than a sprint.
 */
const WALK_RUN_THRESHOLD_FACTOR = 1.5;

/**
 * Sprite tilt cap. Beyond 60° the side-view rig looks anatomically
 * wrong (a side-view cat rotated 90° has its belly pointing at the
 * camera). When a properly authored top-down or 3/4-rear `climb`
 * animation arrives, this constant goes away.
 */
const MAX_TILT_DEG = 60;

/**
 * How fast the rotation angle returns to 0 when (a) motion stops or
 * (b) the active animation is not a side-view motion animation. 360°/s
 * = ~167ms to settle from full ±60° tilt — fast enough not to feel
 * sticky, slow enough to read as a deliberate settling motion.
 */
const TILT_SETTLE_DEG_PER_SEC = 360;

const ARRIVAL_EPSILON_PX = 1;

/**
 * Per-instance rotation angle, expressed as if the sprite faces right
 * (so the value is invariant under facing flips — applyTransform
 * applies rotation before scaleX). Lives in a WeakMap keyed by
 * PetInstance so strategies cannot see each other's state.
 */
const rotationDeg = new WeakMap<PetInstance, number>();

function getRotation(inst: PetInstance): number {
  return rotationDeg.get(inst) ?? 0;
}

function setRotation(inst: PetInstance, deg: number): void {
  rotationDeg.set(inst, deg);
}

function clamp(value: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, value));
}

function settleToward(current: number, target: number, maxDelta: number): number {
  const diff = target - current;
  if (Math.abs(diff) <= maxDelta) return target;
  return current + Math.sign(diff) * maxDelta;
}

/**
 * Is the active animation one this strategy treats as locomotion?
 * Both walk and run move the cat. motionPredicate exposes this same
 * answer to the engine.
 */
function isMotionAnim(anim: string): boolean {
  return anim === "run" || anim === "walk";
}

/**
 * Is the active animation on this pet authored as side-view? Read
 * from the manifest's per-animation view block. Front-view,
 * three-quarter, and top-down animations should not rotate.
 */
function isSideViewActive(pet: PetState): boolean {
  const a = pet.anims[pet.anim];
  return a?.view?.view_kind === "side";
}

/**
 * True when rotation should be computed and rendered for THIS pet:
 * side-view AND a motion animation. Otherwise the pet settles toward
 * 0° (handled in transformExtras).
 */
function rotationActive(pet: PetState): boolean {
  return isSideViewActive(pet) && isMotionAnim(pet.anim);
}

/**
 * Per-frame motion integration. Picks horizontal speed from the
 * currently-playing animation: `walk` uses WALK_SPEED, `run` uses
 * RUN_SPEED. Vertical speed is shared. Updates per-instance rotation
 * angle as a side effect (only meaningful when the rendered
 * transformExtras gates rotation on; the WeakMap stores the angle
 * either way so a click that crosses an animation transition
 * doesn't lose track).
 *
 * Facing is written into petStore by useAnimationLoop after this
 * tick runs, using dominantDx across all instances.
 */
function tick(pet: PetState, dtMs: number): void {
  const inst = pet.instance;
  const speedX = pet.anim === "walk"
    ? WALK_SPEED_PX_PER_SEC
    : RUN_SPEED_PX_PER_SEC;
  const stepX = speedX * (dtMs / 1000);
  const stepY = VERTICAL_SPEED_PX_PER_SEC * (dtMs / 1000);

  let dx = 0;
  let dy = 0;

  if (inst.targetX !== null) {
    dx = inst.targetX - inst.x;
    if (Math.abs(dx) >= ARRIVAL_EPSILON_PX) {
      inst.x = Math.abs(dx) < stepX
        ? inst.targetX
        : inst.x + Math.sign(dx) * stepX;
    }
  }

  const ty = inst.targetY;
  if (typeof ty === "number") {
    const cy = inst.y || 0;
    dy = ty - cy;
    if (Math.abs(dy) >= ARRIVAL_EPSILON_PX) {
      inst.y = Math.abs(dy) < stepY
        ? ty
        : cy + Math.sign(dy) * stepY;
    }
  }

  // Update the tracked rotation angle from the motion vector.
  //
  // Two coordinate-system mismatches the math has to reconcile:
  //
  //   Y AXIS: inst.y is "upward from floor" (positive = high), but
  //   CSS y is downward-positive. Negating dy when computing the
  //   angle makes "going up" produce a counter-clockwise rotation,
  //   which is what visually looks like nose-up.
  //
  //   FACING: the strategy's transform is composed
  //   `translate → rotate → scaleX(facing)`. CSS applies these
  //   right-to-left to the sprite content: scaleX flips the sprite
  //   horizontally FIRST, then rotate spins the (already-flipped)
  //   sprite. A rotation that produces head-up for a right-facing
  //   cat produces head-DOWN for a left-facing cat, because the
  //   mirrored sprite's "head" is on the opposite side of the
  //   rotation pivot. The cleanest fix is to negate the rotation
  //   for left-facing sprites — equivalent to "always tilt toward
  //   the world-direction of travel, regardless of which way the
  //   sprite happens to be visually oriented."
  //
  // Empirical check (all four diagonal cases):
  //   right + up:    angle<0 → rotate CCW → head ↗  ✓
  //   right + down:  angle>0 → rotate CW  → head ↘  ✓
  //   left  + up:    angle<0 × -1 = +     → rotate CW on flipped
  //                  sprite → head ↖  ✓
  //   left  + down:  angle>0 × -1 = -     → rotate CCW on flipped
  //                  sprite → head ↙  ✓
  //
  // |dx| (not dx) because the angle magnitude must be the same for
  // left and right travel — direction of facing is what tells us
  // which way "forward" is, and the facing multiplier handles that.
  const moving = Math.abs(dx) >= ARRIVAL_EPSILON_PX
              || Math.abs(dy) >= ARRIVAL_EPSILON_PX;
  if (moving) {
    // Visual facing for THIS frame: prefer the sign of horizontal
    // motion (we're already moving that direction), fall back to
    // current pet.facing for pure-vertical motion (cat is climbing
    // straight up/down — it stays facing wherever it was facing).
    // Reading dx directly avoids a one-frame lag when reversing
    // direction; pet.facing is updated AFTER the strategy tick
    // completes in the engine's moveTick.
    const visualFacing: 1 | -1 =
      dx > 0 ? 1 : dx < 0 ? -1 : pet.facing;
    const radians = Math.atan2(-dy, Math.abs(dx));
    const degrees = (radians * 180) / Math.PI * visualFacing;
    setRotation(inst, clamp(degrees, -MAX_TILT_DEG, MAX_TILT_DEG));
  }
  // The settle-toward-0 case is handled in transformExtras so that
  // rotation glides back to 0 even when the cat is no longer in a
  // motion animation (e.g. clicked, ran, then auto-state-machine
  // switched it to idle — tick stops being called for this instance,
  // but transformExtras still runs every frame).
}

/**
 * Where a quadruped is allowed to be. Permits the full vertical
 * range — but per spec §2.6, callers (auto wander, cursor chase /
 * approach) hold their target at y = 0 for ambient behavior; only
 * deliberate user clicks (useClickToWalk) take the cat upward.
 */
function pickableArea(stage: StageDims): PickArea {
  // One sprite-height of headroom at the top so a click flush against
  // the stage's upper edge doesn't render the cat's head clipped by
  // the viewport. Named so the intent is readable; the value is a
  // visual margin, not a CSS anchor — the strategy stays unaware of
  // host positioning conventions.
  const topHeadroom = stage.petSize;
  return {
    xMin: 0,
    xMax: Math.max(0, stage.width - stage.petSize),
    yMin: 0,
    yMax: Math.max(0, stage.height - topHeadroom),
  };
}

/**
 * Pick the locomotion animation for a given travel distance. Below
 * the threshold the cat walks (slower gait, no urgency for a small
 * hop); above, it runs. Callers without a distance get the default
 * `run` — that's the right answer for the auto state machine's
 * arrival check and any generic transition that doesn't know the
 * specific click context.
 *
 * The threshold is computed from the live --pet-display-size CSS
 * variable so resizing the pet rescales the threshold automatically.
 */
function motionAnim(distancePx?: number): string {
  if (typeof distancePx !== "number" || !Number.isFinite(distancePx)) {
    return "run";
  }
  // Read the live display size from the CSS variable. Falls back to
  // 96 (the showcase default) when called outside a browser context.
  let petSize = 96;
  if (typeof document !== "undefined") {
    const v = getComputedStyle(document.documentElement)
                .getPropertyValue("--pet-display-size").trim();
    const n = parseFloat(v);
    if (Number.isFinite(n) && n > 0) petSize = n;
  }
  const threshold = WALK_RUN_THRESHOLD_FACTOR * petSize;
  return Math.abs(distancePx) < threshold ? "walk" : "run";
}

function motionPredicate(anim: string): boolean {
  return isMotionAnim(anim);
}

/**
 * Species-level rest-exit weights for quadrupeds. Real cats walk most
 * of the time and only run when there's reason to — these defaults
 * encode that. The host's activity preference (chill / balanced /
 * energetic) layers on top of these in the auto state machine.
 *
 * Manifest fields named `rest_exit_weight` (currently 0.7 run / 0.3
 * walk in the catalog) are now treated as legacy fallbacks for
 * strategies that don't override this method. The strategy is the
 * right home for species behavior because:
 *   - Catalog values are content-factory facts (which pose template
 *     to use, what scales to render at) and shouldn't drive runtime.
 *   - The factory ships sprite frames; the host owns behavior. Same
 *     factoring as the locomotion registry itself.
 *   - Per-host overrides (energetic vs. chill user) need a stable
 *     base to multiply against; that base lives next to the species.
 */
function restExitWeights(): Record<string, number> {
  return {
    walk: 0.7,
    run:  0.3,
  };
}

/**
 * Quadruped's energetic gait is run. The activity_level multiplier
 * reweights run UP when the owner is "energetic" and DOWN when
 * "chill"; the inverse applies to walk. Stated explicitly because it
 * does NOT generalize from motionAnim() — that method is the
 * "default-when-distance-unknown" answer, which is a different
 * question than "which gait is fast for personality purposes." See
 * LocomotionStrategy.fastGaitAnim docstring.
 */
function fastGaitAnim(): string {
  return "run";
}

/**
 * Per-frame transform contribution. Decides whether rotation
 * applies to the current animation and either renders the tracked
 * angle or settles it toward 0.
 *
 * Gating rule: side-view + motion animation only. For front-view
 * idle / greeting and side-view rest (sleep), rotation settles to
 * 0° at TILT_SETTLE_DEG_PER_SEC so a cat that just finished running
 * up to a high target doesn't sit there tilted.
 *
 * Returns DATA (degrees), not a string fragment — applyTransform
 * owns the composed transform string and the operation order
 * (translate → rotate → scaleX).
 */
function transformExtras(pet: PetState, dtMs: number): TransformExtras {
  const inst = pet.instance;
  let angle = getRotation(inst);
  if (!rotationActive(pet)) {
    // Settle toward 0 when the active animation isn't a side-view
    // motion animation. Time-based so the settle is frame-rate
    // independent. dtMs may be 0 for callers outside the rAF loop;
    // those callers get the current angle without advancement.
    if (dtMs > 0 && angle !== 0) {
      const settleStep = TILT_SETTLE_DEG_PER_SEC * (dtMs / 1000);
      angle = settleToward(angle, 0, settleStep);
      setRotation(inst, angle);
    }
    return { rotateDeg: angle };
  }
  return { rotateDeg: angle };
}

export const quadruped: LocomotionStrategy = {
  tick,
  pickableArea,
  motionAnim,
  motionPredicate,
  transformExtras,
  // Quadruped opts into all three page-level behaviors. Cats and dogs
  // glance at cursors, walk to clicked floor points, and inhabit
  // [data-zone] regions. Future avian/aquatic strategies pick the
  // subset that fits their movement model.
  behaviorCapabilities: {
    cursorFollow: true,
    clickToWalk:  true,
    domZones:     true,
  },
  restExitWeights,
  fastGaitAnim,
};
