"use client";

/**
 * ResultsScreen — the finish, framed the §8.8 way: personal best FIRST
 * ("you beat your own time"), placement second; per-event medals; the recap.
 * The standings come from the batch referee (simulateRace over the full
 * logs), never from what the live screen happened to draw — the same
 * authority split the rooms spec makes server-side.
 *
 * Every entrant's handicap is displayed (§8.3.1 — a hidden handicap is the
 * failure the spec forbids) and recorded in the race header, which is also
 * what the recap replays (§7.4: the impulse log IS the race).
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ArenaChallenge } from "./challenges/registry";
import { RECAP_PLAYBACK_SPEED } from "./constants";
import type { ArenaEventDecl } from "./declarations";
import type { LoadedRacer } from "./gameTypes";
import {
  buildRaceHeader, LaneIntegrator, simulateRace, type Impulse,
} from "./raceEngine";
import {
  bestKey, recordResultSeconds, type BestOutcome,
} from "./personalBests";
import ArenaTrack, { type TrackLane } from "./ArenaTrack";
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

export default function ResultsScreen({
  event, challenge, difficulty, raceSeed, lanes, logs,
  onRaceAgain, onBackToSetup,
}: Props) {
  const results = useMemo(() =>
    simulateRace(event,
      lanes.map((lane, i) => ({
        stats: lane.stats, handicap: lane.handicap, impulses: logs[i],
      })),
      raceSeed),
  [event, lanes, logs, raceSeed]);

  // The honest record (§8.3.1) — also what a future "share replay" would send.
  const header = useMemo(() => buildRaceHeader({
    event_key: event.key,
    challenge_key: challenge.key,
    difficulty,
    race_seed: raceSeed,
    entrants: lanes.map((lane, i) => ({
      pet_id: lane.petId, label: lane.label,
      handicap_name: lane.handicapName, handicap: lane.handicap,
      stats: lane.stats, impulses: logs[i],
    })),
  }), [event.key, challenge.key, difficulty, raceSeed, lanes, logs]);

  // Personal bests — device-local, recorded once per mount (§8.8).
  const [bestOutcomes, setBestOutcomes] = useState<Record<number, BestOutcome>>({});
  const recordedRef = useRef(false);
  useEffect(() => {
    if (recordedRef.current) return;
    recordedRef.current = true;
    const outcomes: Record<number, BestOutcome> = {};
    lanes.forEach((lane, i) => {
      const r = results[i];
      if (lane.kind !== "human" || !r.finished || r.finish_ms === null) return;
      const key = bestKey(event.key, challenge.key, difficulty, lane.handicapName);
      outcomes[i] = recordResultSeconds(window.localStorage, key, r.finish_ms / 1000);
    });
    setBestOutcomes(outcomes);
  }, [lanes, results, event.key, challenge.key, difficulty]);

  // The recap (§8.8): same track, same logs, a faster clock.
  const [recapping, setRecapping] = useState(false);
  const recapStartRef = useRef<number | null>(null);
  const recapClock = useCallback(() =>
    recapStartRef.current === null
      ? null
      : (performance.now() - recapStartRef.current) * RECAP_PLAYBACK_SPEED,
  []);
  const recapLanes = useMemo<TrackLane[]>(() => {
    if (!recapping) return [];
    recapStartRef.current = performance.now();
    return lanes.map((lane, i) => ({
      storeId: lane.storeId,
      label: lane.label,
      handicapName: lane.handicapName,
      racingPose: lane.racingPose,
      hopPose: ["jump", "play"].find((p) => lane.stats.poses.includes(p)),
      integrator: new LaneIntegrator(event, lane.stats, lane.handicap, raceSeed, i),
      log: logs[i],
    }));
  }, [recapping, lanes, logs, event, raceSeed]);

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
                {/* The numbers the race actually used (§16.6) — so a child can
                    reason about WHY they lost, not just that they did. */}
                <StatBars stats={lane.stats} className="ml-9 w-44" />
              </div>
              <div className="text-right">
                <span className="mono">
                  {r.finished && r.finish_ms !== null
                    ? `${(r.finish_ms / 1000).toFixed(1)} s`
                    : `${r.distance_m.toFixed(0)} m of ${event.distance_m} m`}
                </span>
                {best && (
                  <div className="text-xs" style={{ color: "var(--green)" }}>
                    {best.improved
                      ? best.previousSeconds === null
                        ? "🎉 First time — that's your best!"
                        : `🎉 New personal best! (was ${best.previousSeconds.toFixed(1)} s)`
                      : best.previousSeconds !== null
                        ? `Your best: ${best.previousSeconds.toFixed(1)} s`
                        : null}
                  </div>
                )}
              </div>
            </div>
          );
        })}
        <div className="pt-1 text-xs" style={{ color: "var(--muted)" }}>
          {challenge.emoji} {challenge.label} · {difficulty.replace(/_/g, " ")} ·
          seed {header.race_seed} · every lane saw the same questions
        </div>
      </div>

      {recapping && (
        <div className="flex flex-col gap-2">
          <ArenaTrack lanes={recapLanes} distanceM={event.distance_m}
            hurdlesEveryM={event.hurdles_every_m} raceClock={recapClock} />
          <button type="button" className="btn-ghost self-end"
            onClick={() => setRecapping(false)}>
            Stop recap
          </button>
        </div>
      )}

      <div className="flex flex-wrap gap-3">
        {!recapping && (
          <button type="button" className="btn" onClick={() => setRecapping(true)}>
            ▶ Watch the recap
          </button>
        )}
        <button type="button" className="btn" onClick={onRaceAgain}>
          🔁 Race again
        </button>
        <button type="button" className="btn-ghost" onClick={onBackToSetup}>
          ← New race
        </button>
      </div>
    </div>
  );
}
