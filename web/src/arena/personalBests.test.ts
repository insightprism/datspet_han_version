/**
 * Personal bests never leave the device (SPEC_PET_ARENA §8.8): a pure
 * key/value contract over an injected store — no fetch anywhere in the
 * module, no jsdom needed here.
 */
import { describe, expect, it } from "vitest";
import { bestKey, readBestSeconds, recordResultSeconds, type BestStore } from "./personalBests";

function memoryStore(): BestStore & { map: Map<string, string> } {
  const map = new Map<string, string>();
  return {
    map,
    getItem: (k) => map.get(k) ?? null,
    setItem: (k, v) => { map.set(k, v); },
  };
}

describe("device-local personal bests (§8.8)", () => {
  it("keyed by event + challenge + difficulty + handicap", () => {
    // A rocket time and a none time are different achievements (§8.3.1).
    const a = bestKey("sprint_100", "arithmetic", "sums_10", "none");
    const b = bestKey("sprint_100", "arithmetic", "sums_10", "rocket");
    const c = bestKey("sprint_100", "tap", "sums_10", "none");
    expect(new Set([a, b, c]).size).toBe(3);
  });

  it("first finish is a best; only faster times overwrite", () => {
    const store = memoryStore();
    const key = bestKey("sprint_100", "arithmetic", "sums_10", "none");
    expect(recordResultSeconds(store, key, 42.5)).toEqual(
      { improved: true, previousSeconds: null });
    expect(recordResultSeconds(store, key, 44.0)).toEqual(
      { improved: false, previousSeconds: 42.5 });
    expect(recordResultSeconds(store, key, 39.9)).toEqual(
      { improved: true, previousSeconds: 42.5 });
    expect(readBestSeconds(store, key)).toBe(39.9);
  });

  it("garbage in storage reads as no best, never a crash", () => {
    const store = memoryStore();
    const key = bestKey("sprint_100", "arithmetic", "sums_10", "none");
    store.setItem(key, "not-a-number");
    expect(readBestSeconds(store, key)).toBeNull();
  });
});
