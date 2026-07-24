"use client";

/**
 * Motion Lab (SPEC_MOTION_LAB) — the visual workbench for authoring pose_prompt
 * clauses (§3.9.1). Pick an animal + a profile's pose, watch the pipeline run its
 * steps — the standing base, the fresh anchor drawn from the pose clause, then the
 * Wan loop — edit the clause and re-run in seconds, and save the clause to the
 * profile. Save is the same motion_admin write the profile editor uses, so a saved
 * clause can never be one the build rejects.
 *
 * LOCAL backend only: the generation endpoints drive ComfyUI, so on the prod tier
 * they 404 (the router isn't mounted). Same admin gate as the profile editor.
 */
import { useCallback, useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import {
  motionAdmin, motionLab, getDatsmeSession, AdminApiError,
  type MotionAdminList, type MotionProfileDetail, type LabAsset,
} from "@/lib/api";

const DEFAULT_SEED = 42;
const inputStyle = { background: "#1c1c1c", border: "1px solid var(--line)", color: "var(--heading)" };
const labelCls = "mono mb-1 block text-xs tracking-wide";

export default function MotionLabPage() {
  const [gate, setGate] = useState<"checking" | "ok" | "denied">("checking");
  const [list, setList] = useState<MotionAdminList | null>(null);
  const [profileKey, setProfileKey] = useState("");
  const [detail, setDetail] = useState<MotionProfileDetail | null>(null);
  const [poseName, setPoseName] = useState("");
  const [animal, setAnimal] = useState("robin");
  const [seed, setSeed] = useState(DEFAULT_SEED);
  const [clause, setClause] = useState("");
  const [base, setBase] = useState<LabAsset | null>(null);
  const [anchor, setAnchor] = useState<LabAsset | null>(null);
  const [loop, setLoop] = useState<LabAsset | null>(null);
  const [busy, setBusy] = useState<"" | "base" | "anchor" | "animate" | "save">("");
  const [notice, setNotice] = useState("");
  const [err, setErr] = useState("");

  // Gate on mount + load the profile list. A 401 → bounce to the host admin-launch.
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
        if (origin) {
          window.location.href = `${origin}/api/integrations/admin-launch?return=/admin/motions/lab`;
          return;
        }
      }
      setGate("denied");
    });
  }, []);

  // Load the selected profile's poses; pick a sensible starting pose.
  useEffect(() => {
    if (!profileKey) return;
    motionAdmin.get(profileKey).then((d) => {
      setDetail(d);
      const enabled = Object.entries(d.profile.poses).filter(([, p]) => p.enabled).map(([n]) => n);
      const withAnchor = enabled.find((n) => d.profile.poses[n].control?.kind === "pose_prompt");
      setPoseName(withAnchor ?? enabled.find((n) => ["fly", "run", "jump"].includes(n)) ?? enabled[0] ?? "");
    }).catch(() => setDetail(null));
  }, [profileKey]);

  // When the pose changes, load its clause and drop the stale anchor/loop.
  useEffect(() => {
    if (!detail || !poseName) return;
    setClause(detail.profile.poses[poseName]?.control?.pose ?? "");
    setAnchor(null);
    setLoop(null);
  }, [detail, poseName]);

  const run = useCallback(async (kind: "base" | "anchor" | "animate", fn: () => Promise<void>) => {
    setBusy(kind);
    setErr("");
    try {
      await fn();
    } catch (e) {
      setErr(e instanceof AdminApiError ? e.message : "Generation failed — is ComfyUI up?");
    } finally {
      setBusy("");
    }
  }, []);

  const genBase = () => run("base", async () => setBase(await motionLab.still(animal, "", seed)));
  const genAnchor = () => run("anchor", async () => {
    setAnchor(await motionLab.still(animal, clause.trim(), seed));
    setLoop(null);
  });
  const animate = () => run("animate", async () => {
    if (anchor) setLoop(await motionLab.animate(anchor.asset_id, animal, profileKey, poseName, seed));
  });

  async function save() {
    if (!detail) return;
    setBusy("save");
    setErr("");
    setNotice("");
    try {
      const profile = structuredClone(detail.profile);
      const pose = { ...profile.poses[poseName] };
      const c = clause.trim();
      if (c) pose.control = { kind: "pose_prompt", pose: c };
      else delete pose.control;
      profile.poses[poseName] = pose;
      await motionAdmin.update(profileKey, profile, detail.label);
      setNotice(`Saved ${profileKey}.${poseName} — live now: new generations use this clause.`);
      setDetail(await motionAdmin.get(profileKey));
    } catch (e) {
      setErr(e instanceof AdminApiError ? (e.errors[0] ?? e.message) : "Save failed.");
    } finally {
      setBusy("");
    }
  }

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

  const enabledPoses = detail ? Object.entries(detail.profile.poses).filter(([, p]) => p.enabled).map(([n]) => n) : [];
  const savedClause = detail?.profile.poses[poseName]?.control?.pose ?? "";
  const dirty = clause.trim() !== savedClause.trim();

  return (
    <main>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl" style={{ color: "var(--heading)" }}>Motion Lab</h1>
        <Link href="/admin/motions" className="mono text-sm underline" style={{ color: "var(--accent)" }}>← Motion profiles</Link>
      </div>
      <p className="mono mb-4 text-xs" style={{ color: "var(--faint)" }}>
        Tune a pose clause and watch it move. The anchor is a fresh still drawn from the clause; a wings-spread bird flaps where a standing one only twitches.
      </p>

      {notice && <div className="mono mb-3 text-sm" style={{ color: "var(--green)" }}>{notice}</div>}
      {err && <div className="mono mb-3 text-sm" style={{ color: "var(--accent)" }}>{err}</div>}

      {/* Controls */}
      <div className="card mb-5 grid grid-cols-2 gap-3 p-4 md:grid-cols-4">
        <div className="col-span-2 md:col-span-1">
          <label className={labelCls} style={{ color: "var(--muted)" }}>animal</label>
          <input value={animal} onChange={(e) => setAnimal(e.target.value)}
            className="w-full rounded-lg px-3 py-2 text-sm outline-none" style={inputStyle} />
        </div>
        <div>
          <label className={labelCls} style={{ color: "var(--muted)" }}>profile</label>
          <select value={profileKey} onChange={(e) => setProfileKey(e.target.value)}
            className="w-full rounded-lg px-3 py-2 text-sm outline-none" style={inputStyle}>
            {list?.profiles.map((p) => <option key={p.key} value={p.key}>{p.key}</option>)}
          </select>
        </div>
        <div>
          <label className={labelCls} style={{ color: "var(--muted)" }}>pose</label>
          <select value={poseName} onChange={(e) => setPoseName(e.target.value)}
            className="w-full rounded-lg px-3 py-2 text-sm outline-none" style={inputStyle}>
            {enabledPoses.map((n) => (
              <option key={n} value={n}>
                {n}{detail?.profile.poses[n].control?.kind === "pose_prompt" ? " ✓" : ""}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className={labelCls} style={{ color: "var(--muted)" }}>seed</label>
          <input type="number" value={seed} onChange={(e) => setSeed(Number(e.target.value) || DEFAULT_SEED)}
            className="w-full rounded-lg px-3 py-2 text-sm outline-none" style={inputStyle} />
        </div>
      </div>

      {/* Step 1 — base (the standing reference, same seed → same animal) */}
      <StepCard n={1} title="Base still" subtitle="the standing reference — same animal, for identity/style comparison"
        action={<RunBtn label="Draw base" busy={busy === "base"} onClick={genBase} />}>
        <AssetView asset={base} kind="png" placeholder="Draw the base to see the standing animal." />
      </StepCard>

      {/* Step 2 — clause + anchor */}
      <StepCard n={2} title="Pose clause → anchor" subtitle={`replaces "standing" in the base prompt (e.g. "wings spread wide open, mid-flight")`}
        action={<RunBtn label="Draw anchor" busy={busy === "anchor"} onClick={genAnchor} disabled={!clause.trim()} />}>
        <textarea value={clause} onChange={(e) => setClause(e.target.value)}
          placeholder="the pose clause…"
          className="mono mb-3 min-h-[60px] w-full resize-y rounded-lg px-3 py-2 text-sm outline-none" style={inputStyle} />
        <AssetView asset={anchor} kind="png" placeholder="Edit the clause, then draw the anchor — this animal, in the pose." />
      </StepCard>

      {/* Step 3 — animate */}
      <StepCard n={3} title="Animate" subtitle="the Wan loop from the anchor, using this pose's action/suffix"
        action={<RunBtn label="Animate" busy={busy === "animate"} onClick={animate} disabled={!anchor} />}>
        <AssetView asset={loop} kind="webp" placeholder="Draw an anchor first, then animate to see it move." />
      </StepCard>

      {/* Save */}
      <div className="mt-5 flex flex-wrap items-center gap-3">
        <button onClick={save} disabled={busy === "save" || !detail || !list?.writable || !dirty}
          className="mono rounded-lg py-2.5 px-5 text-sm font-bold disabled:opacity-45"
          style={{ background: "linear-gradient(135deg, #6366f1, #4f46e5)", color: "var(--heading)" }}>
          {busy === "save" ? "Saving…" : `Save clause → ${profileKey}.${poseName}`}
        </button>
        {dirty && <span className="mono text-xs" style={{ color: "var(--gold)" }}>unsaved clause change</span>}
        {!list?.writable && <span className="mono text-xs" style={{ color: "var(--orange)" }}>read-only instance</span>}
      </div>
    </main>
  );
}

function StepCard({ n, title, subtitle, action, children }: {
  n: number; title: string; subtitle: string; action: ReactNode; children: ReactNode;
}) {
  return (
    <div className="card mb-4 p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <span className="mono text-xs" style={{ color: "var(--faint)" }}>step {n}</span>
          <div className="font-semibold" style={{ color: "var(--heading)" }}>{title}</div>
          <div className="mono text-xs" style={{ color: "var(--faint)" }}>{subtitle}</div>
        </div>
        {action}
      </div>
      {children}
    </div>
  );
}

function RunBtn({ label, busy, onClick, disabled }: {
  label: string; busy: boolean; onClick: () => void; disabled?: boolean;
}) {
  return (
    <button onClick={onClick} disabled={busy || disabled}
      className="mono shrink-0 rounded-lg border px-4 py-2 text-sm font-semibold disabled:opacity-45"
      style={{ background: "rgba(99,102,241,0.12)", color: "var(--accent)", borderColor: "rgba(99,102,241,0.4)" }}>
      {busy ? "Running…" : label}
    </button>
  );
}

function AssetView({ asset, kind, placeholder }: { asset: LabAsset | null; kind: "png" | "webp"; placeholder: string }) {
  if (!asset) {
    return <div className="mono flex h-40 items-center justify-center rounded-lg text-xs"
      style={{ color: "var(--faint)", background: "#151515", border: "1px dashed var(--line)" }}>{placeholder}</div>;
  }
  return (
    <div className="flex items-center gap-3">
      <div className="overflow-hidden rounded-lg" style={{ width: 176, height: 176, background: "#fff", border: "1px solid var(--line)" }}>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={motionLab.assetUrl(asset.url)} alt={kind} className="h-full w-full object-contain" />
      </div>
      <span className="mono text-xs" style={{ color: "var(--faint)" }}>{(asset.ms / 1000).toFixed(1)}s</span>
    </div>
  );
}
