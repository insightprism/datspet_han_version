/**
 * SPEC_MOTION_LAB_DESIGN_PARITY §5 test 9 — the guard the spec named for when D5 landed.
 *
 * `PoseGallery` renders the user's finished pet on the result panel and passes a `petId`.
 * Widening PosePlayer to also accept an explicit sheet (for the Lab's packed tile, which
 * has no saved pet) must not have changed that path at all.
 */
import { describe, expect, it } from "vitest";
import { petManifestUrl, petSheetUrl } from "@/lib/api";
import { posePlayerUrls } from "./posePlayerSource";

describe("posePlayerUrls", () => {
  it("derives a saved pet's URLs exactly as before the widening", () => {
    // Compared against the api adapter itself, not against copied strings: if the URL
    // shape ever changes, this follows it rather than pinning a stale literal.
    expect(posePlayerUrls({ petId: "pet123" })).toEqual({
      manifest: petManifestUrl("pet123"),
      sheet: petSheetUrl("pet123"),
    });
  });

  it("passes an explicit sheet straight through — the Lab's packed tile", () => {
    expect(posePlayerUrls({ sheetUrl: "/a/p.png", manifestUrl: "/a/p.json" }))
      .toEqual({ manifest: "/a/p.json", sheet: "/a/p.png" });
  });

  it("never mixes the two shapes", () => {
    // A petId source must not leak an explicit URL, and vice versa — the union is the
    // point, and a resolver that fell through to both would silently prefer one.
    const saved = posePlayerUrls({ petId: "abc" });
    expect(saved.sheet).toContain("abc");
    const explicit = posePlayerUrls({ sheetUrl: "/x.png", manifestUrl: "/x.json" });
    expect(explicit.sheet).not.toContain("abc");
  });
});
