"use client";

/**
 * PetCanvas — the React surface for ONE pet.
 *
 * Renders a single fixed-position <div> whose background-image is the
 * sprite sheet for the pet identified by `petId`, and registers the
 * element + a stage element on `pet.instance` so the engine and
 * behavior hooks can read/write its position and animation state.
 *
 * One PetCanvas per pet — the host (App.tsx for showcase, PetOverlay
 * for datsme) maps over its pet list and renders one canvas per entry.
 * Multi-pet pages mount multiple PetCanvas components; behavior hooks
 * (useAnimationLoop, useAutoStateMachine, useCursorFollow, etc.) live
 * at the HOST level — one set of hooks for the whole page, each
 * iterating petStore.pets — so cursor listeners and rAF loops aren't
 * multiplied per pet.
 *
 * Responsibilities of PetCanvas:
 *   - Render the per-pet <div> with the right CSS anchor and styling.
 *   - Register the DOM element on `pet.instance.petEl` and the stage
 *     element on `pet.instance.stageEl`.
 *   - Push host overrides (mirroringSetting) to the per-pet store.
 *
 * Not PetCanvas's job:
 *   - Calling behavior hooks. Those are page-level — the host owns them.
 *   - Calling ensurePet. The host owns pet lifecycle (it knows which
 *     pets exist and when they go away).
 */

import { useEffect, useRef } from "react";
import {
  petStore, recomputeMirroringPolicy, PET_BOTTOM_ANCHOR_PX,
  setBgPos, getDisplayFrame,
} from "./petStore";
import type { MirroringPolicy } from "./types";

/**
 * Mirroring setting passed in from showcase chrome. "auto" = honor the
 * manifest's `mirroring_policy`; any explicit value overrides it.
 */
type MirroringSetting = "auto" | MirroringPolicy;

interface Props {
  /** ID of the pet this canvas renders. Must be present in petStore.pets
   *  (i.e. the host has already called ensurePet with this id). */
  petId: string;

  /** The stage element (page root) the pet wanders within. */
  stageRef: React.RefObject<HTMLElement>;

  /** Initial x in stage-local pixels (defaults to 80). */
  initialX?: number;

  /** Mirroring policy override for this pet. "auto" honors the manifest;
   *  any explicit value wins. Defaults to "auto". */
  mirroringSetting?: MirroringSetting;
}

export function PetCanvas({
  petId,
  stageRef,
  initialX = 80,
  mirroringSetting = "auto",
}: Props) {
  const petRef = useRef<HTMLDivElement | null>(null);

  // Register the pet + stage refs on the pet's instance once the DOM
  // exists. Re-running when stageRef changes would tear down the
  // binding; refs in React are stable across renders so this only
  // runs on mount. Also re-bind background-image now that petEl
  // exists — the host's ensurePet ran before this effect (it created
  // the entry the canvas is rendering for) and stamped sheetUrl onto
  // the pet, but at that moment petEl was null.
  useEffect(() => {
    const petEl = petRef.current;
    const stageEl = stageRef.current;
    if (!petEl || !stageEl) return;
    const pet = petStore.pets.get(petId);
    if (!pet) return;
    pet.instance.stageEl = stageEl;
    pet.instance.petEl   = petEl;
    pet.instance.x       = initialX;
    pet.instance.y       = 0;
    pet.instance.targetX = null;
    pet.instance.targetY = null;

    // Bind sheet visuals to the freshly-mounted element. ensurePet
    // already ran applySheet on this pet (which set sheetUrl on the
    // pet record) but couldn't paint the element because it wasn't
    // mounted yet.
    const df = getDisplayFrame();
    if (pet.sheetUrl) {
      petEl.style.backgroundImage =
        `url('${pet.sheetUrl}')`;
      petEl.style.backgroundSize  =
        `${pet.sheetCols * df}px ${pet.sheetRows * df}px`;
      const startFrame = pet.anims[pet.anim]?.frames?.[0] ?? 0;
      setBgPos(pet, petEl, startFrame);
    }

    return () => {
      // Clear the binding so a hot-replaced canvas doesn't leave
      // dangling refs. Don't removePet here — that's the host's call.
      const cur = petStore.pets.get(petId);
      if (cur) {
        cur.instance.stageEl = null;
        cur.instance.petEl   = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [petId]);

  // Resolve effective mirroring policy: "auto" defers to the manifest's
  // per-animation + sheet-level fallbacks; any explicit setting wins.
  // Per docs/SPEC_PER_ANIMATION_FACING.md the actual switching happens
  // inside petStore — here we only record the user's preference and
  // recompute. Re-runs when the user flips the ConfigPopover.
  useEffect(() => {
    const pet = petStore.pets.get(petId);
    if (!pet) return;
    pet.userMirroringOverride =
      mirroringSetting === "auto" ? null : mirroringSetting;
    recomputeMirroringPolicy(pet);
  }, [mirroringSetting, petId]);

  return (
    <div
      ref={petRef}
      className="pet-canvas-sprite"
      data-pet-id={petId}
      style={{
        // Anchored to the VIEWPORT, not the stage. A real datsme user
        // sees their pet near the bottom of the screen no matter how
        // far they've scrolled.
        position: "fixed",
        // Effective bottom anchor = base offset + live BottomNav height.
        // BottomNav (web/src/components/layout/BottomNav.tsx) publishes
        // its measured height via --bottom-nav-height on documentElement;
        // the calc() means the browser keeps the pet floating above the
        // nav in real time as the nav appears, resizes, or unmounts. The
        // 0px fallback is exercised on logged-out / no-nav pages, where
        // the pet drops back to its natural floor anchor.
        // viewport.ts mirrors this same calculation in its
        // bottomAnchorPx field so click-math and zone-math stay aligned.
        bottom: `calc(${PET_BOTTOM_ANCHOR_PX}px + var(--bottom-nav-height, 0px))`,
        left: 0,
        width: "var(--pet-display-size, 96px)",
        height: "var(--pet-display-size, 96px)",
        backgroundRepeat: "no-repeat",
        backgroundPosition: "0 0",
        cursor: "pointer",
        zIndex: 5,
        pointerEvents: "auto",
      }}
    />
  );
}
