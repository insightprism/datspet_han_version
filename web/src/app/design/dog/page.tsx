"use client";

/**
 * Dog World (SPEC_PET_DESIGNER_PLATFORM §3.1) — a hand-authored themed page,
 * bespoke chrome around the shared generation trio (see /design/cat for the
 * pattern). Its look is deliberately its own — a cooler, energetic hero — so
 * "customized, uncluttered, per-animal" is a real difference, not a config flag.
 */

import Link from "next/link";
import PetDesigner from "@/components/PetDesigner";
import SampleGallery from "@/components/SampleGallery";
import { useCatalogAnimal } from "@/hooks/useCatalogAnimal";

export default function DogWorldPage() {
  const { animal, loading, error } = useCatalogAnimal("dog");

  return (
    <main>
      {/* Bespoke Dog World chrome — a cool, energetic hero, distinct from Cat World. */}
      <div
        className="mb-6 rounded-2xl p-8"
        style={{
          background: "linear-gradient(135deg, rgba(56,189,248,0.16), rgba(52,211,153,0.12))",
          border: "1px solid rgba(56,189,248,0.3)",
        }}
      >
        <div className="text-5xl">🐶</div>
        <h1 className="mt-2 text-4xl font-bold" style={{ color: "var(--heading)" }}>
          Dog World
        </h1>
        <p className="mt-2 max-w-xl text-sm leading-relaxed" style={{ color: "var(--muted)" }}>
          {animal?.tagline || "Design your own dog"} — pick a breed to start from a
          curated pup, style it your way, and teach it the moves you want. Good dogs only.
        </p>
      </div>

      <div className="mb-6 flex flex-wrap gap-3">
        <Link
          href="/design"
          className="inline-block rounded-lg border px-5 py-2.5 text-sm font-semibold transition hover:opacity-85"
          style={{ background: "rgba(56,189,248,0.12)", color: "var(--accent)", borderColor: "rgba(56,189,248,0.4)" }}
        >
          ← All the design worlds
        </Link>
        <Link
          href="/house"
          className="inline-block rounded-lg border px-5 py-2.5 text-sm font-semibold transition hover:opacity-85"
          style={{ background: "rgba(52,211,153,0.12)", color: "var(--green)", borderColor: "rgba(52,211,153,0.4)" }}
        >
          🏠 Visit the pet house →
        </Link>
      </div>

      {loading && <div className="mono text-sm" style={{ color: "var(--faint)" }}>Loading Dog World…</div>}
      {error && (
        <div className="card p-5">
          <div className="mono text-sm" style={{ color: "var(--orange)" }}>{error}</div>
          <Link href="/design/general" className="mono mt-2 inline-block text-sm underline" style={{ color: "var(--accent)" }}>
            Use the General studio instead →
          </Link>
        </div>
      )}

      {animal && (
        <>
          <PetDesigner
            base={{
              kind: "catalog",
              options: animal.breeds.map((b) => ({ ...b, animal: animal.key, animalLabel: animal.label })),
              motionProfile: animal.motion_profile,
            }}
          />
          <SampleGallery animal={animal.key} samples={animal.samples} heading="Dogs people made" />
        </>
      )}
    </main>
  );
}
