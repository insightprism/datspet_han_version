"use client";

/**
 * General designer (SPEC_PET_DESIGNER_PLATFORM §3.3) — redesign from a CURATED
 * BASE, in one flat list across every animal. A base pet is a purposely-chosen,
 * clean starting point (from pet_factory/animal_catalog), NOT whatever has piled
 * up in your house — so the "Pet to redesign" list is the curated base set, not
 * /api/pets. The themed pages (Cat/Dog World) show one animal's bases; General
 * shows them all together.
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import PetDesigner, { type CatalogBaseOption } from "@/components/PetDesigner";
import { fetchCatalog, catalogBaseOptions } from "@/lib/api";

export default function GeneralDesignPage() {
  const [options, setOptions] = useState<CatalogBaseOption[] | null>(null);
  const [loadError, setLoadError] = useState("");

  useEffect(() => {
    fetchCatalog()
      .then((animals) => setOptions(catalogBaseOptions(animals)))
      .catch(() => setLoadError("Could not load the base pets."));
  }, []);

  return (
    <main>
      <h1 className="mb-1 text-3xl" style={{ color: "var(--heading)" }}>
        Design your own
      </h1>
      <p className="mb-4 max-w-2xl text-sm leading-relaxed" style={{ color: "var(--muted)" }}>
        Pick a base pet, choose a new color and some accessories, and it gets redrawn to your
        design — same shape, new look. The prompt is composed for you.
      </p>

      <div className="mb-6 flex flex-wrap gap-3">
        <Link
          href="/design"
          className="inline-block rounded-lg border px-5 py-2.5 text-sm font-semibold transition hover:opacity-85"
          style={{ background: "rgba(167,139,250,0.12)", color: "var(--gold)", borderColor: "rgba(167,139,250,0.4)" }}
        >
          ← All the design worlds
        </Link>
        <Link
          href="/make"
          className="inline-block rounded-lg border px-5 py-2.5 text-sm font-semibold transition hover:opacity-85"
          style={{ background: "rgba(99,102,241,0.12)", color: "var(--accent)", borderColor: "rgba(99,102,241,0.4)" }}
        >
          Describe a pet instead
        </Link>
        <Link
          href="/house"
          className="inline-block rounded-lg border px-5 py-2.5 text-sm font-semibold transition hover:opacity-85"
          style={{ background: "rgba(52,211,153,0.12)", color: "var(--green)", borderColor: "rgba(52,211,153,0.4)" }}
        >
          🏠 Visit the pet house →
        </Link>
      </div>

      {loadError && <div className="mono mb-4 text-sm" style={{ color: "var(--orange)" }}>{loadError}</div>}

      {options && options.length > 0 ? (
        <PetDesigner base={{ kind: "catalog", options }} />
      ) : options && options.length === 0 ? (
        <div className="card p-5">
          <p className="text-sm" style={{ color: "var(--muted)" }}>
            No curated base pets yet. Add some to the catalog (pet_factory/animal_catalog), or
            {" "}<Link href="/make" className="underline" style={{ color: "var(--accent)" }}>describe a pet from scratch</Link>.
          </p>
        </div>
      ) : (
        !loadError && <div className="mono text-sm" style={{ color: "var(--faint)" }}>Loading base pets…</div>
      )}
    </main>
  );
}
