/**
 * The challenge registry (SPEC_PET_ARENA §8.1) — the second registry,
 * orthogonal to events: any challenge can drive any event. One challenge =
 * one file here + one entry below; the guard test (challenges.test.ts) fails
 * the build on a half-formed entry, the same enforcement rule every registry
 * in this repo carries.
 *
 * Challenges are browser-only content — nothing server-side ever needs to
 * know what 7 × 8 is (§9.1).
 */

import { arithmetic } from "./arithmetic";
import { tap } from "./tap";

/** §8.2 — a challenge is a seeded generator plus a validator, both pure.
 *  Nobody writes a question bank. */
export interface ChallengeQuestion {
  prompt: string;
  answer: string;
}

export interface DifficultyRung {
  key: string;
  label: string;
}

export interface ArenaChallenge {
  key: string;
  label: string;
  emoji: string;
  /** §8.5/§8.6 — "numeric" is typed digits (never multiple choice); "tap" is
   *  the accessibility floor: no reading, no arithmetic, no typing. */
  inputKind: "numeric" | "tap";
  /** §8.7 — a declared ladder, selectable at race setup, never adaptive. */
  ladder: DifficultyRung[];
  /** Pure and seeded: the same rng sequence yields the same questions — the
   *  fairness mechanism (§8.3) and the replay mechanism (§7.4) at once. */
  generate(rng: () => number, difficulty: string): ChallengeQuestion;
  check(given: string, expected: string): boolean;
}

export const CHALLENGES: Record<string, ArenaChallenge> = {
  [tap.key]: tap,
  [arithmetic.key]: arithmetic,
};

export function listChallenges(): ArenaChallenge[] {
  return Object.values(CHALLENGES);
}
