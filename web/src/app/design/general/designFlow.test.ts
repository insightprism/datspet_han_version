import { describe, it, expect } from "vitest";
import type { DesignAxis, PetReference } from "@/lib/api";
import {
  initialState, designFlowReducer, frontier, previewSettled, hasDesign,
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

const AXES: DesignAxis[] = [
  {
    axis: "body", label: "body", kind: "universal", default: "normal",
    options: [
      { key: "normal", label: "Normal", is_default: true },
      { key: "fat", label: "Chubby", is_default: false },
    ],
  },
];

const ref = (id: string, name: string): PetReference => ({
  reference_id: id, image_url: `/api/reference/${id}.png`,
  description: name, display_name: name,
  motion_profile: "quadruped", source: "catalog",
  min_strength: null, generated: false, suggested_subject: null,
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
    expect(frontier(s, AXES)).toBe(2);
    expect(previewSettled(s)).toBe(false);
  });

  it("does not let a dead lock claim step 2 is settled", () => {
    // The regression: the button gated on `preview ?? reference`, which is ALWAYS truthy
    // at step 2 — so it went live with nothing previewed, and clicking it turned step 2
    // green while the frontier held step 3 shut. A click that lies about its own outcome.
    const clicked = designFlowReducer(designed(), { type: "designAccepted" });
    expect(clicked.designConfirmed).toBe(true);          // the reducer honours the click…
    expect(frontier(clicked, AXES)).toBe(2);           // …but the step is NOT done,
    expect(previewSettled(clicked)).toBe(false);         // so the button must be disabled.
  });

  it("opens the escape hatch once a failure is explicitly dismissed", () => {
    // §5.2's whole point: a user whose preview keeps failing must get FORWARD, not just
    // a retry. Gating on `!s.preview` alone is the dead end the spec names.
    const s = designFlowReducer(designed(), { type: "previewFailureDismissed" });
    expect(previewSettled(s)).toBe(true);
    expect(frontier(designFlowReducer(s, { type: "designAccepted" }), AXES)).toBe(3);
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
    // the dismissal still set. referenceRequested now resets it at fire time, so in the
    // app this fill-time reset is the backstop — but it is pinned separately, because a
    // fill whose request was somehow skipped must not smuggle a stale dismissal in.
    let s = designFlowReducer(designed(), { type: "previewFailureDismissed" });
    expect(previewSettled(s)).toBe(true);

    s = designFlowReducer(s, { type: "referenceFilled", seq: s.seq, reference: ref("r2", "corgi") });
    expect(s.previewFailureDismissed).toBe(false);

    s = designFlowReducer(s, { type: "baseAccepted" });
    s = designFlowReducer(s, { type: "designAccepted" });
    expect(frontier(s, AXES)).toBe(2);   // blocked: the corgi was never previewed
  });

  it("keeps the design when the archetype changes (§0.1 — they were never its properties)", () => {
    let s = designFlowReducer(designed(), { type: "axisPicked", axis: "body", key: "fat" });
    s = designFlowReducer(s, { type: "referenceFilled", seq: s.seq, reference: ref("r2", "corgi") });
    expect(s.color).toBe("purple");             // "I want it chubby and purple" survives
    expect(s.axisPicks.body).toBe("fat");       // changing my mind from tabby to corgi.
    expect(s.preview).toBeNull();          // Only the preview dies — it is (base × design).
  });

  it("counts a non-default axis pick as a design, and nothing else", () => {
    // SPEC_PET_DESIGN_AXES §4: the "designing nothing is adopting" guard widened —
    // hasDesign is what the preview button gates on, and it must agree with the
    // server's rule, or the button and the 400 it triggers would disagree about
    // whether a design exists. A default pick, an unknown option, and a pick on
    // an axis the server never offered for THIS animal are all NOT designs.
    const untouched = atStepTwo();
    expect(hasDesign(untouched, AXES)).toBe(false);
    const realPick = designFlowReducer(untouched, { type: "axisPicked", axis: "body", key: "fat" });
    expect(hasDesign(realPick, AXES)).toBe(true);
    const defaultPick = designFlowReducer(untouched, { type: "axisPicked", axis: "body", key: "normal" });
    const unknownOption = designFlowReducer(untouched, { type: "axisPicked", axis: "body", key: "bogus" });
    const unservedAxis = designFlowReducer(untouched, { type: "axisPicked", axis: "plumage", key: "ruffled" });
    for (const state of [defaultPick, unknownOption, unservedAxis]) {
      expect(hasDesign(state, AXES)).toBe(false);
    }
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

describe("the lock cannot outlive the base it recorded", () => {
  // The box is a door into the chooser even while locked — artifacts never unmount —
  // so a new draw can FIRE with baseConfirmed still true. The regression: the request
  // left the lock standing, and for the whole ~10 s draw the page said "🔒 locked in"
  // under "drawing…", with step 2 open and designable against the OUTGOING animal.
  it("reopens step 1 the moment a new draw fires, not when it lands", () => {
    let s = atStepTwo();
    expect(frontier(s, AXES)).toBe(2);
    s = designFlowReducer(s, { type: "referenceRequested" });
    expect(s.referenceBusy).toBe(true);
    expect(s.baseConfirmed).toBe(false);
    expect(frontier(s, AXES)).toBe(1);     // step 2 unmounts for the whole draw
  });

  it("voids the outgoing animal's preview, design lock, and dismissal with it", () => {
    let s = designed();
    s = designFlowReducer(s, { type: "previewRequested" });
    s = designFlowReducer(s, { type: "previewLanded", seq: s.seq, preview: ref("p1", "tabby") });
    s = designFlowReducer(s, { type: "designAccepted" });
    expect(frontier(s, AXES)).toBe(3);     // fully settled…
    s = designFlowReducer(s, { type: "referenceRequested" });
    expect(s.preview).toBeNull();          // …and a new draw voids all of it:
    expect(s.designConfirmed).toBe(false); // the preview was (base × design), and
    expect(frontier(s, AXES)).toBe(1);     // the base is in play again.
  });
});

describe("a seq bump must not strand a busy flag", () => {
  // Bumping seq voids whatever is in flight — its result is dropped as stale. A busy
  // flag that only that result could clear then stays true forever: a "Drawing…"
  // button disabled for the rest of the session. The swatches stay live during a
  // redraw, so this was one ordinary click away.
  it("a design change mid-preview clears previewBusy, and the stale result still drops", () => {
    let s = designed();
    s = designFlowReducer(s, { type: "previewRequested" });
    const inFlightSeq = s.seq;
    expect(s.previewBusy).toBe(true);
    s = designFlowReducer(s, { type: "colorPicked", color: "teal" });
    expect(s.previewBusy).toBe(false);
    const landed = designFlowReducer(s, {
      type: "previewLanded", seq: inFlightSeq, preview: ref("p1", "tabby"),
    });
    expect(landed).toBe(s);                // the old design's preview never lands
  });

  it("unlocking the base mid-preview clears previewBusy", () => {
    let s = designed();
    s = designFlowReducer(s, { type: "previewRequested" });
    s = designFlowReducer(s, { type: "baseUnlocked" });
    expect(s.previewBusy).toBe(false);
  });
});

describe("§2.4 — keep the rolls (the candidate strip)", () => {
  /** A real draw: request (bump seq) then a matching fill — the pickRoll path is the
   *  same two dispatches, so this doubles as the pick harness. */
  function draw(s: DesignFlowState, id: string, name = id): DesignFlowState {
    s = designFlowReducer(s, { type: "referenceRequested" });
    return designFlowReducer(s, { type: "referenceFilled", seq: s.seq, reference: ref(id, name) });
  }

  it("accumulates drawn bases newest-first", () => {
    let s = initialState(0.85);
    s = draw(s, "a"); s = draw(s, "b"); s = draw(s, "c");
    expect(s.rolls.map((r) => r.reference_id)).toEqual(["c", "b", "a"]);
    expect(s.reference?.reference_id).toBe("c");
  });

  it("caps the strip at ROLL_LIMIT, dropping the oldest", () => {
    let s = initialState(0.85);
    for (const id of ["a", "b", "c", "d", "e"]) s = draw(s, id);
    expect(s.rolls.map((r) => r.reference_id)).toEqual(["e", "d", "c", "b"]);  // ROLL_LIMIT = 4
    expect(s.rolls).toHaveLength(4);
  });

  it("re-picking a roll neither duplicates nor reorders it (dedup by id)", () => {
    let s = initialState(0.85);
    s = draw(s, "a"); s = draw(s, "b"); s = draw(s, "c");
    s = draw(s, "a");  // pick the oldest again — same id comes back through referenceFilled
    expect(s.rolls.map((r) => r.reference_id)).toEqual(["c", "b", "a"]);  // order unchanged
    expect(s.reference?.reference_id).toBe("a");                          // but it IS the base now
  });

  it("picking a roll is not cheaper than a draw: it unlocks step 2 against the outgoing base", () => {
    let s = atStepTwo();                 // r1 drawn AND baseAccepted (step 2 open)
    expect(s.baseConfirmed).toBe(true);
    s = draw(s, "r2");                    // draw a second base
    s = designFlowReducer(s, { type: "baseAccepted" });
    // Now re-pick r1 from the strip (referenceRequested -> referenceFilled with r1).
    s = designFlowReducer(s, { type: "referenceRequested" });
    s = designFlowReducer(s, { type: "referenceFilled", seq: s.seq, reference: ref("r1", "tabby") });
    expect(s.baseConfirmed).toBe(false);          // step 2 re-locked against the new base
    expect(s.preview).toBeNull();                 // and the preview voided
    expect(s.reference?.reference_id).toBe("r1");
  });
});
