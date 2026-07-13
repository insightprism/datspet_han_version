"use client";

/**
 * Cat World (SPEC_PET_DESIGNER_PLATFORM §3.1) — a hand-authored themed page.
 * The chrome (background, copy, "Cat World" vibe) is bespoke and free to look
 * like nothing else; the generation machinery is NOT hand-rolled — it composes
 * the shared, config-fed trio: the breed picker + curated base (inside
 * <PetDesigner base=catalog>), the pose selector (reads the catalog-pinned
 * motion profile), and <SampleGallery> (adopt a pre-made cat, GPU-free).
 *
 * Adding a new world never touches this file — it's a new catalog folder + a new
 * themed shell (§0). Restyling Cat World touches only Cat World.
 */

import Link from "next/link";
import PetDesigner from "@/components/PetDesigner";
import SampleGallery from "@/components/SampleGallery";
import { useCatalogAnimal } from "@/hooks/useCatalogAnimal";

export default function CatWorldPage() {
  const { animal, loading, error } = useCatalogAnimal("cat");

  return (
    <main>
      {/* Bespoke Cat World chrome — a soft, warm hero unlike the other pages. */}
      <div
        className="mb-6 rounded-2xl p-8"
        style={{
          background: "linear-gradient(135deg, rgba(251,146,60,0.16), rgba(167,139,250,0.12))",
          border: "1px solid rgba(251,146,60,0.3)",
        }}
      >
        <div className="text-5xl">🐱</div>
        <h1 className="mt-2 text-4xl font-bold" style={{ color: "var(--heading)" }}>
          Cat World
        </h1>
        <p className="mt-2 max-w-xl text-sm leading-relaxed" style={{ color: "var(--muted)" }}>
          {animal?.tagline || "Design your own cat"} — start from a curated cat, pick a
          color and a few accessories, choose which poses it should learn, and watch it
          come to life. Every cat here moves like a cat.
        </p>
      </div>

      <div className="mb-6 flex flex-wrap gap-3">
        <Link
          href="/design"
          className="inline-block rounded-lg border px-5 py-2.5 text-sm font-semibold transition hover:opacity-85"
          style={{ background: "rgba(251,146,60,0.12)", color: "var(--orange)", borderColor: "rgba(251,146,60,0.4)" }}
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

      {loading && <div className="mono text-sm" style={{ color: "var(--faint)" }}>Loading Cat World…</div>}
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
              animal: animal.key,
              breeds: animal.breeds,
              motionProfile: animal.motion_profile,
            }}
          />
          <SampleGallery animal={animal.key} samples={animal.samples} heading="Cats people made" />
        </>
      )}
    </main>
  );
}
