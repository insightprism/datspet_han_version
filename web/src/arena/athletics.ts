/**
 * The browser-side mirror of `pet_factory.athletics`'s resolver + eligibility
 * (SPEC_PET_ARENA §5, §6.3). Same precedence, same clamps, same roll
 * derivation — the shared race-vector fixture and these being *thin* is what
 * keeps two languages honest about one rule set.
 *
 * Stats resolve at READ TIME from facts every manifest already carries (§5) —
 * which is why every pet ever built can compete on day one, and why nothing
 * here branches on whether a pet was minted with a stamped block (§0.14).
 */

import type { RawManifest } from "@/pet";
import {
  MODIFIERS, MOVEMENT_CLASSES, MOVEMENT_CLASS_DEFAULT, PET_ROLL_RANGE, TUNING,
  type ArenaEventDecl, type ArenaTuning, type MovementClassRow,
} from "./declarations";

export const SCHEMA_VERSION = "pet_athletics.v1";
export const TABLE_VERSION = "athletics.v1";
export const ATTRIBUTES = ["speed", "power", "endurance"] as const;
export const MEDIUMS = ["land", "water", "air"] as const;

export interface AthleticsStats {
  schema_version: string;
  table_version: string;
  speed: number; power: number; endurance: number;
  land: number; water: number; air: number;
  roll: number;
  poses: string[];
}

function clamp01(v: number): number {
  return v < 0 ? 0 : v > 1 ? 1 : v;
}

function baseRow(movementClass: string | undefined): MovementClassRow {
  if (movementClass && MOVEMENT_CLASSES[movementClass]) {
    return MOVEMENT_CLASSES[movementClass];
  }
  return MOVEMENT_CLASSES[MOVEMENT_CLASS_DEFAULT];
}

/**
 * §5.2 — the stable roll for a pet that was never minted one, derived from the
 * sheet bytes the arena fetched anyway. Mirrors `derive_roll_from_sheet`
 * exactly: sha256, first 4 bytes big-endian, mapped onto ±PET_ROLL_RANGE.
 */
export async function deriveRollFromSheet(bytes: ArrayBuffer): Promise<number> {
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  const unit = new DataView(digest).getUint32(0) / 0xffffffff;
  return (2 * unit - 1) * PET_ROLL_RANGE;
}

function isFiniteNumber(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

function blockIsValid(block: unknown): block is AthleticsStats {
  if (typeof block !== "object" || block === null) return false;
  const b = block as Record<string, unknown>;
  if (b.schema_version !== SCHEMA_VERSION) return false;
  if (b.table_version !== TABLE_VERSION) return false;
  return [...ATTRIBUTES, ...MEDIUMS].every((k) => isFiniteNumber(b[k]));
}

/** The manifest fields the resolver reads — RawManifest plus the (optional)
 *  stamped athletics block and the design provenance block. */
export interface AthleticsManifest extends RawManifest {
  athletics?: unknown;
  design?: { picks?: Record<string, string> };
}

/**
 * §5.1 precedence, verbatim from the Python resolver: valid block → use it as
 * is; stale/malformed block → re-derive reusing its stored roll (§5.3 —
 * identity survives a rebalance); absent → derive. `roll` is the pre-computed
 * sheet roll (hashing is async, so the caller derives it once at load time);
 * it is ignored whenever a stored roll exists.
 */
export function resolveAthletics(
  manifest: AthleticsManifest | null | undefined,
  roll: number | null,
): AthleticsStats {
  const m = manifest ?? {};
  const block = m.athletics;
  if (blockIsValid(block)) return block;

  const stored = (typeof block === "object" && block !== null)
    ? (block as Record<string, unknown>).roll : undefined;
  const effectiveRoll = isFiniteNumber(stored) ? stored : (roll ?? 0);

  const row = baseRow(m.movement_class);
  const poses = Object.keys(m.animations ?? {});
  const picks = m.design?.picks ?? {};

  const stats: Record<string, number> = {};
  for (const attr of ATTRIBUTES) {
    let value = row[attr] + effectiveRoll;
    for (const [axis, option] of Object.entries(picks)) {
      const delta = MODIFIERS[axis]?.[option]?.[attr];
      if (isFiniteNumber(delta)) value += delta;
    }
    stats[attr] = clamp01(value);
  }
  for (const medium of MEDIUMS) {
    stats[medium] = clamp01(row[medium]);
  }

  return {
    schema_version: SCHEMA_VERSION,
    table_version: TABLE_VERSION,
    speed: stats.speed, power: stats.power, endurance: stats.endurance,
    land: stats.land, water: stats.water, air: stats.air,
    roll: effectiveRoll,
    poses,
  };
}

// ---------------------------------------------------------------------------
// Eligibility (§6.3) — AND-of-ORs, and deliberately nothing more (§6.3.1).
// ---------------------------------------------------------------------------
export function qualifies(poses: Iterable<string>, requires: string[][]): boolean {
  const owned = new Set(poses);
  return requires.every((clause) => clause.some((pose) => owned.has(pose)));
}

/** §6.3.3 — locked events are SHOWN, with every unsatisfied clause named,
 *  alternatives and all. The UI renders these; it never filters the event out. */
export function unsatisfiedClauses(
  poses: Iterable<string>, requires: string[][],
): string[][] {
  const owned = new Set(poses);
  return requires.filter((clause) => !clause.some((pose) => owned.has(pose)));
}

/** §6.5 — team qualification is per member; a team is refused whole and the
 *  UI names which pet is the problem. Singles are a team of one. */
export function teamQualifies(
  memberPoses: Iterable<string>[], event: ArenaEventDecl,
): { ok: boolean; failingMembers: number[] } {
  const failingMembers = memberPoses
    .map((poses, i) => (qualifies(poses, event.requires) ? -1 : i))
    .filter((i) => i >= 0);
  return { ok: failingMembers.length === 0, failingMembers };
}

// ---------------------------------------------------------------------------
// Stride (§2.3) — pinned by raceEngine.test.ts; mirrors `stride_m` exactly.
// ---------------------------------------------------------------------------
export function strideM(
  stats: AthleticsStats,
  event: ArenaEventDecl,
  handicap: number = 1.0,
  tuningOverride?: ArenaTuning,
): number {
  const knobs = tuningOverride ?? TUNING;
  let score = 0;
  for (const attr of ATTRIBUTES) {
    score += (event.weights[attr] ?? 0) * clamp01(stats[attr]);
  }
  const affinity = clamp01((stats as unknown as Record<string, number>)[event.medium] ?? 0);
  score = clamp01(score) * affinity;
  return knobs.stride_base_m
    * Math.pow(knobs.athletic_stride_spread, score - 0.5)
    * handicap;
}
