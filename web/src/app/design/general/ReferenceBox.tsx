"use client";

/**
 * <ReferenceBox> — the box that holds your base animal (SPEC_PET_DESIGNER_FLOW §3,
 * SPEC_STEP1_SOURCE_RAIL §1.4).
 *
 * It is BOTH the display and one of the ways to fill it. That is the author's
 * original framing — "have a box that will hold the reference picture; the user can
 * click on this box and will be given a choice for getting the reference picture" —
 * and it deletes a whole section of UI: the standalone "— or —" dropzone existed only
 * because the box couldn't accept a photo. A box you can drop onto needs no second box
 * to drop onto.
 *
 * The animal's NAME is not asked for HERE, in the box — but the upload DOOR asks for it,
 * in its own "what animal is it?" field (SPEC_UPLOAD_LIKENESS §2.1, decision 3a). An
 * earlier design put no field on the upload door and had it borrow the typed door's field
 * across the page, on the theory that "type any animal" and "what animal is this photo of?"
 * were the same question wearing two hats. Evidence said otherwise: a real uploader read
 * the two doors as unrelated, never filled the far field, and their photo redrew against
 * the generic "pet". They are different questions — one names an animal to draw from
 * nothing, the other labels a photo you already have — so each door owns its own field.
 *
 * Clicking opens the GALLERY, not a menu — click a picture, get more pictures. The rail
 * beside it names all three sources, so the caption here keeps only the one affordance
 * nothing else on the page reveals: drop.
 *
 * Dropping does NOT commit. The photo lands as a PREVIEW — the box shows your raw file
 * via an object URL, the caption reads "not drawn yet — press draw", and the strength
 * control appears in the rail. It becomes the base only when Draw is pressed.
 *
 * (An earlier version of this comment claimed dropping auto-commits, "so a second confirm
 * would be ceremony". That was never what the code did, and §3.2 is why: an upload is the
 * one door with a DECISION attached — faithful ↔ sprite — so drawing on drop would burn a
 * ~10 s render at whatever default happened to be set. The confirm is not ceremony; it is
 * the user answering the question the slider asks.)
 */
import { useCallback, useEffect, useState } from "react";
import { referenceImageUrl, type PetReference } from "@/lib/api";

interface Props {
  reference: PetReference | null;
  busy: boolean;
  /**
   * A dropped photo is being decoded and downscaled (SPEC_STEP1_SOURCE_RAIL §1.10).
   * Separate from `busy` on purpose: `busy` is a ~10 s GPU render and this is ~200 ms of
   * local work, and telling the user "drawing…" while nothing is being drawn would be a
   * lie the very next state contradicts.
   */
  preparing: boolean;
  onPhoto: (file: File) => void;
  /** Click the box to choose where the base animal comes from. */
  onOpen: () => void;
  /**
   * What the user has lined up but not yet committed — the curated base.png they just
   * clicked, or the raw photo they just chose. Showing it BEFORE the commit is what
   * makes "press the button" a decision rather than a leap: you can see what you are
   * about to make your base. For a typed animal there is nothing to show yet (it does
   * not exist until it is drawn), which is itself honest.
   */
  pendingUrl: string | null;
  pendingLabel: string | null;
  /** Locked = the user has committed this base and step 2 is open. */
  locked: boolean;
}

const SIDE = 200;

