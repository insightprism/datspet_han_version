"use client";

/**
 * <ReferenceBox> — the box that holds your base animal (SPEC_PET_DESIGNER_FLOW §3).
 *
 * It is BOTH the display and one of the ways to fill it. That is the author's
 * original framing — "have a box that will hold the reference picture; the user can
 * click on this box and will be given a choice for getting the reference picture" —
 * and it deletes a whole section of UI: the standalone "— or —" dropzone existed only
 * because the box couldn't accept a photo. A box you can drop onto needs no second box
 * to drop onto.
 *
 * The animal's NAME is not asked for here. The left-hand "or type any animal" field
 * already asks exactly that question, so a photo dropped here simply borrows it as the
 * redraw hint. Two fields asking "which animal?" — one labelled "type any animal" and
 * one labelled "what animal is it?" — were the same question wearing two hats, and
 * step 1 takes ONE input: which animal (§0.1).
 *
 * Dropping auto-commits, unlike the typed door's explicit "Draw it". Dropping a photo
 * IS the explicit act — nobody drags a file by accident — so a second confirm would be
 * ceremony. The ~10 s price is on the box before you drop (§3.3's commit rule).
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { referenceImageUrl, type PetReference } from "@/lib/api";

interface Props {
  reference: PetReference | null;
  busy: boolean;
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
  reference, busy, onPhoto, onOpen, pendingUrl, pendingLabel, locked,
}: Props) {
  const [dragover, setDragover] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

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
        aria-label="Your base animal — click to change it"
        className="flex cursor-pointer items-center justify-center rounded-xl border transition"
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
        <input
          ref={inputRef}
          type="file"
          accept="image/png,image/jpeg,image/webp,image/gif"
          className="hidden"
          onChange={(e) => accept(e.target.files?.[0])}
        />
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
      </div>

      <figcaption className="flex flex-col items-center gap-0.5 text-center">
        <span className="mono text-xs" style={{ color: "var(--muted)" }}>
          {busy ? "drawing…" : shownLabel}
        </span>
        <span className="mono text-xs" style={{ color: locked ? "var(--green)" : "var(--faint)" }}>
          {locked ? "🔒 locked in"
           : isPending ? "not drawn yet — press draw"
           : "click to change · or drop a photo"}
        </span>
      </figcaption>
    </figure>
  );
}
