"use client";

/**
 * <SourceRail> — step 1's question, on the page (SPEC_STEP1_SOURCE_RAIL §1.1).
 *
 * Step 1 asks one thing — *where should the base animal come from?* — and until this
 * component existed that question lived inside a modal opened by clicking a picture that
 * gave no sign it was a menu. The box lands PRE-FILLED (§3.1), so it looks like an answer,
 * so nobody clicks it to find the question: the product's headline capability — type any
 * animal, get a pet — was invisible (§0).
 *
 * This is NOT `SPEC_PET_DESIGNER_FLOW` §3.1's "second door into the same room" coming
 * back. Rev.1–4's second doors each added a control performing an action another control
 * already performed (a dropzone beside a droppable box; a "Change" button beside a
 * clickable picture). This adds none: it performs the one action nothing on the page
 * performed — naming the sources. The dialog's `choices` and `typed` views are DELETED,
 * not duplicated, so the surfaces asking "which source?" go from two to one (§2).
 *
 * Two doors are buttons; the third is the door standing open. That asymmetry is the whole
 * design (§1.2): a gallery's answer surface is a growing thumbnail grid that cannot live
 * in a 280 px column, and a typed animal's answer surface is ONE TEXT INPUT. Putting a
 * single input behind a button that opens a modal containing a single input is ceremony in
 * front of the exact capability users could not find.
 *
 * The archetype guardrail rides along: "Or type any animal", the `blue jay` placeholder and
 * "drawn from scratch" are permanently co-visible instead of living in an unopened modal —
 * so §3.2's highest-risk rule gets MORE exposure here than it did, not less. The rail's own
 * preamble ("Where should it come from? / This is just the starting picture…") was REMOVED
 * in §1.8: the three doors answer the question the heading asked, and the page header a few
 * lines up already frames step 1 as *"start from what a typical animal looks like"* — which
 * is the same guardrail, stated once, where the whole flow can see it.
 *
 * THEY MUST READ AS BUTTONS (§1.6). The first build shipped them as full-width rows with
 * the hint pushed to the far right, which reads as a table of text: a control that spans
 * the column and has no weight of its own does not invite a click. They are capped narrow,
 * carry a glyph in their own brand colour, and stack label-over-hint so the block is
 * button-shaped rather than line-shaped.
 */
import type { PendingSource } from "./pendingSource";

/**
 * One brand colour per door, so the three read as a SET of distinct choices rather than
 * three rows of prose. Colours come from globals.css and are never re-declared here —
 * `color-mix` derives the soft fills, so the palette has exactly one home.
 */
const TONE = {
  catalog: "var(--green)",   // free, instant, curated — the safe door
  upload: "var(--accent)",   // DatsMe indigo, the primary action colour
  typed: "var(--gold)",      // DatsMe purple — the door that draws from nothing
} as const;

const soft = (tone: string, pct: number) =>
  `color-mix(in srgb, ${tone} ${pct}%, transparent)`;

interface Props {
  /** Which source the box's contents came from — marks the rail (§1.5). */
  current: PendingSource["kind"] | null;
  /** A draw is in flight: the typed row's button is disabled and says so. */
  busy: boolean;
  /**
   * The typed draft. Lives in <Designer>, NOT here — <Step> unmounts its children on
   * collapse (Step.tsx:111), so a draft held here would be destroyed every time step 1
   * locked. That is SPEC_PET_DESIGNER_FLOW §13's recorded miss ("reopened claiming
   * Cat/Tabby over a corgi") exactly, and Designer.tsx already documents the rule for
   * `pending`.
   */
  typedDraft: string;
  onTypedDraft: (text: string) => void;
  /** The draft is exactly what is currently drawn in the box → "Draw it again". */
  typedIsDrawn: boolean;
  onGallery: () => void;
  onUpload: () => void;
  /** Draw the typed animal — the typed door's "select, and it executes" (§3.2). */
  onTypedDraw: (animal: string) => void;

  /**
   * A photo is chosen and waiting to be drawn — the upload door grows its Draw button
   * (§1.11). The faithful↔sprite chooser that used to sit here is gone (§1.12): step 2's
   * mandatory redraw overwrote the choice before it ever reached the animation.
   */
  uploadPending: boolean;
  uploadIsDrawn: boolean;
  onUploadDraw: () => void;
  /**
   * The upload door's OWN noun — "what animal is this a photo of?" (SPEC_UPLOAD_LIKENESS
   * §2.1, decision 3a, reversed on evidence). It is a DIFFERENT question from `typedDraft`:
   * that field is the typed door's whole input ("draw this from nothing"); this one labels
   * a photo the user already has. They share no state, so the two fields can never show the
   * same value in two places, and the upload door no longer borrows a value from across the
   * page — the indirection ("change it on the left") that confused a real uploader is gone.
   */
  uploadNoun: string;
  onUploadNoun: (text: string) => void;

  /**
   * The upload door's "AI enabled" toggle, top-right of the card (default ON). ON → the
   * AI names the photo (an animal OR a person) and the noun field is HIDDEN; OFF → the
   * field shows and the user types the name themselves. It also flips the server's
   * captioner off (ai_caption=false), so OFF genuinely means "don't caption", not just
   * "hide the box" — otherwise an empty field would still be captioned.
   */
  aiEnabled: boolean;
  onAiEnabled: (enabled: boolean) => void;
}

