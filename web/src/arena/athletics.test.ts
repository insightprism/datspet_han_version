/**
 * Resolver + eligibility guards, browser side (SPEC_PET_ARENA §14). The
 * Python twin (pet_factory/tests/test_athletics.py) guards the data files;
 * these guard the mirror's behavior and the web-only surfaces.
 */
import { webcrypto } from "node:crypto";
import { describe, expect, it } from "vitest";
import {
  deriveIdentityNudges, qualifies, resolveAthletics, teamQualifies,
  unsatisfiedClauses,
  SCHEMA_VERSION, TABLE_VERSION,
} from "./athletics";

// Node 18's vitest worker threads lack the WebCrypto global every browser
// guarantees; hand the tests what the runtime always has. Harness-only —
// the app code stays browser-clean.
if (!globalThis.crypto) {
  (globalThis as { crypto?: Crypto }).crypto = webcrypto as unknown as Crypto;
}
import {
  ARENA_EVENTS, eventsCoverRegistry, loadEvent, IDENTITY_NUDGE_RANGE,
  MOVEMENT_CLASSES,
} from "./declarations";

describe("declarations cover the registry", () => {
  it("every registry event is imported, nothing extra", () => {
    // "Added the JSON, forgot the import line" fails here instead of shipping
    // an event the browser cannot see.
    expect(eventsCoverRegistry()).toEqual({ missing: [], extra: [] });
  });
});

describe("resolver precedence (§5.1)", () => {
  const validBlock = {
    schema_version: SCHEMA_VERSION, table_version: TABLE_VERSION,
    speed: 0.71, power: 0.42, endurance: 0.63,
    land: 0.95, water: 0.3, air: 0.05,
    identity_nudges: { speed: 0.031, power: -0.02, endurance: 0 },
    poses: ["walk", "idle"],
  };
  const someNudges = { speed: 0.07, power: 0.01, endurance: -0.05 };

  it("a valid stamped block is used verbatim", () => {
    const resolved = resolveAthletics(
      { athletics: validBlock, movement_class: "aquatic_swimmer" }, someNudges);
    expect(resolved).toBe(validBlock);
  });

  it("a stale table_version recomputes but keeps the stored nudges (§5.3)", () => {
    const stale = {
      ...validBlock, table_version: "athletics.v0",
      identity_nudges: { speed: 0.05, power: -0.03, endurance: 0.01 },
    };
    const resolved = resolveAthletics(
      { athletics: stale, movement_class: "mammalian_quadruped" }, someNudges);
    expect(resolved.table_version).toBe(TABLE_VERSION);
    // Identity survives the rebalance — the stored nudges win over the
    // freshly derived ones.
    expect(resolved.identity_nudges).toEqual(stale.identity_nudges);
  });

  it("an absent block derives from manifest facts, never raises", () => {
    for (const manifest of [null, undefined, {}, { movement_class: "nope" }]) {
      const resolved = resolveAthletics(manifest as never, null);
      expect(resolved.speed).toBeGreaterThanOrEqual(0);
      expect(resolved.speed).toBeLessThanOrEqual(1);
    }
    const fish = resolveAthletics(
      { movement_class: "aquatic_swimmer", animations: { walk: {}, swim: {} } }, null);
    expect(fish.water).toBe(MOVEMENT_CLASSES.aquatic_swimmer.water);
    expect(fish.poses).toEqual(["walk", "swim"]);
  });
});

describe("the identity is the pet id, decoded (§3.4 Rev.7)", () => {
  it("same id → same athlete; different id → different athlete; bounded", async () => {
    const a = await deriveIdentityNudges("11111111-2222-3333-4444-555555555555");
    const b = await deriveIdentityNudges("11111111-2222-3333-4444-555555555555");
    const c = await deriveIdentityNudges("99999999-8888-7777-6666-000000000000");
    expect(a).toEqual(b);
    expect(a).not.toEqual(c);
    for (const nudges of [a, c]) {
      for (const value of Object.values(nudges)) {
        expect(Math.abs(value)).toBeLessThanOrEqual(IDENTITY_NUDGE_RANGE);
      }
    }
    // Shape, not just level: the three folds are independent.
    expect(new Set(Object.values(a).map((v) => v.toFixed(6))).size).toBeGreaterThan(1);
  });

  it("matches the Python derivation bit for bit", async () => {
    // Pinned against pet_factory.athletics.identity_nudges_from_pet_id for
    // the fixed id "stamppet0001" — regenerate ONLY if the algorithm
    // deliberately changes (then update both sides together).
    const nudges = await deriveIdentityNudges("stamppet0001");
    expect(nudges.speed).toBeCloseTo(0.05798193491482687, 12);
    expect(nudges.power).toBeCloseTo(0.0157129591181206, 12);
    expect(nudges.endurance).toBeCloseTo(0.07328344777070067, 12);
  });
});

describe("eligibility (§6.3)", () => {
  it("the flopping fish: run owned → admitted; not owned → refused", () => {
    const event = loadEvent("sprint_100")!;
    expect(qualifies(["walk", "idle", "run"], event.requires)).toBe(true);
    expect(qualifies(["walk", "idle", "swim"], event.requires)).toBe(false);
  });

  it("alternatives within a clause are honoured — the whole evaluator", () => {
    const hurdles = [["run"], ["jump", "play"]];
    expect(qualifies(["run", "play"], hurdles)).toBe(true);   // alternative ok
    expect(qualifies(["walk", "jump"], hurdles)).toBe(false); // missing run
    expect(qualifies(["run"], hurdles)).toBe(false);          // missing both alts
  });

  it("locked is visible: every unsatisfied clause named with its alternatives", () => {
    const hurdles = [["run"], ["jump", "play"]];
    expect(unsatisfiedClauses(["run"], hurdles)).toEqual([["jump", "play"]]);
    expect(unsatisfiedClauses(["walk"], hurdles)).toEqual([["run"], ["jump", "play"]]);
  });

  it("the universal event: a 2-pose pet qualifies somewhere", () => {
    // walk+idle is the base-tier floor (§10.5); the racewalk is the guarantee.
    expect(ARENA_EVENTS.some((e) => qualifies(["walk", "idle"], e.requires))).toBe(true);
  });

  it("team qualification is per member, and the failing pet is named (§6.5)", () => {
    const event = loadEvent("sprint_100")!;
    const team = teamQualifies([
      ["walk", "run"], ["walk", "run"], ["walk"], ["walk", "run"],
    ], event);
    expect(team.ok).toBe(false);
    expect(team.failingMembers).toEqual([2]); // carried members fail loudly
    expect(teamQualifies([["run"], ["run"]], event).ok).toBe(true);
  });
});
