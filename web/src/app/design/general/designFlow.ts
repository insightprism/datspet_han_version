/**
 * designFlow — the pure state machine behind the designer (SPEC_PET_DESIGNER_FLOW §7.6).
 *
 * No React, no fetch, no DOM: types, a reducer, and selectors. That is deliberate —
 * the invalidation rules ARE the product, and today they live implicitly across 12
 * useState + 5 useEffects in PetDesigner.tsx, order-dependent and firing as separate
 * renders. Here each transition is one atomic case you can read and test.
 *
 * Two ideas do the work:
 *
 *  1. THE FRONTIER IS A GATE, NOT A CURSOR (§7.6). `frontier(state)` derives the
 *     furthest step the state permits. `expandedStep(state)` derives which panel is
 *     open — a UI override, clamped to the frontier so it can never desync. Rev.2 of
 *     the spec conflated them and deadlocked: once a preview existed the frontier was
 *     4 forever, so the design controls (which mounted only at frontier === 2, i.e.
 *     "design untouched") could never reopen. The user could not change their mind
 *     after seeing the preview.
 *
 *  2. DESIGN SURVIVES A REFERENCE CHANGE. Colour/shape/accessories/text were never
 *     properties of the reference (§0.1: step 1 takes ONE input, which animal), so
 *     changing the animal cannot invalidate them. "I want it chubby" outlives
 *     corgi → labrador. Only the preview — a function of (reference × design) — clears.
 */
import type { BodyShape, PetReference } from "@/lib/api";

/**
 * Three steps, matching the user's model in §0 exactly: an archetype, a design, an
 * animation. Rev.1–5 of the spec split "design it" and "see it" into two screens
 * "because the redraw takes ~10 s and deserves its own beat" — but a preview is not a
 * step, it is the ANSWER to step 2, the same way the box is the answer to step 1. Both
 * steps now have the same shape: work → look → lock.
 */
export type StepId = 1 | 2 | 3;

export interface DesignFlowState {
  /** Step 1's artifact: the archetype. null only before the first fill lands. */
  reference: PetReference | null;
  referenceBusy: boolean;
  referenceError: string | null;

  /**
   * Has the user SAID this is the base animal they want?
   *
   * Filling the box is not choosing — step 1 is a workshop, not a menu. A user tries
   * a tabby, types "blue jay", uploads a photo, tries again, and only then commits.
   * So `reference` means "what's in the box right now" and this means "and I'm happy
   * with it"; every new fill resets it to false, because a new picture is a new
   * question. The frontier gates on this, which is what keeps step 2 out of the way
   * while the user is still deciding what animal they're even designing.
   *
   * It costs one click that an auto-advance wouldn't — deliberately. The iterate loop
   * (try → look → try again) is the point of step 1, and a step that advances the
   * moment you touch it can't be iterated in.
   */
  baseConfirmed: boolean;

  /** Step 2: the design intent. Every "what should it look like" input lives here. */
  color: string;
  accessories: string[];
  bodyShape: string;
  extra: string;
  strength: number;

  /** Step 2's ANSWER: the design made visible — itself a reference (§6.1). */
  preview: PetReference | null;
  previewBusy: boolean;
  previewError: string | null;

  /**
   * Has the user said this is the pet they want? The exact mirror of baseConfirmed
   * (§3.7), one step down: seeing a preview is not choosing it. Any change to the
   * design resets it, because a new design is a new question — the same rule that
   * makes a new fill reset the base.
   */
  designConfirmed: boolean;

  /**
   * The user gave up on the preview and chose to go on without it (§5.2).
   *
   * Preview is UNCONDITIONAL, which took away the bypass the old optional preview
   * gave for free. Without this, a persistently failing preview — the pool down, the
   * 180 s timeout — hard-blocks the flow at step 2 with no way forward: the exact
   * dead end §5.2 exists to prevent. Retry alone does not help when retry is what
   * keeps failing.
   *
   * It only appears after a failure (see previewFailed) and is cleared the moment a
   * preview lands or the design changes — it is an escape hatch, not a mode. Building
   * on it animates the ARCHETYPE, so the user gets an UNDESIGNED pet; the UI has to
   * say that plainly rather than quietly ship something they did not ask for.
   */
  previewFailureDismissed: boolean;

