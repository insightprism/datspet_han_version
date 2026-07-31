"use client";

/**
 * PetJobResult — the progress bar while a pet generates, and the finished
 * panel (portrait, actions, and the pet itself walking onto the page).
 * Shared by the Describe and Design pages.
 */

import { useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import {
  keepPet,
  petZipUrl,
  getDatsmeSession,
  handOffToDatsme,
  maybeRenewLaunch,
  type JobStatus,
  type DatsmeSession,
} from "@/lib/api";
import PetStage from "@/components/PetStage";
import PetThumbnail from "@/components/PetThumbnail";
import { HOUSE_NAME, HOUSE_NAME_OBJ } from "@/lib/houseCopy";
import PoseGallery from "@/components/PoseGallery";
import ConfirmModal from "@/components/ConfirmModal";

interface Props {
  job: JobStatus;
  onReset: () => void;
  resetLabel?: string;
  /**
   * Drop the `card` wrapper and render the contents bare.
   *
   * For a caller that is ALREADY a card — the stepped designer renders this inside its
   * own step 3 rather than replacing the page — the wrapper would nest a card in a
   * card: two borders, two accent strips, doubled padding. The panel's contents are
   * what that caller wants; the chrome is the caller's own business.
   */
  bare?: boolean;
  /** User-initiated Stop (§11). When provided, a Stop button shows while the build runs. */
  onStop?: () => void;
}

// Elapsed seconds → compact human string. Under a minute reads "12s"; past that,
// "1:05" so a long build is legible at a glance without a stopwatch.
function formatElapsed(sec: number): string {
  if (sec < 60) return `${sec}s`;
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

export default function PetJobResult({ job, onReset, resetLabel = "Make another", bare = false, onStop }: Props) {
  const done = job.status === "done";
  // Live elapsed-time counter while the pet is being built. Anchored to when this
  // component first sees a given job.id (generation start, from the user's view) —
  // JobStatus carries no server start time. Ticks every second so the number
  // visibly climbs (proof it's still working) and stops the instant it finishes
  // or errors. Reset per job.id so "Make another" starts the clock fresh.
  const running = job.status === "queued" || job.status === "running";
  const canceled = job.status === "canceled";
  const [confirmStop, setConfirmStop] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    setElapsed(0);
    if (!running) return;
    const startedAt = Date.now();
    const t = setInterval(() => setElapsed(Math.floor((Date.now() - startedAt) / 1000)), 1000);
    return () => clearInterval(t);
    // Re-anchor when the job identity changes, or when it stops running (clears the timer).
  }, [job.id, running]);
  // Fresh pets are DRAFTS: they only join the house when saved here.
  // Unsaved drafts are removed when the next generation starts.
  const [saved, setSaved] = useState(false);
  const [saveError, setSaveError] = useState("");

  // DatsMe launch context (null in standalone mode). When launched, the
  // primary action becomes "Accept — send to my DatsMe" (costs credits);
  // Save-to-house stays as a free/local secondary action.
  const [datsme, setDatsme] = useState<DatsmeSession | null>(null);
  const [adopting, setAdopting] = useState(false);

  useEffect(() => setSaved(false), [job.id]);
  useEffect(() => {
    getDatsmeSession()
      .then((s) => {
        setDatsme(s.launched ? s : null);
        // A long build can outlast the launch assertion. Renew silently now rather
        // than let the adopt hand-off be the thing that discovers it.
        maybeRenewLaunch(s);
      })
      .catch(() => setDatsme(null));
  }, []);

  async function save() {
    setSaveError("");
    try {
      await keepPet(job.id);
      setSaved(true);
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : "Could not save");
    }
  }

  // Adopt runs the ONE purchase path: claim + keep here, then hand off to the
  // host's own checkout, where the user's DatsMe session authenticates and the
  // host quotes a binding price before charging anything
  // (SPEC_DATSPET_FEDERATED_SESSION §2.4). There is no "session expired while
  // designing" branch any more — that failure class is structurally gone, because
  // nothing token-authenticated happens at the end of a build.
  async function adopt() {
    if (!datsme) return;
    setSaveError("");
    setAdopting(true);
    try {
      await handOffToDatsme([job.id], datsme);
    } catch (e) {
      setAdopting(false);
      setSaveError(e instanceof Error ? e.message : "Could not hand this pet to DatsMe");
    }
  }

  // An ESTIMATE. The host's checkout shows the number it is then bound to — it
  // prices from the bundle's own manifest, so this hint can only ever be a hint.
  const adoptLabel =
    datsme?.cost != null
      ? `✓ Adopt into my DatsMe house (about ${datsme.cost} credits)`
      : "✓ Adopt into my DatsMe house";
  const Shell = bare ? BareShell : CardShell;
  return (
    <Shell>
      <div className="mono mb-1.5 flex items-center gap-2 text-sm" style={{ color: job.status === "error" ? "var(--accent)" : "var(--gold)" }}>
        {running && (
          // Running figure — the little bob signals "still working" alongside the
          // climbing timer. aria-hidden: the elapsed text carries the meaning.
          <span aria-hidden className="pet-run inline-block" style={{ lineHeight: 1 }}>🏃</span>
        )}
        <span>{job.message}</span>
        {running && (
          <span className="tabular-nums" style={{ color: "var(--muted)" }}>
            · {formatElapsed(elapsed)}
          </span>
        )}
      </div>
      <div className="h-2 overflow-hidden rounded" style={{ background: "#262626" }}>
        <div
          className="h-full transition-all duration-500"
          style={{
            width: `${Math.round(job.progress * 100)}%`,
            background: "linear-gradient(90deg, var(--green), var(--gold))",
          }}
        />
      </div>

      {running && onStop && (
        <div className="mt-3">
          <button
            type="button"
            onClick={() => setConfirmStop(true)}
            className="mono rounded-lg border px-4 py-2 text-sm"
            style={{ background: "#151515", color: "var(--muted)", borderColor: "var(--line)" }}
          >
            Stop
          </button>
        </div>
      )}

      {canceled && (
        <div className="mt-4">
          <div className="mono mb-3 text-sm" style={{ color: "var(--muted)" }}>Build stopped.</div>
          {/* NOT resetLabel ("Design another") here: a stop keeps steps 1 and 2 locked in —
              onReset only clears the dead job, dropping step 3 back to its build controls with
              the same design. So the honest verb is re-run, not start-over. resetLabel stays
              for the `done` case, where you really are moving on to a new pet. */}
          <button type="button" onClick={onReset} className="btn">Re-run the build</button>
        </div>
      )}

      <ConfirmModal
        open={confirmStop}
        title="Stop this build?"
        body="This cancels the pet that's generating — you'll lose what's rendered so far."
        confirmLabel="Stop build"
        onConfirm={() => { setConfirmStop(false); onStop?.(); }}
        onCancel={() => setConfirmStop(false)}
      />

      {done && (
        <>
          <div className="mt-6 flex flex-wrap items-center gap-5">
            <div className="card p-3" style={{ borderColor: "rgba(52,211,153,0.4)" }}>
              <PetThumbnail petId={job.id} size={128} />
            </div>
            <div>
              <div className="text-xl" style={{ color: "var(--heading)" }}>{job.name}</div>
              <div className="mono mt-1 text-xs" style={{ color: "var(--muted)" }}>
                breed_id: {job.breed_id} · DatsMe bundle
              </div>
              <div className="mono mt-1 text-xs" style={{ color: "var(--green)" }}>
                It&apos;s alive — look at the bottom of the page. Click anywhere to call it over.
              </div>
              <div className="mono mt-1 text-xs" style={{ color: saved ? "var(--green)" : "var(--orange)" }}>
                {saved
                  ? "✓ Saved — this pet now lives in the house."
                  : "Draft — save it to keep it. Unsaved pets are removed when you generate the next one."}
              </div>
            </div>
          </div>
          {/* One animated box per generated pose — a direct check that each pose built. */}
          <PoseGallery petId={job.id} />
          {datsme && (
            <div className="card mt-6 p-3" style={{ borderColor: "rgba(167,139,250,0.4)", background: "rgba(167,139,250,0.08)" }}>
              <div className="mono text-xs" style={{ color: "var(--gold)" }}>
                🐾 Designing for your DatsMe profile — adopt to add this pet to your DatsMe pet house.
              </div>
            </div>
          )}
          <div className="mt-6 flex flex-wrap gap-3">
            {datsme && (
              <button
                onClick={adopt}
                disabled={adopting}
                className="mono flex-1 rounded-lg border px-4 py-3 text-sm font-bold disabled:opacity-70"
                style={{ background: "linear-gradient(135deg, #a78bfa, #7c3aed)", color: "var(--heading)", borderColor: "transparent" }}
              >
                {adopting ? "Opening checkout…" : adoptLabel}
              </button>
            )}
            <button
              onClick={save}
              disabled={saved}
              className="mono flex-1 rounded-lg border px-4 py-3 text-sm font-bold disabled:opacity-70"
              style={
                saved
                  ? { background: "rgba(52,211,153,0.12)", color: "var(--green)", borderColor: "rgba(52,211,153,0.4)" }
                  : datsme
                    // Secondary when the DatsMe adopt is the primary action.
                    ? { background: "rgba(52,211,153,0.12)", color: "var(--green)", borderColor: "rgba(52,211,153,0.4)" }
                    : { background: "linear-gradient(135deg, #10b981, #059669)", color: "var(--heading)", borderColor: "transparent" }
              }
            >
              {saved ? `✓ Saved to ${HOUSE_NAME_OBJ}` : `💾 Save to ${HOUSE_NAME_OBJ}`}
            </button>
            <a
              href={petZipUrl(job.id)}
              download
              className="mono flex-1 rounded-lg border px-4 py-3 text-center text-sm font-semibold"
              style={{ background: "rgba(167,139,250,0.12)", color: "var(--gold)", borderColor: "rgba(167,139,250,0.4)" }}
            >
              Download pet bundle (.zip)
            </a>
            {saved && (
              <Link
                href="/house"
                className="mono flex-1 rounded-lg border px-4 py-3 text-center text-sm font-semibold"
                style={{ background: "rgba(52,211,153,0.12)", color: "var(--green)", borderColor: "rgba(52,211,153,0.4)" }}
              >
                Visit {HOUSE_NAME}
              </Link>
            )}
            <button
              onClick={onReset}
              className="mono flex-1 rounded-lg border px-4 py-3 text-sm font-semibold"
              style={{ background: "rgba(167,139,250,0.12)", color: "var(--gold)", borderColor: "rgba(167,139,250,0.4)" }}
            >
              {resetLabel}
            </button>
          </div>
          {saveError && <div className="mono mt-2 text-sm" style={{ color: "var(--accent)" }}>{saveError}</div>}
          {/* The freshly generated pet, alive on this page via the engine. */}
          <PetStage pets={[{ id: job.id, display_name: job.name }]} />
        </>
      )}
    </Shell>
  );
}

function CardShell({ children }: { children: ReactNode }) {
  return <div className="card p-6">{children}</div>;
}

/** `bare`: the caller supplies the chrome (§ Props.bare). */
function BareShell({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
