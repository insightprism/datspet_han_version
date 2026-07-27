/**
 * Where PosePlayer's frames come from — resolved as a PURE function, deliberately.
 *
 * `PosePlayer` gained a second input shape when the Motion Lab needed to play a packed
 * sheet that has no saved pet behind it (SPEC_MATTE_REPAIR_ORDER §12.4 /
 * SPEC_MOTION_LAB_DESIGN_PARITY §2.5). `PoseGallery` is a shipped consumer on the
 * user-visible result panel, so that widening had to leave its `petId` path byte-identical
 * — and "byte-identical" is a claim worth a test rather than a comment.
 *
 * It lives in its own `.ts` module rather than inside `PosePlayer.tsx` because the
 * frontend's vitest has no jsdom and no React (see vitest.config.ts): logic worth
 * guarding has to be somewhere the harness can reach. Same discipline as `labDraw.ts`.
 */
import { petManifestUrl, petSheetUrl } from "@/lib/api";

export type PoseSource = { petId: string } | { sheetUrl: string; manifestUrl: string };

export function posePlayerUrls(src: PoseSource): { manifest: string; sheet: string } {
  return "petId" in src
    ? { manifest: petManifestUrl(src.petId), sheet: petSheetUrl(src.petId) }
    : { manifest: src.manifestUrl, sheet: src.sheetUrl };
}
