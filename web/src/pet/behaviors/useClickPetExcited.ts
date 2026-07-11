"use client";

/**
 * useClickPetExcited — clicking a pet itself triggers that pet's
 * excited animation (if its breed has one).
 *
 * One listener per pet element. The clicked pet is identified by the
 * listener closure, so multi-pet pages route the click correctly
 * without hit-testing.
 *
 * Uses stopPropagation so the click doesn't also reach useClickToWalk's
 * stage handler underneath.
 *
 * Re-attaches when the pet set changes — petEls come and go as canvases
 * mount/unmount, and a stale listener on a removed element does nothing
 * but a missing listener on a fresh element is silently broken. The
 * effect polls the pet Map size on each rAF tick to pick up new pets;
 * cheap because the body just adds/removes listeners on identity change.
 */

import { useEffect } from "react";
import { petStore, setAnim } from "../petStore";

interface Options {
  enabled?: boolean;
}

export function useClickPetExcited({ enabled = true }: Options = {}): void {
  useEffect(() => {
    if (!enabled) return;
    const removers = new Map<HTMLElement, () => void>();

    function syncListeners() {
      const seen = new Set<HTMLElement>();
      for (const pet of Array.from(petStore.pets.values())) {
        const petEl = pet.instance.petEl;
        if (!petEl) continue;
        seen.add(petEl);
        if (removers.has(petEl)) continue;
        const handler = (e: MouseEvent) => {
          e.stopPropagation();
          if (pet.autoMode && pet.anims.excited) {
            setAnim(pet, "excited");
          }
        };
        petEl.addEventListener("click", handler);
        removers.set(petEl, () => petEl.removeEventListener("click", handler));
      }
      // Drop listeners for pets that have unmounted.
      for (const [el, off] of Array.from(removers.entries())) {
        if (!seen.has(el)) {
          off();
          removers.delete(el);
        }
      }
    }

    let rafId: number | null = null;
    function loop() {
      syncListeners();
      rafId = requestAnimationFrame(loop);
    }
    loop();

    return () => {
      if (rafId !== null) cancelAnimationFrame(rafId);
      for (const off of Array.from(removers.values())) off();
      removers.clear();
    };
  }, [enabled]);
}
