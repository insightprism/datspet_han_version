"use client";

/**
 * promptTemplates — the engine half of a pose's prompt, made visible.
 *
 * A motion profile is only HALF of what reaches the models: the JSON supplies the
 * `{pose}` / `{action}` / `{suffix}` slots, and a sentence template owned by the engine
 * supplies everything around them. The profile editor shows the JSON half; this module
 * shows the template half and how the two assemble.
 *
 * The template STRINGS are never restated here — they are fetched from
 * `GET /api/admin/motions/prompt-templates`, which serves the Python constants
 * (`pet_factory/prompt_templates.py` + `motion_profiles.MOTION_PROMPT_TEMPLATE`)
 * verbatim. This module only knows how to substitute `{slots}` and lay them out, so an
 * edit to a template in Python shows up here with no frontend change — and cannot leave
 * the preview quietly lying.
 */
import { useEffect, useState, type ReactNode } from "react";

import { motionAdmin, type MotionPromptTemplates } from "@/lib/api";

// Who fills each slot. Colour is the same everywhere a prompt is rendered, so the
// template/profile/request split reads identically in the tab and in a pose preview.
export const SLOT_TINT: Record<string, string> = {
  animal: "var(--green)",
  pose: "var(--orange)",
  action: "var(--orange)",
  suffix: "var(--orange)",
};

export const SLOT_SOURCE: Record<string, string> = {
  animal: "the request — what the user typed, or the composed design description",
  pose: "the profile — this pose's control.pose anchor clause (falls back to base_pose)",
  action: "the profile — this pose's action field",
  suffix: "the profile — this pose's suffix field",
};

/** Every string the renderers below index into. Checked at the boundary rather than
 *  guarded at each use: the preview is an extra, and a backend serving an older or
 *  newer shape (a not-yet-restarted dev server is the common case) must cost the page
 *  its preview, never its render. */
function hasUsableShape(t: unknown): t is MotionPromptTemplates {
  const c = t as MotionPromptTemplates | null;
  return typeof c?.still?.base === "string"
    && typeof c?.still?.remix === "string"
    && typeof c?.still?.default_pose === "string"
    && typeof c?.motion?.template === "string";
}

/** Fetch the templates once. Null while loading, and permanently null if the call fails
 *  or answers in a shape this build can't render — every caller treats null as "render
 *  nothing", so the editor keeps working either way. */
export function useMotionPromptTemplates(): MotionPromptTemplates | null {
  const [templates, setTemplates] = useState<MotionPromptTemplates | null>(null);
  useEffect(() => {
    let live = true;
    motionAdmin.promptTemplates().then((t) => {
      if (!live) return;
      if (hasUsableShape(t)) setTemplates(t);
      else console.warn("[motions] prompt-template shape not recognised — preview hidden. Restart the backend?", t);
    }).catch(() => {});
    return () => { live = false; };
  }, []);
  return templates;
}

/** The distinct `{slots}` a template uses, in order of first appearance. */
export function slotsIn(template: string): string[] {
  const found: string[] = [];
  const slot = /\{(\w+)\}/g;
  let match: RegExpExecArray | null;
  while ((match = slot.exec(template)) !== null) {
    if (!found.includes(match[1])) found.push(match[1]);
  }
  return found;
}

/** Render a template with its slots filled and tinted. Pass the placeholder names as
 *  their own values to render the raw, unfilled template with the slots highlighted. */
export function renderPrompt(template: string, values: Record<string, string>): ReactNode[] {
  const out: ReactNode[] = [];
  const slot = /\{(\w+)\}/g;
  let cursor = 0;
  let match: RegExpExecArray | null;
  while ((match = slot.exec(template)) !== null) {
    if (match.index > cursor) {
      out.push(<span key={out.length}>{template.slice(cursor, match.index)}</span>);
    }
    const name = match[1];
    const filled = values[name] ?? "";
    out.push(
      <span key={out.length} style={{ color: SLOT_TINT[name] ?? "var(--muted)" }}>
        {filled || `⟨${name} is empty⟩`}
      </span>,
    );
    cursor = match.index + match[0].length;
  }
  if (cursor < template.length) out.push(<span key={out.length}>{template.slice(cursor)}</span>);
  return out;
}

/** The template with its slots left as `{name}`, tinted — i.e. the engine's half alone. */
export function renderRawTemplate(template: string): ReactNode[] {
  const literal: Record<string, string> = {};
  for (const s of slotsIn(template)) literal[s] = `{${s}}`;
  return renderPrompt(template, literal);
}

