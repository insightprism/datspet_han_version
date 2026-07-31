"use client";

/**
 * <NavAuth> — the toolbar's auth slice: shows the signed-in DatsMe user's name +
 * a sign-out control when launched, or a compact "Sign in" link otherwise. Reads
 * the session client-side (the launch cookie is httponly, so the state comes from
 * /api/datsme/session). Renders nothing in standalone mode (no DatsMe host).
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  getDatsmeSession,
  datsmeSignOut,
  datsmeSignInUrlForHere,
  maybeRenewLaunch,
  type DatsmeSession,
} from "@/lib/api";

export default function NavAuth() {
  const [session, setSession] = useState<DatsmeSession | null>(null);

  useEffect(() => {
    getDatsmeSession()
      .then((s) => {
        setSession(s);
        // Silent re-launch (SPEC_DATSPET_FEDERATED_SESSION §4.2). The nav mounts on
        // every page, so this is the one place that has to ask — and asking on page
        // load rather than at the moment of use means the user never meets a stale
        // greeting or a mid-action bounce. A no-op when there is plenty of time
        // left, when there is nothing to renew, or when this load already came back
        // from a renewal that did not take (the loop guard).
        maybeRenewLaunch(s);
      })
      .catch(() => setSession(null));
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
        ) : adminBounce && session.system_admin ? (
          // Offered ONLY to someone who would pass the bounce. This link is not a
          // page — it is a round trip to the host's /admin-launch, which mints an
          // adm token for a system admin and sends everyone else back to the
          // landing with ?signin=admin_denied. Showing it to every launched user
          // meant a normal user could click "Admin" and be told off for it.
          //
          // `system_admin` is a hint, not a grant: it only decides whether the
          // door is visible. Walking through it still requires the bounce, and
          // every admin route still gates on the verified adm cookie — so a
          // forged hint would reveal a link and nothing behind it.
          <a href={adminBounce} className="font-medium hover:opacity-80" style={{ color: "var(--gold)" }}>
            Admin
          </a>
        ) : null}
        <span className="flex items-center gap-1.5" style={{ color: "var(--muted)" }}>
          <span aria-hidden>👤</span>
          <span className="font-medium" style={{ color: "var(--heading)" }}>{name}</span>
        </span>
        <button
          // A NAVIGATION, not a fetch. A fetch cannot clear the DatsMe session
          // cookie — it is on another origin, and SameSite=Lax means it would not
          // even be sent — so the old POST ended DatsPet's session and left
          // DatsMe's alive, and the next "Sign in" silently re-minted the same
          // person. Ending both is what lets a second user have this browser
          // (SPEC_DATSPET_FEDERATED_SESSION §5.1).
          onClick={() => datsmeSignOut(session)}
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
  //
  // Returns to the CURRENT page, query included, rather than the prebuilt
  // return=/design. This is the nav above the designer, so it is the link a user
  // clicks mid-build — and the designer keeps its running build in `?job=`.
  //
  // RESOLVED ON CLICK, never at render. This component renders once, when the
  // session resolves, which is BEFORE any build has started; the job id is added
  // later by history.replaceState, which deliberately does not re-render React. An
  // href computed during render is therefore frozen at the job-less URL, and the
  // user is sent back to an empty designer with their pet stranded — measured
  // twice, staging and dev, 2026-07-30. The static href stays as the no-JS and
  // middle-click fallback; the handler is what carries the query.
  if (!session.signin_url) return null;
  return (
    <a
      href={session.signin_url}
      onClick={(e) => {
        const url = datsmeSignInUrlForHere(session);
        if (!url) return;              // fall through to the static href
        e.preventDefault();
        window.location.href = url;
      }}
      className="text-sm font-medium hover:opacity-80"
      style={{ color: "var(--accent)" }}
    >
      Sign in
    </a>
  );
}
