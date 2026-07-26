"use client";

/**
 * ProfileEditor — the shared motion-profile form (SPEC_MOTION_PROFILE_ADMIN §5).
 * A strict, schema-guided editor: every write is validated server-side against the
 * exact guard-test contract, so the UI can't produce a profile the build would reject.
 *
 * CONTENT ONLY — it renders no outer card/overlay of its own. The caller supplies the
 * container: the Motions page drops it in a `.card` pane; the Motion Lab drops it inside
 * <ModalOverlay>. That is the same shell-vs-content split the overlay primitive draws —
 * one editor, two hosts, no second copy.
 */
import { useState } from "react";

import {
  CANONICAL_POSES, REQUIRED_POSES, POSE_ROLES,
  type MotionProfileFile, type MotionPromptTemplates,
} from "@/lib/api";
import {
  CALL_TINT, PromptPieces, renderPrompt, useMotionPromptTemplates,
} from "./promptTemplates";
import FieldHelp from "@/components/FieldHelp";

export type Draft = { profile: MotionProfileFile; label: string; editingKey: string | null };

// Each runtime_role gets a colour on the pose card's left edge, so the four behaviours
// (home state · travel gait · auto mood · one-shot reaction) are scannable without
// reading every dropdown. Unknown/disabled poses fall back to the neutral line colour.
const ROLE_TINT: Record<string, string> = {
  rest: "var(--green)",
  active: "var(--accent)",
  timed: "var(--gold)",
  triggered: "var(--orange)",
};


// A blank profile: all 10 canonical poses present, walk+idle enabled (required).
export function blankProfile(): MotionProfileFile {
  const poses: MotionProfileFile["poses"] = {};
  for (const p of CANONICAL_POSES) {
    const required = (REQUIRED_POSES as readonly string[]).includes(p);
    poses[p] = required
      ? { enabled: true, runtime_role: p === "idle" ? "rest" : "active", action: "", suffix: "" }
      : { enabled: false };
  }
  // view is required at write time (SPEC_BUNDLE_MOTION_CONTRACT §3.3); seed today's
  // prompt discipline. loop/timed_buffer_ms are per-pose and default-inert, so a fresh
  // profile needs neither until a pose becomes `triggered` (the role select sets loop).
  return {
    key: "", level: 3, movement_class: "", keywords: [], poses,
    view: { view_kind: "side", native_facing: "right", mirroring_policy: "flip" },
  };
}

