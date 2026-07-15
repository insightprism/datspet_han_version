import { describe, it, expect } from "vitest";
import type { BodyShape, PetReference } from "@/lib/api";
import {
  initialState, designFlowReducer, frontier, previewSettled,
  type DesignFlowState,
} from "./designFlow";

/**
 * The reducer IS the product (SPEC_PET_DESIGNER_FLOW §7.6): the invalidation rules —
 * what a new archetype voids, what survives it, what gates the next step — are the
 * design, not an implementation detail of it. So they are pinned here.
 *
 * These exist because the flow shipped with no frontend tests and review found two
 * regressions in this exact file, both of which a handful of assertions would have
 * caught. Each test below names the failure it prevents rather than the function it
 * calls; a test that only says "reducer works" would have passed while both bugs shipped.
 *
 * No jsdom, no React, no mocks: the reducer is pure, so this is arithmetic.
 */

const SHAPES: BodyShape[] = [
  { key: "normal", label: "Normal", is_default: true },
  { key: "fat", label: "Chubby", is_default: false },
];

const ref = (id: string, name: string): PetReference => ({
  reference_id: id, image_url: `/api/reference/${id}.png`,
  description: name, display_name: name,
  motion_profile: "quadruped", source: "catalog",
  min_strength: null, generated: false,
});

/** Step 1 done: an archetype is in the box and the user has said it is the one. */
function atStepTwo(name = "tabby"): DesignFlowState {
  let s = initialState(0.85);
  s = designFlowReducer(s, { type: "referenceFilled", seq: s.seq, reference: ref("r1", name) });
  return designFlowReducer(s, { type: "baseAccepted" });
}

/** Step 2 in progress: a design exists, nothing previewed yet. */
function designed(): DesignFlowState {
  return designFlowReducer(atStepTwo(), { type: "colorPicked", color: "purple" });
}

describe("§5.2 — the step-2 gate", () => {
  it("blocks the lock until a preview settles: a design alone is not an answer", () => {
    const s = designed();
    expect(frontier(s, SHAPES)).toBe(2);
    expect(previewSettled(s)).toBe(false);
  });

  it("does not let a dead lock claim step 2 is settled", () => {
    // The regression: the button gated on `preview ?? reference`, which is ALWAYS truthy
    // at step 2 — so it went live with nothing previewed, and clicking it turned step 2
    // green while the frontier held step 3 shut. A click that lies about its own outcome.
    const clicked = designFlowReducer(designed(), { type: "designAccepted" });
    expect(clicked.designConfirmed).toBe(true);          // the reducer honours the click…
    expect(frontier(clicked, SHAPES)).toBe(2);           // …but the step is NOT done,
    expect(previewSettled(clicked)).toBe(false);         // so the button must be disabled.
  });

  it("opens the escape hatch once a failure is explicitly dismissed", () => {
    // §5.2's whole point: a user whose preview keeps failing must get FORWARD, not just
    // a retry. Gating on `!s.preview` alone is the dead end the spec names.
    const s = designFlowReducer(designed(), { type: "previewFailureDismissed" });
    expect(previewSettled(s)).toBe(true);
    expect(frontier(designFlowReducer(s, { type: "designAccepted" }), SHAPES)).toBe(3);
  });
});

describe("§7.6 — what a new archetype voids, and what it must not", () => {
  // The regression: dismiss a failure on the tabby, switch to a corgi, and the gate stayed
  // satisfied — you walked to a 3-minute build having never previewed the corgi, on a
  // dismissal you gave for a different animal.
  //
  // TWO tests, not one, because there are two ways to reach a new archetype and they clear
  // the flag in DIFFERENT reducer cases. Unlocking then filling only proves `baseUnlocked`
  // resets it; a mutation that strips the reset from `referenceFilled` survives that test
  // untouched, because the flag was already false by the time the fill ran. Ask any single
  // sequence and it answers for one case while the other rots.
  it("clears a dismissal when the base is unlocked (the 🔒 toggle path)", () => {
    let s = designFlowReducer(designed(), { type: "previewFailureDismissed" });
    expect(previewSettled(s)).toBe(true);

    s = designFlowReducer(s, { type: "baseUnlocked" });
    expect(s.previewFailureDismissed).toBe(false);
  });

  it("clears a dismissal when a new archetype lands WITHOUT an unlock (the click-the-box path)", () => {
    // Designer.tsx's `onOpen` is `setDialogOpen(true)` — it does NOT dispatch baseUnlocked.
    // So clicking the reference box itself, rather than the lock toggle, lands a fill with
    // the dismissal still set. This is the path that makes referenceFilled's reset
    // load-bearing rather than belt-and-braces.
    let s = designFlowReducer(designed(), { type: "previewFailureDismissed" });
    expect(previewSettled(s)).toBe(true);

    s = designFlowReducer(s, { type: "referenceFilled", seq: s.seq, reference: ref("r2", "corgi") });
    expect(s.previewFailureDismissed).toBe(false);

    s = designFlowReducer(s, { type: "baseAccepted" });
    s = designFlowReducer(s, { type: "designAccepted" });
    expect(frontier(s, SHAPES)).toBe(2);   // blocked: the corgi was never previewed
  });

  it("keeps the design when the archetype changes (§0.1 — they were never its properties)", () => {
    let s = designFlowReducer(designed(), { type: "bodyShapePicked", key: "fat" });
    s = designFlowReducer(s, { type: "referenceFilled", seq: s.seq, reference: ref("r2", "corgi") });
    expect(s.color).toBe("purple");        // "I want it chubby and purple" survives
    expect(s.bodyShape).toBe("fat");       // changing my mind from tabby to corgi.
    expect(s.preview).toBeNull();          // Only the preview dies — it is (base × design).
  });

  it("drops a stale fill so a slow draw cannot overwrite a newer one", () => {
    // The race Rev.2 documented: change the base mid-draw and the old one lands on top.
    const s = designed();
    const stale = designFlowReducer(s, {
      type: "referenceFilled", seq: s.seq - 1, reference: ref("old", "ferret"),
    });
    expect(stale).toBe(s);                 // identity: the action was ignored entirely
  });
});
