import { describe, expect, it } from "vitest";
import type { StoreListing } from "@/lib/api";
import { animalsPresent, filterListings, NO_FILTER } from "./storeFilter";

function listing(overrides: Partial<StoreListing>): StoreListing {
  return {
    id: "x", display_name: "Pet", breed_id: "pet", animal: "cat",
    description: "", tags: [], pose_count: 2, poses: ["walk", "idle"],
    created_at: 0, preview_url: "/api/store/x/preview.png",
    ...overrides,
  };
}

const SHELF: StoreListing[] = [
  listing({ id: "leo", display_name: "Snowy The Leopard", animal: "cat",
            description: "A fluffy mountain cat.", tags: ["fluffy", "white"] }),
  listing({ id: "shiba", display_name: "Biscuit", animal: "dog",
            description: "A cheerful shiba.", tags: ["orange"] }),
  listing({ id: "bat", display_name: "Echo", animal: "bat",
            description: "A tiny night flyer.", tags: ["black", "tiny"] }),
];

describe("filterListings", () => {
  it("passes everything through with no filter", () => {
    expect(filterListings(SHELF, NO_FILTER)).toHaveLength(3);
  });

  it("matches the query against name, description, and tags, case-insensitively", () => {
    expect(filterListings(SHELF, { ...NO_FILTER, query: "SNOWY" })
      .map((p) => p.id)).toEqual(["leo"]);
    expect(filterListings(SHELF, { ...NO_FILTER, query: "cheerful" })
      .map((p) => p.id)).toEqual(["shiba"]);
    expect(filterListings(SHELF, { ...NO_FILTER, query: "tiny" })
      .map((p) => p.id)).toEqual(["bat"]);          // tag text is searchable
    expect(filterListings(SHELF, { ...NO_FILTER, query: "  " }))
      .toHaveLength(3);                             // whitespace = no query
  });

  it("filters by animal chip and by tapped tag, and composes them with the query", () => {
    expect(filterListings(SHELF, { ...NO_FILTER, animal: "cat" })
      .map((p) => p.id)).toEqual(["leo"]);
    expect(filterListings(SHELF, { ...NO_FILTER, tag: "orange" })
      .map((p) => p.id)).toEqual(["shiba"]);
    // tag must be an exact member, not a substring of another tag
    expect(filterListings(SHELF, { ...NO_FILTER, tag: "tin" })).toHaveLength(0);
    expect(filterListings(SHELF, { query: "fluffy", animal: "dog", tag: null }))
      .toHaveLength(0);
  });
});

describe("animalsPresent", () => {
  it("derives sorted, deduplicated chips from the shelf", () => {
    expect(animalsPresent(SHELF)).toEqual(["bat", "cat", "dog"]);
    expect(animalsPresent([])).toEqual([]);
  });
});