export default function SourceRail({
  current, busy, typedDraft, onTypedDraft, typedIsDrawn,
  onGallery, onUpload, onTypedDraw,
  uploadPending, uploadIsDrawn, onUploadDraw,
  uploadNoun, onUploadNoun,
  aiEnabled, onAiEnabled,
}: Props) {
  const draft = typedDraft.trim();

  function drawTyped() {
    if (draft && !busy) onTypedDraw(draft);
  }

  return (
    // Capped well short of the column: a control as wide as the page reads as a section,
    // not a button. The box it fills is 200 px, and these should feel like its siblings.
    <div className="flex w-full max-w-[26rem] flex-col gap-2.5">
      <Door
        glyph="🐾"
        tone={TONE.catalog}
        label="Use an existing base animal"
        hint="free · instant"
        current={current === "catalog"}
        onClick={onGallery}
      />
      {/* The upload door, in its two shapes. With no photo chosen it is a plain door like
          the gallery's; with one chosen it grows a Draw button, because a photo is the one
          source that lands undrawn (§3.2).

          It used to grow a faithful↔sprite chooser too. That is gone (§1.12): step 2's
          redraw is mandatory and runs at a strength this door never set, forced to 0.9
          whenever the design fights the source — so "faithful" was overwritten before it
          reached the animation. A control whose effect is erased downstream is worse than
          no control: it charges a decision and silently discards it. */}
      {uploadPending ? (
        <div className="relative flex flex-col gap-2 rounded-xl border px-3 py-2.5"
             style={shell(TONE.upload, current === "upload")}>
          {/* "AI enabled" toggle, top-right (SPEC_UPLOAD_LIKENESS §2.5). ON (default):
              the AI names the animal or person, so the noun field is hidden. OFF: the
              field appears and the user types it. A sibling of the header button, not a
              child — a <button> cannot nest inside the header <button>. */}
          <AiToggle enabled={aiEnabled} onChange={onAiEnabled} />
          <button type="button" onClick={onUpload}
                  className="flex items-center gap-3 pr-16 text-left transition hover:opacity-80">
            <Glyph glyph="📷" tone={TONE.upload} />
            <span className="flex min-w-0 flex-col">
              <span className="text-sm font-medium" style={{ color: "var(--heading)" }}>
                Use my own picture
              </span>
              {/* The SAME hint as the door's closed state, deliberately. A first draft
                  swapped it for "click to pick a different one", which read as helpful and
                  quietly deleted the ~10 s price at the exact moment the user is deciding
                  whether to spend it (§3.3: the price is on the door before you commit).
                  A door's description should not morph into an instruction — the header is
                  still a button, and it is the same click that got them here. */}
              <span className="mono text-xs" style={{ color: "var(--faint)" }}>
                ~10 s · redrawn as a sprite
              </span>
            </span>
          </button>
          {/* THE noun, INSIDE the upload door (SPEC_UPLOAD_LIKENESS §2.1, decision 3a).
              It was on the "type any animal" door across the page, and the upload door
              only pointed at it ("change it on the left") — which a real uploader read as
              two unrelated doors and never filled, so their parakeet redrew against "pet"
              and came back a generic mammal. The question this asks — "what is this a photo
              of?" — is genuinely different from the typed door's "what should I draw from
              nothing?", so a field in each is right, not the "same question twice" the old
              design feared.

              With AI enabled (§2.5, the default) the captioner names it and this field is
              HIDDEN; turning AI off reveals it so the human can name it themselves — and
              their word wins (decision 3). The subject may be an animal OR a person. */}
          <div className="flex flex-col gap-1">
            {aiEnabled ? (
              <p className="mono text-xs" style={{ color: "var(--faint)" }}>
                the AI will identify it — an animal or a person — and name it for you
              </p>
            ) : (
              <input
                id="upload-animal"
                className="input"
                aria-label="what is it? (an animal or a person)"
                /* §3.2's archetype rule holds here too: a NOUN and an example, never
                   "describe your pet" — the upload door names the subject, it does not
                   design it. Now that a photo can also be a person, the copy names both. */
                placeholder="what is it? e.g. parakeet, or a person"
                value={uploadNoun}
                onChange={(e) => onUploadNoun(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !busy) {
                    e.preventDefault();
                    onUploadDraw();
                  }
                }}
              />
            )}
            {/* The pipeline's documented precondition — good-photo advice matters whether
                the AI or the user names it, so it shows in both modes. */}
            <span className="mono text-xs" style={{ color: "var(--faint)" }}>
              side-on, whole subject, good light works best
            </span>
          </div>

          <button type="button" className="btn self-start" disabled={busy}
                  onClick={onUploadDraw}>
            {busy ? "Drawing…" : uploadIsDrawn ? "Draw again" : "Draw it"}
          </button>
        </div>
      ) : (
        <Door
          glyph="📷"
          tone={TONE.upload}
          label="Use my own picture"
          hint="~10 s · redrawn as a sprite"
          current={current === "upload"}
          onClick={onUpload}
        />
      )}

      {/* The third door, standing open. Same shell as a <Door> so the three read as one
          set — but no aria-current: the <input> already carries the animal name as its
          value, which states the same thing more directly than an ARIA flag (§1.5). */}
      <div className="flex flex-col gap-2 rounded-xl border px-3 py-2.5"
           style={shell(TONE.typed, current === "typed")}>
        <div className="flex items-center gap-3">
          <Glyph glyph="✏️" tone={TONE.typed} />
          <label htmlFor="typed-animal" className="flex min-w-0 flex-col">
            <span className="text-sm font-medium" style={{ color: "var(--heading)" }}>
              Or type any animal
            </span>
            <span className="mono text-xs" style={{ color: "var(--faint)" }}>
              ~10 s · drawn from scratch
            </span>
          </label>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <input
            id="typed-animal"
            className="input min-w-0 flex-1"
            /* THE highest-risk copy in the flow (§3.2): "any animal", never "describe
               your pet". The moment it invites a description, users type designs into
               step 1 and the archetype rule breaks in practice even though it holds in
               code. No autoFocus — inline it would steal focus at page load and scroll
               the step into view (decision #11). */
            placeholder="blue jay"
            value={typedDraft}
            onChange={(e) => onTypedDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && draft && !busy) {
                e.preventDefault();
                drawTyped();
              }
            }}
          />
          {/* Typed's OWN draw button, beside the field that feeds it. Sharing the bottom
              one would put two live "Draw it again" buttons on screen for a single
              source — the second door §2 forbids (§5.3). */}
          <button type="button" className="btn shrink-0" disabled={!draft || busy}
                  onClick={drawTyped}>
            {busy ? "Drawing…" : typedIsDrawn ? "Draw again" : "Draw it"}
          </button>
        </div>
      </div>
    </div>
  );
}

