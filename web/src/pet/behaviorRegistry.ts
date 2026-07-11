/**
 * Behavior preference registry — the table of "things the pet can
 * decide to do," each with a stable id, a label for the owner UI,
 * and a runtime handler.
 *
 * Why a registry: the pet's personality (PetPersonality.preferences)
 * is an owner-editable probability table. Every behavior the owner
 * can configure must have a registry entry. Adding a new behavior
 * (e.g. "react to scroll") is one entry here plus a default
 * probability — the auto state machine, the cursor-follow gate, and
 * the ConfigPopover UI all consume the registry, so no consumer
 * code changes when a new id appears.
 *
 * Same plugin-with-registry pattern the locomotion strategies and
 * datsme's resident-pet capabilities use (datsme_me/docs/
 * SPEC_RESIDENT_PET.md §4.2.4).
 *
 * Two categories of behaviors live here:
 *
 *   DESTINATION — produces a wander target (x, y) for the pet to
 *   move to. Fires when the auto state machine rolls into this id's
 *   probability slice on rest-exit. Examples: home, zone:thoughts,
 *   zone:featured.
 *
 *   GATE — modifies behavior elsewhere in the runtime. Currently only
 *   `chase_cursor`, which enables cursor follow's chase logic when
 *   the gate has recently fired. Fires on the same rest-exit roll as
 *   destinations; "winning" the roll arms the gate for the next
 *   wander cycle.
 *
 * The runtime never branches on behavior id directly. It looks up
 * the registry entry, reads `kind`, and dispatches.
 */

import type { PetInstance } from "./types";

export type BehaviorKind = "destination" | "gate";

export interface BehaviorHandler {
  /**
   * Stable identifier. Owner-editable preferences store this string.
   * Zone-bound destinations use the prefix `zone:` followed by the
   * [data-zone] id; the registry handles the prefix in resolveBehavior.
   */
  id: string;

  /** Human-readable label for the ConfigPopover preferences table. */
  label: string;

  /** Optional emoji for the UI row. */
  icon?: string;

  /**
   * Whether this behavior produces a wander target or arms a gate.
   * See module docstring for the distinction.
   */
  kind: BehaviorKind;

  /**
   * For `destination` behaviors: produce a target (x, y) for the pet
   * to move to. Coordinate convention: x in stage-local pixels, y in
   * pet-y (upward from viewport floor — see PET_BOTTOM_ANCHOR_PX).
   * Return null when the behavior can't satisfy this call (e.g. the
   * named zone isn't on the page); the caller falls through to the
   * wildcard fallback.
   *
   * For `gate` behaviors: this is a no-op. The runtime tracks gate
   * arming separately (see useAutoStateMachine.lastGateBehavior).
   */
  resolveTarget?(inst: PetInstance): { x: number; y: number } | null;
}

/**
 * Statically-known behaviors. Zone destinations are NOT listed here —
 * they're generated dynamically from the live [data-zone] set so a
 * new section element added to the page automatically becomes a
 * preference option.
 *
 * The auto state machine and ConfigPopover consume both this static
 * list AND the dynamic zone list via `enumerateBehaviors(zones)`.
 */
export const STATIC_BEHAVIORS: BehaviorHandler[] = [
  {
    id: "home",
    label: "Go home",
    icon: "🏠",
    kind: "destination",
    // Home target resolution is delegated to useDomZones — it has
    // access to the live home zone (the page chrome marks one
    // [data-zone] with data-zone-home="true"). The auto state
    // machine reads `pickHomeTarget` from the window hook the same
    // way it reads zone targets. resolveTarget is overridden at
    // dispatch time; see useAutoStateMachine.
    resolveTarget: () => null,
  },
  {
    id: "chase_cursor",
    label: "Chase cursor",
    icon: "👆",
    kind: "gate",
  },
];

/**
 * Given the live set of [data-zone] elements on the page, produce
 * the full list of behaviors available to the owner — static
 * behaviors plus one `zone:<id>` destination per discovered zone
 * (excluding home, which gets its own dedicated entry).
 *
 * Order: home first, then static gates, then per-zone destinations.
 * UI renders rows in this order.
 */
export function enumerateBehaviors(
  zones: { id: string; label: string; isHome?: boolean }[],
): BehaviorHandler[] {
  const out: BehaviorHandler[] = [];
  // Home first
  const home = STATIC_BEHAVIORS.find((b) => b.id === "home");
  if (home) out.push(home);
  // Static gates next (currently just chase_cursor)
  for (const b of STATIC_BEHAVIORS) {
    if (b.id !== "home") out.push(b);
  }
  // Per-zone destinations (skip the home zone — it's already
  // represented by the "home" entry above)
  for (const z of zones) {
    if (z.isHome) continue;
    out.push({
      id: `zone:${z.id}`,
      label: `Visit ${z.label}`,
      icon: "📍",
      kind: "destination",
    });
  }
  return out;
}

/**
 * Lookup helper. Returns the static handler when the id is
 * statically known; for `zone:*` ids, synthesizes a handler with
 * the matching zone label. Returns null for unknown ids (graceful
 * forgiveness — an old saved preference referencing a deleted zone
 * just gets dropped, doesn't crash).
 */
export function resolveBehavior(
  id: string,
  zones: { id: string; label: string }[],
): BehaviorHandler | null {
  const stat = STATIC_BEHAVIORS.find((b) => b.id === id);
  if (stat) return stat;
  if (id.startsWith("zone:")) {
    const zid = id.slice("zone:".length);
    const z = zones.find((z) => z.id === zid);
    if (!z) return null;
    return {
      id,
      label: `Visit ${z.label}`,
      icon: "📍",
      kind: "destination",
    };
  }
  return null;
}
