/**
 * LOCOMOTION_REGISTRY — host policy for resolving a declared
 * `movement_class` string to a per-frame motion strategy.
 *
 * This is policy, not validation. The host owns this file; the
 * factory cannot reach it. A factory shipping a manifest with
 * `movement_class: "horse"` gets whatever this registry maps "horse"
 * to — today, the quadruped strategy. Any host can promote a class
 * to its own strategy by editing this map alone, with no factory
 * coordination (per docs/SPEC_PET_LOCOMOTION_REGISTRY.md §2.5a).
 *
 * Aliasing is first-class. Multiple declared classes can map to the
 * same strategy:
 *
 *   mammalian_quadruped, dog, cat, horse → quadruped
 *
 * Adding a new movement class is one new strategy file plus one line
 * here. The engine and behavior hooks never branch on movement_class —
 * they dispatch through `petStore.activeStrategy`.
 */

import type { LocomotionStrategy } from "./types";
import { quadruped } from "./quadruped";

/**
 * Map declared movement_class string → strategy instance. Strings on
 * the LEFT come from manifests written by datsPet's Step 6; strings
 * are the contract. Strategies on the RIGHT are host-internal — adding
 * one does not require any coordination with content factories.
 *
 * Aliases for individual species names (`dog`, `cat`) are present so
 * a partner factory that authors per-species movement classes (rather
 * than the generic `mammalian_quadruped` umbrella) gets the same
 * behavior without us having to ship a custom build. When a species
 * deserves its own behavior, we promote the alias to a real strategy
 * here — only this file changes.
 */
export const LOCOMOTION_REGISTRY: Record<string, LocomotionStrategy> = {
  mammalian_quadruped: quadruped,
  dog:                 quadruped,
  cat:                 quadruped,
};

/**
 * Resolve a declared class to a strategy. Unknown classes and missing
 * declarations both fall back to quadruped — the runtime is a delivery
 * target, not a build pipeline; it cannot reject input. A breed
 * declaring `movement_class: "fish"` before `fish.ts` exists gets
 * visibly-wrong-but-non-fatal quadruped behavior, not a black screen.
 *
 * This mirrors how Step 6's _derive_view_fields falls back to
 * silhouette-based defaults when the YAML lacks an explicit `view:`
 * block — same forgiveness pattern, applied at the runtime boundary.
 */
export function getLocomotionStrategy(
  declaredClass: string | undefined
): LocomotionStrategy {
  if (typeof declaredClass !== "string") return quadruped;
  return LOCOMOTION_REGISTRY[declaredClass] ?? quadruped;
}
