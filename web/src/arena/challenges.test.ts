/**
 * Challenge registry guards (SPEC_PET_ARENA §8, §14) — the enforcement rule
 * every registry carries, plus the two child-facing invariants: identical
 * question sequences from one seed (§8.3) and no answer set to guess from
 * (§8.5).
 */
import { describe, expect, it } from "vitest";
import { CHALLENGES, listChallenges } from "./challenges/registry";
import { mulberry32 } from "./rng";

describe("both registries enforced (§14)", () => {
  it("every challenge declares generate, check, inputKind and a ladder", () => {
    expect(listChallenges().length).toBeGreaterThanOrEqual(2); // tap + arithmetic (§12)
    for (const c of listChallenges()) {
      expect(c.key).toBeTruthy();
      expect(c.label).toBeTruthy();
      expect(["numeric", "tap"]).toContain(c.inputKind);
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

describe("guessing does not pay (§8.5)", () => {
  it("arithmetic is typed numeric — no choice list exists to mash", () => {
    const arithmetic = CHALLENGES.arithmetic;
    expect(arithmetic.inputKind).toBe("numeric");
    // The question exposes a prompt and the checked answer — nothing else.
    const q = arithmetic.generate(mulberry32(1), arithmetic.ladder[0].key);
    expect(Object.keys(q).sort()).toEqual(["answer", "prompt"]);
  });

  it("arithmetic answers actually check out", () => {
    const arithmetic = CHALLENGES.arithmetic;
    for (const rung of arithmetic.ladder) {
      const rng = mulberry32(7);
      for (let i = 0; i < 100; i++) {
        const q = arithmetic.generate(rng, rung.key);
        expect(arithmetic.check(q.answer, q.answer)).toBe(true);
        expect(arithmetic.check(`${q.answer}1`, q.answer)).toBe(false);
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
