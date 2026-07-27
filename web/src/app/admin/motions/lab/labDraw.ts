/**
 * labDraw — what a Motion Lab draw puts on the wire, as pure functions
 * (SPEC_MOTION_LAB_DESIGN_PARITY §2.3/§2.6, I10/I12).
 *
 * No React, no fetch, no DOM — so `labDraw.test.ts` runs under the frontend's
 * deliberately browser-free vitest, which includes `.test.ts` only and has no jsdom
 * (see vitest.config.ts). That is the whole reason this file exists apart from the page:
 * D6's frontend half — "a base draw must ALWAYS say base: true" — has no server-side
 * guard. Nothing in webui/ can tell a base draw that forgot the flag from a genuine
 * anchor, and after §2.6 the flag selects the prompt SENTENCE, so forgetting it draws
 * the pale one. Here it is one function with one assertion on it.
 *
 * The mirror rule (I13): a design is only ever attached to a base redraw of a
 * reference. The server 400s otherwise; this keeps the UI from getting there.
 */
import type { LabDesign, LabJob, LabReference, LabStillOptions } from "@/lib/api";

/**
 * The still a base draw is redrawn FROM. One slot, two kinds — never one field with
 * two producers (I12): an uploaded photo carries the captioner's triage verdict, an
 * applied design carries the composed string that was spent on it, and each card
 * renders only its own. A Lab still's asset_id IS a usable reference_id, which is what
 * lets "Apply design" promote its own output to the next draw's source.
 */
export type LabSource =
  | { kind: "upload"; reference_id: string; url: string; upload: LabReference }
  | {
      kind: "design"; reference_id: string; url: string;
      /** The ~240-char composed string this redraw spent. Display only — never re-sent. */
      description: string;
      /** `display_name.lower()` — what a build's reference record now says (see poseSubject). */
      subject: string;
    };

/**
 * The subject every pose anchor and loop prompt draws from — i.e. what a build's
 * `ref["description"]` would say at step 3.
 *
 * THE BUG THIS FIXES (2026-07-27). The Lab used to pass the TYPED noun here, so a
 * designed white snow leopard drew tan anchors. That is not what a build does: step 2
 * saves its redraw with `description = display_name.lower()`, and `/api/generate` reads
 * exactly that field, so a designed pet's anchors and loops are drawn from
 * "white snow leopard". §0.3's table always said `ref["description"]` — it was read as
 * "the typed phrase", and the two are only the same until someone designs something.
 *
 * What rides along is the COLOUR, because `display_name` is `{color} {species}`. The body
 * shape, accessories, free text and the recolor clause do NOT — they were spent on the
 * redraw and a build never sees them again. That asymmetry is the build's, not ours.
 */
export function poseSubject(source: LabSource | null, animal: string): string {
  return source?.kind === "design" ? source.subject : animal.trim();
}

/**
 * The options for a BASE still draw — the shared still every clause-less pose animates.
 *
 * `base: true` unconditionally: with a reference this is step 2's img2img redraw, and
 * without one it is step 1's txt2img archetype draw. Both are base draws; only the
 * second used to arrive unflagged, back when the flag did nothing on that path.
 *
 * Takes the reference ID rather than the `LabSource` itself: "Apply design" redraws the
 * base still that is on screen, which is a valid reference (its asset_id) before it has
 * ever become the `source`.
 */
export function baseDrawOptions(
  referenceId: string | null,
  strength: number,
  design?: LabDesign,
): LabStillOptions {
  if (!referenceId) return { base: true };
  // A design rides ONLY on a redraw of a reference (I13) — the composed string is spent
  // on the img2img and nowhere else, exactly as a build spends it.
  return { base: true, reference_id: referenceId, strength, ...(design ? { design } : {}) };
}

/**
 * The packed tile's two URLs, or null when there is nothing packed to show.
 *
 * F4 publishes the loop FIRST and the packed sheet ~6 s later (SPEC_MATTE_REPAIR_ORDER
 * §12.2), and a pack can fail on a job whose loop is perfectly good — a busy GPU_LOCK, a
 * dead cutout session. Both cases land here as `null`, which is the property that matters:
 * a packer failure costs you the packed tile and NOTHING else. The raw loop cost ~40 s of
 * GPU and is the result you still have when the packer is the broken thing.
 *
 * Both URLs or neither: PosePlayer reads frames from the sheet and fps/columns from the
 * manifest, so half a pair is a blank tile with no error to explain it.
 */
export function packedTile(job: Pick<LabJob, "packed_url" | "packed_manifest_url">,
                           absolute: (url: string) => string) {
  return job.packed_url && job.packed_manifest_url
    ? { sheetUrl: absolute(job.packed_url), manifestUrl: absolute(job.packed_manifest_url) }
    : null;
}