export default function ReferenceBox({
  reference, busy, preparing, onPhoto, onOpen, pendingUrl, pendingLabel, locked,
}: Props) {
  const [dragover, setDragover] = useState(false);
  // Hover reveals the drop hint INSIDE the box (below). It is not a caption line: a line
  // that appears under the box on hover would shove the commit button down every time the
  // pointer crossed the picture.
  const [hover, setHover] = useState(false);

  const accept = useCallback((f: File | null | undefined) => {
    if (f) onPhoto(f);
  }, [onPhoto]);

  // Paste an image from anywhere on the page. Copied from /make (make/page.tsx:34-44)
  // rather than extracted to a shared hook: extracting would mean editing live /make,
  // and "three instances before consolidating" says wait (CLAUDE.md).
  useEffect(() => {
    function onPaste(e: ClipboardEvent) {
      const item = Array.from(e.clipboardData?.items ?? [])
        .find((i) => i.type.startsWith("image/"));
      accept(item?.getAsFile());
    }
    document.addEventListener("paste", onPaste);
    return () => document.removeEventListener("paste", onPaste);
  }, [accept]);

  // The pending pick wins: it is what pressing the button will make the base.
  const shownUrl = pendingUrl ?? (reference ? referenceImageUrl(reference.reference_id) : null);
  const shownLabel = pendingLabel ?? reference?.display_name ?? "";
  const isPending = pendingUrl != null;

  return (
    <figure className="m-0 flex flex-col items-center gap-2">
      <div
        role="button"
        tabIndex={0}
        aria-label="Your base animal — click to browse the gallery"
        className="relative flex cursor-pointer items-center justify-center overflow-hidden rounded-xl border transition"
        onMouseEnter={() => setHover(true)}
        onMouseLeave={() => setHover(false)}
        style={{
          width: SIDE, height: SIDE,
          background: "#151515",
          // Dashed while nothing is locked — the box is asking, not answering.
          borderStyle: locked ? "solid" : "dashed",
          borderColor: dragover ? "var(--green)"
            : locked ? "var(--green)"
            : isPending ? "var(--accent)" : "var(--line)",
        }}
        onClick={onOpen}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") onOpen(); }}
        onDragOver={(e) => { e.preventDefault(); setDragover(true); }}
        onDragLeave={() => setDragover(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragover(false);
          accept(e.dataTransfer.files?.[0]);
        }}
      >
        {shownUrl ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={shownUrl}
            alt={shownLabel}
            style={{
              width: SIDE - 24, height: SIDE - 24, objectFit: "contain",
              // Dim while a replacement is on the way: a crisp picture under a
              // "drawing…" caption reads as the result, and it isn't.
              opacity: busy ? 0.25 : 1,
              transition: "opacity 0.15s",
            }}
          />
        ) : (
          <span className="mono px-4 text-center text-xs" style={{ color: "var(--faint)" }}>
            {busy ? "drawing…" : "click to choose a base animal"}
          </span>
        )}

        {/* The drop affordance, revealed on hover instead of stated permanently. It used
            to be a caption line under the box, which spent a line of the layout on a
            capability most users never reach for — and put "drop a photo here" one line
            below "Tabby", where it read as a description of the tabby.

            `pointer-events-none` is load-bearing: an element under the cursor that
            accepts pointer events fires dragleave as the file passes over it, and the
            drop would land on nothing. */}
        {(hover || dragover) && !locked && !busy && !preparing && (
          <span
            className="mono pointer-events-none absolute inset-x-0 bottom-0 py-1.5 text-center text-xs"
            style={{ background: "rgba(0,0,0,0.72)", color: dragover ? "var(--green)" : "var(--muted)" }}
          >
            {dragover ? "drop to use it" : "drop your own image"}
          </span>
        )}
      </div>

      {/**
       * THE CAPTION SPEAKS ONLY WHEN IT HAS NEWS (SPEC_STEP1_SOURCE_RAIL §1.9).
       *
       * It used to be two permanent lines — the animal's name, and "drop a photo here".
       * Both were noise in the steady state: you can see it is a tabby, and the drop
       * affordance is now the hover overlay above. Two lines of chrome under a finished
       * picture also pushed the commit button a line and a half below the last control in
       * the rail, which is what made the two columns look unrelated.
       *
       * The three states that remain all EXPLAIN something the picture cannot:
       *   drawing…                   — a ~10 s render is in flight (the image is dimmed,
       *                                but dimming alone does not say "wait")
       *   not drawn yet — press draw — why there is no commit button right now (§1.7).
       *                                A missing button with no explanation is exactly
       *                                what that rule exists to avoid
       *   🔒 locked in               — this base is settled and step 2 is open (§3.7)
       *
       * A drawn, unlocked animal says nothing at all, which is the common case.
       */}
      {(busy || preparing || locked || isPending) && (
        <figcaption className="mono text-center text-xs"
                    style={{ color: locked ? "var(--green)" : "var(--faint)" }}>
          {preparing ? "preparing your photo…"
           : busy ? "drawing…"
           : locked ? "🔒 locked in"
           : "not drawn yet — press draw"}
        </figcaption>
      )}
    </figure>
  );
}
