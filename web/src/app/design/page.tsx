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
 * A SERVER-side redirect, not a client one: a launched user arrives with a cookie and a
 * `?from=datsme` marker, and bouncing them through a rendered page first would flash a
 * screen whose only purpose is to leave. The launch cookie is host-scoped, not
 * path-scoped, so it survives the hop (deploy spec §C.5).
 *
 * If themed worlds come back, the landing goes here. That is why this stays a route
 * rather than becoming a rewrite in next.config: the seam is worth keeping visible.
 */
export default function DesignPage() {
  redirect("/design/general");
}
