"use client";

/**
 * useClickToWalk — clicking the stage sends pets to that (x, y).
 *
 * Page-level — one click listener attached to any pet's stage (in v1
 * every pet shares the same stage). Iterates `petStore.pets` on each
 * click and dispatches per-pet:
 *   - pet.activeStrategy.behaviorCapabilities.clickToWalk must be true
 *   - the auto-mode + motion-animation guards apply per pet
 *
 * v1 routing policy: all capable pets respond to the click. With one
 * pet this matches the single-pet behavior; with multiple pets the
 * UX is a product call (closest-pet, primary-pet, all-pets) gated by
 * spec §17.2 — when that decision lands, the routing fans through
 * here.
 *
 * Click events on a pet itself (handled by useClickPetExcited) call
 * stopPropagation so click_pet_excited and click_to_walk don't both
 * fire on a pet click.
 */

import { useEffect } from "react";
import {
  petStore, getDisplayFrame, setAnim, type PetState,
} from "../petStore";
import { readViewport } from "../viewport";

interface Options {
  enabled?: boolean;
}

function pickStageEl(): HTMLElement | null {
  for (const pet of Array.from(petStore.pets.values())) {
    if (pet.instance.stageEl) return pet.instance.stageEl;
  }
  return null;
}

export function useClickToWalk({ enabled = true }: Options = {}): void {
  useEffect(() => {
    if (!enabled) return;
    let retryRaf: number | null = null;
    let stageEl: HTMLElement | null = null;
    let handler: ((e: MouseEvent) => void) | null = null;

    function dispatchTo(pet: PetState, e: MouseEvent, stage: HTMLElement) {
      if (!pet.activeStrategy.behaviorCapabilities.clickToWalk) return;
      const inst = pet.instance;
      if (inst.stageEl !== stage) return;
      const strategy = pet.activeStrategy;
      const view = readViewport();
      const rect = stage.getBoundingClientRect();
      const petW = getDisplayFrame();

      const area = strategy.pickableArea({
        width:   stage.clientWidth,
        height:  view.height,
        petSize: petW,
      });

      const clickX = e.clientX - rect.left - petW / 2;
      const clickY = view.height - view.bottomAnchorPx - petW / 2 - e.clientY;

      const targetX = Math.max(area.xMin, Math.min(area.xMax, clickX));
      const targetY = Math.max(area.yMin, Math.min(area.yMax, clickY));

      const activeIsMotion = strategy.motionPredicate(pet.anim);

      // Auto-mode guard: ignore clicks only when auto-mode is off AND
      // the active animation is non-motion. Motion animations keep
      // accepting clicks because that's how the user steers them.
      if (!pet.autoMode && !activeIsMotion) return;

      const dx = targetX - inst.x;
      const motionAnim = (!pet.autoMode && activeIsMotion)
        ? pet.anim
        : strategy.motionAnim(Math.abs(dx));
      if (!pet.anims[motionAnim]) return;

      inst.targetX = targetX;
      inst.targetY = targetY;
      setAnim(pet, motionAnim, { force: true });
    }

    function attach(stage: HTMLElement) {
      stageEl = stage;
      handler = (e: MouseEvent) => {
        for (const pet of Array.from(petStore.pets.values())) {
          dispatchTo(pet, e, stage);
        }
      };
      stage.addEventListener("click", handler);
    }

    function tryAttach() {
      const stage = pickStageEl();
      if (stage) {
        attach(stage);
        return;
      }
      retryRaf = requestAnimationFrame(tryAttach);
    }
    tryAttach();

    return () => {
      if (retryRaf !== null) cancelAnimationFrame(retryRaf);
      if (stageEl && handler) stageEl.removeEventListener("click", handler);
    };
  }, [enabled]);
}
