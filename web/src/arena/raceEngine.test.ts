/**
 * The game's load-bearing invariants (SPEC_PET_ARENA §14), on the pure
 * integrator — no DOM, no React, per this repo's vitest posture.
 */
import { describe, expect, it } from "vitest";
import raceVectors from "../../../pet_factory/athletics/tests/fixtures/race_vectors.json";
import { resolveAthletics, strideM, type AthleticsStats } from "./athletics";
import { TUNING, loadEvent, type ArenaEventDecl } from "./declarations";
import {
  buildRaceHeader, LaneIntegrator, replayFromHeader, simulateRace,
  type Impulse,
} from "./raceEngine";

function flatStats(value: number, land = 1.0): AthleticsStats {
  return {
    schema_version: "pet_athletics.v1", table_version: "athletics.v1",
    speed: value, power: value, endurance: value,
    land, water: 0, air: 0,
    identity_nudges: { speed: 0, power: 0, endurance: 0 },
    poses: ["walk", "idle", "run"],
  };
}

function steady(n: number, periodMs: number, quality = 1): Impulse[] {
  return Array.from({ length: n }, (_, i) => ({ at: periodMs * (i + 1), quality }));
}

const EVEN_EVENT: ArenaEventDecl = {
  key: "even", label: "even", procedure: "race", medium: "land",
  distance_m: 100, decay: 0,
  race_roll: 0, time_limit_s: 180,
  weights: { speed: 0.5, power: 0.3, endurance: 0.2 },
  requires: [["run"]], team_size: 1, preferred_poses: ["run"],
  result_unit: "seconds",
};

describe("the stride formula is pinned (§2.3)", () => {
  it("score 0.5 → exactly STRIDE_BASE_M", () => {
    expect(strideM(flatStats(0.5), EVEN_EVENT)).toBeCloseTo(TUNING.stride_base_m, 12);
  });
  it("best ÷ worst == ATHLETIC_STRIDE_SPREAD exactly", () => {
    const ratio = strideM(flatStats(1), EVEN_EVENT) / strideM(flatStats(0), EVEN_EVENT);
    expect(ratio).toBeCloseTo(TUNING.athletic_stride_spread, 12);
  });
});

describe("the shared race-vector fixture (§6.1a)", () => {
  // The Python reference produced these numbers; this integrator must land on
  // them. Two implementations that drift are indistinguishable from a
  // cheating child.
  for (const vector of raceVectors.vectors) {
    it(vector.name, () => {
      const results = simulateRace(
        vector.event as unknown as ArenaEventDecl,
        vector.entrants.map((e) => ({
          stats: e.stats as unknown as AthleticsStats,
          handicap: e.handicap,
          impulses: e.impulses,
        })),
        vector.race_seed,
        vector.tuning,
      );
      results.forEach((got, i) => {
        const want = vector.expected[i];
        expect(got.finished).toBe(want.finished);
        expect(got.place).toBe(want.place);
        if (want.finish_ms === null) expect(got.finish_ms).toBeNull();
        else expect(got.finish_ms).toBeCloseTo(want.finish_ms, 9);
        expect(got.distance_m).toBeCloseTo(want.distance_m, 9);
      });
    });
  }
});

describe("replay determinism (§7.4)", () => {
  it("the same impulse log replayed produces identical results", () => {
    const event = loadEvent("sprint_100")!;
    const entrants = [
      { stats: flatStats(0.7, 0.9), handicap: 1, impulses: steady(90, 500) },
      { stats: flatStats(0.4, 0.9), handicap: 1.5, impulses: steady(90, 600) },
    ];
    expect(simulateRace(event, entrants, 99)).toEqual(simulateRace(event, entrants, 99));
  });

  it("the incremental live integrator lands on the referee's numbers", () => {
    const event = loadEvent("sprint_200")!;
    const log = steady(300, 650);
    const stats = flatStats(0.6, 0.9);
    const live = new LaneIntegrator(event, stats, 1.25, 4242, 0);
    // Feed in ragged chunks, the way a race actually arrives.
    for (let t = 0; t <= 300 * 650; t += 1234) live.consume(log, t);
    live.consume(log, 300 * 650);
    const referee = simulateRace(event,
      [{ stats, handicap: 1.25, impulses: log }], 4242)[0];
    expect(live.finished).toBe(referee.finished);
    expect(live.finishMs).toBe(referee.finish_ms);
    expect(live.distanceM).toBeCloseTo(referee.distance_m, 9);
  });
});

