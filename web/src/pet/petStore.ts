"use client";

/**
 * petStore — the imperative state object the pet runtime reads from
 * and writes to during the per-frame loop. React analog of the vanilla
 * demoState object in app/live_demo/static/demo_state.js.
 *
 * Why imperative (not useState / Zustand):
 *
 *   The pet animation loop runs at ~60Hz and mutates `frameIdx`, `x`,
 *   `targetX`, `facing`, `frameElapsedMs` on every frame. Routing those
 *   mutations through React's reconciler would (a) burn CPU on
 *   re-renders no human can perceive, (b) fight React's strict-mode
 *   double-invocation in development, and (c) make the port less
 *   1:1 with the vanilla version. Instead, the loop reads/writes the
 *   store directly and pushes visual updates straight to the DOM via
 *   `style.transform` and `style.backgroundPosition`. React only owns
 *   the lifecycle (setup/teardown via useEffect), not the per-frame
 *   state.
 *
 * Multi-pet shape:
 *
 *   The store splits into PAGE-LEVEL fields (one rAF clock, one cursor)
 *   and a PER-PET `Map<petId, PetState>`. Each pet has its own sheet,
 *   anim, facing, personality, locomotion strategy, mirroring policy,
 *   and render position. Behaviors iterate the Map; the engine never
 *   counts pets and never names them. v1 ships with `pets.size === 1`
 *   on every datsme profile and on the datsPet showcase; the runtime
 *   is ready for 2–5 without engine changes.
 */

import type { AnimationsMap, MirroringPolicy, PetInstance, PetSheet } from "./types";
import type { LocomotionStrategy } from "./locomotion/types";
import { quadruped } from "./locomotion/quadruped";
import { getLocomotionStrategy } from "./locomotion/registry";
import {
  DEFAULT_PERSONALITY,
  type PetPersonality,
} from "./personality";

/**
 * The pet's CSS bottom offset (PetCanvas.tsx applies it as `bottom`
 * on the position: fixed wrapper). Anywhere the runtime converts
 * between viewport coordinates and inst.y MUST account for this
 * offset, because the pet's anchor is the viewport bottom plus
 * this value, not the literal viewport edge. Centralized here so
 * the CSS anchor and the click-math compensation are guaranteed to
 * change together — leaving it as a literal in three files invites
 * the silent breakage of "someone tweaks bottom: 32 to bottom: 16
 * and clicks land 16px low."
 *
 * Imported by PetCanvas.tsx (the style author), useClickToWalk.ts
 * (click-to-target conversion), and useDomZones.ts (zone center
 * conversion). If a fourth consumer appears, it imports from here
 * too.
 */
export const PET_BOTTOM_ANCHOR_PX = 32;

/**
 * Per-pet state. Everything in here scales with pet count: each entry
 * has its own sheet, anim, facing, personality, etc. Page-level state
 * (rAF clock, cursor coordinates, the Map itself) lives on PetStore.
 */
export interface PetState {
  petId: string;

  // ---- Sheet (set per-pet at applySheet time) ----
  sheetUrl: string;
  sourceFrame: number;
  sheetCols: number;
  sheetRows: number;
  anims: AnimationsMap;

  // ---- Animation (driven by useAnimationLoop) ----
  anim: string;
  frameIdx: number;
  frameElapsedMs: number;
  facing: 1 | -1;
  stateStartMs: number;

  // ---- Behavior coordination (per-pet) ----
  autoMode: boolean;
  forcedAnim: string | null;
  /**
   * Cursor-chase gate, set by useAutoStateMachine when the personality
   * preference roll picks `chase_cursor`. useCursorFollow reads this to
   * decide whether to engage chase logic for THIS pet on cursor moves.
   * Per-pet so a five-pet household where one pet rolled into chase
   * doesn't drag the other four with it.
   */
  cursorChaseArmed: boolean;

  // ---- View / mirroring (per-pet — derived from per-pet anim/sheet) ----
  // Active policy `applyTransform` reads per frame. Computed by
  // `recomputeMirroringPolicy(pet)` from three inputs:
  //   1. userMirroringOverride — host setting; null means "auto".
  //   2. The current animation's `view.mirroring_policy`, if present.
  //   3. sheetMirroringPolicy — manifest's top-level fallback.
  mirroringPolicy:        MirroringPolicy;
  sheetMirroringPolicy:   MirroringPolicy;
  userMirroringOverride:  MirroringPolicy | null;

