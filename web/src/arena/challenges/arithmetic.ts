/**
 * arithmetic — the challenge the parents are actually buying (SPEC_PET_ARENA
 * §8). Three choices, tap the right one (§8.5, Rev.10 — the owner's mobile
 * call): the decoys are PLAUSIBLE near-misses (off-by-one, off-by-ten), dealt
 * in seeded order so every entrant sees the identical triple. Guessing loses
 * by mechanics, not hope: a miss burns the question and freezes longer than a
 * typo did — see §8.5 for the arithmetic. The ladder is §8.7's, starting at
 * sums within 10.
 */

import {
  NUM_ANSWER_CHOICES, type ArenaChallenge, type ChallengeQuestion,
} from "./registry";

function intBetween(rng: () => number, lo: number, hi: number): number {
  return lo + Math.floor(rng() * (hi - lo + 1));
}

/** Near-miss offsets a child's actual mistakes produce — the decoys must be
 *  tempting, or elimination-by-absurdity replaces knowing. */
const DECOY_OFFSETS = [1, -1, 2, -2, 10, -10, 3, -3, 20, -20];

function withChoices(prompt: string, answer: number,
                     rng: () => number): ChallengeQuestion {
  const decoys = new Set<number>();
  while (decoys.size < NUM_ANSWER_CHOICES - 1) {
    const offset = DECOY_OFFSETS[Math.floor(rng() * DECOY_OFFSETS.length)];
    const decoy = answer + offset;
    if (decoy !== answer && decoy >= 0) decoys.add(decoy);
  }
  const choices = [answer, ...Array.from(decoys)].map(String);
  // Seeded shuffle — the deal order is part of the question (§8.3).
  for (let i = choices.length - 1; i > 0; i--) {
    const j = Math.floor(rng() * (i + 1));
    [choices[i], choices[j]] = [choices[j], choices[i]];
  }
  return { prompt, answer: String(answer), choices };
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
      return withChoices(`${a} + ${b}`, a + b, rng);
    }
    case TIMES_TABLES: {
      const a = intBetween(rng, 2, 12);
      const b = intBetween(rng, 2, 12);
      return withChoices(`${a} × ${b}`, a * b, rng);
    }
    case BIG_TIMES: {
      const a = intBetween(rng, 12, 99);
      const b = intBetween(rng, 3, 9);
      return withChoices(`${a} × ${b}`, a * b, rng);
    }
    case SUMS_10:
    default: {
      const a = intBetween(rng, 1, 9);
      const b = intBetween(rng, 1, 10 - a);
      return withChoices(`${a} + ${b}`, a + b, rng);
    }
  }
}

export const arithmetic: ArenaChallenge = {
  key: "arithmetic",
  label: "Maths",
  emoji: "🔢",
  inputKind: "choice",
  ladder: [
    { key: SUMS_10, label: "Sums to 10" },
    { key: SUMS_100, label: "Sums to 100" },
    { key: TIMES_TABLES, label: "Times tables" },
    { key: BIG_TIMES, label: "Big multiplication" },
  ],
  generate,
  check: (given, expected) => given.trim() === expected,
};
