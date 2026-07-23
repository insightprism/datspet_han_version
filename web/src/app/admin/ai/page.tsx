"use client";

/**
 * AI engine admin (SPEC_DATSPET_AI_ENGINE §6) — the third admin surface, built
 * like the design admin. One page, three sub-tabs, because to the operator it is
 * one job ("configure how the platform talks to the model"):
 *
 *   Purposes — the editable purpose registry (tier / max_tokens / prompts / active).
 *   Models   — the READ-ONLY model catalog (a catalog edit is a code change + a
 *              guard test; runtime CRUD is how the two drift, §6).
 *   Usage    — calls / tokens / est. cost by purpose over a window (cost derived
 *              server-side from the catalog, never stored, §5).
 *
 * Plus Test configuration: one real connectivity_check call — the engine is
 * end-to-end demonstrable with zero product features built (§3.1). Every purpose
 * edit is validated server-side against the exact guard-test contract, so this UI
 * can't save data the build would reject. Gate: on mount it calls the admin API;
 * a 401 bounces to the host admin-launch. Reads work anywhere; writes 409 on
 * read-only prod.
 */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  aiAdmin, getDatsmeSession, AdminApiError,
  type AiPurposeList, type AiPurposeSummary, type AiPurposeFile,
  type AiModelEntry, type AiUsageReport, type AiTestResult,
} from "@/lib/api";

type Tab = "purposes" | "models" | "usage";

const inputStyle = { background: "#1c1c1c", border: "1px solid var(--line)", color: "var(--heading)" };
const labelCls = "mono mb-1 block text-xs tracking-wide";

const fmtCost = (n: number) => "$" + (n ?? 0).toFixed(4);
const fmtInt = (n: number) => (n ?? 0).toLocaleString();

