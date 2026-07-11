"use client";

/**
 * useAnimationLoop — drives the per-frame render of every pet.
 *
 * Runs ONE requestAnimationFrame loop per page that iterates
 * `petStore.pets` and:
 *   1. Advances each pet's animation frame counter by elapsed ms.
 *   2. Dispatches per-frame motion to that pet's activeStrategy.tick(...)
 *      when the strategy says the current animation is a motion gate.
 *   3. Applies the resulting CSS transform + background-position to
 *      the pet's element via applyTransform.
 *
 * The rAF clock (lastTickMs) stays page-level — one ticker for the page
 * regardless of pet count. Per-pet state (frameIdx, anim, facing,
 * stateStartMs, instance.x/y) advances independently.
 *
 * Speed constants and the literal `petStore.anim === "run"` gate that
 * used to live here belong inside the strategy file (today: quadruped.ts).
 * The engine never branches on movement_class.
 *
 * Facing — set from the dominant horizontal motion of THIS pet — stays
 * here because facing is a render-time decision derived from per-frame
 * motion. Facing is per-pet now (pets in the same household don't share
 * a direction).
 */

import { useEffect } from "react";
import {
  petStore,
  applyTransform,
  setAnim,
  setBgPos,
  getDisplayFrame,
  resolveRestAnim,
  type PetState,
} from "./petStore";
import { readViewport } from "./viewport";

function frameTick(pet: PetState, dtMs: number): void {
  const a = pet.anims[pet.anim];
  if (!a) return;
  pet.frameElapsedMs += dtMs;
  const msPerFrame = 1000 / a.fps;
  while (pet.frameElapsedMs >= msPerFrame) {
    pet.frameElapsedMs -= msPerFrame;
    pet.frameIdx++;
    if (pet.frameIdx >= a.frames.length) {
      pet.frameIdx = a.loop ? 0 : a.frames.length - 1;
    }
  }
  const linearIdx = a.frames[pet.frameIdx];
  if (pet.instance.petEl) setBgPos(pet, pet.instance.petEl, linearIdx);
}

function moveTick(pet: PetState, dtMs: number): void {
  // The strategy decides whether motion integration runs for the
  // current animation. For quadruped this is `anim === "run" || "walk"`;
  // for a future bird strategy it might be `fly`. The engine does not
  // know which animation names mean "moving" — it asks.
  const strategy = pet.activeStrategy;
  if (!strategy.motionPredicate(pet.anim)) return;

  const inst = pet.instance;
  // Capture pre-tick dx so facing reflects intended direction even
  // if the strategy snaps to the target this frame.
  const dx = inst.targetX !== null ? inst.targetX - inst.x : 0;
  strategy.tick(pet, dtMs);

  if (!inst.stageEl) return;
  // Live viewport read so the edge-clamp tracks mobile URL-bar
  // collapse and orientation changes without subscription plumbing.
  const view = readViewport();
  const area = strategy.pickableArea({
    width:   inst.stageEl.clientWidth,
    height:  view.height,
    petSize: getDisplayFrame(),
  });

  // Engine-enforced edge invariant: the pet must stay inside the
  // strategy's pickableArea. Backstop — entry points already clamp
  // targets when they're set. Without this, a leftover target from
  // a prior interaction can drive the pet out of view with no
  // recovery path.
  const clampedX = Math.max(area.xMin, Math.min(area.xMax, inst.x));
  const clampedY = Math.max(area.yMin, Math.min(area.yMax, inst.y || 0));
  const hitEdge = clampedX !== inst.x || clampedY !== (inst.y || 0);
  if (hitEdge) {
    inst.x = clampedX;
    inst.y = clampedY;
    inst.targetX = null;
    inst.targetY = null;
  }

  if (dx !== 0) {
    pet.facing = dx > 0 ? 1 : -1;
  }

  // Switch to the rest animation if this pet hit an edge. Per-pet so
  // one pet's edge-stop doesn't yank other pets out of motion.
  if (hitEdge) {
    setAnim(pet, resolveRestAnim(pet));
  }
}

export function useAnimationLoop(): void {
  useEffect(() => {
    let rafId: number | null = null;
    petStore.lastTickMs = performance.now();

    function loop(now: number) {
      const dt = Math.min(now - petStore.lastTickMs, 50);
      petStore.lastTickMs = now;
      // forEach iterates the Map in place — the previous `Array.from(...)`
      // allocated a fresh array every frame (~60/s), churning GC for no
      // benefit. (forEach also sidesteps the downlevelIteration target
      // constraint that motivated the Array.from in the first place.)
      petStore.pets.forEach((pet) => {
        moveTick(pet, dt);
        frameTick(pet, dt);
        applyTransform(pet, dt);
      });
      rafId = requestAnimationFrame(loop);
    }

    // Pause the loop while the tab is hidden. Browsers already throttle rAF in
    // the background, but on a foregrounded-but-idle PWA this still ran every
    // frame; gating on visibility stops the per-frame work (and resets the
    // clock so the pet doesn't lurch by one giant dt on return).
    function start() {
      if (rafId === null) {
        petStore.lastTickMs = performance.now();
        rafId = requestAnimationFrame(loop);
      }
    }
    function stop() {
      if (rafId !== null) {
        cancelAnimationFrame(rafId);
        rafId = null;
      }
    }
    function onVisibilityChange() {
      if (document.visibilityState === "visible") start();
      else stop();
    }

    document.addEventListener("visibilitychange", onVisibilityChange);
    if (document.visibilityState === "visible") start();

    return () => {
      document.removeEventListener("visibilitychange", onVisibilityChange);
      stop();
    };
  }, []);
}
