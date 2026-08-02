/**
 * Load a pet for racing: manifest + sheet bytes → athletics stats (sheet roll
 * included — §5.2) → engine registration. The same fetch pattern PetStage
 * uses (blob: URL, ownership passes to the engine; removePet revokes it),
 * plus one extra read of the bytes for the roll hash — the §5.2 design point
 * is that the arena already had to fetch these bytes to render the pet.
 */

import {
  animsFromManifest, deriveRows, ensurePet,
  type PetSheet,
} from "@/pet";
import { petManifestUrl, petSheetUrl } from "@/lib/api";
import {
  deriveRollFromSheet, resolveAthletics, type AthleticsManifest,
} from "./athletics";
import { HANDICAP_LADDER, type ArenaEventDecl } from "./declarations";
import type { LoadedRacer, RacerConfig } from "./gameTypes";

/** The pose the lane animates with: the first of the event's preferred poses
 *  the pet actually owns (§7.6), falling back to anything it has. */
export function resolveRacingPose(
  event: ArenaEventDecl, poses: string[],
): string {
  return event.preferred_poses.find((p) => poses.includes(p))
    ?? poses[0] ?? "walk";
}

export async function loadRacer(
  config: RacerConfig, event: ArenaEventDecl,
): Promise<LoadedRacer> {
  const manifestRes = await fetch(petManifestUrl(config.petId));
  if (!manifestRes.ok) throw new Error(`manifest fetch failed: ${manifestRes.status}`);
  const manifest: AthleticsManifest = await manifestRes.json();

  const sheetRes = await fetch(petSheetUrl(config.petId));
  if (!sheetRes.ok) throw new Error(`sheet fetch failed: ${sheetRes.status}`);
  const bytes = await sheetRes.arrayBuffer();

  const roll = await deriveRollFromSheet(bytes);
  const stats = resolveAthletics(manifest, roll);

  const blobUrl = URL.createObjectURL(new Blob([bytes], { type: "image/png" }));
  const sheet: PetSheet = {
    sheetUrl: blobUrl,
    sourceFrame: manifest.frame_width ?? 256,
    sheetCols: manifest.columns ?? 8,
    sheetRows: deriveRows(manifest),
    anims: animsFromManifest(manifest),
    viewKind: manifest.view_kind,
    nativeFacing: manifest.native_facing,
    mirroringPolicy: manifest.mirroring_policy,
    movementClass: manifest.movement_class,
  };
  ensurePet(config.storeId, { sheet });

  return {
    ...config,
    stats,
    // The ladder is CLOSED (§8.3.1): an unknown name gets no boost rather
    // than an arbitrary number.
    handicap: HANDICAP_LADDER[config.handicapName] ?? 1.0,
    racingPose: resolveRacingPose(event, stats.poses),
  };
}
