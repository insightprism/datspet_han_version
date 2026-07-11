"use client";

/**
 * useAutoStateMachine — autonomous pet behavior. Iterates every pet.
 *
 * Same animation-name-free dispatch over runtime_role + per-role
 * weights from the manifest. Per-pet rest dwell, per-pet wander target,
 * per-pet cursor-chase gate. No pet's state machine influences another's.
 *
 * No animation names appear literally in this file — adding a new
 * TIMED animation reachable from REST or run-arrival is a manifest
 * edit (declare rest_exit_weight or run_arrival_weight on the new
 * animation); this hook picks it up generically.
 *
 * Owns: pet.anim transitions when autoMode is true, and the per-pet
 * targetX/targetY when entering ACTIVE animations.
 */

import { useEffect } from "react";
import {
  petStore, setAnim, resolveRestAnim,
  type PetState,
} from "../petStore";
import {
  pickTargetByZoneId, pickTargetHome, pickTargetWildcard,
  getZoneList, petIsOverHomeZone,
} from "./useDomZones";
import { resolveBehavior } from "../behaviorRegistry";
import type { AnimationsMap } from "../types";

const DEFAULT_REST_DWELL_MS: [number, number] = [2500, 6000];

/**
 * The cursor-chase gate is per-pet — stored as `pet.cursorChaseArmed`.
 * The personality's `chase_cursor` preference is rolled each time the
 * auto state machine picks a new wander destination for THAT pet. When
 * the roll picks chase_cursor for a given pet, that pet's flag is set;
 * useCursorFollow.ts reads `pet.cursorChaseArmed` to decide whether
 * chase mode is currently armed for that pet.
 *
 * `isCursorChaseArmed(pet)` is exported so cursor follow can check
 * without crossing through window globals — same explicit-coupling
 * convention as petIsOverHomeZone.
 */
export function isCursorChaseArmed(pet: PetState): boolean {
  return pet.cursorChaseArmed;
}

/**
 * Roll against the personality preference table for ONE pet and pick
 * the next wander target. Same behavior as before, scoped to a single
 * pet's personality and instance.
 */
function pickWanderTarget(pet: PetState): { x: number; y: number } | null {
  const inst = pet.instance;
  const prefs = pet.personality.preferences;
  const sum = prefs.reduce((s, p) => s + Math.max(0, p.probability), 0);
  const norm = sum > 1 ? 1 / sum : 1;
  const roll = Math.random();
  let cursor = 0;
  for (const pref of prefs) {
    const p = Math.max(0, pref.probability) * norm;
    cursor += p;
    if (roll < cursor) {
      const behavior = resolveBehavior(pref.id, livePageZones());
      if (!behavior) break;
      if (behavior.kind === "gate" && behavior.id === "chase_cursor") {
        // Cursor chase wins — arm THIS pet's gate.
        pet.cursorChaseArmed = true;
        const wildcard = pickTargetWildcard(inst);
        return wildcard ? { x: wildcard.x, y: 0 } : null;
      }
      pet.cursorChaseArmed = false;
      let target: { x: number; y: number } | null = null;
      if (behavior.id === "home") {
        target = pickTargetHome();
      } else if (behavior.id.startsWith("zone:")) {
        target = pickTargetByZoneId(behavior.id.slice("zone:".length));
      }
      if (target) return { x: target.x, y: 0 };
      break;
    }
  }
  pet.cursorChaseArmed = false;
  const wildcard = pickTargetWildcard(inst);
  return wildcard ? { x: wildcard.x, y: 0 } : null;
}

function livePageZones(): { id: string; label: string }[] {
  return getZoneList().map((z) => ({ id: z.id, label: z.label }));
}

/**
 * Resolve the effective rest-exit weight for one animation on one pet,
 * layering strategy species default → manifest weight → personality
 * activity multiplier. activityLevel is per-pet (each pet has its own
 * personality profile), so the multiplier varies between pets.
 */
function resolveWeight(
  pet: PetState,
  name: string,
  manifestWeight: number,
  strategyWeights: Record<string, number> | null,
): number {
  let base = manifestWeight;
  if (strategyWeights && name in strategyWeights) {
    base = strategyWeights[name];
  }
  if (base <= 0) return 0;
  if (!pet.activeStrategy.motionPredicate(name)) return base;

  const fastGait = pet.activeStrategy.fastGaitAnim?.() ?? null;
  if (fastGait === null) return base;

  const raw = pet.personality.activity_level;
  const level = Number.isFinite(raw) ? Math.max(0, Math.min(1, raw)) : 0.5;

  const isFastGait = name === fastGait;
  const fastFactor = level <= 0.5
    ? 0.5 + level
    : 1.0 + 2 * (level - 0.5);
  const slowFactor = level <= 0.5
    ? 1.0 + 2 * (0.5 - level)
    : 1.5 - level;
  return base * (isFastGait ? fastFactor : slowFactor);
}