  // ---- Locomotion (per-pet — different movement classes coexist) ----
  // Declaration vs. resolution stored separately on purpose:
  //   declaredMovementClass — what the manifest said (factory truth)
  //   activeStrategy        — what the host registry resolved that
  //                           string to (host policy)
  declaredMovementClass: string | undefined;
  activeStrategy:        LocomotionStrategy;

  // ---- Personality (per-pet) ----
  // Hydrated from `Pet.personality_profile` (per-user SQLite JSON
  // column) in datsme; from the showcase ConfigPopover here. Same
  // shape both sides — see personality.ts.
  personality: PetPersonality;

  // ---- Render position ----
  // Singular per pet. The vanilla showcase's "two render positions of
  // the same pet" (Mobile/Desktop preview) was a demo concern, not a
  // runtime concept; if it ever returns, the loop iterates pets ×
  // instances, but that's a deliberate add rather than a vestigial array.
  instance: PetInstance;
}

/**
 * Page-level store. One rAF clock, one cursor, one pet Map.
 */
interface PetStore {
  lastTickMs: number;
  pets: Map<string, PetState>;
}

export const petStore: PetStore = {
  lastTickMs: 0,
  pets: new Map(),
};

/**
 * Build a fresh PetState with neutral defaults. Caller fills in sheet
 * fields via applySheet(pet, sheet); personality is supplied by the
 * host at create time.
 */
function makePetState(petId: string, init: { personality: PetPersonality }): PetState {
  return {
    petId,
    sheetUrl: "",
    sourceFrame: 256,
    sheetCols: 16,
    sheetRows: 6,
    anims: {},
    anim: "idle",
    frameIdx: 0,
    frameElapsedMs: 0,
    facing: 1,
    stateStartMs: 0,
    autoMode: true,
    forcedAnim: null,
    cursorChaseArmed: false,
    // Default to "flip" — legacy unconditional-flip behavior. Manifests
    // written before docs/SPEC_PET_FACING.md omit `mirroring_policy`,
    // and for those breeds the previous behavior (mirror when going
    // left) is the right fallback. applySheet overwrites these when
    // the manifest carries explicit fields.
    mirroringPolicy:       "flip",
    sheetMirroringPolicy:  "flip",
    userMirroringOverride: null,
    declaredMovementClass: undefined,
    activeStrategy:        quadruped,
    personality:           init.personality,
    instance: {
      stageEl: null,
      petEl:   null,
      x:       0,
      y:       0,
      targetX: null,
      targetY: null,
    },
  };
}

/**
 * Upsert a pet into the store. Used by hosts (PetOverlay in datsme,
 * App.tsx in the showcase) on every fetched/declared pet entry. Idempotent
 * for the same petId — re-calling rebinds sheet + personality without
 * tearing down the existing render position.
 */
export function ensurePet(
  petId: string,
  init: { sheet: PetSheet; personality?: PetPersonality },
): PetState {
  let pet = petStore.pets.get(petId);
  if (!pet) {
    pet = makePetState(petId, {
      personality: init.personality ?? DEFAULT_PERSONALITY,
    });
    petStore.pets.set(petId, pet);
  } else if (init.personality) {
    pet.personality = init.personality;
  }
  applySheet(pet, init.sheet);
  return pet;
}

/**
 * Remove a pet from the store. Called on host unmount, on user
 * removal, or on PetCanvas teardown for that petId. Drops render
 * position too — caller is responsible for unmounting any DOM the pet
 * was bound to.
 *
 * Revokes the pet's sheetUrl blob to free the underlying bytes. See
 * docs/SPEC_PET_ASSET_CREDENTIALS_AND_FALLBACK.md §Change 1c — every
 * sheetUrl reaching applySheet (and therefore stored on PetState) is a
 * blob: URL. If the invariant is ever broken, revokeObjectURL on a
 * non-blob URL is a silent no-op.
 */
