/**
 * The race integrator — the browser's copy of the §6.1a Tier-1 procedure:
 * "integrate stride until the distance is covered", parameterised by the event
 * declaration. Mirrors `simulate_entrant`/`simulate_race` in
 * pet_factory/athletics/__init__.py operation-for-operation; the shared
 * fixture (race_vectors.json) is what keeps the two honest.
 *
 * §7.1: velocity = (answers per second) × (distance per answer) — the player
 * is the tempo, the pet is the exchange rate. §7.2: a wrong answer produced
 * no impulse, so the pet never moves backwards. §7.4: the impulse log IS the
 * race — these functions are pure, so a replay, a recap and a bug report are
 * all the same feature.
 */

import {
  strideM, TABLE_VERSION, type AthleticsStats,
} from "./athletics";
import type { ArenaEventDecl, ArenaTuning } from "./declarations";
import { mix32, unitInterval } from "./rng";

/** §7.1 — quality is 1.0 for a correct answer; no impulse is emitted for a
 *  wrong one. A graded challenge (typing) may emit < 1.0. */
export interface Impulse {
  at: number;      // ms since the gun
  quality: number; // 0..1
}

export interface EntrantSpec {
  stats: AthleticsStats;
  handicap: number;
  impulses: Impulse[];
}

export interface EntrantResult {
  finished: boolean;
  finish_ms: number | null;
  distance_m: number;
  place: number;
}

function clamp01(v: number): number {
  return v < 0 ? 0 : v > 1 ? 1 : v;
}

interface LaneParams {
  base: number;
  decay: number;
  raceRoll: number;
  distance: number;
  endurance: number;
  /** Hurdle spacing, or null for an open track (Rev.9, §6.6). */
  hurdleEvery: number | null;
}

function laneParams(
  event: ArenaEventDecl, stats: AthleticsStats, handicap: number,
  tuningOverride?: ArenaTuning,
): LaneParams {
  return {
    base: strideM(stats, event, handicap, tuningOverride),
    decay: event.decay ?? 0,
    raceRoll: event.race_roll ?? 0,
    distance: event.distance_m,
    endurance: clamp01(stats.endurance),
    hurdleEvery: event.hurdles_every_m && event.hurdles_every_m > 0
      ? event.hurdles_every_m : null,
  };
}

/** Hurdle-gate state (Rev.9): the run clamps at each hurdle line; the NEXT
 *  impulse is the leap. Which impulse cleared is derivable from distance
 *  alone — the log stays untagged and replay exact. Mirrors the Python
 *  reference operation-for-operation. */
interface HurdleState {
  nextHurdle: number | null;
  waiting: boolean;
}

function freshHurdleState(p: LaneParams): HurdleState {
  return { nextHurdle: p.hurdleEvery, waiting: false };
}

/** Apply one impulse's step under the hurdle gate; returns the new distance. */
function applyStep(
  p: LaneParams, covered: number, h: HurdleState, step: number,
): number {
  if (h.waiting) {
    // The leap: clear this hurdle, full stride over it.
    h.waiting = false;
    covered += step;
    h.nextHurdle = (h.nextHurdle ?? 0) + (p.hurdleEvery ?? 0);
    if (p.hurdleEvery && h.nextHurdle < p.distance && covered >= h.nextHurdle) {
      covered = h.nextHurdle;
      h.waiting = true;
    }
  } else if (h.nextHurdle !== null && h.nextHurdle < p.distance
      && covered + step >= h.nextHurdle) {
    covered = h.nextHurdle;
    h.waiting = true;
  } else {
    covered += step;
  }
  return covered;
}

/** One impulse's advance — THE shared arithmetic. §2.4: fatigue tracks
 *  distance covered, never elapsed time; §7.5: the race roll is seeded
 *  texture, small enough to feel alive and too small to decide a race. */
function advance(
  p: LaneParams, covered: number, quality: number,
  raceSeed: number, lane: number, impulseIdx: number,
): number {
  const jitter = 1 + p.raceRoll
    * (2 * unitInterval(mix32(raceSeed, lane, impulseIdx)) - 1);
  const fatigue = 1 - p.decay * Math.min(covered / p.distance, 1) * (1 - p.endurance);
  return Math.max(p.base * fatigue * jitter, 0) * quality;
}

export function simulateEntrant(
  event: ArenaEventDecl, stats: AthleticsStats, handicap: number,
  impulses: Impulse[], raceSeed: number, lane: number,
  tuningOverride?: ArenaTuning,
): Omit<EntrantResult, "place"> {
  const p = laneParams(event, stats, handicap, tuningOverride);
  const hurdles = freshHurdleState(p);
  const ordered = [...impulses].sort((a, b) => a.at - b.at);
  let covered = 0;
  let finishMs: number | null = null;
  for (let idx = 0; idx < ordered.length; idx++) {
    const step = advance(p, covered, ordered[idx].quality ?? 1, raceSeed, lane, idx);
    covered = applyStep(p, covered, hurdles, step);
    if (covered >= p.distance) {
      finishMs = ordered[idx].at;
      break;
    }
  }
  return {
    finished: finishMs !== null,
    finish_ms: finishMs,
    distance_m: Math.min(covered, p.distance),
  };
}

