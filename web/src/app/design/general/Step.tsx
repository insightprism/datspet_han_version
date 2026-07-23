"use client";

/**
 * <Step> — the disclosure shell (SPEC_PET_DESIGNER_FLOW §7.6).
 *
 * One rule, applied in both directions:
 *
 *     Every step always renders its ARTIFACT. A step renders its CONTROLS only
 *     when it is expanded.
 *
 * MEASURED, not quoted from the spec: 2 controls at first paint and 25 at peak,
 * against today's 29/32. First paint beats the spec's 3 (the curated pre-fill
 * suppresses the draw button — nothing to draw); peak misses its ~21, because the
 * palette is 11 with "natural" and the vocabulary is 22.
 *
 * The artifact is the picture; the controls are the swatches. Only the picture ever
 * needed to stay co-visible: "a blue jay" next to "my blue jay" is the clearest
 * possible statement of what steps 1 and 2 each did.
 *
 * NOT a wizard. There is no Next/Back — that chrome would cost ~8-10 controls,
 * fighting the one thing this redesign buys. Steps past the frontier are dimmed and
 * inert; steps behind it collapse to their artifact plus one re-open control.
 */
import type { ReactNode } from "react";

interface Props {
  index: number;
  title: string;
  /** Shown beside the title when collapsed — the one-line answer this step gave. */
  summary?: ReactNode;
  /** The step's artifact. Renders in EVERY state (that is the rule). */
  artifact?: ReactNode;
  /** The step's controls. Mounted only when `expanded`. */
  children?: ReactNode;
  expanded: boolean;
  reachable: boolean;
  /** Absent = this step cannot be re-opened (it is the frontier, or it is locked). */
  onExpand?: () => void;
  expandLabel?: string;
  /**
   * "confirmed" tints the whole section green — the decision here is settled and the
   * step below it is open because of that. It reads at a glance from across the page,
   * which a lock icon on one button does not.
   */
  tone?: "default" | "confirmed";
  /**
   * "split" puts the controls LEFT and the artifact RIGHT while expanded, so the thing
   * you are changing sits beside the controls that change it. Step 2 needs it: it is a
   * loop (tweak → preview → tweak), and stacking the picture above ~17 swatches puts
   * the result off-screen from the controls producing it.
   *
   * Step 1 uses it too, since SPEC_STEP1_SOURCE_RAIL. It used to be centred "because it
   * has three controls, so there is no distance to close" — true of the layout and wrong
   * about the step: two of those three controls were a picture and a commit button, and
   * the question step 1 exists to ask was not on screen at all. <SourceRail> puts it in
   * the left column, and the box it fills sits beside it.
   *
   * Collapsed, both layouts are identical: a summary and the artifact.
   */
  layout?: "stack" | "split";
}

export default function Step({
  index, title, summary, artifact, children,
  expanded, reachable, onExpand, expandLabel = "Edit", tone = "default",
  layout = "stack",
}: Props) {
  const confirmed = tone === "confirmed";
  const split = layout === "split" && expanded && reachable;
  return (
    <section
      className="card mb-4 p-5"
      style={{
        ...(reachable ? null : { opacity: 0.45 }),
        // Tinted, not filled: on a near-black page a literal light green would blow out
        // the contrast of everything sitting on it, including the sprite.
        ...(confirmed
          ? { background: "rgba(52,211,153,0.07)", borderColor: "rgba(52,211,153,0.35)" }
          : null),
      }}
      aria-disabled={!reachable}
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-baseline gap-2">
          {/* "Step 1 — Select the Animal to Design", not a faint numeral beside a title.
              The numeral read as decoration; naming the step in the heading is what ties
              the card to the three-step promise in the page header above it. */}
          <h2 className="text-sm font-semibold">Step {index} — {title}</h2>
          {!expanded && summary && (
            <span className="mono text-xs" style={{ color: "var(--muted)" }}>{summary}</span>
          )}
        </div>
        {!expanded && reachable && onExpand && (
          <button type="button" className="btn-ghost text-xs" onClick={onExpand}>
            {expandLabel} ▸
          </button>
        )}
      </div>

      {split ? (
        <div className="mt-3 flex flex-wrap items-start gap-8">
          {/* Controls left… */}
          <div className="min-w-[280px] flex-1">{children}</div>
          {/* …the thing they produce, right — and sticky, so it stays in view while you
              scroll the controls that change it. A result you have to scroll away from
              to adjust is a result you cannot compare against. */}
          {artifact && (
            <div className="shrink-0 self-start" style={{ position: "sticky", top: "1rem" }}>
              {artifact}
            </div>
          )}
        </div>
      ) : (
        <>
          {artifact && <div className="mt-3">{artifact}</div>}
          {/* Unmounted, not hidden: a hidden control still costs the reader a scan and
              still holds state. Collapsing must actually remove it. */}
          {expanded && reachable && <div className="mt-4">{children}</div>}
        </>
      )}
    </section>
  );
}
