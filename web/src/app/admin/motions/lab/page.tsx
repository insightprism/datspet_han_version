"use client";

/**
 * Motion Lab (SPEC_MOTION_LAB, incl. §12 Phase 2 — multi-pose authoring). Tune the
 * pose_prompt clauses (§3.9.1) for MULTIPLE poses at once, all drawn from ONE shared
 * base + seed, so cross-pose colour/style drift is visible before you save.
 *
 * One column per selected pose: clause · anchor still · animation · save. Generation
 * is ASYNC (start → poll /job), with a live elapsed timer and a Cancel button. Several
 * generations may be fired at once — they QUEUE on the serial GPU and read "pending…"
 * until they start. LOCAL backend only. Save is the existing motion_admin write.
 */
import { useEffect, useState } from "react";
import Link from "next/link";
import {
  motionAdmin, motionLab, getDatsmeSession, AdminApiError, CANONICAL_POSES,
  type MotionAdminList, type MotionProfileDetail, type MotionProfileFile, type LabAsset, type LabJob,
} from "@/lib/api";

const DEFAULT_SEED = 42;
const inputStyle = { background: "#1c1c1c", border: "1px solid var(--line)", color: "var(--heading)" };
const labelCls = "mono mb-1 block text-xs tracking-wide";
type Phase = LabJob["phase"];

type Cell = {
  clause: string; still: LabAsset | null; loop: LabAsset | null;
  busy: "" | "draw" | "animate" | "save"; jobId: string | null; elapsed: number; phase: Phase;
};
type Cells = Record<string, Cell>;

const genErr = (e: unknown) => e instanceof AdminApiError ? e.message : "Generation failed — is ComfyUI up?";
const saveErr = (e: unknown) => e instanceof AdminApiError ? (e.errors[0] ?? e.message) : "Save failed.";
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

async function pollJob(jobId: string, onTick: (elapsed: number, phase: Phase) => void): Promise<LabAsset | null> {
  for (;;) {
    const j = await motionLab.job(jobId);
    onTick(j.elapsed, j.phase);
    if (j.state === "done") return { asset_id: j.asset_id ?? "", url: j.url ?? "", ms: j.ms ?? 0 };
    if (j.state === "canceled") return null;
    if (j.state === "error") throw new AdminApiError(j.error ?? "generation failed", 500);
    await sleep(1500);
  }
}

function profileWithClauses(base: MotionProfileFile, clauses: Record<string, string>): MotionProfileFile {
  const p = structuredClone(base);
  for (const [name, raw] of Object.entries(clauses)) {
    const c = raw.trim();
    const pose = { ...p.poses[name] };
    if (c) pose.control = { kind: "pose_prompt", pose: c };
    else delete pose.control;
    p.poses[name] = pose;
  }
  return p;
}

// "pending…" while queued, else "Verbing… 12s"; the idle label otherwise.
const runLabel = (busy: boolean, phase: Phase, elapsed: number, verb: string, idle: string) =>
  !busy ? idle : phase === "pending" ? "pending…" : `${verb}… ${elapsed}s`;

