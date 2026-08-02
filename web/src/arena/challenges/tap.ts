/**
 * tap — the accessibility floor, and not a lesser mode (SPEC_PET_ARENA §8.6):
 * no reading, no arithmetic, no typing. A four-year-old, a child with
 * dyslexia, and a sibling who just wants to play all need it, and tap rate is
 * a real skill — a fast tapper beating a slow multiplier is a legitimate
 * outcome. Also the control challenge for tuning (§12): same event, same
 * pets, no arithmetic.
 */

import type { ArenaChallenge } from "./registry";

const STEADY = "steady";

export const tap: ArenaChallenge = {
  key: "tap",
  label: "Tap!",
  emoji: "👆",
  inputKind: "tap",
  ladder: [{ key: STEADY, label: "Tap tap tap" }],
  generate: () => ({ prompt: "TAP!", answer: "" }),
  check: () => true,
};
