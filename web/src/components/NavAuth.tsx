"use client";

/**
 * <NavAuth> — the toolbar's auth slice: shows the signed-in DatsMe user's name +
 * a sign-out control when launched, or a compact "Sign in" link otherwise. Reads
 * the session client-side (the launch cookie is httponly, so the state comes from
 * /api/datsme/session). Renders nothing in standalone mode (no DatsMe host).
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { getDatsmeSession, datsmeLogout, type DatsmeSession } from "@/lib/api";

export default function NavAuth() {
  const [session, setSession] = useState<DatsmeSession | null>(null);

  useEffect(() => {
    getDatsmeSession().then(setSession).catch(() => setSession(null));
  }, []);

  // Standalone (no DatsMe host) or still loading → render nothing in the nav.
  if (!session?.integrated) return null;

  if (session.launched) {
    const name = session.display_name || "your DatsMe";
    // Admin entries shown to ANY signed-in user (SPEC_MOTION_PROFILE_ADMIN §2.4,
    // discoverable variant). If already elevated (adm cookie), both editors link
    // directly — Motions beside Design (SPEC_PET_DESIGN_AXES_ADMIN §3.3);
    // otherwise one "Admin" click triggers the admin-launch bounce, where the
    // DatsMe host enforces the actual role — an admin gets in, a non-admin is
    // denied. The host origin comes from signin_url (same origin as admin-launch).
    const hostOrigin = session.signin_url ? new URL(session.signin_url).origin : "";
    const adminBounce = hostOrigin
      ? `${hostOrigin}/api/integrations/admin-launch?return=/admin/motions`
      : "";
    return (
      <span className="flex items-center gap-3 text-sm">
        {session.admin ? (
          <span className="flex items-center gap-2">
            <Link href="/admin/motions" className="font-medium hover:opacity-80" style={{ color: "var(--gold)" }}>
              Motions
            </Link>
            <Link href="/admin/motions/lab" className="font-medium hover:opacity-80" style={{ color: "var(--gold)" }}>
              Lab
            </Link>
            <Link href="/admin/design" className="font-medium hover:opacity-80" style={{ color: "var(--gold)" }}>
              Design
            </Link>
            <Link href="/admin/ai" className="font-medium hover:opacity-80" style={{ color: "var(--gold)" }}>
              AI
            </Link>
            <Link href="/admin/settings" className="font-medium hover:opacity-80" style={{ color: "var(--gold)" }}>
              Settings
            </Link>
          </span>
        ) : adminBounce ? (
          <a href={adminBounce} className="font-medium hover:opacity-80" style={{ color: "var(--gold)" }}>
            Admin
          </a>
        ) : null}
        <span className="flex items-center gap-1.5" style={{ color: "var(--muted)" }}>
          <span aria-hidden>👤</span>
          <span className="font-medium" style={{ color: "var(--heading)" }}>{name}</span>
        </span>
        <button
          onClick={async () => {
            await datsmeLogout();
            setSession((s) => (s ? { ...s, launched: false } : s));
          }}
          className="hover:opacity-80"
          style={{ color: "var(--faint)" }}
        >
          Sign out
        </button>
      </span>
    );
  }

  // Integrated but not signed in — a compact sign-in link (the landing has the
  // full button; this keeps the toolbar consistent on inner pages).
  return session.signin_url ? (
    <a href={session.signin_url} className="text-sm font-medium hover:opacity-80" style={{ color: "var(--accent)" }}>
      Sign in
    </a>
  ) : null;
}