export function removePet(petId: string): void {
  const pet = petStore.pets.get(petId);
  if (pet && pet.sheetUrl) URL.revokeObjectURL(pet.sheetUrl);
  petStore.pets.delete(petId);
}

/**
 * Lookup. Behaviors iterating the Map call `getPet` only when they
 * have an id from a click handler / DOM hit-test; the per-frame loop
 * iterates `petStore.pets.values()` directly.
 */
export function getPet(petId: string): PetState | undefined {
  return petStore.pets.get(petId);
}

/**
 * Replace the sheet metadata + animations on one pet. Used on first
 * mount and on breed changes. Resets animation state to the resolved
 * rest pose on the new sheet (frame indices may differ between breeds).
 *
 * The mirror of core.js's replaceSheet(), now per-pet.
 */
export function applySheet(pet: PetState, sheet: PetSheet): void {
  // Free the previous sheet's blob: URL before overwriting. Invariant
  // (see docs/SPEC_PET_ASSET_CREDENTIALS_AND_FALLBACK.md §Change 1c):
  // every sheet.sheetUrl reaching applySheet is a blob: URL. On first
  // application pet.sheetUrl is the empty-string default from
  // makePetState; revokeObjectURL on "" is a silent no-op, so the
  // explicit truthiness check just avoids a useless call.
  if (pet.sheetUrl) URL.revokeObjectURL(pet.sheetUrl);
  pet.sheetUrl    = sheet.sheetUrl;
  pet.sourceFrame = sheet.sourceFrame;
  pet.sheetCols   = sheet.sheetCols;
  pet.sheetRows   = sheet.sheetRows;
  pet.anims       = sheet.anims;

  // Capture the manifest's top-level mirroring policy as the per-sheet
  // default. Per-animation `view.mirroring_policy` (when present) will
  // override this for individual animations via setAnim.
  pet.sheetMirroringPolicy = sheet.mirroringPolicy ?? "flip";

  // Resolve the locomotion strategy from the manifest's declared
  // movement_class. Both fields are kept on the pet: the raw declared
  // string for telemetry/debug, and the resolved strategy for dispatch.
  // Unknown classes fall back to quadruped (per registry policy).
  pet.declaredMovementClass = sheet.movementClass;
  pet.activeStrategy        = getLocomotionStrategy(sheet.movementClass);

  // Update this pet's element background-image and background-size.
  const df = getDisplayFrame();
  if (pet.instance.petEl) {
    pet.instance.petEl.style.backgroundImage =
      `url('${sheet.sheetUrl}')`;
    pet.instance.petEl.style.backgroundSize  =
      `${sheet.sheetCols * df}px ${sheet.sheetRows * df}px`;
  }

  // Reset to the resolved rest pose on the new sheet — honors the
  // owner's preferred_rest_anim if set, falls back to the manifest's
  // runtime_role: rest animation, then to literal "idle". setAnim
  // also recomputes the active mirroring policy.
  const restName = resolveRestAnim(pet);
  setAnim(pet, restName, { force: true });
  const restStart = pet.anims[restName]?.frames?.[0] ?? 0;
  if (pet.instance.petEl) setBgPos(pet, pet.instance.petEl, restStart);
}

/**
 * Recompute the active `mirroringPolicy` for one pet from the three
 * inputs: user override → current animation's per-animation view →
 * sheet-level default. Called by setAnim and by PetCanvas when the
 * user toggles the ConfigPopover.
 *
 * Per docs/SPEC_PER_ANIMATION_FACING.md §3.3.
 */
export function recomputeMirroringPolicy(pet: PetState): void {
  if (pet.userMirroringOverride !== null) {
    pet.mirroringPolicy = pet.userMirroringOverride;
    return;
  }
  const anim = pet.anims[pet.anim];
  const animPolicy = anim?.view?.mirroring_policy;
  pet.mirroringPolicy = animPolicy ?? pet.sheetMirroringPolicy;
}

/**
 * Set the current animation by name on one pet. No-op if already on
 * that anim unless `force: true`. Mirrors core.js's setAnim().
 */
