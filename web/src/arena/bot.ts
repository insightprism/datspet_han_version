/**
 * The bot (SPEC_PET_ARENA §7.3) — automatic mode as a bot on the same impulse
 * stream. Not a second code path: the log this produces is indistinguishable
 * from a recorded human's, and the event never asks. Rate comes from the
 * declared ladder (bots.json, Rev.6); jitter is seeded so a replayed race
 * containing a bot reproduces exactly (§7.4).
 */

import { BOT_JITTER_FRACTION } from "./constants";
import { BOT_RUNGS } from "./declarations";
import type { Impulse } from "./raceEngine";
import { mix32, unitInterval } from "./rng";

/**
 * Precompute the bot's whole log for one race: impulses at rung rate with
 * ±BOT_JITTER_FRACTION spacing jitter, up to `durationMs` (the event's time
 * limit — the integrator simply stops consuming once the bot finishes).
 */
export function botImpulseLog(
  rungKey: string, raceSeed: number, lane: number, durationMs: number,
): Impulse[] {
  const rate = BOT_RUNGS[rungKey];
  if (!rate || rate <= 0) return [];
  const baseIntervalMs = 1000 / rate;
  const log: Impulse[] = [];
  let at = 0;
  for (let i = 0; at <= durationMs; i++) {
    const jitter = 1 + BOT_JITTER_FRACTION
      * (2 * unitInterval(mix32(raceSeed ^ 0x0b07, lane, i)) - 1);
    at += baseIntervalMs * jitter;
    if (at > durationMs) break;
    log.push({ at, quality: 1 });
  }
  return log;
}
