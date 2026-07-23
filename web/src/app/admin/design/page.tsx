"use client";

/**
 * Design admin (SPEC_PET_DESIGN_AXES_ADMIN §3) — deliberately the motion admin,
 * applied to design. One page, two tabs, because to the look owner it is one
 * job ("configure how pets can be designed"):
 *
 *   Features — the axis vocabulary (design_axes/): options, fragments, slots.
 *   Animals  — each animal's design profile (the catalog's surface tags +
 *              per-breed option restrictions).
 *
 * Every write is validated server-side against the exact guard-test contract
 * (validate_axis / validate_design_profile), so this UI can't produce data the
 * build would reject. Gate: on mount it calls the admin API; a 401 bounces to
 * the host admin-launch. Reads work anywhere; writes 409 on read-only prod.
 *
 * Duplicate is CLIENT-side (prefill the editor as a create), unlike motion's
 * server-side clone: a surface axis's applies_to is unique, so a written clone
 * would be invalid until edited — prefill lets the admin fix it before it exists.
 */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  designAdmin, getDatsmeSession, AdminApiError,
  type DesignAdminAxisList, type DesignAdminAnimals, type DesignAxisFile,
  type DesignAxisSummary,
  type DesignAxisOption, type DesignCalibrationStatus,
} from "@/lib/api";
import ConfirmModal from "@/components/ConfirmModal";

/**
 * The recalibration reminder, read-time derived (SPEC_PET_DESIGN_AXES_CALIBRATION
 * §6, decision 0.2 — never a hand-set flag). An axis is "uncalibrated" when any
 * of its option cells is missing or stale; the badge points the look owner at
 * the §5 heal command. The whole loop is a dev-box act — the browser only ever
 * DISPLAYS this, it can't render.
 */
const HEAL_COMMAND = "source pet_env.sh && .venv/bin/python scripts/calibrate_design_axes.py";

function staleAxisKeys(status: DesignCalibrationStatus | null): Set<string> {
  const stale = new Set<string>();
  if (!status?.available) return stale;
  for (const c of status.cells) {
    if (c.verdict !== "current" && c.axis) stale.add(c.axis);
  }
  return stale;
}

/**
 * Whether ANYTHING needs recalibration — including combo and _base cells, which
 * carry no axis and so never light a per-axis pill (Finding 4c). Without this,
 * a stale combo would leave the page with no reminder at all. A substrate change
 * (whole-record stale) also lands here.
 */
function anyStale(status: DesignCalibrationStatus | null): boolean {
  if (!status?.available) return false;
  return (status.substrate_mismatch?.length ?? 0) > 0
    || status.cells.some((c) => c.verdict !== "current");
}

function blankAxis(): DesignAxisFile {
  return {
    _doc: "",
    axis: "",
    label: "",
    kind: "universal",
    default: "natural",
    clause_slot: 50,
    position: "prefix",
    min_strength: null,
    options: [{ key: "natural", label: "Natural", prompt_fragment: "" }],
  };
}

type Draft = { axis: DesignAxisFile; editingKey: string | null };
type Tab = "features" | "animals";

const inputStyle = { background: "#1c1c1c", border: "1px solid var(--line)", color: "var(--heading)" };
const labelCls = "mono mb-1 block text-xs tracking-wide";

