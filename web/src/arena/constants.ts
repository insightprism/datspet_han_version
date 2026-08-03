/**
 * Named values for the arena (no literal reaches a call site — CLAUDE.md).
 * Game-balance numbers live in pet_factory/athletics/*.json (§8.4); these are
 * the presentation/input knobs that belong to the browser.
 */

/** §7.2 — a wrong answer costs TIME, never distance: brief input lockout,
 *  no impulse, and the pet never moves backwards. */
export const WRONG_ANSWER_LOCKOUT_MS = 600;

/** §8.5 (Rev.10) — a missed CHOICE freezes longer than a typo: ~2 misses per
 *  guessed hit ≈ 4 s per answer vs a knowing child's ~1 s, so mashing runs at
 *  a quarter speed. Guard-pinned to ≥ 2× the typed lockout. */
export const WRONG_CHOICE_LOCKOUT_MS = 1500;

/** Server-less countdown before the gun (rooms will broadcast theirs). */
export const COUNTDOWN_SECONDS = 3;

/** Bot impulse spacing jitter, as a fraction of the rung interval — texture
 *  so the bot does not answer like a metronome; seeded, so replays hold. */
export const BOT_JITTER_FRACTION = 0.25;

/** §7.6 — sprite frame rate tracks the APPARENT velocity (the camera-layer
 *  chase speed), clamped so a stalled pet still trots in place and a
 *  sprinting one does not strobe. */
export const SPRITE_RATE_WINDOW_MS = 2000;
export const SPRITE_RATE_MIN = 0.35;
export const SPRITE_RATE_MAX = 2.5;

/** The runner-game camera (owner design, 2026-08-02 — "think like a game
 *  developer"): each lane is a VIEWPORT onto a fixed window of track; the
 *  runner anchors part-way across and the world scrolls past. A pixel means
 *  a fixed slice of course, so proportions hold on every course length — a
 *  64px runner is ~2 real metres, a hurdle is a hurdle. */
export const ARENA_PET_DISPLAY_SIZE_PX = 64;
export const LANE_HEIGHT_PX = 88;
export const TRACK_EDGE_PADDING_PX = 16;
export const VIEWPORT_TRACK_METERS = 28;
export const CAMERA_ANCHOR_FRACTION = 0.35;
/** Ground marks every N metres — rolling texture for the scroll. */
export const TRACK_SCROLL_MARK_STEP_M = 10;

/** The render chases the simulation (owner: "the animal is always moving, or
 *  appears to move"): drawn position approaches the true integrator distance
 *  exponentially with this time constant, so each answer is a surge that
 *  plays out smoothly and a lockout reads as deceleration — never teleports.
 *  RENDER-ONLY: the referee still scores the impulse log (§7.4).
 *
 *  Tuned by instrument (2026-08-02): at τ=500 a human answering every ~1.3 s
 *  left the runner motionless HALF of all frames (glide done in ~1.2 s). τ=800
 *  plus the creep floor below keeps motion continuous at human pace. */
export const DISPLAY_CHASE_TAU_MS = 800;
/** While ANY distance is still owed, the runner never moves slower than this —
 *  the roll between surges. It still stops dead when fully caught up (a
 *  parked hurdle gate must read as parked). */
export const DISPLAY_MIN_CREEP_M_S = 0.35;
/** …and never faster than this (Rev.11, "move consistently"): the chase is
 *  velocity-BANDED, so a burst of answers reads as steady fast rolling, not a
 *  rubber-band spike. The band converges — max is well above any sustainable
 *  earning rate. */
export const DISPLAY_MAX_CHASE_M_S = 3.2;
/** Apparent m/s that maps to 1× leg speed. */
export const APPARENT_SPEED_BASE_M_S = 2.0;

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

/** The hurdle obstacle, in SCREEN space (owner design, 2026-08-02): the jump
 *  pose triggers by collision — a hidden trigger line a few px in front of
 *  the obstacle; the pose holds while the obstacle is under the runner and
 *  releases when the tail clears it. Screen-space, not metre-windows, so the
 *  leap can never drift from where the obstacle is drawn. Drawn like a real
 *  athletics hurdle (Rev.11): white top board on two legs, hip-height
 *  against the runner. */
export const HURDLE_HEIGHT_PX = 28;
export const HURDLE_WIDTH_PX = 20;
export const HURDLE_TRIGGER_LEAD_PX = 6;

/** Rev.11 (owner rule): a wrong answer while parked at a gate IS hitting the
 *  hurdle. The pet tumbles for CRASH_FX_MS; the third crash disqualifies. */
export const HURDLE_CRASHES_TO_DQ = 3;
export const CRASH_FX_MS = 1400;

/** The obstacle is SOLID (owner: "the hurdle is just an image with no
 *  awareness of the animal"): while crossing, the sprite rises over the bar
 *  on a real parabolic arc — higher than the hurdle, so the body visibly
 *  clears it. Parked at the gate the runner stays grounded. */
export const HURDLE_JUMP_ARC_PX = 36;

/** One ground line for animal and obstacle (owner: "the legs should touch
 *  the same level as the hurdle"). Sprite frames carry transparent padding
 *  BELOW the paws (the factory centers the art in its cell), so the sprite
 *  cell hangs this far below the lane floor to put the visible feet on the
 *  hurdle's baseline. Lane overflow clips the transparent excess.
 *  Measured by canvas alpha-scan (2026-08-02, leopard run frames): 14px of
 *  pad under the paws in the 64px cell → paws rest on TRACK_GROUND_Y_PX. */
export const SPRITE_BASELINE_OFFSET_PX = -12;
export const TRACK_GROUND_Y_PX = 2;

/** SPEC_PET_ARENA_ROOMS §3.3 — one impulse batch per this window: each
 *  impulse carries its own race-clock timestamp, so batching costs no
 *  fidelity, and a fast player stays ~5 requests/s. Client-owned: the
 *  server clamps by time window and never needs the cadence. */
export const IMPULSE_BATCH_MS = 200;

/** Rev.9 — the JUMP color: what the challenge panel wears while the lane is
 *  parked at a hurdle and the question is one rung harder. Amber, distinct
 *  from the running green, readable on the dark card. */
export const HURDLE_JUMP_ACCENT = "#f59e0b";
export const HURDLE_JUMP_ACCENT_BG = "rgba(245,158,11,0.12)";
