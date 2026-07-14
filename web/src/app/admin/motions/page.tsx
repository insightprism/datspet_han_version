"use client";

/**
 * Motion-profile admin (SPEC_MOTION_PROFILE_ADMIN §5). A two-pane editor for the
 * movement registry: the list of profiles on the left, a strict schema-guided
 * form on the right. Every write is validated server-side against the exact
 * guard-test contract, so the UI can't produce a profile the build would reject.
 *
 * Gate: on mount it calls the admin API; a 401 means "not an admin" → bounce to
 * the host admin-launch, which (for a system_admin) mints an adm token and comes
 * back. Reads work on any instance; writes refuse on a read-only prod tier.
 */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  motionAdmin, getDatsmeSession, MotionAdminError,
  CANONICAL_POSES, REQUIRED_POSES, POSE_ROLES,
  type MotionAdminList, type MotionProfileFile, type MotionProfileSummary,
} from "@/lib/api";
import ConfirmModal from "@/components/ConfirmModal";

// A blank profile: all 10 canonical poses present, walk+idle enabled (required).
function blankProfile(): MotionProfileFile {
  const poses: MotionProfileFile["poses"] = {};
  for (const p of CANONICAL_POSES) {
    const required = (REQUIRED_POSES as readonly string[]).includes(p);
    poses[p] = required
      ? { enabled: true, runtime_role: p === "idle" ? "rest" : "active", action: "", suffix: "" }
      : { enabled: false };
  }
  return { key: "", level: 3, movement_class: "", keywords: [], poses };
}

type Draft = { profile: MotionProfileFile; label: string; editingKey: string | null };

export default function MotionAdminPage() {
  const [list, setList] = useState<MotionAdminList | null>(null);
  const [gateState, setGateState] = useState<"checking" | "ok" | "denied">("checking");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [notice, setNotice] = useState("");
  const [confirmDel, setConfirmDel] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    const l = await motionAdmin.list();
    setList(l);
    setGateState("ok");
  }, []);

  // Gate on mount. A 401 → bounce to the host admin-launch (return here).
  useEffect(() => {
    refresh().catch(async (e) => {
      if (e instanceof MotionAdminError && (e.status === 401 || e.status === 403)) {
        const s = await getDatsmeSession().catch(() => null);
        // signin_url gives us the DatsMe origin; swap login-launch → admin-launch.
        const origin = s?.signin_url ? new URL(s.signin_url).origin : "";
        if (origin) {
          window.location.href = `${origin}/api/integrations/admin-launch?return=/admin/motions`;
          return;
        }
        setGateState("denied");
      } else {
        setNotice("Could not load profiles.");
        setGateState("denied");
      }
    });
  }, [refresh]);

  function startNew() {
    setErrors([]);
    setDraft({ profile: blankProfile(), label: "", editingKey: null });
  }

  async function startEdit(key: string) {
    setErrors([]);
    setNotice("");
    const d = await motionAdmin.get(key);
    setDraft({ profile: d.profile, label: d.label, editingKey: key });
  }

  async function save() {
    if (!draft) return;
    setBusy(true);
    setErrors([]);
    try {
      if (draft.editingKey) {
        await motionAdmin.update(draft.editingKey, draft.profile, draft.label);
      } else {
        await motionAdmin.create(draft.profile, draft.label);
      }
      setNotice("Saved — live now: the pose menu and new generations use this immediately.");
      setDraft(null);
      await refresh();
    } catch (e) {
      if (e instanceof MotionAdminError) {
        setErrors(e.errors.length ? e.errors : [e.message]);
      } else {
        setErrors(["Save failed."]);
      }
    } finally {
      setBusy(false);
    }
  }

  async function duplicate(key: string) {
    const newKey = window.prompt(`Duplicate "${key}" as (new key, lowercase/underscore):`, `${key}_copy`);
    if (!newKey) return;
    try {
      const res = await motionAdmin.duplicate(key, newKey, `Copy of ${key}`);
      await refresh();
      setNotice(`Duplicated to "${newKey}" — add its keywords, then Save.`);
      setDraft({ profile: res.profile, label: `Copy of ${key}`, editingKey: newKey });
    } catch (e) {
      setNotice(e instanceof MotionAdminError ? e.message : "Duplicate failed.");
    }
  }

  async function doDelete(key: string) {
    setConfirmDel(null);
    try {
      await motionAdmin.remove(key);
      if (draft?.editingKey === key) setDraft(null);
      setNotice(`Deleted "${key}".`);
      await refresh();
    } catch (e) {
      setNotice(e instanceof MotionAdminError ? e.message : "Delete failed.");
    }
  }

  if (gateState === "checking") {
    return <main><p className="mono text-sm" style={{ color: "var(--faint)" }}>Checking admin access…</p></main>;
  }
  if (gateState === "denied") {
    return (
      <main>
        <h1 className="mb-2 text-2xl" style={{ color: "var(--heading)" }}>Admin access required</h1>
        <p className="text-sm" style={{ color: "var(--muted)" }}>
          This page is for DatsMe system admins. {notice}
        </p>
        <Link href="/" className="mono mt-4 inline-block text-sm underline" style={{ color: "var(--accent)" }}>← Back to DatsPet</Link>
      </main>
    );
  }

  return (
    <main>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl" style={{ color: "var(--heading)" }}>Motion profiles</h1>
        <div className="flex items-center gap-3">
          {list && !list.writable && (
            <span className="mono rounded-full border px-3 py-1 text-xs" style={{ background: "rgba(251,146,60,0.1)", color: "var(--orange)", borderColor: "rgba(251,146,60,0.35)" }}>
              read-only instance — author on dev
            </span>
          )}
          <button onClick={startNew} disabled={!list?.writable}
            className="mono rounded-lg border px-4 py-2 text-sm font-semibold disabled:opacity-45"
            style={{ background: "rgba(99,102,241,0.12)", color: "var(--accent)", borderColor: "rgba(99,102,241,0.4)" }}>
            + New profile
          </button>
        </div>
      </div>

      {notice && <div className="mono mb-4 text-sm" style={{ color: "var(--green)" }}>{notice}</div>}

      <div className="grid gap-6" style={{ gridTemplateColumns: draft ? "minmax(220px, 300px) 1fr" : "1fr" }}>
        {/* List pane */}
        <div className="flex flex-col gap-2">
          {list?.profiles.map((p) => (
            <ProfileRow key={p.key} p={p} writable={!!list.writable}
              onEdit={() => startEdit(p.key)} onDup={() => duplicate(p.key)}
              onDel={() => setConfirmDel(p.key)} active={draft?.editingKey === p.key} />
          ))}
        </div>

        {/* Editor pane */}
        {draft && (
          <ProfileEditor
            draft={draft} setDraft={setDraft} errors={errors} busy={busy}
            defaultKey={list?.default ?? ""}
            onSave={save} onCancel={() => { setDraft(null); setErrors([]); }}
          />
        )}
      </div>

      <ConfirmModal
        open={confirmDel !== null}
        title={`Delete "${confirmDel}"?`}
        body="This removes the profile file and its registry entry. Animals that resolved to it fall back to a coarser profile."
        onConfirm={() => confirmDel && doDelete(confirmDel)}
        onCancel={() => setConfirmDel(null)}
      />
    </main>
  );
}