/** The referee: authoritative results off the full logs — finishers by time,
 *  then the unfinished by distance covered. Lane = index, seeding each lane's
 *  race roll, exactly as the Python reference does. */
export function simulateRace(
  event: ArenaEventDecl, entrants: EntrantSpec[], raceSeed: number,
  tuningOverride?: ArenaTuning,
): EntrantResult[] {
  const partial = entrants.map((e, lane) =>
    simulateEntrant(event, e.stats, e.handicap, e.impulses, raceSeed, lane,
      tuningOverride));
  const order = partial
    .map((_, i) => i)
    .sort((a, b) => {
      const ra = partial[a]; const rb = partial[b];
      if (ra.finished && rb.finished) return ra.finish_ms! - rb.finish_ms!;
      if (ra.finished !== rb.finished) return ra.finished ? -1 : 1;
      return rb.distance_m - ra.distance_m;
    });
  const results = partial.map((r) => ({ ...r, place: 0 }));
  order.forEach((entrantIdx, position) => {
    results[entrantIdx].place = position + 1;
  });
  return results;
}

/**
 * Incremental integrator for the live driver: consumes impulses in arrival
 * order (the live log only ever appends in time order) and lands on exactly
 * the numbers the batch referee produces for the same log — same `advance`,
 * same impulse indices.
 */
export class LaneIntegrator {
  distanceM = 0;
  finished = false;
  finishMs: number | null = null;
  private nextIdx = 0;
  private readonly p: LaneParams;
  private readonly hurdles: HurdleState;

  constructor(
    event: ArenaEventDecl, stats: AthleticsStats, handicap: number,
    private readonly raceSeed: number, private readonly lane: number,
    tuningOverride?: ArenaTuning,
  ) {
    this.p = laneParams(event, stats, handicap, tuningOverride);
    this.hurdles = freshHurdleState(this.p);
  }

  /** Parked at a hurdle line, waiting for the leap (Rev.9) — the screen
   *  shows the harder question in the jump color while this is true. */
  get atHurdle(): boolean {
    return this.hurdles.waiting;
  }

  /** Consume every impulse with `at <= uptoMs` that has not been consumed. */
  consume(log: Impulse[], uptoMs: number): void {
    while (!this.finished
      && this.nextIdx < log.length
      && log[this.nextIdx].at <= uptoMs) {
      const impulse = log[this.nextIdx];
      const step = advance(
        this.p, this.distanceM, impulse.quality ?? 1,
        this.raceSeed, this.lane, this.nextIdx);
      this.distanceM = applyStep(this.p, this.distanceM, this.hurdles, step);
      if (this.distanceM >= this.p.distance) {
        this.distanceM = this.p.distance;
        this.finished = true;
        this.finishMs = impulse.at;
      }
      this.nextIdx++;
    }
  }

  get distanceFraction(): number {
    return this.p.distance > 0 ? this.distanceM / this.p.distance : 0;
  }
}

// ---------------------------------------------------------------------------
// The race header (§8.3.1) — the record that makes a result honest and a
// replay exact: seed, difficulty, and EVERY entrant's handicap, by name.
// ---------------------------------------------------------------------------
export interface RaceHeaderEntrant {
  pet_id: string;
  label: string;
  handicap_name: string;
  handicap: number;
  stats: AthleticsStats;
  impulses: Impulse[];
}

export interface RaceHeader {
  event_key: string;
  challenge_key: string;
  difficulty: string;
  race_seed: number;
  table_version: string;
  entrants: RaceHeaderEntrant[];
}

/** Assemble the honest record of a race. Every entrant's handicap is in it BY
 *  NAME — a result payload that omits a non-1.0 handicap is a failing guard
 *  test, because a hidden handicap is the "secretly easier questions" failure
 *  §8.3 forbids. */
export function buildRaceHeader(input: {
  event_key: string;
  challenge_key: string;
  difficulty: string;
  race_seed: number;
  entrants: RaceHeaderEntrant[];
}): RaceHeader {
  return { ...input, table_version: TABLE_VERSION };
}

/** Re-run a recorded race from its header — recap, bug report and result
 *  verification are the same call (§7.4). */
export function replayFromHeader(
  header: RaceHeader, event: ArenaEventDecl, tuningOverride?: ArenaTuning,
): EntrantResult[] {
  return simulateRace(
    event,
    header.entrants.map((e) => ({
      stats: e.stats, handicap: e.handicap, impulses: e.impulses,
    })),
    header.race_seed,
    tuningOverride,
  );
}

/** Answers-per-second over a trailing window — drives the sprite frame rate
 *  (§7.6: a pet being driven hard visibly runs faster). Presentation only;
 *  never part of the result. */
export function recentAnswerRate(
  log: Impulse[], nowMs: number, windowMs: number,
): number {
  let count = 0;
  for (let i = log.length - 1; i >= 0; i--) {
    if (log[i].at < nowMs - windowMs) break;
    if (log[i].at <= nowMs) count++;
  }
  return count / (windowMs / 1000);
}
