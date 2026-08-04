"use client";

/**
 * PetThumbnail — a still portrait of a generated pet (first idle frame,
 * falling back to the first walk frame), drawn from the real sprite
 * sheet. Used on the maker result card, the pet-house roster and the
 * the pet game's athlete cards so "the image of the pet" appears without mounting
 * a full engine instance.
 *
 * LOADING IS GATED AND RETRIED, deliberately. A roster mounts dozens of
 * these at once and every sheet is a ~2048×4096 PNG: two dozen parallel
 * decodes is close to a gigabyte of decoded raster, under which Chrome's
 * `Image.decode()` rejects spuriously (the image gets evicted mid-decode).
 * The old code awaited decode() once and swallowed the rejection — so a
 * random subset of pets simply had no picture, different ones each load.
 * Three defenses, all load-bearing:
 *   1. a module-level gate holds concurrent sheet loads to a few at a time;
 *   2. decode() rejection falls back to the load event — drawImage works
 *      from a loaded image even when decode() refused;
 *   3. one retry for the truly transient failures.
 */

import { useEffect, useRef } from "react";
import { petManifestUrl, petSheetUrl } from "@/lib/api";
import type { RawManifest } from "@/pet";

interface Props {
  petId: string;
  size?: number;
}

// The decode gate. Small enough that decoded-raster memory stays bounded,
// large enough that a roster still fills quickly.
const MAX_CONCURRENT_SHEET_DECODES = 4;
const RETRY_DELAY_MS = 400;

let activeDecodes = 0;
const decodeWaiters: (() => void)[] = [];

async function acquireDecodeSlot(): Promise<void> {
  if (activeDecodes < MAX_CONCURRENT_SHEET_DECODES) {
    activeDecodes++;
    return;
  }
  await new Promise<void>((resolve) => decodeWaiters.push(resolve));
  activeDecodes++;
}

function releaseDecodeSlot(): void {
  activeDecodes--;
  decodeWaiters.shift()?.();
}

/** Load + decode the sheet, tolerating decode()'s spurious rejections. */
async function loadSheet(url: string): Promise<HTMLImageElement> {
  const sheet = new Image();
  sheet.crossOrigin = "anonymous";
  const loaded = new Promise<void>((resolve, reject) => {
    sheet.onload = () => resolve();
    sheet.onerror = () => reject(new Error("sheet failed to load"));
  });
  sheet.src = url;
  await loaded;
  // decode() gives us a paint-ready raster, but its rejection under memory
  // pressure is not fatal: drawImage decodes synchronously from a loaded
  // image regardless.
  await sheet.decode().catch(() => undefined);
  return sheet;
}

export default function PetThumbnail({ petId, size = 96 }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    let cancelled = false;

    async function drawOnce(): Promise<void> {
      const m: RawManifest = await (await fetch(petManifestUrl(petId))).json();
      await acquireDecodeSlot();
      try {
        const sheet = await loadSheet(petSheetUrl(petId));
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
        ctx.drawImage(sheet, (idx % cols) * fw, Math.floor(idx / cols) * fh,
          fw, fh, 0, 0, fw, fh);
      } finally {
        releaseDecodeSlot();
      }
    }

    (async () => {
      try {
        await drawOnce();
      } catch {
        // One retry for the transient class; a pet with a genuinely broken
        // sheet stays blank, as before — the thumbnail is best-effort.
        await new Promise((r) => setTimeout(r, RETRY_DELAY_MS));
        if (!cancelled) await drawOnce().catch(() => undefined);
      }
    })();

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