  /** Step 4. */
  selectedPoses: string[];
  poseMenu: string[];
  poseNotice: string | null;

  name: string;

  /**
   * Which panel the user asked to open. null = follow the frontier. Clamped in
   * expandedStep(), so it is disclosure state, never reachability state.
   */
  expandedOverride: StepId | null;

  /**
   * Monotonic stamp for async results (§7.6). Every in-flight request records the
   * seq it fired from; a result whose seq is stale is DROPPED. Without this, changing
   * the reference during a 10 s redraw lets the old reference's preview land on the
   * new one — and the user builds a 3-minute pet from a still they never saw, under a
   * button that says "what you saw is what you get".
   */
  seq: number;
}

export const MAX_ACCESSORIES = 3;

export function initialState(strength: number): DesignFlowState {
  return {
    reference: null, referenceBusy: false, referenceError: null, baseConfirmed: false,
    color: "", accessories: [], bodyShape: "", extra: "", strength,
    preview: null, previewBusy: false, previewError: null, designConfirmed: false,
    previewFailureDismissed: false,
    selectedPoses: [], poseMenu: [], poseNotice: null,
    name: "", expandedOverride: null, seq: 0,
  };
}

export type DesignFlowAction =
  | { type: "referenceRequested" }
  | { type: "referenceFailed"; seq: number; message: string }
  | { type: "referenceFilled"; seq: number; reference: PetReference }
  | { type: "baseAccepted" }
  | { type: "baseUnlocked" }
  | { type: "designAccepted" }
  | { type: "designUnlocked" }
  | { type: "colorPicked"; color: string }
  | { type: "accessoryToggled"; accessory: string }
  | { type: "bodyShapePicked"; key: string }
  | { type: "extraChanged"; text: string }
  | { type: "strengthPicked"; strength: number }
  | { type: "nameChanged"; name: string }
  | { type: "previewRequested" }
  | { type: "previewFailed"; seq: number; message: string }
  | { type: "previewLanded"; seq: number; preview: PetReference }
  | { type: "previewFailureDismissed" }
  | { type: "poseMenuLoaded"; menu: string[]; maxPoses: number }
  | { type: "poseToggled"; pose: string; maxPoses: number }
  | { type: "poseNoticeDismissed" }
  | { type: "expand"; step: StepId };

/** A design exists when the user has asked for ANY change (§4.1). */
export function hasDesign(s: DesignFlowState, shapes: BodyShape[]): boolean {
  const shapeIsDefault =
    !s.bodyShape || (shapes.find((x) => x.key === s.bodyShape)?.is_default ?? true);
  return Boolean(s.color || s.accessories.length || !shapeIsDefault || s.extra.trim());
}

/**
 * The GATE: the furthest step this state permits. Derived, never stored — a stored
 * pointer plus state is two sources of truth for "where am I", which is exactly how
 * wizards desync.
 */
export function frontier(s: DesignFlowState, shapes: BodyShape[]): StepId {
  // Both gates read the same: a thing exists AND the user said it is the one they want.
  // Gating on the LOCK rather than on mere existence is what makes each step a place you
  // can WORK — try, look, try again — instead of a menu that fires you onward the
  // instant you touch it.
  if (!s.reference || !s.baseConfirmed) return 1;
  // §5.2: the gate is "seen a preview OR explicitly dismissed a failure" — never
  // "a preview exists". `!s.preview` alone is what dead-ends a user whose preview
  // keeps failing, and the spec names that as the thing not to do.
  const previewSettled = Boolean(s.preview) || s.previewFailureDismissed;
  if (!hasDesign(s, shapes) || !previewSettled || !s.designConfirmed) return 2;
  return 3;
}

