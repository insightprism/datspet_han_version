"use client";

/**
 * Settings admin (SPEC_UPLOAD_LIKENESS §2.2, decision 6a) — the fourth admin surface:
 * runtime feature flags. Built like the other three (a mount-time gate; a 401 bounces to
 * the host admin-launch), but simpler — a switchboard, not a content editor.
 *
 * Today the one flag is `upload_isolate` — subject isolation on the upload door (Phase 3),
 * default OFF. Flipping it here is the A/B test harness (draw the same photo off, then on),
 * the fleet gate (the pool param ships only when on), and the kill-switch. No writability
 * gate: a flag is meant to be toggled at runtime without a deploy.
 */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  settingsAdmin, getDatsmeSession, AdminApiError, type AppSetting,
} from "@/lib/api";

export default function SettingsAdminPage() {
  const [settings, setSettings] = useState<AppSetting[] | null>(null);
  const [gateState, setGateState] = useState<"checking" | "ok" | "denied">("checking");
  const [notice, setNotice] = useState("");
  const [busyKey, setBusyKey] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const r = await settingsAdmin.list();
    setSettings(r.settings);
    setGateState("ok");
  }, []);

  useEffect(() => {
    refresh().catch(async (e) => {
      if (e instanceof AdminApiError && (e.status === 401 || e.status === 403)) {
        const s = await getDatsmeSession().catch(() => null);
        const origin = s?.signin_url ? new URL(s.signin_url).origin : "";
        if (origin) {
          window.location.href = `${origin}/api/integrations/admin-launch?return=/admin/settings`;
          return;
        }
        setGateState("denied");
      } else {
        setNotice("Could not load settings.");
        setGateState("denied");
      }
    });
  }, [refresh]);

  async function toggle(s: AppSetting, next: boolean) {
    setBusyKey(s.key);
    setNotice("");
    try {
      const { updated } = await settingsAdmin.set(s.key, next);
      setSettings((prev) => (prev ?? []).map((x) => (x.key === updated.key ? updated : x)));
      setNotice(`${updated.label}: ${updated.value ? "on" : "off"}`);
    } catch (e) {
      setNotice(e instanceof Error ? e.message : "Save failed.");
    } finally {
      setBusyKey(null);
    }
  }

  if (gateState === "checking") {
    return <main className="mx-auto max-w-3xl px-6 py-10 mono text-sm" style={{ color: "var(--faint)" }}>Checking access…</main>;
  }
  if (gateState === "denied") {
    return (
      <main className="mx-auto max-w-3xl px-6 py-10">
        <p className="mono text-sm" style={{ color: "var(--faint)" }}>
          {notice || "Admin access required."}
        </p>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-3xl px-6 py-10">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-lg font-semibold" style={{ color: "var(--heading)" }}>Settings</h1>
        <nav className="mono flex gap-4 text-xs">
          <Link href="/admin/motions" className="hover:opacity-80" style={{ color: "var(--gold)" }}>motions</Link>
          <Link href="/admin/design" className="hover:opacity-80" style={{ color: "var(--gold)" }}>design</Link>
          <Link href="/admin/ai" className="hover:opacity-80" style={{ color: "var(--gold)" }}>ai</Link>
          <Link href="/admin/store" className="hover:opacity-80" style={{ color: "var(--gold)" }}>store</Link>
        </nav>
      </div>

      {notice && (
        <div className="mono mb-4 text-xs" style={{ color: "var(--faint)" }}>{notice}</div>
      )}

      <div className="flex flex-col gap-3">
        {(settings ?? []).map((s) => (
          <div key={s.key} className="flex items-start justify-between gap-4 rounded-xl border px-4 py-3"
               style={{ background: "#151515", borderColor: "var(--line)" }}>
            <div className="min-w-0">
              <div className="text-sm font-medium" style={{ color: "var(--heading)" }}>{s.label}</div>
              <div className="mono mt-1 text-xs leading-relaxed" style={{ color: "var(--faint)" }}>{s.description}</div>
              <div className="mono mt-1 text-xs" style={{ color: "var(--muted)" }}>
                {s.key} · default {s.default ? "on" : "off"}
              </div>
            </div>
            <button
              type="button"
              role="switch"
              aria-checked={s.value}
              disabled={busyKey === s.key}
              onClick={() => toggle(s, !s.value)}
              className="relative mt-1 h-6 w-11 shrink-0 rounded-full transition disabled:opacity-50"
              style={{ background: s.value ? "var(--green)" : "var(--line)" }}
            >
              <span
                className="absolute top-0.5 h-5 w-5 rounded-full bg-white transition-all"
                style={{ left: s.value ? "1.375rem" : "0.125rem" }}
              />
            </button>
          </div>
        ))}
        {settings && settings.length === 0 && (
          <p className="mono text-xs" style={{ color: "var(--faint)" }}>No settings declared.</p>
        )}
      </div>
    </main>
  );
}
