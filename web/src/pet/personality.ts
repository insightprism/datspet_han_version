/**
 * PetPersonality — the runtime-consumed shape of a pet's personality
 * profile. Maps 1:1 to what datsme will store in
 * `Pet.personality_profile` (see datsme_me/docs/CONCEPT_RESIDENT_PET_v2.md
 * §6.1) so the runtime contract is identical between this showcase and
 * the datsme web app.
 *
 * The factory (datsPet) does NOT ship personality profiles — those are
 * a host concern. This file declares the shape the host populates from
 * its own data source:
 *   - In datsme proper: from `Pet.personality_profile` (per-user SQLite).
 *   - In this showcase: from a user-editable ConfigPopover panel that
 *     simulates what the datsme owner-settings UI will look like.
 *
 * Why a structured object instead of a flat scalar:
 *
 *   The first knob ambient behavior cares about is `activity_level`
 *   (chill ↔ energetic), which by itself fits in a single number. But
 *   datsme's spec calls for several more — temperament tags,
 *   stranger_warmth, active_hours, social_style — each driving a
 *   different facet of behavior. Putting them on a single object means:
 *
 *   1. Future consumers (a "stranger_warmth" reader in the visitor
 *      greeting behavior, an "active_hours" reader in the wander
 *      scheduler) can read the field they care about without the
 *      auto state machine touching code that doesn't concern it.
 *
 *   2. The personality object is what gets serialized to/from datsme's
 *      JSON column. A flat scalar would force a refactor when the
 *      second knob lands.
 *
 *   3. The showcase's ConfigPopover personality panel maps 1:1 to the
 *      datsme owner-settings UI. Same shape both sides.
 *
 * Phase 1 (this PR): only `activity_level` is consumed. The other
 * fields are declared so the type is stable and so future PRs can add
 * consumers without touching this file.
 */

/**
 * Temperament tags from datsme spec §6.1. Multi-select. Used by
 * future behaviors (animation choice on idle exit, voice tone) but
 * not yet consumed by the runtime in this showcase phase.
 */
export type TemperamentTag =
  | "playful" | "calm" | "shy" | "bold"
  | "affectionate" | "aloof" | "curious" | "lazy";

/**
 * Social style: how the pet relates to its owner physically.
 *   "lap"          — wants to be close, follows owner
 *   "independent"  — keeps its distance, does its own thing
 */
export type SocialStyle = "lap" | "independent";

export interface PetPersonality {
  /**
   * Energy level scalar driving ambient gait selection in the auto
   * state machine. The strategy declares species-default rest-exit
   * weights (e.g. quadruped: walk 0.7, run 0.3); this scalar
   * reweights those motion-animation weights without affecting
   * non-motion animations like sleep or eat.
   *
   *   0.0 → chill     (favors slower gait, fewer departures from rest)
   *   0.5 → balanced  (uses species defaults as-is)
   *   1.0 → energetic (favors faster gait, may shorten rest dwells)
   *
   * The same value drives multiple behavior facets:
   *   - Auto state machine motion-anim weight multiplier (today).
   *   - Future: rest_dwell multiplier (energetic pets nap less).
   *   - Future: chase responsiveness (energetic pets follow cursor
   *     sooner; chill pets ignore brief mouse movements).
   */
  activity_level: number;

  /**
   * Temperament tags. Pet may match multiple. Reserved for future
   * consumers — voice tone, idle-action weights — not yet read by
   * the showcase runtime. Spec §6.1.
   */
  temperament: TemperamentTag[];

  /**
   * Social style. Lap pets follow the cursor more aggressively;
   * independent pets ignore it longer. Reserved for future cursor-
   * follow tuning. Spec §6.1.
   */
  social_style: SocialStyle;

  /**
   * 0–1 scalar for how warm the pet is toward strangers vs.
   * friends. Reserved for future visitor-greeting behavior. Spec §6.1.
   */
  stranger_warmth: number;

  /**
   * Hours of the day (0–23) when the pet is more active. Empty array
   * means uniform across the day. Reserved for future schedule-aware
   * behavior. Spec §6.1.
   */
  active_hours: number[];

