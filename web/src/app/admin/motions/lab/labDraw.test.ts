/**
 * labDraw — the Motion Lab's request shaping (SPEC_MOTION_LAB_DESIGN_PARITY §5, tests 9–10).
 *
 * WHY THESE TWO EXIST. D6 (§2.6) gave `base` a job it did not have before: it selects the
 * prompt SENTENCE, not just img2img-vs-txt2img. A base draw that forgets the flag now gets
 * an anchor's sentence — and no server-side guard can catch it, because nothing in webui/
 * can tell a base draw that lied from an anchor that told the truth. The bug it replaced
 * was exactly this: `doDrawBase` sent `base: true` only when a reference existed, which was
 * harmless while the flag did nothing on the other path.
 *
 * Pure by construction (I10): the frontend's vitest has no jsdom and no React testing, so
 * the logic worth guarding was moved OUT of the component to here rather than a browser
 * harness being introduced to reach it.
 */
import { describe, expect, it } from "vitest";
import { baseDrawOptions, packedTile, poseSubject } from "./labDraw";

describe("baseDrawOptions", () => {
  it("always marks the draw as a base — with a reference and without", () => {
    expect(baseDrawOptions(null, 0.85).base).toBe(true);
    expect(baseDrawOptions("abc123", 0.85).base).toBe(true);
  });

  it("carries the reference and its denoise only when there is a reference", () => {
    // No reference → txt2img from text: a `strength` would be inert, and the absence is
    // what makes the request identical to step 1's archetype draw.
    expect(baseDrawOptions(null, 0.7)).toEqual({ base: true });
    expect(baseDrawOptions("abc123", 0.7)).toEqual({
      base: true, reference_id: "abc123", strength: 0.7,
    });
  });

  it("attaches a design only to a redraw of a reference (the I13 mirror)", () => {
    const design = { color: "white", accessories: ["crown"], axis_picks: { body: "fat" }, extra: "" };
    expect(baseDrawOptions("abc123", 0.85, design).design).toEqual(design);
    // The server 400s a design with nowhere to land; the UI must not get there. Dropping
    // it here is safe precisely BECAUSE the button that sends one requires a base still.
    expect(baseDrawOptions(null, 0.85, design)).toEqual({ base: true });
  });
});

describe("poseSubject", () => {
  const upload = {
    kind: "upload" as const, reference_id: "u1", url: "/u1.png",
    upload: { reference_id: "u1", url: "/u1.png", usable: true, subject: "lion", features: "", description: "" },
  };
  const design = {
    kind: "design" as const, reference_id: "d1", url: "/d1.png",
    description: "chubby and round vivid white snow leopard, recolored entirely white",
    subject: "white snow leopard",
  };

  it("is the typed animal until a design exists", () => {
    expect(poseSubject(null, "  snow leopard  ")).toBe("snow leopard");
    // An uploaded PHOTO is not a design: it changes what the base is redrawn from, not
    // what the pet is called. A build's upload keeps the captioner's noun as description.
    expect(poseSubject(upload, "snow leopard")).toBe("snow leopard");
  });

  it("becomes the designed display name once a design is applied", () => {
    // The regression this file exists for: with the typed noun here, a designed white
    // snow leopard drew TAN anchors — an animal no build would have produced.
    expect(poseSubject(design, "snow leopard")).toBe("white snow leopard");
  });
});

describe("packedTile", () => {
  const abs = (u: string) => `http://api${u}`;

  it("resolves both URLs once the pack lands", () => {
    expect(packedTile({ packed_url: "/a/p.png", packed_manifest_url: "/a/p.json" }, abs))
      .toEqual({ sheetUrl: "http://api/a/p.png", manifestUrl: "http://api/a/p.json" });
  });

  it("is null while the pack is still running, and after a pack FAILURE", () => {
    // The loop is published ~6 s before the packed sheet (§12.2), so "no tile yet" is the
    // normal mid-run state — not an error, and not a reason to hold the raw tile back.
    expect(packedTile({ packed_url: null, packed_manifest_url: null }, abs)).toBeNull();
    // A pack that failed leaves the job done with its loop intact. The packed tile is the
    // only casualty; the raw one, which cost ~40 s of GPU, must survive.
    expect(packedTile({ packed_url: null, packed_manifest_url: "/a/p.json" }, abs)).toBeNull();
    expect(packedTile({ packed_url: "/a/p.png", packed_manifest_url: null }, abs)).toBeNull();
  });
});