function ProfileRow({ p, writable, onEdit, onDup, onDel, active }: {
  p: MotionProfileSummary; writable: boolean; active: boolean;
  onEdit: () => void; onDup: () => void; onDel: () => void;
}) {
  return (
    <div className="card p-3" style={active ? { borderColor: "var(--accent)" } : undefined}>
      <div className="flex items-center justify-between gap-2">
        <div>
          <span className="font-semibold" style={{ color: "var(--heading)" }}>{p.key}</span>
          {p.is_default && <span className="mono ml-2 text-xs" style={{ color: "var(--gold)" }}>default</span>}
          <div className="mono text-xs" style={{ color: "var(--faint)" }}>
            L{p.level} · {p.movement_class} · {p.enabled_poses.length} poses · {p.keyword_count} kw
          </div>
          {p.pinned_by.length > 0 && (
            <div className="mono text-xs" style={{ color: "var(--faint)" }}>pinned by: {p.pinned_by.join(", ")}</div>
          )}
        </div>
      </div>
      <div className="mt-2 flex gap-2">
        <button onClick={onEdit} className="mono rounded border px-2 py-1 text-xs" style={{ color: "var(--accent)", borderColor: "var(--line)" }}>Edit</button>
        <button onClick={onDup} disabled={!writable} className="mono rounded border px-2 py-1 text-xs disabled:opacity-40" style={{ color: "var(--gold)", borderColor: "var(--line)" }}>Duplicate</button>
        <button onClick={onDel} disabled={!writable || p.is_default || p.pinned_by.length > 0}
          className="mono rounded border px-2 py-1 text-xs disabled:opacity-40"
          style={{ color: "var(--accent)", borderColor: "var(--line)" }}
          title={p.is_default ? "the default can't be deleted" : p.pinned_by.length ? "pinned by a catalog entry" : undefined}>
          Delete
        </button>
      </div>
    </div>
  );
}

function ProfileEditor({ draft, setDraft, errors, busy, defaultKey, onSave, onCancel }: {
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
    <div className="card p-5">
      <div className="mb-3 text-lg font-semibold" style={{ color: "var(--heading)" }}>
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
    </div>
  );
}
