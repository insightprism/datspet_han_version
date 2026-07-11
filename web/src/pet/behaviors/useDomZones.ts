"use client";

/**
 * useDomZones — DOM-derived zones for pet wandering. Page-level.
 *
 * Scans the stage for [data-zone] elements at mount and on resize,
 * produces a list of zone records with geometry. The zone list is
 * page-level — one stage, one set of zones, regardless of pet count.
 * The auto state machine consumes these via:
 *
 *   - getZoneList()        — full list, for the ConfigPopover UI
 *                            and for "wildcard" uniform-random picks
 *   - pickTargetByZoneId(id) — produce a {x,y} target for a specific
 *                              zone (used when a pet's personality
 *                              preferences roll picks that zone)
 *   - pickTargetHome()     — produce a {x,y} target for the home
 *                            zone, regardless of which [data-zone]
 *                            id is marked as home
 *   - petIsOverHomeZone(inst)  — true when a pet's x is over the home
 *                                zone (used by auto state machine after
 *                                motion arrival)
 *
 * Click-to-zone: clicking a [data-zone] sends every capable pet there
 * in 2D (skipping clicks on interactive children). Multi-pet routing
 * is held pending product decision (§17.3); for v1 with one pet the
 * behavior is unchanged.
 */

import { useEffect } from "react";
import {
  petStore, setAnim, getDisplayFrame, type PetState,
} from "../petStore";
import { readViewport } from "../viewport";
import type { PetInstance } from "../types";

interface Zone {
  id: string;
  label: string;
  isHome: boolean;
  x0: number;
  x1: number;
  centerX: number;
  centerY: number;
  area: number;
}

export interface ZoneTarget {
  x: number;
  y: number;
}

export interface ZoneSummary {
  id: string;
  label: string;
  isHome: boolean;
}

let liveZones: Zone[] = [];

function scanZones(stageEl: HTMLElement): Zone[] {
  const stageRect = stageEl.getBoundingClientRect();
  const elements = stageEl.querySelectorAll<HTMLElement>("[data-zone]");
  const zones: Zone[] = [];
  const view = readViewport();
  for (const el of Array.from(elements)) {
    if (el === stageEl) continue;
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    const x0 = Math.max(0, r.left - stageRect.left);
    const x1 = Math.min(stageRect.width, r.right - stageRect.left);
    if (x1 - x0 < 20) continue;
    const viewportCenterY = (r.top + r.bottom) / 2;
    const centerY = view.height - viewportCenterY;
    zones.push({
      id: el.dataset.zone || "",
      label: el.dataset.zoneLabel || el.dataset.zone || "",
      isHome: el.dataset.zoneHome === "true",
      x0,
      x1,
      centerX: (x0 + x1) / 2,
      centerY,
      area: r.width * r.height,
    });
  }
  return zones;
}

export function getZoneList(): ZoneSummary[] {
  return liveZones.map((z) => ({
    id: z.id,
    label: z.label,
    isHome: z.isHome,
  }));
}

export function pickTargetByZoneId(zoneId: string): ZoneTarget | null {
  const z = liveZones.find((z) => z.id === zoneId);
  if (!z) return null;
  const span = z.x1 - z.x0;
  const jitter = (Math.random() - 0.5) * span * 0.6;
  return { x: z.centerX + jitter, y: z.centerY };
}

export function pickTargetHome(): ZoneTarget | null {
  const z = liveZones.find((z) => z.isHome);
  if (!z) return null;
  const span = z.x1 - z.x0;
  const jitter = (Math.random() - 0.5) * span * 0.6;
  return { x: z.centerX + jitter, y: z.centerY };
}

export function pickTargetWildcard(inst: PetInstance): ZoneTarget | null {
  if (!inst.stageEl) return null;
  const margin = 32;
  const w = inst.stageEl.clientWidth;
  const max = Math.max(margin + 1, w - getDisplayFrame() - margin);
  return {
    x: Math.floor(margin + Math.random() * (max - margin)),
    y: 0,
  };
}

export function petIsOverHomeZone(inst: PetInstance): boolean {
  const z = liveZones.find((z) => z.isHome);
  if (!z) return false;
  const px = inst.x + (inst.petEl?.clientWidth ?? 0) / 2;
  return px >= z.x0 && px <= z.x1;
}

interface Options {
  enabled?: boolean;
}

function pickStageEl(): HTMLElement | null {
  for (const pet of Array.from(petStore.pets.values())) {
    if (pet.instance.stageEl) return pet.instance.stageEl;
  }
  return null;
}

export function useDomZones({ enabled = true }: Options = {}): void {
  useEffect(() => {
    if (!enabled) return;

    let retryRaf: number | null = null;
    let stageEl: HTMLElement | null = null;
    const removers: Array<() => void> = [];

    function refresh() {
      if (stageEl) liveZones = scanZones(stageEl);
    }

    function dispatchZoneClick(z: Zone, pet: PetState) {
      if (!pet.activeStrategy.behaviorCapabilities.domZones) return;
      const inst = pet.instance;
      if (!inst.stageEl) return;
      const petW = getDisplayFrame();
      const view = readViewport();
      const adjustedY = z.centerY - view.bottomAnchorPx - petW / 2;
      const dx = z.centerX - inst.x;
      inst.targetX = z.centerX;
      inst.targetY = adjustedY;
      setAnim(pet, pet.activeStrategy.motionAnim(Math.abs(dx)));
    }

    function attach(stage: HTMLElement) {
      stageEl = stage;
      refresh();

      const zoneEls = stage.querySelectorAll<HTMLElement>("[data-zone]");
      for (const el of Array.from(zoneEls)) {
        if (el === stage) continue;
        const fn = (ev: MouseEvent) => {
          const t = ev.target as HTMLElement;
          if (t.closest("button, a, input, textarea, select")) return;
          const z = liveZones.find((z) => z.id === el.dataset.zone);
          if (!z) return;
          ev.stopPropagation();
          for (const pet of Array.from(petStore.pets.values())) {
            dispatchZoneClick(z, pet);
          }
        };
        el.addEventListener("click", fn);
        removers.push(() => el.removeEventListener("click", fn));
      }

      window.addEventListener("resize", refresh, { passive: true });
      window.addEventListener("orientationchange", refresh, { passive: true });
      removers.push(() => window.removeEventListener("resize", refresh));
      removers.push(() => window.removeEventListener("orientationchange", refresh));
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
      for (const off of removers) off();
    };
  }, [enabled]);
}
