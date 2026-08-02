/**
 * The field-jump procedure (SPEC_PET_ARENA §6.6, Rev.8) — the first Tier-2
 * event scorer. An attempt is a run-up on a FIXED clock: window `i` opens at
 * `i × (attempt_window_s + ATTEMPT_REST_S)` after the gun, so the event is a
 * pure function of the impulse log (§7.4 — replay needs no UI state).
 *
 * Charge uses the SAME arithmetic a race step does — stride (weights ×
 * affinity × handicap) with the seeded per-impulse jitter — integrated only
 * inside the windows. Distance = charge × jump_conversion; best of the
 * attempts counts; ranking is best DESCENDING with ties to the earlier best.
 * The bot jumps by this identical formula over its own log (§7.3).
 */

import { strideM, type AthleticsStats } from "./athletics";
import { ATTEMPT_REST_S } from "./constants";
import type { ArenaEventDecl } from "./declarations";
import type { EntrantSpec, Impulse } from "./raceEngine";
import { mix32, unitInterval } from "./rng";

export interface JumpEntrantResult {
  /** Metres per attempt, in attempt order. */
  attempts: number[];
  best_m: number;
  place: number;
}

/** One attempt's open/close, ms since the gun — the declared schedule. */
export function attemptWindowMs(
  event: ArenaEventDecl, attemptIdx: number,
): { start: number; end: number } {
  const cycleMs = ((event.attempt_window_s ?? 0) + ATTEMPT_REST_S) * 1000;
  const start = attemptIdx * cycleMs;
  return { start, end: start + (event.attempt_window_s ?? 0) * 1000 };
}

/** Total event duration — also how long the bot's log must run. */
export function jumpEventDurationMs(event: ArenaEventDecl): number {
  const cycleMs = ((event.attempt_window_s ?? 0) + ATTEMPT_REST_S) * 1000;
  return (event.attempts ?? 0) * cycleMs;
}

export function scoreJumpEntrant(
  event: ArenaEventDecl, stats: AthleticsStats, handicap: number,
  impulses: Impulse[], raceSeed: number, lane: number,
): { attempts: number[]; best_m: number } {
  const base = strideM(stats, event, handicap);
  const raceRoll = event.race_roll ?? 0;
  const conversion = event.jump_conversion ?? 0;
  const ordered = [...impulses].sort((a, b) => a.at - b.at);
  const attempts: number[] = [];
  for (let a = 0; a < (event.attempts ?? 0); a++) {
    const { start, end } = attemptWindowMs(event, a);
    let charge = 0;
    ordered.forEach((impulse, idx) => {
      // idx is the GLOBAL impulse index — the same jitter stream a race
      // would use, so one arithmetic serves the whole game.
      if (impulse.at >= start && impulse.at < end) {
        const jitter = 1 + raceRoll
          * (2 * unitInterval(mix32(raceSeed, lane, idx)) - 1);
        charge += Math.max(base * jitter, 0) * (impulse.quality ?? 1);
      }
    });
    attempts.push(charge * conversion);
  }
  return { attempts, best_m: attempts.length ? Math.max(...attempts) : 0 };
}

/** The referee for a field event: every entrant scored, places assigned. */
export function scoreJumpEvent(
  event: ArenaEventDecl, entrants: EntrantSpec[], raceSeed: number,
): JumpEntrantResult[] {
  const partial = entrants.map((e, lane) =>
    scoreJumpEntrant(event, e.stats, e.handicap, e.impulses, raceSeed, lane));
  const order = partial
    .map((_, i) => i)
    .sort((a, b) => {
      if (partial[b].best_m !== partial[a].best_m) {
        return partial[b].best_m - partial[a].best_m;
      }
      // Tie → the earlier best attempt wins (§6.6).
      return partial[a].attempts.indexOf(partial[a].best_m)
        - partial[b].attempts.indexOf(partial[b].best_m);
    });
  const results = partial.map((p) => ({ ...p, place: 0 }));
  order.forEach((entrantIdx, position) => {
    results[entrantIdx].place = position + 1;
  });
  return results;
}