/**
 * WHICH PANEL IS OPEN. Defaults to the frontier; an explicit Edit ▸ / Change ▸ opens
 * an earlier one. The min() clamp is what keeps this from becoming a cursor: it can
 * never point past what the state allows, so it cannot desync.
 */
export function expandedStep(s: DesignFlowState, shapes: BodyShape[]): StepId {
  const f = frontier(s, shapes);
  return (s.expandedOverride ? Math.min(s.expandedOverride, f) : f) as StepId;
}

/**
 * The disclosure rule (§7.6): every step always renders its ARTIFACT; a step renders
 * its CONTROLS only when expanded. Only the picture ever needed to stay co-visible —
 * 17 swatches never did. This is what makes first paint 18 and peak 21.
 */
export function showsControls(s: DesignFlowState, shapes: BodyShape[], step: StepId): boolean {
  return expandedStep(s, shapes) === step;
}

export function isReachable(s: DesignFlowState, shapes: BodyShape[], step: StepId): boolean {
  return step <= frontier(s, shapes);
}

/** Intersect picks with a new menu and re-apply the cap IN THE SAME transition (§7.6). */
function reconcilePoses(
  picks: string[], menu: string[], maxPoses: number,
): { kept: string[]; dropped: string[] } {
  const available = picks.filter((p) => menu.includes(p));
  const dropped = picks.filter((p) => !menu.includes(p));
  // walk+idle are always built and always count against the cap, so the optional
  // slots are what remain. Clipping in a later pass would let a request briefly
  // exceed the cap and show the wrong price.
  const slots = Math.max(0, maxPoses - 2);
  return { kept: available.slice(0, slots), dropped: dropped.concat(available.slice(slots)) };
}

