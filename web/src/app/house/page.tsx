"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { deletePet, listPets, petZipUrl, type PetSummary } from "@/lib/api";
import PetStage from "@/components/PetStage";
import PetThumbnail from "@/components/PetThumbnail";
import ConfirmModal from "@/components/ConfirmModal";

/**
 * The Pet House — every pet ever generated on this machine, alive at
 * once. The engine's auto state machine wanders them along the bottom
 * of the page; click anywhere to call one over, click a pet to excite it.
 */
export default function HousePage() {
  const [pets, setPets] = useState<PetSummary[] | null>(null);
  const [error, setError] = useState("");
  const [petToRemove, setPetToRemove] = useState<PetSummary | null>(null);

  useEffect(() => {
    listPets()
      .then(setPets)
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load pets"));
  }, []);

  async function confirmRemove() {
    if (!petToRemove) return;
    const pet = petToRemove;
    setPetToRemove(null);
    try {
      await deletePet(pet.id);
      setPets((cur) => (cur ? cur.filter((p) => p.id !== pet.id) : cur));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not remove the pet");
    }
  }

  return (
    <main>
      <h1 className="mb-1 text-3xl" style={{ color: "var(--heading)" }}>
        The pet house
      </h1>
      <p className="mb-4 max-w-2xl text-sm leading-relaxed" style={{ color: "var(--muted)" }}>
        Every pet made here lives on this page. They wander on their own —
        click anywhere on the page to call one over, or click a pet to get it excited.
      </p>

      <Link
        href="/"
        className="mb-6 inline-block rounded-lg border px-5 py-2.5 text-sm font-semibold transition hover:opacity-85"
        style={{ background: "rgba(99,102,241,0.12)", color: "var(--accent)", borderColor: "rgba(99,102,241,0.4)" }}
      >
        ← Back to designing
      </Link>

      {error && <div className="mono text-sm" style={{ color: "var(--accent)" }}>{error}</div>}

      {pets && pets.length === 0 && (
        <div className="card p-8 text-center">
          <p style={{ color: "var(--muted)" }}>No pets yet — the house is empty.</p>
          <Link
            href="/design/general"
            className="mono mt-4 inline-block rounded-lg border px-5 py-3 text-sm font-semibold"
            style={{ background: "rgba(99,102,241,0.12)", color: "var(--accent)", borderColor: "rgba(99,102,241,0.4)" }}
          >
            Design your first pet
          </Link>
        </div>
      )}

      {pets && pets.length > 0 && (
        <>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4">
            {pets.map((p) => (
              <div key={p.id} className="card p-4 text-center">
                <div className="mx-auto w-fit">
                  <PetThumbnail petId={p.id} size={88} />
                </div>
                <div className="mt-2 truncate text-sm" style={{ color: "var(--heading)" }}>
                  {p.display_name}
                </div>
                <div className="mono mt-0.5 truncate text-[11px]" style={{ color: "var(--faint)" }}>
                  {p.breed_id}
                </div>
                <div className="mt-2 flex flex-wrap justify-center gap-2">
                  <Link
                    href={`/design?base=${p.id}`}
                    className="inline-block rounded-md border px-3 py-1.5 text-xs font-semibold transition hover:opacity-85"
                    style={{ background: "rgba(167,139,250,0.12)", color: "var(--gold)", borderColor: "rgba(167,139,250,0.4)" }}
                  >
                    🎨 Redesign
                  </Link>
                  <a
                    href={petZipUrl(p.id)}
                    download
                    title="Download the DatsMe breed bundle — upload it in DatsMe under Settings → Pet"
                    className="rounded-md border px-3 py-1.5 text-xs font-semibold transition hover:opacity-85"
                    style={{ background: "rgba(52,211,153,0.12)", color: "var(--green)", borderColor: "rgba(52,211,153,0.4)" }}
                  >
                    ⬇ DatsMe zip
                  </a>
                  <button
                    type="button"
                    onClick={() => setPetToRemove(p)}
                    className="rounded-md border px-3 py-1.5 text-xs font-semibold transition hover:opacity-85"
                    style={{ background: "rgba(239,68,68,0.1)", color: "#f87171", borderColor: "rgba(239,68,68,0.35)" }}
                  >
                    🗑 Remove
                  </button>
                </div>
              </div>
            ))}
          </div>

          {/* All pets, alive. Fixed to the viewport floor by the engine. */}
          <PetStage pets={pets.map((p) => ({ id: p.id, display_name: p.display_name }))} />
        </>
      )}

      <ConfirmModal
        open={petToRemove !== null}
        title={`Remove ${petToRemove?.display_name ?? "this pet"}?`}
        body="It disappears from the house and its bundle is deleted from this machine. This can't be undone (though you can always generate a similar one)."
        confirmLabel="Remove pet"
        onConfirm={confirmRemove}
        onCancel={() => setPetToRemove(null)}
      />
    </main>
  );
}
