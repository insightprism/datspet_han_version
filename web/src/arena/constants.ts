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

/** Distance markings on the track (owner ask: "he can be on the 40"): the
 *  smallest of these round steps that keeps a course at no more than
 *  TRACK_MARK_MAX_COUNT marks. */
export const TRACK_MARK_STEPS_M = [5, 10, 25, 50, 100];
export const TRACK_MARK_MAX_COUNT = 5;

/** Recap playback speed (§8.8 — "watch how you won"). */
export const RECAP_PLAYBACK_SPEED = 2;

/** localStorage namespace for device-local personal bests (§8.8). */
export const PERSONAL_BEST_KEY_PREFIX = "datspet.arena.pb.v1";

/** Stats are 0..1 floats in the engine (§2.5); children read them as 0..100.
 *  A display scale, never a game value — the stride formula sees the floats. */
export const STAT_DISPLAY_MAX = 100;

/** §6.6 — the rest between jump attempts: buzzer, leap, measurement, walk
 *  back. Part of the DECLARED schedule (window i opens at i × (window+rest)),
 *  so changing it changes where recorded logs land — a game value, not UI
 *  polish. */
export const ATTEMPT_REST_S = 6;

/** Jump-lane presentation: how many metres the landing pit represents, and
 *  how long the leap moment lingers before the next run-up. */
export const JUMP_PIT_DISPLAY_MAX_M = 16;
export const HURDLE_HOP_WINDOW_M = 2.5;
