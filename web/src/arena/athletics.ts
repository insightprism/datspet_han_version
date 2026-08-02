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
  IDENTITY_NUDGE_RANGE, MODIFIERS, MOVEMENT_CLASSES, MOVEMENT_CLASS_DEFAULT,
  TUNING,
  type ArenaEventDecl, type ArenaTuning, type MovementClassRow,
} from "./declarations";

export const SCHEMA_VERSION = "pet_athletics.v1";
export const TABLE_VERSION = "athletics.v1";
export const ATTRIBUTES = ["speed", "power", "endurance"] as const;
export const MEDIUMS = ["land", "water", "air"] as const;

/** §3.4 (Rev.7) — the identity profile: one bounded nudge per attribute,
 *  decoded from the pet id. Identity has SHAPE, not just level. */
export interface IdentityNudges {
  speed: number; power: number; endurance: number;
}

export interface AthleticsStats {
  schema_version: string;
  table_version: string;
  speed: number; power: number; endurance: number;
  land: number; water: number; air: number;
  identity_nudges: IdentityNudges;
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
 * §3.4 (Rev.7) — decode the pet id into the identity profile. The owner's
 * design ("put values to the letters and convert it into base 10"), hardened:
 * sha256 of the UTF-8 id; attribute i takes bytes [4i, 4i+4) big-endian,
 * mapped onto ±IDENTITY_NUDGE_RANGE. Mirrors `identity_nudges_from_pet_id`
 * exactly. Same id → same athlete, forever, with nothing stored and no asset
 * fetch — which is also why an adopted copy of a store pet (its own id) is a
 * distinct athlete from its twin.
 */
export async function deriveIdentityNudges(petId: string): Promise<IdentityNudges> {
  // globalThis, not the bare identifier: the browser, Node 18+, and the
  // vitest worker sandbox all expose WebCrypto there.
  const digest = await globalThis.crypto.subtle.digest(
    "SHA-256", new TextEncoder().encode(petId));
  const view = new DataView(digest);
  const fold = (segment: number) =>
    (2 * (view.getUint32(segment * 4) / 0xffffffff) - 1) * IDENTITY_NUDGE_RANGE;
  return { speed: fold(0), power: fold(1), endurance: fold(2) };
}

const NEUTRAL_NUDGES: IdentityNudges = { speed: 0, power: 0, endurance: 0 };

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

function nudgesAreValid(nudges: unknown): nudges is IdentityNudges {
  if (typeof nudges !== "object" || nudges === null) return false;
  const n = nudges as Record<string, unknown>;
  return ATTRIBUTES.every((a) => isFiniteNumber(n[a]));
}

/**
 * §5.1 precedence, verbatim from the Python resolver: valid block → use it as
 * is; stale/malformed block → re-derive reusing its stored `identity_nudges`
 * (§5.3 — identity survives a rebalance, and even a nudge-algorithm change);
 * absent → derive. `nudges` is the pre-computed id decode (hashing is async,
 * so the caller derives it once — `deriveIdentityNudges(petId)`); it is
 * ignored whenever stored nudges exist.
 */
export function resolveAthletics(
  manifest: AthleticsManifest | null | undefined,
  nudges: IdentityNudges | null,
): AthleticsStats {
  const m = manifest ?? {};
  const block = m.athletics;
  if (blockIsValid(block)) return block;

  const stored = (typeof block === "object" && block !== null)
    ? (block as Record<string, unknown>).identity_nudges : undefined;
  const identity = nudgesAreValid(stored) ? stored : (nudges ?? NEUTRAL_NUDGES);

  const row = baseRow(m.movement_class);
  const poses = Object.keys(m.animations ?? {});
  const picks = m.design?.picks ?? {};

  const stats: Record<string, number> = {};
  for (const attr of ATTRIBUTES) {
    let value = row[attr] + identity[attr];
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
    identity_nudges: identity,
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
