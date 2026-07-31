import { describe, expect, it } from "vitest";
import type { StoreListing } from "@/lib/api";
import { animalsPresent, filterListings, NO_FILTER, TAG_CHIP_LIMIT,
         tagsPresent } from "./storeFilter";

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

describe("the tag chips that replaced per-card tags (§6.1)", () => {
  const shelf = [
    listing({ display_name: "A", animal: "cat", tags: ["fluffy", "blue"] }),
    listing({ display_name: "B", animal: "dog", tags: ["fluffy"] }),
    listing({ display_name: "C", animal: "cat", tags: ["fluffy", "blue"] }),
    listing({ display_name: "D", animal: "bird", tags: ["rare"] }),
  ];

  it("orders by how many listings carry the tag, not alphabetically", () => {
    // A tag on one listing filters to one listing — a worse chip than one
    // shared by three.
    expect(tagsPresent(shelf)).toEqual(["fluffy", "blue", "rare"]);
  });

  it("breaks ties alphabetically so the bar does not reshuffle on refresh", () => {
    expect(tagsPresent([listing({ tags: ["zebra", "aardvark"] })]))
      .toEqual(["aardvark", "zebra"]);
  });

  it("caps the bar, leaving the long tail to the search box", () => {
    const many = listing({
      tags: Array.from({ length: TAG_CHIP_LIMIT + 5 }, (_, i) => `t${i}`),
    });
    expect(tagsPresent([many])).toHaveLength(TAG_CHIP_LIMIT);
  });

  it("is empty when nothing is tagged, so the row does not render", () => {
    expect(tagsPresent([listing({ tags: [] })])).toEqual([]);
  });
});

describe("text hidden from the card is still searchable", () => {
  // The whole premise of removing description and tags from the card: they are
  // filter vocabulary, not card content. If hiding them stopped them matching,
  // the change would have deleted a feature rather than tidied a layout.
  const shelf = [
    listing({ display_name: "Blue Butterfly", animal: "butterfly",
              description: "iridescent wings that dance", tags: ["magical"] }),
    listing({ display_name: "Black Cobra", animal: "cobra" }),
  ];

  it("matches on a word only the (now hidden) description contains", () => {
    expect(filterListings(shelf, { ...NO_FILTER, query: "iridescent" })
      .map((p) => p.display_name)).toEqual(["Blue Butterfly"]);
  });

  it("matches on a word only the (now hidden) tags contain", () => {
    expect(filterListings(shelf, { ...NO_FILTER, query: "magical" })
      .map((p) => p.display_name)).toEqual(["Blue Butterfly"]);
  });
});