// Which model a section belongs to — the card's edge and heading. Deliberately a
// different axis from the slot tints above, which live inside the prompt text, so the
// two colour languages never compete for the same meaning.
export const CALL_TINT: Record<"still" | "motion", string> = {
  still: "var(--accent)",   // Z-Image — indigo
  motion: "var(--gold)",    // Wan 2.2 — purple
};
const PROMPT_BG = "#0c0c0c";
const SECTION_BG = "#141414";

const PRE_CLS = "mono whitespace-pre-wrap break-words rounded p-2 text-xs leading-relaxed";

/** One model call — its own card, edge-coloured so the eye can find where still ends
 *  and motion begins without reading a word. */
export function CallSection({ step, title, subtitle, call, children }: {
  step: number; title: string; subtitle: string;
  call: "still" | "motion"; children: ReactNode;
}) {
  const tint = CALL_TINT[call];
  return (
    <section className="mt-4 rounded-lg border border-l-4 p-3"
      style={{ borderColor: "var(--line)", borderLeftColor: tint, background: SECTION_BG }}>
      <div className="mono text-sm font-semibold" style={{ color: tint }}>{step} · {title}</div>
      <div className="mono mt-0.5 text-xs" style={{ color: "var(--faint)" }}>{subtitle}</div>
      {children}
    </section>
  );
}

/** One prompt inside a call: a tagged box, badged in the call's colour. */
export function PromptBlock({ label, origin, call, note, children }: {
  label: string; origin?: string; call: "still" | "motion";
  note?: ReactNode; children: ReactNode;
}) {
  const tint = CALL_TINT[call];
  return (
    <div className="mt-3">
      <div className="mono mb-1 flex flex-wrap items-baseline gap-2 text-xs">
        <span className="rounded px-1.5 py-0.5" style={{ color: tint, border: `1px solid ${tint}` }}>
          {label}
        </span>
        {origin && <span style={{ color: "var(--muted)" }}>{origin}</span>}
      </div>
      {note && <div className="mono mb-1 text-xs leading-relaxed" style={{ color: "var(--faint)" }}>{note}</div>}
      <div className={PRE_CLS} style={{ background: PROMPT_BG, border: "1px solid var(--line)", color: "var(--faint)" }}>
        {children}
      </div>
    </div>
  );
}

/**
 * One prompt broken into its ingredients: the template, each slot's value and where it
 * came from, then the assembled result. This is the "show me the pieces" view — the
 * same information as the one-line preview, but unstacked.
 */
export function PromptPieces({ template, templateOrigin, values, call }: {
  template: string;
  templateOrigin: string;
  values: Record<string, string>;
  call: "still" | "motion";
}) {
  return (
    <div className="mt-1 flex flex-col gap-2 rounded p-2" style={{ background: PROMPT_BG, border: "1px solid var(--line)" }}>
      <div>
        <div className="mono text-xs" style={{ color: CALL_TINT[call] }}>
          template <span style={{ color: "var(--faint)" }}>· engine · {templateOrigin}</span>
        </div>
        <div className="mono whitespace-pre-wrap break-words text-xs leading-relaxed" style={{ color: "var(--faint)" }}>
          {renderRawTemplate(template)}
        </div>
      </div>
      {slotsIn(template).map((name) => (
        <div key={name}>
          <div className="mono text-xs">
            <span style={{ color: SLOT_TINT[name] ?? "var(--muted)" }}>{`{${name}}`}</span>{" "}
            <span style={{ color: "var(--faint)" }}>· {SLOT_SOURCE[name] ?? "the profile"}</span>
          </div>
          <div className="mono whitespace-pre-wrap break-words text-xs leading-relaxed"
            style={{ color: SLOT_TINT[name] ?? "var(--muted)" }}>
            {values[name] || <span style={{ color: "var(--faint)" }}>⟨empty⟩</span>}
          </div>
        </div>
      ))}
      <div className="border-t pt-2" style={{ borderColor: "var(--line)" }}>
        <div className="mono text-xs" style={{ color: "var(--muted)" }}>= what is sent</div>
        <div className="mono whitespace-pre-wrap break-words text-xs leading-relaxed" style={{ color: "var(--faint)" }}>
          {renderPrompt(template, values)}
        </div>
      </div>
    </div>
  );
}

