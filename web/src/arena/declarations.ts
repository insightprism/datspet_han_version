/**
 * The ONE place the browser learns where the athletics content lives
 * (SPEC_PET_ARENA §6.1a): the declarations are JSON in `pet_factory/athletics/`
 * — one declaration, four readers (Python resolver, build, tests, this file) —
 * imported at build time, so no backend route exists for the arena (§15).
 *
 * Adding a Tier-1 event = the JSON file + a registry entry (guard-tested in
 * Python) + one import line here; `eventsCoverRegistry` below is the web-side
 * guard that this map and the registry never drift apart.
 */

import movementClassesJson from "../../../pet_factory/athletics/movement_classes.json";
import modifiersJson from "../../../pet_factory/athletics/modifiers.json";
import rollJson from "../../../pet_factory/athletics/roll.json";
import tuningJson from "../../../pet_factory/athletics/tuning.json";
import botsJson from "../../../pet_factory/athletics/bots.json";
import handicapsJson from "../../../pet_factory/athletics/handicaps.json";
import eventsRegistryJson from "../../../pet_factory/athletics/events/registry.json";
import racewalkJson from "../../../pet_factory/athletics/events/racewalk.json";
import sprint100Json from "../../../pet_factory/athletics/events/sprint_100.json";
import sprint200Json from "../../../pet_factory/athletics/events/sprint_200.json";

/** One Tier-1 event declaration (§6.1a). Shapes are guard-tested in
 *  pet_factory/tests/test_athletics.py — the fields here stay loose strings
 *  because the JSON is the contract, not the TypeScript. */
export interface ArenaEventDecl {
  key: string;
  label: string;
  emoji?: string;
  medium: string;
  distance_m: number;
  decay: number;
  race_roll: number;
  time_limit_s: number;
  weights: Record<string, number>;
  requires: string[][];
  team_size: number;
  preferred_poses: string[];
  result_unit: string;
}

export interface MovementClassRow {
  speed: number; power: number; endurance: number;
  land: number; water: number; air: number;
}

export const MOVEMENT_CLASSES: Record<string, MovementClassRow> =
  movementClassesJson.classes;
export const MOVEMENT_CLASS_DEFAULT: string = movementClassesJson.default;

/** {axis: {option: {attribute: delta}}} — §3.2. */
export const MODIFIERS: Record<string, Record<string, Record<string, number>>> =
  modifiersJson.modifiers;

export const PET_ROLL_RANGE: number = rollJson.pet_roll_range;

export interface ArenaTuning { stride_base_m: number; athletic_stride_spread: number; }
export const TUNING: ArenaTuning = tuningJson;

/** answers per second per named rung (§7.3, Rev.6). */
export const BOT_RUNGS: Record<string, number> = botsJson.rungs;

/** name → stride multiplier, the CLOSED ladder (§8.3.1, Rev.6). */
export const HANDICAP_LADDER: Record<string, number> = handicapsJson.handicap_ladder;

export const ARENA_EVENTS: ArenaEventDecl[] = [
  racewalkJson,
  sprint100Json,
  sprint200Json,
];

export function loadEvent(key: string): ArenaEventDecl | undefined {
  return ARENA_EVENTS.find((e) => e.key === key);
}

/** Web-side registry guard: every registry key has an import above and nothing
 *  extra is imported. Asserted by declarations.test.ts so "added the JSON,
 *  forgot the import line" fails the build rather than shipping a missing event. */
export function eventsCoverRegistry(): { missing: string[]; extra: string[] } {
  const registryKeys = eventsRegistryJson.events.map((e) => e.key);
  const importedKeys = ARENA_EVENTS.map((e) => e.key);
  return {
    missing: registryKeys.filter((k) => !importedKeys.includes(k)),
    extra: importedKeys.filter((k) => !registryKeys.includes(k)),
  };
}