export function designFlowReducer(
  state: DesignFlowState, action: DesignFlowAction,
): DesignFlowState {
  switch (action.type) {
    case "referenceRequested":
      // Bumping seq here is what invalidates every in-flight result (§7.6).
      return { ...state, seq: state.seq + 1, referenceBusy: true, referenceError: null };

    case "referenceFailed":
      if (action.seq !== state.seq) return state;
      return { ...state, referenceBusy: false, referenceError: action.message };

    case "referenceFilled": {
      if (action.seq !== state.seq) return state;   // a stale fill must not land
      return {
        ...state,
        reference: action.reference,
        referenceBusy: false,
        referenceError: null,
        // A new picture is a new question: the user has to look at it before it can
        // be the one they meant. Never carry a confirmation across a fill.
        baseConfirmed: false,
        // A function of (reference × design) — the reference moved, so it's void.
        preview: null,
        previewError: null,
        previewBusy: false,
        // Colour/accessories/shape/text are NOT touched: they were never properties
        // of the reference (§0.1). Rev.2 had to reason about this; the archetype rule
        // gives it for free.
        expandedOverride: null,
      };
    }

    case "baseAccepted":
      // Clearing the override hands disclosure back to the frontier, which has just
      // moved to 2 — so accepting the base opens the design step in the same tick,
      // with no stored "current step" to keep in sync.
      return { ...state, baseConfirmed: true, expandedOverride: null };

    case "designAccepted":
      // The mirror of baseAccepted, one step down. Clearing the override hands
      // disclosure back to the frontier, which has just moved to 3.
      return { ...state, designConfirmed: true, expandedOverride: null };

    case "designUnlocked":
      // Unlike unlocking the base, this keeps the preview: the design has not changed,
      // the user has only reopened the question. Editing any value clears it — that is
      // the design-change cases' job, not this one's.
      return { ...state, designConfirmed: false, expandedOverride: null };

    case "baseUnlocked":
      // The lock is a toggle, so unlocking drops the frontier back to 1 and step 2's
      // controls unmount with it. The DESIGN survives — colour and shape were never
      // properties of the base (§0.1) — but the preview cannot: it is a function of
      // (base × design), and the base is in play again.
      return { ...state, baseConfirmed: false, preview: null, designConfirmed: false,
               expandedOverride: null, seq: state.seq + 1 };

    case "colorPicked":
      return { ...state, seq: state.seq + 1, color: action.color, preview: null, designConfirmed: false, previewFailureDismissed: false };

    case "accessoryToggled": {
      const has = state.accessories.includes(action.accessory);
      const next = has
        ? state.accessories.filter((a) => a !== action.accessory)
        : [...state.accessories, action.accessory].slice(0, MAX_ACCESSORIES);
      return { ...state, seq: state.seq + 1, accessories: next, preview: null, designConfirmed: false, previewFailureDismissed: false };
    }

    case "bodyShapePicked":
      return { ...state, seq: state.seq + 1, bodyShape: action.key, preview: null, designConfirmed: false, previewFailureDismissed: false };

    case "extraChanged":
      return { ...state, seq: state.seq + 1, extra: action.text, preview: null, designConfirmed: false, previewFailureDismissed: false };

    case "strengthPicked":
      return { ...state, seq: state.seq + 1, strength: action.strength, preview: null, designConfirmed: false, previewFailureDismissed: false };

    case "nameChanged":
      // The name is a label, not a design input — it never invalidates the preview.
      return { ...state, name: action.name };

    case "previewRequested":
      return { ...state, seq: state.seq + 1, previewBusy: true, previewError: null };

    case "previewFailed":
      if (action.seq !== state.seq) return state;
      // §5.2: preview is unconditional, so a failure MUST offer a way forward or the
      // flow dead-ends. The error is shown with a retry; it never clears the design.
      return { ...state, previewBusy: false, previewError: action.message };

    case "previewLanded": {
      // THE RACE (§7.6). Today's makePreview is a plain async click handler with no
      // cancellation: change the reference mid-redraw and the old promise resolves
      // and re-sets previewId — from a still drawn off the OLD archetype. Dropping a
      // stale seq is the whole fix.
      if (action.seq !== state.seq) return state;
      // A landed preview retires the escape hatch: the thing it was an escape FROM no
      // longer exists, and leaving it set would let a later failure inherit a
      // dismissal the user never gave for it.
      return { ...state, previewBusy: false, previewError: null, preview: action.preview,
               previewFailureDismissed: false, expandedOverride: null };
    }

    case "poseMenuLoaded": {
      const { kept, dropped } = reconcilePoses(state.selectedPoses, action.menu, action.maxPoses);
      return {
        ...state,
        poseMenu: action.menu,
        selectedPoses: kept,
        // A silent drop changes the price with no explanation — that breaks the
        // disclosure rule (platform §5.2) in spirit even though the number is right.
        poseNotice: dropped.length
          ? `${dropped.join(", ")} ${dropped.length > 1 ? "aren't" : "isn't"} available here — removed`
          : null,
      };
    }

    case "poseToggled": {
      const has = state.selectedPoses.includes(action.pose);
      if (has) {
        return { ...state, selectedPoses: state.selectedPoses.filter((p) => p !== action.pose) };
      }
      const slots = Math.max(0, action.maxPoses - 2);
      if (state.selectedPoses.length >= slots) return state;   // at cap; the UI disables it too
      return { ...state, selectedPoses: [...state.selectedPoses, action.pose] };
    }

    case "previewFailureDismissed":
      // Only reachable from a failure — the UI offers it nowhere else (§5.2). Clearing
      // the error too, because the user has answered it; leaving it would keep shouting
      // about a thing they have decided to live with.
      return { ...state, previewFailureDismissed: true, previewError: null,
               expandedOverride: null };

    case "poseNoticeDismissed":
      return { ...state, poseNotice: null };

    case "expand":
      return { ...state, expandedOverride: action.step };

    default:
      return state;
  }
}
