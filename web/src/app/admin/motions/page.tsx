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
  motionAdmin, getDatsmeSession, AdminApiError,
  type MotionAdminList, type MotionProfileSummary,
} from "@/lib/api";
import { ProfileEditor, blankProfile, type Draft } from "./ProfileEditor";
import ConfirmModal from "@/components/ConfirmModal";

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
      if (e instanceof AdminApiError && (e.status === 401 || e.status === 403)) {
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
      if (e instanceof AdminApiError) {
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
      setNotice(e instanceof AdminApiError ? e.message : "Duplicate failed.");
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
      setNotice(e instanceof AdminApiError ? e.message : "Delete failed.");
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

        {/* Editor pane — the shared editor is content-only; this page hosts it in a card */}
        {draft && (
          <div className="card p-5">
            <ProfileEditor
              draft={draft} setDraft={setDraft} errors={errors} busy={busy}
              defaultKey={list?.default ?? ""}
              onSave={save} onCancel={() => { setDraft(null); setErrors([]); }}
            />
          </div>
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

