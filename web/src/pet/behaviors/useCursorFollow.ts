"use client";

/**
 * useCursorFollow — pets react to cursor position with one of four modes:
 *
 *   off:      no cursor reaction
 *   glance:   each pet's facing direction tracks cursor x
 *   approach: each pet walks toward cursor when it stops moving for ~1.5s
 *   chase:    each pet continuously walks toward cursor
 *
 * Page-level — one set of listeners per page, attached to any pet's
 * stage (in v1 every pet shares the same stage, so it's stable).
 * Iterates `petStore.pets` on each event so per-pet capability gating
 * applies (a fish on the same page as a dog ignores the cursor).
 *
 * Per-pet gating:
 *   - pet.activeStrategy.behaviorCapabilities.cursorFollow must be true
 *   - In chase mode, pet.cursorChaseArmed must be true
 *
 * Passing mode: "off" disables the behavior — the hook's effect bails
 * before attaching listeners.
 */

import { useEffect } from "react";
import {
  petStore, getDisplayFrame, setAnim, type PetState,
} from "../petStore";
import { readViewport } from "../viewport";
import { isCursorChaseArmed } from "./useAutoStateMachine";

export type CursorFollowMode = "off" | "glance" | "approach" | "chase";

interface CursorState {
  cursorOverStage: HTMLElement | null;
  cursorXInStage: number | null;
  lastMouseMoveAt: number;
}

function pickStageEl(): HTMLElement | null {
  for (const pet of Array.from(petStore.pets.values())) {
    if (pet.instance.stageEl) return pet.instance.stageEl;
  }
  return null;
}

export function useCursorFollow(mode: CursorFollowMode): void {
  useEffect(() => {
    if (mode === "off") return;
    if (!readViewport().hasPointer) return;

    const state: CursorState = {
      cursorOverStage: null,
      cursorXInStage: null,
      lastMouseMoveAt: 0,
    };

    // The stage element may not be mounted on first effect run
    // (pets register asynchronously after mount). Poll briefly until
    // a pet shows up; bail cleanly if none does.
    let retryRaf: number | null = null;
    const removers: Array<() => void> = [];
    let approachRaf: number | null = null;

    function dispatchGlance(petX: number): { facing: 1 | -1 } | null {
      if (state.cursorXInStage === null) return null;
      return { facing: state.cursorXInStage > petX ? 1 : -1 };
    }

    function onMouseMove(stageEl: HTMLElement, e: MouseEvent) {
      const rect = stageEl.getBoundingClientRect();
      state.cursorOverStage = stageEl;
      state.cursorXInStage = e.clientX - rect.left;
      state.lastMouseMoveAt = performance.now();

      if (mode === "glance") {
        for (const pet of Array.from(petStore.pets.values())) {
          if (!pet.activeStrategy.behaviorCapabilities.cursorFollow) continue;
          // Only flip facing if THIS pet isn't currently in motion;
          // locomotion owns facing while moving, glance owns it
          // otherwise.
          if (pet.activeStrategy.motionPredicate(pet.anim)) continue;
          const g = dispatchGlance(pet.instance.x);
          if (g) pet.facing = g.facing;
        }
        return;
      }

      if (mode === "chase") {
        for (const pet of Array.from(petStore.pets.values())) {
          if (!pet.activeStrategy.behaviorCapabilities.cursorFollow) continue;
          // Honor THIS pet's chase_cursor preference roll.
          if (!isCursorChaseArmed(pet)) continue;
          chaseTick(pet);
        }
      }
    }

    function chaseTick(pet: PetState) {
      const inst = pet.instance;
      if (!inst.stageEl || state.cursorXInStage === null) return;
      const petW = getDisplayFrame();
      const targetX = Math.max(
        0,
        Math.min(
          inst.stageEl.clientWidth - petW,
          state.cursorXInStage - petW / 2
        )
      );
      const ARRIVAL_EPSILON_PX = 4;
      if (Math.abs(targetX - inst.x) < ARRIVAL_EPSILON_PX) return;

      const dx = targetX - inst.x;
      const motionAnim = pet.activeStrategy.motionAnim(Math.abs(dx));
      if (!pet.autoMode || !pet.anims[motionAnim]) return;
      // Chase is auto-mode behavior — stays floor-locked for quadruped
      // per spec §2.6.
      inst.targetX = targetX;
      inst.targetY = null;
      if (pet.anim !== motionAnim) setAnim(pet, motionAnim, { force: true });
    }

    function onMouseLeave(stageEl: HTMLElement) {
      if (state.cursorOverStage === stageEl) {
        state.cursorOverStage = null;
        state.cursorXInStage = null;
      }
    }

    function attachToStage(stageEl: HTMLElement) {
      const move = (e: MouseEvent) => onMouseMove(stageEl, e);
      const leave = () => onMouseLeave(stageEl);
      stageEl.addEventListener("mousemove", move);
      stageEl.addEventListener("mouseleave", leave);
      removers.push(() => {
        stageEl.removeEventListener("mousemove", move);
        stageEl.removeEventListener("mouseleave", leave);
      });

      if (mode === "approach") {
        const approachTick = (now: number) => {
          if (state.cursorOverStage && state.cursorXInStage !== null) {
            const sinceMove = now - state.lastMouseMoveAt;
            if (sinceMove > 1500) {
              const petW = getDisplayFrame();
              const target = state.cursorXInStage - petW / 2;
              for (const pet of Array.from(petStore.pets.values())) {
                if (!pet.activeStrategy.behaviorCapabilities.cursorFollow) continue;
                if (!pet.autoMode) continue;
                const inst = pet.instance;
                if (!inst.stageEl) continue;
                const targetX = Math.max(
                  0,
                  Math.min(inst.stageEl.clientWidth - petW, target)
                );
                const dx = targetX - inst.x;
                const motionAnim =
                  pet.activeStrategy.motionAnim(Math.abs(dx));
                if (
                  pet.anims[motionAnim] &&
                  pet.anim !== motionAnim
                ) {
                  inst.targetX = targetX;
                  inst.targetY = null;
                  setAnim(pet, motionAnim, { force: true });
                }
              }
            }
          }
          approachRaf = requestAnimationFrame(approachTick);
        };
        approachRaf = requestAnimationFrame(approachTick);
      }
    }

    function tryAttach() {
      const stageEl = pickStageEl();
      if (stageEl) {
        attachToStage(stageEl);
        return;
      }
      retryRaf = requestAnimationFrame(tryAttach);
    }
    tryAttach();

    return () => {
      if (retryRaf !== null) cancelAnimationFrame(retryRaf);
      for (const off of removers) off();
      if (approachRaf !== null) cancelAnimationFrame(approachRaf);
    };
  }, [mode]);
}
