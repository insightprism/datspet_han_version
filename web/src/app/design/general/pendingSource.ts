/**
 * What the user has lined up in step 1 but not yet made their base
 * (SPEC_PET_DESIGNER_FLOW §3.2, SPEC_STEP1_SOURCE_RAIL §1.12).
 *
 * Shared by <Designer> (which owns it — <Step> unmounts its children on collapse) and
 * <SourceRail> (which marks the door it came from). It lives in its own module because
 * those two are peers: putting it in either would make the other import from a sibling
 * for a type neither owns.
 *
 * NOTE the upload variant carries no `strength`. It used to — step 1 offered
 * faithful/balanced/sprite — and that choice could not survive to the finished pet:
 * step 2's redraw is MANDATORY (§4.2) and runs at its own strength, which `compose_design`
 * forces to 0.9 whenever the design fights the source image (app.py:296). At 0.9 the
 * redraw wins outright, so a "faithful" base was overwritten before it was ever animated.
 * Uploads are now redrawn at the server's own `UPLOAD_REDRAW_STRENGTH` (app.py:155) and the
 * client sends nothing — one owner for a value the user was never really choosing.
 */
export type PendingSource =
  | { kind: "catalog"; animal: string; breed: string; label: string }
  | { kind: "upload"; file: File; url: string }
  | { kind: "typed"; animal: string };
