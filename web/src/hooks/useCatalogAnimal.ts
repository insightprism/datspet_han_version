"use client";

/**
 * useCatalogAnimal — load one animal's catalog entry (breeds, samples, pinned
 * motion profile) for a themed page (SPEC_PET_DESIGNER_PLATFORM §3.1). This is
 * the shared DATA-loading concern every themed page has in common; the theme
 * chrome around it stays bespoke per page (§0). Returns {animal, loading, error}.
 */

import { useEffect, useState } from "react";
import { fetchCatalog, type CatalogAnimal } from "@/lib/api";

export function useCatalogAnimal(animalKey: string) {
  const [animal, setAnimal] = useState<CatalogAnimal | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    fetchCatalog()
      .then((animals) => {
        if (cancelled) return;
        const found = animals.find((a) => a.key === animalKey) ?? null;
        setAnimal(found);
        if (!found) setError(`No "${animalKey}" world in the catalog yet.`);
      })
      .catch(() => {
        if (!cancelled) setError("Could not load this world — try the General studio.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [animalKey]);

  return { animal, loading, error };
}
