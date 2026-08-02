/**
 * Deterministic randomness for the arena — the reason a replayed impulse log
 * reproduces a race exactly (SPEC_PET_ARENA §7.4) and two hot-seat players
 * get the identical question sequence (§8.3). Never Math.random in game logic.
 */

/**
 * 32-bit hash of (seed, lane, index) — the race roll's and the bot's only
 * randomness source. Mirrored BIT-FOR-BIT by `_mix32` in
 * pet_factory/athletics/__init__.py (masked multiplies there, Math.imul here);
 * the shared race-vector fixture fails if the two ever drift.
 */
export function mix32(a: number, b: number, c: number): number {
  let x = ((a >>> 0)
    ^ Math.imul(b >>> 0, 0x85ebca6b)
    ^ Math.imul(c >>> 0, 0xc2b2ae35)) >>> 0;
  x = (x ^ (x >>> 16)) >>> 0;
  x = Math.imul(x, 0x7feb352d) >>> 0;
  x = (x ^ (x >>> 15)) >>> 0;
  x = Math.imul(x, 0x846ca68b) >>> 0;
  x = (x ^ (x >>> 16)) >>> 0;
  return x;
}

/** Map a mix32 output onto [0, 1). */
export function unitInterval(x: number): number {
  return x / 4294967296;
}

/**
 * Seeded PRNG for question sequences (§8.2): a challenge is a seeded generator,
 * so one race seed → one identical sequence for every entrant.
 */
export function mulberry32(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Mint a race seed (setup time only — never inside game logic). */
export function mintRaceSeed(): number {
  const buf = new Uint32Array(1);
  crypto.getRandomValues(buf);
  return buf[0];
}
