/**
 * Locomotion strategy interface — the host-side contract that turns a
 * declared movement_class string into per-frame motion behavior.
 *
 * One strategy file per movement class; the registry maps strings to
 * strategy instances. The engine never branches on movement_class —
 * it dispatches through whichever strategy `petStore.activeStrategy`
 * resolved to at sheet-bind time.
 *
 * See docs/SPEC_PET_LOCOMOTION_REGISTRY.md for the full design and
 * the factory-vs-host framing that makes this a host-owned concern.
 */

import type { PetState } from "../petStore";
import type { RawManifest } from "../manifest";

/**
 * Stage dimensions in CSS px the strategy uses to clamp targets.
 * Mirrors what behavior hooks read from `inst.stageEl.client*` —
 * passing it explicitly keeps strategies free of DOM dependencies.
 */
export interface StageDims {
  width:  number;
  height: number;
  /**
   * Per-pet sprite display size in px (one cell on screen). Used by
   * strategies that need to leave a margin so the sprite doesn't
   * clip the stage edges.
   */
  petSize: number;
}

/**
 * Where the species is allowed to be on the stage. y is measured
 * upward from the floor (matches `inst.y` and the `bottom: 32` anchor
 * applied in petStore.applyTransform). yMin === yMax === 0 means the
 * strategy is floor-locked.
 */
export interface PickArea {
  xMin: number;
  xMax: number;
  yMin: number;
  yMax: number;
}

/**
 * Optional transform fragment a strategy contributes per frame.
 * Strategies return DATA (not strings); applyTransform owns the
 * composed transform string and the order of operations
 * (translate → rotate → scaleX) per spec §5.
 *
 * Returning numeric data lets every strategy agree on units and lets
 * the engine validate / clamp / format consistently. A strategy that
 * doesn't rotate returns { rotateDeg: 0 }.
 */
export interface TransformExtras {
  /**
   * Rotation angle in degrees, expressed as if the sprite always
   * faces right. applyTransform applies this BEFORE scaleX(facing),
   * so the tilt direction tracks visual facing without sign-flipping.
   */
  rotateDeg: number;
}

/**
 * Species-level rest-exit weight defaults. The strategy declares "in
 * the absence of any host preference, when this species is idle and
 * decides to do something, what fraction of the time should it walk
 * vs. run vs. eat vs. ...".
 *
 * Keys are animation names the strategy knows about (walk, run for
 * quadruped; fly, walk for a future bird). Values are positive
 * weights that get normalized at pick time — they don't have to sum
 * to 1.0, just be in proportion.
 *
 * The auto state machine layers user activity preference on top of
 * these (see ActivityPreference and resolveRestExitWeights). Animations
 * the strategy doesn't mention here keep their manifest-declared
 * weights — that lets a strategy speak only to the gaits it owns
 * (walk/run) without overriding species-orthogonal animations like
 * sleep or eat.
 */
export type RestExitWeights = Record<string, number>;

/**
 * Per-strategy declaration of which page-level behaviors the species
 * opts into. Behaviors that don't fit a movement class are gated off
 * at the strategy boundary rather than at the call site, so adding a
 * new movement class doesn't force an audit of every behavior file.
 *
 *   cursorFollow — does this species track the cursor visually
 *                  (glance/chase/approach modes)? A fish doesn't.
 *   clickToWalk  — does clicking the floor send this species there?
 *                  Aquatic species would respond to clicks inside a
 *                  water zone, not arbitrary floor clicks.
 *   domZones     — does this species occupy [data-zone] regions for
 *                  ambient wander destinations?
 *
 * Quadruped declares all three: true. A future avian or aquatic
 * strategy declares the subset that fits its movement model. Behavior
 * hooks gate on `pet.activeStrategy.behaviorCapabilities` per pet —
 * mixed-class households (a dog plus a fish) work without changing
 * the behavior code.
 */
export interface BehaviorCapabilities {
  cursorFollow: boolean;
  clickToWalk:  boolean;
  domZones:     boolean;
}

