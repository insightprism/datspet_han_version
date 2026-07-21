"use client";

/**
 * <Designer> — the General designer (SPEC_PET_DESIGNER_FLOW). Serves /design/general,
 * which is where the DatsMe launch lands users.
 *
 * The user's model, which this file is only an arrangement of — three steps, each one
 * asking a question, doing some work, and handing back an artifact you can see:
 *
 *     STEP 1  "what does a blue jay look like?"  → an ARCHETYPE. Generic. Not yours.
 *     STEP 2  "what should MINE look like?"      → your pet.
 *     STEP 3  "what can it do?"                  → your pet, alive.
 *
 * Every step has the same shape: work → look → 🔒 lock. The lock is what makes the work
 * above it safe to repeat forever, and what keeps the next step from existing until this
 * one is settled (§3.7, §4.7).
 *
 * `reference_id` is the spine, and that is what DELETES code rather than moving it:
 * `appendBaseFields`, the `base` prop, the `DesignerBase` union, the house `<select>`,
 * `houseEmpty`, the `?base` deep-link effect and the whole unreachable kind:"house"
 * branch are gone. Nothing downstream asks where the picture came from (§6), so there is
 * nothing left for those to configure.
 *
 * State lives in a reducer (designFlow.ts) because the invalidation rules ARE the
 * product. Disclosure lives in <Step> because the artifact/controls split is what makes
 * the page small.
 *
 * This is the ONLY designer. components/PetDesigner.tsx — the old single-form one — and
 * the themed pages and /make that used it are all deleted (§11), and with them the whole
 * legacy /api/generate contract. There is one flow and one contract.
 */
import { useEffect, useRef, useState } from "react";
import {
  fetchCatalog, catalogBaseOptions, referenceImageUrl, catalogBaseImageUrl,
  type CatalogBaseOption,
} from "@/lib/api";
import { usePetJob } from "@/hooks/usePetJob";
import PetJobResult from "@/components/PetJobResult";
import { useDesignFlow } from "./useDesignFlow";
import { showsControls, isReachable, previewSettled } from "./designFlow";
import Step from "./Step";
import ReferenceBox from "./ReferenceBox";
import BaseAnimalDialog from "./BaseAnimalDialog";
import UploadStrength, {
  DEFAULT_UPLOAD_STRENGTH, type PendingSource,
} from "./UploadStrength";
import DesignStep from "./DesignStep";
import PoseStep from "./PoseStep";

