"use client";

/**
 * <PoseStep> — step 4 (SPEC_PET_DESIGNER_FLOW §8).
 *
 * Unchanged in contract from today: walk+idle locked and always built, free pick up
 * to the caller's resolved cap, over-cap disabled with the upsell, `triggered` poses
 * never offered, and the browser never sees the tier table — only its own resolved
 * entitlement. The server clips authoritatively regardless of what this renders.
 *
 * It comes AFTER the preview so the price is disclosed once the user has seen what
 * they are buying.
 */
import type { Entitlement } from "@/lib/api";

const SECONDS_PER_POSE = 75;
const BASE_MAX_POSES = 2;

function timeHint(n: number): string {
  const mins = (n * SECONDS_PER_POSE) / 60;
  const rounded = Math.round(mins * 2) / 2;
  const label = Number.isInteger(rounded) ? `${rounded}` : `${Math.floor(rounded)}½`;
  return `${n} pose${n === 1 ? "" : "s"} ≈ ${label} min`;
}

function priceHint(totalPoses: number, ent: Entitlement | null): string | null {
  if (!ent || ent.base_design_cost == null) return null;
  const extra = Math.max(0, totalPoses - BASE_MAX_POSES);
  return `${ent.base_design_cost + extra * ent.price_per_extra_pose} credits`;
}

// Every pose that will be BUILT is green. The two shades separate "always included"
// from "you chose this" without introducing a second colour to decode: the darker pair
// is the floor every pet gets, the lighter ones are what the user added on top.
const PILL_BASE = {
  borderRadius: 8,
  padding: "0.5rem 0.9rem",
  fontWeight: 500,
  border: "1px solid",
} as const;

const ALWAYS_PILL = {
  ...PILL_BASE,
  background: "rgba(52,211,153,0.30)",
  borderColor: "var(--green)",
  color: "var(--heading)",
  // Not a button and not disabled — it is a statement of fact. `default` says
  // "nothing to click here" without the greying-out that reads as "unavailable".
  cursor: "default",
} as const;

const CHOSEN_PILL = {
  ...PILL_BASE,
  background: "rgba(52,211,153,0.12)",
  borderColor: "rgba(52,211,153,0.55)",
  color: "var(--green)",
} as const;

interface Props {
  menu: string[];
  selected: string[];
  maxPoses: number;
  entitlement: Entitlement | null;
  notice: string | null;
  /** The motion profile this pet will actually be built with — the key resolved at
   *  reference-fill time and pinned on the record, which the build loads verbatim. It
   *  decides which poses exist here AND how every limb moves, so a wrong one explains a
   *  wrong pet. It was already in state and never shown; a Komodo dragon silently
   *  resolving to `winged_flyer` cost an investigation that this line answers at a
   *  glance. Null only if the reference somehow carries no key. */
  motionProfile: string | null;
  onToggle: (pose: string) => void;
  onDismissNotice: () => void;
}

export default function PoseStep({
  menu, selected, maxPoses, entitlement, notice, motionProfile, onToggle, onDismissNotice,
}: Props) {
  const total = selected.length + BASE_MAX_POSES;
  const atCap = total >= maxPoses;
  const price = priceHint(total, entitlement);

  return (
    <div className="flex flex-col gap-3">
      {/* A silent pose drop changes the price with no explanation — that breaks the
          disclosure rule in spirit even when the number is right (§7.6). */}
      {notice && (
        <div className="mono flex items-center justify-between gap-2 text-xs"
             style={{ color: "var(--faint)" }}>
          <span>{notice}</span>
          <button type="button" className="btn-ghost text-xs" onClick={onDismissNotice}>ok</button>
        </div>
      )}

      {motionProfile && (
        <div className="mono text-xs" style={{ color: "var(--faint)" }}>
          moves like: <span style={{ color: "var(--muted)" }}>{motionProfile.replace(/_/g, " ")}</span>
          {" — this body type decides the poses below and how the limbs move"}
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        {/* Walk and idle are ALWAYS built (SPEC_MOTION_PROFILES §3.4), so they are ON,
            and they must look it. Rendering them ghosted read as "off" or "disabled" —
            the exact opposite of the truth, and the two poses every pet is guaranteed
            to have were the two that looked unavailable. */}
        <span className="text-xs" style={ALWAYS_PILL}>walk · always</span>
        <span className="text-xs" style={ALWAYS_PILL}>idle · always</span>
        {menu.map((p) => {
          const on = selected.includes(p);
          const locked = !on && atCap;
          return (
            <button
              key={p}
              type="button"
              className={on ? "text-xs" : "btn-ghost text-xs"}
              disabled={locked}
              onClick={() => onToggle(p)}
              // One meaning, one colour: green = this pose gets built. The shade is the
              // only difference, and it carries the only distinction that matters —
              // deep green is the pair you always get, lighter green is what YOU added.
              style={on ? CHOSEN_PILL : locked ? { opacity: 0.4 } : undefined}
            >
              {p}
            </button>
          );
        })}
      </div>

      <div className="mono text-xs" style={{ color: "var(--faint)" }}>
        {timeHint(total)}{price ? ` · ${price}` : ""}
        {atCap && entitlement?.upsell ? ` · ${entitlement.upsell}` : ""}
      </div>
    </div>
  );
}