describe("no backwards movement (§7.2)", () => {
  it("a run of only wrong answers stays at exactly the start line", () => {
    const event = loadEvent("sprint_100")!;
    // Wrong answers emit no impulse — the log is empty.
    const result = simulateRace(event,
      [{ stats: flatStats(1), handicap: 1, impulses: [] }], 1)[0];
    expect(result.distance_m).toBe(0);
    expect(result.finished).toBe(false);
  });
});

describe("skill beats stats — the headline test (§8.4)", () => {
  it("the worst pet at 2× the answer rate beats the best pet", () => {
    const event = loadEvent("sprint_100")!;
    const results = simulateRace(event, [
      { stats: flatStats(0), handicap: 1, impulses: steady(400, 500) },
      { stats: flatStats(1), handicap: 1, impulses: steady(400, 1000) },
    ], 7);
    expect(results[0].place).toBe(1);
  });
});

describe("the handicap is honest (§8.3.1)", () => {
  it("effective stride is exactly stride × handicap", () => {
    const plain = strideM(flatStats(0.5), EVEN_EVENT, 1);
    expect(strideM(flatStats(0.5), EVEN_EVENT, 2)).toBeCloseTo(plain * 2, 12);
  });

  it("the race header names every entrant's handicap, and replays exactly", () => {
    const event = loadEvent("sprint_100")!;
    const entrants = [
      {
        pet_id: "a", label: "A", handicap_name: "rocket", handicap: 2.0,
        stats: flatStats(0.3, 0.9), impulses: steady(120, 900),
      },
      {
        pet_id: "b", label: "B", handicap_name: "none", handicap: 1.0,
        stats: flatStats(0.8, 0.9), impulses: steady(120, 700),
      },
    ];
    const header = buildRaceHeader({
      event_key: event.key, challenge_key: "arithmetic", difficulty: "sums_10",
      race_seed: 31337, entrants,
    });
    // A result payload that omits a non-1.0 handicap is a failing test.
    expect(header.entrants.map((e) => e.handicap_name)).toEqual(["rocket", "none"]);
    expect(header.entrants[0].handicap).toBe(2.0);
    const first = replayFromHeader(header, event);
    expect(replayFromHeader(header, event)).toEqual(first);
  });
});

describe("the bot is indistinguishable (§7.3)", () => {
  it("a bot log and an identical human-shaped log produce identical results", async () => {
    const { botImpulseLog } = await import("./bot");
    const event = loadEvent("sprint_100")!;
    const botLog = botImpulseLog("steady", 555, 1, event.time_limit_s * 1000);
    expect(botLog.length).toBeGreaterThan(0);
    // Strictly increasing timestamps — a valid impulse stream.
    for (let i = 1; i < botLog.length; i++) {
      expect(botLog[i].at).toBeGreaterThan(botLog[i - 1].at);
    }
    const humanShaped = botLog.map((imp) => ({ ...imp }));
    const stats = flatStats(0.6, 0.9);
    const asBot = simulateRace(event, [{ stats, handicap: 1, impulses: botLog }], 9)[0];
    const asHuman = simulateRace(event, [{ stats, handicap: 1, impulses: humanShaped }], 9)[0];
    expect(asBot).toEqual(asHuman);
  });
});

describe("the legacy pet (§5)", () => {
  it("a manifest with no athletics block still yields a complete entrant", () => {
    const stats = resolveAthletics(
      { movement_class: "aquatic_swimmer", animations: { walk: {}, idle: {} } },
      { speed: 0.03, power: -0.01, endurance: 0.02 });
    const event = loadEvent("racewalk")!;
    const result = simulateRace(event,
      [{ stats, handicap: 1, impulses: steady(60, 1000) }], 3)[0];
    expect(result.distance_m).toBeGreaterThan(0);
  });
});