export default function Designer() {
  const flow = useDesignFlow();
  const { state, dispatch, axes, entitlement, maxPoses, fillReference, makePreview } = flow;
  const { job, error: jobError, submit, reset, stop, busy, done } = usePetJob();
  const [options, setOptions] = useState<CatalogBaseOption[] | null>(null);
  // The pending pick lives HERE, not in the dialog, because the dialog unmounts when
  // it closes — and §3.1 requires the chooser to reopen with the previous choice
  // retained. Held in the dialog, it would be destroyed on every close, and the box
  // would end up showing one thing while the chooser claimed another.
  const [dialogOpen, setDialogOpen] = useState(false);
  const [pending, setPending] = useState<PendingSource | null>(null);
  // Has the pending source been drawn yet? While false the box shows a PREVIEW of the
  // choice (the curated file, or the raw photo); once drawn it shows the real result.
  // Without this the box would keep showing your raw photo after the redraw had
  // already replaced it — claiming the input as the output.
  const [pendingDrawn, setPendingDrawn] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  function choose(next: PendingSource) {
    setPending(next);
    setPendingDrawn(false);   // a new source is a new question
  }

  // Release the object URL when the pending photo is replaced or cleared — every
  // createObjectURL leaks the blob until it is revoked.
  useEffect(() => {
    const url = pending?.kind === "upload" ? pending.url : null;
    return () => { if (url) URL.revokeObjectURL(url); };
  }, [pending]);

  useEffect(() => {
    let cancelled = false;
    fetchCatalog()
      .then((animals) => { if (!cancelled) setOptions(catalogBaseOptions(animals)); })
      .catch(() => { if (!cancelled) setOptions([]); });
    return () => { cancelled = true; };
  }, []);

  // §3.1 — the box lands PRE-FILLED with a curated base, step 2 open. The chooser is
  // opt-in via "Change". An empty box would make the door choice mandatory for
  // everyone, including the majority who want a normal cat and have no opinion about
  // provenance — costing them an action to learn something they don't care about, and
  // taking the flow to ~8 actions against today's ~7 (§1.1).
  useEffect(() => {
    if (!options || options.length === 0 || state.reference || state.referenceBusy) return;
    const first = options[0];
    const form = new FormData();
    form.append("catalog_animal", first.animal);
    form.append("catalog_breed", first.key);
    // Record the pre-fill as the pending SOURCE too, so the buttons describe the thing
    // that is actually in the box. Filling the box without saying what filled it is how
    // the chooser ends up claiming Cat/Tabby over a corgi.
    setPending({ kind: "catalog", animal: first.animal, breed: first.key, label: first.label });
    setPendingDrawn(true);
    fillReference(form);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [options]);

  // A photo, from the OS dialog or dropped on the box. It becomes the PENDING pick —
  // shown in the box immediately via an object URL, so the user sees what they're
  // about to redraw — and only becomes the base when they press the button.
  function acceptPhoto(file: File | null | undefined) {
    if (!file) return;
    // Drop and paste stay live after the lock (the box never unmounts), so a photo
    // can arrive while step 1 is locked. Unlock first: otherwise the pending photo
    // sits on a "🔒 locked in" box whose Draw button is unmounted — a preview of a
    // decision the page claims is settled, with no way to draw it. Choosing a new
    // source IS unlocking, the same rule referenceRequested applies.
    if (state.baseConfirmed) dispatch({ type: "baseUnlocked" });
    choose({
      kind: "upload", file, url: URL.createObjectURL(file),
      strength: DEFAULT_UPLOAD_STRENGTH,
    });
  }

  // THE one button (§3). One job — make this the base animal — with an honest label
  // per source. A curated pick costs nothing and lands in ~6 ms; the other two cost a
  // ~10 s render, which is why the label says so before you press it.
  /**
   * Draw the base image from a source. Pressable as many times as the user likes —
   * that is the point of step 1. A typed animal re-rolls to a different blue jay each
   * press (new seed); a photo re-redraws, so changing "faithful ↔ sprite" and pressing
   * again is how you find the one you want. A curated base is a file, so this just
   * uses it: ~6 ms, no GPU, identical every time.
   *
   * It takes the source EXPLICITLY rather than reading `pending`, because the dialog
   * chooses and draws in one act — and `pending` would still hold the previous value
   * inside that same tick.
   */
  function drawFrom(source: PendingSource) {
    const form = new FormData();
    if (source.kind === "catalog") {
      form.append("catalog_animal", source.animal);
      form.append("catalog_breed", source.breed);
    } else if (source.kind === "upload") {
      form.append("image", source.file);
      form.append("strength", String(source.strength));
    } else {
      form.append("animal", source.animal.trim());
    }
    fillReference(form).then(() => setPendingDrawn(true));
  }

  /** Choose a source and draw it in one act — "select, and it executes". */
  function chooseAndDraw(next: PendingSource) {
    choose(next);
    drawFrom(next);
  }

  // The draw button only exists where drawing can change something.
  //
  // A curated base is a FILE. Picking it in the gallery already copied it into the box
  // (~6 ms, no GPU), and pressing draw again would re-copy the same bytes to the same
  // picture — a button whose only honest label is "do nothing, slowly". A photo and a
  // typed name are the opposite: each press is a new render, so the loop is real.
  const canRedraw = Boolean(pending) && pending?.kind !== "catalog";
  const redrawLabel = pendingDrawn ? "Draw it again · ~10 s" : "Draw it · ~10 s";

  // Every non-default axis pick, in menu order — "purple · chubby · spotted ·
  // grumpy" reads back exactly what the user chose, whichever axes this animal
  // was offered.
  const axisSummary = axes.flatMap((a) => {
    const pick = state.axisPicks[a.axis];
    const option = pick ? a.options.find((o) => o.key === pick) : undefined;
    return option && !option.is_default ? [option.label.toLowerCase()] : [];
  });
  const designSummary = [
    state.color,
    ...axisSummary,
    ...state.accessories,
    state.extra.trim(),
  ].filter(Boolean).join(" · ");

  /**
   * What the build animates: the previewed pet, or — when the preview kept failing and
   * the user dismissed it (§5.2) — the archetype itself.
   *
   * The fallback is the whole point of the escape hatch: `state.preview` alone hard-
   * blocks a user whose preview will not render, which is the dead end §5.2 forbids.
   * It is deliberately NOT silent — the button carries a warning that this builds the
   * undesigned animal (below). Both are references, so `reference_id` is all the build
   * ever needs either way (§6.1); that is the layer earning its keep.
   */
  const buildBase = state.preview ?? state.reference;

  function createPet() {
    if (!buildBase) return;
    const fd = new FormData();
    // The ONLY base field. Everything the build needs — the still, the description,
    // the display name, the pinned motion profile — was resolved at FILL time and
    // rides the record (§7.3).
    fd.append("reference_id", buildBase.reference_id);
    if (state.name.trim()) fd.append("name", state.name.trim());
    const pkg: Record<string, boolean> = { walk: true, idle: true };
    for (const p of state.selectedPoses) pkg[p] = true;
    fd.append("poses", JSON.stringify(pkg));
    submit(fd);
  }

  return (
    <div>
      {/* STEP 1 — pick your base animal. A WORKSHOP, not a menu: the controls sit on
          the left and the animal they produce sits on the right, so try → look → try
          again is one glance instead of a scroll. It stays open until the user says
          "this one" — filling the box is not the same as choosing. */}
      <Step
        index={1}
        title="Select the Animal to Design"
        summary={state.reference?.display_name}
        tone={state.baseConfirmed ? "confirmed" : "default"}
        expanded={showsControls(state, axes, 1)}
        reachable
        // Once locked, step 1 collapses — so the toggle has to live in the header,
        // the one part that stays on screen. Clicking it unlocks AND reopens, because
        // wanting to change the base and wanting to see the chooser are the same wish.
        onExpand={() => dispatch(
          state.baseConfirmed ? { type: "baseUnlocked" } : { type: "expand", step: 1 },
        )}
        expandLabel={state.baseConfirmed ? "🔒 Locked — click to change" : "Change"}
        artifact={
          <ReferenceBox
            reference={state.reference}
            busy={state.referenceBusy}
            locked={state.baseConfirmed}
            onPhoto={acceptPhoto}
            onOpen={() => setDialogOpen(true)}
            pendingUrl={
              pendingDrawn ? null
              : pending?.kind === "upload" ? pending.url
              : pending?.kind === "catalog" ? catalogBaseImageUrl(pending.animal, pending.breed)
              : null
            }
            pendingLabel={
              pendingDrawn ? null
              : pending?.kind === "upload" ? pending.file.name
              : pending?.kind === "catalog" ? pending.label
              : null
            }
          />
        }
      >
        <div className="mx-auto flex max-w-md flex-col items-center gap-4">
          {/* Only an upload needs a control out here — the likeness-vs-animation trade
              is real, and it has to be visible while you press draw again. */}
          {pending?.kind === "upload" && (
            <UploadStrength
              strength={pending.strength}
              onStrength={(s) => setPending({ ...pending, strength: s })}
            />
          )}

          <div className="flex flex-wrap items-center justify-center gap-3">
            {/* DRAW — press it as often as you like. This is the iterate loop: a typed
                animal re-rolls to a different blue jay, a photo re-redraws at whatever
                strength is set. It is absent for a curated base (nothing to draw) and
                once locked (offering to re-roll what you just settled is an invitation
                to undo it by accident). */}
            {!state.baseConfirmed && canRedraw && (
              <button
                type="button"
                className="btn"
                disabled={state.referenceBusy}
                onClick={() => pending && drawFrom(pending)}
              >
                {state.referenceBusy ? "Drawing…" : redrawLabel}
              </button>
            )}

            {/* LOCK — the gate. Step 2 does not exist until this is pressed, which is
                what makes the loop to its left safe to run forever. Its other half —
                unlocking — lives in the header, because this whole body unmounts the
                moment the lock lands. */}
            <button
              type="button"
              className="btn"
              // Locked out while a draw is in flight AND while a pending pick sits
              // undrawn (a chosen photo before its Draw press): in both states the
              // box is not showing `state.reference`, and this button commits
              // `state.reference` — it must never lock something other than what
              // the user is looking at.
              disabled={!state.reference || state.referenceBusy
                        || Boolean(pending && !pendingDrawn)}
              onClick={() => dispatch({ type: "baseAccepted" })}
            >
              Use this animal →
            </button>
          </div>

          {state.referenceError && (
            <div className="mono text-xs" style={{ color: "#f87171" }}>{state.referenceError}</div>
          )}
        </div>
      </Step>

      {/* The OS file input lives OUTSIDE the dialog: the dialog unmounts the moment
          "Use my own picture" is clicked, and an <input> unmounted mid-dialog drops
          its change event on the floor — the file picker would open and then do
          nothing. */}
      <input
        ref={fileRef}
        type="file"
        accept="image/png,image/jpeg,image/webp,image/gif"
        className="hidden"
        onChange={(e) => acceptPhoto(e.target.files?.[0])}
      />
      <BaseAnimalDialog
        open={dialogOpen}
        options={options ?? []}
        onClose={() => setDialogOpen(false)}
        // Both of these draw on the spot. A curated pick is free and instant, and a
        // typed animal does not exist until it is drawn — so in both cases there is
        // nothing to preview and approve first.
        onPickCurated={(o) => chooseAndDraw({
          kind: "catalog", animal: o.animal, breed: o.key, label: o.label,
        })}
        onPickTyped={(animal) => chooseAndDraw({ kind: "typed", animal })}
        // A photo is the exception: it lands as a PREVIEW, undrawn, because the user
        // has to set faithful↔sprite before the redraw is worth spending 10 s on.
        onPickFile={() => fileRef.current?.click()}
      />

      {/* STEP 2 — design it, see it, lock it. The exact shape of step 1: work, look,
          decide. Rev.1–5 split "design" and "see it" across two steps "because the
          redraw deserves its own beat" — but a preview is not a step, it is the ANSWER
          to this one, the same way the box is the answer to step 1. Splitting them put
          the picture on a different screen from the swatches that produce it. */}
      <Step
        index={2}
        title="Design your pet"
        summary={designSummary}
        tone={state.designConfirmed ? "confirmed" : "default"}
        layout="split"
        expanded={showsControls(state, axes, 2)}
        reachable={isReachable(state, axes, 2)}
        // Same structural reason as step 1 (§3.7): once locked this body unmounts, so
        // the unlock half of the toggle has to live in the header.
        onExpand={() => dispatch(
          state.designConfirmed ? { type: "designUnlocked" } : { type: "expand", step: 2 },
        )}
        expandLabel={state.designConfirmed ? "🔒 Locked — click to change" : "Edit"}
        artifact={
          // The archetype and the design sit SIDE BY SIDE: "a blue jay" next to "my
          // blue jay" is the clearest possible statement of what steps 1 and 2 each did.
          <div className="flex flex-col items-center gap-3">
            {/* YOUR PET — the big one, because it is the answer this step exists to
                give. It gets the box treatment step 1's base gets, so the two steps
                read as the same kind of thing. */}
            <figure className="m-0 flex flex-col items-center gap-2">
              <div
                className="flex items-center justify-center rounded-xl border"
                style={{
                  width: 200, height: 200, background: "#151515",
                  borderStyle: state.designConfirmed ? "solid" : "dashed",
                  borderColor: state.designConfirmed ? "var(--green)" : "var(--line)",
                }}
              >
                {state.preview ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={referenceImageUrl(state.preview.reference_id)}
                    alt="your pet"
                    style={{
                      width: 176, height: 176, objectFit: "contain",
                      opacity: state.previewBusy ? 0.25 : 1, transition: "opacity 0.15s",
                    }}
                  />
                ) : (
                  <span className="mono px-4 text-center text-xs" style={{ color: "var(--faint)" }}>
                    {state.previewBusy ? "drawing…" : "press preview to see your pet"}
                  </span>
                )}
              </div>
              <figcaption className="mono text-xs"
                          style={{ color: state.designConfirmed ? "var(--green)" : "var(--faint)" }}>
                {state.previewBusy ? "drawing…"
                 : state.designConfirmed ? "🔒 locked in"
                 : state.preview ? "your pet" : ""}
              </figcaption>
            </figure>

            {/* …and what it started from, small, underneath. Keeping it on screen is
                what makes "what did I change?" answerable at a glance — but it is
                reference material now, not the subject, so it is sized like it. */}
            {state.reference && (
              <figure className="m-0 flex items-center gap-2">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={referenceImageUrl(state.reference.reference_id)}
                  alt="the animal you started from"
                  style={{ width: 44, height: 44, objectFit: "contain", opacity: 0.6 }}
                />
                <figcaption className="mono text-xs" style={{ color: "var(--faint)" }}>
                  from a {state.reference.display_name.toLowerCase()}
                </figcaption>
              </figure>
            )}
          </div>
        }
      >
        <div className="flex flex-col gap-5">
          <DesignStep
            color={state.color}
            accessories={state.accessories}
            axisPicks={state.axisPicks}
            extra={state.extra}
            strength={state.strength}
            axes={axes}
            minStrength={state.preview?.min_strength ?? null}
            onColor={(color) => dispatch({ type: "colorPicked", color })}
            onAccessory={(accessory) => dispatch({ type: "accessoryToggled", accessory })}
            onAxisPick={(axis, key) => dispatch({ type: "axisPicked", axis, key })}
            onExtra={(text) => dispatch({ type: "extraChanged", text })}
            onStrength={(strength) => dispatch({ type: "strengthPicked", strength })}
          />

          <div className="flex flex-wrap items-center gap-3">
            {/* PREVIEW — the loop. Press it after every change; each press is a fresh
                ~10 s redraw of the locked base toward whatever is set above. */}
            <button
              type="button"
              className="btn"
              disabled={state.previewBusy || !flow.hasDesign}
              onClick={makePreview}
            >
              {state.previewBusy ? "Drawing…"
               : state.preview ? "Preview again · ~10 s" : "Preview my pet · ~10 s"}
            </button>

            {/* LOCK — the gate. Poses and the 3-minute build do not exist until the
                user has SEEN this pet and said yes to it. */}
            <button
              type="button"
              className="btn"
              // The SAME predicate the frontier gates on — imported, not re-derived.
              // A user who dismissed a failing preview (§5.2) has settled step 2 and must
              // be able to leave it, so this cannot gate on `state.preview` alone. But it
              // must not gate on `buildBase` either: that is `preview ?? reference`, and
              // `reference` is always set by the time step 2 renders, so the button went
              // live with nothing previewed — a click that turned step 2 green while the
              // frontier held step 3 shut.
              disabled={!previewSettled(state) || state.previewBusy}
              onClick={() => dispatch({ type: "designAccepted" })}
            >
              Use this as my pet →
            </button>
          </div>

          {/* §5.2 — a preview failure MUST offer a way FORWARD, not just a retry.
              Preview is unconditional now, which took away the bypass the old optional
              preview gave for free: when the pool is down or the 180 s times out,
              "try again" is not a way forward, it is the thing that keeps failing. The
              gate is "seen a preview OR dismissed a failure", so this is the only place
              the dismissal is offered — it is an escape hatch, not a mode. */}
          {state.previewError && (
            <div className="flex flex-col gap-2">
              <div className="mono text-xs" style={{ color: "#f87171" }}>
                {state.previewError}
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <button type="button" className="btn text-xs" disabled={state.previewBusy}
                        onClick={makePreview}>
                  Try again
                </button>
                <button
                  type="button"
                  className="btn-ghost text-xs"
                  onClick={() => dispatch({ type: "previewFailureDismissed" })}
                >
                  Skip the preview →
                </button>
              </div>
              {/* Say the price of the hatch BEFORE they take it. Skipping means the
                  build animates the archetype, so the design is lost — the user asked
                  for purple and would get a plain tabby. Shipping that quietly would be
                  worse than the dead end. */}
              <div className="mono text-xs" style={{ color: "var(--faint)" }}>
                skipping builds{" "}
                <strong>a plain {state.reference?.display_name.toLowerCase() ?? "animal"}</strong>{" "}
                — without your design
              </div>
            </div>
          )}
        </div>
      </Step>

      {/* STEP 3 — poses, priced now that the user has seen what they're buying; then
          the build lands HERE, in this card.

          It used to early-return <PetJobResult> and replace the entire page — steps 1
          and 2 vanished the moment the pet finished, and the thing you had just spent
          three minutes and two decisions on appeared somewhere with no memory of them.
          The result is step 3's ARTIFACT, exactly as the base is step 1's and the
          preview is step 2's. Every step answers in its own card.

          It is passed as `artifact`, and that is load-bearing, not tidiness: <Step>
          renders `artifact` unconditionally and `children` only when
          `expanded && reachable`. Passed as children — as it was — reopening step 2's
          lock dropped the frontier to 2, made step 3 unreachable, and UNMOUNTED the
          finished pet: its download link, its Accept-to-DatsMe button, and mid-build
          its progress bar. The comment above claimed "artifact" while the code said
          "children", and the disagreement was the bug. */}
      <Step
        index={3}
        title="Its moves"
        summary={state.selectedPoses.length
          ? `walk · idle · ${state.selectedPoses.join(" · ")}`
          : "walk · idle"}
        tone={done ? "confirmed" : "default"}
        expanded={showsControls(state, axes, 3)}
        reachable={isReachable(state, axes, 3)}
        onExpand={() => dispatch({ type: "expand", step: 3 })}
        artifact={job ? (
          // `bare`: <Step> already IS the card. PetJobResult carries the progress bar
          // too, so this covers the whole 3-minute build, not just its end.
          <PetJobResult job={job} onReset={reset} onStop={stop} bare resetLabel="Design another" />
        ) : null}
      >
        {!job && (
        <div className="flex flex-col gap-4">
          <PoseStep
            menu={state.poseMenu}
            selected={state.selectedPoses}
            maxPoses={maxPoses}
            entitlement={entitlement}
            notice={state.poseNotice}
            onToggle={(pose) => dispatch({ type: "poseToggled", pose, maxPoses })}
            onDismissNotice={() => dispatch({ type: "poseNoticeDismissed" })}
          />
          <label className="flex flex-col gap-1">
            <span className="mono text-xs" style={{ color: "var(--muted)" }}>name (optional)</span>
            <input
              className="input"
              placeholder={state.preview?.display_name ?? state.reference?.display_name ?? ""}
              value={state.name}
              onChange={(e) => dispatch({ type: "nameChanged", name: e.target.value })}
            />
          </label>
          {/* Buildable from the preview, or — when the preview kept failing and the user
              dismissed it — from the archetype (§5.2). `buildBase` is whichever it is. */}
          <button type="button" className="btn" disabled={busy || !buildBase} onClick={createPet}>
            {busy ? "Building…" : "Bring it to life · ~3 min"}
          </button>
          {/* Never let this ship silently: a dismissed-failure build animates the
              UNDESIGNED animal. The user asked for purple and is about to get a plain
              tabby, and the only honest thing is to say so before they spend 3 minutes. */}
          {!state.preview && state.reference && (
            <div className="mono text-xs" style={{ color: "var(--orange)" }}>
              Heads up — we never managed to draw your design, so this builds{" "}
              <strong>a plain {state.reference.display_name.toLowerCase()}</strong> without
              it. Reopen step 2 to try the preview again.
            </div>
          )}
          {jobError && <div className="mono text-xs" style={{ color: "#f87171" }}>{jobError}</div>}
        </div>
        )}
      </Step>

      {/* No "← back to worlds". It linked to /design, which now redirects straight back
          here — a link to the page you are already on. The worlds (the landing tiles)
          went with the themed pages (§11). The global nav still has Design and Pet
          house on every page, so nothing is stranded. */}
    </div>
  );
}
