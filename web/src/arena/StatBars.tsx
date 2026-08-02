"use client";

/**
 * StatBars — the six-numbers-as-bars readout (§16.6: stats are VISIBLE; the
 * design→performance link is the feature, and a hidden stat is
 * indistinguishable from a random one). One component for every surface that
 * shows a pet's athletics — the setup cards and the results rows must never
 * drift into two slightly different readings of the same numbers.
 *
 * Engine values are 0..1 floats (§2.5); children read 0..STAT_DISPLAY_MAX.
 */

import { ATTRIBUTES, type AthleticsStats } from "./athletics";
import { STAT_DISPLAY_MAX } from "./constants";

interface Props {
  stats: AthleticsStats;
  className?: string;
}

export default function StatBars({ stats, className }: Props) {
  return (
    <div className={`mt-1 flex flex-col gap-0.5 ${className ?? ""}`}>
      {ATTRIBUTES.map((attr) => {
        const displayValue = Math.round(stats[attr] * STAT_DISPLAY_MAX);
        return (
          <div key={attr} className="flex items-center gap-1 text-[10px]">
            <span className="w-14 capitalize" style={{ color: "var(--muted)" }}>{attr}</span>
            <div className="h-1.5 flex-1 rounded bg-white/10">
              <div className="h-1.5 rounded"
                style={{
                  // Bar geometry: the 0..1 stat as a CSS percentage.
                  width: `${stats[attr] * 100}%`,
                  background: "var(--green)",
                }} />
            </div>
            <span className="mono w-6 text-right tabular-nums">{displayValue}</span>
          </div>
        );
      })}
    </div>
  );
}