/**
 * The strategy interface every movement class implements. Five
 * required methods + behaviorCapabilities, three optional methods.
 *
 * - tick — per-frame motion integration (x/y/facing/rotation)
 * - pickableArea — where the species is allowed to go
 * - motionAnim — animation name to play when "I am moving"
 * - motionPredicate — true when motion integration should run
 * - transformExtras — per-frame transform contribution (rotation, etc)
 * - behaviorCapabilities — which page-level behaviors this class opts into
 * - configureFromManifest? — optional pull of per-breed numeric tuning
 * - restExitWeights? — species-level base weights for ambient activity
 * - fastGaitAnim? — names the "energetic" gait for activity_level
 */
export interface LocomotionStrategy {
  /**
   * Per-frame motion integration for ONE pet. The strategy reads
   * `pet.anim` for gait selection and `pet.facing` for direction-aware
   * rotation, then mutates `pet.instance.x/y` and any per-pet rotation
   * state it owns.
   */
  tick(pet: PetState, dtMs: number): void;
  pickableArea(stage: StageDims): PickArea;
  /**
   * Animation name to play when starting motion. Optional `distancePx`
   * lets the strategy pick between gaits — e.g. quadruped returns
   * `"walk"` for short distances and `"run"` for long ones. Callers
   * that don't know the distance (auto state machine arrival check,
   * generic transitions) pass nothing and get the strategy's default.
   */
  motionAnim(distancePx?: number): string;
  motionPredicate(anim: string): boolean;
  /**
   * Per-frame transform contribution for ONE pet's instance. Returns
   * the rotation angle (and any future extras); applyTransform composes
   * the full transform string.
   */
  transformExtras(pet: PetState, dtMs: number): TransformExtras;

  /**
   * Required. Declares which page-level behaviors this species opts
   * into. See BehaviorCapabilities. Per-pet-level gating happens at
   * the behavior hook boundary so mixed-class households work
   * without engine changes.
   */
  behaviorCapabilities: BehaviorCapabilities;

  /**
   * Optional. Called once at applySheet time, after the strategy is
   * resolved. The strategy decides which (if any) RawManifest fields
   * it cares about; unknown fields are ignored. Read direction is
   * PULL (strategy reads what it wants) — the engine never PUSHES
   * raw manifest fields as forced parameters.
   *
   * v1 quadruped does not implement this. It exists so that per-breed
   * numeric tuning fields (e.g. `flight_speed_multiplier`,
   * `max_tilt_deg`) have a clean home when they land — without
   * forcing every per-breed variation through a new movement_class.
   */
  configureFromManifest?(raw: RawManifest): void;

  /**
   * Optional. Returns the strategy's species-level rest-exit weights.
   * The auto state machine consults this BEFORE falling back to the
   * manifest's own `rest_exit_weight` fields, then applies any host-
   * level activity preference on top.
   *
   * This puts species defaults next to the strategy that defines the
   * species ("how does a quadruped behave at rest"), where they
   * belong — not in the manifest, which is content-factory output and
   * shouldn't dictate runtime behavior.
   *
   * Strategies that don't override this leave the auto state machine
   * reading manifest weights as before — fully backwards-compatible.
   */
  restExitWeights?(): RestExitWeights;

  /**
   * Optional. Names which motion animation is the strategy's
   * "energetic" gait — the one whose weight goes UP when the host's
   * activity_level is high, and DOWN when it's low. The opposite
   * weight applies to other motion animations.
   *
   * Two distinct concerns this method separates:
   *   - motionAnim(distance) — API contract: "which gait should the
   *     pet play, given a known travel distance?" Used for click-to-
   *     walk and chase. Always returns a name.
   *   - fastGaitAnim() — personality contract: "which gait is the
   *     energetic one for the activity_level multiplier?" May
   *     return null when the species has no fast/slow distinction.
   *
   * For quadruped these happen to coincide (run is both the default
   * gait when distance is unknown AND the energetic gait), but for a
   * single-gait species (e.g. a future bird where fly is the only
   * motion anim) returning null prevents the activity multiplier from
   * accidentally biasing behavior up or down — there's no "slower"
   * alternative to bias toward.
   *
   * Strategies that don't override this leave activity_level inert
   * for them. The auto state machine still applies species defaults
   * and manifest fallbacks; only the personality multiplier sits
   * idle.
   */
  fastGaitAnim?(): string | null;
}