/**
 * The page-level reference: every template the motion pipeline uses, unfilled. Global
 * content — the same sentences for every profile and every animal — which is why it is
 * a tab of its own rather than a field on a profile. Read-only by nature: these live in
 * Python, and changing one re-rolls the look of every pet built afterwards.
 */
export function PromptTemplateReference({ templates }: { templates: MotionPromptTemplates | null }) {
  if (!templates) {
    return <p className="mono text-sm" style={{ color: "var(--faint)" }}>Loading prompt templates…</p>;
  }
  return (
    <div className="card p-5">
      <div className="mb-1 text-lg font-semibold" style={{ color: "var(--heading)" }}>Prompt templates</div>
      <p className="mb-4 text-sm" style={{ color: "var(--muted)" }}>
        The engine&apos;s half of every pose. A motion profile fills the{" "}
        <span className="mono" style={{ color: "var(--orange)" }}>{"{slots}"}</span> below — everything
        around them is the same for every profile and every animal, and lives in Python rather than
        in a profile file. Read-only here: editing one of these re-rolls the look of every pet built
        afterwards.
      </p>

      <CallSection step={1} call="still" title="still prompt → Z-Image (txt2img)"
        subtitle="draws the single frozen frame a pose animates from">
        <PromptBlock call="still" label="typed from scratch"
          origin="prompt_templates.BASE_STILL_TEMPLATE">
          {renderRawTemplate(templates.still.base)}
        </PromptBlock>
        <PromptBlock call="still" label="redrawn from a locked still"
          origin="prompt_templates.REMIX_STILL_TEMPLATE"
          note="Used when the pet started from a reference image. Drops the pastel clause on purpose: a remix is usually about changing the colour, and pastel fights the requested one.">
          {renderRawTemplate(templates.still.remix)}
        </PromptBlock>
        <div className="mono mt-3 text-xs leading-relaxed" style={{ color: "var(--faint)" }}>
          A pose with no anchor clause reuses the shared base still, whose{" "}
          <span style={{ color: "var(--orange)" }}>{"{pose}"}</span> is the profile&apos;s{" "}
          <span style={{ color: "var(--muted)" }}>base_pose</span> (default{" "}
          <span style={{ color: "var(--muted)" }}>&quot;{templates.still.default_pose}&quot;</span>).
        </div>
      </CallSection>

      <CallSection step={2} call="motion" title="motion prompt → Wan 2.2 I2V"
        subtitle="paints ~16 frames out of that still">
        <PromptBlock call="motion" label="the template" origin="motion_profiles.MOTION_PROMPT_TEMPLATE">
          {renderRawTemplate(templates.motion.template)}
        </PromptBlock>
        <p className="mt-3 text-sm" style={{ color: "var(--muted)" }}>
          Note how little of this one is template. The still prompt carries ~20 words of house style
          because Z-Image paints from nothing; Wan is animating an image that already has the style, so
          the profile&apos;s <span className="mono" style={{ color: "var(--orange)" }}>action</span> +{" "}
          <span className="mono" style={{ color: "var(--orange)" }}>suffix</span> are effectively the
          whole instruction. A suffix that forgets to name the limb that moves has no template behind
          it to make up the difference.
        </p>
      </CallSection>

      <div className="mono mt-5 mb-1 block text-xs tracking-wide" style={{ color: "var(--muted)" }}>
        why there is no negative prompt
      </div>
      <p className="mb-2 text-sm" style={{ color: "var(--muted)" }}>
        Both models are distilled — Z-Image-Turbo (8 steps) and Wan with the LightX2V 4-step LoRA —
        and every sampler runs at <span className="mono">cfg 1.0</span>, where guidance degenerates
        to <span className="mono">output = positive</span> and negative conditioning cancels out.
        Measured on 2026-07-26: one seed, one positive prompt, three very different negatives →
        byte-identical pixels. There used to be a negative here; it was removed because it did
        nothing. If a future model raises cfg, <span className="mono">test_samplers_run_at_cfg_one</span>{" "}
        goes red and this becomes a live decision again.
      </p>

      <div className="mono mt-5 mb-1 block text-xs tracking-wide" style={{ color: "var(--muted)" }}>the slots</div>
      <div className="flex flex-col gap-1">
        {["animal", "pose", "action", "suffix"].map((name) => (
          <div key={name} className="mono text-xs">
            <span style={{ color: SLOT_TINT[name] }}>{`{${name}}`}</span>{" "}
            <span style={{ color: "var(--faint)" }}>— {SLOT_SOURCE[name]}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
