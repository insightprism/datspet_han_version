/**
 * The answer rules — ONE definition for every screen that mounts a challenge
 * (SPEC_PET_ARENA §7.2, §8.5, Rev.11). The solo and room race screens forked
 * these once (review finding F5): the room version dropped the choice burn —
 * turning multiple choice into eliminate-and-win in the one mode where you
 * race a human — hand-rolled its own answer comparison instead of the
 * challenge's `check`, and lost crashes entirely. Screens own WHERE a correct
 * answer goes (a local log, an upload queue); this module owns what an answer
 * MEANS.
 */

import {
  WRONG_ANSWER_LOCKOUT_MS, WRONG_CHOICE_LOCKOUT_MS,
} from "../constants";
import type { ArenaChallenge, ChallengeQuestion } from "./registry";

export interface AnswerOutcome {
  correct: boolean;
  /** Rev.10 §8.5 — a wrong CHOICE burns the question: no eliminating your
   *  way to the answer; every guess is a fresh 1-in-3. */
  burnQuestion: boolean;
  /** §7.2 — a wrong answer costs TIME, never distance. Zero when correct. */
  lockoutMs: number;
  /** Rev.11 — a wrong answer while parked at a hurdle gate IS hitting the
   *  hurdle. The screen decides what a crash looks like and when crashes
   *  disqualify; this only says one happened. */
  crash: boolean;
}

export function judgeAnswer(
  challenge: ArenaChallenge,
  question: ChallengeQuestion,
  given: string,
  opts: { atGate: boolean; hurdledEvent: boolean },
): AnswerOutcome {
  // The challenge's own comparator, always — typing normalizes, arithmetic
  // trims, tap always passes. A screen re-implementing this is the fork
  // this module exists to prevent.
  if (challenge.check(given, question.answer)) {
    return { correct: true, burnQuestion: false, lockoutMs: 0, crash: false };
  }
  const isChoice = challenge.inputKind === "choice";
  return {
    correct: false,
    burnQuestion: isChoice,
    lockoutMs: isChoice ? WRONG_CHOICE_LOCKOUT_MS : WRONG_ANSWER_LOCKOUT_MS,
    crash: opts.atGate && opts.hurdledEvent,
  };
}