export default function MotionLabPage() {
  const [gate, setGate] = useState<"checking" | "ok" | "denied">("checking");
  const [list, setList] = useState<MotionAdminList | null>(null);
  const [profileKey, setProfileKey] = useState("");
  const [detail, setDetail] = useState<MotionProfileDetail | null>(null);
  const [animal, setAnimal] = useState("robin");
  const [seed, setSeed] = useState(DEFAULT_SEED);
  const [base, setBase] = useState<LabAsset | null>(null);
  const [baseBusy, setBaseBusy] = useState(false);
  const [baseJob, setBaseJob] = useState<string | null>(null);
  const [baseElapsed, setBaseElapsed] = useState(0);
  const [basePhase, setBasePhase] = useState<Phase>("running");
  const [cells, setCells] = useState<Cells>({});
  const [selected, setSelected] = useState<string[]>([]);
  const [busyAll, setBusyAll] = useState<"" | "draw" | "animate" | "save">("");
  const [notice, setNotice] = useState("");
  const [err, setErr] = useState("");

  useEffect(() => {
    motionAdmin.list().then((l) => {
      setList(l);
      setGate("ok");
      const first = l.profiles.find((p) => p.key === "avian") ?? l.profiles[0];
      if (first) setProfileKey(first.key);
    }).catch(async (e) => {
      if (e instanceof AdminApiError && (e.status === 401 || e.status === 403)) {
        const s = await getDatsmeSession().catch(() => null);
        const origin = s?.signin_url ? new URL(s.signin_url).origin : "";
        if (origin) { window.location.href = `${origin}/api/integrations/admin-launch?return=/admin/motions/lab`; return; }
      }
      setGate("denied");
    });
  }, []);

  useEffect(() => {
    if (!profileKey) return;
    motionAdmin.get(profileKey).then((d) => {
      setDetail(d);
      const enabled = CANONICAL_POSES.filter((n) => d.profile.poses[n]?.enabled);
      const next: Cells = {};
      for (const n of enabled) next[n] = { clause: d.profile.poses[n].control?.pose ?? "", still: null, loop: null, busy: "", jobId: null, elapsed: 0, phase: "running" };
      setCells(next);
      const withClause = enabled.filter((n) => d.profile.poses[n].control?.kind === "pose_prompt");
      const def = enabled.filter((n) => ["walk", "idle"].includes(n) || withClause.includes(n));
      setSelected(def.length ? def : enabled.slice(0, 3));
      setBase(null);
    }).catch(() => setDetail(null));
  }, [profileKey]);

  function clearRenders() {
    setBase(null);
    setCells((c) => Object.fromEntries(Object.entries(c).map(([n, cell]) => [n, { ...cell, still: null, loop: null }])));
  }
  const patch = (name: string, p: Partial<Cell>) => setCells((c) => ({ ...c, [name]: { ...c[name], ...p } }));

  // --- core ops: start a job, poll it (timer + phase), return the asset or null (canceled) ---
  async function doDrawBase(): Promise<LabAsset | null> {
    setBaseElapsed(0); setBasePhase("pending");
    const { job_id } = await motionLab.startStill(animal, "", seed);
    setBaseJob(job_id);
    try {
      const a = await pollJob(job_id, (e, ph) => { setBaseElapsed(e); setBasePhase(ph); });
      if (a) setBase(a);
      return a;
    } finally { setBaseJob(null); }
  }
  async function doDrawAnchor(name: string, clause: string): Promise<LabAsset | null> {
    patch(name, { elapsed: 0, phase: "pending" });
    const { job_id } = await motionLab.startStill(animal, clause, seed);
    patch(name, { jobId: job_id });
    try {
      const a = await pollJob(job_id, (e, ph) => patch(name, { elapsed: e, phase: ph }));
      if (a) patch(name, { still: a, loop: null });
      return a;
    } finally { patch(name, { jobId: null }); }
  }
  async function doAnimate(name: string, source: LabAsset): Promise<LabAsset | null> {
    patch(name, { elapsed: 0, phase: "pending" });
    const { job_id } = await motionLab.startAnimate(source.asset_id, animal, profileKey, name, seed);
    patch(name, { jobId: job_id });
    try {
      const a = await pollJob(job_id, (e, ph) => patch(name, { elapsed: e, phase: ph }));
      if (a) patch(name, { loop: a });
      return a;
    } finally { patch(name, { jobId: null }); }
  }

  // --- per-cell buttons (concurrent: firing one does NOT block the others; they queue) ---
  async function drawBase() {
    setBaseBusy(true); setErr("");
    try { await doDrawBase(); } catch (e) { setErr(genErr(e)); } finally { setBaseBusy(false); }
  }
  async function drawAnchor(name: string) {
    const clause = cells[name].clause.trim();
    if (!clause) return;
    patch(name, { busy: "draw" }); setErr("");
    try { await doDrawAnchor(name, clause); } catch (e) { setErr(genErr(e)); } finally { patch(name, { busy: "" }); }
  }
  async function animateOne(name: string) {
    const clause = cells[name].clause.trim();
    const source = clause ? cells[name].still : base;
    if (!source) { setErr(clause ? "Draw this pose's anchor first." : "Draw the base first."); return; }
    patch(name, { busy: "animate" }); setErr("");
    try { await doAnimate(name, source); } catch (e) { setErr(genErr(e)); } finally { patch(name, { busy: "" }); }
  }
  async function saveOne(name: string) {
    if (!detail) return;
    patch(name, { busy: "save" }); setErr(""); setNotice("");
    try {
      await motionAdmin.update(profileKey, profileWithClauses(detail.profile, { [name]: cells[name].clause }), detail.label);
      setNotice(`Saved ${profileKey}.${name} — live now.`);
      setDetail(await motionAdmin.get(profileKey));
    } catch (e) { setErr(saveErr(e)); } finally { patch(name, { busy: "" }); }
  }

  // --- "all" (serial; canceling the running job stops the run) ---
  async function drawAllAnchors() {
    setBusyAll("draw"); setErr("");
    try {
      for (const name of columns) {
        if (!cells[name].clause.trim()) continue;
        patch(name, { busy: "draw" });
        const a = await doDrawAnchor(name, cells[name].clause.trim());
        patch(name, { busy: "" });
        if (!a) break;
      }
    } catch (e) { setErr(genErr(e)); } finally { setBusyAll(""); }
  }
  async function animateAll() {
    setBusyAll("animate"); setErr("");
    try {
      let b = base ?? await doDrawBase();
      if (!b) return;
      for (const name of columns) {
        const clause = cells[name].clause.trim();
        let source = clause ? cells[name].still : b;
        if (clause && !source) { patch(name, { busy: "draw" }); source = await doDrawAnchor(name, clause); patch(name, { busy: "" }); if (!source) break; }
        if (!source) continue;
        patch(name, { busy: "animate" });
        const a = await doAnimate(name, source);
        patch(name, { busy: "" });
        if (!a) break;
      }
    } catch (e) { setErr(genErr(e)); } finally { setBusyAll(""); }
  }
  async function saveAll() {
    if (!detail) return;
    setBusyAll("save"); setErr(""); setNotice("");
    try {
      const clauses = Object.fromEntries(columns.map((n) => [n, cells[n].clause]));
      await motionAdmin.update(profileKey, profileWithClauses(detail.profile, clauses), detail.label);
      setNotice(`Saved ${columns.length} pose(s) to ${profileKey} — live now.`);
      setDetail(await motionAdmin.get(profileKey));
    } catch (e) { setErr(saveErr(e)); } finally { setBusyAll(""); }
  }

  const cancelJob = (jobId: string | null) => { if (jobId) motionLab.cancel(jobId).catch(() => {}); };

  if (gate === "checking") {
    return <main><p className="mono text-sm" style={{ color: "var(--faint)" }}>Checking admin access…</p></main>;
  }
  if (gate === "denied") {
    return (
      <main>
        <h1 className="mb-2 text-2xl" style={{ color: "var(--heading)" }}>Motion Lab unavailable</h1>
        <p className="text-sm" style={{ color: "var(--muted)" }}>
          The Lab is a DatsMe-admin, GPU-dev-box tool — it needs the local generation backend and admin access.
        </p>
        <Link href="/admin/motions" className="mono mt-4 inline-block text-sm underline" style={{ color: "var(--accent)" }}>← Motion profiles</Link>
      </main>
    );
  }

  const enabledPoses = detail ? CANONICAL_POSES.filter((n) => detail.profile.poses[n]?.enabled) : [];
  const columns = CANONICAL_POSES.filter((n) => selected.includes(n) && cells[n]);
  const anyBusy = baseBusy || busyAll !== "" || Object.values(cells).some((c) => c.busy);
  const anyDirty = columns.some((n) => cells[n].clause.trim() !== (detail?.profile.poses[n]?.control?.pose ?? "").trim());

  return (
    <main>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl" style={{ color: "var(--heading)" }}>Motion Lab</h1>
        <Link href="/admin/motions" className="mono text-sm underline" style={{ color: "var(--accent)" }}>← Motion profiles</Link>
      </div>
      <p className="mono mb-4 text-xs" style={{ color: "var(--faint)" }}>
        Author multiple poses from one base + seed and compare them side by side — catch colour/style drift before you save.
      </p>

      {notice && <div className="mono mb-3 text-sm" style={{ color: "var(--green)" }}>{notice}</div>}
      {err && <div className="mono mb-3 text-sm" style={{ color: "var(--accent)" }}>{err}</div>}

      {/* Controls — the shared base lives here, inline with the Draw base button */}
      <div className="card mb-4 flex flex-wrap items-end gap-3 p-4">
        <div className="basis-5/12 min-w-[160px]">
          <label className={labelCls} style={{ color: "var(--muted)" }}>animal</label>
          <input value={animal} onChange={(e) => { setAnimal(e.target.value); clearRenders(); }}
            className="w-full rounded-lg px-3 py-2 text-sm outline-none" style={inputStyle} />
        </div>
        <div className="w-28">
          <label className={labelCls} style={{ color: "var(--muted)" }}>profile</label>
          <select value={profileKey} onChange={(e) => setProfileKey(e.target.value)}
            className="w-full rounded-lg px-3 py-2 text-sm outline-none" style={inputStyle}>
            {list?.profiles.map((p) => <option key={p.key} value={p.key}>{p.key}</option>)}
          </select>
        </div>
        <div className="w-20">
          <label className={labelCls} style={{ color: "var(--muted)" }}>seed</label>
          <input type="number" value={seed} onChange={(e) => { setSeed(Number(e.target.value) || DEFAULT_SEED); clearRenders(); }}
            className="w-full rounded-lg px-3 py-2 text-sm outline-none" style={inputStyle} />
        </div>
        <div>
          <label className={labelCls} style={{ color: "var(--muted)" }}>base still (shared)</label>
          <div className="flex items-center gap-2">
            <CellImg asset={base} size={52} placeholder={baseBusy ? (basePhase === "pending" ? "…" : `${baseElapsed}s`) : "—"} />
            <button onClick={drawBase} disabled={baseBusy}
              className="mono rounded-lg border px-4 py-2 text-sm font-semibold disabled:opacity-45"
              style={{ background: "rgba(99,102,241,0.12)", color: "var(--accent)", borderColor: "rgba(99,102,241,0.4)" }}>
              {runLabel(baseBusy, basePhase, baseElapsed, "Drawing", base ? "Redraw" : "Draw base")}
            </button>
            {baseBusy && <CancelBtn onClick={() => cancelJob(baseJob)} />}
          </div>
        </div>
      </div>

      {/* Pose selection */}
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <span className="mono text-xs" style={{ color: "var(--muted)" }}>poses:</span>
        {enabledPoses.map((n) => {
          const on = selected.includes(n);
          const hasClause = cells[n]?.clause.trim() || detail?.profile.poses[n]?.control?.kind === "pose_prompt";
          return (
            <button key={n} onClick={() => setSelected((s) => on ? s.filter((x) => x !== n) : [...s, n])}
              className="mono rounded-full border px-3 py-1 text-xs capitalize"
              style={on
                ? { background: "rgba(99,102,241,0.18)", color: "var(--accent)", borderColor: "rgba(99,102,241,0.5)" }
                : { color: "var(--faint)", borderColor: "var(--line)" }}>
              {n}{hasClause ? " ✎" : ""}
            </button>
          );
        })}
      </div>

      {/* Global actions */}
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <BatchBtn label="Draw all anchors" busy={busyAll === "draw"} onClick={drawAllAnchors} disabled={anyBusy || !columns.length} />
        <BatchBtn label="Animate all" busy={busyAll === "animate"} onClick={animateAll} disabled={anyBusy || !columns.length} />
        <button onClick={saveAll} disabled={busyAll === "save" || !detail || !list?.writable || !anyDirty}
          className="mono rounded-lg py-2 px-4 text-sm font-bold disabled:opacity-45"
          style={{ background: "linear-gradient(135deg, #6366f1, #4f46e5)", color: "var(--heading)" }}>
          {busyAll === "save" ? "Saving…" : "Save all"}
        </button>
        {anyDirty && <span className="mono text-xs" style={{ color: "var(--gold)" }}>unsaved changes</span>}
        {!list?.writable && <span className="mono text-xs" style={{ color: "var(--orange)" }}>read-only instance</span>}
      </div>

      {/* Columns */}
      <div className="flex gap-3 overflow-x-auto pb-3">
        {columns.map((name) => {
          const cell = cells[name];
          const isAnchored = !!cell.clause.trim();
          const source = isAnchored ? cell.still : base;
          const dirty = cell.clause.trim() !== (detail?.profile.poses[name]?.control?.pose ?? "").trim();
          return (
            <div key={name} className="card w-56 shrink-0 overflow-hidden p-0">
              <div className="flex items-center justify-between px-3 pt-3">
                <span className="font-semibold capitalize" style={{ color: "var(--heading)" }}>{name}</span>
                <span className="mono text-xs" style={{ color: isAnchored ? "var(--accent)" : "var(--faint)" }}>{isAnchored ? "anchor" : "base"}</span>
              </div>

              {/* Anchor section */}
              <div className="m-3 rounded-lg p-2" style={{ background: "#151515", border: "1px solid var(--line)" }}>
                <div className="mono mb-1 text-xs" style={{ color: "var(--faint)" }}>pose clause → {isAnchored ? "anchor still" : "uses base"}</div>
                <textarea value={cell.clause} onChange={(e) => patch(name, { clause: e.target.value })}
                  placeholder="pose clause (empty = uses base)"
                  className="mono mb-2 min-h-[44px] w-full resize-y rounded px-2 py-1 text-xs outline-none" style={inputStyle} />
                <CellImg asset={source} size={168}
                  placeholder={cell.busy === "draw" ? runLabel(true, cell.phase, cell.elapsed, "Drawing", "") : isAnchored ? "Draw anchor" : "Draw base"} />
                <ActionRow label={runLabel(cell.busy === "draw", cell.phase, cell.elapsed, "Drawing", "Draw anchor")}
                  disabled={cell.busy !== "" || !isAnchored} onClick={() => drawAnchor(name)}
                  onCancel={cell.busy === "draw" ? () => cancelJob(cell.jobId) : undefined} />
              </div>

              {/* Animation section — visually distinct (green) */}
              <div className="m-3 mt-0 rounded-lg p-2" style={{ background: "rgba(52,211,153,0.06)", border: "1px solid rgba(52,211,153,0.22)" }}>
                <div className="mono mb-1 text-xs font-semibold" style={{ color: "var(--green)" }}>▸ animation</div>
                <CellImg asset={cell.loop} size={168}
                  placeholder={cell.busy === "animate" ? runLabel(true, cell.phase, cell.elapsed, "Animating", "") : "Animate"} />
                <ActionRow label={runLabel(cell.busy === "animate", cell.phase, cell.elapsed, "Animating", "Animate")}
                  disabled={cell.busy !== "" || !source} onClick={() => animateOne(name)}
                  onCancel={cell.busy === "animate" ? () => cancelJob(cell.jobId) : undefined} />
              </div>

              <div className="px-3 pb-3">
                <button onClick={() => saveOne(name)} disabled={cell.busy === "save" || !list?.writable || !dirty}
                  className="mono w-full rounded-lg py-1.5 text-xs font-bold disabled:opacity-40"
                  style={{ background: dirty ? "rgba(99,102,241,0.18)" : "transparent", color: "var(--accent)", border: "1px solid rgba(99,102,241,0.4)" }}>
                  {cell.busy === "save" ? "Saving…" : dirty ? "Save clause" : "Saved"}
                </button>
              </div>
            </div>
          );
        })}
        {!columns.length && (
          <div className="mono flex h-40 w-full items-center justify-center rounded-lg text-xs"
            style={{ color: "var(--faint)", background: "#151515", border: "1px dashed var(--line)" }}>
            Select one or more poses above.
          </div>
        )}
      </div>
    </main>
  );
}

