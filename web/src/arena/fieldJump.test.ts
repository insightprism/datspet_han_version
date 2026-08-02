/**
 * The field-jump procedure's invariants (SPEC_PET_ARENA §6.6/§14) — pure
 * scorer, no DOM. The §14 promises: only impulses inside an attempt's
 * declared window count; the same log scores identically twice; the bot's
 * log and a human-shaped copy score identically; ranking is best-descending
 * with ties to the earlier best.
 */
import { describe, expect, it } from "vitest";
import type { AthleticsStats } from "./athletics";
import { botImpulseLog } from "./bot";
import { ATTEMPT_REST_S } from "./constants";
import { loadEvent, type ArenaEventDecl } from "./declarations";
import {
  attemptWindowMs, jumpEventDurationMs, scoreJumpEntrant, scoreJumpEvent,
} from "./fieldJump";
import {
  bestKey, readBestMeters, recordResultMeters, type BestStore,
} from "./personalBests";
import type { Impulse } from "./raceEngine";

function flatStats(value: number, land = 1.0): AthleticsStats {
  return {
    schema_version: "pet_athletics.v1", table_version: "athletics.v1",
    speed: value, power: value, endurance: value,
    land, water: 0, air: 0,
    identity_nudges: { speed: 0, power: 0, endurance: 0 },
    poses: ["walk", "idle", "run", "jump"],
  };
}

/** Deterministic inline event — race_roll 0 so the arithmetic is exact. */
const JUMP_EVENT: ArenaEventDecl = {
  key: "test_jump", label: "test", procedure: "jump", medium: "land",
  distance_m: 40, decay: 0, race_roll: 0, time_limit_s: 90,
  attempts: 3, attempt_window_s: 10, jump_conversion: 0.5,
  weights: { speed: 0.5, power: 0.3, endurance: 0.2 },
  requires: [["jump"]], team_size: 1, preferred_poses: ["run"],
  result_unit: "meters",
};

describe("the attempt schedule is declared, not UI state (§6.6)", () => {
  it("window i opens at i × (window + rest)", () => {
    const cycle = (10 + ATTEMPT_REST_S) * 1000;
    expect(attemptWindowMs(JUMP_EVENT, 0)).toEqual({ start: 0, end: 10_000 });
    expect(attemptWindowMs(JUMP_EVENT, 1)).toEqual({ start: cycle, end: cycle + 10_000 });
    expect(jumpEventDurationMs(JUMP_EVENT)).toBe(3 * cycle);
  });
});

describe("the jump scorer (§6.6)", () => {
  it("only impulses inside a window count, and the arithmetic is exact", () => {
    // 5 answers in window 1, 2 in the rest (ignored), none later.
    // score 0.5 stats → stride = STRIDE_BASE_M exactly (§2.3), roll 0.
    const impulses: Impulse[] = [
      ...[1, 2, 3, 4, 5].map((s) => ({ at: s * 1000, quality: 1 })),
      { at: 11_000, quality: 1 }, { at: 12_000, quality: 1 },  // in the rest
    ];
    const { attempts, best_m } = scoreJumpEntrant(
      JUMP_EVENT, flatStats(0.5), 1, impulses, 42, 0);
    expect(attempts[0]).toBeCloseTo(5 * 2.0 * 0.5, 9);   // 5 answers × stride × conversion
    expect(attempts[1]).toBe(0);
    expect(attempts[2]).toBe(0);
    expect(best_m).toBeCloseTo(5.0, 9);
  });

  it("the same log scores identically twice — replay holds (§7.4)", () => {
    const log = Array.from({ length: 40 }, (_, i) => ({ at: i * 700, quality: 1 }));
    const event = loadEvent("long_jump")!;
    const a = scoreJumpEntrant(event, flatStats(0.7, 0.9), 1.25, log, 777, 0);
    const b = scoreJumpEntrant(event, flatStats(0.7, 0.9), 1.25, log, 777, 0);
    expect(a).toEqual(b);
  });

  it("the bot's log and a human-shaped copy score identically (§7.3)", () => {
    const event = loadEvent("triple_jump")!;
    const botLog = botImpulseLog("steady", 555, 1, jumpEventDurationMs(event));
    const humanShaped = botLog.map((imp) => ({ ...imp }));
    const stats = flatStats(0.6, 0.9);
    expect(scoreJumpEntrant(event, stats, 1, botLog, 9, 1))
      .toEqual(scoreJumpEntrant(event, stats, 1, humanShaped, 9, 1));
  });

  it("ranking is best DESCENDING, ties to the earlier best", () => {
    const inWindow = (n: number, offsetMs: number) =>
      Array.from({ length: n }, (_, i) => ({ at: offsetMs + i * 100, quality: 1 }));
    const cycle = (10 + ATTEMPT_REST_S) * 1000;
    const results = scoreJumpEvent(JUMP_EVENT, [
      // best 3.0 on attempt 2
      { stats: flatStats(0.5), handicap: 1, impulses: inWindow(3, cycle + 1000) },
      // best 5.0 on attempt 1 → wins
      { stats: flatStats(0.5), handicap: 1, impulses: inWindow(5, 1000) },
      // best 3.0 on attempt 1 → beats the attempt-2 tie
      { stats: flatStats(0.5), handicap: 1, impulses: inWindow(3, 1000) },
    ], 1);
    expect(results.map((r) => r.place)).toEqual([3, 1, 2]);
  });

  it("an all-wrong event scores zero, never negative (§7.2)", () => {
    const { best_m } = scoreJumpEntrant(JUMP_EVENT, flatStats(1), 1, [], 1, 0);
    expect(best_m).toBe(0);
  });
});

describe("field personal bests are metres, higher is better (§6.6)", () => {
  function memoryStore(): BestStore {
    const map = new Map<string, string>();
    return { getItem: (k) => map.get(k) ?? null, setItem: (k, v) => { map.set(k, v); } };
  }

  it("only a longer jump improves the best; zero never records", () => {
    const store = memoryStore();
    const key = bestKey("long_jump", "arithmetic", "sums_10", "none");
    expect(recordResultMeters(store, key, 0)).toEqual(
      { improved: false, previousMeters: null });
    expect(recordResultMeters(store, key, 4.2)).toEqual(
      { improved: true, previousMeters: null });
    expect(recordResultMeters(store, key, 3.9)).toEqual(
      { improved: false, previousMeters: 4.2 });
    expect(recordResultMeters(store, key, 5.1)).toEqual(
      { improved: true, previousMeters: 4.2 });
    expect(readBestMeters(store, key)).toBe(5.1);
  });
});
