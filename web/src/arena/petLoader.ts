/**
 * Load a pet for racing: manifest → athletics stats (identity nudges decoded
 * from the pet id — §3.4 Rev.7) → sheet fetch → engine registration. The same
 * fetch pattern PetStage uses (blob: URL, ownership passes to the engine;
 * removePet revokes it).
 */

import {
  animsFromManifest, deriveRows, ensurePet,
  type PetSheet,
} from "@/pet";
import {
  petManifestUrl, petSheetUrl, roomPetManifestUrl, roomPetSheetUrl,
} from "@/lib/api";
import {
  deriveIdentityNudges, resolveAthletics, type AthleticsManifest,
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
  // A room lane fetches through the room-scoped routes (SPEC_PET_ARENA_ROOMS
  // §4.3): membership is the capability — the pets of the OTHER players are
  // not the caller's to fetch through the owner routes.
  const manifestUrl = config.roomCode
    ? roomPetManifestUrl(config.roomCode, config.petId)
    : petManifestUrl(config.petId);
  const sheetUrl = config.roomCode
    ? roomPetSheetUrl(config.roomCode, config.petId)
    : petSheetUrl(config.petId);
  const manifestRes = await fetch(manifestUrl);
  if (!manifestRes.ok) throw new Error(`manifest fetch failed: ${manifestRes.status}`);
  const manifest: AthleticsManifest = await manifestRes.json();

  const sheetRes = await fetch(sheetUrl);
  if (!sheetRes.ok) throw new Error(`sheet fetch failed: ${sheetRes.status}`);
  const bytes = await sheetRes.arrayBuffer();

  // Identity decodes from the PET id, not the lane's storeId (§3.4) — the
  // same pet racing its own twin is the same athlete in both lanes.
  const nudges = await deriveIdentityNudges(config.petId);
  const stats = resolveAthletics(manifest, nudges);

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
