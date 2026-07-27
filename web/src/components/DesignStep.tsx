"use client";

/**
 * <DesignStep> — step 2, where the pet becomes yours (SPEC_PET_DESIGNER_FLOW §4).
 *
 * SHARED (SPEC_MOTION_LAB_DESIGN_PARITY §2.4, I7): the general designer mounts it and
 * so does the Motion Lab, which is why it lives in components/ beside PosePlayer and
 * PetThumbnail rather than inside one route folder. It is pure props — 7 values, 5
 * callbacks, no fetching, no reducer coupling — so a second mount costs nothing. If the
 * Lab ever needs a variant that is a PROP, never a fork: two step-2 UIs drifting apart
 * is the exact fidelity gap the Lab was mounted here to close.
 *
 * EVERYTHING that answers "what should it look like" lives here: colour, body shape,
 * accessories, free text, and how hard to push it. Nothing here is a step-1 input,
 * and that placement is the whole spec (§0.1) — it is why picking "Chubby" can never
 * cost a curated corgi its vetted base.
 *
 * §4.6 — THE VOCABULARY TRIM. This is the only change in the whole redesign that
 * makes the page smaller. Colour was 17 of today's 29 first-paint controls: 59% of
 * the page was one decision. Restructuring the flow bought legibility and correctness
 * and exactly zero controls; trimming the palette buys the size.
 *
 * The trim is only SAFE because of the free-text field below it (decision #4): 10
 * swatches + "anything else" is MORE expressive than 16 swatches alone — "teal with
 * gold spots" was never in the palette — while costing 6 fewer controls. Without free
 * text this would be a straight capability cut and must not happen. The two are one
 * change.
 *
 * MEASURED, so the numbers here stop drifting from the ones in the spec: the palette is
 * 11 controls with "natural", the whole step-2 vocabulary is 22, and the page peaks at
 * 25 with three accessories chosen and step 1 collapsed. §4.6 aspires to ~8 colours;
 * this is 10, deliberately — see the note on the array below. The spec was updated to
 * match the code rather than the other way round, because the two extra colours are
 * black and white and the argument for keeping them is stronger than the round number.
 */
import { useState } from "react";
import type { DesignAxis } from "@/lib/api";
// The accessory cap lives with the designer's state machine, which enforces it in the
// reducer; this component only reports it. Imported, never retyped — two numbers that
// disagree would let the UI offer a fourth chip the reducer silently drops.
import { MAX_ACCESSORIES } from "@/app/design/general/designFlow";

// §4.6: trimmed from 16 to 10 — NOT the "8" this comment used to claim, and the count
// matters because it is the only number in the whole redesign that measures the thing
// the author complained about. Which colours is a CONTENT decision (it belongs to whoever
// owns the look); the engineering constraints are that each must survive
// compose_design's "recolored entirely {colour}" clause and read unambiguously at
// 160 px. SIX were cut, all chromatic near-duplicates free text genuinely covers:
// emerald, teal, sky blue, indigo, rose, cream. (`golden` is not a seventh — it was
// RENAMED to `yellow`, which is why 16 - 6 = 10 and not 9.) The NEUTRALS stay, because
// "black cat" and "white dog" are among the most-wanted pets there are, and making
// someone type for those would be a downgrade from clicking, not a trade.
const COLORS = [
  { name: "red", css: "#ef4444" },
  { name: "orange", css: "#f97316" },
  { name: "yellow", css: "#eab308" },
  { name: "green", css: "#22c55e" },
  { name: "blue", css: "#3b82f6" },
  { name: "purple", css: "#a855f7" },
  { name: "pink", css: "#ec4899" },
  { name: "brown", css: "#926b4a" },
  { name: "white", css: "#f8fafc" },
  { name: "black", css: "#1e1e1e" },
] as const;

// §4.6: the accessory <select> is already ONE control, so this is a scan-load trim,
// not a control-count one — the list inside the dropdown is what a user reads. Kept:
// the ones that read clearly at sprite scale. Free text covers the rest.
const ACCESSORIES = [
  "wizard hat", "party hat", "top hat", "cowboy hat", "crown",
  "flower crown", "red scarf", "bow tie", "cape", "sunglasses",
  "round glasses", "headphones",
] as const;

