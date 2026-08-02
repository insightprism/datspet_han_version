"use client";

/**
 * JumpResultsScreen — the field-event finish (§6.6/§8.8): places by best
 * distance, every attempt shown, personal bests in METRES (higher is
 * better). Same framing rules as the race results: PB first, placement
 * second, every handicap visible. No recap for field events in v1 — the
 * attempt distances ARE the story, and they are all on screen.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import type { ArenaChallenge } from "./challenges/registry";
import type { ArenaEventDecl } from "./declarations";
import { scoreJumpEvent } from "./fieldJump";
import type { LoadedRacer } from "./gameTypes";
import type { Impulse } from "./raceEngine";
import {
  bestKey, recordResultMeters, type BestMetersOutcome,
} from "./personalBests";
import StatBars from "./StatBars";

const MEDALS = ["🥇", "🥈", "🥉"];

interface Props {
  event: ArenaEventDecl;
  challenge: ArenaChallenge;
  difficulty: string;
  raceSeed: number;
  lanes: LoadedRacer[];
  logs: Impulse[][];
  onRaceAgain: () => void;
  onBackToSetup: () => void;
}

export default function JumpResultsScreen({
  event, challenge, difficulty, raceSeed, lanes, logs,
  onRaceAgain, onBackToSetup,
}: Props) {
  const results = useMemo(() =>
    scoreJumpEvent(event,
      lanes.map((lane, i) => ({
        stats: lane.stats, handicap: lane.handicap, impulses: logs[i],
      })),
      raceSeed),
  [event, lanes, logs, raceSeed]);

  const [bestOutcomes, setBestOutcomes] = useState<Record<number, BestMetersOutcome>>({});
  const recordedRef = useRef(false);
  useEffect(() => {
    if (recordedRef.current) return;
    recordedRef.current = true;
    const outcomes: Record<number, BestMetersOutcome> = {};
    lanes.forEach((lane, i) => {
      if (lane.kind !== "human" || results[i].best_m <= 0) return;
      const key = bestKey(event.key, challenge.key, difficulty, lane.handicapName);
      outcomes[i] = recordResultMeters(window.localStorage, key, results[i].best_m);
    });
    setBestOutcomes(outcomes);
  }, [lanes, results, event.key, challenge.key, difficulty]);

  const ordered = useMemo(() =>
    results.map((r, i) => ({ ...r, lane: i })).sort((a, b) => a.place - b.place),
  [results]);

  return (
    <div className="flex flex-col gap-4">
      <h2 className="text-xl font-semibold">{event.emoji} {event.label} — results</h2>

      <div className="card flex flex-col gap-2 p-4">
        {ordered.map((r) => {
          const lane = lanes[r.lane];
          const best = bestOutcomes[r.lane];
          return (
            <div key={lane.storeId}
              className="flex flex-wrap items-baseline justify-between gap-2 border-b border-white/5 pb-2 last:border-b-0">
              <div className="flex flex-col">
                <div className="flex items-baseline gap-2">
                  <span className="text-2xl">{MEDALS[r.place - 1] ?? `#${r.place}`}</span>
                  <span className="font-semibold">{lane.label}</span>
                  {lane.handicapName !== "none" && (
                    <span className="rounded px-1.5 py-0.5 text-[10px] font-semibold"
                      style={{ background: "rgba(52,211,153,0.15)", color: "var(--green)" }}>
                      🚀 {lane.handicapName.replace(/_/g, " ")} ×{lane.handicap}
                    </span>
                  )}
                </div>
                <StatBars stats={lane.stats} className="ml-9 w-44" />
              </div>
              <div className="text-right">
                <span className="mono text-lg font-semibold">
                  {r.best_m.toFixed(2)} m
                </span>
                <div className="mono text-xs" style={{ color: "var(--muted)" }}>
                  {r.attempts.map((d, i) =>
                    `${i + 1}: ${d.toFixed(2)}`).join(" · ")}
                </div>
                {best && (
                  <div className="text-xs" style={{ color: "var(--green)" }}>
                    {best.improved
                      ? best.previousMeters === null
                        ? "🎉 First time — that's your best!"
                        : `🎉 New personal best! (was ${best.previousMeters.toFixed(2)} m)`
                      : best.previousMeters !== null
                        ? `Your best: ${best.previousMeters.toFixed(2)} m`
                        : null}
                  </div>
                )}
              </div>
            </div>
          );
        })}
        <div className="pt-1 text-xs" style={{ color: "var(--muted)" }}>
          {challenge.emoji} {challenge.label} · {difficulty.replace(/_/g, " ")} ·
          seed {raceSeed} · every lane saw the same questions
        </div>
      </div>

      <div className="flex flex-wrap gap-3">
        <button type="button" className="btn" onClick={onRaceAgain}>
          🔁 Jump again
        </button>
        <button type="button" className="btn-ghost" onClick={onBackToSetup}>
          ← New event
        </button>
      </div>
    </div>
  );
}
