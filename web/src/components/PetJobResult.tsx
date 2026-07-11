"use client";

/**
 * PetJobResult — the progress bar while a pet generates, and the finished
 * panel (portrait, actions, and the pet itself walking onto the page).
 * Shared by the Describe and Design pages.
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { keepPet, petZipUrl, type JobStatus } from "@/lib/api";
import PetStage from "@/components/PetStage";
import PetThumbnail from "@/components/PetThumbnail";

interface Props {
  job: JobStatus;
  onReset: () => void;
  resetLabel?: string;
}

export default function PetJobResult({ job, onReset, resetLabel = "Make another" }: Props) {
  const done = job.status === "done";
  // Fresh pets are DRAFTS: they only join the house when saved here.
  // Unsaved drafts are removed when the next generation starts.
  const [saved, setSaved] = useState(false);
  const [saveError, setSaveError] = useState("");

  useEffect(() => setSaved(false), [job.id]);

  async function save() {
    setSaveError("");
    try {
      await keepPet(job.id);
      setSaved(true);
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : "Could not save");
    }
  }
  return (
    <div className="card p-6">
      <div className="mono mb-1.5 text-sm" style={{ color: job.status === "error" ? "var(--accent)" : "var(--gold)" }}>
        {job.message}
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

      {done && (
        <>
          <div className="mt-6 flex flex-wrap items-center gap-5">
            <div className="card p-3" style={{ borderColor: "rgba(52,211,153,0.4)" }}>
              <PetThumbnail petId={job.id} size={128} />
            </div>
            <div>
              <div className="text-xl" style={{ color: "var(--heading)" }}>{job.name}</div>
              <div className="mono mt-1 text-xs" style={{ color: "var(--muted)" }}>
                breed_id: {job.breed_id} · walk + idle · DatsMe bundle
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
          <div className="mt-6 flex flex-wrap gap-3">
            <button
              onClick={save}
              disabled={saved}
              className="mono flex-1 rounded-lg border px-4 py-3 text-sm font-bold disabled:opacity-70"
              style={
                saved
                  ? { background: "rgba(52,211,153,0.12)", color: "var(--green)", borderColor: "rgba(52,211,153,0.4)" }
                  : { background: "linear-gradient(135deg, #10b981, #059669)", color: "var(--heading)", borderColor: "transparent" }
              }
            >
              {saved ? "✓ Saved to the pet house" : "💾 Save to the pet house"}
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
                Visit the pet house
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
    </div>
  );
}
