/**
 * Personal bests — the default framing of a result (SPEC_PET_ARENA §8.8):
 * "you beat your own time" leads, placement comes second.
 *
 * DEVICE-LOCAL, deliberately: localStorage, keyed by event + challenge +
 * difficulty + handicap, and no network call — §15's no-persisted-results
 * posture holds and §11's shared-results tripwire stays unfired. Clearing the
 * browser clears the bests; accepted. A mirror, not a record book.
 *
 * Storage is injected (vitest here is pure-logic only — no jsdom); pages pass
 * window.localStorage.
 */

import { PERSONAL_BEST_KEY_PREFIX } from "./constants";

export interface BestStore {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

/** The handicap is part of the key — a `rocket` time and a `none` time are
 *  different achievements and must never overwrite each other (§8.3.1). */
export function bestKey(
  eventKey: string, challengeKey: string, difficulty: string, handicapName: string,
): string {
  return [PERSONAL_BEST_KEY_PREFIX, eventKey, challengeKey, difficulty, handicapName]
    .join(":");
}

export function readBestSeconds(store: BestStore, key: string): number | null {
  const raw = store.getItem(key);
  if (raw === null) return null;
  const value = Number(raw);
  return Number.isFinite(value) && value > 0 ? value : null;
}

export interface BestOutcome {
  improved: boolean;
  previousSeconds: number | null;
}

/** Record a finished time; keeps the faster of old and new. */
export function recordResultSeconds(
  store: BestStore, key: string, timeSeconds: number,
): BestOutcome {
  const previous = readBestSeconds(store, key);
  if (previous === null || timeSeconds < previous) {
    store.setItem(key, String(timeSeconds));
    return { improved: true, previousSeconds: previous };
  }
  return { improved: false, previousSeconds: previous };
}
