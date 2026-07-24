"use client";

/**
 * ConfirmModal — the shared confirm dialog for destructive actions
 * (never window.confirm). Renders nothing when closed.
 *
 * The overlay SHELL is <ModalOverlay>, not this file's business. This used to
 * hand-roll its own `fixed inset-0 … flex`, which meant no body scroll-lock, no
 * safe-area insets, no height cap and no inner scroller — the four things hand-rolled
 * overlays always miss. Composing the primitive fixed all four here for free, and it
 * is what makes that primitive genuinely shared rather than a second copy of this one.
 */
import ModalOverlay from "./ModalOverlay";

interface Props {
  open: boolean;
  title: string;
  body: string;
  confirmLabel?: string;
  /** "danger" (default) = red confirm for destructive actions; "primary" = indigo for commits (e.g. Save). */
  tone?: "danger" | "primary";
  onConfirm: () => void;
  onCancel: () => void;
}

export default function ConfirmModal({
  open, title, body, confirmLabel = "Delete", tone = "danger", onConfirm, onCancel,
}: Props) {
  const confirmStyle = tone === "primary"
    ? { background: "linear-gradient(135deg, #6366f1, #4f46e5)", color: "var(--heading)", borderColor: "rgba(99,102,241,0.5)" }
    : { background: "rgba(239,68,68,0.15)", color: "#f87171", borderColor: "rgba(239,68,68,0.4)" };
  return (
    <ModalOverlay open={open} onClose={onCancel} labelledBy="confirm-title" maxWidth="max-w-sm">
      <h2 id="confirm-title" className="mb-2 text-lg font-semibold"
          style={{ color: "var(--heading)" }}>
        {title}
      </h2>
      <p className="mb-5 text-sm leading-relaxed" style={{ color: "var(--muted)" }}>
        {body}
      </p>
        <div className="flex gap-3">
          <button
            onClick={onCancel}
            className="mono flex-1 rounded-lg border px-4 py-2.5 text-sm font-semibold"
            style={{ background: "#151515", color: "var(--muted)", borderColor: "var(--line)" }}
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            className="mono flex-1 rounded-lg border px-4 py-2.5 text-sm font-semibold"
            style={confirmStyle}
          >
            {confirmLabel}
          </button>
        </div>
    </ModalOverlay>
  );
}
