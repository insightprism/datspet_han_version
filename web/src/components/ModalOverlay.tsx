"use client";

/**
 * <ModalOverlay> — THE modal-overlay primitive. Every dialog in the app composes this;
 * nothing hand-rolls a `fixed inset-0 … flex` overlay of its own.
 *
 * It exists because those hand-rolled overlays silently miss the same four things
 * every time, and each one is invisible until it isn't:
 *
 *   - SAFE-AREA INSETS  — on a notched phone a centred dialog can sit under the
 *                         status bar or the home indicator.
 *   - BODY SCROLL-LOCK  — without it the page behind scrolls under your finger while
 *                         the dialog sits still, which reads as a broken dialog.
 *   - AN INNER SCROLLER — content taller than the viewport becomes unreachable: no
 *                         scroll, and the buttons are simply gone below the fold.
 *   - A HEIGHT CAP      — the thing that makes the inner scroller ever engage.
 *
 * Escape and backdrop-click close, and focus returns to whatever opened it.
 *
 * This owns the SHELL, not the content: a dialog passes children and its own buttons.
 * The shell is what must never diverge; what goes inside is each dialog's business —
 * the same chrome-vs-contract split the platform spec draws for themed pages.
 */
import { useEffect, useRef, type ReactNode } from "react";

interface Props {
  open: boolean;
  onClose: () => void;
  /** Accessible name. Point at the id of the dialog's heading. */
  labelledBy?: string;
  children: ReactNode;
  /** Tailwind max-width class for the panel. */
  maxWidth?: string;
}

export default function ModalOverlay({
  open, onClose, labelledBy, children, maxWidth = "max-w-lg",
}: Props) {
  const panelRef = useRef<HTMLDivElement>(null);
  const openerRef = useRef<Element | null>(null);

  // Escape closes. Registered on the document so it works before focus lands inside.
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  // Body scroll-lock, restoring whatever was there before rather than assuming "".
  useEffect(() => {
    if (!open) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = previous; };
  }, [open]);

  // Move focus in, and hand it back to the opener on close — otherwise a keyboard
  // user lands at the top of the document every time a dialog closes.
  useEffect(() => {
    if (!open) return;
    openerRef.current = document.activeElement;
    panelRef.current?.focus();
    return () => { (openerRef.current as HTMLElement | null)?.focus?.(); };
  }, [open]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{
        background: "rgba(0,0,0,0.6)",
        // Safe-area insets + a floor, so the panel never sits under a notch or a
        // home indicator and never touches the edge on a plain desktop window.
        paddingTop: "max(1.5rem, env(safe-area-inset-top))",
        paddingBottom: "max(1.5rem, env(safe-area-inset-bottom))",
        paddingLeft: "max(1.5rem, env(safe-area-inset-left))",
        paddingRight: "max(1.5rem, env(safe-area-inset-right))",
      }}
      onClick={onClose}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelledBy}
        tabIndex={-1}
        className={`card w-full ${maxWidth} outline-none`}
        // The cap + the scroller are one mechanism: the cap is what makes the
        // scroller engage, so they live together or neither works.
        style={{ maxHeight: "100%", display: "flex", flexDirection: "column" }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="overflow-y-auto p-6">{children}</div>
      </div>
    </div>
  );
}
