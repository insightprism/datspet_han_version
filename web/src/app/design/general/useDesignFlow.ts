"use client";

/**
 * useDesignFlow — binds the pure reducer (designFlow.ts) to the API
 * (SPEC_PET_DESIGNER_FLOW §7.6).
 *
 * The one job worth naming: EVERY async result is stamped with the `seq` it fired
 * from, and the reducer drops a stale one. That is the fix for a live bug in today's
 * designer (PetDesigner.tsx:254-274) — `makePreview` is a plain async click handler
 * with no cancellation, so changing the base during the ~10 s redraw lets the old
 * promise resolve and re-set previewId from a still drawn off the OLD base. That
 * stale id then flows into the build, and the user gets a 3-minute pet from an image
 * they never saw, under a button that says "what you saw is what you get".
 *
 * The seq lives in the reducer rather than a ref because invalidation is a state
 * transition, not a side effect: picking a colour, swapping the animal, and firing a
 * preview all bump it, and all of them mean "anything in flight is now void".
 */
import { useCallback, useEffect, useReducer, useState } from "react";
import {
  createReference, previewReference, fetchBodyShapes, fetchMotions, fetchEntitlement,
  type BodyShape, type Entitlement,
} from "@/lib/api";
import {
  designFlowReducer, initialState, frontier, expandedStep, hasDesign,
  type DesignFlowState, type StepId,
} from "./designFlow";

const BASE_MAX_POSES = 2;
const DEFAULT_STRENGTH = 0.85;

export function useDesignFlow() {
  const [state, dispatch] = useReducer(designFlowReducer, initialState(DEFAULT_STRENGTH));
  const [shapes, setShapes] = useState<BodyShape[]>([]);
  const [entitlement, setEntitlement] = useState<Entitlement | null>(null);

  // Until the entitlement resolves, fall back to the base cap so the UI never
  // over-promises poses the server would clip (the server is authoritative, §8).
  const maxPoses = entitlement?.max_poses ?? BASE_MAX_POSES;

  useEffect(() => {
    let cancelled = false;
    fetchBodyShapes()
      .then((r) => { if (!cancelled) setShapes(r.shapes); })
      .catch(() => { /* the control simply doesn't render — see DesignStep */ });
    fetchEntitlement()
      .then((e) => { if (!cancelled) setEntitlement(e); })
      .catch(() => { /* keep the conservative base cap */ });
    return () => { cancelled = true; };
  }, []);

  // The pose menu keys off the MOTION PROFILE, not the reference id (§7.6):
  // cat/tabby → cat/siamese are both `quadruped`, so most within-animal changes are
  // pose-neutral. Refetching on every reference change would churn the menu and the
  // picks for nothing.
  const profile = state.preview?.motion_profile ?? state.reference?.motion_profile ?? null;
  const species = state.reference?.description ?? "";
  useEffect(() => {
    if (!state.reference) return;
    let cancelled = false;
    fetchMotions(species, profile ?? undefined)
      .then((menu) => {
        if (cancelled) return;
        dispatch({
          type: "poseMenuLoaded",
          menu: menu.poses.filter((p) => !p.required).map((p) => p.name),
          maxPoses,
        });
      })
      .catch(() => { /* leave the previous menu; the server still clips */ });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profile, species, maxPoses, Boolean(state.reference)]);

  const fillReference = useCallback(async (form: FormData) => {
    dispatch({ type: "referenceRequested" });
    // Read the seq AFTER the bump: +1 is what this request is stamped with.
    const seq = stateSeqAfterBump(state.seq);
    try {
      const reference = await createReference(form);
      dispatch({ type: "referenceFilled", seq, reference });
    } catch (e) {
      dispatch({ type: "referenceFailed", seq, message: (e as Error).message });
    }
  }, [state.seq]);

  const makePreview = useCallback(async () => {
    if (!state.reference) return;
    dispatch({ type: "previewRequested" });
    const seq = stateSeqAfterBump(state.seq);
    const form = new FormData();
    form.append("reference_id", state.reference.reference_id);
    if (state.color) form.append("color", state.color);
    if (state.accessories.length) form.append("accessories", state.accessories.join(","));
    if (state.bodyShape) form.append("body_shape", state.bodyShape);
    if (state.extra.trim()) form.append("extra", state.extra.trim());
    if (state.name.trim()) form.append("name", state.name.trim());
    form.append("strength", String(state.strength));
    try {
      const preview = await previewReference(form);
      dispatch({ type: "previewLanded", seq, preview });
    } catch (e) {
      dispatch({ type: "previewFailed", seq, message: (e as Error).message });
    }
  }, [state.reference, state.color, state.accessories, state.bodyShape, state.extra,
      state.name, state.strength, state.seq]);

  return {
    state, dispatch, shapes, entitlement, maxPoses,
    fillReference, makePreview,
    frontier: frontier(state, shapes),
    expanded: expandedStep(state, shapes),
    hasDesign: hasDesign(state, shapes),
  };
}

/**
 * The seq a request fires under. `dispatch` is async with respect to this closure —
 * `state.seq` still holds the pre-bump value here — so the stamp is computed, not
 * read back. Keeping it in one named function stops the +1 from being re-derived
 * (and mis-derived) at each call site.
 */
function stateSeqAfterBump(seq: number): number {
  return seq + 1;
}

export type UseDesignFlow = ReturnType<typeof useDesignFlow>;
export type { DesignFlowState, StepId };
