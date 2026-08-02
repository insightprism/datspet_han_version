/**
 * Challenge registry guards (SPEC_PET_ARENA §8, §14) — the enforcement rule
 * every registry carries, plus the two child-facing invariants: identical
 * question sequences from one seed (§8.3) and no answer set to guess from
 * (§8.5).
 */
import { describe, expect, it } from "vitest";
import {
  CHALLENGES, listChallenges, questionAt, NUM_ANSWER_CHOICES,
} from "./challenges/registry";
import {
  WRONG_ANSWER_LOCKOUT_MS, WRONG_CHOICE_LOCKOUT_MS,
} from "./constants";
import { mulberry32 } from "./rng";

describe("both registries enforced (§14)", () => {
  it("every challenge declares generate, check, inputKind and a ladder", () => {
    expect(listChallenges().length).toBeGreaterThanOrEqual(2); // tap + arithmetic (§12)
    for (const c of listChallenges()) {
      expect(c.key).toBeTruthy();
      expect(c.label).toBeTruthy();
      expect(["numeric", "tap", "text", "choice"]).toContain(c.inputKind);
      expect(c.ladder.length).toBeGreaterThan(0);
      expect(typeof c.generate).toBe("function");
      expect(typeof c.check).toBe("function");
    }
  });

  it("registry keys match declared keys", () => {
    for (const [key, c] of Object.entries(CHALLENGES)) {
      expect(c.key).toBe(key);
    }
  });
});

describe("same questions for everyone (§8.3)", () => {
  it("one seed → identical prompt sequences in identical order", () => {
    for (const c of listChallenges()) {
      for (const rung of c.ladder) {
        const a = mulberry32(20260802);
        const b = mulberry32(20260802);
        for (let i = 0; i < 50; i++) {
          expect(c.generate(a, rung.key)).toEqual(c.generate(b, rung.key));
        }
      }
    }
  });
});

describe("guessing loses (§8.5, Rev.10)", () => {
  it("arithmetic deals exactly three choices, the answer among them", () => {
    const arithmetic = CHALLENGES.arithmetic;
    expect(arithmetic.inputKind).toBe("choice");
    for (const rung of arithmetic.ladder) {
      const rng = mulberry32(7);
      for (let i = 0; i < 100; i++) {
        const q = arithmetic.generate(rng, rung.key);
        expect(q.choices).toHaveLength(NUM_ANSWER_CHOICES);
        expect(q.choices).toContain(q.answer);
        expect(new Set(q.choices).size).toBe(NUM_ANSWER_CHOICES);
        expect(arithmetic.check(q.answer, q.answer)).toBe(true);
        expect(arithmetic.check(`${q.answer}1`, q.answer)).toBe(false);
      }
    }
  });

  it("the same (seed, index, rung) deals identical choices in order (§8.3)", () => {
    const arithmetic = CHALLENGES.arithmetic;
    for (let i = 0; i < 20; i++) {
      expect(questionAt(arithmetic, 20260802, i, "times_tables"))
        .toEqual(questionAt(arithmetic, 20260802, i, "times_tables"));
    }
  });

  it("the miss freeze keeps mashing at a fraction of knowing", () => {
    // §14 — the constant relation §8.5's arithmetic rests on: if these drift
    // to where guessing approaches knowing, this is the alarm.
    expect(WRONG_CHOICE_LOCKOUT_MS).toBeGreaterThanOrEqual(
      2 * WRONG_ANSWER_LOCKOUT_MS);
  });
});

describe("typing types the shown word (§8.1)", () => {
  it("accepts case and spacing slop, refuses a different word", () => {
    const typing = CHALLENGES.typing;
    for (const rung of typing.ladder) {
      const rng = mulberry32(11);
      for (let i = 0; i < 50; i++) {
        const q = typing.generate(rng, rung.key);
        expect(typing.check(q.answer, q.answer)).toBe(true);
        expect(typing.check(`  ${q.answer.toUpperCase()}  `, q.answer)).toBe(true);
        expect(typing.check(`${q.answer}x`, q.answer)).toBe(false);
      }
    }
  });
});

describe("tap is the floor, not a fallback (§8.6)", () => {
  it("tap is a full registry entry that accepts every press", () => {
    const tap = CHALLENGES.tap;
    expect(tap.inputKind).toBe("tap");
    expect(tap.check("", "")).toBe(true);
  });
});
