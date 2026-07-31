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
  /**
   * For confirms that fire an async action the dialog must OUTLIVE: swaps the
   * confirm label, disables both buttons, and suppresses backdrop/Escape
   * dismissal so the work cannot be orphaned mid-flight. Callers that resolve
   * by closing the dialog themselves can ignore it.
   */
  pending?: boolean;
  pendingLabel?: string;
  /** Shown inline under the body. The dialog stays OPEN on failure — an error
   *  the user must re-find the trigger to retry is a worse error. Never a toast. */
  error?: string;
  onConfirm: () => void;
  onCancel: () => void;
}

export default function ConfirmModal({
  open, title, body, confirmLabel = "Delete", tone = "danger",
  pending = false, pendingLabel = "Working…", error = "", onConfirm, onCancel,
}: Props) {
  const confirmStyle = tone === "primary"
    ? { background: "linear-gradient(135deg, #6366f1, #4f46e5)", color: "var(--heading)", borderColor: "rgba(99,102,241,0.5)" }
    : { background: "rgba(239,68,68,0.15)", color: "#f87171", borderColor: "rgba(239,68,68,0.4)" };
  return (
    <ModalOverlay open={open} onClose={pending ? () => {} : onCancel}
                  labelledBy="confirm-title" maxWidth="max-w-sm">
      <h2 id="confirm-title" className="mb-2 text-lg font-semibold"
          style={{ color: "var(--heading)" }}>
        {title}
      </h2>
      <p className="mb-3 text-sm leading-relaxed" style={{ color: "var(--muted)" }}>
        {body}
      </p>
      {error && (
        <p role="alert" className="mb-3 text-xs leading-relaxed" style={{ color: "#f87171" }}>
          {error}
        </p>
      )}
        <div className="mt-2 flex gap-3">
          <button
            onClick={onCancel}
            disabled={pending}
            className="mono flex-1 rounded-lg border px-4 py-2.5 text-sm font-semibold disabled:opacity-40"
            style={{ background: "#151515", color: "var(--muted)", borderColor: "var(--line)" }}
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            disabled={pending}
            className="mono flex-1 rounded-lg border px-4 py-2.5 text-sm font-semibold disabled:opacity-40"
            style={confirmStyle}
          >
            {pending ? pendingLabel : confirmLabel}
          </button>
        </div>
    </ModalOverlay>
  );
}
