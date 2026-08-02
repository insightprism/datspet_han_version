"use client";

/**
 * Pose capability badges — one glyph per canonical pose, athletic poses first
 * because they are the entry tickets (SPEC_PET_ARENA §10: the pose you buy is
 * the event you unlock). The legend on the athlete section explains every
 * glyph, so the badges stay wordless on the cards.
 *
 * The pose vocabulary GROWS (§6.3.2) and the arena must not care: a pose with
 * no badge yet renders as its name in a small chip — a capability is never
 * hidden just because this map is behind.
 */

interface PoseBadge {
  pose: string;
  glyph: string;
  label: string;
}

export const POSE_BADGES: PoseBadge[] = [
  { pose: "walk", glyph: "🚶", label: "walk" },
  { pose: "run", glyph: "🏃", label: "run" },
  { pose: "jump", glyph: "🦘", label: "jump" },
  { pose: "swim", glyph: "🏊", label: "swim" },
  { pose: "fly", glyph: "🕊️", label: "fly" },
  { pose: "idle", glyph: "🧍", label: "idle" },
  { pose: "sit", glyph: "🪑", label: "sit" },
  { pose: "sleep", glyph: "😴", label: "sleep" },
  { pose: "eat", glyph: "🍖", label: "eat" },
  { pose: "play", glyph: "🎾", label: "play" },
];

/** The capability row at the bottom of an athlete card. */
export function PoseBadges({ poses }: { poses: string[] }) {
  const owned = new Set(poses);
  const known = POSE_BADGES.filter((b) => owned.has(b.pose));
  const unknown = poses.filter((p) => !POSE_BADGES.some((b) => b.pose === p));
  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-1 text-[13px]">
      {known.map((b) => <span key={b.pose}>{b.glyph}</span>)}
      {unknown.map((p) => (
        <span key={p} className="rounded bg-white/10 px-1 text-[9px]"
          style={{ color: "var(--muted)" }}>
          {p}
        </span>
      ))}
    </div>
  );
}

/** The legend above the athlete grid — what each badge means. */
export function PoseLegend() {
  return (
    <div className="mb-2 flex flex-wrap items-baseline gap-x-3 gap-y-0.5 text-[11px]"
      style={{ color: "var(--muted)" }}>
      <span className="font-semibold">Capabilities:</span>
      {POSE_BADGES.map((b) => (
        <span key={b.pose} className="whitespace-nowrap">{b.glyph} {b.label}</span>
      ))}
    </div>
  );
}
