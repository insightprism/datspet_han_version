/**
 * Shared shapes for the arena game flow (setup → race → results). Pure types —
 * the state machine itself lives in ArenaGame.tsx; the integrator contract in
 * raceEngine.ts.
 */

import type { PetAssetUrls } from "@/lib/api";
import type { AthleticsManifest, AthleticsStats } from "./athletics";

/** A pet as the setup screen knows it: manifest fetched, stats resolved with
 *  the id-decoded identity nudges (§3.4 Rev.7) — the bars on the pick cards
 *  are the REAL numbers the race will use. */
export interface ArenaPetInfo {
  id: string;
  /** Composed display: "«pet_name» «animal»", or the breed name when unnamed. */
  label: string;
  /** The breed display name — the surname source for composition. */
  display_name: string;
  /** The owner's first name for the pet (null = unnamed). */
  pet_name: string | null;
  manifest: AthleticsManifest;
  poses: string[];
  previewStats: AthleticsStats;
}

export type RacerKind = "human" | "bot" | "ghost";

/** One lane as configured at setup. */
export interface RacerConfig {
  petId: string;
  /** The engine-store key for THIS lane — distinct per lane (`petId#lane0`…)
   *  so the same pet can fill two lanes (hot-seat twins, a bot borrowing the
   *  only qualified pet) without the two lanes fighting over one PetState. */
  storeId: string;
  label: string;
  kind: RacerKind;
  handicapName: string;
  /** bot lanes only: the rung from bots.json. */
  botRung?: string;
  /** WHERE this lane's sheet + manifest come from — minted by the caller in
   *  api.ts (owner routes for your own pets, room routes for a rival's), so
   *  the loader never branches on a lane's provenance. */
  assets: PetAssetUrls;
}

/** One lane ready to race: sheet fetched (roll derived from its bytes — §5.2),
 *  pet registered in the engine store, racing pose resolved. */
export interface LoadedRacer extends RacerConfig {
  stats: AthleticsStats;
  handicap: number;
  racingPose: string;
}

/** A human run's answer tally (owner ask, 2026-08-02): rights are the impulse
 *  log's length by definition (§7.1 — a wrong emits nothing), wrongs are
 *  counted by the screen. Results show "✓ 18 · ✗ 4 · 82% right".
 *  Rev.11: crashes (wrong answers AT a hurdle gate) ride along, and three of
 *  them set `disqualified` — a screen outcome, never encoded in the log. */
export interface RunAccuracy {
  right: number;
  wrong: number;
  crashes?: number;
  disqualified?: boolean;
}
