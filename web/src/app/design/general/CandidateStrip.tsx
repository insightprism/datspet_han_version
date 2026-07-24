"use client";

/**
 * <CandidateStrip> — the last N drawn bases, kept pickable (SPEC_UPLOAD_LIKENESS §2.4,
 * lever D — "keep the rolls").
 *
 * Every Draw already mints its own reference record and nothing deletes it on the next
 * roll (the 24 h janitor sweeps them, /api/reference/{id}.png serves them owner-scoped),
 * so this is "stop dropping the ids": best-of-N with the owner as the judge, at zero extra
 * GPU. Re-rolling to find a good sprite is the natural workflow — this stops throwing away
 * the good ones. Source-agnostic: a typed animal and an uploaded photo sit in the same
 * strip (§2.4). Clicking one re-selects it as the base, which is a FILL, not a new draw —
 * the reducer routes it through referenceFilled so step 2 unlocks against it exactly as a
 * fresh draw would (the pickRoll invariant).
 */
import { referenceImageUrl, type PetReference } from "@/lib/api";

export default function CandidateStrip({ rolls, currentId, onPick }: {
  rolls: PetReference[];
  currentId: string | null;
  onPick: (roll: PetReference) => void;
}) {
  // A strip of one is just the box again — only worth showing once there is a choice.
  if (rolls.length < 2) return null;

  return (
    <div className="flex flex-col items-center gap-1.5">
      <span className="mono text-xs" style={{ color: "var(--faint)" }}>
        your last {rolls.length} — click one to go back to it
      </span>
      <div className="flex flex-wrap justify-center gap-2">
        {rolls.map((r) => {
          const current = r.reference_id === currentId;
          return (
            <button
              key={r.reference_id}
              type="button"
              onClick={() => onPick(r)}
              aria-current={current ? "true" : undefined}
              title={r.display_name}
              className="overflow-hidden rounded-lg transition hover:opacity-90"
              style={{
                width: 56, height: 56, background: "#fff",
                border: `${current ? 2 : 1}px solid ${current ? "var(--green)" : "var(--line)"}`,
              }}
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={referenceImageUrl(r.reference_id)}
                alt={r.display_name}
                className="h-full w-full object-contain"
              />
            </button>
          );
        })}
      </div>
    </div>
  );
}
