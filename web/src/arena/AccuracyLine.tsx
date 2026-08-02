"use client";

/**
 * The answer tally on a results row (owner ask, 2026-08-02): rights, wrongs,
 * and the percentage — the study readout the maths is actually for. One
 * component so the race and field results can never disagree about rounding.
 */

import type { RunAccuracy } from "./gameTypes";

export default function AccuracyLine({ accuracy }: { accuracy: RunAccuracy | null }) {
  if (!accuracy) return null;
  const total = accuracy.right + accuracy.wrong;
  if (total === 0) return null;
  const pct = Math.round((accuracy.right / total) * 100);
  return (
    <div className="mono text-xs" style={{ color: "var(--muted)" }}>
      ✓ {accuracy.right} · ✗ {accuracy.wrong} · {pct}% right
    </div>
  );
}
