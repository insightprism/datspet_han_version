"use client";

/**
 * PetStage — Pet Maker's host for the pet engine (the role PetOverlay
 * plays in datsme, minus datsme's auth/config/auto-adopt machinery).
 *
 * Give it a list of generated pets and they come alive on the page:
 * each pet's manifest + sprite sheet are fetched from the Pet Maker
 * API, registered in the engine's petStore, and rendered as a
 * PetCanvas. The engine's behavior hooks (animation loop, auto state
 * machine, click-to-walk, click-pet-excited) run once at this level
 * and drive every mounted pet.
 */

import { useEffect, useRef, useState } from "react";
import {
  PetCanvas, ensurePet, removePet,
  animsFromManifest, deriveRows,
  useAnimationLoop, useAutoStateMachine, useCursorFollow,
  useClickToWalk, useClickPetExcited, useDomZones,
} from "@/pet";
import type { PetSheet, RawManifest } from "@/pet";
import { petSheetUrl, petManifestUrl } from "@/lib/api";

export interface StagePet {
  id: string;
  display_name: string;
}

interface Props {
  pets: StagePet[];
  /** Rendered pet size in px (default 112). */
  displaySize?: number;
}

/** Fetch sheet PNG → blob: URL (CSS background-image can't send creds or
 *  survive cross-origin redraws; a blob URL sidesteps both — same strategy
 *  as datsme's PetOverlay). Ownership passes to the engine: removePet
 *  revokes it. */
async function loadSheetBlob(url: string): Promise<string> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Sheet fetch failed: HTTP ${res.status}`);
  return URL.createObjectURL(await res.blob());
}

export default function PetStage({ pets, displaySize = 112 }: Props) {
  const stageRef = useRef<HTMLDivElement>(null);
  const [loadedIds, setLoadedIds] = useState<string[]>([]);

  // Page-level engine hooks — one set for all pets on the stage.
  useAnimationLoop();
  useAutoStateMachine();
  useCursorFollow("off");
  useClickToWalk({ enabled: true });
  useClickPetExcited({ enabled: true });
  useDomZones({ enabled: false });

  useEffect(() => {
    const prev = document.documentElement.style.getPropertyValue("--pet-display-size");
    document.documentElement.style.setProperty("--pet-display-size", `${displaySize}px`);
    return () => {
      if (prev) document.documentElement.style.setProperty("--pet-display-size", prev);
      else document.documentElement.style.removeProperty("--pet-display-size");
    };
  }, [displaySize]);

  useEffect(() => {
    let cancelled = false;

    async function loadOne(pet: StagePet): Promise<string | null> {
      const r = await fetch(petManifestUrl(pet.id));
      if (!r.ok) return null;
      const m: RawManifest = await r.json();
      const blobUrl = await loadSheetBlob(petSheetUrl(pet.id));
      if (cancelled) {
        URL.revokeObjectURL(blobUrl);
        return null;
      }
      const sheet: PetSheet = {
        sheetUrl: blobUrl,
        sourceFrame: m.frame_width ?? 256,
        sheetCols: m.columns ?? 8,
        sheetRows: deriveRows(m),
        anims: animsFromManifest(m),
        viewKind: m.view_kind,
        nativeFacing: m.native_facing,
        mirroringPolicy: m.mirroring_policy,
        movementClass: m.movement_class,
      };
      ensurePet(pet.id, { sheet });
      return pet.id;
    }

    Promise.allSettled(pets.map(loadOne)).then((results) => {
      if (cancelled) return;
      setLoadedIds(
        results
          .map((r) => (r.status === "fulfilled" ? r.value : null))
          .filter((id): id is string => id !== null),
      );
    });

    return () => {
      cancelled = true;
      for (const pet of pets) removePet(pet.id);
      setLoadedIds([]);
    };
    // Re-load when the set of pet ids changes (not on array identity churn).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pets.map((p) => p.id).join(",")]);

  return (
    <div ref={stageRef}>
      {loadedIds.map((petId, i) => (
        <PetCanvas
          key={petId}
          petId={petId}
          stageRef={stageRef}
          initialX={80 + i * 150}
          mirroringSetting="auto"
        />
      ))}
    </div>
  );
}
