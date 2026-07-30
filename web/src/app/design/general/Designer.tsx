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
  type CatalogBaseOption, type PetReference,
} from "@/lib/api";
import { usePetJob } from "@/hooks/usePetJob";
import PetJobResult from "@/components/PetJobResult";
import { useDesignFlow } from "./useDesignFlow";
import { showsControls, isReachable, previewSettled } from "./designFlow";
import Step from "./Step";
import ReferenceBox from "./ReferenceBox";
import SourceRail from "./SourceRail";
import CandidateStrip from "./CandidateStrip";
import BaseGalleryDialog from "./BaseGalleryDialog";
import type { PendingSource } from "./pendingSource";
import { prepareUpload, UploadRejected, ACCEPT_ATTR } from "./prepareUpload";
import DesignStep from "@/components/DesignStep";
import PoseStep from "./PoseStep";

export default function Designer() {
  const flow = useDesignFlow();
  const { state, dispatch, axes, entitlement, maxPoses, fillReference, makePreview, pickRoll } = flow;
  const { job, error: jobError, submit, reset, stop, busy, done,
          unsaved, resumeUnsaved, dismissUnsaved } = usePetJob();
  const [options, setOptions] = useState<CatalogBaseOption[] | null>(null);
  // The pending pick and the typed draft live HERE, not in the surfaces that show them.
  // <Step> unmounts its children on collapse (Step.tsx:111) and <ModalOverlay> unmounts
  // the dialog's body on close, so either one held further down would be destroyed every
  // time step 1 locked or the gallery closed — and §3.1 requires the chooser to reopen
  // with the previous choice retained. That is §13's recorded miss verbatim: the box
  // showing one thing while the chooser claimed another.
  const [dialogOpen, setDialogOpen] = useState(false);
  const [pending, setPending] = useState<PendingSource | null>(null);
  const [typedDraft, setTypedDraft] = useState("");
  // The upload door's OWN noun ("what animal is this a photo of?"), separate from the typed
  // door's draft (SPEC_UPLOAD_LIKENESS §2.1, decision 3a). Kept here for the same reason as
  // `typedDraft`: <Step> unmounts its children on collapse, so a value held in <SourceRail>
  // would be destroyed every time step 1 locked. Two independent fields, so the upload door
  // no longer borrows the typed door's value across the page.
  const [uploadNoun, setUploadNoun] = useState("");
  // The upload door's "AI enabled" toggle (default on). On → the AI names the photo
  // (animal or person) and the noun field is hidden; off → the field shows and the
  // user types it. Held here, not in <SourceRail>, for the same unmount reason as
  // uploadNoun (Step unmounts its children on lock).
  const [aiEnabled, setAiEnabled] = useState(true);
  // Client-side intake failures (§1.10) — a HEIC, a .txt, an unreadable file. Local rather
  // than reducer state because nothing downstream depends on it: it is not a property of
  // the base animal, it is a note about a file we declined to send.
  const [intakeError, setIntakeError] = useState<string | null>(null);
  const [preparing, setPreparing] = useState(false);
  // Has the pending source been drawn yet? While false the box shows a PREVIEW of the
  // choice (the curated file, or the raw photo); once drawn it shows the real result.
  // Without this the box would keep showing your raw photo after the redraw had
  // already replaced it — claiming the input as the output.
  const [pendingDrawn, setPendingDrawn] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  function choose(next: PendingSource) {
    setPending(next);
    setPendingDrawn(false);   // a new source is a new question
    setIntakeError(null);     // ...and it clears the last file's complaint
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

  // A photo, from the OS dialog, dropped on the box, or pasted. ALL THREE land here, which
  // is why one gate covers them (§1.10) — before `prepareUpload` existed, only the OS
  // picker's `accept=` checked anything, drop took literally any file, and both failed as
  // a 400 after the user pressed Draw.
  //
  // It becomes the PENDING pick — shown in the box immediately via an object URL, so the
  // user sees what they're about to redraw — and only becomes the base when they press the
  // button.
  async function acceptPhoto(file: File | null | undefined) {
    if (!file) return;
    setIntakeError(null);
    // Drop and paste stay live after the lock (the box never unmounts), so a photo
    // can arrive while step 1 is locked. Unlock first: otherwise the pending photo
    // sits on a "🔒 locked in" box whose Draw button is unmounted — a preview of a
    // decision the page claims is settled, with no way to draw it. Choosing a new
    // source IS unlocking, the same rule referenceRequested applies.
    if (state.baseConfirmed) dispatch({ type: "baseUnlocked" });
    // Decode + resize is 100-300 ms on a laptop and can exceed a second on a phone with a
    // 48 MP shot. Without a state to show for it, dropping a photo looks like a dropped
    // frame — the box would sit unchanged with no sign anything had happened.
    setPreparing(true);
    try {
      const prepared = await prepareUpload(file);
      // A new photo is a NEW question ("what is THIS photo of?"), so the previous
      // photo's noun must not carry over — otherwise a stale "man" wins over the
      // captioner on the next upload (typed-noun-wins, decision 3) and a parakeet
      // gets drawn as a man. Clearing it lets the captioner re-answer for the new
      // photo, or the user re-type. This funnels every intake path (picker, drop,
      // paste), so it is the one right place to reset it.
      setUploadNoun("");
      choose({ kind: "upload", file: prepared, url: URL.createObjectURL(prepared) });
    } catch (e) {
      // UploadRejected carries copy written for the user; anything else is a surprise and
      // says so rather than pretending to be advice.
      setIntakeError(e instanceof UploadRejected ? e.message
                     : "That image couldn't be prepared. Try a different file.");
    } finally {
      setPreparing(false);
    }
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
      // No `strength`: the client has no opinion since the chooser was removed (§1.12), so
      // the server's own UPLOAD_REDRAW_STRENGTH default (app.py:155) governs. Sending a
      // copy of it from here would be a second owner of one number, free to drift.
      form.append("image", source.file);
      // THE NOUN (SPEC_UPLOAD_LIKENESS §2.1). `animal` alongside an image is a HINT, not a
      // second door — `_resolve_reference_door` (app.py:706) routes ["upload","txt2img"] to
      // "upload" deliberately and documents exactly this. Without it the server falls back to
      // `subject = animal or "pet"` (app.py:822) and the redraw prompt reads "a cute cartoon
      // pet, exactly pet" — `_remix_prompt` repeats the subject to make it WIN over the
      // source's colours, so the one thing it was winning against was the user's dog.
      //
      // It fixes TWO prompts, not one: `description` is saved as the subject, and step 2's
      // redraw takes `species = ... or ref["description"]` (app.py:966). It also recovers the
      // coat/plumage axis, which an upload with no animal silently loses (app.py:841).
      //
      // The noun comes from the upload door's OWN field (`uploadNoun`), not the typed door's
      // draft (decision 3a): the two ask different questions and share no state. The user's
      // own word beats any inference — nobody out-names an owner on their own dog.
      //
      // The "AI enabled" toggle decides who names it. ON → send no noun and ai_caption=true,
      // so the AI identifies the animal/person (the noun field is hidden). OFF → send the
      // user's typed noun and ai_caption=false, so an empty field draws "pet" rather than
      // being captioned anyway (the toggle disables the captioner on the server, not just
      // the field).
      form.append("ai_caption", String(aiEnabled));
      if (!aiEnabled) {
        const noun = uploadNoun.trim();
        if (noun) form.append("animal", noun);
      }
    } else {
      form.append("animal", source.animal.trim());
    }
    fillReference(form).then((ref) => {
      setPendingDrawn(true);
      // The captioner's guess prefills the upload noun (SPEC_UPLOAD_LIKENESS §2.5,
      // the "AI fills THIS field on an empty submit" the door already anticipates,
      // SourceRail.tsx:157). The subject may be an animal or a person. The human's
      // typed word wins, so fill only when the field is still empty (decision 3).
      if (source.kind === "upload" && !uploadNoun.trim() && ref?.suggested_subject) {
        setUploadNoun(ref.suggested_subject);
      }
    });
  }

  /** Choose a source and draw it in one act — "select, and it executes". */
  function chooseAndDraw(next: PendingSource) {
    choose(next);
    drawFrom(next);
  }

  /** Re-select a drawn base from the candidate strip (SPEC_UPLOAD_LIKENESS §2.4). Clearing
   *  `pending` abandons any undrawn source so the box shows the picked roll (not a stale
   *  upload preview); `pickRoll` does the fill + invalidation. */
  function selectRoll(roll: PetReference) {
    setPending(null);
    setPendingDrawn(true);
    pickRoll(roll);
  }

  // NO DRAW BUTTON LIVES HERE ANY MORE (SPEC_STEP1_SOURCE_RAIL §1.11). Each door owns the
  // controls for its own source: typed draws from beside its text field, an upload from
  // beside its strength chips, and a curated base has nothing to draw at all — it is a
  // FILE, already copied into the box in ~6 ms, so the button's only honest label would be
  // "do nothing, slowly".
  //
  // That is why `canRedraw`/`redrawLabel` are gone rather than moved: they existed to
  // decide which of several sources the ONE shared button was currently serving, and there
  // is no shared button left to serve them.

  // The draft is exactly what is already in the box → the rail says "Draw it again".
  // Type over a drawn animal and it reverts to "Draw it", because the draft and the
  // picture have parted company.
  const typedIsDrawn = pending?.kind === "typed" && pendingDrawn
                       && pending.animal === typedDraft.trim();

  // Is the box showing a REAL, finished base animal right now? This is what the commit
  // button used to be *disabled* on; it now decides whether the button exists at all
  // (SPEC_STEP1_SOURCE_RAIL §1.7). A greyed-out button beside a spinner asks the user to
  // work out why it is dead; no button at all, under a box that says "drawing…", says the
  // same thing without the puzzle. It appears the moment the picture does.
  const baseIsDrawn = Boolean(state.reference) && !state.referenceBusy
                      && !(pending && !pendingDrawn);

  // Step 1's controls are mounted — used by BOTH halves of the artifact column: the commit
  // button's existence, and the negative top margin that aligns it with the rail.
  const step1Open = showsControls(state, axes, 1);

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

  // Build-time estimate, shown on the "Bring it to life" button: 3 min baseline for the
  // always-included walk+idle, plus 30 s for each additional pose the user picked. So 2
  // poses = ~3 min, 5 poses = ~4.5 min, 8 poses = ~6 min. (state.selectedPoses is the
  // OPTIONAL set — walk+idle are added on top in createPet, so its length IS the extras.)
  const buildEstMin = (180 + state.selectedPoses.length * 30) / 60;
  const buildEstLabel = Number.isInteger(buildEstMin) ? `${buildEstMin}` : buildEstMin.toFixed(1);

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
      {/* An unanswered build, offered back (SPEC_PET_DESIGNER_FLOW resume).

          Between a build finishing and the user pressing Save there is a window, and
          any navigation used to end it with the pet reachable from nowhere: the house
          shows only saved pets, and the only other route was a job id in the URL that
          the navigation itself discarded. Signing out is how this was found — the
          sign-out chain lands on the landing page — but a closed tab or a stray link
          does exactly the same thing, which is why the route back is to the PET rather
          than a way to carry a job id through one particular hop.

          An OFFER, not an automatic reopen: the user may well have moved on, and
          silently resurrecting an old pet on top of a fresh design is its own surprise.
          Hidden entirely once a build is on screen — `!job` — so it can never compete
          with the thing the user is actually looking at. */}
      {unsaved && !job && (
        <div
          className="card mb-5 flex flex-wrap items-center gap-3 p-3"
          style={{ borderColor: "rgba(52,211,153,0.4)", background: "rgba(52,211,153,0.08)" }}
        >
          <span className="mono text-sm" style={{ color: "var(--green)" }}>
            🐾 You have an unsaved pet — <strong>{unsaved.display_name}</strong>
          </span>
          <button
            onClick={resumeUnsaved}
            className="mono rounded-lg border px-3 py-1.5 text-sm font-bold"
            style={{ background: "linear-gradient(135deg, #10b981, #059669)", color: "var(--heading)", borderColor: "transparent" }}
          >
            Pick it up →
          </button>
          <button
            onClick={dismissUnsaved}
            className="mono text-sm hover:opacity-80"
            style={{ color: "var(--faint)" }}
          >
            Not now
          </button>
        </div>
      )}

      {/* STEP 1 — pick your base animal. A WORKSHOP, not a menu: the controls sit on
          the left and the animal they produce sits on the right, so try → look → try
          again is one glance instead of a scroll. It stays open until the user says
          "this one" — filling the box is not the same as choosing.

          That sentence described an aspiration until SPEC_STEP1_SOURCE_RAIL; the step was
          centred, and the whole source question hid behind a click on the picture. It is
          now literally true: <SourceRail> is the left, the box is the right (§1.1). */}
      <Step
        index={1}
        layout="split"
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
          /* `-mt-3` while step 1 is open cancels the row's own `mt-3` (Step.tsx:94), so the
             picture sits flush with the header baseline instead of a line below it. That is
             what puts "Use this animal →" on the same line as the rail's last button — the
             two columns read as one row of work, not as a caption stack drifting below a
             form. It is scoped to the OPEN state on purpose: collapsed, <Step> wraps the
             artifact in its own `mt-3` beside a live "🔒 Locked" button, and cancelling the
             gap there would crowd them. */
          <div className={`flex flex-col items-center gap-2 ${step1Open ? "-mt-3" : ""}`}>
            <ReferenceBox
              reference={state.reference}
              busy={state.referenceBusy}
              preparing={preparing}
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

            {/* KEEP THE ROLLS (SPEC_UPLOAD_LIKENESS §2.4). Only in the workshop (step 1
                open): once the base is locked, choosing among candidates is over. The strip
                self-hides below two rolls. */}
            {step1Open && (
              <CandidateStrip
                rolls={state.rolls}
                currentId={state.reference?.reference_id ?? null}
                onPick={selectRoll}
              />
            )}

            {/* LOCK — the gate. Step 2 does not exist until this is pressed, which is what
                makes the draw loop in the rail safe to run forever.

                It lives UNDER THE PICTURE, not in the left column: it commits what the box
                is showing, so it belongs to the box (§1.7). And it is RENDERED, not
                disabled — it appears when a finished animal is on screen and is simply
                absent while one is being drawn.

                It sits in the `artifact` slot, which <Step> renders in EVERY state — so it
                must gate on `showsControls` itself. Without that it would survive the
                collapse and offer to re-lock a step that is already locked, which is the
                header toggle's job (§3.7). Its other half — unlocking — is up there
                because this whole subtree unmounts the moment the lock lands. */}
            {step1Open && baseIsDrawn && (
              <button
                type="button"
                className="btn-step"
                onClick={() => dispatch({ type: "baseAccepted" })}
              >
                Use this animal →
              </button>
            )}
          </div>
        }
      >
        <div className="flex flex-col gap-5">
          {/* THE question, on the page (SPEC_STEP1_SOURCE_RAIL §1.1). Two doors are
              buttons; the third — type any animal — is the door standing open, because
              its whole answer surface is one text input and hiding that behind a modal
              hid the product. */}
          <SourceRail
            current={pending?.kind ?? null}
            busy={state.referenceBusy}
            typedDraft={typedDraft}
            onTypedDraft={setTypedDraft}
            typedIsDrawn={typedIsDrawn}
            onGallery={() => setDialogOpen(true)}
            onUpload={() => fileRef.current?.click()}
            onTypedDraw={(animal) => chooseAndDraw({ kind: "typed", animal })}
            uploadPending={pending?.kind === "upload"}
            uploadIsDrawn={pending?.kind === "upload" && pendingDrawn}
            onUploadDraw={() => { if (pending?.kind === "upload") drawFrom(pending); }}
            uploadNoun={uploadNoun}
            onUploadNoun={setUploadNoun}
            aiEnabled={aiEnabled}
            onAiEnabled={setAiEnabled}
          />

          {/* Intake wins when both are set: the newer complaint is about the file the user
              just handed over, and the stale render error is about one they have moved on
              from. */}
          {(intakeError || state.referenceError) && (
            <div className="mono max-w-[26rem] text-xs" style={{ color: "#f87171" }}>
              {intakeError ?? state.referenceError}
            </div>
          )}
        </div>
      </Step>

      {/* The OS file input is the ONE live file input on the page, and it lives out here
          rather than in <SourceRail> because <Step> unmounts its children when step 1
          locks — an <input> unmounted between the click and the change event drops that
          event on the floor, so the picker would open and then do nothing. */}
      <input
        ref={fileRef}
        type="file"
        // From prepareUpload, not spelled out here: the picker's filter and the gate that
        // enforces it must not be able to drift (§1.10).
        accept={ACCEPT_ATTR}
        className="hidden"
        onChange={(e) => {
          acceptPhoto(e.target.files?.[0]);
          // Clear it, or picking the SAME file twice fires no change event — which now
          // matters: reject a photo, fix nothing, pick it again, and the page would sit
          // silent as though the click had missed.
          e.target.value = "";
        }}
      />
      <BaseGalleryDialog
        open={dialogOpen}
        options={options ?? []}
        onClose={() => setDialogOpen(false)}
        // A curated pick is free and instant, so it draws on the spot — there is nothing
        // to preview and approve first (§3.2).
        onPickCurated={(o) => chooseAndDraw({
          kind: "catalog", animal: o.animal, breed: o.key, label: o.label,
        })}
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
              className="btn-step"
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
            // The same resolved key useDesignFlow already reads to fetch the pose menu —
            // preview wins over reference, since a preview re-resolves after a redraw.
            motionProfile={state.preview?.motion_profile ?? state.reference?.motion_profile ?? null}
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
          <button type="button" className="btn-step self-start" disabled={busy || !buildBase}
                  onClick={createPet}>
            {busy ? "Building…" : `Bring it to life · ~${buildEstLabel} min`}
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