export default function AiAdminPage() {
  const [tab, setTab] = useState<Tab>("purposes");
  const [list, setList] = useState<AiPurposeList | null>(null);
  const [models, setModels] = useState<AiModelEntry[] | null>(null);
  const [usage, setUsage] = useState<AiUsageReport | null>(null);
  const [usageDays, setUsageDays] = useState(30);
  const [gateState, setGateState] = useState<"checking" | "ok" | "denied">("checking");
  const [editing, setEditing] = useState<AiPurposeFile | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [test, setTest] = useState<AiTestResult | null>(null);
  const [testing, setTesting] = useState(false);

  const refresh = useCallback(async () => {
    const l = await aiAdmin.listPurposes();
    setList(l);
    setGateState("ok");
    // Catalog + usage are advisory to the first paint — fetch, swallow failures.
    aiAdmin.models().then((r) => setModels(r.models)).catch(() => setModels(null));
    aiAdmin.usage(usageDays).then(setUsage).catch(() => setUsage(null));
  }, [usageDays]);

  useEffect(() => {
    refresh().catch(async (e) => {
      if (e instanceof AdminApiError && (e.status === 401 || e.status === 403)) {
        const s = await getDatsmeSession().catch(() => null);
        const origin = s?.signin_url ? new URL(s.signin_url).origin : "";
        if (origin) {
          window.location.href = `${origin}/api/integrations/admin-launch?return=/admin/ai`;
          return;
        }
        setGateState("denied");
      } else {
        setNotice("Could not load the AI engine registry.");
        setGateState("denied");
      }
    });
  }, [refresh]);

  // Reload usage when the window changes (only matters on the usage tab).
  useEffect(() => {
    if (gateState === "ok") aiAdmin.usage(usageDays).then(setUsage).catch(() => setUsage(null));
  }, [usageDays, gateState]);

  async function startEdit(key: string) {
    setErrors([]);
    setNotice("");
    const d = await aiAdmin.getPurpose(key);
    setEditing(d.purpose);
  }

  async function save() {
    if (!editing) return;
    setBusy(true);
    setErrors([]);
    try {
      await aiAdmin.updatePurpose(editing.purpose_key, editing);
      setNotice(`Saved "${editing.purpose_key}" — live now.`);
      setEditing(null);
      await refresh();
    } catch (e) {
      setErrors(e instanceof AdminApiError && e.errors.length ? e.errors
        : [e instanceof Error ? e.message : "Save failed."]);
    } finally {
      setBusy(false);
    }
  }

  async function runTest() {
    setTesting(true);
    setTest(null);
    try {
      setTest(await aiAdmin.test());
    } catch (e) {
      setTest({ ok: false, kind: "error", reason: e instanceof Error ? e.message : "Test failed." });
    } finally {
      setTesting(false);
      aiAdmin.usage(usageDays).then(setUsage).catch(() => {});
    }
  }

  if (gateState === "checking") {
    return <main><p className="mono text-sm" style={{ color: "var(--faint)" }}>Checking admin access…</p></main>;
  }
  if (gateState === "denied") {
    return (
      <main>
        <h1 className="mb-2 text-2xl" style={{ color: "var(--heading)" }}>Admin access required</h1>
        <p className="text-sm" style={{ color: "var(--muted)" }}>This page is for DatsMe system admins. {notice}</p>
        <Link href="/" className="mono mt-4 inline-block text-sm underline" style={{ color: "var(--accent)" }}>← Back to DatsPet</Link>
      </main>
    );
  }

  const writable = !!list?.writable;
  const available = !!list?.available;

  return (
    <main>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-4">
          <h1 className="text-2xl" style={{ color: "var(--heading)" }}>AI Engine</h1>
          <div className="flex gap-1">
            {(["purposes", "models", "usage"] as Tab[]).map((t) => (
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
          <button onClick={runTest} disabled={testing}
            className="mono rounded-lg border px-4 py-2 text-sm font-semibold disabled:opacity-45"
            style={{ background: "rgba(99,102,241,0.12)", color: "var(--accent)", borderColor: "rgba(99,102,241,0.4)" }}>
            {testing ? "Testing…" : "Test configuration"}
          </button>
        </div>
      </div>

      {!available && (
        <div className="mono mb-4 rounded-lg border p-3 text-xs" style={{ background: "rgba(251,146,60,0.1)", color: "var(--orange)", borderColor: "rgba(251,146,60,0.35)" }}>
          The engine is inert — <code>DATSPET_AI_API_KEY</code> is not set. Reads and edits work; a real call (Test configuration) will report unavailable until the key is installed.
        </div>
      )}

      {test && (
        <div className="mono mb-4 rounded-lg border p-3 text-xs"
          style={test.ok
            ? { background: "rgba(34,197,94,0.08)", color: "var(--green)", borderColor: "rgba(34,197,94,0.35)" }
            : { background: "rgba(239,68,68,0.08)", color: "var(--accent)", borderColor: "rgba(239,68,68,0.4)" }}>
          {test.ok ? (
            <span>
              ✓ live call OK — model <b>{test.model}</b>, {fmtInt(test.input_tokens ?? 0)} in / {fmtInt(test.output_tokens ?? 0)} out,
              est. {fmtCost(test.est_cost_usd ?? 0)}. A usage row was recorded.
            </span>
          ) : (
            <span>✗ {test.kind === "unavailable" ? "engine unavailable" : "call failed"}: {test.reason}</span>
          )}
        </div>
      )}

      {notice && <div className="mono mb-4 text-sm" style={{ color: "var(--green)" }}>{notice}</div>}

      {tab === "purposes" && (
        <div className="grid gap-6" style={{ gridTemplateColumns: editing ? "minmax(220px, 320px) 1fr" : "1fr" }}>
          <div className="flex flex-col gap-2">
            {list?.purposes.map((p) => (
              <PurposeRow key={p.purpose_key} p={p} active={editing?.purpose_key === p.purpose_key}
                onEdit={() => startEdit(p.purpose_key)} />
            ))}
          </div>
          {editing && list && (
            <PurposeEditor purpose={editing} setPurpose={setEditing} tiers={list.tiers}
              errors={errors} busy={busy} writable={writable}
              onSave={save} onCancel={() => { setEditing(null); setErrors([]); }} />
          )}
        </div>
      )}

      {tab === "models" && <ModelsTable models={models} />}

      {tab === "usage" && (
        <UsageTable usage={usage} days={usageDays} setDays={setUsageDays} />
      )}
    </main>
  );
}

function PurposeRow({ p, active, onEdit }: { p: AiPurposeSummary; active: boolean; onEdit: () => void }) {
  return (
    <div className="card p-3" style={active ? { borderColor: "var(--accent)" } : undefined}>
      <div className="flex items-center gap-2">
        <span className="font-semibold" style={{ color: "var(--heading)" }}>{p.purpose_key}</span>
        <span className="mono rounded-full px-2 py-0.5 text-xs"
          style={p.is_active
            ? { background: "rgba(34,197,94,0.15)", color: "var(--green)" }
            : { background: "rgba(148,163,184,0.15)", color: "var(--faint)" }}>
          {p.is_active ? "active" : "off"}
        </span>
      </div>
      <div className="mono text-xs" style={{ color: "var(--faint)" }}>
        tier {p.tier} · {p.input} · max {p.max_tokens}
      </div>
      <div className="text-xs" style={{ color: "var(--muted)" }}>{p.description}</div>
      <div className="mt-2">
        <button onClick={onEdit} className="mono rounded border px-2 py-1 text-xs" style={{ color: "var(--accent)", borderColor: "var(--line)" }}>Edit</button>
      </div>
    </div>
  );
}

function PurposeEditor({ purpose, setPurpose, tiers, errors, busy, writable, onSave, onCancel }: {
  purpose: AiPurposeFile; setPurpose: (p: AiPurposeFile) => void; tiers: string[];
  errors: string[]; busy: boolean; writable: boolean;
  onSave: () => void; onCancel: () => void;
}) {
  // output_schema is edited as raw JSON text so an in-progress edit can't corrupt
  // the object; parsed back on change, with a local error until it parses.
  const [schemaText, setSchemaText] = useState(() => JSON.stringify(purpose.output_schema, null, 2));
  const [schemaErr, setSchemaErr] = useState("");

  function set<K extends keyof AiPurposeFile>(k: K, v: AiPurposeFile[K]) {
    setPurpose({ ...purpose, [k]: v });
  }
  function onSchemaChange(text: string) {
    setSchemaText(text);
    try {
      const parsed = JSON.parse(text);
      setSchemaErr("");
      setPurpose({ ...purpose, output_schema: parsed });
    } catch {
      setSchemaErr("output_schema is not valid JSON yet");
    }
  }

  return (
    <div className="card p-5">
      <div className="mb-3 text-lg font-semibold" style={{ color: "var(--heading)" }}>
        Editing {purpose.purpose_key}
        <span className="mono ml-2 text-xs" style={{ color: "var(--faint)" }}>(key locked — a purpose is a contributed file)</span>
      </div>

      {(errors.length > 0 || schemaErr) && (
        <div className="mb-4 rounded-lg border p-3" style={{ background: "rgba(239,68,68,0.08)", borderColor: "rgba(239,68,68,0.4)" }}>
          <div className="mono mb-1 text-xs" style={{ color: "var(--accent)" }}>fix these before saving:</div>
          <ul className="mono list-disc pl-5 text-xs" style={{ color: "var(--accent)" }}>
            {schemaErr && <li>{schemaErr}</li>}
            {errors.map((e, i) => <li key={i}>{e}</li>)}
          </ul>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={labelCls} style={{ color: "var(--muted)" }}>display name</label>
          <input value={purpose.display_name} onChange={(e) => set("display_name", e.target.value)}
            className="w-full rounded-lg px-3 py-2 text-sm outline-none" style={inputStyle} />
        </div>
        <div>
          <label className={labelCls} style={{ color: "var(--muted)" }}>tier (resolved to a model by the catalog)</label>
          <select value={purpose.tier} onChange={(e) => set("tier", e.target.value)}
            className="w-full rounded-lg px-3 py-2 text-sm outline-none" style={inputStyle}>
            {tiers.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>
        <div>
          <label className={labelCls} style={{ color: "var(--muted)" }}>max tokens</label>
          <input type="number" value={purpose.max_tokens}
            onChange={(e) => set("max_tokens", Number(e.target.value))}
            className="w-full rounded-lg px-3 py-2 text-sm outline-none" style={inputStyle} />
        </div>
        <div>
          <label className={labelCls} style={{ color: "var(--muted)" }}>input</label>
          <select value={purpose.input} onChange={(e) => set("input", e.target.value as AiPurposeFile["input"])}
            className="w-full rounded-lg px-3 py-2 text-sm outline-none" style={inputStyle}>
            <option value="text">text</option>
            <option value="image">image (needs a vision model)</option>
          </select>
        </div>
        <div className="col-span-2 flex items-center gap-2">
          <input id="is_active" type="checkbox" checked={purpose.is_active}
            onChange={(e) => set("is_active", e.target.checked)} />
          <label htmlFor="is_active" className="mono text-xs" style={{ color: "var(--muted)" }}>
            active (switch a purpose off without a deploy)
          </label>
        </div>
      </div>

      <label className={`${labelCls} mt-3`} style={{ color: "var(--muted)" }}>description</label>
      <textarea value={purpose.description} onChange={(e) => set("description", e.target.value)}
        className="min-h-[44px] w-full resize-y rounded-lg px-3 py-2 text-xs outline-none" style={inputStyle} />

      <label className={`${labelCls} mt-3`} style={{ color: "var(--muted)" }}>system prompt</label>
      <textarea value={purpose.system_prompt} onChange={(e) => set("system_prompt", e.target.value)}
        className="min-h-[64px] w-full resize-y rounded-lg px-3 py-2 text-xs outline-none" style={inputStyle} />

      <label className={`${labelCls} mt-3`} style={{ color: "var(--muted)" }}>
        user prompt template ({"{placeholder}"} names must be declared below)
      </label>
      <textarea value={purpose.user_prompt_template} onChange={(e) => set("user_prompt_template", e.target.value)}
        className="min-h-[52px] w-full resize-y rounded-lg px-3 py-2 text-xs outline-none" style={inputStyle} />

      <label className={`${labelCls} mt-3`} style={{ color: "var(--muted)" }}>template variables (comma-separated placeholder names the caller supplies)</label>
      <input value={purpose.template_vars.join(", ")}
        onChange={(e) => set("template_vars", e.target.value.split(",").map((s) => s.trim()).filter(Boolean))}
        className="w-full rounded-lg px-3 py-2 text-xs outline-none" style={inputStyle} />

      <label className={`${labelCls} mt-3`} style={{ color: "var(--muted)" }}>
        output schema (JSON — structured-output keywords only; no minimum/maximum/minLength/maxLength)
      </label>
      <textarea value={schemaText} onChange={(e) => onSchemaChange(e.target.value)}
        className="min-h-[120px] w-full resize-y rounded-lg px-3 py-2 text-xs outline-none font-mono" style={inputStyle} />

      <label className={`${labelCls} mt-3`} style={{ color: "var(--muted)" }}>_doc (why this purpose is shaped the way it is)</label>
      <textarea value={purpose._doc ?? ""} onChange={(e) => set("_doc", e.target.value)}
        className="min-h-[44px] w-full resize-y rounded-lg px-3 py-2 text-xs outline-none" style={inputStyle} />

      <div className="mt-4 flex gap-3">
        <button onClick={onSave} disabled={busy || !writable || !!schemaErr}
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

function ModelsTable({ models }: { models: AiModelEntry[] | null }) {
  if (!models) return <p className="mono text-sm" style={{ color: "var(--faint)" }}>Loading catalog…</p>;
  return (
    <div className="card overflow-x-auto p-0">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="mono text-xs" style={{ color: "var(--muted)" }}>
            {["model", "provider", "tier", "status", "vision", "$ / Mtok in", "$ / Mtok out", "default for"].map((h) => (
              <th key={h} className="border-b px-3 py-2 font-normal" style={{ borderColor: "var(--line)" }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {models.map((m) => (
            <tr key={m.id} style={{ color: "var(--heading)" }}>
              <td className="border-b px-3 py-2" style={{ borderColor: "var(--line)" }}>
                <div className="font-semibold">{m.label}</div>
                <div className="mono text-xs" style={{ color: "var(--faint)" }}>{m.id}</div>
              </td>
              <td className="mono border-b px-3 py-2 text-xs" style={{ borderColor: "var(--line)", color: "var(--muted)" }}>{m.provider}</td>
              <td className="mono border-b px-3 py-2 text-xs" style={{ borderColor: "var(--line)", color: "var(--muted)" }}>{m.tier}</td>
              <td className="mono border-b px-3 py-2 text-xs" style={{ borderColor: "var(--line)", color: m.status === "available" ? "var(--green)" : "var(--orange)" }}>{m.status}</td>
              <td className="mono border-b px-3 py-2 text-xs" style={{ borderColor: "var(--line)", color: "var(--muted)" }}>{m.vision ? "yes" : "no"}</td>
              <td className="mono border-b px-3 py-2 text-xs" style={{ borderColor: "var(--line)", color: "var(--muted)" }}>${m.cost_per_mtok.input.toFixed(2)}</td>
              <td className="mono border-b px-3 py-2 text-xs" style={{ borderColor: "var(--line)", color: "var(--muted)" }}>${m.cost_per_mtok.output.toFixed(2)}</td>
              <td className="mono border-b px-3 py-2 text-xs" style={{ borderColor: "var(--line)", color: "var(--faint)" }}>{m.default_for_tiers.join(", ") || "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mono px-3 py-2 text-xs" style={{ color: "var(--faint)" }}>
        read-only — a catalog change is a code edit guarded by a build test.
      </div>
    </div>
  );
}

function UsageTable({ usage, days, setDays }: {
  usage: AiUsageReport | null; days: number; setDays: (d: number) => void;
}) {
  return (
    <div>
      <div className="mb-3 flex items-center gap-3">
        <label className="mono text-xs" style={{ color: "var(--muted)" }}>window</label>
        <select value={days} onChange={(e) => setDays(Number(e.target.value))}
          className="rounded px-2 py-1 text-xs outline-none" style={inputStyle}>
          <option value={7}>last 7 days</option>
          <option value={30}>last 30 days</option>
          <option value={90}>last 90 days</option>
          <option value={0}>all time</option>
        </select>
        {usage && (
          <span className="mono text-xs" style={{ color: "var(--muted)" }}>
            total est. cost <b style={{ color: "var(--heading)" }}>{fmtCost(usage.total_cost_usd)}</b>
          </span>
        )}
      </div>
      {!usage ? (
        <p className="mono text-sm" style={{ color: "var(--faint)" }}>Loading usage…</p>
      ) : usage.purposes.length === 0 ? (
        <p className="mono text-sm" style={{ color: "var(--faint)" }}>No calls in this window yet — press Test configuration to record one.</p>
      ) : (
        <div className="card overflow-x-auto p-0">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="mono text-xs" style={{ color: "var(--muted)" }}>
                {["purpose", "calls", "ok", "errors", "tokens in", "tokens out", "est. cost"].map((h) => (
                  <th key={h} className="border-b px-3 py-2 font-normal" style={{ borderColor: "var(--line)" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {usage.purposes.map((p) => (
                <tr key={p.purpose_key} style={{ color: "var(--heading)" }}>
                  <td className="border-b px-3 py-2" style={{ borderColor: "var(--line)" }}>
                    <div className="font-semibold">{p.purpose_key}</div>
                    <div className="mono text-xs" style={{ color: "var(--faint)" }}>{p.models.join(", ")}</div>
                  </td>
                  <td className="mono border-b px-3 py-2 text-xs" style={{ borderColor: "var(--line)" }}>{fmtInt(p.calls)}</td>
                  <td className="mono border-b px-3 py-2 text-xs" style={{ borderColor: "var(--line)", color: "var(--green)" }}>{fmtInt(p.ok_calls)}</td>
                  <td className="mono border-b px-3 py-2 text-xs" style={{ borderColor: "var(--line)", color: p.error_calls ? "var(--orange)" : "var(--faint)" }}>{fmtInt(p.error_calls)}</td>
                  <td className="mono border-b px-3 py-2 text-xs" style={{ borderColor: "var(--line)", color: "var(--muted)" }}>{fmtInt(p.input_tokens)}</td>
                  <td className="mono border-b px-3 py-2 text-xs" style={{ borderColor: "var(--line)", color: "var(--muted)" }}>{fmtInt(p.output_tokens)}</td>
                  <td className="mono border-b px-3 py-2 text-xs" style={{ borderColor: "var(--line)" }}>{fmtCost(p.est_cost_usd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
