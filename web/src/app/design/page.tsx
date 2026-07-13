"use client";

/**
 * Designer landing page (SPEC_PET_DESIGNER_PLATFORM §2) — the front door of the
 * designer surface. Pure navigation + merchandising: one tile per "world" (each
 * catalog animal that has a themed page) plus General, always present as the
 * long-tail / power path. The tile list is DATA-DRIVEN from /api/catalog (§4) —
 * adding "Dragon Lair" is a catalog entry + a themed shell, never a change here.
 *
 * Nothing about generation happens on this page. A themed tile routes to
 * /design/<themed_page> carrying the body-type forward; General routes to
 * /design/general (today's form). The DPP launch cookie is origin-scoped, so a
 * launched user survives the landing hop and picks a world like anyone else (§2).
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { fetchCatalog, catalogBaseImageUrl, type CatalogAnimal } from "@/lib/api";

export default function DesignLandingPage() {
  const [animals, setAnimals] = useState<CatalogAnimal[]>([]);
  const [loadError, setLoadError] = useState("");

  useEffect(() => {
    fetchCatalog()
      .then(setAnimals)
      .catch(() => setLoadError("Could not load the design worlds — the General path still works."));
  }, []);

  // Only animals with a themed page get a tile; the rest are reachable via General.
  const themed = animals.filter((a) => a.themed_page);

  return (
    <main>
      <h1 className="mb-1 text-3xl" style={{ color: "var(--heading)" }}>
        Design a pet
      </h1>
      <p className="mb-6 max-w-2xl text-sm leading-relaxed" style={{ color: "var(--muted)" }}>
        Pick a world to design in. Each one starts you from a curated base — a real
        picture, not a blank screen — so your pet looks right and moves right. Or use
        the General studio to redesign any pet already in your house.
      </p>

      <div className="mb-6 flex flex-wrap gap-3">
        <Link
          href="/"
          className="inline-block rounded-lg border px-5 py-2.5 text-sm font-semibold transition hover:opacity-85"
          style={{ background: "rgba(99,102,241,0.12)", color: "var(--accent)", borderColor: "rgba(99,102,241,0.4)" }}
        >
          ← Describe a pet instead
        </Link>
        <Link
          href="/house"
          className="inline-block rounded-lg border px-5 py-2.5 text-sm font-semibold transition hover:opacity-85"
          style={{ background: "rgba(52,211,153,0.12)", color: "var(--green)", borderColor: "rgba(52,211,153,0.4)" }}
        >
          🏠 Visit the pet house →
        </Link>
      </div>

      {loadError && (
        <div className="mono mb-4 text-sm" style={{ color: "var(--orange)" }}>{loadError}</div>
      )}

      <div className="grid gap-5" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))" }}>
        {themed.map((a) => {
          const hero = a.breeds[0];
          return (
            <Link
              key={a.key}
              href={`/design/${a.themed_page}`}
              className="card group flex flex-col items-center p-5 text-center transition hover:opacity-90"
              style={{ textDecoration: "none" }}
            >
              <div
                className="mb-3 flex h-40 w-full items-center justify-center rounded-xl"
                style={{ background: "#101010", border: "1px solid var(--line)" }}
              >
                {hero ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={catalogBaseImageUrl(a.key, hero.key)}
                    alt={`${a.label} base`}
                    style={{ maxWidth: "90%", maxHeight: "90%", objectFit: "contain" }}
                  />
                ) : (
                  <span style={{ color: "var(--faint)" }}>🐾</span>
                )}
              </div>
              <div className="text-lg font-semibold" style={{ color: "var(--heading)" }}>
                {a.label} World
              </div>
              <div className="mono mt-1 text-xs" style={{ color: "var(--muted)" }}>
                {a.tagline || `Design your own ${a.label.toLowerCase()}`}
              </div>
              <div className="mono mt-2 text-xs" style={{ color: "var(--faint)" }}>
                {a.breeds.length} breed{a.breeds.length === 1 ? "" : "s"}
              </div>
            </Link>
          );
        })}

        {/* General is always present — the long-tail / power path (§2/§3.3). */}
        <Link
          href="/design/general"
          className="card group flex flex-col items-center p-5 text-center transition hover:opacity-90"
          style={{ textDecoration: "none" }}
        >
          <div
            className="mb-3 flex h-40 w-full items-center justify-center rounded-xl text-5xl"
            style={{ background: "#101010", border: "1px solid var(--line)" }}
          >
            🎨
          </div>
          <div className="text-lg font-semibold" style={{ color: "var(--heading)" }}>
            General Studio
          </div>
          <div className="mono mt-1 text-xs" style={{ color: "var(--muted)" }}>
            Redesign any pet in your house
          </div>
          <div className="mono mt-2 text-xs" style={{ color: "var(--faint)" }}>
            every control, any species
          </div>
        </Link>
      </div>
    </main>
  );
}