export function setAnim(
  pet: PetState,
  name: string,
  opts: { force?: boolean } = {},
): void {
  const a = pet.anims[name];
  if (!a) return;
  if (pet.anim === name && !opts.force) return;
  pet.anim = name;
  pet.frameIdx = 0;
  pet.frameElapsedMs = 0;
  pet.stateStartMs = performance.now();

  // Switch the active mirroring policy when the animation changes.
  // Per-animation `view.mirroring_policy` (when present in the manifest)
  // overrides the sheet-level default. The user's ConfigPopover override
  // still wins over both. See docs/SPEC_PER_ANIMATION_FACING.md.
  recomputeMirroringPolicy(pet);

  const startFrame = a.frames[0];
  if (pet.instance.petEl) setBgPos(pet, pet.instance.petEl, startFrame);
}

/**
 * Resolve which animation should serve as the pet's "rest" state for
 * arrival, edge-stop, and timed-completion transitions. Three layers
 * of precedence:
 *
 *   1. pet.personality.preferred_rest_anim — owner override.
 *   2. The manifest's runtime_role: rest animation — content default.
 *   3. Literal "idle" — last-ditch fallback.
 */
export function resolveRestAnim(pet: PetState): string {
  const preferred = pet.personality.preferred_rest_anim;
  if (preferred && pet.anims[preferred]) return preferred;
  for (const [name, a] of Object.entries(pet.anims)) {
    if (a.runtime_role === "rest") return name;
  }
  return "idle";
}

/**
 * Map a linear cell index into (col, row) on the sheet, then set
 * background-position so the pet element shows that cell. Per-pet
 * because sheetCols varies between pets sharing the same page.
 */
export function setBgPos(pet: PetState, petEl: HTMLElement, linearIdx: number): void {
  const cols = pet.sheetCols;
  const col = linearIdx % cols;
  const row = Math.floor(linearIdx / cols);
  const df = getDisplayFrame();
  petEl.style.backgroundPosition = `${-col * df}px ${-row * df}px`;
}

/**
 * Apply translate + rotate + scaleX to one pet's instance.
 *
 * Operation ORDER is fixed: `translate → rotate → scaleX`. Rotation is
 * applied BEFORE the mirroring scaleX so that a strategy returning
 * `rotateDeg: 60` (nose-up) tilts the sprite the same direction
 * regardless of facing. See docs/SPEC_PET_LOCOMOTION_REGISTRY.md §5.
 *
 * The strategy returns DATA (rotateDeg as a number), not a string
 * fragment. This file owns the composed transform string and the
 * format (`rotate(${n}deg)`); strategies cannot accidentally violate
 * the order or inject other transform operations.
 *
 * y = 0 means floor-anchored (CSS `bottom`); positive y raises the pet
 * upward into the stage. scaleX is determined by pet.mirroringPolicy.
 * `facing` is always tracked by behaviors but only applied to the
 * transform when the policy says mirroring is the right answer for
 * this sprite.
 */
export function applyTransform(pet: PetState, dtMs: number = 0): void {
  const inst = pet.instance;
  if (!inst.petEl) return;
  const sx = resolveScaleX(pet.mirroringPolicy, pet.facing);
  // dtMs lets the strategy advance per-frame settling (rotation glide-
  // back, jitter phase, etc.) inside transformExtras. Defaults to 0
  // for callers outside the rAF loop.
  const extras = pet.activeStrategy.transformExtras(pet, dtMs);
  const rot = extras.rotateDeg;
  inst.petEl.style.transform =
    `translate(${inst.x}px, ${-(inst.y || 0)}px) `
    + `rotate(${rot}deg) `
    + `scaleX(${sx})`;
}

function resolveScaleX(policy: MirroringPolicy, facing: 1 | -1): 1 | -1 {
  switch (policy) {
    case "none":
      return 1;
    case "flip-from-left":
      return facing === 1 ? -1 : 1;
    case "flip":
    default:
      return facing === -1 ? -1 : 1;
  }
}

/**
 * Read the current --pet-display-size CSS variable. The loop and the
 * store both need this to compute background-size and cell offsets in
 * CSS px.
 */
export function getDisplayFrame(): number {
  if (typeof document === "undefined") return 96;
  const v = getComputedStyle(document.documentElement)
              .getPropertyValue("--pet-display-size").trim();
  const n = parseFloat(v);
  return Number.isFinite(n) && n > 0 ? n : 96;
}
