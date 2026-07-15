import { redirect } from "next/navigation";

/**
 * /design — the DPP launch deep-link target. `webui/datsme_integration.py` sends a
 * "Design a pet" launch here (`return=/design`, pinned by
 * `webui/tests/test_front_door.py`), so this route MUST keep answering: the deployed
 * launch URL and the host's stored config both name it, and neither is ours to edit.
 *
 * It used to render <DesignLanding> — a tile per "world" (Cat World, Dog World,
 * General). The themed pages are gone (SPEC_PET_DESIGNER_FLOW §11), which left the
 * landing with exactly one tile, and a chooser with one choice is a click that teaches
 * nothing. So it redirects.
 *
 * ── THIS FILE ONLY MATTERS IN DEV ──
 *
 * An earlier version of this comment claimed it "deliberately chose a SERVER-side
 * redirect, not a client one" because a rendered hop "would flash a screen whose only
 * purpose is to leave." That was true under `next dev` and FALSE in prod — the only
 * place it matters — and the export proves it: `out/design.html` IS emitted (6 KB), but
 * its body is empty and the hop rides a `NEXT_REDIRECT;replace;/design/general;307`
 * payload in the RSC flight data, with no meta-refresh. nginx would serve that as a
 * plain 200: a blank page that redirects in JS, after a paint. Exactly the flash the
 * comment congratulated itself on avoiding.
 *
 * So prod's redirect lives in nginx now — `location = /design { return 307 …; }` in
 * `deploy/nginx-default.conf`. An exact-match location beats the static `try_files`
 * prefix, so design.html is never served and the 307 is real, server-side, and works
 * with JS off.
 *
 * This route is the DEV half of the same behaviour (`next dev` has no nginx in front
 * of it, and serves this redirect server-side for real). Both halves must move
 * together: if the target ever changes, change it HERE and in the nginx conf, or dev
 * and prod will disagree about where /design goes — which is the failure mode that
 * hid this one.
 */
export default function DesignPage() {
  redirect("/design/general");
}
