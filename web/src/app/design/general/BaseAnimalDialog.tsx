"use client";

/**
 * <BaseAnimalDialog> — click the base animal, get a choice
 * (SPEC_PET_DESIGNER_FLOW §3.2).
 *
 * The box is the subject and this is the one question asked about it: where should the
 * base animal come from? Three answers, and picking one EXECUTES it immediately —
 * no second confirm inside the dialog:
 *
 *   1. an existing base animal  → the gallery, right here
 *   2. my own picture           → the OS file dialog
 *   3. type the animal          → a text box
 *
 * The dialog picks the SOURCE and closes. It does not commit: the base animal is set
 * by the one button outside, so what the user chose is visible in the box before it
 * becomes real. Choosing and committing are different decisions and they get different
 * clicks.
 *
 * The overlay shell is <ModalOverlay> — the shared primitive that owns scroll-lock,
 * safe-area insets, the height cap and the inner scroller. This file owns none of that
 * and must never hand-roll it.
 */
import { useState } from "react";
import ModalOverlay from "@/components/ModalOverlay";
import { catalogBaseImageUrl, type CatalogBaseOption } from "@/lib/api";

type View = "choices" | "gallery" | "typed";

interface Props {
  open: boolean;
  options: CatalogBaseOption[];
  onClose: () => void;
  onPickCurated: (o: CatalogBaseOption) => void;
  onPickTyped: (animal: string) => void;
  /** Opens the OS file dialog. The <input> lives outside so it survives this unmount. */
  onPickFile: () => void;
}

export default function BaseAnimalDialog({
  open, options, onClose, onPickCurated, onPickTyped, onPickFile,
}: Props) {
  const [view, setView] = useState<View>("choices");
  const [typed, setTyped] = useState("");

  function close() {
    setView("choices");   // always reopen at the question, never mid-answer
    onClose();
  }

  // Group by animal, preserving catalog order (the order a human authored them in).
  const groups = options.reduce<{ key: string; label: string; breeds: CatalogBaseOption[] }[]>(
    (acc, o) => {
      let g = acc.find((x) => x.key === o.animal);
      if (!g) { g = { key: o.animal, label: o.animalLabel ?? o.animal, breeds: [] }; acc.push(g); }
      g.breeds.push(o);
      return acc;
    }, []);

  return (
    <ModalOverlay open={open} onClose={close} labelledBy="base-dialog-title">
      <h2 id="base-dialog-title" className="mb-1 text-lg font-semibold"
          style={{ color: "var(--heading)" }}>
        {view === "choices" ? "Your base animal"
         : view === "gallery" ? "Pick an existing base animal"
         : "Type the animal you want"}
      </h2>
      <p className="mb-5 text-sm leading-relaxed" style={{ color: "var(--muted)" }}>
        {view === "choices"
          ? "Where should it come from? This is just the starting picture — you'll make it yours in the next step."
          : view === "gallery"
          ? "These are hand-picked, and free to use."
          : "Any animal. It gets drawn from scratch, so it takes about 10 seconds."}
      </p>

      {view === "choices" && (
        <div className="flex flex-col gap-2">
          <Choice
            label="Use an existing base animal"
            hint="free · instant"
            onClick={() => setView("gallery")}
          />
          <Choice
            label="Use my own picture"
            hint="~10 s · redrawn as a sprite"
            onClick={() => { onPickFile(); close(); }}
          />
          <Choice
            label="Type the animal I want"
            hint="~10 s · drawn from scratch"
            onClick={() => setView("typed")}
          />
        </div>
      )}

      {view === "gallery" && (
        <div className="flex flex-col gap-4">
          {/* The curated bases are SHOWN, not described. They are already images on
              disk, and making someone read "Cat → Tabby" out of a dropdown to learn
              what a tabby looks like inverts the point of curating them (platform
              §4.3: "the user starts from a picture, not a blank screen"). */}
          {groups.map((g) => (
            <div key={g.key} className="flex flex-col gap-2">
              <div className="mono text-xs" style={{ color: "var(--faint)" }}>{g.label}</div>
              <div className="flex flex-wrap gap-2">
                {g.breeds.map((b) => (
                  <button
                    key={`${b.animal}/${b.key}`}
                    type="button"
                    title={b.label}
                    onClick={() => { onPickCurated(b); close(); }}
                    className="flex flex-col items-center gap-1 rounded-lg border p-2 transition hover:opacity-80"
                    style={{ background: "#151515", borderColor: "var(--line)" }}
                  >
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={catalogBaseImageUrl(b.animal, b.key)} alt={b.label}
                         style={{ width: 72, height: 72, objectFit: "contain" }} />
                    <span className="mono text-xs" style={{ color: "var(--muted)" }}>{b.label}</span>
                  </button>
                ))}
              </div>
            </div>
          ))}
          <Back onClick={() => setView("choices")} />
        </div>
      )}

      {view === "typed" && (
        <div className="flex flex-col gap-3">
          <input
            className="input"
            /* THE highest-risk copy in the flow (§3.2): "any animal", never "describe
               your pet". The moment it invites a description, users type designs into
               step 1 and the archetype rule breaks in practice even though it holds in
               code. */
            placeholder="blue jay"
            autoFocus
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && typed.trim()) {
                e.preventDefault();
                onPickTyped(typed.trim());
                close();
              }
            }}
          />
          <div className="flex gap-2">
            {/* Confirm DRAWS — "after the choice is selected, it executes". There is
                nothing to look at first: a typed animal does not exist until it has
                been drawn, so a preview step here would show an empty box asking the
                user to approve nothing. */}
            <button
              type="button"
              className="btn"
              disabled={!typed.trim()}
              onClick={() => { onPickTyped(typed.trim()); close(); }}
            >
              Confirm
            </button>
            {/* Cancel abandons the decision entirely, rather than stepping back to the
                choices — the user asked to leave, not to choose again. */}
            <button type="button" className="btn-ghost" onClick={close}>
              Cancel
            </button>
          </div>
        </div>
      )}
    </ModalOverlay>
  );
}

function Choice({ label, hint, onClick }: { label: string; hint: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex items-center justify-between gap-4 rounded-lg border px-4 py-3 text-left transition hover:opacity-80"
      style={{ background: "#151515", borderColor: "var(--line)" }}
    >
      <span className="text-sm font-medium" style={{ color: "var(--heading)" }}>{label}</span>
      <span className="mono text-xs" style={{ color: "var(--faint)" }}>{hint}</span>
    </button>
  );
}

function Back({ onClick }: { onClick: () => void }) {
  return (
    <button type="button" className="btn-ghost self-start text-xs" onClick={onClick}>
      ← other options
    </button>
  );
}
