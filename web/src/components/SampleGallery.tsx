"use client";

/**
 * <SampleGallery> — "pets people made" (SPEC_PET_DESIGNER_PLATFORM §4.4). Surfaces
 * an animal's curated sample pets; a user can adopt one directly, which skips
 * generation entirely (zero GPU) — a free/cheap tier lever. Adopt copies the
 * stored bundle into the caller's house as a draft, then the adopted pet flows
 * through the SAME result panel (<PetJobResult>) a generated pet does: Save to
 * house, Accept to DatsMe, download, walk onto the page.
 *
 * Shared + config-fed like <PetDesigner> (§0): a themed page drops it in with an
 * `animal` and `samples` list read from the catalog; the chrome stays bespoke.
 * An animal with no samples renders nothing (the section just doesn't appear).
 */

import { useState } from "react";
import {
  adoptSample, catalogSamplePreviewUrl,
  type CatalogSample, type JobStatus,
} from "@/lib/api";
import PetJobResult from "@/components/PetJobResult";

interface Props {
  animal: string;
  samples: CatalogSample[];
  heading?: string;
}

export default function SampleGallery({ animal, samples, heading = "Pets people made" }: Props) {
  const [adopting, setAdopting] = useState<string | null>(null);
  const [error, setError] = useState("");
  // An adopted pet reuses the generated-pet result panel — build a synthetic
  // "done" job for it (adopt is instant, so there is no queue/poll lifecycle).
  const [adopted, setAdopted] = useState<JobStatus | null>(null);

  if (samples.length === 0) return null;

  async function adopt(sample: CatalogSample) {
    setError("");
    setAdopting(sample.key);
    try {
      const res = await adoptSample(animal, sample.key);
      setAdopted({
        id: res.pet_id, name: res.display_name, status: "done",
        progress: 1, message: "Adopted!", breed_id: res.breed_id, error: null,
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not adopt this pet");
    } finally {
      setAdopting(null);
    }
  }

  // Once adopted, show the result panel (Save/Accept/download/walk-on) and let
  // the user reset back to the gallery.
  if (adopted) {
    return <PetJobResult job={adopted} onReset={() => setAdopted(null)} resetLabel="Back to samples" />;
  }

  return (
    <div className="mt-8">
      <h2 className="mb-1 text-xl" style={{ color: "var(--heading)" }}>{heading}</h2>
      <p className="mb-4 text-sm" style={{ color: "var(--muted)" }}>
        Adopt one as-is — it lands in your house instantly, no waiting for a build.
      </p>
      <div className="grid gap-4" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))" }}>
        {samples.map((s) => (
          <div key={s.key} className="card flex flex-col items-center p-4 text-center">
            <div
              className="mb-3 flex h-32 w-full items-center justify-center rounded-lg"
              style={{ background: "#101010", border: "1px solid var(--line)" }}
            >
              {s.preview_url ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={catalogSamplePreviewUrl(s.preview_url)}
                  alt={`${s.key} sample`}
                  style={{ maxWidth: "90%", maxHeight: "90%", objectFit: "contain" }}
                />
              ) : (
                <span style={{ color: "var(--faint)" }}>🐾</span>
              )}
            </div>
            <button
              type="button"
              onClick={() => adopt(s)}
              disabled={adopting !== null}
              className="mono w-full rounded-lg border px-3 py-2 text-sm font-semibold disabled:opacity-45"
              style={{ background: "rgba(52,211,153,0.12)", color: "var(--green)", borderColor: "rgba(52,211,153,0.4)" }}
            >
              {adopting === s.key ? "Adopting…" : "🐾 Adopt this one (free)"}
            </button>
          </div>
        ))}
      </div>
      {error && <div className="mono mt-3 text-sm" style={{ color: "var(--accent)" }}>{error}</div>}
    </div>
  );
}