export function ProfileEditor({ draft, setDraft, errors, busy, defaultKey, onSave, onCancel }: {
  draft: Draft; setDraft: (d: Draft) => void; errors: string[]; busy: boolean;
  defaultKey: string; onSave: () => void; onCancel: () => void;
}) {
  const { profile, label, editingKey } = draft;
  const editingDefault = editingKey === defaultKey;

  // Prompt-preview state. The templates are static content — fetched once; if the call
  // fails the preview simply doesn't render and the form works exactly as before.
  const templates = useMotionPromptTemplates();
  const [sampleAnimal, setSampleAnimal] = useState("red dragon");
  // Which still template the preview shows: a typed pet draws from scratch (base),
  // a designed one is redrawn from the still the user locked (remix) — factory.py:741.
  const [stillVariant, setStillVariant] = useState<"base" | "remix">("base");

  function set<K extends keyof MotionProfileFile>(k: K, v: MotionProfileFile[K]) {
    setDraft({ ...draft, profile: { ...profile, [k]: v } });
  }
  function setPose(name: string, patch: Partial<MotionProfileFile["poses"][string]>) {
    setDraft({ ...draft, profile: { ...profile, poses: { ...profile.poses, [name]: { ...profile.poses[name], ...patch } } } });
  }

  const inputStyle = { background: "#1c1c1c", border: "1px solid var(--line)", color: "var(--heading)" };
  const labelCls = "mono mb-1 block text-xs tracking-wide";

  return (
    <>
      <div id="profile-editor-title" className="mb-3 text-lg font-semibold" style={{ color: "var(--heading)" }}>
        {editingKey ? `Editing ${editingKey}` : "New profile"}
      </div>

      {errors.length > 0 && (
        <div className="mb-4 rounded-lg border p-3" style={{ background: "rgba(239,68,68,0.08)", borderColor: "rgba(239,68,68,0.4)" }}>
          <div className="mono mb-1 text-xs" style={{ color: "var(--accent)" }}>fix these before saving:</div>
          <ul className="mono list-disc pl-5 text-xs" style={{ color: "var(--accent)" }}>
            {errors.map((e, i) => <li key={i}>{e}</li>)}
          </ul>
        </div>
      )}

      {editingDefault && (
        <div className="mono mb-4 rounded-lg border p-2 text-xs" style={{ background: "rgba(251,146,60,0.1)", color: "var(--orange)", borderColor: "rgba(251,146,60,0.35)" }}>
          This is the default profile — editing walk/idle changes the baseline every un-matched animal uses.
        </div>
      )}

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={labelCls} style={{ color: "var(--muted)" }}>key {editingKey && "(locked — rename = duplicate + delete)"}</label>
          <input value={profile.key} disabled={!!editingKey}
            onChange={(e) => set("key", e.target.value)}
            className="w-full rounded-lg px-3 py-2 text-sm outline-none disabled:opacity-60" style={inputStyle} />
        </div>
        <div>
          <div className="mb-1 flex items-center gap-1.5">
            <label className="mono text-xs tracking-wide" style={{ color: "var(--muted)" }}>label</label>
            <FieldHelp term="the label">
              <strong style={{ color: "var(--heading)" }}>This is what the AI reads.</strong> When someone
              types an animal, a fast model picks the body type from one line per profile —{" "}
              <span className="mono" style={{ color: "var(--faint)" }}>key — label (movement_class)</span>{" "}
              — so the label is the <em>only</em> description of this body type it ever sees.
              <br /><br />
              Write it as a body plan and gait (&quot;two legs, wings are the forelimbs…&quot;), not a short
              caption. It is never shown to end users — the pose menu returns only the key.
            </FieldHelp>
          </div>
          <input value={label} onChange={(e) => setDraft({ ...draft, label: e.target.value })}
            className="w-full rounded-lg px-3 py-2 text-sm outline-none" style={inputStyle} />
        </div>
        <div>
          <label className={labelCls} style={{ color: "var(--muted)" }}>level (1–4)</label>
          <select value={profile.level} onChange={(e) => set("level", Number(e.target.value))}
            className="w-full rounded-lg px-3 py-2 text-sm outline-none" style={inputStyle}>
            {[1, 2, 3, 4].map((l) => <option key={l} value={l}>{l}</option>)}
          </select>
        </div>
        <div>
          <label className={labelCls} style={{ color: "var(--muted)" }}>movement_class</label>
          <input value={profile.movement_class} onChange={(e) => set("movement_class", e.target.value)}
            className="w-full rounded-lg px-3 py-2 text-sm outline-none" style={inputStyle} />
        </div>
      </div>

      <div className="mt-3 mb-1 flex items-center gap-1.5">
        <label className="mono text-xs tracking-wide" style={{ color: "var(--muted)" }}>
          keywords (comma-separated; must be globally unique)
        </label>
        <FieldHelp term="keywords">
          <strong style={{ color: "var(--heading)" }}>The offline fallback — the AI never sees these.</strong>{" "}
          They are used only when the classifier can&apos;t answer: no API key, an engine error, or it
          returns a key that isn&apos;t in the registry.
          <br /><br />
          Then the animal name is matched against these words directly — case-insensitive, on word
          boundaries. Across all profiles the most specific <span className="mono">level</span> wins,
          and within a level the longest matching keyword wins. No match anywhere → the default profile.
          <br /><br />
          So a long keyword list does nothing for normal (AI) resolution; the{" "}
          <span className="mono">label</span> is the lever for that.
        </FieldHelp>
      </div>
      <input value={profile.keywords.join(", ")}
        onChange={(e) => set("keywords", e.target.value.split(",").map((s) => s.trim()).filter(Boolean))}
        className="w-full rounded-lg px-3 py-2 text-sm outline-none" style={inputStyle} />

      {/* Pose rows */}
      <div className="mono mt-5 mb-2 text-xs tracking-wide" style={{ color: "var(--muted)" }}>poses (all 10 canonical; walk + idle are always enabled)</div>
      <div className="mono mb-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs" style={{ color: "var(--faint)" }}>
        {POSE_ROLES.map((r) => (
          <span key={r} className="flex items-center gap-1.5">
            <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: ROLE_TINT[r] ?? "var(--line)" }} />
            {r}
          </span>
        ))}
      </div>
      {templates && (
        <div className="mono mb-3 flex flex-wrap items-center gap-2 text-xs" style={{ color: "var(--faint)" }}>
          <span>preview prompts for</span>
          <input value={sampleAnimal} onChange={(e) => setSampleAnimal(e.target.value)}
            placeholder="an animal" className="w-40 rounded px-2 py-1 text-xs outline-none" style={inputStyle} />
          <span>drawn</span>
          <span className="flex overflow-hidden rounded border" style={{ borderColor: "var(--line)" }}>
            {([["base", "from scratch"], ["remix", "from a locked still"]] as const).map(([v, text]) => (
              <button key={v} type="button" onClick={() => setStillVariant(v)}
                className="px-2 py-1 text-xs"
                style={{
                  background: stillVariant === v ? "var(--line)" : "transparent",
                  color: stillVariant === v ? "var(--heading)" : "var(--faint)",
                }}>
                {text}
              </button>
            ))}
          </span>
        </div>
      )}
      <div className="flex flex-col gap-2">
        {CANONICAL_POSES.map((name, i) => {
          const pose = profile.poses[name] ?? { enabled: false };
          const required = (REQUIRED_POSES as readonly string[]).includes(name);
          // Alternating card shade = where one pose ends and the next begins; the left
          // edge carries the role tint. Disabled poses recede so the built set reads first.
          const tint = pose.enabled ? (ROLE_TINT[pose.runtime_role ?? "active"] ?? "var(--line)") : "var(--line)";
          const anchor = pose.control?.kind === "pose_prompt" ? (pose.control.pose ?? "").trim() : "";
          return (
            <div key={name} className="rounded-lg border border-l-4 p-2.5"
              style={{
                borderColor: "var(--line)", borderLeftColor: tint,
                background: i % 2 === 0 ? "#151515" : "#1b1b1b",
                opacity: pose.enabled ? 1 : 0.6,
              }}>
              <div className="flex items-center gap-3">
                <label className="mono flex w-24 items-center gap-2 text-sm font-semibold capitalize" style={{ color: "var(--heading)" }}>
                  <input type="checkbox" checked={!!pose.enabled} disabled={required}
                    onChange={(e) => setPose(name, { enabled: e.target.checked })} />
                  {name}{required && " *"}
                </label>
                {pose.enabled && (
                  // A `triggered` reaction is one-shot; everything else loops. Setting
                  // loop alongside the role keeps the profile write-valid (§3.1) without a
                  // separate control the operator could forget.
                  <select value={pose.runtime_role ?? "active"}
                    onChange={(e) => setPose(name, { runtime_role: e.target.value, loop: e.target.value !== "triggered" })}
                    className="rounded px-2 py-1 text-xs outline-none" style={{ ...inputStyle, color: tint }}>
                    {POSE_ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                  </select>
                )}
              </div>
              {pose.enabled && (
                <div className="mt-2 flex flex-col gap-2">
                  {/* Standing labels, not placeholders: a placeholder vanishes the moment
                      the field is filled, i.e. exactly when you need to know which box
                      you're reading. action + suffix concatenate into the motion prompt. */}
                  <div>
                    <label className={labelCls} style={{ color: "var(--faint)" }}>action — what it is doing</label>
                    <input placeholder="e.g. walking on its legs" value={pose.action ?? ""}
                      onChange={(e) => setPose(name, { action: e.target.value })}
                      className="w-full rounded px-2 py-1 text-xs outline-none" style={inputStyle} />
                  </div>
                  <div>
                    <label className={labelCls} style={{ color: "var(--faint)" }}>suffix — prompt tail: name the limb that moves</label>
                    <textarea placeholder="e.g. , full walk cycle in place: legs cycling…" value={pose.suffix ?? ""}
                      onChange={(e) => setPose(name, { suffix: e.target.value })}
                      className="min-h-[44px] w-full resize-y rounded px-2 py-1 text-xs outline-none" style={inputStyle} />
                  </div>
                  {/* Read-only: the anchor is authored in the Motion Lab, where you can see
                      it drawn. Shown here so the pose's full recipe is legible in one place. */}
                  <div className="mono text-xs leading-relaxed" style={{ color: "var(--faint)" }}>
                    <span style={{ color: "var(--muted)" }}>anchor still</span> (read-only — author in the Motion Lab):{" "}
                    {anchor || <span style={{ color: "var(--faint)" }}>none — this pose animates from the shared base pose</span>}
                  </div>
                  {templates && (
                    <PromptPreview pose={name} templates={templates} animal={sampleAnimal}
                      stillVariant={stillVariant} anchor={anchor}
                      basePose={profile.base_pose ?? templates.still.default_pose}
                      action={pose.action ?? ""} suffix={pose.suffix ?? ""} labelCls={labelCls} />
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Read-only JSON preview */}
      <details className="mt-4">
        <summary className="mono cursor-pointer text-xs" style={{ color: "var(--faint)" }}>raw JSON (preview — what will be written)</summary>
        <pre className="mono mt-2 overflow-x-auto rounded-lg p-3 text-xs" style={{ background: "#0c0c0c", color: "var(--muted)", border: "1px solid var(--line)" }}>
          {JSON.stringify(profile, null, 2)}
        </pre>
      </details>

      <div className="mt-4 flex gap-3">
        <button onClick={onSave} disabled={busy}
          className="mono rounded-lg py-2.5 px-5 text-sm font-bold disabled:opacity-45"
          style={{ background: "linear-gradient(135deg, #6366f1, #4f46e5)", color: "var(--heading)" }}>
          {busy ? "Saving…" : "Save"}
        </button>
        <button onClick={onCancel} className="mono rounded-lg border px-5 py-2.5 text-sm font-semibold" style={{ color: "var(--muted)", borderColor: "var(--line)" }}>
          Cancel
        </button>
      </div>
    </>
  );
}

/**
 * The two prompts this pose will actually send, assembled live from the draft. Collapsed
 * by default — it answers "what does my clause/suffix turn into?", which you want on
 * demand, not on every row at once.
 *
 * The still and the motion are separate generation calls (factory.py Phase A / Phase B):
 * Z-Image paints the frozen shot, then Wan animates ~16 frames out of it. Seeing them
 * stacked is the point — the anchor's posture and the suffix's verbs have to agree, and
 * a mismatch between them is the failure the winged_flyer walk bug was made of.
 */
function PromptPreview({ pose, templates, animal, stillVariant, anchor, basePose, action, suffix, labelCls }: {
  pose: string;
  templates: MotionPromptTemplates;
  animal: string;
  stillVariant: "base" | "remix";
  anchor: string;
  basePose: string;
  action: string;
  suffix: string;
  labelCls: string;
}) {
  const stillTemplate = stillVariant === "base" ? templates.still.base : templates.still.remix;
  const stillOrigin = stillVariant === "base"
    ? "prompt_templates.BASE_STILL_TEMPLATE" : "prompt_templates.REMIX_STILL_TEMPLATE";
  // No anchor clause ⇒ the factory reuses the ONE shared base still for this pose
  // (factory.py: `if not clause: pose_starts[name] = base`), whose posture is base_pose.
  const stillPose = anchor || basePose;
  const stillValues = { animal, pose: stillPose };
  const motionValues = { animal, action, suffix };
  // Assembled by default; "show pieces" unstacks the same prompt into template + each
  // slot + result, so where every word came from is visible without leaving the page.
  const [pieces, setPieces] = useState(false);
  const preCls = "mono mt-1 whitespace-pre-wrap break-words rounded p-2 text-xs leading-relaxed";
  const preStyle = { background: "#0c0c0c", border: "1px solid var(--line)", color: "var(--faint)" };
  return (
    <details className="mt-1">
      <summary className="mono cursor-pointer text-xs" style={{ color: "var(--muted)" }}>
        full prompt preview
      </summary>
      <div className="mt-2">
        <div className="mb-2 flex justify-end">
          <button type="button" onClick={() => setPieces(!pieces)}
            className="mono rounded border px-2 py-1 text-xs"
            style={{
              borderColor: "var(--line)",
              background: pieces ? "var(--line)" : "transparent",
              color: pieces ? "var(--heading)" : "var(--faint)",
            }}>
            {pieces ? "⊟ hide pieces" : "⊞ show pieces"}
          </button>
        </div>
        {/* Edge-coloured to match the Prompt templates tab: indigo = the Z-Image still,
            purple = the Wan loop. Same two colours everywhere a prompt is shown. */}
        <div className="rounded border border-l-4 p-2"
          style={{ borderColor: "var(--line)", borderLeftColor: CALL_TINT.still, background: "#141414" }}>
          <div className={labelCls} style={{ color: CALL_TINT.still }}>
            1 · still prompt → Z-Image {anchor ? `(draws the ${pose} anchor)` : "(no anchor — the shared base still, reused as-is)"}
          </div>
          {pieces ? (
            <PromptPieces call="still" template={stillTemplate} templateOrigin={stillOrigin}
              values={stillValues} />
          ) : (
            <div className={preCls} style={preStyle}>{renderPrompt(stillTemplate, stillValues)}</div>
          )}
        </div>
        <div className="mt-2 rounded border border-l-4 p-2"
          style={{ borderColor: "var(--line)", borderLeftColor: CALL_TINT.motion, background: "#141414" }}>
          <div className={labelCls} style={{ color: CALL_TINT.motion }}>
            2 · motion prompt → Wan 2.2 I2V (paints ~16 frames out of that still)
          </div>
          {pieces ? (
            <PromptPieces call="motion" template={templates.motion.template}
              templateOrigin="motion_profiles.MOTION_PROMPT_TEMPLATE"
              values={motionValues} />
          ) : (
            <div className={preCls} style={preStyle}>{renderPrompt(templates.motion.template, motionValues)}</div>
          )}
        </div>
        <div className="mono mt-2 text-xs leading-relaxed" style={{ color: "var(--faint)" }}>
          <span style={{ color: CALL_TINT.still }}>indigo</span> = the still call ·{" "}
          <span style={{ color: CALL_TINT.motion }}>purple</span> = the motion call
          <br />
          inside a prompt: faint = the template ·{" "}
          <span style={{ color: "var(--orange)" }}>orange</span> = this profile ·{" "}
          <span style={{ color: "var(--green)" }}>green</span> = the animal the user asked for
        </div>
      </div>
    </details>
  );
}
