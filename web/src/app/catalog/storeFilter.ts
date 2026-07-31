/**
 * The Pet Store's client-side filter (SPEC_PET_STORE §6.1) — a pure function,
 * split out of the page so the one piece of shop logic worth pinning has a
 * test. All filtering is client-side over the one cacheable listing response;
 * the tripwire for moving it server-side is ~200+ rows (§6.1), and that move
 * happens in pet_store.py, not here.
 */
import type { StoreListing } from "@/lib/api";

export interface StoreFilter {
  /** Free text, matched case-insensitively over name + description + tags. */
  query: string;
  /** An animal chip ("cat"), or null for all. */
  animal: string | null;
  /** A tapped tag, or null for all. */
  tag: string | null;
}

export const NO_FILTER: StoreFilter = { query: "", animal: null, tag: null };

export function filterListings(
  listings: StoreListing[], filter: StoreFilter,
): StoreListing[] {
  const query = filter.query.trim().toLowerCase();
  return listings.filter((pet) => {
    if (filter.animal && pet.animal !== filter.animal) return false;
    if (filter.tag && !pet.tags.includes(filter.tag)) return false;
    if (!query) return true;
    const haystack =
      `${pet.display_name} ${pet.description} ${pet.tags.join(" ")}`.toLowerCase();
    return haystack.includes(query);
  });
}

/** The animal chips, derived from what is actually on the shelf — never a
 *  hardcoded list (§6.1). Sorted so chip order is stable across refreshes. */
export function animalsPresent(listings: StoreListing[]): string[] {
  return Array.from(new Set(listings.map((pet) => pet.animal))).sort();
}
