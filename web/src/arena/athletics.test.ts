/**
 * Resolver + eligibility guards, browser side (SPEC_PET_ARENA §14). The
 * Python twin (pet_factory/tests/test_athletics.py) guards the data files;
 * these guard the mirror's behavior and the web-only surfaces.
 */
import { describe, expect, it } from "vitest";
import {
  qualifies, resolveAthletics, teamQualifies, unsatisfiedClauses,
  SCHEMA_VERSION, TABLE_VERSION,
} from "./athletics";
import {
  ARENA_EVENTS, eventsCoverRegistry, loadEvent, MOVEMENT_CLASSES,
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
    roll: 0.031, poses: ["walk", "idle"],
  };

  it("a valid stamped block is used verbatim", () => {
    const resolved = resolveAthletics(
      { athletics: validBlock, movement_class: "aquatic_swimmer" }, 0.07);
    expect(resolved).toBe(validBlock);
  });

  it("a stale table_version recomputes but keeps the stored roll (§5.3)", () => {
    const stale = { ...validBlock, table_version: "athletics.v0", roll: 0.05 };
    const resolved = resolveAthletics(
      { athletics: stale, movement_class: "mammalian_quadruped" }, 0.07);
    expect(resolved.table_version).toBe(TABLE_VERSION);
    expect(resolved.roll).toBe(0.05); // identity survives the rebalance
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
