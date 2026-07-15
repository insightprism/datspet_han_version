"use client";

/**
 * The pending base animal, and the one control that only an upload needs
 * (SPEC_PET_DESIGNER_FLOW §3.4).
 */

/** What the user has lined up but not yet made their base. */
export type PendingSource =
  | { kind: "catalog"; animal: string; breed: string; label: string }
  | { kind: "upload"; file: File; url: string; strength: number }
  | { kind: "typed"; animal: string };

/**
 * How hard to redraw an uploaded photo. The USER picks, because the trade is real and
 * only they know which side they want (§3.4):
 *
 *   faithful — stays like YOUR dog, but keeps the photographic pose and lighting that
 *              Wan I2V animates badly. That is today's bug, chosen deliberately.
 *   sprite   — a proper flat side-profile sprite that animates reliably, but looks
 *              redrawn: recognisably A dog rather than YOUR dog.
 *
 * Defaults to `sprite` because the animation is the product — a faithful still that
 * loops badly is a worse pet than a stylised one that moves right. The user can
 * disagree; they just cannot do it by accident.
 */
export const UPLOAD_STRENGTHS = [
  { label: "faithful", value: 0.4, hint: "keep it looking like my photo" },
  { label: "balanced", value: 0.65, hint: "" },
  { label: "sprite", value: 0.85, hint: "animates best" },
] as const;

export const DEFAULT_UPLOAD_STRENGTH = 0.85;

interface Props {
  strength: number;
  onStrength: (s: number) => void;
}

export default function UploadStrength({ strength, onStrength }: Props) {
  return (
    <div className="flex flex-col gap-1">
      <span className="mono text-xs" style={{ color: "var(--muted)" }}>
        how much to redraw your photo
      </span>
      <div className="flex flex-wrap gap-2">
        {UPLOAD_STRENGTHS.map((s) => (
          <button
            key={s.label}
            type="button"
            title={s.hint}
            className={strength === s.value ? "btn text-xs" : "btn-ghost text-xs"}
            onClick={() => onStrength(s.value)}
          >
            {s.label}
          </button>
        ))}
      </div>
      <span className="mono text-xs" style={{ color: "var(--faint)" }}>
        faithful keeps your photo&apos;s look · sprite animates best
      </span>
    </div>
  );
}
