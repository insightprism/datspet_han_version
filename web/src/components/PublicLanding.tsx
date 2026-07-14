"use client";

/**
 * <PublicLanding> — the DatsPet public front door (SPEC_DATSPET_FRONT_DOOR §4).
 * Renders at `/`. Explains what DatsPet is + its relationship to DatsMe, and
 * offers Sign in with DatsMe / Create a DatsMe account (integrated mode) or
 * Start designing (standalone mode). One `GET /api/datsme/session` call drives
 * which of four states shows. Sign-in is a launch-token bounce to DatsMe — no
 * DatsPet accounts, ever (§0.1). Styled with the app's existing tokens.
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { getDatsmeSession, datsmeLogout, type DatsmeSession } from "@/lib/api";

// A non-blocking one-line notice (the shared-toast role for this page).
function Notice({ text, tone }: { text: string; tone: "warn" | "info" }) {
  return (
    <div
      className="mono mb-4 rounded-lg border px-4 py-2.5 text-sm"
      style={
        tone === "warn"
          ? { background: "rgba(251,146,60,0.1)", color: "var(--orange)", borderColor: "rgba(251,146,60,0.35)" }
          : { background: "rgba(99,102,241,0.1)", color: "var(--accent)", borderColor: "rgba(99,102,241,0.35)" }
      }
    >
      {text}
    </div>
  );
}

const HERO_BTN = "inline-block rounded-xl px-6 py-3 text-[15px] font-bold tracking-wide transition active:scale-[0.98]";
const SECONDARY_BTN = "inline-block rounded-lg border px-5 py-2.5 text-sm font-semibold transition hover:opacity-85";

export default function PublicLanding() {
  const [session, setSession] = useState<DatsmeSession | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [fetchFailed, setFetchFailed] = useState(false);
  const [notice, setNotice] = useState<{ text: string; tone: "warn" | "info" } | null>(null);

  useEffect(() => {
    getDatsmeSession()
      .then(setSession)
      .catch(() => setFetchFailed(true))
      .finally(() => setLoaded(true));

    // One-shot toast params from a bounced sign-in (§4.1), then clean the URL.
    const params = new URLSearchParams(window.location.search);
    const signin = params.get("signin");
    if (signin === "unavailable") setNotice({ text: "DatsMe is unavailable right now — try again in a bit.", tone: "warn" });
    else if (signin === "declined") setNotice({ text: "Sign-in cancelled. You can still explore DatsPet.", tone: "info" });
    if (signin) {
      params.delete("signin");
      const qs = params.toString();
      window.history.replaceState({}, "", window.location.pathname + (qs ? `?${qs}` : ""));
    }
  }, []);

  const integrated = session?.integrated ?? false;
  const launched = session?.launched ?? false;
  const signinUrl = session?.signin_url ?? null;
  const signupUrl = session?.signup_url ?? null;
  // Standalone posture applies both when the backend says so and when we couldn't
  // reach it — either way we show the local-mode path, never a broken sign-in.
  const standalone = loaded && (!integrated || fetchFailed);

  async function signOut() {
    await datsmeLogout();
    setSession((s) => (s ? { ...s, launched: false } : s));
  }

  return (
    <main>
      {notice && <Notice text={notice.text} tone={notice.tone} />}
      {fetchFailed && <Notice text="Couldn't reach the server — showing local mode." tone="warn" />}

      {/* Hero */}
      <section className="mb-10">
        <h1 className="mb-3 text-4xl font-bold leading-tight" style={{ color: "var(--heading)" }}>
          Design your own animated pet
        </h1>
        <p className="mb-6 max-w-2xl text-base leading-relaxed" style={{ color: "var(--muted)" }}>
          Describe it or pick a breed — DatsPet builds a living, walking, playing pet you can adopt
          into your DatsMe house.
        </p>

        <div className="flex flex-wrap items-center gap-3">
          {/* State-driven hero actions. The sign-in button renders only when the
              server handed us a signin_url — which gates the STANDALONE case (no
              DatsMe host at all). It does NOT protect against a host that lacks the
              login-launch endpoint: deploy the host FIRST (front-door §8). */}
          {integrated && launched ? (
            <>
              <Link href="/design" className={HERO_BTN} style={{ background: "linear-gradient(135deg, #6366f1, #4f46e5)", color: "var(--heading)" }}>
                Continue designing →
              </Link>
              <span className="mono rounded-full border px-3 py-1.5 text-xs" style={{ background: "rgba(52,211,153,0.12)", color: "var(--green)", borderColor: "rgba(52,211,153,0.4)" }}>
                ✓ Signed in via DatsMe
              </span>
              <button onClick={signOut} className={SECONDARY_BTN} style={{ background: "#151515", color: "var(--muted)", borderColor: "var(--line)" }}>
                Sign out of DatsPet
              </button>
            </>
          ) : integrated && signinUrl ? (
            <>
              <a href={signinUrl} className={HERO_BTN} style={{ background: "linear-gradient(135deg, #6366f1, #4f46e5)", color: "var(--heading)" }}>
                Sign in with DatsMe
              </a>
              {signupUrl && (
                <a href={signupUrl} className={SECONDARY_BTN} style={{ background: "rgba(167,139,250,0.12)", color: "var(--gold)", borderColor: "rgba(167,139,250,0.4)" }}>
                  Create a DatsMe account
                </a>
              )}
            </>
          ) : standalone ? (
            <>
              <Link href="/design" className={HERO_BTN} style={{ background: "linear-gradient(135deg, #6366f1, #4f46e5)", color: "var(--heading)" }}>
                Start designing →
              </Link>
              <span className="mono text-xs" style={{ color: "var(--faint)" }}>local mode</span>
            </>
          ) : (
            // Pre-load placeholder — keeps layout stable while the session loads.
            <div className="h-12" />
          )}
        </div>
      </section>

      {/* How it works */}
      <section className="mb-10">
        <h2 className="mb-4 text-xl font-semibold" style={{ color: "var(--heading)" }}>How it works</h2>
        <div className="grid gap-4" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))" }}>
          {[
            { n: "1", t: "Pick a base or describe your animal", d: "Start from a curated breed — a real picture, not a blank screen — or just describe the pet you want." },
            { n: "2", t: "DatsPet brings it to life, pose by pose", d: "Your pet is generated and animated: walking, idling, and the extra poses you choose." },
            { n: "3", t: "Adopt it into your DatsMe house", d: "It walks home to your DatsMe pet house, right next to everything else you do there." },
          ].map((s) => (
            <div key={s.n} className="card p-5">
              <div className="mono mb-2 text-lg font-bold" style={{ color: "var(--accent)" }}>{s.n}</div>
              <div className="mb-1 font-semibold" style={{ color: "var(--heading)" }}>{s.t}</div>
              <div className="text-sm leading-relaxed" style={{ color: "var(--muted)" }}>{s.d}</div>
            </div>
          ))}
        </div>
      </section>

      {/* DatsPet ♥ DatsMe — the relationship section */}
      <section className="mb-10">
        <div className="card p-6">
          <h2 className="mb-3 text-xl font-semibold" style={{ color: "var(--heading)" }}>
            DatsPet <span style={{ color: "var(--accent)" }}>♥</span> DatsMe
          </h2>
          <div className="grid gap-4 text-sm leading-relaxed" style={{ color: "var(--muted)" }}>
            <p>
              DatsPet is a partner app of DatsMe. One account is all you need — you sign in <em>with</em>{" "}
              DatsMe, on DatsMe&apos;s own page. DatsPet never sees or stores your password; it receives a
              signed, expiring pass that says who you are.
            </p>
            <p>
              Pets you adopt live in your DatsMe house, next to everything else you do there. Your pet
              data is yours: export or delete it any time from DatsMe&apos;s data controls.
            </p>
            <p>
              No DatsMe account? Creating one takes a minute — and it works across every DatsMe partner
              app, not just DatsPet.
            </p>
          </div>
          {integrated && !launched && signupUrl && (
            <a href={signupUrl} className={`${SECONDARY_BTN} mt-4`} style={{ background: "rgba(167,139,250,0.12)", color: "var(--gold)", borderColor: "rgba(167,139,250,0.4)" }}>
              Create a DatsMe account →
            </a>
          )}
        </div>
      </section>

      {/* Footer nav — always-available entry points */}
      <div className="flex flex-wrap gap-3">
        <Link href="/make" className={SECONDARY_BTN} style={{ background: "rgba(99,102,241,0.12)", color: "var(--accent)", borderColor: "rgba(99,102,241,0.4)" }}>
          ✏️ Describe a pet from scratch →
        </Link>
        <Link href="/house" className={SECONDARY_BTN} style={{ background: "rgba(52,211,153,0.12)", color: "var(--green)", borderColor: "rgba(52,211,153,0.4)" }}>
          🏠 Visit the pet house →
        </Link>
      </div>
    </main>
  );
}