function pickRestExitAnim(pet: PetState, anims: AnimationsMap): string | null {
  const strategyWeights =
    pet.activeStrategy.restExitWeights?.() ?? null;

  const animNames = new Set<string>(Object.keys(anims));
  if (strategyWeights) {
    for (const name of Object.keys(strategyWeights)) animNames.add(name);
  }

  const candidates: Array<[string, number]> = [];
  for (const name of Array.from(animNames)) {
    const a = anims[name];
    if (!a) continue;
    const manifestW = a.rest_exit_weight || 0;
    const w = resolveWeight(pet, name, manifestW, strategyWeights);
    if (w > 0) candidates.push([name, w]);
  }
  if (candidates.length === 0) return null;

  const total = candidates.reduce((s, [, w]) => s + w, 0);
  let r = Math.random() * total;
  for (const [name, w] of candidates) {
    r -= w;
    if (r <= 0) return name;
  }
  return candidates[candidates.length - 1][0];
}

function pickRunArrivalAnim(anims: AnimationsMap): string | null {
  const candidates = Object.entries(anims).filter(
    ([, a]) => (a.run_arrival_weight || 0) > 0
  );
  if (candidates.length === 0) return null;
  const r = Math.random();
  let cumulative = 0;
  for (const [name, a] of candidates) {
    cumulative += (a.run_arrival_weight || 0);
    if (r < cumulative) return name;
  }
  return null;
}

function autoTickPet(pet: PetState, now: number): void {
  if (!pet.autoMode) return;
  const sinceState = now - pet.stateStartMs;
  const ANIMS = pet.anims;
  const currentName = pet.anim;
  const currentAnim = ANIMS[currentName];
  if (!currentAnim) return;

  const restName = resolveRestAnim(pet);
  const isRestState = currentName === restName;

  if (currentAnim.runtime_role === "active") {
    // Only locomotion animations arm an arrival check.
    if (pet.activeStrategy.motionPredicate(currentName)) {
      const inst = pet.instance;
      const arrived =
        inst.targetX === null || Math.abs(inst.x - inst.targetX) < 4;
      if (!arrived) return;
      // Side-effect hook for future capabilities that care about
      // "the pet just settled at home" (e.g. switch to sleep when
      // arriving home). Today the predicate is read but no action
      // fires.
      void petIsOverHomeZone(inst);
      inst.targetX = null;
      // Auto wander stays floor-locked (spec §2.6).
      inst.targetY = null;
      const next = pickRunArrivalAnim(ANIMS);
      setAnim(pet, next !== null ? next : restName);
    }
    return;
  }

  if (isRestState) {
    const [min, max] = currentAnim.rest_dwell_ms || DEFAULT_REST_DWELL_MS;
    const dwell = min + Math.random() * (max - min);
    if (sinceState < dwell) return;
    const next = pickRestExitAnim(pet, ANIMS);
    if (next === null) return;
    if (ANIMS[next] && ANIMS[next].runtime_role === "active") {
      const target = pickWanderTarget(pet);
      if (target) {
        pet.instance.targetX = target.x;
        pet.instance.targetY = null;
      }
    }
    setAnim(pet, next);
    return;
  }

  if (currentAnim.runtime_role === "timed") {
    const buf = currentAnim.timed_buffer_ms || 0;
    const dur = currentAnim.loop
      ? buf
      : (currentAnim.frames.length / currentAnim.fps) * 1000 + buf;
    if (sinceState > dur) setAnim(pet, restName);
    return;
  }

  // TRIGGERED animations are never auto-driven (only fired from
  // per-trigger behaviors like useClickPetExcited).
}

function autoTick(now: number): void {
  for (const pet of Array.from(petStore.pets.values())) {
    autoTickPet(pet, now);
  }
}

export function useAutoStateMachine(): void {
  useEffect(() => {
    let rafId: number | null = null;
    function tick(now: number) {
      autoTick(now);
      rafId = requestAnimationFrame(tick);
    }
    rafId = requestAnimationFrame(tick);
    return () => {
      if (rafId !== null) cancelAnimationFrame(rafId);
    };
  }, []);
}