/**
 * The door surface, and the current-source marker (§1.5).
 *
 * "Current" is a BORDER treatment — the door's own colour on the left edge, and that
 * colour mixed into the rest of the border — never a fill, a check or a pressed state.
 * These slots open doors, they do not select, and a selected look would promise the
 * select-then-confirm ceremony §3.2 removed. The left edge is 3 px in both states so
 * marking a door never shifts the layout.
 */
function shell(tone: string, current: boolean) {
  return {
    background: "#151515",
    borderColor: current ? soft(tone, 45) : "var(--line)",
    borderLeft: `3px solid ${current ? tone : "transparent"}`,
  };
}

/**
 * The upload door's "AI enabled" switch (SPEC_UPLOAD_LIKENESS §2.5), a compact pill in
 * the card's top-right: label "AI" + a switch track. ON (default) = the captioner names
 * the photo and the noun field is hidden; OFF = the field shows so the human names it.
 * A real role="switch" so it reads as a toggle to assistive tech.
 */
function AiToggle({ enabled, onChange }: { enabled: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={enabled}
      aria-label="AI enabled — name the photo automatically"
      onClick={() => onChange(!enabled)}
      title={enabled
        ? "AI enabled — the AI names your photo (an animal or a person). Turn off to type the name yourself."
        : "AI off — type the name yourself. Turn on to let the AI name it."}
      className="mono absolute right-2.5 top-2.5 z-10 flex items-center gap-1.5 text-xs transition hover:opacity-80"
    >
      <span style={{ color: enabled ? TONE.upload : "var(--faint)" }}>AI</span>
      <span className="relative inline-block h-3.5 w-6 rounded-full transition-colors"
            style={{ background: enabled ? TONE.upload : "var(--line)" }}>
        <span className="absolute top-0.5 block h-2.5 w-2.5 rounded-full transition-all"
              style={{ background: "#fff", left: enabled ? "0.75rem" : "0.125rem" }} />
      </span>
    </button>
  );
}

/** The door's glyph, in its own colour — what carries the colour and most of the weight. */
function Glyph({ glyph, tone }: { glyph: string; tone: string }) {
  return (
    <span
      aria-hidden
      className="flex shrink-0 items-center justify-center rounded-lg text-base leading-none"
      style={{
        width: 34, height: 34,
        background: soft(tone, 16),
        border: `1px solid ${soft(tone, 35)}`,
      }}
    >
      {glyph}
    </span>
  );
}

/** Moved from the dialog's `Choice`, rebuilt as a button rather than a table row. */
function Door({ glyph, tone, label, hint, current, onClick }: {
  glyph: string; tone: string; label: string; hint: string;
  current: boolean; onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-current={current ? "true" : undefined}
      className="flex items-center gap-3 rounded-xl border px-3 py-2.5 text-left transition hover:opacity-80"
      style={shell(tone, current)}
    >
      <Glyph glyph={glyph} tone={tone} />
      <span className="flex min-w-0 flex-col">
        <span className="text-sm font-medium" style={{ color: "var(--heading)" }}>{label}</span>
        <span className="mono text-xs" style={{ color: "var(--faint)" }}>{hint}</span>
      </span>
    </button>
  );
}
