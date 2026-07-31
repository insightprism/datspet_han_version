"use client";

/**
 * PosePlayer — plays ONE named animation of a pet by cycling that pose's frames
 * from the real sprite sheet on a canvas. Used by PoseGallery on the result panel
 * so each generated pose (walk, idle, run, …) can be seen animating independently —
 * a direct visual check that the multi-pose build produced distinct motion.
 *
 * Reuses PetThumbnail's sheet-crop approach, extended from one still frame to a
 * frame loop at the pose's fps (respecting prefers-reduced-motion).
 */
import { useEffect, useRef } from "react";
import type { RawManifest } from "@/pet";
// The source resolution lives in its own pure module so it can be tested without a DOM —
// PoseGallery's `petId` path is user-visible and must not regress (posePlayerSource.ts).
import { posePlayerUrls, type PoseSource } from "./posePlayerSource";

/**
 * WHERE THE FRAMES COME FROM. Two shapes, because there are two kinds of caller
 * (SPEC_MATTE_REPAIR_ORDER §12.4 / SPEC_MOTION_LAB_DESIGN_PARITY §2.5):
 *
 *   petId              a SAVED pet — the result panel's PoseGallery. Derives both URLs.
 *   {sheetUrl,
 *    manifestUrl}      an arbitrary sheet — the Motion Lab's packed tile, which is a
 *                      scratch bundle with no pet row behind it.
 *
 * A union rather than a second component: the Lab's packed tile must be rendered by the
 * SAME code the user's result card uses, or "does this imitate what really happens" has
 * no answer. A second frame-cycling implementation is exactly how the two would start
 * disagreeing about fps, column count or the final-frame duplicate.
 */
export type { PoseSource };

interface Props {
  /** A saved pet id — the original call shape, unchanged for PoseGallery. */
  petId?: string;
  /** …or an explicit sheet + manifest, for a bundle that was never saved as a pet. */
  source?: PoseSource;
  pose: string;
  size?: number;
  /** Fill the parent's width instead of a fixed px box, keeping it square. For
   *  callers whose column width is responsive — the store card's grid is 2/3/4
   *  columns by breakpoint, so no single `size` is right. */
  fill?: boolean;
  /** Draw a checkerboard behind the frames, so MISSING ALPHA is visible (§2.5). */
  checkered?: boolean;
}

export default function PosePlayer({ petId, source, pose, size = 128, fill, checkered }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const src: PoseSource | null = source ?? (petId ? { petId } : null);
  // Depend on the resolved URLs, not the object identity: `source={{…}}` is a fresh
  // object every render, and an effect keyed on it would restart the animation each time.
  const { manifest: manifestUrl, sheet: sheetUrl } = src ? posePlayerUrls(src) : { manifest: "", sheet: "" };

  useEffect(() => {
    if (!manifestUrl || !sheetUrl) return;
    let cancelled = false;
    let raf = 0;

    (async () => {
      const m: RawManifest = await (await fetch(manifestUrl, { credentials: "include" })).json();
      const sheet = new Image();
      sheet.crossOrigin = "anonymous";
      sheet.src = sheetUrl;
      await sheet.decode();
      if (cancelled || !canvasRef.current) return;

      const anim = (m.animations ?? {})[pose];
      const frames = anim?.frames ?? [0];
      const fps = anim?.fps ?? 12;
      const cols = m.columns ?? 8;
      const fw = m.frame_width ?? 256;
      const fh = m.frame_height ?? 256;
      const ctx = canvasRef.current.getContext("2d");
      if (!ctx) return;

      const drawFrame = (idx: number) => {
        ctx.clearRect(0, 0, fw, fh);
        ctx.drawImage(sheet, (idx % cols) * fw, Math.floor(idx / cols) * fh, fw, fh, 0, 0, fw, fh);
      };

      // Reduced-motion: show the first frame, don't animate.
      const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
      if (reduce || frames.length <= 1) {
        drawFrame(frames[0] ?? 0);
        return;
      }

      const interval = 1000 / Math.max(1, fps);
      let last = performance.now();
      let i = 0;
      drawFrame(frames[0]);
      const tick = (now: number) => {
        if (cancelled) return;
        if (now - last >= interval) {
          last = now;
          i = (i + 1) % frames.length;
          drawFrame(frames[i]);
        }
        raf = requestAnimationFrame(tick);
      };
      raf = requestAnimationFrame(tick);
    })().catch(() => { /* best-effort — a broken pose just shows blank */ });

    return () => {
      cancelled = true;
      if (raf) cancelAnimationFrame(raf);
    };
  }, [manifestUrl, sheetUrl, pose]);

  return (
    <canvas
      ref={canvasRef}
      width={256}
      height={256}
      style={{
        ...(fill
          ? { width: "100%", height: "auto", aspectRatio: "1" }
          : { width: size, height: size }),
        imageRendering: "auto",
        // A checkerboard, drawn in CSS so nothing lands in the pixels being judged. On
        // white, missing alpha is invisible — and a matte defect that only shows against
        // a background is the exact class of bug this substrate exists to catch (§2.5).
        ...(checkered ? {
          backgroundColor: CHECKER_LIGHT,
          backgroundImage: `linear-gradient(45deg, ${CHECKER_DARK} 25%, transparent 25%),
                            linear-gradient(-45deg, ${CHECKER_DARK} 25%, transparent 25%),
                            linear-gradient(45deg, transparent 75%, ${CHECKER_DARK} 75%),
                            linear-gradient(-45deg, transparent 75%, ${CHECKER_DARK} 75%)`,
          backgroundSize: `${CHECKER_PX}px ${CHECKER_PX}px`,
          backgroundPosition: `0 0, 0 ${CHECKER_PX / 2}px, ${CHECKER_PX / 2}px -${CHECKER_PX / 2}px, -${CHECKER_PX / 2}px 0`,
        } : null),
      }}
    />
  );
}

// Mid-greys: light enough that black fill reads as black, dark enough that white fur
// reads as white. A checkerboard of pure white/black would hide one or the other.
const CHECKER_LIGHT = "#8a8a8a";
const CHECKER_DARK = "#6e6e6e";
const CHECKER_PX = 16;
