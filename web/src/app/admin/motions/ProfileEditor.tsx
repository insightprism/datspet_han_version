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
import {
  CANONICAL_POSES, REQUIRED_POSES, POSE_ROLES,
  type MotionProfileFile,
} from "@/lib/api";

export type Draft = { profile: MotionProfileFile; label: string; editingKey: string | null };

// A blank profile: all 10 canonical poses present, walk+idle enabled (required).
export function blankProfile(): MotionProfileFile {
  const poses: MotionProfileFile["poses"] = {};
  for (const p of CANONICAL_POSES) {
    const required = (REQUIRED_POSES as readonly string[]).includes(p);
    poses[p] = required
      ? { enabled: true, runtime_role: p === "idle" ? "rest" : "active", action: "", suffix: "" }
      : { enabled: false };
  }
  return { key: "", level: 3, movement_class: "", keywords: [], poses };
}

export function ProfileEditor({ draft, setDraft, errors, busy, defaultKey, onSave, onCancel }: {
  draft: Draft; setDraft: (d: Draft) => void; errors: string[]; busy: boolean;
  defaultKey: string; onSave: () => void; onCancel: () => void;
}) {
  const { profile, label, editingKey } = draft;
  const editingDefault = editingKey === defaultKey;

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
          <label className={labelCls} style={{ color: "var(--muted)" }}>label</label>
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

      <label className={`${labelCls} mt-3`} style={{ color: "var(--muted)" }}>keywords (comma-separated; must be globally unique)</label>
      <input value={profile.keywords.join(", ")}
        onChange={(e) => set("keywords", e.target.value.split(",").map((s) => s.trim()).filter(Boolean))}
        className="w-full rounded-lg px-3 py-2 text-sm outline-none" style={inputStyle} />

      {/* Pose rows */}
      <div className="mono mt-5 mb-2 text-xs tracking-wide" style={{ color: "var(--muted)" }}>poses (all 10 canonical; walk + idle are always enabled)</div>
      <div className="flex flex-col gap-2">
        {CANONICAL_POSES.map((name) => {
          const pose = profile.poses[name] ?? { enabled: false };
          const required = (REQUIRED_POSES as readonly string[]).includes(name);
          return (
            <div key={name} className="rounded-lg border p-2" style={{ borderColor: "var(--line)", background: "#151515" }}>
              <div className="flex items-center gap-3">
                <label className="mono flex w-24 items-center gap-2 text-xs capitalize" style={{ color: "var(--heading)" }}>
                  <input type="checkbox" checked={!!pose.enabled} disabled={required}
                    onChange={(e) => setPose(name, { enabled: e.target.checked })} />
                  {name}{required && " *"}
                </label>
                {pose.enabled && (
                  <select value={pose.runtime_role ?? "active"} onChange={(e) => setPose(name, { runtime_role: e.target.value })}
                    className="rounded px-2 py-1 text-xs outline-none" style={inputStyle}>
                    {POSE_ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                  </select>
                )}
              </div>
              {pose.enabled && (
                <div className="mt-2 flex flex-col gap-2">
                  <input placeholder="action (e.g. walking)" value={pose.action ?? ""}
                    onChange={(e) => setPose(name, { action: e.target.value })}
                    className="w-full rounded px-2 py-1 text-xs outline-none" style={inputStyle} />
                  <textarea placeholder="suffix (prompt tail, e.g. ', side profile…')" value={pose.suffix ?? ""}
                    onChange={(e) => setPose(name, { suffix: e.target.value })}
                    className="min-h-[44px] w-full resize-y rounded px-2 py-1 text-xs outline-none" style={inputStyle} />
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
