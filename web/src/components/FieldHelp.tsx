"use client";

/**
 * FieldHelp — the shared "what is this field for?" affordance: an ⓘ button that
 * toggles a short explanation beside a form label.
 *
 * Click, not hover. These explanations are read deliberately (an author working out
 * what a field feeds), not glanced at, and hover tooltips are unreachable on touch and
 * vanish while you read them. Native `title=` is not an option — it can't be styled,
 * can't be tapped, and can't hold more than a phrase.
 *
 * Content is `children`, so a caller can use markup (code spans, emphasis) rather than
 * being limited to a string.
 */
import { useId, useState, type ReactNode } from "react";

export default function FieldHelp({ term, children }: {
  /** What the ⓘ explains — used for the screen-reader label ("what is X used for?"). */
  term: string;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  return (
    <span className="relative inline-block align-middle">
      <button type="button" onClick={() => setOpen(!open)}
        aria-expanded={open} aria-controls={panelId}
        aria-label={`What is ${term} used for?`}
        className="mono flex h-4 w-4 items-center justify-center rounded-full border text-[10px] leading-none"
        style={{
          borderColor: open ? "var(--accent)" : "var(--line)",
          color: open ? "var(--accent)" : "var(--faint)",
          background: open ? "rgba(99,102,241,0.12)" : "transparent",
        }}>
        i
      </button>
      {open && (
        <span id={panelId} role="note"
          className="absolute left-0 top-6 z-30 block w-72 max-w-[70vw] rounded-lg border p-2.5 text-xs leading-relaxed"
          style={{ background: "#0c0c0c", borderColor: "var(--line)", color: "var(--muted)" }}>
          {children}
          <button type="button" onClick={() => setOpen(false)}
            className="mono mt-2 block text-xs" style={{ color: "var(--accent)" }}>
            close
          </button>
        </span>
      )}
    </span>
  );
}
