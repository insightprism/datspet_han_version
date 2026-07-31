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

/** How many tag chips the filter bar offers. Tags are per-listing and
 *  unbounded, so the whole shelf's vocabulary would outgrow the bar long
 *  before the shelf outgrows one page. The rest stay reachable through the
 *  search box, which matches tags too. */
export const TAG_CHIP_LIMIT = 12;

/**
 * The tag chips, most-used first — the filter bar's copy of what used to live
 * on every card (§6.1).
 *
 * Tags moved off the cards because a shopper reads the picture, not the prose;
 * they are filter vocabulary, not card content. But they were also the ONLY
 * way to SET a tag filter, so hiding them without putting them here would have
 * removed the filter rather than tidied it.
 *
 * Frequency first because a tag on one listing filters to one listing, which
 * is a worse chip than one shared by six. Ties break alphabetically so the bar
 * does not reshuffle between refreshes.
 */
export function tagsPresent(listings: StoreListing[]): string[] {
  const counts = new Map<string, number>();
  for (const pet of listings) {
    for (const tag of pet.tags) counts.set(tag, (counts.get(tag) ?? 0) + 1);
  }
  return Array.from(counts.entries())
    .sort((a, b) => (b[1] - a[1]) || a[0].localeCompare(b[0]))
    .slice(0, TAG_CHIP_LIMIT)
    .map(([tag]) => tag);
}
