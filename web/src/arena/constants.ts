/**
 * Named values for the arena (no literal reaches a call site — CLAUDE.md).
 * Game-balance numbers live in pet_factory/athletics/*.json (§8.4); these are
 * the presentation/input knobs that belong to the browser.
 */

/** §7.2 — a wrong answer costs TIME, never distance: brief input lockout,
 *  no impulse, and the pet never moves backwards. */
export const WRONG_ANSWER_LOCKOUT_MS = 600;

/** Server-less countdown before the gun (rooms will broadcast theirs). */
export const COUNTDOWN_SECONDS = 3;

/** Bot impulse spacing jitter, as a fraction of the rung interval — texture
 *  so the bot does not answer like a metronome; seeded, so replays hold. */
export const BOT_JITTER_FRACTION = 0.25;

/** §7.6 — sprite frame rate tracks velocity. Rate factor = velocity over
 *  (stride_base_m × 1 answer/s), clamped so a stalled pet still breathes and
 *  a sprinting one does not strobe. */
export const SPRITE_RATE_WINDOW_MS = 2000;
export const SPRITE_RATE_MIN = 0.35;
export const SPRITE_RATE_MAX = 2.5;

/** Track presentation. */
export const ARENA_PET_DISPLAY_SIZE_PX = 96;
export const LANE_HEIGHT_PX = 116;
export const TRACK_EDGE_PADDING_PX = 16;

/** Recap playback speed (§8.8 — "watch how you won"). */
export const RECAP_PLAYBACK_SPEED = 2;

/** localStorage namespace for device-local personal bests (§8.8). */
export const PERSONAL_BEST_KEY_PREFIX = "datspet.arena.pb.v1";

/** Stats are 0..1 floats in the engine (§2.5); children read them as 0..100.
 *  A display scale, never a game value — the stride formula sees the floats. */
export const STAT_DISPLAY_MAX = 100;