// Swatches light enough that a white tick would vanish on them. Kept beside COLORS so
// adding a colour and forgetting this is a one-line miss, not a hunt.
const LIGHT_SWATCHES = new Set(["yellow", "white"]);

const STRENGTHS = [
  { label: "subtle", value: 0.78, hint: "small tweaks" },
  { label: "balanced", value: 0.85, hint: "recolor/restyle" },
  { label: "strong", value: 0.9, hint: "redesign" },
] as const;

interface Props {
  color: string;
  accessories: string[];
  /** axis key → option key; the server filters what applies (SPEC_PET_DESIGN_AXES §4). */
  axisPicks: Record<string, string>;
  extra: string;
  strength: number;
  /** Pre-filtered by the animal's surface — this component holds NO animal logic. */
  axes: DesignAxis[];
  /** The clamp the LAST preview actually applied, so the control can say so (§4.5). */
  minStrength: number | null;
  onColor: (c: string) => void;
  onAccessory: (a: string) => void;
  onAxisPick: (axis: string, key: string) => void;
  onExtra: (t: string) => void;
  onStrength: (s: number) => void;
}

export default function DesignStep({
  color, accessories, axisPicks, extra, strength, axes, minStrength,
  onColor, onAccessory, onAxisPick, onExtra, onStrength,
}: Props) {
  const clamped = minStrength != null && strength < minStrength;
  // The page-size discipline (SPEC_PET_DESIGN_AXES §0.7/§7): body keeps its
  // inline chip row; every OTHER axis sits behind a collapsed disclosure, so
  // step 2's first paint is unchanged and depth is opt-in.
  const [moreOpen, setMoreOpen] = useState(false);
  const bodyAxis = axes.find((a) => a.axis === "body");
  const moreAxes = axes.filter((a) => a.axis !== "body");
  return (
    <div className="flex flex-col gap-4">
      <div>
        <div className="mono mb-1 text-xs" style={{ color: "var(--muted)" }}>colour</div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            className={color === "" ? "btn text-xs" : "btn-ghost text-xs"}
            onClick={() => onColor("")}
          >
            natural
          </button>
          {COLORS.map((c) => {
            const on = color === c.name;
            return (
              <button
                key={c.name}
                type="button"
                title={c.name}
                aria-label={c.name}
                aria-pressed={on}
                onClick={() => onColor(c.name)}
                className="flex items-center justify-center transition"
                style={{
                  width: 28, height: 28, borderRadius: 999, background: c.css,
                  // A RING, drawn with box-shadow rather than `outline`: the inner
                  // shadow is the page colour, so the ring reads as a gap and stays
                  // legible against a swatch of any colour — including white and black,
                  // where a plain border disappears into the page or into the swatch.
                  boxShadow: on
                    ? "0 0 0 2px var(--background), 0 0 0 4px var(--heading)"
                    : "inset 0 0 0 1px rgba(255,255,255,0.15)",
                  transform: on ? "scale(1.1)" : undefined,
                }}
              >
                {/* Colour must never be the ONLY signal of state — that fails anyone who
                    cannot separate two swatches by hue, and this control is made of
                    nothing but hue. The tick is the state; the ring just makes it fast.
                    Dark on light swatches, light on dark, so it survives all ten. */}
                {on && (
                  <span
                    aria-hidden
                    style={{
                      fontSize: 13, lineHeight: 1, fontWeight: 700,
                      color: LIGHT_SWATCHES.has(c.name) ? "#1e1e1e" : "#ffffff",
                    }}
                  >
                    ✓
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </div>

      {/* Renders by MAPPING /api/design-axes — zero hardcoded keys. Deleting the data
          deletes the control: that is the test that it is genuinely data-fed. (The
          COLORS/ACCESSORIES arrays above are hardcoded; do NOT follow that precedent
          here — they have shipped arrays and no second consumer, this doesn't.) */}
      {bodyAxis && bodyAxis.options.length >= 2 && (
        <div>
          <div className="mono mb-1 text-xs" style={{ color: "var(--muted)" }}>
            {bodyAxis.label}
          </div>
          <div className="flex flex-wrap gap-2">
            {bodyAxis.options.map((s) => {
              const pick = axisPicks[bodyAxis.axis];
              const active = s.is_default ? !pick || pick === s.key : pick === s.key;
              return (
                <button
                  key={s.key}
                  type="button"
                  className={active ? "btn text-xs" : "btn-ghost text-xs"}
                  onClick={() => onAxisPick(bodyAxis.axis, s.key)}
                >
                  {s.label}
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* The rest of the vocabulary (SPEC_PET_DESIGN_AXES §7): pattern, mood, and
          the ONE surface axis the server chose for this animal — an uncatalogued
          creature simply receives fewer axes and renders fewer selects (§3.3).
          Collapsed by default; opening it adds at most three compact selects. */}
      {moreAxes.length > 0 && (
        <div>
          <button
            type="button"
            className="btn-ghost text-xs"
            aria-expanded={moreOpen}
            onClick={() => setMoreOpen(!moreOpen)}
          >
            ✨ more ways to make it yours {moreOpen ? "▴" : "▾"}
          </button>
          {moreOpen && (
            <div className="mt-2 flex flex-col gap-3">
              {moreAxes.map((a) => (
                <label key={a.axis} className="flex flex-col gap-1">
                  <span className="mono text-xs" style={{ color: "var(--muted)" }}>
                    {a.label}
                  </span>
                  <select
                    className="input"
                    value={axisPicks[a.axis] || a.default}
                    onChange={(e) => onAxisPick(a.axis, e.target.value)}
                  >
                    {a.options.map((o) => (
                      <option key={o.key} value={o.key}>{o.label}</option>
                    ))}
                  </select>
                </label>
              ))}
            </div>
          )}
        </div>
      )}

      <div>
        <div className="mono mb-1 text-xs" style={{ color: "var(--muted)" }}>
          accessories <span style={{ color: "var(--faint)" }}>(up to {MAX_ACCESSORIES})</span>
        </div>
        <select
          className="input"
          value=""
          disabled={accessories.length >= MAX_ACCESSORIES}
          onChange={(e) => { if (e.target.value) onAccessory(e.target.value); }}
        >
          <option value="">
            {accessories.length >= MAX_ACCESSORIES ? "that's plenty" : "add one…"}
          </option>
          {ACCESSORIES.filter((a) => !accessories.includes(a)).map((a) => (
            <option key={a} value={a}>{a}</option>
          ))}
        </select>
        {accessories.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-2">
            {accessories.map((a) => (
              <button key={a} type="button" className="btn-ghost text-xs" onClick={() => onAccessory(a)}>
                {a} ✕
              </button>
            ))}
          </div>
        )}
      </div>

      <label className="flex flex-col gap-1">
        <span className="mono text-xs" style={{ color: "var(--muted)" }}>anything else?</span>
        <input
          className="input"
          placeholder="made of clockwork gears"
          value={extra}
          onChange={(e) => onExtra(e.target.value)}
        />
      </label>

      <div>
        <div className="mono mb-1 text-xs" style={{ color: "var(--muted)" }}>how far to push it</div>
        <div className="flex flex-wrap gap-2">
          {STRENGTHS.map((s) => (
            <button
              key={s.label}
              type="button"
              className={strength === s.value ? "btn text-xs" : "btn-ghost text-xs"}
              onClick={() => onStrength(s.value)}
              title={s.hint}
            >
              {s.label}
            </button>
          ))}
        </div>
        {/* §4.5 — min_strength must stop lying. The server silently raises a "subtle"
            pick to "strong" when the redraw has to fight the source (a colour word in
            the species name, or a silhouette change). Saying so is the whole fix; the
            surprise is pre-existing, and adding a second trigger is the moment to
            surface it rather than double it. */}
        {clamped && (
          <div className="mono mt-1 text-xs" style={{ color: "var(--faint)" }}>
            using strong — required for this change
          </div>
        )}
      </div>
    </div>
  );
}
