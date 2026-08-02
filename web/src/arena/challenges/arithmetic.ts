/**
 * arithmetic — the challenge the parents are actually buying (SPEC_PET_ARENA
 * §8). Typed answers, never multiple choice (§8.5: four-way choice hands out
 * 25% of the progress for free and rewards mashing over knowing). The ladder
 * is §8.7's, starting at sums within 10.
 */

import type { ArenaChallenge, ChallengeQuestion } from "./registry";

function intBetween(rng: () => number, lo: number, hi: number): number {
  return lo + Math.floor(rng() * (hi - lo + 1));
}

const SUMS_10 = "sums_10";
const SUMS_100 = "sums_100";
const TIMES_TABLES = "times_tables";
const BIG_TIMES = "big_times";

function generate(rng: () => number, difficulty: string): ChallengeQuestion {
  switch (difficulty) {
    case SUMS_100: {
      const a = intBetween(rng, 10, 89);
      const b = intBetween(rng, 1, 99 - a);
      return { prompt: `${a} + ${b}`, answer: String(a + b) };
    }
    case TIMES_TABLES: {
      const a = intBetween(rng, 2, 12);
      const b = intBetween(rng, 2, 12);
      return { prompt: `${a} × ${b}`, answer: String(a * b) };
    }
    case BIG_TIMES: {
      const a = intBetween(rng, 12, 99);
      const b = intBetween(rng, 3, 9);
      return { prompt: `${a} × ${b}`, answer: String(a * b) };
    }
    case SUMS_10:
    default: {
      const a = intBetween(rng, 1, 9);
      const b = intBetween(rng, 1, 10 - a);
      return { prompt: `${a} + ${b}`, answer: String(a + b) };
    }
  }
}

export const arithmetic: ArenaChallenge = {
  key: "arithmetic",
  label: "Maths",
  emoji: "🔢",
  inputKind: "numeric",
  ladder: [
    { key: SUMS_10, label: "Sums to 10" },
    { key: SUMS_100, label: "Sums to 100" },
    { key: TIMES_TABLES, label: "Times tables" },
    { key: BIG_TIMES, label: "Big multiplication" },
  ],
  generate,
  check: (given, expected) => given.trim() === expected,
};
