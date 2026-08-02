/**
 * Shared shapes for the arena game flow (setup → race → results). Pure types —
 * the state machine itself lives in ArenaGame.tsx; the integrator contract in
 * raceEngine.ts.
 */

import type { AthleticsManifest, AthleticsStats } from "./athletics";

/** A pet as the setup screen knows it: manifest fetched, stats previewed
 *  WITHOUT the sheet roll (±0.08 — invisible on a stat bar; the race itself
 *  uses the full sheet-rolled stats from loadRacer). */
export interface ArenaPetInfo {
  id: string;
  label: string;
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
}

/** One lane ready to race: sheet fetched (roll derived from its bytes — §5.2),
 *  pet registered in the engine store, racing pose resolved. */
export interface LoadedRacer extends RacerConfig {
  stats: AthleticsStats;
  handicap: number;
  racingPose: string;
}
