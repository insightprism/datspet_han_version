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
import { petManifestUrl, petSheetUrl } from "@/lib/api";
import type { RawManifest } from "@/pet";

interface Props {
  petId: string;
  pose: string;
  size?: number;
}

export default function PosePlayer({ petId, pose, size = 128 }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    let cancelled = false;
    let raf = 0;

    (async () => {
      const m: RawManifest = await (await fetch(petManifestUrl(petId))).json();
      const sheet = new Image();
      sheet.crossOrigin = "anonymous";
      sheet.src = petSheetUrl(petId);
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
  }, [petId, pose]);

  return (
    <canvas
      ref={canvasRef}
      width={256}
      height={256}
      style={{ width: size, height: size, imageRendering: "auto" }}
    />
  );
}