  /**
   * Owner's preferred rest animation. When set and the named animation
   * exists in the active manifest, the runtime uses this animation as
   * the pet's "settled" state — what plays after motion arrival, edge
   * stops, and timed-animation completions. When unset (or the named
   * animation isn't in the manifest), the runtime falls back to the
   * manifest's `runtime_role: rest` animation (typically `idle`).
   *
   * This is genuinely per-pet because some owners want a sleepy
   * companion (rests on `sleep`) while others want an alert one
   * (rests on `idle`). It's NOT a species-level fact (cats can be
   * either) and NOT a manifest-level fact (the same breed serves both
   * preferences) — it belongs on the personality profile.
   *
   * Phase 1: contract-committed; consumed by the runtime today via
   * `resolveRestAnim()` in the auto state machine.
   */
  preferred_rest_anim?: string;

  /**
   * Behavior preference table. Each entry assigns a probability to a
   * specific behavior id (registered in pet/behaviorRegistry.ts).
   * The auto state machine rolls against this table on each rest-
   * exit; whichever behavior wins the roll fires.
   *
   * Probabilities are absolute, not relative. They must sum to ≤ 1;
   * the residual is the "wildcard" slice (uniform-random behavior).
   * If the sum exceeds 1, the runtime normalizes proportionally.
   *
   * Behavior ids fall into two categories (see behaviorRegistry.ts):
   *   - DESTINATION ids (e.g. "home", "zone:thoughts") produce wander
   *     targets when their slice wins.
   *   - GATE ids (e.g. "chase_cursor") arm cursor-follow modes when
   *     their slice wins. The gate stays armed until the next rest-
   *     exit roll re-evaluates.
   *
   * Example: a pet that goes home 25% of the time, visits the
   * Thoughts and Featured sections 10% each, chases the cursor 20%
   * of the time, and does whatever it wants the remaining 35%:
   *
   *   preferences: [
   *     { id: "home",            probability: 0.25 },
   *     { id: "zone:thoughts",   probability: 0.10 },
   *     { id: "zone:featured",   probability: 0.10 },
   *     { id: "chase_cursor",    probability: 0.20 },
   *   ]
   *
   * Owner-editable via the ConfigPopover Preferences section.
   * Single-source-of-truth for "what does this pet feel like doing."
   *
   * Phase 1: contract-committed.
   */
  preferences: BehaviorPreference[];
}

/**
 * One row in the personality preference table. The runtime looks
 * up `id` in `behaviorRegistry.ts` to dispatch; `probability` is the
 * absolute slice of the 0-1 roll space this behavior claims.
 */
export interface BehaviorPreference {
  id: string;
  probability: number;
}

/**
 * Default personality used when the host hasn't supplied one. Neutral
 * everywhere — cat behaves to its species defaults with no owner-
 * imposed bias. The showcase ConfigPopover starts here and lets the
 * viewer push knobs in either direction.
 */
export const DEFAULT_PERSONALITY: PetPersonality = {
  activity_level:      0.5,
  temperament:         [],
  social_style:        "independent",
  stranger_warmth:     0.5,
  active_hours:        [],
  // Unset → runtime uses manifest's runtime_role: rest. The owner can
  // override via the ConfigPopover Personality section.
  preferred_rest_anim: undefined,
  // Default behavior preferences. Adds up to 0.65 of probability mass;
  // residual 0.35 is the wildcard slice (the pet does its own thing).
  // Owners can re-balance any row via the ConfigPopover Preferences
  // table. Zone-specific entries (`zone:thoughts` etc.) reference the
  // [data-zone] ids in the page chrome — if the page layout changes,
  // unused preferences are dropped gracefully (forgiveness pattern).
  preferences: [
    { id: "home",          probability: 0.25 },
    { id: "zone:thoughts", probability: 0.10 },
    { id: "zone:featured", probability: 0.10 },
    { id: "chase_cursor",  probability: 0.20 },
  ],
};
