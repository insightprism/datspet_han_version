"use client";

/**
 * PetThumbnail — a still portrait of a generated pet (first idle frame,
 * falling back to the first walk frame), drawn from the real sprite
 * sheet. Used on the maker result card and the pet-house roster so "the
 * image of the pet" appears without mounting a full engine instance.
 */

import { useEffect, useRef } from "react";
import { petManifestUrl, petSheetUrl } from "@/lib/api";
import type { RawManifest } from "@/pet";

interface Props {
  petId: string;
  size?: number;
}

export default function PetThumbnail({ petId, size = 96 }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const m: RawManifest = await (await fetch(petManifestUrl(petId))).json();
      const sheet = new Image();
      sheet.crossOrigin = "anonymous";
      sheet.src = petSheetUrl(petId);
      await sheet.decode();
      if (cancelled || !canvasRef.current) return;
      const anims = m.animations ?? {};
      const frames = anims.idle?.frames ?? anims.walk?.frames ?? [0];
      const idx = frames[0] ?? 0;
      const cols = m.columns ?? 8;
      const fw = m.frame_width ?? 256;
      const fh = m.frame_height ?? 256;
      const ctx = canvasRef.current.getContext("2d");
      if (!ctx) return;
      ctx.clearRect(0, 0, fw, fh);
      ctx.drawImage(sheet, (idx % cols) * fw, Math.floor(idx / cols) * fh, fw, fh, 0, 0, fw, fh);
    })().catch(() => { /* thumbnail is best-effort */ });
    return () => { cancelled = true; };
  }, [petId]);

  return (
    <canvas
      ref={canvasRef}
      width={256}
      height={256}
      style={{ width: size, height: size }}
    />
  );
}
