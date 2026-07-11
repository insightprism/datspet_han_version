"use client";

/**
 * ConfirmModal — the shared confirm dialog for destructive actions
 * (never window.confirm). Renders nothing when closed.
 */

interface Props {
  open: boolean;
  title: string;
  body: string;
  confirmLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
}

export default function ConfirmModal({
  open, title, body, confirmLabel = "Delete", onConfirm, onCancel,
}: Props) {
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-6"
      style={{ background: "rgba(0,0,0,0.6)" }}
      onClick={onCancel}
    >
      <div
        className="card w-full max-w-sm p-6"
        role="dialog"
        aria-modal="true"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="mb-2 text-lg font-semibold" style={{ color: "var(--heading)" }}>
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
            style={{ background: "rgba(239,68,68,0.15)", color: "#f87171", borderColor: "rgba(239,68,68,0.4)" }}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
