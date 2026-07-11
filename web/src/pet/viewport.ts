"use client";

/**
 * viewport — single source of truth for live device + window facts
 * the pet runtime needs.
 *
 * Three concerns this module owns:
 *
 *   1. Viewport dimensions (width/height in CSS px). Read live each
 *      call — mobile URL-bar collapse, orientationchange, browser
 *      window resize all change these mid-session, and motion code
 *      that compares against stale values puts the pet off-screen
 *      or clamps it incorrectly.
 *
 *   2. Pointer capability. matchMedia tells us whether the user has
 *      a real pointing device (mouse, trackpad). Touch-only devices
 *      have no `mousemove`, so cursor-follow modes (`glance`,
 *      `chase`, `approach`) are no-ops there. This module exposes
 *      the bit; consumers decide what to do with it.
 *
 *   3. The CSS anchor used to convert click Y to inst.y. This is a
 *      runtime fact (set by the host's CSS), not a device fact, but
 *      it ships next to the other viewport-conversion helpers
 *      because every consumer that converts clientY also needs the
 *      anchor.
 *
 * Stateless by design. Every call reads `window` live — no store, no
 * subscription, no useState. Reasons:
 *   - The engine reads from rAF at 60Hz. A React-state subscription
 *     would force re-renders no human can see (see petStore.ts:13
 *     for the same rationale).
 *   - Click handlers read at click-time, which is exactly when the
 *     value matters.
 *   - Behaviors that need to react to changes (useDomZones cache
 *     invalidation) already subscribe to `resize` /
 *     `orientationchange` directly. They stay as they are.
 *
 * What this module deliberately does NOT do:
 *   - Classify devices ("phone" / "tablet" / "desktop"). UA sniffing
 *     is unreliable, and motion code should branch on capability
 *     (has-pointer, viewport-size) not device class. Width-based
 *     classification (e.g. `<768px = phone`) belongs in chrome /
 *     layout code, not motion.
 *   - Cache or memoize. Live reads are sub-microsecond; caching
 *     introduces invalidation bugs.
 */

import { PET_BOTTOM_ANCHOR_PX } from "./petStore";

export interface ViewportSnapshot {
  /**
   * CSS pixels, live `window.innerWidth`. On mobile this excludes
   * the URL bar's footprint when collapsed.
   */
  width:  number;

  /**
   * CSS pixels, live `window.innerHeight`. Changes mid-session on
   * mobile when the URL bar hides/shows; readers should not cache.
   */
  height: number;

  /**
   * True when the user has a fine-grained pointer (mouse, trackpad,
   * stylus). False on touch-only devices. Cursor-follow modes
   * (`useCursorFollow`) should bail when this is false rather than
   * register `mousemove` listeners that will never fire.
   */
  hasPointer: boolean;

  /**
   * Pet's CSS bottom offset (PetCanvas.tsx). Re-exported here so a
   * single import handles both viewport math and the anchor
   * conversion the math depends on. The constant itself lives in
   * petStore.ts (single source of truth); this is a convenience
   * surface for consumers that already pull a viewport snapshot.
   */
  bottomAnchorPx: number;
}

/**
 * Test for fine-pointer capability. matchMedia is supported in every
 * browser the showcase targets (Chrome, Safari, Firefox, mobile
 * variants thereof). Defaults to `true` outside a browser context
 * (SSR / tests) so server-rendered behavior matches the desktop
 * fallback rather than silently disabling pointer features.
 */
function detectPointer(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return true;
  }
  // (hover: hover) — pointing device can hover (mouse, trackpad).
  // (pointer: fine) — has fine-grained pointing precision.
  // Both must be true for cursor-follow modes to make sense.
  return window.matchMedia("(hover: hover) and (pointer: fine)").matches;
}

/**
 * Read the live --bottom-nav-height CSS variable. BottomNav
 * (web/src/components/layout/BottomNav.tsx) publishes its measured
 * height here via a ResizeObserver — falls back to 0px when the nav
 * isn't mounted (e.g. on logged-out profiles or pages that don't
 * render BottomNav). Returning 0 in those cases lets the pet drop
 * back to the natural floor anchor without any extra branching.
 */
function readBottomNavHeight(): number {
  if (typeof document === "undefined") return 0;
  const v = getComputedStyle(document.documentElement)
              .getPropertyValue("--bottom-nav-height").trim();
  const n = parseFloat(v);
  return Number.isFinite(n) && n > 0 ? n : 0;
}

/**
 * Read a fresh snapshot of all viewport facts. Stateless — call
 * every time you need the value. Cheap; do not cache.
 *
 * The effective bottom anchor is PET_BOTTOM_ANCHOR_PX + the live
 * BottomNav height. Three consumers depend on this being a single
 * source of truth: PetCanvas (CSS anchor for the sprite element),
 * useClickToWalk (clientY → inst.y conversion), and useDomZones
 * (zone center → inst.y conversion). If any of them drifted from the
 * others by even a few px, clicks would land off-target. Reading
 * here keeps them in lockstep — when BottomNav resizes, all three
 * consumers automatically pick up the new value on their next read.
 *
 * For SSR / tests where `window` is undefined, returns a desktop-
 * shaped fallback (1280×800, has-pointer, no nav) so motion code paths
 * exercise the same branches they would on a real desktop.
 */
export function readViewport(): ViewportSnapshot {
  if (typeof window === "undefined") {
    return {
      width:          1280,
      height:         800,
      hasPointer:     true,
      bottomAnchorPx: PET_BOTTOM_ANCHOR_PX,
    };
  }
  return {
    width:          window.innerWidth,
    height:         window.innerHeight,
    hasPointer:     detectPointer(),
    bottomAnchorPx: PET_BOTTOM_ANCHOR_PX + readBottomNavHeight(),
  };
}
