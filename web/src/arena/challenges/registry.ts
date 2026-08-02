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

import { mix32, mulberry32 } from "../rng";
import { arithmetic } from "./arithmetic";
import { tap } from "./tap";
import { typing } from "./typing";

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
  /** §8.5/§8.6 — "numeric" is typed digits, "text" typed words (never
   *  multiple choice, either); "tap" is the accessibility floor: no reading,
   *  no arithmetic, no typing. */
  inputKind: "numeric" | "tap" | "text";
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
  [typing.key]: typing,
};

export function listChallenges(): ArenaChallenge[] {
  return Object.values(CHALLENGES);
}

/** Salt for the per-question rng stream — distinct from the race-roll and bot
 *  streams that share mix32. */
const QUESTION_STREAM_SALT = 0x517e57;

/**
 * Question `i` at difficulty `d` as a pure function of `(raceSeed, i, d)` —
 * Rev.9's fairness rule (§8.3): every player's question #i at a given rung is
 * identical, even when hurdle gates make their difficulty PATHS diverge.
 */
export function questionAt(
  challenge: ArenaChallenge, raceSeed: number, index: number, difficulty: string,
): ChallengeQuestion {
  return challenge.generate(
    mulberry32(mix32(raceSeed, QUESTION_STREAM_SALT, index)), difficulty);
}

/** One ladder-rung harder — the hurdle-gate question (Rev.9). A single-rung
 *  challenge (tap) stays itself; only its color flips. */
export function harderRung(challenge: ArenaChallenge, difficulty: string): string {
  const idx = challenge.ladder.findIndex((rung) => rung.key === difficulty);
  return challenge.ladder[Math.min(idx + 1, challenge.ladder.length - 1)]?.key
    ?? difficulty;
}
