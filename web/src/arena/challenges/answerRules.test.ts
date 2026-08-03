/**
 * The answer rules (F5's de-fork) — the contract both race screens mount.
 * The room screen once re-implemented these and drifted on all four counts
 * (no choice burn, hand-rolled comparison, no crashes, silent about the
 * limit); the rules now live here once, and these tests are the spec.
 */
import { describe, expect, it } from "vitest";
import { judgeAnswer } from "./answerRules";
import { CHALLENGES, questionAt } from "./registry";
import {
  WRONG_ANSWER_LOCKOUT_MS, WRONG_CHOICE_LOCKOUT_MS,
} from "../constants";

const arithmetic = CHALLENGES.arithmetic;
const typing = CHALLENGES.typing;
const tap = CHALLENGES.tap;
const NO_GATE = { atGate: false, hurdledEvent: true };

describe("judgeAnswer", () => {
  it("uses the challenge's own comparator, not string equality", () => {
    const q = questionAt(typing, 42, 0, typing.ladder[0].key);
    // typing.check normalizes; a raw !== comparison would fail this.
    expect(judgeAnswer(typing, q, `  ${q.answer.toUpperCase()}  `, NO_GATE)
      .correct).toBe(true);
  });

  it("burns the question on a wrong CHOICE — every guess is a fresh 1-in-3 (§8.5)", () => {
    const q = questionAt(arithmetic, 42, 0, arithmetic.ladder[0].key);
    const wrong = (q.choices ?? []).find((c) => c !== q.answer)!;
    const out = judgeAnswer(arithmetic, q, wrong, NO_GATE);
    expect(out.correct).toBe(false);
    expect(out.burnQuestion).toBe(true);
    expect(out.lockoutMs).toBe(WRONG_CHOICE_LOCKOUT_MS);
  });

  it("locks a wrong typed answer without burning", () => {
    const q = questionAt(typing, 7, 3, typing.ladder[0].key);
    const out = judgeAnswer(typing, q, "definitely-wrong", NO_GATE);
    expect(out.burnQuestion).toBe(false);
    expect(out.lockoutMs).toBe(WRONG_ANSWER_LOCKOUT_MS);
  });

  it("a wrong answer AT a gate in a hurdled event is a crash (Rev.11)", () => {
    const q = questionAt(arithmetic, 42, 0, arithmetic.ladder[1].key);
    const wrong = (q.choices ?? []).find((c) => c !== q.answer)!;
    expect(judgeAnswer(arithmetic, q, wrong,
      { atGate: true, hurdledEvent: true }).crash).toBe(true);
    // No hurdles in the event → a gate flag can't crash anyone.
    expect(judgeAnswer(arithmetic, q, wrong,
      { atGate: true, hurdledEvent: false }).crash).toBe(false);
  });

  it("tap always lands — rate is the game, not accuracy (§8.6)", () => {
    const q = questionAt(tap, 1, 0, tap.ladder[0].key);
    expect(judgeAnswer(tap, q, "", NO_GATE).correct).toBe(true);
  });
});
