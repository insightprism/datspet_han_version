"use client";

/**
 * PoseGallery — one animated box per pose the pet actually contains, so after a
 * build you can visually confirm each requested pose (walk, idle, run, sleep, …)
 * generated real, distinct motion. Reads the pet's manifest for the pose list and
 * plays each via PosePlayer. Shows nothing until the manifest loads (best-effort).
 */
import { useEffect, useState } from "react";
import { petManifestUrl } from "@/lib/api";
import type { RawManifest } from "@/pet";
import PosePlayer from "@/components/PosePlayer";

// Canonical order so the boxes read walk, idle, then the extras — matches the
// build order and the pose selector.
const POSE_ORDER = ["walk", "idle", "run", "sleep", "sit", "eat", "jump", "play", "swim", "fly"];

interface Props {
  petId: string;
}

export default function PoseGallery({ petId }: Props) {
  const [poses, setPoses] = useState<string[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const m: RawManifest = await (await fetch(petManifestUrl(petId))).json();
      if (cancelled) return;
      const names = Object.keys(m.animations ?? {});
      names.sort((a, b) => {
        const ia = POSE_ORDER.indexOf(a); const ib = POSE_ORDER.indexOf(b);
        return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
      });
      setPoses(names);
    })().catch(() => { if (!cancelled) setPoses([]); });
    return () => { cancelled = true; };
  }, [petId]);

  if (!poses || poses.length === 0) return null;

  return (
    <div className="mt-6">
      <div className="mono mb-2 text-xs tracking-wide" style={{ color: "var(--muted)" }}>
        Generated poses ({poses.length}) — each animation is playing:
      </div>
      <div className="flex flex-wrap gap-3">
        {poses.map((name) => (
          <div
            key={name}
            className="card flex flex-col items-center p-2"
            style={{ borderColor: "rgba(99,102,241,0.35)" }}
          >
            <PosePlayer petId={petId} pose={name} size={112} />
            <div className="mono mt-1 text-xs capitalize" style={{ color: "var(--gold)" }}>
              {name}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