function BatchBtn({ label, busy, onClick, disabled }: { label: string; busy: boolean; onClick: () => void; disabled?: boolean }) {
  return (
    <button onClick={onClick} disabled={busy || disabled}
      className="mono shrink-0 rounded-lg border px-4 py-2 text-sm font-semibold disabled:opacity-45"
      style={{ background: "rgba(99,102,241,0.12)", color: "var(--accent)", borderColor: "rgba(99,102,241,0.4)" }}>
      {busy ? "Running…" : label}
    </button>
  );
}

function CancelBtn({ onClick }: { onClick: () => void }) {
  return (
    <button onClick={onClick} title="Cancel"
      className="mono shrink-0 rounded-lg border px-3 py-2 text-sm font-semibold"
      style={{ background: "rgba(239,68,68,0.12)", color: "#f87171", borderColor: "rgba(239,68,68,0.4)" }}>Cancel</button>
  );
}

function ActionRow({ label, disabled, onClick, onCancel }: {
  label: string; disabled: boolean; onClick: () => void; onCancel?: () => void;
}) {
  return (
    <div className="mt-2 flex items-center gap-1">
      <button onClick={onClick} disabled={disabled}
        className="mono flex-1 rounded border px-2 py-1 text-xs disabled:opacity-40"
        style={{ color: "var(--accent)", borderColor: "var(--line)" }}>{label}</button>
      {onCancel && (
        <button onClick={onCancel} title="Cancel"
          className="mono rounded border px-2 py-1 text-xs"
          style={{ color: "#f87171", borderColor: "rgba(239,68,68,0.4)" }}>✕</button>
      )}
    </div>
  );
}

function CellImg({ asset, size, placeholder }: { asset: LabAsset | null; size: number; placeholder: string }) {
  if (!asset) {
    return <div className="mono flex items-center justify-center rounded-lg text-center text-xs"
      style={{ width: size, height: size, color: "var(--faint)", background: "#151515", border: "1px dashed var(--line)" }}>
      {placeholder}
    </div>;
  }
  return (
    <div className="overflow-hidden rounded-lg" style={{ width: size, height: size, background: "#fff", border: "1px solid var(--line)" }}>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={motionLab.assetUrl(asset.url)} alt="" className="h-full w-full object-contain" />
    </div>
  );
}
