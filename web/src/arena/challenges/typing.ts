/**
 * typing — type the shown word before your rivals type theirs (SPEC_PET_ARENA
 * §8.1 names it; Nitro Type is the proof this loop carries a race). Binary
 * scoring like every v1 challenge: the word is right or it is not — §7.1's
 * graded-quality door stays open for a future words-per-minute variant, but
 * partial credit on spelling is a judgement call and v1 declines it.
 *
 * The vocabulary is content inside the generator (§8.2: a seeded generator,
 * not an authored question bank — the same seed always deals the same words,
 * which is what makes hot-seat fair).
 */

import type { ArenaChallenge, ChallengeQuestion } from "./registry";

const SHORT_WORDS = "short_words";
const LONG_WORDS = "long_words";
const WORD_PAIRS = "word_pairs";

/** Child-friendly, lowercase, no punctuation — the input check is exact after
 *  case/whitespace folding, so the words themselves must be unambiguous. */
const SHORT_POOL = [
  "cat", "dog", "sun", "hat", "run", "big", "red", "top", "cup", "pig",
  "fox", "bed", "map", "jam", "log", "wet", "fun", "zip", "box", "hop",
];
const LONG_POOL = [
  "rabbit", "dragon", "purple", "rocket", "jungle", "window", "basket",
  "monkey", "pencil", "garden", "castle", "planet", "silver", "cheese",
  "button", "flower", "puddle", "helmet", "magnet", "turtle",
];

function pick(pool: string[], rng: () => number): string {
  return pool[Math.floor(rng() * pool.length)];
}

function generate(rng: () => number, difficulty: string): ChallengeQuestion {
  switch (difficulty) {
    case LONG_WORDS: {
      const word = pick(LONG_POOL, rng);
      return { prompt: word, answer: word };
    }
    case WORD_PAIRS: {
      const phrase = `${pick(SHORT_POOL, rng)} ${pick(LONG_POOL, rng)}`;
      return { prompt: phrase, answer: phrase };
    }
    case SHORT_WORDS:
    default: {
      const word = pick(SHORT_POOL, rng);
      return { prompt: word, answer: word };
    }
  }
}

export const typing: ArenaChallenge = {
  key: "typing",
  label: "Typing",
  emoji: "⌨️",
  inputKind: "text",
  ladder: [
    { key: SHORT_WORDS, label: "Short words" },
    { key: LONG_WORDS, label: "Longer words" },
    { key: WORD_PAIRS, label: "Two words" },
  ],
  generate,
  check: (given, expected) =>
    given.trim().toLowerCase().replace(/\s+/g, " ") === expected,
};