export default function DesignAdminPage() {
  const [tab, setTab] = useState<Tab>("features");
  const [list, setList] = useState<DesignAdminAxisList | null>(null);
  const [animals, setAnimals] = useState<DesignAdminAnimals | null>(null);
  const [calibration, setCalibration] = useState<DesignCalibrationStatus | null>(null);
  const [gateState, setGateState] = useState<"checking" | "ok" | "denied">("checking");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [notice, setNotice] = useState("");
  const [confirmDel, setConfirmDel] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    const [l, a] = await Promise.all([designAdmin.listAxes(), designAdmin.animals()]);
    setList(l);
    setAnimals(a);
    setGateState("ok");
    // Calibration status is advisory — a failure here must never block the
    // editor, so it is fetched separately and swallowed.
    designAdmin.calibrationStatus().then(setCalibration).catch(() => setCalibration(null));
  }, []);

  // Gate on mount. A 401 → bounce to the host admin-launch (return here).
  useEffect(() => {
    refresh().catch(async (e) => {
      if (e instanceof AdminApiError && (e.status === 401 || e.status === 403)) {
        const s = await getDatsmeSession().catch(() => null);
        const origin = s?.signin_url ? new URL(s.signin_url).origin : "";
        if (origin) {
          window.location.href = `${origin}/api/integrations/admin-launch?return=/admin/design`;
          return;
        }
        setGateState("denied");
      } else {
        setNotice("Could not load the design registry.");
        setGateState("denied");
      }
    });
  }, [refresh]);

  function startNew() {
    setErrors([]);
    setDraft({ axis: blankAxis(), editingKey: null });
  }

  async function startEdit(key: string) {
    setErrors([]);
    setNotice("");
    const d = await designAdmin.getAxis(key);
    setDraft({ axis: d.axis, editingKey: key });
  }

  async function startDuplicate(key: string) {
    setErrors([]);
    const d = await designAdmin.getAxis(key);
    // Client-side clone (see the header comment): blank the key, drop the
    // unique applies_to claim, and open as a CREATE for the admin to finish.
    const clone: DesignAxisFile = { ...d.axis, axis: "" };
    delete clone.applies_to;
    if (clone.kind === "surface") clone.kind = "universal";
    setDraft({ axis: clone, editingKey: null });
    setNotice(`Editing a copy of "${key}" — give it a key (and surface, if any), then Save.`);
  }

  async function save() {
    if (!draft) return;
    setBusy(true);
    setErrors([]);
    try {
      if (draft.editingKey) {
        await designAdmin.updateAxis(draft.editingKey, draft.axis);
      } else {
        await designAdmin.createAxis(draft.axis);
      }
      setNotice("Saved — live now: the design step serves this immediately.");
      setDraft(null);
      await refresh();
    } catch (e) {
      setErrors(e instanceof AdminApiError && e.errors.length ? e.errors
        : [e instanceof Error ? e.message : "Save failed."]);
    } finally {
      setBusy(false);
    }
  }

  async function doDelete(key: string) {
    setConfirmDel(null);
    try {
      await designAdmin.removeAxis(key);
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

  const writable = !!list?.writable;
  const stale = staleAxisKeys(calibration);
  const needsRecal = anyStale(calibration);

  return (
    <main>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-4">
          <h1 className="text-2xl" style={{ color: "var(--heading)" }}>Design</h1>
          <div className="flex gap-1">
            {(["features", "animals"] as Tab[]).map((t) => (
              <button key={t} onClick={() => setTab(t)}
                className="mono rounded-lg border px-3 py-1.5 text-xs font-semibold capitalize"
                style={tab === t
                  ? { background: "rgba(99,102,241,0.12)", color: "var(--accent)", borderColor: "rgba(99,102,241,0.4)" }
                  : { color: "var(--muted)", borderColor: "var(--line)" }}>
                {t}
              </button>
            ))}
          </div>
        </div>
        <div className="flex items-center gap-3">
          {list && !writable && (
            <span className="mono rounded-full border px-3 py-1 text-xs" style={{ background: "rgba(251,146,60,0.1)", color: "var(--orange)", borderColor: "rgba(251,146,60,0.35)" }}>
              read-only instance — author on dev
            </span>
          )}
          {tab === "features" && (
            <button onClick={startNew} disabled={!writable}
              className="mono rounded-lg border px-4 py-2 text-sm font-semibold disabled:opacity-45"
              style={{ background: "rgba(99,102,241,0.12)", color: "var(--accent)", borderColor: "rgba(99,102,241,0.4)" }}>
              + New axis
            </button>
          )}
        </div>
      </div>

      {notice && <div className="mono mb-4 text-sm" style={{ color: "var(--green)" }}>{notice}</div>}

      {tab === "features" && needsRecal && (
        <div className="mono mb-4 rounded-lg border p-3 text-xs" style={{ background: "rgba(251,146,60,0.1)", color: "var(--orange)", borderColor: "rgba(251,146,60,0.35)" }}>
          <div className="mb-1 font-semibold">
            {calibration?.substrate_mismatch?.length
              ? "The render substrate changed — the whole calibration record is stale."
              : stale.size > 0
                ? `${stale.size} ${stale.size > 1 ? "axes need" : "axis needs"} recalibration — `
                  + "an option was added or a fragment changed since the last render."
                : "A combo or baseline cell needs recalibration since the last render."}
          </div>
          <div style={{ color: "var(--muted)" }}>Re-measure on a dev box, then review the sheets:</div>
          <code className="mt-1 block select-all rounded px-2 py-1" style={{ background: "#0c0c0c", color: "var(--heading)" }}>{HEAL_COMMAND}</code>
        </div>
      )}

      {tab === "features" && (
        <div className="grid gap-6" style={{ gridTemplateColumns: draft ? "minmax(220px, 300px) 1fr" : "1fr" }}>
          <div className="flex flex-col gap-2">
            {list?.axes.map((a) => (
              <AxisRow key={a.key} a={a} writable={writable} uncalibrated={stale.has(a.key)}
                onEdit={() => startEdit(a.key)} onDup={() => startDuplicate(a.key)}
                onDel={() => setConfirmDel(a.key)} active={draft?.editingKey === a.key} />
            ))}
          </div>
          {draft && (
            <AxisEditor draft={draft} setDraft={setDraft} errors={errors} busy={busy}
              onSave={save} onCancel={() => { setDraft(null); setErrors([]); }} />
          )}
        </div>
      )}

      {tab === "animals" && animals && (
        <AnimalsTab animals={animals} onSaved={async (msg) => { setNotice(msg); await refresh(); }} />
      )}

      <ConfirmModal
        open={confirmDel !== null}
        title={`Delete "${confirmDel}"?`}
        body="This removes the axis file and its registry entry; the design step stops offering it immediately. A surface axis still used by catalog animals will refuse."
        onConfirm={() => confirmDel && doDelete(confirmDel)}
        onCancel={() => setConfirmDel(null)}
      />
    </main>
  );
}

function AxisRow({ a, writable, uncalibrated, onEdit, onDup, onDel, active }: {
  a: DesignAxisSummary; writable: boolean; uncalibrated: boolean; active: boolean;
  onEdit: () => void; onDup: () => void; onDel: () => void;
}) {
  return (
    <div className="card p-3" style={active ? { borderColor: "var(--accent)" } : undefined}>
      <div>
        <span className="font-semibold" style={{ color: "var(--heading)" }}>{a.key}</span>
        <span className="mono ml-2 text-xs" style={{ color: a.kind === "surface" ? "var(--gold)" : "var(--faint)" }}>
          {a.kind === "surface" ? `surface: ${a.applies_to}` : "universal"}
        </span>
        {uncalibrated && (
          <span className="mono ml-2 rounded-full px-2 py-0.5 text-xs" style={{ background: "rgba(251,146,60,0.15)", color: "var(--orange)" }}
            title="an option is missing or stale in the calibration record — re-measure on a dev box">
            uncalibrated
          </span>
        )}
        <div className="mono text-xs" style={{ color: "var(--faint)" }}>
          {a.option_count} options · slot {a.clause_slot} · {a.position}
          {a.min_strength != null && ` · min ${a.min_strength}`}
        </div>
        {a.used_by.length > 0 && (
          <div className="mono text-xs" style={{ color: "var(--faint)" }}>used by: {a.used_by.join(", ")}</div>
        )}
      </div>
      <div className="mt-2 flex gap-2">
        <button onClick={onEdit} className="mono rounded border px-2 py-1 text-xs" style={{ color: "var(--accent)", borderColor: "var(--line)" }}>Edit</button>
        <button onClick={onDup} disabled={!writable} className="mono rounded border px-2 py-1 text-xs disabled:opacity-40" style={{ color: "var(--gold)", borderColor: "var(--line)" }}>Duplicate</button>
        <button onClick={onDel} disabled={!writable || a.used_by.length > 0}
          className="mono rounded border px-2 py-1 text-xs disabled:opacity-40"
          style={{ color: "var(--accent)", borderColor: "var(--line)" }}
          title={a.used_by.length ? "still used by catalog animals — retag them first" : undefined}>
          Delete
        </button>
      </div>
    </div>
  );
}

function AxisEditor({ draft, setDraft, errors, busy, onSave, onCancel }: {
  draft: Draft; setDraft: (d: Draft) => void; errors: string[]; busy: boolean;
  onSave: () => void; onCancel: () => void;
}) {
  const { axis, editingKey } = draft;

  function set<K extends keyof DesignAxisFile>(k: K, v: DesignAxisFile[K]) {
    setDraft({ ...draft, axis: { ...axis, [k]: v } });
  }
  function setOption(i: number, patch: Partial<DesignAxisFile["options"][number]>) {
    const options = axis.options.map((o, j) => (j === i ? { ...o, ...patch } : o));
    setDraft({ ...draft, axis: { ...axis, options } });
  }
  function moveOption(i: number, delta: number) {
    const j = i + delta;
    if (j < 0 || j >= axis.options.length) return;
    const options = [...axis.options];
    [options[i], options[j]] = [options[j], options[i]];
    setDraft({ ...draft, axis: { ...axis, options } });
  }

  return (
    <div className="card p-5">
      <div className="mb-3 text-lg font-semibold" style={{ color: "var(--heading)" }}>
        {editingKey ? `Editing ${editingKey}` : "New axis"}
      </div>

      {errors.length > 0 && (
        <div className="mb-4 rounded-lg border p-3" style={{ background: "rgba(239,68,68,0.08)", borderColor: "rgba(239,68,68,0.4)" }}>
          <div className="mono mb-1 text-xs" style={{ color: "var(--accent)" }}>fix these before saving:</div>
          <ul className="mono list-disc pl-5 text-xs" style={{ color: "var(--accent)" }}>
            {errors.map((e, i) => <li key={i}>{e}</li>)}
          </ul>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={labelCls} style={{ color: "var(--muted)" }}>key {editingKey && "(locked — rename = duplicate + delete)"}</label>
          <input value={axis.axis} disabled={!!editingKey}
            onChange={(e) => set("axis", e.target.value)}
            className="w-full rounded-lg px-3 py-2 text-sm outline-none disabled:opacity-60" style={inputStyle} />
        </div>
        <div>
          <label className={labelCls} style={{ color: "var(--muted)" }}>label (the design step&apos;s heading)</label>
          <input value={axis.label} onChange={(e) => set("label", e.target.value)}
            className="w-full rounded-lg px-3 py-2 text-sm outline-none" style={inputStyle} />
        </div>
        <div>
          <label className={labelCls} style={{ color: "var(--muted)" }}>kind</label>
          <select value={axis.kind}
            onChange={(e) => {
              const kind = e.target.value as DesignAxisFile["kind"];
              const next = { ...axis, kind };
              if (kind === "universal") delete next.applies_to;
              setDraft({ ...draft, axis: next });
            }}
            className="w-full rounded-lg px-3 py-2 text-sm outline-none" style={inputStyle}>
            <option value="universal">universal (every animal)</option>
            <option value="surface">surface (one per surface)</option>
          </select>
        </div>
        {axis.kind === "surface" && (
          <div>
            <label className={labelCls} style={{ color: "var(--muted)" }}>applies_to (the catalog surface it serves)</label>
            <input value={axis.applies_to ?? ""} onChange={(e) => set("applies_to", e.target.value)}
              className="w-full rounded-lg px-3 py-2 text-sm outline-none" style={inputStyle} />
          </div>
        )}
        <div>
          <label className={labelCls} style={{ color: "var(--muted)" }}>clause_slot (lower = nearer the noun)</label>
          <input type="number" value={axis.clause_slot}
            onChange={(e) => set("clause_slot", Number(e.target.value))}
            className="w-full rounded-lg px-3 py-2 text-sm outline-none" style={inputStyle} />
        </div>
        <div>
          <label className={labelCls} style={{ color: "var(--muted)" }}>position</label>
          <select value={axis.position} onChange={(e) => set("position", e.target.value as DesignAxisFile["position"])}
            className="w-full rounded-lg px-3 py-2 text-sm outline-none" style={inputStyle}>
            <option value="prefix">prefix (adjective before the noun)</option>
            <option value="suffix">suffix (phrase after the noun)</option>
          </select>
        </div>
        <div>
          <label className={labelCls} style={{ color: "var(--muted)" }}>min_strength (blank = none; 0.3–0.9)</label>
          <input value={axis.min_strength ?? ""}
            onChange={(e) => {
              const v = e.target.value.trim();
              set("min_strength", v === "" ? null : Number(v));
            }}
            className="w-full rounded-lg px-3 py-2 text-sm outline-none" style={inputStyle} />
        </div>
        <div>
          <label className={labelCls} style={{ color: "var(--muted)" }}>default (must have an empty fragment)</label>
          <select value={axis.default} onChange={(e) => set("default", e.target.value)}
            className="w-full rounded-lg px-3 py-2 text-sm outline-none" style={inputStyle}>
            {axis.options.map((o) => <option key={o.key} value={o.key}>{o.key}</option>)}
          </select>
        </div>
      </div>

      <label className={`${labelCls} mt-3`} style={{ color: "var(--muted)" }}>_doc (why this axis is shaped the way it is)</label>
      <textarea value={axis._doc ?? ""} onChange={(e) => set("_doc", e.target.value)}
        className="min-h-[52px] w-full resize-y rounded-lg px-3 py-2 text-xs outline-none" style={inputStyle} />

      <div className="mono mt-5 mb-2 text-xs tracking-wide" style={{ color: "var(--muted)" }}>
        options (the default&apos;s fragment must be empty; every other option must change something)
      </div>
      <div className="flex flex-col gap-2">
        {axis.options.map((o, i) => (
          <div key={i} className="rounded-lg border p-2" style={{ borderColor: "var(--line)", background: "#151515" }}>
            <div className="flex items-center gap-2">
              <input placeholder="key" value={o.key} onChange={(e) => setOption(i, { key: e.target.value })}
                className="w-32 rounded px-2 py-1 text-xs outline-none" style={inputStyle} />
              <input placeholder="label" value={o.label} onChange={(e) => setOption(i, { label: e.target.value })}
                className="w-32 rounded px-2 py-1 text-xs outline-none" style={inputStyle} />
              <input placeholder={o.key === axis.default ? "(default — no words)" : "prompt fragment"}
                value={o.prompt_fragment} onChange={(e) => setOption(i, { prompt_fragment: e.target.value })}
                className="flex-1 rounded px-2 py-1 text-xs outline-none" style={inputStyle} />
              <button onClick={() => moveOption(i, -1)} className="mono px-1 text-xs" style={{ color: "var(--faint)" }} title="move up">↑</button>
              <button onClick={() => moveOption(i, 1)} className="mono px-1 text-xs" style={{ color: "var(--faint)" }} title="move down">↓</button>
              <button onClick={() => setDraft({ ...draft, axis: { ...axis, options: axis.options.filter((_, j) => j !== i) } })}
                className="mono px-1 text-xs" style={{ color: "var(--accent)" }} title="remove">✕</button>
            </div>
          </div>
        ))}
        <button
          onClick={() => setDraft({ ...draft, axis: { ...axis, options: [...axis.options, { key: "", label: "", prompt_fragment: "" }] } })}
          className="mono self-start rounded border px-2 py-1 text-xs" style={{ color: "var(--accent)", borderColor: "var(--line)" }}>
          + add option
        </button>
      </div>

      <details className="mt-4">
        <summary className="mono cursor-pointer text-xs" style={{ color: "var(--faint)" }}>raw JSON (preview — what will be written)</summary>
        <pre className="mono mt-2 overflow-x-auto rounded-lg p-3 text-xs" style={{ background: "#0c0c0c", color: "var(--muted)", border: "1px solid var(--line)" }}>
          {JSON.stringify(axis, null, 2)}
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

// ── Animals tab (§3.2): the per-animal design profile ────────────────────────
//
// Each row writes the classification the design step reads: the surface (which
// surface axis shows) and an optional option restriction. `surface_default` is
// deliberately not offered yet — it persists in the schema but is read-inert
// until its semantics are settled (spec §9.5).
function AnimalsTab({ animals, onSaved }: {
  animals: DesignAdminAnimals;
  onSaved: (msg: string) => Promise<void>;
}) {
  return (
    <div className="flex flex-col gap-4">
      {animals.animals.map((a) => (
        <div key={a.key} className="card p-4">
          <ProfileRow
            title={a.label} entry={a} inherited={null}
            surfaces={animals.surfaces} optionVocab={animals.surface_axis_options}
            writable={animals.writable}
            onSave={(p) => designAdmin.setProfile(a.key, null, p)
              .then(() => onSaved(`Saved ${a.key} — the design step reflects it now.`))}
          />
          <div className="mt-3 flex flex-col gap-3 border-t pt-3" style={{ borderColor: "var(--line)" }}>
            {a.breeds.map((b) => (
              <ProfileRow
                key={b.key} title={`↳ ${b.label}`}
                entry={b} inherited={a.surface}
                surfaces={animals.surfaces} optionVocab={animals.surface_axis_options}
                writable={animals.writable}
                onSave={(p) => designAdmin.setProfile(a.key, b.key, p)
                  .then(() => onSaved(`Saved ${a.key}/${b.key} — the design step reflects it now.`))}
              />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function ProfileRow({ title, entry, inherited, surfaces, optionVocab, writable, onSave }: {
  title: string;
  entry: { surface: string | null; surface_options: string[] | null };
  /** The animal-level surface a breed falls back to; null for animal rows. */
  inherited: string | null;
  surfaces: string[];
  optionVocab: Record<string, DesignAxisOption[]>;
  writable: boolean;
  onSave: (p: { surface: string | null; surface_options: string[] | null }) => Promise<void>;
}) {
  const [surface, setSurface] = useState<string | null>(entry.surface);
  const [restricted, setRestricted] = useState<boolean>(entry.surface_options !== null);
  const [picked, setPicked] = useState<string[]>(entry.surface_options ?? []);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const effective = surface ?? inherited;
  const vocab = (effective ? optionVocab[effective] ?? [] : []).filter((o) => !o.is_default);

  async function save() {
    setSaving(true);
    setError("");
    try {
      await onSave({ surface, surface_options: restricted ? picked : null });
    } catch (e) {
      setError(e instanceof AdminApiError
        ? (e.errors[0] ?? e.message) : "Save failed.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <div className="flex flex-wrap items-center gap-3">
        <span className="w-28 font-semibold" style={{ color: "var(--heading)" }}>{title}</span>
        <label className="mono flex items-center gap-2 text-xs" style={{ color: "var(--muted)" }}>
          surface
          <select value={surface ?? ""} disabled={!writable}
            onChange={(e) => setSurface(e.target.value || null)}
            className="rounded px-2 py-1 text-xs outline-none" style={inputStyle}>
            {inherited && <option value="">inherit ({inherited})</option>}
            {surfaces.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        <label className="mono flex items-center gap-2 text-xs" style={{ color: "var(--muted)" }}>
          <input type="checkbox" checked={restricted} disabled={!writable || !effective}
            onChange={(e) => setRestricted(e.target.checked)} />
          restrict options
        </label>
        {restricted && vocab.map((o) => (
          <label key={o.key} className="mono flex items-center gap-1 text-xs" style={{ color: "var(--muted)" }}>
            <input type="checkbox" checked={picked.includes(o.key)} disabled={!writable}
              onChange={(e) => setPicked(e.target.checked
                ? [...picked, o.key] : picked.filter((k) => k !== o.key))} />
            {o.label}
          </label>
        ))}
        <button onClick={save} disabled={!writable || saving}
          className="mono rounded border px-3 py-1 text-xs font-semibold disabled:opacity-40"
          style={{ color: "var(--accent)", borderColor: "var(--line)" }}>
          {saving ? "Saving…" : "Save"}
        </button>
      </div>
      {error && <div className="mono mt-1 text-xs" style={{ color: "var(--accent)" }}>{error}</div>}
    </div>
  );
}
